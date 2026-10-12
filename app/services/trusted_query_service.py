from __future__ import annotations
import re
from app.services.market_service import MarketService
from app.services.text_utils import similarity, normalize
from app.services.value_index_service import ValueIndexService

class TrustedQueryService:
    def __init__(self): self.markets=MarketService(); self.values=ValueIndexService()
    def all(self,market): return self.markets.context(market).get('trusted_queries',[]) or []
    def match(self,question,market):
        best=None
        for q in self.all(market):
            score=max([similarity(question,x) for x in [q.get('question',''),*(q.get('aliases',[]) or [])]] or [0])
            if score>=float(q.get('min_match',.78)) and (not best or score>best['match_score']): best={**q,'match_score':round(score,3)}
        if not best: return None
        params={}; missing=[]; low=normalize(question)
        for p in best.get('parameters',[]) or []:
            name=p['name']; typ=p.get('type','string')
            if typ=='year':
                m=re.search(r'\b(20\d{2}|19\d{2})\b',question); params[name]=int(m.group(1)) if m else p.get('default')
            elif typ=='market_value':
                dim=p.get('dimension'); hits=self.values.resolve(question,market)
                h=next((x for x in hits if x.get('dimension')==dim),None); params[name]=(h or {}).get('representations',{}).get(p.get('representation')) or (h or {}).get('canonical')
            else: params[name]=p.get('default')
            if params.get(name) in {None,''}: missing.append(name)
        return {**best,'parameters_resolved':params,'missing_parameters':missing,'eligible':not missing}
    def render(self,match:dict)->str:
        sql=match.get('sql','')
        for k,v in (match.get('parameters_resolved') or {}).items():
            safe=str(v).replace("'","''")
            sql=sql.replace('{{'+k+'}}',safe)
        return sql
