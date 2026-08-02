#Requires -Version 5.1
<#
.SYNOPSIS
  One-time Cloudflare Tunnel setup for IROS desk on iros.sigq.in

.DESCRIPTION
  1) Ensures cloudflared is available
  2) Opens browser login (you must approve + select sigq.in zone)
  3) Creates tunnel "iros-desk" if missing
  4) Routes DNS iros.sigq.in -> tunnel
  5) Writes %USERPROFILE%\.cloudflared\config.yml

.NOTES
  Prerequisites (you do once in the browser):
  - Add sigq.in to Cloudflare (Free plan)
  - At GoDaddy: change nameservers to the two Cloudflare NS values
  - Wait until Cloudflare shows domain Status = Active
#>

$ErrorActionPreference = "Stop"
$TunnelName = "iros-desk"
$Hostname = "iros.sigq.in"
$LocalService = "http://127.0.0.1:3000"
$CloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
$ConfigPath = Join-Path $CloudflaredDir "config.yml"

function Find-Cloudflared {
  $candidates = @(
    (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:ProgramFiles\cloudflared\cloudflared.exe",
    "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
  ) | Where-Object { $_ -and (Test-Path $_) }
  if (-not $candidates) {
    throw "cloudflared not found. Install with: winget install Cloudflare.cloudflared"
  }
  return $candidates[0]
}

$cf = Find-Cloudflared
Write-Host "Using: $cf" -ForegroundColor Cyan
& $cf --version

New-Item -ItemType Directory -Force -Path $CloudflaredDir | Out-Null

Write-Host ""
Write-Host "=== STEP 1: Cloudflare login ===" -ForegroundColor Yellow
Write-Host "A browser window will open. Log in and authorize the tunnel for zone sigq.in."
Write-Host "If sigq.in is not Active in Cloudflare yet, finish GoDaddy nameserver change first."
Write-Host ""
$null = Read-Host "Press Enter to open Cloudflare login"

& $cf tunnel login
if ($LASTEXITCODE -ne 0) { throw "cloudflared tunnel login failed" }

$certPath = Join-Path $CloudflaredDir "cert.pem"
if (-not (Test-Path $certPath)) {
  throw "Login did not produce cert.pem at $certPath"
}
Write-Host "[OK] Logged in ($certPath)" -ForegroundColor Green

Write-Host ""
Write-Host "=== STEP 2: Create tunnel '$TunnelName' ===" -ForegroundColor Yellow
$existing = & $cf tunnel list 2>&1 | Out-String
$tunnelId = $null

if ($existing -match $TunnelName) {
  Write-Host "Tunnel already exists. Resolving ID..."
  $listJson = & $cf tunnel list --output json 2>$null
  if ($listJson) {
    $tunnels = $listJson | ConvertFrom-Json
    $match = $tunnels | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
    if ($match) { $tunnelId = $match.id }
  }
}

if (-not $tunnelId) {
  $createOut = & $cf tunnel create $TunnelName 2>&1 | Out-String
  Write-Host $createOut
  if ($createOut -match "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})") {
    $tunnelId = $Matches[1]
  }
  if (-not $tunnelId) {
    $listJson = & $cf tunnel list --output json
    $tunnels = $listJson | ConvertFrom-Json
    $match = $tunnels | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
    if ($match) { $tunnelId = $match.id }
  }
}

if (-not $tunnelId) { throw "Could not determine tunnel UUID for $TunnelName" }
Write-Host "[OK] Tunnel ID: $tunnelId" -ForegroundColor Green

$credFile = Join-Path $CloudflaredDir "$tunnelId.json"
if (-not (Test-Path $credFile)) {
  throw "Credentials file missing: $credFile"
}

Write-Host ""
Write-Host "=== STEP 3: DNS route $Hostname ===" -ForegroundColor Yellow
& $cf tunnel route dns $TunnelName $Hostname
if ($LASTEXITCODE -ne 0) {
  Write-Host "DNS route command returned non-zero. If record already exists, you can continue." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== STEP 4: Write config.yml ===" -ForegroundColor Yellow
# YAML needs forward slashes or escaped backslashes; use forward slashes for cloudflared on Windows
$credPosix = $credFile -replace '\\', '/'
$config = @"
tunnel: $TunnelName
credentials-file: $credPosix

ingress:
  - hostname: $Hostname
    service: $LocalService
  - service: http_status:404
"@
Set-Content -Path $ConfigPath -Value $config -Encoding UTF8
Write-Host "[OK] Wrote $ConfigPath" -ForegroundColor Green
Write-Host $config

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Setup complete"
Write-Host "========================================" -ForegroundColor Green
Write-Host "1. Start IROS:  config\startup\start_app.bat"
Write-Host "2. Start tunnel: config\startup\start-tunnel.bat"
Write-Host "3. Open: https://$Hostname"
Write-Host ""
Write-Host "Optional: Cloudflare Zero Trust -> Access -> protect $Hostname with email login."
Write-Host ""
