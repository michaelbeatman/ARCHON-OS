@echo off
chcp 65001 >nul
echo ===================================================
echo [AgenticOS 2026] GitHub Sync & Push
echo ===================================================
echo.
cd /d "%~dp0"

echo 1. Pruefe aktuellen Git-Status...
git status -s

echo.
echo 2. Fuege freigegebene Aenderungen hinzu...
git add -A

echo.
echo 3. Erstelle Commit...
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set dt=%%I
if defined dt (
  set TIMESTAMP=%dt:~0,4%-%dt:~4,2%-%dt:~6,2% %dt:~8,2%:%dt:~10,2%
) else (
  set TIMESTAMP=%date% %time%
)

git commit -m "Auto-Sync: %TIMESTAMP%"
if errorlevel 1 (
  echo [INFO] Keine neuen Aenderungen zum Committen vorhanden.
)

echo.
echo 4. Hole Updates von GitHub ab (Rebase)...
git pull origin main --rebase

echo.
echo 5. Uebertrage Aenderungen zu GitHub (Push)...
git push origin main
if errorlevel 1 (
  echo.
  echo ===================================================
  echo [FEHLER] Push fehlgeschlagen!
  echo Falls du dich noch nicht angemeldet hast, sollte sich
  echo jetzt ein GitHub-Login-Fenster geoeffnet haben.
  echo ===================================================
) else (
  echo.
  echo ===================================================
  echo [OK] Stand erfolgreich mit GitHub synchronisiert!
  echo ===================================================
)

echo.
pause
