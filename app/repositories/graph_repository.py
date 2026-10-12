from __future__ import annotations
import json
from threading import RLock
from app.config import get_settings
from app.adapters.aws import AwsAdapter


class GraphRepository:
    """Persistence for market semantic graphs.

    Local/native execution uses state/semantic-graph-<market>.json. AWS durable mode uses the same
    serialized graph in S3 when SEMANTIC_BUCKET is configured. The graph is a
    rebuildable index; governed ontology/relationships remain the source of truth.
    """

    def __init__(self):
        self.s = get_settings()
        self.lock = RLock()
        self.aws = AwsAdapter() if self.s.is_aws else None

    def _path(self, market: str):
        return self.s.state_dir / f"semantic-graph-{market}.json"

    def _key(self, market: str) -> str:
        prefix = self.s.graph_key_prefix.strip("/")
        return f"{prefix}/{market}.json"

    def load(self, market: str) -> dict | None:
        if self.aws and self.s.semantic_bucket:
            remote = self.aws.get_json(self._key(market))
            if remote:
                return remote
        p = self._path(market)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def save(self, market: str, data: dict) -> None:
        with self.lock:
            if self.aws and self.s.semantic_bucket:
                self.aws.put_json(self._key(market), data)
            if self.s.persist_local_state or not self.aws:
                self._path(market).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
