param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Start-Phase5Worker.ps1') @Arguments
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { exit $LASTEXITCODE }
