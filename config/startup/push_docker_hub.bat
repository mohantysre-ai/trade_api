@echo off
REM ============================================================
REM IROS — Build and push Hub images (all machines pull these)
REM ============================================================
REM Images:
REM   smohanty010620/iros-market-api
REM   smohanty010620/iros-frontend
REM   smohanty010620/cloudflared   (tunnel run baked in; no secrets)
REM
REM Does NOT push credentials.json or backend/.env
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

echo [*] Building stack images ^(including cloudflared^)...
docker compose --profile tunnel build
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

popd
echo.
echo [PASS] Hub images updated.
echo     Other machine: start-from-hub.bat
echo     ^(needs backend\.env + config\cloudflare\credentials.json^)
echo.
if "%IROS_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:pushfail
echo [FAIL] docker push failed — run: docker login
popd
if not "%IROS_NO_PAUSE%"=="1" pause
exit /b 1
