$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BackendUrl = "http://127.0.0.1:8000"
$OutputPath = Join-Path $Root "trade_api_snapshot.json"
$SnapshotPath = Join-Path $Root "backend\app\services\last_market_snapshot.json"
$Pool = $null
$Prompt = $null
$SkipNews = $false
$Index = 0
$RefreshTimeoutSec = 900
$PollIntervalSec = 3

Write-Host "[PRE-CLEAR] Clearing export snapshot only (keeping last_market_snapshot.json for reuse)..." -ForegroundColor Yellow
$cleared = $false
if (Test-Path $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
    $cleared = $true
    Write-Host "  [OK] Removed: $OutputPath" -ForegroundColor Green
}
if (-not $cleared) {
    Write-Host "  [OK] No export snapshot to clear." -ForegroundColor Green
}
if (Test-Path $SnapshotPath) {
    Write-Host "  [OK] Preserved: $SnapshotPath (backend reuses for intraday + AI cache)" -ForegroundColor Green
}

while ($Index -lt $args.Count) {
    $arg = $args[$Index]
    if (($arg -eq "--pool" -or $arg -eq "-Pool") -and ($Index + 1) -lt $args.Count) {
        $Pool = $args[$Index + 1]
        $Index += 2
    } elseif (($arg -eq "--prompt" -or $arg -eq "-Prompt") -and ($Index + 1) -lt $args.Count) {
        $Prompt = $args[$Index + 1]
        $Index += 2
    } elseif ($arg -eq "--skip-news" -or $arg -eq "-SkipNews") {
        $SkipNews = $true
        $Index++
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

function Invoke-RefreshOnDemandAsync {
    param(
        [string]$Uri,
        [hashtable]$Body,
        [int]$MaxWaitSec = 900,
        [int]$PollIntervalSec = 3
    )

    $jsonBody = if ($Body.Count -gt 0) { $Body | ConvertTo-Json } else { "{}" }
    $response = Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $jsonBody -TimeoutSec 60 -UseBasicParsing
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "HTTP $($response.StatusCode) from $Uri"
    }
    $init = $response.Content | ConvertFrom-Json

    if ($init.payload) {
        return $init
    }

    $isAsync = ($init.accepted -eq $true) -or $init.statusUrl -or $init.taskId
    if (-not $isAsync) {
        throw "Backend refresh did not return payload or async task handles"
    }

    $statusPath = [string]$init.statusUrl
    if (-not $statusPath) {
        if ($init.taskId) {
            $encodedTaskId = [System.Uri]::EscapeDataString([string]$init.taskId)
            $statusPath = "/api/refresh-data-on-demand/status?taskId=$encodedTaskId"
        } else {
            throw "Backend refresh did not return statusUrl or taskId"
        }
    }

    if ($statusPath.StartsWith("http")) {
        $statusUrl = $statusPath
    } else {
        $statusUrl = "$BackendUrl$statusPath"
    }

    $deadline = (Get-Date).AddSeconds($MaxWaitSec)
    while ((Get-Date) -lt $deadline) {
        $statusResponse = Invoke-WebRequest -Uri $statusUrl -TimeoutSec 60 -UseBasicParsing
        if ($statusResponse.StatusCode -lt 200 -or $statusResponse.StatusCode -ge 300) {
            throw "HTTP $($statusResponse.StatusCode) polling $statusUrl"
        }
        $status = $statusResponse.Content | ConvertFrom-Json
        if ($status.status -eq "done") {
            if (-not $status.result) {
                throw "Refresh task completed without a result payload"
            }
            return $status.result
        }
        if ($status.status -eq "error" -or $status.status -eq "failed") {
            throw "Refresh failed: $($status.error)"
        }
        if ($status.status -eq "expired") {
            throw "Refresh task expired"
        }
        $progress = if ($status.progress) { $status.progress } else { $status.status }
        Write-Host "  [..] $progress" -ForegroundColor Gray
        Start-Sleep -Seconds $PollIntervalSec
    }

    throw "Refresh timed out after ${MaxWaitSec}s"
}

$body = @{}
if ($Pool) { $body["pool"] = $Pool }
if ($Prompt) { $body["prompt"] = $Prompt }
if (-not $SkipNews) { $body["refreshTickerNews"] = $true }

try {
    $uri = "$BackendUrl/api/refresh-data-on-demand"
    Write-Host "Starting async refresh: POST $uri (max wait ${RefreshTimeoutSec}s)" -ForegroundColor Cyan
    $payload = Invoke-RefreshOnDemandAsync -Uri $uri -Body $body -MaxWaitSec $RefreshTimeoutSec -PollIntervalSec $PollIntervalSec

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

Write-Host "  [CMD] Changing to backend directory and running module..." -ForegroundColor Cyan
$cliArgs = @(
    "-m",
    "app.services.angel_one_feed",
    "--refresh-on-demand",
    "--output",
    $OutputPath
)
if ($Pool) { $cliArgs += "--pool"; $cliArgs += $Pool }
if ($Prompt) { $cliArgs += "--prompt"; $cliArgs += $Prompt }

Push-Location (Join-Path $Root "backend")
try {
    & $Python @cliArgs
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) {
    throw "CLI refresh failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $OutputPath)) {
    throw "Expected snapshot file was not created: $OutputPath"
}

Write-Host "CLI refresh completed and snapshot saved: $OutputPath"
