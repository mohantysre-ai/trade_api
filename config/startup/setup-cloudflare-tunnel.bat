@echo off
REM One-time Cloudflare Tunnel setup for sigq.in
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-cloudflare-tunnel.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed.
  pause
  exit /b 1
)
pause
