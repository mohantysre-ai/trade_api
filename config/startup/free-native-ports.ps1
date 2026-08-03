# Free ports 8000/8001/3000 only when held by native (non-Docker) processes.
$ErrorActionPreference = "Continue"
$ports = @(8000, 8001, 3000)
$dockerNames = '^(com\.docker|docker-proxy|Docker Desktop|vpnkit)$'
$killed = 0

foreach ($p in $ports) {
    $conns = @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
    if (-not $conns) {
        Write-Host "  [OK] Port $p free"
        continue
    }

    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { "?" }

        if ($name -match $dockerNames) {
            Write-Host "  [OK] Port $p held by Docker ($name) — leave it"
            continue
        }

        Write-Host "  [BUSY] Port $p held by $name (pid $($c.OwningProcess)) — stopping"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        $killed++
    }
}

if ($killed -gt 0) {
    Start-Sleep -Seconds 2
    Write-Host "[OK] Freed $killed native process(es)."
}

exit 0
