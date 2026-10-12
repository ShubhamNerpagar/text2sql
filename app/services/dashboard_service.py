from app.repositories.semantic_repository import SemanticRepository
from app.services.relationship_service import RelationshipService

class DashboardService:
    def __init__(self): self.repo=SemanticRepository(); self.rels=RelationshipService()
    def stats(self):
        ont=self.repo.ontology(); dd=ont.get("data_dictionary",{})
        tables=sum(len(x) for x in dd.values()); cols=sum(len(t.get("columns",[])) for db in dd.values() for t in db.values())
        descriptions=sum(1 for db in dd.values() for t in db.values() for c in t.get("columns",[]) if c.get("comment") or c.get("description") or c.get("meaningful_name"))
        rel=self.rels.stats()
        return {"databases":len(dd),"tables":tables,"columns":cols,"described_columns":descriptions,"description_coverage":round(100*descriptions/cols,1) if cols else 0,"relationships":rel}
