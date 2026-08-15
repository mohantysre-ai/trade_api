@echo off
REM ============================================================
REM IROS — Rebuild Docker images after code changes
REM ============================================================
REM Use this whenever backend/ or iros-terminal/ (or compose) code changes.
REM Builds fresh images, recreates containers, deletes old dangling images.
REM
REM Usage:
REM   rebuild_docker.bat              no-cache rebuild + restart + prune
REM   rebuild_docker.bat --cached     reuse layer cache (faster)
REM   rebuild_docker.bat --no-open    skip opening browser
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"

set NO_CACHE=1
set DO_OPEN=1
for %%A in (%*) do (
    if /i "%%~A"=="--cached" set NO_CACHE=0
    if /i "%%~A"=="--no-open" set DO_OPEN=0
)

where docker >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker CLI not found. Install Docker Desktop first.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [WARN] Docker daemon not running — launching Docker Desktop...
    if not exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
        echo [FAIL] Docker Desktop not found.
        if not "%IROS_NO_PAUSE%"=="1" pause
        exit /b 1
    )
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%wait-docker-engine.ps1"
    if errorlevel 1 (
        if not "%IROS_NO_PAUSE%"=="1" pause
        exit /b 1
    )
)

if not exist "%PROJECT_ROOT%\backend\.env" (
    echo [FAIL] Missing backend\.env
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

cls
echo ================================================
echo Alphix — REBUILD Docker images ^(code change^)
echo ================================================
echo.
echo [*] This replaces running containers with newly built images
echo     and deletes dangling/old unused images afterward.
echo.

echo [1/5] Stopping host cloudflared + preparing tunnel...
powershell -NoProfile -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"
set "COMPOSE_PROFILES="
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%prepare-docker-tunnel.ps1"
if errorlevel 1 (
    echo [WARN] Tunnel credentials missing — rebuild without public URL.
) else (
    set "COMPOSE_PROFILES=--profile tunnel"
    echo [OK] Tunnel profile enabled.
)
echo.

pushd "%PROJECT_ROOT%"

echo [2/5] Stopping stack ^(volumes kept^)...
docker compose --profile tunnel down --remove-orphans
echo.

echo [3/5] Building new images...
if %NO_CACHE% equ 1 (
    echo     mode: --no-cache ^(full rebuild^)
    docker compose --profile tunnel build --no-cache --pull
) else (
    echo     mode: cached layers
    docker compose --profile tunnel build --pull
)
set BUILD_CODE=%ERRORLEVEL%
if %BUILD_CODE% neq 0 (
    echo [FAIL] docker compose build failed ^(exit %BUILD_CODE%^).
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b %BUILD_CODE%
)
echo.

echo [4/5] Starting stack with new images...
docker compose %COMPOSE_PROFILES% up -d --force-recreate --remove-orphans
set UP_CODE=%ERRORLEVEL%
if %UP_CODE% neq 0 (
    echo [FAIL] docker compose up failed ^(exit %UP_CODE%^).
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b %UP_CODE%
)

echo.
echo [*] Waiting for health...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%wait-docker-health.ps1"
set HEALTH_CODE=%ERRORLEVEL%

echo.
echo [5/5] Deleting old/dangling images...
docker image prune -f
REM Drop untagged leftovers from previous iros builds
for /f "tokens=*" %%I in ('docker images -f "dangling=true" -q 2^>nul') do docker rmi -f %%I >nul 2>&1

echo.
echo [*] Current IROS images:
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}" | findstr /i "iros REPOSITORY cloudflare"
echo.
docker compose %COMPOSE_PROFILES% ps
popd

if %HEALTH_CODE% neq 0 (
    echo.
    echo [FAIL] Rebuild finished but health checks did not pass.
    echo        Inspect: docker compose logs --tail=100
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo.
echo [PASS] New images built, old dangling images removed, stack healthy.
echo     UI:      http://localhost:3000
echo     Public:  https://sigq.in
echo     Tip:     after ANY code change affecting containers, run rebuild-docker.bat
echo.

if %DO_OPEN% equ 1 (
    if defined COMPOSE_PROFILES (
        start "" "https://sigq.in"
    ) else (
        start "" "http://localhost:3000"
    )
)

if "%IROS_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0
