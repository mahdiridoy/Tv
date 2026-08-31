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
echo Copying to mahdi_iptv.m3u8 for GitHub
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

REM ── Push mahdi_iptv.m3u8 + mahdi_scan_stats.json to main ──
echo.
echo =====================================
echo Pushing to GitHub (main branch)
echo =====================================

git add mahdi_iptv.m3u8 mahdi_scan_stats.json
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Auto update: mahdi_iptv.m3u8"
    git push origin main
    if errorlevel 1 (
        echo.
        echo [WARN] Git push failed. Check internet connection.
    ) else (
        echo [OK] Pushed to GitHub successfully!
        echo [OK] Telegram notification will be sent by GitHub Actions.
    )
) else (
    echo [INFO] No changes to push.
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
