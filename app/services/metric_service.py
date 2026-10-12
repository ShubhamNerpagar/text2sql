from __future__ import annotations
from collections import defaultdict, deque
from app.services.market_service import MarketService

class MetricService:
    ALLOWED_AGGREGATIONS={'sum','count','count_distinct','avg','min','max','derived','custom','ratio'}
    ALLOWED_ADDITIVITY={'additive','semi_additive','non_additive'}
    ALLOWED_COMPARISONS={'none','period_over_period','year_over_year','month_over_month','quarter_over_quarter'}
    def __init__(self): self.markets=MarketService()
    def catalog(self,market=''):
        ctx=self.markets.context(market); metrics=ctx.get('metrics',{}) or {}; out=[]
        for mid,spec in metrics.items():
            spec=spec or {}; deps=list(spec.get('depends_on',[]) or []); sources=list(spec.get('preferred_sources',[]) or [])
            verified=[x for x in sources if str(x.get('status','')).lower() in {'verified','approved','governed','certified'}]
            out.append({'id':mid,'label':spec.get('label',mid.replace('_',' ').title()),'description':spec.get('description',''),'status':spec.get('status','draft'),'owner':spec.get('owner',{}),'unit':spec.get('unit'),'format':spec.get('format'),'aggregation':spec.get('aggregation','derived' if deps else 'custom'),'additivity':spec.get('additivity','additive'),'time_semantics':spec.get('time_semantics',{}),'currency':spec.get('currency',{}),'depends_on':deps,'dimensions':spec.get('dimensions',[]),'comparison':spec.get('comparison','none'),'comparison_grain':spec.get('comparison_grain',(spec.get('time_semantics',{}) or {}).get('default_grain','month')),'semantics':spec.get('semantics',{}),'formula':spec.get('semantics',{}).get('expression',spec.get('formula')),'window':spec.get('window'),'filters':spec.get('filters',[]),'source_count':len(sources),'verified_source_count':len(verified),'certified':str(spec.get('status','')).lower()=='certified','contract_version':spec.get('contract_version',1)})
        return {'market':market,'calendar':ctx.get('calendar',{}) or {},'metrics':out,'validation':self.validate(market)}
    def validate(self,market=''):
        ctx=self.markets.context(market); metrics=ctx.get('metrics',{}) or {}; bindings=ctx.get('bindings',{}) or {}; dimensions=set((bindings.get('dimensions',{}) or {}))|set((bindings.get('concepts',{}) or {}))|set((bindings.get('dates',{}) or {})); issues=[]; warnings=[]; graph=defaultdict(list); indeg={k:0 for k in metrics}
        for mid,spec in metrics.items():
            spec=spec or {}; agg=str(spec.get('aggregation','derived' if spec.get('depends_on') else 'custom')).lower(); add=str(spec.get('additivity','additive')).lower(); comp=str(spec.get('comparison','none')).lower()
            if agg not in self.ALLOWED_AGGREGATIONS: issues.append({'metric':mid,'type':'invalid_aggregation','value':agg})
            if add not in self.ALLOWED_ADDITIVITY: issues.append({'metric':mid,'type':'invalid_additivity','value':add})
            if comp not in self.ALLOWED_COMPARISONS: issues.append({'metric':mid,'type':'invalid_comparison','value':comp})
            for dep in spec.get('depends_on',[]) or []:
                if dep not in metrics: issues.append({'metric':mid,'type':'missing_dependency','dependency':dep})
                else: graph[dep].append(mid); indeg[mid]=indeg.get(mid,0)+1
            if str(spec.get('status','')).lower() in {'certified','governed'} and not (spec.get('preferred_sources') or spec.get('depends_on')): issues.append({'metric':mid,'type':'missing_source'})
            unknown=sorted(set(spec.get('dimensions',[]) or [])-dimensions)
            if unknown: issues.append({'metric':mid,'type':'unknown_dimensions','dimensions':unknown})
            if spec.get('time_semantics') and not (spec.get('time_semantics') or {}).get('default_dimension'): warnings.append({'metric':mid,'type':'time_dimension_not_declared'})
            if comp!='none' and not spec.get('depends_on'): warnings.append({'metric':mid,'type':'comparison_without_dependencies'})
            sources=spec.get('preferred_sources',[]) or []; verified=[x for x in sources if str(x.get('status','')).lower() in {'verified','approved','governed','certified'}]
            if str(spec.get('status','')).lower()=='certified' and not verified and not spec.get('depends_on'): issues.append({'metric':mid,'type':'certified_without_verified_source'})
            if not spec.get('owner'): warnings.append({'metric':mid,'type':'owner_missing'})
        q=deque([k for k,v in indeg.items() if v==0]); seen=[]
        while q:
            x=q.popleft(); seen.append(x)
            for y in graph[x]: indeg[y]-=1; q.append(y) if indeg[y]==0 else None
        cycles=[k for k,v in indeg.items() if v>0]
        if cycles: issues.append({'type':'dependency_cycle','metrics':cycles})
        return {'ok':not issues,'issues':issues,'warnings':warnings,'metric_count':len(metrics),'certified_count':sum(1 for x in metrics.values() if str((x or {}).get('status','')).lower()=='certified'),'dependency_graph':{k:list(v) for k,v in graph.items()},'validated_nodes':len(seen)}
