<#
.SYNOPSIS
    Archon OS 2026 - Interactive Setup Wizard for Windows (DAU & Power-User)
.DESCRIPTION
    Checks/installs the mandatory foundations (Docker Desktop, Obsidian Desktop + Vault,
    OmniRoute + Nous Research Hermes Agent), collects user preferences (Language, Stack Tier,
    API Keys, Local AI / Zero-Egress, LAN Bind, Telegram), generates unique instance secrets,
    launches the Docker stack, syncs all 70 SOUL + profile.yaml profiles, and verifies live health.
#>
param(
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Write-Header {
    Clear-Host
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host "     ARCHON AGENTIC OS 2026 - FULL STACK SETUP WIZARD (WIN)       " -ForegroundColor Cyan
    Write-Host "  Foundations: Docker | Hermes Agent | OmniRoute | RAG | Obsidian " -ForegroundColor DarkCyan
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Prompt-Choice {
    param(
        [string]$PromptText,
        [string]$DefaultValue
    )
    if ($NonInteractive) { return $DefaultValue }
    $ans = Read-Host "$PromptText [Enter = $DefaultValue]"
    if ([string]::IsNullOrWhiteSpace($ans)) { return $DefaultValue }
    return $ans.Trim()
}

function New-RandomHexSecret {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Upsert-EnvVar {
    param(
        [System.Collections.Generic.List[string]]$Lines,
        [string]$Key,
        [string]$Value
    )
    $updated = $false
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match "^\s*#?\s*$([regex]::Escape($Key))=") {
            $Lines[$i] = "$Key=$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) {
        $Lines.Add("$Key=$Value")
    }
}

function Ensure-EnvSecret {
    param(
        [System.Collections.Generic.List[string]]$Lines,
        [string]$Key
    )
    foreach ($line in $Lines) {
        if ($line -match "^$([regex]::Escape($Key))=(.+)$") {
            return
        }
    }
    Upsert-EnvVar $Lines $Key (New-RandomHexSecret)
}

Write-Header

Write-Host "[1/6] Checking Core Foundations (Docker Desktop & Obsidian)..." -ForegroundColor Yellow

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Host ""
    Write-Host "[MISSING] Docker Desktop is required to run Archon OS + Hermes Agent." -ForegroundColor Red
    if (-not $NonInteractive) {
        $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
        if ($hasWinget) {
            $instDocker = Read-Host "Install Docker Desktop automatically via winget now? (Y/N) [Y]"
            if ([string]::IsNullOrWhiteSpace($instDocker) -or $instDocker -match "^(y|yes|j|ja)$") {
                winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
                Write-Host "[INFO] Please reboot/sign in if prompted, launch Docker Desktop, and run setup.bat again." -ForegroundColor Yellow
                exit 0
            }
        }
        $open = Read-Host "Open Docker Desktop download page in browser? (Y/N) [Y]"
        if ([string]::IsNullOrWhiteSpace($open) -or $open -match "^(y|yes|j|ja)$") {
            Start-Process "https://www.docker.com/products/docker-desktop/"
        }
    }
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Docker Desktop is not running yet. Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
    $dockerOk = $false
    for ($d = 0; $d -lt 25; $d++) {
        Start-Sleep -Seconds 3
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break }
    }
    if (-not $dockerOk) {
        Write-Host "[ERROR] Docker daemon did not respond. Wait until Docker Desktop shows 'Running', then re-run setup.bat." -ForegroundColor Red
        exit 1
    }
}
Write-Host "[OK] Docker Desktop is ready." -ForegroundColor Green

$obsidianExeCandidates = @(
    "$env:LOCALAPPDATA\Obsidian\Obsidian.exe",
    "$env:LOCALAPPDATA\Programs\obsidian\Obsidian.exe",
    "C:\Program Files\Obsidian\Obsidian.exe"
)
$obsidianFound = $obsidianExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $obsidianFound) {
    $obsCmd = Get-Command obsidian -ErrorAction SilentlyContinue
    if ($obsCmd) { $obsidianFound = $obsCmd.Source }
}

if ($obsidianFound) {
    Write-Host "[OK] Obsidian Desktop found: $obsidianFound" -ForegroundColor Green
} else {
    Write-Host "[INFO] Obsidian Desktop not detected (recommended to browse Archon's Second Brain)." -ForegroundColor Yellow
    if (-not $NonInteractive) {
        $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
        if ($hasWinget) {
            $instObs = Prompt-Choice "   Install Obsidian Desktop automatically via winget? (Y/N)" "Y"
            if ($instObs -match "^(y|yes|j|ja)$") {
                winget install -e --id Obsidian.Obsidian --accept-package-agreements --accept-source-agreements
            }
        } else {
            Write-Host "   Download Obsidian anytime at: https://obsidian.md/download" -ForegroundColor Gray
        }
    }
}
Write-Host ""

Write-Host "[2/6] Configuration Wizard (press Enter to accept defaults)" -ForegroundColor Yellow

$obsidianDir = Prompt-Choice "1) Path to Obsidian Vault folder (Archon & Hermes Knowledge Base)" "./obsidian_vault"
if (-not (Test-Path $obsidianDir)) {
    New-Item -ItemType Directory -Path $obsidianDir -Force | Out-Null
}
@("00_HR_Agenten", "01_PROJEKTE", "02_Wissensbibliothek", "04_Radar", "05_Content") | ForEach-Object {
    $sub = Join-Path $obsidianDir $_
    if (-not (Test-Path $sub)) { New-Item -ItemType Directory -Path $sub -Force | Out-Null }
}

$langRaw = Prompt-Choice "2) System language: [en] English or [de] Deutsch" "en"
$lang = if ($langRaw -match "^de") { "de" } else { "en" }

if (-not $NonInteractive) {
    Write-Host "3) Choose Stack Size:" -ForegroundColor White
    Write-Host "   [1] Standard (Recommended, ~4 GB RAM): Archon OS + Hermes + OmniRoute + AnythingLLM/Chroma + Socket Proxy" -ForegroundColor Gray
    Write-Host "   [2] Full Automation (~7 GB RAM): Standard + n8n Workflows + Ollama-Embed" -ForegroundColor Gray
    Write-Host "   [3] Minimal Core (Low-RAM ~2.5 GB): Archon OS + Hermes + OmniRoute + Socket Proxy (no RAG)" -ForegroundColor Gray
}
$stackChoice = Prompt-Choice "   Select 1, 2, or 3" "1"
$stackProfile = switch ($stackChoice) {
    "2" { "full" }
    "3" { "minimal" }
    default { "standard" }
}

if (-not $NonInteractive) {
    Write-Host "4) AI Provider API Keys (shared cleanly with Archon OS, OmniRoute & Hermes Agent):" -ForegroundColor White
}
$openrouterKey = Prompt-Choice "   OpenRouter API Key (Recommended: 1 key unlocks Gemini/Claude/GPT/DeepSeek)" ""
$openaiKey = ""
$anthropicKey = ""
$geminiKey = ""
if ([string]::IsNullOrWhiteSpace($openrouterKey) -and -not $NonInteractive) {
    $openaiKey    = Prompt-Choice "   OpenAI API Key (optional)" ""
    $anthropicKey = Prompt-Choice "   Anthropic API Key (optional)" ""
    $geminiKey    = Prompt-Choice "   Google Gemini API Key (optional)" ""
}

$localAiDetected = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -UseBasicParsing | Out-Null
    $localAiDetected = $true
    Write-Host "   [Auto-Detected] Ollama is running locally on port 11434!" -ForegroundColor Green
} catch {}

$useLocalDefault = if ($localAiDetected) { "Y" } else { "N" }
$useLocalAns = Prompt-Choice "5) Integrate Local AI (Ollama/LM Studio for DSGVO Zero-Egress)? (Y/N)" $useLocalDefault
$zeroEgress = if ($useLocalAns -match "^(y|yes|j|ja)$") { "true" } else { "false" }

$lanAns = Prompt-Choice "6) Allow access from other devices on your local Wi-Fi/LAN? (Y = 0.0.0.0, N = 127.0.0.1)" "N"
$bindIp = if ($lanAns -match "^(y|yes|j|ja)$") { "0.0.0.0" } else { "127.0.0.1" }

$tgToken = Prompt-Choice "7) Optional Telegram Bot Token (used by Hermes Gateway & Archon, Enter to skip)" ""
$tgChat  = ""
if (-not [string]::IsNullOrWhiteSpace($tgToken)) {
    $tgChat = Prompt-Choice "   Telegram Chat ID" ""
}

Write-Host ""

Write-Host "[3/6] Preparing directories and .env..." -ForegroundColor Yellow
@("data", "data\inbox", "data\tenants\primary", "agent_workspace\builds", "logs", ".hermes", ".hermes\profiles") | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
    } else {
        Set-Content -Path ".env" -Value "PORT=8501`nHOST=0.0.0.0"
    }
}

$envLines = [System.Collections.Generic.List[string]]::new([string[]](Get-Content ".env" -Encoding UTF8))
Upsert-EnvVar $envLines "ARCHON_BIND_IP" $bindIp
Upsert-EnvVar $envLines "ARCHON_LANGUAGE" $lang
Upsert-EnvVar $envLines "ARCHON_STACK_PROFILE" $stackProfile
Upsert-EnvVar $envLines "ARCHON_HERMES_DIR" "./.hermes"
Upsert-EnvVar $envLines "ARCHON_OBSIDIAN_DIR" $obsidianDir
Upsert-EnvVar $envLines "PRIVACY_ZERO_EGRESS" $zeroEgress
if (-not [string]::IsNullOrWhiteSpace($openrouterKey)) { Upsert-EnvVar $envLines "OPENROUTER_API_KEY" $openrouterKey }
if (-not [string]::IsNullOrWhiteSpace($openaiKey))     { Upsert-EnvVar $envLines "OPENAI_API_KEY" $openaiKey }
if (-not [string]::IsNullOrWhiteSpace($anthropicKey))  { Upsert-EnvVar $envLines "ANTHROPIC_API_KEY" $anthropicKey }
if (-not [string]::IsNullOrWhiteSpace($geminiKey))     { Upsert-EnvVar $envLines "GEMINI_API_KEY" $geminiKey }
if (-not [string]::IsNullOrWhiteSpace($tgToken))       { Upsert-EnvVar $envLines "TELEGRAM_BOT_TOKEN" $tgToken }
if (-not [string]::IsNullOrWhiteSpace($tgChat))        { Upsert-EnvVar $envLines "TELEGRAM_CHAT_ID" $tgChat }
Ensure-EnvSecret $envLines "HERMES_DASHBOARD_SESSION_TOKEN"
Ensure-EnvSecret $envLines "N8N_USER_MANAGEMENT_JWT_SECRET"
Ensure-EnvSecret $envLines "OMNIROUTE_INITIAL_PASSWORD"
Set-Content -Path ".env" -Value $envLines -Encoding UTF8

Write-Host "[OK] Configuration saved to .env." -ForegroundColor Green
Write-Host ""

Write-Host "[4/6] Pulling containers & building Archon OS ($stackProfile)..." -ForegroundColor Yellow
$services = @("archon-os", "docker-socket-proxy", "omniroute", "hermes")
if ($stackProfile -eq "standard") {
    $services += @("anything-llm", "chroma")
} elseif ($stackProfile -eq "full" -or $stackProfile -eq "rag") {
    $services += @("anything-llm", "chroma", "n8n", "ollama-embed")
}

& docker compose up -d --build @services
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Docker Compose failed. Check logs via: docker compose logs archon-os hermes" -ForegroundColor Red
    exit 1
}

Write-Host "[5/6] Generating 70 Specialist SOUL.md & Hermes profile.yaml configurations ($lang)..." -ForegroundColor Yellow
& docker compose exec -T archon-os python scripts/sync_soul_modes.py --mode compact --lang $lang
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] Profile sync inside container reported a warning; continuing health check..." -ForegroundColor Yellow
} else {
    Write-Host "[OK] 70 Specialist SOUL & profile.yaml configurations ready." -ForegroundColor Green
}
Write-Host ""

Write-Host "[6/6] Waiting for Archon OS Dashboard (http://127.0.0.1:8501/health)..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 35; $i++) {
    try {
        $res = Invoke-WebRequest -Uri "http://127.0.0.1:8501/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($res.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
if ($ready) {
    Write-Host "  ARCHON OS + HERMES AGENT + OMNIROUTE + OBSIDIAN ARE READY!" -ForegroundColor Green
} else {
    Write-Host "  CONTAINERS STARTED (Dashboard is still warming up...)" -ForegroundColor Yellow
}
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "  Web Dashboard  : http://localhost:8501" -ForegroundColor Cyan
Write-Host "  OmniRoute Hub  : http://localhost:20128" -ForegroundColor Cyan
Write-Host "  Hermes Agent   : Active on internal gateway (port 8644)" -ForegroundColor Cyan
if ($services -contains "anything-llm") {
    Write-Host "  AnythingLLM RAG: http://localhost:3001 (also embedded in Library -> RAG)" -ForegroundColor Cyan
}
Write-Host "  Obsidian Vault : Open '$((Resolve-Path $obsidianDir).Path)' in Obsidian Desktop" -ForegroundColor Cyan
if ($bindIp -eq "0.0.0.0") {
    Write-Host "  LAN Access     : Enabled on port 8501 (enable Multi-User Auth in Settings!)" -ForegroundColor Cyan
}
if ($services -contains "n8n") {
    Write-Host "  n8n Workflows  : http://localhost:5678" -ForegroundColor Cyan
}
Write-Host "  Daily Start    : Double-click start.bat  |  Stop: stop.bat" -ForegroundColor White
Write-Host ""
if (-not $NonInteractive) {
    Start-Process "http://localhost:8501"
}
