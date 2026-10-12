param([string]$TaskName = "DataIntelligencePlatform")
$ErrorActionPreference = "Stop"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task '$TaskName' removed." -ForegroundColor Green
} else {
    Write-Host "Scheduled task '$TaskName' is not installed." -ForegroundColor Yellow
}
