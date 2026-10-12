from __future__ import annotations
import json, re, uuid
from datetime import datetime, timezone
from threading import RLock
from app.config import get_settings
from app.adapters.aws import AwsAdapter
from app.services.market_service import MarketService
from app.services.graph_rag_service import GraphRAGService
from app.services.relationship_service import RelationshipService
from app.services.evaluation_service import EvaluationService
from app.repositories.control_repository import ControlRepository


class ReleaseService:
    """Lightweight semantic release/audit registry.

    A release records the exact market context + graph fingerprint + governance state
    used by a deployment. Runtime YAML remains source-controlled; the registry gives
    us traceability and rollback targets for future CI/CD automation.
    """
    def __init__(self):
        self.s=get_settings(); self.markets=MarketService(); self.graph=GraphRAGService(); self.rels=RelationshipService(); self.evals=EvaluationService(); self.lock=RLock(); self.aws=AwsAdapter() if self.s.is_aws else None
        self.path=self.s.state_dir/'semantic-releases.json'; self.control=ControlRepository()
    def _load(self):
        if self.aws and self.s.semantic_bucket:
            x=self.aws.get_json('semantic-releases/index.json')
            if x: return x
        if self.path.exists():
            return json.loads(self.path.read_text(encoding='utf-8'))
        return {'releases':[]}
    def _save(self,data):
        if self.aws and self.s.semantic_bucket: self.aws.put_json('semantic-releases/index.json',data)
        if self.s.persist_local_state or not self.aws: self.path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    def list(self,market:str|None=None):
        rows=self._load().get('releases',[])
        if market: rows=[x for x in rows if x.get('market')==market]
        return rows
    def publish(self,market:str,version:str,notes:str=''):
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version): raise ValueError('version must be semantic version format such as 7.0.0')
        ctx=self.markets.context(market); graph=self.graph.graph(market); latest=self.evals.latest()
        queue=__import__('app.services.governance_service',fromlist=['GovernanceService']).GovernanceService().queue(market)
        release={'id':'rel-'+uuid.uuid4().hex[:10],'market':market,'version':version,'notes':notes,'created_at':datetime.now(timezone.utc).isoformat(),
                 'graph_fingerprint':graph.get('fingerprint'),'graph_stats':graph.get('stats',{}),'relationship_stats':self.rels.stats(),
                 'governance_open_items':queue.get('total',0),'evaluation_score':latest.get('score') if latest else None,
                 'semantic_summary':{'concepts':len(ctx.get('concepts',{}) or {}),'metrics':len(ctx.get('metrics',{}) or {}),'dimensions':len((ctx.get('bindings',{}) or {}).get('dimensions',{}) or {}),'verified_queries':len(ctx.get('verified_queries',[]) or []),'trusted_queries':len(ctx.get('trusted_queries',[]) or []),'actions':len(ctx.get('actions',[]) or [])},
                 'control_plane':{'merged_branches':sum(1 for x in self.control.list('BRANCH',200) if x.get('market')==market and x.get('status')=='merged'),'security_enabled':self.s.security_enabled,'graph_version':graph.get('version')}}
        with self.lock:
            data=self._load(); data.setdefault('releases',[]).insert(0,release); data['releases']=data['releases'][:100]; self._save(data)
        if self.aws and self.s.semantic_bucket: self.aws.put_json(f"semantic-releases/{market}/{version}-{release['id']}.json",release)
        return release
