# MCP / agent tool surface

The application exposes MCP-compatible JSON-RPC at `/mcp` and `/api/mcp`.

Tools:
- `search_semantic_model`
- `get_metric`
- `resolve_query`
- `query_data`
- `get_lineage`
- `list_verified_queries`
- `list_actions`
- `execute_action`

Every tool runs through the same identity, GraphRAG column filtering, query policy and action permissions as the UI/API. There is intentionally no unrestricted arbitrary-SQL or arbitrary-write tool.
