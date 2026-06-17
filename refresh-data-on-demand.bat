@echo off
REM ============================================================
REM IROS Trade API - On-Demand Data Refresh
REM ============================================================
REM This script performs a complete data refresh for all
REM available API endpoints in the IROS platform.
REM
REM APIs covered:
REM   Market API (port 8000) - Market data, intelligence, terminal intelligence
REM   AI News API (port 8001) - Ticker news & batch news refresh
REM
REM Usage:  refresh-data-on-demand.bat
REM         refresh-data-on-demand.bat --skip-news   (skip AI news refresh)
REM         refresh-data-on-demand.bat --pool Nifty 500
REM         refresh-data-on-demand.bat --ticker RELIANCE
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PS1_SCRIPT="%SCRIPT_DIR%refresh-data-on-demand.ps1"

REM Build arguments for PowerShell script
set PS_ARGS=

REM Check each argument
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--skip-news" set PS_ARGS=%PS_ARGS% -SkipNews
if /i "%~1"=="--pool" set PS_ARGS=%PS_ARGS% -Pool %~2 & shift
if /i "%~1"=="--ticker" set PS_ARGS=%PS_ARGS% -Ticker %~2 & shift
if /i "%~1"=="--no-ticker-news" set PS_ARGS=%PS_ARGS% -NoTickerNews
shift
goto parse_args
:args_done

REM Execute the PowerShell refresh script
powershell -NoProfile -ExecutionPolicy Bypass -File %PS1_SCRIPT% %PS_ARGS%

set EXIT_CODE=%ERRORLEVEL%

REM Pause if not in auto mode
if "%IROS_NO_PAUSE%"=="1" exit /b %EXIT_CODE%

echo.
if %EXIT_CODE% equ 0 (
    echo.
) else (
    echo [!] Refresh completed with errors (exit code: %EXIT_CODE%^). Check output above.
    echo.
    pause
)

exit /b %EXIT_CODE%