<#
.SYNOPSIS
    Synchronisiert die persistenten Laufzeitdaten und optional den gesamten Code
    zwischen lokalem Entwicklungs-PC und dem Homeserver (micha@192.168.0.43).

.PARAMETER Direction
    "Pull" (Server -> PC) oder "Push" (PC -> Server). Standard: "Pull".

.PARAMETER ServerHost
    SSH-Zieladresse des Homeservers. Standard: "micha@192.168.0.43".

.PARAMETER RemoteDir
    Projektverzeichnis auf dem Homeserver. Standard: "/home/micha/AgenticOS-2026".

.PARAMETER IncludeCode
    Wenn gesetzt, werden auch die Programm-Dateien (main.py, core_dispatcher.py, backend/, static/) übertragen.

.PARAMETER RestartService
    Startet nach einem Code-Push uvicorn / den Systemdienst auf dem Server neu.
#>
param(
    [ValidateSet("Pull", "Push")]
    [string]$Direction = "Pull",
    [string]$ServerHost = "micha@192.168.0.43",
    [string]$RemoteDir = "/home/micha/AgenticOS-2026",
    [switch]$IncludeCode,
    [switch]$RestartService
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = Split-Path -Parent $PSScriptRoot

$RuntimeItems = @(
    "kanban.db",
    "agentic_memory.db",
    "config/org_hierarchy.json",
    "config.yaml",
    "agent_profiles.json"
)

Write-Host "=== Archon OS Runtime-State Sync ($Direction) ===" -ForegroundColor Cyan
Write-Host "Workspace:   $WorkspaceRoot"
Write-Host "Server:      ${ServerHost}:${RemoteDir}"
Write-Host "IncludeCode: $IncludeCode"

if ($Direction -eq "Pull") {
    foreach ($item in $RuntimeItems) {
        $localPath = Join-Path $WorkspaceRoot $item
        $remotePath = "${ServerHost}:${RemoteDir}/${item}"
        Write-Host "[PULL] Lade $item vom Server..." -ForegroundColor Yellow
        scp -o ConnectTimeout=5 $remotePath $localPath 2>$null
    }
    Write-Host "[PULL] Synchronisiere profiles/*.json vom Server..." -ForegroundColor Yellow
    scp -o ConnectTimeout=5 "${ServerHost}:${RemoteDir}/profiles/*.json" (Join-Path $WorkspaceRoot "profiles") 2>$null
    Write-Host "Runtime-State erfolgreich vom Homeserver geladen." -ForegroundColor Green
} else {
    foreach ($item in $RuntimeItems) {
        $localPath = Join-Path $WorkspaceRoot $item
        if (Test-Path $localPath) {
            $remotePath = "${ServerHost}:${RemoteDir}/${item}"
            Write-Host "[PUSH] Übertrage $item zum Server..." -ForegroundColor Yellow
            scp -o ConnectTimeout=5 $localPath $remotePath
        }
    }
    Write-Host "[PUSH] Synchronisiere profiles/*.json zum Server..." -ForegroundColor Yellow
    $profileFiles = Get-ChildItem -Path (Join-Path $WorkspaceRoot "profiles") -Filter "*.json" -ErrorAction SilentlyContinue
    if ($profileFiles) {
        foreach ($pf in $profileFiles) {
            scp -o ConnectTimeout=5 $pf.FullName "${ServerHost}:${RemoteDir}/profiles/$($pf.Name)"
        }
    }

    if ($IncludeCode) {
        Write-Host "[PUSH-CODE] Übertrage Python- und Frontend-Dateien zum Server..." -ForegroundColor Cyan
        $CodeItems = @("main.py", "core_dispatcher.py", "local_memory_bridge.py", "backup_archon.py")
        foreach ($ci in $CodeItems) {
            $src = Join-Path $WorkspaceRoot $ci
            if (Test-Path $src) {
                Write-Host "  -> $ci"
                scp -o ConnectTimeout=5 $src "${ServerHost}:${RemoteDir}/$ci"
            }
        }
        Write-Host "  -> backend/"
        scp -r -o ConnectTimeout=5 (Join-Path $WorkspaceRoot "backend") "${ServerHost}:${RemoteDir}/"
        Write-Host "  -> static/"
        scp -r -o ConnectTimeout=5 (Join-Path $WorkspaceRoot "static") "${ServerHost}:${RemoteDir}/"
        Write-Host "Code erfolgreich synchronisiert." -ForegroundColor Green

        if ($RestartService) {
            Write-Host "[RESTART] Starte Uvicorn auf dem Server neu..." -ForegroundColor Cyan
            ssh -o ConnectTimeout=5 $ServerHost "pkill -f uvicorn || true; nohup python -m uvicorn main:app --host 0.0.0.0 --port 8501 > /tmp/archon.log 2>&1 &"
            Write-Host "Server-Dienst neu gestartet." -ForegroundColor Green
        }
    }
    Write-Host "Push-Vorgang abgeschlossen." -ForegroundColor Green
}
