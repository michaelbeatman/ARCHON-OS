@echo off
chcp 65001 >nul
echo ===================================================
echo [AgenticOS 2026] Neustart / Container Sync (Rebuild)
echo ===================================================
echo.
echo 1. Wechsel in Projektordner...
cd /d "%~dp0"

echo.
echo 1b. Pruefe auf GitHub-Updates (git pull)...
git pull origin main --rebase
if errorlevel 1 (
  echo [HINWEIS] Kein Update gezogen (offline oder lokale Aenderungen vorhanden). Fahre fort...
)

echo.
echo 2. Baue das Docker-Image neu (kopiert main.py + static/ frisch ins Image)...
docker compose build archon-os
if errorlevel 1 (
  echo [FEHLER] Build fehlgeschlagen - Abbruch.
  pause
  exit /b 1
)

echo.
echo 3. Entferne alten ARCHON-OS Container (falls vorhanden)...
docker stop ARCHON-OS 2>nul
docker rm ARCHON-OS 2>nul

echo.
echo 4. Container mit neuem Image neu erstellen und starten...
docker compose up -d --force-recreate --remove-orphans archon-os

echo.
echo 5. Pruefe Container Status...
docker ps --filter "name=ARCHON"

echo.
echo ===================================================
echo [OK] Image neu gebaut + Container neu gestartet!
echo Bitte oeffne / aktualisiere den Browser auf http://localhost:8501
echo ===================================================
pause
