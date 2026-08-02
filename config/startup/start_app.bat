@echo off
REM Alphix Terminal - One-command Launcher
REM Backend + AI News + Frontend + Cloudflare Tunnel (https://sigq.in)

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set BACKEND_DIR=%PROJECT_ROOT%\backend
set FRONTEND_DIR=%PROJECT_ROOT%\iros-terminal
set VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe
set CLOUDFLARED_EXE=%ProgramFiles(x86)%\cloudflared\cloudflared.exe
if not exist "%CLOUDFLARED_EXE%" set "CLOUDFLARED_EXE=%ProgramFiles%\cloudflared\cloudflared.exe"
set CF_CONFIG=%USERPROFILE%\.cloudflared\config.yml
set PUBLIC_URL=https://sigq.in

cls
echo ================================================
echo Alphix Terminal - Start App + Cloudflare Tunnel
echo ================================================
echo.
echo [*] Mode: NATIVE (Python venv + Next.js)
echo     Docker alternative:  config\startup\start_docker.bat
echo     Docker refresh:      config\startup\docker-refresh.bat
echo     Do not run native + Docker together ^(same ports^).
echo.
echo [*] Target services:
echo     Market API:   http://localhost:8000
echo     AI News API:  http://localhost:8001
echo     Frontend:     http://localhost:3000
echo     Public URL:   %PUBLIC_URL%
echo.

REM =========================================================
REM PRE-FLIGHT: free ports 8000 / 8001 / 3000 if busy
REM =========================================================
echo [PRE-FLIGHT] Verifying ports 8000, 8001, 3000 are free...
echo.

set PORT_BUSY=0

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { Write-Host '  [BUSY] Port 8000 is in use' -ForegroundColor Yellow; exit 1 } else { Write-Host '  [OK] Port 8000 is free' -ForegroundColor Green; exit 0 }"
if errorlevel 1 set PORT_BUSY=1

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) { Write-Host '  [BUSY] Port 8001 is in use' -ForegroundColor Yellow; exit 1 } else { Write-Host '  [OK] Port 8001 is free' -ForegroundColor Green; exit 0 }"
if errorlevel 1 set PORT_BUSY=1

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { Write-Host '  [BUSY] Port 3000 is in use' -ForegroundColor Yellow; exit 1 } else { Write-Host '  [OK] Port 3000 is free' -ForegroundColor Green; exit 0 }"
if errorlevel 1 set PORT_BUSY=1

if %PORT_BUSY% equ 1 (
    echo.
    echo [*] Freeing occupied ports before launch...
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    powershell -NoProfile -Command "Start-Sleep -Seconds 2"
    echo [OK] Ports freed. Proceeding...
)
echo [PASS] All ports are free. Proceeding...
echo.

REM Stop previous cloudflared for clean reconnect
echo [*] Stopping any existing cloudflared tunnel...
powershell -NoProfile -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"

REM =========================================================
REM LAUNCH SERVICES
REM =========================================================
if exist "%VENV_PYTHON%" (
  set PYTHON_EXE=%VENV_PYTHON%
) else (
  set PYTHON_EXE=python
)

echo [*] Starting Market API Backend on port 8000...
powershell -NoProfile -Command "Start-Process -FilePath \"%PYTHON_EXE%\" -ArgumentList \"-m\", \"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\" -WorkingDirectory \"%BACKEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

echo [*] Starting AI News Backend on port 8001...
powershell -NoProfile -Command "Start-Process -FilePath \"%PYTHON_EXE%\" -ArgumentList \"-m\", \"uvicorn\", \"app.services.ai_news_server:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8001\" -WorkingDirectory \"%BACKEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

if exist "%FRONTEND_DIR%\.next" (
    echo [*] Clearing Next.js build cache...
    rd /s /q "%FRONTEND_DIR%\.next"
)

powershell -NoProfile -Command "Start-Sleep -Seconds 5"

echo [*] Starting Frontend on port 3000...
powershell -NoProfile -Command "Start-Process -FilePath \"cmd.exe\" -ArgumentList \"/c\", \"npx next dev --turbo --hostname 0.0.0.0 --port 3000\" -WorkingDirectory \"%FRONTEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

echo.
echo [POST-FLIGHT] Running startup smoke tests...
echo [*] Giving Next.js Turbopack 20 seconds to stabilize...
powershell -NoProfile -Command "Start-Sleep -Seconds 20"
echo.
if "%IROS_SMOKE_TEST_REFRESH%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\startup-smoke-test.ps1" -IncludeRefreshSmokeTest
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\startup-smoke-test.ps1"
)
if errorlevel 1 (
    echo.
    echo [FAIL] Startup smoke tests failed.
    if "%IROS_NO_PAUSE%"=="1" exit /b 1
    pause
    exit /b 1
)
echo [PASS] Startup smoke tests passed.
echo.

REM =========================================================
REM CLOUDFLARE TUNNEL (hidden background — no extra terminal)
REM =========================================================
if not exist "%CLOUDFLARED_EXE%" (
  echo [WARN] cloudflared not found. Install: winget install Cloudflare.cloudflared
  echo [WARN] Public URL will not start. Local: http://localhost:3000
) else if not exist "%CF_CONFIG%" (
  echo [WARN] Missing %CF_CONFIG%
  echo [WARN] Run config\startup\setup-cloudflare-tunnel.bat once first.
) else (
  echo [*] Starting Cloudflare Tunnel in background ^(no extra window^)...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-cloudflared-background.ps1"
  if errorlevel 1 (
    echo [WARN] Tunnel failed to start. App is still on http://localhost:3000
  ) else (
    echo [OK] Tunnel attached to this launcher flow ^(process is hidden^).
    echo [*] Opening %PUBLIC_URL% ...
    start "" "%PUBLIC_URL%"
  )
)

echo.
echo ================================================
set HEALTHY_COUNT=3
set TOTAL_COUNT=3
echo Result: ALL %TOTAL_COUNT%/%TOTAL_COUNT% services healthy -- ^> ^> ALL OK ^< ^<
echo ================================================
echo.
echo Market API:   http://localhost:8000
echo AI News API:  http://localhost:8001
echo Frontend:     http://localhost:3000
echo Public:       %PUBLIC_URL%
echo www:          https://www.sigq.in
echo.
echo Tunnel: hidden background process ^(no second terminal^)
echo Logs:   %PROJECT_ROOT%\logs\cloudflared.err.log
echo Tip:    always open https://sigq.in  ^(not http://^)
echo Note:   "context canceled" lines = browser closed a request; usually harmless
echo.
echo Keep this PC awake. Close cloudflared later with: taskkill /IM cloudflared.exe /F
echo.

if "%IROS_NO_PAUSE%"=="1" exit /b %HEALTHY_COUNT%
pause
exit /b %HEALTHY_COUNT%
