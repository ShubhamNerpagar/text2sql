"""Deterministic in-memory DynamoDB contract test; NOT a live AWS acceptance test."""
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from botocore.exceptions import ClientError
from app.services.phase5_dynamo_jobs import DynamoJobStore

def conflict():
    return ClientError({'Error':{'Code':'ConditionalCheckFailedException','Message':'conflict'}},'PutItem')

class Table:
    def __init__(self):self.d={};self.lock=RLock()
    def put_item(self,Item,ConditionExpression,ExpressionAttributeValues=None):
        key=(Item['pk'],Item['sk'])
        with self.lock:
            prior=self.d.get(key)
            if ConditionExpression=='attribute_not_exists(pk)' and prior is not None:raise conflict()
            if ConditionExpression=='version = :v' and (not prior or prior['version']!=ExpressionAttributeValues[':v']):raise conflict()
            self.d[key]=dict(Item)
    def get_item(self,Key,ConsistentRead=False):
        with self.lock:
            found=self.d.get((Key['pk'],Key['sk']))
            return {'Item':dict(found)} if found else {}
    def query(self,KeyConditionExpression,Limit,ConsistentRead,ExclusiveStartKey=None):
        # Tests use a single partition and workspace; production boto3 enforces Key() filters.
        with self.lock:rows=[dict(x) for x in self.d.values() if x['pk']=='P5_JOB']
        return {'Items':rows[:Limit]}

def test_dynamo_simulated_contention_and_idempotency():
    s=DynamoJobStore(Table());w='dynamo-test'
    j=s.enqueue(w,'search_snapshot',{},'owner','idempotent-key')
    assert j['id']==s.enqueue(w,'search_snapshot',{},'owner','idempotent-key')['id']
    with ThreadPoolExecutor(max_workers=12) as pool:
        claimed=list(pool.map(lambda x:s.claim('worker-'+str(x),30),range(12)))
    winners=[x for x in claimed if x]
    assert len(winners)==1,winners
    x=winners[0]
    assert s.heartbeat(x['id'],x['owner'],1,30,workspace=w)
    assert s.finish(x['id'],x['owner'],1,result={'ok':True},workspace=w)['status']=='succeeded'
    assert s.summary(w)['succeeded']==1
    assert s.events(w,x['id'])[-1]['event']=='succeeded'

def test_dynamo_simulated_dead_letter_cancel_requeue():
    s=DynamoJobStore(Table());w='dynamo-ops'
    x=s.enqueue(w,'search_snapshot',{},'owner',max_attempts=1)
    run=s.claim('worker',30)
    assert s.cancel(w,x['id'],'owner')['cancel_requested']
    assert s.finish(x['id'],'worker',1,result={'ok':True},workspace=w)['status']=='cancelled'
    assert s.retry(w,x['id'],'owner')['status']=='queued'
    run=s.claim('worker',30)
    assert s.finish(x['id'],'worker',1,error='error',workspace=w)['status']=='dead'
