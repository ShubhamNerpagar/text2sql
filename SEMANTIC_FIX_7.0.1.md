# Data Intelligence Platform 7.0.1 — Semantic Runtime Fix

This patch fixes the semantic behavior observed during real application testing of 7.0.0.

## Symptoms fixed

1. Semantic Studio displayed `0` metrics even though the review queue contained many numeric metric candidates.
2. Questions such as `give me total car ids` could silently fall back to `COUNT(*)` and return the table row count.
3. Promoted metric candidates could become stuck in `reviewed` because the physical source binding could not become certified through the UI lifecycle.
4. `SUM`, `AVG`, and `COUNT DISTINCT` metadata were not honored by the deterministic SQL compiler when the metric source did not contain an explicit SQL expression.
5. Dataset questions such as `What's the data about?` were routed as analytical SQL questions instead of metadata/ontology explanations.
6. The Semantics top navigation could continue to visually highlight `Model` while the Semantic Studio content was displayed.
7. Governance could inspect physical columns from outside the active workspace.

## New semantic behavior

### Metadata onboarding

Onboarding now materializes inferred metrics directly in the workspace semantic model while keeping them explicitly `inferred`.

Generated examples include:

- row count for each physical entity/table;
- distinct-count metrics for identifier/reference columns;
- sum metrics for additive numeric fields;
- average metrics for ratio/rate/score/confidence/lift/support/median-like fields.

These definitions are generated from metadata only. No sample business rows are required.

### Test/development execution

`ALLOW_INFERRED_ANALYTICS=true` enables clearly labeled **inferred preview** execution. This is intended for development and source validation.

The UI displays a warning and does not offer `Add to report` for inferred-preview answers.

### Production execution

Use:

```dotenv
ALLOW_INFERRED_ANALYTICS=false
```

In this mode inferred metrics must be reviewed/certified before production execution.

### No silent row-count fallback

An unresolved aggregate question no longer becomes `COUNT(*)` merely because a table was found. The platform returns a clarification request instead.

### Metric aggregation

The deterministic compiler now honors:

- `SUM(column)`
- `AVG(column)`
- `MIN(column)`
- `MAX(column)`
- `COUNT(column)`
- `COUNT(DISTINCT column)`
- `COUNT(*)` only for an explicit row-count metric

### Dataset explanation

Questions such as:

- `What is the data about?`
- `Explain this dataset`
- `Describe the dataset`
- `Tell me about the data`

are answered from catalog + semantic metadata without executing analytical SQL.

## Upgrading an existing 7.0.0 workspace

The 7.0.1 code is compatible with an existing state directory, including legacy metric-candidate IDs.

After replacing the application code:

1. Keep your existing `.env`.
2. For test/dev, add:

   ```dotenv
   ALLOW_INFERRED_ANALYTICS=true
   ```

3. Restart the application.
4. Open **Admin → Onboarding**.
5. Click **Resync metadata** once for the existing workspace.
6. Open **Semantics → Semantic Studio**.
7. The Metrics count should now be greater than zero when the schema contains suitable numeric/identifier fields.
8. Review/certify the metrics that have valid business meaning.

## Expected behavior for the VGA-style table seen during testing

A single physical wide table may still show **1 inferred entity**. That is intentional: the platform does not fabricate multiple business entities merely from column names. The same table can still generate many dimensions and metrics. Additional business entities/concepts should come from steward review or optional AI enrichment.

For a table with fields such as `segment_id`, `total_cycles`, `total_time_score`, `median_gap_days`, `lift`, `confidence_a_to_b`, and `support`, the repaired metadata bootstrap creates inferred metrics such as:

- Unique Segment Id — COUNT DISTINCT
- Total Cycles — SUM
- Average Total Time Score — AVG
- Average Median Gap Days — AVG
- Average Lift — AVG
- Average Confidence A To B — AVG
- Average Support — AVG

## Validation

The 7.0.1 Windows-native build passes the complete automated suite plus regression tests created specifically for the observed failures.
