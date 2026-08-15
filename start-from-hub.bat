@echo off
REM Other machines: pull Hub images and start. Does not rebuild from source.
call "%~dp0config\startup\start_docker.bat" --pull %*
exit /b %ERRORLEVEL%
