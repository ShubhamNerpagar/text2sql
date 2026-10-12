# Phase 2 Change Log

## 8.0.0-phase2 — Understand Data

- Added `Phase2Service` control-plane records: scoped profiles, contracts, evidence relationships, quality rules and runs, transformations and audit events.
- Added three profiling tiers, protected aggregate computation, canonical asset hashes and schema drift fingerprints.
- Added dataset contracts with stewardship roles, owner, SLA, optimistic version checks and explicit review/certification.
- Added data relationship candidate inference, live aggregate referential coverage and uniqueness, human approval/rejection and evidence invalidation on drift.
- Added quality rule enable/disable lifecycle and quality rule engine with immutable run IDs, factual pass/fail/error observations, waivers, rulings and remediation tracker.
- Added lineage dependency graph with measurement source, optional lookup nodes, documented transformations and impact traversal.
- Added 20+ Phase 2 endpoints and five data-workspace UI tabs, including an ER evidence diagram and audit endpoint.
- Preserved Phase 1 onboarding, Bedrock routing and previous APIs; upgraded reported app version.
- Added Phase 2 Windows smoke test and 12 API/service regression tests.

See `PHASE2_VALIDATION.json` for verification limitations and `docs/PHASE2_ACCEPTANCE.md` for live deployment checks.
