from __future__ import annotations
import re
from app.services.market_service import MarketService
from app.services.value_index_service import ValueIndexService
from app.services.verified_query_service import VerifiedQueryService
from app.services.text_utils import normalize, token_set, phrase_in_text, clamp
from app.repositories.semantic_repository import SemanticRepository
from app.services.graph_rag_service import GraphRAGService

_MONTHS={
 'january':1,'jan':1,'janvier':1,'february':2,'feb':2,'fevrier':2,'février':2,'march':3,'mar':3,'mars':3,
 'april':4,'apr':4,'avril':4,'may':5,'mai':5,'june':6,'jun':6,'juin':6,'july':7,'jul':7,'juillet':7,
 'august':8,'aug':8,'aout':8,'août':8,'september':9,'sep':9,'septembre':9,'october':10,'oct':10,'octobre':10,
 'november':11,'nov':11,'novembre':11,'december':12,'dec':12,'decembre':12,'décembre':12
}

class SemanticResolver:
    """Deterministic first-pass semantic understanding before an LLM is allowed to plan SQL."""
    def __init__(self):
        self.markets=MarketService(); self.values=ValueIndexService(); self.vq=VerifiedQueryService(); self.repo=SemanticRepository(); self.graph=GraphRAGService()

    @staticmethod
    def _aliases(key:str,spec:dict)->set[str]:
        aliases={key, str(spec.get('label',key))}
        aliases.update(str(x) for x in spec.get('synonyms',[]) or [])
        aliases.update(str(x) for x in spec.get('aliases',[]) or [])
        return {a for a in aliases if a}

    def _match_named(self,question:str,items:dict,kind:str)->list[dict]:
        qtokens=token_set(question); out=[]
        for key,spec in (items or {}).items():
            spec=spec or {}; aliases=self._aliases(key,spec); matched=[]; best=0.0
            for a in aliases:
                atoks=token_set(a)
                if phrase_in_text(a,question) or (len(normalize(a))>3 and phrase_in_text(normalize(a)+'s',question)): matched.append(a); best=max(best,.98)
                elif atoks and atoks <= qtokens: matched.append(a); best=max(best,.90)
                elif atoks and qtokens:
                    overlap=len(atoks & qtokens)/len(atoks)
                    if overlap>=.67: matched.append(a); best=max(best,.55+.35*overlap)
            if matched:
                out.append({'id':key,'kind':kind,'label':spec.get('label',key.replace('_',' ').title()),
                            'description':spec.get('description',''),'matched':matched,'confidence':round(clamp(best),3),'spec':spec})
        out.sort(key=lambda x:x['confidence'],reverse=True)
        return out

    @staticmethod
    def _time(question:str)->dict:
        q=normalize(question); out={}
        years=[int(x) for x in re.findall(r'\b(20\d{2})\b',q)]
        if years: out['years']=sorted(set(years))
        qm=re.search(r'\bq([1-4])\b',q)
        if qm: out['quarter']=int(qm.group(1))
        for name,num in _MONTHS.items():
            if phrase_in_text(name,q): out['month']=num; out['month_text']=name; break
        if 'last year' in q or 'previous year' in q: out['relative']='previous_year'
        elif 'last month' in q or 'previous month' in q: out['relative']='previous_month'
        elif 'last quarter' in q or 'previous quarter' in q: out['relative']='previous_quarter'
        return out

    @staticmethod
    def _intent(question:str)->str:
        q=normalize(question)
        if any(x in q for x in ['compare','comparison','versus',' vs ','difference','growth']): return 'comparison'
        if any(x in q for x in ['trend','over time','monthly','weekly','rolling']): return 'trend'
        if any(x in q for x in ['list','show all','which','top ','bottom ','highest','lowest']): return 'breakdown'
        return 'aggregate'

    def table_candidates(self,question:str,concepts:list[dict],metrics:list[dict],values:list[dict],limit:int=8)->list[dict]:
        dd=self.repo.ontology().get('data_dictionary',{}); q=token_set(question); semantic_terms=set(q)
        for x in concepts+metrics:
            semantic_terms |= token_set(x['id']); semantic_terms |= token_set(x.get('label',''))
        for v in values:
            semantic_terms |= token_set(v['dimension']); semantic_terms |= token_set(v['canonical'])
        ranked=[]
        for db,tables in dd.items():
            for table,info in tables.items():
                cols=info.get('columns',[]) or []
                blob=' '.join([db,table,info.get('description','') or info.get('table_description','')] +
                              [f"{c.get('name','')} {c.get('meaningful_name','')} {c.get('description','')} {c.get('comment','')} {c.get('semantic_type','')}" for c in cols])
                bt=token_set(blob); overlap=semantic_terms & bt
                score=float(len(overlap))
                for tok in semantic_terms:
                    if tok in normalize(table): score += 2.5
                # Entity-oriented boosts.
                tn=normalize(table)
                for c in concepts:
                    for a in self._aliases(c['id'],c.get('spec',{})):
                        if normalize(a) and normalize(a) in tn: score += 3
                if score>0:
                    ranked.append({'database':db,'table':table,'score':round(score,3),'matched_terms':sorted(overlap)[:20]})
        ranked.sort(key=lambda x:(x['score'],x['database'],x['table']),reverse=True)
        return ranked[:limit]

    def resolve(self,question:str,market:str)->dict:
        ctx=self.markets.context(market); metrics=self._match_named(question,ctx.get('metrics',{}),'metric')
        concepts=self._match_named(question,ctx.get('concepts',{}),'concept')
        # Deterministic aggregate fallbacks for common phrasing that does not repeat a metric's formal name.
        qnorm=normalize(question); concept_ids={x['id'] for x in concepts}
        metric_map=ctx.get('metrics',{}) or {}
        if ('how many' in qnorm or phrase_in_text('count',qnorm) or 'number of' in qnorm or 'records' in qnorm or 'rows' in qnorm) and not metrics:
            preferred='invoice_count' if 'invoice' in concept_ids and 'invoice_count' in metric_map else None
            if not preferred:
                row_metrics=[mid for mid,spec in metric_map.items() if str((spec or {}).get('aggregation','')).lower()=='count' and not any((src or {}).get('column') for src in (spec or {}).get('preferred_sources',[]) or [])]
                if len(concept_ids)==1:
                    cid=next(iter(concept_ids)); preferred=next((mid for mid in row_metrics if (metric_map.get(mid) or {}).get('entity')==cid),None)
                if not preferred and len(row_metrics)==1: preferred=row_metrics[0]
            if preferred and preferred in metric_map:
                spec=metric_map[preferred] or {}; metrics=[{'id':preferred,'kind':'metric','label':spec.get('label',preferred.replace('_',' ').title()),'description':spec.get('description',''),'matched':['aggregate wording'],'confidence':.9,'spec':spec}]
        values=self.values.resolve(question,market); time=self._time(question); intent=self._intent(question)
        # Canonical values also imply their parent governed business dimension.
        existing_concepts={x['id'] for x in concepts}
        for v in values:
            dim=v.get('dimension')
            if dim in (ctx.get('concepts',{}) or {}) and dim not in existing_concepts:
                spec=(ctx.get('concepts',{}) or {}).get(dim) or {}
                concepts.append({'id':dim,'kind':'concept','label':spec.get('label',dim.replace('_',' ').title()),'description':spec.get('description',''),'matched':[v.get('label') or v.get('canonical')],'confidence':round(float(v.get('confidence',.9))*.95,3),'spec':spec})
                existing_concepts.add(dim)
        concepts.sort(key=lambda x:x['confidence'],reverse=True)
        literals=[]
        if any(x['id']=='department' for x in concepts):
            # Short numeric geography/code literals remain explicit and inspectable; market-specific interpretation must come from the runtime semantic workspace.
            for code in re.findall(r'(?<!\d)(\d{2})(?!\d)',question):
                literals.append({'dimension':'department','value':code,'confidence':.9,'source':'question_literal'})
        ambiguities=[]
        q=normalize(question)
        # Generic word "sales" is intentionally not silently bound to revenue vs units.
        if phrase_in_text('sales',q) and not any(phrase_in_text(x,q) for x in ['revenue','amount','vehicles sold','units','invoice','turnover']):
            ambiguities.append({'term':'sales','reason':'Sales can mean revenue, vehicle units, or invoice volume.','options':['revenue','vehicles_sold','invoice_count']})
        # Explicit metric candidates with close confidence can also require clarification.
        if len(metrics)>1 and metrics[0]['confidence']-metrics[1]['confidence']<.05:
            ambiguities.append({'term':'metric','reason':'More than one governed metric matches the wording.',
                                'options':[x['id'] for x in metrics[:3]]})
        # GraphRAG 3.0 retrieves the most relevant semantic/physical neighborhood.
        # It informs retrieval only; join authority still comes from JoinPlanner.
        graph_ctx=self.graph.search(question,market,top_k=8,depth=1)
        candidates=self.table_candidates(question,concepts,metrics,values)
        graph_scores={}
        for item in graph_ctx.get('results',[]):
            a=item.get('attributes',{}) or {}
            if item.get('node_type') in {'table','column'} and a.get('database') and a.get('table'):
                key=(a['database'],a['table']); graph_scores[key]=max(graph_scores.get(key,0),float(item.get('score',0)))
        merged={(x['database'],x['table']):dict(x) for x in candidates}
        for (db,table),score in graph_scores.items():
            row=merged.setdefault((db,table),{'database':db,'table':table,'score':0.0,'matched_terms':[]})
            row['graph_score']=round(score,4); row['score']=round(float(row.get('score',0))+score*6,4)
        candidates=sorted(merged.values(),key=lambda x:x.get('score',0),reverse=True)[:8]
        vq=self.vq.retrieve(question,market)
        evidence=[]
        if metrics: evidence.append('metric_dictionary')
        if concepts: evidence.append('business_concepts')
        if values: evidence.append('value_index')
        if time: evidence.append('time_parser')
        if vq: evidence.append('verified_queries')
        if graph_ctx.get('results'): evidence.append('graphrag_v3')
        confidence=.35
        confidence += .18 if metrics else 0
        confidence += .12 if concepts else 0
        confidence += .12 if values else 0
        confidence += .08 if candidates else 0
        confidence += .08 if vq else 0
        confidence += .08 if graph_ctx.get('results') else 0
        confidence -= .25 if ambiguities else 0
        return {
            'intent':intent,'metrics':metrics,'concepts':concepts,'resolved_values':values,'literals':literals,'time':time,
            'table_candidates':candidates,'verified_query_matches':vq,'graph_retrieval':graph_ctx,'ambiguities':ambiguities,
            'confidence':round(clamp(confidence),3),'evidence':evidence,
        }
