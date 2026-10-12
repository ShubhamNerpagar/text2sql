# Data Intelligence Platform 8.0 — Phase 5 build notes

**Track:** Scale & Operate · **Package:** `8.0.0-phase5` · **Build:** Windows-native source distribution.

## New capabilities

- **Durable Job Center:** allowlisted profile, golden-suite, connector-benchmark and search-snapshot jobs; queue views, per-job events, retries, cancellations, manual recovery, idempotency keys and bounded priorities. No arbitrary shell/SQL execution.
- **Two operational queue backends:** SQLite WAL with cross-process atomic leases on one host (default), or opt-in shared DynamoDB control table with conditional versioned lease claims for multiple hosts. At-least-once processing; execute writes must remain idempotent. DynamoDB mode not tested with live AWS.
- **Federated domains:** independently certified release required; separate domain draft/publish/revoke and grant/revoke to named existing workspaces; fail-closed on stale evidence. Published manifests contain ONLY safe business object names, type labels and descriptions.
- **Enterprise search:** locally scoped datasets and fresh certified semantic objects, plus domains explicitly granted to the current workspace. No raw rows, data values or physical bindings from external domains. Permission checks occur on each query.
- **Connector benchmarking:** read-only Contoso table counts through two adapters and scoped column enumeration; external configured connectors metadata-only with an explicit selected-schema allowlist (no undocumented parity claims).
- **Bounded load smoke tool** for health/ready endpoints, plus Windows worker scripts, deployment runbook, online SQLite job backup and startup-task template.
- **Operate UI:** Job Center, Federation, Enterprise Search, Connectors, Readiness.

## Notes and limitations

- This is a **locally validated release candidate**, not verified on a real Windows EC2 instance or a live AWS control plane.
- A shared DynamoDB table with string `pk` and `sk` keys is required for multi-host queue coordination. Claim discovery currently queries a dedicated `P5_JOB` partition; a GSI/sharded queue or dedicated broker is needed for high-throughput estates. No DynamoDB TTL/reaper and no guaranteed exactly-once execution.
- In-process job cancellation is cooperative at completion; it does not forcibly abort DB scans. Workers verify lease ownership before committing queue status; downstream tasks need their own idempotency strategy.
- Live Athena, Snowflake, Databricks, PostgreSQL connector parity and full multi-host failover have NOT been validated. External connector benchmarks are metadata-only until a cross-engine canonical schema mapping is configured.
- Existing Phase 1–4 interfaces, security gates and offline Contoso dataset are retained. Phase 4 external warehouse SQL still remains preview-only.
