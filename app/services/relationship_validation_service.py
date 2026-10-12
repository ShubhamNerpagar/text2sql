from __future__ import annotations
from datetime import datetime, timezone
from app.repositories.semantic_repository import SemanticRepository
from app.services.relationship_service import RelationshipService
from app.services.data_source_service import DataSourceService
from app.services.market_service import MarketService

class RelationshipValidationService:
    """Connector-neutral, aggregate-only relationship validation."""
    def __init__(self): self.repo=SemanticRepository(); self.sources=DataSourceService(); self.workspaces=MarketService()
    def validate(self,rel_id:str,coverage_threshold:float=.90,uniqueness_threshold:float=.90,workspace=None,actor='relationship-validator')->dict:
        if rel_id.startswith('rel:'):
            from app.services.phase2_service import Phase2Service
            matches=[r for r in RelationshipService().all() if r['id']==rel_id and (not workspace or r['workspace_id']==workspace)]
            if len(matches)>1:raise ValueError('Specify the relationship workspace')
            r=matches[0] if matches else None
            if not r:raise KeyError(rel_id)
            out=Phase2Service().validate_relationship(r['workspace_id'],rel_id,actor)
            return {'relationship':out,'evidence':out['evidence'],'promoted':out.get('trusted_for_queries',False)}
        rows=RelationshipService().all(); rel=next((r for r in rows if r.get('id')==rel_id),None)
        if not rel: raise KeyError(rel_id)
        workspace=rel.get('market') or rel.get('workspace_id')
        if not workspace: raise ValueError('Relationship is not assigned to a workspace.')
        ctx=self.workspaces.context(workspace); source_id=(ctx.get('market',{}) or {}).get('data_source') or (ctx.get('data_sources',{}) or {}).get('default')
        stats=self.sources.relationship_stats(source_id,rel)
        sd,td,tr,md=[float(stats.get(k) or 0) for k in ('source_distinct','target_distinct','target_non_null_rows','matched_distinct')]
        coverage=md/sd if sd else 0.0; uniqueness=td/tr if tr else 0.0; passed=coverage>=coverage_threshold and uniqueness>=uniqueness_threshold
        evidence={**stats,'source_id':source_id,'referential_coverage':round(coverage,4),'target_uniqueness':round(uniqueness,4),'coverage_threshold':coverage_threshold,'uniqueness_threshold':uniqueness_threshold,'validated_at':datetime.now(timezone.utc).isoformat(),'passed':passed}
        doc=self.repo.relationships(); rels=doc.get('relationships',[])
        idx=next((i for i,r in enumerate(rels) if (r.get('id') or f'rel-{i}')==rel_id),None)
        if idx is None: raise KeyError(rel_id)
        rels[idx]['data_validation']=evidence
        if passed: rels[idx]['status']='data_validated'
        doc['last_updated']=datetime.now(timezone.utc).isoformat(); self.repo.save_relationships(doc)
        return {'relationship':RelationshipService().all()[idx],'evidence':evidence,'promoted':passed}
