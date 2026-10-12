param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Load-Env.ps1")
if ($env:APP_ENV -eq "production") { throw "Direct test headers are disabled for production. Use Test-ProductionReadiness.ps1 and run authenticated tests through the ALB." }
$headers = @{ 'X-User'='windows-ec2-test'; 'X-Roles'='semantic_admin' }

function Check($Name, $Script) {
    try {
        $result = & $Script
        Write-Host "[PASS] $Name" -ForegroundColor Green
        return $result
    } catch {
        Write-Host "[FAIL] $Name - $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

$health = Check "Health endpoint" { Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 15 }
$ready = Check "Readiness endpoint responds" { Invoke-RestMethod -Uri "$BaseUrl/api/ready" -TimeoutSec 15 }
$bootstrap = Check "Authenticated bootstrap" { Invoke-RestMethod -Uri "$BaseUrl/api/bootstrap" -Headers $headers -TimeoutSec 15 }
$catalog = Check "Contoso catalog" { Invoke-RestMethod -Uri "$BaseUrl/api/phase1/catalog/contoso/catalogs" -Headers $headers -TimeoutSec 15 }
$demo = Check "Demo table discovery" { Invoke-RestMethod -Uri "$BaseUrl/api/phase1/catalog/contoso/tables?database=contoso_demo&schema=public" -Headers $headers -TimeoutSec 15 }
$scopes = Check "Saved catalog scopes" { Invoke-RestMethod -Uri "$BaseUrl/api/phase1/scopes" -Headers $headers -TimeoutSec 15 }
$sources = Check "Data-source health" { Invoke-RestMethod -Uri "$BaseUrl/api/data-sources/health" -Headers $headers -TimeoutSec 30 }

Write-Host ""
Write-Host "Application version: $($health.version)" -ForegroundColor Cyan
Write-Host "Readiness: $($ready.ready)" -ForegroundColor Cyan
Write-Host "Configured sources: $($ready.configured_sources -join ', ')" -ForegroundColor Cyan
Write-Host "Runtime workspaces: $($ready.workspaces.Count)" -ForegroundColor Cyan
$sources.sources | Format-Table id,configured,status -AutoSize

if (-not $ready.ready) {
    Write-Host "Readiness can remain false until a source is configured and a workspace is generated." -ForegroundColor Yellow
}
