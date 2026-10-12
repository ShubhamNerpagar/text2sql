"""Phase5 acceptance: jobs, atomic leases, safe federation, bench and enforcement."""
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service
from app.services.phase5_service import Phase5Service
from app.services.phase5_jobs import JobStore
from app.workers.phase5_worker import process_one

c=TestClient(app)
W='p5-'+uuid4().hex[:8]
O='p5-out-'+uuid4().hex[:8]
THIRD='p5-third-'+uuid4().hex[:8]
ADMIN={'X-User':'author','X-Roles':'semantic_admin'}
REVIEWER={'X-User':'reviewer','X-Roles':'semantic_admin'}
ANALYST={'X-User':'analyst','X-Roles':'analyst'}
def u(path,workspace=W):return '/api/phase5/'+path+('?' if '?' not in path else '&')+'workspace='+workspace
def post(path,data=None,workspace=W,headers=ADMIN):return c.post(u(path,workspace),json=data or {},headers=headers)

@pytest.fixture(scope='module')
def prepared():
    for w,table in [(W,'Orders'),(O,'Customer'),(THIRD,'Store')]:
        sc={'scope_id':w+'-scope','workspace_id':w,'source_id':'contoso','tables':[{'database':'contoso_demo','table':table}]}
        ScopeService().save(sc);ScopeService().build(sc['scope_id'])
    p2=Phase2Service();a=p2.assets(W)[0]
    p2.profile(W,a['asset_id'],'standard','author',200)
    p2.save_contract(W,a['asset_id'],{'owner':'retail steward'},'author')
    p2.transition_contract(W,a['asset_id'],'reviewed','Meaning checked','author')
    p2.transition_contract(W,a['asset_id'],'certified','Metadata examined','author')
    p3=Phase3Service();obj=p3.create(W,{'kind':'entity','label':'Orders',
       'description':'Business order entity, without raw values',
       'binding':{'asset_id':a['asset_id'],'columns':['OrderKey']}},'author')
    obj=p3.transition(W,obj['object_id'],'reviewed','Verified grain','author',obj['version'])
    obj=p3.transition(W,obj['object_id'],'certified','Independently reviewed','reviewer',obj['version'])
    p3.publish_snapshot(W,'p5-base','Initial certified ontology','reviewer')
    release=Phase4Service().promote(W,'p5-base','author')
    return {'w':W,'other':O,'asset':a,'obj':obj,'release':release['release_id'],'p2':p2}

def test_status_and_guard(prepared):
    assert c.get('/api/health').json()['version']=='8.5.0'
    assert c.get(u('overview'),headers=ADMIN).json()['worker_backend']=='sqlite_single_host'
    assert c.get(u('overview'),headers=ANALYST).status_code==403
    assert c.get(u('overview',O),headers=ADMIN).status_code==200
    assert c.get(u('jobs/nope',O),headers=ADMIN).status_code==404

def test_queued_job_runs_worker_and_idempotent(prepared):
    b={'task':'search_snapshot','idempotency_key':'index-p5-v1'}
    first=post('jobs',b)
    assert first.status_code==200,first.text
    jid=first.json()['id']
    assert post('jobs',b).json()['id']==jid
    assert post('jobs',{'task':'profile','payload':{'asset_id':prepared['asset']['asset_id'],'tier':'standard'},'idempotency_key':'index-p5-v1'}).status_code==400
    assert c.get(u('jobs/'+jid,O),headers=ADMIN).status_code==404
    run=process_one(Phase5Service(),'test-runner-'+uuid4().hex[:8])
    assert run['id']==jid and run['status']=='succeeded'
    result=c.get(u('jobs/'+jid),headers=ADMIN).json()
    assert result['job']['result']['local_assets']==1
    assert any(e['event']=='succeeded' for e in result['events'])

def test_lease_contention_and_reclaim(prepared,tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3')
    jid=store.enqueue(W,'search_snapshot',{},'author')['id']
    def get_claim(i):return store.claim('w'+str(i),30)
    with ThreadPoolExecutor(max_workers=8) as pool: wins=list(pool.map(get_claim,range(8)))
    winners=[x for x in wins if x]
    assert len(winners)==1 and winners[0]['id']==jid
    j=winners[0]
    assert not store.heartbeat(jid,'wrong',j['attempts'])
    assert store.heartbeat(jid,j['owner'],j['attempts'],30)
    assert store.finish(jid,j['owner'],j['attempts'],{'ok':True})['status']=='succeeded'
    with pytest.raises(ValueError):store.finish(jid,j['owner'],j['attempts'],{'ok':False})
    expired=store.enqueue(W,'search_snapshot',{},'author',max_attempts=2)
    a=store.claim('stale',10)
    with sqlite3.connect(store.path) as db:db.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(a['id'],))
    b=store.claim('recovery',10)
    assert b['attempts']==2 and b['id']==expired['id']
    with pytest.raises(ValueError):store.finish(a['id'],'stale',1,{'illegal':True})
    assert store.finish(b['id'],'recovery',2,{'ok':True})['status']=='succeeded'

def test_cancel_retry_dead_letter(prepared,tmp_path):
    s=JobStore(tmp_path/'jobs.sqlite3')
    x=s.enqueue(W,'search_snapshot',{},'author',max_attempts=1)
    run=s.claim('w',20)
    assert s.cancel(W,x['id'],'admin')['cancel_requested']
    assert s.finish(x['id'],'w',run['attempts'],{'success':True})['status']=='cancelled'
    again=s.retry(W,x['id'],'admin');assert again['status']=='queued'
    a=s.claim('w',20)
    assert s.finish(x['id'],'w',a['attempts'],error='synthetic fault')['status']=='dead'
    assert s.retry(W,x['id'],'admin')['status']=='queued'

def test_domain_publication_grants_and_revocation(prepared):
    b={'domain_id':'retail_orders','label':'Retail Orders','description':'Certified retail metrics', 'release_id':prepared['release']}
    x=post('domains',b)
    assert x.status_code==200,x.text
    assert not c.get(u('federation',O),headers=ADMIN).json()['domains']
    d=post('domains/retail_orders/publish',{'expected_version':x.json()['version']})
    assert d.status_code==200,d.text
    assert not c.get(u('federation',O),headers=ADMIN).json()['domains']
    assert post('domains/retail_orders/grant',{'target_workspace':O,'expected_version':d.json()['version']}).status_code==200
    z=c.get(u('federation',O),headers=ADMIN).json()['domains']
    assert len(z)==1 and z[0]['count']==1
    assert not c.get(u('federation',THIRD),headers=ADMIN).json()['domains']
    assert set(z[0]['objects'][0])=={'object_id','kind','label','description'}
    found=c.get(u('search?q=Orders',O),headers=ADMIN).json()
    assert found['results'][0]['source']=='federated'
    assert all('binding' not in str(x) for x in found['results'])
    fresh=Phase5Service()._domain(W,'retail_orders')
    assert post('domains/retail_orders/grant',{'target_workspace':O,'allow':False,'expected_version':fresh['version']}).status_code==200
    assert not c.get(u('federation',O),headers=ADMIN).json()['domains']
    again=Phase5Service()._domain(W,'retail_orders')
    assert post('domains/retail_orders/revoke',{'expected_version':again['version']}).status_code==200
    assert not c.get(u('federation'),headers=ADMIN).json()['domains']

def test_offline_connector_benchmark_and_job_checks(prepared):
    assert post('jobs',{'task':'run_sql','payload':{'sql':'DROP TABLE Orders'}}).status_code==400
    assert post('jobs',{'task':'connector_benchmark','payload':{'source_id':'athena'}}).status_code==400
    assert post('jobs',{'task':'profile','payload':{'tier':'deep','asset_id':'not-owned'}}).status_code==404
    b=post('jobs',{'task':'connector_benchmark','payload':{'source_id':'contoso'}})
    assert b.status_code==200,b.text
    result=process_one(Phase5Service(),'bench-'+uuid4().hex[:6])
    assert result['id']==b.json()['id'] and result['status']=='succeeded',result
    bench=result['result']
    assert bench['status']=='passed' and bench['table_count']==1
    assert bench['tables'][0]['source_count']==10000
    assert not bench['cross_connector_equivalence_verified']
    assert c.get(u('benchmarks'),headers=ADMIN).json()['runs']

def test_certification_drift_invalidates_federation(prepared):
    x=post('domains',{'domain_id':'drift_test','label':'Drift Checks','release_id':prepared['release']})
    d=post('domains/drift_test/publish',{'expected_version':x.json()['version']})
    assert d.status_code==200
    grant=post('domains/drift_test/grant',{'expected_version':d.json()['version'],'target_workspace':O})
    assert grant.status_code==200
    assert any(q['domain_id']=='drift_test' for q in c.get(u('federation',O),headers=ADMIN).json()['domains'])
    prepared['p2'].transition_contract(W,prepared['asset']['asset_id'],'draft','Evidence needs refresh','author')
    assert not any(q['domain_id']=='drift_test' for q in c.get(u('federation',O),headers=ADMIN).json()['domains'])
