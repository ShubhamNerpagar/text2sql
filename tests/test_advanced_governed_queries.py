"""Multi-table compiler controls with explicit synthetic execution and adversarial negative controls."""
from uuid import uuid4
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service
from app.services.scope_service import ScopeService
from app.services.advanced_query_service import AdvancedQueryService
from app.repositories.control_repository import ControlRepository

client=TestClient(app)
W='advanced-'+uuid4().hex[:9]
H={'X-Roles':'semantic_admin','X-User':'creator'}

def url(name):return f'/api/phase4/advanced/{name}?workspace={W}'

@pytest.fixture(scope='module')
def env():
    names=['Sales','Customer','Orders','Store']
    sc={'scope_id':W+'-scope','workspace_id':W,'source_id':'contoso',
        'tables':[{'database':'contoso_demo','table':table} for table in names]}
    ScopeService().save(sc);ScopeService().build(sc['scope_id'])
    p2=Phase2Service();ids={a['table']:a['asset_id'] for a in p2.assets(W)}
    for table in names:
        aid=ids[table];p2.profile(W,aid,'standard','creator',100)
        p2.save_contract(W,aid,{'owner':'demo steward'},'creator')
        p2.transition_contract(W,aid,'reviewed','Verified reference tables','creator')
        p2.transition_contract(W,aid,'certified','Validated profile and owner','reviewer')
    expected=[('Sales','Customer','CustomerKey','CustomerKey'),('Sales','Orders','OrderKey','OrderKey'),('Orders','Store','StoreKey','StoreKey')]
    rel={}
    for src,dst,fc,tc in expected:
        found=next(r for r in p2.relationships(W) if r['from_asset']==ids[src] and r['to_asset']==ids[dst] and r['from_column']==fc and r['to_column']==tc)
        checked=p2.validate_relationship(W,found['relationship_id'],'creator')
        assert checked['evidence']['target_uniqueness']==1.0
        p2.review_relationship(W,found['relationship_id'],'approved','Unique target key measured','reviewer')
        rel[src,dst]=found['relationship_id']
    p3=Phase3Service();metric_ids={}
    definitions=[('Sales','measure',['SalesKey','NetAmount','CustomerKey','OrderKey'],'Net sales amount'),
        ('Customer','entity',['CustomerKey','Segment'],'Customer dimension'),
        ('Orders','entity',['OrderKey','StoreKey'],'Order dimension'),
        ('Store','entity',['StoreKey','StoreName'],'Retail store dimension')]
    for table,kind,columns,definition in definitions:
        obj=p3.create(W,{'kind':kind,'label':table+' certified',
            'description':'Certified '+table+' semantics','definition':definition,
            'binding':{'asset_id':ids[table],'columns':columns},
            'semantics':{'grain':['SalesKey'],'aggregation':'sum','expression':{'column':'NetAmount'},'unit':'USD','additivity':'additive'} if kind=='measure' else {}},'creator')
        obj=p3.transition(W,obj['object_id'],'reviewed','Physical schema and grain checked','creator',obj['version'])
        obj=p3.transition(W,obj['object_id'],'certified','Independent semantic review passed','reviewer',obj['version'])
        if kind=='measure':metric_ids['sum']=obj['object_id']
    for table,key in [('Sales','SalesKey'),('Orders','OrderKey')]:
        obj=p3.create(W,{'kind':'measure','object_id':'count_'+table.lower(),'label':table+' count',
            'description':'Count at one '+table+' record grain','binding':{'asset_id':ids[table],'columns':[key]},
            'semantics':{'grain':[key],'aggregation':'count','unit':'records','additivity':'additive'}},'creator')
        obj=p3.transition(W,obj['object_id'],'reviewed','Record grain checked','creator',obj['version'])
        obj=p3.transition(W,obj['object_id'],'certified','Independent grain approval','reviewer',obj['version'])
        metric_ids[table]=obj['object_id']
    p3.publish_snapshot(W,'complex-v1','Advanced analytics baseline','reviewer')
    release=Phase4Service().promote(W,'complex-v1','creator')
    return {'ids':ids,'relationships':rel,'release_id':release['release_id'],'p2':p2,'metric_ids':metric_ids}

def plan(env):
    ids=env['ids'];rel=env['relationships']
    return {'base_asset_id':ids['Sales'],'join_relationship_ids':[rel['Sales','Customer']],
        'dimensions':[{'asset_id':ids['Customer'],'column':'Segment'}],
        'metrics':[{'metric_id':env['metric_ids']['sum'],'alias':'total_sales'},
                    {'metric_id':env['metric_ids']['Sales'],'alias':'sale_rows'}],
        'filters':[],'having':[{'metric':'total_sales','op':'gt','value':0}],
        'order_by':[{'alias':'total_sales','direction':'desc'}],'limit':20}

def test_schema_approved_relationships_and_live_execution(env):
    r=client.get(url('schema')+'&release_id='+env['release_id'],headers=H)
    assert r.status_code==200,r.text
    assert len(r.json()['assets'])==4 and len(r.json()['relationships'])==3
    response=client.post(url('ask'),json={'release_id':env['release_id'], 'question':'Total sales by customer segment',
        'structured_plan':plan(env),'execute':False},headers=H)
    assert response.status_code==200,response.text
    assert not response.json()['executed']
    out=AdvancedQueryService().run(W,env['release_id'],'Total sales by customer segment',plan=plan(env),execute=True)
    assert out['executed'] and out['model_used'] is False
    assert 'LEFT JOIN' in out['plan']['sql'] and 'GROUP BY' in out['plan']['sql']
    assert 'HAVING' in out['plan']['sql'] and 'ORDER BY' in out['plan']['sql']
    assert sum(row['sale_rows'] for row in out['rows'])>0
    assert all(row['total_sales']>0 for row in out['rows'])
    assert 'Sales' in [t['table'] for t in out['plan']['tables']]


def test_four_table_join_with_filter_and_grouping(env):
    x=plan(env);x['join_relationship_ids']=[env['relationships']['Sales','Orders'],env['relationships']['Orders','Store'],env['relationships']['Sales','Customer']]
    x['dimensions']=[{'asset_id':env['ids']['Store'],'column':'StoreName'},
                     {'asset_id':env['ids']['Customer'],'column':'Segment'}]
    x['filters']=[{'asset_id':env['ids']['Customer'],'column':'Segment','op':'in','value':['Business','Retail']}]
    x['having']=[];x['order_by']=[]
    resp=client.post(url('ask'),json={'release_id':env['release_id'],'question':'Sales by store and segment',
        'structured_plan':x,'execute':False},headers=H)
    assert resp.status_code==200,resp.text
    assert resp.json()['plan']['sql'].count('LEFT JOIN')==3
    assert not resp.json()['executed']
    assert AdvancedQueryService().run(W,env['release_id'],'Fixture join verification',plan=x,execute=True)['rows']


def test_adversarial_plan_validation(env):
    service=AdvancedQueryService();p=plan(env);release=env['release_id']
    def denied(data):
        with pytest.raises(ValueError):service.compile(W,release,data)
    t=deepcopy(p);t['sql']='DROP TABLE Orders';denied(t)
    t=deepcopy(p);t['metrics'][0]['column']='PasswordHash';denied(t)
    t=deepcopy(p);t['join_relationship_ids']=['invented-relation'];denied(t)
    t=deepcopy(p);t['join_relationship_ids']=[];denied(t)
    t=deepcopy(p);t['base_asset_id']=env['ids']['Customer'];denied(t) # backwards fact-to-dimension
    t=deepcopy(p);t['filters']=[{'asset_id':env['ids']['Customer'],'column':'Segment','op':'eq','value':"x' OR 1=1 --"}]
    compiled=service.compile(W,release,t)
    assert "'x'' OR 1=1 --'" in compiled['sql']
    t=deepcopy(p);t['metrics'][0]['alias']='x); DROP TABLE y; --';denied(t)
    t=deepcopy(p);t['limit']=100000;denied(t)
    t=deepcopy(p);t['metrics'][0]['asset_id']=env['ids']['Customer'];t['metrics'][0]['column']='CustomerKey';denied(t)


def test_unapproved_and_stale_relationships_fail_closed(env):
    service=AdvancedQueryService();p=plan(env);rid=env['relationships']['Sales','Customer']
    rel=env['p2']._get('relationship',W,rid)
    env['p2']._put('relationship',W,rid,{**rel,'trusted_for_queries':False})
    try:
        with pytest.raises(ValueError):service.compile(W,env['release_id'],p)
    finally:env['p2']._put('relationship',W,rid,rel)
    target=env['ids']['Customer'];contract=env['p2'].contracts(W,target)[0]
    env['p2'].transition_contract(W,target,'draft','Source contract reopened','creator')
    try:
        with pytest.raises(ValueError,match='stale'):
            service.compile(W,env['release_id'],p)
    finally:
        env['p2'].transition_contract(W,target,'reviewed','Contract reviewed again','creator')
        env['p2'].transition_contract(W,target,'certified','Contract renewed','reviewer')


def test_bedrock_requires_verified_model_and_cross_workspace_denied(env):
    response=client.post(url('ask'),json={'release_id':env['release_id'],
        'question':'Total sales by customer segment','use_bedrock':True},headers=H)
    assert response.status_code==400,response.text
    other=client.post('/api/phase4/advanced/ask?workspace=unrelated-workspace',json={
        'release_id':env['release_id'],'question':'Sales by segment','structured_plan':plan(env)},headers=H)
    assert other.status_code in (400,404)
    assert client.get(url('schema')+'&release_id='+env['release_id'],headers={'X-Roles':'analyst'}).status_code==403


def test_model_json_only_and_schema_guards(env,bedrock_contract,monkeypatch):
    from app.adapters.aws import AwsAdapter
    bedrock_contract.plan=plan(env)
    out=AdvancedQueryService().run(W,env['release_id'],'Total sales by customer segment',use_bedrock=True,execute=True)
    assert out['model_used'] and out['rows'] and out['plan']['join_evidence']
    monkeypatch.setattr(AwsAdapter,'invoke_text',lambda self,prompt,**kwargs:'SELECT * FROM Sales')
    with pytest.raises(ValueError,match='structured JSON'):
        AdvancedQueryService().run(W,env['release_id'],'Total sales by customer segment',use_bedrock=True)


def test_unified_requires_model_for_counts_and_joins(env,monkeypatch):
    from app.services.llm_planner_service import LLMPlannerService
    monkeypatch.setattr(LLMPlannerService,'status',lambda self:{'ready':False})
    for question in ['Count Orders','Total Sales by Customer Segment']:
        r=client.post(f'/api/phase4/unified/ask?workspace={W}',json={'release_id':env['release_id'],'question':question},headers=H)
        assert r.status_code==400 and 'LLM_CONNECTION_REQUIRED' in r.text


def test_unified_four_tables_and_followup(env,bedrock_contract):
    url=f'/api/phase4/unified/ask?workspace={W}'
    x=plan(env);x['join_relationship_ids']=[env['relationships']['Sales','Orders'],env['relationships']['Orders','Store'],env['relationships']['Sales','Customer']]
    x['dimensions']=[{'asset_id':env['ids']['Store'],'column':'StoreName'},{'asset_id':env['ids']['Customer'],'column':'Segment'}]
    bedrock_contract.plan=x
    four=client.post(url,json={'release_id':env['release_id'],'question':'Total Sales by store and segment'},headers=H)
    assert four.status_code==200,four.text
    assert four.json()['plan']['sql'].count('LEFT JOIN')==3
    bedrock_contract.plan=plan(env)
    base=client.post(url,json={'release_id':env['release_id'],'question':'Total Sales by Customer Segment'},headers=H)
    assert base.status_code==200,base.text
    q='Now by StoreName';bedrock_contract.plan=x
    bedrock_contract.intent={'mode':'followup','change_fields':['dimensions','join_relationship_ids'],'clauses':[{'start':0,'end':len(q),'text':q,'targets':['/dimensions/0']}]}
    follow=client.post(url,json={'release_id':env['release_id'],'question':q,'previous_plan':base.json()['structured_plan']},headers=H)
    assert follow.status_code==200,follow.text
    assert follow.json()['plan']['sql'].count('LEFT JOIN')==3
    assert follow.json()['structured_plan']['metrics']==base.json()['structured_plan']['metrics']


def test_unified_safety_and_workspace_guards(env,monkeypatch):
    from app.services.llm_planner_service import LLMPlannerService
    monkeypatch.setattr(LLMPlannerService,'status',lambda self:{'ready':False})
    url=f'/api/phase4/unified/ask?workspace={W}'
    for question in ['DELETE FROM Sales','Total Sales last 12 months','Count InventedTable',
                     'Now by StoreName','Total Sales by UnknownDimension']:
        r=client.post(url,json={'release_id':env['release_id'],'question':question},headers=H)
        assert r.status_code==400,(question,r.text)
    denied=client.post(url,json={'release_id':env['release_id'],'question':'Count Orders'},headers={'X-Roles':'analyst'})
    assert denied.status_code==403
    different=client.post('/api/phase4/unified/ask?workspace=unrelated-workspace',
          json={'release_id':env['release_id'],'question':'Count Orders'},headers=H)
    assert different.status_code in (400,404)
    # Never trust client-supplied previous plans without recompiling them against the release.
    invalid=client.post(url,json={'release_id':env['release_id'],'question':'Now by StoreName',
        'previous_plan':{'base_asset_id':env['ids']['Sales'],'metrics':[{'function':'count','asset_id':env['ids']['Sales'],'column':'*','alias':'count'}],
        'join_relationship_ids':['made-up-join']}},headers=H)
    assert invalid.status_code==400


def test_unified_verified_bedrock_plan_is_compiled(env,bedrock_contract):
    bedrock_contract.plan=plan(env)
    r=client.post(f'/api/phase4/unified/ask?workspace={W}',json={'release_id':env['release_id'],'question':'Revenue by customer segment'},headers=H)
    assert r.status_code==200,r.text
    assert r.json()['planner']=='bedrock' and r.json()['model_id']=='contract-semantic_planning'
    assert r.json()['executed'] and r.json()['rows'] and r.json()['semantic_review']['passed']


def test_unified_denies_active_row_policies(env,monkeypatch):
    from app.api import routes
    monkeypatch.setattr(routes.queries.security,'row_predicates',lambda user,workspace:[{'column':'TenantKey','operator':'eq','value':'x'}])
    denied=client.post(f'/api/phase4/unified/ask?workspace={W}',json={
        'release_id':env['release_id'],'question':'Count Orders'},headers=H)
    assert denied.status_code==403
