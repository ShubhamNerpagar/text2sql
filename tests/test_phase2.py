"""Phase 2 acceptance: full local execution, guardrails, persistence and UI wiring."""
import re
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service

ADMIN={'X-Roles':'semantic_admin','X-User':'phase2-steward'}
ANALYST={'X-Roles':'analyst','X-User':'phase2-viewer'}
WORKSPACE='p2-acceptance'
client=TestClient(app)

@pytest.fixture(scope='module')
def demo():
    scope={'scope_id':'p2-acceptance-scope','workspace_id':WORKSPACE,
           'display_name':'Phase 2 Acceptance','source_id':'contoso','tables':[
               {'database':'contoso_demo','table':t} for t in ('Orders','Customer','Store','OrderRows','Product')]}
    ScopeService().save(scope)
    assert ScopeService().build(scope['scope_id'])['tables_scanned']==5
    svc=Phase2Service()
    assets={a['table']:a['asset_id'] for a in svc.assets(WORKSPACE)}
    return svc,assets

def url(route):return route+'?workspace='+WORKSPACE

def test_p2_overview_exact_selected_scope(demo):
    svc,assets=demo
    r=client.get(url('/api/phase2/overview'),headers=ADMIN)
    assert r.status_code==200,r.text
    assert {a['table'] for a in r.json()['assets']}==set(assets)
    assert r.json()['scope_id']=='p2-acceptance-scope'
    assert client.get('/api/phase2/overview?workspace=unknown-workspace',headers=ADMIN).status_code==400


def test_p2_metadata_does_not_scan_rows(demo):
    _,assets=demo
    with patch('app.services.phase2_service.DataSourceService.execute',side_effect=AssertionError('Should not read rows')):
        r=client.post(url('/api/phase2/profiles'),headers=ADMIN,json={'asset_id':assets['Orders'],'tier':'metadata'})
    assert r.status_code==200,r.text
    p=r.json();assert p['row_count'] is None and p['queries_executed']==0 and not p['measured']
    assert p['data_handling']=='aggregates_only_no_sample_rows'


def test_p2_standard_and_deep_real_full_aggregates(demo):
    _,assets=demo
    for tier in ('standard','deep'):
        r=client.post(url('/api/phase2/profiles'),headers=ADMIN,json={'asset_id':assets['Orders'],'tier':tier})
        assert r.status_code==200,r.text
        p=r.json()
        assert p['row_count']==10000 and p['status']=='complete' and p['queries_executed']>=2
        c=next(x for x in p['columns'] if x['name']=='OrderKey')
        assert c['null_count']==0 and c['distinct_count']==10000
        if tier=='deep':assert c['numeric_summary']['max_value']==10000
        assert all('rows' not in x and 'sample_values' not in x for x in p['columns'])
    assert client.post(url('/api/phase2/profiles'),headers=ADMIN,json={'asset_id':assets['Orders'],'tier':'nonsense'}).status_code==400
    assert client.post(url('/api/phase2/profiles'),headers=ANALYST,json={'asset_id':assets['Orders'],'tier':'standard'}).status_code==403


def test_p2_contract_workflow_and_concurrency(demo):
    _,assets=demo;aid=assets['Orders'];path=url('/api/phase2/contracts/'+aid)
    proposal=next(x for x in client.get(url('/api/phase2/contracts'),headers=ADMIN).json()['contracts'] if x['asset_id']==aid)
    assert proposal['status']=='suggested' and proposal['version']==0
    saved=client.post(path,headers=ADMIN,json={'owner':'data-team','description':'Validated retail orders','expected_version':0})
    assert saved.status_code==200,saved.text
    assert saved.json()['status']=='draft' and saved.json()['version']==1
    assert client.post(path,headers=ADMIN,json={'owner':'x','expected_version':0}).status_code==400
    assert client.post(url('/api/phase2/contracts/'+aid+'/review'),headers=ADMIN,json={'decision':'certified','note':'skip review'}).status_code==400
    r=client.post(url('/api/phase2/contracts/'+aid+'/review'),headers=ADMIN,json={'decision':'reviewed','note':'verified against physical schema'})
    assert r.status_code==200,r.text
    r=client.post(url('/api/phase2/contracts/'+aid+'/review'),headers=ADMIN,json={'decision':'certified','note':'measured profile and owner verified'})
    assert r.status_code==200,r.text
    assert r.json()['status']=='certified'
    assert client.post(path,headers=ADMIN,json={'owner':'another-team'}).json()['status']=='draft'


def test_p2_rejects_contract_renames_and_invalid_roles(demo):
    _,assets=demo;aid=assets['Customer']
    proposal=next(x for x in Phase2Service().contracts(WORKSPACE) if x['asset_id']==aid)
    cols=[dict(x) for x in proposal['columns']]
    cols[0]['name']='INJECTED'
    r=client.post(url('/api/phase2/contracts/'+aid),headers=ADMIN,json={'columns':cols})
    assert r.status_code==400
    cols=[dict(x) for x in proposal['columns']]
    cols[0]['role']='superuser'
    assert client.post(url('/api/phase2/contracts/'+aid),headers=ADMIN,json={'columns':cols}).status_code==400


def test_p2_relationship_is_untrusted_until_measured_and_approved(demo):
    _,assets=demo
    rs=client.get(url('/api/phase2/relationships'),headers=ADMIN).json()['relationships']
    rel=next(x for x in rs if x['from_asset']==assets['Orders'] and x['to_asset']==assets['Customer'] and x['from_column']=='CustomerKey')
    assert rel['status']=='suggested' and not rel['trusted_for_queries']
    rid=rel['relationship_id'];path=url('/api/phase2/relationships/'+rid)
    wrong=client.post('/api/phase2/relationships/'+rid+'/review?workspace='+WORKSPACE,headers=ADMIN,json={'decision':'approved','note':'no measurements yet'})
    assert wrong.status_code==404 or wrong.status_code==400
    measured=client.post('/api/phase2/relationships/'+rid+'/validate?workspace='+WORKSPACE,headers=ADMIN)
    assert measured.status_code==200,measured.text
    e=measured.json()['evidence']
    assert e['coverage']==1 and e['target_uniqueness']==1 and e['matched_distinct']==1000
    assert not measured.json()['trusted_for_queries']
    approved=client.post('/api/phase2/relationships/'+rid+'/review?workspace='+WORKSPACE,headers=ADMIN,json={'decision':'approved','note':'FK coverage verified and reviewed'})
    assert approved.status_code==200,approved.text
    assert approved.json()['trusted_for_queries']


def test_p2_quality_rule_activation_lifecycle(demo):
    _,assets=demo
    created=client.post(url('/api/phase2/quality/rules'),headers=ADMIN,json={
       'asset_id':assets['Store'],'rule_type':'not_null','column':'StoreKey'})
    assert created.status_code==200
    rid=created.json()['rule_id']
    route=url('/api/phase2/quality/rules/'+rid+'/status')
    assert client.post(route,headers=ADMIN,json={'decision':'disabled','note':''}).status_code==400
    disabled=client.post(route,headers=ADMIN,json={'decision':'disabled','note':'Maintenance window'})
    assert disabled.status_code==200 and disabled.json()['status']=='disabled'
    enabled=client.post(route,headers=ADMIN,json={'decision':'active','note':'Checks restored'})
    assert enabled.status_code==200 and enabled.json()['status']=='active'


def test_p2_quality_observations_fail_closed_and_remediation(demo):
    _,assets=demo
    mk='/api/phase2/quality/rules?workspace='+WORKSPACE
    passed=client.post(mk,headers=ADMIN,json={'asset_id':assets['Orders'],'rule_type':'not_null','column':'OrderKey','threshold':1})
    assert passed.status_code==200,passed.text
    failed=client.post(mk,headers=ADMIN,json={'asset_id':assets['Orders'],'rule_type':'row_count_min','threshold':10001})
    assert failed.status_code==200,failed.text
    r=client.post('/api/phase2/quality/run?workspace='+WORKSPACE,headers=ADMIN)
    assert r.status_code==200,r.text
    item=r.json();assert item['passed']>=1 and item['failed']>=1
    rid=item['run_id'];path='/api/phase2/quality/runs/'+rid
    wrong=client.post(path+'/review?workspace='+WORKSPACE,headers=ADMIN,json={'decision':'accepted','note':'looks fine'})
    assert wrong.status_code==400
    ruling=client.post(path+'/review?workspace='+WORKSPACE,headers=ADMIN,json={'decision':'needs_remediation','note':'Too few source rows'})
    assert ruling.status_code==200
    rem=client.post(path+'/remediate?workspace='+WORKSPACE,headers=ADMIN,json={'status':'in_progress','owner':'DWH','note':'Open issue DWH-101'})
    assert rem.status_code==200 and rem.json()['remediation_status']=='in_progress'
    assert client.post(path+'/remediate?workspace='+WORKSPACE,headers=ADMIN,json={'status':'resolved','note':'Not reviewed'}).status_code==400
    waived=client.post(path+'/review?workspace='+WORKSPACE,headers=ADMIN,json={'decision':'waived','note':'Synthetic data is intentionally smaller than SLO'})
    assert waived.status_code==200
    assert client.post(path+'/remediate?workspace='+WORKSPACE,headers=ADMIN,json={'status':'resolved','note':'Waiver approved'}).status_code==200


def test_p2_transformation_lineage_and_impact(demo):
    _,assets=demo
    tr=client.post('/api/phase2/transformations?workspace='+WORKSPACE,headers=ADMIN,json={'label':'Order rows into modeled sales','inputs':[assets['Orders']],'outputs':[assets['OrderRows']],'description':'Steward-declared upstream dependency'})
    assert tr.status_code==200,tr.text
    tid=tr.json()['transform_id']
    g=client.get('/api/phase2/lineage?workspace='+WORKSPACE,headers=ADMIN)
    assert g.status_code==200,g.text
    nodes=g.json()['nodes'];edges=g.json()['edges']
    assert any(n['id']==tid and n['kind']=='transformation' and n['status']=='declared' for n in nodes)
    assert any(e['source_id']==assets['Orders'] and e['target_id']==tid for e in edges)
    assert any(e['source_id']==tid and e['target_id']==assets['OrderRows'] for e in edges)
    imp=client.get('/api/phase2/lineage/impact',params={'workspace':WORKSPACE,'node_id':tid,'depth':2},headers=ADMIN)
    assert imp.status_code==200
    assert assets['Orders'] in {n['id'] for n in imp.json()['nodes']}
    assert assets['OrderRows'] in {n['id'] for n in imp.json()['nodes']}
    assert client.post('/api/phase2/transformations?workspace='+WORKSPACE,headers=ADMIN,json={'label':'nonsense','inputs':[assets['Orders']],'outputs':['asset:non-selected']}).status_code==404


def test_p2_security_and_audit(demo):
    _,assets=demo
    assert client.get(url('/api/phase2/audit'),headers=ANALYST).status_code==403
    audit=client.get(url('/api/phase2/audit'),headers=ADMIN)
    assert audit.status_code==200 and len(audit.json()['events'])>=6
    assert all(e['workspace_id']==WORKSPACE for e in audit.json()['events'])
    assert client.get('/api/phase2/assets/asset:madeup/metadata?workspace='+WORKSPACE,headers=ADMIN).status_code==404
    assert client.get('/api/phase2/overview?workspace=another-workspace',headers=ANALYST).status_code==404


def test_p2_sql_namespace_supports_major_connectors():
    svc=Phase2Service()
    def a(source,db='main',schema='public',table='Orders'):
        return {'source_id':source,'database':db,'schema':schema,'catalog':'main','table':table}
    assert svc._table_sql(a('postgres'))=='"public"."Orders"'
    assert svc._table_sql(a('athena'))=='"main"."Orders"'
    assert svc._table_sql(a('snowflake'))=='"main"."public"."Orders"'
    assert svc._table_sql(a('databricks'))=='`main`.`public`.`Orders`'
    with pytest.raises(ValueError):svc._table_sql(a('postgres',table='Orders; DROP'))


def test_p2_ui_is_actual_wired_workspace():
    from pathlib import Path
    js=(Path(__file__).resolve().parents[1]/'app/static/assets/app.js').read_text()
    for required in ('Profiling','Contracts','Relationship Evidence','Quality Center','Lineage Studio','bindPhase2()',
                     'p2-profile-run','p2-contract-save','p2-rel-validate','p2-rule-create','p2-quality-run','p2-transform-add'):
        assert required in js
