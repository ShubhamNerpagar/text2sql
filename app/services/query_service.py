"""Compatibility facade over the shared certified LLM workflow."""
from __future__ import annotations
from datetime import datetime, timezone
import uuid
from app.config import get_settings
from app.repositories.control_repository import ControlRepository
from app.repositories.learning_repository import LearningRepository
from app.services.market_service import MarketService
from app.services.security_service import SecurityService, UserContext
from app.services.conversation_service import ConversationService
from app.services.semantic_registry_service import SemanticRegistryService


class QueryService:
    def __init__(self):
        self.s=get_settings();self.markets=MarketService();self.control=ControlRepository()
        self.security=SecurityService();self.conversations=ConversationService();self.learning=LearningRepository()
        self.registry=SemanticRegistryService()

    def authorize(self,user,workspace):
        if not self.security.can(user,'query',workspace):raise PermissionError('Query permission denied')
        if self.security.denied_columns(user,workspace):raise PermissionError('Certified analytics requires unrestricted access to its semantic columns')
        if self.security.row_predicates(user,workspace):raise PermissionError('Row-policy compilation is required before granting analytics access')

    def run(self,question,market,execute=True,database=None,conversation_id=None,data_source=None,user=None,release_id=None,approved_plan=None):
        from app.services.unified_ask_service import UnifiedAskService
        from app.services.advanced_query_service import AdvancedQueryService
        user=user or UserContext('local-user',self.s.default_roles,{})
        self.authorize(user,market)
        release_id=release_id or self.registry.latest_release(market);previous=None
        if data_source or database:
            from app.services.phase2_service import Phase2Service
            scope=Phase2Service().scope(market)
            if data_source and scope['source_id']!=data_source:raise ValueError('Connector does not match the certified workspace')
            if database and database not in {t['database'] for t in scope['tables']}:raise ValueError('Database does not match the certified workspace')
        if conversation_id:
            c=self.conversations.get(conversation_id)
            if c['market']!=market or (c['user_id']!=user.user_id and not self.security.is_admin(user)):raise PermissionError('Conversation access denied')
            previous=c.get('context',{}).get('structured_plan')
        if approved_plan is not None:
            out=AdvancedQueryService().run(market,release_id,question,plan=approved_plan,execute=execute)
            out['structured_plan']=approved_plan
        else:out=UnifiedAskService().ask(market,release_id,question,execute,previous)
        if data_source and out.get('plan',{}).get('source_id')!=data_source:raise ValueError('Requested connector does not match the certified release')
        if database and out.get('plan',{}).get('database')!=database:raise ValueError('Requested database does not match the certified release')
        result={k:out.get(k) for k in ('rows','columns','row_count','usage')} if out.get('executed') else None
        response={**out,'query_id':'q-'+uuid.uuid4().hex[:16],'conversation_id':conversation_id,
            'status':'success' if out.get('executed') else out['status'],'market':market,'mode':self.s.app_mode,
            'data_source':out.get('plan',{}).get('source_id'),'sql':out.get('plan',{}).get('sql'),'result':result,
            'security':self.security.summary(user,market),'routing':{'route':'certified_llm_plan','offline_fallback':False},
            'validation':{'status':'VALID' if out.get('plan') else 'NOT_RUN'},'cost':{},'created_at':datetime.now(timezone.utc).isoformat()}
        self.learning.put_query({k:response.get(k) for k in ('query_id','question','market','status','sql','created_at')})
        self.control.put('AUDIT',response['query_id'],{'event':'query.execute' if execute else 'query.plan','actor':user.user_id,'workspace':market,
            'release_id':release_id,'metric_ids':out.get('plan',{}).get('metric_ids',[]),'created_at':response['created_at']})
        if conversation_id:self.conversations.append(conversation_id,question,response)
        return response
