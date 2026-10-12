from __future__ import annotations
from collections import Counter
from statistics import mean
from app.repositories.learning_repository import LearningRepository
from app.repositories.control_repository import ControlRepository
from app.services.evaluation_service import EvaluationService
from app.services.relationship_service import RelationshipService

def percentile(values,p):
    if not values:return None
    xs=sorted(float(x) for x in values); k=(len(xs)-1)*p; lo=int(k); hi=min(lo+1,len(xs)-1); frac=k-lo
    return round(xs[lo]+(xs[hi]-xs[lo])*frac,1)
class MonitorService:
    def __init__(self): self.learning=LearningRepository(); self.control=ControlRepository(); self.eval=EvaluationService(); self.rels=RelationshipService()
    def summary(self,limit=200):
        rows=self.learning.recent_queries(limit); status=Counter(x.get('status','unknown') for x in rows); routes=Counter(x.get('route','unknown') for x in rows)
        lat=[(x.get('execution') or {}).get('execution_ms') for x in rows if (x.get('execution') or {}).get('execution_ms') is not None]; costs=[(x.get('execution') or {}).get('estimated_cost_usd') for x in rows if (x.get('execution') or {}).get('estimated_cost_usd') is not None]
        audit=self.control.list('AUDIT',limit); sec=[x for x in audit if str(x.get('event','')).startswith('security.')]; route_fail=Counter(x.get('route','unknown') for x in rows if x.get('status') not in {'success','needs_clarification'}); latest=self.eval.latest(); evs=self.learning.recent_evaluations(50); r=self.rels.stats()
        return {'queries':{'total':len(rows),'success':status.get('success',0),'needs_clarification':status.get('needs_clarification',0),'failed':status.get('failed',0),'routes':dict(routes),'route_failures':dict(route_fail),'avg_execution_ms':round(mean(lat),1) if lat else None,'p50_execution_ms':percentile(lat,.5),'p95_execution_ms':percentile(lat,.95),'p99_execution_ms':percentile(lat,.99),'estimated_cost_usd':round(sum(costs),6),'max_estimated_cost_usd':round(max(costs),6) if costs else None},'quality':{'latest_evaluation_score':latest.get('score') if latest else None,'latest_suite':latest.get('suite_id') if latest else None,'evaluation_regressions':sum(len(x.get('regressions',[]) or []) for x in evs),'evaluation_improvements':sum(len(x.get('improvements',[]) or []) for x in evs),'trusted_relationships':r.get('trusted',0),'relationship_review':r.get('needs_review',0)},'security':{'audit_events':len(audit),'blocks':len(sec),'block_rate':round(len(sec)/max(1,len(rows)),4)},'recent':rows[:10]}
