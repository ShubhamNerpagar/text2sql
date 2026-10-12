from __future__ import annotations
import uuid
from datetime import datetime, timezone
import yaml
from app.config import get_settings
from app.services.semantic_resolver import SemanticResolver
from app.services.plan_service import PlanService
from app.services.graph_rag_service import GraphRAGService
from app.services.sql_compiler import SQLCompiler
from app.repositories.learning_repository import LearningRepository
from app.services.text_utils import normalize
from app.services.query_router import QueryRouter
from app.services.trusted_query_service import TrustedQueryService
from app.services.feature_classifier import FeatureClassifier


class EvaluationService:
    """Semantic regression harness.

    Suites can validate pure semantic resolution or the complete deterministic path:
    GraphRAG retrieval -> semantic plan -> trusted joins -> governed SQL compiler.
    """
    def __init__(self):
        self.s=get_settings(); self.root=self.s.data_dir/'evaluation'; self.resolver=SemanticResolver(); self.plans=PlanService(); self.graph=GraphRAGService(); self.compiler=SQLCompiler(); self.learning=LearningRepository(); self.router=QueryRouter(); self.trusted=TrustedQueryService(); self.features=FeatureClassifier()

    def suites(self)->list[dict]:
        out=[]
        for p in sorted(self.root.glob('*.yaml')):
            d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}; meta=d.get('suite',{})
            out.append({**meta,'mode':meta.get('mode','semantic'),'case_count':len(d.get('cases',[]) or []),'file':p.name})
        return out

    def _load(self,suite_id:str)->dict:
        for p in self.root.glob('*.yaml'):
            d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
            if d.get('suite',{}).get('id')==suite_id: return d
        raise KeyError(suite_id)

    @staticmethod
    def _decision(resolution:dict)->str:
        return 'ASK' if resolution.get('ambiguities') else 'COMMIT'

    def _score_case(self,case:dict,res:dict,plan:dict|None=None,graph:dict|None=None,compiled:dict|None=None)->dict:
        exp=case.get('expected',{}) or {}; checks=[]
        def compact(value):
            if isinstance(value,str) and len(value)>2000: return value[:2000]+'…'
            if isinstance(value,list) and len(value)>30: return value[:30]+['…']
            return value
        def add(name,passed,expected=None,actual=None,weight=1.0):
            checks.append({'name':name,'passed':bool(passed),'expected':compact(expected),'actual':compact(actual),'weight':weight})
        if exp.get('decision'):
            actual=(plan or {}).get('decision') or self._decision(res)
            add('decision',actual==exp['decision'],exp['decision'],actual,2)
        if exp.get('metric'):
            actual=res['metrics'][0]['id'] if res.get('metrics') else None
            add('metric',actual==exp['metric'],exp['metric'],actual,2)
        if exp.get('concepts'):
            actual={x['id'] for x in res.get('concepts',[])}
            for c in exp['concepts']: add(f'concept:{c}',c in actual,c,sorted(actual),1)
        if exp.get('values'):
            actual={(x['dimension'],x['canonical']) for x in res.get('resolved_values',[])}
            for dim,val in exp['values'].items(): add(f'value:{dim}',(dim,val) in actual,val,sorted(actual),1.5)
        if exp.get('year'):
            years=res.get('time',{}).get('years',[]); add('year',exp['year'] in years,exp['year'],years,1)
        if exp.get('ambiguity'):
            actual=[x.get('term') for x in res.get('ambiguities',[])]; add('ambiguity',exp['ambiguity'] in actual,exp['ambiguity'],actual,1.5)
        if exp.get('verified_query'):
            actual=[x.get('id') for x in res.get('verified_query_matches',[])]; add('verified_query',exp['verified_query'] in actual,exp['verified_query'],actual,1)
        if exp.get('tables'):
            actual=set((plan or {}).get('tables',[]) or [])
            for t in exp['tables']: add(f'table:{t.split(".")[-1]}',t in actual,t,sorted(actual),1.5)
        if exp.get('graph_types'):
            actual=[x.get('node_type') for x in (graph or {}).get('results',[])]; aset=set(actual)
            for t in exp['graph_types']: add(f'graph_type:{t}',t in aset,t,actual,1)
        if exp.get('graph_labels'):
            labels={normalize(x.get('label','')) for x in (graph or {}).get('results',[])}
            for label in exp['graph_labels']: add(f'graph_label:{label}',normalize(label) in labels,label,sorted(labels),1)
        if 'compiler_supported' in exp:
            actual=bool((compiled or {}).get('supported')); add('compiler_supported',actual==bool(exp['compiler_supported']),bool(exp['compiler_supported']),actual,2)
        if exp.get('sql_contains'):
            sql=normalize((compiled or {}).get('sql') or '')
            for bit in exp['sql_contains']: add(f'sql:{bit}',normalize(bit) in sql,bit,(compiled or {}).get('sql'),1)
        if exp.get('join_sources'):
            actual=[x.get('source') for x in (plan or {}).get('join_plan',{}).get('joins',[])];
            for src in exp['join_sources']: add(f'join_source:{src}',src in actual,src,actual,1)
        if exp.get('trusted_joins_only'):
            actual=all(bool(x.get('trusted')) for x in (plan or {}).get('join_plan',{}).get('joins',[]))
            add('trusted_joins_only',actual,True,actual,2)
        if exp.get('sql_not_contains'):
            sql=normalize((compiled or {}).get('sql') or '')
            for bit in exp['sql_not_contains']: add(f'sql_not:{bit}',normalize(bit) not in sql,bit,(compiled or {}).get('sql'),1.5)
        if exp.get('feature'):
            f=self.features.classify(case.get('question','')); actual=set(f.get('features',[])); add(f"feature:{exp['feature']}",exp['feature'] in actual,exp['feature'],sorted(actual),1)
        if exp.get('route') and plan is not None and compiled is not None:
            tq=self.trusted.match(case.get('question',''),plan.get('market','')); actual=self.router.route(case.get('question',''),plan,compiled,tq).get('route'); add('route',actual==exp['route'],exp['route'],actual,2)
        if exp.get('min_graph_authority') is not None:
            vals=[float(x.get('authority',0)) for x in (graph or {}).get('results',[])[:8]]; actual=sum(vals)/len(vals) if vals else 0; add('min_graph_authority',actual>=float(exp['min_graph_authority']),exp['min_graph_authority'],round(actual,3),1)
        total=sum(x['weight'] for x in checks) or 1; earned=sum(x['weight'] for x in checks if x['passed'])
        return {'id':case.get('id'),'question':case.get('question'),'score':round(100*earned/total,1),'passed':all(x['passed'] for x in checks),'checks':checks,
                'resolution':{k:v for k,v in res.items() if k!='graph_retrieval'},'plan_summary':{'decision':(plan or {}).get('decision'),'tables':(plan or {}).get('tables',[]),'joins':len((plan or {}).get('join_plan',{}).get('joins',[]))} if plan else None,
                'graph_summary':{'result_count':len((graph or {}).get('results',[])),'tables':(graph or {}).get('tables',[])} if graph else None,
                'compiler_summary':{'supported':(compiled or {}).get('supported'),'compiler':(compiled or {}).get('compiler')} if compiled else None}

    def run(self,suite_id:str)->dict:
        data=self._load(suite_id); meta=data.get('suite',{}); market=meta.get('market',''); mode=meta.get('mode','semantic'); results=[]
        for case in data.get('cases',[]) or []:
            question=case.get('question',''); res=self.resolver.resolve(question,market); plan=graph=compiled=None
            if mode in {'full','intelligence','compiler'}:
                plan=self.plans.build(question,market); graph=res.get('graph_retrieval') or self.graph.search(question,market,top_k=8,depth=1); compiled=self.compiler.compile(plan)
            results.append(self._score_case(case,res,plan,graph,compiled))
        avg=round(sum(x['score'] for x in results)/max(1,len(results)),1); passed=sum(x['passed'] for x in results)
        run={'run_id':'eval-'+uuid.uuid4().hex[:10],'suite_id':suite_id,'suite_name':meta.get('name',suite_id),'market':market,'mode':mode,
             'score':avg,'passed_cases':passed,'total_cases':len(results),'failed_cases':len(results)-passed,'results':results,'created_at':datetime.now(timezone.utc).isoformat()}
        previous=next((x for x in self.learning.recent_evaluations(50) if x.get('suite_id')==suite_id),None)
        if previous:
            run['previous_score']=previous.get('score'); run['delta']=round(avg-float(previous.get('score',0)),1)
            prev={x.get('id'):x for x in previous.get('results',[])}
            run['regressions']=[x['id'] for x in results if not x['passed'] and prev.get(x['id'],{}).get('passed')]
            run['improvements']=[x['id'] for x in results if x['passed'] and prev.get(x['id']) and not prev[x['id']].get('passed')]
        else:
            run['previous_score']=None; run['delta']=None; run['regressions']=[]; run['improvements']=[]
        self.learning.put_evaluation(run); return run

    def latest(self,suite_id:str|None=None)->dict|None:
        rows=self.learning.recent_evaluations(50)
        if suite_id: rows=[x for x in rows if x.get('suite_id')==suite_id]
        return rows[0] if rows else None
