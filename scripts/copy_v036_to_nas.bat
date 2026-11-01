@echo off
chcp 65001 >nul
echo =======================================================
echo   Archon OS v0.3.6 - Synchronisation zum Synology NAS
echo =======================================================
echo.

if exist "Y:\_ARCHON Backups" (
    set "DEST=Y:\_ARCHON Backups\releases\Archon v0.3.6"
) else (
    echo [WARNUNG] Laufwerk Y: ist nicht verbunden!
    echo Versuche Netzwerkpfad \\nasdc73fa.local\home\_ARCHON Backups ...
    set "DEST=\\nasdc73fa.local\home\_ARCHON Backups\releases\Archon v0.3.6"
)

echo Zielverzeichnis: %DEST%
mkdir "%DEST%" 2>nul

echo.
echo Kopiere Release-Dateien...
robocopy "C:\.Antigravity-projekte\AgenticOS-2026\backups\Archon_v0.3.6" "%DEST%" /E /Z /R:2 /W:2

echo.
echo =======================================================
echo   Synchronisation abgeschlossen!
echo =======================================================
pause
