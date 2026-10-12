"""Persist exact table allowlists and feed only those objects to onboarding."""
from __future__ import annotations
from datetime import datetime, timezone
import re
from app.repositories.control_repository import ControlRepository
from app.services.enterprise_catalog_service import EnterpriseCatalogService,SUPPORTED,safe_identifier
from app.services.onboarding_service import OnboardingService

WORKSPACE_RE=re.compile(r'^[A-Za-z0-9_-]{2,80}$')

class ScopeService:
    def __init__(self):
        self.repo=ControlRepository();self.catalog=EnterpriseCatalogService()
    def save(self,body):
        sid=str(body.get('scope_id','')).strip()
        wid=str(body.get('workspace_id','')).strip()
        if not WORKSPACE_RE.fullmatch(sid) or not WORKSPACE_RE.fullmatch(wid): raise ValueError('Scope and workspace IDs must use letters, numbers, hyphens or underscores (2–80 characters)')
        source=body.get('source_id','')
        if source not in SUPPORTED:raise ValueError('Unsupported source')
        tables=body.get('tables') or []
        if len(tables)<1 or len(tables)>500:raise ValueError('Select between 1 and 500 tables per scope; split larger estates into workspaces')
        cleaned=[]; seen=set()
        for obj in tables:
            if not isinstance(obj,dict):raise ValueError('Invalid table selection')
            db=str(obj.get('database') or '').strip();cat=str(obj.get('catalog') or '').strip();sch=str(obj.get('schema') or '').strip();name=safe_identifier(obj.get('table'))
            if source=='contoso':
                if db not in {'contoso_demo','contoso_official'}:raise ValueError('Invalid Contoso dataset')
                sch='public';cat='Bundled Sample'
            elif source=='athena':
                safe_identifier(db);cat=cat or self.catalog.s.athena_catalog
                if cat!=self.catalog.s.athena_catalog:raise ValueError('Only configured Athena catalog supported')
                sch=db
            else:
                safe_identifier(sch);safe_identifier(db)
                if cat:safe_identifier(cat)
            k=(cat,db,sch,name)
            if k in seen:continue
            seen.add(k);cleaned.append({'catalog':cat,'database':db,'schema':sch,'table':name})
        existing=self.repo.get('SCOPE',sid)
        if existing and (existing['workspace_id']!=wid or existing['source_id']!=source):raise ValueError('Scope ID already belongs to another workspace or connector')
        old_workspace=self.repo.get('WORKSPACE',wid)
        if old_workspace and old_workspace.get('scope_id') not in {None,sid}:
            raise ValueError('Workspace already belongs to another scope')
        keypairs=[(t['database'],t['table']) for t in cleaned]
        if len(set(keypairs))!=len(keypairs):raise ValueError('Two selected tables share database.table but differ by schema; use different workspaces')
        out={'scope_id':sid,'workspace_id':wid,'display_name':str(body.get('display_name') or wid)[:120], 'source_id':source,'tables':cleaned,'version':1+(existing or {}).get('version',0),'status':'selected','created_at':(existing or {}).get('created_at') or datetime.now(timezone.utc).isoformat(),'selected_count':len(cleaned)}
        return self.repo.put('SCOPE',sid,out)
    def list(self):return self.repo.list('SCOPE',500)
    def get(self,sid):
        out=self.repo.get('SCOPE',sid)
        if not out:raise KeyError('Scope not found')
        return out
    def build(self,sid,discover_relationships=False):
        scope=self.get(sid)
        discovery=self.catalog.selected_discovery(scope)
        # No global discovery and no unselected table metadata read.
        result=OnboardingService().bootstrap_source(scope['source_id'],scope['workspace_id'],scope['display_name'],discover_relationships=discover_relationships,discovery=discovery,scope_id=sid)
        scope.update({'status':'generated','last_generated_at':datetime.now(timezone.utc).isoformat()})
        self.repo.put('SCOPE',sid,scope)
        wr=self.repo.get('WORKSPACE',scope['workspace_id']) or {}
        wr.update({'scope_id':sid,'scope_version':scope['version'],'selected_tables':scope['tables']})
        self.repo.put('WORKSPACE',scope['workspace_id'],wr)
        return {**result,'scope_id':sid,'scope_version':scope['version'],'selected_count':len(scope['tables'])}
    def sync_workspace(self,wid):
        record=self.repo.get('WORKSPACE',wid) or {}
        if not record.get('scope_id'):return None
        return self.build(record['scope_id'],False)
