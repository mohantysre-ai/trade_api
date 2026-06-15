@echo off
setlocal enabledelayedexpansion

set PROJECT_ROOT=d:\trade_api
set BACKEND_DIR=%PROJECT_ROOT%\backend
set VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe
set BACKEND_HOST=localhost
set BACKEND_PORT=8000
set AI_NEWS_API_URL=http://localhost:8001

echo ================================================
echo IROS Trade API - Backend Restart and Validate
echo ================================================
echo.

echo [*] Stopping existing backend service on port %BACKEND_PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT%') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak >nul
echo.

echo [*] Starting Backend API on http://%BACKEND_HOST%:%BACKEND_PORT%
start "IROS Backend" cmd /k "cd /d %BACKEND_DIR% && %VENV_PYTHON% -m uvicorn angel_one_feed:create_app --host 0.0.0.0 --port %BACKEND_PORT%"
echo.

echo [*] Waiting for backend to start (15 seconds)...
timeout /t 15 /nobreak >nul
echo.

echo ================================================
echo Backend API Endpoint Tests
echo ================================================

echo.
echo [TEST] /health
curl -s http://%BACKEND_HOST%:%BACKEND_PORT%/health > health_response.json
type health_response.json
findstr /C:"\\"status\\":\\"ok\\"" health_response.json >nul
if %errorlevel% equ 0 (
    echo [PASS] Health check successful.
) else (
    echo [FAIL] Health check failed.
)
echo.

echo [TEST] /api/market-data
curl -s http://%BACKEND_HOST%:%BACKEND_PORT%/api/market-data > market_data_response.json
type market_data_response.json
findstr /C:"\\"success\\": true" market_data_response.json >nul
if %errorlevel% equ 0 (
    echo [PASS] Market data API returned success.
) else (
    echo [FAIL] Market data API failed.
)
echo.

echo [TEST] /api/news
curl -s http://%BACKEND_HOST%:%BACKEND_PORT%/api/news > news_response.json
type news_response.json
findstr /C:"\\"success\\": true" news_response.json >nul
if %errorlevel% equ 0 (
    echo [PASS] News feed API returned success.
) else (
    echo [FAIL] News feed API failed.
)
echo.

echo [TEST] /api/market-intelligence
curl -s http://%BACKEND_HOST%:%BACKEND_PORT%/api/market-intelligence > market_intelligence_response.json
type market_intelligence_response.json
findstr /C:"\\"success\\": true" market_intelligence_response.json >nul
if %errorlevel% equ 0 (
    echo [PASS] Market intelligence API returned success.
) else (
    echo [FAIL] Market intelligence API failed.
)
echo.

echo [TEST] /api/terminal-intelligence?ticker=RELIANCE
curl -s "http://%BACKEND_HOST%:%BACKEND_PORT%/api/terminal-intelligence?ticker=RELIANCE" > terminal_intelligence_reliance_response.json
type terminal_intelligence_reliance_response.json
findstr /C:"\\"ticker\\":\\"RELIANCE\\"" terminal_intelligence_reliance_response.json >nul
if %errorlevel% equ 0 (
    echo [PASS] Terminal intelligence API for RELIANCE returned successfully.
) else (
    echo [FAIL] Terminal intelligence API for RELIANCE failed.
)
echo.

echo ================================================
echo Backend Validation Complete.
echo ================================================
echo.
pause

