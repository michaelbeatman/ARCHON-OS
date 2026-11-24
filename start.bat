@echo off
setlocal enabledelayedexpansion
title ARCHON AGENTIC OS 2026 - Starter
cd /d "%~dp0"

set "STACK_PROFILE=standard"
set "OBS_FLAGS="
set "TG_TOKEN_SET="
set "TG_CHAT_SET="
set "ALERTS_CONFIGURED="
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if /i "%%A"=="ARCHON_STACK_PROFILE" set "STACK_PROFILE=%%B"
        if /i "%%A"=="ARCHON_OBSERVABILITY" if /i "%%B"=="full" set "OBS_FLAGS=--profile monitoring --profile logging --profile replication --profile tracing"
        if /i "%%A"=="TELEGRAM_BOT_TOKEN" if not "%%B"=="" set "TG_TOKEN_SET=1"
        if /i "%%A"=="TELEGRAM_CHAT_ID" if not "%%B"=="" set "TG_CHAT_SET=1"
    )
)

docker network inspect archon-os-dev_agents_net >nul 2>&1 || docker network create archon-os-dev_agents_net >nul 2>&1

set "SERVICES=archon-os docker-socket-proxy hermes anything-llm chroma"
if /i "!STACK_PROFILE!"=="minimal" set "SERVICES=archon-os docker-socket-proxy hermes"
if /i "!STACK_PROFILE!"=="core" set "SERVICES=archon-os docker-socket-proxy hermes"
if /i "!STACK_PROFILE!"=="full" set "SERVICES=archon-os docker-socket-proxy hermes anything-llm chroma n8n ollama-embed"
if /i "!STACK_PROFILE!"=="rag" set "SERVICES=archon-os docker-socket-proxy hermes anything-llm chroma n8n ollama-embed"

rem C23: Profile starten keine Container, wenn eine explizite Service-Liste
rem uebergeben wird -> die Profil-Services ergoenzend aufnehmen.
rem Audit D10: Alertmanager NUR mit gesetzten Telegram-Secrets mitstarten —
rem ohne Secrets meldet der Stack ehrlich `alerts_not_configured`.
rem Audit D09/D10 (D-D8): langfuse (v2, EOL) ist aus Compose/Startern entfernt.
if defined OBS_FLAGS (
    set "SERVICES=!SERVICES! prometheus grafana uptime-kuma loki promtail litestream"
    if defined TG_TOKEN_SET if defined TG_CHAT_SET (
        set "SERVICES=!SERVICES! alertmanager"
        set "ALERTS_CONFIGURED=1"
    ) else (
        echo [INFO] alerts_not_configured: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID fehlen - Alertmanager wird nicht gestartet.
    )
)

rem Audit D10: der externe Autoheal ist IMMER Teil des Normal-Starts — nur
rem er erkennt einen Event-Loop-Hang (Docker markiert ihn nur unhealthy,
rem restart: unless-stopped greift nicht bei unhealthy).
set "SERVICES=!SERVICES! archon-autoheal"

echo Starte Archon Agentic OS 2026 + Hermes Agent + AnythingLLM (!STACK_PROFILE!)...
rem Audit D10: immer die produktive Compose-Datei. Eine gitignored
rem docker-compose.override.yml wuerde sonst /app bind-mounen und die .env
rem mit dem Audit-HMAC-Key in den Container exposed.
docker compose -f docker-compose.yml config --quiet
if !errorlevel! neq 0 (
    echo [FEHLER] docker-compose.yml ist ungueltig.
    pause
    exit /b 1
)
docker compose -f docker-compose.yml !OBS_FLAGS! up -d !SERVICES!
if !errorlevel! neq 0 (
    echo [FEHLER] Start fehlgeschlagen. Bitte pruefe Docker Desktop.
    pause
    exit /b 1
)

rem Audit D10: verpflichtender Testalarm direkt nach dem Start.
if defined ALERTS_CONFIGURED (
    rem Alertmanager hat start_period 20 s — erst auf /-/healthy warten.
    set "ALERT_READY="
    for /L %%i in (1,1,10) do (
        if not defined ALERT_READY (
            curl.exe -sf -o NUL http://localhost:9093/-/healthy
            if !errorlevel! equ 0 set "ALERT_READY=1"
        )
        if not defined ALERT_READY timeout /t 2 /nobreak >nul
    )
    if not defined ALERT_READY (
        echo [FEHLER] Alertmanager nicht binnen 20 s bereit — kein Testalarm moeglich.
        pause
        exit /b 1
    )
    echo Sende Alertmanager-Testalarm...
    >"%TEMP%\archon_testalert.json" echo [{"labels":{"alertname":"ArchonAlertmanagerSmokeTest","severity":"critical","service":"archon-deploy"},"annotations":{"summary":"Archon OS Alertmanager smoke test","description":"Testalarm nach dem Deploy - bitte Telegram-Empfang pruefen"}}]
    curl.exe -sf -o NUL -H "Content-Type: application/json" --data-binary "@%TEMP%\archon_testalert.json" http://localhost:9093/api/v2/alerts
    if !errorlevel! neq 0 (
        echo [FEHLER] Testalarm nicht an Alertmanager zugestellt.
        pause
        exit /b 1
    )
    echo [OK] Testalarm an Alertmanager zugestellt - Telegram-Empfang bitte pruefen.
)
timeout /t 4 /nobreak >nul
start http://localhost:8501
exit /b 0
