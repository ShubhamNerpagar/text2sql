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


@pytest.fixture
def business():
    token=uuid4().hex[:8];w='business-'+token;orders='orders_'+token;customers='customers_'+token
    with sqlite3.connect(TEST_DB) as db:
        db.executescript(f'''
        CREATE TABLE {customers}(customer_id INTEGER PRIMARY KEY, segment TEXT, city TEXT, credit_limit REAL, status TEXT);
        CREATE TABLE {orders}(order_id INTEGER PRIMARY KEY, customer_id INTEGER, shipping_customer_id INTEGER,
            amount REAL, refund REAL, weight REAL, status TEXT, order_date DATE,
            FOREIGN KEY(customer_id) REFERENCES {customers}(customer_id),
            FOREIGN KEY(shipping_customer_id) REFERENCES {customers}(customer_id));
        INSERT INTO {customers} VALUES(1,'Retail','Berlin',1000,'finished'),(2,'Business','Paris',500,'Complete');
        INSERT INTO {orders} VALUES
            (1,1,2,100,10,1,'Complete','2026-09-01'),
            (2,1,1,50,0,3,'Cancelled','2026-09-15'),
            (3,2,2,200,20,2,'Complete','2026-10-01'),
            (4,2,1,80,0,4,'Complete','2026-10-05');
        ''')
    scope={'scope_id':w+'-scope','workspace_id':w,'source_id':'postgres',
        'tables':[{'database':'main','schema':'main','table':t} for t in (orders,customers)]}
    ScopeService().save(scope);ScopeService().build(scope['scope_id'])
    p2=Phase2Service();p3=Phase3Service();ids={a['table']:a['asset_id'] for a in p2.assets(w)}
    for aid in ids.values():
        p2.profile(w,aid,'standard','creator',200)
        p2.save_contract(w,aid,{'owner':'data steward'},'creator')
        p2.transition_contract(w,aid,'reviewed','Schema and definitions reviewed','creator')
        p2.transition_contract(w,aid,'certified','Measured evidence approved','reviewer')
    metrics={}
    def create(kind,oid,aid,sem=None):
        columns=[c['name'] for c in p2.metadata(w,aid)['columns']]
        o=p3.create(w,{'kind':kind,'object_id':oid,'label':oid.replace('_',' '),'synonyms':['Revenue'] if oid=='net_sales' else [],
            'description':'Approved business definition','binding':{'asset_id':aid,'columns':columns},'semantics':sem or {},'definition':'Business owner reviewed'},'creator')
        o=p3.transition(w,oid,'reviewed','Business meaning reviewed','creator',o['version'])
        return p3.transition(w,oid,'certified','Independent evidence review','reviewer',o['version'])
    order_id=ids[orders];customer_id=ids[customers]
    create('entity','orders',order_id,{'grain':['order_id']})
    create('entity','customers',customer_id,{'grain':['customer_id']})
    complete=[{'column':'status','op':'eq','value':'Complete'}]
    defs={
        'order_count':{'aggregation':'count','unit':'records','additivity':'additive'},
        'net_sales':{'aggregation':'sum','expression':{'op':'subtract','args':[{'column':'amount'},{'column':'refund'}]},'unit':'USD','additivity':'additive','filters':complete,'time':{'column':'order_date','timezone':'UTC','calendar':'gregorian'}},
        'customer_count':{'aggregation':'count_distinct','expression':{'column':'customer_id'},'unit':'customers','additivity':'non_additive'},
        'weighted_amount':{'aggregation':'avg','expression':{'column':'amount'},'weight_column':'weight','unit':'USD','additivity':'non_additive','filters':complete},
        'refund_ratio':{'aggregation':'ratio','numerator':{'aggregation':'sum','expression':{'column':'refund'}},'denominator':{'aggregation':'sum','expression':{'column':'amount'}},'unit':'ratio','additivity':'non_additive','filters':complete},
    }
    for mid,sem in defs.items():metrics[mid]=create('measure',mid,order_id,{'grain':['order_id'],**sem})
    metrics['credit_limit']=create('measure','credit_limit',customer_id,{'grain':['customer_id'],'aggregation':'sum','expression':{'column':'credit_limit'},'unit':'USD','additivity':'additive'})
    create('business_concept','completed_orders',order_id,{'filters':complete})
    relationships={}
    for r in p2.relationships(w):
        if r['from_asset']!=order_id:continue
        assert r['origin']=='declared_foreign_key'
        measured=p2.validate_relationship(w,r['relationship_id'],'creator');assert measured['evidence']['target_duplicate_rows']==0
        p2.review_relationship(w,r['relationship_id'],'approved','Exact unique target keys and meaning reviewed','reviewer')
        relationships[r['from_column']]=r['relationship_id']
    p3.publish_snapshot(w,'v1','Business benchmark baseline','reviewer');release=Phase4Service().promote(w,'v1','reviewer')['release_id']
    yield SimpleNamespace(w=w,order_id=order_id,customer_id=customer_id,orders=orders,customers=customers,p2=p2,p3=p3,metrics=metrics,relationships=relationships,release=release)
    # Keep each integration fixture isolated from catalog discovery and the local
    # control store, including deliberately invalidated evidence in negative tests.
    with p2.repo.lock:
        store=p2.repo._local()
        for kind,rows in store.items():
            for key,row in list(rows.items()):
                if w in (row.get('workspace_id'),row.get('market'),row.get('workspace')) or key==w or key.startswith(w+'::'):
                    rows.pop(key)
        p2.repo._save(store)
    with sqlite3.connect(TEST_DB) as db:
        db.execute('DROP TABLE '+orders);db.execute('DROP TABLE '+customers)


def plan(b,metric='net_sales',**changes):
    return {'base_asset_id':b.order_id,'metrics':[{'metric_id':metric,'alias':'value'}],
        'dimensions':[],'concept_ids':[],'join_relationship_ids':[],'filters':[],'having':[],'order_by':[],'limit':50,**changes}


@pytest.fixture
def bedrock_contract(monkeypatch):
    repo=ControlRepository()
    for task in ('semantic_planning','semantic_verification'):repo.put('MODEL_PROBE','contract-'+task,{'status':'verified'})
    monkeypatch.setattr(BedrockModelService,'chosen_model',lambda self,task='ask':'contract-'+task)
    controller=SimpleNamespace(plan=None,clarification=None,calls=[],review={'complete':True,'correct':True,'preserved_context':True,'unresolved':[]},intent=None)
    def invoke(self,prompt,max_tokens=4000,task='ask'):
        controller.calls.append(task)
        if task=='semantic_verification':return json.dumps(controller.review)
        if controller.clarification:return json.dumps({'clarification':controller.clarification})
        q=json.loads(prompt.split('\nQUESTION: ')[-1])
        intent=controller.intent or {'mode':'new','change_fields':[],
            'clauses':[{'start':0,'end':len(q),'text':q,'targets':['/metrics/0']} ]}
        return json.dumps({'plan':controller.plan,'intent':intent})
    monkeypatch.setattr(AwsAdapter,'invoke_text',invoke)
    return controller
