param(
    [string]$BaseUrl = "http://127.0.0.1:8014",
    [string]$FrontendUrl = "http://127.0.0.1:3000",
    [ValidateSet("smoke", "load", "stress")][string]$Profile = "load",
    [switch]$AllowWrites,
    [switch]$SkipBackendTests,
    [switch]$SkipFrontendChecks,
    [switch]$SkipRealtime,
    [switch]$SkipUi
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$Reports = Join-Path $PSScriptRoot "reports"
New-Item -ItemType Directory -Path $Reports -Force | Out-Null
$env:LOAD_BASE_URL = $BaseUrl
$env:FRONTEND_URL = $FrontendUrl

if ($AllowWrites) {
    if ($BaseUrl -notmatch '^http://(127\.0\.0\.1|localhost)(:\d+)?$') { throw "Write load requires a loopback BaseUrl" }
    if ($env:QA_ISOLATED_STATE -ne "true") { throw "Set QA_ISOLATED_STATE=true and redirect mutable state before write load" }
    if ($env:QA_CONFIRM_WRITE_LOAD -ne "I_UNDERSTAND_THIS_MUTATES_TEST_STATE") { throw "Missing QA_CONFIRM_WRITE_LOAD confirmation" }
}

$Results = [ordered]@{}
if (-not $SkipBackendTests) {
    Push-Location (Join-Path $RepoRoot "backend")
    try {
        $env:PYTHONPATH = Join-Path $RepoRoot "backend"
        & $Python -m pytest tests -q
        $Results.backendTests = $LASTEXITCODE
    } finally { Pop-Location }
}
if (-not $SkipFrontendChecks) {
    Push-Location (Join-Path $RepoRoot "iros-terminal")
    try {
        npm run lint
        $Results.frontendLint = $LASTEXITCODE
        npm run build
        $Results.frontendBuild = $LASTEXITCODE
    } finally { Pop-Location }
}

Push-Location $RepoRoot
try {
    $LoadArgs = @("performance/market_load_test.py", "--base-url", $BaseUrl, "--profile", $Profile, "--output", "performance/reports/load-report.json")
    if ($AllowWrites) { $LoadArgs += "--allow-writes" }
    & $Python @LoadArgs
    $Results.load = $LASTEXITCODE
    if (-not $SkipRealtime) {
        & $Python performance/realtime_validation.py --base-url $BaseUrl --output performance/reports/realtime-report.json
        $Results.realtime = $LASTEXITCODE
    }
    if (-not $SkipUi) {
        Push-Location performance
        try {
            npm run ui
            $Results.ui = $LASTEXITCODE
        } finally { Pop-Location }
    }
} finally { Pop-Location }

$SummaryPath = Join-Path $Reports "execution-summary.json"
$Results | ConvertTo-Json | Set-Content -Path $SummaryPath -Encoding utf8
$Results | ConvertTo-Json
if (($Results.Values | Where-Object { $_ -ne 0 }).Count -gt 0) { exit 1 }
