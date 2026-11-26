@echo off
chcp 65001 >nul 2>&1
title Anonymisierer - Update
cd /d "%~dp0"

set REPO=durums/anonymizer
set EXE=Anonymisierer.exe
set VER_DATEI=Anonymisierer_version.txt

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

:: Blacklist sichern falls vorhanden (wird NIE ueberschrieben)
if exist blacklist.txt (
    echo Blacklist gefunden - wird beibehalten.
)

:: GitHub-Update via PowerShell
if exist "%EXE%" (
    echo Pruefe auf neue Version ...
) else (
    echo Erstinstallation - lade Anonymisierer herunter ...
)
echo.

powershell -ExecutionPolicy Bypass -NoProfile -Command ^
 "$ErrorActionPreference = 'Stop';" ^
 "$verDatei = '%~dp0%VER_DATEI%';" ^
 "$exe = '%~dp0%EXE%';" ^
 "try {" ^
 "  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
 "  $rel = Invoke-RestMethod 'https://api.github.com/repos/%REPO%/releases/latest';" ^
 "  $tag = $rel.tag_name -replace '^v','';" ^
 "  $aktuell = if (Test-Path $verDatei) { (Get-Content $verDatei -Raw).Trim() } else { '?' };" ^
 "  Write-Host ('  Installiert:  ' + $aktuell);" ^
 "  Write-Host ('  Verfuegbar:   ' + $tag);" ^
 "  Write-Host '';" ^
 "  if ($aktuell -eq $tag) {" ^
 "    Write-Host 'Bereits auf dem neuesten Stand!' -ForegroundColor Green;" ^
 "    exit 0" ^
 "  }" ^
 "  $asset = $rel.assets | Where-Object { $_.name -like '*.exe' } | Select-Object -First 1;" ^
 "  if (-not $asset) {" ^
 "    Write-Host '[FEHLER] Kein .exe im GitHub Release gefunden.' -ForegroundColor Red;" ^
 "    Write-Host 'Bitte beim Ersteller nachfragen.';" ^
 "    exit 1" ^
 "  }" ^
 "  Write-Host ('Lade ' + $asset.name + ' herunter (' + [math]::Round($asset.size/1MB,1) + ' MB) ...');" ^
 "  $tmp = $exe + '.update';" ^
 "  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing;" ^
 "  if (Test-Path $exe) { Remove-Item $exe -Force }" ^
 "  Rename-Item $tmp '%EXE%' -Force;" ^
 "  Set-Content $verDatei $tag -NoNewline;" ^
 "  Write-Host '';" ^
 "  Write-Host ('Update auf ' + $tag + ' abgeschlossen!') -ForegroundColor Green;" ^
 "} catch {" ^
 "  Write-Host '';" ^
 "  Write-Host ('[FEHLER] ' + $_.Exception.Message) -ForegroundColor Red;" ^
 "  Write-Host '';" ^
 "  Write-Host 'Moegl. Ursachen:';" ^
 "  Write-Host '  - Keine Internetverbindung';" ^
 "  Write-Host '  - GitHub nicht erreichbar (Proxy/Firewall)';" ^
 "  Write-Host '  - Noch kein Release veroeffentlicht';" ^
 "  exit 1" ^
 "}"

echo.
pause
