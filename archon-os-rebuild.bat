@echo off
chcp 65001 >nul
echo ===================================================
echo [AgenticOS 2026] IMAGE REBUILD / Container Sync
echo ===================================================
echo.
echo 1. Wechsel in Projektordner...
cd /d "%~dp0"

echo.
echo 1b. Compose-Vertrag pruefen (Audit D10-M6: kein Override-Bypass)...
docker compose -f docker-compose.yml config --quiet
if errorlevel 1 (
  echo [FEHLER] docker-compose.yml ungueltig oder Pflicht-Env fehlt.
  echo Eine gitignorierte docker-compose.override.yml wuerde sonst /app
  echo bind-mounten und die .env mit dem Audit-HMAC-Key exposed.
  pause
  exit /b 1
)

echo.
echo 2. Neues Docker-Image bauen (kopiert main.py + static/ frisch ins Image)...
docker compose -f docker-compose.yml build archon-os
if errorlevel 1 (
  echo [FEHLER] Build fehlgeschlagen.
  pause
  exit /b 1
)

echo.
echo 3. Container mit neuem Image neu erstellen und starten...
docker compose -f docker-compose.yml up -d --force-recreate archon-os

echo.
echo 4. Pruefe Container Status...
docker ps --filter "name=ARCHON"

echo.
echo ===================================================
echo [OK] Image neu gebaut + Container neu gestartet!
echo Bitte oeffne / aktualisiere den Browser auf http://localhost:8501
echo ===================================================
pause
