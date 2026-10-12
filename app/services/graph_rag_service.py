from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import combinations

from app.config import get_settings
from app.repositories.graph_repository import GraphRepository
from app.repositories.semantic_repository import SemanticRepository
from app.services.market_service import MarketService
from app.services.embedding_service import EmbeddingService
from app.services.relationship_service import RelationshipService
from app.services.type_inference import infer_semantic_type, are_types_fk_compatible
from app.services.text_utils import normalize, token_set
from app.services.verified_query_service import VerifiedQueryService
from app.services.value_index_service import ValueIndexService
from app.repositories.control_repository import ControlRepository


_IGNORE_PREFIX = ("_hoodie_", "_execution", "_source", "_uuid")
_GENERIC = {"id", "code", "type", "date", "name", "status", "value", "key", "year", "month", "created_at", "updated_at"}


class GraphRAGService:
    """GraphRAG 3.0: metadata-first hybrid semantic retrieval.

    The graph combines physical schema, governed market semantics, values, metrics,
    verified queries and relationship evidence. Retrieval uses deterministic vector
    hashing + lexical relevance + graph expansion. This keeps local mode fully
    offline. The graph *recommends* context; it never authorizes an untrusted join.
    """

    def __init__(self):
        self.s = get_settings()
        self.repo = SemanticRepository()
        self.graph_repo = GraphRepository()
        self.markets = MarketService()
        self.relationships = RelationshipService()
        self.values = ValueIndexService()
        self.verified = VerifiedQueryService()
        self.control = ControlRepository()
        self.embeddings = EmbeddingService()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [x for x in re.findall(r"[a-zA-ZÀ-ÿ0-9_]+", normalize(text or "")) if len(x) > 1]

    def _embedding(self, text: str) -> list[float]:
        return self.embeddings.embed(text)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        return max(0.0, min(1.0, sum(x * y for x, y in zip(a, b))))

    @staticmethod
    def _node_text(node: dict) -> str:
        a = node.get("attributes", {}) or {}
        bits = [
            node.get("label", ""), node.get("summary", ""), node.get("node_type", ""),
            str(a.get("description", "")), str(a.get("meaningful_name", "")),
            str(a.get("comment", "")), str(a.get("semantic_type", "")),
            str(a.get("database", "")), str(a.get("table", "")), str(a.get("column", "")),
            " ".join(str(x) for x in a.get("synonyms", []) or []),
            " ".join(str(x) for x in a.get("aliases", []) or []),
        ]
        return " ".join(x for x in bits if x)

    @staticmethod
    def _authority(status: str = "", source: str = "", node_type: str = "") -> float:
        status=(status or "").lower(); source=(source or "").lower()
        if status == "deprecated": return 0.05
        if status in {"certified","approved"}: return 1.0
        if status in {"verified","governed"}: return 0.95
        if status == "data_validated": return 0.82
        if source in {"s3","business","manual","market_semantic_package"}: return 0.85
        if node_type == "verified_query": return 0.95
        if status in {"reviewed","observed"}: return 0.72
        if status in {"inferred","ai_suggested","draft"}: return 0.40
        return 0.60

    @staticmethod
    def _freshness(status: str = "", updated_at: str | None = None) -> float:
        if (status or "").lower() == "deprecated": return 0.10
        if not updated_at: return 1.0 if (status or "").lower() in {"certified","verified","governed"} else 0.90
        try:
            dt=datetime.fromisoformat(updated_at.replace("Z","+00:00")); age=max(0,(datetime.now(timezone.utc)-dt).days)
            return round(max(0.25, 0.5 ** (age / max(1, get_settings().graph_freshness_half_life_days))),4)
        except Exception: return 0.85

    @classmethod
    def _edge(cls, source: str, target: str, edge_type: str, *, label: str = "", confidence: float = 1.0,
              status: str = "verified", trusted: bool = True, evidence=None, attributes=None, authority: float | None = None, freshness: float | None = None) -> dict:
        attrs=attributes or {}; src=str(attrs.get("source", ""))
        auth=cls._authority(status,src,edge_type) if authority is None else float(authority)
        fresh=cls._freshness(status,attrs.get("updated_at")) if freshness is None else float(freshness)
        return {
            "source_id": source, "target_id": target, "edge_type": edge_type, "label": label,
            "confidence": round(float(confidence), 4), "authority": round(max(0,min(1,auth)),4), "freshness": round(max(0,min(1,fresh)),4), "status": status,
            "trusted_for_queries": bool(trusted), "evidence": evidence or {}, "attributes": attrs,
        }

    def _workspace_dictionary(self, market: str) -> dict:
        dd=(self.repo.ontology().get("data_dictionary", {}) or {})
        out={}
        for db,tables in dd.items():
            selected={}
            for name,info in (tables or {}).items():
                info=info or {}; memberships=set(info.get("workspace_ids") or ([info.get("market")] if info.get("market") else []))
                if not memberships or market in memberships: selected[name]=info
            if selected: out[db]=selected
        return out

    def _fingerprint(self, market: str) -> str:
        rel = self.repo.relationships(); ctx = self.markets.context(market); dd=self._workspace_dictionary(market)
        # Hash source-of-truth semantic content rather than trusting timestamps. This
        # makes description edits, relationship review actions and YAML changes all
        # invalidate the rebuildable graph automatically.
        basis={
            "dictionary":dd,
            "relationships":[r for r in self.relationships.all() if not r.get("market") or r.get("market")==market],
            "concepts":ctx.get("concepts",{}),"metrics":ctx.get("metrics",{}),
            "bindings":ctx.get("bindings",{}),"values":ctx.get("value_mappings",{}),
            "joins":ctx.get("governed_joins",[]),"verified_queries":ctx.get("verified_queries",[]),
            "entities":ctx.get("entities",{}),"dimensions":ctx.get("dimensions",{}),
            "hierarchies":ctx.get("hierarchies",[]),"lineage":ctx.get("lineage",[]),
            "inferred_knowledge":[x for x in self.control.list("SUGGESTION",300) if x.get("market")==market and x.get("type")!="semantic_overlay"],
            "embedding":self.embeddings.metadata(),
        }
        raw=json.dumps(basis,sort_keys=True,ensure_ascii=False,default=str,separators=(",",":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def build(self, market: str, persist: bool = True) -> dict:
        ctx = self.markets.context(market)
        dd = self._workspace_dictionary(market)
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def add_node(node_id: str, label: str, node_type: str, *, summary: str = "", attributes=None):
            attrs = attributes or {}; status=str(attrs.get("status", "governed" if node_type in {"market","region","entity","concept","dimension","metric","hierarchy"} else "observed")); source=str(attrs.get("source","semantic_model" if node_type in {"market","region","entity","concept","dimension","metric","hierarchy","business_term","value"} else "catalog"))
            node = {"id": node_id, "label": label, "node_type": node_type, "summary": summary, "attributes": attrs, "status":status, "authority":self._authority(status,source,node_type), "freshness":self._freshness(status,attrs.get("updated_at"))}
            node["embedding"] = self._embedding(self._node_text(node))
            nodes[node_id] = node
            return node_id

        m = ctx.get("market", {}) or {}
        market_id = add_node(
            f"market:{market}", m.get("name", market), "market",
            summary=f"{m.get('name', market)} market; locale {m.get('locale','')}; currency {m.get('currency','')}",
            attributes={**m, "description": m.get("description", "")},
        )
        region = m.get("region")
        if region:
            rid = add_node(f"region:{region}", region.title(), "region", summary=f"Regional semantic layer: {region}")
            edges.append(self._edge(rid, market_id, "HAS_MARKET"))
        ds_cfg=ctx.get("data_sources",{}) or {}; supported=ds_cfg.get("supported",[]) or [ds_cfg.get("default","athena")]
        for ds in supported:
            sid=add_node(f"data_source:{ds}",str(ds).title(),"data_source",summary=f"Configured analytics source: {ds}",attributes={"source":ds,"status":"governed"})
            edges.append(self._edge(market_id,sid,"USES_DATA_SOURCE"))

        bindings = ctx.get("bindings", {}) or {}
        concept_bindings = bindings.get("concepts", {}) or {}
        dimension_bindings = bindings.get("dimensions", {}) or {}

        # Business concepts/entities. Formal entity YAML augments the concept layer;
        # bound concepts are also entities even when a dedicated entity spec is absent.
        entity_specs=ctx.get("entities",{}) or {}; concept_specs=ctx.get("concepts",{}) or {}
        for key in sorted(set(concept_specs)|set(entity_specs)):
            spec={**(concept_specs.get(key) or {}),**(entity_specs.get(key) or {})}
            ntype = "entity" if key in concept_bindings or key in entity_specs else "concept"
            nid = add_node(
                f"{ntype}:{key}", spec.get("label", key.replace("_", " ").title()), ntype,
                summary=spec.get("description", ""),
                attributes={"semantic_id": key, "description": spec.get("description", ""), "synonyms": spec.get("synonyms", []) or [], "status": spec.get("status", "governed"), "market_notes":spec.get("market_notes","")},
            )
            edges.append(self._edge(market_id, nid, "HAS_CONCEPT"))

        # Governed dimensions and metrics. Formal dimension definitions augment physical bindings.
        dimension_specs=ctx.get("dimensions",{}) or {}
        for key in sorted(set(dimension_bindings)|set(dimension_specs)):
            spec={**(dimension_specs.get(key) or {}),**(dimension_bindings.get(key) or {})}
            nid = add_node(
                f"dimension:{key}", spec.get("label", key.replace("_", " ").title()), "dimension",
                summary=spec.get("description", f"Governed dimension {key}"),
                attributes={"semantic_id": key, **spec, "status": spec.get("status", "governed")},
            )
            edges.append(self._edge(market_id, nid, "HAS_DIMENSION"))
        for key, spec in (ctx.get("metrics", {}) or {}).items():
            spec = spec or {}
            nid = add_node(
                f"metric:{key}", spec.get("label", key.replace("_", " ").title()), "metric",
                summary=spec.get("description", ""),
                attributes={"semantic_id": key, "description": spec.get("description", ""), "aliases": spec.get("aliases", []) or [], "status": spec.get("status", "governed")},
            )
            edges.append(self._edge(market_id, nid, "HAS_METRIC"))

        # Glossary terms become first-class business-term nodes.
        for term, spec in (ctx.get("glossary", {}) or {}).items():
            spec = spec or {}
            nid = add_node(
                f"term:{term}", spec.get("preferred", term), "business_term",
                summary=spec.get("definition", ""), attributes={"term": term, **spec},
            )
            edges.append(self._edge(market_id, nid, "HAS_BUSINESS_TERM"))

        # Physical catalog.
        for db, tables in dd.items():
            dbid = add_node(f"database:{db}", db, "database", attributes={"database": db, "status":"observed"})
            edges.append(self._edge(market_id, dbid, "CAN_ACCESS_DATABASE"))
            default_ds=(ctx.get("data_sources",{}) or {}).get("default","athena")
            if f"data_source:{default_ds}" in nodes: edges.append(self._edge(f"data_source:{default_ds}",dbid,"HOSTS_DATABASE",status="governed",trusted=True))
            for table, info in tables.items():
                info = info or {}
                tid = f"table:{db}.{table}"
                add_node(
                    tid, table, "table", summary=info.get("description") or info.get("table_description") or info.get("meaningful_name", ""),
                    attributes={"database": db, "table": table, "meaningful_name": info.get("meaningful_name", ""), "description": info.get("description") or info.get("table_description", ""), "column_count": len(info.get("columns", []) or []), "location": info.get("location", ""), "source_id": info.get("source_id", "")},
                )
                edges.append(self._edge(dbid, tid, "HAS_TABLE"))
                for c in info.get("columns", []) or []:
                    name = c.get("name", "")
                    if not name or name.lower().startswith(_IGNORE_PREFIX):
                        continue
                    sem = c.get("semantic_type") or infer_semantic_type(name, c.get("type", "string"), [])
                    cid = f"column:{db}.{table}.{name}"
                    add_node(
                        cid, name, "column", summary=c.get("description") or c.get("meaningful_name") or c.get("comment", ""),
                        attributes={"database": db, "table": table, "column": name, "type": c.get("type", "string"), "semantic_type": sem, "meaningful_name": c.get("meaningful_name", ""), "description": c.get("description", ""), "comment": c.get("comment", ""), "profile": c.get("profile", {}) or {}},
                    )
                    edges.append(self._edge(tid, cid, "HAS_COLUMN"))

        # Bind semantic entities/concepts to physical tables.
        for concept, spec in concept_bindings.items():
            source = f"entity:{concept}" if f"entity:{concept}" in nodes else f"concept:{concept}"
            target = f"table:{spec.get('database')}.{spec.get('table')}"
            if source in nodes and target in nodes:
                edges.append(self._edge(source, target, "REPRESENTED_BY", label=spec.get("key", ""), attributes={"key": spec.get("key")}))

        # Bind dimensions to columns/expressions.
        for dim, spec in dimension_bindings.items():
            source = f"dimension:{dim}"
            table_id = f"table:{spec.get('database')}.{spec.get('table')}"
            col = spec.get("column")
            target = f"column:{spec.get('database')}.{spec.get('table')}.{col}" if col else table_id
            if source in nodes and target in nodes:
                edges.append(self._edge(source, target, "REPRESENTED_BY", label=spec.get("expression") or col or "expression", attributes={"expression": spec.get("expression"), "representation": spec.get("representation")}))

        # Bind metric sources.
        for metric, spec in (ctx.get("metrics", {}) or {}).items():
            mid = f"metric:{metric}"
            for src in spec.get("preferred_sources", []) or []:
                table_id = f"table:{src.get('database')}.{src.get('table')}"
                col = src.get("column")
                target = f"column:{src.get('database')}.{src.get('table')}.{col}" if col else table_id
                if mid in nodes and target in nodes:
                    status = str(src.get("status", "draft")).lower()
                    trusted = status in {"verified", "approved", "governed"}
                    edges.append(self._edge(mid, target, "CALCULATED_FROM", label=src.get("expression", ""), status=status, trusted=trusted, confidence=1.0 if trusted else .65, attributes={"expression": src.get("expression"), "source_status": status}))

        # Market values are nodes, linked to their dimensions.
        for entry in self.values.entries(market):
            dim = entry["dimension"]
            vid = f"value:{dim}:{entry['canonical']}"
            add_node(vid, entry.get("label") or entry["canonical"], "value", summary=f"Canonical {dim} value", attributes=entry)
            did = f"dimension:{dim}"
            if did not in nodes:
                # Some value dimensions are concepts rather than explicit bindings.
                did = f"entity:{dim}" if f"entity:{dim}" in nodes else f"concept:{dim}"
            if did in nodes:
                edges.append(self._edge(did, vid, "HAS_VALUE"))

        # Verified questions are graph retrieval anchors.
        for row in self.verified.all(market):
            qid = f"verified_query:{row['id']}"
            add_node(qid, row.get("question", row["id"]), "verified_query", summary=row.get("notes", ""), attributes={"verified_query_id": row["id"], "question": row.get("question"), "tags": row.get("tags", []), "status": row.get("status", "verified"), "expected_semantics": row.get("expected_semantics", {})})
            edges.append(self._edge(market_id, qid, "HAS_VERIFIED_QUERY"))
            sem = row.get("expected_semantics", {}) or {}
            metric = sem.get("metric")
            if metric and f"metric:{metric}" in nodes:
                edges.append(self._edge(qid, f"metric:{metric}", "SUPPORTS"))
            for c in sem.get("concepts", []) or []:
                target = f"entity:{c}" if f"entity:{c}" in nodes else f"concept:{c}"
                if target in nodes:
                    edges.append(self._edge(qid, target, "SUPPORTS"))

        # Relationship edges: candidate relationships stay untrusted even if their score is high.
        for r in self.relationships.all():
            if r.get("market") and r.get("market")!=market: continue
            a = f"column:{r.get('from_db')}.{r.get('from_table')}.{r.get('from_column')}"
            b = f"column:{r.get('to_db')}.{r.get('to_table')}.{r.get('to_column')}"
            if a not in nodes or b not in nodes:
                continue
            evidence = self.relationship_evidence(r)
            etype = "JOINS_TO" if r.get("trusted_for_queries") else "CANDIDATE_JOIN"
            edges.append(self._edge(a, b, etype, label=r.get("label") or r.get("relationship_type", ""), confidence=evidence["overall_confidence"], status=r.get("status", "ai_suggested"), trusted=bool(r.get("trusted_for_queries")), evidence=evidence, attributes={"relationship_id": r.get("id"), "source": r.get("source"), "relationship_type": r.get("relationship_type")}))

        # Governed joins connect tables even when the physical relationship uses an expression.
        for j in ctx.get("governed_joins", []) or []:
            left = j.get("left", {}) or {}; right = j.get("right", {}) or {}
            a = f"table:{left.get('database')}.{left.get('table')}"; b = f"table:{right.get('database')}.{right.get('table')}"
            if a in nodes and b in nodes:
                edges.append(self._edge(a, b, "JOINS_TO", label=j.get("description", j.get("id", "governed join")), confidence=float(j.get("confidence", 1.0)), status=j.get("status", "verified"), trusted=True, evidence={"governed_condition": j.get("condition"), "source": "market_semantic_package"}, attributes={"join_id": j.get("id"), "condition": j.get("condition")}))

        # Optional semantic model extensions: entities/dimensions/hierarchies/lineage are loaded by MarketService.
        for h in ctx.get("hierarchies", []) or []:
            hid = add_node(f"hierarchy:{h.get('id')}", h.get("label", h.get("id", "hierarchy")), "hierarchy", summary=h.get("description", ""), attributes=h)
            edges.append(self._edge(market_id, hid, "HAS_HIERARCHY"))
            for level in h.get("levels", []) or []:
                target = f"dimension:{level}"
                if target in nodes:
                    edges.append(self._edge(hid, target, "HAS_LEVEL"))
        for lin in ctx.get("lineage", []) or []:
            source = lin.get("source"); target = lin.get("target")
            if source in nodes and target in nodes:
                edges.append(self._edge(source, target, "DERIVED_FROM", label=lin.get("description", ""), status=lin.get("status", "governed"), trusted=True))

        for sug in self.control.list("SUGGESTION",300):
            if sug.get("market")!=market or sug.get("type")=="semantic_overlay": continue
            st=sug.get("status","inferred"); sid=f"inferred:{sug.get('id')}"
            add_node(sid,sug.get("label",sug.get("id","suggestion")),"inferred_knowledge",summary=sug.get("reason",""),attributes={**sug,"source":"ontology_inference","status":st})
            edges.append(self._edge(market_id,sid,"HAS_INFERRED_KNOWLEDGE",status=st,trusted=st in {"approved","certified"},confidence=float(sug.get("confidence",.5)),authority=float(sug.get("authority",.35))))

        graph = {
            "version": "3.0",
            "market": market,
            "fingerprint": self._fingerprint(market),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding": self.embeddings.metadata(),
            "nodes": nodes,
            "edges": edges,
        }
        graph["stats"] = self._stats(graph)
        if persist:
            self.graph_repo.save(market, graph)
        return graph

    @staticmethod
    def _stats(graph: dict) -> dict:
        types = defaultdict(int); etypes = defaultdict(int); trusted = 0; candidate = 0
        for n in graph.get("nodes", {}).values():
            types[n.get("node_type", "unknown")] += 1
        for e in graph.get("edges", []):
            etypes[e.get("edge_type", "unknown")] += 1
            if e.get("edge_type") == "CANDIDATE_JOIN": candidate += 1
            if e.get("edge_type") == "JOINS_TO" and e.get("trusted_for_queries"): trusted += 1
        return {"total_nodes": len(graph.get("nodes", {})), "total_edges": len(graph.get("edges", [])), "node_types": dict(types), "edge_types": dict(etypes), "trusted_join_edges": trusted, "candidate_join_edges": candidate}

    def graph(self, market: str, fresh: bool = False) -> dict:
        self.markets.context(market)
        existing = None if fresh else self.graph_repo.load(market)
        if existing and existing.get("fingerprint") == self._fingerprint(market):
            return existing
        return self.build(market, persist=True)

    @staticmethod
    def _adjacency(graph: dict):
        adj = defaultdict(list)
        for i, e in enumerate(graph.get("edges", [])):
            adj[e["source_id"]].append((e["target_id"], i, e))
            adj[e["target_id"]].append((e["source_id"], i, e))
        return adj

    def search(self, question: str, market: str, top_k: int | None = None, depth: int = 1) -> dict:
        graph = self.graph(market)
        top_k = top_k or self.s.graph_top_k
        qvec = self._embedding(question); qtoks = token_set(question)
        scored = []
        type_prior = {"metric": .10, "entity": .08, "dimension": .08, "concept": .06, "value": .08, "verified_query": .08, "table": .04, "column": .02, "business_term": .04}
        for nid, node in graph.get("nodes", {}).items():
            text = self._node_text(node); ntoks = token_set(text)
            vec = self._cosine(qvec, node.get("embedding", []))
            overlap = len(qtoks & ntoks) / max(1, len(qtoks))
            phrase = .20 if normalize(node.get("label", "")) and normalize(node.get("label", "")) in normalize(question) else 0
            node_type=node.get("node_type")
            # Raw physical names are especially vulnerable to hash collisions. If a
            # table/column has no lexical hit, let it enter primarily through graph
            # propagation from a matched business node rather than vector noise.
            vector_factor=.22 if node_type in {"table","column","database"} and overlap==0 and phrase==0 else 1.0
            relevance = .58 * vec * vector_factor + .30 * overlap + phrase + type_prior.get(node_type, 0)
            authority=float(node.get("authority",.6)); freshness=float(node.get("freshness",.9))
            score = relevance * (.55 + .45 * authority) * (.70 + .30 * freshness)
            if authority >= self.s.graph_min_authority and score > .04:
                scored.append((score, nid, vec, overlap))
        scored.sort(reverse=True)
        seeds = scored[:top_k]
        adj = self._adjacency(graph)
        aggregate: dict[str, float] = {}
        provenance: dict[str, list[str]] = defaultdict(list)
        for score, nid, vec, overlap in seeds:
            aggregate[nid] = max(aggregate.get(nid, 0), min(1.0, score))
            provenance[nid].append("vector+lexical")
            if depth <= 0: continue
            q = deque([(nid, 0, score)])
            seen = {nid}
            while q:
                cur, d, base = q.popleft()
                if d >= depth: continue
                for nxt, _, edge in adj.get(cur, []):
                    if nxt in seen: continue
                    seen.add(nxt)
                    trust = 1.05 if edge.get("trusted_for_queries") else .82
                    authority=.55 + .45*float(edge.get("authority",.6)); freshness=.70+.30*float(edge.get("freshness",.9))
                    edge_type=edge.get("edge_type")
                    semantic_factor={'CALCULATED_FROM':1.12,'REPRESENTED_BY':1.08,'HAS_VALUE':1.05,'SUPPORTS':1.02,'DERIVED_FROM':1.05,'JOINS_TO':.95,'CANDIDATE_JOIN':.55,'HAS_COLUMN':.72,'HAS_TABLE':.55,'CAN_ACCESS_DATABASE':.30,'HAS_CONCEPT':.45,'HAS_DIMENSION':.45,'HAS_METRIC':.45,'HAS_BUSINESS_TERM':.38,'HAS_VERIFIED_QUERY':.45,'HAS_MARKET':.35}.get(edge_type,.65)
                    propagated = min(1.0, base * (0.62 ** (d + 1)) * trust * authority * freshness * semantic_factor * max(.45, float(edge.get("confidence", .7))))
                    if propagated > aggregate.get(nxt, 0):
                        aggregate[nxt] = propagated
                        provenance[nxt].append(f"graph:{edge.get('edge_type')}")
                    q.append((nxt, d + 1, propagated))
        ranked = sorted(aggregate.items(), key=lambda x: x[1], reverse=True)[: max(top_k * 3, 20)]
        results = []
        selected_ids = set()
        for nid, score in ranked:
            node = graph["nodes"].get(nid)
            if not node: continue
            selected_ids.add(nid)
            results.append({"id": nid, "label": node.get("label"), "node_type": node.get("node_type"), "summary": node.get("summary"), "attributes": {k:v for k,v in (node.get("attributes") or {}).items() if k != "profile"}, "score": round(min(1.0, score), 4), "knowledge_score":round(min(1.0,score),4), "authority":node.get("authority"), "freshness":node.get("freshness"), "status":node.get("status"), "provenance": provenance.get(nid, [])})
        sub_edges = [e for e in graph.get("edges", []) if e.get("source_id") in selected_ids and e.get("target_id") in selected_ids]
        tables = []
        for x in results:
            a = x.get("attributes", {}) or {}
            if x["node_type"] == "table":
                n = f"{a.get('database')}.{a.get('table')}"
            elif x["node_type"] == "column":
                n = f"{a.get('database')}.{a.get('table')}"
            else:
                continue
            if a.get("database") and a.get("table") and float(x.get("score",0))>=.20 and n not in tables:
                tables.append(n)
        return {"question": question, "market": market, "results": results, "subgraph": {"node_ids": list(selected_ids), "edges": sub_edges}, "tables": tables[: self.s.max_planner_tables], "graph_stats": graph.get("stats", {}), "embedding_provider": graph.get("embedding", {}).get("provider")}

    def explorer(self, market: str, node_id: str | None = None, depth: int = 2, limit: int = 200, node_types: list[str] | None = None, statuses: list[str] | None = None, trusted_only: bool = False, min_authority: float = 0.0, cluster: str | None = None) -> dict:
        """Scalable explorer payload for the Obsidian-style UI.

        The full graph remains server-side. The UI receives only a filtered neighborhood or
        priority slice, capped by GRAPH_EXPLORER_MAX_NODES. This keeps rendering bounded
        even when the semantic graph contains tens of thousands of physical nodes.
        """
        graph=self.graph(market); limit=min(max(int(limit),20),self.s.graph_explorer_max_nodes)
        wanted_types={x for x in (node_types or []) if x}; wanted_status={x for x in (statuses or []) if x}
        if node_id:
            payload=self.neighborhood(market,node_id,depth,limit)
            candidates=payload.get("nodes",[])
        else:
            priority={"market":0,"entity":1,"metric":1,"dimension":1,"concept":2,"business_term":2,"value":3,"table":3,"verified_query":4,"data_source":4,"region":4,"hierarchy":4,"column":8,"inferred_knowledge":7}
            candidates=sorted(graph.get("nodes",{}).values(),key=lambda n:(priority.get(n.get("node_type"),6),-float(n.get("authority",.5)),n.get("label",'')))
        raw_nodes=[]
        def node_cluster(n):
            a=n.get('attributes') or {}
            return str(a.get('database') or a.get('entity') or a.get('table') or n.get('node_type') or 'other')
        for n in candidates:
            if wanted_types and n.get("node_type") not in wanted_types: continue
            if wanted_status and str(n.get("status",'')) not in wanted_status: continue
            if float(n.get("authority",0) or 0)<float(min_authority or 0): continue
            if cluster and node_cluster(n)!=cluster: continue
            raw_nodes.append(n)
            if len(raw_nodes)>=limit: break
        selected={n.get("id") for n in raw_nodes}
        edges=[e for e in graph.get("edges",[]) if e.get("source_id") in selected and e.get("target_id") in selected and (not trusted_only or e.get("trusted_for_queries"))]
        if trusted_only:
            connected={e.get("source_id") for e in edges}|{e.get("target_id") for e in edges}; raw_nodes=[n for n in raw_nodes if n.get("id") in connected or n.get("node_type") in {"market","entity","metric","dimension","concept"}]
            selected={n.get("id") for n in raw_nodes}; edges=[e for e in edges if e.get("source_id") in selected and e.get("target_id") in selected]
        compact=[]; clusters=defaultdict(lambda:{"count":0,"types":defaultdict(int),"nodes":[]})
        for n in raw_nodes:
            a={k:v for k,v in (n.get("attributes") or {}).items() if k not in {"profile","sample_values","embedding"}}
            item={"id":n.get("id"),"label":n.get("label"),"node_type":n.get("node_type"),"summary":n.get("summary"),"status":n.get("status"),"authority":n.get("authority"),"freshness":n.get("freshness"),"attributes":a}; compact.append(item)
            cluster=str(a.get("database") or a.get("entity") or a.get("table") or n.get("node_type") or "other")
            clusters[cluster]["count"]+=1; clusters[cluster]["types"][n.get("node_type")]+=1
            if len(clusters[cluster]["nodes"])<12: clusters[cluster]["nodes"].append(n.get("id"))
        cluster_rows=[{"id":k,"count":v["count"],"types":dict(v["types"]),"sample_node_ids":v["nodes"]} for k,v in clusters.items()]
        cluster_rows.sort(key=lambda x:x["count"],reverse=True)
        return {"market":market,"workspace_id":market,"center":node_id,"nodes":compact,"edges":edges,"clusters":cluster_rows,"filters":{"node_types":sorted({n.get("node_type") for n in graph.get("nodes",{}).values() if n.get("node_type")}),"statuses":sorted({str(n.get("status")) for n in graph.get("nodes",{}).values() if n.get("status")}),"cluster":cluster or ""},"total_graph_nodes":len(graph.get("nodes",{})),"returned_nodes":len(compact),"truncated":len(graph.get("nodes",{}))>len(compact),"stats":graph.get("stats",{}),"fingerprint":graph.get("fingerprint"),"version":graph.get("version")}

    def neighborhood(self, market: str, node_id: str, depth: int = 1, limit: int = 80) -> dict:
        graph = self.graph(market)
        if node_id not in graph.get("nodes", {}):
            raise KeyError(node_id)
        adj = self._adjacency(graph); q = deque([(node_id, 0)]); seen = {node_id}; edge_ids = set()
        while q and len(seen) < limit:
            cur, d = q.popleft()
            if d >= depth: continue
            for nxt, idx, _ in adj.get(cur, []):
                edge_ids.add(idx)
                if nxt not in seen:
                    seen.add(nxt); q.append((nxt, d + 1))
                    if len(seen) >= limit: break
        return {"center": node_id, "nodes": [graph["nodes"][x] for x in seen], "edges": [e for i,e in enumerate(graph.get("edges", [])) if i in edge_ids], "depth": depth}

    @staticmethod
    def _normalize_column(name: str) -> str:
        x = normalize(name).replace(" ", "_")
        x = re.sub(r"^(fk_|pk_|ref_|cod_|code_|num_|id_)", "", x)
        x = re.sub(r"(_id|_key|_code|_num|_no|_ref|_fk|_pk)$", "", x)
        return x

    @staticmethod
    def _physical_type_family(t: str) -> str:
        x = (t or "").lower()
        if any(k in x for k in ["int", "decimal", "double", "float", "numeric"]): return "numeric"
        if any(k in x for k in ["date", "timestamp", "time"]): return "date"
        if any(k in x for k in ["bool"]): return "boolean"
        return "text"

    def relationship_evidence(self, relationship: dict) -> dict:
        a = relationship.get("from_column", ""); b = relationship.get("to_column", "")
        na = self._normalize_column(a); nb = self._normalize_column(b)
        name_sim = SequenceMatcher(None, na, nb).ratio() if na and nb else 0.0
        sa = relationship.get("from_semantic_type") or "unknown"; sb = relationship.get("to_semantic_type") or "unknown"
        semantic = 1.0 if sa == sb and sa != "unknown" else (.78 if are_types_fk_compatible(sa, sb) else .15)
        pa = relationship.get("from_type"); pb = relationship.get("to_type")
        physical = None
        if pa and pb:
            physical = 1.0 if self._physical_type_family(pa) == self._physical_type_family(pb) else .2
        raw_conf=relationship.get("confidence_score", relationship.get("confidence", 0))
        try: base=float(raw_conf or 0)
        except Exception: base={"high":.9,"medium":.7,"low":.5}.get(str(raw_conf).lower(),0)
        trust_bonus = 1.0 if relationship.get("trusted_for_queries") else .0
        dv=relationship.get("data_validation") or relationship.get('evidence') or {}
        coverage=dv.get("referential_coverage",dv.get('coverage')); uniqueness=dv.get("target_uniqueness")
        components=[(name_sim,.28),(semantic,.22),(base,.18),(trust_bonus,.08)]
        denom=.76
        if physical is not None: components.append((physical,.08)); denom+=.08
        if coverage is not None: components.append((float(coverage),.10)); denom+=.10
        if uniqueness is not None: components.append((float(uniqueness),.06)); denom+=.06
        score=sum(v*w for v,w in components)/max(denom,.01)
        return {
            "overall_confidence": round(max(0.0, min(1.0, score)), 4),
            "name_similarity": round(name_sim, 4),
            "semantic_type_compatibility": round(semantic, 4),
            "physical_type_compatibility": None if physical is None else round(physical, 4),
            "source_confidence": round(base, 4),
            "referential_coverage": None if coverage is None else round(float(coverage),4),
            "target_uniqueness": None if uniqueness is None else round(float(uniqueness),4),
            "trust_status": relationship.get("status", "ai_suggested"),
            "sample_values_used": False,
            "profile_evidence_available": coverage is not None or uniqueness is not None,
            "data_validation_passed": dv.get("passed") if dv else None,
        }

    def discover_relationship_candidates(self, market: str, max_candidates: int = 300) -> dict:
        """Enhanced metadata-only discovery used by onboarding.

        It combines fuzzy normalized names, semantic-type compatibility, physical type
        families and existing graph context. Candidates always remain ai_suggested.
        """
        from app.repositories.control_repository import ControlRepository
        row=ControlRepository().get('WORKSPACE',market) or {}
        if row.get('scope_id'):
            from app.services.phase2_service import Phase2Service
            service=Phase2Service();candidates=service.relationship_candidates(market,max_candidates)
            for r in candidates:
                if not service.repo.get('P2_RELATIONSHIP',market+'::'+r['relationship_id']):
                    service._put('relationship',market,r['relationship_id'],r)
            self.build(market,persist=True)
            return {'generated':len(candidates),'candidates':candidates,'engine':'canonical_fk_discovery','sample_values_used':False}
        self.markets.context(market)
        dd = self._workspace_dictionary(market)
        cols = []
        for db, tables in dd.items():
            for table, info in tables.items():
                for c in info.get("columns", []) or []:
                    name = c.get("name", "")
                    if not name or name.lower().startswith(_IGNORE_PREFIX): continue
                    norm = self._normalize_column(name)
                    if norm in _GENERIC or len(norm) < 3: continue
                    sem = c.get("semantic_type") or infer_semantic_type(name, c.get("type", "string"), [])
                    cols.append({"db": db, "table": table, "column": name, "norm": norm, "type": c.get("type", "string"), "semantic_type": sem})
        rel_doc = self.repo.relationships(); existing = rel_doc.get("relationships", [])
        keys = set()
        for r in existing:
            if r.get("market") and r.get("market")!=market: continue
            a=(r.get("from_db"),r.get("from_table"),r.get("from_column")); b=(r.get("to_db"),r.get("to_table"),r.get("to_column")); keys.add(tuple(sorted((a,b))))
        # Avoid quadratic explosion by blocking on first two normalized chars or exact semantic identifiers.
        buckets = defaultdict(list)
        for c in cols:
            buckets[c["norm"][:2]].append(c)
        candidates=[]
        for bucket in buckets.values():
            if len(bucket) > 90: continue
            for a,b in combinations(bucket,2):
                if a["db"]==b["db"] and a["table"]==b["table"]: continue
                key=tuple(sorted(((a["db"],a["table"],a["column"]),(b["db"],b["table"],b["column"]))))
                if key in keys: continue
                name_sim=SequenceMatcher(None,a["norm"],b["norm"]).ratio()
                sem_ok=are_types_fk_compatible(a["semantic_type"],b["semantic_type"])
                if name_sim < .72 or not sem_ok: continue
                semantic_score=1.0 if a["semantic_type"]==b["semantic_type"] and a["semantic_type"]!="unknown" else .78
                physical=1.0 if self._physical_type_family(a["type"])==self._physical_type_family(b["type"]) else .25
                id_boost=1.0 if a["semantic_type"] in {"identifier","reference","code"} or b["semantic_type"] in {"identifier","reference","code"} else .55
                score=.42*name_sim+.23*semantic_score+.18*physical+.17*id_boost
                if score < self.s.graph_candidate_min_confidence: continue
                r={"from_db":a["db"],"from_table":a["table"],"from_column":a["column"],"from_type":a["type"],"from_semantic_type":a["semantic_type"],"to_db":b["db"],"to_table":b["table"],"to_column":b["column"],"to_type":b["type"],"to_semantic_type":b["semantic_type"],"relationship_type":"candidate","confidence":"high" if score>=.85 else "medium","confidence_score":round(score,4),"reason":"GraphRAG 3.0 metadata candidate: fuzzy naming + semantic/physical type compatibility","evidence":{"name_similarity":round(name_sim,4),"semantic_type_compatibility":round(semantic_score,4),"physical_type_compatibility":round(physical,4),"identifier_reference_signal":round(id_boost,4),"sample_values_used":False},"edge_type":"graphrag_candidate","status":"ai_suggested","source":"graphrag_v3","market":market,"discovered_at":datetime.now(timezone.utc).isoformat()}
                candidates.append(r); keys.add(key)
                if len(candidates)>=max_candidates: break
            if len(candidates)>=max_candidates: break
        candidates.sort(key=lambda x:x["confidence_score"],reverse=True)
        existing.extend(candidates); rel_doc["relationships"]=existing; rel_doc["last_updated"]=datetime.now(timezone.utc).isoformat(); self.repo.save_relationships(rel_doc)
        self.build(market,persist=True)
        return {"generated":len(candidates),"sample_values_used":False,"engine":"GraphRAG 3.0","candidates":candidates[:50],"message":"GraphRAG candidates remain blocked until data-validated or human-verified.","relationship_stats":RelationshipService().stats()}
