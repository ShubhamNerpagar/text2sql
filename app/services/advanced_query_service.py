"""Compile certified business IDs into bounded, read-only analytical SQL."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, date
import json
import math
import re
from zoneinfo import ZoneInfo
from app.config import get_settings
from app.services.phase4_service import Phase4Service, digest
from app.services.semantic_registry_service import SemanticRegistryService
from app.services.business_semantics import expression_sql, is_fresh, validate_semantics
from app.services.sql_safety import validate_read_only_sql

COMPARISONS={'eq':'=','ne':'<>','gt':'>','gte':'>=','lt':'<','lte':'<=','in':'IN','between':'BETWEEN','is_null':'IS NULL','not_null':'IS NOT NULL'}
ALIAS=re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,49}$')


def literal(value):
    if value is None:raise ValueError('Null comparisons require is_null/not_null')
    if type(value)==bool:return 'TRUE' if value else 'FALSE'
    if type(value)==int and abs(value)<=10**15:return str(value)
    if type(value)==float and math.isfinite(value) and abs(value)<=10**15:return repr(value)
    if isinstance(value,str) and len(value)<=120 and '\x00' not in value:return "'"+value.replace("'","''")+"'"
    raise ValueError('Unsupported filter value')


class AdvancedQueryService:
    def __init__(self):
        self.governed=Phase4Service();self.p2=self.governed.p2

    def schema(self,w,release_id):
        self.p2.refresh_relationships(w)
        release,valid,blocked=self.governed._eligible(w,release_id)
        if blocked:raise ValueError('Pinned ontology contains stale or uncertified objects; publish a fresh release')
        bindings={}
        for obj in valid:
            aid=obj.get('binding',{}).get('asset_id')
            if aid:bindings.setdefault(aid,[]).append(obj)
        scoped={a['asset_id']:a for a in self.p2.assets(w)};candidates=[];metas={}
        for aid,objs in bindings.items():
            a=scoped[aid];meta=self.p2.metadata(w,aid);metas[aid]=meta
            certified={c for o in objs for c in o['binding']['columns']}
            candidates.append({'asset_id':aid,'table':a['table'],'database':a['database'],'source_id':a['source_id'],
                'columns':[{'name':c['name'],'type':str(c.get('type','')),'description':c.get('comment',''),
                    'certified_by':[{'object_id':o['object_id'],'kind':o['kind'],'label':o['label']} for o in objs if c['name'] in o['binding']['columns']]}
                    for c in meta['columns'] if c['name'] in certified]})
        approved=[]
        for edge in self.p2.relationships(w):
            if edge['from_asset'] not in bindings or edge['to_asset'] not in bindings:continue
            ev=edge.get('evidence') or {}
            if edge.get('status')!='approved' or not edge.get('trusted_for_queries') or ev.get('passed') is not True:continue
            if ev.get('target_duplicate_rows')!=0 or not is_fresh(ev):continue
            sm,tm=metas[edge['from_asset']],metas[edge['to_asset']]
            if ev.get('source_fingerprint')!=sm['fingerprint'] or ev.get('target_fingerprint')!=tm['fingerprint']:continue
            sc,tc=self.p2.relationship_columns(edge)
            from app.services.phase2_service import digest as evidence_digest
            if ev.get('definition_digest')!=evidence_digest([edge['from_asset'],sc,edge['to_asset'],tc,edge.get('role','')]):continue
            if not set(sc)<={c for o in bindings[edge['from_asset']] for c in o['binding']['columns']}:continue
            if not set(tc)<={c for o in bindings[edge['to_asset']] for c in o['binding']['columns']}:continue
            approved.append({**{k:edge[k] for k in ('relationship_id','from_asset','to_asset')},
                'from_columns':sc,'to_columns':tc,'role':edge.get('role',''),'evidence_digest':digest(ev)})
        return SemanticRegistryService.catalog(valid,sorted(candidates,key=lambda a:a['table']),approved,release)

    def _llm(self,question,schema,previous_plan=None):
        from app.services.llm_planner_service import LLMPlannerService
        return LLMPlannerService().propose(question,schema,previous_plan)

    def compile(self,w,release_id,plan):
        if not isinstance(plan,dict):raise ValueError('A structured plan is required')
        allowed={'base_asset_id','join_relationship_ids','join_sources','dimensions','metrics','concept_ids','filters','having','order_by','limit'}
        if set(plan)-allowed:raise ValueError('Unsupported plan fields; raw SQL and aggregation overrides are forbidden')
        schema=self.schema(w,release_id);amap={a['asset_id']:a for a in schema['assets']};rmap={r['relationship_id']:r for r in schema['relationships']}
        base=plan.get('base_asset_id')
        if base not in amap:raise ValueError('Base dataset is not certified in this release')
        def listfield(key,maximum):
            value=plan.get(key,[])
            if not isinstance(value,list) or len(value)>maximum:raise ValueError('Invalid '+key)
            return value
        links=listfield('join_relationship_ids',4)
        if len(set(links))!=len(links) or any(r not in rmap for r in links):raise ValueError('Join is unapproved, non-unique, stale or uncertified')
        join_sources=plan.get('join_sources',{})
        if not isinstance(join_sources,dict) or set(join_sources)-set(links):raise ValueError('Invalid join sources')
        nodes={base:[('t0',None)]};roles={};joins=[];pending=links[:]
        while pending:
            progress=False
            for rid in pending[:]:
                e=rmap[rid];left=e['from_asset'];right=e['to_asset']
                if left not in nodes:continue
                choices=nodes[left];requested=join_sources.get(rid)
                if requested:
                    choices=[n for n in choices if n[1]==requested]
                    if not choices:continue
                if len(choices)!=1:raise ValueError('Ambiguous relationship role; specify join_sources')
                if amap[left]['source_id']!=amap[right]['source_id'] or amap[left]['database']!=amap[right]['database']:
                    raise ValueError('Cross-source/database joins are prohibited')
                alias=f't{len(joins)+1}';roles[rid]=(right,alias);nodes.setdefault(right,[]).append((alias,rid))
                joins.append((e,choices[0][0],alias));pending.remove(rid);progress=True
            if not progress:raise ValueError('Disconnected or reverse-direction join')
        quote=(lambda v:'`'+self.p2._ident(v)[1:-1]+'`') if amap[base]['source_id']=='databricks' else self.p2._ident
        def ref(aid,column,role=None):
            if aid not in nodes or column not in {c['name'] for c in amap[aid]['columns']}:raise ValueError('Column is not certified on a joined dataset')
            options=nodes[aid]
            if role:
                options=[n for n in options if n[1]==role]
            elif aid==base:options=[('t0',None)]
            if len(options)!=1:raise ValueError('Specify the relationship role for an ambiguous dimension')
            return options[0][0]+'.'+quote(column)
        dims=listfield('dimensions',8);metrics=listfield('metrics',8)
        if not metrics:raise ValueError('Select at least one approved metric ID')
        select=[];groups=[];metric_expr={};used_metrics=[];effective_filters=deepcopy(listfield('filters',20));time_specs=[]
        for i,d in enumerate(dims,1):
            if not isinstance(d,dict) or set(d)-{'asset_id','column','role','time_grain'} or not {'asset_id','column'}<=set(d):raise ValueError('Invalid dimension')
            expr=ref(d['asset_id'],d['column'],d.get('role'));grain=d.get('time_grain')
            if grain:
                if grain not in {'day','month','quarter','year'}:raise ValueError('Unsupported time grouping')
                typ=next(c['type'] for c in amap[d['asset_id']]['columns'] if c['name']==d['column']).lower()
                for m in metrics:
                    o=schema['metrics'].get(m.get('metric_id')) if isinstance(m,dict) else None
                    t=(o or {}).get('semantics',{}).get('time',{})
                    if o and o['binding']['asset_id']==d['asset_id'] and t.get('column')==d['column'] and t.get('timezone','UTC')!='UTC' and ('time' in typ):
                        raise ValueError('Local-time timestamp grouping requires an explicit timezone conversion definition')
                if not any(t in typ for t in ('date','time')) and not any(x in d['column'].lower() for x in ('date','time')):raise ValueError('Time grouping requires a declared date column')
                source=amap[base]['source_id']
                if source=='contoso':
                    if grain=='quarter':expr=f"(strftime('%Y', {expr}) || '-Q' || ((CAST(strftime('%m', {expr}) AS INTEGER)+2)/3))"
                    else:expr=f"strftime('{ {'day':'%Y-%m-%d','month':'%Y-%m','year':'%Y'}[grain] }', {expr})"
                else:expr=f"DATE_TRUNC('{grain}', {expr})"
            groups.append(expr);select.append(expr+f' AS d{i}')
        def aggregate(aggregation,expression,reference):
            term=expression_sql(expression,reference)
            return f'COUNT(DISTINCT {term})' if aggregation=='count_distinct' else aggregation.upper()+f'({term})'
        for m in metrics:
            if not isinstance(m,dict) or set(m)!={'metric_id','alias'}:raise ValueError('Use an approved metric_id and alias; aggregation overrides are prohibited')
            mid=m['metric_id'];alias=m['alias'];obj=schema['metrics'].get(mid)
            if not obj or not isinstance(alias,str) or not ALIAS.fullmatch(alias) or alias in metric_expr or re.fullmatch(r'd\d+',alias):raise ValueError('Invalid metric identity or alias')
            aid=obj['binding']['asset_id'];sem=obj['semantics']
            if aid!=base:raise ValueError('Metric grain differs from the base dataset; a parent measure would be repeated by this join')
            evidence=self.p2.grain_evidence(w,aid,sem['grain'])
            if not evidence['passed']:raise ValueError('Measure grain has null or duplicate keys; query refused')
            validate_semantics('measure',sem,obj['binding'])
            reference=lambda c:ref(aid,c)
            agg=sem['aggregation']
            if agg=='count':expr='COUNT(*)'
            elif agg=='ratio':
                parts=[aggregate(sem[k]['aggregation'],sem[k]['expression'],reference) for k in ('numerator','denominator')]
                expr=f'(1.0 * {parts[0]} / NULLIF({parts[1]}, 0))'
            elif agg=='avg' and sem.get('weight_column'):
                value=expression_sql(sem['expression'],reference);weight=reference(sem['weight_column'])
                expr=f'(1.0 * SUM({value} * {weight}) / NULLIF(SUM(CASE WHEN {value} IS NOT NULL THEN {weight} ELSE 0 END), 0))'
            else:expr=aggregate(agg,sem['expression'],reference)
            metric_expr[alias]=expr;used_metrics.append(mid);select.append(expr+' AS '+quote(alias))
            for f in sem.get('filters',[]):effective_filters.append({'asset_id':aid,**f})
            if sem.get('time'):time_specs.append({'asset_id':aid,**sem['time']})
        # Different required populations cannot be combined into one WHERE clause.
        populations=[schema['metrics'][m['metric_id']]['semantics'].get('filters',[]) for m in metrics]
        if any(p!=populations[0] for p in populations):raise ValueError('Metrics have different required populations; query them separately')
        concepts=listfield('concept_ids',10)
        if len(set(concepts))!=len(concepts):raise ValueError('Duplicate concept IDs')
        for cid in concepts:
            c=schema['concepts'].get(cid)
            if not c or not c['executable']:raise ValueError('Concept has no certified executable predicate')
            for f in c['semantics']['filters']:effective_filters.append({'asset_id':c['binding']['asset_id'],**f})
        filters=[]
        for f in effective_filters:
            if not isinstance(f,dict) or set(f)-{'asset_id','column','role','op','value'} or not {'asset_id','column','op'}<=set(f):raise ValueError('Invalid filter')
            column=ref(f['asset_id'],f['column'],f.get('role'));op=f['op'];value=f.get('value')
            if op=='relative_period':
                declared=next((t for t in time_specs if t['asset_id']==f['asset_id'] and t['column']==f['column']),None)
                if not declared:raise ValueError('Relative time requires the approved metric time role')
                typ=next(c['type'] for c in amap[f['asset_id']]['columns'] if c['name']==f['column']).lower()
                if declared.get('timezone','UTC')!='UTC' and 'time' in typ:
                    raise ValueError('Local-time timestamp periods require an explicit timezone conversion definition')
                start,end=self.period_bounds(value,declared.get('timezone','UTC'))
                filters.extend([column+' >= '+literal(start),column+' < '+literal(end)]);continue
            if op not in COMPARISONS:raise ValueError('Unsupported filter operator')
            if op in {'is_null','not_null'}:filters.append(column+' '+COMPARISONS[op]);continue
            mappings={}
            definitions=[schema['metrics'][mid] for mid in used_metrics]+[schema['concepts'][cid] for cid in concepts]
            for definition in definitions:
                if definition['binding']['asset_id']!=f['asset_id']:continue
                codes=definition['semantics'].get('value_mappings',{}).get(f['column'],{})
                if any(k in mappings and mappings[k]!=v for k,v in codes.items()):raise ValueError('Conflicting business value mappings for the same bound column')
                mappings.update(codes)
            if isinstance(value,str):value=mappings.get(value,value)
            if op=='in':
                if not isinstance(value,list) or not 1<=len(value)<=20:raise ValueError('IN requires 1–20 values')
                rhs='('+', '.join(literal(mappings.get(x,x) if isinstance(x,str) else x) for x in value)+')'
            elif op=='between':
                if not isinstance(value,list) or len(value)!=2:raise ValueError('BETWEEN requires two bounds')
                rhs=literal(value[0])+' AND '+literal(value[1])
            else:rhs=literal(value)
            filters.append(column+' '+COMPARISONS[op]+' '+rhs)
        having=[]
        for h in listfield('having',5):
            if not isinstance(h,dict) or set(h)!={'metric','op','value'} or h['metric'] not in metric_expr or h['op'] not in {'gt','gte','lt','lte','eq'}:raise ValueError('Invalid HAVING')
            having.append(metric_expr[h['metric']]+' '+COMPARISONS[h['op']]+' '+literal(h['value']))
        orders=[];outputs=set(metric_expr)|{f'd{i}' for i in range(1,len(dims)+1)}
        for o in listfield('order_by',5):
            if not isinstance(o,dict) or set(o)!={'alias','direction'} or o['alias'] not in outputs or o['direction'] not in {'asc','desc'}:raise ValueError('Invalid ordering')
            orders.append(quote(o['alias'])+' '+o['direction'].upper())
        limit=plan.get('limit',50)
        if type(limit)!=int or not 1<=limit<=100:raise ValueError('Limit must be 1–100')
        asset=self.p2.asset(w,base);sql='SELECT '+', '.join(select)+' FROM '+self.p2._table_sql(asset)+' AS t0'
        for e,left_alias,right_alias in joins:
            # Role-specific aliases support composite and role-playing dimensions.
            conditions=[left_alias+'.'+quote(sc)+' = '+right_alias+'.'+quote(tc) for sc,tc in zip(e['from_columns'],e['to_columns'])]
            sql+=' LEFT JOIN '+self.p2._table_sql(self.p2.asset(w,e['to_asset']))+' AS '+right_alias+' ON '+' AND '.join(conditions)
        if filters:sql+=' WHERE '+' AND '.join(dict.fromkeys(filters))
        if groups:sql+=' GROUP BY '+', '.join(groups)
        if having:sql+=' HAVING '+' AND '.join(having)
        if orders:sql+=' ORDER BY '+', '.join(orders)
        sql+=' LIMIT '+str(limit)
        ok,message=validate_read_only_sql(sql)
        if not ok:raise ValueError('SQL safety check failed: '+message)
        return {'workspace_id':w,'release_id':release_id,'source_id':asset['source_id'],'database':asset['database'],
            'tables':[{'asset_id':aid,'table':amap[aid]['table'],'alias':alias,'role':role} for aid,entries in nodes.items() for alias,role in entries],
            'metric_ids':used_metrics,'concept_ids':concepts,'effective_filters':effective_filters,
            'join_evidence':links,'sql':sql,'query_type':'certified_business_aggregate',
            'plan_digest':digest([schema['release_digest'],plan,sql]),'result_limit':limit,
            'policy':{'read_only':True,'approved_many_to_one_joins':True,'certified_columns':True,'metric_definitions_enforced':True,'grain_checked':True,'llm_sql_execution':False}}

    @staticmethod
    def period_bounds(period,tz='UTC',today=None):
        today=today or datetime.now(ZoneInfo(tz)).date()
        month=date(today.year,today.month,1)
        previous=lambda d:date(d.year-1,12,1) if d.month==1 else date(d.year,d.month-1,1)
        following=lambda d:date(d.year+1,1,1) if d.month==12 else date(d.year,d.month+1,1)
        if period=='last_month':return previous(month).isoformat(),month.isoformat()
        if period=='this_month':return month.isoformat(),following(month).isoformat()
        if period=='last_year':return date(today.year-1,1,1).isoformat(),date(today.year,1,1).isoformat()
        if period=='last_quarter':
            end=date(today.year,((today.month-1)//3)*3+1,1);start=previous(previous(previous(end)))
            return start.isoformat(),end.isoformat()
        raise ValueError('Unsupported relative period; specify explicit dates')

    def run(self,w,release_id,question,plan=None,use_bedrock=False,execute=False):
        if plan is None or use_bedrock:
            from app.services.unified_ask_service import UnifiedAskService
            return UnifiedAskService().ask(w,release_id,question,execute)
        compiled=self.compile(w,release_id,plan)
        out={'question':question,'release_id':release_id,'proposed_plan':plan,'plan':compiled,'status':'validated_preview','executed':False,'model_used':False,'columns':[],'rows':[]}
        if execute:
            if compiled['source_id']=='contoso' and not get_settings().enable_sample_execution:
                raise ValueError('Sample execution is disabled; connect a live governed data source')
            checked=self.compile(w,release_id,plan)
            if checked['plan_digest']!=compiled['plan_digest']:raise ValueError('Evidence changed before execution')
            result=self.p2.sources.execute(compiled['source_id'],compiled['sql'],compiled['database'])
            out.update({'status':'executed','executed':True,'columns':result['columns'],'rows':result['rows'],'row_count':result['row_count'],
                'usage':{k:result.get(k) for k in ('query_id','execution_ms','bytes_scanned')}})
            self.governed.audit(w,'system','governed_business_aggregate',{'release_id':release_id,'plan_digest':compiled['plan_digest'],'metric_ids':compiled['metric_ids']})
        return out
