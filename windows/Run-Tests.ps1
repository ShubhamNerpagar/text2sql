$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run .\windows\Install-App.ps1 first." }
& $Python -m pytest -q tests --tb=short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m compileall -q app scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "All Windows-native validation checks passed." -ForegroundColor Green
