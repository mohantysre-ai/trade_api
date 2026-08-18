# Pull iros-desk-state and copy JSON into the stack's named volumes.
# Does not write desk JSON into the git working tree.
# Restarts market-api / ai-news if they were already running so they reload JSON.
$ErrorActionPreference = "Stop"
# docker cp prints "Successfully copied ..." on stderr; PS Stop treats that as NativeCommandError.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Image = "smohanty010620/iros-desk-state:latest"

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DockerArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & docker @DockerArgs 2>&1
        $code = [int]$LASTEXITCODE
        foreach ($line in @($out)) {
            $text = "$line"
            if ($text -match "Successfully copied") { continue }
            if ($text) { Write-Host $text }
        }
        return $code
    } finally {
        $ErrorActionPreference = $prev
    }
}

Write-Host "[*] Pulling $Image ..."
if ((Invoke-Docker pull $Image) -ne 0) {
    throw "docker pull $Image failed - run push-docker-hub.bat on the desk that has the live JSON."
}

$cid = (docker create $Image).Trim()
if (-not $cid) { throw "docker create $Image failed." }
$tmp = Join-Path $env:TEMP ("iros-desk-state-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    if ((Invoke-Docker cp "${cid}:/desk-state/." $tmp) -ne 0) {
        throw "docker cp from $Image failed."
    }
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

$running = (docker inspect -f "{{.State.Running}}" $api 2>$null)
if ($running -eq "true") {
    Write-Host "  stopping market-api + ai-news so seed is on disk before process start"
    docker stop iros-market-api iros-ai-news 2>$null | Out-Null
}

function Copy-Into {
    param([string]$From, [string]$To)
    if (-not (Test-Path -LiteralPath $From)) { return 0 }
    $files = @(Get-ChildItem -LiteralPath $From -Recurse -File -Force -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) { return 0 }
    if ((Invoke-Docker cp "${From}/." "${api}:${To}") -ne 0) {
        throw "docker cp into $To failed."
    }
    return $files.Count
}

$copied = 0
$layoutState = Join-Path $tmp "state"
$layoutData = Join-Path $tmp "data"
$layoutArchive = Join-Path $tmp "archive"
$legacyEod = Join-Path $tmp "eod"

if (Test-Path -LiteralPath $layoutState) {
    $n = Copy-Into $layoutState "/app/state/"
    $copied += $n
    Write-Host "  seeded /app/state/ ($n files)"
} else {
    $legacyNames = @(
        "intraday_session.json",
        "swing_session.json",
        "last_market_snapshot.json",
        "fixed_trade_plan.json",
        "alert_history.json",
        "trade_api_snapshot.json"
    )
    foreach ($name in $legacyNames) {
        $src = Join-Path $tmp $name
        if (-not (Test-Path -LiteralPath $src)) { continue }
        if ((Invoke-Docker cp $src "${api}:/app/state/$name") -ne 0) {
            throw "docker cp $name into /app/state failed."
        }
        $copied += 1
        Write-Host "  seeded volume /app/state/$name"
    }
}

if (Test-Path -LiteralPath $layoutData) {
    $n = Copy-Into $layoutData "/app/backend/app/data/"
    $copied += $n
    Write-Host "  seeded /app/backend/app/data/ ($n files)"
} elseif (Test-Path -LiteralPath $legacyEod) {
    if ((Invoke-Docker cp "${legacyEod}/." "${api}:/app/backend/app/data/eod/") -ne 0) {
        throw "docker cp eod into /app/backend/app/data/eod failed."
    }
    Write-Host "  seeded volume /app/backend/app/data/eod/"
}

if (Test-Path -LiteralPath $layoutArchive) {
    $n = Copy-Into $layoutArchive "/app/backend/app/services/eod_archive/"
    $copied += $n
    Write-Host "  seeded /app/backend/app/services/eod_archive/ ($n files)"
}

$snapSeeded = Test-Path -LiteralPath (Join-Path $layoutState "last_market_snapshot.json")
if (-not $snapSeeded) {
    $snapSeeded = Test-Path -LiteralPath (Join-Path $tmp "last_market_snapshot.json")
}
if (-not $snapSeeded) {
    Write-Host "[WARN] Hub image has no last_market_snapshot.json - Matrix quotes will be empty until live refresh."
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

if ($copied -eq 0) {
    Write-Host "[WARN] Hub state image had no desk JSON - volumes unchanged."
} else {
    Write-Host "[OK] Seeded $copied file(s) from Hub into Docker volumes via iros-market-api"
}
