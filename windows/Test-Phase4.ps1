param([string]$BaseUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference='Stop'
$work='phase4-windows-'+(Get-Date -Format 'yyyyMMddHHmmss')
$author=@{'X-User'='windows-p4-author';'X-Roles'='semantic_admin'}
$steward=@{'X-User'='windows-p4-steward';'X-Roles'='semantic_admin'}
function Check([bool]$ok,[string]$message){if(-not $ok){throw "[FAILED] $message"}; Write-Host "[PASS] $message" -ForegroundColor Green}
function GetData([string]$endpoint,$who=$author){Invoke-RestMethod -Uri "$BaseUrl$endpoint" -Headers $who -TimeoutSec 120}
function PostData([string]$endpoint,$payload,$who=$author){$json=ConvertTo-Json -InputObject $payload -Depth 25 -Compress;Invoke-RestMethod -Uri "$BaseUrl$endpoint" -Method Post -Headers $who -Body $json -ContentType 'application/json' -TimeoutSec 120}
Check ((GetData '/api/health').version -in @('8.3.0')) 'Correct Phase 4 application version'
$scope=@{scope_id="$work-scope";workspace_id=$work;source_id='contoso';display_name='Phase 4 Windows Acceptance';tables=@(@{database='contoso_demo';table='Orders'})}
PostData '/api/phase1/scopes' $scope|Out-Null
PostData "/api/phase1/scopes/$work-scope/generate" @{}|Out-Null
$assets=GetData "/api/phase2/overview?workspace=$work"
$asset=$assets.assets|Where-Object {$_.table -eq 'Orders'}|Select-Object -First 1
Check ($null -ne $asset) 'Phase 1 scope discovery and workspace creation'
$p=PostData "/api/phase2/profiles?workspace=$work" @{asset_id=$asset.asset_id;tier='standard';max_columns=200}
Check ($p.status -eq 'complete' -and $p.row_count -eq 10000) 'Phase 2 measured 10,000 Contoso orders'
PostData "/api/phase2/contracts/$($asset.asset_id)?workspace=$work" @{owner='local steward'}|Out-Null
PostData "/api/phase2/contracts/$($asset.asset_id)/review?workspace=$work" @{decision='reviewed';note='Physical contract reviewed'}|Out-Null
$contract=PostData "/api/phase2/contracts/$($asset.asset_id)/review?workspace=$work" @{decision='certified';note='Profile and schema certified'}
Check ($contract.status -eq 'certified') 'Phase 2 independently reviewed contract'
$o=PostData "/api/phase3/objects?workspace=$work" @{kind='entity';label='Orders';description='Business orders';binding=@{asset_id=$asset.asset_id;columns=@('OrderKey')}}
$o=PostData "/api/phase3/objects/$($o.object_id)/review?workspace=$work" @{decision='reviewed';note='Business semantics reviewed';expected_version=$o.version}
$o=PostData "/api/phase3/objects/$($o.object_id)/review?workspace=$work" @{decision='certified';note='Independent evidence certification';expected_version=$o.version} $steward
Check ($o.status -eq 'certified') 'Phase 3 independent ontology certification'
PostData "/api/phase3/releases?workspace=$work" @{version='smoke-1';note='Reviewed stable ontology source'} $steward|Out-Null
$release=PostData "/api/phase4/releases/promote?workspace=$work" @{version='smoke-1'}
Check ($release.release_id -eq 'p3-smoke-1') 'Phase 4 immutable pinned semantic release'
$ask=PostData "/api/phase4/ask?workspace=$work" @{release_id=$release.release_id;question='Count Orders';object_id=$o.object_id;execute=$true}
Check ($ask.executed -and $ask.value -eq 10000) 'Grounded single-aggregate offline execution'
$bi=PostData "/api/phase4/bi?workspace=$work" @{release_id=$release.release_id;question='Count Orders';object_id=$o.object_id;execute=$true}
Check ($bi.series[0].value -eq 10000) 'Release-pinned BI KPI rendering'
PostData "/api/phase4/golden/cases?workspace=$work" @{release_id=$release.release_id;question='Count Orders';object_id=$o.object_id;expected='allow'}|Out-Null
PostData "/api/phase4/golden/cases?workspace=$work" @{release_id=$release.release_id;question='Unrecognized nonsense';expected='reject'}|Out-Null
$suite=PostData "/api/phase4/golden/run?workspace=$work" @{release_id=$release.release_id;mutations=$true}
Check ($suite.status -eq 'passed' -and $suite.score -eq 100) 'Golden, fuzz and unknown-concept mutation gate'
$impact=GetData "/api/phase4/impact?workspace=$work&release_id=$($release.release_id)&object_id=$($o.object_id)"
Check ($impact.nodes.Count -ge 1) 'Release-aware impact analysis'
$mcp=PostData "/api/phase4/mcp?workspace=$work" @{jsonrpc='2.0';id=1;method='tools/list';params=@{}}
Check ($mcp.result.tools.Count -ge 4) 'MCP JSON-RPC governed tool list'
Write-Host "Phase 4 Windows smoke test PASSED ($work). Live AWS and warehouse data execution is not covered." -ForegroundColor Green
