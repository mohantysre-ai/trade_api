@echo off
call "%~dp0config\startup\push_docker_hub.bat" %*
exit /b %ERRORLEVEL%
