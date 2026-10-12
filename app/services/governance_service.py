from __future__ import annotations
from app.repositories.semantic_repository import SemanticRepository
from app.services.market_service import MarketService
from app.services.relationship_service import RelationshipService
from app.services.graph_rag_service import GraphRAGService
from app.repositories.control_repository import ControlRepository


class GovernanceService:
    """Unified semantic governance view across physical and business metadata."""
    def __init__(self):
        self.repo=SemanticRepository(); self.markets=MarketService(); self.relationships=RelationshipService(); self.graph=GraphRAGService(); self.control=ControlRepository()

    def queue(self,market:str)->dict:
        ctx=self.markets.context(market); ont=self.repo.ontology(); dd=ont.get('data_dictionary',{}) or {}
        items=[]
        for r in self.relationships.all():
            if not r.get('trusted_for_queries') and r.get('status')!='rejected':
                items.append({'id':r.get('id'),'type':'relationship','status':r.get('status'),'severity':'high' if float(r.get('confidence_score',0))>=.85 else 'medium',
                              'title':f"{r.get('from_table')}.{r.get('from_column')} → {r.get('to_table')}.{r.get('to_column')}",
                              'reason':'Candidate relationship is blocked from production queries until validated or verified.'})
        for db,tables in dd.items():
            for table,info in tables.items():
                memberships=set(info.get('workspace_ids') or ([info.get('market')] if info.get('market') else []))
                if memberships and market not in memberships: continue
                for c in info.get('columns',[]) or []:
                    desc=c.get('description') or c.get('meaningful_name') or c.get('comment')
                    status=str(c.get('description_status','')).lower()
                    if not desc or status in {'ai_generated','draft',''}:
                        if not desc or status=='ai_generated':
                            items.append({'id':f"{db}.{table}.{c.get('name')}",'type':'column_description','status':status or ('missing' if not desc else 'unreviewed'),
                                          'severity':'low','title':f"{table}.{c.get('name')}",
                                          'reason':'Column description is missing or has not been human-reviewed.'})
        for mid,spec in (ctx.get('metrics',{}) or {}).items():
            sources=spec.get('preferred_sources',[]) or []
            governed=any(str(x.get('status','')).lower() in {'verified','approved','governed','certified'} for x in sources) or mid=='record_count'
            if not governed:
                items.append({'id':mid,'type':'metric','status':'draft','severity':'high','title':spec.get('label',mid),'reason':'Metric has no verified/governed physical source.'})
        for row in ctx.get('verified_queries',[]) or []:
            if str(row.get('status','verified')).lower() not in {'verified','approved','golden'}:
                items.append({'id':row.get('id'),'type':'verified_query','status':row.get('status','draft'),'severity':'medium','title':row.get('question',row.get('id')),'reason':'Query example is not approved for retrieval.'})
        for sug in self.control.list('SUGGESTION',300):
            if sug.get('market')!=market or sug.get('type')=='semantic_overlay': continue
            if sug.get('status') in {'approved','certified','rejected','deprecated'}: continue
            items.append({'id':sug.get('id'),'type':'ontology_inference','status':sug.get('status','inferred'),'severity':'medium','title':sug.get('label',sug.get('source','suggestion')),'reason':sug.get('reason','Automatically inferred semantic knowledge requires review.')})
        graph=self.graph.graph(market)
        by_type={}
        for x in items: by_type[x['type']]=by_type.get(x['type'],0)+1
        return {'market':market,'total':len(items),'by_type':by_type,'items':items[:500],'graph_fingerprint':graph.get('fingerprint'),'graph_stats':graph.get('stats',{})}
