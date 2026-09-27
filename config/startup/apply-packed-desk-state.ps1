$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Seed = Join-Path $Root "config\docker\desk-state\seed"
$api = "iros-market-api"
docker inspect $api 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "iros-market-api container missing." }
if ((docker inspect -f "{{.State.Running}}" $api) -ne "false") { throw "iros-market-api must be stopped before state restore." }

function Clear-ContainerVolume {
    param([string]$Target)
    docker run --rm --volumes-from $api alpine:3.21 sh -c "find '$Target' -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +"
    if ($LASTEXITCODE -ne 0) { throw "Failed clearing stopped volume target $Target" }
}

foreach ($entry in @(
    @{ Folder = "state"; Target = "/app/state/" },
    @{ Folder = "data"; Target = "/app/backend/app/data/" },
    @{ Folder = "archive"; Target = "/app/backend/app/services/eod_archive/" }
)) {
    $source = Join-Path $Seed $entry.Folder
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing packed $source" }
    $files = @(Get-ChildItem -LiteralPath $source -Recurse -File -Force)
    if ($files.Count -eq 0) { continue }
    Clear-ContainerVolume $entry.Target
    docker cp "${source}/." "${api}:$($entry.Target)"
    if ($LASTEXITCODE -ne 0) { throw "Failed restoring packed $($entry.Folder) into $($entry.Target)" }
    Write-Host "  restored $($entry.Folder) ($($files.Count) files)"
}
