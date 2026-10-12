# Phase 2 acceptance report and operator runbook

## What is verified locally

- Existing Phase 1 regression tests continue passing, including exact-scope resync and offline NL2SQL.
- Phase 2 Python route, persistence and permission tests exercise explicit Contoso table selection, metadata-only profiling (zero row scans), 10,000-order aggregate profiles, schema role contracts, version conflicts, FK relationship validation, approval not-before-evidence, quality failure/waiver/remediation, transform lineage/impact, SQL identifier rejection, and audit access.
- Browser-driven interaction loads Home, Data Profiling, Contracts, Quality Center and Lineage Studio against a locally running FastAPI backend. JavaScript console reports no exceptions. Browser HTTP was bridged to the local FastAPI service for testing because direct local navigation was blocked in the test environment.

## Acceptance procedure on Windows EC2

1. Create Windows Server EC2 with private-only inbound access and a tested Python 3.12 runtime. Back up `state/`, `.env` and all external data before upgrades.
2. Install the app using `windows/Install-App.ps1`; start with `Start-App.ps1` bound to localhost. Confirm `/api/health` says `8.0.0-phase2`.
3. Run `windows/Test-App.ps1`, then `windows/Test-Phase2.ps1` (creates the `phase2-smoke` demo workspace and measured/quality evidence). Run `windows/Run-Tests.ps1`.
4. Open UI: Data → Catalog Explorer, check table paging/scope selection; then run a Standard profile, edit a contract and transition it through review/certification, measure and review an ER candidate, create and run a quality check, and inspect evidence lineage.
5. For production connectors, configure only a **read-only warehouse credential**. Independently verify Athena scans/Lake Formation grants, PostgreSQL schema permissions, Snowflake/Databricks identifier dialect and compute costs, network and TLS, and restricted column policies. Use a non-production dataset and verify query plans before large-table profiling.
6. Independently validate ALB OIDC identity and production auth settings, audit retention, shared control-plane persistence, concurrency/backups, Windows service restart behavior, scan timeouts, and actual load testing. Do not declare production acceptance until they pass.

## Known deliberate phase boundaries

- Phase 2 records validated relationship evidence, but does **not** silently amend the legacy SQL join-planner trust graph; Phase 3 will implement controlled semantics promotion.
- Transform lineage is registered/declarative. No job-log integration proves execution.
- Freshness SLA is contractual metadata, not a background SLA monitor.
- A single source/selection scope is required for each Phase 2 workspace. Dataset collisions that older Phase 1 rejects remain unsupported.
- No unsandboxed free-form profiling SQL is accepted; identifiers are allowlisted and aggregate statements are constructed server-side.
- Local test results don't demonstrate live connector compatibility, accuracy at petabyte scale, production uptime or Windows-specific operation.
