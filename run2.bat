@echo off
title Pulse Stream
color 0A

REM ── Make sure we're always in the project folder ──
cd /d "%~dp0"

echo =====================================
echo     Pulse Stream
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

REM ── Pull latest BEFORE pipeline runs ──
echo.
echo =====================================
echo Pulling latest from GitHub...
echo =====================================
if not exist ".git" (
    echo [INFO] Initializing git repo...
    git init
    git branch -M main
    git config user.email "bot@iptv.local"
    git config user.name "IPTV Bot"
    git remote add origin https://github.com/mahdiridoy/Tv.git
)
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    git remote add origin https://github.com/mahdiridoy/Tv.git
)
git config credential.helper store
git pull --rebase origin main
if errorlevel 1 (
    echo [WARN] Pull failed, force syncing...
    git fetch origin main
    git reset --hard origin/main
)

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
echo Preparing output (no scan)
echo =====================================
copy /y merged.m3u mahdi_iptv.m3u8 >nul
python -c "import json; d=open('mahdi_iptv.m3u8',encoding='utf-8',errors='ignore').read(); c=d.count('#EXTINF'); open('mahdi_scan_stats.json','w').write(json.dumps({'total':c,'alive':c,'dead':0,'avg_latency_ms':0,'median_latency_ms':0,'p95_latency_ms':0})); print(f'[OK] Channels: {c} (no scan)')"
echo [OK] Output ready: mahdi_iptv.m3u8

REM ── Push mahdi_iptv.m3u8 + mahdi_scan_stats.json ──
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
        echo [WARN] Push failed, retrying in 15 seconds... (%RETRY%/3)
        ipconfig /flushdns >nul 2>&1
        timeout /t 15 /nobreak >nul
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
echo DONE! Output: mahdi_iptv.m3u8
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
