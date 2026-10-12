param(
    [switch]$Once,
    [double]$PollSeconds = 2,
    [string]$WorkerId = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
. (Join-Path $PSScriptRoot 'Load-Env.ps1')
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Install the app first with .\windows\Install-App.ps1' }
$Args = @('-m','app.workers.phase5_worker','--poll',"$PollSeconds")
if ($Once) { $Args += '--once' }
if ($WorkerId) { $Args += @('--worker-id',$WorkerId) }
Write-Host "Background worker starting (queue backend: $($env:JOB_QUEUE_BACKEND))" -ForegroundColor Cyan
& $Python @Args
exit $LASTEXITCODE
