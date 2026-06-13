@echo off
REM IROS Trade API - One-command Launcher (Backend + Frontend)
REM Starts services in separate windows (non-persistent).

setlocal enabledelayedexpansion

set PROJECT_ROOT=%~dp0
REM Normalize PROJECT_ROOT (remove trailing backslash)
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set BACKEND_DIR=%PROJECT_ROOT%\backend\backend
set FRONTEND_DIR=%PROJECT_ROOT%\iros-terminal
set VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe

cls
echo ================================================
echo IROS Trade API - Start App (Backend + Frontend)
echo ================================================
echo.
echo [*] Backend:  http://localhost:8000
echo [*] Frontend: http://localhost:3000
echo.

REM Pick python executable
if exist "%VENV_PYTHON%" (
  set PYTHON_EXE=%VENV_PYTHON%
) else (
  set PYTHON_EXE=python
)

REM Start Backend
echo [*] Starting Backend...
start "IROS Backend" cmd /k "cd /d %BACKEND_DIR% && %PYTHON_EXE% -m uvicorn angel_one_feed:create_app --reload --host 0.0.0.0 --port 8000"

REM Wait briefly so ports are more likely to be free before frontend starts
timeout /t 3 /nobreak >nul

REM Start Frontend
echo [*] Starting Frontend...
start "IROS Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo.
echo ================================================
echo Services started in separate windows!
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:3000
echo ================================================
echo.

pause
