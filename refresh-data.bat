@echo off
REM Manual on-demand data refresh — against whatever is on :8000 / :8001
REM (native start-app.bat OR docker start-docker.bat)
call "%~dp0config\startup\refresh-data-on-demand.bat" %*
exit /b %ERRORLEVEL%
