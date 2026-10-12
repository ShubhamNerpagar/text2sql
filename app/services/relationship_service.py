from datetime import datetime, timezone
from app.repositories.semantic_repository import SemanticRepository

RUNTIME_STATUSES={"certified","verified","data_validated","edited","s3_imported","manual_verified"}

class RelationshipService:
    def __init__(self): self.repo=SemanticRepository()
    def _normalized(self,r:dict,index:int):
        status=(r.get("status") or "").lower(); source=(r.get("source") or "").lower()
        if not status and source in {"manual","s3","tables_link"}: status="verified"
        if source=="manual" and status in {"","manual"}: status="verified"
        confidence=r.get("confidence_score",r.get("confidence",0))
        try: confidence=float(confidence)
        except Exception: confidence={"high":.9,"medium":.7,"low":.5}.get(str(confidence).lower(),0)
        trusted=status in RUNTIME_STATUSES or (source in {"s3","tables_link"} and status!="rejected")
        return {**r,"id":r.get("id") or f"rel-{index}","status":status or "ai_suggested","confidence_score":confidence,"trusted_for_queries":trusted}
    def all(self):
        from app.services.semantic_registry_service import SemanticRegistryService
        from app.repositories.control_repository import ControlRepository
        registry=SemanticRegistryService();scoped=[r for r in ControlRepository().list('WORKSPACE',500) if r.get('scope_id')]
        workspaces={r['workspace_id'] for r in scoped if (ControlRepository().get('SCOPE',r['scope_id']) or {}).get('status')=='generated'};out=[]
        for w in workspaces:out.extend(registry.graph_relationships(w))
        out.extend(self._normalized(r,i) for i,r in enumerate(self.repo.relationships().get('relationships',[])) if (r.get('market') or r.get('workspace_id')) not in workspaces)
        return out
    def trusted(self): return [r for r in self.all() if r["trusted_for_queries"] and r["status"]!="rejected"]
    def stats(self):
        rs=self.all()
        return {"total":len(rs),"trusted":sum(r["trusted_for_queries"] for r in rs),"ai_suggested":sum(r["status"]=="ai_suggested" for r in rs),"needs_review":sum((not r["trusted_for_queries"] and r["status"]!="rejected") for r in rs),"rejected":sum(r["status"]=="rejected" for r in rs)}
    def act(self,rel_id:str,action:str,note:str|None=None,workspace=None,actor='relationship-reviewer'):
        if rel_id.startswith('rel:'):
            from app.services.phase2_service import Phase2Service
            matches=[r for r in self.all() if r['id']==rel_id and (not workspace or r['workspace_id']==workspace)]
            if len(matches)>1:raise ValueError('Specify the relationship workspace')
            r=matches[0] if matches else None
            if not r:raise KeyError(rel_id)
            service=Phase2Service();w=r['workspace_id']
            if action=='validate':return service.validate_relationship(w,rel_id,actor)
            if action not in {'verify','certify','reject','deprecate'}:raise ValueError('Unknown relationship action')
            return service.review_relationship(w,rel_id,'rejected' if action in {'reject','deprecate'} else 'approved',note or '',actor)
        data=self.repo.relationships(); rels=data.get("relationships",[])
        try: idx=int(rel_id.split("-")[-1])
        except Exception: idx=-1
        if idx<0 or idx>=len(rels): raise KeyError(rel_id)
        r=rels[idx]
        if action=="verify": r["status"]="verified"
        elif action=="validate": r["status"]="data_validated"
        elif action=="certify": r["status"]="certified"
        elif action=="deprecate": r["status"]="deprecated"
        elif action=="reject": r["status"]="rejected"
        else: raise ValueError(action)
        r["review_note"]=note or ""; r["reviewed_at"]=datetime.now(timezone.utc).isoformat(); data["last_updated"]=datetime.now(timezone.utc).isoformat(); self.repo.save_relationships(data)
        return self._normalized(r,idx)
