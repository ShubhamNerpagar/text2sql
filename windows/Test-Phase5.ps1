param([string]$BaseUrl='http://127.0.0.1:8000', [string]$Workspace='')
$ErrorActionPreference='Stop'
$BaseUrl=$BaseUrl.TrimEnd('/')
function Check($ok,$msg){if(-not $ok){throw "🚨 $msg"};Write-Host "✅ $msg" -ForegroundColor Green}
$headers=@{'X-User'='phase5-test';'X-Roles'='semantic_admin'}
$h=Invoke-RestMethod "$BaseUrl/api/health" -Headers $headers
Check ($h.ok -and $h.version -eq '8.3.0') 'Phase 5 healthy application'
$spec=Invoke-RestMethod "$BaseUrl/api/openapi.json" -Headers $headers
Check ([bool]$spec.paths.'/api/phase5/jobs') 'Phase 5 job endpoints registered'
Check ([bool]$spec.paths.'/api/phase5/federation') 'Federation endpoints registered'
Check ([bool]$spec.paths.'/api/phase5/benchmarks') 'Benchmark endpoints registered'
if ($Workspace) {
 $w=[Uri]::EscapeDataString($Workspace)
 $v=Invoke-RestMethod "$BaseUrl/api/phase5/overview?workspace=$w" -Headers $headers
 Check ($v.worker_backend -eq 'sqlite_single_host') 'Phase 5 workspace and worker backend'
 $payload=@{task='search_snapshot';payload=@{};idempotency_key=('accept-'+[Guid]::NewGuid().ToString('N'))}|ConvertTo-Json -Depth 5
 $j=Invoke-RestMethod "$BaseUrl/api/phase5/jobs?workspace=$w" -Method Post -Headers $headers -ContentType 'application/json' -Body $payload
 Check ($j.status -eq 'queued') 'Job persists to queue'
 Write-Host "Queued $($j.id). Start .\windows\Start-Phase5Worker.ps1 and inspect Job Center for completion."
}
Write-Host 'Phase 5 HTTP smoke complete. Live Windows EC2, connector parity and multi-node failover remain separate acceptance gates.'
