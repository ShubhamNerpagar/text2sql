from __future__ import annotations
from collections import defaultdict, deque
from app.services.graph_rag_service import GraphRAGService
from app.repositories.learning_repository import LearningRepository

class LineageService:
    def __init__(self): self.graphs=GraphRAGService(); self.learning=LearningRepository()
    def graph(self,market=''):
        g=self.graphs.graph(market); edges=[]
        for e in g.get('edges',[]):
            if e.get('edge_type') in {'DERIVED_FROM','CALCULATED_FROM','REPRESENTED_BY','JOINS_TO','SUPPORTS','HAS_COLUMN','HAS_TABLE','HOSTS_DATABASE','USES_DATA_SOURCE'}: edges.append(e)
        # Query usage becomes lineage too.
        nodes=dict(g.get('nodes',{}))
        for q in self.learning.recent_queries(200):
            if q.get('market')!=market: continue
            qid='query:'+q.get('query_id',''); nodes[qid]={'id':qid,'label':q.get('question',''), 'node_type':'query','summary':'Observed user query','attributes':{'status':q.get('status')}}
            for t in (q.get('plan_summary',{}) or {}).get('tables',[]) or []:
                tid='table:'+t
                if tid in nodes: edges.append({'source_id':qid,'target_id':tid,'edge_type':'USED_TABLE','trusted_for_queries':True,'confidence':1.0,'status':'observed','label':'','evidence':{},'attributes':{}})
        return {'market':market,'nodes':nodes,'edges':edges,'stats':{'nodes':len(nodes),'edges':len(edges)}}
    def impact(self,market,node_id,direction='both',depth=3,limit=150):
        g=self.graph(market); adj=defaultdict(list)
        for e in g['edges']:
            if direction in {'both','downstream'}: adj[e['source_id']].append((e['target_id'],e))
            if direction in {'both','upstream'}: adj[e['target_id']].append((e['source_id'],e))
        if node_id not in g['nodes']: raise KeyError(node_id)
        q=deque([(node_id,0)]); seen={node_id}; out_edges=[]
        while q and len(seen)<limit:
            cur,d=q.popleft()
            if d>=depth: continue
            for nxt,e in adj.get(cur,[]):
                out_edges.append(e)
                if nxt not in seen: seen.add(nxt); q.append((nxt,d+1))
        return {'center':node_id,'nodes':[g['nodes'][x] for x in seen],'edges':out_edges[:limit*3],'direction':direction,'depth':depth}
