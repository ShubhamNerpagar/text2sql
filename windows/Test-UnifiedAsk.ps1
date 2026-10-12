# Requires the installed Python environment, including pytest and demo sample data.
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
$version = (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 15).version
if ($version -ne '8.3.0') { throw "Unexpected build version: $version" }
Write-Host "Unified Ask build $version is healthy" -ForegroundColor Green
$python = if (Test-Path '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
& $python -m pytest -q tests/test_advanced_governed_queries.py
if ($LASTEXITCODE -ne 0) { throw 'Unified Ask regression suite failed' }
Write-Host 'Unified Ask local regression passed (live AWS acceptance is separate)' -ForegroundColor Green
