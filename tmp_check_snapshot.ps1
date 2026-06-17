param()

$ErrorActionPreference = "Stop"

$snapPath = "backend\last_market_snapshot.json"
if (-not (Test-Path $snapPath)) {
    Write-Host "ERROR: Snapshot file not found at $snapPath"
    exit 1
}

$snap = Get-Content $snapPath -Raw | ConvertFrom-Json

Write-Host "=== SNAPSHOT STATUS ==="
Write-Host "Mode:       $($snap.selectionMeta.mode)"
Write-Host "Stocks:     $(@($snap.stocks).Count)"
Write-Host "UpdatedAt:  $($snap.updatedAt)"
Write-Host "DataDate:   $($snap.selectionMeta.dataDate)"
Write-Host ""

# Check Nifty macro in snapshot
Write-Host "=== MACRO DATA (morning) ==="
$morning = $snap.macroDataStrip.morning
if ($morning) {
    foreach ($row in $morning) {
        Write-Host "  $($row.label) = $($row.val) $($row.delta) [$($row.state)]"
    }
} else {
    Write-Host "  No morning data"
}

Write-Host ""
Write-Host "=== GLOBAL MACRO ==="
$global = $snap.globalMacro
if ($global) {
    foreach ($idx in $global.indices) {
        Write-Host "  $($idx.label) = $($idx.val) $($idx.delta) [$($idx.state)]"
    }
    foreach ($cmdty in $global.commodities) {
        Write-Host "  $($cmdty.label) = $($cmdty.val) $($cmdty.delta) [$($cmdty.state)]"
    }
}

Write-Host ""
Write-Host "=== TOP 5 STOCKS ==="
$topStocks = $snap.stocks | Select-Object -First 5
foreach ($s in $topStocks) {
    Write-Host "  $($s.ticker): LTP=$($s.ltp) delta=$($s.delta) state=$($s.state) score=$($s.score)"
}

Write-Host ""
Write-Host "=== TICKER COUNT in stockQuotes ==="
$qcount = if ($snap.stockQuotes) { @($snap.stockQuotes.PSObject.Properties).Count } else { 0 }
Write-Host "  StockQuotes count: $qcount"