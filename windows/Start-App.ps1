param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [int]$Workers = 1,
    [switch]$NoBrowser,
    [switch]$LogToFile
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
. (Join-Path $PSScriptRoot "Load-Env.ps1")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Virtual environment not found. Run .\windows\Install-App.ps1 first." }

if ($env:APP_ENV -eq 'production') {
    if (-not $NoBrowser) { $NoBrowser = $true }
    & $Python (Join-Path $Root 'scripts\production_preflight.py') --require-production
    if ($LASTEXITCODE -ne 0) { throw 'Production preflight failed. Review configuration and deployment checklist.' }
    if ($BindHost -eq '0.0.0.0') {
        Write-Warning 'Binding all interfaces. Restrict inbound Windows EC2 security group traffic to your ALB security group only.'
    }
} elseif ($BindHost -eq '0.0.0.0') {
    throw 'Development mode cannot bind all interfaces. Use the default loopback host.'
}

New-Item -ItemType Directory -Force -Path "logs","state" | Out-Null

if (-not $NoBrowser -and $BindHost -in @('127.0.0.1','localhost','0.0.0.0')) {
    Start-Process "http://127.0.0.1:$Port" | Out-Null
}

Write-Host "Starting Data Intelligence Platform on port $Port" -ForegroundColor Cyan
Write-Host "Local URL: http://127.0.0.1:$Port" -ForegroundColor Green

$uvicornArgs = @('-m','uvicorn','app.main:app','--host',$BindHost,'--port',"$Port",'--workers',"$Workers",'--no-proxy-headers')
if ($LogToFile) {
    $log = Join-Path $Root 'logs\app.log'
    $err = Join-Path $Root 'logs\app-error.log'
    foreach ($f in @($log,$err)) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 20MB) {
            $backup = "$f.1"
            if (Test-Path $backup) { Remove-Item $backup -Force }
            Move-Item $f $backup -Force
        }
    }
    & $Python @uvicornArgs 1>> $log 2>> $err
} else {
    & $Python @uvicornArgs
}
exit $LASTEXITCODE
