@echo off
title ARCHON AGENTIC OS 2026 - 1-Click Setup
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if %errorlevel% neq 0 (
    echo.
    echo Setup ended with exit code %errorlevel%.
    pause
    exit /b %errorlevel%
)
exit /b 0
