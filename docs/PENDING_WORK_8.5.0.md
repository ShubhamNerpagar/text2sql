# Pending-work audit — 8.5.0

An audit is a record of remaining implementation and acceptance work. It does not mean every item is a missing data download. This update implements the user's optional-sample and multiple-selected-connector requirements; the 8.4.0 audit is retained as historical context.

## Implemented in 8.5.0

- Contoso is available as an optional source and can be left unselected. New questions on local sample data still require verified LLM access.
- The catalog picker retains table selections from multiple connectors in one workspace.
- Canonical asset identities include the source, catalog, database, schema and table. Dataset inspection and scoped catalog reads use those identities/selections.
- Approved cross-connector relationships have measured complete bounded evidence. One aggregate question can combine selected connectors through transient DuckDB snapshots.
- Native questions remain native; incomplete/oversized snapshots and invalid relationships/grain are blocked. Source rows are not sent to the LLM.
- Independent cross-source reference benchmarks use explicit source-bound snapshot table aliases.

The bundled Contoso illustration already exists. On 2026-10-12, the official SQLBI CSV 10K export was also downloaded, checksum-verified and installed locally. Typed archive importing, named optional dataset discovery and a public-release fallback were added; malformed rows no longer disappear silently. Installation does not certify business definitions. See [the dataset review](CONTOSO_DATASET_REVIEW.md) and [the dataset and connector workflow](MULTI_CONNECTOR_WORKFLOW.md).

## Remaining implementation work

1. **Windows acceptance scripts:** the six older version checks and Phase 4's obsolete offline/object-pinning/golden-case assumptions still need migration and a native Windows run. Optional sample configuration is now allowed; disabling a local planner remains enforced.
2. **Ask-to-report UI:** the report backend stores reviewed plans, but unified Ask needs its Add to report button.
3. **Policy-aware compilation:** active row policies and restricted semantic columns currently block analytics; implementing filtered/column-aware results remains required for those enterprise roles.
4. **Authoring/diagnostics:** richer metric forms, read-only executable-definition inspection, and actual-versus-reference benchmark differences.
5. **Source freshness SLAs:** the contract field is stored; enforcing source-watermark freshness remains pending. Relationship/grain evidence refresh is implemented.
6. **Connection instances and large-data federation:** the provider registry has one configured connection per type. Separately named instances and warehouse-side federation/pushdown for large inputs are further work.
7. **Additional calculation strategies:** independent facts with different grains/populations, fiscal calendars and unsupported local-time operations.
8. **Exact financial precision:** typed CSV imports now work; SQLite REAL remains binary floating point. Exact decimal financial arithmetic across native/federated execution needs a precision-preserving strategy and result benchmarks.

## Remaining setup and acceptance work

- Configure and verify live Bedrock planning/review access; run representative language-accuracy benchmarks.
- Configure actual enterprise connectors and validate their dialects, complete bounded extraction, key types and result parity. SQLite/Contoso tests do not establish Snowflake/Athena/Databricks live acceptance.
- Certify the actual deployment's definitions/roles and migrate older prose-only measures, reports and benchmark cases.
- Validate native Windows deployment, workers, scheduled reports, identity integration, queue/control storage and state recovery.
- Complete cloud-configuration publication as appropriate; the earlier onboarding configuration was recorded as a draft.

See [the new validation record](../VALIDATION_8.5.0.md) for checks actually performed. Passing mocked provider tests is evidence of the compiler integration, not a live model-accuracy claim.
