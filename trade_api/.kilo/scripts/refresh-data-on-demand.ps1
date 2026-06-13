$ErrorActionPreference = "Stop"

$Root = "D:\trade_api"
$BackendUrl = "http://127.0.0.1:8000"
$OutputPath = Join-Path $Root "trade_api_snapshot.json"
$Pool = $null
$Prompt = $null
$Index = 0

while ($Index -lt $args.Count) {
    $arg = $args[$Index]
    if (($arg -eq "--pool" -or $arg -eq "--prompt") -and ($Index + 1) -lt $args.Count) {
        $value = $args[$Index + 1]
        if ($arg -eq "--pool") {
            $Pool = $value
        } else {
            $Prompt = $value
        }
        $Index += 2
    } else {
        $Index++
    }
}

function Write-Snapshot {
    param([object]$Payload)

    $snapshot = [ordered]@{
        exportedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
        source = "refresh-data-on-demand"
        payload = $Payload
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
    $snapshotJson = $snapshot | ConvertTo-Json -Depth 50
    Set-Content -Path $OutputPath -Value $snapshotJson -Encoding UTF8
    Write-Host "Snapshot saved: $OutputPath"
}

$body = @{}
if ($Pool) { $body["pool"] = $Pool }
if ($Prompt) { $body["prompt"] = $Prompt }

try {
    $uri = "$BackendUrl/api/refresh-data-on-demand"
    if ($body.Count -gt 0) {
        $payload = Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body ($body | ConvertTo-Json) -TimeoutSec 180
    } else {
        $payload = Invoke-RestMethod -Method Post -Uri $uri -TimeoutSec 180
    }

    if (-not $payload.success) {
        throw "Backend refresh failed: $($payload | ConvertTo-Json -Depth 20)"
    }
    if (-not $payload.payload) {
        throw "Backend refresh returned an empty payload."
    }

    Write-Snapshot $payload.payload
    $selectionMode = if ($payload.selectionMeta) { $payload.selectionMeta.mode } else { "unknown" }
    Write-Host "Backend refresh completed: $uri"
    Write-Host "Snapshot fallback: $($payload.isSnapshotFallback)"
    Write-Host "Selection mode: $selectionMode"
    exit 0
} catch {
    Write-Warning "Backend refresh endpoint was not reachable: $($_.Exception.Message)"
    Write-Host "Falling back to backend CLI refresh..."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$cliArgs = @(
    (Join-Path $Root "backend\angel_one_feed.py"),
    "--refresh-on-demand",
    "--output",
    $OutputPath
)
if ($Pool) { $cliArgs += "--pool"; $cliArgs += $Pool }
if ($Prompt) { $cliArgs += "--prompt"; $cliArgs += $Prompt }

& $Python @cliArgs
if ($LASTEXITCODE -ne 0) {
    throw "CLI refresh failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $OutputPath)) {
    throw "Expected snapshot file was not created: $OutputPath"
}

Write-Host "CLI refresh completed and snapshot saved: $OutputPath"
