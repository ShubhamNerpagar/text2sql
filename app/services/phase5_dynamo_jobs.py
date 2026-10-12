"""Optional multi-host DynamoDB job broker with conditional CAS leases.

Opt in with APP_MODE=aws, LEARNING_TABLE, PHASE5_QUEUE_BACKEND=dynamodb.
Requires a DynamoDB table with pk (partition key) and sk (sort key), both strings.
No GSI required. The queue scans only its P5_JOB partition (bounded pagination).
IAM principal needs dynamodb:{Query,GetItem,PutItem} on that table.
"""
from __future__ import annotations
import hashlib,json,time
from uuid import uuid4
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from app.config import get_settings
from app.services.phase5_jobs import TYPES,TERMINAL,iso

class DynamoJobStore:
    backend='dynamodb_multi_host'
    def __init__(self,table=None):
        s=get_settings()
        if table is not None:self.table=table
        else:
            if not s.is_aws or not s.learning_table:raise ValueError('DynamoDB worker queue needs APP_MODE=aws and LEARNING_TABLE')
            import boto3
            self.table=boto3.resource('dynamodb',region_name=s.aws_region).Table(s.learning_table)
    @staticmethod
    def _sk(w,jid):return w+'::'+jid
    @staticmethod
    def _item(job):
        # Large sample/profile payloads are not safe DynamoDB single-item writes.
        raw=json.dumps(job,default=str,ensure_ascii=False)
        if len(raw.encode('utf-8'))>300000:
            job={**job,'result':{'truncated':True,'message':'Detailed output too large for DynamoDB; inspect the downstream profile/evaluation registry.'}}
        return {'pk':'P5_JOB','sk':job['workspace']+'::'+job['id'],
                'version':job['version'],'document':json.dumps(job,default=str,ensure_ascii=False)}
    @staticmethod
    def _decode(item):return json.loads(item['document']) if item else None
    @staticmethod
    def _conflict(exc):return isinstance(exc,ClientError) and exc.response.get('Error',{}).get('Code')=='ConditionalCheckFailedException'
    @staticmethod
    def _event(j,level,event,details=None):
        j.setdefault('events',[]).append({'at':iso(),'level':level,'event':event,'detail':details or {}})
        j['events']=j['events'][-100:]
    def _new(self,j):
        self.table.put_item(Item=self._item(j),ConditionExpression='attribute_not_exists(pk)')
        return j
    def _cas(self,j,change):
        new=dict(j);new['events']=[dict(x) for x in j.get('events',[])]
        change(new);new['version']=j['version']+1;new['updated_at']=iso()
        try:self.table.put_item(Item=self._item(new),ConditionExpression='version = :v',
                 ExpressionAttributeValues={':v':j['version']})
        except ClientError as e:
            if self._conflict(e):return None
            raise
        return new
    def _query(self,prefix=None,limit=10000):
        cond=Key('pk').eq('P5_JOB')
        if prefix is not None:cond=cond & Key('sk').begins_with(prefix)
        out=[];next_key=None
        while len(out)<limit:
            kw={'KeyConditionExpression':cond,'Limit':min(250,limit-len(out)),'ConsistentRead':True}
            if next_key:kw['ExclusiveStartKey']=next_key
            r=self.table.query(**kw);out.extend(self._decode(x) for x in r.get('Items',[]))
            next_key=r.get('LastEvaluatedKey')
            if not next_key:break
        return out
    def enqueue(self,workspace,task,payload,actor,idem=None,priority=0,max_attempts=3):
        if task not in TYPES:raise ValueError('Job type not allowlisted')
        if not isinstance(payload,dict):raise ValueError('Job payload must be an object')
        if not 1<=max_attempts<=5 or not -5<=priority<=5:raise ValueError('Invalid retry/priority policy')
        if idem is not None and not 4<=len(idem)<=100:raise ValueError('Idempotency key must be 4–100 chars')
        jid=hashlib.sha256((workspace+'\x00'+idem).encode()).hexdigest()[:32] if idem else uuid4().hex
        now=iso();j={'id':jid,'workspace':workspace,'task':task,'payload':payload,'status':'queued',
            'priority':priority,'attempts':0,'max_attempts':max_attempts,'owner':None,'lease_until':None,
            'available_at':time.time(),'cancel_requested':False,'idem':idem,'created_at':now,'updated_at':now,
            'result':None,'error':None,'events':[],'version':1}
        self._event(j,'info','queued',{'actor':actor,'task':task})
        try:return self._new(j)
        except ClientError as e:
            if not self._conflict(e):raise
            prev=self.get(workspace,jid)
            if prev['task']!=task or prev['payload']!=payload:raise ValueError('Idempotency key reused with a different payload')
            return prev
    def get(self,w,jid):
        item=self.table.get_item(Key={'pk':'P5_JOB','sk':self._sk(w,jid)},ConsistentRead=True).get('Item')
        if not item:raise KeyError('Job not found in workspace')
        return self._decode(item)
    def list(self,w,limit=50,status=None):
        items=self._query(w+'::')
        if status:items=[j for j in items if j['status']==status]
        return sorted(items,key=lambda x:x['created_at'],reverse=True)[:limit]
    def events(self,w,jid,limit=100):return self.get(w,jid).get('events',[])[-limit:]
    def claim(self,worker,lease_seconds=90):
        if not 10<=lease_seconds<=1800:raise ValueError('Lease must be 10–1800 seconds')
        current=time.time()
        candidates=[j for j in self._query() if
            (j['status'] in ('queued','retry') and j['available_at']<=current) or
            (j['status']=='running' and (j['lease_until'] or 0)<=current)]
        for row in sorted(candidates,key=lambda x:(-x['priority'],x['available_at'],x['created_at'])):
            def take(j):
                if j['cancel_requested']:
                    j.update(status='cancelled',owner=None,lease_until=None)
                    self._event(j,'warn','cancelled_before_claim')
                elif j['attempts']>=j['max_attempts']:
                    j.update(status='dead',owner=None,lease_until=None,error='Lease expired after final attempt')
                    self._event(j,'error','dead_after_lease')
                else:
                    j.update(status='running',attempts=j['attempts']+1,owner=worker,lease_until=current+lease_seconds)
                    self._event(j,'info','claimed',{'worker':worker,'attempt':j['attempts']})
            winner=self._cas(row,take)
            if winner and winner['status']=='running':return winner
        return None
    def heartbeat(self,job,worker,attempt,lease_seconds=90,workspace=None):
        # Lease token is (owner,attempt,version); stale workers can't extend it.
        for _ in range(2):
            try:row=self._get_by_id(job,workspace)
            except KeyError:return False
            if row['status']!='running' or row['owner']!=worker or row['attempts']!=attempt or (row['lease_until'] or 0)<time.time():return False
            n=self._cas(row,lambda j:j.update(lease_until=time.time()+lease_seconds))
            if n:return True
        return False
    def _get_by_id(self,jid,workspace=None):
        if workspace:return self.get(workspace,jid)
        # Full job ID lookup requires partition query; bounded and index-free.
        for r in self._query():
            if r['id']==jid:return r
        raise KeyError('Job not found')
    def finish(self,job,worker,attempt,result=None,error=None,workspace=None):
        for _ in range(3):
            row=self._get_by_id(job,workspace)
            if row['status']!='running' or row['owner']!=worker or row['attempts']!=attempt or (row['lease_until'] or 0)<time.time():
                raise ValueError('Worker does not own a live job lease')
            def done(j):
                if j['cancel_requested']:status='cancelled';event='cancelled'
                elif error:status='retry' if attempt<j['max_attempts'] else 'dead';event='retry_scheduled' if status=='retry' else 'dead'
                else:status='succeeded';event='succeeded'
                j.update(status=status,owner=None,lease_until=None,
                  available_at=time.time()+min(300,2**attempt) if status=='retry' else time.time(),
                  error=str(error)[:500] if error else None,
                  result=result if status=='succeeded' else None)
                self._event(j,'error' if error else 'info',event,{'attempt':attempt,'error':str(error)[:250] if error else ''})
            finished=self._cas(row,done)
            if finished:return finished
        raise ValueError('Job CAS contention; retry completion')
    def cancel(self,w,jid,actor):
        for _ in range(3):
            j=self.get(w,jid)
            if j['status'] in TERMINAL:return j
            def cancel_job(x):
                if x['status']=='running':x['cancel_requested']=True
                else:x['status']='cancelled'
                self._event(x,'warn','cancel_requested',{'actor':actor})
            changed=self._cas(j,cancel_job)
            if changed:return changed
        raise ValueError('Concurrent cancellation conflict')
    def retry(self,w,jid,actor):
        for _ in range(3):
            j=self.get(w,jid)
            if j['status'] not in {'dead','cancelled'}:raise ValueError('Only dead/cancelled jobs may be retried')
            def retry_job(x):
                x.update(status='queued',attempts=0,owner=None,cancel_requested=False,lease_until=None,
                         available_at=time.time(),error=None,result=None)
                self._event(x,'info','requeued',{'actor':actor})
            changed=self._cas(j,retry_job)
            if changed:return changed
        raise ValueError('Concurrent retry conflict')
    def summary(self,w):
        totals={}
        for j in self._query(w+'::'):totals[j['status']]=totals.get(j['status'],0)+1
        return totals
