param([string]$BaseUrl='http://127.0.0.1:8000',[string]$Workspace='', [string]$ReleaseId='')
$ErrorActionPreference='Stop'
$headers=@{'X-Roles'='semantic_admin'; 'X-User'='windows-test'}
$health=Invoke-RestMethod -Uri "$BaseUrl/api/health" -Headers $headers
if ($health.version -ne '8.3.0') { throw 'Unexpected application version' }
Write-Host "Application health passed: $($health.version)" -ForegroundColor Green
if (-not $Workspace -or -not $ReleaseId) {
    Write-Host 'Provide -Workspace and -ReleaseId for certified multi-table schema validation.' -ForegroundColor Yellow
    exit 0
}
$uri="$BaseUrl/api/phase4/advanced/schema?workspace=$([uri]::EscapeDataString($Workspace))&release_id=$([uri]::EscapeDataString($ReleaseId))"
$schema=Invoke-RestMethod -Uri $uri -Headers $headers
if (-not $schema.release_id -or $schema.assets.Count -lt 1) { throw 'No eligible certified objects in selected release' }
Write-Host "Advanced schema: $($schema.assets.Count) assets, $($schema.relationships.Count) currently approved joins" -ForegroundColor Green
Write-Host 'To execute a multi-table query, submit a validated structured_plan or invoke Bedrock using /api/phase4/advanced/ask.' -ForegroundColor Cyan
