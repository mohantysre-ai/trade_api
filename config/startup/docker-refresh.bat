@echo off
REM ============================================================
REM IROS — On-demand refresh against Docker stack
REM ============================================================
REM Requires containers from start_docker.bat / docker compose.
REM Delegates to refresh-data-on-demand.bat (same HTTP API on :8000).
REM
REM Usage:
REM   docker-refresh.bat
REM   docker-refresh.bat --skip-news
REM   docker-refresh.bat --pool "Nifty 500"
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set REFRESH_BAT=%SCRIPT_DIR%refresh-data-on-demand.bat
set CALLER_NO_PAUSE=%IROS_NO_PAUSE%

REM Ensure docker CLI is on PATH (Docker Desktop)
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"

where docker >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker CLI not found. Install/start Docker Desktop first.
    if not "%CALLER_NO_PAUSE%"=="1" pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker daemon not running. Start Docker Desktop, then retry.
    if not "%CALLER_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo ================================================
echo IROS — Docker on-demand data refresh
echo ================================================
echo.

pushd "%PROJECT_ROOT%"
docker compose ps --status running 2>nul | findstr /i "iros-market-api" >nul
if errorlevel 1 (
    echo [FAIL] iros-market-api is not running.
    echo        Start stack first:  config\startup\start_docker.bat
    echo        Or:                 docker compose up -d
    popd
    if not "%CALLER_NO_PAUSE%"=="1" pause
    exit /b 1
)
popd

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 8; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo [FAIL] Market API http://127.0.0.1:8000/health not reachable.
    echo        Check: docker compose logs market-api
    if not "%CALLER_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [OK] Docker Market API is healthy — running refresh...
echo.

REM Nested refresh should not double-pause; restore caller preference after
set IROS_NO_PAUSE=1
call "%REFRESH_BAT%" %*
set EXIT_CODE=!ERRORLEVEL!
set IROS_NO_PAUSE=%CALLER_NO_PAUSE%

echo.
if !EXIT_CODE! equ 0 (
    echo [PASS] Docker on-demand refresh finished.
) else (
    echo [FAIL] Refresh exited with code !EXIT_CODE!.
)

if not "%CALLER_NO_PAUSE%"=="1" pause
exit /b %EXIT_CODE%
