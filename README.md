# Data Intelligence Platform 8.4.0

A Windows-native Python/FastAPI application for discovering warehouse metadata, defining governed business concepts and metrics, asking analytical questions with Amazon Bedrock, and publishing reports.

**New questions require a verified LLM. Offline answering has been removed.** Browsing metadata and reviewing definitions do not require an LLM. Synthetic Contoso execution is disabled by default and retained for explicit automated test fixtures.

## Start and connect

```powershell
.\windows\Install-App.ps1
.\windows\Start-App.ps1
```

Use an EC2 IAM instance role or an AWS CLI/SSO profile available to the process running the application. Set `AWS_REGION`, `BEDROCK_REGION` and your warehouse connector in `.env`. Configure Athena's result location when using Athena. Never store credentials in this source package.

Open **Administration → AI Models**, discover available models or inference profiles, click **Test access**, then select verified models for **Semantic planning** and **Semantic verification** and save. Both tasks can use the same model; verification is a separate invocation. A configured model ID alone does not enable Ask.

[The connection guide](docs/LLM_CONNECTION.md) explains IAM, region, profiles and troubleshooting. [The accuracy and migration guide](docs/BUSINESS_ACCURACY.md) explains definitions, relationships, benchmarks and manual review.

## What changed

| Area | Behavior in this release |
|---|---|
| Complete intent | Exact question spans must map to plan fields. A separate LLM review checks meaning and retained follow-up context before execution. |
| Executable definitions | Approved metric and concept IDs carry structured formulas, predicates, units, time roles and grain. The compiler applies them. |
| Grain | Measured unique, non-null grain and unique-target joins are required. Parent measures cannot be repeated across child joins; aggregation overrides are refused. |
| Shared stores | Object Studio and Semantic Studio author the same objects. GraphRAG, Ask and reports use those IDs and the same relationship records. Promoted releases authorize execution. |
| Relationships | Declared foreign keys, composite keys and billing/shipping roles are supported. Exact duplicate counts and native key equality replace rounded uniqueness assumptions. |
| Benchmarks | AI answers are compared with independent reference SQL results. Cases can cover paraphrases, ambiguity, filters, dates and joins. Missing LLM access is reported as blocked. |
| Onboarding | Guided preparation batches profiling, contracts and draft proposals. Review and certification remain human decisions. The worker refreshes expired evidence and preserves unchanged passing approvals. |

Reports store an LLM-reviewed plan and its release. Refresh recompiles that saved plan against current evidence and permissions. Old widgets must be re-saved against certified definitions. Client-supplied structured plans are preview-only through the HTTP API.

## Before the first question

1. Connect and explicitly scope the tables in **Data → Catalog Explorer**.
2. Open **Administration → Onboarding** and prepare profiles, contract drafts and business-definition proposals.
3. Confirm metric formula, unit, grain, required predicates, time meaning and synonyms in **Ontology → Object Studio**. Define executable predicates for concepts such as “completed order.”
4. Review contracts and measured relationships. A different steward certifies authored ontology objects.
5. Publish and activate a certified release, configure verified AI models, then open **Ask Data**.
6. Add independently approved reference SQL in **Ontology → Question Testing** and run business-result benchmarks against your warehouse.

Existing inferred dictionaries and prose-only measures do not authorize queries. A metadata sync cannot certify business meaning. See the migration guide before upgrading an existing state directory.

## Development and validation

Python 3.12 is recommended; Python 3.11+ is supported.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-test.txt
.venv/bin/python -m pytest -q
APP_MODE=local .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For Windows, use `.venv\Scripts\python.exe`. Start background jobs with `windows\Start-Worker.ps1`; it also refreshes expired semantic evidence. [VALIDATION_8.4.0.md](VALIDATION_8.4.0.md) records the checks performed on this version. Earlier QA files and screenshots describe historical versions and are not evidence for 8.4.0.

The implementation supports bounded aggregate queries on a single source/database, up to four directional joins, eight metrics and dimensions, and 100 result rows. Cross-source joins, unrestricted SQL, window functions, unsupported fiscal calendars and raw-row extraction are refused. Relative periods use approved time roles; timestamp grouping outside UTC requires an explicit timezone conversion definition and is refused by the current compiler.

LLM review reduces interpretation errors; it cannot prove a business definition is correct. Reference benchmarks and steward review remain necessary. Roles with active row policies or restricted semantic columns are denied until an appropriate policy compiler is available. Use read-only warehouse credentials and the existing production profile/ALB/OIDC deployment controls. This source release has not been accepted on live Bedrock, live enterprise warehouses or Windows EC2 in this environment.

## AWS storage boundaries

- **Actual business data** stays in its existing governed lake or warehouse. The platform records aggregate evidence rather than source-row samples.
- **Athena query results** use a separate encrypted prefix such as `ATHENA_OUTPUT=s3://YOUR-RESULTS-BUCKET/dip/results/` with its own IAM and retention settings.
- **Platform semantic artifacts** use `SEMANTIC_BUCKET` and the control repository for ontology, workspaces, graphs and evidence. Restrict editing and back up this state separately.

## UI walkthrough and pending work

- [Open the UI walkthrough guide](docs/UI_WALKTHROUGH_8.4.0.md). Download its standalone HTML file and open it in a browser to follow nine actual application screens. The example uses demonstration data and mocked model responses.
- [Review the pending-work audit](docs/PENDING_WORK_8.4.0.md), including Windows acceptance script fixes, live Bedrock/warehouse validation, policy-aware compilation and the Ask-to-report UI handoff.
- [Read recorded validation](VALIDATION_8.4.0.md). Passing mocked integration tests does not establish live model accuracy.
