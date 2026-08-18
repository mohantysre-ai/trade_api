# Pack live Docker volumes into config/docker/desk-state/seed for the Hub state image.
# Source of truth is the running stack volumes, not the git tree:
#   /app/state                  → seed/state/   (sessions + last_market_snapshot + plan)
#   /app/backend/app/data       → seed/data/    (eod/YYYY-MM-DD + desk stamps)
#   /app/backend/app/services/eod_archive → seed/archive/
$ErrorActionPreference = "Stop"
# docker cp prints "Successfully copied ..." on stderr; PS Stop treats that as NativeCommandError.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Seed = Join-Path $Root "config\docker\desk-state\seed"
New-Item -ItemType Directory -Force -Path $Seed | Out-Null

function Reset-SeedDir {
    param([string]$Rel)
    $path = Join-Path $Seed $Rel
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    return $path
}

Get-ChildItem -Path $Seed -File -Filter "*.json" -ErrorAction SilentlyContinue |
    Remove-Item -Force
$seedState = Reset-SeedDir "state"
$seedData = Reset-SeedDir "data"
$seedArchive = Reset-SeedDir "archive"
$legacyEod = Join-Path $Seed "eod"
if (Test-Path -LiteralPath $legacyEod) {
    Remove-Item -LiteralPath $legacyEod -Recurse -Force
}

$tmp = Join-Path $env:TEMP ("iros-pack-state-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$tmpState = Join-Path $tmp "state"
$tmpData = Join-Path $tmp "data"
$tmpArchive = Join-Path $tmp "archive"
New-Item -ItemType Directory -Force -Path $tmpState, $tmpData, $tmpArchive | Out-Null

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

function Copy-FromApi {
    param([string]$Cid, [string]$From, [string]$To, [switch]$Optional)
    $code = Invoke-Docker cp "${Cid}:${From}/." $To
    if ($code -ne 0) {
        if ($Optional) {
            Write-Host "  skip $From (missing in container)"
            return
        }
        throw "docker cp $From failed."
    }
}

function Copy-FromVolume {
    param([string]$Volume, [string]$Sub, [string]$To)
    $inner = if ($Sub) { "/vol/$Sub" } else { "/vol" }
    $code = Invoke-Docker run --rm -v "${Volume}:/vol" -v "${To}:/out" alpine:3.21 sh -c "if [ -d $inner ]; then cp -a $inner/. /out/; fi"
    if ($code -ne 0) { throw "volume pack of $Volume failed." }
}

try {
    $cid = (docker ps -aq -f "name=iros-market-api").Trim()
    if ($cid) {
        Copy-FromApi $cid "/app/state" $tmpState
        Copy-FromApi $cid "/app/backend/app/data" $tmpData
        Copy-FromApi $cid "/app/backend/app/services/eod_archive" $tmpArchive -Optional
    } else {
        Write-Host "  iros-market-api missing - packing compose project volumes"
        $stateVol = (docker volume ls -q | Select-String -Pattern "iros-desk-state$").Line
        $dataVol = (docker volume ls -q | Select-String -Pattern "iros-backend-data$").Line
        $archVol = (docker volume ls -q | Select-String -Pattern "iros-eod-archive$").Line
        if (-not $stateVol) { throw "named volume iros-desk-state not found." }
        Copy-FromVolume $stateVol "" $tmpState
        if ($dataVol) { Copy-FromVolume $dataVol "" $tmpData }
        if ($archVol) { Copy-FromVolume $archVol "" $tmpArchive }
    }
} catch {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    throw
}

function Copy-Tree {
    param([string]$From, [string]$To)
    if (-not (Test-Path -LiteralPath $From)) { return 0 }
    $items = Get-ChildItem -LiteralPath $From -Force -ErrorAction SilentlyContinue
    if (-not $items) { return 0 }
    Copy-Item -Path (Join-Path $From "*") -Destination $To -Recurse -Force -ErrorAction SilentlyContinue
    return @($items).Count
}

Copy-Tree $tmpState $seedState | Out-Null
Copy-Tree $tmpData $seedData | Out-Null
Copy-Tree $tmpArchive $seedArchive | Out-Null

function Get-TreeFiles {
    param([string]$Dir)
    if (-not (Test-Path -LiteralPath $Dir)) { return @() }
    return @(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force -ErrorAction SilentlyContinue)
}

$stateFiles = Get-TreeFiles $seedState
$dataFiles = Get-TreeFiles $seedData
$archFiles = Get-TreeFiles $seedArchive
$allFiles = @($stateFiles) + @($dataFiles) + @($archFiles)

foreach ($f in $stateFiles) {
    $rel = $f.FullName.Substring($seedState.Length).TrimStart("\", "/")
    $kb = [Math]::Round($f.Length / 1024.0, 1)
    Write-Host "  packed state/$rel ($kb KB)"
}
Write-Host "  packed data/ ($($dataFiles.Count) files)"
Write-Host "  packed archive/ ($($archFiles.Count) files)"

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

$manifest = [ordered]@{
    packedAtUtc = [DateTime]::UtcNow.ToString("o")
    host        = $env:COMPUTERNAME
    source      = "docker-volume"
    layout      = "state+data+archive"
    files = @(
        $allFiles | ForEach-Object {
            $root = $Seed
            $rel = $_.FullName.Substring($root.Length).TrimStart("\", "/").Replace("\", "/")
            [ordered]@{ name = $rel; bytes = $_.Length }
        }
    )
}
$manifestPath = Join-Path $Seed "manifest.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "  wrote manifest.json ($($allFiles.Count) files)"

$snap = Join-Path $seedState "last_market_snapshot.json"
$session = Join-Path $seedState "intraday_session.json"
$swing = Join-Path $seedState "swing_session.json"
if (-not (Test-Path -LiteralPath $snap)) {
    Write-Host "[WARN] last_market_snapshot.json missing on volume - other machines will not get live Matrix quotes."
}
if (-not (Test-Path -LiteralPath $session) -and -not (Test-Path -LiteralPath $swing)) {
    Write-Host "[WARN] No session JSON on the Docker volume - Hub state image will be thin."
}
if ($allFiles.Count -eq 0) {
    Write-Host "[WARN] No desk JSON on the Docker volume - Hub state image will be empty seed."
}
