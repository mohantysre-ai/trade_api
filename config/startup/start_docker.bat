@echo off
REM ============================================================
REM IROS — Start app via Docker Compose
REM ============================================================
REM Alternative to start_app.bat (native Python + Next).
REM Do NOT run both at once — same ports 8000 / 8001 / 3000.
REM
REM Usage:
REM   start_docker.bat           build + start detached
REM   start_docker.bat --no-build   start only (reuse images)
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"

set DO_BUILD=1
if /i "%~1"=="--no-build" set DO_BUILD=0

where docker >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker CLI not found. Install Docker Desktop first.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker daemon not running. Start Docker Desktop, then retry.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

if not exist "%PROJECT_ROOT%\backend\.env" (
    echo [FAIL] Missing backend\.env — copy backend\.env.example and fill secrets.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

cls
echo ================================================
echo Alphix Terminal — Docker Compose start
echo ================================================
echo.
echo [*] Native alternative:  config\startup\start_app.bat
echo [*] Refresh later with:  config\startup\docker-refresh.bat
echo [*] Stop with:           config\startup\stop_docker.bat
echo.
echo [*] Target:
echo     Market API:   http://localhost:8000
echo     AI News API:  http://localhost:8001
echo     Frontend:     http://localhost:3000
echo.

pushd "%PROJECT_ROOT%"
if %DO_BUILD% equ 1 (
    echo [*] docker compose up -d --build ...
    docker compose up -d --build
) else (
    echo [*] docker compose up -d ...
    docker compose up -d
)
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% neq 0 (
    echo [FAIL] docker compose failed.
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b %EXIT_CODE%
)

echo.
echo [*] Waiting for health...
docker compose ps
popd

echo.
echo [PASS] Stack started.
echo     UI:     http://localhost:3000
echo     Health: http://localhost:8000/health
echo     Refresh: config\startup\docker-refresh.bat
echo.

if "%IROS_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0
