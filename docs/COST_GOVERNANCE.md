# Cost Governance

The application records estimated query cost from source execution metadata when available.

For Athena, use a dedicated workgroup and configure a **server-side bytes-scanned cutoff per query**. The application-side `MAX_QUERY_BYTES` is a planning/observability control; the Athena Workgroup is the hard warehouse-side guardrail.

Recommended controls:

- dedicated read-only Athena Workgroup;
- `BytesScannedCutoffPerQuery`;
- Athena/S3 CloudWatch billing alarms;
- `MAX_RESULT_ROWS` and query timeout in the application;
- curated semantic relationships to prevent accidental broad joins;
- separate development and production workgroups.
