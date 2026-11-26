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
    echo Bitte erst den Browser-Tab schliessen.
    pause
    exit /b 1
)

:: Python pruefen
python --version >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python 3.8+ wird benoetigt.
    echo https://www.python.org/downloads/
    echo Wichtig: "Add Python to PATH" aktivieren!
    pause
    exit /b 1
)

:: Aufraeumen falls letztes Update abgebrochen wurde
if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%"

echo Lade neuesten Quellcode von GitHub ...
echo.

powershell -ExecutionPolicy Bypass -NoProfile -Command ^
 "try {" ^
 "  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
 "  Invoke-WebRequest -Uri 'https://github.com/%REPO%/archive/refs/heads/main.zip' -OutFile '_update.zip' -UseBasicParsing;" ^
 "  Expand-Archive '_update.zip' -DestinationPath '%TEMP_DIR%' -Force;" ^
 "  Remove-Item '_update.zip' -Force;" ^
 "} catch {" ^
 "  Write-Host ('[FEHLER] ' + $_.Exception.Message) -ForegroundColor Red; exit 1" ^
 "}"

if not exist "%TEMP_DIR%\anonymizer-main\build.bat" (
    echo [FEHLER] Download fehlgeschlagen.
    if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%"
    pause
    exit /b 1
)

:: build.bat vom Repo ausfuehren
echo Baue neue Version ...
echo.
pushd "%TEMP_DIR%\anonymizer-main"
call build.bat
popd

:: Neue .exe zurueckkopieren
if not exist "%TEMP_DIR%\anonymizer-main\%EXE%" (
    echo [FEHLER] Build fehlgeschlagen - keine .exe erstellt.
    if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%"
    pause
    exit /b 1
)

copy /Y "%TEMP_DIR%\anonymizer-main\%EXE%" "%EXE%" >nul

:: Version merken
if exist "%TEMP_DIR%\anonymizer-main\Anonymisierer_version.txt" (
    copy /Y "%TEMP_DIR%\anonymizer-main\Anonymisierer_version.txt" Anonymisierer_version.txt >nul
)

:: Aufraeumen
rmdir /S /Q "%TEMP_DIR%"

echo.
echo ============================================
echo   Update abgeschlossen!
echo ============================================
echo.
echo Blacklist wurde nicht veraendert.
echo Zum Starten: %EXE% doppelklicken.
echo.
pause
