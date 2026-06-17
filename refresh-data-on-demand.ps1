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
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $BaseDir "logs"
$null = New-Item -ItemType Directory -Path $LogDir -Force -ErrorAction SilentlyContinue

$PassCount = 0
$FailCount = 0
$TotalCount = 0
$ExitCode = 0

# Global: stores tickers from the refresh for later steps
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

Write-Host ""
Write-Host "[PASS] Pre-flight checks complete." -ForegroundColor Green

# ============================================================================
# STEP 2: Refresh Market Data (on-demand live refresh)
# ============================================================================
Write-Step -Step 2 -Name "Refreshing Market Data (live Angel One feed)"
$TotalCount++

try {
    $body = @{
        pool = if ($Pool) { $Pool } else { $null }
        prompt = $null
        refreshTickerNews = $false   # We handle ticker-news separately in STEP 7
    }
    Write-Host "  Request: POST /api/refresh-data-on-demand" -ForegroundColor Gray

    $json = Invoke-PostJson -Uri "$MarketApi/api/refresh-data-on-demand" -Body $body -TimeoutSec 300

    $stocks = @($json.payload.stocks)
    $quotes = $json.payload.stockQuotes
    $qcount = if ($null -eq $quotes) { 0 } else { @($quotes.PSObject.Properties).Count }

    # Store tickers for downstream steps
    $Script:RefreshedTickers = @($stocks | ForEach-Object { $_.ticker } | Where-Object { $_ })

    Write-Host "  [OK] Market data refreshed successfully." -ForegroundColor Green
    Write-Host "       Stocks: $($stocks.Count), StockQuotes: $qcount" -ForegroundColor Green
    Write-Host "       Selection mode: $($json.selectionMeta.mode)" -ForegroundColor Green
    Write-Host "       Data date: $($json.selectionMeta.dataDate)" -ForegroundColor Green
    Write-Host "       Tickers loaded: $($Script:RefreshedTickers.Count)" -ForegroundColor Green
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
        Write-Host "  [WARN] No tickers available from STEP 2. Calling market-intelligence directly..." -ForegroundColor Yellow
        $miUri = "$MarketApi/api/market-intelligence"
        if ($Pool) { $miUri += "?pool=$Pool" }
        $miJson = Invoke-GetJson -Uri $miUri -TimeoutSec 300
        Assert-Success -Json $miJson -Label "Market intelligence"
        $tickerMap = $miJson.tickerIntelligenceByTicker
    } else {
        # Use the refresh-data-on-demand response which already has tickerIntelligenceByTicker
        Write-Host "  Fetching ticker intelligence details via market-intelligence API..." -ForegroundColor Gray
        $miUri = "$MarketApi/api/market-intelligence"
        if ($Pool) { $miUri += "?pool=$Pool" }
        $miJson = Invoke-GetJson -Uri $miUri -TimeoutSec 300
        Assert-Success -Json $miJson -Label "Market intelligence"
        $tickerMap = $miJson.tickerIntelligenceByTicker
    }

    # Process and display ticker intelligence
    $tickerCount = 0
    $aiSummaryCount = 0
    $skippedNoReport = 0
    $displayedTickers = @()

    foreach ($ticker in $Script:RefreshedTickers) {
        $tickerCount++
        $report = $null
        if ($tickerMap) {
            $report = $tickerMap.$ticker
        }

        if ($report) {
            $aiSummaryCount++
            $reason = $report.active_factor_hub.selection_reason
            $score = $report.active_factor_hub.score
            $narrative = $report.active_factor_hub.narrative
            $focusTicker = $report.focusTicker

            $displayedTickers += [PSCustomObject]@{
                Ticker  = $ticker
                Score   = if ($score) { [double]($score -as [double]) } else { 0.0 }
                Reason  = if ($reason) { $reason.Substring(0, [Math]::Min(120, $reason.Length)) + "..." } else { "N/A" }
            }

            # Show detailed info for first 5 tickers
            if ($tickerCount -le 5) {
                Write-Host "  [$ticker/$($Script:RefreshedTickers.Count)] $ticker" -ForegroundColor Gray
                Write-Host "       Score: $(if($score){'{0:N2}' -f [double]($score -as [double])}else{'N/A'})" -ForegroundColor Gray
                Write-Host "       Reason: $(if($reason){$reason.Substring(0,[Math]::Min(100,$reason.Length)) + '...'}else{'N/A'})" -ForegroundColor Gray
                if ($narrative) {
                    $narrShort = $narrative.Substring(0, [Math]::Min(150, $narrative.Length)) + "..."
                    Write-Host "       Narrative: $narrShort" -ForegroundColor Gray
                }
            }
        } else {
            $skippedNoReport++
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
            $i++
            Write-Host "         $i. $($s.Ticker) (score: $('{0:N2}' -f $s.Score))" -ForegroundColor Green
        }
    }
    $PassCount++
} catch {
    Write-Host "  [FAIL] Ticker intelligence refresh failed: $_" -ForegroundColor Red
    # Don't fail the whole run - this is an enhancement step
    Write-Host "  [WARN] Continuing with remaining steps..." -ForegroundColor Yellow
    $FailCount++; $ExitCode = 1
}

# ============================================================================
# STEP 4: Refresh Market Intelligence (LLM analysis)
# ============================================================================
Write-Step -Step 4 -Name "Refreshing Market Intelligence"
$TotalCount++

try {
    $uri = "$MarketApi/api/market-intelligence"
    if ($Pool) { $uri += "?pool=$Pool" }

    Write-Host "  Request: GET $uri" -ForegroundColor Gray
    $json = Invoke-GetJson -Uri $uri -TimeoutSec 300
    Assert-Success -Json $json -Label "Market intelligence"

    $stocks = @($json.stocks)
    $ns = $json.newsSummary
    $newsHasData = $ns -and (@($ns.PSObject.Properties).Count -gt 0)
    $ti = $json.terminalIntelligence
    $tiPopulated = $ti -and (@($ti.PSObject.Properties).Count -gt 0)
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
    $uri = "$MarketApi/api/terminal-intelligence"
    if ($Pool) { $uri += "?pool=$Pool" }
    Write-Host "  Request: GET $uri" -ForegroundColor Gray

    $json = Invoke-GetJson -Uri $uri -TimeoutSec 300
    Assert-Success -Json $json -Label "Terminal intelligence"

    $ledger = @($json.terminalIntelligence.ledger_stocks)
    $narrative = $json.terminalIntelligence.narrative
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
            $i++
            $sc = [double]($s.score -as [double])
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

    $articles = @($json.articles)
    Write-Host "  [OK] News feed refreshed." -ForegroundColor Green
    Write-Host "       Articles: $($articles.Count)" -ForegroundColor Green
    Write-Host "       Sources: $($json.sourceCount)" -ForegroundColor Green
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
        # Use tickers from STEP 2 if available, otherwise fetch from market-data
        $tickers = @()
        if ($Script:RefreshedTickers.Count -gt 0) {
            $tickers = $Script:RefreshedTickers | Select-Object -First 10
            Write-Host "  Using $($tickers.Count) tickers from STEP 2 refresh." -ForegroundColor Gray
        } else {
            Write-Host "  Fetching top stocks from Market API to refresh news..." -ForegroundColor Gray
            $mdJson = Invoke-GetJson -Uri "$MarketApi/api/market-data" -TimeoutSec 120
            if ($mdJson.success -ne $true) {
                throw "Could not fetch market data for news refresh"
            }
            $allStocks = @($mdJson.stocks)
            if ($allStocks.Count -eq 0) {
                throw "No stocks available for news refresh"
            }
            $tickers = @($allStocks | Sort-Object -Property score -Descending | Select-Object -First 10 | ForEach-Object { $_.ticker })
        }

        if ($tickers.Count -eq 0) {
            Write-Host "  [WARN] No tickers to refresh news for" -ForegroundColor Yellow
        } else {
            Write-Host "  Tickers: $($tickers -join ', ')" -ForegroundColor Gray
            Write-Host "  Calling AI News API batch refresh (timeout: 180s)... " -ForegroundColor Gray

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
        Write-Host "  [WARN] This is a non-critical failure. Continuing..." -ForegroundColor Yellow
        $FailCount++; $ExitCode = 1
    }
}

# ============================================================================
# STEP 8: Validate - Re-fetch market data to confirm refresh
# ============================================================================
Write-Step -Step 8 -Name "Validating refreshed data"
$TotalCount++

try {
    $uri = "$MarketApi/api/market-data"
    if ($Pool) { $uri += "?pool=$Pool" }
    Write-Host "  Request: GET $uri" -ForegroundColor Gray

    $json = Invoke-GetJson -Uri $uri -TimeoutSec 180
    Assert-Success -Json $json -Label "Validation"

    $stocks = @($json.stocks)
    $quotes = $json.stockQuotes
    $qcount = if ($null -eq $quotes) { 0 } else { @($quotes.PSObject.Properties).Count }

    Write-Host "  [OK] Validation complete." -ForegroundColor Green
    Write-Host "       Stocks: $($stocks.Count), StockQuotes: $qcount" -ForegroundColor Green
    Write-Host "       Last updated: $($json.updatedAt)" -ForegroundColor Green
    Write-Host "       Selection mode: $($json.selectionMeta.mode)" -ForegroundColor Green
    Write-Host "       Data date: $($json.selectionMeta.dataDate)" -ForegroundColor Green
    $PassCount++
} catch {
    Write-Host "  [FAIL] Validation request failed: $_" -ForegroundColor Red
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
} else {
    Write-Host " [!] $FailCount of $TotalCount steps failed." -ForegroundColor Red
    Write-Host "     Some steps had issues but core data may still be fresh." -ForegroundColor Red
}

Write-Host ""
Write-Host ("=" * 64) -ForegroundColor Yellow
Write-Host ""

if (-not $Quiet) {
    Read-Host "Press Enter to exit..."
}

exit $ExitCode