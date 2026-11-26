@echo off
chcp 65001 >nul 2>&1
title Anonymisierer - Build

echo ============================================
echo   Anonymisierer .exe bauen
echo ============================================
echo.

:: Python pruefen
python --version >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python wird zum Bauen benoetigt.
    echo Bitte Python 3.8+ installieren: https://www.python.org/downloads/
    pause
    exit /b 1
)

cd /d "%~dp0"

:: Build-Umgebung
if not exist "build_env\Scripts\activate.bat" (
    echo Erstelle Build-Umgebung ...
    python -m venv build_env
)
call build_env\Scripts\activate.bat

echo Installiere Abhaengigkeiten ...
pip install -q -r requirements.txt pyinstaller

echo.
echo Baue .exe (das kann 1-2 Minuten dauern) ...
echo.

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --noconsole ^
    --distpath . ^
    --name Anonymisierer ^
    --add-data "blacklist.txt;." ^
    --hidden-import openpyxl ^
    --hidden-import email ^
    --hidden-import email.mime ^
    --hidden-import email.mime.text ^
    --hidden-import email.mime.multipart ^
    --hidden-import email.header ^
    --hidden-import email.utils ^
    --hidden-import csv ^
    --hidden-import html ^
    --hidden-import unicodedata ^
    --hidden-import codecs ^
    --hidden-import mailbox ^
    app.py

if errorlevel 1 (
    echo.
    echo [FEHLER] Build fehlgeschlagen.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Fertig!
echo ============================================
echo.
echo Die .exe liegt in:  Anonymisierer.exe
echo.
echo Zum Ausfuehren:
echo   1. dist\Anonymisierer.exe starten
echo   2. Browser oeffnet sich automatisch
echo.
echo Optional: blacklist.txt neben die .exe kopieren.
echo.
pause
