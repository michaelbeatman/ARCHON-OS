# ARCHON AGENTIC OS 2026 - PowerShell Setup & 1-Click Installer
# ==============================================================

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "         ARCHON AGENTIC OS 2026 - 1-CLICK INSTALLER              " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 1. Pruefe Docker
Write-Host "[1/4] Ueberpruefe Docker Desktop..." -ForegroundColor Yellow
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue

if (-not $dockerCmd) {
    Write-Host ""
    Write-Host "[FEHLER] Docker Desktop wurde nicht gefunden!" -ForegroundColor Red
    Write-Host "Bitte installiere Docker Desktop von: https://www.docker.com/products/docker-desktop/" -ForegroundColor White
    $open = Read-Host "Moechtest du die Docker-Downloadseite jetzt im Browser oeffnen? (J/N)"
    if ($open -eq "J" -or $open -eq "j") {
        Start-Process "https://www.docker.com/products/docker-desktop/"
    }
    exit 1
}

# Pruefe ob Docker Daemon antwortet
$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[HINWEIS] Docker laeuft noch nicht. Starte Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 15
}
Write-Host "[OK] Docker ist betriebsbereit." -ForegroundColor Green
Write-Host ""

# 2. Verzeichnisse & .env
Write-Host "[2/4] Initialisiere Konfiguration & Datenordner..." -ForegroundColor Yellow
@("data", "data\tenants\primary", "logs", ".hermes") | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[OK] .env aus .env.example erstellt." -ForegroundColor Green
    } else {
        Set-Content -Path ".env" -Value "PORT=8501`nWORKSPACE_DIR=/app"
        Write-Host "[OK] Standard .env erstellt." -ForegroundColor Green
    }
} else {
    Write-Host "[OK] Bestehende .env Konfiguration gefunden." -ForegroundColor Green
}
Write-Host ""

# 3. Docker Compose starten
Write-Host "[3/4] Starte Archon OS Cluster (Backend, Hermes, n8n)..." -ForegroundColor Yellow
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FEHLER] Start der Container fehlgeschlagen!" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 4. Healthcheck & Browser Start
Write-Host "[4/4] Warte auf Bereitschaft des Web-Dashboards..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 25; $i++) {
    try {
        $res = Invoke-WebRequest -Uri "http://localhost:8501/api/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($res.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "  ARCHON AGENTIC OS 2026 WURDE ERFOLGREICH GESTARTET!            " -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Web Dashboard:  http://localhost:8501" -ForegroundColor Cyan
Write-Host "Hermes Core:    http://localhost:8644" -ForegroundColor Cyan
Write-Host "n8n Automations:http://localhost:5678" -ForegroundColor Cyan
Write-Host ""
Write-Host "Oeffne Browser..." -ForegroundColor Yellow
Start-Process "http://localhost:8501"
