# Changelog

All notable changes to **Archon OS** are documented in this file.

## [v0.5.2.1] — 2026-11-13 (Global Release Edition)

### Added
- **M31 — Complete Global English Edition (DE / EN System-Wide Parity):**
  - Full bilingual specialist roster: all **70 specialists across 8 domains** now ship with complete English and German personas, 3-stage `SOUL.md` directives (`compact` / `pro` / `full`), and international regulatory profiles (US-GAAP/IFRS, GDPR/CCPA, FDA/OSHA, ISO alongside HGB/BauGB/GoBD).
  - **832 Bilingual Parametric Prompt Templates** in `prompt_studio_catalog.json` with dynamic `en`/`de` schema and rendering support (`/api/templates/catalog?lang=en`).
  - **55 Bilingual AI Boardroom Frameworks** across 7 decision-science categories (`/api/boardroom/frameworks?lang=en`).
- **M30 — Interactive First-Run Web Setup Wizard & Onboarding (`archon/routers/onboarding.py`):**
  - Guided 4-step browser wizard (1. Company & Tenant Profile, 2. AI Providers & Live Latency Check + Zero-Egress, 3. Channels & Obsidian Vault, 4. Specialist Domain Activation) complementing `./install.sh` and `setup.ps1`.
- **M47 — "Zero-Install" Read-Only Live-Demo Mode (`ARCHON_DEMO_MODE=true`):**
  - Hardened ASGI `DemoModeMiddleware` + `docker-compose.demo.yml` for zero-risk, zero-token public showcase hosting (*"Mittelstand Muster GmbH"* pre-populated 6-phase Boardroom debate, Kanban tasks, CRM/ERP sample records, and deterministic instant chat simulation).
- **M35 & M36 — Public Launch Kit & Ecosystem Integration Pack:**
  - Added `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, GitHub Issue/PR templates, and `deploy/ecosystem/` manifests & migration guides (*Awesome-Selfhosted*, *Awesome-AI-Agents*, CrewAI/AutoGen/Relevance AI migration).

## [v0.5.2] — 2026-11-13 (Zero-Trust & Multi-Arch Hardening)

### Fixed & Hardened
- **Multi-Arch Docker Build (`amd64` + `arm64` / Apple Silicon):** Dynamic `TARGETARCH` Docker CLI binary resolution and standalone image packaging (`archon/`, `backend/`, `utils/`, `plugins/`, `config/`, `scripts/`, `templates/`).
- **Fresh-Clone Compose Reliability:** Removed `external: true` network blocker, resolved host port `3001` collision (`grafana` moved to `3003`), integrated `omniroute:3.8.50` into default `docker-compose.yml`, and pinned multi-arch upstream images (`nousresearch/hermes-agent:v0.23.1`, `n8nio/n8n:2.36.8`, `tecnativa/docker-socket-proxy:v0.5.0`).
- **Zero-Trust Runtime & RBAC:** Enforced non-root UID `1000` (`read_only: true`, `cap_drop: [ALL]`, no raw `docker.sock`), added global + 72-router write-block for `viewer` role, and upgraded 83 SQLite context-manager sites to deterministic handle-closing connections.
