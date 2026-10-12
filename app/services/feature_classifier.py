from __future__ import annotations
import re
from app.services.text_utils import normalize

class FeatureClassifier:
    """Deterministic query-feature classifier used to route specialized SQL skills."""
    def classify(self,question:str)->dict:
        q=normalize(question); features=[]; skills=[]
        def flag(name,patterns,skill=None):
            hit=any(re.search(p,q) for p in patterns)
            if hit: features.append(name); skills.append(skill or name)
            return hit
        rank=flag('ranking',[r'\btop\b',r'\bbottom\b',r'\brank',r'highest',r'lowest'],'ranking')
        pop=flag('period_over_period',[r'year over year',r'yo[y ]',r'quarter over quarter',r'qo[q ]',r'month over month',r'mo[m ]',r'growth',r'change versus',r'compared to'],'period_over_period')
        rolling=flag('rolling_window',[r'rolling',r'moving average',r'last \d+ (days|weeks|months)'],'rolling_window')
        cumulative=flag('cumulative',[r'cumulative',r'running total',r'year to date',r'\bytd\b'],'cumulative')
        cohort=flag('cohort',[r'cohort',r'retention'],'cohort')
        funnel=flag('funnel',[r'funnel',r'conversion rate',r'converted'],'funnel')
        distribution=flag('distribution',[r'distribution',r'percentile',r'median',r'p\d\d'],'distribution')
        anomaly=flag('anomaly',[r'anomal',r'outlier',r'unusual',r'spike',r'drop'],'anomaly')
        timeseries=flag('time_series',[r'by (day|week|month|quarter|year)',r'trend',r'over time'],'time_series')
        detail=flag('detail',[r'list ',r'show all',r'detail',r'records'],'detail')
        aggregate=bool(re.search(r'\b(total|sum|average|avg|count|how many|revenue|sales|amount)\b',q))
        if aggregate: features.append('aggregation'); skills.append('aggregation')
        complexity=1 + int(pop)+int(rolling)+int(cumulative)+int(cohort)+int(funnel)+int(distribution)+int(anomaly)+int(timeseries)+int(rank)
        return {'intent':'detail' if detail and not aggregate else 'analysis','features':list(dict.fromkeys(features)),'skills':list(dict.fromkeys(skills)),'complexity_score':min(10,complexity),'requires_window':pop or rolling or cumulative or rank,'requires_multi_step':cohort or funnel or anomaly}
