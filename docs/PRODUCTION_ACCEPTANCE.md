# Production acceptance — release 8.1.0

**Decision: BLOCKED pending on-environment evidence.** This package is a hardened, locally tested *release candidate*, not a certified enterprise production deployment.

## What was fixed in this release

1. Central authentication for **every `/api/*` and `/mcp` route in production**. Only the minimal `/api/health` check is public. Legacy route names remain for compatibility.
2. Reject startup on unsafe production configuration: development identities, disabled security, missing ALB signer/client pinning, wildcard HTTP CORS, enabled raw samples/inferred analytics, or missing durable AWS stores.
3. OIDC signature and claim hardening: strict ALB key identifier, signer and client binding, token expiration, signed subject matching the ALB identity header.
4. Enforced workspace or review permissions on formerly unguarded legacy catalog, graph, lineage, evaluation, governance and source metadata routes; restricted cross-user action history and bootstrap global statistics.
5. Sanitize unexpected production API failures; hide AWS details from the public health endpoint; add browser response security headers.
6. Windows launch defaults to localhost, rejects all-interface development binds, runs config checks in production, and disables trusted forwarding headers; a firewall script refuses unrestricted inbound rules.
7. Corrected cross-workspace report ID access, global monitoring and action catalog exposure; reject cross-site state-changing requests and invalid/expired OIDC expiry values.
8. Require the **DynamoDB** worker queue in production; reject misspelled production profiles (`APP_ENV=prod`) instead of silently enabling development auth.
9. Repaired old Windows smoke-test version gates, demo connector health, and added automated security tests and offline preflight tooling.
10. Preserved 8.0.2 grouped sidebar and selected-dataset contextual Page/YAML/Profile/Sample/Transformation/SQL/Lineage views.

## Operator checklist — must be evidenced before go-live

- [ ] **Dedicated Windows EC2:** clean Windows Server image; Python 3.12 x64; install this ZIP. Capture OS build and exact dependency versions.
- [ ] **Private origin:** EC2 security group inbound app port restricted **only to ALB security group**; no publicly reachable 8000; optional Windows firewall ALB subnet CIDRs only.
- [ ] **TLS & authenticated ALB:** HTTPS listener, managed valid certificate, mandatory ALB authenticate-oidc/Cognito action before forwarding; no bypass listener or unauthenticated target group.
- [ ] **Pinned token trust:** `ALB_EXPECTED_SIGNER_ARN`, `ALB_EXPECTED_CLIENT_ID`, AWS region and identity role claims match your real ALB; unauthorized direct calls return 401.
- [ ] **Access matrix:** prove analyst, steward, admin permissions for *every* workspace including prohibited-column and cross-tenant probes. Carry out full external penetration/security review.
- [ ] **Secrets:** use IAM instance profile and managed secrets; no embedded access keys in `.env` or distribution archive; rotate tokens; confirm S3 and DynamoDB SSE/KMS policies.
- [ ] **Durable state:** `SEMANTIC_BUCKET`, `LEARNING_TABLE`, `PERSIST_LOCAL_STATE=false`; validate workspace/contract/release survival after restart and machine replacement.
- [ ] **Live AWS:** STS/IAM, S3, DynamoDB, Glue catalog, Athena read-only workgroup, encrypted Athena results, model discovery and Bedrock invocation permissions.
- [ ] **Databases:** PostgreSQL, Snowflake, Databricks connector TLS, schema drift, row and relationship consistency, query limits and failure handling using actual credentials.
- [ ] **Distributed jobs:** production now requires `JOB_QUEUE_BACKEND=dynamodb`; test lease contention, cancellation, expired lease recovery, hard crash and dead-letter retry across real machines.
- [ ] **Reliability:** bounded load and 24-hour soak with representative datasets, timeout budgets, backups/restores, RTO/RPO, CloudWatch alerts, cost controls, rollback drill.
- [ ] **UI:** run 41-page and 11-workflow acceptance via the authenticated production URL; inspect responsive views and the seven dataset contextual tabs.
- [ ] **Approve:** obtain business/security sign-offs and record evidence. Do not mark ready based solely on configuration preflight.

## Native Windows installation

In PowerShell, from the application root:

```powershell
.\windows\Install-App.ps1 -SkipTests
Copy-Item .env.windows.production.example .env
# Populate .env with real production values (no angle-bracket placeholders).
.\windows\Test-ProductionReadiness.ps1
.\windows\Test-ProductionReadiness.ps1 -CheckAws
# AFTER verifying the ALB SG-only network restrictions:
.\windows\Start-App.ps1 -BindHost 0.0.0.0 -NoBrowser -LogToFile
# Separate process or managed Scheduled Task:
.\windows\Start-Worker.ps1
```

`Test-ProductionReadiness.ps1` checks configuration, and `-CheckAws` checks a limited subset of real STS/S3/DynamoDB/Athena permissions. It **does not** exercise Bedrock invocation, database parity, the ALB listener, worker failover, or Windows availability. Those must be tested by the operator. Launching under `APP_ENV=production` automatically rejects unsafe settings before requests are served.

> Important: the bundled `Test-App.ps1` and historical test scripts send development-only headers. They are for local testing; do not use them as production authentication evidence.

## Deliberately limited features

The contextual YAML and SQL panels remain **read-only projections**; SQL is not a multi-engine transformation editor. Sample rows are restricted to the synthetic local demo; no external warehouse row preview. Bedrock, external connectors and cross-machine workers are implemented integration paths but not live-validated in this delivery. GraphRAG synthesis, penetration testing and enterprise workload scale need separate acceptance.
