param(
    [int]$Port = 8000,
    [Parameter(Mandatory=$true)]
    [string[]]$RemoteAddress
)
$ErrorActionPreference = 'Stop'
# Supply ALB subnet CIDRs. Never expose the EC2 origin directly to the Internet.
if (-not $RemoteAddress -or ($RemoteAddress | Where-Object { $_ -in @('Any','*','0.0.0.0/0','::/0') })) {
    throw 'Specify narrow ALB subnet addresses/CIDRs with -RemoteAddress; broad inbound rules are prohibited.'
}
$ruleName = "Data Intelligence Platform TCP $Port"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Set-NetFirewallRule -DisplayName $ruleName -RemoteAddress $RemoteAddress -Enabled True -Action Allow
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress $RemoteAddress | Out-Null
}
Write-Host 'Scoped Windows firewall rule created/updated.' -ForegroundColor Green
Write-Host 'REQUIRED: the EC2 AWS security group must accept inbound traffic ONLY from the trusted ALB security group.' -ForegroundColor Yellow
