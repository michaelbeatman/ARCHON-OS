#!/usr/bin/env bash
# ==============================================================================
# AgenticOS / Archon OS 2026 — Automated Setup Script for Linux/macOS
# ==============================================================================
set -e

echo "🚀 Starting AgenticOS 2026 Setup..."

# 1. Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed. Please install Python 3.11+."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Found Python $PY_VER"

# 2. Virtual Environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment (.venv)..."
    python3 -m venv .venv
else
    echo "✓ Existing .venv detected."
fi

source .venv/bin/activate

# 3. Upgrade pip and install requirements
echo "📦 Installing Python dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Environment config (.env)
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "📝 Creating .env from .env.example..."
        cp .env.example .env
        echo "⚠️ Please edit .env with your specific API keys and network settings."
    fi
else
    echo "✓ .env file exists."
fi

# 5. Database check
echo "🔍 Checking SQLite Database..."
python -c "import sqlite3; con = sqlite3.connect('data/agentic_memory.db'); tables = [r[0] for r in con.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall()]; print('✓ Database tables found:', len(tables)); con.close()"

echo "=============================================================================="
echo "✅ Setup complete!"
echo "To start Archon OS, run:"
echo "    source .venv/bin/activate"
echo "    python main.py"
echo "To start the Watchdog daemon in the background:"
echo "    python watchdog_daemon.py &"
echo "=============================================================================="
