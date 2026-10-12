from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import Response
from app.config import get_settings
from app.models import *
from app.services.market_service import MarketService
from app.services.catalog_service import CatalogService
from app.services.relationship_service import RelationshipService
from app.services.description_service import DescriptionService
from app.services.query_service import QueryService
from app.services.dashboard_service import DashboardService
from app.repositories.semantic_repository import SemanticRepository
from app.adapters.aws import AwsAdapter
from app.services.onboarding_service import OnboardingService
from app.services.plan_service import PlanService
from app.services.evaluation_service import EvaluationService
from app.services.learning_service import LearningService
from app.services.value_index_service import ValueIndexService
from app.services.graph_rag_service import GraphRAGService
from app.services.governance_service import GovernanceService
from app.services.release_service import ReleaseService
from app.services.relationship_validation_service import RelationshipValidationService
from app.services.security_service import SecurityService
from app.services.conversation_service import ConversationService
from app.services.branch_service import BranchService
from app.services.lineage_service import LineageService
from app.services.action_service import ActionService
from app.services.data_source_service import DataSourceService
from app.services.ontology_inference_service import OntologyInferenceService
from app.services.mcp_service import MCPService
from app.services.logical_schema_service import LogicalSchemaService
from app.services.feature_classifier import FeatureClassifier
from app.repositories.control_repository import ControlRepository
from app.services.metric_service import MetricService
from app.services.universal_search_service import UniversalSearchService
from app.services.monitor_service import MonitorService
from app.services.capability_service import CapabilityService
from app.services.report_service import ReportService
from app.services.readiness_service import ReadinessService
from app.services.semantic_studio_service import SemanticStudioService
from app.services.workspace_service import WorkspaceService

router=APIRouter(prefix="/api")
markets=MarketService(); catalog=CatalogService(); rels=RelationshipService(); descriptions=DescriptionService(); queries=QueryService(); dashboard=DashboardService(); repo=SemanticRepository(); onboarding=OnboardingService(); plans=PlanService(); evaluations=EvaluationService(); learning=LearningService(); value_index=ValueIndexService(); graphrag=GraphRAGService(); governance=GovernanceService(); releases=ReleaseService(); relationship_validator=RelationshipValidationService(); security=SecurityService(); conversations=ConversationService(); branches=BranchService(); lineage=LineageService(); actions=ActionService(); data_sources=DataSourceService(); inference=OntologyInferenceService(); mcp=MCPService(); logical=LogicalSchemaService(); features=FeatureClassifier(); control=ControlRepository(); metrics=MetricService(); universal=UniversalSearchService(); monitor=MonitorService(); capabilities=CapabilityService(); reports=ReportService(); readiness=ReadinessService(); studio=SemanticStudioService(); workspaces=WorkspaceService()

def user_ctx(request:Request):
    try: return security.context_from_request(request)
    except PermissionError as e: raise HTTPException(401,str(e))

def safe(call):
    try: return call()
    except KeyError as e: raise HTTPException(404,str(e))
    except PermissionError as e: raise HTTPException(403,str(e))
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception as e:
        if get_settings().is_production: raise HTTPException(500,'Request could not be completed.') from None
        raise HTTPException(400,str(e))

@router.get('/health')
def health():
    s=get_settings(); base={'ok':True,'app':s.app_name,'version':'8.4.0','mode':s.app_mode,'learning_store':'dynamodb' if s.learning_table else 'local_state','security_enabled':s.security_enabled}
    if s.is_production: return {'ok':True,'app':s.app_name,'version':'8.4.0'}
    if s.is_aws:
        try: base['aws']=AwsAdapter().health()
        except Exception as e: base['aws']={'error':str(e)}
    return base

@router.get('/bootstrap')
def bootstrap(request:Request):
    s=get_settings(); ms=markets.list_markets(); default=next((m for m in ms if m['id']==s.default_market),ms[0] if ms else None); latest=evaluations.latest(); u=user_ctx(request)
    ms=[m for m in ms if security.is_admin(u) or security.can(u,'query',m.get('id',''))]
    if default and default not in ms: default=ms[0] if ms else None
    sec=security.summary(u,default['id']) if default else {'user_id':u.user_id,'roles':list(u.roles),'is_admin':security.is_admin(u),'permissions':{}}
    return {'app':{'name':s.app_name,'version':'8.4.0','mode':s.app_mode,'environment':s.app_env},'markets':ms,'default_market':default,'requires_onboarding':not bool(ms),'stats':dashboard.stats() if security.is_admin(u) else {'tables':len(catalog.tables(market=default['id'])) if default else 0},'databases':catalog.databases(default['id']) if default and not security.is_admin(u) else catalog.databases() if security.is_admin(u) else [],'evaluation':{'latest_score':latest.get('score') if latest and security.is_admin(u) else None,'latest_run_id':latest.get('run_id') if latest and security.is_admin(u) else None},'security':sec,'data_sources':data_sources.sources() if security.is_admin(u) else []}

@router.get('/ready')
def ready():
    return readiness.report()


@router.get('/search')
def universal_search(request:Request,q:str,market:str='',limit:int=20):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Search permission denied.')
    return safe(lambda:universal.search(q,market,u,min(max(limit,1),50)))

@router.get('/metrics')
def metric_catalog(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Metric access denied.')
    return safe(lambda:metrics.catalog(market))

@router.get('/semantic/functions')
def semantic_functions(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Semantic function access denied.')
    return {'market':market,'semantic_functions':markets.context(market).get('semantic_functions',{}) or {}}

@router.get('/data-sources/health')
def data_source_health(request:Request):
    u=user_ctx(request)
    if not security.is_admin(u): raise HTTPException(403,'Data-source health requires an admin role.')
    return safe(lambda:data_sources.health())

@router.get('/monitor/summary')
def monitor_summary(request:Request):
    u=user_ctx(request)
    if get_settings().is_production and not security.is_admin(u):
        raise HTTPException(403,'Global operational monitoring requires administrator access.')
    ms=markets.list_markets(); target=get_settings().default_market or (ms[0]['id'] if ms else '')
    if target and not security.can(u,'query',target): raise HTTPException(403,'Monitoring permission denied.')
    if not target and not security.is_admin(u): raise HTTPException(403,'Monitoring permission denied until a workspace exists.')
    return monitor.summary()

@router.get('/capabilities')
def capability_report(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Capability access denied.')
    return safe(lambda:capabilities.report(market))

@router.get('/markets')
def market_list(request:Request):
    u=user_ctx(request)
    return [m for m in markets.list_markets() if security.is_admin(u) or security.can(u,'query',m.get('id',''))]
@router.get('/markets/{market_id}')
def market_context(market_id:str,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market_id): raise HTTPException(403,'Full market semantic context requires semantic review permission.')
    return safe(lambda:markets.context(market_id))
@router.get('/logical-schema')
def logical_schema(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Query permission denied.')
    x=safe(lambda:logical.build(market))
    # Hide physical bindings that point to denied columns while retaining business definitions.
    denied=security.denied_columns(u,market)
    if denied:
        import fnmatch
        for item in x.get('dimensions',[]):
            phys=item.get('physical') or {}
            if isinstance(phys,dict):
                full=f"{phys.get('database','')}.{phys.get('table','')}.{phys.get('column','')}"
                if any(fnmatch.fnmatch(full,p) or fnmatch.fnmatch(phys.get('column',''),p) for p in denied): item['physical']=None
        for item in x.get('metrics',[]):
            safe_sources=[]
            for src in item.get('sources',[]) or []:
                full=f"{src.get('database','')}.{src.get('table','')}.{src.get('column','')}"
                if not any(fnmatch.fnmatch(full,p) or fnmatch.fnmatch(src.get('column',''),p) for p in denied): safe_sources.append(src)
            item['sources']=safe_sources
    return x
@router.get('/semantic/value-index')
def semantic_value_index(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Query permission denied.')
    return safe(lambda:{'market':market,'entries':value_index.entries(market)})
@router.post('/semantic/resolve')
def semantic_resolve(body:ResolveRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'query',body.market): raise HTTPException(403,'Query permission denied.')
    return safe(lambda:queries.run(body.question,body.market,False,conversation_id=body.conversation_id,user=u))
@router.post('/query/features')
def query_features(body:ResolveRequest): return features.classify(body.question)

@router.get('/catalog/tables')
def tables(request:Request,database:str|None=None,market:str=''):
    if not security.can(user_ctx(request),'query',market): raise HTTPException(403,'Catalog access denied.')
    return catalog.tables(database,market or None)
@router.get('/catalog/columns')
def columns(request:Request,database:str,table:str,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Catalog access denied.')
    rows=catalog.columns(database,table,market or None); return [c for c in rows if security.column_allowed(u,market,database,table,c.get('name',''))]
@router.get('/ontology')
def ontology(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Query permission denied.')
    return security.filter_ontology(repo.ontology(),u,market)
@router.post('/ontology/infer')
def ontology_infer(body:OntologyInferRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.market): raise HTTPException(403,'Semantic review permission denied.')
    return safe(lambda:inference.infer(body.market,body.max_suggestions))
@router.get('/ontology/suggestions')
def ontology_suggestions(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market): raise HTTPException(403,'Semantic review permission denied.')
    return {'suggestions':inference.list(market)}
@router.post('/ontology/suggestions/{suggestion_id}')
def ontology_suggestion_review(suggestion_id:str,body:SuggestionReviewRequest,request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market): raise HTTPException(403,'Semantic review permission denied.')
    return safe(lambda:inference.review(suggestion_id,body.status,body.note,u.user_id))

@router.get('/relationships')
def relationships(request:Request,status:str|None=None,trusted:bool|None=None,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Relationship access denied.')
    rs=[r for r in rels.all() if security.relationship_allowed(u,market,r)]
    if status: rs=[r for r in rs if r.get('status')==status]
    if trusted is not None: rs=[r for r in rs if r.get('trusted_for_queries')==trusted]
    return {'stats':rels.stats(),'relationships':[dict(r,evidence_breakdown=graphrag.relationship_evidence(r)) for r in rs]}
@router.post('/relationships/{rel_id}')
def relationship_action(rel_id:str,body:RelationshipAction,request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market): raise HTTPException(403,'Semantic review permission denied.')
    if rel_id.startswith('rel:') and not market:raise HTTPException(400,'A relationship workspace is required')
    return safe(lambda:rels.act(rel_id,body.action,body.note,market,u.user_id))
@router.post('/relationships/{rel_id}/data-validate')
def relationship_data_validate(rel_id:str,request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market): raise HTTPException(403,'Semantic review permission denied.')
    if rel_id.startswith('rel:') and not market:raise HTTPException(400,'A relationship workspace is required')
    return safe(lambda:relationship_validator.validate(rel_id,workspace=market,actor=u.user_id))

@router.post('/descriptions/generate')
def generate_description(body:DescriptionGenerateRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.market): raise HTTPException(403,'Semantic review permission denied.')
    if not security.column_allowed(u,body.market,body.database,body.table,body.column): raise HTTPException(403,'Column policy blocks description access.')
    return safe(lambda:descriptions.generate(body.market,body.database,body.table,body.column,body.force_ai))
@router.post('/descriptions/{database}/{table}/{column}')
def update_description(database:str,table:str,column:str,body:DescriptionUpdateRequest,request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market): raise HTTPException(403,'Semantic review permission denied.')
    return safe(lambda:descriptions.update(database,table,column,body.description,body.status))

@router.post('/query')
def run_query(body:QueryRequest,request:Request):
    u=user_ctx(request)
    return safe(lambda:queries.run(body.question,body.market,body.execute,body.database,body.conversation_id,body.data_source,u))
@router.get('/queries/history')
def query_history(request:Request,limit:int=30):
    u=user_ctx(request); rows=learning.recent(min(max(limit,1),100))
    if not security.is_admin(u): rows=[x for x in rows if x.get('user_id') in {None,u.user_id}]
    return {'queries':rows}
@router.post('/queries/{query_id}/feedback')
def query_feedback(query_id:str,body:QueryFeedbackRequest,request:Request):
    u=user_ctx(request); row=next((x for x in learning.recent(200) if x.get('query_id')==query_id),None)
    if row and row.get('user_id') not in {None,u.user_id} and not security.is_admin(u): raise HTTPException(403,'Query feedback access denied.')
    return safe(lambda:learning.feedback(query_id,body.rating,body.note))

@router.post('/conversations')
def conversation_create(body:ConversationCreateRequest,request:Request): return conversations.create(body.market,body.title,user_ctx(request).user_id)
@router.get('/conversations')
def conversation_list(request:Request,limit:int=50): return {'conversations':conversations.list(user_ctx(request).user_id,limit)}
@router.get('/conversations/{conversation_id}')
def conversation_get(conversation_id:str,request:Request):
    c=safe(lambda:conversations.get(conversation_id)); u=user_ctx(request)
    if c.get('user_id')!=u.user_id and not security.is_admin(u): raise HTTPException(403,'Conversation access denied.')
    return c

@router.get('/evaluations')
def evaluation_suites(request:Request,market:str=''):
    if not security.can(user_ctx(request),'semantic_review',market): raise HTTPException(403,'Evaluation access denied.')
    return {'suites':evaluations.suites(),'history':evaluations.learning.recent_evaluations(20)}
@router.get('/evaluations/{suite_id}')
def evaluation_latest(suite_id:str,request:Request,market:str=''):
    if not security.can(user_ctx(request),'semantic_review',market): raise HTTPException(403,'Evaluation access denied.')
    suite=next((x for x in evaluations.suites() if x.get('id')==suite_id),None)
    if not suite: raise HTTPException(404,suite_id)
    return {'suite':suite,'latest':evaluations.latest(suite_id)}
@router.post('/evaluations/{suite_id}/run')
def evaluation_run(suite_id:str,request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',market): raise HTTPException(403,'Evaluation execution requires semantic review permission.')
    return safe(lambda:evaluations.run(suite_id))

@router.get('/onboarding/status')
def onboarding_status(request:Request,market:str=''):
    u=user_ctx(request)
    if market and not security.can(u,'query',market): raise HTTPException(403,'Onboarding status access denied.')
    if not market and not security.is_admin(u): raise HTTPException(403,'Onboarding status requires an admin role before the first workspace exists.')
    return safe(lambda:onboarding.status(market or None))

@router.post('/onboarding/bootstrap')
def onboarding_bootstrap(body:WorkspaceBootstrapRequest,request:Request):
    u=user_ctx(request)
    if not security.is_admin(u): raise HTTPException(403,'Creating a semantic workspace requires an admin role.')
    return safe(lambda:onboarding.bootstrap_source(body.source_id,body.workspace_id,body.display_name,body.schemas or None,body.discover_relationships))
@router.post('/onboarding/sync')
def onboarding_sync(body:CatalogSyncRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.market): raise HTTPException(403,'Onboarding requires semantic review permission.')
    return safe(lambda:onboarding.sync_catalog(body.market,body.databases))
@router.post('/onboarding/discover-relationships')
def onboarding_discover(body:RelationshipDiscoveryRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.market): raise HTTPException(403,'Onboarding requires semantic review permission.')
    return safe(lambda:onboarding.discover_relationships(body.market,body.max_candidates))

@router.get('/graphrag/stats')
def graphrag_stats(request:Request,market:str=''):
    if not security.can(user_ctx(request),'query',market): raise HTTPException(403,'Graph access denied.')
    g=safe(lambda:graphrag.graph(market)); return {'market':market,'version':g.get('version'),'fingerprint':g.get('fingerprint'),'embedding':g.get('embedding'),'stats':g.get('stats',{}),'created_at':g.get('created_at')}
@router.post('/graphrag/rebuild')
def graphrag_rebuild(body:GraphRebuildRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.market): raise HTTPException(403,'Graph rebuild requires semantic review permission.')
    g=safe(lambda:graphrag.build(body.market,persist=True)); return {'market':body.market,'fingerprint':g.get('fingerprint'),'stats':g.get('stats',{}),'created_at':g.get('created_at')}
@router.post('/graphrag/search')
def graphrag_search(body:GraphSearchRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'query',body.market): raise HTTPException(403,'Graph access denied.')
    r=safe(lambda:graphrag.search(body.question,body.market,body.top_k,body.depth)); r['results']=security.filter_graph_results(r.get('results',[]),u,body.market); return r
@router.post('/graphrag/neighborhood')
def graphrag_neighborhood(body:GraphNeighborhoodRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'query',body.market): raise HTTPException(403,'Graph access denied.')
    r=safe(lambda:graphrag.neighborhood(body.market,body.node_id,body.depth)); return security.filter_graph_payload(r,u,body.market)



@router.get('/workspaces')
def workspace_list(request:Request):
    u=user_ctx(request); rows=workspaces.list_workspaces()
    if not security.is_admin(u): rows=[x for x in rows if security.workspace_allowed(u,x.get('id',''))]
    return {'workspaces':rows}

@router.get('/semantic-studio')
def semantic_studio_overview(request:Request,workspace:str):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',workspace): raise HTTPException(403,'Semantic Studio requires semantic review permission.')
    return safe(lambda:studio.overview(workspace))

@router.get('/semantic-studio/objects')
def semantic_studio_objects(request:Request,workspace:str,kind:str):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',workspace): raise HTTPException(403,'Semantic Studio requires semantic review permission.')
    return {'objects':safe(lambda:studio.objects(workspace,kind))}

@router.post('/semantic-studio/object')
def semantic_studio_upsert(body:SemanticObjectUpsertRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.workspace): raise HTTPException(403,'Semantic Studio requires semantic review permission.')
    return safe(lambda:studio.upsert(body.workspace,body.kind,body.object_id,body.spec,u.user_id))

@router.post('/semantic-studio/transition')
def semantic_studio_transition(body:SemanticTransitionRequest,request:Request):
    u=user_ctx(request); needed='publish' if body.status=='certified' else 'semantic_review'
    if not security.can(u,needed,body.workspace): raise HTTPException(403,'Semantic transition permission denied.')
    return safe(lambda:studio.transition(body.workspace,body.kind,body.object_id,body.status,body.note,u.user_id))

@router.post('/semantic-studio/promote-suggestion')
def semantic_studio_promote(body:SemanticSuggestionPromoteRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'semantic_review',body.workspace): raise HTTPException(403,'Semantic Studio requires semantic review permission.')
    return safe(lambda:studio.promote_suggestion(body.workspace,body.suggestion_id,u.user_id))


@router.get('/reports')
def report_list(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Report access denied.')
    return {'reports':reports.list(market,u)}

@router.post('/reports')
def report_create(body:ReportCreateRequest,request:Request):
    return safe(lambda:reports.create(body.market,body.title,body.description,user_ctx(request)))

@router.get('/reports/{report_id}')
def report_get(report_id:str,request:Request):
    return safe(lambda:reports.get(report_id,user_ctx(request)))

@router.post('/reports/{report_id}/widgets')
def report_add_widget(report_id:str,body:ReportWidgetRequest,request:Request):
    return safe(lambda:reports.add_widget(report_id,body.question,body.title,body.chart_type,user_ctx(request),body.release_id))

@router.delete('/reports/{report_id}/widgets/{widget_id}')
def report_remove_widget(report_id:str,widget_id:str,request:Request):
    return safe(lambda:reports.remove_widget(report_id,widget_id,user_ctx(request)))

@router.post('/reports/{report_id}/status')
def report_status(report_id:str,body:ReportStatusRequest,request:Request):
    return safe(lambda:reports.set_status(report_id,body.status,user_ctx(request)))

@router.get('/reports/{report_id}/lineage')
def report_lineage(report_id:str,request:Request):
    return safe(lambda:reports.lineage(report_id,user_ctx(request)))

@router.post('/reports/{report_id}/widgets/{widget_id}/drilldown')
def report_drilldown(report_id:str,widget_id:str,request:Request,dimension:str,data_source:str|None=None):
    return safe(lambda:reports.drilldown(report_id,widget_id,dimension,user_ctx(request),data_source))

@router.get('/reports/{report_id}/render')
def report_render(report_id:str,request:Request,data_source:str|None=None):
    return safe(lambda:reports.render(report_id,user_ctx(request),data_source))


@router.post('/reports/{report_id}/share')
def report_share(report_id:str,body:ReportShareRequest,request:Request): return safe(lambda:reports.share(report_id,body.roles,user_ctx(request)))

@router.post('/reports/{report_id}/filters')
def report_filters(report_id:str,body:ReportFiltersRequest,request:Request): return safe(lambda:reports.set_filters(report_id,body.filters,user_ctx(request)))

@router.post('/reports/{report_id}/schedule')
def report_schedule(report_id:str,body:ReportScheduleRequest,request:Request): return safe(lambda:reports.set_schedule(report_id,body.model_dump(),user_ctx(request)))

@router.post('/reports/{report_id}/alerts')
def report_alert(report_id:str,body:ReportAlertRequest,request:Request): return safe(lambda:reports.add_alert(report_id,body.model_dump(),user_ctx(request)))

@router.get('/reports/{report_id}/export/{fmt}')
def report_export(report_id:str,fmt:str,request:Request,data_source:str|None=None):
    data,media,name=safe(lambda:reports.export(report_id,user_ctx(request),fmt,data_source)); return Response(content=data,media_type=media,headers={'Content-Disposition':f'attachment; filename="{name}"'})

@router.post('/report-worker/run-due')
def report_worker_run_due(request:Request,x_report_worker_token:str|None=Header(default=None)):
    s=get_settings()
    if s.report_worker_token:
        if x_report_worker_token!=s.report_worker_token: raise HTTPException(401,'Invalid report worker token.')
    elif not security.is_admin(user_ctx(request)): raise HTTPException(403,'Report worker requires admin role when REPORT_WORKER_TOKEN is unset.')
    return reports.run_due()

@router.get('/graphrag/explorer')
def graphrag_explorer(request:Request,market:str='',node_id:str|None=None,depth:int=2,limit:int=220,node_types:str|None=None,statuses:str|None=None,trusted_only:bool=False,min_authority:float=0.0,cluster:str|None=None):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Graph access denied.')
    types=[x.strip() for x in (node_types or '').split(',') if x.strip()]; sts=[x.strip() for x in (statuses or '').split(',') if x.strip()]
    g=safe(lambda:graphrag.explorer(market,node_id,min(max(depth,1),4),limit,types,sts,trusted_only,min(max(min_authority,0),1),cluster))
    return security.filter_graph_payload(g,u,market)

@router.get('/lineage')
def lineage_graph(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Lineage access denied.')
    r=safe(lambda:lineage.graph(market)); return security.filter_graph_payload(r,u,market)
@router.get('/lineage/impact')
def lineage_impact(request:Request,node_id:str,market:str='',direction:str='both',depth:int=3):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Lineage access denied.')
    r=safe(lambda:lineage.impact(market,node_id,direction,min(max(depth,1),5))); return security.filter_graph_payload(r,u,market)

@router.get('/governance')
def governance_queue(request:Request,market:str=''):
    if not security.can(user_ctx(request),'semantic_review',market): raise HTTPException(403,'Governance access denied.')
    return safe(lambda:governance.queue(market))
@router.get('/releases')
def semantic_releases(request:Request,market:str|None=None):
    u=user_ctx(request)
    if market and not security.can(u,'query',market): raise HTTPException(403,'Release access denied.')
    rows=releases.list(market)
    return {'releases':[x for x in rows if security.is_admin(u) or security.can(u,'query',x.get('market',''))]}
@router.post('/releases/publish')
def semantic_release_publish(body:SemanticReleaseRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'publish',body.market): raise HTTPException(403,'Publish permission denied.')
    return safe(lambda:releases.publish(body.market,body.version,body.notes))

@router.post('/branches')
def branch_create(body:BranchCreateRequest,request:Request):
    u=user_ctx(request)
    if not security.can(u,'manage_branch',body.market): raise HTTPException(403,'Branch permission denied.')
    return branches.create(body.market,body.name,body.description,body.base_version,u.user_id)
@router.get('/branches')
def branch_list(request:Request,market:str|None=None):
    target=market or get_settings().default_market; u=user_ctx(request)
    if not security.can(u,'manage_branch',target): raise HTTPException(403,'Branch access denied.')
    return {'branches':branches.list(market)}
@router.get('/branches/{branch_id}')
def branch_get(branch_id:str,request:Request):
    b=safe(lambda:branches.get(branch_id)); u=user_ctx(request)
    if not security.can(u,'manage_branch',b['market']): raise HTTPException(403,'Branch access denied.')
    return safe(lambda:branches.compare(branch_id))
@router.post('/branches/{branch_id}/patch')
def branch_patch(branch_id:str,body:BranchPatchRequest,request:Request):
    b=safe(lambda:branches.get(branch_id)); u=user_ctx(request)
    if not security.can(u,'manage_branch',b['market']): raise HTTPException(403,'Branch permission denied.')
    return safe(lambda:branches.patch(branch_id,body.path,body.value,body.operation))
@router.post('/branches/{branch_id}/validate')
def branch_validate(branch_id:str,request:Request):
    b=safe(lambda:branches.get(branch_id)); u=user_ctx(request)
    if not security.can(u,'manage_branch',b['market']): raise HTTPException(403,'Branch permission denied.')
    return safe(lambda:branches.validate(branch_id))

@router.post('/branches/{branch_id}/merge')
def branch_merge(branch_id:str,body:BranchMergeRequest,request:Request):
    b=safe(lambda:branches.get(branch_id)); u=user_ctx(request)
    if not security.can(u,'publish',b['market']): raise HTTPException(403,'Merge permission denied.')
    return safe(lambda:branches.merge(branch_id,body.note,u.user_id))

@router.get('/security/me')
def security_me(request:Request,market:str=''):
    u=user_ctx(request)
    return security.summary(u,market) if market else {'user_id':u.user_id,'roles':list(u.roles),'is_admin':security.is_admin(u),'denied_columns':[],'permissions':{}}
@router.get('/data-sources')
def source_list(request:Request):
    if not security.is_admin(user_ctx(request)): raise HTTPException(403,'Data-source configuration requires an admin role.')
    return {'data_sources':data_sources.sources()}
@router.get('/data-sources/{source_id}/catalog')
def source_catalog(source_id:str,request:Request,schemas:str|None=None,market:str=''):
    u=user_ctx(request)
    if market:
        if not security.can(u,'semantic_review',market): raise HTTPException(403,'Catalog discovery requires semantic review permission.')
    elif not security.is_admin(u): raise HTTPException(403,'Catalog discovery requires an admin role before onboarding.')
    selected=[x.strip() for x in schemas.split(',') if x.strip()] if schemas else None
    return safe(lambda:data_sources.discover(source_id,selected))
@router.get('/actions')
def action_list(request:Request,market:str=''):
    u=user_ctx(request)
    if not security.can(u,'query',market): raise HTTPException(403,'Action catalog access denied.')
    rows=[]
    for x in actions.definitions(market):
        allowed=not x.get('roles') or u.has_any(x.get('roles')) or security.is_admin(u); rows.append({**x,'allowed':allowed})
    return {'actions':rows,'history':actions.history(30) if security.is_admin(u) else []}
@router.post('/actions/{action_id}/execute')
def action_execute(action_id:str,body:ActionExecuteRequest,request:Request): return safe(lambda:actions.execute(action_id,body.market,body.parameters,user_ctx(request),body.dry_run))

@router.get('/audit')
def audit(request:Request,limit:int=100,market:str=''):
    u=user_ctx(request)
    if not security.is_admin(u): raise HTTPException(403,'Audit access requires an admin role.')
    return {'events':control.list('AUDIT',min(max(limit,1),500))}

@router.post('/mcp')
def mcp_endpoint(body:MCPRequest,request:Request): return safe(lambda:mcp.handle(body.model_dump(),user_ctx(request)))

# ---------------------------------------------------------------------------
# Phase 1: permission-guarded progressive catalog, exact table scopes and Bedrock
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field
from app.services.enterprise_catalog_service import EnterpriseCatalogService
from app.services.scope_service import ScopeService
from app.services.bedrock_model_service import BedrockModelService

enterprise_catalog=EnterpriseCatalogService()
scopes=ScopeService()
bedrock_models=BedrockModelService()

class Phase1ScopeRequest(BaseModel):
    scope_id: str = Field(min_length=2,max_length=80)
    workspace_id: str = Field(min_length=2,max_length=80)
    display_name: str = Field(default='',max_length=120)
    source_id: str
    tables: list[dict] = Field(min_length=1,max_length=500)

class Phase1ModelRequest(BaseModel):
    strategy: str = 'balanced'
    task_models: dict[str,str] = Field(default_factory=dict)
    pinned: bool = False

class Phase1ProbeRequest(BaseModel):
    model_id: str = Field(min_length=3,max_length=512)

def _phase1_admin(request:Request):
    ctx=user_ctx(request)
    if not security.is_admin(ctx):raise HTTPException(403,'Phase 1 configuration requires an administrator')

@router.get('/phase1/catalog/{source_id}/{level}')
def phase1_catalog(source_id:str,level:str,request:Request,catalog:str='',database:str='',schema:str='',q:str='',limit:int=50,cursor:str=''):
    _phase1_admin(request)
    if limit<1 or limit>100:raise HTTPException(422,'limit must be between 1 and 100')
    if len(q)>120:raise HTTPException(422,'search too long')
    if level not in {'catalogs','databases','schemas','tables'}:raise HTTPException(404,'Unsupported catalog level')
    kwargs={'q':q,'limit':limit,'cursor':cursor or None}
    if level!='catalogs':kwargs['catalog']=catalog
    if level in {'schemas','tables'}:kwargs['database']=database
    if level=='tables':kwargs['schema']=schema
    return safe(lambda:getattr(enterprise_catalog,level)(source_id,**kwargs))

@router.get('/phase1/table-detail/{source_id}')
def phase1_table_detail(source_id:str,request:Request,catalog:str='',database:str='',schema:str='',table:str=''):
    _phase1_admin(request)
    return safe(lambda:enterprise_catalog.table_details(source_id,catalog,database,schema,table))

@router.get('/phase1/scopes')
def phase1_scopes(request:Request):
    _phase1_admin(request)
    return {'scopes':scopes.list()}

@router.post('/phase1/scopes')
def phase1_save_scope(body:Phase1ScopeRequest,request:Request):
    _phase1_admin(request)
    return safe(lambda:scopes.save(body.model_dump()))

@router.get('/phase1/scopes/{scope_id}')
def phase1_read_scope(scope_id:str,request:Request):
    _phase1_admin(request)
    return safe(lambda:scopes.get(scope_id))

@router.post('/phase1/scopes/{scope_id}/generate')
def phase1_generate(scope_id:str,request:Request,discover_relationships:bool=False):
    _phase1_admin(request)
    return safe(lambda:scopes.build(scope_id,discover_relationships))

@router.get('/phase1/bedrock/models')
def phase1_models(request:Request):
    _phase1_admin(request)
    return safe(lambda:bedrock_models.overview())

@router.post('/phase1/bedrock/probe')
def phase1_model_probe(body:Phase1ProbeRequest,request:Request):
    _phase1_admin(request)
    return safe(lambda:bedrock_models.probe(body.model_id))

@router.post('/phase1/bedrock/configuration')
def phase1_model_config(body:Phase1ModelRequest,request:Request):
    _phase1_admin(request)
    return safe(lambda:bedrock_models.save(body.model_dump()))


# ---------------------------------------------------------------------------
# Phase 2 — evidence-backed understanding; exact Phase 1 workspace allowlist.
# ---------------------------------------------------------------------------
from app.services.phase2_service import Phase2Service
p2=Phase2Service()

class P2ProfileRequest(BaseModel):
    asset_id: str
    tier: str = 'standard'
    max_columns: int = Field(default=80, ge=1,le=200)

class P2ContractSave(BaseModel):
    expected_version: int | None = None
    owner: str = Field(default='',max_length=120)
    description: str = Field(default='',max_length=1000)
    freshness_sla_hours: float | None = Field(default=None,gt=0,le=8760)
    columns: list[dict] | None = None

class P2Decision(BaseModel):
    decision: str
    note: str = Field(default='',max_length=2000)

class P2Rule(BaseModel):
    asset_id: str
    rule_type: str
    column: str = ''
    threshold: float = 1.0
    relationship_id: str | None = None
    description: str = Field(default='',max_length=500)

class P2Remediation(BaseModel):
    status: str
    note: str = Field(min_length=1,max_length=2000)
    owner: str = Field(default='',max_length=120)

class P2Transformation(BaseModel):
    label: str = Field(min_length=1,max_length=160)
    inputs: list[str] = Field(min_length=1,max_length=30)
    outputs: list[str] = Field(min_length=1,max_length=30)
    description: str = Field(default='',max_length=1200)

def _p2_guard(request:Request,workspace:str,write:bool=False):
    u=user_ctx(request)
    # Metadata-only statistics can still reveal restricted business information.
    try: permitted=security.can(u,'semantic_review' if write else 'query',workspace)
    except KeyError:raise HTTPException(404,'Unknown Phase 2 workspace')
    if not permitted:raise HTTPException(403,'Phase 2 workspace permission denied')
    return u

def _p2_filtered(payload,u,workspace):
    # Existing per-column policies apply to profiles and contracts as well.
    if isinstance(payload,list):return [_p2_filtered(x,u,workspace) for x in payload]
    if not isinstance(payload,dict):return payload
    import copy
    out=copy.deepcopy(payload)
    if 'columns' in out and isinstance(out['columns'],list):
        a=next((a for a in p2.assets(workspace) if a['asset_id']==out.get('asset_id')),None)
        if a:
            out['columns']=[c for c in out['columns'] if security.column_allowed(u,workspace,a['database'],a['table'],c.get('name',''))]
    return out

@router.get('/phase2/overview')
def p2_overview(request:Request,workspace:str):
    _p2_guard(request,workspace)
    return safe(lambda:p2.overview(workspace))

@router.get('/phase2/assets/{asset_id}/metadata')
def p2_metadata(asset_id:str,request:Request,workspace:str):
    u=_p2_guard(request,workspace)
    return safe(lambda:_p2_filtered(p2.metadata(workspace,asset_id),u,workspace))

@router.get('/phase2/assets/{asset_id}/sample')
def p2_sample(asset_id:str,request:Request,workspace:str,limit:int=10):
    """Explicitly scoped, bounded synthetic demo preview only; no external row extraction."""
    u=_p2_guard(request,workspace)
    def preview():
        from app.services.data_source_service import DataSourceService
        asset=p2.asset(workspace,asset_id)
        if asset['source_id']!='contoso':raise PermissionError('Sample preview is disabled for external data sources. Use governed query policies.')
        if security.row_predicates(u,workspace):raise PermissionError('Row-level policies prohibit generic sample preview.')
        if not 1<=limit<=10:raise ValueError('Preview must request between 1 and 10 rows.')
        metadata=p2.metadata(workspace,asset_id)
        cols=[c['name'] for c in metadata['columns'] if not c.get('sensitive_candidate') and security.column_allowed(u,workspace,asset['database'],asset['table'],c['name'])]
        if not cols:return {'columns':[],'rows':[],'disclaimer':'No unrestricted columns available for preview.'}
        sel=', '.join(p2._ident(c) for c in cols)
        sql=f'SELECT {sel} FROM {p2._table_sql(asset)} LIMIT {int(limit)}'
        out=DataSourceService().execute('contoso',sql,asset['database'])
        return {'columns':cols,'rows':out.get('rows',[])[:limit],'source':'synthetic_contoso',
                'disclaimer':'Synthetic local demo data only. Sensitive and disallowed columns are excluded. Nothing is persisted.'}
    return safe(preview)

@router.get('/phase2/profiles')
def p2_profiles(request:Request,workspace:str,asset_id:str|None=None):
    u=_p2_guard(request,workspace)
    return safe(lambda:{'profiles':_p2_filtered(p2.profiles(workspace,asset_id),u,workspace)})

@router.post('/phase2/profiles')
def p2_profile(body:P2ProfileRequest,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.profile(workspace,body.asset_id,body.tier,u.user_id,body.max_columns))

@router.get('/phase2/contracts')
def p2_contracts(request:Request,workspace:str,asset_id:str|None=None):
    u=_p2_guard(request,workspace)
    return safe(lambda:{'contracts':_p2_filtered(p2.contracts(workspace,asset_id),u,workspace)})

@router.post('/phase2/contracts/{asset_id}')
def p2_contract_save(asset_id:str,body:P2ContractSave,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    data=body.model_dump(exclude_unset=True)
    return safe(lambda:p2.save_contract(workspace,asset_id,data,u.user_id))

@router.post('/phase2/contracts/{asset_id}/review')
def p2_contract_transition(asset_id:str,body:P2Decision,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.transition_contract(workspace,asset_id,body.decision,body.note,u.user_id))

@router.get('/phase2/relationships')
def p2_relationships(request:Request,workspace:str):
    u=_p2_guard(request,workspace)
    def get_filtered():
        rows=[]
        for r in p2.relationships(workspace):
            a=p2.asset(workspace,r['from_asset']);b=p2.asset(workspace,r['to_asset'])
            if security.column_allowed(u,workspace,a['database'],a['table'],r['from_column']) and security.column_allowed(u,workspace,b['database'],b['table'],r['to_column']):rows.append(r)
        return {'relationships':rows}
    return safe(get_filtered)

@router.post('/phase2/relationships/{rel_id}/validate')
def p2_validate_relationship(rel_id:str,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.validate_relationship(workspace,rel_id,u.user_id))

@router.post('/phase2/relationships/{rel_id}/review')
def p2_review_relationship(rel_id:str,body:P2Decision,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.review_relationship(workspace,rel_id,body.decision,body.note,u.user_id))

@router.get('/phase2/quality/rules')
def p2_rules(request:Request,workspace:str):
    _p2_guard(request,workspace)
    u=_p2_guard(request,workspace)
    def allowed(rule):
        a=p2.asset(workspace,rule['asset_id'])
        return not rule.get('column') or security.column_allowed(u,workspace,a['database'],a['table'],rule['column'])
    return safe(lambda:{'rules':[r for r in p2.rules(workspace) if allowed(r)]})

@router.post('/phase2/quality/rules')
def p2_create_rule(body:P2Rule,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.create_rule(workspace,body.model_dump(),u.user_id))

@router.post('/phase2/quality/rules/{rule_id}/status')
def p2_rule_status(rule_id:str,body:P2Decision,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.set_rule_status(workspace,rule_id,body.decision,body.note,u.user_id))

@router.get('/phase2/quality/runs')
def p2_runs(request:Request,workspace:str):
    _p2_guard(request,workspace)
    u=_p2_guard(request,workspace)
    def filtered():
        out=[]
        for run in p2.runs(workspace):
            import copy
            row=copy.deepcopy(run)
            row['observations']=[o for o in row['observations'] if not o.get('column') or security.column_allowed(u,workspace,p2.asset(workspace,o['asset_id'])['database'],p2.asset(workspace,o['asset_id'])['table'],o['column'])]
            out.append(row)
        return {'runs':out}
    return safe(filtered)

@router.post('/phase2/quality/run')
def p2_run(request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.run_rules(workspace,u.user_id))

@router.post('/phase2/quality/runs/{run_id}/review')
def p2_review_run(run_id:str,body:P2Decision,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.review_run(workspace,run_id,body.model_dump(),u.user_id))

@router.post('/phase2/quality/runs/{run_id}/remediate')
def p2_remediate(run_id:str,body:P2Remediation,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.remediate(workspace,run_id,body.model_dump(),u.user_id))

@router.get('/phase2/lineage')
def p2_lineage(request:Request,workspace:str):
    _p2_guard(request,workspace)
    u=_p2_guard(request,workspace)
    def filtered():
        g=p2.lineage(workspace)
        forbidden=set()
        for r in p2.relationships(workspace):
            a=p2.asset(workspace,r['from_asset']);b=p2.asset(workspace,r['to_asset'])
            if not (security.column_allowed(u,workspace,a['database'],a['table'],r['from_column']) and security.column_allowed(u,workspace,b['database'],b['table'],r['to_column'])):forbidden.add(r['relationship_id'])
        g['nodes']=[n for n in g['nodes'] if n['id'] not in forbidden]
        g['edges']=[e for e in g['edges'] if e['source_id'] not in forbidden and e['target_id'] not in forbidden]
        return g
    return safe(filtered)

@router.get('/phase2/lineage/impact')
def p2_impact(request:Request,workspace:str,node_id:str,direction:str='both',depth:int=3):
    _p2_guard(request,workspace)
    return safe(lambda:p2.impact(workspace,node_id,direction,depth))

@router.get('/phase2/transformations')
def p2_transformations(request:Request,workspace:str):
    _p2_guard(request,workspace)
    return safe(lambda:{'transformations':p2.transformations(workspace)})

@router.post('/phase2/transformations')
def p2_transform(body:P2Transformation,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.register_transform(workspace,body.model_dump(),u.user_id))

@router.get('/phase2/audit')
def p2_audit(request:Request,workspace:str,limit:int=100):
    _p2_guard(request,workspace,True)
    return safe(lambda:{'events':p2._owned('audit',workspace)[:min(max(limit,1),100)]})

# ---------------------------------------------------------------------------
# Phase 3 — Ontology 2.0, immutable provenance snapshots, SME decisions,
# trust-aware diagnostics and four semantic graph views.
# ---------------------------------------------------------------------------
from app.services.phase3_service import Phase3Service
p3=Phase3Service()

class P3ObjectRequest(BaseModel):
    kind: str
    object_id: str = Field(default='',max_length=100)
    label: str = Field(min_length=2,max_length=160)
    description: str = Field(default='',max_length=2000)
    definition: str = Field(default='',max_length=1000)
    binding: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    semantics: dict = Field(default_factory=dict)
    synonyms: list[str] = Field(default_factory=list)

class P3EditRequest(BaseModel):
    expected_version: int
    label: str | None = Field(default=None,min_length=2,max_length=160)
    description: str | None = Field(default=None,max_length=2000)
    definition: str | None = Field(default=None,max_length=1000)
    binding: dict | None = None
    depends_on: list[str] | None = None
    semantics: dict | None = None
    synonyms: list[str] | None = None

class P3ReviewRequest(BaseModel):
    decision: str
    note: str = Field(min_length=5,max_length=1500)
    expected_version: int

class P3QuestionReview(BaseModel):
    decision: str
    note: str = Field(min_length=5,max_length=1500)

class P3ReleaseRequest(BaseModel):
    version: str = Field(min_length=1,max_length=80)
    note: str = Field(min_length=5,max_length=2000)

def _p3_guard(request:Request,workspace:str,publish:bool=False):
    # All Phase 3 views contain sensitive semantic/physical bindings, even in
    # diagnostics, so no analyst-level metadata bypass of column restrictions.
    u=_p2_guard(request,workspace,write=True)
    if security.denied_columns(u,workspace):
        raise HTTPException(403,'Ontology review requires unrestricted workspace column access')
    if publish and not security.can(u,'publish',workspace):
        raise HTTPException(403,'Publishing ontology requires publish permission')
    return u

@router.get('/phase3/overview')
def p3_overview(request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:p3.overview(workspace))

@router.get('/phase3/objects')
def p3_objects(request:Request,workspace:str,kind:str|None=None):
    _p3_guard(request,workspace)
    return safe(lambda:{'workspace_id':workspace,'objects':p3.objects(workspace,kind)})

@router.post('/phase3/proposals')
def p3_propose(request:Request,workspace:str,max_assets:int=30):
    u=_p3_guard(request,workspace)
    return safe(lambda:p3.propose(workspace,u.user_id,max_assets))

@router.post('/phase3/objects')
def p3_create(body:P3ObjectRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace)
    return safe(lambda:p3.create(workspace,body.model_dump(),u.user_id))

@router.get('/phase3/objects/{object_id}')
def p3_read(object_id:str,request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:p3.object(workspace,object_id))

@router.put('/phase3/objects/{object_id}')
def p3_update(object_id:str,body:P3EditRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace)
    return safe(lambda:p3.update(workspace,object_id,body.model_dump(),u.user_id))

@router.post('/phase3/objects/{object_id}/review')
def p3_review(object_id:str,body:P3ReviewRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace)
    return safe(lambda:p3.transition(workspace,object_id,body.decision,body.note,u.user_id,body.expected_version))

@router.get('/phase3/compile')
def p3_compile(request:Request,workspace:str,object_id:str|None=None):
    _p3_guard(request,workspace)
    return safe(lambda:p3.compile(workspace,object_id))

@router.get('/phase3/evidence')
def p3_evidence(request:Request,workspace:str,object_id:str|None=None):
    _p3_guard(request,workspace)
    return safe(lambda:{'workspace_id':workspace,'ledger':p3.evidence(workspace,object_id)})

@router.get('/phase3/questions')
def p3_questions(request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:{'workspace_id':workspace,'questions':p3.questions(workspace)})

@router.post('/phase3/questions/{question_id}/review')
def p3_question_review(question_id:str,body:P3QuestionReview,request:Request,workspace:str):
    u=_p3_guard(request,workspace)
    return safe(lambda:p3.review_question(workspace,question_id,body.decision,body.note,u.user_id))

@router.get('/phase3/graph')
def p3_graph(request:Request,workspace:str,mode:str='conceptual',focus:str|None=None,limit:int=250):
    _p3_guard(request,workspace)
    return safe(lambda:p3.graph(workspace,mode,focus,limit))

@router.get('/phase3/releases')
def p3_releases(request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:{'workspace_id':workspace,'releases':[
        {k:v for k,v in row.items() if k!='objects'} for row in p3._list('P3_RELEASE',workspace)]})

@router.post('/phase3/releases')
def p3_release(body:P3ReleaseRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace,publish=True)
    return safe(lambda:p3.publish_snapshot(workspace,body.version,body.note,u.user_id))

@router.get('/phase3/audit')
def p3_audit(request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:{'workspace_id':workspace,'events':p3._list('P3_AUDIT',workspace)})

# ---------------------------------------------------------------------------
# Phase 4 — explicit opt-in governed consumption of immutable Phase 3 releases.
# The existing /query, /reports and /mcp endpoints are intentionally unchanged.
# ---------------------------------------------------------------------------
from app.services.phase4_service import Phase4Service
p4=Phase4Service()

class P4Promote(BaseModel):
    version: str = Field(min_length=1,max_length=80)
class P4Ask(BaseModel):
    release_id: str = Field(min_length=1,max_length=80)
    question: str = Field(min_length=2,max_length=500)
    object_id: str | None = None
    execute: bool = False
class P4Case(BaseModel):
    release_id: str
    question: str = Field(min_length=2,max_length=500)
    object_id: str | None = None
    expected: str = 'allow'
    reference_sql: str = ''
    reference_asset_id: str | None = None
class P4Eval(BaseModel):
    release_id: str
    mutations: bool = True
class P4BranchCreate(BaseModel):
    release_id: str
    branch_id: str = Field(min_length=1,max_length=80)
class P4Patch(BaseModel):
    object_id: str
    field: str
    value: str = Field(min_length=2,max_length=500)
    expected_version: int
class P4BranchReview(BaseModel):
    decision: str
    note: str = Field(min_length=5,max_length=1000)
    expected_version: int
class P4BranchPublish(BaseModel):
    release_id: str = Field(min_length=1,max_length=80)
class P4Agent(BaseModel):
    release_id: str
    tool: str
    arguments: dict = Field(default_factory=dict)

def _p4_guard(request:Request,workspace:str,publish:bool=False):
    u=user_ctx(request)
    safe(lambda:queries.authorize(u,workspace))
    if publish and not security.can(u,'publish',workspace):raise HTTPException(403,'Publish permission required')
    return u

@router.get('/phase4/overview')
def p4_overview(request:Request,workspace:str,release_id:str=''):
    _p4_guard(request,workspace)
    return safe(lambda:p4.overview(workspace,release_id))

@router.get('/phase4/releases')
def p4_releases(request:Request,workspace:str):
    _p4_guard(request,workspace)
    return safe(lambda:{'releases':p4.releases(workspace)})

@router.post('/phase4/releases/promote')
def p4_promote(body:P4Promote,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.promote(workspace,body.version,u.user_id))

@router.get('/phase4/retrieve')
def p4_retrieve(request:Request,workspace:str,release_id:str,question:str,limit:int=8):
    _p4_guard(request,workspace)
    return safe(lambda:p4.retrieval(workspace,release_id,question,limit))

@router.post('/phase4/plan')
def p4_plan(body:P4Ask,request:Request,workspace:str):
    _p4_guard(request,workspace)
    if body.object_id:raise HTTPException(400,'Object pinning was replaced by approved metric definitions; remove object_id')
    return safe(lambda:queries.run(body.question,workspace,False,user=user_ctx(request),release_id=body.release_id))

@router.post('/phase4/ask')
def p4_ask(body:P4Ask,request:Request,workspace:str):
    _p4_guard(request,workspace)
    if body.object_id:raise HTTPException(400,'Object pinning was replaced by approved metric definitions; remove object_id')
    return safe(lambda:queries.run(body.question,workspace,body.execute,user=user_ctx(request),release_id=body.release_id))

# Advanced governed analytics: Bedrock supplies structured JSON, never executable SQL.
from app.services.advanced_query_service import AdvancedQueryService
advanced_queries=AdvancedQueryService()

class AdvancedAskRequest(BaseModel):
    release_id: str = Field(min_length=1,max_length=80)
    question: str = Field(min_length=2,max_length=500)
    structured_plan: dict | None = None
    use_bedrock: bool = False
    execute: bool = False

@router.get('/phase4/advanced/schema')
def p4_advanced_schema(request:Request,workspace:str,release_id:str):
    u=_p4_guard(request,workspace)
    if security.row_predicates(u,workspace):raise HTTPException(403,'Advanced query requires a governed row-policy compiler before granting access')
    return safe(lambda:advanced_queries.schema(workspace,release_id))

@router.post('/phase4/advanced/ask')
def p4_advanced_ask(body:AdvancedAskRequest,request:Request,workspace:str):
    u=_p4_guard(request,workspace)
    if security.row_predicates(u,workspace):raise HTTPException(403,'Advanced query requires a governed row-policy compiler before granting access')
    if body.structured_plan is not None and body.execute:
        raise HTTPException(400,'Client-supplied structured plans are preview-only; execute a question through the verified LLM workflow')
    return safe(lambda:advanced_queries.run(workspace,body.release_id,body.question,
        body.structured_plan,body.use_bedrock,body.execute))

# Unified natural-language Ask: simple and multi-table requests take one governed path.
from app.services.unified_ask_service import UnifiedAskService
unified_ask=UnifiedAskService()

class UnifiedAskRequest(BaseModel):
    release_id: str = Field(min_length=1,max_length=80)
    question: str = Field(min_length=2,max_length=500)
    execute: bool = True
    previous_plan: dict | None = None

@router.post('/phase4/unified/ask')
def p4_unified_ask(body:UnifiedAskRequest,request:Request,workspace:str):
    u=user_ctx(request)
    safe(lambda:queries.authorize(u,workspace))
    return safe(lambda:unified_ask.ask(workspace,body.release_id,body.question,
        body.execute,body.previous_plan))

@router.post('/phase4/bi')
def p4_bi(body:P4Ask,request:Request,workspace:str):
    _p4_guard(request,workspace)
    if body.object_id:raise HTTPException(400,'Object pinning was replaced by approved metric definitions; remove object_id')
    return safe(lambda:queries.run(body.question,workspace,body.execute,user=user_ctx(request),release_id=body.release_id))

@router.get('/phase4/golden/cases')
def p4_cases(request:Request,workspace:str):
    _p4_guard(request,workspace)
    return safe(lambda:{'cases':p4.cases(workspace)})

@router.post('/phase4/golden/cases')
def p4_case(body:P4Case,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.save_case(workspace,body.model_dump(),u.user_id))

@router.get('/phase4/golden/runs')
def p4_evals(request:Request,workspace:str):
    _p4_guard(request,workspace)
    return safe(lambda:{'runs':p4.evaluations(workspace)})

@router.post('/phase4/golden/run')
def p4_eval(body:P4Eval,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.evaluation(workspace,body.release_id,u.user_id,body.mutations))

@router.get('/phase4/impact')
def p4_impact(request:Request,workspace:str,release_id:str,object_id:str,depth:int=5):
    _p4_guard(request,workspace)
    return safe(lambda:p4.impact(workspace,release_id,object_id,depth))

@router.get('/phase4/branches')
def p4_branches(request:Request,workspace:str):
    _p4_guard(request,workspace)
    return safe(lambda:{'branches':p4.branches(workspace)})

@router.post('/phase4/branches')
def p4_branch(body:P4BranchCreate,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.branch(workspace,body.release_id,body.branch_id,u.user_id))

@router.get('/phase4/branches/{branch_id}/compare')
def p4_compare(branch_id:str,request:Request,workspace:str):
    _p4_guard(request,workspace)
    return safe(lambda:p4.compare(workspace,branch_id))

@router.post('/phase4/branches/{branch_id}/patch')
def p4_patch(branch_id:str,body:P4Patch,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.patch(workspace,branch_id,body.object_id,body.field,body.value,body.expected_version,u.user_id))

@router.post('/phase4/branches/{branch_id}/review')
def p4_branch_review(branch_id:str,body:P4BranchReview,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.review_branch(workspace,branch_id,body.decision,body.note,body.expected_version,u.user_id))

@router.post('/phase4/branches/{branch_id}/publish')
def p4_branch_publish(branch_id:str,body:P4BranchPublish,request:Request,workspace:str):
    u=_p4_guard(request,workspace,True)
    return safe(lambda:p4.publish_branch(workspace,branch_id,body.release_id,u.user_id))

@router.get('/phase4/agent/tools')
def p4_tools(request:Request,workspace:str):
    _p4_guard(request,workspace)
    return {'tools':p4.agent_tools(),'version':'0.1','write_tools_enabled':False}

@router.post('/phase4/agent/call')
def p4_agent(body:P4Agent,request:Request,workspace:str):
    _p4_guard(request,workspace)
    return safe(lambda:p4.agent(workspace,body.release_id,body.tool,body.arguments))

@router.get('/phase4/audit')
def p4_audit(request:Request,workspace:str):
    _p4_guard(request,workspace,True)
    return safe(lambda:{'events':p4._list('P4_AUDIT',workspace)})

class P4MCPRequest(BaseModel):
    jsonrpc: str = '2.0'
    id: str | int | None = None
    method: str
    params: dict = Field(default_factory=dict)

@router.post('/phase4/mcp')
def p4_mcp_rpc(body:P4MCPRequest,request:Request,workspace:str):
    """Opt-in Phase4 JSON-RPC MCP method adapter, no arbitrary execution."""
    _p4_guard(request,workspace)
    import json
    rid=body.id
    if body.jsonrpc!='2.0':raise HTTPException(400,'Expected JSON-RPC 2.0')
    if body.method=='initialize':
        result={'protocolVersion':'2025-06-18','serverInfo':{'name':'dip-governed' ,'version':'8.4.0'},
                'capabilities':{'tools':{}}}
    elif body.method=='tools/list':
        result={'tools':[{'name':t['name'],'description':t['description'],
            'inputSchema':{'type':'object','properties':{
              'release_id':{'type':'string'},'question':{'type':'string'},
              'object_id':{'type':'string'},'execute':{'type':'boolean'}},
              'required':['release_id']+(['object_id'] if t['name']=='ontology.impact' else ['question']),
              'additionalProperties':False}} for t in p4.agent_tools()]}
    elif body.method=='tools/call':
        args=body.params.get('arguments',{}) or {}
        if not isinstance(args,dict):raise HTTPException(400,'Tool arguments must be an object')
        release_id=args.get('release_id')
        if not isinstance(release_id,str) or not release_id:raise HTTPException(400,'Tool release_id is required')
        tool=body.params.get('name','')
        result={'content':[{'type':'text','text':json.dumps(safe(lambda:p4.agent(workspace,release_id,tool,args)),ensure_ascii=False,default=str)}],
                'isError':False}
    else:
        return {'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Unknown Phase4 MCP method'}}
    return {'jsonrpc':'2.0','id':rid,'result':result}

# ---------------------------------------------------------------------------
# Phase 5 — bounded job control, governed federation, permission-aware search,
# connector preflight/equivalence diagnostics, and operational evidence.
# ---------------------------------------------------------------------------
from app.services.phase5_service import Phase5Service
p5=Phase5Service()

class P5Submit(BaseModel):
    task: str
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None,min_length=4,max_length=100)
    priority: int = Field(default=0,ge=-5,le=5)
    max_attempts: int = Field(default=3,ge=1,le=5)
class P5Domain(BaseModel):
    domain_id: str
    label: str = Field(min_length=2,max_length=120)
    description: str = Field(default='',max_length=500)
    release_id: str
class P5Version(BaseModel):
    expected_version: int = Field(ge=1)
class P5Grant(BaseModel):
    target_workspace: str
    allow: bool = True
    expected_version: int = Field(ge=1)

def _p5_guard(request:Request,workspace:str):
    # Admin/steward reviewer-only: job outputs may contain sensitive profiling
    # details and federation must require explicit publication privileges.
    u=_p3_guard(request,workspace)
    return u

@router.get('/phase5/overview')
def p5_overview(request:Request,workspace:str):
    _p5_guard(request,workspace)
    return safe(lambda:p5.overview(workspace))

@router.get('/phase5/jobs')
def p5_jobs(request:Request,workspace:str,limit:int=50,status:str=''):
    _p5_guard(request,workspace)
    if status and status not in {'queued','running','retry','dead','succeeded','cancelled'}:raise HTTPException(400,'Invalid job status')
    return {'jobs':p5.jobs.list(workspace,min(max(limit,1),100),status or None)}

@router.post('/phase5/jobs')
def p5_job_submit(request:Request,workspace:str,body:P5Submit):
    u=_p5_guard(request,workspace)
    return safe(lambda:p5.submit(workspace,body.model_dump(),u.user_id))

@router.get('/phase5/jobs/{job_id}')
def p5_job_get(job_id:str,request:Request,workspace:str):
    _p5_guard(request,workspace)
    return safe(lambda:{'job':p5.jobs.get(workspace,job_id),'events':p5.jobs.events(workspace,job_id)})

@router.post('/phase5/jobs/{job_id}/cancel')
def p5_job_cancel(job_id:str,request:Request,workspace:str):
    u=_p5_guard(request,workspace)
    return safe(lambda:p5.jobs.cancel(workspace,job_id,u.user_id))

@router.post('/phase5/jobs/{job_id}/retry')
def p5_job_retry(job_id:str,request:Request,workspace:str):
    u=_p5_guard(request,workspace)
    return safe(lambda:p5.jobs.retry(workspace,job_id,u.user_id))

@router.get('/phase5/domains')
def p5_domains(request:Request,workspace:str):
    _p5_guard(request,workspace)
    return safe(lambda:{'domains':p5.domains(workspace)})

@router.post('/phase5/domains')
def p5_create_domain(body:P5Domain,request:Request,workspace:str):
    u=_p5_guard(request,workspace)
    if not security.can(u,'publish',workspace):raise HTTPException(403,'Publishing privilege required')
    return safe(lambda:p5.create_domain(workspace,body.model_dump(),u.user_id))

@router.post('/phase5/domains/{domain_id}/publish')
def p5_domain_publish(domain_id:str,body:P5Version,request:Request,workspace:str):
    u=_p5_guard(request,workspace)
    if not security.can(u,'publish',workspace):raise HTTPException(403,'Publishing privilege required')
    return safe(lambda:p5.publish_domain(workspace,domain_id,u.user_id,body.expected_version))

@router.post('/phase5/domains/{domain_id}/grant')
def p5_domain_grant(domain_id:str,body:P5Grant,request:Request,workspace:str):
    u=_p5_guard(request,workspace)
    if not security.can(u,'publish',workspace):raise HTTPException(403,'Publishing privilege required')
    return safe(lambda:p5.grant(workspace,domain_id,body.target_workspace,u.user_id,body.expected_version,body.allow))

@router.post('/phase5/domains/{domain_id}/revoke')
def p5_domain_revoke(domain_id:str,body:P5Version,request:Request,workspace:str):
    u=_p5_guard(request,workspace)
    if not security.can(u,'publish',workspace):raise HTTPException(403,'Publishing privilege required')
    return safe(lambda:p5.revoke(workspace,domain_id,u.user_id,body.expected_version))

@router.get('/phase5/federation')
def p5_federation(request:Request,workspace:str):
    _p5_guard(request,workspace)
    return safe(lambda:{'domains':p5.federation(workspace)})

@router.get('/phase5/search')
def p5_search(request:Request,workspace:str,q:str,limit:int=20,federated:bool=True):
    _p5_guard(request,workspace)
    return safe(lambda:p5.search(workspace,q,limit,federated))

@router.get('/phase5/benchmarks')
def p5_benchmarks(request:Request,workspace:str):
    _p5_guard(request,workspace)
    return safe(lambda:{'runs':p5.benchmarks(workspace)})

@router.get('/phase5/readiness')
def p5_readiness(request:Request,workspace:str):
    _p5_guard(request,workspace)
    return safe(lambda:{'workspace_id':workspace,
        'phase5':p5.overview(workspace),
        'native_windows_ec2_tested':False,
        'shared_multi_host_queue_configured':p5.overview(workspace)['cross_machine_worker_leasing'],
        'cross_warehouse_parity_tested':False,
        'production_accepted':False})

# Shared LLM connectivity, guided semantic preparation and business-result acceptance.
from app.services.llm_planner_service import LLMPlannerService
from app.services.guided_onboarding_service import GuidedOnboardingService
from app.services.business_benchmark_service import BusinessBenchmarkService

guided=GuidedOnboardingService();business_benchmarks=BusinessBenchmarkService()

@router.get('/llm/status')
def llm_status(request:Request):
    user_ctx(request)
    return LLMPlannerService().status()

class GuidedPrepareRequest(BaseModel):
    owner: str = Field(min_length=1,max_length=120)

class GuidedReviewRequest(BaseModel):
    items: list[dict] = Field(min_length=1,max_length=100)
    note: str = Field(min_length=5,max_length=1500)

@router.get('/onboarding/guided')
def guided_status(request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:guided.status(workspace))

@router.post('/onboarding/guided/prepare')
def guided_prepare(body:GuidedPrepareRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace)
    return safe(lambda:guided.prepare(workspace,u.user_id,body.owner))

@router.post('/onboarding/guided/review')
def guided_review(body:GuidedReviewRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace,any(i.get('decision')=='certified' for i in body.items))
    return safe(lambda:guided.review_batch(workspace,body.items,u.user_id,body.note))

@router.post('/onboarding/guided/publish')
def guided_publish(body:P3ReleaseRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace,True)
    return safe(lambda:guided.publish(workspace,body.version,body.note,u.user_id))

@router.post('/onboarding/guided/refresh')
def guided_refresh(request:Request,workspace:str):
    u=_p3_guard(request,workspace)
    return safe(lambda:guided.refresh(workspace,u.user_id))

class RelationshipCreateRequest(BaseModel):
    from_asset: str
    to_asset: str
    from_columns: list[str] = Field(min_length=1,max_length=8)
    to_columns: list[str] = Field(min_length=1,max_length=8)
    role: str = Field(default='',max_length=100)

@router.post('/phase2/relationships')
def relationship_create(body:RelationshipCreateRequest,request:Request,workspace:str):
    u=_p2_guard(request,workspace,True)
    return safe(lambda:p2.create_relationship(workspace,body.model_dump(),u.user_id))

class BusinessCaseRequest(BaseModel):
    release_id: str
    question: str = Field(min_length=2,max_length=500)
    expected: str = 'answer'
    reference_sql: str = Field(default='',max_length=10000)
    previous_plan: dict | None = None
    reference_asset_id: str | None = None
    case_id: str | None = None

class BusinessRunRequest(BaseModel):
    release_id: str

@router.get('/benchmarks/business/cases')
def business_cases(request:Request,workspace:str):
    _p3_guard(request,workspace)
    return safe(lambda:{'cases':business_benchmarks.cases(workspace)})

@router.post('/benchmarks/business/cases')
def business_case(body:BusinessCaseRequest,request:Request,workspace:str):
    u=_p3_guard(request,workspace,True)
    return safe(lambda:business_benchmarks.save(workspace,body.model_dump(),u.user_id))

@router.post('/benchmarks/business/run')
def business_run(body:BusinessRunRequest,request:Request,workspace:str):
    _p3_guard(request,workspace,True)
    return safe(lambda:business_benchmarks.run(workspace,body.release_id))
