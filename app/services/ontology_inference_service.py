from __future__ import annotations
import re, uuid
from datetime import datetime, timezone
from app.repositories.semantic_repository import SemanticRepository
from app.repositories.control_repository import ControlRepository
from app.services.type_inference import infer_semantic_type

class OntologyInferenceService:
    def __init__(self): self.semantic=SemanticRepository(); self.repo=ControlRepository()
    def infer(self,market='',max_suggestions=100):
        dd=self.semantic.ontology().get('data_dictionary',{}) or {}; out=[]
        for db,tables in dd.items():
            for table,info in tables.items():
                twords=set(re.findall(r'[a-z0-9]+',table.lower()))
                cols=info.get('columns',[]) or []
                ids=[c for c in cols if infer_semantic_type(c.get('name',''),c.get('type','string'),[]) in {'identifier','reference'}]
                if ids:
                    out.append({'id':'sug-'+uuid.uuid4().hex[:8],'type':'entity','label':table.replace('_',' ').title(),'source':f'{db}.{table}','confidence':.72,'authority':.35,'reason':'Table contains identifier/reference columns and looks entity-shaped.','status':'inferred'})
                for c in cols:
                    sem=infer_semantic_type(c.get('name',''),c.get('type','string'),[]); name=c.get('name','')
                    if sem in {'code','category'} or any(x in name.lower() for x in ['brand','country','status','type','region']):
                        out.append({'id':'sug-'+uuid.uuid4().hex[:8],'type':'dimension','label':name,'source':f'{db}.{table}.{name}','confidence':.68,'authority':.30,'reason':'Categorical/code field suitable for grouping or filtering.','status':'inferred'})
                    if any(x in name.lower() for x in ['amount','revenue','montant','price','cost','total']) and sem in {'numeric','amount','unknown'}:
                        out.append({'id':'sug-'+uuid.uuid4().hex[:8],'type':'metric','label':name,'source':f'{db}.{table}.{name}','confidence':.62,'authority':.25,'reason':'Numeric amount-like field is a candidate governed measure.','status':'inferred'})
                    if len(out)>=max_suggestions: break
                if len(out)>=max_suggestions: break
            if len(out)>=max_suggestions: break
        now=datetime.now(timezone.utc).isoformat()
        for x in out: x.update({'market':market,'created_at':now}); self.repo.put('SUGGESTION',x['id'],x)
        return {'market':market,'suggestions':out,'count':len(out),'samples_used':False}
    def list(self,market=None):
        rows=self.repo.list('SUGGESTION',300)
        return [x for x in rows if x.get('type')!='semantic_overlay' and (not market or x.get('market')==market)]

    def review(self,suggestion_id,status,note='',user='local-user'):
        item=self.repo.get('SUGGESTION',suggestion_id)
        if not item: raise KeyError(suggestion_id)
        if item.get('type')=='semantic_overlay': raise ValueError('Semantic overlays are governed through the branch workflow.')
        authority={'approved':.90,'certified':1.0,'rejected':0.0,'deprecated':.05}.get(status,item.get('authority',.35))
        item.update({'status':status,'authority':authority,'review_note':note,'reviewed_by':user,'reviewed_at':datetime.now(timezone.utc).isoformat()})
        return self.repo.put('SUGGESTION',suggestion_id,item)
