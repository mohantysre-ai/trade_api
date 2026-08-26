@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy-portable.ps1" -Mode Build
exit /b %ERRORLEVEL%
