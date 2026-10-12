> Phase 5 note: shared multi-host jobs require optional DynamoDB `PHASE5_QUEUE_BACKEND=dynamodb` and live acceptance; see `docs/PHASE5_ACCEPTANCE.md`. SQLite is single-host only.

# Windows EC2 Deployment — Phase 3

This release is native Python/Uvicorn, no Docker and no container services.

## Install

1. Use Windows Server 2019/2022/2025 with Python 3.12 x64 installed and added to PATH.
2. Copy ZIP to `C:\DataIntelligencePlatform`, extract the application files, open PowerShell in the extracted directory.
3. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows\Install-App.ps1
notepad .env
.\windows\Start-App.ps1 -BindHost 127.0.0.1 -Port 8000
```

App: `http://127.0.0.1:8000`. If you must access remotely, open the Windows port and AWS Security Group **only to your trusted public IP**, and do not use unauthenticated development headers on a public host.

## First run without AWS

Keep `APP_ENV=development` and change `APP_MODE=local` in `.env` to test the **bundled offline retail illustration**. Open **Data → Catalog Explorer**; choose `contoso_demo`, `Orders`; click **Save & generate workspace**. Then Ask `How many orders are there?` (10,000 expected). This is a safe self-contained smoke test.

To add official SQLBI Contoso V2 10K CSV into application data storage (requires internet):

```powershell
.\windows\Install-Contoso.ps1
```

Then restart server and select database `contoso_official`. Source provenance in `sample-data/contoso/official-manifest.json`.

## Phase 2 UI flow

After Phase 1 workspace generation, select that workspace and use **Data → Profiling, Contracts, ER Evidence, Quality, Lineage**. A Standard profile must complete before a contract can be certified. All live warehouse profiling may incur compute/query costs; start with the metadata tier and a small explicitly selected scope.

Run `windows/Test-Phase2.ps1` for a self-contained bundled-dataset acceptance check. This writes a reproducible non-production `phase2-smoke` workspace into your current `STATE_DIR`.


## Phase 3 Ontology 2.0

After generating a Phase 1 scope, open **Semantics → Ontology 2.0**. Infer untrusted candidates from selected tables, edit drafts, and record SME reviews. To certify a bound ontology object, first run a complete Phase 2 measured profile and certify the corresponding contract; use a **different verified reviewer identity** from the author. Cross-asset semantic dependencies also require measured and approved Phase 2 relationship evidence.

Use **Semantics → Trust Engine** to view blocking diagnostics and immutable ledger snapshots. **SME Review** records issue decisions without waiving trust requirements. **Ontology Graph** offers conceptual, logical, evidence and dependency projections. Publishing creates a *review-only* immutable semantic snapshot, not a production NL2SQL deployment.

Run the new Windows-native Phase 3 smoke workflow:

```powershell
.\windows\Test-Phase3.ps1
```

The script uses a disposable sample workspace. It cannot prove any live AWS or production warehouse integration; those must be validated separately.

## Real Athena + Glue

Set `APP_MODE=aws`, `AWS_REGION`, `ATHENA_OUTPUT` in `.env`. Attach instance profile with Glue list/get APIs, Athena workgroup/query, S3 result path access and optional Bedrock list/invoke permissions. `SEMANTIC_BUCKET` can remain empty for local-state test deployments; `LEARNING_TABLE` can remain empty. Never paste AWS secret keys into configuration.

Navigate Data → Catalog Explorer → Amazon Athena → AwsDataCatalog → selected Glue database → selected tables → Save & generate workspace. Columns are fetched **only for the selected tables**. The schema-onboarding endpoint from 7.x is retained for backward compatibility, but the new enterprise selector should be used for large catalogs.

## Bedrock model configuration

Set `BEDROCK_REGION` and open Admin → AI Models. Use **Test access** for a model/profile. Once status is **verified**, choose and save it as an override for Ask, Semantic Planning, etc. Auto stays on the configured default (`BEDROCK_MODEL`) until models have been explicitly verified. Permission probes invoke Bedrock and incur a small charge.

## Run validation

In another PowerShell window:

```powershell
.\windows\Test-App.ps1
.\windows\Test-Phase2.ps1
.\windows\Test-Phase3.ps1
.\windows\Test-Aws.ps1
.\windows\Run-Tests.ps1
```

## Production cautions

- The default role dropdown/`dev_headers` is **not identity authentication**; restrict testing to RDP/localhost/VPN/IP-allowlisting. Set up ALB/OIDC or another proven identity boundary for production.
- Platform state on a single Windows disk is intended for a test instance; back up `state/` and move to durable shared stores for production/multiple nodes.
- Phase 2 brings scoped profiling, contracts, relationship evidence, quality rules and declared lineage; Phase 3 adds a scoped ontology/review-only trust ledger. Distributed profiling workers, cross-engine production equivalence and massive-load tests remain Phase 5 acceptance work.
- The actual official Contoso archive and actual AWS environment were **not** tested here. See the current root README and `docs/PHASE2_ACCEPTANCE.md` for precise limits.

## S3 configuration reference

- **Actual business data** stays in the S3 location registered on the Glue table; do not put it into `ATHENA_OUTPUT`.
- **Athena query results** go to `ATHENA_OUTPUT=s3://YOUR-ATHENA-RESULTS-BUCKET/dip/results/`.
- **Platform semantic artifacts** can be persisted in the optional semantic bucket selected with `SEMANTIC_BUCKET`.

Do not permit `0.0.0.0/0` inbound to the development server in your AWS **Security Group**.
