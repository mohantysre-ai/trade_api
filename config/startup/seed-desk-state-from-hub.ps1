# Pull iros-desk-state and copy JSON into the running stack's named volumes.
# Does not write desk JSON into the git working tree.
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Image = "smohanty010620/iros-desk-state:latest"
$names = @(
    "intraday_session.json",
    "swing_session.json",
    "last_market_snapshot.json",
    "fixed_trade_plan.json",
    "alert_history.json",
    "trade_api_snapshot.json"
)

Write-Host "[*] Pulling $Image ..."
docker pull $Image
if ($LASTEXITCODE -ne 0) {
    throw "docker pull $Image failed - run push-docker-hub.bat on the desk that has the live JSON."
}

$cid = (docker create $Image).Trim()
if (-not $cid) { throw "docker create $Image failed." }
$tmp = Join-Path $env:TEMP ("iros-desk-state-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    docker cp "${cid}:/desk-state/." $tmp
    if ($LASTEXITCODE -ne 0) { throw "docker cp from $Image failed." }
} finally {
    docker rm $cid | Out-Null
}

$api = (docker ps -aq -f "name=iros-market-api").Trim()
if (-not $api) {
    Push-Location $Root
    try {
        docker compose create market-api
    } finally {
        Pop-Location
    }
    $api = (docker ps -aq -f "name=iros-market-api").Trim()
}
if (-not $api) { throw "iros-market-api container missing - start the stack, then re-run seed." }

$copied = 0
foreach ($name in $names) {
    $src = Join-Path $tmp $name
    if (-not (Test-Path -LiteralPath $src)) { continue }
    docker cp $src "${api}:/app/state/$name"
    if ($LASTEXITCODE -ne 0) { throw "docker cp $name into /app/state failed." }
    $copied += 1
    Write-Host "  seeded volume /app/state/$name"
}

$eodSrc = Join-Path $tmp "eod"
if (Test-Path -LiteralPath $eodSrc) {
    docker cp "${eodSrc}/." "${api}:/app/backend/app/data/eod/"
    Write-Host "  seeded volume /app/backend/app/data/eod/"
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

if ($copied -eq 0) {
    Write-Host "[WARN] Hub state image had no desk JSON - volumes unchanged."
} else {
    Write-Host "[OK] Seeded $copied desk file(s) from Hub into Docker volumes via iros-market-api"
}
