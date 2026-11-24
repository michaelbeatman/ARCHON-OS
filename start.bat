@echo off
setlocal enabledelayedexpansion
title ARCHON AGENTIC OS 2026 - Starter
cd /d "%~dp0"

set "STACK_PROFILE=standard"
set "OBS_FLAGS="
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if /i "%%A"=="ARCHON_STACK_PROFILE" set "STACK_PROFILE=%%B"
        if /i "%%A"=="ARCHON_OBSERVABILITY" if /i "%%B"=="full" set "OBS_FLAGS=--profile monitoring --profile logging --profile replication --profile tracing"
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
rem F-073: Alertmanager muss explizit mitgestartet werden — Prometheus hat
rem kein depends_on darauf, sonst bleiben alle 8 Alarme adressenlos.
if defined OBS_FLAGS set "SERVICES=!SERVICES! prometheus grafana uptime-kuma loki promtail litestream alertmanager langfuse"

rem Audit D10: der externe Autoheal ist IMMER Teil des Normal-Starts — nur
rem er erkennt einen Event-Loop-Hang (Docker markiert ihn nur unhealthy,
rem restart: unless-stopped greift nicht bei unhealthy).
set "SERVICES=!SERVICES! archon-autoheal"

echo Starte Archon Agentic OS 2026 + Hermes Agent + AnythingLLM (!STACK_PROFILE!)...
docker compose !OBS_FLAGS! up -d !SERVICES!
if %errorlevel% neq 0 (
    echo [FEHLER] Start fehlgeschlagen. Bitte pruefe Docker Desktop.
    pause
    exit /b 1
)
timeout /t 4 /nobreak >nul
start http://localhost:8501
exit /b 0
