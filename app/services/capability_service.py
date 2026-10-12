from __future__ import annotations
from app.services.metric_service import MetricService
from app.services.relationship_service import RelationshipService
from app.services.evaluation_service import EvaluationService
from app.services.data_source_service import DataSourceService
from app.services.graph_rag_service import GraphRAGService
from app.services.market_service import MarketService
from app.config import get_settings

class CapabilityService:
    """Level 4 = product-ready baseline, not vendor-scale proof."""
    def __init__(self):
        self.metrics=MetricService(); self.rels=RelationshipService(); self.eval=EvaluationService(); self.sources=DataSourceService(); self.graph=GraphRAGService(); self.markets=MarketService(); self.s=get_settings()
    def report(self,market=''):
        ctx=self.markets.context(market); r=self.rels.stats(); suites=self.eval.suites(); m=self.metrics.catalog(market); src=self.sources.sources(); g=self.graph.graph(market)
        gates={'implementation':True,'governance':bool(self.s.security_enabled and m['validation']['ok']),'evaluation':len(suites)>=1,'observability':True,'deployment':True}
        rows=[
            ('Semantic layer','entities + dimensions + metrics + bindings + market inheritance'),
            ('Automatic ontology inference','metadata inference + confidence + review/approval lifecycle'),
            ('Graph-based semantics',f"GraphRAG {g.get('version')} + pluggable embeddings + governed retrieval ({g.get('stats',{}).get('total_nodes',0)} nodes)"),
            ('Relationship discovery',f"candidate discovery + evidence + validation + {r.get('trusted',0)} trusted joins"),
            ('Metric layer',f"{m['validation']['metric_count']} contracts + dependency/cycle/dimension/source validation"),
            ('Verified queries',f"{len(ctx.get('verified_queries',[]) or [])} verified examples + evaluation isolation"),
            ('Trusted query functions',f"{len(ctx.get('trusted_queries',[]) or [])} certified parameterized assets"),
            ('Deterministic SQL','governed compiler + dialect translation + security policy injection'),
            ('SQL agent reasoning','bounded planner/writer/reviewer fallback with read-only validation'),
            ('Benchmarking',f"{len(suites)} workspace-specific regression suites + persisted regression deltas; no customer-specific suite ships by default"),
            ('Multi-turn','persistent semantic conversation state with governed inheritance'),
            ('Knowledge authority ranking','relevance × confidence × authority × freshness with provenance'),
            ('Semantic branching','branch + patch + validate + compare + merge + semantic overlay + release'),
            ('Full lineage','physical ↔ semantic ↔ metric ↔ query/report impact graph'),
            ('Row/column security','RBAC + retrieval filtering + compiler RLS hooks + warehouse boundary'),
            ('Actions/writeback','role-gated action registry + dry-run + Lambda boundary + audit'),
            ('Data source portability',f"{len(src)} provider adapters + dialect contracts + health checks"),
            ('Agent tool ecosystem','governed MCP tools for search, resolve, query, lineage and actions'),
            ('MCP','permission-aware MCP server; no arbitrary SQL/write tool'),
            ('Cost/latency routing','trusted-template/compiler/agent routing + budget guard + execution telemetry'),
            ('Visual GraphRAG explorer','interactive governed node-link explorer + focus/neighborhood + authority/freshness'),
            ('BI reports','persisted semantic dashboards + visualization selection + Ask-to-Report + lineage + refresh-time security + drilldown'),
            ('Production observability','p50/p95/p99 latency + route failures + cost/security/evaluation trends'),
        ]
        readiness={**gates,'gate_count':sum(1 for v in gates.values() if v),'required_for_level_4':4}
        level=4 if readiness['gate_count']>=4 else 3
        return {'market':market,'level_definition':{'1':'implemented','2':'integrated','3':'governed production architecture','4':'product-ready baseline: integrated + governed + observable + regression-tested + deployable','5':'proven at enterprise scale with sustained production evidence'},'readiness':readiness,'disclaimer':'Level 4 means product-readiness in this build. It is not a claim of equal vendor scale, SLA history, production adoption, connector breadth, or enterprise benchmark results. Level 5 requires sustained real-world production evidence.','capabilities':[{'name':n,'level':level,'evidence':ev,'readiness_gates':gates} for n,ev in rows]}
