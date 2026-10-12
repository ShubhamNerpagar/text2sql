# Pending work — Data Intelligence Platform 8.4.0

Reviewed on 12 October 2026 (Asia/Calcutta). This is a read-only source review of the supplied 8.4.0 release and its recorded validation, not a check of an independently deployed instance. No new live AWS, warehouse or Windows execution was performed during this review.

The recorded baseline is 189 Python tests and 10 Chromium application checks passing. The model responses in those checks were mocked; queries executed against isolated SQLite/synthetic fixtures. The seven accuracy areas have implemented controls, but live accuracy, deployment acceptance and several UI/enterprise capabilities remain pending.

## Release blockers and deployment prerequisites

| Priority | Pending work | What closes it |
|---|---|---|
| P0 | Repair Windows acceptance scripts and CI smoke setup | Update the six stale version checks to the release version; replace old offline/entity-count assumptions and golden-case schemas; use explicitly isolated fixtures for contract tests; keep live acceptance separate; obtain a passing native Windows run. |
| P0 | Verify real Bedrock access | Configure an instance role or AWS CLI/SSO profile, IAM and region; perform real access tests and select planning/verification models; exercise model errors and clarification without fallback. |
| P0 | Verify the target warehouse | Configure a real read-only connector; run catalog discovery, profiling, composite/role joins and compiled aggregate SQL against the intended SQL dialect. |
| P0 | Certify the deployment's business definitions | Confirm formulas, units, grain, additive behavior, time roles, required filters and relationship roles; independently certify and publish/promote the relevant release. Test fixture definitions do not certify production meanings. |
| P0 | Establish live business-result accuracy | Author independent reference SQL and a representative question corpus; test paraphrases, filters, dates, joins, ambiguity, refusals and follow-ups against a stable real-data snapshot; set and meet explicit acceptance criteria. |
| P0 when upgrading existing state | Migrate old definitions, reports and benchmarks | Back up state; refresh FK/schema evidence; convert prose/inferred measures to executable definitions; recertify; activate a new release; re-save legacy widgets; replace old object-matching cases with reference SQL. |
| P0 when using restricted enterprise roles | Implement policy-aware query compilation | Compile row-level policies and column restrictions into every applicable query/report path and validate permitted/denied results. Those users are currently denied rather than receiving policy-filtered analytics. |

### Confirmed Windows release issue

The release VERSION is 8.4.0, but these six scripts still require 8.3.0:

- `windows/Test-Phase2.ps1:10`
- `windows/Test-Phase3.ps1:18`
- `windows/Test-Phase4.ps1:9`
- `windows/Test-Phase5.ps1:7`
- `windows/Test-AdvancedQueries.ps1:5`
- `windows/Test-UnifiedAsk.ps1:5`

The Windows CI workflow invokes Phase 2–5 scripts at `.github/workflows/windows-native.yml:43`, so these version checks are active acceptance failures, not historical documentation.

Further mismatches require more than a version substitution:

- `Test-Phase4.ps1:29` submits obsolete `object_id` pinning, which the current Ask/BI endpoints reject.
- `Test-Phase4.ps1:30` expects offline answering, intentionally removed from new natural-language queries.
- `Test-Phase4.ps1:33` uses old `allow`/`reject` golden expectations without independent reference SQL.
- The CI boot step copies `.env.windows.test.example`, whose `ENABLE_SAMPLE_EXECUTION=false`, while the native acceptance scripts expect synthetic Contoso profiling. A separate explicitly enabled fixture configuration is needed for these tests; production should retain sample execution disabled.

The prior Python test result does not cover execution of these PowerShell scripts. Native acceptance remains unrun.

## Implementation and UI gaps

| Priority | Pending work | Current evidence |
|---|---|---|
| P1 | Wire Add to report into unified Ask | `app/static/assets/app.js:101` renders the unified answer without this action. The button exists only in the older result renderer at line 136. The supported report API plans and stores widgets in `app/services/report_service.py:54`. |
| P1 | Improve business-definition authoring and inspection | The simple builder at `app/static/assets/app.js:768` supports a column/two-column formula, one equality condition, and a UTC time role. More complex definitions, weights and mappings need advanced JSON authoring. The certified-object inspector at line 526 does not display the full executable definition. |
| P1 | Add useful benchmark failure diagnostics | `app/services/business_benchmark_service.py:80` stores successful execution outcomes as pass/fail without the actual/reference value differences. The UI at `app/static/assets/app.js:825` displays outcomes and reasons, but does not explain the differing calculations. |
| P1 when freshness commitments are required | Enforce source-data freshness SLAs | `freshness_sla_hours` is validated and saved in `app/services/phase2_service.py:204` and exposed in the contract form. Source review found no scheduler consuming it to compare a source watermark or alert/block on stale data. Evidence refresh is a separate implemented feature. |
| P1 | Validate operational deployment | Install and verify background workers, report refresh, real identity integration, queue/control storage, restarts and state recovery on the target deployment. Evidence refresh code exists at `app/workers/phase5_worker.py:38`; its availability still depends on running the worker. |

## Supported-query boundaries and optional extensions

These are explicit current scope limits, not evidence that the implemented supported compiler is failing:

- One connector/database per query; directional many-to-one joins, up to four relationships.
- Metrics must belong to the base dataset; cross-fact/different-grain calculations require additional compilation strategies.
- Metrics with different required populations cannot be combined in one current aggregate query (`advanced_query_service.py:155`). Conditional aggregates or separate subqueries would be needed.
- Gregorian relative periods; fiscal/business calendars need implementation.
- Timestamp grouping and relative periods requiring non-UTC conversion are refused by the current compiler.
- No window-function analytics, unrestricted raw-row extraction or arbitrary SQL.
- The current model provider is Amazon Bedrock. Direct OpenAI, Azure OpenAI or Gemini connectors would be additional provider work if wanted.
- Large catalogs use bounded lexical retrieval (`llm_planner_service.py:35`) and explicit scope-size refusal. Benchmark retrieval recall and latency on realistic catalog sizes before claiming enterprise-scale coverage.

Grain evidence proves key uniqueness and null behavior, not the business additivity of every numeric column. A steward must still detect order-level amounts repeated on line records. The 24-hour evidence cache is not an atomic warehouse snapshot; set an appropriate refresh/constraint strategy for critical calculations.

## Delivery status

- The updated application is packaged in `data-intelligence-platform-8.4.0-llm-governed-windows-native.zip` and extracted under `/workspace/artifacts/data-intelligence-platform-8.4.0`.
- The original audit found that the selected GitHub checkout contained only its initial README. This source import places the full updated application, walkthrough and review documents in `ShubhamNerpagar/text2sql`; the live deployment and validation gaps above remain pending.
- Cloud installation/start instructions and network configuration were saved as a reviewable draft. The recorded configuration was not published; this review did not query a later publication state.
- The UI walkthrough is a self-contained screenshot tour with demonstration data and mocked models. It is not a hosted production deployment.

## Recommended execution order

1. Repair native acceptance scripts and the CI fixture setup.
2. Verify a real model and one real warehouse.
3. Certify a small useful set of business definitions and relationships.
4. Run a representative live result benchmark and fix observed meaning/retrieval failures.
5. Complete the Ask-to-report handoff and definition/benchmark diagnostics.
6. Implement policy compilation before enabling restricted enterprise roles; add freshness enforcement when required.
7. Complete native deployment/worker acceptance and source-control/configuration handoff.

New or changed business meanings deliberately require human review. Routine unchanged passing evidence refresh is already automated; removing all review is not pending work for this governed workflow.
