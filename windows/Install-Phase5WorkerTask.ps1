param([string]$TaskName='DIP-Phase5-Worker')
$ErrorActionPreference='Stop'
$Root=Split-Path $PSScriptRoot -Parent
$Script=Join-Path $PSScriptRoot 'Start-Phase5Worker.ps1'
$Action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $Script) -WorkingDirectory $Root
$Trigger=New-ScheduledTaskTrigger -AtStartup
$Settings=New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 365) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Data Intelligence Platform Phase5 durable worker; local-host SQLite queue' -Force | Out-Null
Write-Host "Registered startup task: $TaskName. Configure the run-as account and permissions to access the installation and state folders." -ForegroundColor Yellow
