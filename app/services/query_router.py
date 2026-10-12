from __future__ import annotations
from app.config import get_settings
from app.services.feature_classifier import FeatureClassifier

class QueryRouter:
    def __init__(self): self.s=get_settings(); self.features=FeatureClassifier()
    def route(self,question:str,plan:dict,compiled:dict, trusted_query:dict|None=None)->dict:
        feat=self.features.classify(question)
        if trusted_query and trusted_query.get('eligible'):
            route='trusted_template'; llm_calls=0; latency='very_low'; reason='Matched an approved parameterized trusted query.'
        elif compiled.get('supported'):
            route='deterministic_compiler'; llm_calls=0; latency='low'
            reason='Metadata-grounded inferred semantic preview; certify the metric before production publishing.' if plan.get('governance_mode')=='inferred_preview' else 'All semantic objects are governed and compiler-supported.'
        else:
            route='agent_reasoning'; llm_calls=min(self.s.max_llm_calls_per_query,2 if feat['complexity_score']<5 else 3); latency='medium_high'; reason='Semantic shape requires model-assisted SQL reasoning.'
        return {'route':route,'reason':reason,'features':feat,'estimated_llm_calls':llm_calls,'latency_class':latency,'max_query_bytes':self.s.max_query_bytes,'estimated_cost_guard_usd':round(self.s.max_query_bytes/(1024**4)*self.s.query_cost_per_tb_usd,4)}
