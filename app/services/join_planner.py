from __future__ import annotations
from collections import defaultdict, deque
from app.services.relationship_service import RelationshipService
from app.services.market_service import MarketService

class JoinPlanner:
    """Builds join paths only from runtime-trusted relationships and explicit governed market joins."""
    def __init__(self): self.rels=RelationshipService(); self.markets=MarketService()

    @staticmethod
    def _node(db,table): return f"{db}.{table}" if db else table

    def edges(self,market:str)->list[dict]:
        out=[]
        for r in self.rels.trusted():
            l=self._node(r.get('from_db',''),r.get('from_table','')); rr=self._node(r.get('to_db',''),r.get('to_table',''))
            if not l or not rr: continue
            out.append({
                'id':r.get('id'),'left':l,'right':rr,
                'condition':f"{{left}}.{r.get('from_column')} = {{right}}.{r.get('to_column')}",
                'left_column':r.get('from_column'),'right_column':r.get('to_column'),
                'type':'column_equality','status':r.get('status'),'source':r.get('source','relationship_store'),
                'confidence':r.get('confidence_score',1.0),'trusted':True,
            })
        ctx=self.markets.context(market)
        for i,j in enumerate(ctx.get('governed_joins',[]) or []):
            if str(j.get('status','')).lower() not in {'verified','data_validated','approved','governed'}: continue
            left=j.get('left',{}); right=j.get('right',{})
            l=self._node(left.get('database',''),left.get('table','')); rr=self._node(right.get('database',''),right.get('table',''))
            if not l or not rr: continue
            out.append({
                'id':j.get('id',f'{market}-governed-{i+1}'),'left':l,'right':rr,
                'condition':j.get('condition',''),'type':'governed_expression','status':j.get('status','verified'),
                'source':'market_semantic_package','confidence':float(j.get('confidence',1.0)),'trusted':True,
                'description':j.get('description',''),
            })
        # Exact duplicate directions are unnecessary. Prefer explicit market-governed
        # joins, then human/data-validated relationships, then imported links. This
        # makes equal-length paths deterministic and governance-aware.
        priority={'market_semantic_package':100,'manual':95,'relationship_store':80,'tables_link':75,'s3':75}
        def rank(e):
            status_bonus={'verified':20,'approved':20,'governed':20,'data_validated':15,'edited':12,'s3_imported':10}.get(str(e.get('status','')).lower(),0)
            return (priority.get(str(e.get('source','')).lower(),70)+status_bonus+float(e.get('confidence',0)), str(e.get('id','')))
        out.sort(key=rank,reverse=True)
        uniq={}
        for e in out:
            key=(e['left'],e['right'],e['condition'])
            if key not in uniq: uniq[key]=e
        return list(uniq.values())

    def _graph(self,market:str):
        adj=defaultdict(list)
        for e in self.edges(market):
            adj[e['left']].append((e['right'],e,False))
            adj[e['right']].append((e['left'],e,True))
        return adj

    def shortest_path(self,market:str,start:str,target:str)->list[dict]|None:
        if start==target: return []
        adj=self._graph(market); q=deque([(start,[])]); seen={start}
        while q:
            node,path=q.popleft()
            for nxt,e,reverse in adj.get(node,[]):
                if nxt in seen: continue
                step={**e,'from':node,'to':nxt,'reverse':reverse}
                np=path+[step]
                if nxt==target: return np
                seen.add(nxt); q.append((nxt,np))
        return None

    def connect(self,market:str,tables:list[str])->dict:
        tables=list(dict.fromkeys(t for t in tables if t))
        if len(tables)<=1: return {'connected':True,'root':tables[0] if tables else None,'joins':[],'unreachable':[]}
        root=tables[0]; joined={root}; joins=[]; unreachable=[]
        for target in tables[1:]:
            best=None
            for source in list(joined):
                p=self.shortest_path(market,source,target)
                if p is not None and (best is None or len(p)<len(best)): best=p
            if best is None:
                unreachable.append(target); continue
            for step in best:
                key=(step['id'],step['from'],step['to'])
                if not any((x['id'],x['from'],x['to'])==key for x in joins): joins.append(step)
                joined.add(step['from']); joined.add(step['to'])
        return {'connected':not unreachable,'root':root,'joins':joins,'unreachable':unreachable}

    @staticmethod
    def prompt_lines(plan:dict)->str:
        if not plan.get('joins'): return 'No joins are required.'
        lines=[]
        for j in plan['joins']:
            cond=j.get('condition','')
            lines.append(f"- {j['from']} -> {j['to']} | {cond} | source={j.get('source')} | status={j.get('status')}")
        return '\n'.join(lines)
