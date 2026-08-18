# Pack live Docker volume JSON into config/docker/desk-state/seed for the Hub state image.
# Source of truth is /app/state (and EOD under /app/backend/app/data/eod), not the git tree.
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Seed = Join-Path $Root "config\docker\desk-state\seed"
New-Item -ItemType Directory -Force -Path $Seed | Out-Null

$names = @(
    "intraday_session.json",
    "swing_session.json",
    "last_market_snapshot.json",
    "fixed_trade_plan.json",
    "alert_history.json",
    "trade_api_snapshot.json"
)

Get-ChildItem -Path $Seed -File -Filter "*.json" -ErrorAction SilentlyContinue |
    Remove-Item -Force
$eodSeed = Join-Path $Seed "eod"
if (Test-Path -LiteralPath $eodSeed) {
    Remove-Item -LiteralPath $eodSeed -Recurse -Force
}

$tmp = Join-Path $env:TEMP ("iros-pack-state-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Copy-VolumeState {
    param([string]$Dest)
    $cid = (docker ps -aq -f "name=iros-market-api").Trim()
    if ($cid) {
        docker cp "${cid}:/app/state/." $Dest
        if ($LASTEXITCODE -ne 0) { throw "docker cp /app/state failed." }
        $eodDest = Join-Path $Dest "eod"
        New-Item -ItemType Directory -Force -Path $eodDest | Out-Null
        docker cp "${cid}:/app/backend/app/data/eod/." $eodDest
        return
    }
    Write-Host "  iros-market-api missing - packing compose project volumes"
    $stateVol = (docker volume ls -q | Select-String -Pattern "iros-desk-state$").Line
    $dataVol = (docker volume ls -q | Select-String -Pattern "iros-backend-data$").Line
    if (-not $stateVol) { throw "named volume iros-desk-state not found." }
    docker run --rm -v "${stateVol}:/state" -v "${Dest}:/out" alpine:3.21 sh -c "cp -a /state/. /out/"
    if ($LASTEXITCODE -ne 0) { throw "volume pack of $stateVol failed." }
    $eodDest = Join-Path $Dest "eod"
    New-Item -ItemType Directory -Force -Path $eodDest | Out-Null
    if ($dataVol) {
        docker run --rm -v "${dataVol}:/data" -v "${eodDest}:/out" alpine:3.21 sh -c "if [ -d /data/eod ]; then cp -a /data/eod/. /out/; fi"
    }
}

try {
    Copy-VolumeState $tmp
} finally {
    # keep $tmp until copied into seed
}

$packed = @()
foreach ($name in $names) {
    $src = Join-Path $tmp $name
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Host "  skip $name (missing on volume)"
        continue
    }
    Copy-Item -LiteralPath $src -Destination (Join-Path $Seed $name) -Force
    $len = (Get-Item -LiteralPath $src).Length
    $packed += @{ name = $name; bytes = $len }
    $kb = [Math]::Round($len / 1024.0, 1)
    Write-Host "  packed $name ($kb KB)"
}

$tmpEod = Join-Path $tmp "eod"
if (Test-Path -LiteralPath $tmpEod) {
    New-Item -ItemType Directory -Force -Path $eodSeed | Out-Null
    Copy-Item -Path (Join-Path $tmpEod "*") -Destination $eodSeed -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  packed eod/"
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

$manifest = [ordered]@{
    packedAtUtc = [DateTime]::UtcNow.ToString("o")
    host        = $env:COMPUTERNAME
    source      = "docker-volume"
    files       = $packed
}
$manifestPath = Join-Path $Seed "manifest.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
$count = $packed.Count
Write-Host "  wrote manifest.json ($count files)"

if ($packed.Count -eq 0) {
    Write-Host "[WARN] No desk JSON on the Docker volume - Hub state image will be empty seed."
}
