# Data-source portability

Built-in source adapters:
- Amazon Athena / Glue — native AWS adapter
- PostgreSQL / Aurora PostgreSQL — SQLAlchemy
- Snowflake — SQLAlchemy connector
- Databricks SQL — SQLAlchemy/Databricks connector
- Demo — local deterministic results

`GET /api/data-sources` reports configured adapters. Privileged users can use `/api/data-sources/{source}/catalog` for metadata discovery.

The semantic model is source-neutral. Logical objects bind to physical tables/columns; SQLCompiler selects a target dialect. Trusted templates declare supported dialects and are bypassed when the selected source is not certified for that template.
