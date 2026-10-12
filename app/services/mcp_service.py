from __future__ import annotations
import json
from app.services.graph_rag_service import GraphRAGService
from app.services.market_service import MarketService
from app.services.lineage_service import LineageService
from app.services.plan_service import PlanService
from app.services.verified_query_service import VerifiedQueryService
from app.services.security_service import SecurityService, UserContext
from app.services.query_service import QueryService
from app.services.action_service import ActionService

class MCPService:
    """MCP-compatible semantic/analytics/action tool surface.

    Tools inherit the same GraphRAG filtering, query security and action permissions as the UI/API.
    There is deliberately no generic arbitrary-SQL or arbitrary-write tool.
    """
    def __init__(self):
        self.graph=GraphRAGService(); self.markets=MarketService(); self.lineage=LineageService(); self.plans=PlanService(); self.verified=VerifiedQueryService(); self.security=SecurityService(); self.queries=QueryService(); self.actions=ActionService()

    @staticmethod
    def _tool(name,description,properties,required=None):
        schema={'type':'object','properties':properties,'additionalProperties':False}
        if required: schema['required']=required
        return {'name':name,'description':description,'inputSchema':schema}

    def tools(self,user:UserContext,market=''):
        return [
            self._tool('search_semantic_model','Search governed GraphRAG business and physical semantics.',{'question':{'type':'string'},'market':{'type':'string'}},['question']),
            self._tool('get_metric','Get a governed metric definition.',{'metric_id':{'type':'string'},'market':{'type':'string'}},['metric_id']),
            self._tool('resolve_query','Resolve a natural-language question to a semantic plan without executing it.',{'question':{'type':'string'},'market':{'type':'string'}},['question']),
            self._tool('query_data','Run the governed analytics engine. Set execute=false for planning only.',{'question':{'type':'string'},'market':{'type':'string'},'execute':{'type':'boolean'},'data_source':{'type':'string'}},['question']),
            self._tool('get_lineage','Inspect upstream/downstream semantic lineage.',{'node_id':{'type':'string'},'market':{'type':'string'},'direction':{'type':'string','enum':['upstream','downstream','both']},'depth':{'type':'integer','minimum':1,'maximum':5}},['node_id']),
            self._tool('list_verified_queries','List governed verified query examples.',{'market':{'type':'string'}}),
            self._tool('list_actions','List governed actions available to the current identity.',{'market':{'type':'string'}}),
            self._tool('execute_action','Execute a named governed action; permissions and required parameters are enforced.',{'action_id':{'type':'string'},'market':{'type':'string'},'parameters':{'type':'object'},'dry_run':{'type':'boolean'}},['action_id']),
        ]

    def call(self,name,args,user:UserContext):
        market=args.get('market','')
        if name=='search_semantic_model':
            r=self.graph.search(args.get('question',''),market,top_k=8,depth=1); r['results']=self.security.filter_graph_results(r['results'],user,market); return r
        if name=='get_metric':
            if not self.security.can(user,'query',market): raise PermissionError('Query permission denied.')
            return (self.markets.context(market).get('metrics',{}) or {}).get(args.get('metric_id')) or {}
        if name=='resolve_query':
            if not self.security.can(user,'query',market): raise PermissionError('Query permission denied.')
            return self.queries.run(args.get('question',''),market,False,user=user)
        if name=='query_data':
            return self.queries.run(args.get('question',''),market,bool(args.get('execute',False)),data_source=args.get('data_source'),user=user)
        if name=='get_lineage':
            payload=self.lineage.impact(market,args.get('node_id',''),args.get('direction','both'),int(args.get('depth',2)))
            return self.security.filter_graph_payload(payload,user,market)
        if name=='list_verified_queries':
            if not self.security.can(user,'query',market): raise PermissionError('Query permission denied.')
            return {'verified_queries':self.verified.all(market)}
        if name=='list_actions':
            rows=[]
            for x in self.actions.definitions(market):
                allowed=not x.get('roles') or user.has_any(x.get('roles')) or self.security.is_admin(user)
                rows.append({**x,'allowed':allowed})
            return {'actions':rows}
        if name=='execute_action':
            return self.actions.execute(args.get('action_id'),market,args.get('parameters') or {},user,bool(args.get('dry_run',False)))
        raise KeyError(name)

    def handle(self,req:dict,user:UserContext):
        method=req.get('method'); rid=req.get('id'); params=req.get('params',{}) or {}
        if method=='initialize':
            result={'protocolVersion':'2025-06-18','serverInfo':{'name':'data-intelligence-platform','version':'7.0.1'},'capabilities':{'tools':{}}}
        elif method=='tools/list': result={'tools':self.tools(user,params.get('market',''))}
        elif method=='tools/call': result={'content':[{'type':'text','text':json.dumps(self.call(params.get('name'),params.get('arguments',{}),user),ensure_ascii=False)}]}
        else: return {'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}}
        return {'jsonrpc':'2.0','id':rid,'result':result}
