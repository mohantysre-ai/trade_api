@echo off
REM After code changes: rebuild images, recreate containers, prune old images.
call "%~dp0config\startup\rebuild_docker.bat" %*
exit /b %ERRORLEVEL%
@echo off
call "%~dp0config\startup\push_docker_hub.bat" %*
exit /b %ERRORLEVEL%
