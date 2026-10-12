# 6.1 Interface Design

The 6.1 interface uses the same broad usability principles visible in current Snowflake Snowsight and Databricks analyst experiences: grouped navigation, a prominent global search, a dedicated analyst question surface, compact catalog tables, and progressive disclosure of administrative complexity.

It is not a pixel clone of either product.

## Design rules
- Seven primary navigation areas only, with **Reports** promoted for business users.
- Global search is available from every page.
- `Ask` is optimized for an analyst; trust evidence stays in a contextual side panel.
- `Reports` is a first-class BI workspace; dashboards persist semantic questions rather than raw SQL/results.
- Technical governance lives under `Semantics`, not the analyst home page.
- Monitoring is consolidated instead of split across multiple workspaces.
- Data tables are preferred over visually heavy cards for metadata-heavy screens.
- Light, neutral surfaces make status and exceptions more visible.

Reference material:
- https://docs.snowflake.com/en/user-guide/ui-snowsight-navigation
- https://docs.snowflake.com/en/user-guide/ui-snowsight-homepage
- https://www.databricks.com/product/genie/one
