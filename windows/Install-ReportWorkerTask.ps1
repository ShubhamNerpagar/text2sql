param(
    [int]$EveryMinutes = 5,
    [string]$TaskName = "DataIntelligenceReportWorker"
)
$ErrorActionPreference = "Stop"
if ($EveryMinutes -lt 1) { throw "EveryMinutes must be >= 1." }
$Root = Split-Path $PSScriptRoot -Parent
$runner = Join-Path $PSScriptRoot "Run-ReportWorker.ps1"
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Report worker task '$TaskName' installed; runs every $EveryMinutes minute(s)." -ForegroundColor Green
