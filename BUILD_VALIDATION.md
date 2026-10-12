> Historical report from the original attachment. For the updated release, see [VALIDATION_8.4.0.md](VALIDATION_8.4.0.md).

# Build Validation — Windows EC2 Native Edition

This edition is intentionally Docker-free. It runs directly on Windows Server using Python/Uvicorn.

Validation performed while assembling the package:

- automated pytest regression suite;
- Python compilation;
- JavaScript syntax check;
- JSON/YAML parse checks;
- live Uvicorn startup/health smoke test;
- concurrent HTTP health requests;
- ZIP integrity check.

A true Windows execution of the PowerShell scripts must run on the target Windows EC2 host or the included GitHub Actions `windows-latest` workflow. Real Athena/Glue/S3/IAM validation requires the target AWS account and is performed with `windows\\Test-Aws.ps1` plus the runtime onboarding flow.

## Phase 3 addendum

108 local pytest cases passed, Python compilation passed, and `node --check app/static/assets/app.js` passed. Chromium visual/interaction checks passed for the four Phase 3 tabs and draft editing with 40 successful API calls via a FastAPI TestClient fetch bridge (direct Chromium HTTP navigation was restricted by the sandbox). The release was not executed on Windows EC2 or with live cloud connections; see `docs/PHASE3_ACCEPTANCE.md` and `PHASE3_VALIDATION.json`.
