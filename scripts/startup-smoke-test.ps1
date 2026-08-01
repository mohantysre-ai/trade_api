param(
    [int] $BackendTimeoutSec = 120,
    [int] $FrontendTimeoutSec = 120,
    [switch] $IncludeRefreshSmokeTest
)

$ErrorActionPreference = "Stop"

function Invoke-GetJson {
    param(
        [string] $Uri,
        [int] $TimeoutSec = 30
    )

    $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "HTTP $($response.StatusCode) from $Uri"
    }
    return $response.Content | ConvertFrom-Json
}

function Wait-Http {
    param(
        [string] $Uri,
        [int] $TimeoutSec = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -lt 500) {
                return $response
            }
        } catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Seconds 2
    }

    throw "Timed out waiting for $Uri. Last error: $lastError"
}

function Assert-True {
    param(
        [bool] $Condition,
        [string] $Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Count-ObjectProperties {
    param([object] $Value)

    if ($null -eq $Value) {
        return 0
    }
    if ($Value -is [System.Collections.IDictionary]) {
        return $Value.Count
    }
    return @($Value.PSObject.Properties).Count
}

Write-Host "[SMOKE] Waiting for Market API health..."
Wait-Http -Uri "http://127.0.0.1:8000/health" -TimeoutSec 120 | Out-Null
Write-Host "[SMOKE] Market API health OK"

Write-Host "[SMOKE] Waiting for AI News API health..."
Wait-Http -Uri "http://127.0.0.1:8001/health" -TimeoutSec 60 | Out-Null
Write-Host "[SMOKE] AI News API health OK"

Write-Host "[SMOKE] Waiting for Frontend..."
Wait-Http -Uri "http://127.0.0.1:3000/" -TimeoutSec 240 | Out-Null
Write-Host "[SMOKE] Frontend health OK"

Write-Host "[SMOKE] Validating backend market-data payload..."
$backendData = Invoke-GetJson -Uri "http://127.0.0.1:8000/api/market-data?pool=Nifty%20100" -TimeoutSec $BackendTimeoutSec
Assert-True ($backendData.success -eq $true) "Backend market-data returned success=false"
Assert-True ((@($backendData.stocks) | Measure-Object).Count -gt 0) "Backend market-data returned no stocks"
Assert-True ((Count-ObjectProperties $backendData.stockQuotes) -gt 0) "Backend market-data returned no stockQuotes"
Assert-True ($null -ne $backendData.updatedAt) "Backend market-data did not return updatedAt"
Write-Host "[SMOKE] Backend market-data OK: stocks=$((@($backendData.stocks) | Measure-Object).Count), quotes=$(Count-ObjectProperties $backendData.stockQuotes)"

Write-Host "[SMOKE] Validating frontend market-data proxy payload..."
$frontendData = Invoke-GetJson -Uri "http://127.0.0.1:3000/api/market-data?pool=Nifty%20100" -TimeoutSec $FrontendTimeoutSec
Assert-True ($frontendData.success -eq $true) "Frontend market-data proxy returned success=false"
Assert-True ((@($frontendData.stocks) | Measure-Object).Count -gt 0) "Frontend market-data proxy returned no stocks"
Assert-True ((Count-ObjectProperties $frontendData.stockQuotes) -gt 0) "Frontend market-data proxy returned no stockQuotes"
Assert-True ($null -ne $frontendData.updatedAt) "Frontend market-data proxy did not return updatedAt"
Write-Host "[SMOKE] Frontend market-data proxy OK: stocks=$((@($frontendData.stocks) | Measure-Object).Count), quotes=$(Count-ObjectProperties $frontendData.stockQuotes)"

if ($IncludeRefreshSmokeTest) {
    Write-Host "[SMOKE] Validating refresh-data-on-demand without ticker-news refresh..."
    $body = @{
        pool = "Nifty 100"
        refreshTickerNews = $false
    } | ConvertTo-Json -Depth 8

    $initResponse = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/api/refresh-data-on-demand" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -UseBasicParsing `
        -TimeoutSec 60

    $initJson = $initResponse.Content | ConvertFrom-Json
    Assert-True ($initJson.success -eq $true) "refresh-data-on-demand POST returned success=false"

    $refreshJson = $null
    if ($initJson.payload) {
        $refreshJson = $initJson
    } else {
        Assert-True ($null -ne $initJson.statusUrl -or $null -ne $initJson.taskId) "refresh-data-on-demand returned no statusUrl or taskId"
        $statusUrl = if ([string]$initJson.statusUrl -like "http*") {
            [string]$initJson.statusUrl
        } elseif ($initJson.statusUrl) {
            "http://127.0.0.1:8000$($initJson.statusUrl)"
        } else {
            $encodedTaskId = [System.Uri]::EscapeDataString([string]$initJson.taskId)
            "http://127.0.0.1:8000/api/refresh-data-on-demand/status?taskId=$encodedTaskId"
        }
        $deadline = (Get-Date).AddSeconds(900)
        while ((Get-Date) -lt $deadline) {
            $statusResponse = Invoke-WebRequest -Uri $statusUrl -UseBasicParsing -TimeoutSec 60
            $statusJson = $statusResponse.Content | ConvertFrom-Json
            if ($statusJson.status -eq "done") {
                $refreshJson = $statusJson.result
                break
            }
            if ($statusJson.status -eq "error" -or $statusJson.status -eq "failed") {
                throw "refresh-data-on-demand failed: $($statusJson.error)"
            }
            if ($statusJson.status -eq "expired") {
                throw "refresh-data-on-demand task expired"
            }
            Start-Sleep -Seconds 3
        }
        if ($null -eq $refreshJson) {
            throw "refresh-data-on-demand timed out after 900s"
        }
    }

    Assert-True ($refreshJson.success -eq $true) "refresh-data-on-demand returned success=false"
    Assert-True ($null -ne $refreshJson.payload) "refresh-data-on-demand returned no payload"
    Assert-True ((@($refreshJson.payload.stocks) | Measure-Object).Count -gt 0) "refresh-data-on-demand returned no stocks"
    Write-Host "[SMOKE] Refresh endpoint OK: stocks=$((@($refreshJson.payload.stocks) | Measure-Object).Count)"
}

Write-Host "[SMOKE] All startup smoke tests passed."
