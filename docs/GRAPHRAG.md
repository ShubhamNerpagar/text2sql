# GraphRAG 3.0

GraphRAG 3.0 is the semantic discovery/retrieval layer, not the permission or join-authority layer.

## Knowledge model

Nodes can represent data sources, databases, tables, columns, markets, domains, entities, concepts, dimensions, metrics, values, business terms, verified queries and inferred knowledge.

Edges capture physical containment, semantic representation, metric derivation, value membership, query support, lineage, governed joins and candidate relationships.

## Trust model

Retrieval separates:

- **relevance** — match to the current question;
- **confidence** — evidence strength that the knowledge is true;
- **authority** — source trust for production decisions;
- **freshness** — age/currentness of the evidence.

AI-inferred metadata can be highly relevant and confident while still having insufficient authority to control a production join.

## Retrieval

1. Load/rebuild the selected market graph.
2. Generate deterministic dense-hash + lexical query signals.
3. Rank semantic nodes with authority/freshness weighting.
4. Expand relevant typed graph neighborhoods.
5. Apply identity/column policy filtering.
6. Return a compact semantic subgraph to the resolver.

The vectorizer is intentionally dependency-free for the current graph size. The retrieval boundary is provider-neutral so a future pgvector/OpenSearch/embedding service can replace it without changing the semantic planner.

## Relationship lifecycle

```text
AI_SUGGESTED
   ↓
aggregate-only data validation
   ↓
DATA_VALIDATED
   ↓
human verification/certification
   ↓
runtime-trusted semantic relationship
```

Raw sample rows are not required.
