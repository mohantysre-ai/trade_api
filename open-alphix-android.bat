@echo off
REM Open Alphix Terminal Android project in Android Studio (after sync to prod desk)
cd /d "%~dp0mobile"
if not exist "node_modules\@capacitor\cli" (
  echo [*] Installing mobile dependencies...
  call npm install
)
call npm run desk:prod
call npm run open:android
