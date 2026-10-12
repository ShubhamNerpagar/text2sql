from __future__ import annotations
import json
from datetime import datetime, timezone
from threading import RLock
from app.config import get_settings
from app.services.text_utils import similarity

class LearningRepository:
    """Persistent query/evaluation history using Query-based DynamoDB access."""
    def __init__(self):
        self.s=get_settings(); self.lock=RLock(); self.path=self.s.state_dir/'learning.json'; self._ddb=None
        if self.s.is_aws and self.s.learning_table:
            import boto3
            self._ddb=boto3.resource('dynamodb',region_name=self.s.aws_region).Table(self.s.learning_table)
    def _local(self):
        if not self.path.exists(): return {'queries':[],'evaluations':[]}
        try: return json.loads(self.path.read_text(encoding='utf-8'))
        except Exception: return {'queries':[],'evaluations':[]}
    def _save_local(self,data): self.path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    def put_query(self,item):
        item=dict(item); item.setdefault('created_at',datetime.now(timezone.utc).isoformat())
        if self._ddb:
            self._ddb.put_item(Item={'pk':'QUERY','sk':f"{item['created_at']}#{item['query_id']}",'lookup_id':item['query_id'],'payload':json.dumps(item,ensure_ascii=False),'created_at':item['created_at']}); return
        with self.lock:
            d=self._local(); rows=[x for x in d['queries'] if x.get('query_id')!=item.get('query_id')]; rows.append(item); d['queries']=rows[-self.s.max_learning_records:]; self._save_local(d)
    def _ddb_rows(self,pk,limit):
        from boto3.dynamodb.conditions import Key
        out=[]; kwargs={'KeyConditionExpression':Key('pk').eq(pk),'Limit':min(limit,200),'ScanIndexForward':False}
        while len(out)<limit:
            r=self._ddb.query(**kwargs); out.extend(r.get('Items',[])); lek=r.get('LastEvaluatedKey')
            if not lek: break
            kwargs['ExclusiveStartKey']=lek; kwargs['Limit']=min(limit-len(out),200)
        return [json.loads(x['payload']) for x in out[:limit]]
    def _find_ddb_query(self,query_id):
        for item in self._ddb_rows('QUERY',max(200,self.s.max_learning_records)):
            if item.get('query_id')==query_id: return item
        return None
    def update_feedback(self,query_id,rating,note=None):
        if self._ddb:
            item=self._find_ddb_query(query_id)
            if not item: raise KeyError(query_id)
            item['feedback']={'rating':rating,'note':note or '','at':datetime.now(timezone.utc).isoformat()}; self.put_query(item); return item
        with self.lock:
            d=self._local()
            for item in d['queries']:
                if item.get('query_id')==query_id:
                    item['feedback']={'rating':rating,'note':note or '','at':datetime.now(timezone.utc).isoformat()}; self._save_local(d); return item
        raise KeyError(query_id)
    def recent_queries(self,limit=50):
        if self._ddb: return self._ddb_rows('QUERY',min(max(limit,1),500))
        rows=self._local()['queries']; return list(reversed(rows[-limit:]))
    def similar_successes(self,question,market,limit=3):
        scored=[]
        for x in self.recent_queries(200):
            if x.get('market')!=market or x.get('status')!='success' or (x.get('feedback') or {}).get('rating')!='up': continue
            score=similarity(question,x.get('question',''))
            if score>=.18: scored.append((score,x))
        scored.sort(key=lambda z:z[0],reverse=True); return [{**x,'match_score':round(score,3)} for score,x in scored[:limit]]
    def put_evaluation(self,item):
        item=dict(item); item.setdefault('created_at',datetime.now(timezone.utc).isoformat())
        if self._ddb:
            self._ddb.put_item(Item={'pk':'EVAL','sk':f"{item['created_at']}#{item['run_id']}",'payload':json.dumps(item,ensure_ascii=False),'created_at':item['created_at']}); return
        with self.lock:
            d=self._local(); d['evaluations'].append(item); d['evaluations']=d['evaluations'][-100:]; self._save_local(d)
    def recent_evaluations(self,limit=20):
        if self._ddb: return self._ddb_rows('EVAL',min(max(limit,1),200))
        return list(reversed(self._local()['evaluations'][-limit:]))
