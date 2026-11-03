@echo off
title ARCHON AGENTIC OS 2026 - Stop
cd /d "%~dp0"
echo Beende Archon OS Container...
docker compose down
echo Alle Dienste sicher gestoppt.
timeout /t 2 /nobreak >nul
exit /b 0
