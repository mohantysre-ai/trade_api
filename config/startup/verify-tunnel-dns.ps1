#Requires -Version 5.1
# Verify public tunnel hostnames resolve (local ISP + Cloudflare 1.1.1.1).

$ErrorActionPreference = "Continue"
$Hostnames = @("sigq.in", "calendar.sigq.in", "job.sigq.in", "mantra.sigq.in")

function Test-Doh($name) {
  try {
    $uri = "https://cloudflare-dns.com/dns-query?name=$name&type=A"
    $r = Invoke-RestMethod -Uri $uri -Headers @{ Accept = "application/dns-json" }
    return ($r.Status -eq 0 -and $r.Answer)
  } catch {
    return $false
  }
}

function Test-Local($name) {
  try {
    $r = Resolve-DnsName -Name $name -Type A -ErrorAction Stop
    return [bool]$r
  } catch {
    return $false
  }
}

$failedLocal = @()
Write-Host "Tunnel DNS check" -ForegroundColor Cyan
foreach ($h in $Hostnames) {
  $local = Test-Local $h
  $doh = Test-Doh $h
  $mark = if ($local -and $doh) { "OK" } elseif ($doh) { "LOCAL_STALE" } else { "MISSING" }
  $color = switch ($mark) { "OK" { "Green" } "LOCAL_STALE" { "Yellow" } default { "Red" } }
  Write-Host ("  {0,-22} local={1} cloudflare={2}  [{3}]" -f $h, $local, $doh, $mark) -ForegroundColor $color
  if (-not $local -and $doh) { $failedLocal += $h }
}

if ($failedLocal.Count -gt 0) {
  Write-Host ""
  Write-Host "Cloudflare has the record; your ISP DNS is stale (negative cache)." -ForegroundColor Yellow
  Write-Host "Fix: set adapter DNS to 1.1.1.1, or run fix-tunnel-dns-local.bat as Administrator." -ForegroundColor Yellow
  exit 1
}
exit 0
