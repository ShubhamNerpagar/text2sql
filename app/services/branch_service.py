from __future__ import annotations
import copy, uuid
from datetime import datetime, timezone
from app.repositories.control_repository import ControlRepository
from app.services.market_service import MarketService
from app.services.evaluation_service import EvaluationService

class BranchService:
    def __init__(self): self.repo=ControlRepository(); self.markets=MarketService()
    def create(self,market,name,description='',base_version=None,user='local-user'):
        bid='branch-'+uuid.uuid4().hex[:10]; now=datetime.now(timezone.utc).isoformat(); row={'branch_id':bid,'market':market,'name':name,'description':description,'base_version':base_version or 'main','status':'open','patches':[],'created_by':user,'created_at':now,'updated_at':now}
        return self.repo.put('BRANCH',bid,row)
    def get(self,bid):
        x=self.repo.get('BRANCH',bid)
        if not x: raise KeyError(bid)
        return x
    def list(self,market=None):
        rows=self.repo.list('BRANCH',200); return [x for x in rows if not market or x.get('market')==market]
    def patch(self,bid,path,value,operation='set'):
        b=self.get(bid); b.setdefault('patches',[]).append({'path':path,'value':value,'operation':operation,'at':datetime.now(timezone.utc).isoformat()}); return self.repo.put('BRANCH',bid,b)
    @staticmethod
    def _apply(obj,path,value,operation):
        parts=[p for p in path.strip('/').split('/') if p]; cur=obj
        for p in parts[:-1]: cur=cur.setdefault(p,{})
        if not parts: return obj
        if operation=='delete': cur.pop(parts[-1],None)
        else: cur[parts[-1]]=copy.deepcopy(value)
        return obj
    def materialize(self,bid):
        b=self.get(bid); ctx=copy.deepcopy(self.markets.context(b['market']))
        for p in b.get('patches',[]): self._apply(ctx,p['path'],p.get('value'),p.get('operation','set'))
        return ctx
    def compare(self,bid):
        b=self.get(bid); base=self.markets.context(b['market']); branch=self.materialize(bid)
        return {'branch':b,'patch_count':len(b.get('patches',[])),'base_keys':sorted(base.keys()),'branch_keys':sorted(branch.keys()),'patches':b.get('patches',[])}
    def validate(self,bid):
        b=self.get(bid); ctx=self.materialize(bid); issues=[]; warnings=[]
        market=ctx.get('market',{}) or {}
        if not market.get('id'): issues.append('market.id is required')
        metrics=ctx.get('metrics',{}) or {}
        for mid,m in metrics.items():
            if not isinstance(m,dict): issues.append(f'metric {mid} must be an object'); continue
            if not m.get('description'): warnings.append(f'metric {mid} has no description')
            sources=m.get('preferred_sources',[]) or []
            if not sources and not m.get('expression'): warnings.append(f'metric {mid} has no physical binding or expression')
        bindings=ctx.get('bindings',{}) or {}
        if not bindings: warnings.append('no logical-to-physical bindings are configured')
        return {'branch_id':bid,'market':b['market'],'valid':not issues,'issues':issues,'warnings':warnings,'patch_count':len(b.get('patches',[]))}

    def merge(self,bid,note='',user='local-user'):
        # Safe baseline: merge creates an approved semantic overlay artifact instead of rewriting source YAML.
        b=self.get(bid); b['status']='merged'; b['merged_by']=user; b['merge_note']=note; b['merged_at']=datetime.now(timezone.utc).isoformat(); self.repo.put('BRANCH',bid,b)
        self.repo.put('SUGGESTION','merged:'+bid,{'type':'semantic_overlay','market':b['market'],'branch_id':bid,'patches':b.get('patches',[]),'status':'approved','created_at':b['merged_at']})
        return b
