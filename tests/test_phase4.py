"""Phase4 acceptance: LLM planning, explicitly enabled synthetic execution, releases, trust drift,
branches, golden/fuzz/mutation, agent tools, cross-workspace isolation.
"""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service

client=TestClient(app)
W='p4-'+uuid4().hex[:10]
O='p4-out-'+uuid4().hex[:10]
ADMIN={'X-Roles':'semantic_admin','X-User':'creator'}
STEWARD={'X-Roles':'semantic_admin','X-User':'reviewer'}
ANALYST={'X-Roles':'analyst','X-User':'analyst'}

def u(endpoint):return f'/api/phase4/{endpoint}{"&" if "?" in endpoint else "?"}workspace={W}'
def post(endpoint,data,actor=ADMIN):return client.post(u(endpoint),json=data,headers=actor)

@pytest.fixture(scope='module')
def release():
    for w,tables in [(W,['Orders','Customer','OrderRows']),(O,['Store'])]:
        sc={'scope_id':w+'-scope','workspace_id':w,'source_id':'contoso','tables':[
            {'database':'contoso_demo','table':t} for t in tables]}
        ScopeService().save(sc);ScopeService().build(sc['scope_id'])
    p2=Phase2Service();asset=next(a for a in p2.assets(W) if a['table']=='Orders')
    p2.profile(W,asset['asset_id'],'standard','creator',200)
    p2.save_contract(W,asset['asset_id'],{'owner':'retail steward'},'creator')
    p2.transition_contract(W,asset['asset_id'],'reviewed','Physical meaning checked','creator')
    p2.transition_contract(W,asset['asset_id'],'certified','Aggregate profile and ownership confirmed','creator')
    p3=Phase3Service();obj=p3.create(W,{'kind':'entity','label':'Orders',
        'description':'Business orders, grain one order',
        'binding':{'asset_id':asset['asset_id'],'columns':['OrderKey']}},'creator')
    obj=p3.transition(W,obj['object_id'],'reviewed','Business grain verified','creator',obj['version'])
    obj=p3.transition(W,obj['object_id'],'certified','Independent semantic certification','reviewer',obj['version'])
    metric=p3.create(W,{'kind':'measure','object_id':'order_count','label':'Order count','description':'One order per primary key',
        'binding':{'asset_id':asset['asset_id'],'columns':['OrderKey']},
        'semantics':{'grain':['OrderKey'],'aggregation':'count','unit':'records','additivity':'additive'}},'creator')
    metric=p3.transition(W,metric['object_id'],'reviewed','Count definition reviewed','creator',metric['version'])
    p3.transition(W,metric['object_id'],'certified','Independent count certification','reviewer',metric['version'])
    p3.publish_snapshot(W,'v1','Approved semantic baseline','reviewer')
    promoted=post('releases/promote',{'version':'v1'})
    assert promoted.status_code==200,promoted.text
    return {'release_id':promoted.json()['release_id'],'object_id':obj['object_id'],'asset':asset,'p2':p2,'p3':p3,'metric_id':'order_count'}

@pytest.fixture(autouse=True)
def provider_contract(release,bedrock_contract):
    bedrock_contract.plan={'base_asset_id':release['asset']['asset_id'],'metrics':[{'metric_id':'order_count','alias':'value'}],
        'dimensions':[],'concept_ids':[],'join_relationship_ids':[],'filters':[],'having':[],'order_by':[],'limit':50}
    return bedrock_contract

def test_p4_packaging_and_permissions(release):
    assert client.get('/api/health').json()['version']=='8.4.0'
    d=client.get(u('overview'),headers=ADMIN)
    assert d.status_code==200 and d.json()['eligible']==2
    assert client.get(u('releases'),headers=ANALYST).status_code==403
    assert client.get(f'/api/phase4/overview?workspace={O}',headers=ADMIN).json()['eligible']==0
    assert client.get(u('overview?release_id=p3-nonexistent'),headers=ADMIN).status_code==404
    assert post('releases/promote',{'version':'v1'}).status_code==400

def test_p4_grounded_planning_and_execution(release):
    r=release['release_id']
    for question in ('Count Orders','How many orders?'):
        d=post('plan',{'release_id':r,'question':question})
        assert d.status_code==200,d.text
        p=d.json()['plan']
        assert 'COUNT(*)' in p['sql'] and p['metric_ids']==['order_count']
        assert p['policy']['grain_checked'] and p['policy']['metric_definitions_enforced']
    result=post('ask',{'release_id':r,'question':'Count Orders','execute':True})
    assert result.status_code==200,result.text
    assert result.json()['result']['rows']==[{'value':10000}] and result.json()['executed']
    assert result.json()['evidence']['plan_digest'] and result.json()['semantic_review']['passed']
    widget=post('bi',{'release_id':r,'question':'Count Orders','execute':True})
    assert widget.status_code==200 and widget.json()['result']['rows']==[{'value':10000}]
    preview=post('ask',{'release_id':r,'question':'count Orders'})
    assert preview.status_code==200 and preview.json()['result'] is None


def test_p4_fail_closed_for_untrusted_sql_and_nonmatching_concepts(release,provider_contract):
    r=release['release_id'];obj=release['object_id']
    provider_contract.clarification='Choose a supported approved metric.'
    for q in ('Delete from Orders','ZZZ completely unknown token','sum Orders','average Orders'):
        x=post('plan',{'release_id':r,'question':q})
        assert x.status_code==200 and x.json()['status']=='needs_clarification' and not x.json()['executed'],(q,x.text)
    assert post('plan',{'release_id':r,'question':'Count Orders','object_id':'untrusted'}).status_code==400
    assert post('plan',{'release_id':'p3-false','question':'Count Orders'}).status_code==404
    x=post('plan',{'release_id':r,'question':'Count Orders','object_id':obj},ANALYST)
    assert x.status_code==403
    assert client.get(u('retrieve?release_id='+r+'&question=Count%20Orders'),headers=ADMIN).json()['hits'][0]['object_id']=='order_count'

def test_p4_business_result_benchmark_catches_wrong_semantics(release):
    r=release['release_id'];asset=release['asset']['asset_id']
    # Old object-only tests cannot claim result accuracy.
    assert post('golden/cases',{'release_id':r,'question':'Count Orders','object_id':release['object_id'],'expected':'allow'}).status_code==400
    assert post('golden/cases',{'release_id':r,'question':'Count Orders','expected':'allow','reference_asset_id':asset,'reference_sql':'SELECT COUNT(*) AS value FROM contoso_demo.Orders'}).status_code==200
    assert post('golden/cases',{'release_id':r,'question':'strange unknown business object','expected':'reject'}).status_code==200
    result=post('golden/run',{'release_id':r,'mutations':True})
    assert result.status_code==200,result.text
    row=result.json()
    assert row['counts']=={'passed':1,'failed':1,'blocked':0}  # The mocked planner incorrectly answers the unknown concept.
    assert row['method']=='llm_answers_vs_independent_reference_sql'
    assert client.get(u('golden/runs'),headers=ADMIN).json()['runs']


def test_p4_ontology_impact_and_agent(release):
    r=release['release_id'];obj=release['object_id']
    impact=client.get(u('impact?release_id='+r+'&object_id='+obj),headers=ADMIN)
    assert impact.status_code==200 and impact.json()['affected_count']==0
    tools=client.get(u('agent/tools'),headers=ADMIN).json()
    assert not tools['write_tools_enabled'] and len(tools['tools'])>=4
    executed=post('agent/call',{'release_id':r,'tool':'ontology.ask','arguments':{'question':'Count Orders','execute':True}})
    assert executed.status_code==200 and executed.json()['rows']==[{'value':10000}]
    assert post('agent/call',{'release_id':r,'tool':'os.execute','arguments':{'cmd':'rm -rf /'}}).status_code==400
    assert post('agent/call',{'release_id':r,'tool':'ontology.plan','arguments':{'question':'Count Orders'}},ANALYST).status_code==403

def test_p4_branch_review_and_immutable_release(release):
    r=release['release_id'];obj=release['object_id']
    assert post('branches',{'release_id':r,'branch_id':'retail-update'}).status_code==200
    bad=post('branches/retail-update/patch',{'object_id':obj,'field':'binding','value':'arbitrary','expected_version':1})
    assert bad.status_code==400
    patch=post('branches/retail-update/patch',{'object_id':obj,'field':'description','value':'Review-ready order grain','expected_version':1})
    assert patch.status_code==200 and patch.json()['version']==2
    comp=client.get(u('branches/retail-update/compare'),headers=ADMIN).json()
    assert comp['changes'][0]['changes']['description']['after']=='Review-ready order grain'
    assert post('branches/retail-update/review',{'decision':'approved','note':'Approved documentation update','expected_version':2}).status_code==400
    ok=post('branches/retail-update/review',{'decision':'approved','note':'Approved independent semantic documentation update','expected_version':2},STEWARD)
    assert ok.status_code==200 and ok.json()['status']=='approved'
    pub=post('branches/retail-update/publish',{'release_id':'release-2'})
    assert pub.status_code==200 and pub.json()['branch_id']=='retail-update'
    assert post('branches/retail-update/publish',{'release_id':'release-2'}).status_code==400
    query=post('ask',{'release_id':'release-2','question':'Count Orders','execute':True})
    assert query.status_code==200 and query.json()['result']['rows']==[{'value':10000}]

def test_p4_stale_evidence_blocks_all_query_consumers(release):
    r=release['release_id'];aid=release['asset']['asset_id']
    release['p2'].transition_contract(W,aid,'draft','Contract renewal requires re-evaluation','creator')
    overview=client.get(u('overview?release_id='+r),headers=ADMIN).json()
    assert overview['eligible']==0 and overview['blocked'][0]['code']=='EVIDENCE_EXPIRED'
    for path in ('ask','plan','bi'):
        result=post(path,{'release_id':r,'question':'Count Orders','execute':True})
        assert result.status_code==400,(path,result.text)
    assert post('golden/run',{'release_id':r}).status_code==200  # regression suite must fail closed, not bypass trust
    assert post('branches',{'release_id':r,'branch_id':'unsafe-branch'}).status_code==400
    assert post('agent/call',{'release_id':r,'tool':'ontology.ask','arguments':{'question':'Count Orders','execute':True}}).status_code==400
    # Restore the workspace so other acceptance tests remain independent.
    release['p2'].transition_contract(W,aid,'reviewed','New physical contract review completed','creator')
    release['p2'].transition_contract(W,aid,'certified','Renewed contract approved','creator')
    assert post('plan',{'release_id':r,'question':'Count Orders'}).status_code==200

def test_p4_mcp_jsonrpc_contract(release):
    r=client.post(u('mcp'),json={'jsonrpc':'2.0','id':1,'method':'initialize'},headers=ADMIN)
    assert r.status_code==200 and r.json()['result']['serverInfo']['version']=='8.4.0'
    tools=client.post(u('mcp'),json={'id':2,'method':'tools/list'},headers=ADMIN)
    assert len(tools.json()['result']['tools'])==4
    x=client.post(u('mcp'),json={'id':3,'method':'tools/call','params':{'name':'ontology.ask',
        'arguments':{'release_id':release['release_id'],'question':'Count Orders','execute':True}}},headers=ADMIN)
    assert x.status_code==200 and '10000' in x.json()['result']['content'][0]['text']
    assert client.post(u('mcp'),json={'id':3,'method':'tools/call','params':{'name':'os.execute',
        'arguments':{'release_id':release['release_id']}}},headers=ADMIN).status_code==400
    assert client.post(u('mcp'),json={'id':1,'method':'initialize'},headers=ANALYST).status_code==403
