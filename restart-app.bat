@echo off
REM IROS Trade API - Full system restart
REM Kills existing owners of the app ports, verifies the ports are clear, then starts services.

setlocal enabledelayedexpansion

set PROJECT_ROOT=%~dp0
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

cls
echo ================================================
echo IROS Trade API - Full System Restart
echo ================================================
echo.
echo [*] Checking app ports: 8000, 8001, 3000
echo.

for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports = 8000,8001,3000; Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique"') do (
    echo [*] Found port owner PID %%P
    taskkill /F /T /PID %%P >nul 2>&1
    if errorlevel 1 (
        echo [!] Failed to terminate PID %%P
    ) else (
        echo [*] Terminated PID %%P
    )
)

echo.
echo [*] Waiting up to 15 seconds for ports 8000, 8001, and 3000 to clear...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports = 8000,8001,3000; $deadline = (Get-Date).AddSeconds(15); do { $busy = @(); foreach ($port in $ports) { if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { $busy += $port } }; if ($busy.Count -eq 0) { exit 0 }; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); Write-Host ('Ports still active: ' + (($busy | Sort-Object -Unique) -join ', ')); exit 1"
if errorlevel 1 (
    echo.
    echo [!] Restart aborted: one or more ports did not clear.
    exit /b 1
)

echo [*] Ports cleared.
echo.
echo [*] Starting services with start_app.bat...
set IROS_NO_PAUSE=1
call "%PROJECT_ROOT%\start_app.bat"
if errorlevel 1 (
    echo.
    echo [!] start_app.bat failed.
    exit /b %errorlevel%
)

echo.
echo ================================================
echo Restart command completed.
echo Market API:   http://localhost:8000
echo AI News API:  http://localhost:8001
echo Frontend:     http://localhost:3000
echo ================================================
