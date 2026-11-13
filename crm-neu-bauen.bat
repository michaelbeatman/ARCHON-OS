@echo off
title CRM Frontend NEU BAUEN (Archon)
echo ============================================
echo  CRM Frontend wird neu gebaut und gestartet
echo  Das dauert ca. 2-5 Minuten. Bitte warten...
echo ============================================
echo.
cd /d "%~dp0"
echo [1/2] Baue Docker-Image (laedt die neuen Aenderungen)...
docker compose -f CRM/docker-compose.yml up -d --build CRM
echo.
if %errorlevel%==0 (
  echo ============================================
  echo  [2/2] FERTIG! CRM laeuft mit der neuen Version.
  echo  Jetzt im Browser F5 druecken (oder Chrome neu starten).
  echo ============================================
) else (
  echo.
  echo  FEHLER! Bitte diese Meldung abfotografieren
  echo  und an den Assistenten schicken.
)
echo.
pause
