@echo off
REM IROS Trade API - One-command Launcher (Backend + AI News + Frontend)
REM Starts services in separate windows (non-persistent).

setlocal enabledelayedexpansion

set PROJECT_ROOT=%~dp0
REM Normalize PROJECT_ROOT (remove trailing backslash)
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set BACKEND_DIR=%PROJECT_ROOT%\backend
set AI_NEWS_BACKEND_DIR=%PROJECT_ROOT%\iros-terminal\backend
set FRONTEND_DIR=%PROJECT_ROOT%\iros-terminal
set VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe

cls
echo ================================================
echo IROS Trade API - Start App
echo ================================================
echo.
echo [*] Market API:   http://localhost:8000
echo [*] AI News API:  http://localhost:8001
echo [*] Frontend:     http://localhost:3000
echo.

REM Pick python executable
if exist "%VENV_PYTHON%" (
  set PYTHON_EXE=%VENV_PYTHON%
) else (
  set PYTHON_EXE=python
)

REM Start Market API Backend
echo [*] Starting Market API Backend on port 8000...
start "IROS Market API" cmd /k "cd /d "%BACKEND_DIR%" && "%PYTHON_EXE%" -m uvicorn angel_one_feed:create_app --reload --host 0.0.0.0 --port 8000"

REM Start AI News Backend
echo [*] Starting AI News Backend on port 8001...
start "IROS AI News" cmd /k "cd /d "%AI_NEWS_BACKEND_DIR%" && "%PYTHON_EXE%" -m uvicorn ai_news_server:app --reload --host 0.0.0.0 --port 8001"

REM Wait briefly so backend ports are more likely to be free before frontend starts
timeout /t 3 /nobreak >nul

REM Start Frontend
echo [*] Starting Frontend on port 3000...
start "IROS Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev -- -p 3000"

echo.
echo ================================================
echo Services started in separate windows!
echo Market API:   http://localhost:8000
echo AI News API:  http://localhost:8001
echo Frontend:     http://localhost:3000
echo ================================================
echo.

if "%IROS_NO_PAUSE%"=="1" exit /b 0
pause
