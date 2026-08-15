@echo off
REM ============================================================
REM IROS — Build + start app via Docker Compose
REM ============================================================
REM Alternative to start_app.bat (native Python + Next).
REM Do NOT run both at once — same ports 8000 / 8001 / 3000.
REM Cloudflare Tunnel runs as container iros-cloudflared (not host cloudflared).
REM
REM Usage:
REM   start_docker.bat              build + start + wait healthy
REM   start_docker.bat --no-build   start only (reuse local images)
REM   start_docker.bat --pull       pull Hub images, then start (other machines)
REM   start_docker.bat --no-open    do not open browser
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"

set DO_BUILD=1
set DO_PULL=0
set DO_OPEN=1
for %%A in (%*) do (
    if /i "%%~A"=="--no-build" set DO_BUILD=0
    if /i "%%~A"=="--pull" (
        set DO_BUILD=0
        set DO_PULL=1
    )
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
        echo [FAIL] Docker Desktop not found. Install it, then retry.
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
    echo [FAIL] Missing backend\.env — copy backend\.env.example and fill secrets.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

cls
echo ================================================
echo Alphix Terminal — Docker Compose build + start
echo ================================================
echo.
echo [*] Native alternative:  start-app.bat
echo [*] Refresh later with:  docker-refresh.bat  ^(or refresh-data.bat^)
echo [*] Stop with:           config\startup\stop_docker.bat
echo.
echo [*] Target:
echo     Market API:   http://localhost:8000
echo     AI News API:  http://localhost:8001
echo     Frontend:     http://localhost:3000
echo     Public:       https://sigq.in  ^(cloudflared container^)
echo.

echo [PRE-FLIGHT] Checking ports 8000, 8001, 3000...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%free-native-ports.ps1"
echo.

REM Host cloudflared conflicts with the same tunnel name inside Docker
echo [*] Stopping host cloudflared ^(tunnel runs in Docker^)...
powershell -NoProfile -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"

set "COMPOSE_PROFILES="
echo [*] Preparing Cloudflare Tunnel for Docker...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%prepare-docker-tunnel.ps1"
if errorlevel 1 (
    echo [WARN] Tunnel credentials missing — stack will start without public URL.
    echo        One-time setup: config\startup\setup-cloudflare-tunnel.bat
) else (
    set "COMPOSE_PROFILES=--profile tunnel"
    echo [OK] Tunnel profile enabled ^(iros-cloudflared^).
)
echo.

pushd "%PROJECT_ROOT%"
if %DO_PULL% equ 1 (
    echo [*] docker compose %COMPOSE_PROFILES% pull ...
    docker compose %COMPOSE_PROFILES% pull
    if errorlevel 1 (
        echo [FAIL] docker compose pull failed — docker login, or run push-docker-hub.bat on the build PC.
        popd
        if not "%IROS_NO_PAUSE%"=="1" pause
        exit /b 1
    )
    echo [*] docker compose %COMPOSE_PROFILES% up -d ...
    docker compose %COMPOSE_PROFILES% up -d
) else if %DO_BUILD% equ 1 (
    echo [*] docker compose %COMPOSE_PROFILES% up -d --build ...
    echo     ^(first build can take several minutes^)
    docker compose %COMPOSE_PROFILES% up -d --build
) else (
    echo [*] docker compose %COMPOSE_PROFILES% up -d ...
    docker compose %COMPOSE_PROFILES% up -d
)
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% neq 0 (
    echo [FAIL] docker compose failed ^(exit %EXIT_CODE%^).
    echo        Logs: docker compose logs --tail=80
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b %EXIT_CODE%
)

echo.
echo [*] Waiting for container health ^(up to ~3 min^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%wait-docker-health.ps1"
set HEALTH_CODE=%ERRORLEVEL%

echo.
docker compose %COMPOSE_PROFILES% ps
popd

if %HEALTH_CODE% neq 0 (
    echo.
    echo [FAIL] Stack started but health checks did not pass.
    echo        Inspect: docker compose logs --tail=100
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo.
echo [PASS] Stack is up and healthy.
echo     UI:      http://localhost:3000
echo     Public:  https://sigq.in
echo     Health:  http://localhost:8000/health
echo     Refresh: docker-refresh.bat
echo     Stop:    config\startup\stop_docker.bat
echo     Tunnel:  docker compose logs -f cloudflared
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
