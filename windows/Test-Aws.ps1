$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
. (Join-Path $PSScriptRoot "Load-Env.ps1")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run .\windows\Install-App.ps1 first." }
& $Python scripts\aws_acceptance.py
exit $LASTEXITCODE
