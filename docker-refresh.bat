@echo off
REM Docker on-demand data refresh — requires containers from start-docker.bat
call "%~dp0config\startup\docker-refresh.bat" %*
exit /b %ERRORLEVEL%
