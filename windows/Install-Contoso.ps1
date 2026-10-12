$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Run windows\Install-App.ps1 first.' }
& '.\.venv\Scripts\python.exe' -m pip install py7zr
if ($LASTEXITCODE -ne 0) { throw 'py7zr installation failed.' }
& '.\.venv\Scripts\python.exe' scripts\install_contoso_official.py
if ($LASTEXITCODE -ne 0) { throw 'Official Contoso installation failed.' }
Write-Host 'Contoso installed; restart app and select database contoso_official.' -ForegroundColor Green
