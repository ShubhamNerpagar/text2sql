from app.config import get_settings
from app.repositories.semantic_repository import SemanticRepository
from app.adapters.aws import AwsAdapter
from app.services.type_inference import infer_semantic_type

class CatalogService:
    def __init__(self): self.s=get_settings(); self.repo=SemanticRepository(); self.aws=AwsAdapter() if self.s.is_aws else None
    def _dd(self,market:str|None=None):
        dd=self.repo.ontology().get('data_dictionary',{}) or {}
        if not market: return dd
        from app.repositories.control_repository import ControlRepository
        control=ControlRepository();workspace=control.get('WORKSPACE',market) or {}
        scope=control.get('SCOPE',workspace['scope_id']) if workspace.get('scope_id') else None
        if scope:
            out={}
            for t in scope['tables']:
                source=t.get('source_id') or scope['source_id']
                db=t['database'] if scope['source_id']!='federated' else f"{source}::{t['database']}::{t.get('schema','')}"
                info=dd.get(db,{}).get(t['table'])
                if info is not None:out.setdefault(db,{})[t['table']]=info
            return out
        out={}
        for db,tables in dd.items():
            selected={name:info for name,info in (tables or {}).items() if market in ((info or {}).get('workspace_ids') or [(info or {}).get('market')])}
            if selected: out[db]=selected
        return out
    def databases(self,market:str|None=None): return sorted(self._dd(market).keys())
    def tables(self,database:str|None=None,market:str|None=None):
        dd=self._dd(market); out=[]; dbs=[database] if database else dd.keys()
        for db in dbs:
            for name,info in dd.get(db,{}).items():
                cols=info.get('columns',[])
                out.append({'database':db,'table':name,'name':name,'description':info.get('description') or info.get('table_description') or '','columns':len(cols),'domain':info.get('domain',''),'source_id':info.get('source_id'),'market':info.get('market'),'location':info.get('location','')})
        return sorted(out,key=lambda x:(x['database'],x['table']))
    def columns(self,database:str,table:str,market:str|None=None):
        info=self._dd(market).get(database,{}).get(table,{})
        return info.get('columns',[])
