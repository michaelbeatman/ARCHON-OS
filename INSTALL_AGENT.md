# AI Agent Onboarding & Installation Protocol (`INSTALL_AGENT.md`)

> **Target Audience:** AI Coding & System Agents (*Antigravity, Claude Code, OpenAI Codex, Cursor, Windsurf, Cline*) asked by a user to install, configure, or localize **Archon OS** on a fresh machine or homeserver.

---

## Mandatory Core Foundations (The 4 Archon Pillars)

Archon OS relies on **four foundational modules** working together. Never leave the Vector-RAG tab (`Central Library → AnythingLLM`) broken on a fresh install unless the user explicitly chooses a Low-RAM Minimal footprint:

1. **Docker Desktop / Docker Engine + Compose v2:** Runs Archon OS, Socket Proxy, Hermes Agent, AnythingLLM, Chroma, and optional n8n in isolated containers.
2. **Nous Research Hermes Agent (`nousresearch/hermes-agent:latest`):** The autonomous agent runtime & Telegram/session gateway (`hermes` service in `docker-compose.yml`, reading `./.hermes/profiles` and `SOUL.md`).
3. **AnythingLLM + Chroma (`mintplexlabs/anythingllm:latest` + `chromadb/chroma:latest`):** Vector RAG Engine (port `3001`) powering *Central Library → AnythingLLM* with persistent knowledge indexing (`anythingllm_storage` + mounted Obsidian Vault).
4. **Obsidian (Desktop App + Mounted Vault):** The persistent Markdown Second Brain (`ARCHON_OBSIDIAN_DIR`, mounted at `/opt/data/obsidian`). Archon reads/writes `.md` files directly inside the Vault folder, and the user explores Knowledge Graphs, Reports, and HR `Personalakten/` in Obsidian Desktop (`https://obsidian.md/download`).

---

## Rule 0: Stop and Interview First (Mandatory Gate)

**NEVER install, start containers, or write final configuration files before completing Phase 1 (Pre-Flight) and Phase 2 (Discovery Interview) with the user.**

Ask all Discovery Questions concisely in one message, wait for answers, and then run Phase 3 and Phase 4.

---

## Phase 1: Silent System Pre-Flight (Inspect Before Asking)

1. **OS & Resources:** Detect Windows / Linux / macOS, CPU cores, RAM, and free disk space (`>= 15 GB` recommended).
2. **Docker Check:** Check `docker` & `docker compose`. Check whether Docker Desktop / Docker Engine needs to be installed.
3. **Obsidian Check:** Check whether Obsidian Desktop is installed (`%LOCALAPPDATA%\Obsidian\Obsidian.exe`, `/Applications/Obsidian.app`, or `obsidian` / Flatpak) and whether the user has an existing Vault.
4. **Hermes Image Check:** Note whether `nousresearch/hermes-agent:latest` (or custom `HERMES_IMAGE`) can be pulled via Docker.
5. **Local AI Probing (Read-Only):** Probe `http://localhost:11434/api/tags` (Ollama) and `http://localhost:1234/v1/models` (LM Studio).
6. **Ports:** Verify `8501` (Archon Web UI), `8644` (Hermes), and `5678` (n8n) availability.

---

## Phase 2: Mandatory User Discovery Interview

Summarize Phase 1 in 3–4 short lines, then ask these **6 mandatory questions** (with `[Default]` hints):

### Question 1 — Target Path, Docker & Obsidian Vault (*Wohin wird installiert?*)
- **Install Directory:** Keep current folder or move to a target path (e.g., `/opt/archon-os` or `C:\ArchonOS`)?
- **Missing Prerequisites:** If **Docker** or **Obsidian Desktop** is missing, ask permission to install them automatically (`winget` on Windows, `get.docker.com` / Flatpak on Linux, `brew --cask` on macOS).
- **Obsidian Vault:** Path to an existing Vault, or create & initialize `./obsidian_vault`?

### Question 2 — Language & Localization Scope (*Sprache & Frameworks*)
- **Primary UI Language:** `en`, `de`, `es`, `fr`, `pt`, `ru`, `ja`, `ko`, `zh`.
- **Specialist `SOUL.md` & 55 Boardroom Frameworks:** Inform the user honestly whether their target language still uses German `SOUL.md` / methodology files and ask whether to translate them now or keep defaults.

### Question 3 — Stack Profile (*Framework / Umfang*)
*(All container tiers include `archon-os`, `hermes`, and `docker-socket-proxy`!)*
1. **`Standard` (~4 GB RAM, Recommended Default):** `archon-os` + `hermes` (Hermes Agent) + `anything-llm` + `chroma` (Vector RAG) + `docker-socket-proxy`
2. **`Full Automation` (~7 GB RAM):** `Standard` + `n8n` Automation + `ollama-embed`
3. **`Minimal Core` (Low-RAM ~2 GB):** `archon-os` + `hermes` + `docker-socket-proxy` *(without AnythingLLM RAG)*
4. **`Bare-Metal Dev`:** `.venv` Python 3.11+ alongside containerized `hermes` + `anything-llm` + `chroma`

### Question 4 — Cloud LLM Keys & Local AI Integration (*API-Keys & Lokale KI*)
- Ask for provider keys (`OPENROUTER_API_KEY` recommended — shared by Archon **and** Hermes Agent — or `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or configure later in Web UI).
- Ask whether **Ollama** / **LM Studio** should handle sensitive data locally (`PRIVACY_ZERO_EGRESS=true`).

### Question 5 — Network Exposure & Auth
- `ARCHON_BIND_IP=127.0.0.1` (localhost default) vs. `0.0.0.0` (LAN access; advise enabling `auth.enabled=true`).

### Question 6 — Optional Channels & Company Context
- Optional `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (used by Hermes Telegram Gateway & Archon).
- Optional company name, legal form, currency for CRM/ERP *(Alpha)*.

---

## Phase 3: Provisioning Execution

1. **Install Missing Desktop Prerequisites (if approved in Q1):** Docker Desktop/Engine and Obsidian Desktop.
2. **Initialize Directories, Vault Structure & Network:**
   ```bash
   mkdir -p data data/tenants/primary agent_workspace/builds logs .hermes/profiles
   mkdir -p obsidian_vault/{00_HR_Agenten,01_PROJEKTE,02_Wissensbibliothek,04_Radar,05_Content}
   docker network inspect archon-os-dev_agents_net >/dev/null 2>&1 || docker network create archon-os-dev_agents_net
   ```
3. **Write `.env` from `.env.example`:** Set `ARCHON_BIND_IP`, `ARCHON_LANGUAGE`, `ARCHON_STACK_PROFILE`, `ARCHON_HERMES_DIR`, `ARCHON_OBSIDIAN_DIR`, `PRIVACY_ZERO_EGRESS`, provider keys, and optional Telegram credentials.
4. **Pull Hermes Agent & AnythingLLM + Start Selected Stack:**
   - **Standard (Recommended):** `docker compose up -d --build archon-os docker-socket-proxy hermes anything-llm chroma`
   - **Full Automation:** `docker compose up -d --build archon-os docker-socket-proxy hermes anything-llm chroma n8n ollama-embed`
   - **Minimal Core:** `docker compose up -d --build archon-os docker-socket-proxy hermes`
5. **Sync 70 Specialist `SOUL.md` Profiles (Shared by Archon & Hermes):**
   ```bash
   docker exec ARCHON-OS python scripts/sync_soul_modes.py --mode compact
   ```

---

## Phase 4: Mandatory Verification & Handoff

Confirm all 4 checks before finishing:
1. `GET http://127.0.0.1:8501/health` returns `HTTP 200`.
2. `docker ps` shows `ARCHON-OS`, `hermes`, and `docker-socket-proxy` running cleanly.
3. `${ARCHON_HERMES_DIR}/profiles` contains all **70 synced specialist `SOUL.md` profiles**.
4. Remind the user to open `${ARCHON_OBSIDIAN_DIR}` via **"Open folder as vault"** in Obsidian Desktop, and state the regulatory disclaimer (advisory domains 3/4/8 are not licensed professional advice).
