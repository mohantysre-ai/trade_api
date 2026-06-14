@echo off
REM IROS Trade API - One-command Launcher (Backend + AI News + Frontend)
REM Starts services as background processes (non-persistent).

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
echo IROS Trade API - Start App (Background Mode)
echo ================================================
echo.
echo [*] Launching Market API:   http://localhost:8000
echo [*] Launching AI News API:  http://localhost:8001
echo [*] Launching Frontend:     http://localhost:3000
echo.

REM Pick python executable
if exist "%VENV_PYTHON%" (
  set PYTHON_EXE=%VENV_PYTHON%
) else (
  set PYTHON_EXE=python
)

REM Start Market API Backend in background
echo [*] Starting Market API Backend on port 8000...
powershell -NoProfile -Command "Start-Process -FilePath \"%PYTHON_EXE%\" -ArgumentList \"-m\", \"uvicorn\", \"angel_one_feed:create_app\", \"--reload\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\" -WorkingDirectory \"%BACKEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

REM Start AI News Backend in background
echo [*] Starting AI News Backend on port 8001...
powershell -NoProfile -Command "Start-Process -FilePath \"%PYTHON_EXE%\" -ArgumentList \"-m\", \"uvicorn\", \"ai_news_server:app\", \"--reload\", \"--host\", \"0.0.0.0\", \"--port\", \"8001\" -WorkingDirectory \"%AI_NEWS_BACKEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

REM Wait briefly so backend ports are more likely to be free before frontend starts
powershell -NoProfile -Command "Start-Sleep -Seconds 3"

REM Start Frontend in background
echo [*] Starting Frontend on port 3000...
powershell -NoProfile -Command "Start-Process -FilePath \"cmd.exe\" -ArgumentList \"/c\", \"npm run dev -- -p 3000\" -WorkingDirectory \"%FRONTEND_DIR%\" -NoNewWindow -PassThru | Out-Null"

echo.
echo ================================================
echo All services launched in background.
echo Market API:   http://localhost:8000
echo AI News API:  http://localhost:8001
echo Frontend:     http://localhost:3000
echo ================================================
echo.

if "%IROS_NO_PAUSE%"=="1" exit /b 0
REM In background mode, the script completes without pausing unless IROS_NO_PAUSE is not 1
