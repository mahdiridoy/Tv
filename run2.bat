@echo off
title Pulse Stream - With Link Scan
color 0A

REM ── Make sure we're always in the project folder ──
cd /d "%~dp0"

echo =====================================
echo     Pulse Stream (WITH LINK SCAN)
echo =====================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed!
    pause
    exit /b
)

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

echo.
echo Installing requirements...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo =====================================
echo Running merge_m3u.py
echo =====================================
python merge_m3u.py
if errorlevel 1 goto :error

echo.
echo =====================================
echo Running adult_filter.py
echo =====================================
python adult_filter.py
if errorlevel 1 goto :error

echo.
echo =====================================
echo Running attach_logos.py
echo =====================================
python attach_logos.py
if errorlevel 1 goto :error

echo.
echo =====================================
echo Running order_m3u.py
echo =====================================
python order_m3u.py
if errorlevel 1 goto :error

echo.
echo =====================================
echo Running scan_valid.py (link validation)
echo =====================================
python scan_valid.py merged.m3u merged.m3u --stats-file mahdi_scan_stats.json
if errorlevel 1 goto :error

echo.
echo =====================================
echo Copying to mahdi_iptv.m3u8
echo =====================================
copy /Y merged.m3u mahdi_iptv.m3u8

REM ── Setup git repo if needed ──
if not exist ".git" (
    echo [INFO] Initializing git repo...
    git init
    git branch -M main
    git config user.email "bot@iptv.local"
    git config user.name "IPTV Bot"
)
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    git remote add origin https://github.com/mahdiridoy/Tv.git
)
git config credential.helper store

REM ── Pull latest first to avoid conflicts ──
echo.
echo =====================================
echo Pulling latest from GitHub...
echo =====================================
git pull --rebase origin main
if errorlevel 1 (
    echo [WARN] Pull failed, trying force pull...
    git fetch origin main
    git reset --hard origin/main
)

REM ── Stage and push ──
echo.
echo =====================================
echo Pushing to GitHub (main branch)
echo =====================================

git add mahdi_iptv.m3u8 mahdi_scan_stats.json
git commit -m "Auto update: mahdi_iptv.m3u8 [%date% %time%]"

REM ── Retry push up to 3 times ──
set RETRY=0
:push_retry
git push origin main
if errorlevel 1 (
    set /a RETRY+=1
    if %RETRY% lss 3 (
        echo [WARN] Push failed, retrying in 5 seconds... (%RETRY%/3)
        timeout /t 5 /nobreak >nul
        goto :push_retry
    ) else (
        echo.
        echo [ERROR] Push failed after 3 attempts.
        echo         Check your internet connection.
    )
) else (
    echo [OK] Pushed to GitHub successfully!
    echo [OK] Telegram notification will be sent automatically.
)

echo.
echo =====================================
echo DONE! Output saved to merged.m3u
echo GitHub Pages link: https://mahdiridoy.github.io/Tv/mahdi_iptv.m3u8
echo =====================================
pause
exit /b

:error
echo.
echo =====================================
echo ERROR! A script failed.
echo =====================================
pause
