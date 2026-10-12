import re
from datetime import datetime, timezone
from app.config import get_settings
from app.repositories.semantic_repository import SemanticRepository
from app.services.market_service import MarketService
from app.services.type_inference import infer_semantic_type
from app.adapters.aws import AwsAdapter

class DescriptionService:
    def __init__(self): self.s=get_settings(); self.repo=SemanticRepository(); self.markets=MarketService(); self.aws=AwsAdapter() if self.s.is_aws else None
    def _find(self,database,table,column):
        ont=self.repo.ontology(); info=ont.get("data_dictionary",{}).get(database,{}).get(table,{})
        for c in info.get("columns",[]):
            if c.get("name")==column: return ont,info,c
        raise KeyError(f"{database}.{table}.{column}")
    def generate(self,market,database,table,column,force_ai=False):
        _,tinfo,col=self._find(database,table,column); name=col.get("name",column); typ=col.get("type","string"); sem=infer_semantic_type(name,typ,[])
        tokens=[t for t in re.split(r"[_\W]+",name) if t]; context=self.markets.context(market); glossary=context.get("glossary",{})
        expanded=[glossary.get(t.lower(),{}).get("preferred",t) if isinstance(glossary.get(t.lower(),{}),dict) else t for t in tokens]
        table_desc=tinfo.get("description") or tinfo.get("table_description") or table.replace("_"," ")
        description=f"{' '.join(expanded).replace('-', ' ').title()} associated with {table_desc}."
        evidence={"column_name":True,"datatype":True,"table_context":True,"market_glossary":any(t.lower() in glossary for t in tokens),"relationships":False,"profile_statistics":False,"sample_values":False}
        confidence=.52+.08*evidence["market_glossary"]+.08*(sem!="unknown")+.06*bool(table_desc); touching=[]
        from app.services.relationship_service import RelationshipService
        for r in RelationshipService().all():
            if (r.get("from_db")==database and r.get("from_table")==table and r.get("from_column")==column) or (r.get("to_db")==database and r.get("to_table")==table and r.get("to_column")==column): touching.append(r)
        if touching: evidence["relationships"]=True; confidence+=.1
        if self.aws and (force_ai or confidence<.8):
            prompt=("You are a data steward. Write one concise business description for a database column. Do not invent facts. Samples are intentionally unavailable.\n"
                    f"Market context:\n{self.markets.prompt_context(market)}\nDatabase: {database}\nTable: {table}\nTable context: {table_desc}\nColumn: {name}\nPhysical type: {typ}\nSemantic type: {sem}\n"
                    f"Neighbour columns: {', '.join(c.get('name','') for c in tinfo.get('columns',[])[:30])}\nRelationships touching column: {touching[:5]}\nReturn description only.")
            try:
                ai=self.aws.invoke_text(prompt,700,task='classification').strip().strip('"')
                if 8<len(ai)<600: description=ai; confidence=min(.94,confidence+.12); evidence["ai_enriched"]=True
            except Exception as e: evidence["ai_error"]=str(e)[:120]
        return {"database":database,"table":table,"column":column,"description":description,"semantic_type":sem,"confidence":round(min(confidence,.98),2),"status":"ai_generated","evidence":evidence,"sample_data_required":False}
    def update(self,database,table,column,description,status):
        ont,_,col=self._find(database,table,column); col["comment"]=description; col["description"]=description; col["description_status"]=status; col["description_reviewed_at"]=datetime.now(timezone.utc).isoformat(); self.repo.save_ontology(ont); return col
