@echo off
REM Other machines: pull Hub images, seed ALL live desk JSON from iros-desk-state, then start.
REM Seed runs before the API process so last_market_snapshot + sessions load on first boot.
REM Does not rebuild from source. Run push-docker-hub.bat on the live desk first.
REM If backend\.env doesn't exist yet, this looks like a fresh machine: pull the
REM private sigq-runtime-private image first and restore credentials + volumes from it.
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
if not exist "%~dp0backend\.env" (
  echo [*] backend\.env not found - restoring from private Hub image...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0config\startup\restore-runtime-private.ps1"
  if errorlevel 1 (
    echo [FAIL] Runtime restore from sigq-runtime-private failed. Run: docker login
    echo        Nothing will be started.
    pause
    exit /b 1
  )
  echo [OK] Runtime restored.
) else (
  echo [*] backend\.env already present - skipping runtime-private restore.
  echo     Run restore-runtime-private.bat directly to force a resync from Hub.
)
call "%~dp0config\startup\start_docker.bat" --pull %*
exit /b %ERRORLEVEL%
