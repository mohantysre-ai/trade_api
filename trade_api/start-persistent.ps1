# Persistent IROS Backend & Frontend Launcher
# This script keeps both services running and auto-restarts if they crash

$projectRoot = "d:\trade_api"
$backendDir = "$projectRoot\backend\backend"
$frontendDir = "$projectRoot\iros-terminal"
$venvPython = "$projectRoot\.venv\Scripts\python.exe"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "IROS Trade API - Persistent Server Launcher" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Start Backend Server
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting Backend API (Port 8000)..." -ForegroundColor Green
$backendProcess = Start-Process -FilePath $venvPython `
  -ArgumentList "-m uvicorn angel_one_feed:create_app --reload --host 0.0.0.0 --port 8000" `
  -WorkingDirectory $backendDir `
  -WindowStyle Normal `
  -PassThru

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Backend PID: $($backendProcess.Id)" -ForegroundColor Green

# Wait for backend to be ready
Start-Sleep -Seconds 3

# Start Frontend Server
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting Frontend (Port 3000)..." -ForegroundColor Green
$frontendProcess = Start-Process -FilePath "cmd.exe" `
  -ArgumentList "/k cd /d $frontendDir & npm run dev" `
  -WindowStyle Normal `
  -PassThru

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Frontend PID: $($frontendProcess.Id)" -ForegroundColor Green

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "✓ Both services are running!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backend:  http://localhost:8000" -ForegroundColor Yellow
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Yellow
Write-Host ""
Write-Host "Monitoring processes..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop both services" -ForegroundColor Gray
Write-Host ""

# Monitor and auto-restart on crash
$monitoringInterval = 5  # seconds

while ($true) {
    try {
        # Check if backend is still running
        if ($backendProcess.HasExited) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ⚠ Backend crashed! Restarting..." -ForegroundColor Yellow
            $backendProcess = Start-Process -FilePath $venvPython `
              -ArgumentList "-m uvicorn angel_one_feed:create_app --reload --host 0.0.0.0 --port 8000" `
              -WorkingDirectory $backendDir `
              -WindowStyle Normal `
              -PassThru
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Backend restarted (PID: $($backendProcess.Id))" -ForegroundColor Green
        }

        # Check if frontend is still running
        if ($frontendProcess.HasExited) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Frontend crashed! Restarting..." -ForegroundColor Yellow
            $frontendProcess = Start-Process -FilePath "cmd.exe" `
              -ArgumentList "/k cd /d $frontendDir & npm run dev" `
              -WindowStyle Normal `
              -PassThru
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Frontend restarted (PID: $($frontendProcess.Id))" -ForegroundColor Green
        }

        Start-Sleep -Seconds $monitoringInterval
    }
    catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Error in monitoring: $PSItem" -ForegroundColor Red
        Start-Sleep -Seconds $monitoringInterval
    }
}
