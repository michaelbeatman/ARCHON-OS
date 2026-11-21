# AgenticOS-2026 (Archon OS) – Systemarchitektur & Technisches Audit (v0.5.6.0)

*Stand: 21. November 2026 | Release: v0.5.6.0 (Phase 1–3 Hardening, 28→3 SQLite Consolidation & Content-Maschine v2)*  
*Maschinenlesbares Gegenstück:* [`docs/system/system_architecture_spec.json`](system_architecture_spec.json)  
*Endbenutzer-Handbuch (PDF):* [`docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf`](ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)  
*Vollständige Featureliste (PDF):* [`docs/system/ARCHON_OS_FEATURELISTE_2026.pdf`](ARCHON_OS_FEATURELISTE_2026.pdf) | *55 Boardroom-Frameworks:* [`docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf`](ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)

---

## 1. Systemübersicht & Topologie

AgenticOS-2026 (Archon OS) ist ein modulares, containerisiertes Betriebssystem für autonome Multi-Agenten-Netzwerke. Das System verbindet eine modulare FastAPI-Steuerzentrale auf Port `8501` (`main.py` + `archon/routers/*`) mit spezialisierten Diensten für LLM-Routing, Workflow-Automatisierung, relationale Datenspeicherung und Agenten-Orchestrierung.

### 1.1 Aktive Container-Landschaft (Docker Runtime)

| Container | Host-Port | Interne Rolle | Status | Datenpfad / Volume |
| :--- | :--- | :--- | :--- | :--- |
| **ARCHON-OS** | `:8501` | Zentrales Gateway, FastAPI Backend & Frontend UI | **Aktiv** | `./` (Bind-Mount), `/app/data` |
| **omniroute** | `:20128` | Multi-Provider LLM-Router (OpenAI, Anthropic, Gemini, Groq, DeepSeek) | **Aktiv** | `omniroute-data` |
| **hermes-webui** | `:8787` | Aktiver Hermes Agent Core & WebUI-Laufzeitcontainer | **Aktiv** | `/opt/data`, `~/.hermes` |
| **hermes-dashboard** | `:9119` | Visualisierungs-Dashboard für Hermes-Sitzungen | **Aktiv** | intern (`archon-hermes_hermes-net`) |
| **hermes-agent** | `:8642` | Hermes Gateway-Container (`gateway run`, manuell gestoppt / on-demand) | **Bereit** | `/home/hermes/.hermes` |
| **Pocketbase** | `:8090` | Optionaler externer CRM-Sync (Archon intern deaktiviert bei `POCKETBASE_ENABLED=false`, lokal via `erp.db`) | **Optional / Deaktiviert** | `./pocketbase/pb_data` |
| **Pocketbase-Media** | `:8092` | Optionaler Asset-, Audio- & Medien-Speicher | **Optional** | `./pocketbase-media` |
| **CRM** | `:3005` | Separates Server-CRM außerhalb des Archon-Standard-Stacks (`DEFAULT_SERVICES` deaktiviert) | **Extern / Separat** | `./CRM` |
| **n8n** | `:5678` | Event-Trigger & Low-Code Workflow-Automatisierung | **Bereit** | `n8n_data` |
| **docker-socket-proxy** | `:2375` (intern) | Isolierter HAProxy-Docker-API-Proxy (`archon-admin_net`, Allowlist + `DockerAdminClient`) | **Aktiv** | `/var/run/docker.sock:ro` |
| **anything-llm** | `:3001` | Lokale RAG-Engine & Vektorspeicher für Wissensarchive (`qwen3-embedding-8b`) | **Aktiv** | internes Storage |
| **litestream** | - (Daemon) | Kontinuierliche SQLite-WAL-Replikation (5–10s Intervall) | **Bereit** | `config/litestream.yml` |
| **langfuse** | `:3000` | OpenTelemetry & Langfuse Observability & Tracing UI | **Bereit** | Profile `tracing` in `docker-compose.yml` |

---

## 2. Speicher-Architektur & Persistenzschichten

Das System nutzt SQLite (WAL-Modus) als durchgängige Single Source of Truth:

1. **SQLite Datenbanken (Transaktional & Systemzustand — Phase-2-Konsolidierung `28 → 3`):**
   - [`backend/db_consolidation.py`](../../backend/db_consolidation.py) & [`backend/db_paths.py`](../../backend/db_paths.py) konsolidieren die historisch gewachsenen 28 Einzel-SQLite-Dateien in **3 domänenisolierte WAL-Datenbanken** (`PRAGMA journal_mode=WAL`, `busy_timeout=5000`, automatische Kollisions-Präfixe `<legacy_stem>__<table>`, Pre-Consolidation-Backups und transparenter Pfad-Adapter `resolve_db()` + `TenantContextManager.resolve_active_db()` + `DBBackupManager`):
     1. **`data/ops.db` (Operative Steuerung, Workflows & Security):** Vereint `kanban.db`, `workflow_dags.db`, `state.db`, `audit_log.db`, `execution_receipts.db`, `precedents.db`, `taint_guard.db`, `flightlog.db`, `watchdog_v2.db` u. a.
     2. **`data/business.db` (ERP, CRM, Verträge, Treasury & Content-Maschine):** Vereint `erp.db`, `crm.db`, `deals.db`, `contracts.db`, `treasury.db`, `time_tracking.db`, `client_portal.db` sowie die Tabellen der **Multi-Channel Content-Maschine v2** (`content_campaigns`, `content_assets`, `content_metrics`, `content_repurpose_runs`).
     3. **`data/memory.db` (Agenten-Gedächtnis & Sessions):** Vereint `agentic_memory.db` (`user_profile`, `learnings`, `kv_store`, `tasks`, `conversations`, `ephemeral_task_forces`), `compartment_vault.db` und `lcm_sessions.db`.
   - Abwärtskompatibilität: Solange oder wo Einzeldateien (`data/kanban.db`, `data/agentic_memory.db`, `/opt/data/state.db`) angefordert werden, routet `backend/db_paths.py` bei aktivierter Konsolidierung transparent auf die jeweilige Ziel-Domänen-DB.

2. **JSON-Deklarationen & Sidecar-Dateien:**
   - [`agent_profiles.json`](../../agent_profiles.json): **70 vollständige Agenten-Profile** mit zweisprachigen System-Prompts (DE/EN), 3-Stufen-`SOUL.md` (`Compact`, `Pro / Skills+`, `Full-SOUL`), Tool-Scopes, Fähigkeiten (`skills`), Avataren und Modell-Routings.
   - [`prompt_studio_catalog.json`](../../prompt_studio_catalog.json): **832 zweisprachige Prompt-Vorlagen** (DE/EN) mit verifizierter 100 % Variablen-Parität für das Archon Prompt Studio.
   - [`core_dispatcher.py`](../../core_dispatcher.py): **55 Boardroom-Frameworks** (DE/EN) für mehrperspektivische Exekutiv-Debatten.
   - [`backend/onboarding_wizard.py`](../../backend/onboarding_wizard.py): **Web-Setup-Wizard (M30)** für geführtes 4-Schritte-First-Run-Onboarding.
   - [`backend/demo_mode.py`](../../backend/demo_mode.py): **Zero-Install Live-Demo-Modus (`ARCHON_DEMO_MODE`, M47)** für sichere, öffentliche Showcase-Instanzen.
   - [`backend/mcp_gateway.py`](../../backend/mcp_gateway.py): **Nativer MCP-Server (`/mcp` Gateway, M48)** mit Streamable HTTP/SSE, Scoped API-Keys & HITL-Gate.
   - [`backend/squad_pack_manager.py`](../../backend/squad_pack_manager.py): **Squad-Blueprint-Paketmanager (`.archonpack`, M51)** für portablen Export/Import.
   - [`backend/tenant_context.py`](../../backend/tenant_context.py): **Multi-Mandanten-Kontext (M43)** mit durchgängiger physischer SQLite-DB-Isolation (`data/tenants/<id>/` für `erp.db`, `kanban.db`, `crm.db`, `contracts.db`, `deals.db`), 1-Klick-Mandantenanlage & atomaren Nummernkreisen ([Guide](EU_AI_ACT_GOBD_COMPLIANCE_GUIDE.md)).
   - [`backend/compliance_engine.py`](../../backend/compliance_engine.py) & [`backend/compliance_pdf.py`](../../backend/compliance_pdf.py): **EU AI Act Compliance-Engine & 1-Klick GoBD-Verfahrensdokumentation PDF (M49)** mit präziser Anhang-III-/Art.-50-Klassifizierung aller 70 Spezialisten, `SOUL.md`-SHA-256-Hashes, Art.-4-KI-Kompetenzregister und abhängigkeitsfreiem DIN-A4-PDF-1.4-Export ([Guide](EU_AI_ACT_GOBD_COMPLIANCE_GUIDE.md)).
   - [`backend/playbooks_engine.py`](../../backend/playbooks_engine.py): **Business Playbooks (M44)** mit 10 aktiven Vorlagen, 15 Katalog-Rezepten & Editor-CRUD.
   - [`backend/shadow_mode.py`](../../backend/shadow_mode.py) & [`backend/epistemic_hygiene.py`](../../backend/epistemic_hygiene.py) & [`backend/operations_calendar.py`](../../backend/operations_calendar.py): **Pre-Flight/Shadow-Mode (M52)**, **Obsidian Epistemic Hygiene (M53)** & **Operations-Kalender (M25)**.
   - [`config/kanban_meta.json`](../../config/kanban_meta.json): Sidecar-Metadaten (WIP-Limits, Obsidian-Verknüpfungen, Tags) über [`backend/kanban_sidecar.py`](../../backend/kanban_sidecar.py).
   - [`config/org_hierarchy.json`](../../config/org_hierarchy.json): Interaktives Ablaufdiagramm (64 Knoten, 63 Berichtslinien).
   - [`config/teams.json`](../../config/teams.json): Zuordnung der Unternehmensbereiche.

---

## 3. Workflow-Engine & Board-Architektur

### 3.1 Operations Kanban & Mission Control auf `kanban.db`
Die operative Steuerung und das Monitoring-Cockpit arbeiten auf derselben SQLite-Datenbank (`kanban.db`):
- **Operations Kanban:** 5 Standard-Spalten (`To-Do`, `In Bearbeitung`, `Review & QA`, `Blockiert`, `Abgeschlossen`) mit 10 %-Spaltentönung und SSE-Echtzeit-Push (`docs/system/LIVE_STREAMING_SSE_WEBSOCKET_GUIDE.md`).
- **Mission Control Store (`archon/core/mission_control.py`):** Schreibt und liest direkt gegen `kanban.db` (`tasks`, `task_links`, `task_events`, `mc_task_meta`, `mc_kv`) mit Prozess-Serialisierung (`_MC_DATA_LOCK` + `BEGIN IMMEDIATE`) sowie `backend/audit_log.py`.

### 3.2 Delegation, Synthese & Governance-Kaskade
1. **Strategische Aufgabenteilung:** Chef-Stratege Robert (`executive_decision_architect`) bzw. `archon/core/delegation.py` zerlegt komplexe Vorhaben in Teilaufgaben und verknüpft Parent und Child direkt über `task_links` und `project_id` in `kanban.db`.
2. **Fan-in-Synchronisation (`archon/core/orchestration.py`):** Sobald alle Kind-Tasks in `kanban.db` den Status `completed`/`done` erreichen, startet die Synthese automatisch unter Sperrschutz (`_MC_ASYNC_LOCK` + `_MC_DATA_LOCK`).
3. **Synthese-Qualitätsprüfung (Marker-Kontrakt):** Lisa (`aggregation_lisa`) bündelt die Fachberichte mit Marker-Prüfung (`SYNTHESE-BEREIT` + Reparatur-Retry).
4. **Strikte Robert-Freigabe & HITL:** Robert prüft den konsolidierten Bericht. Nur explizites `FREIGABE` in der ersten Zeile finalisiert das Projekt; alles andere landet als Kanban-Entscheidung beim Owner.

---

## 4. Kommunikations- und Triage-Eingang (Inbox & Telegram)

- **Posteingang (Triage):** Mehrspaltige Übersicht im SPA-Posteingang (`static/views/inbox_view.html`):
  1. *Webhooks & Intern:* System-Logs, Docker-Events, Approval-Gates.
  2. *E-Mail:* Aus Posteo/IMAP synchronisierte Nachrichten (`/opt/data/inbox/emails/`).
  3. *Messenger / Telegram:* Echtzeit-Stream eingehender Benutzernachrichten (`/opt/data/inbox/telegram/`).
- **Telegram-Integration:** Der Hermes-Telegram-Adapter ([`scripts/patches/hermes_telegram_adapter.py`](../../scripts/patches/hermes_telegram_adapter.py)) spiegelt eingehende Nachrichten in das Archon-Postfach und sichert interaktive HITL-Buttons per HTML-Escaping ab.

---

## 5. Ist-Analyse gegen die 7 Antigravity-Säulen

| Säule | Vorgabe | Aktueller Zustand | Status |
| :--- | :--- | :--- | :--- |
| **1. Kernel & Scheduling** | Daemon-Architektur, Tickless Sleep, Watchdog 30s, OTel Tracing | Watchdog läuft in eigenem Thread (`watchdog_daemon.py`); App auf Port `8501` via Uvicorn; OpenTelemetry & Langfuse Tracing ([Guide](LLM_TRACING_LANGFUSE_GUIDE.md)); Pre-Flight Validator ([Guide](CONFIG_VALIDATION_GUIDE.md)); Prometheus & Grafana Monitoring ([Guide](PROMETHEUS_GRAFANA_MONITORING_GUIDE.md)); Zentrale Logs mit Loki & Promtail ([Guide](CENTRAL_LOGGING_LOKI_GUIDE.md)); Live-Streaming per SSE & WebSocket ([Guide](LIVE_STREAMING_SSE_WEBSOCKET_GUIDE.md)). | **Erfüllt** |
| **2. Prozessmodell** | Subagenten als Prozesse, Task-Zustände, Crash-Recovery, Concurrency Throttle | 70 Profile mit einheitlichem 3-Stufen-`SOUL.md` (DE/EN) & Skills-Wiring aktiv; Tasks und Subagenten-Links über `kanban.db` nachverfolgt; Auto-Crash-Recovery (6h); Prompt-Registry mit Canary-Rollout ([Guide](PROMPT_REGISTRY_CANARY_GUIDE.md)); Chaos- und Resilienz-Tests ([Guide](CHAOS_RESILIENCE_GUIDE.md)). | **Erfüllt** |
| **3. Device Driver (MCP)** | MCP Server-Ecosystem, `mcp__{server}__{tool}`, Lock-Scheduler | MCP-Treiber für CRM (`archon_crm_mcp.py`), n8n (`scripts/mcp_n8n_driver.py`) und nativer Archon OS MCP-Server (`scripts/archon_mcp_server.py`) aktiv ([Guide](ARCHON_MCP_SERVER_GUIDE.md)). | **Erfüllt** |
| **4. Dateisystem & RAM** | SQLite WAL, 5 Tabellen, einheitliche Persistenz, Litestream | Vollständig vereinheitlicht auf SQLite WAL (`kanban.db` + `agentic_memory.db`), atomare Sidecars (`kanban_sidecar.py`), Obsidian-Ablage, Litestream-Replikation ([Guide](LITESTREAM_REPLICATION_GUIDE.md)) und Restore-Tests ([Guide](AUTOMATED_RESTORE_TEST_GUIDE.md)). | **Erfüllt** |
| **5. Hardware-Routing** | Multi-Provider Routing über OmniRoute, Logit-Snapshots | OmniRoute läuft auf Port `20128`; vorgeschaltetes Zero-Egress- & Privacy-Router-Gate (`backend/llm_egress_guard.py`, `backend/privacy_router.py`) erzwingt On-Premise-Routing für Finanzen/Verträge/CRM mit **hartem Fail-Closed Block** bei Offline-Lokalmodell sowie isoliertem Docker-Worker-Netz `archon-worker-zero-egress_net` (`internal: true`, keine Internet-Route) ([Guide](../security/LOCAL_LLM_PRIVACY_ROUTING_GUIDE.md)). | **Erfüllt** |
| **6. Governance & Sicherheit** | RBAC, HITL-Approval, manipulationssicheres Audit-Log, Injection-Filter | RBAC über alle schreibenden Admin-Routen; 25 Prompt-Injection-Muster (`local_security_guard.py`); **SHA-256-verkettetes Audit-Log inkl. lückenloser LLM-Dispatch-Protokollierung (Provider, Modell, Ziel-Host, Ziel-Endpunkt & Spaltenkonsistenz)** ([Guide](../security/GOBD_ISO27001_AUDIT_LOG_GUIDE.md)); **EU AI Act Compliance-Engine, Art.-4-Register & 1-Klick GoBD-Verfahrensdokumentations-PDF** ([Guide](EU_AI_ACT_GOBD_COMPLIANCE_GUIDE.md)); Secrets-Gate (`scripts/audit_secrets.py`); Caddy Reverse Proxy & Authelia SSO ([Guide](../security/REVERSE_PROXY_SSO_GUIDE.md)); DSGVO Art. 15/17 ([Guide](GDPR_COMPLIANCE_GUIDE.md)). | **Erfüllt** |
| **7. Selbst-Evolution** | Dynamisches Laden & Testen neuer Skills, Feedback-Loop | [`core_skills_engine.py`](../../core_skills_engine.py) & Runtime-Skill-Wiring über `skill_resolver.py`; Human-Feedback-Loop ([Guide](HUMAN_FEEDBACK_LOOP_GUIDE.md)). | **Erfüllt** |

---

## 6. Abschlussstatus aller Architekturschritte (v0.5.0.1)

Alle im Architektur-Audit definierten Konsolidierungs- und Härtungsschritte sind vollständig umgesetzt:

1. **Vollständige Vereinheitlichung der Datenzugriffe (Erledigt):**
   - `mission_control_data.json` vollständig durch native SQLite-Zugriffe auf [`data/kanban.db`](../../data/kanban.db) (`tasks`, `task_links`, `task_events`, `mc_task_meta`, `mc_kv`) abgelöst; historische Daten beim Start nach `.bak` migriert.
2. **Kryptografische Hash-Kette für das Audit-Log (Erledigt):**
   - Lückenlose SHA-256-Hashverkettung (`hash = SHA256(prev_hash + timestamp + payload)`) für DSGVO-Löschungen, Governance-Aktionen und Boardroom-Entscheidungen über `backend/audit_log.py`.
3. **Automatisierte CI/CD- & E2E-Testpipeline (Erledigt):**
   - End-to-End Lebenszyklus-Tests (`tests/test_e2e_lifecycle.py`), lokales Qualitätstor (`scripts/run_ci_suite.py`) und GitHub Actions Workflow ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), [Guide](CI_PIPELINE_E2E_TESTING_GUIDE.md)).
4. **Resilienz & zentrale Log-Aggregation (Erledigt):**
   - Chaos-Testing für Concurrency und Restart-Verhalten ([Guide](CHAOS_RESILIENCE_GUIDE.md)) sowie Grafana Loki / Promtail Logsammlung ([Guide](CENTRAL_LOGGING_LOKI_GUIDE.md)).
5. **Business Intelligence, Beleg-OCR & E-Signatur (Erledigt):**
   - Telegram-Belegdigitalisierung mit Vision-OCR nach `kanban.db` ([Guide](TELEGRAM_RECEIPT_OCR_GUIDE.md)), Metabase BI-Dashboards ([Guide](BI_DASHBOARD_METABASE_GUIDE.md)) und DocuSeal E-Signatur ([Guide](ESIGN_DOCUSEAL_GUIDE.md)).
6. **Mahnwesen & Forderungsmanagement (Erledigt):**
   - 3-stufiges BGB-konformes Mahnwesen mit HITL-Freigabe vor Versand ([Guide](DUNNING_ENGINE_GUIDE.md)).
7. **Infrastruktur als Code mit Ansible (Erledigt):**
   - Idempotente Host- und Container-Bereitstellung per Ansible Playbooks ([Guide](ANSIBLE_INFRASTRUCTURE_GUIDE.md)).
8. **Modell-Feintuning Pipeline (Erledigt):**
   - Automatisierte Extraktion und Secrets-Bereinigung für QLoRA-Finetuning kompakter Routing- und Triage-Modelle ([Guide](MODEL_FINETUNING_GUIDE.md)).

---

## 5. Technisches Tiefen-Audit & Härtung (15. November 2026)

- **Orchestrierung & Dispatch-Stabilität:** Fehlende Wrapper-Imports in `main.py` ergänzt, AutoHire-Statusrückgabe (`bool`) korrigiert, MoA-Synthese-`UnboundLocalError` in `core_dispatcher.py` behoben, Subtask-ID-Kollisionen (`% 100000`) auf volle Millisekunden-IDs umgestellt und Lifespan-Hooks in `main.py` (`_archon_lifespan`) per `asyncio.to_thread()` ausgelagert.
- **Zero-Egress, RBAC & Sandbox-Isolation:** `dispatch_to_external_agent` propagiert `status == "blocked"` hart ohne Cloud-Fallback; `container_ops.send_prompt_to_agent` nutzt `evaluate_and_gate_llm_dispatch`; Fail-Open-Admin-Wrapper in 6 Routern auf fail-closed `_rbac.require_admin_or_503` umgestellt; Chat-Dateianhänge (`safe_path_within`), `hermes_proxy.py` (`follow_redirects=False` + `html.escape`) und `reverse_proxy.py` (Auth-Header-Stripping) gehärtet; `self_evolving_tooling.test_in_sandbox` läuft isoliert (`python -I`, `TemporaryDirectory`, ohne Host-Env-Secrets, POSIX-`rlimit`).
- **Frontend, SSE & i18n-Parität:** Doppelte `/api/v1/events/stream`-Verbindungen auf einen gemeinsamen `archon:sse`-Bus konsolidiert, `setOperationsTab` mit In-Flight-Guard abgesichert, XSS-Escaping in `chat_engine.js`, `system_settings.js`, `watchdog_controller.js`, `static/index.html` (`renderWatchdogAuditorIncidents`) und `operations_kanban.js` (`populateOpsKanbanAssigneeFilter`, `renderOpsOrgFlowchart`) ergänzt, `app.py` nach `_archive_legacy/app.py` verschoben und vollständige i18n-Parität über alle 11 Sprachkataloge (`static/locales/*.json`) hergestellt.
- **SQLite-Punkt-Abfragen, begrenztes I/O-Offloading & Modul-Verdrahtung:** `mc_get_task_sqlite` und `mc_update_task_sqlite` in `archon/core/mission_control.py` laden über `_load_single_task_from_conn` gezielt nur den angeforderten Task statt des gesamten Zustands. `archon/core/runtime.py` stellt `run_io_bound` (`ThreadPoolExecutor(max_workers=4)`) für blockierende Obsidian-Syncs in `archon/core/orchestration.py` bereit. `core_dispatcher.py` bindet XML-escapte Core-Memory-Blöcke (`backend/core_memory_manager.py`) sowie Epsilon-Greedy-Bandit-Routing (`backend/bandit_model_router.py` via `auto/bandit`) direkt in den Dispatch ein.

---

## 6. Sanierung der Kernfunktion, Performance & Compliance (15. November 2026, M57–M61)

- **Core-Pipeline, Crashes & Auth-Härtung:** Behobene Runtime-Crashes in `hr.py`, `governance.py`, `operations_autonomy.py`, `email_draft_engine.py`, `operations_org.py` und `memory_consolidator.py`; alle 9 fail-open `_require_admin`-Fallbacks auf fail-closed `require_admin_or_503` gehärtet; `core_settings.py` (`/api/settings` GET & POST) leitet `Authorization: Bearer` nicht länger fälschlich an Hermes weiter; `delegation.py` behandelt `"failed"`/`"blocked"` terminal; `operations_api.py` schreibt echten `target_status`; `agent_chat.py`/`core_dispatcher.py`/`agent_router.py` verarbeiten Gesprächs-`history`, Anthropic-`type == "text"`-Blöcke, OmniRoute-Vorrang und vollständiges Token-Usage-Logging; `telemetry.py`, `speculative_prefetcher.py`, `playbooks_engine.py` und `apollo_voice_engine.py` liefern reale Runtime-/DB-Ausführung statt Stub-Daten.
- **Aktive Egress-/DLP-Middleware, Sandbox & Recht (GoBD, DSGVO, BGB, AI Act, DDG):** `llm_egress_guard.py` erzwingt nun in `core_dispatcher.py` und `agent_router.py` aktiv `enforce_egress_firewall_for_url()` sowie `sanitize_outbound_llm_payload()` (`secret_masker` + `pii_scrubber`) vor externen Dispatches; `views_core.py` erzwingt `safe_path_within` auf Trash/Restore/Purge/Run und isoliert Python-Code in `TemporaryDirectory` (`python -I`, ohne Host-Secrets, POSIX-`rlimit`); `frontend/src/utils/aiAudio.ts` nutzt serverseitiges `POST /api/voice/transcribe` (`archon/routers/voice.py`) ohne Browser-Keys; `execution_receipt_ledger.verify_chain_integrity()` prüft alle SHA-256-Zeilenhashes neu; `erp_manager.py` sperrt GoBD-Statusrückstufungen (`booked`/`paid -> draft`); `dunning_engine.py` erhebt in Stufe 1 `0,00 €` Gebühr und berechnet tagesgenaue § 288 BGB-Verzugszinsen; `crm_service.py` & `tenant_context.py` setzen DSGVO Opt-In default auf `0`; `gdpr_compliance_engine.py` exportiert nach Art. 15 paginiert ohne 100er-Abschnitt und schwärzt nach Art. 17 case-insensitiv; `compliance_engine.py`/`eu_ai_act_inventory.py`/`chat.py` erzwingen Art.-4-/Art.-50-Regeln; `/api/legal/impressum` & `/api/legal/datenschutz` sind in `index.html`/`mobile.html` verlinkt und `THIRD_PARTY_LICENSES.md` umfasst Backend- & Frontend-Vendor-Pakete.
- **Event-Loop, SQLite, Frontend-Performance, WCAG & Legacy-Entkopplung:** `asyncio.to_thread` in `gateway.py`, `operations_org.py` (`try/finally: conn.close()`), `skills.py`; HTTP-Client-Pools in `core_dispatcher.py`, `hermes_proxy.py`, `system.py`; WAL/Cache-Tuning & Indizes in `auth_service.py`, `db_paths.py`, `state_db.py`, `mission_control.py`, `local_memory_bridge.py`, `guardian.py`, `async_write_batcher.py`; Frontend auf einen zentralen `archon:sse`-Bus, lazy `localhost:9119`-Iframes, debounced/`AbortController`-Suchen, `escapeErpHtml`/`safeMd`/Boardroom-/Comm-Feed-/NotebookLM-XSS-Escaping, vorkompiliertes Tailwind-CSS (`scripts/build_tailwind_css.mjs` -> `static/css/tailwind.generated.css` ohne Runtime-JIT-CDN in `index.html` & `hermes-hud/index.html`), vollständige `ui.erp_studio.*`-i18n-Parität (`erp_studio.js` -> 11 Sprachkataloge), bereinigtes `<main>`/Viewport-Zoom (`mobile.html`), sichtbare `themes.css`-Fokus-Ringe sowie `modal_a11y.js` (`role="dialog"`, Focus-Trap, `Escape` + Fokus-Rückführung auf 39 Modals/Drawer) gehärtet; `docker-compose.yml`, `crm:3005`/`pocketbase:8090` (`POCKETBASE_ENABLED=false`) und unaktivierte `evey-*`-Altlasten bereinigt.

---

## 7. Voll-Audit, Phase 1–3 Hardening, SQLite 28→3, Content-Maschine v2 & Next.js 16 (21. November 2026, M106–M108)

- **Phase 1 Security-Hardening & Exception-Eliminierung (`fc41341`, `c6763dc`, `0a69dd4`, `5db6d0e`):**
  - Echte kryptografische FIDO2/WebAuthn-Signaturprüfung (ES256/RS256, `rpIdHash`, `signCount`-Replay-Schutz) in `backend/passkey_hitl.py`.
  - Lückenloses Zero-Egress-Enforcement (`evaluate_and_gate_llm_dispatch`) in `archon/routers/boardroom.py` und `archon/routers/chat.py`; AST-basierte Sandbox-Sperre gefährlicher Module (`os`, `subprocess`, `socket`, `ctypes`, `urllib`) in `archon/routers/views_core.py`; SSRF-Schutz (`check_public_url`) für `backend/visual_web_agent.py`.
  - Über **407 stille `except ...: pass`-Blöcke** im gesamten Produktivkern (`archon/routers/*`, `backend/*`, `main.py`, `local_memory_bridge.py`, `archon/core/orchestration.py`) durch risikogestuftes Logging ersetzt.
- **Workflow-/DAG-Engine E2E & Legacy-Bereinigung:**
  - `backend/workflow_templates.py`, `backend/workflow_dag_runner.py`, `backend/workflow_scheduler.py`, `archon/routers/v2_capabilities.py` und `archon/routers/decisions.py` bilden eine durchgängige Ausführungs- und HITL-Gate-Resume-Pipeline (`tests/test_workflow_dag_e2e.py`).
  - Veraltete Doppel-Runner (`backend/dag_scheduler.py`, `backend/hybrid_sop_runner.py`, `backend/main.py`) nach `archive/20261121_legacy_workflows/` archiviert; 7 unverdrahtete Theater-Module entfernt.
- **M106 Datenbank-Konsolidierung (`28 → 3`):** `backend/db_consolidation.py` + `backend/db_paths.py` führen 28 SQLite-DBs verlustfrei und mandantenfähig (`backend/tenant_context.py`, `backend/db_backup_manager.py`) in `ops.db`, `business.db` und `memory.db` zusammen.
- **M107 Multi-Channel Content-Maschine v1 & v2 (`backend/content_machine.py`, `archon/routers/content_machine.py`):** Kampagnen- und Repurposing-DAG für LinkedIn, YouTube Longform, YouTube Shorts, TikTok & X/Threads mit deterministischem Anti-AI-Slop-Quality-Gate (`evaluate_asset_quality`), Quellen-Ingestion (`url` SSRF-safe, `obsidian` path-jailed, `transcript`), 9:16-Video-Clip-Matrix, Webhook-Dispatch, Due-Publish-Sweep und Performance-Learning-Loop.
- **M108 Next.js 16 UI-Konsolidierung (`frontend/`):** Direkte FastAPI-Anbindung ohne PocketBase über `/api/archon/[...path]` und `archon-api.ts` mit `/content-studio` (`ContentMachineCockpit.tsx`), `/workflows` (`WorkflowDagCockpit.tsx`) und `/cockpit` (`ExecutiveCockpit.tsx`).
