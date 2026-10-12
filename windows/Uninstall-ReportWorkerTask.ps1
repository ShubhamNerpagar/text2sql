param([string]$TaskName = "DataIntelligenceReportWorker")
$ErrorActionPreference = "Stop"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Report worker task '$TaskName' removed." -ForegroundColor Green
} else {
    Write-Host "Report worker task '$TaskName' is not installed." -ForegroundColor Yellow
}
