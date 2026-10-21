# ==============================================================================
# AgenticOS / Archon OS 2026 — Automated Setup Script for Windows PowerShell
# ==============================================================================
$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting AgenticOS 2026 Setup for Windows..." -ForegroundColor Cyan

# 1. Check Python
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-Host "❌ Error: python was not found on PATH. Please install Python 3.11+." -ForegroundColor Red
    exit 1
}

$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "✓ Found Python $pyVer" -ForegroundColor Green

# 2. Virtual Environment
if (-not (Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment (.venv)..." -ForegroundColor Yellow
    & python -m venv .venv
} else {
    Write-Host "✓ Existing .venv detected." -ForegroundColor Green
}

& .\.venv\Scripts\Activate.ps1

# 3. Install requirements
Write-Host "📦 Installing Python dependencies from requirements.txt..." -ForegroundColor Yellow
& python -m pip install --upgrade pip
& python -m pip install -r requirements.txt

# 4. Environment config (.env)
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "📝 Creating .env from .env.example..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "⚠️ Please review .env with your specific API keys." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "✓ .env file exists." -ForegroundColor Green
}

# 5. Database check
Write-Host "🔍 Checking SQLite Database..." -ForegroundColor Yellow
& python -c "import sqlite3; con = sqlite3.connect('data/agentic_memory.db'); tables = [r[0] for r in con.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall()]; print('✓ Database tables found:', len(tables)); con.close()"

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host "To start Archon OS, run:" -ForegroundColor White
Write-Host "    .\.venv\Scripts\activate" -ForegroundColor White
Write-Host "    python main.py" -ForegroundColor White
Write-Host "==============================================================================" -ForegroundColor Cyan
