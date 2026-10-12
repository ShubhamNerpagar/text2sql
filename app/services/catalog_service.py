from app.config import get_settings
from app.repositories.semantic_repository import SemanticRepository
from app.adapters.aws import AwsAdapter
from app.services.type_inference import infer_semantic_type

class CatalogService:
    def __init__(self): self.s=get_settings(); self.repo=SemanticRepository(); self.aws=AwsAdapter() if self.s.is_aws else None
    def _dd(self,market:str|None=None):
        dd=self.repo.ontology().get('data_dictionary',{}) or {}
        if not market: return dd
        out={}
        for db,tables in dd.items():
            selected={name:info for name,info in (tables or {}).items() if not (info or {}).get('market') or (info or {}).get('market')==market}
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
