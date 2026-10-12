from __future__ import annotations
from app.services.market_service import MarketService

class LogicalSchemaService:
    """Business/logical schema separated from warehouse-specific physical bindings."""
    def __init__(self): self.markets=MarketService()
    def build(self,market=''):
        c=self.markets.context(market); b=c.get('bindings',{}) or {}
        entities=[]; dimensions=[]; metrics=[]
        for k,v in (c.get('entities',{}) or {}).items(): entities.append({'id':k,'label':v.get('label',k.replace('_',' ').title()),'description':v.get('description',''),'physical':(b.get('concepts',{}) or {}).get(k),'status':v.get('status','governed')})
        for k,v in (c.get('dimensions',{}) or {}).items(): dimensions.append({'id':k,'label':v.get('label',k.replace('_',' ').title()),'description':v.get('description',''),'physical':(b.get('dimensions',{}) or {}).get(k),'status':v.get('status','governed')})
        for k,v in (c.get('metrics',{}) or {}).items(): metrics.append({'id':k,'label':v.get('label',k.replace('_',' ').title()),'description':v.get('description',''),'sources':v.get('preferred_sources',[]),'status':v.get('status','governed'),'owner':v.get('owner')})
        return {'market':market,'entities':entities,'dimensions':dimensions,'metrics':metrics,'hierarchies':c.get('hierarchies',[]) or [],'logical_to_physical':{'entities':b.get('concepts',{}),'dimensions':b.get('dimensions',{}),'dates':b.get('dates',{})}}
