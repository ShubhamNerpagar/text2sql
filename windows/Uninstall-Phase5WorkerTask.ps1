param([string]$TaskName='DIP-Phase5-Worker')
$ErrorActionPreference='Stop'
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed Phase 5 task: $TaskName"
