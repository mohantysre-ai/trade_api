# Pack host desk JSON into config/docker/desk-state/seed for the Hub state image.
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Seed = Join-Path $Root "config\docker\desk-state\seed"
New-Item -ItemType Directory -Force -Path $Seed | Out-Null

$names = @(
    "intraday_session.json",
    "swing_session.json",
    "last_market_snapshot.json",
    "fixed_trade_plan.json",
    "alert_history.json",
    "trade_api_snapshot.json"
)

Get-ChildItem -Path $Seed -File -Filter "*.json" -ErrorAction SilentlyContinue |
    Remove-Item -Force

$packed = @()
foreach ($name in $names) {
    $src = Join-Path $Root $name
    if (-not (Test-Path -LiteralPath $src)) {
        $alt = Join-Path $Root "backend\app\services\$name"
        if (Test-Path -LiteralPath $alt) { $src = $alt }
    }
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Host "  skip $name (missing)"
        continue
    }
    Copy-Item -LiteralPath $src -Destination (Join-Path $Seed $name) -Force
    $len = (Get-Item -LiteralPath $src).Length
    $packed += @{ name = $name; bytes = $len }
    Write-Host ("  packed {0} ({1:N1} KB)" -f $name, ($len / 1KB))
}

$manifest = [ordered]@{
    packedAtUtc = [DateTime]::UtcNow.ToString("o")
    host        = $env:COMPUTERNAME
    files       = $packed
}
$manifestPath = Join-Path $Seed "manifest.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "  wrote manifest.json ($($packed.Count) files)"

if ($packed.Count -eq 0) {
    Write-Host "[WARN] No desk JSON found - Hub state image will be empty seed."
}
