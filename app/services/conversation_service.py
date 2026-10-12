from __future__ import annotations
import uuid
from datetime import datetime, timezone
from app.repositories.control_repository import ControlRepository
from app.services.feature_classifier import FeatureClassifier

class ConversationService:
    def __init__(self): self.repo=ControlRepository(); self.features=FeatureClassifier()
    def create(self,market='',title=None,user_id='local-user'):
        cid='conv-'+uuid.uuid4().hex[:12]; now=datetime.now(timezone.utc).isoformat()
        row={'conversation_id':cid,'market':market,'title':title or 'New analysis','user_id':user_id,'turns':[],'context':{},'created_at':now,'updated_at':now}
        return self.repo.put('CONVERSATION',cid,row)
    def get(self,cid):
        x=self.repo.get('CONVERSATION',cid)
        if not x: raise KeyError(cid)
        return x
    def list(self,user_id=None,limit=50):
        rows=self.repo.list('CONVERSATION',limit)
        return [x for x in rows if not user_id or x.get('user_id')==user_id]
    def contextualize(self,question:str,cid:str|None)->dict:
        if not cid: return {'effective_question':question,'conversation':None,'inherited':{}}
        c=self.get(cid); ctx=c.get('context',{}) or {}; q=question.strip(); low=q.lower(); inherited={}
        # Follow-up replacement: inherit previous metric/time/dimensions when user supplies only a new entity/filter.
        is_followup=len(q.split())<=10 or any(x in low for x in ['what about','and ','same for','instead','versus','vs '])
        if is_followup and ctx:
            inherited={k:v for k,v in ctx.items() if k in {'metric','time','group_dimensions','market','resolved_values'} and v}
        return {'effective_question':q,'conversation':c,'inherited':inherited}
    def append(self,cid:str,question:str,response:dict):
        c=self.get(cid); plan=response.get('plan',{}) or {}; now=datetime.now(timezone.utc).isoformat()
        c.setdefault('turns',[]).append({'question':question,'query_id':response.get('query_id'),'status':response.get('status'),'created_at':now,'plan_summary':{'metric':(plan.get('metric') or {}).get('id') if isinstance(plan.get('metric'),dict) else plan.get('metric'),'time':plan.get('time',{}),'group_dimensions':plan.get('group_dimensions',[]),'resolved_values':plan.get('resolution',{}).get('resolved_values',[])}})
        c['turns']=c['turns'][-50:]
        c['context']={'metric':(plan.get('metric') or {}).get('id') if isinstance(plan.get('metric'),dict) else plan.get('metric'),'time':plan.get('time',{}),'group_dimensions':plan.get('group_dimensions',[]),'market':response.get('market'),'resolved_values':plan.get('resolution',{}).get('resolved_values',[])}
        if response.get('structured_plan'):
            c['context']['structured_plan']=response['structured_plan']
            c['context']['release_id']=response.get('release_id')
        c['updated_at']=now
        return self.repo.put('CONVERSATION',cid,c)
