<#
Drill phone access (Phase 8): let the phone reach Drill over Tailscale, and nobody else.

Run ONCE, in PowerShell opened with "Run as administrator", from the Drill folder:
    powershell -ExecutionPolicy Bypass -File tools\phone-firewall.ps1
Remove the rule again:
    powershell -ExecutionPolicy Bypass -File tools\phone-firewall.ps1 -Remove
Different port than PORT in .env (default 8765):
    powershell -ExecutionPolicy Bypass -File tools\phone-firewall.ps1 -Port 8765

What it does: one inbound Windows Firewall rule "Drill phone access (Tailscale)" that allows
TCP on the Drill port ONLY from Tailscale addresses (100.64.0.0/10 and fd7a:115c:a1e0::/48).
It changes nothing else. The Drill server itself also refuses every other address.
#>
param(
    [int]$Port = 0,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$RuleName = 'Drill phone access (Tailscale)'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Please run this in PowerShell opened with "Run as administrator".' -ForegroundColor Red
    exit 1
}

if ($Port -eq 0) {
    $Port = 8765
    $envFile = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*PORT\s*=\s*"?(\d+)"?\s*$') { $Port = [int]$Matches[1] }
        }
    }
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue

if ($Remove) {
    if ($existing) {
        $existing | Remove-NetFirewallRule
        Write-Host "Removed the firewall rule '$RuleName'." -ForegroundColor Green
    } else {
        Write-Host "There was no rule named '$RuleName'. Nothing changed."
    }
    exit 0
}

if ($existing) {
    $existing | Remove-NetFirewallRule   # replace our own rule (e.g. the port changed)
}
New-NetFirewallRule -DisplayName $RuleName `
    -Description 'Drill study app: phone access over Tailscale only. Created by tools\phone-firewall.ps1.' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
    -RemoteAddress @('100.64.0.0/10', 'fd7a:115c:a1e0::/48') `
    -Profile Any | Out-Null
Write-Host "Added: inbound TCP $Port allowed from Tailscale addresses only (100.64.0.0/10, fd7a:115c:a1e0::/48)." -ForegroundColor Green

# Windows "Block" rules win over "Allow" rules. If Windows ever asked about Python and the
# answer was Cancel/Block, a block rule for python.exe would stop the phone. Show them; change nothing.
$blocks = Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True -ErrorAction SilentlyContinue |
    Where-Object { ($_ | Get-NetFirewallApplicationFilter).Program -match 'python' }
if ($blocks) {
    Write-Host ''
    Write-Host 'Note: these inbound BLOCK rules for Python exist and would stop the phone:' -ForegroundColor Yellow
    $blocks | ForEach-Object { Write-Host ("  " + $_.DisplayName + "  (" + ($_ | Get-NetFirewallApplicationFilter).Program + ")") }
    Write-Host 'Open "Windows Defender Firewall with Advanced Security" > Inbound Rules to disable them if needed.'
}
