from __future__ import annotations
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from filelock import FileLock
from app.config import get_settings

_LOCAL_STORE_LOCK=RLock()
_LOCAL_STORE_CACHE={}

class ControlRepository:
    """Durable control-plane state.

    DynamoDB uses a single-table partition-per-kind pattern. Reads use Query rather than
    Scan so growth in unrelated item kinds does not degrade list operations.
    """
    KINDS=('CONVERSATION','BRANCH','ACTION','AUDIT','SUGGESTION','WORKSPACE','REPORT','REPORT_RUN','SCHEMA_DRIFT','SCOPE','MODEL_PROBE','MODEL_CONFIG','MODEL_DISCOVERY','P2_PROFILE','P2_CONTRACT','P2_RELATIONSHIP','P2_RULE','P2_RUN','P2_TRANSFORM','P2_AUDIT','P3_OBJECT','P3_EVIDENCE','P3_QUESTION','P3_RELEASE','P3_AUDIT','P4_RELEASE','P4_BRANCH','P4_CASE','P4_EVAL','P4_AUDIT','P5_DOMAIN','P5_BENCH','P5_INDEX')
    def __init__(self):
        self.s=get_settings(); self.lock=_LOCAL_STORE_LOCK; self.path=self.s.state_dir/'control-plane.json'; self._ddb=None
        self.process_lock=FileLock(str(self.path)+'.lock',timeout=30)
        if self.s.is_aws and self.s.learning_table:
            import boto3
            self._ddb=boto3.resource('dynamodb',region_name=self.s.aws_region).Table(self.s.learning_table)

    def _blank(self): return {k:{} for k in self.KINDS}
    def _local(self):
        if not self.path.exists(): return self._blank()
        try:
            stat=self.path.stat();signature=(stat.st_mtime_ns,stat.st_size)
            cached=_LOCAL_STORE_CACHE.get(str(self.path))
            if cached and cached[0]==signature:return cached[1]
            d=json.loads(self.path.read_text(encoding='utf-8'))
            for k in self.KINDS: d.setdefault(k,{})
            if len(_LOCAL_STORE_CACHE)>=4:_LOCAL_STORE_CACHE.clear()
            _LOCAL_STORE_CACHE[str(self.path)]=(signature,d)
            return d
        except Exception: return self._blank()
    def _save(self,d):
        # Thread and process locks serialize local writers. Replace avoids partial
        # JSON during crashes; multi-host deployments use DynamoDB.
        # A failed disk write must not leave uncommitted approvals in the read cache.
        _LOCAL_STORE_CACHE.pop(str(self.path),None)
        temp=self.path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding='utf-8')
        os.replace(temp,self.path)
        stat=self.path.stat()
        _LOCAL_STORE_CACHE[str(self.path)]=((stat.st_mtime_ns,stat.st_size),d)

    def put(self,kind:str,key:str,payload:dict)->dict:
        item=deepcopy(payload); item['updated_at']=datetime.now(timezone.utc).isoformat(); item.setdefault('created_at',item['updated_at'])
        if self._ddb:
            self._ddb.put_item(Item={'pk':kind,'sk':key,'payload':json.dumps(item,ensure_ascii=False),'created_at':item['created_at'],'updated_at':item['updated_at']}); return item
        with self.lock,self.process_lock:
            d=self._local(); d.setdefault(kind,{})[key]=item; self._save(d); return deepcopy(item)
    def get(self,kind:str,key:str)->dict|None:
        if self._ddb:
            x=self._ddb.get_item(Key={'pk':kind,'sk':key},ConsistentRead=True).get('Item'); return json.loads(x['payload']) if x else None
        with self.lock:return deepcopy(self._local().get(kind,{}).get(key))
    def list(self,kind:str,limit:int=200)->list[dict]:
        limit=min(max(int(limit),1),1000)
        if self._ddb:
            from boto3.dynamodb.conditions import Key
            items=[]; kwargs={'KeyConditionExpression':Key('pk').eq(kind),'Limit':min(limit,200),'ScanIndexForward':False,'ConsistentRead':True}
            while len(items)<limit:
                r=self._ddb.query(**kwargs); items.extend(r.get('Items',[]))
                lek=r.get('LastEvaluatedKey')
                if not lek: break
                kwargs['ExclusiveStartKey']=lek; kwargs['Limit']=min(limit-len(items),200)
            rows=[json.loads(x['payload']) for x in items]; rows.sort(key=lambda x:x.get('updated_at',''),reverse=True); return rows[:limit]
        with self.lock:
            rows=list(self._local().get(kind,{}).values()); rows.sort(key=lambda x:x.get('updated_at',''),reverse=True); return deepcopy(rows[:limit])
    def delete(self,kind:str,key:str):
        if self._ddb: self._ddb.delete_item(Key={'pk':kind,'sk':key}); return
        with self.lock,self.process_lock:
            d=self._local(); d.get(kind,{}).pop(key,None); self._save(d)
