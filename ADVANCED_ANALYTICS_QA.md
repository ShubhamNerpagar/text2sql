> Historical report from the original attachment. For the updated release, see [VALIDATION_8.4.0.md](VALIDATION_8.4.0.md).

# Advanced analytics — implementation and QA

Release: 8.2.0. The trusted model generates **structured JSON**, never executable SQL.

## Confirmed in local environment
- Multi-table SQL compiler with up to four approved, directed joins and five certified assets
- Measured join target uniqueness must be 100%; relationships require approved status, matching source/target schema fingerprints, and measurement age <= 24 hours
- Certified columns on release-pinned ontology objects required for every selected field and join key
- GROUP BY, SUM/COUNT/COUNT DISTINCT/AVG/MIN/MAX, WHERE, IN, BETWEEN, HAVING, ORDER BY, LIMIT
- Bounded read-only aggregated results on the bundled Contoso SQLite dataset
- Fresh ontology/contract checks before compilation and again immediately before execution
- Rejections for noncertified columns, invented relation IDs, reverse and disconnected joins, raw SQL input, oversized LIMIT, unknown aliases, and permission violations
- Bedrock integration exercised with a mocked Converse JSON response; malformed model output rejected
- Chromium UI smoke: Advanced Ask navigated, loaded example, previewed join SQL, executed offline, rendered three result rows without console exceptions (test used a Python-backed fetch bridge due network-navigation restrictions)

## Not validated / deliberately restricted
- Actual Bedrock Converse calls using an AWS account, prompt accuracy, latency, cost and model-to-model differences
- Production external warehouse query execution or field-level/row-level authorization beyond the scoped certification guard
- Complex fan-out/snowflake joins with nonunique dimensions or fact-to-fact joins
- Performance at enterprise data scale and query cost protections for external engines
- Native Windows EC2 deployment and SSO security acceptance

This is an advanced-query development release, not a production-certified execution engine.

## Windows smoke test
Run `\.\windows\Test-AdvancedQueries.ps1 -Workspace <id> -ReleaseId <release>` after starting the application. The script validates the active version and certified metadata; it does not create reviewer approvals or invoke Bedrock.
