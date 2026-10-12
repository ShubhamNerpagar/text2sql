> Historical report from the original attachment. For the updated release, see [VALIDATION_8.4.0.md](VALIDATION_8.4.0.md).

# QA report — Data Intelligence Platform 8.1.0 release candidate

**Decision:** Local QA passed. **Production sign-off remains blocked** by unavailable Windows EC2, real ALB/OIDC and live AWS/warehouse acceptance evidence.

## Completed QA

- **141 automated tests passed** across prior functionality and new authentication, authorization, cross-workspace report and configuration checks.
- Python compile and frontend JavaScript syntax checks passed.
- **41** sidebar destinations checked: **40** ordinary passes, **1** expected missing-AWS-credentials warning, **0** browser failures.
- **11/11** end-to-end application interactions passed, including real synthetic data profiling, certification, relationship evidence, quality, ontology, background worker, search and navigation.
- **231 browser-bridged API responses HTTP 200**; **0** JavaScript exceptions.
- Mobile viewport checked: no horizontal overflow observed.
- Unsafe `APP_ENV=production` configuration was rejected by the startup preflight.
- New tests validate rejected forged development headers, invalid signed-token properties, cross-origin mutations, report-ID cross-workspace isolation and global monitoring restrictions.

## Not proven by local QA

1. Native Windows Server execution and scheduled-task recovery.
2. Live HTTPS ALB/OIDC identity and private origin security.
3. Bedrock inference profiles, model availability, Glue/Athena, PostgreSQL, Snowflake and Databricks connectors on real data.
4. AWS multi-host DynamoDB queue lease/failover and persistent-state disaster recovery.
5. Performance at production data scale, accessibility and independent penetration testing.
6. Complete end-user capabilities: YAML and SQL dataset tabs are generated read-only views; external data row previews are deliberately unavailable.

## Evidence

- `qa_results/qa_browser_release.json` (per-page outcomes, calls and workflows).
- `qa_results/` desktop and mobile screenshots (same layout as the validated release).
- `PRODUCTION_ACCEPTANCE.md` (go-live gates).
- `VALIDATION_8.1.0.json` (machine-readable local status).

Do not treat `Test-ProductionReadiness.ps1` as a substitute for live production acceptance.
