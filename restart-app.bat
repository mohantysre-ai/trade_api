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
echo [*] Running health checks...
timeout /t 5 /nobreak >nul

echo [*] Checking Market API (port 8000)...
for /f %%i in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 5; exit 0 } catch { exit 1 }" 2^>nul') do set HEALTH=%%i
if %errorlevel% equ 0 ( echo     Market API: OK ) else ( echo     Market API: FAILED )

echo [*] Checking AI News API (port 8001)...
for /f %%i in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8001/health' -UseBasicParsing -TimeoutSec 5; exit 0 } catch { exit 1 }" 2^>nul') do set HEALTH=%%i
if %errorlevel% equ 0 ( echo     AI News API: OK ) else ( echo     AI News API: FAILED )

echo [*] Checking Frontend (port 3000)...
for /f %%i in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 5; exit 0 } catch { exit 1 }" 2^>nul') do set HEALTH=%%i
if %errorlevel% equ 0 ( echo     Frontend: OK ) else ( echo     Frontend: FAILED )

echo.
echo ================================================
echo Restart command completed.
echo Market API:   http://localhost:8000
echo AI News API:  http://localhost:8001
echo Frontend:     http://localhost:3000
echo ================================================
