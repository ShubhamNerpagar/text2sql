"""Cross-connector results against independent SQLite and bundled Contoso data."""
from dataclasses import replace
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
import pytest
from conftest import TEST_DB
from governed_fixtures import bedrock_contract
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service
from app.services.advanced_query_service import AdvancedQueryService
from app.services.unified_ask_service import UnifiedAskService
from app.services.federation_service import FederationService
from app.services.business_benchmark_service import BusinessBenchmarkService
from app.services.data_source_service import DataSourceService
from app.services.llm_planner_service import LLMPlannerService
from app.services.market_service import MarketService


@pytest.fixture
def multi():
    token=uuid4().hex[:8];w='multi-'+token;table='sales_'+token
    with sqlite3.connect(TEST_DB) as db:
        db.execute(f'CREATE TABLE {table}(order_id INTEGER PRIMARY KEY, amount REAL, refund REAL, status TEXT, currency TEXT)')
        db.executemany(f'INSERT INTO {table} VALUES(?,?,?,?,?)',[(1,100,10,'Complete','USD'),(2,50,0,'Cancelled','GBP'),(3,200,20,'Complete','EUR'),(4,80,0,'Complete','GBP')])
    selection={'scope_id':w+'-scope','workspace_id':w,'tables':[
        {'source_id':'postgres','catalog':'PostgreSQL','database':'main','schema':'main','table':table},
        {'source_id':'contoso','database':'contoso_demo','table':'CurrencyExchange'}]}
    sc=ScopeService();saved=sc.save(selection);assert saved['source_id']=='federated';sc.build(saved['scope_id'])
    p2=Phase2Service();p3=Phase3Service();assets=p2.assets(w)
    sales=next(a for a in assets if a['source_id']=='postgres');currency=next(a for a in assets if a['source_id']=='contoso')
    for a in assets:
        p2.profile(w,a['asset_id'],'standard','creator',200)
        p2.save_contract(w,a['asset_id'],{'owner':'business steward'},'creator')
        p2.transition_contract(w,a['asset_id'],'reviewed','Schema and profile reviewed','creator')
        p2.transition_contract(w,a['asset_id'],'certified','Evidence approved','reviewer')
    def certify(oid,kind,asset,sem):
        columns=[c['name'] for c in p2.metadata(w,asset['asset_id'])['columns']]
        o=p3.create(w,{'object_id':oid,'kind':kind,'label':oid,'description':'Amounts are normalized USD; currency identifies original transaction currency',
            'binding':{'asset_id':asset['asset_id'],'columns':columns},'semantics':sem},'creator')
        o=p3.transition(w,oid,'reviewed','Business meaning reviewed','creator',o['version'])
        p3.transition(w,oid,'certified','Independent business evidence review','reviewer',o['version'])
    certify('net_sales','measure',sales,{'grain':['order_id'],'aggregation':'sum','expression':{'op':'subtract','args':[{'column':'amount'},{'column':'refund'}]},'unit':'USD','additivity':'additive','filters':[{'column':'status','op':'eq','value':'Complete'}]})
    certify('currency','entity',currency,{'grain':['CurrencyCode']})
    rel=p2.create_relationship(w,{'from_asset':sales['asset_id'],'to_asset':currency['asset_id'],
        'from_columns':['currency'],'to_columns':['CurrencyCode'],'role':'currency'},'creator')
    measured=p2.validate_relationship(w,rel['relationship_id'],'creator')
    assert measured['evidence']['coverage']==1 and measured['evidence']['target_duplicate_rows']==0
    p2.review_relationship(w,rel['relationship_id'],'approved','Exact keys and matching business role reviewed','reviewer')
    p3.publish_snapshot(w,'v1','Cross-connector reference baseline','reviewer')
    release=Phase4Service().promote(w,'v1','reviewer')['release_id']
    plan={'base_asset_id':sales['asset_id'],'metrics':[{'metric_id':'net_sales','alias':'value'}],
        'dimensions':[{'asset_id':currency['asset_id'],'column':'CurrencyCode'}],
        'join_relationship_ids':[rel['relationship_id']],'filters':[],'concept_ids':[],'having':[],'order_by':[],'limit':50}
    yield SimpleNamespace(w=w,table=table,sales=sales,currency=currency,p2=p2,p3=p3,relationship=rel,release=release,plan=plan)
    with p2.repo.lock:
        store=p2.repo._local()
        for rows in store.values():
            for key,row in list(rows.items()):
                if w in (row.get('workspace_id'),row.get('market'),row.get('workspace')) or key==w or key.startswith(w+'::'):rows.pop(key)
        p2.repo._save(store)
    with sqlite3.connect(TEST_DB) as db:db.execute('DROP TABLE '+table)


def test_sample_is_optional_and_can_be_disabled():
    sources=DataSourceService();sample=next(x for x in sources.sources() if x['id']=='contoso')
    assert sample['optional'] and sample['configured'] and 'optional' in sample['label']
    sources.s=replace(sources.s,enable_sample_execution=False)
    assert not next(x for x in sources.sources() if x['id']=='contoso')['configured']
    with pytest.raises(ValueError,match='sample source is disabled'):sources.execute('contoso','SELECT COUNT(*) FROM Orders','contoso_demo')


def test_optional_sample_does_not_weaken_production_identity_requirements():
    from app.config import production_configuration_errors
    from test_production_hardening_810 import production_settings
    profile=replace(production_settings(),enable_sample_execution=True)
    assert not production_configuration_errors(profile)
    assert production_configuration_errors(replace(profile,allow_dev_identity_headers=True))


def test_scope_contains_exact_datasets_from_both_connectors(multi):
    assets=multi.p2.assets(multi.w)
    assert {a['source_id'] for a in assets}=={'postgres','contoso'}
    assert {a['table'] for a in assets}=={multi.table,'CurrencyExchange'}
    assert len({a['asset_id'] for a in assets})==2
    context=MarketService().context(multi.w)
    assert set(context['data_sources']['supported'])=={'postgres','contoso'}
    refreshed=ScopeService().sync_workspace(multi.w)
    assert refreshed['tables_scanned']==2
    assert {a['asset_id'] for a in multi.p2.assets(multi.w)}=={a['asset_id'] for a in assets}


def test_cross_connector_question_uses_reviewed_plan_and_actual_results(multi,bedrock_contract):
    bedrock_contract.plan=multi.plan
    out=UnifiedAskService().ask(multi.w,multi.release,'Net sales by currency')
    assert out['executed'] and out['plan']['source_ids']==['contoso','postgres']
    assert out['plan']['execution_engine']=='duckdb'
    assert sorted((r['d1'],r['value']) for r in out['rows'])==[('EUR',180),('GBP',80),('USD',90)]
    assert out['federation']['total_rows_loaded']==8
    assert out['federation']['source_rows_sent_to_llm'] is False
    assert bedrock_contract.calls==['semantic_planning','semantic_verification']


def test_sample_still_requires_llm(multi,monkeypatch):
    monkeypatch.setattr(LLMPlannerService,'status',lambda self:{'ready':False})
    with pytest.raises(ValueError,match='LLM_CONNECTION_REQUIRED'):
        UnifiedAskService().ask(multi.w,multi.release,'Net sales by currency')


def test_unapproved_cross_source_relationship_cannot_execute(multi):
    multi.p2.review_relationship(multi.w,multi.relationship['relationship_id'],'rejected','No longer business-approved','reviewer')
    with pytest.raises(ValueError,match='unapproved'):
        AdvancedQueryService().compile(multi.w,multi.release,multi.plan)


def test_federation_refuses_incomplete_or_oversized_data(multi,monkeypatch):
    federation=FederationService(multi.p2)
    federation.s=replace(federation.s,federation_max_rows_per_asset=3)
    with pytest.raises(ValueError,match='FEDERATION_LIMIT_EXCEEDED'):
        with federation.snapshot(multi.w,[multi.sales,multi.currency]):pass
    original=multi.p2.sources.execute
    def incomplete(source,sql,database=None,**kw):
        out=original(source,sql,database,**kw)
        if source=='contoso' and 'COUNT(*)' not in sql:out={**out,'rows':out['rows'][:-1]}
        return out
    monkeypatch.setattr(multi.p2.sources,'execute',incomplete)
    with pytest.raises(ValueError,match='FEDERATION_INCOMPLETE_SNAPSHOT'):
        with FederationService(multi.p2).snapshot(multi.w,[multi.sales,multi.currency]):pass


def test_native_question_in_multi_source_workspace_stays_native(multi,bedrock_contract):
    bedrock_contract.plan={**multi.plan,'dimensions':[],'join_relationship_ids':[]}
    out=UnifiedAskService().ask(multi.w,multi.release,'Net sales')
    assert out['rows']==[{'value':350.0}]
    assert out['plan']['execution_engine']=='native' and out['plan']['source_ids']==['postgres']


def test_cross_source_benchmark_matches_independent_sql(multi,bedrock_contract):
    bedrock_contract.plan=multi.plan
    source=FederationService.table_name(multi.sales);target=FederationService.table_name(multi.currency)
    sql=f'SELECT c.CurrencyCode, SUM(o.amount-o.refund) FROM "{source}" o LEFT JOIN "{target}" c ON o.currency=c.CurrencyCode WHERE o.status=\'Complete\' GROUP BY c.CurrencyCode'
    benchmark=BusinessBenchmarkService()
    case=benchmark.save(multi.w,{'release_id':multi.release,'question':'Net sales by currency','expected':'answer',
        'reference_asset_id':multi.sales['asset_id'],'reference_sql':sql},'reviewer')
    assert case['federated_reference'] and len(case['reference_asset_ids'])==2
    run=benchmark.run(multi.w,multi.release)
    assert run['counts']=={'passed':1,'failed':0,'blocked':0},run


@pytest.mark.parametrize('change,expected',[('grain','Measure grain changed'),('coverage','Relationship coverage changed')])
def test_snapshot_rechecks_changes_despite_cached_evidence(multi,monkeypatch,change,expected):
    original=DataSourceService.execute
    def changed(self,source,sql,database=None,**kw):
        out=original(self,source,sql,database,**kw)
        if source=='postgres' and kw.get('row_limit') and out['rows'] and 'order_id' in out['rows'][0]:
            rows=[dict(r) for r in out['rows']]
            if change=='grain':rows[1]['order_id']=rows[0]['order_id']
            else:rows[0]['currency']='UNMATCHED'
            out={**out,'rows':rows}
        return out
    monkeypatch.setattr(DataSourceService,'execute',changed)
    with pytest.raises(ValueError,match=expected):
        AdvancedQueryService().run(multi.w,multi.release,'Net sales by currency',plan=multi.plan,execute=True)


def test_explicit_connector_constraint_is_checked_before_execution(multi,bedrock_contract):
    bedrock_contract.plan=multi.plan
    with pytest.raises(ValueError,match='Requested connector'):
        UnifiedAskService().ask(multi.w,multi.release,'Net sales by currency',constraints={'source_id':'postgres'})
    assert bedrock_contract.calls==['semantic_planning']


def test_federated_snapshots_cannot_load_local_files_or_unselected_columns(multi):
    import duckdb
    service=FederationService(multi.p2)
    with service.snapshot(multi.w,[multi.currency]) as (con,_):
        with pytest.raises(duckdb.PermissionException):con.execute("SELECT * FROM read_csv_auto('/etc/passwd')")
    with pytest.raises(ValueError,match='outside scoped metadata'):
        with service.snapshot(multi.w,[multi.currency],{multi.currency['asset_id']:['unknown_column']}):pass


def test_connector_identity_distinguishes_identically_named_tables():
    selection={'source_id':'federated'}
    table={'catalog':'same','database':'same','schema':'same','table':'Customer'}
    a=Phase2Service.asset_id(selection,{**table,'source_id':'postgres'})
    b=Phase2Service.asset_id(selection,{**table,'source_id':'snowflake'})
    assert a!=b


def test_connector_limits_payload_during_fetch(multi):
    with pytest.raises(ValueError,match='Connector payload exceeds'):
        DataSourceService().execute('postgres',f'SELECT amount, status FROM main.{multi.table}',row_limit=100,payload_limit=10)
    with pytest.raises(ValueError,match='Contoso payload exceeds'):
        DataSourceService().execute('contoso','SELECT CurrencyCode FROM CurrencyExchange','contoso_demo',row_limit=100,payload_limit=10)
