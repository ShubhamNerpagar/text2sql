## 8.4.0 — LLM-required business analytics

- Remove offline natural-language answering. Verified Bedrock planning and semantic verification are required; structured HTTP plans are preview-only.
- Compile approved metric/concept IDs with structured formulas, required predicates, units, time roles and measured grain. Preserve unrelated follow-up filters and require explicit clause mappings for removals.
- Share object and relationship identities across Object Studio, Semantic Studio, GraphRAG, Ask and saved reports. Expired graph evidence is untrusted.
- Import declared foreign keys; execute composite and role-playing joins with native equality and exact duplicate counts. Preserve unchanged passing approvals on refresh and revoke failed evidence.
- Add guided preparation, independent review, evidence refresh and reference-SQL business-result benchmarks, including optional follow-up context.
- Protect local API/worker control-state writes with a process lock and use consistent DynamoDB reads. Failed writes cannot leave uncommitted approvals in cache.
- Add Windows timezone data and document model connection, upgrade and remaining execution limits. Current verification is recorded in VALIDATION_8.4.0.md; older reports below are historical.

## 8.3.0 — Unified governed Ask

- A single Ask Data workspace now handles simple aggregates and multi-table analytics; no advanced query mode or JSON plan editor in the UI.
- New `POST /api/phase4/unified/ask` uses certified release-pinned structured planning and the existing safety compiler for *all* supported query types.
- Routes to verified Bedrock automatically, otherwise uses a narrow, fail-closed offline semantic planner.
- Adds conversation follow-up context with server-side revalidation, tabular/chart results and expandable SQL/provenance details.
- Maintains legacy APIs for compatibility; applies existing semantic ACL and denies unsupported row policies.
- 152 automated tests and a browser-bridged UI acceptance covering 4 successful questions, 1 safe refusal, and zero JavaScript errors.
- Known limits: live Bedrock, external warehouse execution, certified report widget integration, and persisted conversations need production work.

# Data Intelligence Platform 8.1.0 — Production hardening (local release candidate)

- Retains all five capabilities and the 8.0.2 three-level dataset workbench (sidebar, objects, contextual tabs).
- Enforces signed ALB/OIDC identity for production APIs and MCP and rejects startup with insecure environment/configuration.
- Verifies token signer, client, signed subject, expiry, key-id and fixed official regional AWS key server; cross-origin mutations denied.
- Adds missing legacy endpoint permissions and reduces cross-workspace/report-ID/global-monitoring data disclosure.
- Restricts Windows development bind to localhost, adds Windows preflight, authenticated ALB-only ingress guidance and security headers.
- Requires multi-host DynamoDB-backed job queue in production.
- Adds regression/security tests, deployment guidance and browser evidence.

**Status:** Local QA passed; live Windows EC2/ALB/OIDC/AWS connectors/HA/scale/security sign-off remains required.

## 8.2.0 — Certified multi-table analytics and Bedrock structured planning
- Added Advanced Ask inside Ontology → Governed Ask + BI, with full-width JSON plan editor, Bedrock mode and offline sample execution.
- Added `/api/phase4/advanced/schema` and `/api/phase4/advanced/ask` with application-compiled SQL generated from certified fields and approved, fresh, measured joins.
- Added many-to-one multi-hop joins (up to five tables), aggregate measures, GROUP BY, WHERE, HAVING, ORDER BY, and bounded results.
- Bedrock Converse proposes JSON; malformed or unverified output fails closed. Full prompt accuracy and live Bedrock integration remain to be validated.
- Verified full regression suite, local data execution and browser-bridged UI smoke. No external warehouse execution enabled in this release.
