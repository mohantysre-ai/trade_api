#Requires -Version 5.1
# Re-provision tunnel DNS and patch hosts when ISP resolver still returns NXDOMAIN.
# Run as Administrator for hosts-file updates.

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Cf = @(
  (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
  "$env:ProgramFiles\cloudflared\cloudflared.exe",
  "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $Cf) { throw "cloudflared not found" }

$Tunnel = "iros-desk"
$Routes = @("calendar.sigq.in", "job.sigq.in", "mantra.sigq.in", "sigq.in")
$HostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$HostsMarker = "# iros-desk tunnel (auto)"

foreach ($routeHost in $Routes) {
  Write-Host "DNS route: $routeHost" -ForegroundColor Cyan
  & $Cf tunnel route dns -f $Tunnel $routeHost
}

& (Join-Path $PSScriptRoot "prepare-docker-tunnel.ps1") | Out-Null

$needsHosts = @()
foreach ($routeHost in @("job.sigq.in", "mantra.sigq.in", "calendar.sigq.in")) {
  try {
    $null = Resolve-DnsName -Name $routeHost -Type A -ErrorAction Stop
  } catch {
    $uri = "https://cloudflare-dns.com/dns-query?name=$routeHost&type=A"
    $doh = Invoke-RestMethod -Uri $uri -Headers @{ Accept = "application/dns-json" }
    if ($doh.Status -eq 0 -and $doh.Answer) {
      $ip = ($doh.Answer | Where-Object { $_.type -eq 1 } | Select-Object -First 1).data
      if ($ip) { $needsHosts += [pscustomobject]@{ Host = $routeHost; Ip = $ip } }
    }
  }
}

if ($needsHosts.Count -eq 0) {
  Write-Host "[OK] All tunnel hostnames resolve locally." -ForegroundColor Green
  exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
  Write-Host "[WARN] Local DNS still stale for: $($needsHosts.Host -join ', ')" -ForegroundColor Yellow
  Write-Host "       Re-run this script as Administrator to add temporary hosts entries," -ForegroundColor Yellow
  Write-Host "       or set DNS to 1.1.1.1 on your network adapter." -ForegroundColor Yellow
  exit 1
}

$lines = @()
if (Test-Path $HostsPath) {
  $skipBlock = $false
  foreach ($line in Get-Content $HostsPath) {
    if ($line -match [regex]::Escape($HostsMarker)) {
      $skipBlock = $true
      continue
    }
    if ($skipBlock) {
      if ($line -match '\.sigq\.in\s*$') { continue }
      $skipBlock = $false
    }
    if ($line -match '^\d+\.\d+\.\d+\.\d+\s+\S+\.sigq\.in\s*$') { continue }
    $lines += $line
  }
}
$lines += $HostsMarker
foreach ($row in $needsHosts) {
  $lines += "$($row.Ip)`t$($row.Host)"
}
Set-Content -Path $HostsPath -Value $lines -Encoding ASCII
ipconfig /flushdns | Out-Null
Write-Host "[OK] Patched hosts for: $($needsHosts.Host -join ', ')" -ForegroundColor Green
Write-Host "     Remove the '$HostsMarker' block when your ISP DNS catches up." -ForegroundColor DarkGray
