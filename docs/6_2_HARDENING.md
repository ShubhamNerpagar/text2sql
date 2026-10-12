# 6.2 Hardening and Level-4 Readiness

## What changed

### GraphRAG
- Provider abstraction added.
- Local Docker uses a deterministic 128-dimensional fallback so the app stays offline and fast.
- ECS/AWS can use Bedrock embeddings through environment variables.
- Provider/model/dimension metadata is stored with the graph.
- Graph fingerprint includes embedding configuration, so provider changes force rebuild.
- Explorer payload never sends embeddings to the browser.

### Metrics
- Metric contracts now validate aggregation, additivity, comparison type, dependencies, dimensions, time semantics, owners and certified-source coverage.
- Dependency cycles are rejected.
- Added governed examples for revenue-per-vehicle and period-over-period revenue growth.

### BI Reports
- Reports remain semantic-question based rather than raw-result based.
- Refresh executes under current security policy.
- Added governed widget drill-down API.
- Report lineage remains available.

### Observability
- p50/p95/p99 query latency.
- Route failure counts.
- Cost totals and maximum observed estimated cost.
- Security block rate.
- Evaluation regression/improvement counts.

### Data sources
- Provider health checks for Athena, PostgreSQL/Aurora, Snowflake and Databricks SQL.
- Unconfigured providers are explicitly reported rather than appearing healthy.

### Testing
- Project-level `pytest.ini` fixes import behavior.
- Legacy TestClient lifecycle is isolated by `tests/conftest.py`.
- Full regression suite: **61 passed**.
- A fourth platform-readiness evaluation suite is included.

## Level 4 definition

Level 4 means:

1. implemented,
2. integrated into the product flow,
3. governed by security/semantic controls,
4. observable,
5. regression-tested,
6. deployable through the same container architecture.

It does **not** mean the product has the production scale, adoption, SLA history or connector depth of Snowflake, Databricks, ThoughtSpot, Palantir or Power BI. Those require real customer workload evidence.
