param(
    [int]$Port = 8000,
    [string]$TaskName = "DataIntelligencePlatform"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$script = Join-Path $PSScriptRoot "Start-App.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Port $Port -NoBrowser -LogToFile"
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument $arguments -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task '$TaskName' installed and started." -ForegroundColor Green
Write-Host "Logs: $Root\logs\app.log and app-error.log"
