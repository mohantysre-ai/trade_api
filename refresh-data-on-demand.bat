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
REM         refresh-data-on-demand.bat --orchestrate (run sequential orchestrated refresh)
REM         refresh-data-on-demand.bat --orchestrate --pool "Nifty 100" --prompt "high volume"
REM ============================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PS1_SCRIPT="%SCRIPT_DIR%.kilo\scripts\refresh-data-on-demand.ps1"
set PYTHON_SCRIPT="%SCRIPT_DIR%backend\angel_one_feed.py"
set PYTHON_EXE="%SCRIPT_DIR%.venv\Scripts\python.exe"

REM Initialize flags and arguments
set ORCHESTRATE_MODE=0
set PS_ARGS=
set PYTHON_ARGS=

REM Check each argument
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--orchestrate" (
    set ORCHESTRATE_MODE=1
    set PYTHON_ARGS=!PYTHON_ARGS! --orchestrate
) else if /i "%~1"=="--skip-news" (
    set PS_ARGS=!PS_ARGS! -SkipNews
) else if /i "%~1"=="--pool" (
    set PS_ARGS=!PS_ARGS! -Pool "%~2"
    set PYTHON_ARGS=!PYTHON_ARGS! --pool "%~2"
    shift
) else if /i "%~1"=="--ticker" (
    set PS_ARGS=!PS_ARGS! -Ticker "%~2"
    REM --ticker is specific to the PowerShell script's existing logic, not directly used by --orchestrate
    shift
) else if /i "%~1"=="--no-ticker-news" (
    set PS_ARGS=!PS_ARGS! -NoTickerNews
) else if /i "%~1"=="--prompt" (
    set PYTHON_ARGS=!PYTHON_ARGS! --prompt "%~2"
    shift
)
shift
goto parse_args
:args_done

if %ORCHESTRATE_MODE% equ 1 (
    echo.
    echo ================================================
    echo [*] Starting Orchestrated Sequential Refresh...
    echo ================================================
    echo.
    echo Running command: %PYTHON_EXE% %PYTHON_SCRIPT% %PYTHON_ARGS%
    %PYTHON_EXE% %PYTHON_SCRIPT% %PYTHON_ARGS%
    set EXIT_CODE=%ERRORLEVEL%
) else (
    REM Execute the PowerShell refresh script
    echo Running command: powershell -NoProfile -ExecutionPolicy Bypass -File %PS1_SCRIPT% %PS_ARGS%
    powershell -NoProfile -ExecutionPolicy Bypass -File %PS1_SCRIPT% %PS_ARGS%
    set EXIT_CODE=%ERRORLEVEL%
)

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