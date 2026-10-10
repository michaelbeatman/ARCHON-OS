@echo off
chcp 65001 >nul
echo ===================================================
echo [AgenticOS 2026] IMAGE REBUILD / Container Sync
echo ===================================================
echo.
echo 1. Wechsel in Projektordner...
cd /d "%~dp0"

echo.
echo 2. Neues Docker-Image bauen (kopiert main.py + static/ frisch ins Image)...
docker compose build archon-os
if errorlevel 1 (
  echo [FEHLER] Build fehlgeschlagen.
  pause
  exit /b 1
)

echo.
echo 3. Container mit neuem Image neu erstellen und starten...
docker compose up -d --force-recreate archon-os

echo.
echo 4. Pruefe Container Status...
docker ps --filter "name=ARCHON"

echo.
echo ===================================================
echo [OK] Image neu gebaut + Container neu gestartet!
echo Bitte oeffne / aktualisiere den Browser auf http://localhost:8501
echo ===================================================
pause
