from __future__ import annotations
import re
from app.config import get_settings
from app.services.market_service import MarketService
from app.services.semantic_resolver import SemanticResolver
from app.services.join_planner import JoinPlanner
from app.services.text_utils import normalize, phrase_in_text

class PlanService:
    """Creates a structured semantic plan before SQL generation.

    It resolves semantics deterministically and lets the join graph—not an LLM—decide which joins are legal.
    """
    def __init__(self):
        self.s=get_settings(); self.markets=MarketService(); self.resolver=SemanticResolver(); self.joins=JoinPlanner()

    @staticmethod
    def node(spec:dict)->str|None:
        db=spec.get('database'); table=spec.get('table')
        if not table: return None
        return f'{db}.{table}' if db else table

    @staticmethod
    def _dimension_requests(question:str,bindings:dict,resolution:dict)->list[str]:
        q=normalize(question); requested=[]
        for dim,spec in (bindings.get('dimensions',{}) or {}).items():
            labels=[dim,spec.get('label',dim)]
            if any(phrase_in_text(f'by {x}',q) or phrase_in_text(f'per {x}',q) for x in labels): requested.append(dim)
        # "list dealers" is an entity breakdown even without an explicit "by".
        if resolution.get('intent')=='breakdown':
            for c in resolution.get('concepts',[]):
                if c['id'] in (bindings.get('concepts',{}) or {}) and c['id'] not in requested:
                    requested.append(c['id'])
        return requested

    def build(self,question:str,market:str,inherited:dict|None=None)->dict:
        ctx=self.markets.context(market); resolution=self.resolver.resolve(question,market); inherited=inherited or {}
        if not resolution.get("metrics") and inherited.get("metric") and inherited["metric"] in (ctx.get("metrics",{}) or {}):
            mid=inherited["metric"]; spec=ctx["metrics"][mid] or {}; resolution["metrics"]=[{"id":mid,"kind":"metric","label":spec.get("label",mid.replace("_"," ").title()),"description":spec.get("description",""),"matched":["conversation context"],"confidence":.92,"spec":spec}]
            resolution.setdefault("evidence",[]).append("conversation_metric")
        if not resolution.get("time") and inherited.get("time"):
            resolution["time"]=inherited["time"]; resolution.setdefault("evidence",[]).append("conversation_time")
        prior_values=inherited.get("resolved_values",[]) or []; new_dims={x.get("dimension") for x in resolution.get("resolved_values",[]) or []}
        for pv in prior_values:
            if pv.get("dimension") not in new_dims: resolution.setdefault("resolved_values",[]).append(pv)

        bindings=ctx.get('bindings',{}) or {}; metric=resolution['metrics'][0] if resolution.get('metrics') else None
        tables=[]; source=None
        if metric:
            allowed={'verified','approved','governed','certified'}
            if self.s.allow_inferred_analytics: allowed |= {'inferred','draft','reviewed'}
            for src in metric.get('spec',{}).get('preferred_sources',[]) or []:
                if str(src.get('status','')).lower() in allowed:
                    source=src; n=self.node(src)
                    if n: tables.append(n)
                    break
        # If no metric source exists, root on the best resolved business concept.
        if not tables:
            for concept in resolution.get('concepts',[]):
                spec=(bindings.get('concepts',{}) or {}).get(concept['id'])
                if spec:
                    n=self.node(spec); source=spec; tables.append(n); break
        # Finally use ontology retrieval as a fallback, but keep the selection inspectable.
        if not tables and resolution.get('table_candidates') and not resolution.get('ambiguities'):
            c=resolution['table_candidates'][0]; tables.append(f"{c['database']}.{c['table']}")

        dimensions=self._dimension_requests(question,bindings,resolution)
        group_dimensions=list(dimensions)
        if not group_dimensions and inherited.get("group_dimensions"):
            group_dimensions=list(inherited.get("group_dimensions") or [])
            for dim in group_dimensions:
                if dim not in dimensions: dimensions.append(dim)
        # A resolved value implies the corresponding dimension is needed as a filter.
        for v in resolution.get('resolved_values',[]):
            if v.get('dimension') not in dimensions: dimensions.append(v.get('dimension'))
        for lit in resolution.get('literals',[]):
            if lit.get('dimension') not in dimensions: dimensions.append(lit.get('dimension'))

        dim_bindings={}
        for dim in dimensions:
            spec=(bindings.get('dimensions',{}) or {}).get(dim)
            if spec:
                dim_bindings[dim]=spec; n=self.node(spec)
                if n and n not in tables: tables.append(n)
            elif dim in (bindings.get('concepts',{}) or {}):
                spec=bindings['concepts'][dim]; dim_bindings[dim]=spec; n=self.node(spec)
                if n and n not in tables: tables.append(n)

        # Limit plan size before any model prompt is created.
        tables=tables[:self.s.max_planner_tables]
        join_plan=self.joins.connect(market,tables)
        # Join paths can introduce bridge tables. Make them explicit in the structured plan so SQL compilation and audit views see the full path.
        expanded=list(tables)
        for step in join_plan.get('joins',[]):
            for node in (step.get('left'),step.get('right')):
                if node and node not in expanded: expanded.append(node)
        tables=expanded
        decision='ASK' if resolution.get('ambiguities') else ('ASK' if tables and not join_plan['connected'] else 'COMMIT')
        metric_status=str((metric or {}).get('spec',{}).get('status','')).lower() if metric else ''
        governance_mode='governed' if metric_status in {'verified','approved','governed','certified'} else ('inferred_preview' if metric and self.s.allow_inferred_analytics else ('inferred_blocked' if metric else 'governed'))
        plan={
            'question':question,
            'decision':decision,
            'intent':resolution.get('intent','aggregate'),
            'market':market,
            'metric':metric,
            'governance_mode':governance_mode,
            'allow_inferred_metrics':bool(self.s.allow_inferred_analytics),
            'dimensions':dimensions,
            'group_dimensions':group_dimensions,
            'dimension_bindings':dim_bindings,
            'filters':[],
            'time':resolution.get('time',{}),
            'tables':tables,
            'join_plan':join_plan,
            'semantic_confidence':resolution.get('confidence',0),
            'ambiguities':list(resolution.get('ambiguities',[])),
            'verified_query_matches':resolution.get('verified_query_matches',[]),
            'resolution':resolution,
        }
        for v in resolution.get('resolved_values',[]):
            plan['filters'].append({'dimension':v['dimension'],'operator':'=','canonical':v['canonical'],'label':v.get('label'),
                                    'representations':v.get('representations',{}),'confidence':v.get('confidence')})
        for lit in resolution.get('literals',[]):
            plan['filters'].append({'dimension':lit['dimension'],'operator':'=','value':lit['value'],'confidence':lit.get('confidence')})
        if tables and not join_plan['connected'] and not resolution.get('ambiguities'):
            plan['ambiguities'].append({'term':'join_path','reason':'The required semantic tables are not connected by a trusted/governed join path.',
                                        'options':join_plan.get('unreachable',[])})
        if not tables:
            plan['decision']='ASK'; plan['ambiguities'].append({'term':'data_source','reason':'No suitable governed table could be resolved.','options':[]})
        elif plan.get('intent')=='aggregate' and not metric:
            plan['decision']='ASK'; plan['ambiguities'].append({'term':'metric','reason':'An aggregate was requested but no matching metric could be resolved. The system will not silently substitute a row count.','options':[x.get('id') for x in (resolution.get('metrics') or [])[:5]]})
        elif metric and governance_mode=='inferred_blocked':
            plan['decision']='ASK'; plan['ambiguities'].append({'term':'metric_governance','reason':'The matching metric is inferred and must be reviewed/certified before production execution.','options':[metric.get('id')]})
        elif (resolution.get('confidence',0) < self.s.planner_min_confidence and not resolution.get('verified_query_matches')
              and not resolution.get('metrics') and not resolution.get('concepts') and not resolution.get('resolved_values')):
            plan['decision']='ASK'; plan['ambiguities'].append({'term':'semantic_confidence','reason':'The question could not be grounded strongly enough in the selected market semantic model.','options':[]})
        return plan
