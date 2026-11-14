# AgenticOS-2026 (Archon OS) – Systemarchitektur & Technisches Audit (v0.5.2.1)

*Stand: 13. November 2026 | Release: v0.5.2.1 (Global Release Edition)*  
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
| **Pocketbase** | `:8090` | Relationale Datenbank für CRM, Kontakte, Korrespondenz & Kalender | **Aktiv** | `./pocketbase/pb_data` |
| **Pocketbase-Media** | `:8092` | Asset-, Audio- & Medien-Speicher | **Aktiv** | `./pocketbase-media` |
| **CRM** | `:3005` | Dediziertes Web-Frontend für Vertrieb & Kontaktverwaltung | **Aktiv** | `./CRM` |
| **n8n** | `:5678` | Event-Trigger & Low-Code Workflow-Automatisierung | **Bereit** | `n8n_data` |
| **docker-socket-proxy** | `:2375` (intern) | Isolierter HAProxy-Docker-API-Proxy (`archon-admin_net`, Allowlist + `DockerAdminClient`) | **Aktiv** | `/var/run/docker.sock:ro` |
| **anything-llm** | `:3001` | Lokale RAG-Engine & Vektorspeicher für Wissensarchive (`qwen3-embedding-8b`) | **Aktiv** | internes Storage |
| **litestream** | - (Daemon) | Kontinuierliche SQLite-WAL-Replikation (5–10s Intervall) | **Bereit** | `config/litestream.yml` |
| **langfuse** | `:3000` | OpenTelemetry & Langfuse Observability & Tracing UI | **Bereit** | Profile `tracing` in `docker-compose.yml` |

---

## 2. Speicher-Architektur & Persistenzschichten

Das System nutzt SQLite (WAL-Modus) als durchgängige Single Source of Truth:

1. **SQLite Datenbanken (Transaktional & Systemzustand):**
   - [`data/kanban.db`](../../data/kanban.db): **Einzige Single Source of Truth** für alle operativen Aufgaben, Mission Control, Delegation und Fan-In (`tasks`, `task_links`, `task_events`, `task_comments`, `task_attachments`, `mc_task_meta`, `mc_kv`). Die frühere parallele Datei `mission_control_data.json` ist vollständig abgelöst.
   - [`data/agentic_memory.db`](../../data/agentic_memory.db): Zentraler Zustandsspeicher mit Write-Ahead-Logging (WAL) inkl. den 5 Standardtabellen (`user_profile`, `learnings`, `kv_store`, `tasks`, `conversations`) sowie SHA-256-verkettetem Audit-Log (`audit_log`).
   - `/opt/data/state.db`: Hermes Sitzungshistorie, Prompt-Kontexte und Interaktionslogs.
   - `pocketbase/pb_data`: CRM-Datenbank für Kontakte, Nachrichtenverläufe und Bewerbungen.

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
| **5. Hardware-Routing** | Multi-Provider Routing über OmniRoute, Logit-Snapshots | OmniRoute läuft auf Port `20128` und routet dynamisch auf OpenAI, Anthropic, Gemini, DeepSeek und lokale Endpunkte; `hermes_updater` nutzt dedizierten `DockerAdminClient` über `docker-socket-proxy`. | **Erfüllt** |
| **6. Governance & Sicherheit** | RBAC, HITL-Approval, manipulationssicheres Audit-Log, Injection-Filter | RBAC über alle schreibenden Admin-Routen; 25 Prompt-Injection-Muster (`local_security_guard.py`); SHA-256-verkettetes Audit-Log (`backend/audit_log.py`); **EU AI Act Compliance-Engine, Art.-4-Register & 1-Klick GoBD-Verfahrensdokumentations-PDF** ([Guide](EU_AI_ACT_GOBD_COMPLIANCE_GUIDE.md)); Secrets-Gate (`scripts/audit_secrets.py`); Caddy Reverse Proxy & Authelia SSO ([Guide](../security/REVERSE_PROXY_SSO_GUIDE.md)); DSGVO Art. 15/17 ([Guide](GDPR_COMPLIANCE_GUIDE.md)). | **Erfüllt** |
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
