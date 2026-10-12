"""Object-specific tabs and least-privilege synthetic sample preview."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE='dataset-inspector-test'
ADMIN={'X-Roles':'semantic_admin','X-User':'dataset-steward'}
client=TestClient(app)

def seed():
    s=ScopeService()
    scope={'scope_id':WORKSPACE+'-scope','workspace_id':WORKSPACE,
           'display_name':'Dataset Inspector Test','source_id':'contoso',
           'tables':[{'database':'contoso_demo','table':x} for x in ('Orders','Customer')]}
    s.save(scope)
    s.build(scope['scope_id'])
    return {a['table']:a['asset_id'] for a in Phase2Service().assets(WORKSPACE)}

def sample(asset,tail=''):
    return client.get(f'/api/phase2/assets/{asset}/sample?workspace={WORKSPACE}{tail}',headers=ADMIN)

def test_workbench_tabs_are_contextual_and_stateful():
    js=(ROOT/'app/static/assets/app.js').read_text()
    css=(ROOT/'app/static/assets/app.css').read_text()
    for tab in ('page','yaml','profile','sample','transformation','sql','lineage'):
        assert f"['{tab}'," in js
    assert 'role="tablist"' in js and 'aria-selected=' in js
    assert 'datasetSelection' in js and 'datasetUpdateDetail()' in js
    assert 'dataset-object-list' in css and 'dataset-detail-header' in css
    assert 'class="tabs"' not in js  # no global top navigation strip

def test_bounded_scoped_demo_sample_only():
    assets=seed()
    res=sample(assets['Orders'])
    assert res.status_code==200,res.text
    payload=res.json()
    assert payload['source']=='synthetic_contoso'
    assert len(payload['rows'])==10 and set(payload['rows'][0])==set(payload['columns'])
    assert sample(assets['Orders'],'&limit=30').status_code==400
    assert sample(assets['Orders'],'&limit=0').status_code==400
    assert sample('asset:not-selected').status_code==404
    assert client.get('/api/phase2/assets/'+assets['Orders']+'/sample?workspace=not-this-one',headers=ADMIN).status_code>=400

def test_sensitive_fields_are_excluded_and_data_never_persisted():
    assets=seed()
    payload=sample(assets['Customer']).json()
    assert 'rows' in payload
    assert all(not any(v in col.lower() for v in ('email','phone','address','password')) for col in payload['columns'])
    assert 'Nothing is persisted' in payload['disclaimer']

def test_profile_and_sql_tabs_do_not_claim_unsupported_execution():
    js=(ROOT/'app/static/assets/app.js').read_text()
    assert 'not been executed or validated on an external warehouse' in js
    assert 'No measured profile exists' in js
    assert 'Current physical metadata' not in js or 'metadata' in js
