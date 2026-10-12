from pathlib import Path
from app.services.security_service import UserContext
from app.services.query_service import QueryService
from app.services.semantic_studio_service import SemanticStudioService
from app.services.market_service import MarketService

ROOT=Path(__file__).resolve().parents[1]


def test_dataset_explanation_requires_model_and_never_extracts_rows(business,bedrock_contract):
    bedrock_contract.clarification='Choose a business metric from the certified catalog.'
    r=QueryService().run('What is the data about?',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert r['status']=='needs_clarification' and r['sql'] is None and r['result'] is None
    assert not r['executed'] and r['model_used']


def test_distinct_identifier_question_does_not_fall_back_to_row_count(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'customer_count')
    r=QueryService().run('How many distinct customers?',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert r['status']=='success' and 'COUNT(DISTINCT' in r['sql'].upper()
    assert r['result']['rows']==[{'value':2}]  # Four orders, two customers.


def test_sum_metric_honors_formula_instead_of_count_star(business,bedrock_contract):
    from governed_fixtures import plan
    bedrock_contract.plan=plan(business,'net_sales')
    r=QueryService().run('Total completed net sales?',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert r['status']=='success' and 'SUM(' in r['sql'].upper() and 'COUNT(*)' not in r['sql'].upper()
    assert r['result']['rows']==[{'value':350.0}]


def test_aggregate_without_metric_never_silently_counts_rows(business,bedrock_contract):
    bedrock_contract.clarification='The requested metric is not certified.'
    r=QueryService().run('What is the total banana quantum?',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert r['status']=='needs_clarification' and r['sql'] is None and r['result'] is None


def test_unknown_car_id_question_does_not_return_table_row_count(business,bedrock_contract):
    bedrock_contract.clarification='No certified car metric exists.'
    r=QueryService().run('Give me total car ids',business.w,True,user=UserContext('tester',('semantic_admin',),{}))
    assert r['status']=='needs_clarification' and r['sql'] is None and r['result'] is None


def test_suggestion_promotion_creates_reviewable_drafts(business):
    svc=SemanticStudioService();overview=svc.overview(business.w)
    suggestion=next(x for x in overview['suggestions'] if x.get('type')=='metric_candidate')
    promoted=svc.promote_suggestion(business.w,suggestion['id'],'tester')
    assert promoted['status']=='draft' and promoted['objects']
    assert all(o['status']=='draft' for o in promoted['objects'])
    assert all(o['object_id'] in {x['object_id'] for x in business.p3.objects(business.w)} for o in promoted['objects'])


def test_semantic_tab_navigation_rerenders_active_tab_shell():
    js=(ROOT/'app/static/assets/app.js').read_text()
    assert "setTab(b.dataset.parent,b.dataset.tab)" in js
    assert "state.section=s;state.tab=t;state.navOpen[s]=true" in js
    assert "data-parent=" in js
    assert "navMenu()" in js
    assert "<div class=\"tabs\"" not in js
