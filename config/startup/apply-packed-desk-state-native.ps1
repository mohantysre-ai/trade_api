$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Seed = Join-Path $Root "config\docker\desk-state\seed"
$State = Join-Path $Seed "state"
$Data = Join-Path $Seed "data"
$Archive = Join-Path $Seed "archive"

function Copy-NewerFile {
    param([string]$Source, [string]$Target)
    if (-not (Test-Path -LiteralPath $Source)) { return $false }
    if (Test-Path -LiteralPath $Target) {
        if ((Get-Item -LiteralPath $Source).LastWriteTimeUtc -le (Get-Item -LiteralPath $Target).LastWriteTimeUtc) {
            return $false
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
    if ([IO.Path]::GetExtension($Source) -in @('.db', '.sqlite3')) {
        $python = Join-Path $Root '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $Root '.test-venv\Scripts\python.exe' }
        if (-not (Test-Path -LiteralPath $python)) { throw "Python venv required to restore $Source" }
        $temp = "$Target.restore"
        & $python (Join-Path $PSScriptRoot 'sqlite-backup.py') $Source $temp
        if ($LASTEXITCODE -ne 0) { throw "SQLite restore failed for $Source" }
        Move-Item -LiteralPath $temp -Destination $Target -Force
    } else {
        Copy-Item -LiteralPath $Source -Destination $Target -Force
    }
    (Get-Item -LiteralPath $Target).LastWriteTimeUtc = (Get-Item -LiteralPath $Source).LastWriteTimeUtc
    return $true
}

$copied = 0
foreach ($name in @('intraday_session.json')) {
    if (Copy-NewerFile (Join-Path $State $name) (Join-Path $Root $name)) { $copied++ }
}
if (Test-Path -LiteralPath $State) {
    foreach ($item in Get-ChildItem -LiteralPath $State -File -Force) {
        if ($item.Name -in @('intraday_session.json', 'manifest.json')) { continue }
        if (Copy-NewerFile $item.FullName (Join-Path $Root "backend\app\services\$($item.Name)")) { $copied++ }
    }
}
foreach ($entry in @(
    @{ Source = $Data; Target = (Join-Path $Root 'backend\app\data') },
    @{ Source = $Archive; Target = (Join-Path $Root 'backend\app\services\eod_archive') }
)) {
    if (-not (Test-Path -LiteralPath $entry.Source)) { continue }
    foreach ($item in Get-ChildItem -LiteralPath $entry.Source -Recurse -File -Force) {
        $relative = $item.FullName.Substring($entry.Source.Length).TrimStart('\', '/')
        if (Copy-NewerFile $item.FullName (Join-Path $entry.Target $relative)) { $copied++ }
    }
}
Write-Host "[OK] Native runtime reconciled from newest packed state ($copied newer files)."
