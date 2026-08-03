@echo off
REM Manual / native start — Python venv + Next.js (+ tunnel)
REM Do not run together with start-docker.bat (same ports).
call "%~dp0config\startup\start_app.bat" %*
exit /b %ERRORLEVEL%
