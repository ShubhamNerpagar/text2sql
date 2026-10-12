from __future__ import annotations
import re
from app.services.market_service import MarketService
from app.repositories.semantic_repository import SemanticRepository

class DatasetExplanationService:
    """Deterministic metadata-only answers for dataset/schema explanation questions."""
    PATTERNS=(
        r"what(?:'s| is) (?:the |this )?data about",
        r"what(?:'s| is) (?:the |this )?dataset about",
        r"explain (?:me )?(?:the |this )?dataset",
        r"describe (?:the |this )?dataset",
        r"tell me about (?:the |this )?data",
        r"what (?:tables|columns|fields) (?:are|do) (?:in|we have|this dataset)",
        r"summari[sz]e (?:the |this )?(?:data|dataset|schema)",
    )
    def __init__(self):
        self.markets=MarketService(); self.repo=SemanticRepository()

    def matches(self,question:str)->bool:
        q=' '.join(str(question or '').lower().split())
        return any(re.search(p,q) for p in self.PATTERNS)

    def describe(self,workspace:str)->dict:
        ctx=self.markets.context(workspace); dd=self.repo.ontology().get('data_dictionary',{}) or {}
        tables=[]; column_count=0
        for db,dbtables in dd.items():
            for table,info in (dbtables or {}).items():
                memberships=set(info.get('workspace_ids') or ([info.get('market')] if info.get('market') else []))
                if memberships and workspace not in memberships: continue
                cols=info.get('columns',[]) or []; column_count+=len(cols)
                tables.append({'database':db,'table':table,'description':info.get('description',''),'columns':[c.get('name') for c in cols if c.get('name')]})
        metrics=ctx.get('metrics',{}) or {}; entities=ctx.get('entities',{}) or {}; dimensions=ctx.get('dimensions',{}) or {}
        table_names=', '.join(x['table'] for x in tables[:8]) or 'none'
        entity_names=', '.join((x or {}).get('label',k) for k,x in list(entities.items())[:8]) or 'none'
        metric_names=', '.join((x or {}).get('label',k) for k,x in list(metrics.items())[:8]) or 'none yet'
        status_counts={}
        for spec in metrics.values():
            st=str((spec or {}).get('status','inferred')).lower(); status_counts[st]=status_counts.get(st,0)+1
        parts=[
            f"This workspace contains {len(tables)} table{'s' if len(tables)!=1 else ''} and {column_count} cataloged columns.",
            f"Main tables: {table_names}.",
            f"Inferred business entities: {entity_names}.",
            f"Available metric definitions: {metric_names}.",
        ]
        if status_counts.get('inferred'):
            parts.append(f"{status_counts['inferred']} metric definition{'s are' if status_counts['inferred']!=1 else ' is'} inferred from metadata and should be reviewed in Semantic Studio before production certification.")
        parts.append('The onboarding process used catalog metadata only; sample business rows were not required.')
        return {
            'answer_text':' '.join(parts),
            'tables':tables,
            'table_count':len(tables),
            'column_count':column_count,
            'entity_count':len(entities),
            'dimension_count':len(dimensions),
            'metric_count':len(metrics),
            'metric_status_counts':status_counts,
        }
