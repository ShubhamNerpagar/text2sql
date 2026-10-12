from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)
ADMIN={'X-Roles':'semantic_admin','X-User':'test-admin'}
ANALYST={'X-Roles':'analyst','X-User':'test-analyst'}


def test_health_and_version():
    d=client.get('/api/health',headers=ADMIN).json(); assert d['ok'] and d['version']=='8.4.0'


def test_bootstrap_returns_generated_workspace():
    d=client.get('/api/bootstrap',headers=ADMIN).json()
    assert d['requires_onboarding'] is False
    assert any(x['id']=='test-lab' for x in d['markets'])


def test_ready_endpoint_is_green_for_local_test_runtime():
    d=client.get('/api/ready',headers=ADMIN).json(); assert d['ready'] is True


def test_catalog_is_workspace_scoped():
    d=client.get('/api/catalog/tables?market=test-lab',headers=ANALYST).json()
    assert {x['table'] for x in d}=={'customers','orders'}


def test_query_api_enforces_column_policy_before_planning():
    r=client.post('/api/query',headers=ANALYST,json={'question':'How many orders are there?','market':'test-lab','execute':True})
    assert r.status_code==403  # This role lacks access to all certified semantic columns.


def test_graphrag_explorer_api():
    d=client.get('/api/graphrag/explorer?market=test-lab&limit=100',headers=ANALYST).json()
    assert len(d['nodes'])>10 and len(d['edges'])>0


def test_data_source_health_requires_admin():
    assert client.get('/api/data-sources/health',headers=ANALYST).status_code==403
    assert client.get('/api/data-sources/health',headers=ADMIN).status_code==200


def test_reports_are_not_seeded():
    d=client.get('/api/reports?market=test-lab',headers=ADMIN).json()
    assert d['reports']==[]


def test_report_create_add_render(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'order_count',dimensions=[{'asset_id':business.order_id,'column':'status'}])
    r=client.post('/api/reports',headers=ADMIN,json={'market':business.w,'title':'Operations','description':'Runtime report'}).json()
    response=client.post(f"/api/reports/{r['report_id']}/widgets",headers=ADMIN,json={'question':'Orders by status','title':'Orders by status','chart_type':'bar'})
    assert response.status_code==200,response.text
    w=response.json();assert 'rows' not in w and 'sql' not in w and w['release_id']==business.release
    d=client.get(f"/api/reports/{r['report_id']}/render",headers=ADMIN).json()
    assert d['rendered_widgets'][0]['visualization']['type']=='bar'


def test_onboarding_status_confirms_metadata_only():
    d=client.get('/api/onboarding/status?market=test-lab',headers=ADMIN).json()
    assert d['sample_values_enabled'] is False
    assert d['capabilities']['sample_rows_required'] is False


def test_release_and_governance_paths():
    g=client.get('/api/governance?market=test-lab',headers=ADMIN); assert g.status_code==200
    r=client.post('/api/releases/publish',headers=ADMIN,json={'market':'test-lab','version':'7.0.1-test','notes':'runtime test'})
    assert r.status_code==200 and r.json()['graph_fingerprint']


def test_mcp_tools_are_available_for_runtime_workspace():
    d=client.post('/mcp',headers=ANALYST,json={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{'market':'test-lab'}}).json()
    assert d['result']['tools']


def test_ui_contains_force_directed_canvas_and_no_country_seed():
    js=client.get('/assets/app.js').text
    assert 'semanticGraphCanvas' in js and 'force-directed' in js.lower()
    assert "market:''" in js
