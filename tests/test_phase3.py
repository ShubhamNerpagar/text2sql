"""Phase 3 acceptance: typed ontology, scope isolation, immutable evidence,
compiler trust gates, SME queue, 4 graph modes and safe releases.
"""
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service

client=TestClient(app)
WORKSPACE='p3-accept-'+uuid4().hex[:9]
ADMIN={'X-Roles':'semantic_admin','X-User':'phase3-creator'}
REVIEWER={'X-Roles':'semantic_admin','X-User':'independent-reviewer'}
ANALYST={'X-Roles':'analyst','X-User':'business-reader'}
OTHER='p3-other-'+uuid4().hex[:8]
def uri(path,workspace=WORKSPACE):return f'/api/phase3/{path}{"&" if "?" in path else "?"}workspace={workspace}'
def post(path,data,headers=ADMIN,workspace=WORKSPACE):return client.post(uri(path,workspace),json=data,headers=headers)

@pytest.fixture(scope='module')
def prepared():
    scope={'scope_id':WORKSPACE+'-scope','workspace_id':WORKSPACE,'source_id':'contoso','tables':[
        {'database':'contoso_demo','table':'Orders'}, {'database':'contoso_demo','table':'Customer'},
        {'database':'contoso_demo','table':'OrderRows'}]}
    ScopeService().save(scope);ScopeService().build(scope['scope_id'])
    ScopeService().save({'scope_id':OTHER+'-scope','workspace_id':OTHER,'source_id':'contoso','tables':[
        {'database':'contoso_demo','table':'Store'}]})
    ScopeService().build(OTHER+'-scope')
    p2=Phase2Service();assets={a['table']:a['asset_id'] for a in p2.assets(WORKSPACE)}
    return p2,assets

def test_p3_candidates_never_auto_certified(prepared):
    response=post('proposals?max_assets=3',{})
    assert response.status_code==200,response.text
    assert response.json()['created']>=5
    assert all(o['status']=='draft' for o in response.json()['objects'])
    again=post('proposals?max_assets=3',{})
    assert again.status_code==200 and again.json()['created']==0
    assert again.json()['skipped_existing']>=5
    overview=client.get(uri('overview'),headers=ADMIN).json()
    assert overview['assets']==3 and overview['by_status']['certified']==0
    assert overview['evidence_records']>=5 and overview['production_query_integration'] is False

def test_p3_scope_and_typed_binding(prepared):
    _,a=prepared
    rejected=post('objects',{'kind':'measure','label':'Invalid string measure',
        'binding':{'asset_id':a['Orders'],'columns':['OrderKey','OrderStatus']},'definition':'Invalid string sum','semantics':{'grain':['OrderKey'],'aggregation':'sum','expression':{'column':'OrderStatus'},'unit':'records','additivity':'additive'}})
    assert rejected.status_code==400
    outside=post('objects',{'kind':'entity','label':'Invalid cross workspace',
        'binding':{'asset_id':Phase2Service().assets(OTHER)[0]['asset_id'],'columns':['StoreKey']}})
    assert outside.status_code==404
    missing=post('objects',{'kind':'event','label':'Missing date','binding':{'asset_id':a['Orders'],'columns':['OrderKey']}})
    assert missing.status_code==400
    badcol=post('objects',{'kind':'entity','label':'Missing physical column',
        'binding':{'asset_id':a['Orders'],'columns':['not_a_column']}})
    assert badcol.status_code==400
    good=post('objects',{'kind':'event','label':'Order placed',
        'binding':{'asset_id':a['Orders'],'columns':['OrderDate']}})
    assert good.status_code==200,good.text
    assert good.json()['kind']=='event' and good.json()['status']=='draft'
    assert post('objects',{'kind':'business_concept','label':'An ungrounded concept'}).status_code==400
    assert client.get(uri('objects'),headers=ANALYST).status_code==403
    assert client.get(uri('overview',OTHER),headers=ADMIN).json()['objects']==0

def test_p3_compile_blocks_unsupported_and_has_actionable_questions(prepared):
    o=client.get(uri('objects'),headers=ADMIN).json()['objects'][0]
    d=client.get(uri('compile?object_id='+o['object_id']),headers=ADMIN)
    assert d.status_code==200,d.text
    assert d.json()['results'][0]['blocking']>=1
    assert d.json()['results'][0]['trust_state']=='blocked'
    q=client.get(uri('questions'),headers=ADMIN).json()['questions']
    assert q and all('diagnostic_code' in item for item in q)
    first=q[0]
    assert post('questions/'+first['question_id']+'/review',{'decision':'resolved','note':'Work item DATA-123 needs a contract'}).status_code==200
    same=client.get(uri('questions'),headers=ADMIN).json()['questions']
    assert next(x for x in same if x['question_id']==first['question_id'])['review_status']=='resolved'
    assert client.get(uri('compile?object_id='+o['object_id']),headers=ADMIN).json()['results'][0]['blocking']>=1

def test_p3_compiler_review_and_certify_requires_independent_reviewer(prepared):
    p2,assets=prepared;aid=assets['Orders']
    profile=p2.profile(WORKSPACE,aid,'standard','p3-test',max_columns=200)
    assert profile['status']=='complete' and profile['row_count']==10000
    contract=p2.save_contract(WORKSPACE,aid,{'owner':'retail-steward'},'p3-test')
    p2.transition_contract(WORKSPACE,aid,'reviewed','Physical schema reviewed','p3-test')
    p2.transition_contract(WORKSPACE,aid,'certified','Owner and measured profile verified','p3-test')
    candidate=next(x for x in client.get(uri('objects'),headers=ADMIN).json()['objects']
                   if x['kind']=='entity' and x['binding'].get('asset_id')==aid)
    oid=candidate['object_id'];v=candidate['version']
    assert post('objects/'+oid+'/review',{'decision':'certified','note':'Skipping review should fail','expected_version':v}).status_code==400
    reviewed=post('objects/'+oid+'/review',{'decision':'reviewed','note':'Verified source and field meaning','expected_version':v})
    assert reviewed.status_code==200,reviewed.text
    v=reviewed.json()['version']
    assert post('objects/'+oid+'/review',{'decision':'certified','note':'Self approval should fail','expected_version':v}).status_code==400
    assert post('objects/'+oid+'/review',{'decision':'certified','note':'Stale version should fail','expected_version':v-1},REVIEWER).status_code==400
    certified=post('objects/'+oid+'/review',{'decision':'certified','note':'Independent evidence certification','expected_version':v},REVIEWER)
    assert certified.status_code==200,certified.text
    assert certified.json()['status']=='certified'
    r=client.get(uri('compile?object_id='+oid),headers=ADMIN).json()['results'][0]
    assert r['trust_state']=='certified' and r['blocking']==0
    assert oid

def test_p3_versioned_release_and_immutability(prepared):
    objs=client.get(uri('objects'),headers=ADMIN).json()['objects']
    certified=next((o for o in objs if o['status']=='certified'),None)
    if not certified:
        # Test standalone under pytest ordering, or rerun test's prerequisites.
        test_p3_compiler_review_and_certify_requires_independent_reviewer(prepared)
    bad=post('releases',{'version':'v1','note':'Approved by independent reviewer'},ANALYST)
    assert bad.status_code==403
    r=post('releases',{'version':'v1','note':'First evidence-backed approval'})
    assert r.status_code==200,r.text
    assert r.json()['certified_count']>=1 and len(r.json()['content_digest'])==64
    assert r.json()['production_query_integration'] is False
    assert post('releases',{'version':'v1','note':'Overwrite existing version'}).status_code==400
    assert client.get(uri('releases'),headers=ADMIN).json()['releases'][0]['version']=='v1'
    oid=next(o['object_id'] for o in client.get(uri('objects'),headers=ADMIN).json()['objects'] if o['status']=='certified')
    assert client.put(uri('objects/'+oid),headers=ADMIN,json={'expected_version':2,'label':'Change locked semantic object'}).status_code==400


def test_p3_ledger_contains_versioned_provenance_and_no_raw_rows(prepared):
    entries=client.get(uri('evidence'),headers=ADMIN).json()['ledger']
    assert entries and all(len(x['source_digest'])==64 for x in entries)
    assert all(x['provenance']=='metadata_and_phase2_snapshots_no_row_samples' for x in entries)
    assert all('sample_rows' not in str(x) and 'raw_values' not in str(x) for x in entries)
    assert any(any(s['source_kind']=='aggregate_profile' for s in e['sources']) for e in entries)
    assert client.get(uri('audit'),headers=ADMIN).json()['events']


def test_p3_graph_four_modes_and_focus(prepared):
    for mode in ('conceptual','logical','evidence','dependency'):
        g=client.get(uri('graph?mode='+mode),headers=ADMIN)
        assert g.status_code==200,g.text
        assert g.json()['mode']==mode and len(g.json()['nodes'])>=1
    logical=client.get(uri('graph?mode=logical'),headers=ADMIN).json()
    assert any(n['kind']=='column' for n in logical['nodes'])
    evidence=client.get(uri('graph?mode=evidence'),headers=ADMIN).json()
    assert any(e['kind']=='SUPPORTED_BY' for e in evidence['edges'])
    oid=next(x['object_id'] for x in client.get(uri('objects'),headers=ADMIN).json()['objects'])
    focused=client.get(uri('graph?mode=dependency&focus='+oid),headers=ADMIN).json()
    assert oid in {n['id'] for n in focused['nodes']}
    assert client.get(uri('graph?mode=nonexistent'),headers=ADMIN).status_code==400
    assert client.get(uri('graph?mode=logical&limit=9999'),headers=ADMIN).status_code==400


def test_p3_restrict_cross_workspace_dependencies_and_cycle(prepared):
    aid=prepared[1]['Orders']
    first=post('objects',{'kind':'business_concept','label':'Orders domain concept',
        'binding':{'asset_id':aid}, 'description':'Business domain semantics'})
    assert first.status_code==200,first.text
    oid=first.json()['object_id']
    second=post('objects',{'kind':'business_concept','label':'Order service concept',
        'depends_on':[oid],'description':'Service depends on domain'})
    assert second.status_code==200,second.text
    sid=second.json()['object_id']
    v=first.json()['version']
    loop=client.put(uri('objects/'+oid),headers=ADMIN,json={'expected_version':v,'label':'Orders domain concept',
        'binding':{'asset_id':aid},'depends_on':[sid]})
    assert loop.status_code==400 and 'cycle' in loop.text.lower()
    other=post('objects',{'kind':'rule','label':'External rule','depends_on':[sid],
        'definition':'Some rule'},workspace=OTHER)
    assert other.status_code==404



def test_p3_cross_asset_join_requires_measured_approval(prepared):
    all_objects=client.get(uri('objects'),headers=ADMIN).json()['objects']
    orders=next(o for o in all_objects if o['kind']=='entity' and o['binding'].get('asset_id')==prepared[1]['Orders'])
    customer=next(o for o in all_objects if o['kind']=='entity' and o['binding'].get('asset_id')==prepared[1]['Customer'])
    created=post('objects',{'kind':'business_concept','label':'Customer order attribution',
        'depends_on':[orders['object_id'],customer['object_id']],
        'definition':'Orders attributed to customers only on verified CustomerKey'})
    assert created.status_code==200,created.text
    oid=created.json()['object_id']
    before=client.get(uri('compile?object_id='+oid),headers=ADMIN).json()['results'][0]
    assert 'UNVERIFIED_SEMANTIC_JOIN' in {e['code'] for e in before['diagnostics']}
    p2=prepared[0]
    rel=next(r for r in p2.relationships(WORKSPACE) if r['from_asset']==prepared[1]['Orders']
        and r['to_asset']==prepared[1]['Customer'] and r['from_column']=='CustomerKey')
    measured=p2.validate_relationship(WORKSPACE,rel['relationship_id'],'phase3-creator')
    assert measured['evidence']['passed'] is True
    approved=p2.review_relationship(WORKSPACE,rel['relationship_id'],'approved','Aggregate results and key uniqueness checked','independent-reviewer')
    assert approved['trusted_for_queries'] is True
    after=client.get(uri('compile?object_id='+oid),headers=ADMIN).json()['results'][0]
    assert 'UNVERIFIED_SEMANTIC_JOIN' not in {e['code'] for e in after['diagnostics']}
    assert 'RELATIONSHIP_APPROVED' in {e['code'] for e in after['diagnostics']}


def test_p3_dependency_invalidation_after_approval(prepared):
    objs=client.get(uri('objects'),headers=ADMIN).json()['objects']
    target=next(o for o in objs if o['status']=='certified')
    aid=target['binding']['asset_id']
    # Certified snapshot remains immutable; live compiler must detect revoked Phase 2 contract.
    p2=Phase2Service();p2.transition_contract(WORKSPACE,aid,'draft','Change request','p3-test')
    compiled=client.get(uri('compile?object_id='+target['object_id']),headers=ADMIN).json()['results'][0]
    assert compiled['trust_state']=='blocked' and any(d['code']=='CONTRACT_NOT_CERTIFIED' for d in compiled['diagnostics'])
    assert post('releases',{'version':'v2','note':'Attempt releasing stale semantic trust'}).status_code==400
    assert client.get(uri('releases'),headers=ADMIN).json()['releases'][0]['version']=='v1'
