@echo off
chcp 65001 >nul 2>&1
title Anonymisierer - Update
cd /d "%~dp0"

set REPO=durums/anonymizer
set EXE=Anonymisierer.exe
set TEMP_DIR=_update_temp

echo ============================================
echo   Anonymisierer - Update
echo ============================================
echo.

:: Pruefen ob die App noch laeuft
tasklist /FI "IMAGENAME eq %EXE%" 2>nul | find /I "%EXE%" >nul
if not errorlevel 1 (
    echo [FEHLER] %EXE% laeuft noch!
    echo Bitte erst den Browser-Tab schliessen und warten,
    echo bis sich das Konsolenfenster von selbst schliesst.
    echo.
    pause
    exit /b 1
)

:: Python pruefen
python --version >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python wird zum Bauen benoetigt.
    echo Bitte Python 3.8+ installieren: https://www.python.org/downloads/
    echo Wichtig: "Add Python to PATH" aktivieren!
    pause
    exit /b 1
)

:: Aufraeumen falls letztes Update abgebrochen wurde
if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%"

echo Lade neuesten Quellcode von GitHub ...
echo.

:: Quellcode als ZIP herunterladen und entpacken
powershell -ExecutionPolicy Bypass -NoProfile -Command ^
 "$ErrorActionPreference = 'Stop';" ^
 "try {" ^
 "  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
 "  Invoke-WebRequest -Uri 'https://github.com/%REPO%/archive/refs/heads/main.zip' -OutFile '_update.zip' -UseBasicParsing;" ^
 "  Expand-Archive '_update.zip' -DestinationPath '%TEMP_DIR%' -Force;" ^
 "  Remove-Item '_update.zip' -Force;" ^
 "} catch {" ^
 "  Write-Host ('[FEHLER] Download fehlgeschlagen: ' + $_.Exception.Message) -ForegroundColor Red;" ^
 "  exit 1" ^
 "}"

if not exist "%TEMP_DIR%\anonymizer-main\app.py" (
    echo [FEHLER] Download fehlgeschlagen oder Repo-Struktur unerwartet.
    if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%"
    pause
    exit /b 1
)

:: In den entpackten Ordner wechseln und .exe bauen
echo Baue neue Version (das kann 1-2 Minuten dauern) ...
echo.

pushd "%TEMP_DIR%\anonymizer-main"

if not exist "build_env\Scripts\activate.bat" (
    python -m venv build_env
)
call build_env\Scripts\activate.bat

pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [FEHLER] Abhaengigkeiten konnten nicht installiert werden.
    popd
    rmdir /S /Q "%~dp0%TEMP_DIR%"
    pause
    exit /b 1
)

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --noconsole ^
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
    popd
    rmdir /S /Q "%~dp0%TEMP_DIR%"
    pause
    exit /b 1
)

:: Neue .exe zurueckkopieren
popd
copy /Y "%TEMP_DIR%\anonymizer-main\dist\%EXE%" "%EXE%" >nul

:: Version speichern
for /f "tokens=2 delims='" %%v in ('findstr /R "^VERSION" "%TEMP_DIR%\anonymizer-main\app.py"') do (
    echo %%v> Anonymisierer_version.txt
)

:: Aufraeumen
rmdir /S /Q "%TEMP_DIR%"

echo.
echo ============================================
echo   Update abgeschlossen!
echo ============================================
echo.
if exist Anonymisierer_version.txt (
    set /p VER=<Anonymisierer_version.txt
    echo Version: %VER%
    echo.
)
echo Blacklist und Einstellungen wurden nicht veraendert.
echo Zum Starten: %EXE% doppelklicken.
echo.
pause
