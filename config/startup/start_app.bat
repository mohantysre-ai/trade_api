@echo off
REM IROS Trade API - One-command Launcher (Backend + AI News + Frontend)
REM Starts services as background processes with pre-flight and post-flight validation.

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
REM Normalize PROJECT_ROOT (remove trailing backslash)
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set BACKEND_DIR=%PROJECT_ROOT%\backend
set AI_NEWS_BACKEND_DIR=%PROJECT_ROOT%\iros-terminal\backend
set FRONTEND_DIR=%PROJECT_ROOT%\iros-terminal
set VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe

cls
echo ================================================
echo IROS Trade API - Start App (Background Mode)
echo ================================================
echo.
echo [*] Target services:
echo     Market API:   http://localhost:8000
echo     AI News API:  http://localhost:8001
echo     Frontend:     http://localhost:3000
echo.

REM =========================================================
REM PRE-FLIGHT VALIDATION: Check if ports are already in use
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

REM =========================================================
REM LAUNCH SERVICES
REM =========================================================

REM Pick python executable
if exist "%VENV_PYTHON%" (
  set PYTHON_EXE=%VENV_PYTHON%
) else (
  set PYTHON_EXE=python
)

REM Start Market API Backend in background
echo [*] Starting Market API Backend on port 8000...
powershell -NoProfile -Command "Start-Process -FilePath \"%PYTHON_EXE%\" -ArgumentList \"-m\", \"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\" -WorkingDirectory \"%BACKEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

REM Start AI News Backend in background
echo [*] Starting AI News Backend on port 8001...
powershell -NoProfile -Command "Start-Process -FilePath \"%PYTHON_EXE%\" -ArgumentList \"-m\", \"uvicorn\", \"app.services.ai_news_server:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8001\" -WorkingDirectory \"%BACKEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

REM =========================================================
REM FRONTEND PREPARATION: Clear Next.js cache to fix SWC errors
REM =========================================================
if exist "%FRONTEND_DIR%\.next" (
    echo [*] Clearing Next.js build cache...
    rd /s /q "%FRONTEND_DIR%\.next"
)

powershell -NoProfile -Command "Start-Sleep -Seconds 5"

REM Start Frontend in background
echo [*] Starting Frontend on port 3000...
powershell -NoProfile -Command "Start-Process -FilePath \"cmd.exe\" -ArgumentList \"/c\", \"npx next dev --turbo --hostname 0.0.0.0 --port 3000\" -WorkingDirectory \"%FRONTEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

echo.

REM =========================================================
REM POST-FLIGHT VALIDATION: Health + data smoke tests
REM =========================================================
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
echo ================================================
set HEALTHY_COUNT=3
set TOTAL_COUNT=3
echo Result: ALL %TOTAL_COUNT%/%TOTAL_COUNT% services healthy and data verified -- ^> ^> ALL OK ^< ^<
echo ================================================
echo.
echo Market API:   http://localhost:8000
echo AI News API:  http://localhost:8001
echo Frontend:     http://localhost:3000
echo.

if "%IROS_NO_PAUSE%"=="1" exit /b %HEALTHY_COUNT%
pause
exit /b %HEALTHY_COUNT%
