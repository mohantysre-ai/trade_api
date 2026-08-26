@echo off
REM Force a resync of backend/.env, Cloudflare credentials, and volumes from
REM smohanty010620/sigq-runtime-private, even if backend\.env already exists.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0config\startup\restore-runtime-private.ps1"
exit /b %ERRORLEVEL%