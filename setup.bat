@echo off
setlocal enabledelayedexpansion
title ARCHON AGENTIC OS 2026 - 1-Click Installer
color 0B

echo ==============================================================================
echo                ARCHON AGENTIC OS 2026 - 1-CLICK INSTALLER
echo                Autonomes Agenten-Betriebssystem fuer Michael Keller
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. Docker-Pruefung
echo [1/4] Ueberpruefe Systemvoraussetzungen...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ==============================================================================
    echo [FEHLER] Docker Desktop ist auf diesem Rechner noch nicht installiert!
    echo ==============================================================================
    echo.
    echo Archon OS benoetigt Docker Desktop fuer Container-Isolation und Daemon-Betrieb.
    echo.
    echo Bitte installiere Docker Desktop:
    echo 1. Download: https://www.docker.com/products/docker-desktop/
    echo 2. Setup ausfuehren und Rechner ggf. neu starten.
    echo 3. Docker Desktop starten und dieses Setup erneut per Doppelklick oeffnen.
    echo.
    set /p OPEN_BROWSER="Moechtest du die Docker-Downloadseite jetzt im Browser oeffnen? (J/N): "
    if /i "!OPEN_BROWSER!"=="J" (
        start https://www.docker.com/products/docker-desktop/
    )
    echo.
    echo Setup abgebrochen. Druecke eine beliebige Taste zum Beenden...
    pause >nul
    exit /b 1
)

:: Pruefe ob Docker Daemon laeuft
docker info >nul 2>&1
if %errorlevel% neq 0 (
    color 0E
    echo.
    echo [HINWEIS] Docker ist installiert, aber der Docker Daemon laeuft noch nicht.
    echo Starte Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe" >nul 2>&1
    echo Warte 15 Sekunden auf den Start von Docker...
    timeout /t 15 /nobreak >nul
)

echo [OK] Docker Desktop ist betriebsbereit.
echo.

:: 2. Verzeichnisse & Umgebungsvariablen (.env)
echo [2/4] Initialisiere Konfiguration und Verzeichnisse...
if not exist "data" mkdir "data"
if not exist "data\tenants\primary" mkdir "data\tenants\primary"
if not exist "logs" mkdir "logs"
if not exist ".hermes" mkdir ".hermes"

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [OK] Standard-.env aus Vorlage erstellt.
    ) else (
        echo PORT=8501 > .env
        echo WORKSPACE_DIR=/app >> .env
        echo [OK] Basis-.env erstellt.
    )
) else (
    echo [OK] Bestehende .env-Konfiguration gefunden.
)
echo.

:: 3. Container starten via Docker Compose
echo [3/4] Starte Archon OS Cluster (ARCHON-OS, Hermes, n8n)...
docker compose up -d
if %errorlevel% neq 0 (
    color 0C
    echo [FEHLER] Start der Container fehlgeschlagen. Bitte Logs pruefen: docker compose logs
    pause
    exit /b 1
)
echo.

:: 4. Healthcheck & Browser-Start
echo [4/4] Warte auf Bereitschaft des Archon OS Web-Dashboards...
set RETRIES=0
:WAIT_LOOP
set /a RETRIES+=1
curl -s -f http://localhost:8501/api/health >nul 2>&1
if %errorlevel% neq 0 (
    if !RETRIES! lss 20 (
        timeout /t 2 /nobreak >nul
        goto WAIT_LOOP
    )
)

color 0A
echo.
echo ==============================================================================
echo   ERFOLG: ARCHON AGENTIC OS 2026 IST ERFOLGREICH GESTARTET!
echo ==============================================================================
echo.
echo Dashboard:     http://localhost:8501
echo Hermes Core:   http://localhost:8644
echo n8n Workflow:  http://localhost:5678
echo.
echo Oeffne Dashboard im Browser...
start http://localhost:8501

echo.
echo Du kannst dieses Konsolenfenster nun schliessen.
echo Zum Beenden des Systems fuehre einfach 'stop.bat' aus.
echo.
pause
exit /b 0
