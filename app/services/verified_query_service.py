from __future__ import annotations
from app.services.market_service import MarketService
from app.services.text_utils import similarity

class VerifiedQueryService:
    """Retrieves approved question/plan/SQL examples from the selected semantic package."""
    def __init__(self): self.markets=MarketService()

    def all(self,market:str)->list[dict]:
        ctx=self.markets.context(market)
        rows=ctx.get('verified_queries',[]) or []
        out=[]
        for i,row in enumerate(rows):
            if not isinstance(row,dict): continue
            x=dict(row)
            x.setdefault('id',f'{market}-vq-{i+1}')
            x.setdefault('status','verified')
            out.append(x)
        return out

    def retrieve(self,question:str,market:str,limit:int=3,min_score:float=.12)->list[dict]:
        scored=[]
        for row in self.all(market):
            if str(row.get('status','verified')).lower() not in {'verified','approved','golden'}: continue
            score=similarity(question,row.get('question',''))
            tag_text=' '.join(str(x) for x in row.get('tags',[]))
            score=max(score, similarity(question,tag_text)*.8)
            if score>=min_score:
                scored.append((score,row))
        scored.sort(key=lambda x:x[0],reverse=True)
        return [{**row,'match_score':round(score,4)} for score,row in scored[:limit]]
