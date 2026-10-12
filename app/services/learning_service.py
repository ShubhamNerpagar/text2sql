from __future__ import annotations
from app.repositories.learning_repository import LearningRepository

class LearningService:
    def __init__(self): self.repo=LearningRepository()
    def recent(self,limit:int=30):
        rows=self.repo.recent_queries(limit)
        # The API deliberately omits result rows from history to minimise data retention.
        out=[]
        for x in rows:
            y=dict(x); y.pop('result_preview',None); out.append(y)
        return out
    def feedback(self,query_id:str,rating:str,note:str|None=None): return self.repo.update_feedback(query_id,rating,note)
