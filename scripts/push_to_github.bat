@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo ========================================================
echo   Archon OS - Entwicklungsrechner Git Push zu GitHub
echo ========================================================
echo.

cd /d "%~dp0\.."

set "COMMIT_MSG=%~1"
if "%COMMIT_MSG%"=="" (
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
    set "DATE_STR=!datetime:~0,4!-!datetime:~4,2!-!datetime:~6,2! !datetime:~8,2!:!datetime:~10,2!"
    set "COMMIT_MSG=Dev-Sync: !DATE_STR!"
)

echo [1/3] Pruefe Status und fuege Aenderungen hinzu...
git add -A

echo [2/3] Erstelle Commit: "%COMMIT_MSG%"...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo [Hinweis] Keine neuen Aenderungen zum Committen vorhanden oder Commit abgebrochen.
)

echo [3/3] Pushe zu GitHub origin/main...
git push origin main
if errorlevel 1 (
    echo [FEHLER] Git Push fehlgeschlagen! Bitte Verbindung oder Token pruefen.
    exit /b 1
)

echo.
echo [ERFOLG] Aenderungen wurden erfolgreich zu GitHub gepusht!
echo Auf dem Server kann nun das Update eingespielt werden.
echo ========================================================
