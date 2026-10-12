param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Uninstall-Phase5WorkerTask.ps1') @Arguments
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { exit $LASTEXITCODE }
