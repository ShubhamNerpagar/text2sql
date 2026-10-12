# Data Intelligence Platform 8.0 — Phase 1 · Windows EC2 Native

> **Complete Phase 1 deliverable** on top of the 7.0.1 semantic runtime. No Docker. Existing Ask, GraphRAG, Semantic Studio, Reports, lineage, RBAC and related endpoints remain in the package.
>
> Phase 1 focuses on **enterprise discovery, explicit scope selection, an offline demo and Bedrock model permissions**. Semantic engineering, evidence, compiler, versioned releases and distributed workers are scheduled for Phases 2–5; they are not claimed as Phase 1 features.

## Quick start — Windows Server EC2

1. Install **Python 3.12 x64** (add Python to PATH).
2. Unzip the Phase 1 release to `C:\DataIntelligencePlatform` (avoid extracting *inside* another version's folder).
3. Open PowerShell in that folder and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\windows\Install-App.ps1
   notepad .env
   .\windows\Start-App.ps1 -BindHost 127.0.0.1 -Port 8000
   ```

4. Open `http://127.0.0.1:8000` on the Windows EC2 desktop.
5. Go to **Data → Enterprise Catalog**. The **Offline Retail Demo (illustrative)** is available immediately, even without AWS permissions. Select `Bundled Sample → contoso_demo → public → Orders`, click **Save & generate workspace**. Then use **Ask** to ask *How many orders are there?* (expected **10000**).
6. Open another PowerShell window and run `./windows/Test-App.ps1` and `./windows/Run-Tests.ps1`.

**Do not open port 8000 publicly while `.env` uses `AUTH_MODE=dev_headers`.** This mode is for private test access only. Use localhost/RDP or an allowlisted security group and move to ALB/OIDC before external multi-user access. IAM instance profile is preferred; never put AWS secret keys in `.env`.

## New Phase 1 features

### A. Hierarchical, paged source catalog

| Source | Navigation | What actually loads |
|---|---|---|
| Local retail demo | Package → local dataset → schema → tables | SQLite metadata only |
| Athena / Glue | Configured Glue catalog → database → tables | Paged `GetDatabases`/`GetTables`; columns retrieved only for chosen tables |
| PostgreSQL / Aurora | Configured database → schema → tables | SQLAlchemy inspector scoped to configured connection |
| Snowflake | Database → schema → tables | Metadata-only `SHOW` discovery |
| Databricks | Catalog → schema → tables | Metadata-only `SHOW` discovery |

- UI provides **search**, server-side pagination (40 tables per page, max API limit 100), **multi-page selection**, **Select visible**, and **previously saved scopes**.
- A scope is an allowlist of exact `{source, catalog, database, schema, table}` identifiers; no global all-table onboarding is needed.
- Scopes have their own IDs, workspace IDs and increasing versions, preserved in the existing control repository. `Admin → Onboarding → Resync` reuses this exact allowlist for Phase 1-created workspaces.
- Up to **500 explicit tables per scope** in Phase 1; create multiple workspaces for larger sets. The metadata catalog can browse much larger estates but **1000-db load testing and concurrent multi-worker discovery remain Phase 5 acceptance work**.
- This layer still has the earlier 7.x single-workspace semantic namespace limitations for some cross-catalog/schema SQL plans. Selection is functional; full connector SQL-semantic parity comes in the next phases.

### B. Contoso retail demo

- `sample-data/contoso/contoso_demo.sqlite3` is **bundled, offline and generated in this build** (10,000 orders, 8 tables). It is **not** an unchanged official SQLBI release.
- Run `./windows/Install-Contoso.ps1` (outbound GitHub required) to fetch and install **official SQLBI Contoso V2 10K CSV** into `sample-data/contoso/contoso_official.sqlite3` as a second selectable database. The installer discovers the asset through the official GitHub release API, checks downloaded size and advertised SHA-256 where available, extracts CSV and records provenance.
- The original archive/CSVs remain in the application sample-data directory. For upstream provenance and license, see `sample-data/contoso/README.md`.
- **The official binary could not be fetched in the isolated build environment**, so it is not pre-bundled. The local illustration ensures Phase 1 works entirely offline.

### C. Bedrock model discovery and routing

Open **Admin → AI Models**. AWS credentials are loaded through the EC2 instance role.

1. Discover foundation models and inference profiles in `BEDROCK_REGION`.
2. Listed items display **UNVERIFIED** until you click **Test access**; only a successful real Bedrock `Converse` call turns them **VERIFIED**.
3. Choose a general strategy (Balanced / Quality / Cost / Latency) and optionally pin **verified models** to ontology, semantic planning, Ask, summaries, classification and SME tasks.
4. Save routing preferences in the control repository. Existing Bedrock text invocation uses the selected inference profile/model via `Converse` (no hardcoded Anthropic-only body).
5. Recommendations are **heuristic**, not measured model-quality benchmark scores. Contoso-based model scoring is deferred to Phase 3/4.

IAM policy template at `infra/windows/ec2-instance-role-policy.json` includes Bedrock listing and invoke permissions; replace S3/Region/account placeholders and reduce resource scope before applying. Some inference profiles may require permissions on their destination Region/model resources and permission to use cross-Region inference.

**Important distinction:** Bedrock catalog listing ≠ permission to invoke. AWS IAM and Bedrock settings can also change after a successful probe.

## AWS EC2 configuration

Use `.env.windows.test.example` for an isolated test and `.env.windows.production.example` only with production identity, storage and network controls.

```dotenv
APP_ENV=development
APP_MODE=aws
AWS_REGION=ap-south-1
BEDROCK_REGION=ap-south-1
ATHENA_CATALOG=AwsDataCatalog
ATHENA_OUTPUT=s3://YOUR-ATHENA-RESULTS-BUCKET/dip/results/
ATHENA_WORKGROUP=primary
SEMANTIC_BUCKET=
LEARNING_TABLE=
PERSIST_LOCAL_STATE=true
ALLOW_SAMPLE_VALUES=false
AUTH_MODE=dev_headers
ALLOW_DEV_IDENTITY_HEADERS=true
```

The three S3 purposes are separate:

1. **Source data** is located by Glue table `StorageDescriptor.Location` (not an `.env` setting).
2. **Athena result output** is `ATHENA_OUTPUT` and needs write/list/read permissions.
3. **Semantic artifacts** use optional `SEMANTIC_BUCKET`; Phase 1 testing can store control/semantic state on the EC2 Windows disk.

The Bedrock panel needs `bedrock:ListFoundationModels`, `bedrock:ListInferenceProfiles`, and `bedrock:InvokeModel`. It only sends a tiny test prompt when you explicitly click **Test access**, which can incur a small cost.

## API surface (admin-only unless noted)

```text
GET  /api/phase1/catalog/{source}/catalogs
GET  /api/phase1/catalog/{source}/databases?catalog=...
GET  /api/phase1/catalog/{source}/schemas?catalog=...&database=...
GET  /api/phase1/catalog/{source}/tables?catalog=...&database=...&schema=...&limit=40&cursor=...
GET  /api/phase1/table-detail/{source}?database=...&schema=...&table=...
GET  /api/phase1/scopes
POST /api/phase1/scopes
GET  /api/phase1/scopes/{scope_id}
POST /api/phase1/scopes/{scope_id}/generate
GET  /api/phase1/bedrock/models
POST /api/phase1/bedrock/probe
POST /api/phase1/bedrock/configuration
```

Scope POST JSON:

```json
{
  "scope_id":"retail-demo-scope",
  "workspace_id":"retail-demo",
  "display_name":"Retail Intelligence",
  "source_id":"contoso",
  "tables":[
    {"catalog":"Bundled Sample","database":"contoso_demo","schema":"public","table":"Orders"},
    {"catalog":"Bundled Sample","database":"contoso_demo","schema":"public","table":"Customer"}
  ]
}
```

## Tests and validation boundaries

- Windows-independent Python suite including regression tests, scoped onboarding, local Ask result, paged fake Glue catalog, permission/role checks and mocked Bedrock discovery/probe.
- Syntax checks (`compileall`, `node --check`), ZIP CRC, local Uvicorn smoke tests performed during packaging.
- **Not executed on actual Windows / real AWS during packaging.** The repository retains `.github/workflows/windows-native.yml` for a Windows runner and the PowerShell acceptance scripts.
- Real Athena, Glue, PostgreSQL, Snowflake, Databricks and Bedrock permissions must be validated on your EC2 instance with actual networks/roles.

See `WINDOWS_EC2_README.md`, `PHASE1_VALIDATION.json`, and the preserved 7.0.1 historical docs under `docs/`.

### S3 map — keep these distinct

| Purpose | Location / setting |
|---|---|
| **Actual business data** | Glue table `StorageDescriptor.Location`, for example `s3://company-curated-data/orders/`. The app does not ingest this data during metadata discovery. |
| **Athena query results** | `ATHENA_OUTPUT=s3://company-query-results/dip/results/` with S3 read/write permissions. |
| **Platform semantic artifacts** | Optional `SEMANTIC_BUCKET` (`s3://company-semantic-control/`); otherwise `state/` on the Windows EC2 disk in test mode. |
