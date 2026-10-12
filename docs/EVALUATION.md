# Evaluation and regression

Version 7.0 ships the evaluation engine but intentionally no customer-specific suites. After a real workspace is generated, add workspace-specific suites such as:

- `core_semantic` — metric/concept/value/time/ambiguity resolution.
- `semantic_intelligence` — GraphRAG retrieval, table selection, trusted joins and deterministic SQL compilation.
- `adversarial_semantics` — routing, PII exclusion expectations, authority thresholds, ambiguity and complex market/join cases.

Runs are persisted and compared with the previous run to expose regressions and improvements.

## Benchmark isolation

Held-out questions must not be inserted into runtime verified/trusted queries. Training/verified examples and evaluation examples remain separate to avoid answer leakage.

## Result-equivalence extension

For production acceptance, add real warehouse cases with gold SQL/result assertions. To avoid false positives where two different SQL statements happen to return the same current result, include adversarial fixtures such as orphan join keys, nulls, duplicates, ties and missing periods.

## Deployment gate

Recommended CI rule:

```text
unit/integration tests pass
AND semantic suites do not regress
AND execution benchmark stays above agreed threshold
THEN deploy the validated Windows-native application package
```
