$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dockerReady = $false
$probeOut = Join-Path $env:TEMP ("iros-docker-probe-" + [guid]::NewGuid().ToString('n') + '.txt')
$probeErr = "$probeOut.err"
try {
    $probe = Start-Process -FilePath 'docker' -ArgumentList @('info', '--format', '{{.ServerVersion}}') -RedirectStandardOutput $probeOut -RedirectStandardError $probeErr -WindowStyle Hidden -PassThru
    if ($probe.WaitForExit(10000)) {
        $dockerReady = $probe.ExitCode -eq 0
    } else {
        Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue
    }
} catch {
    $dockerReady = $false
} finally {
    Remove-Item -LiteralPath $probeOut, $probeErr -Force -ErrorAction SilentlyContinue
}

Push-Location $Root
try {
    if ($dockerReady) {
        & (Join-Path $PSScriptRoot 'pack-desk-state.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'State pack failed.' }
        docker compose --profile tunnel stop market-api ai-news frontend cloudflared 2>$null | Out-Null
    }
    & (Join-Path $PSScriptRoot 'apply-packed-desk-state-native.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Native state reconciliation failed.' }
} finally {
    Pop-Location
}
