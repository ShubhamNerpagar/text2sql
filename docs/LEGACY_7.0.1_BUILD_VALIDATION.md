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
