@echo off
REM ============================================================
REM IROS — Stop Docker Compose stack
REM ============================================================

setlocal
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"

where docker >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker CLI not found.
    if not "%IROS_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [*] Stopping Docker stack...
pushd "%PROJECT_ROOT%"
docker compose down
set EXIT_CODE=%ERRORLEVEL%
popd

if %EXIT_CODE% equ 0 (
    echo [OK] Containers stopped. Volumes kept ^(JSON state preserved^).
) else (
    echo [FAIL] docker compose down exited %EXIT_CODE%.
)

if "%IROS_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
