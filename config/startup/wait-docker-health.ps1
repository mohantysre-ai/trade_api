# Poll HTTP health endpoints until the Docker stack is ready.
$ErrorActionPreference = "Continue"

$checks = @(
    @{ Name = "AI News";    Uri = "http://127.0.0.1:8001/health" },
    @{ Name = "Market API"; Uri = "http://127.0.0.1:8000/health" },
    @{ Name = "Frontend";   Uri = "http://127.0.0.1:3000/" }
)

$deadline = (Get-Date).AddSeconds(300)
$allOk = $true

foreach ($check in $checks) {
    Write-Host "[*] Waiting for $($check.Name) ($($check.Uri))..."
    $ready = $false

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $check.Uri -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -lt 500) {
                Write-Host "[OK] $($check.Name) healthy"
                $ready = $true
                break
            }
        } catch {
            # keep waiting
        }
        Start-Sleep -Seconds 3
    }

    if (-not $ready) {
        Write-Host "[FAIL] $($check.Name) not healthy in time"
        $allOk = $false
    }
}

if (-not $allOk) { exit 1 }
exit 0
