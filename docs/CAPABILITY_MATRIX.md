# Data Intelligence Platform 7.0 — Capability Matrix

The internal level-4 label means a product-ready architecture baseline: implemented, integrated, governed, observable/regression-testable and deployable. It is not a claim of vendor-scale SLA history or production adoption.

Key 7.0 posture:

| Capability | 7.0 evidence |
|---|---|
| Runtime semantic layer | Generated from connected metadata; no bundled customer/country package |
| Automatic ontology inference | Table/entity and column/dimension drafts plus reviewable metric suggestions |
| Graph-based semantics | GraphRAG 3.0 + authority/freshness + force-directed visual explorer |
| Relationship discovery | Metadata candidates remain blocked until review/validation |
| Metric layer | Contract validation; business metrics must be explicitly governed/certified |
| Deterministic SQL | Governed compiler, dialect translation, read-only gate and security hooks |
| SQL agent reasoning | Bounded Bedrock fallback when enabled |
| Benchmarking | Evaluation engine available; workspace-specific suites are added after real onboarding |
| Multi-turn | Persistent governed conversation context |
| Semantic branching/releases | Patch, validate, compare, merge and publish workflows |
| Lineage | Physical/semantic/report lineage and impact APIs |
| Security | RBAC, column filtering, row-policy compiler hooks, trusted identity boundary |
| Data-source portability | Athena/Glue, PostgreSQL/Aurora, Snowflake, Databricks SQL |
| MCP | Permission-aware tools without arbitrary write access |
| BI reports | Semantic-question widgets, refresh-time security, lineage and drill-down |
| Production operations | `/api/health`, `/api/ready`, telemetry, S3/DynamoDB persistence patterns |

Workspace-specific production acceptance still requires real source onboarding, steward review, security testing, evaluation suites and load/cost testing.
