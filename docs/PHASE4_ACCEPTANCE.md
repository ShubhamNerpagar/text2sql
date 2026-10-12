# Phase 4 acceptance — Test and Use Ontology

## Scope and honest status

Phase 4 introduces a **separate opt-in, governance-preserving consumption layer** over the Phase 3 review ontology. Existing `/api/query`, legacy `/api/mcp`, and report/render endpoints remain unchanged, so this build **does not represent a production migration of all Ask/BI features**. It is a locally exercised Windows-native development build with a Windows acceptance script. Real Windows EC2, AWS Bedrock, Athena, PostgreSQL, Snowflake and Databricks have not been acceptance-tested.

### User-facing workspaces

- **Governed Ask + BI:** release-pinned semantic questions, deterministic aggregate planning, evidence citations and an offline KPI widget.
- **Plan Lab:** transparent read-only aggregate SQL plan preview with source/release/ontology/evidence digests.
- **Golden Tests:** explicit `allow`/`reject` golden questions, pinned object identity, deterministic uppercase/spacing fuzz cases and unknown-concept mutation controls; per-run scores stored durably.
- **Ontology Releases:** promote immutable Phase 3 certified snapshots. Documentation-only branches support optimistic versions, compare/diff, independent SME review and immutable Phase 4 release publication. Executable semantic changes must go back through Phase 3, not through a branch patch.
- **Impact + Agents:** downstream ontology dependency tracing and a guarded read-only tool registry with request invocation; opt-in `/api/phase4/mcp` JSON-RPC `initialize`, `tools/list`, `tools/call` adapter.

### Trust invariants

1. The source Phase 3 release digest must match its pinned immutable source objects.
2. Each release object must still be **certified, on the same version, within workspace scope**, and supported by passing **current** Phase 2 profiles/contracts/relationships and Phase 3 diagnostics. Stale evidence blocks plans and execution.
3. No arbitrary SQL, SQL joins, row scans, writes, shell access or arbitrary tool names. `COUNT(*)` for entities/events; `SUM`, `AVG`, `MIN`, `MAX` for schema-confirmed numeric measures. Identifiers are taken from the exact Phase 1 allowlist.
4. **Execution is available only for the bundled Contoso connector** and must be explicitly requested. For Athena, PostgreSQL, Snowflake and Databricks, Phase 4 plans are preview-only pending connector-specific evaluation and production safeguards.
5. Access to Phase 4 API requires the same unrestricted semantic reviewer + workspace permissions as Phase 3; only publisher roles can promote/release changes. Developer-supplied identity headers must be disabled in production, with verified ALB/OIDC enforced.
6. Retrieval is **deterministic hierarchical lexical retrieval** (physical domain → certified objects → provenance fingerprints), not a trained graph model, embedding similarity benchmark, LLM narrative or production GraphRAG service. Unsupported/ambiguous matches fail closed.
7. A golden test records **planning behavior**, not ground truth accuracy on unseen real queries. Fuzz/mutation coverage is constrained and does not establish model safety for broad natural language.

### APIs

All require a `workspace` query parameter.

| Operation | API |
| --- | --- |
| Overview/releases | `GET /api/phase4/overview`, `GET /api/phase4/releases` |
| Promote Phase 3 snapshot | `POST /api/phase4/releases/promote` |
| Hierarchical retrieval | `GET /api/phase4/retrieve` |
| Semantic planning | `POST /api/phase4/plan` |
| Governed Ask/BI | `POST /api/phase4/ask`, `POST /api/phase4/bi` |
| Golden cases/runs | `GET/POST /api/phase4/golden/cases`, `GET /api/phase4/golden/runs`, `POST /api/phase4/golden/run` |
| Downstream impact | `GET /api/phase4/impact` |
| Branches | `GET/POST /api/phase4/branches`, `/branches/{id}/compare`, `/patch`, `/review`, `/publish` |
| Agent tools + MCP JSON-RPC adapter | `GET /api/phase4/agent/tools`, `POST /api/phase4/agent/call`, `POST /api/phase4/mcp` |
| Audit | `GET /api/phase4/audit` |

### Reproducing tests

```powershell
.\windows\Install-App.ps1
.\windows\Start-App.ps1
# In a second PowerShell session
.\windows\Test-Phase4.ps1
.\.venv\Scripts\python.exe -m pytest -q
```

The Windows smoke exercises a new isolated workspace and real 10,000-order Contoso queries. On Linux/CI with Playwright and Chromium installed, `python tools/smoke_phase4_chromium.py` runs UI screens against a real in-process FastAPI app without a network-dependent live browser; screenshots go into `validation_screenshots/`.

### Deferred to external acceptance / Phase 5

True native Windows/EC2 and production IAM tests; connector-specific SQL dialect, performance and billing/quotas; production MCP streamable HTTP/SSE transport compliance; Bedrock-driven interpretation with prompt-injection and authorization evaluation; enterprise concurrency and atomic DynamoDB compare-and-swap; federated search and production query execution. Do not claim these as completed.
