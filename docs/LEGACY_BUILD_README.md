# Data Intelligence Platform 8.0 — Phase 5: Scale & Operate

**Release candidate / locally validated. Not yet production-certified.**

Phase 5 adds a durable Job Center, explicit federated semantic domains, permission-filtered enterprise search, offline Contoso conformance checks, optional DynamoDB multi-host worker coordination, a bounded load smoke tool and a Windows deployment runbook. All previous Phase 1–4 features are retained.

**Quick start:** `windows\Install-App.ps1`, `windows\Start-App.ps1`, then in another PowerShell terminal run `windows\Start-Phase5Worker.ps1`. Navigate to **Operate** after creating a scope. See [Phase 5 Acceptance](docs/PHASE5_ACCEPTANCE.md) and [Phase 5 Changelog](CHANGELOG_PHASE5.md).

---

# Data Intelligence Platform 8.0 — Phase 4 Windows-native build

**Phase 4:** governed semantic consumption, pinned releases, golden/fuzz/mutation evaluation, read-only offline Ask/BI and agent tool contracts. This is a locally validated development release, not production certified. See [Phase 4 acceptance](docs/PHASE4_ACCEPTANCE.md) for prerequisites and limits.

Windows: `./windows/Install-App.ps1`, then `./windows/Start-App.ps1`, and in another PowerShell shell `./windows/Test-Phase4.ps1`.

---

# Data Intelligence Platform 8.0 — Phase 2 · Understand Data

**Release:** `8.0.0-phase3` | **Deployment target:** Windows Server / Windows EC2, native Python (no Docker required)

Phase 2 builds **directly on the Phase 1 ZIP**. It retains Enterprise Catalog, explicit table scopes, Contoso-style offline demo, Bedrock routing, Ask/NL2SQL, existing Semantic Studio, Reports, graph explorer, and existing backend APIs. New Data workspaces provide measured evidence and human-governed contracts.


## Phase 3 — Ontology 2.0 / Semantic Evidence Trust

This Phase 3 development release builds on all Phase 1 and Phase 2 features and introduces six scoped semantic kinds: **entity, event, measure, code_set, business_concept, rule**.

**UI:** Semantics → **Ontology 2.0**, **Trust Engine**, **SME Review**, and **Ontology Graph**. Four different graph projections are **Conceptual**, **Logical**, **Evidence**, and **Dependencies**. Use the same Phase 1 generated workspace and Phase 2 evidence. Create candidates using *Infer candidates from selected tables*, or author a typed semantic object and select its columns. Explicit asset/column bindings are validated against that workspace's exact selected tables.

**Trust model:** candidates start as untrusted drafts. Schema snapshots, measured Phase 2 profile evidence, and certified current-schema contracts feed the *Semantic Evidence Ledger*. Reviews require a reason, optimistic versions, and an independent reviewer to certify. The semantic compiler reports missing physical evidence, schema drift, invalid dependencies, definitions, and code-set cardinality questions. SME rulings remain auditable and **do not override failed compiler checks**. Release publication creates a versioned, review-only snapshot of currently certified objects, never overwriting an existing version. Release records include a SHA-256 content digest. No individual source rows are stored in the ledger.

**Security:** All Phase 3 endpoints require semantic review permission in the workspace; publishing additionally requires publish permission. Development X-User identity controls exist solely for local tests; production must use a verified ALB/OIDC identity.

**Important limitations:** Phase 3 diagnostics are structural/provenance checks, **not an executable SQL compiler**. The reviewed ontology is **not automatically installed into Ask/NL2SQL, production joins, GraphRAG, or MCP**; integration and advanced semantic-plan evaluation belong to Phase 4. A semantic release does not authorize production data access or query execution. Connectors still need validation on actual Windows EC2/AWS resources. Chromium browser UI testing was performed with browser navigation replaced by an in-process bridge to the real FastAPI test app because sandbox policy blocks direct HTTP navigation. Full served-browser testing on Windows remains a deployment acceptance item.

Run the native Windows Phase 3 test after starting the app:

```powershell
.\windows\Test-Phase3.ps1
```

This smoke test creates a disposable Contoso sample workspace, executes aggregate profiling, contract certification, ontology proposals, independent review, four graph projections, and release publication.

### Phase 3 API

Routes under `/api/phase3` accept the exact `workspace` query parameter: `/overview`, `/proposals` (POST), `/objects` (GET/POST), `/objects/{id}` (GET/PUT), `/objects/{id}/review` (POST), `/compile`, `/evidence`, `/questions`, `/questions/{id}/review` (POST), `/graph?mode=conceptual|logical|evidence|dependency`, `/releases` (GET/POST), and `/audit`. Data input schemas are documented in the non-production OpenAPI documentation at `/api/docs`.


## Launch locally or on Windows EC2

1. Install **Python 3.12 x64** and extract this release to an application folder. For upgrades, first **back up** your existing `.env`, `state/` and any downloaded `sample-data/contoso/contoso_official.sqlite3`. Preserve them when replacing application code. Do not publish a development authentication configuration to the internet.
2. PowerShell (Windows):

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\windows\Install-App.ps1
   # Review .env; keep APP_ENV=development / AUTH_MODE=dev_headers on PRIVATE test systems only.
   .\windows\Start-App.ps1 -BindHost 127.0.0.1 -Port 8000
   ```

3. Browse `http://127.0.0.1:8000`. Under **Data → Catalog Explorer**, select the offline demo connector, `contoso_demo → public`, and tick `Orders`, `Customer`, `OrderRows`, `Product` and `Store`. Save & generate a workspace (Phase 1 existing behavior).
4. Select that workspace at the top of the UI, then explore **Data → Profiling, Contracts, ER Evidence, Quality, and Lineage**. Phase 2 requires a workspace generated from a **saved exact Phase 1 table scope**; legacy unscoped workspaces are intentionally not scanned.
5. On Windows, run smoke tests in a second PowerShell:

   ```powershell
   .\windows\Test-App.ps1
   .\windows\Test-Phase2.ps1
   .\windows\Run-Tests.ps1
   ```

The bundled `contoso_demo.sqlite3` is an **illustrative generated 10,000-order dataset**, not the official SQLBI Contoso release. `windows/Install-Contoso.ps1` can optionally install the official CSV release from the external source. No AWS account is required for the bundled demo.

## What's added in Phase 2

| Workspace | Working functionality | Trust boundary |
|---|---|---|
| **Profiling** | Metadata-only, standard full aggregate (row count, null/unique measures), deep numeric summary (min/max/mean); schema fingerprint/drift and per-column diagnostics | No raw records or distinct value lists persisted. Cloud scans may incur costs. |
| **Contracts** | Suggested column semantic roles, required/sensitive flags, owner, description, freshness SLA, optimistic versions and steward editing | Explicit `draft → reviewed → certified` decision; certification checks current schema and complete measured profile. |
| **ER Evidence** | Exact-scope relationship candidate discovery, actual referential coverage and target uniqueness, visual entity diagram, rejection or human approval | Naming is **not** evidence. Measured relationships are **not** query-trusted without approval. Phase 2 approvals do not automatically mutate legacy semantic SQL join definitions. |
| **Quality Center** | Rules for row minimum, non-null, completeness, uniqueness, FK coverage; durable runs, pass/fail/error evidence, steward rulings, waivers, remediation owner/status | Failed/error checks cannot be marked accepted. Explicit waiver requires rationale. |
| **Lineage** | Source, datasets, profile evidence, contracts, explicitly declared transforms, lookup evidence, relationships, dependency impact | Inferred edges labeled distinctly; transforms are steward-declared, **not** execution-verified. |
| **Audit** | Reviewer, action, object, timestamp and non-row data in control-plane storage | Admin/reviewer access only. |

### Measured evidence and limitations

* `metadata` is catalog-only; `standard` and `deep` run read-only aggregate SQL **on demand**. Measured row count uses the selected physical table. Failed columns mark the profile **partial**, never silently complete. A profile may take time or cost money on real warehouses. Profiling is bound to the Phase 1 selected table allowlist, with at most 200 columns per run.
* Physical identifiers in SQL are validated; SQL is generated by the server. Profiling does not store business-row samples. Numerical minima/maxima are aggregate values, so use normal role and data sensitivity governance before allowing access.
* Relationship evidence uses distinct-source matching, target-key uniqueness and a conservative coverage threshold (90% coverage and 98% uniqueness). Threshold failures return `needs_review` rather than trusted. Approval also rejects evidence invalidated by schema drift.
* Contract certification is per table and **does not** imply all quality rules pass automatically. Data-quality review remains a separate approval workflow. Freshness SLA is *recorded* but not yet executed on a scheduler; production freshness enforcement is further work.
* Contoso SQL aggregates are exercised end-to-end locally. Athena/Glue, PostgreSQL, Snowflake and Databricks use connector-specific qualified SQL paths, but their live credentials, permissions, scan costs and production dialect behavior **cannot be verified from this environment**. The Windows EC2 runtime was not exercised on an actual Windows host.
* Local JSON control-plane persistence is suitable for single-process development. Configure the supported DynamoDB control store and enterprise identity for a multi-instance deployment. This is **not** a claim of production-scale validation.
* The lineage canvas is an evidence navigator, not a live query/job execution monitor. Cross-connector join measurement and Phase 3 ontology promotion remain out of Phase 2's scope.

## AWS storage separation

Do not mix these three S3 purposes:

* **Actual business data:** existing governed data lakes or warehouse storage locations. Source data stays in its original source. The profiler executes SQL aggregates and does not persist individual records.
* **Athena query results:** a dedicated encrypted Athena query-results prefix configured using `ATHENA_OUTPUT=s3://YOUR-ATHENA-RESULTS-BUCKET/dip/results/`. Configure IAM access and retention independently of the business-data bucket.
* **Platform semantic artifacts:** ontology, runtime-generated workspace definitions, evidence and related graph artifacts using `SEMANTIC_BUCKET` / the control repository. Back these up and restrict edit access.

## API overview

All endpoints use `/api/phase2/*` and require `?workspace=<generated-workspace-id>`. Views check query permissions; mutations check semantic review permissions; reviews use the authenticated user's identity.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/overview` | Exact-scope assets, counters |
| GET | `/assets/{asset_id}/metadata` | Current schema and fingerprint |
| POST / GET | `/profiles` | Run/list measured profiling |
| POST / GET | `/contracts/{asset_id}` / `/contracts` | Edit/list data contracts |
| POST | `/contracts/{asset_id}/review` | Review, certify, reject, return to draft |
| POST / GET | `/relationships/{id}/validate` / `/relationships` | Measure/list candidates |
| POST | `/relationships/{id}/review` | Approve/reject evidence |
| POST / GET | `/quality/rules` | Create/list/disable quality expectations |
| POST / GET | `/quality/run` / `/quality/runs` | Execute/list quality runs |
| POST | `/quality/runs/{id}/review` | Accept / needs-remediation / waiver |
| POST | `/quality/runs/{id}/remediate` | Assign/track remediation |
| GET | `/lineage` and `/lineage/impact` | Evidence graph and impact paths |
| POST / GET | `/transformations` | Declare/list actual input/output dependencies |
| GET | `/audit` | Evidence workflow audit history |

For complete Phase 1 and pre-existing application documentation, see `docs/PHASE1_REFERENCE.md`, `docs/ARCHITECTURE.md` and `WINDOWS_EC2_README.md`. For phase-specific testing instructions and caveats see `docs/PHASE2_ACCEPTANCE.md`.

## Development and test commands

```bash
python -m pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q
python -m compileall -q app scripts
node --check app/static/assets/app.js
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Current local acceptance baseline:** 98 passing Python tests (86 inherited plus 12 Phase 2 tests); Python compilation, JavaScript syntax, HTTP API integration and a real UI-interaction smoke pass on the bundled demo. Details in `PHASE2_VALIDATION.json`. CI includes Python tests on `windows-latest`; the actual cloud connector and EC2 deployment acceptance remain environment-dependent.

### Roadmap after this release

- **Phase 3:** ontology model/editor, semantic proposals, evidence ledger, compiler diagnostics and reviewer workflow.
- **Phase 4:** semantic test suites, ontology branches/releases, grounded Ask/BI/MCP/agent flows and impact testing.
- **Phase 5:** durable distributed workers, enterprise-scale federated search, connector equivalence and live production load/security/Windows EC2 acceptance.
