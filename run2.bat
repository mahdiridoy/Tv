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

echo.
echo =====================================
echo DONE! Output: mahdi_iptv.m3u8 (local only, no auto-push)
echo Manually upload mahdi_iptv.m3u8 to GitHub when ready.
echo =====================================
pause
exit /b

:error
echo.
echo =====================================
echo ERROR! A script failed.
echo =====================================
pause
