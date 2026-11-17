@echo off
chcp 65001 >nul 2>&1
title Dokument-Anonymisierer

echo ============================================
echo   Dokument-Anonymisierer
echo ============================================
echo.

:: Pruefen ob die fertige .exe existiert
if exist "%~dp0Anonymisierer.exe" (
    echo Starte Anonymisierer.exe ...
    start "" "%~dp0Anonymisierer.exe"
    exit /b 0
)

:: Fallback: Python direkt ausfuehren
python --version >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python wurde nicht gefunden und keine .exe vorhanden.
    echo.
    echo Option 1: build.bat ausfuehren um eine .exe zu erstellen
    echo Option 2: Python 3.8+ installieren: https://www.python.org/downloads/
    echo            Wichtig: "Add Python to PATH" aktivieren!
    pause
    exit /b 1
)

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Erstelle virtuelle Umgebung ...
    python -m venv venv
    if errorlevel 1 (
        echo [FEHLER] Virtuelle Umgebung konnte nicht erstellt werden.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

pip install -q -r requirements.txt
if errorlevel 1 (
    echo [FEHLER] Abhaengigkeiten konnten nicht installiert werden.
    pause
    exit /b 1
)

echo.
echo Starte Server ...
echo Zum Beenden dieses Fenster schliessen oder Strg+C druecken.
echo.

python app.py
pause
