@echo off
setlocal enabledelayedexpansion
title ARCHON AGENTIC OS 2026 - Starter
cd /d "%~dp0"

set "STACK_PROFILE=standard"
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if /i "%%A"=="ARCHON_STACK_PROFILE" set "STACK_PROFILE=%%B"
    )
)

docker network inspect archon-os-dev_agents_net >nul 2>&1 || docker network create archon-os-dev_agents_net >nul 2>&1

set "SERVICES=archon-os docker-socket-proxy hermes anything-llm chroma"
if /i "!STACK_PROFILE!"=="minimal" set "SERVICES=archon-os docker-socket-proxy hermes"
if /i "!STACK_PROFILE!"=="core" set "SERVICES=archon-os docker-socket-proxy hermes"
if /i "!STACK_PROFILE!"=="full" set "SERVICES=archon-os docker-socket-proxy hermes anything-llm chroma n8n ollama-embed"
if /i "!STACK_PROFILE!"=="rag" set "SERVICES=archon-os docker-socket-proxy hermes anything-llm chroma n8n ollama-embed"

echo Starte Archon Agentic OS 2026 + Hermes Agent + AnythingLLM (!STACK_PROFILE!)...
docker compose up -d !SERVICES!
if %errorlevel% neq 0 (
    echo [FEHLER] Start fehlgeschlagen. Bitte pruefe Docker Desktop.
    pause
    exit /b 1
)
timeout /t 4 /nobreak >nul
start http://localhost:8501
exit /b 0
