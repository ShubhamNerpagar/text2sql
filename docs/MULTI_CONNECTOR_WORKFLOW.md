# Optional sample data and combined-source questions — 8.5.0

Contoso is an optional data source. Removing offline natural-language answering does not remove locally stored data: every accepted new question still requires verified Amazon Bedrock planning and semantic verification, even when its data comes from Contoso.

## What data is included

The repository includes `sample-data/contoso/contoso_demo.sqlite3`, an independently generated retail illustration with eight tables: Orders (10,000 rows), OrderRows and Sales (19,969 each), Customer (1,000), Product (120), Store (40), Date (730) and CurrencyExchange (4). It is not an official SQLBI export.

The official SQLBI archive/database is not present in this checkout. `windows/Install-Contoso.ps1` and `scripts/install_contoso_official.py` install it separately as `contoso_official.sqlite3`; the catalog offers `contoso_official` only when that file is installed. A public-release check from this cloud environment was blocked by a network-proxy 403; no successful official download is claimed. The bundled illustration remains available without that download.

The optional official installer currently imports columns as TEXT to preserve CSV values. That imported variant needs typed numeric columns/conversion before numeric measures can be certified; the bundled illustration already has numeric physical types. The compiler refuses a numeric formula on a TEXT binding rather than guessing a conversion.

`ENABLE_SAMPLE_EXECUTION=true` makes the optional source available. It does not select its tables, bootstrap a workspace, supply business meanings or enable a local question planner. Set it to false to remove sample execution from an installation. Selecting only enterprise connectors keeps Contoso out of that workspace's scope.

## Select sources and datasets

1. Configure the desired Athena, PostgreSQL, Snowflake or Databricks connections.
2. Open **Data → Catalog Explorer** and check one or more available connector boxes. Contoso can be checked or left unchecked.
3. Browse each selected connector's catalog/database/schema and check its tables. Selections survive switching the connector being browsed.
4. Save and generate the workspace. Every table stores its source identity; a mixed scope records `source_id: federated` and its actual `source_ids`.
5. Prepare profiles, contracts, metric/concept definitions and relationships. Review and independently certify business meanings, then publish and activate a release.
6. Verify/select the planning and verification models in **Administration → AI Models**, then use **Ask Data**.

The current source registry configures one connection per supported provider type. Additional separately named connections to multiple PostgreSQL instances, for example, require a connection-instance registry; separate database URLs are not automatically exposed as new selectable instances.

## How one question uses multiple connectors

The planner receives certified definitions and source-bound asset identities. It can select a relationship joining assets on different connectors when that relationship has passing exact-key evidence and explicit approval. The compiler applies the metric's formula, predicates and grain, and uses role-specific aliases.

A query using only one connector/database follows native execution. A query using multiple connector/database pairs reads its necessary columns from the selected assets into a transient DuckDB database and executes the compiled aggregate there. Source rows are never added to LLM prompts, stored in semantic metadata, or written as a federation data cache. External-file access, extension autoload and disk spilling are disabled in the temporary engine.

Cross-source key types must be compatible. Approval compares complete bounded snapshots using the same DuckDB equality as execution and requires zero duplicate target keys plus at least 90% distinct-key and row coverage. Loaded snapshots recheck metric grain, target duplicates and coverage before aggregate execution. Unapproved joins, type mismatches, incomplete extraction and changed grain/coverage are refused.

Default limits are 16 snapshot assets, 100,000 rows per asset, 400,000 total rows and a 64 MiB serialized payload budget. DuckDB has a 256 MB memory limit. The supported aggregate plan still allows four directional joins, eight metrics/dimensions and 100 result rows. Raising a result-display limit does not remove snapshot limits. Large datasets require a narrower physical selection or a warehouse federation layer; the application refuses oversized or incomplete snapshots instead of answering from a truncated sample.

The extraction uses a row count followed by a bounded read and checks that both agree. This catches incomplete extraction and some concurrent changes; it is not a distributed transaction or a common point-in-time snapshot across warehouses. For critical calculations, use stable source snapshots and benchmark that consistency requirement.

Metrics still belong to the base dataset. Cross-connector fact-to-dimension joins are supported; combining independent fact metrics at different grains needs additional aggregation strategies. Row-policy/restricted-column compilation, fiscal calendars and unsupported non-UTC timestamp operations retain their existing limits.

## Benchmarks

For an independent combined-source reference, use the scoped snapshot names shown in **Question Testing**: `f_` followed by the asset ID suffix. These names identify sources unambiguously even when both connectors expose the same physical table name. The benchmark reads only the referenced selected assets, executes the reference in its own temporary snapshot, and compares values. Native references can continue using their source's physical table names.

The automated/browser example joins PostgreSQL-backed SQLite sales to Contoso CurrencyExchange and returns EUR 180, GBP 80 and USD 90. The measure's USD amounts are treated as already normalized; the currency dimension describes original transaction currency, not an automatic conversion. Model responses are explicitly mocked, and live enterprise/provider acceptance remains pending.
