param([string]$BaseUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Stop'
$workspace = 'phase3-smoke-' + (Get-Date -Format 'yyyyMMddHHmmss')
$headers = @{'X-User'='windows-phase3-author';'X-Roles'='semantic_admin'}
$reviewer = @{'X-User'='windows-phase3-reviewer';'X-Roles'='semantic_admin'}
function Check([bool]$Condition,[string]$Message) {
  if (-not $Condition) { throw "Phase 3 acceptance FAILED: $Message" }
  Write-Host "[PASS] $Message" -ForegroundColor Green
}
function GetData([string]$Path, $Who=$headers) {
  Invoke-RestMethod -Uri "$BaseUrl$Path" -Headers $Who -TimeoutSec 120
}
function PostData([string]$Path,$Payload,$Who=$headers) {
  $body=ConvertTo-Json -InputObject $Payload -Depth 25 -Compress
  Invoke-RestMethod -Uri "$BaseUrl$Path" -Method Post -Headers $Who -Body $body -ContentType 'application/json' -TimeoutSec 120
}
$health=GetData '/api/health'
Check ($health.version -in @('8.3.0')) 'Phase 3 package version'
$scope=@{scope_id="$workspace-scope";workspace_id=$workspace;display_name='Phase 3 Windows Acceptance';source_id='contoso';tables=@(
 @{database='contoso_demo';table='Orders'},@{database='contoso_demo';table='Customer'}
)}
PostData '/api/phase1/scopes' $scope | Out-Null
PostData "/api/phase1/scopes/$workspace-scope/generate" @{} | Out-Null
$overview=GetData "/api/phase2/overview?workspace=$workspace"
Check ($overview.assets.Count -eq 2) 'Reused exact Phase 1 table scope'
$asset=$overview.assets | Where-Object { $_.table -eq 'Orders' } | Select-Object -First 1
$profile=PostData "/api/phase2/profiles?workspace=$workspace" @{asset_id=$asset.asset_id;tier='standard';max_columns=200}
Check ($profile.status -eq 'complete' -and $profile.row_count -eq 10000) 'Measured Phase 2 aggregates'
$contract=PostData "/api/phase2/contracts/$($asset.asset_id)?workspace=$workspace" @{owner='windows-demo-data-steward'}
$contract=PostData "/api/phase2/contracts/$($asset.asset_id)/review?workspace=$workspace" @{decision='reviewed';note='Physical schema reviewed in smoke test'}
$contract=PostData "/api/phase2/contracts/$($asset.asset_id)/review?workspace=$workspace" @{decision='certified';note='Complete measured profile and stewardship verified'}
Check ($contract.status -eq 'certified') 'Phase 2 contract certified'
$proposal=PostData "/api/phase3/proposals?workspace=$workspace" @{}
Check ($proposal.created -ge 3) 'Phase 3 schema-based candidates generated'
$object=GetData "/api/phase3/objects?workspace=$workspace"
$entity=$object.objects | Where-Object { $_.kind -eq 'entity' -and $_.binding.asset_id -eq $asset.asset_id } | Select-Object -First 1
Check ($entity.status -eq 'draft') 'Inferred entity remains untrusted'
$compiler=GetData "/api/phase3/compile?workspace=$workspace&object_id=$($entity.object_id)"
Check ($compiler.results[0].blocking -eq 0) 'Compiler checks measured profile and certified contract'
$review=PostData "/api/phase3/objects/$($entity.object_id)/review?workspace=$workspace" @{decision='reviewed';note='Physical domain business semantics checked';expected_version=$entity.version}
$certified=PostData "/api/phase3/objects/$($entity.object_id)/review?workspace=$workspace" @{decision='certified';note='Independent reviewer verified evidence';expected_version=$review.version} $reviewer
Check ($certified.status -eq 'certified') 'Separate reviewer certifies entity'
foreach($mode in @('conceptual','logical','evidence','dependency')) {
  $graph=GetData "/api/phase3/graph?workspace=$workspace&mode=$mode"
  Check ($graph.nodes.Count -gt 0 -and $graph.mode -eq $mode) "$mode graph projection"
}
$ledger=GetData "/api/phase3/evidence?workspace=$workspace"
Check ($ledger.ledger.Count -ge $proposal.created) 'Evidence snapshots persisted'
$questions=GetData "/api/phase3/questions?workspace=$workspace"
Check ($null -ne $questions.questions) 'SME questions endpoint responds'
$release=PostData "/api/phase3/releases?workspace=$workspace" @{version='smoke-1';note='Independent evidence checks passed'}
Check ($release.certified_count -ge 1 -and $release.production_query_integration -eq $false) 'Review-only immutable release'
Write-Host "Phase 3 Windows smoke test PASSED ($workspace). Live AWS and warehouse connections are NOT tested." -ForegroundColor Green
