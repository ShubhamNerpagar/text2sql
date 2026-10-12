# Phase 3 — Acceptance and boundaries

## Passed on this build host (Linux)

- 108 Python tests covering Phase 1 / Phase 2 / inherited features and new Phase 3 API/workflows.
- Python `compileall` and Node JavaScript syntax validation.
- Scope-isolated, typed ontology proposals across the embedded 10K-order Contoso synthetic dataset.
- Steward-controlled contract / independent ontology certification with version conflict and edit lifecycle checks.
- Immutable evidence snapshot hashes, checked compiler failures, SME decisions, four graph modes, cycle-safe dependencies, and review-only ontology releases.
- Cross-asset dependencies fail closed until Phase 2 aggregate join measurement and approval.
- Chromium DOM smoke with a Python/FastAPI TestClient fetch bridge (the sandbox disallows direct Chromium HTTP navigation). Verified object editor, Trust Engine, SME Review, 4 graph modes, and no console/view errors during test; 40 successful API calls.

## Not validated / not promised

- Windows PowerShell scripts have not been run on Windows Server / EC2 on this host. `windows/Test-Phase3.ps1` and the Windows GitHub Actions job perform these checks on Windows.
- Live IAM, Glue, Athena, Bedrock, PostgreSQL, Snowflake, Databricks or other production connector validation was not executed.
- Formal semantic SQL compilation and integration of Phase 3 certified object snapshots into Ask, BI, MCP or GraphRAG execution belongs to Phase 4. Existing legacy workflows are preserved, but Phase 3 trust labels are **not** automatically used by them.
- AI/SME semantic correctness still requires domain steward review; a schema- and aggregate-provenance gate is not a guarantee of business truth.
- State backend defaults to local JSON for desktop/single instance testing. Deploy a durable shared control store for multi-instance production.

## Startup on Windows

From the extracted folder in PowerShell (Python 3.12 x64):

```powershell
.\windows\Install-App.ps1
.\windows\Start-App.ps1
```

Then in a separate terminal:

```powershell
.\windows\Test-Phase2.ps1
.\windows\Test-Phase3.ps1
```

See README.md for identity settings, scope onboarding, application endpoints and acceptance details.
