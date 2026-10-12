from __future__ import annotations
from app.services.catalog_service import CatalogService
from app.services.market_service import MarketService
from app.services.graph_rag_service import GraphRAGService
from app.services.security_service import SecurityService, UserContext
from app.services.text_utils import similarity, normalize

class UniversalSearchService:
    def __init__(self): self.catalog=CatalogService(); self.markets=MarketService(); self.graph=GraphRAGService(); self.security=SecurityService()
    def search(self,query:str,market:str,user:UserContext,limit:int=20):
        q=normalize(query); results=[]; ctx=self.markets.context(market)
        for mid,s in (ctx.get('metrics',{}) or {}).items():
            text=' '.join([mid,(s or {}).get('label',''),(s or {}).get('description',''),' '.join((s or {}).get('aliases',[]) or [])]); score=1.0 if q in {normalize(mid),normalize((s or {}).get('label',mid))} else max(similarity(q,normalize(text)), .82 if q and q in normalize(text) else 0)
            if score>.12: results.append({'kind':'metric','id':mid,'label':(s or {}).get('label',mid),'description':(s or {}).get('description',''),'score':score,'status':(s or {}).get('status')})
        for cid,s in (ctx.get('concepts',{}) or {}).items():
            text=' '.join([cid,(s or {}).get('label',''),(s or {}).get('description',''),' '.join((s or {}).get('synonyms',[]) or [])]); score=1.0 if q in {normalize(cid),normalize((s or {}).get('label',cid))} else max(similarity(q,normalize(text)), .82 if q and q in normalize(text) else 0)
            if score>.12: results.append({'kind':'concept','id':cid,'label':(s or {}).get('label',cid),'description':(s or {}).get('description',''),'score':score,'status':(s or {}).get('status')})
        for t in self.catalog.tables():
            text=f"{t.get('database','')} {t.get('table','')} {t.get('description','')}"; score=similarity(q,normalize(text))
            if score>.16: results.append({'kind':'table','id':f"{t.get('database')}.{t.get('table')}",'label':t.get('table'),'description':t.get('description',''),'score':score,'database':t.get('database')})
        try:
            gr=self.graph.search(query,market,top_k=min(limit,8),depth=1)
            for x in self.security.filter_graph_results(gr.get('results',[]),user,market):
                if x.get('score',0)>.18: results.append({'kind':'graph','id':x.get('id'),'label':x.get('label') or x.get('id'),'description':x.get('description',''),'score':x.get('score',0),'node_type':x.get('type')})
        except Exception: pass
        dedup={}
        for x in results:
            k=(x['kind'],x['id'])
            if k not in dedup or x['score']>dedup[k]['score']: dedup[k]=x
        rows=sorted(dedup.values(),key=lambda x:x.get('score',0),reverse=True)[:limit]
        return {'query':query,'market':market,'results':rows,'count':len(rows)}
