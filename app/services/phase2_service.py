"""Phase 2: scoped data understanding. No source records or sample values are persisted.

All physical operations are restricted to the exact Phase 1 allowlist. Evidence is
measured, rather than inferred, and never automatically certified. Storage uses the
existing control plane (local JSON or configured DynamoDB).
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4
from app.repositories.control_repository import ControlRepository
from app.services.scope_service import ScopeService
from app.services.enterprise_catalog_service import EnterpriseCatalogService
from app.services.data_source_service import DataSourceService

TIERS=('metadata','standard','deep')
RULES=('row_count_min','not_null','completeness_min','unique_min','relationship_coverage_min')
KINDS={'profile':'P2_PROFILE','contract':'P2_CONTRACT','relationship':'P2_RELATIONSHIP',
       'rule':'P2_RULE','run':'P2_RUN','transform':'P2_TRANSFORM','audit':'P2_AUDIT'}

def now():return datetime.now(timezone.utc).isoformat()
def digest(o):return hashlib.sha256(json.dumps(o,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def col_role(c):
    name=str(c.get('name','')).lower();typ=str(c.get('type','')).lower()
    if c.get('primary_key'): return 'identifier'
    if name.endswith(('key','_id','id')):return 'foreign_key_candidate'
    if 'date' in name or 'time' in name:return 'temporal'
    if any(x in name for x in ('amount','price','total','quantity','cost','rate','discount')):return 'measure'
    if any(x in typ for x in ('char','text','string')):return 'dimension'
    return 'attribute'

def sensitive(c):
    return bool(re.search(r'email|phone|mobile|address|ssn|passport|dob|birth|credential|secret|password|token',str(c.get('name','')),re.I))

class Phase2Service:
    def __init__(self):
        self.repo=ControlRepository();self.scopes=ScopeService()
        self.catalog=EnterpriseCatalogService();self.sources=DataSourceService()

    def scope(self,workspace):
        row=self.repo.get('WORKSPACE',workspace)
        if not row or not row.get('scope_id'):
            raise ValueError('Phase 2 requires a Phase 1 generated table scope for this workspace.')
        s=self.scopes.get(row['scope_id'])
        if s.get('workspace_id')!=workspace or not s.get('tables'):raise ValueError('Workspace scope is invalid or empty.')
        if s.get('status')!='generated':raise ValueError('Generate the Phase 1 workspace before using Phase 2.')
        return s

    @staticmethod
    def asset_id(scope,obj):
        return 'asset:'+digest({'source':scope['source_id'],**{k:obj.get(k,'') for k in ('catalog','database','schema','table')}})[:24]

    def assets(self,workspace):
        s=self.scope(workspace)
        return [{'asset_id':self.asset_id(s,t),'workspace_id':workspace,'source_id':s['source_id'],**t} for t in s['tables']]

    def asset(self,workspace,asset_id):
        a=next((x for x in self.assets(workspace) if x['asset_id']==asset_id),None)
        if not a:raise KeyError('Asset not in selected workspace scope')
        return a

    def metadata(self,workspace,asset_id):
        a=self.asset(workspace,asset_id)
        d=self.catalog.table_details(a['source_id'],a.get('catalog',''),a['database'],a.get('schema',''),a['table'])
        d['columns']=[{**c,'suggested_role':col_role(c),'sensitive_candidate':sensitive(c)} for c in d.get('columns',[])]
        d['asset_id']=asset_id
        d['fingerprint']=digest({'columns':[(c['name'],str(c.get('type','')),bool(c.get('nullable',True)),bool(c.get('primary_key'))) for c in d['columns']], 'foreign_keys':d.get('foreign_keys',[])})
        return d

    def _owned(self,kind,workspace):return [r for r in self.repo.list(KINDS[kind],1000) if r.get('workspace_id')==workspace]
    def _get(self,kind,workspace,id):
        row=self.repo.get(KINDS[kind],workspace+'::'+id)
        if not row or row.get('workspace_id')!=workspace:raise KeyError(f'{kind} not found in workspace')
        return row
    def _put(self,kind,workspace,id,row):return self.repo.put(KINDS[kind],workspace+'::'+id,row)
    def audit(self,workspace,actor,action,subject,detail=None):
        aid=str(uuid4())
        self._put('audit',workspace,aid,{'audit_id':aid,'workspace_id':workspace,'actor':actor,'action':action,'subject':subject,'detail':detail or {},'at':now()})

    def overview(self,workspace):
        assets=self.assets(workspace)
        return {'workspace_id':workspace,'scope_id':self.scope(workspace)['scope_id'],'source_id':self.scope(workspace)['source_id'],
                'assets':assets,'profile_count':len(self._owned('profile',workspace)),
                'contracts':len(self._owned('contract',workspace)),
                'relationships':len(self._owned('relationship',workspace)),
                'rules':len(self._owned('rule',workspace))}

    @staticmethod
    def _ident(s):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9\-$]*',str(s)):
            raise ValueError('Unsupported SQL identifier for aggregate profiling')
        return '"'+s+'"'

    def _table_sql(self,a):
        q=(lambda v:'`'+self._ident(v)[1:-1]+'`') if a['source_id']=='databricks' else self._ident
        # Cross-catalog/schema resolution is explicit. No interpolated user SQL.
        if a['source_id']=='contoso':return q(a['database'])+'.'+q(a['table'])
        if a['source_id']=='athena':return q(a['database'])+'.'+q(a['table'])
        if a['source_id']=='postgres':return q(a['schema'])+'.'+q(a['table'])
        if a['source_id'] in ('snowflake','databricks'):
            return '.'.join(q(x) for x in [a.get('database') or a.get('catalog'),a['schema'],a['table']])
        raise ValueError('Unsupported data source')

    def _aggregate(self,a,sql):
        d=self.sources.execute(a['source_id'],sql,a['database'] if a['source_id'] in ('athena','contoso') else None)
        rows=d.get('rows') or []
        if not rows:raise ValueError('Aggregate query returned no rows')
        return rows[0],{'query_id':d.get('query_id'),'bytes_scanned':d.get('bytes_scanned'),'execution_ms':d.get('execution_ms')}

    def profile(self,workspace,asset_id,tier='standard',actor='system',max_columns=80):
        if tier not in TIERS:raise ValueError('Unknown profiling tier')
        if max_columns<1 or max_columns>200:raise ValueError('max_columns must be between 1 and 200')
        a=self.asset(workspace,asset_id);meta=self.metadata(workspace,asset_id)
        cols=meta['columns']; selected=cols[:max_columns]
        findings=[];row_count=None;diagnostics=[];queries=0;usage=[]
        if tier!='metadata':
            table=self._table_sql(a)
            quote=(lambda v:'`'+self._ident(v)[1:-1]+'`') if a['source_id']=='databricks' else self._ident
            count,stat=self._aggregate(a,f'SELECT COUNT(*) AS total_rows FROM {table}')
            row_count=int(count['total_rows']);queries+=1;usage.append(stat)
        for c in selected:
            row={k:c.get(k) for k in ('name','type','nullable','primary_key','suggested_role','sensitive_candidate')}
            row['measured']=False
            if tier!='metadata':
                q=quote(c['name'])
                try:
                    # Counts only, no distinct values/samples persisted or returned.
                    sql=f'SELECT COUNT({q}) AS non_null_rows, COUNT(DISTINCT {q}) AS distinct_count FROM {table}'
                    v,stat=self._aggregate(a,sql);queries+=1;usage.append(stat)
                    present=int(v['non_null_rows']); distinct=int(v['distinct_count'])
                    row.update({'measured':True,'non_null_count':present,'null_count':row_count-present,
                       'null_pct':round(100*(row_count-present)/row_count,2) if row_count else 0,
                       'distinct_count':distinct,'uniqueness_ratio':round(distinct/present,5) if present else 0})
                    typ=str(c.get('type','')).lower()
                    numeric=any(x in typ for x in ('int','numeric','decimal','real','double','float','number'))
                    if tier=='deep' and numeric and not sensitive(c):
                        values,stat=self._aggregate(a,f'SELECT AVG({q}) AS mean_value, MIN({q}) AS min_value, MAX({q}) AS max_value FROM {table}')
                        queries+=1;usage.append(stat)
                        row['numeric_summary']={k:round(float(values[k]),5) if values.get(k) is not None else None for k in ('mean_value','min_value','max_value')}
                except Exception as exc:
                    diagnostics.append({'column':c['name'],'error':str(exc)[:240]})
            findings.append(row)
        id='profile-'+uuid4().hex[:16]
        previous=next((x for x in self._owned('profile',workspace) if x.get('asset_id')==asset_id),None)
        drift=bool(previous and previous.get('fingerprint')!=meta['fingerprint'])
        record={'profile_id':id,'workspace_id':workspace,'asset_id':asset_id,'source_id':a['source_id'],
            'tier':tier,'status':'complete' if not diagnostics and len(selected)==len(cols) else 'partial',
            'row_count':row_count,'columns_total':len(cols),'columns_profiled':len(selected),
            'columns':findings,'fingerprint':meta['fingerprint'],'schema_drift_detected':drift,
            'measured':tier!='metadata','queries_executed':queries,'usage':usage[:2],
            'diagnostics':diagnostics,'profiled_at':now(),'actor':actor,
            'data_handling':'aggregates_only_no_sample_rows'}
        out=self._put('profile',workspace,id,record)
        self.audit(workspace,actor,'profile_run',id,{'asset_id':asset_id,'tier':tier,'status':out['status']})
        return out

    def profiles(self,workspace,asset_id=None):
        rows=self._owned('profile',workspace)
        if asset_id:self.asset(workspace,asset_id);rows=[x for x in rows if x['asset_id']==asset_id]
        return rows

    def current_profile(self,workspace,asset_id):
        return next(iter(self.profiles(workspace,asset_id)),None)

    def _contract_proposal(self,workspace,a):
        meta=self.metadata(workspace,a['asset_id'])
        return {'contract_id':a['asset_id'],'workspace_id':workspace,'asset_id':a['asset_id'],
                'version':0,'status':'suggested','schema_fingerprint':meta['fingerprint'],
                'owner':'','description':'','freshness_sla_hours':None,
                'columns':[{'name':c['name'],'physical_type':c.get('type',''),
                            'role':c['suggested_role'],'required':bool(c.get('primary_key')) or not c.get('nullable',True),
                            'sensitive':c['sensitive_candidate'],'description':''} for c in meta['columns']],
                'source':'metadata_inference_not_certified'}

    def contracts(self,workspace,asset_id=None):
        assets=self.assets(workspace)
        if asset_id:assets=[self.asset(workspace,asset_id)]
        found={c['asset_id']:c for c in self._owned('contract',workspace)}
        return [found.get(a['asset_id']) or self._contract_proposal(workspace,a) for a in assets]

    def save_contract(self,workspace,asset_id,body,actor):
        a=self.asset(workspace,asset_id);proposal=self._contract_proposal(workspace,a)
        old=self.repo.get(KINDS['contract'],workspace+'::'+asset_id)
        prior=int((old or {}).get('version',0))
        if int(body.get('expected_version',prior))!=prior:raise ValueError('Contract version conflict; reload before saving')
        allowed_roles={'identifier','foreign_key_candidate','temporal','measure','dimension','attribute','ignore'}
        incoming=body.get('columns')
        if incoming is not None:
            original={x['name']:x for x in proposal['columns']}
            if {x.get('name') for x in incoming}!={*original} or len(incoming)!=len(original):
                raise ValueError('Contract columns must match current physical schema exactly')
            result=[]
            for item in incoming:
                if item.get('role') not in allowed_roles:raise ValueError('Invalid column role')
                actual=original[item['name']]
                result.append({**actual,'role':item['role'],'required':bool(item.get('required')),
                   'sensitive':bool(item.get('sensitive')) or actual['sensitive'],
                   'description':str(item.get('description',''))[:500]})
        else:result=(old or proposal)['columns']
        current=self.metadata(workspace,asset_id)['fingerprint']
        if current!=(old or proposal).get('schema_fingerprint'):raise ValueError('Physical schema drift; recreate/review contract')
        sla=body.get('freshness_sla_hours',(old or proposal).get('freshness_sla_hours'))
        if sla is not None and (not isinstance(sla,(int,float)) or sla<=0 or sla>8760):raise ValueError('SLA hours must be 1–8760')
        record={**(old or proposal),'version':prior+1,'status':'draft','owner':str(body.get('owner',(old or proposal)['owner']))[:120],
            'description':str(body.get('description',(old or proposal)['description']))[:1000],
            'freshness_sla_hours':sla,'columns':result,'schema_fingerprint':current,'updated_by':actor,'updated_at':now(),
            'source':'steward_authored'}
        out=self._put('contract',workspace,asset_id,record)
        self.audit(workspace,actor,'contract_saved',asset_id,{'version':out['version']})
        return out

    def transition_contract(self,workspace,asset_id,status,note,actor):
        self.asset(workspace,asset_id)
        c=self._get('contract',workspace,asset_id)
        allowed={'draft':{'reviewed','rejected'},'reviewed':{'certified','draft','rejected'},'certified':{'draft'},'rejected':{'draft'}}
        if status not in allowed.get(c['status'],set()):raise ValueError('Unsupported contract status transition')
        if status in ('reviewed','certified') and not note.strip():raise ValueError('A review note is required')
        if status=='certified':
            meta=self.metadata(workspace,asset_id)
            if meta['fingerprint']!=c['schema_fingerprint']:raise ValueError('Cannot certify a contract with schema drift')
            if not c.get('owner'):raise ValueError('Assign a contract owner before certification')
            p=self.current_profile(workspace,asset_id)
            if not p or p['status']!='complete' or not p['measured'] or p['fingerprint']!=c['schema_fingerprint']:
                raise ValueError('A complete measured profile of the current schema is required to certify')
        c.update({'status':status,'version':c['version']+1,'review_note':note[:2000],
                  'reviewed_by':actor,'reviewed_at':now()})
        out=self._put('contract',workspace,asset_id,c)
        self.audit(workspace,actor,'contract_'+status,asset_id,{'note':note[:400]})
        return out

    @staticmethod
    def relationship_columns(r):
        return (r.get('from_columns') or [r['from_column']], r.get('to_columns') or [r['to_column']])

    def _relationship(self, workspace, source, target, source_columns, target_columns, role='', origin='manual'):
        a=self.asset(workspace,source);b=self.asset(workspace,target)
        ma=self.metadata(workspace,source);mb=self.metadata(workspace,target)
        if not source_columns or len(source_columns)!=len(target_columns) or len(source_columns)>8:
            raise ValueError('Relationships require 1–8 matching key columns')
        if len(set(source_columns))!=len(source_columns) or len(set(target_columns))!=len(target_columns):
            raise ValueError('Duplicate relationship columns')
        if not set(source_columns)<={c['name'] for c in ma['columns']} or not set(target_columns)<={c['name'] for c in mb['columns']}:
            raise ValueError('Relationship keys must belong to scoped assets')
        if a['source_id']!=b['source_id'] or a['database']!=b['database']:
            raise ValueError('Relationships must use one connector and database')
        role=role or '_'.join(source_columns)
        key=(source,source_columns[0],target,target_columns[0]) if len(source_columns)==1 else (source,source_columns,target,target_columns)
        rid='rel:'+digest(key)[:24]
        return {'relationship_id':rid,'workspace_id':workspace,'from_asset':source,'to_asset':target,
            'from_column':source_columns[0],'to_column':target_columns[0],
            'from_columns':source_columns,'to_columns':target_columns,'role':role,
            'status':'suggested','confidence':origin,'origin':origin,'evidence':None,'trusted_for_queries':False}

    def create_relationship(self, workspace, body, actor):
        r=self._relationship(workspace,body['from_asset'],body['to_asset'],body['from_columns'],body['to_columns'],body.get('role',''))
        existing=self.repo.get(KINDS['relationship'],workspace+'::'+r['relationship_id'])
        if existing:
            if existing.get('role')!=r['role']:
                if existing['status']!='rejected':raise ValueError('Reject the existing relationship before changing its business role')
                self.audit(workspace,actor,'relationship_role_changed',r['relationship_id'],{'previous_role':existing.get('role'),'role':r['role']})
                return self._put('relationship',workspace,r['relationship_id'],{**r,'created_by':actor,'previous_review':existing.get('review_note')})
            return existing
        out=self._put('relationship',workspace,r['relationship_id'],{**r,'created_by':actor})
        self.audit(workspace,actor,'relationship_created',r['relationship_id'])
        return out

    def relationship_candidates(self,workspace,cap=150):
        assets=self.assets(workspace);meta={a['asset_id']:self.metadata(workspace,a['asset_id']) for a in assets}
        candidates={}
        # Declared foreign keys are stronger discovery evidence, never automatic approval.
        for src in assets:
            for fk in meta[src['asset_id']].get('foreign_keys',[]):
                for dst in assets:
                    if dst['table']!=fk.get('referred_table') or dst['source_id']!=src['source_id'] or dst['database']!=src['database']:continue
                    if fk.get('referred_schema') and dst.get('schema')!=fk['referred_schema']:continue
                    sc=fk.get('constrained_columns') or [];tc=fk.get('referred_columns') or []
                    if not tc or any(x is None for x in tc):tc=[c['name'] for c in meta[dst['asset_id']]['columns'] if c.get('primary_key')]
                    r=self._relationship(workspace,src['asset_id'],dst['asset_id'],sc,tc,'_'.join(sc),'declared_foreign_key')
                    candidates[r['relationship_id']]=r
        for src in assets:
            for col in meta[src['asset_id']]['columns']:
                if col['suggested_role'] not in ('foreign_key_candidate','identifier'):continue
                for dst in assets:
                    if src['asset_id']==dst['asset_id']:continue
                    keys=[x for x in meta[dst['asset_id']]['columns'] if x.get('primary_key')]
                    if len(keys)!=1:continue
                    match=keys[0]
                    if match['name'].lower()!=col['name'].lower():continue
                    r=self._relationship(workspace,src['asset_id'],dst['asset_id'],[col['name']],[match['name']],origin='naming_only')
                    candidates.setdefault(r['relationship_id'],r)
        # A bound is explicit, rather than silently excluding unknown relationships.
        rows=list(candidates.values())
        if len(rows)>cap:raise ValueError('Too many relationship candidates; narrow the workspace or increase the discovery cap')
        return rows

    def relationships(self,workspace):
        saved={r['relationship_id']:r for r in self._owned('relationship',workspace)}
        for r in self.relationship_candidates(workspace,2000):saved.setdefault(r['relationship_id'],r)
        return list(saved.values())

    def validate_relationship(self,workspace,relation_id,actor):
        r=next((x for x in self.relationships(workspace) if x['relationship_id']==relation_id),None)
        if not r:raise KeyError('Relationship not found')
        if r['status']=='rejected':raise ValueError('Rejected relationship cannot be validated')
        a=self.asset(workspace,r['from_asset']);b=self.asset(workspace,r['to_asset'])
        ma=self.metadata(workspace,a['asset_id']);mb=self.metadata(workspace,b['asset_id'])
        sc,tc=self.relationship_columns(r)
        if not set(sc)<={c['name'] for c in ma['columns']} or not set(tc)<={c['name'] for c in mb['columns']}:
            raise ValueError('Relationship schema drift')
        if a['source_id']!=b['source_id'] or a['database']!=b['database']:
            raise ValueError('Cross-connector/database joins are prohibited')
        q=(lambda v:'`'+self._ident(v)[1:-1]+'`') if a['source_id']=='databricks' else self._ident
        src=self._table_sql(a);tgt=self._table_sql(b)
        scol=', '.join(q(c)+f' AS k{i}' for i,c in enumerate(sc));tcol=', '.join(q(c)+f' AS k{i}' for i,c in enumerate(tc))
        sgroup=', '.join(q(c) for c in sc);tgroup=', '.join(q(c) for c in tc)
        snon=' AND '.join(q(c)+' IS NOT NULL' for c in sc);tnon=' AND '.join(q(c)+' IS NOT NULL' for c in tc)
        on=' AND '.join(f's.k{i}=t.k{i}' for i in range(len(sc)))
        # Native comparison matches execution semantics. Exact duplicate counts must not be rounded.
        sql=(f'WITH src AS (SELECT {scol}, COUNT(*) AS n FROM {src} WHERE {snon} GROUP BY {sgroup}), '
             f'tgt AS (SELECT {tcol}, COUNT(*) AS n FROM {tgt} WHERE {tnon} GROUP BY {tgroup}) '
             'SELECT (SELECT COUNT(*) FROM src) AS source_distinct, '
             '(SELECT COALESCE(SUM(n),0) FROM src) AS source_non_null_rows, '
             '(SELECT COUNT(*) FROM tgt) AS target_distinct, '
             '(SELECT COALESCE(SUM(n),0) FROM tgt) AS target_non_null_rows, '
             '(SELECT COALESCE(SUM(n-1),0) FROM tgt) AS target_duplicate_rows, '
             f'(SELECT COUNT(*) FROM src s JOIN tgt t ON {on}) AS matched_distinct, '
             f'(SELECT COALESCE(SUM(s.n),0) FROM src s JOIN tgt t ON {on}) AS matched_rows')
        stats,usage=self._aggregate(a,sql)
        values={k:int(v) for k,v in stats.items()};sd=values['source_distinct'];td=values['target_distinct'];tr=values['target_non_null_rows']
        measured={**values,'coverage':values['matched_distinct']/sd if sd else 0.0,
            'row_coverage':values['matched_rows']/values['source_non_null_rows'] if values['source_non_null_rows'] else 0.0,
            'target_uniqueness':td/tr if tr else 0.0,'evaluated_at':now(),'source':a['source_id'],
            'query_id':usage.get('query_id'),'measurement':'full_aggregate_native_keys',
            'source_fingerprint':ma['fingerprint'],'target_fingerprint':mb['fingerprint'],
            'definition_digest':digest([r['from_asset'],sc,r['to_asset'],tc,r.get('role','')])}
        measured['passed']=sd>0 and measured['coverage']>=0.90 and measured['row_coverage']>=0.90 and values['target_duplicate_rows']==0
        old=r.get('evidence') or {}
        preserve=(r['status']=='approved' and r.get('trusted_for_queries') and measured['passed']
            and all(old.get(k)==measured[k] for k in ('source_fingerprint','target_fingerprint','definition_digest')))
        updated={**r,'status':'approved' if preserve else 'evidenced' if measured['passed'] else 'needs_review',
            'evidence':measured,'trusted_for_queries':bool(preserve),'validated_by':actor,'validated_at':now()}
        out=self._put('relationship',workspace,relation_id,updated)
        self.audit(workspace,actor,'relationship_validated',relation_id,{'passed':measured['passed'],'approval_preserved':bool(preserve)})
        return out

    def refresh_relationships(self,workspace,actor='evidence-worker'):
        from app.services.business_semantics import is_fresh
        results=[]
        for r in self._owned('relationship',workspace):
            if r['status']=='approved' and not is_fresh(r.get('evidence') or {}):
                results.append(self.validate_relationship(workspace,r['relationship_id'],actor))
        return results

    def grain_evidence(self,workspace,asset_id,columns):
        from app.services.business_semantics import is_fresh
        a=self.asset(workspace,asset_id);m=self.metadata(workspace,asset_id)
        if not columns or not set(columns)<={c['name'] for c in m['columns']}:raise ValueError('Invalid measure grain')
        ident=digest([workspace,asset_id,columns]);old=self.repo.get('P2_GRAIN',ident)
        if old and old['fingerprint']==m['fingerprint'] and is_fresh(old):return old
        q=(lambda v:'`'+self._ident(v)[1:-1]+'`') if a['source_id']=='databricks' else self._ident
        table=self._table_sql(a);keys=', '.join(q(c) for c in columns);nonnull=' AND '.join(q(c)+' IS NOT NULL' for c in columns)
        sql=(f'WITH grains AS (SELECT {keys}, COUNT(*) AS n FROM {table} GROUP BY {keys}) '
             f'SELECT (SELECT COUNT(*) FROM {table}) AS total_rows, '
             f'(SELECT COUNT(*) FROM {table} WHERE {nonnull}) AS non_null_rows, '
             '(SELECT COALESCE(SUM(n-1),0) FROM grains) AS duplicate_rows')
        stats,_=self._aggregate(a,sql)
        out={**{k:int(v) for k,v in stats.items()},'fingerprint':m['fingerprint'],'columns':columns,'evaluated_at':now()}
        out['passed']=out['duplicate_rows']==0 and out['total_rows']==out['non_null_rows']
        return self.repo.put('P2_GRAIN',ident,out)

    def review_relationship(self,workspace,relation_id,decision,note,actor):
        from app.services.business_semantics import is_fresh
        r=self._get('relationship',workspace,relation_id)
        if decision not in ('approved','rejected') or not note.strip():raise ValueError('Decision and review rationale required')
        if decision=='approved':
            e=r.get('evidence') or {}
            if r['status']!='evidenced' or not e.get('passed') or e.get('target_duplicate_rows')!=0 or not is_fresh(e):
                raise ValueError('Fresh exact unique-target evidence must pass before approval')
            a=self.metadata(workspace,r['from_asset']);b=self.metadata(workspace,r['to_asset'])
            if e['source_fingerprint']!=a['fingerprint'] or e['target_fingerprint']!=b['fingerprint']:raise ValueError('Schema drift invalidates evidence')
            sc,tc=self.relationship_columns(r)
            if e.get('definition_digest')!=digest([r['from_asset'],sc,r['to_asset'],tc,r.get('role','')]):raise ValueError('Relationship meaning changed after measurement')
        out=self._put('relationship',workspace,relation_id,{**r,'status':decision,'trusted_for_queries':decision=='approved',
            'reviewed_by':actor,'reviewed_at':now(),'review_note':note[:2000]})
        self.audit(workspace,actor,'relationship_'+decision,relation_id,{'note':note[:400]})
        return out

    def rules(self,workspace):return self._owned('rule',workspace)
    def create_rule(self,workspace,body,actor):
        typ=body.get('rule_type')
        if typ not in RULES:raise ValueError('Unsupported rule type')
        asset_id=body.get('asset_id')
        a=self.asset(workspace,asset_id);meta=self.metadata(workspace,asset_id)
        column=str(body.get('column') or '')
        if typ in ('not_null','completeness_min','unique_min') and column not in {c['name'] for c in meta['columns']}:
            raise ValueError('Quality rule references unknown column')
        if typ=='relationship_coverage_min':
            relation=next((r for r in self.relationships(workspace) if r['relationship_id']==body.get('relationship_id') and r['from_asset']==asset_id),None)
            if not relation:raise ValueError('Rule requires a valid scoped relationship')
        threshold=float(body.get('threshold',1))
        if threshold<0 or (typ not in ('row_count_min',) and threshold>1) or threshold>1e12:raise ValueError('Invalid threshold')
        if typ=='not_null':threshold=1.0
        rid='rule-'+uuid4().hex[:16]
        rule={'rule_id':rid,'workspace_id':workspace,'asset_id':asset_id,'column':column,'rule_type':typ,
            'threshold':threshold,'relationship_id':body.get('relationship_id') if typ=='relationship_coverage_min' else None,
            'description':str(body.get('description',''))[:500],'status':'active','created_by':actor,'created_at':now()}
        out=self._put('rule',workspace,rid,rule)
        self.audit(workspace,actor,'quality_rule_created',rid,{'type':typ})
        return out

    def set_rule_status(self,workspace,rule_id,status,note,actor):
        rule=self._get('rule',workspace,rule_id)
        if status not in ('active','disabled') or not str(note).strip():
            raise ValueError('Rule status must be active or disabled and include a reason')
        rule.update({'status':status,'status_note':str(note)[:800],'changed_by':actor,'changed_at':now()})
        out=self._put('rule',workspace,rule_id,rule)
        self.audit(workspace,actor,'quality_rule_'+status,rule_id,{'note':str(note)[:400]})
        return out

    def run_rules(self,workspace,actor):
        rules=self.rules(workspace);by_asset={};observations=[]
        for rule in rules:
            if rule.get('status')!='active':continue
            aid=rule['asset_id']; col=rule.get('column'); kind=rule['rule_type']
            status='error';actual=None;details='';evidence_id=None
            try:
                if kind=='relationship_coverage_min':
                    relation=self.validate_relationship(workspace,rule['relationship_id'],actor)
                    e=relation['evidence'];actual=e['coverage'];evidence_id=rule['relationship_id']
                else:
                    if aid not in by_asset:by_asset[aid]=self.profile(workspace,aid,'standard',actor)
                    p=by_asset[aid];evidence_id=p['profile_id']
                    if p['status']!='complete':raise ValueError('Profiling is incomplete; no quality verdict')
                    if kind=='row_count_min':actual=p['row_count']
                    else:
                        metric=next((c for c in p['columns'] if c['name']==col),None)
                        if not metric or not metric.get('measured'):raise ValueError('Column could not be measured')
                        total=p['row_count'] or 0
                        if kind in ('not_null','completeness_min'):actual=metric['non_null_count']/total if total else 0
                        elif kind=='unique_min':actual=metric['uniqueness_ratio']
                status='pass' if actual>=rule['threshold'] else 'fail'
            except Exception as exc:details=str(exc)[:300]
            observations.append({'rule_id':rule['rule_id'],'asset_id':aid,'column':col,
              'rule_type':kind,'threshold':rule['threshold'],'actual':round(actual,5) if actual is not None else None,
              'status':status,'error':details,'evidence_id':evidence_id})
        runid='run-'+uuid4().hex[:16]
        out=self._put('run',workspace,runid,{'run_id':runid,'workspace_id':workspace,'status':'complete' if not any(x['status']=='error' for x in observations) else 'partial',
              'observations':observations,'passed':sum(x['status']=='pass' for x in observations),
              'failed':sum(x['status']=='fail' for x in observations),'errors':sum(x['status']=='error' for x in observations),
              'run_at':now(),'actor':actor,'review_status':'pending','remediation_status':'unassigned'})
        self.audit(workspace,actor,'quality_run',runid,{'pass':out['passed'],'fail':out['failed'],'error':out['errors']})
        return out

    def runs(self,workspace):return self._owned('run',workspace)

    def review_run(self,workspace,run_id,body,actor):
        r=self._get('run',workspace,run_id)
        decision=body.get('decision')
        if decision not in ('accepted','needs_remediation','waived'):raise ValueError('Unsupported ruling')
        note=str(body.get('note') or '').strip()
        if not note:raise ValueError('Ruling requires an explanation')
        if decision=='accepted' and (r['failed'] or r['errors']):raise ValueError('Cannot accept a run with failed/error rules; choose remediation or a documented waiver')
        r.update({'review_status':decision,'reviewed_by':actor,'reviewed_at':now(),'review_note':note[:2000]})
        out=self._put('run',workspace,run_id,r)
        self.audit(workspace,actor,'quality_'+decision,run_id,{'note':note[:400]})
        return out

    def remediate(self,workspace,run_id,body,actor):
        r=self._get('run',workspace,run_id)
        status=body.get('status');note=str(body.get('note') or '').strip()
        if status not in ('unassigned','open','in_progress','resolved') or not note:raise ValueError('Remediation status and note required')
        if status=='resolved' and r['review_status'] not in ('accepted','waived'):
            raise ValueError('Resolve only after a clean accepted run or explicit waiver; ideally re-run the rules')
        r.update({'remediation_status':status,'remediation_owner':str(body.get('owner') or actor)[:120],
                  'remediation_note':note[:2000],'remediation_updated_at':now()})
        out=self._put('run',workspace,run_id,r)
        self.audit(workspace,actor,'remediation_'+status,run_id,{'note':note[:400]})
        return out

    def transformations(self,workspace):return self._owned('transform',workspace)
    def register_transform(self,workspace,body,actor):
        inputs=list(body.get('inputs') or []);outputs=list(body.get('outputs') or [])
        if not inputs or not outputs or len(inputs)>30 or len(outputs)>30:raise ValueError('Transform needs bounded input and output assets')
        for aid in set(inputs+outputs):self.asset(workspace,aid)
        if len(set(inputs+outputs))<2 or set(inputs)&set(outputs):raise ValueError('Transformation input/output assets must differ')
        label=str(body.get('label') or '').strip()
        if not label or len(label)>160:raise ValueError('Transformation label required (max 160)')
        tid='transform-'+uuid4().hex[:14]
        out=self._put('transform',workspace,tid,{'transform_id':tid,'workspace_id':workspace,
            'label':label,'inputs':sorted(set(inputs)),'outputs':sorted(set(outputs)),
            'description':str(body.get('description') or '')[:1200], 'evidence_type':'steward_declared_not_executed',
            'status':'declared','registered_by':actor,'registered_at':now()})
        self.audit(workspace,actor,'transformation_registered',tid)
        return out

    def lineage(self,workspace):
        scope=self.scope(workspace);assets=self.assets(workspace)
        nodes=[];edges=[];idset=set()
        def node(id,label,kind,detail='',status='observed'):
            if id not in idset:
                nodes.append({'id':id,'label':label,'kind':kind,'detail':detail,'status':status});idset.add(id)
        def edge(source,target,kind,evidence):
            edges.append({'source_id':source,'target_id':target,'kind':kind,'evidence':evidence})
        source='source:'+scope['source_id'];node(source,scope['source_id'],'source','Configured connector')
        for a in assets:
            aid=a['asset_id'];node(aid,a['table'],'dataset',f"{a['database']}.{a['schema']}")
            edge(source,aid,'HOSTS','scope_allowlist')
        for p in self.profiles(workspace):
            pid=p['profile_id'];node(pid,p['tier']+' profile','profile',p['profiled_at'],p['status'])
            edge(p['asset_id'],pid,'MEASURED_BY','aggregate_query' if p['measured'] else 'metadata_only')
        for c in self._owned('contract',workspace):
            cid='contract:'+c['asset_id'];node(cid,c['asset_id'][-8:]+' contract','contract',c.get('owner',''),c['status'])
            edge(c['asset_id'],cid,'GOVERNED_BY','steward_review')
        for t in self.transformations(workspace):
            tid=t['transform_id'];node(tid,t['label'],'transformation',t.get('description',''),t['status'])
            for src in t['inputs']:edge(src,tid,'INPUT_TO','steward_declared')
            for dst in t['outputs']:edge(tid,dst,'OUTPUT_TO','steward_declared')
        for r in self.relationships(workspace):
            if r['status']=='suggested':continue
            rid=r['relationship_id'];node(rid,f"{r['from_column']} → {r['to_column']}",'relationship',r['status'],r['status'])
            edge(r['from_asset'],rid,'JOIN_SOURCE','aggregate_evidence' if r.get('evidence') else 'inferred')
            if r.get('evidence'):
                lid='lookup:'+rid;node(lid,r['to_column']+' lookup','lookup',r['to_asset'],r['status'])
                edge(r['to_asset'],lid,'PROVIDES_LOOKUP','aggregate_evidence')
                edge(lid,rid,'RESOLVES_RELATIONSHIP','aggregate_evidence')
            else:
                edge(rid,r['to_asset'],'LOOKUP_TARGET','inferred')
        return {'workspace_id':workspace,'nodes':nodes,'edges':edges,'counts':{kind:sum(n['kind']==kind for n in nodes) for kind in ('source','dataset','profile','contract','transformation','lookup','relationship')},
              'note':'Lineage is recorded only for measured profiles, declared transformations and evidenced relationships; inferred relations are not certified.'}

    def impact(self,workspace,node_id,direction='both',depth=3):
        if direction not in ('both','upstream','downstream') or depth<1 or depth>7:raise ValueError('Invalid impact options')
        graph=self.lineage(workspace);ids={n['id'] for n in graph['nodes']}
        if node_id not in ids:raise KeyError('Unknown lineage node')
        touched={node_id};frontier=[node_id];linked=[]
        for _ in range(depth):
            nxt=[]
            for e in graph['edges']:
                if (direction in ('both','downstream') and e['source_id'] in frontier) or (direction in ('both','upstream') and e['target_id'] in frontier):
                    linked.append(e);target=e['target_id'] if e['source_id'] in frontier else e['source_id']
                    if target not in touched:touched.add(target);nxt.append(target)
            frontier=nxt
            if not frontier:break
        return {'center':node_id,'nodes':[n for n in graph['nodes'] if n['id'] in touched],
                'edges':list({(e['source_id'],e['target_id'],e['kind']):e for e in linked}.values()),'direction':direction,'depth':depth}
