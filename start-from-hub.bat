@echo off
REM Other machines: pull Hub images, seed desk JSON from iros-desk-state, start.
REM Does not rebuild from source. Run push-docker-hub.bat on the live desk first.
call "%~dp0config\startup\start_docker.bat" --pull %*
exit /b %ERRORLEVEL%
