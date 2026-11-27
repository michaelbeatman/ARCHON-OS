# Changelog

All notable changes to **Archon OS** are documented in this file.

## [Unreleased] — 2026-11-27 (Roadmap-Welle M67–M72, M95, M97–M100, M109, M111, M112)

### Added & Verified
- **M67/M68/M69/M70/M74/M71/M72/M111/M112:** Host-State & Prompt-Kompression, Compliance-Inventar/DPIA/Audit-Replay, Policy-as-Code (YAML, 24h-Vendor-Limits, signierte Tokens), „Braucht mich"-Panel + Auto-Review, Eval-Attestierung, modellabhängiges Task-Sizing/Skills-Leihe, Bulkheads/Tool-Output-Caps/Circuit-Breaker und unveränderliches Event-Ledger mit Merkle-Anker. Neue Router zentral in `main.py` registriert; `NeedsMePanel` im Cockpit eingehängt.
- **Qualität & Gates:** `ruff check --select E,F,I --ignore E501` und `mypy --config-file mypy.ini` über 35 geänderte/neue Python-Dateien jeweils Exit 0; gezielte Suite **611 passed** (1 bekannte Starlette-/httpx-Warnung); `npm run build` und `npx tsc --noEmit` Exit 0. Bestehende Router-Sequenz-, Pfad- und Hook-Ratchets auf die neuen Endpunkte aktualisiert.
- **Risiko-Abschluss:** periodischer Merkle-Anker als Startup-/Shutdown-Hook (M112), DPIA-Salt in Produktion fail-closed statt deployweit identisch (M68), explizite M68/M69-Adapterverdrahtung im Needs-Me-Router (M70/M74), Cross-Tenant-Test für den Host-State (M67), Pydantic-Feld `response_schema` mit Wire-Alias `schema` (Warnung eliminiert), Node-Engine auf `>=22 <25` erweitert.
- **Roadmap:** Status der umgesetzten Meilensteine auf `Umgesetzt` gesetzt; M96, M2/M34 und M66 bleiben bewusst `Geplant`.

## [v0.6.0.1] — 2026-11-27 (Audit Remediation W0–W7 & Full-Suite Green)

### Fixed & Verified
- **Audit-Sanierung W0–W7 vollständig abgeschlossen:** Alle **121 gewichteten Funde** der Wellen W0–W7 behoben und dokumentiert (`0` offen, `0` teilweise); `docs/system/NEVER_DO_LIST.md` in allen Wellen eingehalten.
- **Testsuite auf 0 Fehler gebracht:** Alle 21 vorbestehenden Baseline-Testfehler über eine explizite, nicht-`autouse` Auth-/RBAC-Fixture (`admin_rbac_bypass`) und aktualisierte Einzelverträge behoben (`5fcbc352`), Produktiv-Guards unverändert fail-closed; zusätzlich Windows-Teardown-Flake (`WinError 32`) in `tests/test_m49_eu_ai_act_compliance.py` behoben (`3d174692`).
- **Qualität & Gates:** Full-Suite **2961 passed / 16 skipped / 0 failed**, Ruff (`E,F,I`), MyPy (`mypy.ini`), `lint-imports` (2/2 Verträge KEPT) und Frontend `tsc --noEmit` jeweils **Exit 0**.
- **Dokumentation & Landing Page:** `config/version.json`, `README.md`, `README.de.md`, Sprach-Readmes, `docs/SYSTEM_HANDBUCH.md` und `site/index.html` auf **v0.6.0.1** synchronisiert.

## [v0.6.0] — 2026-11-26 (Full-Scan Hardening, Red-Team Verification & Operational Resilience)

### Added & Hardened
- **Security & Workspace Isolation:** Gehärteter Workspace-Path-Jail in `plugins/security_audit_hook/plugin.py` (Case-Normalisierung, Traversal-, Symlink- und Sensitive-File-Schutz), PocketBase-Filter-Escaping in `extension/background.js` und atomare Cost-Guard-Persistierung in `plugins/cost_guard/plugin.py`.
- **Runtime & Shutdown Resilience:** Timeout-Record-Erfassung und Cancel-Drain-Eskalation in `archon/core/background_loops.py`; `SOUL`-Pinning und fehlertolerantes Shutdown-Handling gehärtet.
- **Audit-Kette & Produktivbetrieb:** Fail-Closed-HMAC-Startup-Gate aktiv (`auth.enabled=true`); historischer Kettenbruch aus DB-Restoration bewusst Read-Only nach GoBD archiviert (`data/backups/pre_hmac_archive_2026-11-26/`), nicht re-signiert, Betreiberentscheidung dokumentiert.
- **Qualität & Gates:** MyPy über 439 Dateien fehlerfrei (`0` Fehler, `--disallow-untyped-defs` auf neuen D5-Modulen), 13/13 Maschinen-Gates grün, `pytest tests/` **2538 passed / 20 skipped / 0 failed**, 12/12 Red-Team-Mutations-Checks rot (`audit_reports/V06_CERTIFICATION.md`, `audit_reports/V06_OPEN_POINTS_REVIEW.md`).
- **Dokumentation & Landing Page:** `config/version.json`, `README.md`, `README.de.md`, alle Sprach-Readmes, `docs/SYSTEM_HANDBUCH.md` und `site/index.html` auf **v0.6.0** aktualisiert (PDF-Manuale basieren weiterhin auf **v0.5.2.1**).

### Known Backlog (`v0.6.x`)
- `D5` bleibt bewusst partiell (C4 Boardroom-Orchestrierung & C5 Dispatch-Core offen), `D4` (Telegram-Adapter) außerhalb Ownership; `.mcp.json`-Pinning und `tools/migrate_projects_structure.py` Dry-Run/Rollback auf `v0.6.x` verschoben.

## [Remediation 25.11.2026] — v0.5.7.8 (Final-Re-Audit)

### Fixed
- **Remediation W0–W5 abgeschlossen:** 2 BLOCKER (`B-05` Audit-Fail-Fast, `B-11` verlustfreie Session-DAG) und **49 HIGH**-Befunde des Audits vom 25.11.2026 behoben; Nachweise in `audit_reports/fix_w*.md` und `audit_reports/FIX_VERIFICATION_LOG.md`.
- **Full-Suite grün:** `ARCHON_DATA_DIR=<temp> .ci_venv\Scripts\python.exe -m pytest tests/ -q --tb=short` → **2335 passed / 0 failed / 16 skipped**. `compileall`, `docker compose -f docker-compose.yml config --quiet`, `npx tsc --noEmit` und `npm run build` jeweils Exit 0; Produktiv-Login bestätigt.
- **Doku-Abgleich:** Versionsreferenzen in `README.md`, `README.de.md`, allen 11 Sprach-Readmes und `docs/SYSTEM_HANDBUCH.md` an den Code-Stand **v0.5.7.8** (`config/version.json`) angepasst. Die PDF-Manuale wurden **nicht** neu erzeugt und basieren weiter auf **v0.5.2.1** — siehe die Einträge ab `[v0.5.7]` in diesem CHANGELOG für v0.5.7.8.
- **Re-Audit:** Alle 16 `audit_reports/domain_*.md` um `## Re-Audit 25.11.2026 (Final)` ergänzt; ursprüngliche Befunde bleiben als historische Evidenz unverändert erhalten.
- **`hermes-orchestrator`:** Alias-Auflösung über die kanonische SSOT (`config/org_hierarchy.json`, `backend/agent_aliases.py`) im Compliance-Pfad wirksam — `COMPLIANCE_BLOCKED` durch `agent_not_in_ai_act_inventory` behoben (statisch geprüft, kein eigener Testlauf in diesem Doku-Pass).

> **Verifikationshinweis:** Die Gate-Ergebnisse stammen aus den dokumentierten Läufen des Orchestrators (`FIX_VERIFICATION_LOG.md`, §9 `MASTER_PLAN.md`). Der Doku-Pass selbst konnte keine Shell starten (`pwsh.exe: Zugriff verweigert, os error 5`) und hat daher keine eigenen Tests ausgeführt.

## [Unreleased] — 2026-11-22 (M114: Abschluss der Multi-Agent- & Content-Machine-Roadmap, 28/28)

### Added
- **M114 Multi-Agent-Orchestrierung (12/12):** Durable-Execution-Kernel mit Fencing-Token, CAS-Leases/Heartbeats, typisierte A2A-Envelope (`message_id`/`reply_to`/`correlation_id`/`confidence`/`attachments`) inkl. `role="assistant"`-Fix, Shared Task Queue mit Idempotenz/Priorität/Work-Stealing, Supervisor-Rollover (`backend/supervisor_rollover.py`), Memory-Scope mit ACL/TTL, Event-Push statt 10-s-Polling, zentrale Cancel-Kette (`backend/cancellation.py`), deterministischer Konsens und Eval-/Promotion-Gates inkl. strikter Profil-Aktivierung.
- **M114 Content-Machine (16/16):** Publish-Sweep im 5-min-Scheduler, zentralisierte HITL-Finalisierung, Research-Tool-Knoten mit Dossier-Pfad, harte Quality-/Kanal-/Fact-Check-Gates, Plagiat-/Rechte-Check mit Quellenlizenzen, SEO-HITL statt Direkt-Publish, kanonischer `idea`-Status, Feedback-Loop, A/B-Experimente, Editorial-Rollen/Historie, verpflichtende `li-human`-Skill-Injektion, GEO-JSON-LD/`llms.txt` mit 48-h-Citation-Check, `idea`-Badge und Media-Handoff im Frontend.
- **Dokumentation:** `docs/system/MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md` mit vollständiger 28-Punkt-Matrix, Dateireferenzen und Verifikationsschritten; Roadmap-Meilenstein M114 ergänzt.

### Changed
- Fan-in-Synthese nutzt `resolve_debate_consensus()` (Votes/Evidence) statt des `aggregation_lisa`-LLM-Prompts inkl. Marker-Repair-Retry; Boardroom-Konsens wird deterministisch und offline entschieden (M-1-Negationsschutz bleibt).
- CI: `validate_config.py --strict` und Profil-SSOT-Drift-Check (`--allow-missing-hermes` für saubere Checkouts).
- Oracle News Radar: zentraler SSRF-geschützter Client + dynamischer GitHub-Cutoff statt hart codiertem Datum.
- `handoff_desk.accept_handoff()` validiert Ergebnis/Status/Akzeptanzkriterien statt bedingungsloser Quittierung.

### Fixed
- Research-Verdict war immer leer (`verdict` vs. `triangulation_verdict`).
- Manuelle Freigaben schrieben keine `decision_id`.
- `success_rate=98.0` für Agenten ohne Daten → `None`/`data_sufficient=false`.
- `datetime`-Fehler im Content-Feedback-Sweep behoben.
- Review-Knoten nutzte einen Skill-Namen als `agent_id` (nicht auflösbar) → echtes Profil.

> **Verifikation:** Die neuen `tests/test_p2_*.py` sind geschrieben, konnten in der Entwicklungssession aber nicht ausgeführt werden (kein Python im PATH). CI muss sie beim nächsten Lauf prüfen.

## [v0.5.7] — 2026-11-22 (Execution Hardening, Governance-Zentrierung & Idempotenz)

### Added
- **M110 Effect-Ledger** (`backend/event_mesh.py`): `PENDING → COMMITTED / FAILED / UNKNOWN`, verpflichtende Reconciliation vor Retry nach `UNKNOWN` (mit Evidence), Outbox mit `X-Idempotency-Key` und DLQ nach 5 Versuchen.
- **Worker-Leases/Heartbeats** (`backend/deadlock_supervisor.py`): atomare Leases, Liveness-Check via `os.kill(pid, 0)`, CAS-Reset, Mindestschwelle 120 s (über dem 90-s-LLM-Timeout).
- **Pre-Execution Plan Validator** (`backend/workflow_dag_runner.py`): Zyklus-Erkennung via Kahn vor dem Start, Schema/Mapping/Budget/Deadline/RBAC-HITL-Prüfung, `replan_count`-Deckel (= 2).
- **PolicyEngine + BudgetBank**: zentrale Tool-Entscheidung, harter Warrant-Zwang für `pay`/`mcp__*` u. a., atomare Budget-Reservierung (`BEGIN IMMEDIATE`) statt Check-then-Use.
- **Audit-HMAC** mit Env-Key (`ARCHON_AUDIT_HMAC_KEY`) und blockierungsfreiem Hintergrund-Anker (`ARCHON_AUDIT_ANCHOR_PATH`).
- **OTel-Verdrahtung** in `llm_kernel.py` und `workflow_dag_runner.py` (Trace pro Run/Call, Span pro Node).
- **Trace-to-Eval (M112):** `build_fixture_from_trace()` und `replay_and_evaluate()` in `backend/eval_gates.py` – PII-redaktierte Replay-Fixtures aus OTel-Traces, Bewertung über die bestehenden Eval-Gates.
- **Workspace:** 5-Stufen-Onboarding-Wizard v2 mit SSRF-sicheren Integrations-Probes, Operations-Kalender-Engine inkl. Service Worker, 11 LinkedIn-Skills (post, profile, human, …) mit Hooks/Rubrics, `competitor_idea_bridge.py` und `execution_routing_guard.py`.

### Changed
- Python 3.13 in Runtime-Images und CI; Test-Abhängigkeiten in `requirements-test.txt` ausgelagert.
- Tenant-Header nur noch für Admins/Service-Tokens; `executescript`-Transaktionsbruch im Mission-Control-Store behoben.
- Versions-/Pfad-/Config-SSOT: `config/version.json` = v0.5.7, einheitliche Vault-Pfad-Auflösung über `archon.core.runtime`, `clear_rules.json` repariert.
- **Compose-Bereinigung:** veraltete Varianten `docker-compose.archon.yml`, `docker-compose.cro.yml` und `docker-compose.vpn.yml` entfernt (Produktiv/Dev/Demo/Hermes bleiben).
- Dokumentation auf v0.5.7 aktualisiert: Security-Versionsmatrix, Roadmap M110 → abgeschlossen, Proxy-README, EU-AI-Act-Guide, 5 statt 4 Wizard-Schritte, JSON-LD-Version.

## [0.5.6.0] - 2026-11-21 (Phase 1–3 Hardening, SQLite 28→3 Consolidation, Content-Maschine v2, Workflow-DAG E2E & Next.js 16 Cockpits)

### Added
- **M106 SQLite Database Consolidation (`28 → 3` Domain DBs: `backend/db_consolidation.py`, `backend/db_paths.py`, `backend/tenant_context.py`, `backend/db_backup_manager.py`):**
  - Consolidated 28 scattered SQLite databases into 3 domain-isolated WAL databases: `data/ops.db` (Kanban, workflows, state, audit, security), `data/business.db` (ERP, CRM, deals, contracts, treasury, content machine), and `data/memory.db` (agentic memory, learnings, compartment vault, LCM sessions).
  - Automatic schema-collision prefixing (`<legacy_stem>__<table>`), pre-migration backup snapshots (`data/_pre_consolidation_backups/<timestamp>/`), `PRAGMA integrity_check`, and transparent backward-compatible path resolution via `db_paths.resolve_db()`, `TenantContextManager.resolve_active_db()`, and `DBBackupManager`.
  - Admin endpoints: `GET /api/v2/system/db-consolidation/plan` and `POST /api/v2/system/db-consolidation/run`.
- **M107 Multi-Channel Content-Maschine v1 & v2 (`backend/content_machine.py`, `archon/routers/content_machine.py`):**
  - Full campaign & asset pipeline for **LinkedIn**, **YouTube Longform**, **YouTube Shorts**, **TikTok**, and **X/Threads** stored in `data/business.db`.
  - **Multi-Agent Repurposing DAG (`run_campaign_repurpose_dag`):** `n_research` → `n_master_brief` → parallel channel fan-out (`n_ch_linkedin`, `n_ch_youtube_longform`, `n_ch_youtube_shorts`, `n_ch_tiktok`, `n_ch_x_threads`) → `n_editorial_gate` (HITL approval).
  - **Content-Maschine v2:** Deterministic **Anti-AI-Slop & Quality Gate** (`evaluate_asset_quality`, 0–100 score), **Source Ingestion** (`POST /api/v2/content-machine/ingest` for SSRF-guarded URLs, path-jailed Obsidian notes, and raw transcripts), **9:16 Video Clip Repurposing Matrix** (`POST /api/v2/content-machine/campaigns/{id}/clip-matrix`), **Webhook Publishing Bridge** (`POST /api/v2/content-machine/assets/{id}/dispatch-webhook`), and **Scheduled Due-Publish Sweep** (`POST /api/v2/content-machine/publish-due`) plus performance feedback learnings (`record_asset_metrics` → `memory.db`).
- **M108 Next.js 16 FastAPI UI Consolidation (`frontend/`):**
  - Direct server-side proxy (`frontend/src/app/api/archon/[...path]/route.ts`) and typed client (`frontend/src/lib/archon-api.ts`) talking directly to Archon FastAPI (`127.0.0.1:8420`) without PocketBase dependency.
  - Added `/workflows` (`WorkflowDagCockpit.tsx`) and `/cockpit` (`ExecutiveCockpit.tsx` for System Health, 28→3 DB Consolidation, Kanban, HITL Decisions, DAG Runs, Content Pipeline & CRM). **Product-model correction 2026-11-23 (D09-M7):** The separate content surface originally listed here is not part of the product model — content runs as task → workflow → agent → gate → artifact; its features are consolidated in `/workflows`, old deep links are only redirected via a legacy alias. There is no standalone content domain.

### Changed & Fixed
- **Phase 1 Security Hardening & P0 Logic Fixes (`fc41341`):**
  - Cryptographic WebAuthn/Passkey verification (`backend/passkey_hitl.py` ES256/RS256 signature verification, `rpIdHash`, `signCount` replay protection).
  - Enforced Zero-Egress (`evaluate_and_gate_llm_dispatch`) in `archon/routers/boardroom.py` and `archon/routers/chat.py`; hardened Showroom Python sandbox (`views_core.py`) with static AST inspection blocking `os`, `subprocess`, `socket`, `ctypes`, and `urllib`.
  - Added public SSRF guard (`check_public_url` in `utils/egress_guard.py`) for `visual_web_agent.py` and fixed XSS in `static/js/boardroom.js` and `static/js/inbox.js`.
  - Fixed P0 runtime bugs across `agent_router.py`, `delegation.py`, `orchestration.py`, `mission_control.py`, `erp_manager.py`, `dunning_engine.py`, `gdpr_compliance_engine.py`, and `obsidian_hygiene.py`.
- **Workflow-DAG Engine E2E Wiring & Legacy Cleanup (`c6763dc`, `0a69dd4`, `5db6d0e`):**
  - Unified `workflow_templates.py`, `workflow_dag_runner.py`, `workflow_scheduler.py`, `v2_capabilities.py`, and `decisions.py` onto a single production DAG execution and HITL-gate resume pipeline (`tests/test_workflow_dag_e2e.py`).
  - Archived obsolete duplicate runners (`backend/dag_scheduler.py`, `backend/hybrid_sop_runner.py`, `backend/main.py`) to `archive/20261121_legacy_workflows/` and removed 7 unwired Triage-C theater modules (`worktree_joust`, `special_extensions`, `external_connectors`, `voice_to_workflow`, `contract_diff_redliner`, `agent_eval_arena`, `workflow_freeze`).
  - Eliminated **407+** silent `except ...: pass` blocks across `archon/routers/*`, `backend/*`, `main.py`, `local_memory_bridge.py`, and `archon/core/orchestration.py` in favor of structured logging.

## [0.5.5.4] — 2026-11-20 (Passkey HITL, Visual Workflow Studio, Event-Bus & Treasury)

### Added
- **M101 Passkey / WebAuthn HITL (`backend/passkey_hitl.py`, `archon/routers/auth.py`, `static/js/passkey_hitl.js`):** Optional two-stage FIDO2/Passkey verification per user in Settings (global or selective for payments, project starts, budget overrides, destructive actions) with SHA-256 audit logging. See `docs/system/PASSKEY_HITL_GUIDE.md`.
- **M102 Visual Multi-Agent Workflow Studio & Event-Bus (`backend/workflow_templates.py`, `backend/workflow_monetization_catalog.py`, `backend/workflow_scheduler.py`, `static/js/workflow_templates_studio.js`):**
  - Dedicated **Workflows** tab under Operations with drag-and-drop 20px-grid node editor, configurable edge conditions & data modes, per-station Prompt/Expected-Output/Tools/Guardrails inspector, **52 curated templates** (including Dropshipping & 36 monetization workflows), and **n8n JSON import**.
  - Active **Cron Scheduler** (`start_at`, `end_at`, `start_condition`, `end_condition`) and unified **Event-Bus** connecting Watchdog, Inbox, Research Lab, AI Boardroom, Calendar, and Approvals with loop protection and a live **Event-Bus** tab under Telemetrie & Logs. See `docs/system/WORKFLOW_TEMPLATES_GUIDE.md`.
- **M103 Treasury & Payment Cockpit (`backend/treasury_engine.py`, `static/js/treasury_studio.js`):** Liquidity overview across bank accounts, PayPal, Stripe, watch-only crypto wallets, and capped agent-allowance (`x402`) wallets, categorized spend ledger with SHA-256 hash chain, and enforced Passkey/HITL payment approval queue. See `docs/system/TREASURY_PAYMENTS_GUIDE.md`.
- **UI & Operations Polish:** Read-only archived task modal & clone action, DAW Gantt & interactive Dependency Graph improvements, non-destructive Org grid snap + hierarchy presets/undo, Playbooks consolidation, new transparent Cadre icons (`calendar.png`, `workflows.png`, `approvals.png`), and rebuilt `static/css/tailwind.generated.css`.

## [Unreleased] — 2026-11-19 (UI-Konsolidierung & Operations-Feinschliff)

### Changed
- **Autonomie-Module in „Autonomie & Freigaben“ integriert:** Der separate Sidebar-Punkt `Autonomie-Module` (`#nav-autonomy`) wurde entfernt. Die 36 Autonomie-, Resilienz- & Enterprise-Module sitzen nun direkt als eigener Reiter **Autonomie** (mit eigenem Icon `static/img/cadre_icons/approval_autonomy.png`) hinter *Finanzen* in **Autonomie & Freigaben** (`view_approval_policies.html`).
- **Corporate & Mandant in Settings integriert:** Die eigenständige Sidebar-Ansicht `view_corporate.html` (`nav-corporate`) wurde vollständig in das **System Control Center** als Reiter `CORPORATE & MANDANT` (`#settings-tab-corporate`) überführt. `setTab('corporate')` leitet nahtlos in diesen Reiter weiter.

## [Unreleased] — 2026-11-18 (Hermes Marketplace Skills & MCP Plugins)

### Added
- **M6 Design System v2 & v2 Capabilities UI Bridge:** Added `static/css/design_system_v2.css` (typography, WCAG 2.2 `:focus-visible`, refined scrollbar/modal tokens) and `static/js/v2_capabilities_panel.js` (`window.archonV2Panel`), wired into `static/index.html`.
- **Compliance, Tenant DB Registry & Legacy RCE Cleanup:**
  - Removed legacy `node -e eval(...)`, `sql.unsafe(...)`, and hardcoded Postgres credentials from `backend/post_task_pipeline.py` (`sync_paperclip_completion` now fails closed).
  - Added `backend/tenant_db_registry.py` (`resolve_tenant_db_path`, `gdpr_erase_subject_data`) and mounted `POST /api/v2/gdpr/erase` in `archon/routers/v2_capabilities.py` for Art. 17 DSGVO erasure across all v2 SQLite DBs.
  - Enforced § 201 StGB participant consent gate (`all_participants_consented=True`) in `backend/meeting_copilot.py` and `/api/v2/meetings/note`.
  - Enforced BGB/EU-AI-Act Art. 50 contract confirmation (`terms_accepted`, `ai_disclosure_shown`, `client_ip`, `document_sha256`) in `backend/client_approval_portal.py`.
  - Added EU AI Act Annex III high-risk human-oversight mandate to `.agents/skills/auto_senior_applicant_screener/SKILL.md`.
- **Audit Hardening & Full v2 Router Wiring:**
  - Hardened `backend/main.py` CORS (replaced `allow_origins=["*"]` with configurable localhost origins via `ARCHON_CORS_ORIGINS`).
  - Removed hardcoded HMAC fallback secret in `backend/tool_warrants.py` (now loads `ARCHON_WARRANT_SECRET` or generates a 32-byte random local key in `data/warrant_hmac.key`).
  - Added unified runtime gate `enforce_runtime_tool_gate` + `mark_session_tainted_on_tool_read` in `backend/delegation_isolation.py` and wired it into `archon/routers/plugins.py` (`api_execute_plugin_tool`).
  - Mounted all 26 v2 capability modules via `archon/routers/v2_capabilities.py` (`/api/v2/*`) in `main.py` (orphaned backend modules reduced from 26 to 0).
- **Milestone M88 Implemented (`backend/special_extensions.py`):** Added SSH/Slurm remote worker command builder (`flota`/`own-compute`), approval-gated Kujo runtime bridge (`kujo-hermes`), media Keep/Cut/Redo swipe deck (`riah-swipe`), and politeness/token metrics (`manners-meter`).
- **Milestones M41, M40, M42, M85, M87 Implemented:**
  - **M41 (`backend/calendar_sync_blocker.py`):** Bidirectional CalDAV/ICS sync (`parse_ics_events`, `export_ics_events`, `sync_calendar_bidirectional`) and automated Deep-Work focus blocker (`schedule_focus_blocks`).
  - **M40 (`backend/contract_diff_redliner.py`):** Clause-level contract diff, XSS-safe HTML redlining, and legal risk keyword detection (`diff_contract_clauses`, `assess_clause_risks`).
  - **M42 (`backend/client_approval_portal.py`):** Password-protected, expiring client approval links (`data/client_portal.db`) with direct ERP status transition (`Angebot` -> `Auftrag`).
  - **M85 (`backend/worktree_joust.py`):** Best-of-N isolated Git worktree contender planning, creation, and test/diff ranking (`score_joust_contenders`).
  - **M87 (`backend/external_connectors.py`):** Unified connector adapters for `inkly` (eSignature), `local-business-leads`, `hermes-issue-sync`, and `ghl-command`.
- **Block C & D Milestones Implemented (M32, M63, M64, M62, M55/M25, M33, M38, M37, M39, M54):**
  - **M32 (`backend/telegram_gateway_v2.py`):** Conflict-free session keying, slash-command agent routing, inline HITL keyboards, and live status formatting.
  - **M63 (`static/js/sidebar_v2.js`):** Persistent collapsible sidebar sections wired into `static/index.html`.
  - **M64 (`static/views/system_settings_modal.html`):** Added `Setup-Wizard` relaunch button (`#modal-header-onboarding-btn`) in the Settings header.
  - **M62 (`backend/operations_templates.py`):** Unified template registry and live placeholder preview renderer (`list_operations_templates`, `preview_operations_template`).
  - **M55 / M25 (`backend/enterprise_calendar.py`, `static/js/enterprise_calendar_ui.js`):** Day/week/month grid builder, recurring event expansion, drag-and-drop reschedule, and agent resource grouping.
  - **M33 (`backend/watchdog_radar_v2.py`):** Semantic relevance scoring, SHA-256 deduplication (`data/watchdog_v2.db`), and automatic fallback-URL self-healing.
  - **M38 (`backend/contract_deadline_watcher.py`):** 30/14-day contract & subscription deadline scanner with automated cancellation notice drafts.
  - **M37 (`backend/time_tracking_invoice.py`):** SQLite WAL timer (`data/time_tracking.db`), project budget variance, and 1-click ERP invoice line-item export.
  - **M39 (`backend/meeting_copilot.py`):** Speaker-diarized transcript formatting, Kanban action-item extraction, and CRM meeting note builder.
  - **M54 (`backend/voice_to_workflow.py`):** Two-stage dictation ambiguity detector and deterministic playbook compiler.
- **Block A & B Milestones Implemented (M84, M90, M80, M82, M93, M92, M94, M50, M45, M65):**
  - **M84 (`backend/injection_range.py`):** 8-scenario prompt injection drill suite (`run_injection_drill`) incl. Base64, HTML comments, memory poisoning, and tool smuggling.
  - **M90 (`backend/tool_warrants.py`):** HMAC-SHA256 signed, expiring tool warrants with parameter constraints (`issue_warrant`, `verify_warrant_for_call`).
  - **M80 (`backend/hybrid_sop_runner.py`):** Hybrid SOP runner separating deterministic `script` steps from `agent` judgment steps.
  - **M82 (`backend/session_receipts.py`):** Structured delegation receipts and self-contained offline HTML evidence documents (`render_offline_html_receipt`).
  - **M93 (`backend/tool_output_firewall.py`):** Context-protecting `guard_tool_output` and single-turn `run_batch_tool_calls`.
  - **M92 (`backend/workflow_freeze.py`):** Deterministic `freeze_tool_sequence` and zero-token `replay_frozen_workflow` (`data/frozen_workflows.db`).
  - **M94 (`backend/lossless_session_dag.py`):** Lossless SQLite turn/summary DAG (`data/lcm_sessions.db`) and multi-perspective `run_storm_panel`.
  - **M50 (`backend/agent_eval_arena.py`):** Local reference benchmark deck (`run_eval_arena`, `data/eval_arena.db`).
  - **M45 (`backend/deep_research_lab.py`):** Trust-tier source triangulation (`triangulate_sources`) and Obsidian dossier export (`compile_research_dossier`).
  - **M65 (`static/views/system_settings_modal.html`):** Grouped wrapping tab navigation and consistent spacing in the System Control Center modal.
- **Next-5 Roadmap Milestones Implemented (M77, M79, M81, M83, M86):**
  - **M77 (Workflow DAG Runner):** Added `backend/workflow_dag_runner.py` (JSON-DAGs with parallel fan-out/quorum, human/machine gates, and SHA-256 fingerprint replay-skip resume in SQLite WAL).
  - **M79 (Offline Encrypted Memory Vault):** Added `backend/offline_memory_vault.py` (100% offline AEAD-encrypted local hybrid/vector memory store with zero network calls or external API keys).
  - **M81 (Cross-Model Verifier & Assertion Guard):** Extended `backend/kanban_verifier.py` with `detect_deleted_test_assertions`, `pick_independent_verifier_model`, and `cross_model_verify_card`.
  - **M83 (Flightlog & Policy Backtester):** Added `backend/flightlog_backtester.py` (`record_flight_event`, `detect_silent_failures`, `backtest_policy`).
  - **M86 (Quota & Verification Escalation):** Extended `backend/agent_router.py` with `select_quota_and_escalation_route` and `chat_with_verification_escalation`.
- **Top-5 Roadmap Milestones Implemented (M75, M89, M76, M91, M78):**
  - **M75 (Delegation Isolation):** Added `backend/delegation_isolation.py` and wired strict profile-only `tools`/`skills`/`model` isolation into `archon/core/delegation.py` (`_execute_delegation`).
  - **M89 (Session Taint Guard):** Added `backend/session_taint_guard.py` (SQLite WAL) and HITL approval endpoints (`GET/POST /api/v1/guardian/taint/approvals`) in `archon/routers/kanban.py`.
  - **M76 (Kanban Verifier & Proof Gate):** Added `backend/kanban_verifier.py` (token budget check, proof-command execution, 1 auto-retry, HITL decision endpoint `POST /api/operations/kanban/tasks/{task_id}/hitl`) and wired it into `backend/operations_api.py`.
  - **M91 (Tenant-Isolated Precedent Log):** Added `backend/precedent_log.py` (strict `(tenant_id, project_id)` isolation, CRUD endpoints `/api/operations/precedents`) and prompt injection in `backend/operations_api.py`.
  - **M78 (Kanban Gantt & Dependency Graph):** Added `backend/kanban_views.py` (hybrid Gantt + longest-path dependency graph), endpoints `GET /api/operations/kanban/gantt|graph`, and frontend renderer `static/js/kanban_gantt_graph.js`.
- **Hermes Marketplace Skills & MCP Integration:** Integrated 18 skills in `.agents/skills/` (`hermes-agent`, `sdlc-review`, `simplify-code`, `claude-code`, `codex`, `kinocut`, `kinocut-repurpose`, `pay`, `patsnap-search`, `canonry`, `penthera`, `opendockit`, `seo`, `seo-audit`, `seo-geo`, `seo-technical`, `seo-schema`, `seo-content`), added `.mcp.json` (`kinocut`, `pay`, `pay-cli`, `patsnap`, `canonry`, `opendockit`), assigned skills and `mcp` tool access to specialist profiles in `agent_profiles.json`, added Roadmap Milestones **M75–M94** in `docs/system/ROADMAP_2026.md`, and documented server prerequisites in `docs/HERMES_PLUGINS_SKILLS_INTEGRATION.md`.

## [Unreleased] — 2026-11-15 (Core Audit & Hardening Fixes)

### Added
- **Context Hygiene (M73):** Context meter in the master chat footer (fill level with green/amber/red thresholds), click-to-open context panel with one-click session compaction (`POST /api/chat/compact-session`), automatic compaction hook before every chat dispatch (`auto_compact_pct`, default 85%), and the HITL-gated MCP tool `archon__compress_agent_context` for orchestrator-triggered compaction. Docs: `docs/system/CONTEXT_METER_GUIDE.md`.

### Fixed
- **Orchestration & Runtime Stability:**
  - Imported missing orchestration helpers (`project_folder_name`, `build_dossier_from_report`, `send_telegram_document`, `send_telegram_message`) in `main.py` to resolve `NameError` in synthesis wrappers, and fixed `_set_agent_profile_status` to return its `bool` result for AutoHire.
  - Fixed `UnboundLocalError` in `core_dispatcher.stream_boardroom_debate` when `use_moa=True`, prevented empty HTTP-200 OmniRoute responses from masking fallback providers, passed `full_system_prompt` (incl. memory/prefetch) to Anthropic direct calls, and used `openrouter_api_key` in the OpenRouter fallback.
  - Replaced `int(time.time() * 1000) % 100000` sub-task IDs in `archon/core/orchestration.py` with full millisecond timestamps to prevent 100s modulo collisions, and narrowed error detection to status codes / explicit error prefixes.
  - Fixed `api_provider.deploy_keys(dry_run=True)` so dry-runs no longer write `.env` files, and ensured `_cli()` returns integer exit codes.
  - Fixed `archon/routers/telegram.py` (`api_telegram_voice_relay` passing empty `datei_name`/`datei_b64` instead of FastAPI `FieldInfo` objects; secret redaction in `api_telegram_send`) and `scripts/patches/hermes_telegram_adapter.py` inbox key lookup (`emails`/`email`).
- **Routing, Memory & Context Compaction:**
  - `backend/agent_router.py`: Circuit breaker now aborts outbound LLM calls via `BudgetExceededError`; `_compress_conversation_window` preserves the task anchor before recent turns; `stream_chat_completion` now applies `AUTO_MODEL_MAP` and `gate["provider"]` (EU fallback).
  - `backend/memory_consolidator.py`: Corrected `audit_log` pruning columns (`timestamp`, `action`) with warning logging; `backend/context_compactor.py`: fixed `and` vs `or` trigger condition; `local_memory_bridge.py`: isolated explicit `session_id` history queries and chunked `DELETE ... IN (...)` eviction into 500-row batches.
- **Security, Zero-Egress & RBAC:**
  - `archon/routers/chat.py`: Enforced `safe_path_within` on `[Datei angehängt: ...]` attachments and validated `agent_id` against path traversal.
  - `archon/routers/hermes_proxy.py` & `utils/reverse_proxy.py`: Disabled HTTP redirect following (`follow_redirects=False`) in `proxy_web_ui`, HTML-escaped `url`/error output, and stripped `Authorization`, `Proxy-Authorization`, `X-Archon-Session`, and `X-Archon-Service-Token` from proxied upstream headers.
  - Enforced Zero-Egress hard-block propagation in `core_dispatcher.dispatch_to_external_agent` and gated `archon/routers/container_ops.send_prompt_to_agent` via `evaluate_and_gate_llm_dispatch`.
  - Replaced fail-open `hasattr(app_main, "require_admin")` checks in `mesh.py`, `resilience.py`, `documents.py`, `watchdog.py`, `core_settings.py`, and `inbox_tools.py` with fail-closed fallback to `archon.routers._rbac.require_admin_or_503` (and handled `request is None` cleanly in `archon/routers/auth.py`).
  - Hardened `backend/agent_rbac_jail.py` (removed leading `/` stripping via `lstrip("./")`, fail-closed on unknown roles) and sanitized `tool_name`/`skill_name`/`agent_id` in `backend/self_evolving_tooling.py` and `backend/skill_synthesizer.py`.
- **Concurrency, SQLite & Frontend:**
  - `archon/core/runtime.py`: Thread-safe SSE dispatch via `loop.call_soon_threadsafe()` and `_TICKER_LOCK` around `ticker_entries`.
  - `archon/core/delegation.py`: Closed Kanban connections in `try/finally` and spawned background execution after `commit()`; enabled `PRAGMA journal_mode=WAL;` in `archon/core/state_db.py`.
  - `static/js/watchdog_controller.js` & `static/js/chat_engine.js`: Re-enabled basket button in `finally`, added non-2xx error alert, and kept `window.currentMasterChatAttachments` in sync on clear.
  - `scripts/audit_secrets.py`: Whitelisted `tests/test_zero_egress_and_dispatch_audit.py` dummy key in `SAFE_FILE_EXCEPTIONS` for CI.
  - **Locale Parity & Legacy Cleanup:** Added missing `data-i18n` / `data-i18n-title` annotations in `system_settings_modal.html`, `log_stream_view.html`, and `index.html` with full key parity across all 11 locale JSON catalogs (`static/locales/*.json`); archived the disconnected Streamlit mock `app.py` to `_archive_legacy/app.py`.
  - **Frontend XSS & Single-SSE Consolidation:** Consolidated duplicate `/api/v1/events/stream` `EventSource` connections onto the shared `archon:sse` event bus (`operations_kanban.js` + `chat_engine.js`), added in-flight mount guards to `setOperationsTab`, enforced `http(s)/`-scheme filtering on Watchdog links, escaped dynamic attributes/quotes (`chat_engine.js`, `system_settings.js`, `watchdog_controller.js`, `static/index.html`, `operations_kanban.js`), and gated `_privacyPollingInterval` on `document.hidden`.
  - **Voyager Sandbox & Event-Loop Offloading:** Isolated `backend/self_evolving_tooling.test_in_sandbox` in a clean `TemporaryDirectory` with `python -I`, stripped host env secrets, and POSIX `rlimit` caps; offloaded `main.py` lifespan hooks to `asyncio.to_thread(...)`, and converted `core_dispatcher._TASK_SEMAPHORE` to per-loop lookup.
  - **SQLite Point-Lookups, Bounded I/O & Backend Module Wiring:** Added `_load_single_task_from_conn` in `archon/core/mission_control.py` so `mc_get_task_sqlite` and `mc_update_task_sqlite` query only the target task + links instead of loading the entire state; introduced bounded `run_io_bound` (`ThreadPoolExecutor(max_workers=4)`) in `archon/core/runtime.py` for `orchestration.py` Obsidian sync; wired XML-escaped `core_memory_manager.compile_system_prompt_injection()` and epsilon-greedy `bandit_model_router.select_best_model()` (`auto/bandit`) into `core_dispatcher.py`.
  - **Runtime-Crash-, Auth- & Pipeline-Sanierung (M59):** Fixed import/method crashes in `hr.py`, `governance.py`, `operations_autonomy.py`, `email_draft_engine.py` (`get_status_counts`), `operations_org.py`, and `memory_consolidator.py`; eliminated the remaining 9 fail-open `_require_admin` fallbacks; stopped `archon/routers/core_settings.py` from forwarding Archon `Authorization: Bearer` calls to Hermes; unified `auth.py` toggle paths and dynamic `secure` cookie flag; completed `"failed"` terminal detection in `archon/core/delegation.py`, accurate `target_status` propagation in `operations_api.py`, chat `history` + Anthropic `type == "text"` parsing + OmniRoute precedence + token usage logging in `core_dispatcher.py`/`agent_router.py`, live telemetry in `archon/routers/telemetry.py`, tenant `erp.db` lookups in `backend/speculative_prefetcher.py`, real async step execution in `backend/playbooks_engine.py`, and missing handlers in `apollo_voice_engine.py`.
  - **Event-Loop, HTTP-Pool, SQLite & Frontend-Entlastung (M57/M58):** Offloaded blocking subprocess/SQLite loops (`gateway.py`, `operations_org.py`, `skills.py`) via `asyncio.to_thread`; added pooled `httpx.AsyncClient` reuse across `core_dispatcher.py`, `hermes_proxy.py`, and `system.py`; hardened SQLite connections (`_ClosingAuthConn` in `auth_service.py`, path/PRAGMA caching in `db_paths.py`, `state_db.py`, `mission_control.py`, indexes + touch cooldown in `local_memory_bridge.py`, SQL date filter in `guardian.py`, `deque` + config cache in `async_write_batcher.py`). Removed dead `EventSource` in `skill_markt.js` and duplicate SSE stream in `mission_control_cockpit.js`, lazy-loaded `localhost:9119` iframes and secondary views in `static/index.html`, restricted `no-cache` to `/static/avatars/` in `main.py`, removed `selectionchange` icon re-scans in `agent_profiles.js`, and added debounced/`AbortController` search in `crm_studio.js`, `agent_profiles.js`, and `erp_studio.js`.
  - **Aktive Security-Middleware, Recht/Compliance & Legacy-Entkopplung (M60/M61):** Wired `enforce_egress_firewall_for_url` and `sanitize_outbound_llm_payload` (`secret_masker` + `pii_scrubber`) directly into `core_dispatcher.py` and `agent_router.py`; moved browser transcription in `frontend/src/utils/aiAudio.ts` onto server-side `POST /api/voice/transcribe` (`archon/routers/voice.py`); added full payload SHA-256 recomputation in `execution_receipt_ledger.verify_chain_integrity()`, GoBD reversion locks in `erp_manager.py`, daily § 288 BGB default interest + fee-free level 1 in `dunning_engine.py`, strict DSGVO opt-in defaults (`0`) in `crm_service.py`/`tenant_context.py`, honest `privacy_router` local labels, EU AI Act Art. 4/Art. 50 guards (`compliance_engine.py`, `eu_ai_act_inventory.py`, `chat.py`), `/api/legal/impressum` & `/api/legal/datenschutz` links (§ 5 DDG / Art. 13 DSGVO), XSS escaping in `prompt_studio.js` & `erp_studio.js`, legacy `evey-*` filtering (`guardian.py`), and `POCKETBASE_ENABLED=false` gating in `erp_manager.py`, `gdpr_compliance_engine.py`, and `settings_state.py`.
  - **Sprint-2 Härtung (Sandbox, DSGVO Voll-Export, Frontend-XSS/WCAG & Compose/Lizenzen):**
    - `views_core.py`: Enforced `safe_path_within` on `/showroom/file/delete`, `/restore`, `/purge` and `run_showroom_code` `filepath`, and isolated Python execution inside `TemporaryDirectory` with `python -I`, stripped host env secrets, and POSIX `rlimit` caps.
    - `backend/gdpr_compliance_engine.py`: Switched Art. 15 `export_subject_data` default to ungekürzte `LIMIT 500 OFFSET ?` pagination (optional `max_messages` preview still flags truncation) and Art. 17 redaction to case-insensitive `re.IGNORECASE` matching.
    - `docker-compose.yml` & `THIRD_PARTY_LICENSES.md`: Passed missing API/service/webhook/vault/PocketBase env keys (`POCKETBASE_ENABLED=false`) to `archon-os` and documented Backend Python & Frontend vendor libraries (`lucide`, `tailwind`, `marked`, `dompurify`, `chart.js`, `3d-force-graph`/`Three.js`).
    - Frontend XSS & WCAG fixes: Removed nested `<main>` in `static/index.html`, removed `maximum-scale=1.0, user-scalable=no` in `static/mobile.html`, escaped Boardroom SSE + history (`static/js/skill_markt.js`), Comm-Feed (`static/js/operations_kanban.js`), and NotebookLM (`static/index.html`) interpolations, and replaced bare `outline: none` focus suppression in `static/css/themes.css` with visible `box-shadow` focus rings.
  - **M57 Abschluss (Build-CSS, WCAG-Dialoge & ERP-i18n):**
    - `scripts/build_tailwind_css.mjs` & `static/css/tailwind.generated.css`: Precompiled Tailwind v3.4 utilities offline (`npm`/browser-JIT-free), replacing `static/js/tailwind.cdn.js` in `static/index.html` and external CDNs in `static/hermes-hud/index.html` with local static CSS/vendor assets.
    - `static/js/modal_a11y.js`, `static/index.html`, and `static/views/*.html`: Added `role="dialog" aria-modal="true"` across all 39 modals/drawers (`role="status" aria-live="polite"` on `global-loading-overlay`) with automatic `aria-labelledby`, `Tab`/`Shift+Tab` focus trap, `Escape` handling, and opener focus restoration.
    - `static/erp_studio.js` & `static/locales/*.json`: Replaced all 124 hardcoded German UI strings and static tab metadata tables with `erpT("ui.erp_studio.*", ...)` (`window.archonI18n`), synced cleanly across all 11 locale catalogs (`de`, `en`, `es`, `fr`, `it`, `ja`, `ko`, `nl`, `pt`, `ru`, `zh`).
  - **M30 First-Run Branding & M28 ERP Core Exports:**
    - `static/archon_os_logo.png`, `static/js/onboarding_wizard.js`, `static/js/customizer.js`, `backend/onboarding_wizard.py`, `archon/routers/onboarding.py`, `static/views/system_settings_modal.html`: Added the Archon OS hero logo banner above the First-Run wizard settings, added a live top-left Corner CI-Brand logo selector (3 presets + custom image upload + validated `logo_url` persistence into `company_profile` and `/api/theme`), exposed `existing_data_detected` hints so pre-configured systems can safely skip or reopen Setup via *Settings > Design*, and aligned `customizer.js` default corner logo to `/static/archon_os_logo.png`.
    - `backend/erp_manager.py`, `backend/erp_zugferd_pdf.py`, `archon/routers/erp.py`, `static/erp_studio.js`, `static/views/view_operations_erp.html`: Completed **M28 ERP Core Expansion** with EN 16931 / XRechnung 3.0 UBL-2.1 XML export (`GET /api/erp/documents/{doc_id}/xrechnung.xml`), dependency-free ZUGFeRD 2.2 / Factur-X Hybrid PDF export (`GET /api/erp/documents/{doc_id}/zugferd.pdf` embedding `factur-x.xml` + EN 16931 XMP), DATEV EXTF Buchungsstapel CSV export (`GET /api/erp/export/datev.csv`), `leitweg_id` schema/snapshot propagation, idempotent atomic inventory deduction/reversal (`stock_deducted`), and ISO 20022 `CAMT.053` / SWIFT `MT940` / Bank-`CSV` import & OPOS reconciliation (`erp_bank_transactions`, `/api/erp/bank/import`, `/api/erp/bank/transactions/{tx_id}/match`, XXE guard, SHA-256 deduplication). Removed obsolete duplicate static/view files (`static/3d-force-graph.min.js`, `static/three.min.js`, `views/view_library.py`) and updated `backend/system_dossier_generator.py` & `docs/system/ROADMAP_2026.md`.
    - **M29 Visual Form & Document Editor:** Added dependency-free ISO-18004 ECC-M EPC-QR GiroCode generator (`backend/qr_girocode.py`), refactored `backend/corporate_manager.py` with per-company persisted template layouts (`template_layouts`), DIN 5008 fold marks, company logo embedding, 6 document templates (incl. `dunning` levels 1–3), idempotent XSS-safe `{{placeholder}}` resolution, and live § 14 Abs. 4 UStG compliance verification (`validate_ustg_compliance`); added `/api/corporate/template-layout` and A4 vector-PDF export `/api/corporate/render-pdf` (`backend/erp_zugferd_pdf.build_corporate_template_pdf`) alongside upgraded editor UI (`static/views/view_corporate.html`, `static/js/corporate_controller.js`, `static/erp_studio.js`, 11 locale catalogs).
  - **Air-Gap Vendoring, Profile SSOT & GPU Micro-Effects Polish:**
    - `static/hermes-webui/` (`index.html`, `boot.js`, `ui.js`, `terminal.js`, `sw.js`): Vendored remaining `cdn.jsdelivr.net` libraries (`xterm@5.3.0`, `xterm-addon-fit`, `xterm-addon-web-links`, `prismjs@1.29.0`, `pdfjs-dist@4.9.155`, `mermaid@10.9.3`) locally under `static/hermes-webui/vendor/` for zero external CDN calls.
    - `archon/routers/hermes_config.py` & `archon/core/profiles.py`: Fixed `APP_ROOT` resolution for `agent_profiles.json` and stopped `save_all_agent_profiles` from writing redundant `roles.json` clones when mirror paths do not already exist; archived duplicate `data/live_theme_overrides.json` into `archive/live_theme_overrides.json`.
    - `static/index.html` & `static/custom.css`: Pointed favicon links to existing `/static/logo.png` and `/static/favicon.ico`, added Tailwind v4 utility polyfills, lifted blanket `* { box-shadow: none !important; }` reset, and added GPU-accelerated hover/press/dialog micro-effects with `prefers-reduced-motion` support (`tests/test_audit_fixes_batch.py`).

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
- **M56 — Archon OS Sidebar Version & GitHub Update Badge (`static/js/archon_version_badge.js`):**
  - Permanent Archon OS version bar in the bottom-left sidebar above the Hermes status strip, comparing local `config/version.json` & `HEAD` against `origin/main` on GitHub and jumping with 1 click directly to *Settings → System-Update* when an update is available.
- **M44, M52, M53 & M25 — Business Playbooks, Pre-Flight/Shadow-Mode, Epistemic Hygiene & Operations Calendar:**
  - Added 10 active + 15 catalog Business Playbooks with editor CRUD (`backend/playbooks_engine.py`), chain cost estimation & >90% Shadow-Mode graduation (`backend/shadow_mode.py`), Obsidian vault conflict/staleness scanner (`backend/epistemic_hygiene.py`), and unified Operations Calendar (`backend/operations_calendar.py`).

## [v0.5.2] — 2026-11-13 (Zero-Trust & Multi-Arch Hardening)

### Fixed & Hardened
- **Multi-Arch Docker Build (`amd64` + `arm64` / Apple Silicon):** Dynamic `TARGETARCH` Docker CLI binary resolution and standalone image packaging (`archon/`, `backend/`, `utils/`, `plugins/`, `config/`, `scripts/`, `templates/`).
- **Fresh-Clone Compose Reliability:** Removed `external: true` network blocker, resolved host port `3001` collision (`grafana` moved to `3003`), integrated `omniroute:3.8.50` into default `docker-compose.yml`, and pinned multi-arch upstream images (`nousresearch/hermes-agent:v0.23.1`, `n8nio/n8n:2.36.8`, `tecnativa/docker-socket-proxy:v0.5.0`).
- **Zero-Trust Runtime & RBAC:** Enforced non-root UID `1000` (`read_only: true`, `cap_drop: [ALL]`, no raw `docker.sock`), added global + 72-router write-block for `viewer` role, and upgraded 83 SQLite context-manager sites to deterministic handle-closing connections.
