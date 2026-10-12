from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import yaml
from app.config import get_settings
from app.repositories.control_repository import ControlRepository
from app.adapters.aws import AwsAdapter

GLOBAL_FILES = [
    'concepts.yaml','metrics.yaml','glossary.yaml','rules.yaml','entities.yaml',
    'dimensions.yaml','hierarchies.yaml','lineage.yaml','security.yaml','actions.yaml',
    'trusted_queries.yaml','data_sources.yaml','calendar.yaml','semantic_functions.yaml'
]
RUNTIME_FILES = {
    'market':'market.yaml','concepts':'concepts.yaml','metrics':'metrics.yaml',
    'glossary':'glossary.yaml','value_mappings':'value_mappings.yaml','rules':'rules.yaml',
    'governed_joins':'joins.yaml','bindings':'bindings.yaml','verified_queries':'verified_queries.yaml',
    'entities':'entities.yaml','dimensions':'dimensions.yaml','hierarchies':'hierarchies.yaml',
    'lineage':'lineage.yaml','security':'security.yaml','actions':'actions.yaml',
    'trusted_queries':'trusted_queries.yaml','data_sources':'data_sources.yaml','calendar':'calendar.yaml',
    'semantic_functions':'semantic_functions.yaml'
}

def deep_merge(base, extra):
    if isinstance(base, dict) and isinstance(extra, dict):
        out = deepcopy(base)
        for k, v in extra.items(): out[k] = deep_merge(out[k], v) if k in out else deepcopy(v)
        return out
    if isinstance(base, list) and isinstance(extra, list): return deepcopy(base) + deepcopy(extra)
    return deepcopy(extra)

def _yaml(path: Path):
    if not path.exists(): return {}
    return yaml.safe_load(path.read_text(encoding='utf-8')) or {}

def _safe_id(value: str) -> str:
    value = re.sub(r'[^a-zA-Z0-9_-]+', '-', (value or '').strip()).strip('-').lower()
    if not value: raise ValueError('workspace_id is required')
    return value[:80]

class MarketService:
    """Runtime semantic workspaces.

    No country/customer semantic package ships with the product. A workspace is created
    only after metadata discovery against a configured data source. Local/native execution stores
    generated YAML under STATE_DIR/semantic/workspaces/<workspace>; AWS deployments also
    persist the canonical context to SEMANTIC_BUCKET and/or DynamoDB control state.
    """
    def __init__(self):
        self.s=get_settings(); self.root=self.s.data_dir/'semantic'; self.runtime_root=self.s.state_dir/'semantic'/'workspaces'; self.runtime_root.mkdir(parents=True,exist_ok=True)
        self.control=ControlRepository(); self.aws=AwsAdapter() if self.s.is_aws and self.s.semantic_bucket else None

    def _global_context(self):
        result={}
        for name in GLOBAL_FILES: result=deep_merge(result,_yaml(self.root/'global'/name))
        return result

    def _remote_key(self,workspace_id:str)->str:
        return f"{self.s.workspace_key_prefix.strip('/')}/{workspace_id}/context.json"

    def _record(self,workspace_id:str)->dict|None:
        wid=_safe_id(workspace_id)
        row=self.control.get('WORKSPACE',wid)
        if row: return row
        if self.aws:
            remote=self.aws.get_json(self._remote_key(wid))
            if remote:
                # Warm local/DynamoDB control state for subsequent requests.
                try: self.control.put('WORKSPACE',wid,remote)
                except Exception: pass
                return remote
        return None

    def list_markets(self):
        rows={}
        for row in self.control.list('WORKSPACE',500):
            wid=row.get('workspace_id') or (row.get('market') or {}).get('id')
            if wid: rows[wid]=row
        if self.aws:
            prefix=self.s.workspace_key_prefix.strip('/')
            for key in self.aws.list_keys(prefix):
                if not key.endswith('/context.json'): continue
                parts=key.split('/')
                if len(parts)<2: continue
                wid=parts[-2]
                if wid in rows: continue
                remote=self.aws.get_json(key)
                if remote: rows[wid]=remote
        out=[]
        for wid,row in rows.items():
            m=(row.get('semantic_context') or {}).get('market',{}) or row.get('market',{}) or {}
            out.append({
                'id':wid,'name':m.get('name',wid.replace('-',' ').title()),'country':m.get('country',''),
                'flag':m.get('flag','◉'),'currency':m.get('currency',''),'locale':m.get('locale',''),
                'region':m.get('region'),'data_source':m.get('data_source') or row.get('data_source'),
                'generated_at':row.get('generated_at') or m.get('generated_at'),'status':row.get('status','draft')
            })
        return sorted(out,key=lambda x:x['name'].lower())

    def context(self,market_id):
        if not market_id: raise KeyError('No semantic workspace is selected. Connect a data source first.')
        wid=_safe_id(market_id); row=self._record(wid)
        if not row: raise KeyError(f'Unknown semantic workspace: {wid}. Connect or bootstrap a data source first.')
        result=self._global_context(); result=deep_merge(result,row.get('semantic_context',{}) or {})
        overlays=[x for x in self.control.list('SUGGESTION',300) if x.get('type')=='semantic_overlay' and x.get('status')=='approved' and x.get('market')==wid]
        for ov in reversed(overlays):
            for patch in ov.get('patches',[]) or []:
                parts=[p for p in str(patch.get('path','')).strip('/').split('/') if p]; cur=result
                if not parts: continue
                for key in parts[:-1]: cur=cur.setdefault(key,{})
                if patch.get('operation')=='delete': cur.pop(parts[-1],None)
                else: cur[parts[-1]]=deepcopy(patch.get('value'))
        if row.get("scope_id"):
            from app.services.semantic_registry_service import SemanticRegistryService
            result=SemanticRegistryService().project_context(wid,result)
        return result

    def save_workspace(self,workspace_id:str,semantic_context:dict,*,source_id:str,source_scope:list[str]|None=None,status:str='draft')->dict:
        wid=_safe_id(workspace_id); now=datetime.now(timezone.utc).isoformat(); ctx=deepcopy(semantic_context)
        ctx.setdefault('market',{}); ctx['market'].update({'id':wid,'data_source':source_id,'generated_at':now})
        existing=self.control.get('WORKSPACE',wid) or {}
        record={**{k:existing[k] for k in ('scope_id','scope_version','selected_tables','catalog_snapshot','schema_drift') if k in existing},'workspace_id':wid,'data_source':source_id,'source_scope':source_scope or [],'status':status,'generated_at':now,'semantic_context':ctx}
        saved=self.control.put('WORKSPACE',wid,record)
        if self.aws: self.aws.put_json(self._remote_key(wid),saved)
        self._write_runtime_yaml(wid,ctx)
        return saved

    def _write_runtime_yaml(self,wid:str,ctx:dict):
        folder=self.runtime_root/wid; folder.mkdir(parents=True,exist_ok=True)
        # Generated files are an inspectable/exportable mirror. The control/S3 record is canonical.
        for key,filename in RUNTIME_FILES.items():
            if key not in ctx: continue
            payload={key:ctx[key]} if key not in {'market'} else {'market':ctx[key]}
            (folder/filename).write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding='utf-8')
        (folder/'GENERATED.md').write_text(
            '# Generated semantic workspace\n\nThis directory was generated from connected source metadata. '
            'Do not treat inferred semantics as certified until they are reviewed and published.\n',encoding='utf-8')

    # Canonical 7.x naming. Kept alongside list_markets/context for 6.x compatibility.
    def list_workspaces(self): return self.list_markets()
    def workspace(self,workspace_id): return self.context(workspace_id)

    def prompt_context(self,market_id):
        c=self.context(market_id); m=c.get('market',{}); lines=[f"WORKSPACE: {m.get('name',market_id)}",f"Data source: {m.get('data_source','')}; Locale: {m.get('locale','')}; Currency: {m.get('currency','')}"]
        if c.get('concepts'):
            lines.append('\nBUSINESS CONCEPTS:'); lines += [f"- {k}: {v.get('description','')} | synonyms={', '.join(v.get('synonyms',[]))}" for k,v in c['concepts'].items()]
        if c.get('metrics'):
            lines.append('\nGOVERNED METRICS:'); lines += [f"- {k}: {v.get('description','')} | status={v.get('status','draft')}" for k,v in c['metrics'].items()]
        if c.get('rules'):
            lines.append('\nWORKSPACE RULES:'); lines += [f"- {r.get('id','rule')}: {r.get('description','')}" for r in c['rules']]
        return '\n'.join(lines)
