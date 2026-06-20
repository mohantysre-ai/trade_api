@echo off
REM IROS Trade API - Persistent Backend & Frontend Launcher

setlocal enabledelayedexpansion

set PROJECT_ROOT=d:\trade_api
set BACKEND_DIR=%PROJECT_ROOT%\backend\backend
set FRONTEND_DIR=%PROJECT_ROOT%\iros-terminal
set VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe

cls
echo ================================================
echo IROS Trade API - Persistent Server Launcher
echo ================================================
echo.

REM Start Backend
echo [*] Starting Backend API on http://localhost:8000
start "IROS Backend" cmd /k "cd /d %BACKEND_DIR% && %VENV_PYTHON% -m uvicorn angel_one_feed:create_app --reload --host 0.0.0.0 --port 8000"

REM Wait a few seconds for backend to start
timeout /t 3 /nobreak

REM Start Frontend
echo [*] Starting Frontend on http://localhost:3000
start "IROS Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo.
echo ================================================
echo Services started in separate windows!
echo ================================================
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Keep this window open to maintain services.
echo Close individual windows to stop that service.
echo.
pause
