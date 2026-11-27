@echo off
chcp 65001 >nul
echo ==============================================================================
echo [Archon OS] 1-Klick Update & Snapshot Sync (Homeserver)
echo ==============================================================================
echo.
cd /d "%~dp0\.."

echo.
echo [0/3] Compose-Vertrag pruefen (Audit D10-M6: kein Override-Bypass)...
docker compose -f docker-compose.yml config --quiet
if errorlevel 1 (
  echo.
  echo [FEHLER] docker-compose.yml ungueltig oder Pflicht-Env fehlt.
  echo Bitte .env pruefen; Abbruch ohne Container-Aenderung.
  pause
  exit /b 1
)

echo [1/3] Pruefe System und erstelle Sicherheits-Snapshot...
python backend\system_updater.py --apply
if errorlevel 1 (
  echo.
  echo [FEHLER] Update-Vorgang abgebrochen oder fehlgeschlagen.
  echo Es wurden keine Daten verloren. Bitte Logs pruefen.
  pause
  exit /b 1
)

echo.
echo [2/4] Baue und synchronisiere Docker Container (mit Image-Rebuild)...
docker compose -f docker-compose.yml up -d --build --remove-orphans archon-os
if errorlevel 1 (
  echo [FEHLER] Docker-Rebuild oder Container-Start fehlgeschlagen.
  pause
  exit /b 1
)

echo.
echo [3/4] Bereinige alte Dangling-Images und begrenze Build-Cache auf 4 GB...
docker image prune -f >nul 2>&1
docker builder prune -f --keep-storage 4GB >nul 2>&1

echo.
echo [4/4] Pruefe Service Health...
timeout /t 3 >nul
python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/api/v1/research/providers', timeout=5); print('Archon OS API ist online und bereit!')" 2>nul

echo.
echo ==============================================================================
echo [ERFOLG] Archon OS wurde erfolgreich auf den neuesten Stand gebracht!
echo ==============================================================================
pause
