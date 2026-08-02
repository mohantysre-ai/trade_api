@echo off
REM Run Cloudflare Tunnel: https://iros.sigq.in -> localhost:3000
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-tunnel.ps1"
if errorlevel 1 (
  echo.
  echo Tunnel failed. Did you run setup-cloudflare-tunnel.bat first?
  pause
  exit /b 1
)
