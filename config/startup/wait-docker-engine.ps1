# Wait until Docker Desktop engine accepts API calls.
$ErrorActionPreference = "Continue"
$deadline = (Get-Date).AddMinutes(3)

while ((Get-Date) -lt $deadline) {
    try {
        & docker info 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) {
            $server = & docker version --format "{{.Server.Version}}" 2>$null
            if ($server) {
                Write-Host "[OK] Docker engine ready ($server)"
                exit 0
            }
        }
    } catch {
        # keep waiting
    }
    Write-Host "[*] Waiting for Docker engine..."
    Start-Sleep -Seconds 4
}

Write-Host "[FAIL] Docker engine did not start in time"
exit 1
