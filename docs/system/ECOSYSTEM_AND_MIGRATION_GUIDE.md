# Archon OS — Ecosystem Integrations & Migration Guide (M36)

Archon OS is designed as a **sovereign, self-hosted alternative** to cloud-locked agent wrappers and fragmented SaaS tools, built on top of **[Hermes Agent (Nous Research)](https://github.com/NousResearch/hermes-agent)**.

---

## 1. Architectural Positioning

| Capability | Single Chatbots (ChatGPT / Claude Web) | Code-Only Frameworks (CrewAI / AutoGen / LangGraph) | Cloud Agent SaaS (Relevance AI / Lindy) | **Archon OS (Self-Hosted)** |
|---|---|---|---|---|
| **Ready-to-Run Specialists** | 0 (blank prompt box) | 0 (write Python boilerplate first) | Paid templates | **70 Specialists in 8 Domains (EN & DE)** |
| **Token-Smart Persona Scaling** | Manual | Manual | Fixed | **3-Stage `SOUL.md` (`compact` / `pro` / `full`)** |
| **Structured Multi-Agent Debate** | No | Custom graph coding | Limited | **6-Phase AI Boardroom + 55 Frameworks** |
| **Parametric Prompt Library** | No | No | Partial | **832 Bilingual Enterprise Templates** |
| **Operations Cockpit (UI)** | Chat only | CLI / paid cloud studio | Cloud only | **Full Web OS: Kanban, CRM, ERP, Inbox, Showroom** |
| **Human-in-the-Loop & Audit** | None | DIY | Basic | **4-Eyes Gates + SHA-256 GoBD Merkle Audit Log** |
| **Data Sovereignty & Cost** | US Cloud subscription | BYO infra | Per-credit SaaS markup | **100% Local / Zero-Egress (Ollama) + Free-Tier Router** |
| **Knowledge Persistence** | Opaque cloud memory | Vector DB only | Proprietary DB | **Plain Markdown Obsidian Vault + Chroma RAG** |

---

## 2. Migrating to Archon OS

### A. From CrewAI / AutoGen Python Scripts
1. **Map Roles to the 70-Agent Roster:** Check `agent_profiles.json` — most corporate roles (`senior_fullstack_engineer`, `commercial_jurist_contracts`, `finance_lead`, `research_scout`, `red_team_challenger`) already exist with 3-stage `SOUL.md` directives.
2. **Import Custom Personas:** Place custom domain instructions in `profiles_src/<agent_id>/persona.en.md` (or `persona.de.md`) and run:
   ```bash
   docker compose exec archon-os python scripts/sync_soul_modes.py --mode compact --lang en
   ```
3. **Replace Hardcoded Chains with Kanban & Boardroom:** Use `/api/mission-control/tasks/capture` for autonomous specialist delegation with built-in 4-eyes review gates, or `/api/boardroom/run` for adversarial multi-perspective synthesis.

### B. From Cloud SaaS Automation (Zapier / Make / Lindy)
1. Enable the `full` profile (`./install.sh` -> Option `2`) to launch the bundled localhost-bound **n8n** workflow mesh (`http://localhost:5678`).
2. Connect external triggers to Archon's scoped API (`/api/v1/...` with `X-Archon-Service-Token` or scoped API keys from *System Control Center -> API-Keys*).
3. Keep sensitive finance, HR, and legal documents on-premise by enabling **Zero-Egress Privacy Routing** (`PRIVACY_ZERO_EGRESS=true`) toward local **Ollama** or **LM Studio**.

### C. Connecting Obsidian Desktop ("Second Brain")
1. Point Obsidian Desktop at `./obsidian_vault` (or your existing vault path selected during `./install.sh` / First-Run Web Wizard).
2. All Research Lab dossiers, AI Boardroom syntheses, HR scorecards (`00_HR_Agenten/Personalakten/`), and project artifacts (`01_PROJEKTE/`) sync directly as clean, portable Markdown files.
