# IROS Trade API - On-Demand Data Refresh (PowerShell)
# ======================================================
# Performs a complete refresh of all available API endpoints.

param(
    [switch]$SkipNews,
    [string]$Pool,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$InformationPreference = "Continue"

$MarketApi = "http://127.0.0.1:8000"
$AiNewsApi = "http://127.0.0.1:8001"
$FrontendApi = "http://127.0.0.1:3000"
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $BaseDir "logs"
$null = New-Item -ItemType Directory -Path $LogDir -Force -ErrorAction SilentlyContinue

$PassCount = 0
$FailCount = 0
$TotalCount = 0
$ExitCode = 0

# Store the refresh result payload to avoid re-fetching with competing requests
$Script:RefreshPayload = $null
$Script:RefreshedTickers = @()

function Write-Step {
    param([int]$Step, [string]$Name)
    Write-Host ""
    Write-Host "[STEP $Step/8] $Name" -ForegroundColor Cyan
    Write-Host ("-" * 60) -ForegroundColor DarkGray
}

function Invoke-HealthCheck {
    param([string]$Uri, [string]$Name)
    try {
        $r = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 10
        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
            Write-Host "  [OK] $Name is running." -ForegroundColor Green
            return $true
        } else {
            Write-Host "  [FAIL] $Name returned status $($r.StatusCode)" -ForegroundColor Red
            return $false
        }
    } catch {
        Write-Host "  [FAIL] $Name is not reachable: $_" -ForegroundColor Red
        return $false
    }
}

function Invoke-GetJson {
    param([string]$Uri, [int]$TimeoutSec = 60)
    $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "HTTP $($response.StatusCode) from $Uri"
    }
    return $response.Content | ConvertFrom-Json
}

function Invoke-PostJson {
    param([string]$Uri, [object]$Body, [int]$TimeoutSec = 180)
    $jsonBody = $Body | ConvertTo-Json -Depth 8 -Compress
    $response = Invoke-WebRequest -Uri $Uri -Method POST -ContentType "application/json" -Body $jsonBody -UseBasicParsing -TimeoutSec $TimeoutSec
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "HTTP $($response.StatusCode) from $Uri"
    }
    return $response.Content | ConvertFrom-Json
}

function Assert-Success {
    param([object]$Json, [string]$Label)
    if ($Json.success -ne $true) {
        throw "$Label returned success=false"
    }
}

# ============================================================================
# HEADER
# ============================================================================
if (-not $Quiet) {
    Clear-Host
    Write-Host ("=" * 64) -ForegroundColor Yellow
    Write-Host "   IROS Trade API - On-Demand Data Refresh" -ForegroundColor Yellow
    Write-Host ("=" * 64) -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
    Write-Host "Log Dir:   $LogDir" -ForegroundColor Gray
    Write-Host ""
    Write-Host "APIs covered:" -ForegroundColor Gray
    Write-Host "  - Market API:       $MarketApi  (port 8000)" -ForegroundColor Gray
    Write-Host "  - AI News API:      $AiNewsApi  (port 8001)" -ForegroundColor Gray
    Write-Host ""
    if ($Pool) { Write-Host "Pool: $Pool" -ForegroundColor Cyan }
    if ($SkipNews) { Write-Host "AI News refresh: SKIPPED" -ForegroundColor Yellow }
    Write-Host ("=" * 64) -ForegroundColor Yellow
}

# ============================================================================
# STEP 1: Pre-flight checks
# ============================================================================
Write-Step -Step 1 -Name "Pre-flight: Checking service availability"

$marketHealthy = Invoke-HealthCheck -Uri "$MarketApi/health" -Name "Market API port 8000"
if (-not $marketHealthy) {
    Write-Host ""
    Write-Host "[FAIL] Market API is not running. Please start services first." -ForegroundColor Red
    Write-Host ""
    Write-Host "       Commands:" -ForegroundColor Gray
    Write-Host "         start_app.bat          - Start all services" -ForegroundColor Gray
    Write-Host "         restart-app.bat        - Restart all services" -ForegroundColor Gray
    Write-Host ""
    if (-not $Quiet) { Read-Host "Press Enter to exit..." }
    exit 1
}
if (-not (Invoke-HealthCheck -Uri "$AiNewsApi/health" -Name "AI News API port 8001")) {
    Write-Host ""
    Write-Host "[WARN] AI News API is not running on port 8001. News refresh will be skipped." -ForegroundColor Yellow
    Write-Host ""
    $Script:SkipNews = $true
}

# Check if frontend is running
$frontendHealthy = $false
try {
    $fr = Invoke-WebRequest -Uri "$FrontendApi/" -UseBasicParsing -TimeoutSec 5
    if ($fr.StatusCode -ge 200 -and $fr.StatusCode -lt 500) { $frontendHealthy = $true }
} catch {}

Write-Host ""
Write-Host "[PASS] Pre-flight checks complete." -ForegroundColor Green

# ============================================================================
# STEP 2: Refresh Market Data (on-demand live refresh) - THE KEY STEP
# ============================================================================
Write-Step -Step 2 -Name "Refreshing Market Data (live Angel One feed)"
$TotalCount++

try {
    $body = @{
        pool = if ($Pool) { $Pool } else { $null }
        prompt = $null
        refreshTickerNews = $false
    }
    Write-Host "  This performs a FORCED live Angel One refresh and saves to snapshot." -ForegroundColor Gray
    Write-Host "  Request: POST $MarketApi/api/refresh-data-on-demand" -ForegroundColor Gray

    $json = Invoke-PostJson -Uri "$MarketApi/api/refresh-data-on-demand" -Body $body -TimeoutSec 300

    $stocks = @($json.payload.stocks)
    $quotes = $json.payload.stockQuotes
    $qcount = if ($null -eq $quotes) { 0 } else { @($quotes.PSObject.Properties).Count }
    $Script:RefreshedTickers = @($stocks | ForEach-Object { $_.ticker } | Where-Object { $_ })
    $Script:RefreshPayload = $json.payload

    $mode = $json.selectionMeta.mode
    Write-Host "  [OK] Market data refreshed successfully." -ForegroundColor Green
    Write-Host "       Stocks: $($stocks.Count), StockQuotes: $qcount" -ForegroundColor Green
    Write-Host "       Selection mode: $mode" -ForegroundColor Green
    Write-Host "       Data date: $($json.selectionMeta.dataDate)" -ForegroundColor Green
    Write-Host "       Tickers loaded: $($Script:RefreshedTickers.Count)" -ForegroundColor Green

    if ($mode -ne "live") {
        Write-Host "  [WARN] Mode is '$mode' not 'live'. Snapshot was not refreshed live." -ForegroundColor Yellow
    }
    $PassCount++
} catch {
    Write-Host "  [FAIL] Refresh request failed: $_" -ForegroundColor Red
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# STEP 3: Refresh Ticker Intelligence (AI analysis for ALL fetched tickers)
# ============================================================================
Write-Step -Step 3 -Name "Refreshing Ticker Intelligence (AI analysis for all stocks)"
$TotalCount++

try {
    if ($Script:RefreshedTickers.Count -eq 0) {
        Write-Host "  [WARN] No tickers available. Skipping ticker intelligence." -ForegroundColor Yellow
        Write-Host "  [OK] Ticker intelligence skipped (no tickers)." -ForegroundColor Green
        $PassCount++
    } else {
        Write-Host "  Processing $($Script:RefreshedTickers.Count) tickers from refresh payload..." -ForegroundColor Gray

        # First try to get tickerIntelligenceByTicker from the market-intelligence endpoint
        # Use a longer delay to let the snapshot settle
        Start-Sleep -Seconds 2
        $miUri = "$MarketApi/api/market-intelligence"
        if ($Pool) { $miUri += "?pool=$Pool" }
        Write-Host "  Request: GET $miUri" -ForegroundColor Gray

        $miJson = Invoke-GetJson -Uri $miUri -TimeoutSec 300
        Assert-Success -Json $miJson -Label "Market intelligence"
        $tickerMap = $miJson.tickerIntelligenceByTicker

        # Also directly check the snapshot for an alternate source of ticker data
        if ((-not $tickerMap) -or (@($tickerMap.PSObject.Properties).Count -eq 0)) {
            Write-Host "  [WARN] Ticker map empty from API. Checking snapshot directly..." -ForegroundColor Yellow
            try {
                $snapPath = "$BaseDir\backend\last_market_snapshot.json"
                if (Test-Path $snapPath) {
                    $snap = Get-Content $snapPath -Raw | ConvertFrom-Json
                    if ($snap.tickerIntelligenceByTicker) {
                        $tickerMap = $snap.tickerIntelligenceByTicker
                        Write-Host "  [OK] Retrieved ticker intelligence from snapshot file." -ForegroundColor Green
                    }
                }
            } catch {}
        }

        $tickerCount = 0; $aiSummaryCount = 0; $skippedNoReport = 0
        $displayedTickers = @()

        foreach ($ticker in $Script:RefreshedTickers) {
            $tickerCount++
            $report = $null
            if ($tickerMap) { $report = $tickerMap.$ticker }

            if ($report) {
                $aiSummaryCount++
                $score = $report.active_factor_hub.score
                $reason = $report.active_factor_hub.selection_reason
                $narrative = $report.active_factor_hub.narrative

                $displayedTickers += [PSCustomObject]@{
                    Ticker  = $ticker
                    Score   = if ($score) { [double]($score -as [double]) } else { 0.0 }
                }

                if ($tickerCount -le 5) {
                    Write-Host "  [$ticker/$($Script:RefreshedTickers.Count)] $ticker" -ForegroundColor Gray
                    Write-Host "       Score: $(if($score){'{0:N2}' -f [double]($score -as [double])}else{'N/A'})" -ForegroundColor Gray
                    if ($reason) {
                        Write-Host "       Reason: $($reason.Substring(0,[Math]::Min(100,$reason.Length)) + '...')" -ForegroundColor Gray
                    }
                }
            } else {
                $skippedNoReport++
                if ($tickerCount -le 3) {
                    Write-Host "  [$ticker/$($Script:RefreshedTickers.Count)] $ticker (no report)" -ForegroundColor DarkGray
                }
            }
        }

        Write-Host "  [OK] Ticker intelligence refreshed." -ForegroundColor Green
        Write-Host "       Total tickers: $tickerCount" -ForegroundColor Green
        Write-Host "       AI analysis available: $aiSummaryCount" -ForegroundColor Green
        Write-Host "       No report: $skippedNoReport" -ForegroundColor Green

        if ($displayedTickers.Count -gt 0) {
            Write-Host "       Top scoring tickers:" -ForegroundColor Green
            $sorted = $displayedTickers | Sort-Object -Property Score -Descending | Select-Object -First 10
            $i = 0
            foreach ($s in $sorted) {
                $i++; Write-Host "         $i. $($s.Ticker) (score: $('{0:N2}' -f $s.Score))" -ForegroundColor Green
            }
        }
        $PassCount++
    }
} catch {
    Write-Host "  [FAIL] Ticker intelligence refresh failed: $_" -ForegroundColor Red
    Write-Host "  [WARN] Continuing with remaining steps..." -ForegroundColor Yellow
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# STEP 4: Refresh Market Intelligence (LLM analysis via POST, not competing GET)
# ============================================================================
Write-Step -Step 4 -Name "Refreshing Market Intelligence"
$TotalCount++

try {
    # Use POST refresh-data-on-demand to get fresh market intelligence
    # This avoids competing GET that would trigger another Angel One connection
    $body = @{
        pool = if ($Pool) { $Pool } else { $null }
        prompt = $null
        refreshTickerNews = $false
    }
    $json = Invoke-PostJson -Uri "$MarketApi/api/refresh-data-on-demand" -Body $body -TimeoutSec 300
    $miPayload = $json.payload

    $stocks = @($miPayload.stocks)
    $ti = $miPayload.terminalIntelligence
    $tiPopulated = $ti -and (@($ti.PSObject.Properties).Count -gt 0)
    $newsSummary = $miPayload.newsSummary
    $newsHasData = $newsSummary -and $newsSummary.Length -gt 0
    $nsStr = if ($newsHasData) { "present" } else { "empty" }
    $tiStr = if ($tiPopulated) { "populated" } else { "empty" }

    Write-Host "  [OK] Market intelligence refreshed." -ForegroundColor Green
    Write-Host "       Stocks: $($stocks.Count)" -ForegroundColor Green
    Write-Host "       News summary: $nsStr" -ForegroundColor Green
    Write-Host "       Terminal intelligence: $tiStr" -ForegroundColor Green
    $PassCount++
} catch {
    Write-Host "  [FAIL] Market intelligence request failed: $_" -ForegroundColor Red
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# STEP 5: Refresh Terminal Intelligence (ticker scoring)
# ============================================================================
Write-Step -Step 5 -Name "Refreshing Terminal Intelligence"
$TotalCount++

try {
    # Use the refresh-data-on-demand which already has terminalIntelligence
    if ($Script:RefreshPayload -and $Script:RefreshPayload.terminalIntelligence) {
        $ledger = @($Script:RefreshPayload.terminalIntelligence.ledger_stocks)
        $narrative = $Script:RefreshPayload.terminalIntelligence.narrative
        Write-Host "  [OK] Using terminal intelligence from the refresh response." -ForegroundColor Green
    } else {
        Write-Host "  [WARN] No terminal intelligence in refresh payload. Fetching via POST..." -ForegroundColor Yellow
        $body = @{ pool = if ($Pool) { $Pool } else { $null }; prompt = $null; refreshTickerNews = $false }
        $json = Invoke-PostJson -Uri "$MarketApi/api/refresh-data-on-demand" -Body $body -TimeoutSec 300
        $tiPayload = $json.payload.terminalIntelligence
        $ledger = @($tiPayload.ledger_stocks)
        $narrative = $tiPayload.narrative
    }

    $narrHasData = $narrative -and (@($narrative.PSObject.Properties).Count -gt 0)
    $narrStr = if ($narrHasData) { "present" } else { "empty" }

    Write-Host "  [OK] Terminal intelligence refreshed." -ForegroundColor Green
    Write-Host "       Ledger stocks: $($ledger.Count)" -ForegroundColor Green
    Write-Host "       Narrative: $narrStr" -ForegroundColor Green
    if ($ledger.Count -gt 0) {
        Write-Host "       Top scored tickers:" -ForegroundColor Green
        $sorted = $ledger | Sort-Object -Property score -Descending | Select-Object -First 10
        $i = 0
        foreach ($s in $sorted) {
            $i++; $sc = [double]($s.score -as [double])
            Write-Host "         $i. $($s.ticker) (score: $('{0:N2}' -f $sc))" -ForegroundColor Green
        }
    }
    $PassCount++
} catch {
    Write-Host "  [FAIL] Terminal intelligence request failed: $_" -ForegroundColor Red
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# STEP 6: Refresh News Feed (RSS news aggregation)
# ============================================================================
Write-Step -Step 6 -Name "Refreshing News Feed"
$TotalCount++

try {
    Write-Host "  Request: GET $MarketApi/api/news" -ForegroundColor Gray
    $json = Invoke-GetJson -Uri "$MarketApi/api/news" -TimeoutSec 60
    Assert-Success -Json $json -Label "News feed"

    $articles = @($json.news)
    Write-Host "  [OK] News feed refreshed." -ForegroundColor Green
    Write-Host "       Articles: $($articles.Count)" -ForegroundColor Green
    $PassCount++
} catch {
    Write-Host "  [FAIL] News feed request failed: $_" -ForegroundColor Red
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# STEP 7: Refresh AI Ticker News (batch news via port 8001)
# ============================================================================
Write-Step -Step 7 -Name "Refreshing AI Ticker News"

if ($SkipNews) {
    Write-Host "[SKIP] AI News refresh skipped via --skip-news flag." -ForegroundColor Yellow
    Write-Host ""
} else {
    $TotalCount++
    try {
        $tickers = @()
        if ($Script:RefreshedTickers.Count -gt 0) {
            $tickers = $Script:RefreshedTickers | Select-Object -First 10
            Write-Host "  Using $($tickers.Count) tickers from STEP 2 refresh." -ForegroundColor Gray
        } else {
            Write-Host "  Fetching top stocks from Market API..." -ForegroundColor Gray
            $mdJson = Invoke-GetJson -Uri "$MarketApi/api/market-data" -TimeoutSec 120
            Assert-Success -Json $mdJson -Label "Market data"
            $allStocks = @($mdJson.stocks)
            if ($allStocks.Count -eq 0) { throw "No stocks available for news refresh" }
            $tickers = @($allStocks | Sort-Object -Property score -Descending | Select-Object -First 10 | ForEach-Object { $_.ticker })
        }

        if ($tickers.Count -eq 0) {
            Write-Host "  [WARN] No tickers to refresh news for" -ForegroundColor Yellow
        } else {
            Write-Host "  Tickers: $($tickers -join ', ')" -ForegroundColor Gray
            Write-Host "  Calling AI News API batch refresh..." -ForegroundColor Gray

            $newsBody = @{ tickers = $tickers; max_articles = 20; include_raw = $false }
            $newsJson = Invoke-PostJson -Uri "$AiNewsApi/api/ticker-news/batch-check" -Body $newsBody -TimeoutSec 240

            $results = @($newsJson.results)
            $updated = 0; $cached = 0; $failed = 0
            foreach ($r in $results) {
                if ($r.cached -eq $true) { $cached++ }
                elseif ($r.error -eq $true) { $failed++ }
                else { $updated++ }
            }

            Write-Host "  [OK] AI Ticker News batch refresh complete." -ForegroundColor Green
            Write-Host "       Total: $($results.Count), Updated: $updated, Cached: $cached, Failed: $failed" -ForegroundColor Green
            $PassCount++
        }
    } catch {
        Write-Host "  [FAIL] AI Ticker News batch refresh: $_" -ForegroundColor Red
        Write-Host "  [WARN] Non-critical failure. Continuing..." -ForegroundColor Yellow
        $FailCount++; $ExitCode = 1
    }
}

# ============================================================================
# STEP 8: Validate & Invalidate Frontend Cache
# ============================================================================
Write-Step -Step 8 -Name "Validating & invalidating frontend cache"
$TotalCount++

try {
    # 8a: Validate using the snapshot file directly (avoids competing with GET /api/market-data)
    Write-Host "  [8a] Validating snapshot file..." -ForegroundColor Gray
    $snapPath = "$BaseDir\backend\last_market_snapshot.json"
    $foundStocks = 0
    $foundUpdated = ""
    if (Test-Path $snapPath) {
        $snap = Get-Content $snapPath -Raw | ConvertFrom-Json
        $foundStocks = @($snap.stocks).Count
        $foundUpdated = $snap.updatedAt
        Write-Host "  [OK] Snapshot validation:" -ForegroundColor Green
        Write-Host "       Stocks: $foundStocks, UpdatedAt: $foundUpdated" -ForegroundColor Green
        Write-Host "       Mode: $($snap.selectionMeta.mode)" -ForegroundColor Green

        if ($foundStocks -eq 0) {
            throw "Snapshot has 0 stocks - data may be stale"
        }
    } else {
        throw "Snapshot file not found at $snapPath"
    }

    # 8b: Call frontend proxy to trigger cache refresh (if frontend is running)
    if ($frontendHealthy) {
        Write-Host "  [8b] Invalidating frontend cache..." -ForegroundColor Gray

        # Call frontend refresh-data-on-demand proxy which does POST to backend
        # This is the only reliable way to update the frontend
        try {
            # First, call the backend directly again to make sure snapshot is 100% fresh
            Start-Sleep -Milliseconds 500
            $refreshResult = Invoke-PostJson -Uri "$MarketApi/api/refresh-data-on-demand" -Body @{} -TimeoutSec 300
            $success = $refreshResult.success
            if ($success) {
                Write-Host "  [OK] Backend snapshot confirmed fresh." -ForegroundColor Green
            } else {
                Write-Host "  [WARN] Backend returned success=false" -ForegroundColor Yellow
            }

            # Now force frontend to re-read by calling its proxy
            Start-Sleep -Milliseconds 500
            $frontendRefresh = Invoke-PostJson -Uri "$FrontendApi/api/refresh-data-on-demand" -Body @{} -TimeoutSec 300
            if ($frontendRefresh -and $frontendRefresh.success) {
                Write-Host "  [OK] Frontend cache invalidated via proxy." -ForegroundColor Green
                Write-Host "       Frontend will pick up fresh data immediately." -ForegroundColor Green
            } else {
                Write-Host "  [WARN] Frontend proxy returned: $(if($frontendRefresh){$frontendRefresh.success}else{'no response'})" -ForegroundColor Yellow
                Write-Host "         Press 'Refresh' button on frontend page." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "  [WARN] Frontend proxy call failed: $_" -ForegroundColor Yellow
            Write-Host "         Press 'Refresh' button on frontend page." -ForegroundColor Yellow
        }

        # Also wake up the frontend proxy via a simple GET (non-competing endpoint)
        try {
            $warmResult = Invoke-WebRequest -Uri "$FrontendApi/api/market-data?pool=Nifty%20500" -UseBasicParsing -TimeoutSec 10 -ErrorAction SilentlyContinue
            if ($warmResult.StatusCode -ge 200 -and $warmResult.StatusCode -lt 500) {
                Write-Host "  [OK] Frontend market-data proxy warmed." -ForegroundColor Green
            }
        } catch {
            # Non-critical
        }
    } else {
        Write-Host "  [8b] Frontend not running. Cache invalidation skipped." -ForegroundColor Yellow
    }

    Write-Host "  [OK] Validation and cache invalidation complete." -ForegroundColor Green
    $PassCount++
} catch {
    Write-Host "  [FAIL] Validation step failed: $_" -ForegroundColor Red
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# SUMMARY
# ============================================================================
Write-Host ""
Write-Host ("=" * 64) -ForegroundColor Yellow
Write-Host "   REFRESH SUMMARY" -ForegroundColor Yellow
Write-Host ("=" * 64) -ForegroundColor Yellow
Write-Host ""
Write-Host "Total steps:    $TotalCount" -ForegroundColor Gray
if ($PassCount -gt 0) {
    Write-Host "Passed:         $PassCount" -ForegroundColor Green
}
if ($FailCount -gt 0) {
    Write-Host "Failed:         $FailCount" -ForegroundColor Red
}
Write-Host ""
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host "Log Dir:   $LogDir" -ForegroundColor Gray
Write-Host ""

if ($ExitCode -eq 0) {
    Write-Host " >> ALL REFRESHES COMPLETED SUCCESSFULLY <<" -ForegroundColor Green
    Write-Host ""
    Write-Host " Data is now fresh across all APIs:" -ForegroundColor Gray
    Write-Host "   - Market API:       http://localhost:8000" -ForegroundColor Gray
    Write-Host "   - AI News API:      http://localhost:8001" -ForegroundColor Gray
    Write-Host "   - Frontend:         http://localhost:3000" -ForegroundColor Gray
    Write-Host ""
    Write-Host " Frontend will pick up fresh data on next auto-poll (~30s)." -ForegroundColor Gray
    Write-Host " Or manually press the 'Refresh' button on the frontend page." -ForegroundColor Gray
} else {
    Write-Host " [!] $FailCount of $TotalCount steps failed." -ForegroundColor Red
    Write-Host "     But snapshot was still updated during STEP 2." -ForegroundColor Yellow
    Write-Host "     Frontend will pick up the latest snapshot on next poll." -ForegroundColor Yellow
}

Write-Host ""
Write-Host ("=" * 64) -ForegroundColor Yellow
Write-Host ""

if (-not $Quiet) {
    Read-Host "Press Enter to exit..."
}

exit $ExitCode