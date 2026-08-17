#Requires -Version 5.1
<#
.SYNOPSIS
  One-time Cloudflare Tunnel setup for IROS desk on sigq.in

.DESCRIPTION
  1) Ensures cloudflared is available
  2) Opens browser login (you must approve + select sigq.in zone)
  3) Creates tunnel "iros-desk" if missing
  4) Routes DNS calendar.sigq.in and sigq.in -> tunnel
  5) Writes %USERPROFILE%\.cloudflared\config.yml

.NOTES
  Prerequisites (you do once in the browser):
  - Add sigq.in to Cloudflare (Free plan)
  - At GoDaddy: change nameservers to the two Cloudflare NS values
  - Wait until Cloudflare shows domain Status = Active
#>

$ErrorActionPreference = "Stop"
$TunnelName = "iros-desk"
$CloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
$ConfigPath = Join-Path $CloudflaredDir "config.yml"
$Ingress = @(
  @{ Hostname = "calendar.sigq.in"; Service = "http://127.0.0.1:8088" },
  @{ Hostname = "sigq.in"; Service = "http://127.0.0.1:3000" }
)

function Refresh-Path {
  $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  $combined = @()
  if ($machinePath) { $combined += $machinePath -split ';' | Where-Object { $_ } }
  if ($userPath) { $combined += $userPath -split ';' | Where-Object { $_ } }
  $env:Path = ($combined | Select-Object -Unique) -join ';'
}

function Install-Cloudflared {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "cloudflared not found and winget is unavailable. Install Cloudflare Tunnel manually from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation or run: winget install Cloudflare.cloudflared"
  }

  Write-Host "cloudflared not found. Installing via winget..." -ForegroundColor Yellow
  & winget install --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements --silent
  if ($LASTEXITCODE -ne 0) {
    throw "cloudflared installation failed via winget. Install manually with: winget install Cloudflare.cloudflared"
  }

  Refresh-Path
}

function Find-Cloudflared {
  $candidates = @(
    (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:ProgramFiles\cloudflared\cloudflared.exe",
    "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
  ) | Where-Object { $_ -and (Test-Path $_) }
  if (-not $candidates) {
    Install-Cloudflared
    $candidates = @(
      (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
      "$env:ProgramFiles\cloudflared\cloudflared.exe",
      "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
  }
  if (-not $candidates) {
    throw "cloudflared still not found after installation. Check PATH or install manually with: winget install Cloudflare.cloudflared"
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
Write-Host "=== STEP 3: DNS routes ===" -ForegroundColor Yellow
foreach ($route in $Ingress) {
  Write-Host "Routing $($route.Hostname) -> $TunnelName"
  & $cf tunnel route dns $TunnelName $route.Hostname
  if ($LASTEXITCODE -ne 0) {
    Write-Host "DNS route command returned non-zero. If record already exists, you can continue." -ForegroundColor Yellow
  }
}

Write-Host ""
Write-Host "=== STEP 4: Write config.yml ===" -ForegroundColor Yellow
# YAML needs forward slashes or escaped backslashes; use forward slashes for cloudflared on Windows
$credPosix = $credFile -replace '\\', '/'
$configLines = @(
  "tunnel: $TunnelName",
  "credentials-file: $credPosix",
  "",
  "ingress:"
)
foreach ($route in $Ingress) {
  $configLines += "  - hostname: $($route.Hostname)"
  $configLines += "    service: $($route.Service)"
}
$configLines += "  - service: http_status:404"
$config = $configLines -join [Environment]::NewLine
Set-Content -Path $ConfigPath -Value $config -Encoding UTF8
Write-Host "[OK] Wrote $ConfigPath" -ForegroundColor Green
Write-Host $config

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Setup complete"
Write-Host "========================================" -ForegroundColor Green
Write-Host "1. Start IROS:  config\startup\start_app.bat"
Write-Host "2. Start tunnel: config\startup\start-tunnel.bat"
Write-Host "3. Open: https://sigq.in"
Write-Host "4. Calendar: https://calendar.sigq.in"
Write-Host ""
Write-Host "Optional: Cloudflare Zero Trust -> Access -> protect sigq.in/calendar.sigq.in with email login."
Write-Host ""
