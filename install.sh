#!/usr/bin/env bash
# ==============================================================================
# Archon OS 2026 — Interactive Full-Stack Installer (Linux & macOS / ARM64 & x64)
# Core Foundations: Docker + Nous Research Hermes Agent + OmniRoute + Obsidian
# Usage: ./install.sh [--yes]
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NON_INTERACTIVE=false
if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
  NON_INTERACTIVE=true
fi

prompt_val() {
  local prompt="$1"
  local default_val="$2"
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    echo "$default_val"
    return
  fi
  local input
  read -r -p "$prompt [Enter = $default_val]: " input || input=""
  if [[ -z "${input// }" ]]; then
    echo "$default_val"
  else
    echo "$input"
  fi
}

gen_hex_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_hex(32))"
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

upsert_env() {
  local key="$1"
  local val="$2"
  local file=".env"
  if command -v python3 >/dev/null 2>&1; then
    ARCHON_ENV_KEY="$key" ARCHON_ENV_VAL="$val" ARCHON_ENV_FILE="$file" python3 - <<'PY'
import os, pathlib, re
key = os.environ["ARCHON_ENV_KEY"]
val = os.environ["ARCHON_ENV_VAL"]
p = pathlib.Path(os.environ["ARCHON_ENV_FILE"])
txt = p.read_text(encoding="utf-8") if p.exists() else ""
pat = re.compile(rf"(?m)^#?{re.escape(key)}=.*$")
if pat.search(txt):
    txt = pat.sub(lambda _: f"{key}={val}", txt, count=1)
else:
    if txt and not txt.endswith("\n"):
        txt += "\n"
    txt += f"{key}={val}\n"
p.write_text(txt, encoding="utf-8")
PY
  else
    grep -vE "^#?${key}=" "$file" 2>/dev/null > "${file}.tmp" || true
    mv "${file}.tmp" "$file"
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}

ensure_env_secret() {
  local key="$1"
  local cur=""
  if [[ -f ".env" ]]; then
    cur="$(grep -E "^${key}=" .env 2>/dev/null | head -n1 | cut -d= -f2- || true)"
  fi
  if [[ -z "${cur// }" ]]; then
    upsert_env "$key" "$(gen_hex_secret)"
  fi
}

echo "=================================================================="
echo "     ARCHON AGENTIC OS 2026 - FULL STACK INSTALLER (UNIX)"
echo "  Foundations: Docker | Hermes Agent | OmniRoute | RAG | Obsidian"
echo "=================================================================="
echo ""

# 1. Foundation Check: Docker Engine / Desktop & Obsidian Desktop
echo "[1/6] Checking Core Foundations (Docker & Obsidian)..."
OS_NAME="$(uname -s)"
if ! command -v docker >/dev/null 2>&1; then
  echo "[MISSING] Docker is required for Archon OS + Hermes Agent."
  if [[ "$NON_INTERACTIVE" != "true" ]]; then
    if [[ "$OS_NAME" == "Linux" ]]; then
      INST_DOC=$(prompt_val "Install Docker Engine automatically via get.docker.com? (Y/N)" "Y")
      if [[ "${INST_DOC,,}" =~ ^(y|yes|j|ja)$ ]]; then
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER" || true
        echo "[INFO] Docker installed. Log out and back in if 'docker' asks for sudo, then re-run ./install.sh."
      else
        exit 1
      fi
    elif [[ "$OS_NAME" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
      INST_DOC=$(prompt_val "Install Docker Desktop via Homebrew? (Y/N)" "Y")
      if [[ "${INST_DOC,,}" =~ ^(y|yes|j|ja)$ ]]; then
        brew install --cask docker
      else
        exit 1
      fi
    else
      echo "Please install Docker from https://www.docker.com/products/docker-desktop/ and retry."
      exit 1
    fi
  else
    exit 1
  fi
fi

if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] Docker daemon is not running. Start Docker Desktop or 'sudo systemctl start docker' and try again."
  exit 1
fi
echo "[OK] Docker is running ($(uname -m))."

# Check Obsidian Desktop (non-blocking)
HAS_OBSIDIAN=false
if [[ "$OS_NAME" == "Darwin" && -d "/Applications/Obsidian.app" ]]; then
  HAS_OBSIDIAN=true
elif command -v obsidian >/dev/null 2>&1; then
  HAS_OBSIDIAN=true
elif command -v flatpak >/dev/null 2>&1 && flatpak info md.obsidian.Obsidian >/dev/null 2>&1; then
  HAS_OBSIDIAN=true
fi

if [[ "$HAS_OBSIDIAN" == "true" ]]; then
  echo "[OK] Obsidian Desktop detected."
else
  echo "[INFO] Obsidian Desktop not found (recommended as visual Second Brain client)."
  if [[ "$NON_INTERACTIVE" != "true" ]]; then
    if [[ "$OS_NAME" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
      INST_OBS=$(prompt_val "Install Obsidian Desktop via Homebrew? (Y/N)" "Y")
      [[ "${INST_OBS,,}" =~ ^(y|yes|j|ja)$ ]] && brew install --cask obsidian || true
    elif [[ "$OS_NAME" == "Linux" ]] && command -v flatpak >/dev/null 2>&1; then
      INST_OBS=$(prompt_val "Install Obsidian Desktop via Flatpak? (Y/N)" "N")
      [[ "${INST_OBS,,}" =~ ^(y|yes|j|ja)$ ]] && flatpak install -y flathub md.obsidian.Obsidian || true
    else
      echo "   Download Obsidian anytime at: https://obsidian.md/download"
    fi
  fi
fi
echo ""

# 2. Interactive Discovery
echo "[2/6] Configuration Wizard (press Enter to accept defaults)"
OBSIDIAN_DIR=$(prompt_val "1) Path to Obsidian Vault" "./obsidian_vault")
mkdir -p "$OBSIDIAN_DIR"/{00_HR_Agenten,01_PROJEKTE,02_Wissensbibliothek,04_Radar,05_Content}

LANG_RAW=$(prompt_val "2) System language (en / de)" "en")
if [[ "$LANG_RAW" == de* ]]; then ARCHON_LANG="de"; else ARCHON_LANG="en"; fi

if [[ "$NON_INTERACTIVE" != "true" ]]; then
  echo "3) Choose Stack Size:"
  echo "   [1] Standard (Recommended, ~4 GB RAM): Archon OS + Hermes + OmniRoute + AnythingLLM/Chroma + Socket Proxy"
  echo "   [2] Full Automation (~7 GB RAM): Standard + n8n Workflows + Ollama-Embed"
  echo "   [3] Minimal Core (Low-RAM ~2.5 GB): Archon OS + Hermes + OmniRoute + Socket Proxy (no RAG)"
fi
STACK_NUM=$(prompt_val "   Select 1, 2, or 3" "1")
case "$STACK_NUM" in
  2) STACK_PROFILE="full" ;;
  3) STACK_PROFILE="minimal" ;;
  *) STACK_PROFILE="standard" ;;
esac

OPENROUTER_KEY=$(prompt_val "4) OpenRouter API Key (shared with Archon, OmniRoute & Hermes; Enter to configure in Web UI)" "")
OPENAI_KEY=""
ANTHROPIC_KEY=""
GEMINI_KEY=""
if [[ -z "$OPENROUTER_KEY" && "$NON_INTERACTIVE" != "true" ]]; then
  OPENAI_KEY=$(prompt_val "   OpenAI API Key (optional)" "")
  ANTHROPIC_KEY=$(prompt_val "   Anthropic API Key (optional)" "")
  GEMINI_KEY=$(prompt_val "   Google Gemini API Key (optional)" "")
fi

LOCAL_DEF="N"
if command -v curl >/dev/null 2>&1 && curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "   [Auto-Detected] Local Ollama found on port 11434!"
  LOCAL_DEF="Y"
fi
USE_LOCAL=$(prompt_val "5) Integrate Local AI (Ollama/LM Studio for DSGVO Zero-Egress)? (Y/N)" "$LOCAL_DEF")
if [[ "${USE_LOCAL,,}" =~ ^(y|yes|j|ja)$ ]]; then ZERO_EGRESS="true"; else ZERO_EGRESS="false"; fi

LAN_ANS=$(prompt_val "6) Allow LAN/Wi-Fi access? (Y = 0.0.0.0, N = 127.0.0.1 localhost only)" "N")
if [[ "${LAN_ANS,,}" =~ ^(y|yes|j|ja)$ ]]; then BIND_IP="0.0.0.0"; else BIND_IP="127.0.0.1"; fi

TG_TOKEN=$(prompt_val "7) Optional Telegram Bot Token (used by Hermes Gateway & Archon; Enter to skip)" "")
TG_CHAT=""
if [[ -n "$TG_TOKEN" ]]; then
  TG_CHAT=$(prompt_val "   Telegram Chat ID" "")
fi
echo ""

# 3. Directories & .env (with cryptographically random per-install secrets)
echo "[3/6] Preparing folders and .env..."
mkdir -p data data/inbox data/tenants/primary agent_workspace/builds logs .hermes .hermes/profiles
if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
  else
    printf "PORT=8501\nHOST=0.0.0.0\n" > .env
  fi
fi
chmod 600 .env || true

if [[ "$OS_NAME" == "Linux" ]]; then
  upsert_env "ARCHON_UID" "$(id -u)"
  upsert_env "ARCHON_GID" "$(id -g)"
fi
upsert_env "ARCHON_BIND_IP" "$BIND_IP"
upsert_env "ARCHON_LANGUAGE" "$ARCHON_LANG"
upsert_env "ARCHON_STACK_PROFILE" "$STACK_PROFILE"
upsert_env "ARCHON_HERMES_DIR" "./.hermes"
upsert_env "ARCHON_OBSIDIAN_DIR" "$OBSIDIAN_DIR"
upsert_env "PRIVACY_ZERO_EGRESS" "$ZERO_EGRESS"
[[ -n "$OPENROUTER_KEY" ]] && upsert_env "OPENROUTER_API_KEY" "$OPENROUTER_KEY"
[[ -n "$OPENAI_KEY" ]]     && upsert_env "OPENAI_API_KEY" "$OPENAI_KEY"
[[ -n "$ANTHROPIC_KEY" ]]  && upsert_env "ANTHROPIC_API_KEY" "$ANTHROPIC_KEY"
[[ -n "$GEMINI_KEY" ]]     && upsert_env "GEMINI_API_KEY" "$GEMINI_KEY"
[[ -n "$TG_TOKEN" ]]       && upsert_env "TELEGRAM_BOT_TOKEN" "$TG_TOKEN"
[[ -n "$TG_CHAT" ]]        && upsert_env "TELEGRAM_CHAT_ID" "$TG_CHAT"

ensure_env_secret "HERMES_DASHBOARD_SESSION_TOKEN"
ensure_env_secret "N8N_USER_MANAGEMENT_JWT_SECRET"
ensure_env_secret "OMNIROUTE_INITIAL_PASSWORD"
echo "[OK] Configuration & unique instance secrets saved to .env (mode 600)."
echo ""

# 4. Pull & Start Containers
echo "[4/6] Building & starting Archon OS ($STACK_PROFILE)..."
SERVICES=(archon-os docker-socket-proxy omniroute hermes)
if [[ "$STACK_PROFILE" == "standard" ]]; then
  SERVICES+=(anything-llm chroma)
elif [[ "$STACK_PROFILE" == "full" || "$STACK_PROFILE" == "rag" ]]; then
  SERVICES+=(anything-llm chroma n8n ollama-embed)
fi

docker compose up -d --build "${SERVICES[@]}"

# 5. Sync 70 SOUL.md + profile.yaml Specialist Profiles
echo "[5/6] Generating 70 Specialist SOUL.md & Hermes profile.yaml configurations ($ARCHON_LANG)..."
if ! docker compose exec -T archon-os python scripts/sync_soul_modes.py --mode compact --lang "$ARCHON_LANG"; then
  echo "[WARN] Profile sync inside container reported an issue; retrying locally if python3 is available..."
  if command -v python3 >/dev/null 2>&1; then
    ARCHON_LANGUAGE="$ARCHON_LANG" python3 scripts/sync_soul_modes.py --mode compact --lang "$ARCHON_LANG" || true
  fi
fi

# 6. Health Check
echo "[6/6] Waiting for Dashboard health check..."
READY=false
for _ in $(seq 1 35); do
  if command -v curl >/dev/null 2>&1 && curl -sf http://127.0.0.1:8501/health >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 2
done

echo ""
echo "=================================================================="
if [[ "$READY" == "true" ]]; then
  echo "  ARCHON OS + HERMES AGENT + OMNIROUTE + OBSIDIAN ARE READY!"
else
  echo "  CONTAINERS STARTED (Warming up...)"
fi
echo "=================================================================="
echo "  Web Dashboard  : http://localhost:8501"
echo "  OmniRoute Hub  : http://localhost:20128"
echo "  Hermes Agent   : Running via Docker Compose (gateway port 8644)"
if [[ "$STACK_PROFILE" != "minimal" && "$STACK_PROFILE" != "core" ]]; then
  echo "  AnythingLLM RAG: http://localhost:3001 (also embedded in Library -> RAG)"
fi
echo "  Obsidian Vault : Open '$OBSIDIAN_DIR' in Obsidian Desktop"
[[ "$BIND_IP" == "0.0.0.0" ]] && echo "  LAN Bind       : Enabled on port 8501 (enable Multi-User Auth in Settings!)"
echo "  Config         : $SCRIPT_DIR/.env"
echo ""

if [[ "$NON_INTERACTIVE" != "true" ]]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:8501 >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open http://localhost:8501 >/dev/null 2>&1 || true
  fi
fi
