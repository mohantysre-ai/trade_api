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

foreach ($entry in @(
    @{ Volume = "iros-desk-state"; Folder = "state" },
    @{ Volume = "iros-backend-data"; Folder = "data" },
    @{ Volume = "iros-eod-archive"; Folder = "archive" }
)) {
    $source = Join-Path $Root "config\docker\desk-state\seed\$($entry.Folder)"
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing staged $source - pack-desk-state.ps1 must succeed first." }
    $archive = Join-Path $Volumes "$($entry.Volume).tar.gz"
    tar -czf $archive -C $source .
    if ($LASTEXITCODE -ne 0) { throw "Failed to pack staged $($entry.Volume)" }
    $kb = [Math]::Round((Get-Item -LiteralPath $archive).Length / 1024.0, 1)
    Write-Host "  packed volumes/$($entry.Volume).tar.gz ($kb KB)"
}

@(
    "bundleVersion=1",
    "createdAt=$((Get-Date).ToUniversalTime().ToString('o'))",
    "gitCommit=$(git rev-parse HEAD)",
    "composeProject=sigq"
) | Set-Content (Join-Path $Seed "manifest.txt")
Write-Host "  wrote manifest.txt"
