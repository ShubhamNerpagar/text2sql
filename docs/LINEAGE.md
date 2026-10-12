# Semantic lineage and impact

Lineage links data source -> database -> table -> column -> entity/dimension/metric -> verified query -> observed user query.

`/api/lineage` returns the graph. `/api/lineage/impact` traverses upstream, downstream or both and is security-filtered for the current identity.

This enables both provenance (`Where did this KPI come from?`) and impact analysis (`What metrics and queries use this column?`).
