import base64, json, time
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.services.onboarding_service import OnboardingService
from app.services.market_service import MarketService
from app.services.semantic_studio_service import SemanticStudioService
from app.repositories.semantic_repository import SemanticRepository
from app.repositories.control_repository import ControlRepository
from app.repositories.learning_repository import LearningRepository
from app.services.data_source_service import DataSourceService
from app.services.relationship_service import RelationshipService
from app.services.relationship_validation_service import RelationshipValidationService
from app.services.graph_rag_service import GraphRAGService
from app.services.security_service import SecurityService, UserContext
from app.services.report_service import ReportService
from app.services.cron_service import next_run, cron_matches
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
ADMIN=UserContext('admin',('semantic_admin',),{})
client=TestClient(app)
HEAD={'X-Roles':'semantic_admin','X-User':'v7-test'}

def test_v7_workspace_alias_and_semantic_studio_api():
    w=client.get('/api/workspaces',headers=HEAD).json()['workspaces']
    assert any(x['id']=='test-lab' for x in w)
    d=client.get('/api/semantic-studio?workspace=test-lab',headers=HEAD).json()
    assert 'counts' in d and 'schema_drift' in d

def test_semantic_studio_authoring_and_certification(business):
    svc=SemanticStudioService()
    import pytest
    spec={'label':'Order business','description':'Steward-owned order entity','binding':{'asset_id':business.order_id,'columns':['order_id']},'semantics':{'grain':['order_id']}}
    with pytest.raises(ValueError,match='review transitions'):svc.upsert(business.w,'entity','order_business',{**spec,'status':'reviewed'},'tester')
    x=svc.upsert(business.w,'entity','order_business',spec,'tester')
    assert x['status']=='draft'
    x=svc.transition(business.w,'entity','order_business','reviewed','Business definition checked','tester')
    with pytest.raises(ValueError,match='Independent'):svc.transition(business.w,'entity','order_business','certified','Self approval fails','tester')
    y=svc.transition(business.w,'entity','order_business','certified','Independent steward review','other-steward')
    assert y['status']=='certified' and MarketService().context(business.w)['entities']['order_business']['status']=='certified'


def test_resync_preserves_steward_certified_semantics(business):
    before=MarketService().context(business.w)['entities']['orders']
    d=OnboardingService().sync_catalog(business.w,['main'])
    after=MarketService().context(business.w)['entities']['orders']
    assert d['preserved_steward_semantics'] is True
    assert before['object_id']==after['object_id'] and before['status']==after['status']=='certified'


def test_schema_drift_detection_contract():
    old={'main.orders':{'id':'INTEGER','amount':'REAL'}}
    new={'main.orders':{'id':'BIGINT','amount':'REAL','status':'TEXT'},'main.customers':{'id':'INTEGER'}}
    rows=OnboardingService._drift(old,new)
    types={x['type'] for x in rows}
    assert {'table_added','column_added','column_type_changed'} <= types

def test_multi_workspace_physical_membership_isolated():
    OnboardingService().bootstrap_source('postgres','second-lab','Second Analytics',['main'],discover_relationships=False)
    dd=SemanticRepository().ontology()['data_dictionary']
    memberships=set(dd['main']['orders']['workspace_ids'])
    assert {'test-lab','second-lab'} <= memberships
    assert MarketService().context('test-lab')['market']['id']=='test-lab'
    assert MarketService().context('second-lab')['market']['id']=='second-lab'

def test_connector_neutral_relationship_statistics_execute_without_samples():
    rel=next(x for x in RelationshipService().all() if x.get('market')=='test-lab')
    stats=DataSourceService().relationship_stats('postgres',rel)
    assert stats['sample_rows_returned'] is False
    assert {'source_distinct','target_distinct','matched_distinct'} <= set(stats)

def test_relationship_validator_uses_workspace_connector(monkeypatch):
    rel=next(x for x in RelationshipService().all() if x.get('market')=='test-lab')
    monkeypatch.setattr(DataSourceService,'relationship_stats',lambda self,source_id,r:{'source_distinct':2,'target_distinct':2,'target_non_null_rows':2,'matched_distinct':2,'query_id':'q','bytes_scanned':0,'sample_rows_returned':False})
    out=RelationshipValidationService().validate(rel['id'],workspace='test-lab')
    assert out['promoted'] is False and out['evidence']['target_duplicate_rows']==0
    assert out['relationship']['status']=='evidenced'  # Measurement cannot grant business approval.

def test_dynamodb_repositories_do_not_use_scan():
    assert '.scan(' not in (ROOT/'app/repositories/control_repository.py').read_text()
    assert '.scan(' not in (ROOT/'app/repositories/learning_repository.py').read_text()
    policy=json.loads((ROOT/'infra/windows/ec2-instance-role-policy.json').read_text())
    memory=next(x for x in policy['Statement'] if x['Sid']=='DynamoControlOptional')
    assert 'dynamodb:Query' in memory['Action'] and 'dynamodb:Scan' not in memory['Action']

def test_alb_oidc_signature_verification():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key=ec.generate_private_key(ec.SECP256R1()); pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    enc=lambda b: base64.urlsafe_b64encode(b).decode().rstrip('=')
    header={'alg':'ES256','kid':'unit','signer':'arn:aws:elasticloadbalancing:eu-west-1:123:loadbalancer/app/test','client':'client-1'}
    payload={'sub':'u-1','exp':int(time.time())+120,'roles':['analyst']}
    h=enc(json.dumps(header,separators=(',',':')).encode()); p=enc(json.dumps(payload,separators=(',',':')).encode()); der=key.sign(f'{h}.{p}'.encode(),ec.ECDSA(hashes.SHA256())); r,s=decode_dss_signature(der); sig=enc(r.to_bytes(32,'big')+s.to_bytes(32,'big')); token=f'{h}.{p}.{sig}'
    svc=SecurityService(); svc.s=SimpleNamespace(**{**svc.s.__dict__,'alb_expected_signer_arn':header['signer'],'alb_expected_client_id':'client-1','alb_jwt_public_key_url_template':'unused','aws_region':'eu-west-1'}); svc._alb_public_key=lambda kid:pub
    out=svc.verify_alb_oidc(token); assert out['sub']=='u-1'

def test_workspace_claim_blocks_cross_workspace_access():
    svc=SecurityService(); user=UserContext('u',('analyst',),{'workspace':'test-lab'})
    assert svc.workspace_allowed(user,'test-lab')
    assert not svc.workspace_allowed(user,'second-lab')

def test_graph_explorer_scaling_filters_and_clusters():
    d=GraphRAGService().explorer('test-lab',limit=500,node_types=['table'])
    assert d['returned_nodes']<=500 and d['clusters']
    assert all(x['node_type']=='table' for x in d['nodes'])
    assert 'total_graph_nodes' in d and 'truncated' in d

def test_report_filters_sharing_schedule_and_exports(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'order_count',dimensions=[{'asset_id':business.order_id,'column':'status'}])
    svc=ReportService(); r=svc.create(business.w,'V7 report','production feature test',ADMIN); svc.add_widget(r['report_id'],'How many orders are there by status?','Orders by status','bar',ADMIN)
    svc.share(r['report_id'],['analyst'],ADMIN); svc.set_filters(r['report_id'],[{'dimension':'orders:status','operator':'equals','value':'Complete'}],ADMIN)
    saved=svc.set_schedule(r['report_id'],{'enabled':True,'cron':'*/15 * * * *','timezone':'UTC','data_source':None},ADMIN)
    assert saved['schedule']['next_run_at']
    for fmt,magic in [('csv',None),('xlsx',b'PK'),('pdf',b'%PDF')]:
        data,media,name=svc.export(r['report_id'],ADMIN,fmt)
        assert data and name.endswith('.'+fmt)
        if magic: assert data.startswith(magic)

def test_report_alert_contract(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'order_count')
    svc=ReportService(); r=svc.create(business.w,'Alert report','',ADMIN); w=svc.add_widget(r['report_id'],'How many orders are there?','Order count','kpi',ADMIN)
    a=svc.add_alert(r['report_id'],{'enabled':True,'widget_id':w['widget_id'],'operator':'>','threshold':1,'value_column':'value','message':'Orders exist'},ADMIN)
    rendered=svc.render(r['report_id'],ADMIN); alerts=svc.evaluate_alerts(rendered)
    assert a['alert_id'] and alerts and alerts[0]['actual_value']==4

def test_cron_engine():
    dt=datetime(2026,10,6,10,30,tzinfo=timezone.utc)
    assert cron_matches(dt,'*/15 * * * *')
    assert next_run('0 11 * * *',dt).hour==11

def test_windows_native_infra_and_ci_present():
    for name in ['ec2-instance-role-policy.json','cloudwatch-agent-config.json']:
        assert (ROOT/'infra/windows'/name).exists()
    wf=(ROOT/'.github/workflows/windows-native.yml').read_text()
    assert 'windows-latest' in wf and 'pytest' in wf and 'uvicorn' in wf
    assert (ROOT/'docs/BACKUP_DR.md').exists() and (ROOT/'docs/PRODUCTION_ACCEPTANCE.md').exists()

def test_ui_has_semantic_studio_graph_filters_and_report_exports():
    js=(ROOT/'app/static/assets/app.js').read_text()
    for text in ['Semantic Studio','graphTypeFilter','graphTrustedOnly','reportExport','reportSchedule']:
        assert text in js

def test_no_france_or_customer_semantic_package_returned():
    market_root=ROOT/'data/semantic/markets'
    assert not market_root.exists() or not list(market_root.rglob('*.yaml'))

def test_graph_explorer_bounds_synthetic_enterprise_graph(monkeypatch):
    svc=GraphRAGService()
    nodes={}
    edges=[]
    for i in range(10000):
        nid=f'column:main.t{i//20}.c{i}'
        nodes[nid]={'id':nid,'label':f'c{i}','node_type':'column','status':'observed','authority':0.6,'freshness':1.0,'summary':'','attributes':{'database':'main','table':f't{i//20}','column':f'c{i}'}}
        if i and i%20:
            prev=f'column:main.t{i//20}.c{i-1}'
            edges.append({'source_id':prev,'target_id':nid,'trusted_for_queries':False})
    graph={'nodes':nodes,'edges':edges,'stats':{},'fingerprint':'synthetic','version':'3.0'}
    monkeypatch.setattr(svc,'graph',lambda workspace:graph)
    out=svc.explorer('synthetic',limit=10000,node_types=['column'])
    assert out['total_graph_nodes']==10000
    assert out['returned_nodes']==svc.s.graph_explorer_max_nodes
    assert out['truncated'] is True
    assert len(out['nodes'])<=500
    assert len(out['clusters'])<=500

def test_rls_predicate_is_compiled_into_governed_sql(monkeypatch):
    from app.services.sql_compiler import SQLCompiler
    c=SQLCompiler(); monkeypatch.setattr(c.markets,'context',lambda workspace:{'bindings':{}})
    plan={'market':'test-lab','decision':'COMMIT','tables':['main.orders'],'join_plan':{'connected':True,'root':'main.orders','joins':[]},'metric':'record_count','group_dimensions':[],'filters':[],'time':{},'question':'count orders','intent':'aggregate'}
    out=c.compile(plan,'postgresql',[{'database':'main','table':'orders','expression':"{alias}.tenant_id = 'tenant-a'"}])
    assert out['supported'] and "t0.tenant_id = 'tenant-a'" in out['sql']

def test_alb_oidc_tampered_signature_is_rejected():
    import pytest
    svc=SecurityService(); svc.s=SimpleNamespace(**{**svc.s.__dict__,'alb_expected_signer_arn':'arn:test','alb_expected_client_id':'','alb_jwt_public_key_url_template':'unused','aws_region':'eu-west-1'})
    enc=lambda b: base64.urlsafe_b64encode(b).decode().rstrip('=')
    h=enc(json.dumps({'alg':'ES256','kid':'k','signer':'arn:test'}).encode()); p=enc(json.dumps({'sub':'u','exp':int(time.time())+120}).encode()); token=f'{h}.{p}.{enc(bytes(64))}'
    svc._alb_public_key=lambda kid:b'not-a-valid-key'
    with pytest.raises(PermissionError): svc.verify_alb_oidc(token)

def test_windows_native_env_templates_separate_test_and_production():
    test=(ROOT/'.env.windows.test.example').read_text()
    prod=(ROOT/'.env.windows.production.example').read_text()
    assert 'AUTH_MODE=dev_headers' in test and 'PERSIST_LOCAL_STATE=true' in test
    assert 'AUTH_MODE=alb_oidc' in prod and 'PERSIST_LOCAL_STATE=false' in prod
    assert 'ALLOW_DEV_IDENTITY_HEADERS=false' in prod

def test_windows_native_startup_and_report_worker_tasks_present():
    app_task=(ROOT/'windows/Install-StartupTask.ps1').read_text()
    report_task=(ROOT/'windows/Install-ReportWorkerTask.ps1').read_text()
    worker=(ROOT/'windows/Run-ReportWorker.ps1').read_text()
    assert 'AtStartup' in app_task and 'RestartCount' in app_task
    assert 'RepetitionInterval' in report_task
    assert 'scripts\\run_report_worker.py' in worker

def test_relationship_validation_sql_contract_all_supported_sources(monkeypatch):
    svc=DataSourceService(); relation={'from_db':'analytics','from_table':'orders','from_column':'customer_id','to_db':'analytics','to_table':'customers','to_column':'customer_id'}
    calls=[]
    def fake_execute(source_id,sql,database=None):
        calls.append((source_id,sql,database)); return {'query_id':f'{source_id}-q','bytes_scanned':0,'rows':[{'source_distinct':3,'target_distinct':3,'target_non_null_rows':3,'matched_distinct':3}]}
    monkeypatch.setattr(svc,'execute',fake_execute)
    for source in ['athena','postgres','snowflake','databricks']:
        out=svc.relationship_stats(source,relation)
        assert out['matched_distinct']==3 and out['sample_rows_returned'] is False
    assert {x[0] for x in calls}=={'athena','postgres','snowflake','databricks'}

def test_windows_ci_validates_native_runtime_without_docker():
    wf=(ROOT/'.github/workflows/windows-native.yml').read_text()
    assert 'windows-latest' in wf
    assert 'Invoke-RestMethod http://127.0.0.1:8000/api/health' in wf
    assert 'docker build' not in wf
