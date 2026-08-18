@echo off
REM Other machines: pull Hub images, seed ALL live desk JSON from iros-desk-state, then start.
REM Seed runs before the API process so last_market_snapshot + sessions load on first boot.
REM Does not rebuild from source. Run push-docker-hub.bat on the live desk first.
call "%~dp0config\startup\start_docker.bat" --pull %*
exit /b %ERRORLEVEL%
