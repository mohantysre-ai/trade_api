# Pull iros-desk-state and copy JSON onto the host repo (bind-mounted as /app/state).
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Image = "smohanty010620/iros-desk-state:latest"
$names = @(
    "intraday_session.json",
    "swing_session.json",
    "last_market_snapshot.json",
    "fixed_trade_plan.json",
    "alert_history.json",
    "trade_api_snapshot.json",
    "manifest.json"
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

$copied = 0
foreach ($name in $names) {
    $src = Join-Path $tmp $name
    if (-not (Test-Path -LiteralPath $src)) { continue }
    $destName = if ($name -eq "manifest.json") { "desk_state_hub_manifest.json" } else { $name }
    Copy-Item -LiteralPath $src -Destination (Join-Path $Root $destName) -Force
    $copied += 1
    Write-Host "  seeded $destName"
}
Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

if ($copied -eq 0) {
    Write-Host "[WARN] Hub state image had no desk JSON - local files unchanged."
} else {
    Write-Host "[OK] Seeded $copied desk file(s) from Hub into $Root"
}
