$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
. (Join-Path $PSScriptRoot "Load-Env.ps1")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
& $Python scripts\run_report_worker.py 1>> logs\report-worker.log 2>> logs\report-worker-error.log
exit $LASTEXITCODE
