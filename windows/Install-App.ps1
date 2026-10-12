param(
    [string]$PythonExe = "python",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Invoke-Checked {
    param([string]$Exe, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE: $Exe $($Arguments -join ' ')" }
}

Write-Host "Data Intelligence Platform 8.4 - Windows native setup" -ForegroundColor Cyan

try {
    $version = & $PythonExe -c "import sys; print('.'.join(map(str,sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0) { throw "python failed" }
} catch {
    throw "Python was not found. Install 64-bit Python 3.12, select 'Add python.exe to PATH', then rerun this script."
}

$parts = $version.Trim().Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
    throw "Python 3.11+ is required. Python 3.12 x64 is recommended. Detected: $version"
}
Write-Host "Python $version detected" -ForegroundColor Green

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Invoke-Checked $PythonExe -m venv .venv
}
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
Invoke-Checked $VenvPython -m pip install --upgrade pip setuptools wheel
Invoke-Checked $VenvPython -m pip install -r requirements-windows.txt
if (-not $SkipTests) { Invoke-Checked $VenvPython -m pip install -r requirements-test.txt }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.windows.test.example" ".env"
    Write-Host "Created .env from the Windows EC2 test template." -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path "state","logs" | Out-Null

if (-not $SkipTests) {
    Write-Host "Running automated tests..." -ForegroundColor Cyan
    Invoke-Checked $VenvPython -m pytest -q tests --tb=short
}

Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next: edit .env, then run .\windows\Start-App.ps1"
