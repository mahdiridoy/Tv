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

REM ── Setup git repo if not already one ──
if not exist ".git" (
    echo.
    echo [INFO] Initializing git repo...
    git init
    git branch -M main
    git remote add origin https://github.com/mahdiridoy/Tv.git
    git config credential.helper store
    echo [INFO] Git repo initialized. First push will ask for username + token.
    echo [INFO] Token: https://github.com/settings/tokens (check "repo" scope)
)

echo.
echo =====================================
echo Pushing to GitHub
echo =====================================
git add mahdi_iptv.m3u8 merged.m3u sources2.txt
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Auto update: playlist"
    git push -u origin main
    if errorlevel 1 (
        echo.
        echo [WARN] Git push failed.
        echo        Run this ONCE in this project folder:
        echo.
        echo          git config credential.helper store
        echo          git push -u origin main
        echo.
        echo        Enter username + token when asked. Saved forever after that.
        echo        Token: https://github.com/settings/tokens (勾选 "repo")
        echo.
        echo        The local merged.m3u is still saved.
    ) else (
        echo [OK] Pushed to GitHub successfully!
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