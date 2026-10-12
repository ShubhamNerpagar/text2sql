param([string]$BaseUrl = "http://127.0.0.1:8000")
$ErrorActionPreference="Stop"
$headers=@{'X-User'='windows-phase2-smoke';'X-Roles'='semantic_admin'}
function Check([bool]$Condition,[string]$Message) { if (-not $Condition) { throw "Phase 2 acceptance failed: $Message" }; Write-Host "[PASS] $Message" -ForegroundColor Green }
function Post($Path,$Object) {
    $body=ConvertTo-Json -InputObject $Object -Depth 12 -Compress
    Invoke-RestMethod -Uri "$BaseUrl$Path" -Headers $headers -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 120
}
$health=Invoke-RestMethod -Uri "$BaseUrl/api/health" -Headers $headers
Check ($health.version -in @('8.3.0')) 'Phase 2 application version'
# This intentionally creates a reproducible non-production demo workspace.
$selection=@{scope_id='phase2-smoke-scope';workspace_id='phase2-smoke';display_name='Phase 2 Windows Smoke';source_id='contoso';tables=@(
    @{database='contoso_demo';table='Orders'},@{database='contoso_demo';table='Customer'},@{database='contoso_demo';table='Store'}
)}
$s=Post '/api/phase1/scopes' $selection
$g=Post '/api/phase1/scopes/phase2-smoke-scope/generate' @{}
Check ($g.tables_scanned -eq 3) 'Exact-scope workspace generated'
$over=Invoke-RestMethod -Uri "$BaseUrl/api/phase2/overview?workspace=phase2-smoke" -Headers $headers
Check ($over.assets.Count -eq 3) 'Phase 2 scoped assets'
$orders=$over.assets | Where-Object {$_.table -eq 'Orders'} | Select-Object -First 1
$prof=Post '/api/phase2/profiles?workspace=phase2-smoke' @{asset_id=$orders.asset_id;tier='standard'}
Check ($prof.row_count -eq 10000 -and $prof.status -eq 'complete') 'Measured 10,000 demo Orders'
$contract=Post "/api/phase2/contracts/$($orders.asset_id)?workspace=phase2-smoke" @{owner='demo-steward';description='Smoke-tested Orders contract'}
Check ($contract.status -eq 'draft') 'Contract draft created'
$rels=Invoke-RestMethod -Uri "$BaseUrl/api/phase2/relationships?workspace=phase2-smoke" -Headers $headers
$rel=$rels.relationships | Where-Object {$_.from_asset -eq $orders.asset_id -and $_.from_column -eq 'CustomerKey'} | Select-Object -First 1
Check (![string]::IsNullOrEmpty($rel.relationship_id)) 'Candidate relationship discovered'
$measured=Post "/api/phase2/relationships/$($rel.relationship_id)/validate?workspace=phase2-smoke" @{}
Check ($measured.evidence.coverage -eq 1 -and !$measured.trusted_for_queries) 'Relationship measured but not auto-trusted'
$rule=Post '/api/phase2/quality/rules?workspace=phase2-smoke' @{asset_id=$orders.asset_id;rule_type='row_count_min';threshold=10000}
$run=Post '/api/phase2/quality/run?workspace=phase2-smoke' @{}
Check ($run.passed -ge 1 -and $run.failed -eq 0) 'Data quality evidence passes'
$lineage=Invoke-RestMethod -Uri "$BaseUrl/api/phase2/lineage?workspace=phase2-smoke" -Headers $headers
Check ($lineage.nodes.Count -ge 5) 'Lineage graph built from scope and evidence'
Write-Host 'Phase 2 smoke test PASSED. This tests the bundled synthetic dataset, not live AWS/warehouse connectors.' -ForegroundColor Green
