"""Business correctness controls using independent expected results and mocked Bedrock responses.
These test the integration contract, not the natural-language accuracy of a live model.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.adapters.aws import AwsAdapter
from app.repositories.control_repository import ControlRepository
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service
from app.services.advanced_query_service import AdvancedQueryService
from app.services.unified_ask_service import UnifiedAskService
from app.services.llm_planner_service import LLMPlannerService
from app.services.bedrock_model_service import BedrockModelService
from app.services.guided_onboarding_service import GuidedOnboardingService
from app.services.business_benchmark_service import BusinessBenchmarkService
from app.services.semantic_studio_service import SemanticStudioService
from app.services.semantic_registry_service import SemanticRegistryService
from app.services.market_service import MarketService
from app.services.report_service import ReportService
from app.services.security_service import UserContext
from app.config import get_settings
from conftest import TEST_DB

ADMIN=UserContext('creator',('semantic_admin',),{})
H={'X-User':'creator','X-Roles':'semantic_admin'}


from governed_fixtures import plan


def test_no_offline_model_fallback_even_for_counts(business,monkeypatch):
    monkeypatch.setattr(LLMPlannerService,'status',lambda self:{'ready':False})
    with pytest.raises(ValueError,match='LLM_CONNECTION_REQUIRED'):
        UnifiedAskService().ask(business.w,business.release,'Count orders')


@pytest.mark.parametrize('question',['Revenue','What is our net revenue?','Total completed sales'])
def test_paraphrases_use_same_approved_formula_and_predicates(business,bedrock_contract,question):
    bedrock_contract.plan=plan(business)
    out=UnifiedAskService().ask(business.w,business.release,question)
    assert out['executed'] and out['rows']==[{'value':350.0}]
    assert 'refund' in out['plan']['sql'] and "'Complete'" in out['plan']['sql']
    assert bedrock_contract.calls==['semantic_planning','semantic_verification']
    assert out['model_used'] and out['semantic_review']['passed']


def test_clause_loss_is_rejected_before_execution(business,bedrock_contract):
    q='Count orders in Berlin';bedrock_contract.plan=plan(business,'order_count')
    bedrock_contract.intent={'mode':'new','change_fields':[],'clauses':[{'start':0,'end':12,'text':q[:12],'targets':['/metrics/0']}]}
    with pytest.raises(ValueError,match='INTENT_INCOMPLETE'):UnifiedAskService().ask(business.w,business.release,q)
    assert bedrock_contract.calls==['semantic_planning']


def test_independent_review_rejects_wrong_clause_mapping(business,bedrock_contract):
    bedrock_contract.plan=plan(business,'order_count')
    bedrock_contract.review={'complete':False,'correct':False,'preserved_context':True,'unresolved':['Berlin filter is missing']}
    out=UnifiedAskService().ask(business.w,business.release,'Count orders in Berlin')
    assert out['status']=='needs_clarification' and not out['executed'] and 'Berlin' in out['clarification']


def test_structured_clarification_never_runs_query(business,bedrock_contract):
    bedrock_contract.clarification='Do you mean net or gross revenue?'
    out=UnifiedAskService().ask(business.w,business.release,'Revenue')
    assert out['status']=='needs_clarification' and not out['executed']
    assert bedrock_contract.calls==['semantic_planning']


def test_followup_preserves_filters_metrics_concepts_and_limits(business,bedrock_contract):
    previous=plan(business,'order_count',concept_ids=['completed_orders'],filters=[{'asset_id':business.order_id,'column':'status','op':'ne','value':'Cancelled'}],limit=10)
    rid=business.relationships['customer_id']
    bedrock_contract.plan=plan(business,'order_count',dimensions=[{'asset_id':business.customer_id,'column':'city'}],join_relationship_ids=[rid])
    q='Now by city';bedrock_contract.intent={'mode':'followup','change_fields':['dimensions','join_relationship_ids'],
        'clauses':[{'start':0,'end':len(q),'text':q,'targets':['/dimensions/0']}]}
    out=UnifiedAskService().ask(business.w,business.release,q,previous_plan=previous)
    assert out['structured_plan']['filters']==previous['filters'] and out['structured_plan']['concept_ids']==previous['concept_ids']
    assert out['structured_plan']['limit']==10
    assert {r['d1']:r['value'] for r in out['rows']}=={'Berlin':1,'Paris':2}


def test_parent_measure_repetition_and_raw_aggregation_are_rejected(business):
    compiler=AdvancedQueryService();rid=business.relationships['customer_id']
    with pytest.raises(ValueError,match='parent measure'):
        compiler.compile(business.w,business.release,plan(business,'credit_limit',join_relationship_ids=[rid]))
    p=plan(business);p['metrics']=[{'asset_id':business.order_id,'column':'amount','function':'sum','alias':'value'}]
    with pytest.raises(ValueError,match='metric_id'):compiler.compile(business.w,business.release,p)


@pytest.mark.parametrize('metric,expected',[('order_count',4),('customer_count',2),('weighted_amount',820/7),('refund_ratio',30/380)])
def test_counts_weighted_averages_and_ratios_match_independent_results(business,metric,expected):
    out=AdvancedQueryService().run(business.w,business.release,'Reference contract',plan=plan(business,metric),execute=True)
    assert out['rows'][0]['value']==pytest.approx(expected)


def test_role_playing_dimensions_get_distinct_aliases(business):
    billing=business.relationships['customer_id'];shipping=business.relationships['shipping_customer_id']
    p=plan(business,'order_count',join_relationship_ids=[billing,shipping],dimensions=[
        {'asset_id':business.customer_id,'column':'city','role':billing},
        {'asset_id':business.customer_id,'column':'city','role':shipping}])
    out=AdvancedQueryService().run(business.w,business.release,'Billing vs shipping cities',plan=p,execute=True)
    assert out['plan']['sql'].count('LEFT JOIN')==2
    assert {(r['d1'],r['d2']):r['value'] for r in out['rows']}=={('Berlin','Paris'):1,('Berlin','Berlin'):1,('Paris','Paris'):1,('Paris','Berlin'):1}
    p['dimensions'][0].pop('role')
    with pytest.raises(ValueError,match='relationship role'):AdvancedQueryService().compile(business.w,business.release,p)


def test_refresh_preserves_approval_for_unchanged_passing_evidence(business):
    rid=business.relationships['customer_id'];r=business.p2._get('relationship',business.w,rid)
    old={**r,'evidence':{**r['evidence'],'evaluated_at':(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()}}
    business.p2._put('relationship',business.w,rid,old)
    graph=SemanticRegistryService().graph_relationships(business.w)
    assert not next(x for x in graph if x['relationship_id']==rid)['trusted_for_queries']
    refreshed=business.p2.refresh_relationships(business.w)
    assert refreshed and refreshed[0]['status']=='approved' and refreshed[0]['trusted_for_queries']
    assert refreshed[0]['reviewed_by']=='reviewer'


def test_exact_duplicate_evidence_and_composite_foreign_keys():
    token=uuid4().hex[:8];w='composite-'+token;parent='parent_'+token;child='child_'+token
    with sqlite3.connect(TEST_DB) as db:
        db.executescript(f'''CREATE TABLE {parent}(tenant INTEGER, id INTEGER, PRIMARY KEY(tenant,id));
            CREATE TABLE {child}(row_id INTEGER PRIMARY KEY, tenant INTEGER, parent_id INTEGER, FOREIGN KEY(tenant,parent_id) REFERENCES {parent}(tenant,id));
            INSERT INTO {parent} VALUES(1,1),(2,1);INSERT INTO {child} VALUES(10,1,1),(11,2,1);''')
    sc={'scope_id':w+'-scope','workspace_id':w,'source_id':'postgres','tables':[{'database':'main','schema':'main','table':t} for t in (parent,child)]}
    ScopeService().save(sc);ScopeService().build(sc['scope_id']);p2=Phase2Service()
    r=next(r for r in p2.relationships(w) if len(r['from_columns'])==2)
    assert r['from_columns']==['tenant','parent_id'] and r['to_columns']==['tenant','id']
    out=p2.validate_relationship(w,r['relationship_id'],'creator')
    assert out['evidence']['target_duplicate_rows']==0 and out['evidence']['matched_rows']==2 and out['evidence']['passed']
    # A duplicate target outside a declared key must fail exactly, regardless of ratio rounding.
    with sqlite3.connect(TEST_DB) as db:
        db.executescript(f'CREATE TABLE duplicate_{token}(tenant INTEGER,id INTEGER);INSERT INTO duplicate_{token} VALUES(1,1),(2,1);')
    # Re-scope with the manually declared composite target, then measure.
    sc['tables'].append({'database':'main','schema':'main','table':'duplicate_'+token});ScopeService().save(sc);ScopeService().build(sc['scope_id'])
    assets={a['table']:a['asset_id'] for a in p2.assets(w)}
    r=p2.create_relationship(w,{'from_asset':assets[child],'to_asset':assets['duplicate_'+token],'from_columns':['tenant','parent_id'],'to_columns':['tenant','id'],'role':'parent'},'creator')
    out=p2.validate_relationship(w,r['relationship_id'],'creator')
    assert out['evidence']['passed']
    approved=p2.review_relationship(w,r['relationship_id'],'approved','Composite role and exact evidence checked','reviewer')
    with sqlite3.connect(TEST_DB) as db:db.execute(f'INSERT INTO duplicate_{token} VALUES(1,1)')
    p2._put('relationship',w,r['relationship_id'],{**approved,'evidence':{**approved['evidence'],'evaluated_at':(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()}})
    refreshed=p2.refresh_relationships(w)
    out=next(x for x in refreshed if x['relationship_id']==r['relationship_id'])
    assert out['evidence']['target_duplicate_rows']==1 and not out['evidence']['passed'] and not out['trusted_for_queries']
    with p2.repo.lock:
        store=p2.repo._local()
        for rows in store.values():
            for key,row in list(rows.items()):
                if row.get('workspace_id')==w or key==w or key.startswith(w+'::'):rows.pop(key)
        p2.repo._save(store)
    with sqlite3.connect(TEST_DB) as db:
        for t in (child,parent,'duplicate_'+token):db.execute('DROP TABLE '+t)


def test_changed_grain_invalidates_metric(business):
    # Replace grain evidence with a measured failing refresh; schema remains identical.
    sem=business.metrics['net_sales']['semantics'];key=__import__('app.services.phase2_service',fromlist=['digest']).digest([business.w,business.order_id,sem['grain']])
    old=business.p2.repo.get('P2_GRAIN',key);business.p2.repo.put('P2_GRAIN',key,{**old,'passed':False,'duplicate_rows':1})
    with pytest.raises(ValueError,match='stale|grain|uncertified'):AdvancedQueryService().compile(business.w,business.release,plan(business))


def test_relative_periods_have_explicit_half_open_bounds():
    assert AdvancedQueryService.period_bounds('last_month',today=date(2026,1,15))==('2025-12-01','2026-01-01')
    assert AdvancedQueryService.period_bounds('last_quarter',today=date(2026,1,15))==('2025-10-01','2026-01-01')
    with pytest.raises(ValueError):AdvancedQueryService.period_bounds('fiscal_year')


def test_registry_ids_are_shared_by_authoring_graph_and_query(business):
    studio=SemanticStudioService();metric=next(m for m in studio.objects(business.w,'metric') if m['id']=='net_sales')
    schema=AdvancedQueryService().schema(business.w,business.release)
    context=MarketService().context(business.w)
    assert metric['id']==schema['metrics']['net_sales']['object_id']
    assert context['metrics']['net_sales']['semantics']==metric['semantics']
    rels=SemanticRegistryService().graph_relationships(business.w)
    assert {r['relationship_id'] for r in rels}=={r['relationship_id'] for r in schema['relationships']}


def test_guided_preparation_is_repeatable_and_does_not_auto_certify(business):
    service=GuidedOnboardingService();first=service.prepare(business.w,'creator','steward')
    second=service.prepare(business.w,'creator','steward')
    assert first['certified_automatically']==0 and second['objects_proposed']==0 and second['contracts_prepared']==0
    drafts=[o for o in second['status']['objects'] if o['created_from']=='schema_inference']
    assert drafts and all(o['status']=='draft' for o in drafts)


def test_report_refresh_uses_same_pinned_formula_and_permissions(business,bedrock_contract):
    bedrock_contract.plan=plan(business);svc=ReportService();r=svc.create(business.w,'Revenue','',ADMIN)
    widget=svc.add_widget(r['report_id'],'Revenue','Net revenue','kpi',ADMIN,business.release)
    assert widget['release_id']==business.release and widget['structured_plan']==bedrock_contract.plan
    before=len(bedrock_contract.calls);rendered=svc.render(r['report_id'],ADMIN)
    assert rendered['rendered_widgets'][0]['query']['result']['rows']==[{'value':350.0}]
    assert len(bedrock_contract.calls)==before  # Saved LLM plan, recompiled with live evidence; no offline planner.
    unauthorized=UserContext('outsider',('analyst',),{'workspace':'another-workspace'})
    with pytest.raises(PermissionError):svc.render(r['report_id'],unauthorized)


def test_business_benchmark_compares_real_results_and_catches_wrong_metrics(business,bedrock_contract):
    service=BusinessBenchmarkService();sql=f'SELECT SUM(amount-refund) AS reference FROM "main"."{business.orders}" WHERE status=\'Complete\''
    for q in ('Net sales','Revenue'):
        service.save(business.w,{'release_id':business.release,'question':q,'reference_asset_id':business.order_id,'reference_sql':sql},'reviewer')
    bedrock_contract.plan=plan(business)
    out=service.run(business.w,business.release)
    assert out['counts']=={'passed':2,'failed':0,'blocked':0}
    bedrock_contract.plan=plan(business,'order_count')
    assert service.run(business.w,business.release)['counts']['failed']==2


def test_unified_api_and_connectivity_status(business,bedrock_contract):
    bedrock_contract.plan=plan(business);client=TestClient(app)
    status=client.get('/api/llm/status',headers=H).json();assert status['ready'] and status['offline_fallback'] is False
    result=client.post('/api/phase4/unified/ask?workspace='+business.w,headers=H,json={'release_id':business.release,'question':'Revenue'})
    assert result.status_code==200,result.text
    assert result.json()['rows']==[{'value':350.0}]
    outsider=client.post('/api/phase4/unified/ask?workspace='+business.w,headers={'X-Roles':'analyst','X-Workspace':'other'},json={'release_id':business.release,'question':'Revenue'})
    assert outsider.status_code==403


def test_http_structured_execution_cannot_bypass_llm(business):
    response=TestClient(app).post('/api/phase4/advanced/ask?workspace='+business.w,headers=H,
        json={'release_id':business.release,'question':'Revenue','structured_plan':plan(business),'execute':True})
    assert response.status_code==400 and 'preview-only' in response.text


def test_exact_date_filter_and_declared_time_role(business):
    p=plan(business,filters=[{'asset_id':business.order_id,'column':'order_date','op':'gte','value':'2026-10-01'}])
    out=AdvancedQueryService().run(business.w,business.release,'October net sales',plan=p,execute=True)
    assert out['rows']==[{'value':260.0}]
    p=plan(business,'order_count',filters=[{'asset_id':business.order_id,'column':'order_date','op':'relative_period','value':'last_month'}])
    with pytest.raises(ValueError,match='approved metric time role'):AdvancedQueryService().compile(business.w,business.release,p)


def test_invalid_executable_predicates_and_raw_formulas_fail_at_authoring(business):
    from app.services.business_semantics import validate_semantics
    b=business.metrics['net_sales']['binding'];sem=business.metrics['net_sales']['semantics']
    for change in [{'expression':{'sql':'SUM(amount)'}},{'filters':[{'column':'status','op':'eq','value':None}]},
                   {'filters':[{'column':'amount','op':'gt','value':float('nan')}]},
                   {'time':{'column':'order_date','timezone':'unknown/timezone'}},
                   {'additivity':'non_additive'}]:
        with pytest.raises(ValueError):validate_semantics('measure',{**sem,**change},b)


def test_semantic_review_requires_true_booleans(business,bedrock_contract):
    bedrock_contract.plan=plan(business)
    bedrock_contract.review={'complete':'true','correct':True,'preserved_context':True,'unresolved':[]}
    with pytest.raises(ValueError,match='explicit boolean'):UnifiedAskService().ask(business.w,business.release,'Revenue')


def test_benchmark_missing_llm_cannot_pass_negative_cases(business,monkeypatch):
    service=BusinessBenchmarkService()
    service.save(business.w,{'release_id':business.release,'question':'Unknown measure','expected':'refuse'},'reviewer')
    monkeypatch.setattr(LLMPlannerService,'status',lambda self:{'ready':False})
    run=service.run(business.w,business.release)
    assert run['status']=='blocked' and run['counts']=={'passed':0,'failed':0,'blocked':1}


def test_local_store_cache_does_not_persist_unwritten_mutation():
    repo=ControlRepository();key='isolation-'+uuid4().hex
    repo.put('BUSINESS_CASE',key,{'nested':{'value':1}})
    row=repo.get('BUSINESS_CASE',key);row['nested']['value']=2
    assert repo.get('BUSINESS_CASE',key)['nested']['value']==1
    repo.delete('BUSINESS_CASE',key)


def test_sample_source_can_be_disabled_by_configuration(monkeypatch):
    from dataclasses import replace
    from app.services.data_source_service import DataSourceService
    service=DataSourceService();service.s=replace(service.s,enable_sample_execution=False)
    with pytest.raises(ValueError,match='Contoso sample source is disabled'):service.execute('contoso','SELECT COUNT(*) FROM Orders','contoso_demo')


def test_sql_safety_distinguishes_data_from_statement_tokens():
    from app.services.sql_safety import validate_read_only_sql
    assert validate_read_only_sql("SELECT COUNT(*) FROM orders WHERE status='DROP; DELETE'")[0]
    assert not validate_read_only_sql('SELECT COUNT(*) FROM orders; DELETE FROM orders')[0]
    assert not validate_read_only_sql("SELECT COUNT(*) FROM orders WHERE status='unterminated")[0]


def test_followup_adds_filter_without_dropping_other_constraints(business,bedrock_contract):
    previous=plan(business,'order_count',filters=[{'asset_id':business.order_id,'column':'status','op':'eq','value':'Complete'}])
    rid=business.relationships['customer_id'];q='Only Berlin'
    bedrock_contract.plan=plan(business,'order_count',join_relationship_ids=[rid],filters=[{'asset_id':business.customer_id,'column':'city','op':'eq','value':'Berlin'}])
    bedrock_contract.intent={'mode':'followup','change_fields':['filters'], 'clauses':[{'start':0,'end':len(q),'text':q,'targets':['/filters/0']}]}
    out=UnifiedAskService().ask(business.w,business.release,q,previous_plan=previous)
    assert out['rows']==[{'value':1}]
    assert previous['filters'][0] in out['structured_plan']['filters']


def test_followup_filter_removal_needs_exact_clause_and_review(business,bedrock_contract):
    previous=plan(business,'order_count',filters=[{'asset_id':business.order_id,'column':'status','op':'eq','value':'Complete'}])
    q='Include all statuses';bedrock_contract.plan=plan(business,'order_count')
    bedrock_contract.intent={'mode':'followup','change_fields':['filters'],'remove_filter_indices':[0],
        'clauses':[{'start':0,'end':len(q),'text':q,'targets':['/previous/filters/0']}]}
    out=UnifiedAskService().ask(business.w,business.release,q,previous_plan=previous)
    assert out['rows']==[{'value':4}] and out['structured_plan']['filters']==[]
    bedrock_contract.intent['clauses'][0]['targets']=['/metrics/0']
    with pytest.raises(ValueError,match='removed filter'):UnifiedAskService().ask(business.w,business.release,q,previous_plan=previous)


def test_composite_join_executes_both_keys_without_fanout(business):
    parent='composite_parent_'+business.orders;child='composite_child_'+business.orders
    with sqlite3.connect(TEST_DB) as db:
        db.executescript(f'''CREATE TABLE {parent}(tenant INTEGER,id INTEGER,label TEXT,PRIMARY KEY(tenant,id));
        CREATE TABLE {child}(row_id INTEGER PRIMARY KEY,tenant INTEGER,parent_id INTEGER,FOREIGN KEY(tenant,parent_id) REFERENCES {parent}(tenant,id));
        INSERT INTO {parent} VALUES(1,5,'A'),(1,6,'B'),(2,5,'C');INSERT INTO {child} VALUES(10,1,5),(11,2,5);''')
    try:
        scope=business.p2.scope(business.w)
        scope['tables']+= [{'database':'main','schema':'main','table':t} for t in (parent,child)]
        ScopeService().save(scope);ScopeService().build(scope['scope_id'])
        assets={a['table']:a['asset_id'] for a in business.p2.assets(business.w)}
        for table in (parent,child):
            aid=assets[table];business.p2.profile(business.w,aid,'standard','creator',200)
            business.p2.save_contract(business.w,aid,{'owner':'steward'},'creator')
            business.p2.transition_contract(business.w,aid,'reviewed','Schema reviewed','creator')
            business.p2.transition_contract(business.w,aid,'certified','Measured profile approved','reviewer')
            columns=[c['name'] for c in business.p2.metadata(business.w,aid)['columns']]
            oid='entity_'+table[-20:];o=business.p3.create(business.w,{'object_id':oid,'kind':'entity','label':table,'description':'Composite key fixture','binding':{'asset_id':aid,'columns':columns}},'creator')
            o=business.p3.transition(business.w,oid,'reviewed','Composite meaning reviewed','creator',o['version'])
            business.p3.transition(business.w,oid,'certified','Independent role approval','reviewer',o['version'])
        o=business.p3.create(business.w,{'object_id':'composite_count','kind':'measure','label':'Composite child count','description':'One child row',
            'binding':{'asset_id':assets[child],'columns':['row_id']},'semantics':{'grain':['row_id'],'aggregation':'count','unit':'records','additivity':'additive'}},'creator')
        o=business.p3.transition(business.w,o['object_id'],'reviewed','Count meaning reviewed','creator',o['version'])
        business.p3.transition(business.w,o['object_id'],'certified','Independent count approval','reviewer',o['version'])
        r=next(r for r in business.p2.relationships(business.w) if r['from_asset']==assets[child] and r['to_asset']==assets[parent])
        business.p2.validate_relationship(business.w,r['relationship_id'],'creator')
        business.p2.review_relationship(business.w,r['relationship_id'],'approved','Composite parent role approved','reviewer')
        business.p3.publish_snapshot(business.w,'composite-v1','Composite execution baseline','reviewer')
        release=Phase4Service().promote(business.w,'composite-v1','reviewer')['release_id']
        p=plan(business,'composite_count',base_asset_id=assets[child],join_relationship_ids=[r['relationship_id']],dimensions=[{'asset_id':assets[parent],'column':'label'}])
        out=AdvancedQueryService().run(business.w,release,'Composite fixture contract',plan=p,execute=True)
        assert {row['d1']:row['value'] for row in out['rows']}=={'A':1,'C':1}
        assert 't0."tenant" = t1."tenant" AND t0."parent_id" = t1."id"' in out['plan']['sql']
    finally:
        with sqlite3.connect(TEST_DB) as db:db.execute('DROP TABLE '+child);db.execute('DROP TABLE '+parent)


def test_local_api_and_evidence_worker_writes_do_not_lose_records():
    import subprocess,sys
    marker='process-'+uuid4().hex
    code="from app.repositories.control_repository import ControlRepository;import sys;r=ControlRepository();[r.put('CONTROL_TEST',sys.argv[1]+str(i),{'index':i}) for i in range(12)]"
    jobs=[subprocess.Popen([sys.executable,'-c',code,marker+str(n)+'-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for n in range(2)]
    for job in jobs:
        stdout,stderr=job.communicate(timeout=40)
        assert job.returncode==0,stderr
    repo=ControlRepository()
    assert all(repo.get('CONTROL_TEST',marker+str(n)+'-'+str(i))=={**repo.get('CONTROL_TEST',marker+str(n)+'-'+str(i)),'index':i} for n in range(2) for i in range(12))
    for n in range(2):
        for i in range(12):repo.delete('CONTROL_TEST',marker+str(n)+'-'+str(i))


def test_failed_write_cannot_leave_an_uncommitted_approval_in_cache(monkeypatch):
    from pathlib import Path
    repo=ControlRepository();key='failed-write-'+uuid4().hex
    repo.put('CONTROL_TEST',key,{'status':'draft'})
    original=Path.write_text
    def fail_temp(path,*args,**kwargs):
        if path==repo.path.with_suffix('.json.tmp'):raise OSError('Simulated disk failure')
        return original(path,*args,**kwargs)
    with monkeypatch.context() as m:
        m.setattr(Path,'write_text',fail_temp)
        with pytest.raises(OSError):repo.put('CONTROL_TEST',key,{'status':'certified'})
        assert repo.get('CONTROL_TEST',key)['status']=='draft'
    repo.delete('CONTROL_TEST',key)


def test_value_mappings_cannot_leak_across_assets_with_same_column_name(business):
    base=business.metrics['net_sales'];sem={**base['semantics'],'value_mappings':{'status':{'finished':'Complete'}}}
    o=business.p3.create(business.w,{'kind':'measure','object_id':'mapped_net','label':'Mapped net sales','description':'Fact status vocabulary',
        'binding':base['binding'],'semantics':sem},'creator')
    o=business.p3.transition(business.w,o['object_id'],'reviewed','Status code meaning checked','creator',o['version'])
    business.p3.transition(business.w,o['object_id'],'certified','Independent code review','reviewer',o['version'])
    business.p3.publish_snapshot(business.w,'codes-v1','Scoped code meanings','reviewer')
    release=Phase4Service().promote(business.w,'codes-v1','reviewer')['release_id']
    p=plan(business,'mapped_net',join_relationship_ids=[business.relationships['customer_id']],filters=[{'asset_id':business.customer_id,'column':'status','op':'eq','value':'finished'}])
    out=AdvancedQueryService().run(business.w,release,'Fixture: parent status code finished',plan=p,execute=True)
    assert out['rows']==[{'value':90.0}]  # Parent code 'finished' belongs to Berlin; fact alias 'finished' means Complete.
