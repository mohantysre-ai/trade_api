@echo off
REM Convenience wrapper — repo root → config\startup\start_docker.bat
call "%~dp0config\startup\start_docker.bat" %*
exit /b %ERRORLEVEL%
