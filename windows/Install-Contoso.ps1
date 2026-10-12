param(
    [string]$ArchivePath,
    [string]$DatasetId = 'contoso_1m'
)
$ErrorActionPreference = 'Stop'
if ($ArchivePath) { $ArchivePath = (Resolve-Path $ArchivePath).Path }
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Run windows\Install-App.ps1 first.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-contoso.txt
if ($LASTEXITCODE -ne 0) { throw 'py7zr installation failed.' }
if ($ArchivePath) {
    & '.\.venv\Scripts\python.exe' scripts\import_contoso.py $ArchivePath --dataset-id $DatasetId
} else {
    & '.\.venv\Scripts\python.exe' scripts\install_contoso_official.py
    $DatasetId = 'contoso_official'
}
if ($LASTEXITCODE -ne 0) { throw 'Contoso installation failed.' }
Write-Host "Contoso installed; reload Catalog Explorer and select database $DatasetId." -ForegroundColor Green
