@echo off
REM ==========================================
REM IROS Trade API Repository Reorganization (Windows)
REM ==========================================
REM
REM Run from the root of your trade-api repository
REM Usage: reorganize.bat

setlocal enabledelayexpansion

REM Colors (Windows 10+)
for /F %%A in ('copy /Z "%~f0" nul') do set "BS=%%A"

set "BLUE=[94m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "NC=[0m"

echo.
echo %BLUE%========================================%NC%
echo %BLUE%IROS Trade API Repository Reorganization%NC%
echo %BLUE%========================================%NC%
echo.

REM Check if git exists
git --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR] Git not found. Please install Git.%NC%
    exit /b 1
)

REM Check if git repo
git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR] Not a git repository. Run from repo root.%NC%
    exit /b 1
)

REM Check if working directory is clean
git status --porcelain | find . >nul
if not errorlevel 1 (
    echo %RED%[ERROR] Working directory has uncommitted changes!%NC%
    echo Please commit or stash changes first.
    exit /b 1
)

echo %GREEN%[OK] Git repository clean%NC%
echo.

REM Create backup
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set BACKUP_DIR=.archive\backup_%mydate%_%mytime%

echo %BLUE%[INFO] Creating backup in %BACKUP_DIR%%NC%
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
if exist "backend" xcopy "backend" "%BACKUP_DIR%\src\backend" /E /I /Y >nul
if exist "iros-terminal" xcopy "iros-terminal" "%BACKUP_DIR%\src\iros-terminal" /E /I /Y >nul
echo %GREEN%[OK] Backup created%NC%
echo.

REM Create folder structure
echo %BLUE%[INFO] Creating folder structure...%NC%

setlocal
for %%F in (
    backend\app\api\routes
    backend\app\services
    backend\app\models
    backend\app\utils
    backend\app\middleware
    frontend\iros-terminal\src\app\api
    frontend\iros-terminal\src\app\components\Terminal
    frontend\iros-terminal\src\app\components\Dashboard
    frontend\iros-terminal\src\app\components\Widgets
    frontend\iros-terminal\src\app\components\Layout
    frontend\iros-terminal\src\app\hooks
    frontend\iros-terminal\src\app\styles
    frontend\iros-terminal\src\lib
    config\deployment\nginx
    config\deployment\systemd
    config\credentials
    config\startup
    scripts
    logs
    tests\unit
    tests\integration
    docs\images
) do (
    if not exist "%%F" (
        mkdir "%%F"
        echo %GREEN%[OK] Created %%F%NC%
    )
)

REM Create __init__.py files
(echo.) > "backend\app\__init__.py"
(echo.) > "backend\app\api\__init__.py"
(echo.) > "backend\app\api\routes\__init__.py"
(echo.) > "backend\app\services\__init__.py"
(echo.) > "backend\app\models\__init__.py"
(echo.) > "backend\app\utils\__init__.py"
(echo.) > "tests\__init__.py"
(echo.) > "tests\unit\__init__.py"
(echo.) > "tests\integration\__init__.py"

echo %GREEN%[OK] Python package files created%NC%
echo.

REM Move backend files
echo %BLUE%[INFO] Moving backend files...%NC%

if exist "backend\angel_one_feed.py" (
    move "backend\angel_one_feed.py" "backend\app\services\" >nul
    echo %GREEN%[OK] Moved angel_one_feed.py%NC%
)

if exist "backend\global_feed.py" (
    move "backend\global_feed.py" "backend\app\services\market_feeds.py" >nul
    echo %GREEN%[OK] Moved global_feed.py → market_feeds.py%NC%
)

if exist "backend\terminal_intelligence_full.py" (
    move "backend\terminal_intelligence_full.py" "backend\app\services\intelligence_engine.py" >nul
    echo %GREEN%[OK] Moved terminal_intelligence_full.py → intelligence_engine.py%NC%
)

if exist "backend\llm_client.py" (
    move "backend\llm_client.py" "backend\app\services\" >nul
    echo %GREEN%[OK] Moved llm_client.py%NC%
)

if exist "backend\moneycontrol_probe.py" (
    move "backend\moneycontrol_probe.py" "backend\app\services\" >nul
    echo %GREEN%[OK] Moved moneycontrol_probe.py%NC%
)

if exist "backend\symbols.py" (
    move "backend\symbols.py" "backend\app\utils\" >nul
    echo %GREEN%[OK] Moved symbols.py%NC%
)

if exist "iros-terminal\backend\ai_ticker_news.py" (
    move "iros-terminal\backend\ai_ticker_news.py" "backend\app\services\" >nul
    echo %GREEN%[OK] Moved ai_ticker_news.py%NC%
)

if exist "iros-terminal\backend\ai_news_server.py" (
    move "iros-terminal\backend\ai_news_server.py" "backend\app\services\" >nul
    echo %GREEN%[OK] Moved ai_news_server.py%NC%
)

echo.

REM Delete redundant files
echo %BLUE%[INFO] Deleting redundant files...%NC%

if exist "backend\terminal_intelligence_heuristic_backup.py" (
    del "backend\terminal_intelligence_heuristic_backup.py"
    echo %GREEN%[OK] Deleted terminal_intelligence_heuristic_backup.py%NC%
)

if exist "backend\terminal_intelligence.py" (
    del "backend\terminal_intelligence.py"
    echo %GREEN%[OK] Deleted terminal_intelligence.py%NC%
)

if exist "backend\ti_out.json" (
    del "backend\ti_out.json"
    echo %GREEN%[OK] Deleted ti_out.json%NC%
)

if exist "backend\last_market_snapshot.json" (
    del "backend\last_market_snapshot.json"
    echo %GREEN%[OK] Deleted last_market_snapshot.json%NC%
)

echo.

REM Move config files
echo %BLUE%[INFO] Moving configuration files...%NC%

if exist "backend\.env.example" (
    copy "backend\.env.example" "config\.env.example" >nul
    echo %GREEN%[OK] Copied .env.example to config\%NC%
)

if exist "start_backend.sh" (
    move "start_backend.sh" "config\startup\" >nul
    echo %GREEN%[OK] Moved start_backend.sh%NC%
)

if exist "start_frontend.sh" (
    move "start_frontend.sh" "config\startup\" >nul
    echo %GREEN%[OK] Moved start_frontend.sh%NC%
)

if exist "start-services.bat" (
    move "start-services.bat" "config\startup\" >nul
    echo %GREEN%[OK] Moved start-services.bat%NC%
)

if exist "start_app.bat" (
    move "start_app.bat" "config\startup\" >nul
    echo %GREEN%[OK] Moved start_app.bat%NC%
)

if exist "start-persistent.ps1" (
    move "start-persistent.ps1" "config\startup\" >nul
    echo %GREEN%[OK] Moved start-persistent.ps1%NC%
)

if exist "refresh-data-on-demand.bat" (
    move "refresh-data-on-demand.bat" "config\startup\" >nul
    echo %GREEN%[OK] Moved refresh-data-on-demand.bat%NC%
)

if exist "refresh-data-on-demand.ps1" (
    move "refresh-data-on-demand.ps1" "config\startup\" >nul
    echo %GREEN%[OK] Moved refresh-data-on-demand.ps1%NC%
)

echo.

REM Cleanup root
echo %BLUE%[INFO] Cleaning up root directory...%NC%

if exist "main.py" (
    move "main.py" ".archive\main.py.bak" >nul
    echo %YELLOW%[WARNING] Archived main.py%NC%
)

if exist "index.tsx" (
    del "index.tsx"
    echo %GREEN%[OK] Deleted index.tsx%NC%
)

if exist "routeTree.gen.ts" (
    del "routeTree.gen.ts"
    echo %GREEN%[OK] Deleted routeTree.gen.ts%NC%
)

if exist "package.json" (
    move "package.json" ".archive\package.json.root.bak" >nul
    echo %YELLOW%[WARNING] Archived root package.json%NC%
)

echo.

REM Create .gitignore
echo %BLUE%[INFO] Creating .gitignore...%NC%
(
    echo # Environment
    echo .env.local
    echo .env.*.local
    echo config/credentials/
    echo.
    echo # Python
    echo __pycache__/
    echo *.py[cod]
    echo .pytest_cache/
    echo .coverage
    echo venv/
    echo .venv/
    echo.
    echo # Node / Frontend
    echo node_modules/
    echo .next/
    echo.
    echo # Logs
    echo logs/
    echo *.log
    echo.
    echo # OS
    echo .DS_Store
    echo Thumbs.db
    echo.
    echo .archive/
) > .gitignore
echo %GREEN%[OK] Created .gitignore%NC%
echo.

REM Create config/.env.example
echo %BLUE%[INFO] Creating config/.env.example...%NC%
(
    echo # IROS Trade API Configuration
    echo # Copy to config/.env.local and fill in your values
    echo.
    echo ANGEL_ONE_API_KEY=your_api_key_here
    echo ANGEL_ONE_USERNAME=your_username
    echo ANGEL_ONE_PWD=your_password
    echo ANGEL_ONE_OTP=000000
    echo.
    echo GOOGLE_API_KEY=your_google_api_key_here
    echo.
    echo DEBUG=False
    echo LOG_LEVEL=INFO
    echo FRONTEND_URL=http://localhost:3000
    echo BACKEND_URL=http://localhost:8000
) > config\.env.example
echo %GREEN%[OK] Created config/.env.example%NC%
echo.

REM Summary
echo.
echo %BLUE%========================================%NC%
echo %BLUE%Reorganization Complete!%NC%
echo %BLUE%========================================%NC%
echo.
echo %GREEN%Backup location: %BACKUP_DIR%%NC%
echo.
echo %YELLOW%Next Steps:%NC%
echo 1. Review changes:
echo    git status
echo    git diff --stat
echo.
echo 2. Create config\.env.local:
echo    copy config\.env.example config\.env.local
echo    REM Edit config\.env.local with your credentials
echo.
echo 3. Start development:
echo    cd backend
echo    pip install -r requirements.txt
echo    cd ../frontend/iros-terminal
echo    npm install
echo.
echo 4. Run backend:
echo    cd backend
echo    python -m uvicorn app.main:app --reload
echo.
echo 5. Run frontend (new terminal):
echo    cd frontend\iros-terminal
echo    npm run dev
echo.
echo 6. Commit changes:
echo    git add .
echo    git commit -m "refactor: reorganize repository structure"
echo.

pause
