# Governed BI Reports — 6.1

Reports are saved **semantic questions**, not saved raw SQL or persisted result rows.

## Why

A dashboard widget stores:
- market
- natural-language semantic question
- title
- visualization preference

When a dashboard refreshes, the question runs through the same pipeline as **Ask**:

`RBAC/CLS/RLS -> semantic resolver -> trusted template / deterministic compiler / agent fallback -> SQL safety -> warehouse policy -> result`

This prevents a saved dashboard from bypassing new security rules or semantic model changes.

## Workspaces

- **Reports > Dashboards** — saved reports, KPI cards, bar/line/table visualizations, publish/certify controls.
- **Reports > Lineage** — report -> widget -> metric/dimension -> physical table impact view.
- **Ask > Add to report** — promotes a successful governed question into a report widget.

## Persistence

Windows/local test mode uses the control-plane state file. AWS durable mode can use the same DynamoDB-backed `ControlRepository` pattern already used by conversations, branches, actions and audit.

## Status lifecycle

`draft -> published -> certified -> deprecated`

Certification requires publish permission.

## Cost note

Report refresh re-executes widgets. In AWS production, use the Athena workgroup scan cutoff and choose an explicit refresh strategy appropriate for dashboard frequency and warehouse cost.
