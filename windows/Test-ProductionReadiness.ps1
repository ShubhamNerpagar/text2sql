param([switch]$CheckAws)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'Load-Env.ps1')
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Install the application first.' }
$argsList = @((Join-Path $Root 'scripts\production_preflight.py'),'--require-production')
if ($CheckAws) { $argsList += '--check-aws' }
& $Python @argsList
if ($LASTEXITCODE -ne 0) { throw 'Production readiness blocked. Resolve all failed checks.' }
Write-Host 'Configuration preflight passed. Complete manual environment acceptance before go-live.' -ForegroundColor Yellow
