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
python scan_valid.py merged.m3u merged.m3u
if errorlevel 1 goto :error

echo.
echo =====================================
echo Copying to mahdi_iptv.m3u8 for GitHub Pages
echo =====================================
copy /Y merged.m3u mahdi_iptv.m3u8

REM ── Push ONLY mahdi_iptv.m3u8 to GitHub Pages branch ──
echo.
echo =====================================
echo Pushing mahdi_iptv.m3u8 to GitHub (gh-pages branch)
echo =====================================

set "TEMP_DIR=%TEMP%\gh-pages-push-%RANDOM%"
mkdir "%TEMP_DIR%"
copy /Y mahdi_iptv.m3u8 "%TEMP_DIR%\mahdi_iptv.m3u8" >nul

pushd "%TEMP_DIR%"
git init
git config user.email "bot@iptv.local"
git config user.name "IPTV Bot"
git branch -M gh-pages
git remote add origin https://github.com/mahdiridoy/Tv.git
git config credential.helper store
git add mahdi_iptv.m3u8
git commit -m "Auto update: playlist"
git push -u origin gh-pages --force
popd

if errorlevel 1 (
    echo.
    echo [WARN] Git push failed.
    echo        Run this ONCE anywhere to save credentials:
    echo.
    echo          git config credential.helper store
    echo.
    echo        Token: https://github.com/settings/tokens (勾选 "repo")
) else (
    echo [OK] Pushed to GitHub successfully!
)

rd /s /q "%TEMP_DIR%" 2>nul

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