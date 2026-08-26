@echo off
REM Other machines: pull Hub images, seed ALL live desk JSON from iros-desk-state, then start.
REM Seed runs before the API process so last_market_snapshot + sessions load on first boot.
REM Does not rebuild from source. Run push-docker-hub.bat on the live desk first.
REM If sigq-runtime-transfer.zip is present, restore credentials, Cloudflare and volumes first.
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"
where docker >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Docker Desktop is not installed.
  pause
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo [*] Starting Docker Desktop...
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0config\startup\wait-docker-engine.ps1"
  if errorlevel 1 (
    echo [FAIL] Docker Desktop did not become ready.
    pause
    exit /b 1
  )
)
if exist "%~dp0sigq-runtime-transfer.zip" (
  echo [*] Found sigq-runtime-transfer.zip - restoring complete runtime...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\import-runtime-bundle.ps1" "%~dp0sigq-runtime-transfer.zip"
  if errorlevel 1 (
    echo [FAIL] Runtime transfer import failed. Nothing will be started.
    pause
    exit /b 1
  )
  ren "%~dp0sigq-runtime-transfer.zip" "sigq-runtime-transfer.imported.zip"
  echo [OK] Runtime imported. The ZIP was renamed so it cannot overwrite newer state later.
)
call "%~dp0config\startup\start_docker.bat" --pull %*
exit /b %ERRORLEVEL%
