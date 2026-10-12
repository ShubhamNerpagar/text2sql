from __future__ import annotations
import json
from threading import RLock
from app.config import get_settings
from app.adapters.aws import AwsAdapter

class SemanticRepository:
    def __init__(self):
        self.s=get_settings(); self.lock=RLock(); self.aws=AwsAdapter() if self.s.is_aws else None
        self.seed=self.s.data_dir/"seed"; self.state=self.s.state_dir
    def _load_local(self,name:str)->dict:
        state=self.state/name; seed=self.seed/name; p=state if state.exists() else seed
        return json.loads(p.read_text(encoding="utf-8"))
    def ontology(self)->dict:
        if self.aws:
            remote=self.aws.get_json(self.s.ontology_key)
            if remote: return remote
        return self._load_local("ontology.json")
    def relationships(self)->dict:
        if self.aws:
            remote=self.aws.get_json(self.s.relationships_key)
            if remote: return remote
        return self._load_local("relationships.json")
    def save_relationships(self,data:dict)->None:
        with self.lock:
            if self.aws and self.s.semantic_bucket: self.aws.put_json(self.s.relationships_key,data)
            if self.s.persist_local_state or not self.aws: (self.state/"relationships.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    def save_ontology(self,data:dict)->None:
        with self.lock:
            if self.aws and self.s.semantic_bucket: self.aws.put_json(self.s.ontology_key,data)
            if self.s.persist_local_state or not self.aws: (self.state/"ontology.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
