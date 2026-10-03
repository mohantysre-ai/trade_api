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
    $code = Invoke-Docker -DockerArgs @('cp', "${Cid}:${From}/.", $To)
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
    $code = Invoke-Docker -DockerArgs @('run', '--rm', '-v', "${Volume}:/vol", '-v', "${To}:/out", 'alpine:3.21', 'sh', '-c', "if [ -d $inner ]; then cp -a $inner/. /out/; fi")
    if ($code -ne 0) { throw "volume pack of $Volume failed." }
}

try {
    $cid = [string](docker ps -aq -f "name=iros-market-api" | Select-Object -First 1)
    $cid = "$cid".Trim()
    if ($cid) {
        Copy-FromApi $cid "/app/state" $tmpState
        Copy-FromApi $cid "/app/backend/app/data" $tmpData
        Copy-FromApi $cid "/app/backend/app/services/eod_archive" $tmpArchive -Optional
    } else {
        Write-Host "  iros-market-api missing - packing compose project volumes"
        $stateVol = [string](docker volume ls -q | Select-String -Pattern "iros-desk-state$" | Select-Object -First 1)
        $dataVol = [string](docker volume ls -q | Select-String -Pattern "iros-backend-data$" | Select-Object -First 1)
        $archVol = [string](docker volume ls -q | Select-String -Pattern "iros-eod-archive$" | Select-Object -First 1)
        if ($stateVol) {
            Copy-FromVolume $stateVol.Trim() "" $tmpState
            if ($dataVol) { Copy-FromVolume $dataVol.Trim() "" $tmpData }
            if ($archVol) { Copy-FromVolume $archVol.Trim() "" $tmpArchive }
        } else {
            Write-Host "  no IROS volumes found - packing direct-app state only"
        }
    }
} catch {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    throw
}

function Copy-SqliteSnapshot {
    param([string]$Source, [string]$Target)
    $python = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $Root '.test-venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host "  [WARN] no Python venv - skipping live database $Source (will not be packed)"
        return $false
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
    $backup = "$Target.pack"
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
    & $python (Join-Path $PSScriptRoot 'sqlite-backup.py') $Source $backup
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $backup)) {
        Write-Host "  [WARN] SQLite snapshot failed for $Source - preserving existing seed copy"
        return $false
    }
    Move-Item -LiteralPath $backup -Destination $Target -Force
    (Get-Item -LiteralPath $Target).LastWriteTimeUtc = (Get-Item -LiteralPath $Source).LastWriteTimeUtc
    # A WAL database must never travel with stale sidecars: an orphaned -wal from
    # the source host is what makes the restored image report "database malformed".
    foreach ($suffix in @('-wal', '-shm')) {
        $sidecar = "$Target$suffix"
        if (Test-Path -LiteralPath $sidecar) { Remove-Item -LiteralPath $sidecar -Force }
    }
    return $true
}

function Copy-Tree {
    param([string]$From, [string]$To, [switch]$State)
    if (-not (Test-Path -LiteralPath $From)) { return 0 }
    $items = if ($State) {
        Get-ChildItem -LiteralPath $From -File -Filter '*.json' -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch '(\.bak|\.tmp|\.lock)\.json$' }
    } else {
        Get-ChildItem -LiteralPath $From -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch '\.(wal|shm)$' }
    }
    if (-not $items) { return 0 }
    $copied = 0
    foreach ($item in $items) {
        if (-not $item.PSIsContainer -and $item.Extension -in @('.sqlite3', '.db')) {
            # Snapshot through SQLite itself: a byte copy of an open WAL database
            # ships torn pages and produces "database disk image is malformed".
            $dest = Join-Path $To $item.Name
            if (Copy-SqliteSnapshot $item.FullName $dest) {
                Write-Host "  snapshotted database $($item.Name)"
                $copied++
            }
            continue
        }
        Copy-Item -LiteralPath $item.FullName -Destination $To -Recurse -Force
        $copied++
    }
    return $copied
}

Copy-Tree $tmpState $seedState -State | Out-Null
Copy-Tree $tmpData $seedData | Out-Null
Copy-Tree $tmpArchive $seedArchive | Out-Null

function Merge-NewerFiles {
    param([string]$From, [string]$To, [switch]$TopLevelOnly)
    if (-not (Test-Path -LiteralPath $From)) { return }
    $items = if ($TopLevelOnly) {
        Get-ChildItem -LiteralPath $From -File -Force
    } else {
        Get-ChildItem -LiteralPath $From -Recurse -File -Force
    }
    foreach ($item in $items) {
        if ($item.Extension -notin @('.json', '.sqlite3', '.db')) { continue }
        if ($item.Name -match '(\.bak|\.tmp|\.lock)$') { continue }
        if ($item.Name -in @('client_secret.json', 'gemini_oauth_token.json')) { continue }
        $relative = $item.FullName.Substring($From.Length).TrimStart('\', '/')
        $target = Join-Path $To $relative
        if (Test-Path -LiteralPath $target) {
            if ($item.Name -eq 'swing_v2_ledger.sqlite3') {
                $python = Join-Path $Root '.venv\Scripts\python.exe'
                if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $Root '.test-venv\Scripts\python.exe' }
                $sequenceScript = Join-Path $PSScriptRoot 'sqlite-sequence.py'
                $sourceSequence = [long](& $python $sequenceScript $item.FullName)
                $targetSequence = [long](& $python $sequenceScript $target)
                if ($sourceSequence -le $targetSequence) { continue }
                Write-Host "  newer direct-app ledger sequence: $sourceSequence > $targetSequence"
            } elseif ($item.LastWriteTimeUtc -le (Get-Item -LiteralPath $target).LastWriteTimeUtc) {
                continue
            }
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
        if ($item.Extension -in @('.sqlite3', '.db')) {
            if (-not (Copy-SqliteSnapshot $item.FullName $target)) {
                Write-Host "  [WARN] live database not packed: $relative"
                continue
            }
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
            try { $null = Get-Content -LiteralPath $target -Raw -Encoding utf8 | ConvertFrom-Json } catch { throw "Invalid JSON in $($item.FullName)" }
        }
        (Get-Item -LiteralPath $target).LastWriteTimeUtc = $item.LastWriteTimeUtc
        Write-Host "  newer direct-app state: $relative"
    }
}

Merge-NewerFiles (Join-Path $Root 'backend\app\services') $seedState -TopLevelOnly
$nativeRootState = Join-Path $tmp 'native-root-state'
New-Item -ItemType Directory -Force -Path $nativeRootState | Out-Null
foreach ($name in @('intraday_session.json')) {
    $source = Join-Path $Root $name
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $nativeRootState $name) -Force
        (Get-Item -LiteralPath (Join-Path $nativeRootState $name)).LastWriteTimeUtc = (Get-Item -LiteralPath $source).LastWriteTimeUtc
    }
}
Merge-NewerFiles $nativeRootState $seedState -TopLevelOnly
Merge-NewerFiles (Join-Path $Root 'backend\app\data') $seedData
Merge-NewerFiles (Join-Path $Root 'backend\app\services\eod_archive') $seedArchive


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
    source      = "newest-per-file:docker-volume+direct-app"
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
$swing = Join-Path $seedData "swing_v2_session.json"
if (-not (Test-Path -LiteralPath $snap)) {
    Write-Host "[WARN] last_market_snapshot.json missing on volume - other machines will not get live Matrix quotes."
}
if (-not (Test-Path -LiteralPath $session) -and -not (Test-Path -LiteralPath $swing)) {
    Write-Host "[WARN] No session JSON on the Docker volume - Hub state image will be thin."
}
if ($allFiles.Count -eq 0) {
    Write-Host "[WARN] No desk JSON on the Docker volume - Hub state image will be empty seed."
}
