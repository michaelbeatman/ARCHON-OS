@echo off
title ARCHON AGENTIC OS 2026 - Starter
cd /d "%~dp0"
echo Starte Archon Agentic OS 2026...
docker compose up -d
timeout /t 3 /nobreak >nul
start http://localhost:8501
exit /b 0
