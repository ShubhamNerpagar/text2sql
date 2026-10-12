"""Compare shared LLM answers against independently authored aggregate reference SQL."""
from datetime import datetime, timezone
from decimal import Decimal
import math
import re
from uuid import uuid4
from app.repositories.control_repository import ControlRepository
from app.services.advanced_query_service import AdvancedQueryService
from app.services.unified_ask_service import UnifiedAskService
from app.services.sql_safety import validate_read_only_sql


class BusinessBenchmarkService:
    def __init__(self):self.repo=ControlRepository();self.engine=AdvancedQueryService()

    def cases(self,workspace):return [r for r in self.repo.list('BUSINESS_CASE',1000) if r['workspace_id']==workspace]

    def save(self,workspace,body,actor):
        self.engine.schema(workspace,body['release_id'])
        expected=body.get('expected','answer')
        if expected not in {'answer','refuse'}:raise ValueError('Benchmark expectation must be answer or refuse')
        question=body.get('question','')
        if not isinstance(question,str) or not 2<=len(question)<=500:raise ValueError('Invalid benchmark question')
        sql=body.get('reference_sql','')
        asset_id=body.get('reference_asset_id')
        if body.get('previous_plan') is not None:self.engine.compile(workspace,body['release_id'],body['previous_plan'])
        if expected=='answer':
            ok,_=validate_read_only_sql(sql)
            if not ok or not re.match(r'\s*SELECT\b',sql,re.I) or not re.search(r'\b(SUM|COUNT|AVG|MIN|MAX)\s*\(',sql,re.I):
                raise ValueError('Reference SQL must be an independently reviewed read-only aggregate SELECT')
            asset=self.engine.p2.asset(workspace,asset_id)
            allowed={self.engine.p2._table_sql(a).replace('"','').replace('`','').lower() for a in self.engine.p2.assets(workspace)}
            scrubbed=re.sub(r"'(?:''|[^'])*'", "''",sql)
            tables=re.findall(r'\b(?:FROM|JOIN)\s+([\w."`]+)',scrubbed,re.I)
            if not tables or any(t.replace('"','').replace('`','').lower() not in allowed for t in tables):raise ValueError('Reference SQL reads an unscoped table')
            if any(a['source_id']!=asset['source_id'] for a in self.engine.p2.assets(workspace)):raise ValueError('Reference connector must be unambiguous')
            funcs=set(x.upper() for x in re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)\s*\(',scrubbed))
            if funcs-{'SUM','COUNT','AVG','MIN','MAX','COALESCE','NULLIF','ROUND','CAST','DATE_TRUNC','STRFTIME','IN'}:
                raise ValueError('Reference SQL contains an unsupported function')
        ident=body.get('case_id') or 'case-'+uuid4().hex[:16]
        row={'workspace_id':workspace,'case_id':ident,'release_id':body['release_id'],'question':question,
            'expected':expected,'reference_sql':sql,'reference_asset_id':asset_id,'previous_plan':body.get('previous_plan'),
            'authored_by':actor,'updated_at':datetime.now(timezone.utc).isoformat()}
        return self.repo.put('BUSINESS_CASE',workspace+'::'+ident,row)

    @staticmethod
    def equivalent(actual,reference):
        if len(actual)!=len(reference):return False
        def normalized(row):
            # Compare SELECT order, not model-chosen display aliases.
            values=[]
            for v in row.values():
                if isinstance(v,(int,float,Decimal)) and not isinstance(v,bool):values.append(('number',float(v)))
                elif v is None:values.append(('null',None))
                else:values.append(('text',str(v)))
            return values
        left=sorted([normalized(r) for r in actual],key=repr);right=sorted([normalized(r) for r in reference],key=repr)
        if [len(r) for r in left]!=[len(r) for r in right]:return False
        for a,b in zip(left,right):
            for x,y in zip(a,b):
                if x[0]!=y[0]:return False
                if x[0]=='number':
                    if not math.isclose(x[1],y[1],rel_tol=1e-8,abs_tol=1e-8):return False
                elif x[1]!=y[1]:return False
        return True

    def run(self,workspace,release_id):
        cases=[c for c in self.cases(workspace) if c['release_id']==release_id]
        if not cases:raise ValueError('Add business-result benchmark cases before running')
        observations=[]
        for c in cases:
            try:
                answer=UnifiedAskService().ask(workspace,release_id,c['question'],True,c.get('previous_plan'))
                if c['expected']=='refuse':passed=answer['status']=='needs_clarification' and not answer['executed']
                elif answer['executed']:
                    a=self.engine.p2.asset(workspace,c['reference_asset_id'])
                    reference=self.engine.p2.sources.execute(a['source_id'],c['reference_sql'],a['database'])
                    passed=self.equivalent(answer['rows'],reference['rows'])
                else:passed=False
                observations.append({'case_id':c['case_id'],'status':'passed' if passed else 'failed','question':c['question']})
            except ValueError as exc:
                message=str(exc);blocked=any(x in message for x in ('LLM_CONNECTION_REQUIRED','LLM_UNAVAILABLE','LLM_INVALID','SEMANTIC_SCOPE_TOO_LARGE'))
                # A model/setup/execution exception is never evidence that an ambiguous
                # business question was correctly refused.
                observations.append({'case_id':c['case_id'],'status':'blocked' if blocked else 'failed','reason':message})
            except Exception as exc:observations.append({'case_id':c['case_id'],'status':'blocked','reason':type(exc).__name__})
        run_id='benchmark-'+uuid4().hex[:16];counts={k:sum(o['status']==k for o in observations) for k in ('passed','failed','blocked')}
        out={'workspace_id':workspace,'release_id':release_id,'run_id':run_id,'counts':counts,'total':len(cases),
            'status':'blocked' if counts['blocked'] else 'failed' if counts['failed'] else 'passed',
            'observations':observations,'created_at':datetime.now(timezone.utc).isoformat(),'method':'llm_answers_vs_independent_reference_sql'}
        self.repo.put('BUSINESS_RUN',run_id,out)
        return out
