"""Phase 1 acceptance: permissions, lazy discovery, scope isolation, sample, routing."""
from unittest.mock import patch,MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.enterprise_catalog_service import EnterpriseCatalogService
from app.services.scope_service import ScopeService
from app.services.contoso_sample_service import ContosoSampleService
from app.services.bedrock_model_service import BedrockModelService
from app.repositories.control_repository import ControlRepository

client=TestClient(app)
ADMIN={'X-Roles':'semantic_admin','X-User':'phase1-admin'}
ANALYST={'X-Roles':'analyst','X-User':'phase1-analyst'}


def test_phase1_source_catalog_no_workspace_required():
    r=client.get('/api/phase1/catalog/contoso/catalogs',headers=ADMIN)
    assert r.status_code==200
    assert r.json()['items'][0]['name']=='Bundled Sample'


def test_phase1_local_hierarchy_and_table_details():
    d=client.get('/api/phase1/catalog/contoso/databases',headers=ADMIN).json()
    assert 'contoso_demo' in [x['name'] for x in d['items']]
    d=client.get('/api/phase1/catalog/contoso/schemas?database=contoso_demo',headers=ADMIN).json()
    assert 'public' in [x['name'] for x in d['items']]
    d=client.get('/api/phase1/catalog/contoso/tables?database=contoso_demo&schema=public&limit=3',headers=ADMIN).json()
    assert len(d['items'])==3 and d['next_cursor']
    next_page=client.get('/api/phase1/catalog/contoso/tables',params={'database':'contoso_demo','schema':'public','limit':3,'cursor':d['next_cursor']},headers=ADMIN).json()
    assert set(x['name'] for x in next_page['items']).isdisjoint(x['name'] for x in d['items'])
    details=client.get('/api/phase1/table-detail/contoso',params={'database':'contoso_demo','table':'Orders'},headers=ADMIN).json()
    assert any(c['name']=='OrderKey' for c in details['columns'])
    assert details['sample_rows_used'] is False


def test_phase1_roles_and_bad_pagination():
    assert client.get('/api/phase1/scopes',headers=ANALYST).status_code==403
    assert client.get('/api/phase1/bedrock/models',headers=ANALYST).status_code==403
    assert client.get('/api/phase1/catalog/contoso/tables?database=contoso_demo&schema=public&limit=300',headers=ADMIN).status_code==422
    assert client.get('/api/phase1/catalog/contoso/tables?database=contoso_demo&schema=public&cursor=bogus',headers=ADMIN).status_code==400


def test_phase1_save_generate_resync_only_selected():
    selection={'scope_id':'p1-retail-scope','workspace_id':'p1-retail-demo','display_name':'Phase 1 Test','source_id':'contoso','tables':[
        {'catalog':'Bundled Sample','database':'contoso_demo','schema':'public','table':'Customer'},
        {'catalog':'Bundled Sample','database':'contoso_demo','schema':'public','table':'Orders'},
    ]}
    saved=client.post('/api/phase1/scopes',headers=ADMIN,json=selection)
    assert saved.status_code==200,saved.text
    assert saved.json()['selected_count']==2
    gen=client.post('/api/phase1/scopes/p1-retail-scope/generate',headers=ADMIN)
    assert gen.status_code==200,gen.text
    d=gen.json();assert d['tables_scanned']==2 and d['selected_count']==2
    assert d['sample_rows_used'] is False
    from app.services.catalog_service import CatalogService
    rows=CatalogService().tables(market='p1-retail-demo')
    assert {x['table'] for x in rows}=={'Customer','Orders'}
    # Re-sync must honor persisted exact selection, not indiscriminately read all local tables.
    d=ScopeService().sync_workspace('p1-retail-demo')
    assert d['tables_scanned']==2
    assert ScopeService().get('p1-retail-scope')['version']==1
    assert client.get('/api/phase1/scopes',headers=ANALYST).status_code==403


def test_phase1_scope_validation_and_duplicate_table_names():
    svc=ScopeService()
    data={'scope_id':'p1-invalid','workspace_id':'p1-invalid','source_id':'contoso','tables':[{'database':'contoso_demo','table':'../../broken'}]}
    r=client.post('/api/phase1/scopes',headers=ADMIN,json=data)
    assert r.status_code==400
    assert ContosoSampleService().execute('select count(*) AS n from Orders')['rows'][0]['n']==10000


def test_phase1_athena_uses_continuation_tokens_without_bulk_column_enumeration():
    class Glue:
        def get_databases(self,**kw):
            n=kw.get('MaxResults',2);offset=int(kw.get('NextToken','0'))
            items=[{'Name':f'database_{i}'} for i in range(12)]
            end=min(len(items),offset+n)
            return {'DatabaseList':items[offset:end],'NextToken':str(end) if end<len(items) else None}
        def get_tables(self,**kw):
            n=kw.get('MaxResults',2);offset=int(kw.get('NextToken','0'))
            items=[{'Name':f'table_{i}','StorageDescriptor':{'Columns':[{'Name':'id'}]}} for i in range(12)]
            end=min(len(items),offset+n)
            return {'TableList':items[offset:end],'NextToken':str(end) if end<len(items) else None}
    svc=EnterpriseCatalogService()
    with patch('app.services.enterprise_catalog_service.AwsAdapter') as adapter:
        adapter.return_value.glue=Glue()
        page=svc._athena_dbs('',5,None)
        assert len(page['items'])==5 and page['next_cursor']
        nxt=svc._athena_dbs('',5,page['next_cursor'])
        assert nxt['items'][0]['name']=='database_5'
        tables=svc._athena_tables('database_0','',4,None)
        assert len(tables['items'])==4 and tables['next_cursor']
        assert adapter.return_value.get_columns.call_count==0


def test_phase1_bedrock_discovery_is_unverified_and_preference_persists():
    svc=BedrockModelService()
    bedrock=MagicMock()
    bedrock.list_foundation_models.return_value={'modelSummaries':[{'modelId':'us.amazon.nova-lite-v1:0','modelName':'Nova Lite','providerName':'Amazon'}]}
    bedrock.list_inference_profiles.return_value={'inferenceProfileSummaries':[]}
    with patch.object(svc,'_client',return_value=bedrock):
        found=svc.discover(); assert found['models'][0]['status']=='unverified'
        import pytest
        with pytest.raises(ValueError,match='VERIFIED'):svc.save({'strategy':'cost','task_models':{'ask':'us.amazon.nova-lite-v1:0'}})
        recommended=svc.recommend(found['models'])
        assert recommended['method']=='heuristic_not_benchmarked'
    with patch.object(svc,'_client',return_value=bedrock):
        bedrock.converse.return_value={'output':{'message':{'content':[{'text':'OK'}]}}}
        probe=svc.probe('us.amazon.nova-lite-v1:0')
        assert probe['status']=='verified'
        save=svc.save({'strategy':'cost','task_models':{'ask':'us.amazon.nova-lite-v1:0'}})
        assert save['task_models']['ask']=='us.amazon.nova-lite-v1:0'
        assert svc.chosen_model('ask')=='us.amazon.nova-lite-v1:0'


def test_phase1_ui_controls_are_wired():
    from pathlib import Path
    js=(Path(__file__).resolve().parents[1]/'app/static/assets/app.js').read_text()
    for fragment in ('Enterprise Catalog','AI Models','p1-save','p1-generate','p1-probe','bindPhase1()','phase1AiPage()'):
        assert fragment in js


def test_phase1_metadata_scope_does_not_enable_uncertified_ask():
    from app.services.query_service import QueryService
    import pytest
    with pytest.raises(ValueError,match='certified ontology release'):
        QueryService().run('How many orders are there?','p1-retail-demo',True,user=__import__('app.services.security_service',fromlist=['UserContext']).UserContext('admin',('semantic_admin',),{}))

def test_phase1_selections_cannot_use_arbitrary_sql_identifiers():
    r=client.post('/api/phase1/scopes',headers=ADMIN,json={
      'scope_id':'unsafe-scope','workspace_id':'unsafe-wid','source_id':'athena',
      'tables':[{'database':'prod;drop table users','table':'transactions'}]})
    assert r.status_code==400

def test_phase1_legacy_bulk_metadata_scan_rejected():
    from app.services.data_source_service import DataSourceService
    import pytest
    with pytest.raises(ValueError,match='Explicit schema scope'):
        DataSourceService().discover('postgres')

def test_phase1_1000_databases_browse_pages_without_full_download():
    class FakeGlue:
        calls=[]
        def get_databases(self,**kwargs):
            self.calls.append(kwargs)
            start=int(kwargs.get('NextToken','0')); n=kwargs['MaxResults']
            end=min(1000,start+n)
            return {'DatabaseList':[{'Name':f'db_{i:04d}'} for i in range(start,end)],
                    'NextToken':str(end) if end<1000 else None}
    fake=FakeGlue();svc=EnterpriseCatalogService()
    with patch('app.services.enterprise_catalog_service.AwsAdapter') as adapter:
        adapter.return_value.glue=fake
        d=svc._athena_dbs('',50,None)
        assert len(d['items'])==50
        assert len(fake.calls)==1
        nxt=svc._athena_dbs('',50,d['next_cursor'])
        assert nxt['items'][0]['name']=='db_0050'
        assert len(fake.calls)==2
        assert adapter.return_value.get_columns.call_count==0

def test_phase1_bedrock_runtime_uses_manually_verified_model():
    from app.adapters.aws import AwsAdapter
    svc=BedrockModelService()
    svc.repo.put('MODEL_CONFIG','default',{'strategy':'balanced','task_models':{'semantic_planning':'us.amazon.nova-lite-v1:0'}})
    mock=MagicMock()
    mock.converse.return_value={'output':{'message':{'content':[{'text':'SQL plan OK'}]}}}
    adapter=AwsAdapter()
    adapter._bedrock=mock
    result=adapter.invoke_text('parse',10,task='semantic_planning')
    assert result=='SQL plan OK'
    assert mock.converse.call_args.kwargs['modelId']=='us.amazon.nova-lite-v1:0'
