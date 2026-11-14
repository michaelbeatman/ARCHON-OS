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
  - Added `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, GitHub Issue/PR templates, and `deploy/ecosystem/` manifests & migration guides (*Awesome-Selfhosted*, *Awesome-AI-Agents*, *Awesome-MCP-Servers*, CrewAI/AutoGen/Relevance AI migration).
- **M48 — Native Archon OS MCP Server (`/mcp` Gateway):**
  - Streamable HTTP (`POST /mcp`), SSE (`GET /mcp`, `/mcp/sse`), and client config helper (`GET /mcp/info`) for Claude Desktop, Cursor & VS Code with Scoped API-Keys and HITL approval gates.
- **M51 — Portable `.archonpack` Squad Blueprint Manager:**
  - Verified ZIP export/inspect/import for agent squads, 3-stage `SOUL.md`, skills, boardroom frameworks, prompt templates & n8n workflows with SHA-256 verification and Zip-Slip protection.
- **M43 — Multi-Tenant Switcher & End-to-End SQLite Isolation (Holding / GmbH / SPV):**
  - Topbar tenant switcher & isolation modal (`static/js/tenant_switcher.js`), physical per-tenant SQLite WAL DB isolation (`data/tenants/<id>/` wired across `erp.db`, `kanban.db`, `crm.db`, `contracts.db`, and `deals.db` with non-destructive primary-tenant migration), company provisioning (`POST /api/v1/tenants/companies`), and atomic per-tenant document number ranges.
- **M49 — EU AI Act Compliance Engine & 1-Click GoBD / AI Act Procedural Documentation PDF:**
  - Precision specialist risk classification across all 70 specialists (`HIGH_RISK` Annex III, `SPECIFIC_TRANSPARENCY` Art. 50, `MINIMAL_RISK` Art. 95) with cryptographic `SOUL.md` SHA-256 hashes, Art. 4 AI Literacy & Competence Register (`backend/compliance_engine.py`), mandatory guardrail checks, Operations Compliance Studio (`static/js/eu_ai_act_studio.js`), and dependency-free multi-page DIN-A4 PDF 1.4 export (`GET /api/v1/governance/compliance/verfahrensdokumentation.pdf`).
- **M44, M52, M53 & M25 — Business Playbooks, Pre-Flight/Shadow-Mode, Epistemic Hygiene & Operations Calendar:**
  - Added 10 active + 15 catalog Business Playbooks with editor CRUD (`backend/playbooks_engine.py`), chain cost estimation & >90% Shadow-Mode graduation (`backend/shadow_mode.py`), Obsidian vault conflict/staleness scanner (`backend/epistemic_hygiene.py`), and unified Operations Calendar (`backend/operations_calendar.py`).

## [v0.5.2] — 2026-11-13 (Zero-Trust & Multi-Arch Hardening)

### Fixed & Hardened
- **Multi-Arch Docker Build (`amd64` + `arm64` / Apple Silicon):** Dynamic `TARGETARCH` Docker CLI binary resolution and standalone image packaging (`archon/`, `backend/`, `utils/`, `plugins/`, `config/`, `scripts/`, `templates/`).
- **Fresh-Clone Compose Reliability:** Removed `external: true` network blocker, resolved host port `3001` collision (`grafana` moved to `3003`), integrated `omniroute:3.8.50` into default `docker-compose.yml`, and pinned multi-arch upstream images (`nousresearch/hermes-agent:v0.23.1`, `n8nio/n8n:2.36.8`, `tecnativa/docker-socket-proxy:v0.5.0`).
- **Zero-Trust Runtime & RBAC:** Enforced non-root UID `1000` (`read_only: true`, `cap_drop: [ALL]`, no raw `docker.sock`), added global + 72-router write-block for `viewer` role, and upgraded 83 SQLite context-manager sites to deterministic handle-closing connections.
