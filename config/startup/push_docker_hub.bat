@echo off
REM ============================================================
REM IROS — Build and push Hub images (all machines pull these)
REM ============================================================
REM Images:
REM   smohanty010620/iros-market-api
REM   smohanty010620/iros-frontend
REM   smohanty010620/cloudflared   (tunnel run baked in; no secrets)
REM   smohanty010620/iros-desk-state  (desk JSON snapshot — Hub has no volumes)
REM
REM   smohanty010620/sigq-runtime-private  (PRIVATE ONLY - backend/.env,
REM     Cloudflare credentials.json, live volume snapshot)
REM
REM sigq-runtime-private must already exist on Docker Hub as a PRIVATE repo
REM before this script's first run - create it once at hub.docker.com.
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"
set HUB=smohanty010620

where docker >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker CLI not found.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker engine is not running. Start Docker Desktop first.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo ================================================
echo Push IROS images to Docker Hub ^(%HUB%^)
echo ================================================
echo.

pushd "%PROJECT_ROOT%"

echo [*] Packing desk JSON into iros-desk-state seed...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%pack-desk-state.ps1"
if errorlevel 1 (
    echo [FAIL] pack-desk-state failed
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [*] Packing backend/.env + Cloudflare credentials + live volumes into sigq-runtime-private seed...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%pack-runtime-private.ps1"
if errorlevel 1 (
    echo [FAIL] pack-runtime-private failed
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [*] Building stack images ^(including cloudflared + desk-state + runtime-private^)...
docker compose --profile tunnel --profile desk-state --profile runtime-private build
if errorlevel 1 (
    echo [FAIL] build failed
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo.
echo [*] Pushing %HUB%/iros-market-api:latest ...
docker push %HUB%/iros-market-api:latest
if errorlevel 1 goto :pushfail

echo [*] Pushing %HUB%/iros-frontend:latest ...
docker push %HUB%/iros-frontend:latest
if errorlevel 1 goto :pushfail

echo [*] Pushing %HUB%/cloudflared:latest ...
docker push %HUB%/cloudflared:latest
if errorlevel 1 goto :pushfail

echo [*] Pushing %HUB%/iros-desk-state:latest ...
docker push %HUB%/iros-desk-state:latest
if errorlevel 1 goto :pushfail

echo.
echo [*] Pushing %HUB%/sigq-runtime-private:latest ^(PRIVATE REPO ONLY - live secrets^)...
docker push %HUB%/sigq-runtime-private:latest
if errorlevel 1 (
    echo [FAIL] If this is the first push, create %HUB%/sigq-runtime-private
    echo            on hub.docker.com FIRST and set its Visibility to Private.
    echo            Hub creates repos as Public by default on first push otherwise,
    echo            which would expose backend/.env and the Cloudflare token.
    popd
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

popd
echo.
echo [PASS] Hub images updated, including the private runtime bundle.
echo     Other machine: double-click start-from-hub.bat - it pulls everything,
echo     including backend/.env and Cloudflare credentials, automatically.
echo.
if "%IROS_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:pushfail
echo [FAIL] docker push failed — run: docker login
popd
if not "%IROS_NO_PAUSE%"=="1" pause
exit /b 1
