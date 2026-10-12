# 8.0 Phase 1 release notes

- Preserves 7.0.1 semantic query guardrails, Semantic Studio, GraphRAG, reports, governance and existing routes.
- New lazy source catalog with connector-specific catalogs, databases, schemas, tables and targeted table-detail requests.
- New persisted, versioned workspace scopes with explicit selected-table allowlist, a safe scoped bootstrap and scope-preserving resync.
- Added offline, generated retail dataset (10,000 orders; not official SQLBI) with SQL execution and selected-table onboarding.
- Included installer for official SQLBI V2 10K CSV dataset into the application directory (GitHub download requires internet).
- New admin UI for enterprise table selection, search, paged browsing, selection persistence, saved scopes and workspace creation.
- New Bedrock model and inference profile discovery, explicit invocation probes, recommended task choices, verified-only manual overrides and saved model routing.
- Bedrock runtime now uses Converse for supported text models/inference profiles rather than a generic provider-specific InvokeModel body.
- Added Phase 1 tests, Windows workflow and deployment documentation.
