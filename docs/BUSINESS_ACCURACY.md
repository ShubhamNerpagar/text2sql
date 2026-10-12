# Business definitions, ontology and accurate queries

## The execution path

```mermaid
flowchart LR
    Q[Question and previous plan] --> L[Verified Bedrock planner]
    O[Certified ontology release] --> L
    L --> I[Exact clause coverage]
    I --> C[Metric and concept compiler]
    E[Fresh grain and relationship evidence] --> C
    C --> V[Separate semantic review]
    V --> D[Read-only warehouse query]
    D --> R[Answer and pinned report plan]
```

The model selects IDs and structured query operations; it never supplies executable SQL. The compiler resolves certified formulas, applies mandatory predicates, checks measured grain and approved many-to-one relationships, and emits bounded aggregate SQL. A separate LLM call checks whether the plan answers the complete question. Missing coverage, unsupported meanings, ambiguous roles or failed evidence prevent execution.

Follow-ups carry the previous structured plan. Fields remain unchanged unless the model explicitly identifies a change, and the reviewer checks whether the question actually authorizes it. Unrelated filters remain even when a follow-up adds a new constraint. Explicit removal must identify previous filter indices and map the removal to exact question spans. Retained filters and concept predicates are applied again. A model can still misinterpret an explicit change; benchmarks are the way to measure this behavior on real questions.

## Adding a metric or concept

Use **Object Studio** (also opened by **Semantic Studio**) or `POST /api/phase3/objects?workspace=...`. Bind all physical columns used by the formula, grain, predicates and time role. An example measure's `semantics` is:

```json
{
  "grain": ["line_id"],
  "aggregation": "sum",
  "expression": {
    "op": "subtract",
    "args": [{"column": "amount"}, {"column": "refund"}]
  },
  "unit": "USD",
  "additivity": "additive",
  "filters": [{"column": "status", "op": "eq", "value": "Complete"}],
  "time": {"column": "order_date", "timezone": "UTC", "calendar": "gregorian"}
}
```

The draft also needs an object ID, label, description, physical asset binding and bound column names. An independent steward certifies it after review. SQL plans select `{"metric_id":"net_sales","alias":"value"}`; the model cannot change SUM to AVG, omit the required status or rewrite the formula.

Expressions permit bound columns, numeric literals and bounded arithmetic/coalesce operations. They do not accept SQL strings. Supported aggregations include count, distinct count, sum, average, min/max and ratios of approved sum/distinct-count expressions. Weighted averages declare `weight_column`; the compiler computes a weighted aggregate rather than averaging already aggregated results. Percentage scaling must be explicit in the approved formula; a unit label does not automatically multiply a ratio by 100 or convert currencies.

An executable concept such as “completed order” has a scoped binding and `{"filters":[{"column":"status","op":"eq","value":"Complete"}]}`. Selecting its approved concept ID injects that predicate. Documentation-only concepts can describe the ontology, but cannot supply a missing executable condition. Synonyms help retrieval; they do not change the formula.

Grain is a business assertion supported by measured uniqueness and null checks. If an order-level value is repeated on line rows, declare the order grain or bind the metric to the order table. A unique line key does not prove that every numeric column is additive at line grain. Steward review and independent results remain essential.

## How ontology and relationships work

`P3_OBJECT` is the shared authoring store; `P2_RELATIONSHIP` is the shared physical relationship store. Object Studio, Semantic Studio and GraphRAG project the same IDs. Promoted `P4_RELEASE` records pin certified object versions, bindings and structured semantics. Reports pin that release and those metric IDs. Editing or de-certifying an object invalidates a pinned executable release until it is re-certified and re-published.

Discovery imports declared foreign keys, including differing column names and composite keys. A naming match to a single primary key is a weaker candidate when no foreign key exists. Neither becomes query-approved automatically. Manual relationships support key lists in corresponding order and a business role such as billing customer or shipping customer. Role-playing dimensions use separate SQL aliases; ambiguous roles must be specified.

Evidence compares native keys exactly, using the same equality semantics as the join. Approval requires **zero duplicate target key rows**, at least **90% distinct-key coverage and row coverage**, a nonempty source-key population, and current schema/definition fingerprints. Partial-null composite keys do not match. A left join preserves unmatched fact rows; a business filter on a target dimension intentionally excludes unmatched rows.

Relationship and grain evidence expires after 24 hours. Ask refreshes expired approved relationship evidence; the worker checks for expired evidence every minute. Unchanged passing evidence keeps its prior approval and reviewer. Duplicate keys, failed coverage or changed fingerprints remove query trust. GraphRAG also marks expired or changed evidence as untrusted. Grain failures block metrics. Data can change within that cache window; these checks are not an atomic database snapshot or a continuous guarantee. Use warehouse constraints and appropriate refresh timing for critical workloads.

## Manual intervention before queries

The guided onboarding flow prepares profiles, owned contract drafts, count/distinct-count and numeric measure proposals, temporal objects and relationship evidence. Preparation is repeatable and never automatically certifies business meaning. Numeric proposals with an unspecified unit cannot be certified.

A steward must confirm meanings, formula, measured grain, additive behavior, units, default date role, synonyms/codes, mandatory predicates and relationship roles. Contracts need review and certification, and a different steward must certify authored ontology objects. Batch review reduces repeated clicks; individual review changes are auditable, and a batch is not an atomic database transaction. Publish/promote once after the relevant definitions are approved, then configure verified models.

Routine passing evidence refresh needs no new approval. New or changed business meanings require review. There is no universal zero-touch path from arbitrary schemas to reliable business answers.

## Business-result benchmarks

Use **Ontology → Question Testing** or `/api/benchmarks/business/cases` and `/api/benchmarks/business/run`. Each answer case has a pinned release, question, independently authored aggregate reference SQL and scoped reference asset. Results compare values in SELECT order, ignoring display aliases and row order, with tolerance for native numeric values. An expected-refusal case passes only on an explicit clarification with no execution; missing model access or infrastructure failure is never a correct refusal.

Add distinct cases for paraphrases, date boundaries, locations/statuses, combinations of filters, multi-table joins, ambiguous concepts, follow-ups and unsupported requests. For follow-up cases, provide an optional `previous_plan` through the benchmark API; it is recompiled against the pinned release before model interpretation. The integration tests also exercise retained filters, concepts and limits. Store reference queries with the same expected ordering of dimensions and metrics and compatible output limits. Run benchmarks against a stable data snapshot to avoid changes between actual/reference execution.

`scripts/benchmark_accuracy.py` imports these cases through the API and runs result comparisons. Old object-matching golden cases require reference SQL migration. Passing mocked provider tests demonstrates compiler and integration behavior, not general language accuracy of a live model.

## Upgrade an existing installation

Back up platform state first. Keep the same explicitly selected physical scope. Profiles and relationship fingerprints now include foreign-key metadata, so refresh evidence and re-certify changed contracts/bindings as required. Prose-only or inferred metrics must receive structured semantics, measured grain and independent certification. Legacy Semantic Studio dictionaries/verified SQL templates cannot authorize Ask.

Publish and activate a new certified release. Re-save existing report questions so widgets store LLM-reviewed plans and release IDs; legacy widgets are explicitly refused until migrated. Replace old object-only golden cases with independent reference SQL. Re-test IAM/model access if region, credentials or models change.

The compiler currently supports Gregorian relative periods, one connector/database, bounded directional many-to-one joins and aggregate results. Fiscal calendars, cross-source/fact-to-fact calculations needing different grains, arbitrary SQL/window functions, unsupported local-time timestamp operations and unrestricted row extraction require separate implementation; they are refused rather than guessed. Restricted semantic columns and active row policies fail closed until policy-aware compilation is implemented.
