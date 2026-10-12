# Validation — Data Intelligence Platform 8.5.0

- **204 automated tests passed**, zero failures/skips, one dependency deprecation warning. Full suite: `python -m pytest -q`; 169.75 seconds.
- **10 Chromium browser checks passed**, with zero JavaScript page errors. These cover empty initial selection, optional Contoso, source-specific selections retained across browsing and saved-scope reload, dataset identity, combined-source follow-ups, reference SQL guidance, and mandatory model access.
- The integration executes actual SQL on the PostgreSQL/SQLAlchemy SQLite fixture and the bundled Contoso SQLite database, followed by temporary DuckDB aggregation. Independent expected results and reference SQL check the answer. Bedrock planning/review responses are explicitly mocked.
- Cross-connector tests cover incomplete/oversized extraction, payload limits during fetching, cached-evidence changes, duplicate grain, failed coverage, unapproved joins, source constraints before execution, and disabled external-file access. The original semantic/compiler/security controls also run in the full suite.
- Python compilation, JavaScript syntax and Git whitespace checks passed.

The repository includes eight illustrative Contoso tables and 10,000 Orders. The official SQLBI download is not installed in this checkout; an attempted public release lookup was blocked by a network-proxy 403. The included installer remains available for machines with upstream access. No live download, live Bedrock, live enterprise warehouse or native Windows acceptance is claimed.

Cross-source execution uses complete bounded per-source snapshots, not an atomic distributed snapshot. Large inputs require an appropriately narrowed physical dataset or warehouse federation layer. Independent fact calculations with different grains/populations and the other items in [the current pending-work audit](docs/PENDING_WORK_8.5.0.md) remain outside this acceptance.

See [test output](qa_results/pytest_8.5.0.txt), [browser checks](qa_results/browser_8.5.0.json), [current UI](docs/UI_WALKTHROUGH_8.5.0.md), and [the sample/multi-connector workflow](docs/MULTI_CONNECTOR_WORKFLOW.md). Earlier version records remain historical.
