# Pack backend/.env, Cloudflare credentials, and the live sigq_iros-* volumes into
# config/docker/runtime-private/seed for the private Hub image.
# Mirrors the payload scripts/export-runtime-bundle.ps1 used to put in the ZIP —
# same contents, different transport (a private Docker Hub image, not a file to copy).
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root

$Seed = Join-Path $Root "config\docker\runtime-private\seed"
$Secrets = Join-Path $Seed "secrets"
$Volumes = Join-Path $Seed "volumes"

if (-not (Test-Path "backend\.env")) { throw "Missing backend\.env - nothing to pack." }
if (-not (Test-Path "config\cloudflare\credentials.json")) { throw "Missing config\cloudflare\credentials.json - nothing to pack." }

if (Test-Path -LiteralPath $Seed) { Remove-Item -LiteralPath $Seed -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Secrets, $Volumes | Out-Null

Copy-Item "backend\.env" (Join-Path $Secrets "backend.env") -Force
Copy-Item "config\cloudflare\credentials.json" (Join-Path $Secrets "cloudflare-credentials.json") -Force
Write-Host "  packed secrets/backend.env"
Write-Host "  packed secrets/cloudflare-credentials.json"

$Stopped = $false
try {
    $running = docker compose ps --status running --services
    if ($running -match "market-api|ai-news") {
        docker compose stop market-api ai-news | Out-Null
        $Stopped = $true
    }
    foreach ($volume in @("iros-desk-state", "iros-backend-data", "iros-eod-archive")) {
        docker volume inspect "sigq_${volume}" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Missing Docker volume sigq_${volume}" }
        docker run --rm -v "sigq_${volume}:/source:ro" -v "${Volumes}:/backup" alpine:3.21 sh -c "tar czf /backup/${volume}.tar.gz -C /source ."
        if ($LASTEXITCODE -ne 0) { throw "Failed to pack volume $volume" }
        $kb = [Math]::Round((Get-Item (Join-Path $Volumes "$volume.tar.gz")).Length / 1024.0, 1)
        Write-Host "  packed volumes/$volume.tar.gz ($kb KB)"
    }
} finally {
    if ($Stopped) { docker compose start market-api ai-news | Out-Null }
}

@(
    "bundleVersion=1",
    "createdAt=$((Get-Date).ToUniversalTime().ToString('o'))",
    "gitCommit=$(git rev-parse HEAD)",
    "composeProject=sigq"
) | Set-Content (Join-Path $Seed "manifest.txt")
Write-Host "  wrote manifest.txt"