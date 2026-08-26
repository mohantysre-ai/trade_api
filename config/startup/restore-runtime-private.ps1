# Pull smohanty010620/sigq-runtime-private, restore backend/.env, Cloudflare
# credentials, and the sigq_iros-* volumes from it, then remove the temp container.
# Counterpart to config/startup/pack-runtime-private.ps1. Requires `docker login`
# to an account with pull access to the private repo.
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root

$Image = "smohanty010620/sigq-runtime-private:latest"
$Container = "sigq-runtime-private-restore-" + [guid]::NewGuid().ToString("n").Substring(0, 8)
$Stage = Join-Path ([IO.Path]::GetTempPath()) ("sigq-runtime-private-" + [guid]::NewGuid())

Write-Host "[*] Pulling $Image ..."
docker pull $Image
if ($LASTEXITCODE -ne 0) { throw "docker pull failed - run 'docker login' first if the repo is private." }

New-Item -ItemType Directory -Force -Path $Stage | Out-Null
try {
    docker create --name $Container $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker create failed." }

    docker cp "${Container}:/runtime-private/secrets" (Join-Path $Stage "secrets") 2>&1 | Out-Null
    docker cp "${Container}:/runtime-private/volumes" (Join-Path $Stage "volumes") 2>&1 | Out-Null

    $envFile = Join-Path $Stage "secrets\backend.env"
    $cfFile = Join-Path $Stage "secrets\cloudflare-credentials.json"
    if (-not (Test-Path $envFile)) { throw "backend.env missing from image - was pack-runtime-private.ps1 run before pushing?" }
    if (-not (Test-Path $cfFile)) { throw "cloudflare-credentials.json missing from image." }

    New-Item -ItemType Directory -Force -Path "config\cloudflare" | Out-Null
    Copy-Item $envFile "backend\.env" -Force
    Copy-Item $cfFile "config\cloudflare\credentials.json" -Force
    Write-Host "[OK] Restored backend\.env and Cloudflare credentials."

    foreach ($volume in @("iros-desk-state", "iros-backend-data", "iros-eod-archive")) {
        $archive = Join-Path $Stage "volumes\$volume.tar.gz"
        if (-not (Test-Path $archive)) {
            Write-Host "  skip $volume (not in image)"
            continue
        }
        docker volume create --label com.docker.compose.project=sigq --label "com.docker.compose.volume=${volume}" "sigq_${volume}" | Out-Null
        docker run --rm -v "sigq_${volume}:/target" -v "$Stage\volumes:/backup:ro" alpine:3.21 sh -c "find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar xzf /backup/$volume.tar.gz -C /target"
        if ($LASTEXITCODE -ne 0) { throw "Failed to restore volume $volume" }
        Write-Host "  restored volume sigq_$volume"
    }
} finally {
    docker rm -f $Container 2>&1 | Out-Null
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] Runtime restored from $Image."