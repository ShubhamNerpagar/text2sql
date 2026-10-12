# Phase 5 Acceptance and Operations Runbook

## 1. Running locally (Windows PowerShell)

From the extracted package root:

```powershell
.\windows\Install-App.ps1
.\windows\Start-App.ps1 -BindHost 127.0.0.1
```

Open a second PowerShell window and **keep the worker running**:

```powershell
.\windows\Start-Phase5Worker.ps1
```

Open `http://127.0.0.1:8000`, create/generate a Phase 1 scope if needed, then choose **Operate → Job Center**. Create a `search_snapshot` task. The separate worker process should execute it and emit a succeeded event. Job and event state is kept under `$env:STATE_DIR` (or `state\`).

```powershell
.\windows\Test-Phase5.ps1 -BaseUrl 'http://127.0.0.1:8000' -Workspace YOUR_GENERATED_WORKSPACE_ID
.\windows\Start-Phase5Worker.ps1 -Once
```

**Important:** `Test-Phase5.ps1` queues one safe snapshot task if `-Workspace` is provided. In `APP_ENV=production`, OpenAPI may be disabled; use the equivalent authorized checks with your production identity rather than the development script.

## 2. Multi-host DynamoDB queue (not live-certified)

The default SQLite file is safe for multiple local worker processes on one host, **not a shared network folder or independent EC2 hosts**. For multi-host orchestration:

1. Provision an AWS DynamoDB table with string `pk` partition key and string `sk` sort key (the existing control-plane table can be reused when appropriate). Use IAM roles with `Query`, `GetItem`, and `PutItem` rights scoped to that table. Enable encryption at rest, backups and CloudWatch alarms.
2. Configure the SAME `APP_MODE=aws`, `LEARNING_TABLE=<table>`, `AWS_REGION=<region>` and `PHASE5_QUEUE_BACKEND=dynamodb` on every API and worker host. Ensure all use the same identity provider, workspace scopes and code version. AWS resource creation is operator-owned, not bundled.
3. Start at least two worker processes on separate Windows EC2 hosts using `Start-Phase5Worker.ps1` and verify only one gets a given job. Kill the claimed worker; wait for lease expiration and verify a second worker reclaims it without duplicate logical effects.
4. Observe CloudWatch costs and DynamoDB throttling. Queue polls currently list the `P5_JOB` partition, with an upper bound of 10,000 items per poll. For high-scale workloads migrate to a sharded GSI/SQS queue before acceptance.
5. Run recovery testing while disabling one host, closing/reopening a Phase 2 contract, checking authorization boundaries and verifying false/incomplete semantic evidence never publishes federation objects.

**Caveat:** queue semantics are **at-least-once**, not exactly-once. If a worker crashes after completing a downstream side effect but before reporting completion, the job may run again. Make profiles/evaluations idempotent or deduplicated per logical job ID before production use.

## 3. Security and trust gates

- Only authenticated semantic reviewers/admins with workspace permission may access Phase 5 APIs; publication and grants require publish privilege.
- Cross-workspace publication requires a certified Phase 4 release. Each search re-evaluates source release digests, current Phase 3 certification, and Phase 2 physical evidence. Revoked or stale results disappear immediately.
- Published manifests do not include physical columns, row values, provenance payloads, SQL, or credentials.
- Never expose development identity headers directly over the internet. Configure production ALB/OIDC, private networking, HTTPS, least privilege and audit storage retention.
- Queue workers execute only known task names and validated payloads. All connector scans are explicitly scoped. Avoid providing untrusted credentials in job arguments.

## 4. Connector benchmarks

- Bundled Contoso: user-selected tables, `SELECT COUNT(*)` through DataSourceService and read-only direct SQLite query; compare counts and enumerate columns. This is **internal consistency** on illustrative data, not cross-engine equivalence.
- External engines: only configured source for that workspace, explicit selected schemas, metadata conformance; output `status=metadata_only`, `cross_connector_equivalence_verified=false`.
- Before claiming enterprise equivalence, prepare canonical types/normalizations, identical datasets, reference SQL, engine-specific dialect implementations, tolerances, row/aggregate parity, and documented result hashes; then execute a separate live acceptance suite.

## 5. Load and durability checks

```powershell
.\.venv\Scripts\python.exe scripts\phase5_load_test.py --url http://127.0.0.1:8000 --requests 120 --concurrency 8 --output logs\phase5-load.json
.\.venv\Scripts\python.exe -m app.workers.phase5_worker --once
.\.venv\Scripts\python.exe -m scripts.phase5_backup
```

The load script caps requests at 1,000 and concurrency at 32, targets only `/api/health` or `/api/ready`, and requires `--allow-remote` for remote hosts. This **does not** benchmark production query throughput or worker capacity. Backup covers SQLite jobs transactionally and takes a best-effort control-plane JSON copy; DynamoDB needs native PITR/scheduled backups.

## 6. Pre-production checklist

- [ ] Windows EC2 AMI and Python installation verified, firewall/HTTPS secured, application service started and restarted.
- [ ] Phase 1–4 regression suite and Phase 5 suite run on Windows Server under correct identity and networking.
- [ ] Multi-host lease contention, crash/reclaim, cancellation and retry run against actual DynamoDB and IAM roles.
- [ ] AWS and configured warehouses tested with bounded schema scopes, policy and credentials confirmed.
- [ ] End-to-end baseline parity checks for supported source/destination mapping reviewed.
- [ ] Load/soak test for real workloads, limits, monitoring, backups and disaster recovery run.
- [ ] Security review and independent production sign-off completed.

Until these gates are signed off, call this **Phase 5 development / release candidate**, not a production-certified distributed system.
