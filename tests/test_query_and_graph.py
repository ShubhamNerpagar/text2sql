from app.services.query_service import QueryService
from app.services.plan_service import PlanService
from app.services.sql_safety import validate_read_only_sql
from app.services.graph_rag_service import GraphRAGService
from app.services.security_service import SecurityService, UserContext


def test_count_query_executes_against_connected_source(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'order_count')
    r=QueryService().run('How many orders are there?',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert r['status']=='success' and r['data_source']=='postgres'
    assert validate_read_only_sql(r['sql'])[0] and r['result']['rows']==[{'value':4}]
    assert r['semantic_review']['passed'] and r['routing']['offline_fallback'] is False


def test_generated_dimension_can_drive_breakdown(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'order_count',dimensions=[{'asset_id':business.order_id,'column':'status'}])
    r=QueryService().run('How many orders by status?',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert {x['d1']:x['value'] for x in r['result']['rows']}=={'Cancelled':1,'Complete':3}


def test_graph_search_returns_physical_and_semantic_context():
    r=GraphRAGService().search('orders status','test-lab',12,1)
    assert r['results']
    assert any(x['node_type'] in {'entity','dimension','table','column'} for x in r['results'])
    assert any('orders' in x.lower() for x in r['tables'])


def test_graph_explorer_omits_embeddings_from_browser_payload():
    d=GraphRAGService().explorer('test-lab',limit=100)
    assert d['nodes'] and d['edges']
    assert all('embedding' not in n for n in d['nodes'])


def test_pii_column_policy_blocks_analyst():
    sec=SecurityService(); u=UserContext('analyst',('analyst',),{})
    assert not sec.column_allowed(u,'test-lab','main','customers','email')
    ok,_=sec.enforce_sql('SELECT email FROM main.customers',u,'test-lab')
    assert ok is False


def test_read_only_sql_policy():
    assert validate_read_only_sql('SELECT * FROM main.orders')[0]
    assert not validate_read_only_sql('DROP TABLE orders')[0]
