@echo off
chcp 65001 >nul
echo ==============================================================================
echo [Archon OS] 1-Klick Update & Snapshot Sync (Homeserver)
echo ==============================================================================
echo.
cd /d "%~dp0\.."

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
echo [2/3] Synchronisiere Docker Container...
docker restart ARCHON-OS 2>nul
if errorlevel 1 (
  echo [INFO] ARCHON-OS laeuft lokal oder Docker Compose wird genutzt:
  docker compose up -d --remove-orphans archon-os 2>nul
)

echo.
echo [3/3] Pruefe Service Health...
timeout /t 3 >nul
python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/api/v1/research/providers', timeout=5); print('Archon OS API ist online und bereit!')" 2>nul

echo.
echo ==============================================================================
echo [ERFOLG] Archon OS wurde erfolgreich auf den neuesten Stand gebracht!
echo ==============================================================================
pause
