# Archon OS – Entwicklungs-Roadmap & Aufgabenliste

| ID | Meilenstein / Vorhaben | Priorität | Status | Kernfokus |
|---|---|---|---|---|
| **0** | **AI Boardroom finalisieren** | Hoch | Abgeschlossen | Polishing UI, Reset-Logik, PDF-Parsing via pypdf, Client-Disconnect-Handling, strukturierter Markdown-Export |
| **1** | **Updatesystem erarbeiten** | Hoch | Abgeschlossen | Versionierung, Git-Sync, automatisierte Pre-Update-Snapshots (SQLite & Configs), In-App 1-Klick Update & Rollback-Fähigkeit |
| **2** | **Steuerapp für Android** | Mittel | Geplant | PWA vs. Native Kotlin/Flutter-Client, Endpunkt-Sicherheit, Push-Benachrichtigungen, Dynamic DNS/Tailscale-Tunneling |
| **3** | **Multilingualität (i18n)** | Mittel | Abgeschlossen | 9 Weltsprachen (de, en, es, fr, pt, ru, ja, ko, zh), Locale-JSONs, dynamische DOM-Engine & Settings-Selector |
| **4** | **Multi-User & Kollaboration** | Mittel | Abgeschlossen | 3-Stufen-Rollenmodell (Admin, Operator, Viewer), PBKDF2-Auth, Sessions, Settings-Verwaltung & Topbar-Badge |
| **5** | **Funktionserweiterung / Pluginsystem** | Mittel | Abgeschlossen | Standardisierte Plugin-Schnittstelle (`backend/plugin_manager.py`), Manifeste (`plugin.json`), Lifecycle-Hooks, Registry-Integration & 3 Starter-Plugins |
| **6** | **Designkonzept-Überarbeitung** | Hoch | Abgeschlossen | Ergonomisches Designsystem v2 (`static/css/design_system_v2.css`), WCAG-Fokus-Ringe, einheitliche Typografie & Settings-/Sidebar-Modernisierung |
| **7** | **LinkedIn-Import im CRM (Bugfix & Dedup)** | Dringend | Abgeschlossen | 1.722 Duplikate bei 908 Kontakten bereinigt, CRM-Route & Import-Dedupe zeitzonen- und sender-unabhängig gehärtet |
| **8** | **Obere Icons prüfen & korrigieren** | Hoch | Abgeschlossen | Audit aller oberen Navigations- und Subview-Icons, Behebung doppelter Icons, Korrektur des Kanban-Icons |
| **9** | **Redesign der oberen Leiste & Avatar-Überlappung** | Hoch | Abgeschlossen | Vereinheitlichung nach dem Vorbild "AI Mastermind · Übersicht", Klärung & CSS-Konzept für überlappende Avatare im Kader |
| **10** | **Eingang (Inbox) Funktionsprüfung & Re-Architektur** | Hoch | Abgeschlossen | Suchleiste unter den Header mit Filter-/Markierungstools; linker Balken fokussiert auf markierte/angepinnte Items |
| **11** | **Tokenguard: Zeitraum-Skalierungsleiste für Grafen** | Normal | Abgeschlossen | Interaktive Steuerleiste zur flexiblen Skalierung des Zeitraums (24h, 7T, 30T, 90T, Gesamt) für Verbrauchs-Chart |
| **12** | **Informationsquellen-Strategie (Research Lab)** | Hoch | Abgeschlossen | Gemeinsame Bestandsaufnahme und Bewertung aller Wissensquellen (Grokipedia, Wikipedia, Fachportale, amtliche Quellen, ArXiv, Websuche): Vertrauensstufen, Rolle KI-generierter Quellen, Kosten/Limits, Quellen-Priorisierung je Fragetyp |
| **13** | **n8n Workflow-Mesh & Routine-Automation** | Hoch | Abgeschlossen | Vollständige n8n-Anbindung, Webhook-Trigger, zeitgesteuerte Routine-Workflows (Morning-Briefing 07:30 Uhr Mo-Fr, Weekly Maintenance So 23:00 Uhr, stündlicher RSS-Scan) |
| **14** | **Telegram Voice-Pipeline (Voice-to-Text & Audio)** | Hoch | Abgeschlossen | Whisper-Transkription eingehender Telegram-Sprachnachrichten, Delegation an Ziel-Agenten, Sprachausgabe via edge-tts |
| **15** | **Kanban Qualitäts-Gate (4-Augen-Review vor Done)** | Hoch | Abgeschlossen | Automatischer Peer-Review-Prüfschritt vor Verschieben auf "Done", Prüfung auf Vollständigkeit & Belege, Re-Iterationsschleife |
| **16** | **Interaktive Showroom-Sandbox & Live-Runner** | Normal | Abgeschlossen | Sichere Ausführung von generiertem Code (Python-Datenanalyse, HTML/JS-Rechner) direkt im Showroom mit interaktiven Testdaten |
| **17** | **API-Tokens & Key-Sicherheit mit Scopes** | Hoch | Abgeschlossen | Feingranulare Scopes (`read:tasks`, `write:tasks`, `admin:system`), Token-Bucket Rate-Limits & Settings-Tab (`backend/api_auth.py`) |
| **18** | **E-Mail-Freigabe-Queue (4-Augen / HITL)** | Hoch | Abgeschlossen | Quarantäne-Warteschlange für E-Mail-Entwürfe autonomer Agenten vor Versand (`backend/email_draft_queue.py`) |
| **19** | **Kanban-Mehrfachaktionen & 10-Minuten-Undo** | Hoch | Abgeschlossen | Bulk-Move, Bulk-Delete, Bulk-Assignee mit persistenten DB-Snapshots und 10-Minuten Reversibilitäts-Puffer |
| **20** | **Agent-Scorecards & Personalakte (Obsidian-Sync)** | Hoch | Abgeschlossen | 8 standardisierte operative Leistungskennzahlen in der Personalakte mit bidirektionalem Sync in `Personalakten/<agent>.md` |
| **21** | **GoBD & ISO 27001 Revisions-Audit-Log** | Kritisch | Abgeschlossen | Lückenlose SHA-256 Hashkette (Merkle-Prinzip), Manipulationserkennung `/verify`, 1-Klick Prüfer-Export (JSON/CSV) |
| **22** | **Datenschutz-Routing (Zero Egress) & Lokales LLM** | Kritisch | Abgeschlossen | Automatisches Routing sensibler Daten an On-Premise LLMs (LM Studio/Ollama), EU-Fallback (Mistral AI), Footer-Statusleuchten `LOKAL`/`DSGVO` |
| **23** | **Dual-LLM Guard gegen Prompt Injection** | Kritisch | Abgeschlossen | 2-Stufen Quarantäne-Filterung externer Daten vor Übergabe an Werkzeug-Agenten & interaktiver `[T]`-Trusted Source Toggle |
| **24** | **Verschlüsselter Notfallzugang (Break-Glass Protocol)** | Kritisch | Abgeschlossen | Zero-Dependency PBKDF2-200k/HMAC verschlüsselter Tresor (`break_glass_vault.enc`) für Katastrophen-Wiederherstellung bei Betreiberausfall |
| **25** | **Operativer Operations-Kalender (ERP, Kanban & Agenten)** | Hoch | Abgeschlossen | Aggregations-API (`/api/v1/calendar/events`) + Enterprise-Kalender-Engine & UI (`backend/enterprise_calendar.py`, `static/js/enterprise_calendar_ui.js`) |
| **26** | **Autonomous Computer-Use & PbD (Demo-to-Skill)** | Kritisch | Abgeschlossen | Vormachen & Lernen per Bot-Screen, Ghost-Cursor Anti-Detection (Bézier-Pfade, Bounding-Box Jitter), SoM-Visual-Grounding und a11y Observation-Pruning |
| **27** | **MCTS Action Trajectories & Deep Reasoning Gate** | Mittel | Abgeschlossen | Optionale Monte-Carlo-Baumsuche in Autonomie-Settings zur Voraus-Simulation heikler Handlungsstränge vor Ausführung |
| **28** | **ERP-Modul zum vollwertigen Kernsystem ausbauen** | Kritisch | Abgeschlossen | EN 16931 / XRechnung-3.0-UBL-XML (`/xrechnung.xml`), ZUGFeRD-2.2 / Factur-X Hybrid-PDF (`/zugferd.pdf`), DATEV-EXTF-SKR03-CSV (`/export/datev.csv`), `leitweg_id`, atomare Lagerbestands-Abbuchung (`stock_deducted`) sowie Bank-Import (`CAMT.053` / `MT940` / `CSV`) & OPOS-Abgleich (`/api/erp/bank/*`) |
| **29** | **Visueller Formular- & Beleg-Editor (im ERP-Modul)** | Hoch | Abgeschlossen | WYSIWYG-/Block-Editor (`view_corporate.html`, `corporate_controller.js`) für 6 Belegtypen (Brief, Angebot, AB, Rechnung, Mahnung 1–3, NDA) inkl. Live-§ 14-UStG-Prüfung, Platzhaltern (`{{customer.*}}`/`{{doc.*}}`), DIN-5008-Falzmarken, Pure-Python EPC-QR GiroCode (`backend/qr_girocode.py`), Layout-Persistenz & direktem A4-PDF-Download (`/api/corporate/render-pdf`) |
| **30** | **Interaktiver Setup-Wizard & Installationsprogramm** | Kritisch | Abgeschlossen | Geführter First-Run-Installer (GUI & CLI) mit Abfrage von Firmendaten, Mandantenstamm, API-Keys, lokalen LLM-Pfaden, IMAP/SMTP und Telegram-Bot-Setup |
| **31** | **Vollständige Englische Version (Global Edition)** | Kritisch | Abgeschlossen | Durchgehende Übersetzung aller 70 Spezialisten-Profile (`SOUL.md`), 832 Prompt-Templates, 55 Boardroom-Frameworks, UI-Masken und Dokumentation auf Englisch |
| **32** | **Telegram-Kommunikation & Gateway-Härtung** | Hoch | Abgeschlossen | Konfliktfreies Session-Keying, Slash-Command-Routing, Inline-HITL-Buttons & Live-Status-Formatter (`backend/telegram_gateway_v2.py`) |
| **33** | **Watchdog & Internet-Radar 2.0** | Hoch | Abgeschlossen | Semantisches Relevanz-Scoring, SHA-256-Dubletten-Sperre & Auto-Fallback-Selbstheilung (`backend/watchdog_radar_v2.py`) |
| **34** | **Android-App (Mobile Command & Receipt Scanner)** | Mittel | Geplant | Mobile App für Direkt-Chat, Push-Freigaben (Approval Gates), Sprachnotizen und Kamera-Beleg-Scan direkt in die ERP-Buchhaltung |
| **35** | **GitHub-Präsentation & Public Launch Kit** | Hoch | Abgeschlossen | Zweisprachige Showcase-`README.md`, Architektur-Schaubilder, 90-Sekunden-Walkthrough-Video, One-Line-Installer und Security/License-Badges |
| **36** | **Ökosystem-Verzeichnisse & Community-Integrationen** | Hoch | Abgeschlossen | Offizielle Aufnahme in kuratierte Open-Source- und Self-Hosting-Kataloge (*Awesome-Selfhosted*, *Awesome-AI-Agents*, *Awesome-MCP-Servers*), Community-Blueprints & Integrations-Guides |
| **37** | **Zeiterfassung & Projekt-Nachkalkulation (Time-to-Invoice)** | Hoch | Abgeschlossen | Start/Stop-Timer in SQLite WAL, Soll-/Ist-Budgetabgleich & 1-Klick-ERP-Rechnungspositionen (`backend/time_tracking_invoice.py`) |
| **38** | **Automatischer Vertrags-, Fristen- & Abo-Wächter** | Hoch | Abgeschlossen | Kündigungs-Radar (30/14-Tage-Vorwarnung) & automatischer Kündigungsentwurf (`backend/contract_deadline_watcher.py`) |
| **39** | **Lokaler Meeting- & Call-Copilot (Audio → Protokoll + Tasks)** | Hoch | Abgeschlossen | Sprechergetrenntes Transkript, CRM-Aktennotiz & automatische Kanban-Action-Items (`backend/meeting_copilot.py`) |
| **40** | **Vertrags-Diff & Redlining-Ansicht (Alt gegen Neu)** | Mittel | Abgeschlossen | Klausel-Diff, XSS-sicheres HTML-Redlining & juristische Risiko-Erkennung (`backend/contract_diff_redliner.py`) |
| **41** | **Bi-direktionaler Kalender-Sync & Fokus-Blocker** | Hoch | Abgeschlossen | CalDAV/ICS-Parser/-Exporter, 2-Wege-Merge & Deep-Work-Fokus-Blocker (`backend/calendar_sync_blocker.py`) |
| **42** | **Geteilte Kunden- & Mandanten-Links (Mini-Freigabe-Portal)** | Mittel | Abgeschlossen | Passwortgeschützte PBKDF2-Links mit Ablaufzeit & direktem ERP-Statuswechsel (`backend/client_approval_portal.py`, `data/client_portal.db`) |
| **43** | **Multi-Mandanten-Umschalter (Holding / Operative GmbH / SPV)** | Hoch | Abgeschlossen | Topbar-Schnellumschalter (`tenant_switcher.js`), physisch isolierte SQLite-DBs je Mandant (`erp.db`, `kanban.db`, `crm.db`, `contracts.db`, `deals.db`) & getrennte Beleg-Nummernkreise |
| **44** | **Fertige „1-Click Business Playbooks“ (Workflow-Rezepte)** | Hoch | Abgeschlossen | 10 aktive Starter-Playbooks + 15 nachladbare Katalog-Rezepte (n8n-Prinzip), Playbook-Editor-CRUD & 1-Klick-Runner in Operations |
| **45** | **Research Lab zum Deep-Research-Labor ausbauen (Alpha → Produktiv)** | Hoch | Abgeschlossen | Mehrstufige Quellen-Triangulation (Trust-Tiers), PatSnap-/ArXiv-Support & Vault-Dossier-Export (`backend/deep_research_lab.py`) |
| **46** | **Open-Source Community-Hub, Sponsoring & Projekt-Portal** | Niedrig (Nachgelagert) | Zurückgestellt | Kanonische Projekt-Website (GitHub-Präsentation mit 11 Sprachen, GIFs & `FUNDING.yml` deckt den Launch bereits ab) |
| **47** | **„Zero-Install“ Read-Only Live-Demo-Modus (`ARCHON_DEMO_MODE`)** | Hoch | Abgeschlossen | Gehärteter öffentlicher Demo-Mandant („Mittelstand Muster GmbH“) mit gesperrten Schreib-/Shell-/Egress-Pfaden und deterministischen Muster-Debatten ohne Token-Kosten |
| **48** | **Archon OS als nativer MCP-Server (`/mcp` Gateway)** | Hoch | Abgeschlossen | Streamable HTTP (`/mcp`) + SSE Model-Context-Protocol-Endpunkt mit Scoped API-Keys (`read_only`, `kanban_rw`, `agent_execute`) & HITL-Freigabe-Gate für Claude Desktop, Cursor & VS Code |
| **49** | **EU AI Act Compliance-Engine & 1-Klick-Verfahrensdokumentation** | Kritisch | Abgeschlossen | Automatische Risikoklassifizierung je Spezialist (Anhang III / Art. 50) inkl. SOUL-SHA-256, KI-Kompetenznachweis-Log (Art. 4) und prüferfertiger GoBD- & EU-AI-Act-Verfahrensdokumentations-PDF-Export |
| **50** | **Agent-Eval- & Modell-Benchmark-Arena** | Hoch | Abgeschlossen | Lokales Referenz-Testdeck zum Qualitäts-, Latenz- und Kostenvergleich (`backend/agent_eval_arena.py`, `data/eval_arena.db`) |
| **51** | **Portabler „Squad-Blueprint“-Paketmanager (`.archonpack`)** | Hoch | Abgeschlossen | 1-Klick-Export & -Import kompletter Fachabteilungen (Agenten-Profile, 3-Stufen-`SOUL.md`, Fach-Skills, Boardroom-Frameworks, Prompt-Templates & n8n-Flows) mit SHA-256-Prüfung & Zip-Slip-Schutz |
| **52** | **Pre-Flight Cost-Estimator & „Shadow-Mode“** | Mittel | Abgeschlossen | Vorab-Token-/Kostenschätzung für ganze Ketten (`estimate_chain_cost`) sowie passiver Parallel-Trockenlauf-Tracker bis > 90 % Trefferquote |
| **53** | **„Epistemic Hygiene“-Wächter für den Obsidian-Vault** | Mittel | Abgeschlossen | Konsistenz-Scan über den Obsidian-Vault zur Erkennung widersprüchlicher Zahlen/Konditionen, veralteter Vertragsdaten & verwaister Notizen |
| **54** | **Voice-to-Workflow & 2-Stufen-KI-Spezifikations-Helfer (Editoren)** | Hoch | Abgeschlossen | 2-Stufen-Diktat-Analyse (Rückfragen bei Unklarheiten) & Playbook-Compiler (`backend/voice_to_workflow.py`) |
| **55** | **Enterprise-Kalender-Ausbau & Operations-Kalender UI-Überarbeitung (M25)** | Hoch | Abgeschlossen | Monats-/Wochen-/Tagesraster, Drag-&-Drop-Reschedule, Serientermine & Agenten-Ansicht (`backend/enterprise_calendar.py`, `static/js/enterprise_calendar_ui.js`) |
| **56** | **Archon OS Versions- & GitHub-Update-Badge (Sidebar unten links)** | Hoch | Abgeschlossen | Analog zur Hermes-Versionsanzeige unten links: Anzeige der aktuellen Archon-OS-Version (`archon_version_badge.js`) mit sofortigem Update-Badge bei neuem GitHub-Release/Commit und 1-Klick-Sprung in *Settings → System-Update* |
| **57** | **Frontend-Performance, Streaming-Bus & WCAG/i18n-Härtung** | Kritisch | Abgeschlossen | Lazy-Loading statt 20-View-Boot-Stau, lokales Tailwind-CSS (`tailwind.generated.css`), konsolidierter `archon:sse`-Bus, `lucide`-Scoping, `250ms` Search-Debounce + `AbortController`, XSS-Escaping, WCAG 2.2 AA (`modal_a11y.js` auf 39 Dialogen) & 11-Sprachen-Parität |
| **58** | **Backend-Performance, Async-Event-Loop & SQLite-Tuning** | Kritisch | Abgeschlossen | `asyncio.to_thread` für Docker/SQLite/File-I/O (`gateway`, `operations_org`, `chat`, `skills`, `orchestration`, `inbox_watcher`), zentraler `httpx.AsyncClient`-Pool, `ClosingConnection` + `WAL`/`cache_size=-32000`/Indizes, Mtime-Config-Cache & SQL-`WHERE` statt 72-DB-Vollscan |
| **59** | **Kern-Pipeline, Runtime-Crash-Fixes & Routing-Konsolidierung** | Kritisch | Abgeschlossen | Behebung aller `ImportError`/`AttributeError`/`NameError`-Crashes (`hr`, `operations_autonomy`, `operations_emails`, `operations_org`, `memory_consolidator`, `governance`), Auth-/Settings-Fix (`core_settings.py`, Auth-SSOT, 9x fail-open `_require_admin`), Delegations- & Status-Integrität, `agent_chat`-History, `AUTO_MODEL_MAP` & Entfernung von Fake-Telemetrie |
| **60** | **Aktive Security-Middleware & Recht/Compliance 2026** | Kritisch | Abgeschlossen | Pre-/Post-Dispatch-Verdrahtung (`pii_scrubber`, `secret_masker`, `egress_firewall`), Backend-Audio-Proxy (`aiAudio.ts`), DSGVO/UWG Opt-in & § 147 AO-Trennung, GoBD-Hashketten-Integrität (`audit_log`, `execution_receipt_ledger`, `erp_manager`), § 288 BGB-Mahnwesen mit echtem Versand, EU-AI-Act-Gates, § 5 DDG / § 25 TDDDG & `THIRD_PARTY_LICENSES.md` |
| **61** | **Legacy-Bereinigung: `evey-*`-Altlasten & CRM/PocketBase-Entkopplung** | Hoch | Abgeschlossen | Rückbau alter `evey-*`-Artefakte aus `guardian.py`, `index.html` & `~/.hermes/plugins/evey-*`, Deaktivierung/Optionalisierung von `crm:3005` & `pocketbase:8090` (`settings_state.py`, Health-Probes, `POCKETBASE_ENABLED=false`), Port-Abgleich (`hermes:8642/8644`) & `docker-compose.yml` Env-Passthrough |
| **62** | **Vorlagen in Operations überarbeiten** | Hoch | Abgeschlossen | Einheitliche Registry & Live-Vorschau-Renderer für Beleg-, Playbook- & Workflow-Vorlagen (`backend/operations_templates.py`) |
| **63** | **Linkes Menü (Sidebar) & untere linke Ecke modernisieren** | Hoch | Abgeschlossen | Einklappbare Sidebar-Sektionen mit Persistenz (`static/js/sidebar_v2.js`, eingebunden in `static/index.html`) |
| **64** | **Onboarding-Dialog (First-Run) überarbeiten & in Settings einbinden** | Hoch | Abgeschlossen | Direkter `Setup-Wizard`-Startbutton im Header des Settings-Modals (`static/views/system_settings_modal.html`) |
| **65** | **Design & Struktur der Systemeinstellungen (Settings) überarbeiten** | Hoch | Abgeschlossen | Gruppierte, umbrechende Tab-Leiste ohne Horizontal-Scroll-Zwang & einheitliche Content-Abstände (`static/views/system_settings_modal.html`) |
| **75** | **Strikte Rollen- & Tool-Isolation bei Agenten-Delegation (`hermes-teammates`-Pattern)** | Sehr hoch | Abgeschlossen | Harte Laufzeit-Durchsetzung von Profil-Toolsets und Modell-Routes pro delegierter Rolle (`backend/delegation_isolation.py`, `archon/core/delegation.py`) |
| **76** | **Verifizierte Kanban-Cards mit Token-Budget & Proof-Gate (`crew`-Pattern)** | Sehr hoch | Abgeschlossen | Token-Budget- & Proof-Command-Prüfung mit 1 Auto-Retry und HITL-Freigabe (`backend/kanban_verifier.py`, `backend/operations_api.py`, `POST /api/operations/kanban/tasks/{id}/hitl`) |
| **77** | **Agenten-Workflow-DAGs mit Fan-Out/Quorum & Resume (`hermes-workflows`-Pattern)** | Sehr hoch | Abgeschlossen | JSON-DAG-Workflow-Runner mit Fan-Out/Quorum, Human/Machine-Gates und Fingerprint-Replay-Skip-Resume (`backend/workflow_dag_runner.py`, E2E-Regressionstest `tests/test_workflow_dag_e2e.py`) |
| **78** | **Mission Control Kanban: Gantt-Timeline & Dependency-Graph (`kanban-gantt`-Pattern)** | Sehr hoch | Abgeschlossen | Hybrid-Gantt-Timeline & Longest-Path-Dependency-Graph auf Archons `tasks`-SQLite-DB (`backend/kanban_views.py`, `/api/operations/kanban/gantt|graph`, `static/js/kanban_gantt_graph.js`) |
| **79** | **Lokaler verschlüsselter Offline-Memory-Vault (`compartment` als Zero-Egress-Ergänzung)** | Sehr hoch | Abgeschlossen | AEAD-verschlüsselter lokaler Hybrid-Memory-Vault ohne Netzwerk/API-Key (`backend/offline_memory_vault.py`, `data/compartment_vault.db`) |
| **80** | **Hybrid-SOP-Runner: Script + Agenten-Urteil (`opensop`-Pattern)** | Hoch | Konsolidiert in M77/M102 | Archiviert nach `archive/20261121_legacy_workflows/hybrid_sop_runner.py` — vollständig abgelöst durch `backend/workflow_dag_runner.py` & `backend/workflow_templates.py` |
| **81** | **Cross-Model-Verifier & Test-Wächter (`shadow-army`-Pattern)** | Hoch | Abgeschlossen | Unabhängige Modell-Familien-Wahl & Diff-Assertion-Wächter vor Kanban-Done (`backend/kanban_verifier.py`: `cross_model_verify_card`) |
| **82** | **Subagenten- & Session-Receipts (`delegation-receipts` / `session-receipts`)** | Hoch | Abgeschlossen | Strukturierte Abschluss-Receipts & autarke Offline-HTML-Belegdokumente inkl. Retries (`backend/session_receipts.py`) |
| **83** | **Agenten-Flugschreiber & Guardrail-Backtester (`flightlog` / `policy-backtester`)** | Hoch | Abgeschlossen | Erkennung „grün fehlgeschlagener“ Runs & Policy-Replay gegen historische Tool-Calls (`backend/flightlog_backtester.py`) |
| **84** | **Prompt-Injection-Feuerübung (`injection-range`-Pattern)** | Hoch | Abgeschlossen | Automatisierte 8-Szenarien-Test-Suite inkl. Base64-, HTML- & Memory-Poisoning-Checks (`backend/injection_range.py`) |
| **85** | **Best-of-N Coding-Worktrees (`joust` / `multiverse`-Pattern)** | Mittel | Bereinigt (Triage C) | Als unverdrahtetes Stand-alone-Modul entfernt (Worktree-Isolation läuft nativ über Subagent-Workspaces) |
| **86** | **Quota-, Verification- & Quality-Escalation-Fallback im `AgentRouter` (`vibe-relay` / `calling-mom` / `nvidia-switchyard`)** | Hoch | Abgeschlossen | Quota-Threshold-Routing & Verification-Gated Escalation im `AgentRouter` (`backend/agent_router.py`: `select_quota_and_escalation_route`, `chat_with_verification_escalation`) |
| **87** | **Externe Fach-Connectoren (`inkly`, `local-business-leads`, `hermes-issue-sync`, `ghl-command`)** | Mittel | Bereinigt (Triage C) | Statische Mock-Adapter entfernt; echte Integrationen laufen über n8n/MCP & DocuSeal |
| **88** | **Optionale Spezial-Erweiterungen (`flota`/`own-compute`, `kujo-hermes`, `riah-swipe`, `manners-meter`)** | Niedrig | Bereinigt (Triage C) | Unverdrahtete Theater-Stubs am 21.11.2026 entfernt |
| **89** | **Information-Flow-Taint-Tracking & Session-Versiegelung (`airlock`-Pattern)** | Sehr hoch | Abgeschlossen | Session-Versiegelung nach untrusted Content + HITL-Freigabe-Gate für kritische Ausgänge (`backend/session_taint_guard.py`, `/api/v1/guardian/taint/approvals`) |
| **90** | **Signierte, ablaufende Tool-Warrants (`hermes-tenuo`-Pattern)** | Hoch | Abgeschlossen | HMAC-SHA256 signierte, zeitlich begrenzte Tool-Warrants mit Parameter-Constraints (`backend/tool_warrants.py`) |
| **91** | **Präzedenzfall-Gedächtnis für Kanban-Rückfragen (`precedent-log`-Pattern)** | Sehr hoch | Abgeschlossen | Strikt mandanten-/projektisoliertes Ruling-Gedächtnis (`backend/precedent_log.py`, `/api/operations/precedents`, Prompt-Injection in `operations_api.py`) |
| **92** | **Deterministischer Workflow-Freeze & Replay (`freeze` / `workflow-record`)** | Hoch | Konsolidiert in M105 | Abgelöst durch Event-Bus Replay (`replay_workflow_event` in `backend/workflow_scheduler.py`) & DAG Fingerprint-Skip |
| **93** | **Code-as-Orchestration & Tool-Output-Firewall (`codemode` / `toolaria`)** | Hoch | Abgeschlossen | Paralleler Batch-Tool-Orchestrator & Output-Kürzung vor Kontext-Injection (`backend/tool_output_firewall.py`) |
| **94** | **Lossless Session-DAG & Multi-Perspektiven-Research (`hermes-lcm-x` / `storm-fusion-research`)** | Hoch | Abgeschlossen | Verlustfreie SQLite-Session-Historie als Summary-DAG & STORM-Research-Panel (`backend/lossless_session_dag.py`) |
| **101** | **Passkey / WebAuthn HITL-Verifizierung (FIDO2)** | Kritisch | Abgeschlossen | Zweistufige kryptografische WebAuthn-Signaturprüfung (ES256/RS256, `rpIdHash`, `signCount`) für Zahlungen, Projektstarts & kritische Freigaben (`backend/passkey_hitl.py`) |
| **102** | **Visuelles Multi-Agent Workflow-Studio & DAG-Materializer** | Sehr hoch | Abgeschlossen | 20px-Grid-Editor, 52 Vorlagen, n8n-Import & direkte E2E-Anbindung an `workflow_dag_runner.py` (`backend/workflow_templates.py`) |
| **103** | **Treasury-, Wallet- & Passkey-gesichertes Zahlungs-Cockpit** | Hoch | Abgeschlossen | Liquiditätsübersicht, SHA-256 Spend-Ledger & Passkey-HITL-Freigabe (`backend/treasury_engine.py`) |
| **104** | **Operations-Kalender 2.0 & Event-Bus-Kopplung** | Hoch | Abgeschlossen | Eigene Kalender-Engine mit 6 Farblayern, ICS/CalDAV-Sync & Event-Bus-Triggern (`backend/operations_calendar.py`) |
| **105** | **Event-Bus Governance (Trigger-Matrix, Rate-Limits, Replay)** | Hoch | Abgeschlossen | Policy-Matrix (`allow`/`require_hitl`/`deny`), Loop-Schutz & Dead-Letter-Replay (`backend/workflow_scheduler.py`) |
| **106** | **SQLite-Datenbank-Konsolidierung (`28 → 3` Domänen-DBs)** | Kritisch | Abgeschlossen | Zusammenführung von 28 SQLite-Dateien in `ops.db`, `business.db` & `memory.db` inkl. Mandanten- & Backup-Integration (`backend/db_consolidation.py`, `backend/db_paths.py`) |
| **107** | **Multi-Channel Content-Maschine v1 & v2 (LinkedIn, YouTube, TikTok, X)** | Sehr hoch | Abgeschlossen | Repurposing-DAG, Anti-AI-Slop-Quality-Gate, Quellen-Ingestion (URL/Obsidian/Transkript), 9:16-Clip-Matrix & Publishing-Bridge (`backend/content_machine.py`) |
| **108** | **Next.js 16 UI-Konsolidierung auf Archon FastAPI** | Hoch | Abgeschlossen | Direkter FastAPI-Proxy (`/api/archon/[...path]`) ohne PocketBase-Zwang für `/content-studio`, `/workflows` und `/cockpit` (`frontend/`) |
| **109** | **Code Mode (M109a Deferred Discovery → M109b Isolierte Sandbox)** | Hoch | Geplant | Token-Reduktion für ~200+ Endpunkte: erst Deferred Catalog (`search`/`describe`/`call` über `tool_runtime.py`), danach optional isolierte Sandbox mit Capability-Broker |
| **110** | **Execution Hardening: Idempotency, Effect-Ledger, Leases & Plan-Validator** | Sehr hoch | Abgeschlossen (v0.5.7) | Umgesetzt in `event_mesh.py` (Effect-Ledger + Outbox), `deadlock_supervisor.py` (Leases/Heartbeats) und `workflow_dag_runner.py` (Plan-Validator, `replan_count`=2) |
| **111** | **Isolation & Resilience: Bulkheads, Tool-Output-Caps, Circuit-Breaker & Queues** | Hoch | Geplant | Getrennte Scheduling-Klassen (Chat vs. Background vs. DAG), Tool-Output-Größenlimits vor Kontext-Injektion, Provider-Circuit-Breaker & Backpressure |
| **112** | **OTel GenAI Tracing & Trace-to-Eval-Pipeline** | Hoch | Geplant | Durchgängige `trace_id` (Gateway → `LLMKernel` → Tools → DAG) mit PII-Redaktion, Kosten/Latenz und 1-Klick-Export in `backend/eval_gates.py` |
| **113** | **Content-Maschine Safety & Lifecycle: Brand-Safety-Pass, Kill-Switch & Asset-Retirement** | Sehr hoch | Geplant | Dedizierter Legal/Brand-Safety-Second-Pass vor Publish, zentraler Kill-Switch + Plattform-Caps, Asset-Rückzug/Update, 30-Tage-Derivate & Crop-vs-Gen |
| **114** | **Multi-Agent-Orchestrierung & Content-Maschine: Roadmap-Abschluss (28 Punkte)** | Sehr hoch | Abgeschlossen | Durable Kernel, CAS-Leases, A2A-Envelope, Shared Queue, Supervisor-Rollover, Memory-Scope, Event-Push, Cancellation, Consensus, Eval-Gates, Handoff, CI-SSOT sowie Publish-Sweep, HITL, Research-Dossier, Quality-, Fact-Check-, Plagiat-/Rechte- und SEO-Gates, A/B, Kanalvalidierung, Editorial-Rollen, Skills-Injektion, GEO, Frontend-Flow und SSRF (`docs/system/MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md`) |

---

## Detaillierte Arbeitspakete

### Meilenstein 0: AI Boardroom finalisieren (Abgeschlossen)
- **UI & Ergonomie:** 3-Tab-Architektur (Übersicht, Debatte, Live), Reset-Logik für Standard-Slots, Markdown-Export.
- **Backend & Streaming:** Client-Disconnect-Abbruch via SSE, Bereinigung von Platzhaltermodellen auf `deepseek-chat`.
- **Dokumenten-Pipeline:** Automatisches Extrahieren von PDF- und Textinhalten per Backend (`/api/boardroom/parse-attachment` via `pypdf`).

### Meilenstein 1: Updatesystem erarbeiten (Abgeschlossen)
- **Sync & Release-Lifecycle:** Automatisierte Update-Pipeline zwischen Entwicklungsrechner und Homeserver (`backend/system_updater.py`).
- **In-App 1-Klick-Update:** Eigener Tab *System-Update & Server-Sync* in den Systemeinstellungen mit Status-Anzeige, Commit-Differenz und Installations-Button.
- **Datenintegrität & Snapshots:** Konsistente Online-Snapshots aller Datenbanken (`ops.db`, `business.db`, `memory.db`) und Konfigurationen vor jedem Git-Pull.
- **Rollback-Fähigkeit:** Snapshots können mit 1 Klick im Web-UI oder per CLI wiederhergestellt werden.
- **Server-Skripte:** Bereitstellung von 1-Klick-Host-Skripten (`scripts/update_archon.bat` für Windows, `scripts/update_archon.sh` für Linux/Ubuntu).

### Meilenstein 2: Steuerapp für Android
- **Architektur-Evaluation:** Vergleich zwischen installierbarer Progressive Web App (PWA) mit Service Workern vs. schlanker nativer Android-App.
- **Remote-Konnektivität:** Sicherer Zugriff ohne statische IP (WireGuard / Tailscale / Cloudflare Tunnel / Reverse-Proxy mit TLS).
- **Benachrichtigungen:** Webhooks und Push-Notifications für dringende Agenten-Events und manuelle Freigaben (HITL).

### Meilenstein 3: Multilingualität (i18n)
- **Frontend-Lokalisierung:** Trennung von UI-Texten in strukturierte Lokalisierungsdateien (JSON/YAML).
- **Prompt-Lokalisierung:** Sprachunabhängige oder zweisprachig optimierte System-Prompts für alle 56 Agenten-Rollen.
- **Dynamische Erkennung:** Automatische Spracherkennung der Benutzereingaben mit adäquater Antwortsprache.

### Meilenstein 4: Multi-User-Architektur (Abgeschlossen)
- **Identitäts- & Sitzungsmanagement:** Benutzerkonten mit sicherer Authentifizierung (PBKDF2-HMAC-SHA256, 100k Runden, 30-Tage Session-Tokens).
- **Rechte & Rollen (RBAC):** 3-Stufen-Modell (Admin, Operator, Viewer) mit Schutz des letzten Administrators.
- **UI-Integration:** Profil-Badge in der Seitenleiste, interaktiver Benutzer- und Rollen-Manager im System Control Center.

### Meilenstein 5: Funktionserweiterung & Pluginsystem (Abgeschlossen)
- **Plugin-Architektur:** Zentraler `PluginManager` (`backend/plugin_manager.py`) mit standardisierten Manifesten (`plugin.json`), dynamischem Import via `importlib` und Exception-Isolation.
- **Lifecycle- & Filter-Hooks:** Standard-Hooks `on_load`, `on_enable`, `on_disable`, `before_tool_execute`, `after_tool_execute`, `on_message_received`, `on_task_completed`.
- **Sicherheits- & Tool-Auditing:** Hook-Pipeline blockiert destruktive Befehle (`rm -rf`, Directory Traversal) und maskiert Secrets in Ausgaben.
- **REST-API & UI-Integration:** `/api/v1/plugins` (Auflisten, Umschalten, Neuladen, Konfigurieren) nahtlos in die Settings-Registry (Tab PLUGINS) integriert.
- **3 Produktions-Plugins:**
  1. `plugins/system_metrics/`: Exportiert das LLM-Tool `get_system_telemetry` für Host- und Docker-Status.
  2. `plugins/security_audit_hook/`: Interzeptiert destruktive Shell-Kommandos und schützt sensible Token.
  3. `plugins/cost_guard/`: Überwacht Token-Verbrauch und Tagesbudget mit Werkzeug `check_token_budget`.

### Meilenstein 6: Designkonzept modernisieren
- **Design Tokens:** Vereinheitlichung von Farbwerten, Abständen, Typografie und Schatten in einem zentralen Theme.
- **Visuelle Hierarchie:** Reduktion von visueller Überladung, klare Gruppierung von Bedienelementen und Statusanzeigen.
- **Responsive Anpassung:** Optimierte Skalierung für Tablets und Mobilgeräte als Vorstufe zur Android-Steuerung.

---

### Meilenstein 7: LinkedIn-Import im CRM (Bugfix & Deduplizierung)
- **Fehlerursache:** Erneute Duplizierung aller importierten Nachrichten in der CRM-/PocketBase-Datenbank.
- **Import-Härtung:** Implementierung eines robusten Deduplizierungs-Mechanismus in `scripts/import_linkedin_archive.py` (Kombination aus Message-ID, Sender, Empfänger, Timestamp und SHA-256-Body-Hash).
- **Bereinigung:** Bereitstellung eines Cleanup-Skripts zur Identifizierung und sicheren Entfernung der bestehenden Duplikate in den Message-Tabellen.

### Meilenstein 8: Obere Icons prüfen & korrigieren
- **Icon-Audit:** Prüfung aller Icons in den oberen Navigationsleisten und Sub-Tabs (`static/index.html`).
- **Fehlerbehebung:** Beseitigung redundanter/doppelter Icons; Ersetzung des falschen Kanban-Icons durch das korrekte Lucide-Symbol.
- **Semantische Konsistenz:** Einheitliche Ikonografie über alle Fachmodule (Operations, Kader, Mastermind, CRM, Cockpit).

### Meilenstein 9: Redesign der oberen Leiste & Avatar-Überlappung
- **Design-Vorlage:** Ausrichtung aller Modulkopfzeilen am Standard von `AI Mastermind · Übersicht` (Banner-Kachel, Status-Pill, Kachel-Subtabs, Help-Button).
- **Agenten-Kader Avatar-Überlappung:** Technische Prüfung und CSS-Gestaltung, ob und wie der Avatar im Agentenkader vertikal über den Kachelrand hinaus überlappen kann (Negative Margins, `overflow: visible`, z-index Hierarchie) für eine plastische, hochwertige Optik.

### Meilenstein 10: Eingang (Inbox) Re-Architektur & Funktionsprüfung
- **Funktionsdiagnose:** End-to-End-Audit aller Intake- und Triage-Abläufe.
- **Header-Neuordnung:** Platzierung der Suchleiste prominent direkt unter dem Header, flankiert von Filter-, Markierungs- und Tagging-Tools.
- **Linke Leiste Umbau:** Neukonzeption des linken Eingangsbalkens als fokussierte Schnellansicht für alle markierten ("Starred") oder angepinnten Vorgänge ("Wichtiges / Wiedervorlage").

### Meilenstein 11: Tokenguard Zeitraum-Skalierungsleiste
- **Interaktiver Filter:** Einbau einer Zeitleiste über dem Chart (`guardian-trend-canvas`) in `static/js/guardian.js` und `static/index.html`.
- **Zeitbereiche:** Umschaltung zwischen 24 Stunden, 7 Tagen, 30 Tagen, 90 Tagen und All-Time.
- **Dynamische Skalierung:** Automatische Neuberechnung der Verbrauchsdaten, Token-Kosten und Trendlinien bei Zeitraum-Wechsel.

### Meilenstein 12: Informationsquellen-Strategie & Vertrauens-Registry (Abgeschlossen)
- **Kuratierter Quellen-Pool (15 Quellen):** Strukturierte Unterteilung in 4 Kernbereiche:
  1. *Investitionen & Geopolitik (High Impact):* Bundesregierung (Kabinett/Gipfel), BMWK (Industrieförderung/Subventionen), DIHK (Außenwirtschaft/Freihandelsabkommen), GTAI (Germany Trade & Invest), High-Impact Investitions-Radar (Invest in Germany Summit, Deutschlandfonds).
  2. *Wirtschaft & Finanzen (Makroökonomie):* Handelsblatt Top-Themen & Politik/Ökonomie, Deutsche Bundesbank (Geldpolitik/Monatsberichte), Reuters Business, Finanzen & Börse Radar (DAX/Investorenströme).
  3. *Technologie & KI:* Heise Online (IT-Leitmedium DACH), TechCrunch (Startups/Venture), ArXiv AI (Wissenschaftliche CS-Preprints).
  4. *Politik & Wissenschaft:* Tagesschau (Öffentlich-rechtliche Faktenbasis), Spektrum der Wissenschaft.
- **Trust-Tiers & Gewichtung in der Triangulation:**
  - *Tier 1 (Amtlich & Primärquelle, Gewicht 1.0):* Bundesregierung, BMWK, Bundesbank, DIHK, GTAI.
  - *Tier 2 (Etabliertes Leitmedium, Gewicht 0.9):* Handelsblatt, Tagesschau, Reuters, Heise, Spektrum, TechCrunch.
  - *Tier 3 (Wissenschaftliche Evidenz, Gewicht 0.85):* ArXiv CS/AI.
  - *Tier 4 (Markt- & Börsendaten, Gewicht 0.8):* Finanzen.net, Börse Online.
  - *Tier 5 (KI-Hinweis, Gewicht 0.5):* Grokipedia, Web-Snippets (Gilt nur als Hinweis, zählt nicht als unabhängige Quelle in der Triangulation).
- **Zitations-Standard (0-Halluzination):** Verpflichtende Markdown-Hyperlinks `[Quelle: Name](URL)` im Text sowie abschließende Triangulations- und Quellenverzeichnisse in allen generierten Dossiers, LinkedIn-Posts und Strategievorlagen.
- **System-Integration:** Vollständig hinterlegt in `backend/research_sources.py`, `research_engine.py`, `settings.json` (Watchdog Radar Targets & 16 High-Impact Keywords) sowie im Research Lab UI (`static/views/view_research.html`, `static/js/research_lab.js`) und via API `GET /api/v1/research/sources`.

---

### Meilenstein 13: n8n Workflow-Mesh & Routine-Automation (Abgeschlossen)
- **n8n Konnektivität & Health-Check:** Vollständige Kopplung von Archon OS an die containerisierte n8n-Instanz (Port 5678, `agentic_mesh` Netzwerk) über `scripts/mcp_n8n_driver.py` und native Webhook-Endpoints.
- **Aktive Routine-Workflows:**
  1. *Archon Morning-Briefing Routine* (Schedule: Werktags 07:30 Uhr & Webhook `POST /webhook/archon-morning-briefing`): Ruft `/api/system/standup/run` auf, speichert Briefing im Obsidian Vault und sendet es via `POST /api/telegram/send` an den Nutzer.
  2. *Archon Weekly Maintenance & System-Audit* (Schedule: Sonntags 23:00 Uhr & Webhook `POST /webhook/archon-weekly-audit`): Führt atomare SQLite-Backups aus (`/api/system/backup-db`) und prüft den System-Health-Score.
  3. *Archon RSS & News Watchdog Routine* (Schedule: Stündlich & Webhook `POST /webhook/archon-rss-watchdog`): Führt automatisierte Scans der konfigurierten RSS-Feeds (z. B. WinFuture) und Web-Diff-Ziele durch.
- **Funktions-Webhooks & Treiber:** 5 weitere Spezial-Workflows für Web-Extraktion, Multi-Channel-Dispatching, Dokumenten-Rendering, Feed-Suche und CRM-Sync vollständig in n8n aktiviert und verifiziert.

### Meilenstein 14: Telegram Voice-Pipeline (Sprachnachrichten & Audio-Antwort)
- **Voice-to-Text Ingestion:** Empfang von Telegram-Sprachnachrichten (`.ogg`/Opus) über das Hermes-Gateway und Transkription via Whisper (lokal oder API).
- **Intelligente Intent-Erkennung & Routing:** Zuordnung der transkribierten Sprachnachricht an den gewünschten Agenten (z. B. `/robert` oder Erkennung des Rufnamens im Fließtext).
- **Optionale Audio-Antwort (TTS):** Generierung kompakter Sprachnotizen als Telegram-Audioblase (z. B. via Edge-TTS oder Piper) für unterwegs.

### Meilenstein 15: Kanban Qualitäts-Gate (4-Augen-Review vor Task-Abschluss)
- **Peer-Review Workflow:** Automatische Abfang-Logik beim Übergang eines Tasks in den Status `done`.
- **Reviewer-Delegation:** Zuweisung an eine definierte Prüf-Rolle (z. B. Kritiker, Faktenprüfer oder Katharina Völk für Compliance/Stil).
- **Abnahmekriterien & Re-Iteration:** Automatischer Abgleich des Arbeitsergebnisses gegen Aufgabenstellung und Mindeststandards. Bei Mängeln Rückversetzung auf `in_progress` mit konkretem Feedback; bei Freigabe finaler Abschluss.

### Meilenstein 16: Interaktive Showroom-Sandbox & Live-Runner
- **Ausführungsumgebung:** Einbindung einer sicheren Code-Sandbox im Showroom (Browser-basiert via Pyodide oder flüchtiger Docker-Subcontainer).
- **Interaktive Vorschau:** Direkte Ausführung von generierten Python-Datenanalysen, Tabellen-Kalkulationen oder HTML5/JS-Rechnern mit dynamischen Eingabefeldern.
- **Artefakt-Export:** Bereitstellung von Download- und Teilen-Optionen für validierte Code-Artefakte.

---

### Meilenstein 17: API-Tokens & Key-Sicherheit mit Scopes (Abgeschlossen)
- **Feingranulare Scopes:** API-Keys mit Rechten (`read:tasks`, `write:tasks`, `execute:agent`, `admin:system`).
- **Token-Bucket Rate-Limiting:** Konfigurierbares Sliding-Window Rate-Limiting zum Schutz vor DoS (`backend/api_auth.py`).
- **Settings-Tab:** Verwaltung und Revocation von API-Schlüsseln im System Control Center.

### Meilenstein 18: E-Mail-Freigabe-Queue (Abgeschlossen)
- **HITL-Quarantäne:** Ausgehende E-Mail-Entwürfe autonomer Agenten werden in `pending_approval` gehalten (`backend/email_draft_queue.py`).
- **Postfach-Integration:** Eigener Reiter *Entwürfe & Freigaben* im Postfach mit Freigabe-, Überarbeitungs- und Löschfunktion.

### Meilenstein 19: Kanban-Mehrfachaktionen & 10-Minuten-Undo (Abgeschlossen)
- **Massenoperationen:** Checkbox-Auswahl für Bulk-Move, Bulk-Delete und Bulk-Assignee im Kanban-Board (`backend/operations_api.py`).
- **Reversibilität:** Automatischer SQLite-Snapshot vor jeder Sammeloperation und 10-Minuten-Undo-Toast zur vollständigen Wiederherstellung.

### Meilenstein 20: Agent-Scorecards & Personalakte (Abgeschlossen)
- **8 Operative Kennzahlen:** Erfolgsrate, Token-Verbrauch, Kosten, Latenz, Tool-Zuverlässigkeit, HITL-Feedback, Pünktlichkeit, Aufgabenvolumen (`backend/agent_scorecards.py`).
- **Obsidian-Synchronisation:** Nahtloser Abgleich mit Notizen und Beurteilungen in `Personalakten/<agent_id>.md`.

### Meilenstein 21: Revisionssicheres GoBD / ISO 27001 Audit-Log (Abgeschlossen)
- **SHA-256 Hashkette:** Unveränderliche Merkle-Verkettung aller System-, Finanz- und Freigabetransaktionen (`backend/audit_log.py`).
- **Integritätsprüfung & Export:** REST-Endpunkt `/api/governance/audit-log/verify` zur Manipulationserkennung und 1-Klick Prüfbericht-Export als JSON/CSV.

### Meilenstein 22: Datenschutz-Routing (Zero Egress) & Lokales LLM (Abgeschlossen)
- **Zero Egress:** Sensible Datenkategorien (Finanzen, Verträge, CRM, HR) werden zwingend an lokale LLMs (LM Studio/Ollama) oder EU-Mistral geroutet (`backend/privacy_router.py`).
- **DSGVO-Statusleuchten:** Permanente visuelle Indikatoren (`LOKAL` & `DSGVO`) im Footer der Seitenleiste.

### Meilenstein 23: Dual-LLM Guard gegen Prompt Injection (Abgeschlossen)
- **2-Stufen Quarantäne:** Fremddaten durchlaufen Stufe 1 (unprivilegiertes Modell ohne Tools) vor Übergabe an Stufe 2 (Werkzeug-Agent) (`backend/dual_llm_sanitizer.py`).
- **`[T]`-Trusted Source Badges:** Interaktives Whitelisting vertrauenswürdiger Absender in der Inbox und im Master Chat.

### Meilenstein 24: Verschlüsselter Notfallzugang (Break-Glass Protocol) (Abgeschlossen)
- **Katastrophen-Wiederherstellung:** Zero-Dependency Verschlüsselung (PBKDF2-200k, HMAC-SHA256, Keystream) via `scripts/break_glass_recovery.py`.
- **Notfall-Kit:** Bereitstellung von `data/backups/break_glass_vault.enc` und ausdruckbarer Anleitung `data/backups/BREAK_GLASS_RECOVERY_KIT.md`.

### Meilenstein 25: Operativer Operations-Kalender (Geplant)
- **Aggregierte Zeitprojektion:** Tages-, Wochen- und Monatsraster direkt in Operations.
- **Automatische Datenquellen:** Kanban-Deadlines (`due_date`), ERP-Vertragsfristen & Zahlungsziele, n8n/Hintergrund-Fahrplan (Wann startet welcher Agenten-Job?).
- **Reallife-Termine & Kontaktpflege:** Integration wichtiger Termine und Geburtstage aus dem CRM für automatisierte Gratulationen und Beziehungspflege.
- **Externer Sync:** Optionale ICS/CalDAV-Synchronisation mit Mobilgeräten.

### Meilenstein 26: Autonomous Computer-Use Engine & PbD (Abgeschlossen)
- **Programming by Demonstration (PbD):** Aufnahme-Button im Bot-Screen (`[ 🔴 Vormachen & Aufnehmen ]`) zeichnet Bediener-Aktionen und Sprach-/Absichts-Kommentare live auf und synthetisiert sie vollautomatisch in wiederverwendbare Skills (`.agents/skills/<name>/SKILL.md`) und Python-Automationsskripte (`scripts/dynamic_tools/`).
- **Anti-Bot Trajektorien (Ghost-Cursor):** Biomechanische Bézier-Trajektorien (Cubic Bézier mit Fitts's Law Verzögerung), Gauss-verteilter Bounding-Box Jitter (gegen starre Pixelklicks) und menschliche Tasten-Kadenzen (50-180ms variierend) zur Umgehung von Anti-Bot WAFs und Fingerprinting.
- **Visual Grounding & a11y Observation Pruning:** Kompakte Extraktion des semantischen Accessibility-Trees mit bis zu 85-92% Token-Reduktion und Chat-/Screen-Toggle (`[ 🌲 a11y Pruning: Aktiv ]`).

### Meilenstein 27: MCTS & Heuristik-Tree-Search (Abgeschlossen)
- **Gedankliche Voraus-Simulation:** Monte-Carlo-Baumsuche (`backend/mcts_engine.py`) mit UCB1-Exploration, Risiko-Penalties und Rollout-Simulation für hochriskante Aufgaben vor der ersten Tool-Ausführung.
- **Konfigurierbar:** Verwaltet in `settings.json` (`mcts_reasoning.enabled: false` als Standard) zur Schonung von Token-Credits bei Routine-Tasks.

---

### Meilenstein 28: ERP-Modul zum vollwertigen Kernsystem ausbauen (Abgeschlossen – Kritisch)
- **EN 16931 / XRechnung 3.0 E-Rechnung (UBL 2.1 XML):** Standardkonformer XML-Export (`/api/erp/documents/{doc_id}/xrechnung.xml` + `XRechnung XML`-Button in Operations ERP) inkl. `leitweg_id` (`crm_entities`), Seller-/Buyer-Stammdaten, USt-Kategorien (`S`/`AE`/`K`/`E`/`Z`) & IBAN/BIC-Zahlungsdaten.
- **ZUGFeRD 2.2 / Factur-X Hybrid-PDF (`backend/erp_zugferd_pdf.py`):** Abhängigkeitsfreier DIN-A4-PDF-Generator (`/api/erp/documents/{doc_id}/zugferd.pdf` + `ZUGFeRD PDF`-Button) mit eingebetteter `factur-x.xml` (`/EmbeddedFiles`, `/AF`, `/AFRelationship /Alternative`) und XMP `fx:ConformanceLevel EN 16931`-Metadaten.
- **DATEV EXTF Buchungsstapel CSV (SKR03):** Semikolon-CSV-Export mit UTF-8-BOM (`/api/erp/export/datev.csv` + `DATEV EXTF`-Button) inkl. SKR03-Erlöskonten (`8400`/`8300`/`8125`/`8337`), BU-Schlüssel (`3`/`2`), `DDMM`-Belegdatum & CSV-Formel-Injection-Schutz.
- **Atomare Lagerbestands-Führung (`stock_qty`):** Festschreiben einer Rechnung (`booked`/`paid`) bucht Lagerartikel (`track_inventory = 1`) einmalig ab (`stock_deducted = 1`); Storno (`cancelled`) bucht den Bestand atomar zurück.
- **Bankkonten-Import & OPOS-Zahlungsabgleich (`erp_bank_transactions`):** Parser & APIs für ISO 20022 `CAMT.053` XML (mit `<!DOCTYPE`/`<!ENTITY`-XXE-Schutz), SWIFT `MT940` (`.sta`) und Bank-`CSV` (`/api/erp/bank/import`, `/api/erp/bank/transactions`, `/api/erp/bank/transactions/{tx_id}/match`) inkl. SHA-256-Deduplizierung, Konfidenz-Matching gegen offene Ausgangsrechnungen (`auto_mark_paid`) und modalem OPOS-Dialog (`Bank-Import & OPOS`). *(Hinweis: Echtzeit-HBCI/FinTS/PSD2-Online-Abruf bleibt als späteres Gateway-Plugin optional.)*

### Meilenstein 29: Visueller Formular- & Beleg-Editor im ERP-Modul (Abgeschlossen – Hoch)
- **Interaktiver Vorlagen-Baukasten (`corporate_manager.py`, `view_corporate.html`, `corporate_controller.js`):** Einheitlicher visueller Editor für Geschäftsbriefe (DIN 5008 mit optionalen Falzmarken 105/148,5/210 mm), Angebote, Auftragsbestätigungen, Ausgangsrechnungen, Mahnungen (Stufen 1–3 nach § 286/§ 288 BGB) und NDAs — inkl. 1-Klick-Absprung `Beleg-Editor` direkt aus ERP-Belegen (`erp_studio.js`).
- **Dynamische Datenbindung, Platzhalter & § 14 UStG-Check:** Mandanten- und Beleg-Persistenz (`GET/POST /api/corporate/template-layout`), Live-ERP-Belegverknüpfung, sichere `{{company.*}}` / `{{customer.*}}` / `{{doc.*}}`-Platzhalter sowie automatische § 14 Abs. 4 UStG Live-Compliance-Prüfung (`validate_ustg_compliance()`).
- **Pure-Python GiroCode EPC-QR & A4-PDF-Export:** Abhängigkeitsfreier ISO-18004-QR-Matrix-Generator (`backend/qr_girocode.py`) als gestochen scharfes Vektor-SVG in Rechnungen/Mahnungen sowie echter PDF-Download via `POST /api/corporate/render-pdf` (`build_corporate_template_pdf`).

### Meilenstein 30: Interaktiver Setup-Wizard & Installationsprogramm (Abgeschlossen)
- **Geführter 4-Schritte-Web-Wizard (`/onboarding` & Setup-Modal):**
  1. *Unternehmensstamm & Mandant:* Firmenname, Branche, Rechtsform, Standardwährung (`EUR`/`USD`/`CHF`), Steuernummer und Admin-E-Mail.
  2. *LLM- & Provider-Orchestrierung:* Schnellauswahl & API-Key-Validierung für OpenRouter, Hermes-Local, vLLM, Ollama und LM Studio mit Live-Ping-Test.
  3. *Kommunikation & Kanäle:* SMTP/IMAP-Postfächer für Auto-E-Mail-Sync und Telegram-Bot-Token mit Sofort-Validierung (`getMe`).
  4. *Domänen-Auswahl:* Auswahl, welche der 8 Fachdomänen (70 Spezialisten) sofort aktiv geschaltet werden sollen.

### Meilenstein 31: Vollständige Englische Version – Global Release Edition (Abgeschlossen)
- **Systemweite Zweisprachigkeit (DE / EN):** Vollständige Übersetzung aller 70 Spezialisten-Profile (`SOUL_COMPACT.md`, `SOUL_PRO.md`, `SOUL_FULL.md`), der 832 Prompt-Studio-Vorlagen und der 55 Boardroom-Frameworks ins Englische.
- **Internationale Rechts- & Steuer-Adaption:** Umschaltbare Normen-Profile für den englischsprachigen Raum (z. B. US-GAAP/IFRS, GDPR/CCPA, FDA/OSHA statt reinem HGB/BauGB/StBerG).
- **Englisches Systemhandbuch:** Vollständige englische Ausgabe des 218-seitigen Archon-OS-Handbuchs (`ARCHON_OS_SYSTEM_MANUAL_2026_EN.docx` / PDF).

### Meilenstein 32: Telegram-Kommunikation & Gateway-Härtung (Geplant – Hoch)
- **Stabiles Session- & Lock-Management:** Beseitigung von `gateway.lock`-Blockaden und Session-Drifts zwischen Mobilgerät, Hermes-Core und Web-UI.
- **Interaktive Inline-Keyboards:** 1-Klick-Buttons direkt in Telegram für `Approval Gates` (*„Freigeben“ / „Ablehnen“ / „Überarbeiten“*), Agenten-Wechsel und Rückfragen.
- **Zwischenstand-Streaming:** Kompakte Status-Updates in Telegram bei mehrminütigen Recherchen oder Boardroom-Debatten statt stummer Wartezeit.

### Meilenstein 33: Watchdog & Internet-Radar 2.0 (Geplant – Hoch)
- **Semantischer Relevanz-Filter:** Zweistufiges Scoring eingehender News/RSS-Treffer anhand des eigenen Unternehmensprofils (Filterung von Clickbait und Duplikaten).
- **Quellen-Selbstheilung & Health-Monitor:** Automatische Erkennung ausgefallener RSS-Feeds oder geänderter Website-Selektoren mit Meldung im Dashboard.
- **Actionable Triggers:** Direkte Umwandlung hochrelevanter Treffer (z. B. neue KfW-Förderbedingung, Gesetzesänderung, Wettbewerber-Preisänderung) in einen vorbereiteten Kanban-Task für den zuständigen Spezialisten.

### Meilenstein 34: Native Android-App & Mobile Command Center (Geplant – Mittel)
- **Mobiler Begleiter für Unterwegs:** Dedizierte Android-App (Kotlin/Capacitor-PWA) mit biometrischer Entsperrung (Fingerabdruck/Face-Unlock).
- **Kamera-Belegscanner & Sprach-First:** Direktes Fotografieren von Tank-/Bewirtungsbelegen mit sofortiger Übergabe an die ERP-Beleg-OCR sowie Push-to-Talk-Sprachbefehle an alle 70 Agenten.
- **Echtzeit-Push für HITL-Gates:** Sofortige Push-Benachrichtigung, wenn ein Agent auf eine kritische Freigabe (Zahlung, E-Mail, Vertragsentwurf) wartet.

### Meilenstein 35: GitHub-Präsentation & Public Launch Kit (Abgeschlossen)
- **High-Impact Repository-Auftritt:** Zweigeteilte `README.md` (Englisch als Hauptsprache für globale Reichweite + Deutsch-Link) mit interaktiver Architektur-Grafik, Vergleichstabelle (*Single Chatbot vs. Super-Agent vs. Archon OS*) und 3-Befehle-Schnellstart.
- **Visuelle Produkt-Tour:** Eingebettete kurze GIF-/MP4-Demos für die 4 Kern-Highlights: *70-Agenten-Kader mit 3-Stufen-SOUL*, *AI Boardroom Debatte*, *ERP/CRM mit HITL-Freigabe* und *Obsidian Second Brain*.

### Meilenstein 36: Ökosystem-Verzeichnisse & Community-Integrationen (Abgeschlossen)
- **Kuratierte Open-Source-Kataloge:** Strukturierte Bereitstellung von Metadaten, Self-Hosting-Manifesten und Architektur-Steckbriefen für *Awesome-Selfhosted*, *Awesome-AI-Agents* und *Awesome-MCP-Servers*.
- **Interoperabilitäts- & Migrations-Guides:** Praxisnahe Vergleichs- und Umstiegsdokumentation für Teams, die von Einzel-Chatbots oder Cloud-only-Agenten-Plattformen auf eine selbstgehostete Multi-Agenten-Infrastruktur wechseln.
- **Community-Beitrags-Workflow:** Standardisierte Issue-/PR-Vorlagen für neue Spezialisten-Profile, Fach-Skills, Lokalisierungen und Workflow-Rezepte.

---

### Meilenstein 37: Zeiterfassung & Projekt-Nachkalkulation – „Time-to-Invoice“ (Geplant – Hoch)
- **Integrierte Stoppuhr & Projekt-Zeiterfassung:** Start/Stop-Timer direkt in der Topbar sowie an jedem Kanban-Ticket und CRM-Kundenprojekt.
- **Soll-/Ist-Projektbudget & Deckungsbeitrag:** Laufender Abgleich geleisteter Stunden gegen das vereinbarte Projektbudget oder Pauschalangebot mit Frühwarnung bei drohender Budgetüberschreitung.
- **1-Klick-Fakturierung ins ERP:** Gesammelte Zeiten eines Monats lassen sich mit einem Klick gruppiert (nach Projekt, Mitarbeiter/Agent oder Leistungsart) als fertige Rechnungspositionen in einen ERP-Rechnungsentwurf überführen.

### Meilenstein 38: Automatischer Vertrags-, Fristen- & Abo-Wächter (Geplant – Hoch)
- **Zentrales Vertrags- & Kündigungs-Radar:** Übersicht aller laufenden Verträge, Lizenzen, SaaS-Abos, Leasing- und Versicherungspolicen inklusive Laufzeit, Kündigungsfrist, automatischer Verlängerung und monatlicher/jährlicher Kostenlast.
- **Proaktiver Fristen-Alarm (30 / 14 / 7 Tage):** Der Watchdog prüft täglich auslaufende Kündigungsfenster und meldet anstehende Verlängerungen im Morning-Briefing sowie per Telegram.
- **Vorbereitete Kündigungs- & Neuverhandlungs-Entwürfe:** Auf Knopfdruck erstellt `commercial_jurist_contracts` oder `procurement_specialist` das rechtssichere Kündigungsschreiben oder ein Nachverhandlungs-Angebot.

### Meilenstein 39: Lokaler Meeting- & Call-Copilot (Audio → Protokoll + Tasks) (Geplant – Hoch)
- **100 % Lokale Gesprächsaufzeichnung:** Mitschnitt von Vor-Ort-Besprechungen, Telefonaten oder Video-Calls über lokales Whisper inkl. Sprecher-Zuordnung (Diarization) ohne Cloud-Abfluss.
- **Strukturierte Aktennotiz im CRM:** Automatische Aufbereitung in *Kernergebnisse*, *Offene Fragen*, *Vereinbarte Konditionen* und direkte Ablage in der verknüpften Kundenakte sowie im Obsidian Vault.
- **Automatische Aufgaben-Extraktion:** Im Gespräch genannte Zusagen und Deadlines werden als fertig vorbefüllte Aufgabenkarten für das Kanban-Board vorgeschlagen.

### Meilenstein 40: Vertrags-Diff & Redlining-Ansicht (Alt gegen Neu im Browser) (Geplant – Mittel)
- **Visueller Dokumenten-Vergleich:** Nebeneinander-Ansicht zweier Vertragsstände (PDF, DOCX oder Markdown) mit farblicher Hervorhebung aller Einfügungen, Streichungen und umformulierten Klauseln.
- **Juristische Risiko-Bewertung der Änderungen:** Der Spezialist `commercial_jurist_contracts` prüft ausschließlich die geänderten Passagen der Gegenpartei, stuft das Haftungs- oder Kostenrisiko ein (Grün / Gelb / Rot) und liefert direkt eine Gegenformulierung.

### Meilenstein 41: Bi-direktionaler Kalender-Sync & Fokus-Blocker (Geplant – Hoch)
- **Echter Zwei-Wege-Kalenderabgleich:** Synchronisation über CalDAV, Google Calendar und Microsoft 365 / Exchange in beiden Richtungen (Lesen externer Termine & Schreiben neuer Zeitblöcke).
- **Autonomer Deep-Work-Blocker:** Stehen im Kanban-Board dringende Aufgaben kurz vor der Deadline, reserviert der Chief of Staff (`coo`) automatisch passende freie 60- bis 90-Minuten-Fokusblöcke im Kalender.

### Meilenstein 42: Geteilte Kunden- & Mandanten-Links – Mini-Freigabe-Portal (Geplant – Mittel)
- **Geschützte Showroom-Freigabe-Seiten:** Erzeugung zeitlich begrenzter, optional PIN-/Passwort-geschützter Links für Angebote, Projektberichte, Konzepte oder Entwürfe.
- **Digitale Angebotsannahme & Direkt-Feedback:** Kunden können Positionen im Browser kommentieren oder das Angebot digital bestätigen; bei Annahme wechselt der Belegstatus im ERP automatisch von *Angebot* auf *Auftrag* und informiert den Nutzer per Telegram.

### Meilenstein 43: Multi-Mandanten-Umschalter (Holding / Operative GmbH / SPV) (Abgeschlossen)
- **Mandantenfähigkeit in einer Instanz:** Auswahl-Dropdown in der Topbar (`tenant_switcher.js`) zum nahtlosen Wechsel zwischen mehreren eigenen Gesellschaften (z. B. Holding, operative GmbH, Immobilien-SPV oder Privatvermögen).
- **Strikte Kontext- & Nummernkreis-Trennung:** Jede Gesellschaft besitzt eigene isolierte SQLite-Datenbanken, ERP-Nummernkreise, Briefbögen, Steuernummern, Bankkonten, Kostenstellen und getrennte Buchhaltungs-Exporte bei gleichzeitigem Zugriff auf dieselbe 70-köpfige Spezialisten-Flotte.

### Meilenstein 44: Fertige „1-Click Business Playbooks“ – Workflow-Rezepte (Abgeschlossen)
- **Sofort startbare Prozess-Vorlagen für Einsteiger:** Kuratierte Bibliothek mit 10 mehrstufigen Standard-Workflows, die mehrere Spezialisten automatisch nacheinander orchestrieren:
  1. *Neuen Kunden komplett onboarden* (CRM-Anlage → Bonitäts-/Web-Check → NDA-Entwurf → Willkommens-Mail → Projekt-Ordner im Vault).
  2. *Monatsabschluss & Steuerberater-Paket vorbereiten* (Beleg-Vollständigkeitscheck → OPOS-Abgleich → BWA-Kommentar → DATEV-Stapel).
  3. *Wettbewerber-Teardown & Gegenstrategie* (Website-/Preis-Analyse → SEO/GEO-Lücken → Positionierungs-Memo → 5 Content-Entwürfe).
  4. *Lastenheft in Angebot & Projektplan verwandeln* (Anforderungs-Extraktion → Aufwandsschätzung → Kalkulation → Angebots-PDF + Kanban-Meilensteine).

### Meilenstein 45: Research Lab zum vollwertigen Deep-Research-Labor ausbauen (Geplant – Hoch)
- **Vom Alpha-Prototyp zur belastbaren Wissensmaschine:** Ausbau der aktuell noch rudimentären Recherche-Oberfläche (im UI als `alpha` gekennzeichnet) zu einer geführten Multi-Source-Pipeline.
- **Autonome Such- & Triangulations-Loops:** Iterative Suche über Live-Web, wissenschaftliche Datenbanken (ArXiv, EuropePMC, PubMed), Patentämter und amtliche Register mit automatischer Gegenprüfung widersprüchlicher Aussagen über die definierten Trust-Tiers (Tier 1–5).
- **Quellen-Verifikation & Halluzinations-Blocker:** Jede Kernaussage erhält klickbare Inline-Belege (`[Quelle: Name](URL)`) inklusive Abrufdatum und Hash-Snapshot der Primärquelle.
- **Direkt-Export in Obsidian & Showroom:** Automatische Aufbereitung als formatiertes Management-Dossier (Markdown + PDF) inklusive direkter Verlinkung in den Showroom, das ERP-CRM oder den Obsidian-Vault.

### Meilenstein 46: Open-Source Community-Hub, Sponsoring & Projekt-Portal (Geplant – Hoch)
- **GitHub Sponsors & Nachhaltige Open-Source-Finanzierung:** Aktivierung von `FUNDING.yml`, Sponsor-Tiers (Supporter / Professional / Enterprise-Support) als transparente Projektförderung neben der reinen MIT-Lizenz.
- **Kanonische Dokumentations- & Architektur-Website:** Öffentliches Projekt-Portal mit interaktiven Architektur-Rundgängen, 11-sprachigen Handbüchern, Sicherheits-Spezifikation, Roadmap und Release-Changelogs.
- **Reproduzierbare Qualitäts- & Release-Governance:** Automatisierte Multi-Arch-Container-Builds (x86_64 & ARM64), gepinnte Infrastruktur-Abhängigkeiten und signierte Release-Artefakte.

---

### Meilenstein 47: „Zero-Install“ Read-Only Live-Demo-Modus (`ARCHON_DEMO_MODE`) (Abgeschlossen)
- **Öffentlicher Showcase-Mandant ohne Token-Risiko:** Startschalter `ARCHON_DEMO_MODE=true`, der Archon OS mit einem vollständig vorbefüllten Muster-Unternehmen (*„Mittelstand Muster GmbH“*: fertige 6-Phasen-Boardroom-Debatte, aktive Kanban-Karten, Muster-Rechnungen, CRM-Pipeline und 70er-Organigramm) initialisiert.
- **Harte Middleware-Schreib- & Exec-Sperre:** Blockiert auf ASGI-Ebene sämtliche schreibenden Mutationen, Container-/Sandbox-Ausführungen, Dateisystem-Schreibpfade und externen LLM-Egress; liefert für Interaktionen deterministische, vorab aufgezeichnete Referenz-Antworten aus.
- **5-€-VPS-Deployment-Fähigkeit:** Ermöglicht den risikolosen Betrieb einer öffentlichen Live-Instanz (`demo.archon-os...`) ohne 0-Day-Angriffsfläche und ohne laufende API-/Token-Kosten.

### Meilenstein 48: Archon OS als nativer MCP-Server (`/mcp` Gateway) (Abgeschlossen)
- **Vom reinen MCP-Client zum zentralen Unternehmens-MCP-Hub:** Bereitstellung eines standardkonformen Model-Context-Protocol-Endpunkts (`/mcp` via Streamable HTTP / SSE), abgesichert über Scoped-API-Keys (M17) und die bestehenden Human-in-the-Loop-Freigabe-Gates.
- **Externe IDE- & Desktop-Anbindung:** Externe Clients wie *Claude Desktop*, *Cursor*, *Windsurf*, *VS Code* oder *Hermes Desktop* können direkt Archon-Spezialisten delegieren (`delegate_specialist`), ein mehrstimmiges AI-Boardroom-Votum einholen (`convene_boardroom`) oder kontrolliert Wissen aus Obsidian-Vault und ERP/CRM abfragen.
- **Granulare Tool-Freigabe pro API-Key:** Jeder verbundene MCP-Client sieht ausschließlich die ihm per Scope freigegebenen Fach-Agenten und Lese-/Schreib-Werkzeuge.

### Meilenstein 49: EU AI Act Compliance-Engine & 1-Klick-Verfahrensdokumentation (Abgeschlossen)
- **Automatische EU-AI-Act-Risikoklassifizierung je Spezialist:** Präzise rollen- und wortgrenzenbasierte Einstufung aller 70 Spezialisten-Profile nach EU-KI-Verordnung (`HIGH_RISK` Anhang III Nr. 4/5, `SPECIFIC_TRANSPARENCY` Art. 50, `MINIMAL_RISK` Art. 95) inkl. kryptografischer `SOUL.md`-SHA-256-Prüfsumme und Pflicht-Guardrail-Prüfung (`backend/eu_ai_act_inventory.py`, `backend/compliance_engine.py`).
- **KI-Kompetenznachweis- & Governance-Register (Art. 4 EU AI Act):** Revisionssicheres Protokoll über eingewiesene Bediener, freigegebene Modelle, System-Prompt-Hashes und Zero-Egress-Status, automatisch verkettet in `audit_log` (M21).
- **1-Klick-PDF-Verfahrensdokumentation (GoBD + EU AI Act):** Abhängigkeitsfreier DIN-A4-PDF-1.4-Generator (`backend/compliance_pdf.py`), der live aus Mandantenstamm, physischer DB-Isolation (M43), Nummernkreisen, Datenschutz-Routing (M22), GoBD-Merkle-Hashkette (M21) und EU-AI-Act-Inventar ein prüferfertiges Verfahrensdokumentations-PDF erzeugt (`/api/v1/governance/compliance/verfahrensdokumentation.pdf`).

### Meilenstein 50: Agent-Eval- & Modell-Benchmark-Arena (Pre-Live Regressions-Schutz) (Geplant – Hoch)
- **Kuratierter Gold-Standard-Prüfkatalog (~25 Referenz-Tasks):** Lokales Benchmark-Deck mit repräsentativen Unternehmensaufgaben (JSON-Delegationstreue, juristischer Klausel-Risikocheck, Deckungsbeitrags-/Margen-Kalkulation, DSGVO-Schwärzung, Zero-Hallucination-Faktentreue bei fehlenden Daten).
- **A/B-Modell- & SOUL-Vergleich vor Live-Schaltung:** Lässt bei Modellwechseln (z. B. neues lokales Ollama-/Qwen-/Llama-Modell) oder `SOUL.md`-Umbauten alte gegen neue Konfiguration automatisiert gegeneinander antreten.
- **Entscheidungs-Scorecard im Cockpit:** Direkter Vorher/Nachher-Ausweis von Qualitätsscore, Halluzinationsrate, Schema-Treue, Antwortlatenz und Kosten pro Aufgabe vor Produktivsetzung.

### Meilenstein 51: Portabler „Squad-Blueprint“-Paketmanager (`.archonpack`) (Abgeschlossen)
- **Komplette Fachabteilungen als Einzelpaket bündeln:** 1-Klick-Export und signierter Import ganzer Spezialisten-Squads als portables `.archonpack`-Archiv (Agenten-Definitionen, 3-Stufen-`SOUL.md`, zugehörige Fach-Skills, passende Boardroom-Frameworks und optionale n8n-Workflow-Vorlagen).
- **Schlüsselfertige Branchen- & Domänen-Blueprints:** Ermöglicht sofort installierbare Fachpakete wie *„Pharma / GDP-Quality-Squad“*, *„Immobilien-Ankaufsprüfung & SPV-Analyse“*, *„Steuer- & Monatsabschluss-Vorbereitung“* oder *„E-Commerce Operations“*.
- **Abhängigkeits- & Sicherheits-Prüfung beim Import:** Vorab-Inspektion aller enthaltenen Prompts, Tool-Berechtigungen und benötigten MCP-Connectoren in einer Quarantäne-Vorschau vor Aktivierung im Kader.

### Meilenstein 52: Pre-Flight Cost-Estimator & „Shadow-Mode“ (Trockenlauf für Agenten) (Abgeschlossen)
- **Pre-Flight-Kostenvoranschlag vor großen Ketten:** Transparente Vorab-Kalkulation vor Start mehrstufiger Delegationskaskaden oder 6-Phasen-Boardroom-Debatten (*„Geschätzt: ~48k Tokens ≈ 0,14 € · 4 lokale Zero-Cost-Agenten + 1 Cloud-Synthese“*) mit konfigurierbarer Kostenschwelle für Pflicht-Freigaben.
- **Passiver „Shadow-Mode“ für neue Agenten & Prompts:** Neue oder umgebaute Spezialisten lesen reale Eingänge, Tickets und Aufgaben im Hintergrund parallel mit und erzeugen interne Entwürfe, ohne nach außen senden oder Status mutieren zu dürfen.
- **Reifegrad-Freischaltung nach Trefferquote:** Das Cockpit legt den Shadow-Entwurf neben die reale menschliche Entscheidung und empfiehlt die Beförderung in den aktiven Betrieb erst ab einer gemessenen Übereinstimmungsquote (z. B. > 90 % über 20 Vorgänge).

### Meilenstein 53: „Epistemic Hygiene“-Wächter für den Obsidian-Vault (Abgeschlossen)
- **Wöchentlicher Wissens-Konsistenz-Scan:** Lokaler Hintergrund-Job (Embeddings + regelbasierte Faktenextraktion) über `01_PROJEKTE` und `02_Wissensbibliothek`, der schleichende Widersprüche zwischen eigenen Notizen erkennt (z. B. abweichende Zinssätze, Stundensätze, Fristen oder Projektannahmen in verschiedenen Dokumenten).
- **Verfallsdatum- & Rechtsstand-Radar:** Markiert Notizen, Kalkulationen und Vorlagen mit abgelaufenen Vertragsständen, überholten Steuersätzen/Gesetzesfassungen oder verwaisten Querverweisen.
- **Saubere Bereinigungs-Tickets statt stiller Korrektur:** Legt erkannte Diskrepanzen mit exaktem Zitat-Paar (Dokument A vs. Dokument B) als prüfbares Klärungs-Ticket im Triage-/Kanban-Board an, ohne das Second Brain ungefragt umzuschreiben.

### Meilenstein 56: Archon OS Versions- & GitHub-Update-Badge in der linken unteren Seitenleiste (Abgeschlossen)
- **Versions- & Update-Anzeige analog zu Hermes Agent:** Unten links in der Seitenleiste (direkt neben/über der Hermes-Agent-Versionsanzeige) wird die aktuell installierte Archon-OS-Version permanent angezeigt.
- **Sofortiger GitHub-Update-Badge:** Liegt auf GitHub eine neuere Version bzw. ein neues Release vor, erscheint sofort ein gut sichtbarer Update-Badge an der Archon-Versionsanzeige.
- **1-Klick-Sprung zum System-Update:** Ein Klick auf den Badge öffnet direkt *Settings → System-Update & Server-Sync*, sodass das Update unmittelbar gezogen werden kann.

---

### Meilenstein 57: Frontend-Performance, Streaming-Bus & WCAG/i18n-Härtung (Abgeschlossen)
- **Umgesetzt (15.11.2026 — Performance, SSE & XSS):** `initArchonApp()` (`static/index.html`) entkoppelt sekundäre Views vom initialen Overlay-Boot und lädt versteckte `localhost:9119`-Iframes (`#agent-dash-iframe`, `#hermes-dashboard-iframe`) erst per `data-src` bei Aktivierung; `add_no_cache_for_avatars` (`main.py`) gilt nur noch für `/static/avatars/` und doppeltes `/assets`-Mounting wurde bereinigt. Toter `EventSource("/api/v1/telemetry/logs")` in `static/js/skill_markt.js` sowie doppelter SSE-Stream in `mission_control_cockpit.js` wurden auf den geteilten `archon:sse`-Bus umgestellt. Überflüssiger `selectionchange`-Icon-Scan in `agent_profiles.js` entfernt; Debounce + `AbortController` in `crm_studio.js`, `agent_profiles.js` und `erp_studio.js` (`static/views/view_items.html`) ergänzt; XSS-Escaping in `prompt_studio.js`, `erp_studio.js`, `skill_markt.js` (Boardroom SSE & Thread-Verlauf), `operations_kanban.js` (Comm-Feed) sowie `static/index.html` (NotebookLM) nachgezogen; verschachteltes `<main>` in `index.html` bereinigt, `user-scalable=no` in `mobile.html` entfernt, sichtbare Fokus-Ringe in `static/css/themes.css` ergänzt und Impressum-/Datenschutz-Links integriert.
- **Umgesetzt (15.11.2026 — Build-CSS, WCAG-Dialoge & ERP-i18n Abschluss):**
  - **Vorkompiliertes Tailwind-CSS:** Neues Offline-Build-Skript `scripts/build_tailwind_css.mjs` compiliert alle genutzten Klassen aus `static/` vorab in `static/css/tailwind.generated.css` und ersetzt sowohl `tailwind.cdn.js` in `static/index.html` als auch externe Tailwind-/Lucide-/Font-CDNs in `static/hermes-hud/index.html`.
  - **WCAG 2.2 AA Dialog-Sweep:** Alle 39 aktiven Modals und Drawer (`22` in `static/index.html` + `17` in `static/views/*.html`) tragen `role="dialog" aria-modal="true"`; `static/js/modal_a11y.js` übernimmt per `MutationObserver` automatisches `aria-labelledby`-Binding, `Tab`/`Shift+Tab`-Focus-Trap, `Escape`-Schließen und Fokus-Rückführung auf das auslösende Element (`role="status" aria-live="polite"` am `global-loading-overlay`).
  - **ERP-Studio i18n-Parität:** Alle 124 hardcodierten deutschen UI-Strings in `static/erp_studio.js` auf `erpT("ui.erp_studio.*", ...)` (`window.archonI18n`) inkl. Live-Getter-Funktionen (`getAddressTabMeta`, `getItemsTabMeta`, `getOpsErpTabMeta`) umgestellt und über alle 11 Sprachkataloge (`static/locales/{de,en,es,fr,it,ja,ko,nl,pt,ru,zh}.json`) vollständig synchronisiert.

### Meilenstein 58: Backend-Performance, Async-Event-Loop & SQLite-Tuning (Abgeschlossen)
- **Event-Loop entblockt:** Blockierende Docker-Exec-Schleifen (`archon/routers/gateway.py`), `stream_comm_feed` (`archon/routers/operations_org.py` inkl. `try/finally: conn.close()` + 1.5s-Poll) und Index-Scans (`archon/routers/skills.py`) via `asyncio.to_thread` ausgelagert.
- **Persistente HTTP-Connection-Pools & Endpoint-Cache:** Langlebige `httpx.AsyncClient`-Instanzen in `core_dispatcher.py`, `archon/routers/hermes_proxy.py` (inkl. 30s Target-Cache) und `archon/routers/system.py`.
- **SQLite-Standardisierung & Indizierung:** Deterministisches Connection-Closing in `backend/auth_service.py` (`_ClosingAuthConn`), aufgelöster DB-Pfad-Cache sowie einmalige `WAL`/`synchronous=NORMAL`/`cache_size=-32000`/`temp_store=MEMORY`-Initialisierung in `backend/db_paths.py`, `archon/core/state_db.py` und `archon/core/mission_control.py`; 3 fehlende Indizes plus 30s-Touch-Cooldown in `local_memory_bridge.py`; SQL-Datumsfilter in `archon/routers/guardian.py`; `collections.deque` + 5s-Config-Cache in `backend/async_write_batcher.py`.

### Meilenstein 59: Kern-Pipeline, Runtime-Crash-Fixes & Routing-Konsolidierung (Abgeschlossen)
- **Akute Runtime-Crashes geschlossen:** Repariert in `hr.py`, `governance.py`, `operations_autonomy.py`, `backend/email_draft_engine.py` (`get_status_counts`), `operations_org.py` und `backend/memory_consolidator.py` (inkl. Entfernen destruktiven Audit-Log-Prunings).
- **Auth- & Settings-Widersprüche behoben:** Weiterleitungs-Trigger in `archon/routers/core_settings.py` (GET & POST) auf explizite `x-hermes-*`-Header begrenzt (`Authorization: Bearer` bleibt lokal); alle `9` fail-open `_require_admin`-Fallbacks auf fail-closed `_rbac.require_admin_or_503` gezogen; `archon/routers/auth.py` Toggle-Pfade & dynamisches HTTPS-`secure`-Cookie-Flag angeglichen.
- **Chat-, Delegations-, Telemetry- & Playbook-Pipeline repariert:** `archon/routers/agent_chat.py` übergibt `history` an `core_dispatcher.py` inkl. Anthropic-Textblock-Extraktion, OmniRoute-Vorrang und lückenlosem `_log_dispatcher_usage`; `archon/core/delegation.py` erkennt `"failed"`/`"blocked"` terminal; `backend/operations_api.py` meldet echten `target_status`; `backend/agent_router.py` nutzt `db_paths`-Auflösung für `_daily_spend_usd`; `archon/routers/telemetry.py` liefert reale SQLite-/Skill-/Vault-Metriken; `backend/speculative_prefetcher.py` liest aktives Tenant-`erp.db`; `backend/playbooks_engine.py` + `archon/routers/playbooks.py` führen Schritte real über `core_dispatcher` aus; `apollo_voice_engine.py` bindet `sync_emails`/`create_task`/`chat_or_execute` an.

### Meilenstein 60: Aktive Security-Middleware & Recht/Compliance 2026 (Abgeschlossen)
- **DLP & Egress-Schutz technisch erzwungen:** `enforce_egress_firewall_for_url` und `sanitize_outbound_llm_payload` (`secret_masker` + `pii_scrubber`) aktiv in `core_dispatcher.py` und `backend/agent_router.py` vor Cloud-HTTP-Dispatches; `frontend/src/utils/aiAudio.ts` entfernt alle Browser-Groq-Keys und nutzt `POST /api/voice/transcribe` (`archon/routers/voice.py`).
- **Showroom Path-Jail & Python-Sandbox (`views_core.py`):** `/showroom/file/delete`, `/restore` und `/purge` sowie `run_showroom_code` erzwingen `safe_path_within`; Python-Ausführung läuft isoliert im `TemporaryDirectory` mit `python -I`, bereinigter Environment-Liste (ohne Host-Secrets) und POSIX-`rlimit`.
- **DSGVO, GoBD & § 288 BGB:** `execution_receipt_ledger.verify_chain_integrity()` prüft alle gespeicherten SHA-256-Hashes neu; `backend/erp_manager.py` sperrt `booked`/`paid -> draft`-Rückstufungen; `backend/dunning_engine.py` setzt Mahnstufe 1 auf `0,00 €`, berechnet tagesgenaue Verzugszinsen (§ 288 BGB) und koppelt `approve_and_send_dunning` an `email_draft_engine`/`erp_manager`; `backend/crm_service.py` & `backend/tenant_context.py` erzwingen Opt-In-Default `0`; `backend/gdpr_compliance_engine.py` liefert standardmäßig einen paginierten Voll-Export nach Art. 15 DSGVO (optional begrenzt via `max_messages` mit Truncation-Flag) und löscht nach Art. 17 case-insensitiv (`re.IGNORECASE`); `backend/privacy_router.py` vergibt `"DSGVO (100% On-Premise)"` nur bei streng lokalem Betrieb.
- **EU AI Act, § 5 DDG & OSS-Lizenzen:** `compliance_engine.py` & `eu_ai_act_inventory.py` prüfen Art.-4-Kompetenz für `HIGH_RISK` dynamisch; `chat.py` gibt Art.-50-Tag nur bei erfolgreicher KI-Antwort aus; `/api/legal/impressum` & `/api/legal/datenschutz` in `archon/routers/system.py` bereitgestellt und verlinkt; `THIRD_PARTY_LICENSES.md` um Backend-Python- und Frontend-Vendor-Pakete vervollständigt.

### Meilenstein 61: Legacy-Bereinigung: `evey-*`-Altlasten & CRM/PocketBase-Entkopplung (Abgeschlossen)
- **Deaktivierung/Optionalisierung von `crm:3005` & `pocketbase:8090`:** Aus aktiven Standard-Checks in `archon/core/settings_state.py` und Default-Logansicht (`static/index.html`) entfernt; `backend/erp_manager.py` und `backend/gdpr_compliance_engine.py` über `POCKETBASE_ENABLED=false` lokal autark auf `erp.db` geschaltet; `docker-compose.yml` reicht `POCKETBASE_ENABLED=${POCKETBASE_ENABLED:-false}` sowie fehlende Provider-/Service-/Vault-Variablen an `archon-os` durch.
- **Abbau aktiver `evey-*`-Altlasten:** Hardcodiertes `evey-telegram-ux`-Auto-Enable entfernt und nicht aktivierte `evey-*`-Legacy-Plugins in `archon/routers/guardian.py` ausgeblendet.

### Meilenstein 55 (Ergänzung zu M25): Kalender in Operations überarbeiten (Geplant – Hoch)
- **Operations-Kalender UI/UX:** Grundlegende Überarbeitung der Kalender-Ansicht innerhalb von *Operations* (`operations_calendar.js`) über das bestehende Kachel-/API-Fundament hinaus: vollständiges Monats-, Wochen- und Tagesraster, Drag-&-Drop-Terminplanung, Serientermine, Erinnerungen/Benachrichtigungen sowie Ressourcen- und Agenten-Ansicht.

### Meilenstein 62: Vorlagen in Operations überarbeiten (Geplant – Hoch)
- **Vorlagen-UX in Operations:** Überarbeitung des Vorlagen-Bereichs in Operations (Formular-, Beleg- und Workflow-Vorlagen unter *Operations* / `view_corporate.html` / `corporate_controller.js`): klarere Navigation, übersichtlichere Vorschau/Bearbeitung und nahtlosere Übergabe in den operativen Workflow.

### Meilenstein 63: Linkes Menü (Sidebar) & untere linke Ecke modernisieren (Geplant – Hoch)
- **Navigationsstruktur:** Überarbeitung und Modernisierung der linken Seitenleiste inkl. Prüfung/Umsetzung einklappbarer Sektionen für weniger visuelles Rauschen und bessere Übersicht bei vielen Modulen.
- **Untere linke Ecke aufräumen/umbauen:** Komplette Entrümpelung und Neuordnung des unteren Sidebar-Bereichs (Status-Pills `LOKAL`/`DSGVO`, Versions-/Update-Badges für Hermes & Archon, Benutzer-Badge, Settings- & Recht-Links), sodass keine Überlagerung oder visuelle Überfrachtung mehr entsteht.

### Meilenstein 64: Onboarding-Dialog (First-Run) überarbeiten & in Settings verankern (Geplant – Hoch)
- **Wizard-Überarbeitung:** Visuelles, sprachliches und funktionales Polishing des First-Run-Onboarding-Dialogs (`onboarding_wizard.js`) inklusive klarerer Schrittführung und Validierungs-Feedback.
- **Auffindbarkeit in den Settings:** Prominenter und leicht auffindbarer Einstiegspunkt („Setup-Assistent / Onboarding erneut starten“) direkt in den Systemeinstellungen (verzahnt mit M65).

### Meilenstein 65: Design & Struktur der Systemeinstellungen (Settings) überarbeiten (Geplant – Hoch)
- **Settings-Redesign:** Grundlegende Modernisierung des *System Control Center* (`static/views/system_settings_modal.html`, `static/js/system_settings.js`, verzahnt mit M6): ruhigere, konsistente Karten-/Formular-Layouts, aufgeräumte Tab-Führung ohne visuelles Gedränge, bessere Abstände/Typografie im Light- und Dark-Mode sowie saubere Einordnung von Bereichen wie Onboarding, Kernel, Routing und Design.

### Meilenstein 66: Hardware-gebundene Agent-Authentifizierung („Agent Authenticator“) (Geplant – Mittel)
- **Orientierung:** Ein aktueller IETF-Internet-Draft (Stand November 2026) zur hardware-gebundenen, origin-gebundenen Authentifizierung von KI-Agenten: Agentenprozesse halten keine Geheimnisse; Schluessel liegen in Secure Hardware oder einem attestierten Key-Dienst; Origin-Binding verhindert die Umleitung von Credentials durch Prompt-Injection; eine namentlich bekannte Person genehmigt jede Agent-Credential und jede Hochrisiko-Aktion per Passkey (Step-Up); jede signierte oder verweigerte Aktion landet in einem signierten, tamper-evidenten Action-Record.
- **Status des Entwurfs:** Draft `-00`, Work in Progress, läuft 19.05.2027 aus. Noch keine Implementierungen oder unterstützende Dienste. Gilt hier als Architektur-Orientierung, nicht als Compliance-Claim.
- **Anschluss an Bestand:** Die Hälfte der Eigenschaften ist vorhanden — menschliche Freigabe pro Hochrisiko-Aktion (`approval_policy_engine.py`, Kanban Four-Eyes-Gate) und tamper-evidentes Log (`audit_log.py`, SHA-256-Kette). Fehlend und Zielbild dieses Meilensteins: Agentenprozesse ohne eigene Secrets; ein Authenticator-Dienst mit hardware-gebundenen Schlüsseln (z. B. TPM 2.0 auf dem Host) als Signaturendienst; Step-Up-Freigabe über das Kanban-Gate für Hochrisiko-Domänen (Buchhaltung/ERP-Schreibvorgänge); Action-Records in die bestehende Audit-Kette einspeisen.
- **Offen:** Hardware-Basis (TPM 2.0 / Secure Enclave / attestierter Cloud-KMS), Integration mit der MCP-Autorisierung, Bewertung der weiteren Draft-Entwicklung (Nachfolge-Drafts, IETF-Arbeitsgruppe) vor Umsetzung.

### Meilenstein 67: Host-seitige Zustandsfuehrung & Prompt-Kompression (Preprint-Ansatz, November 2026) (Geplant – Mittel)
- **Orientierung:** Ein Preprint (November 2026, ohne Peer-Review) zur host-seitigen Zustandsfuehrung und Prompt-Kompression. Kernidee: Der Job-Zustand wird aus dem wachsenden Chat heraus auf den Host verlagert und dort exakt gehalten; jede Modellantwort wird vor der Uebernahme durch ein deterministisches Gate geprueft; das Modell erhaelt pro Schritt nur einen kurzen, frischen Prompt.
- **Status der Quelle:** Preprint ohne Peer-Review (Selbstpublikation, Indie-Autoren). Autoren berichten Messungen (u. a. Prompts ~169x kleiner, Zustand exakt ueber 1.500/1.500 Schritte, Kosten je Step 4,5-9,3x niedriger) mit vorab hash-gelockten Praediktionen und rekonstruierbaren Testdaten im Repo. Zahlen sind vor einer Übernahme im Detail gegen das Repository nachzuprüfen — als Fakt zitieren wir sie nicht.
- **Verhältnis zum Bestand:** Komplementär, nicht konkurrierend. OmniRoute (`cost_estimator.py`, Dispatch-Budgets) kontrolliert Kosten auf der Verteilungsebene (welche Anfrage, wohin, was kostet sie). Der Praeprint-Ansatz greift eine Ebene tiefer an: wie groß die Anfrage überhaupt ist (Kontext-/Zustandsführung im `core_dispatcher`/Kontext-Assembly). Beides zusammen bedeutet: kleinere Anfragen UND kontrollierte Verteilung.
- **Offen:** Messungen im Repo replizieren bzw. gegen eigene Workloads prüfen; bewerten, ob die deterministische Gate-Prüfung mit unseren Approval-Gates (`approval_policy_engine.py`) verzahnt werden kann; Interaktion mit Obsidian-RAG-Kontext (der Ansatz komprimiert Chat-Verlauf, nicht Wissensbasis); Beobachtung, ob der Ansatz in der Community Replikation/Adaption findet.

### Meilenstein 68: Compliance-Inventar, DPIA-Register & Replay-Nachweis (Geplant – Mittel)
- **Orientierung:** Ein Fachbeitrag zur KI-Einfuehrung in Organisationen mit Compliance-Audit-Pflicht (November 2026). Kernthese: SOC 2 / ISO 27001 / DSGVO / EU AI Act fragen letztlich dieselben sieben Dinge: Existenz im Inventar, Datenfluesse, Vendor, Zugriffe, Handlungen, Verantwortlichkeit, Nachweisbarkeit ueber Zeit.
- **Vorhanden:** Freigabegates (M25/M60), SHA-256-Audit-Kette und Receipt-Ledger, Egress-Firewall + Outbound-Masking, DSGVO Art.-15/17-Engine, Art.-50-Kennzeichnung im Chat. Nicht vorhanden: Inventar, DPIA-Register, Aufbewahrungslogik, getesteter Replay, Policy-Export.
- **Neu zu bauen:**
  - **Compliance-Inventar pro Tenant, automatisch generiert:** Aus den vorhandenen Konfigurationsdaten (Agent-Profile, Toolrechte, Egress-Konfiguration, Modell-Routing, Tenant-Kontext) eine Ansicht „Agent -> beruehrte Daten -> Ziel (lokal/Cloud) -> Freigabestufe" ableiten. Auditor-tauglich als Tabelle und PDF-Export.
  - **DPIA-/Use-Case-Register:** Pro Use Case ein Eintrag (Verarbeitungszweck, Datenklassen, Risikoprofil, verantwortliche Person, geprueft am), verzahnt mit Art. 35 DSGVO. Change-Trigger: neues Modell, neue Datenklasse oder neuer Zweck markiert den Eintrag als ueberpruefungsbeduerftig.
  - **Aufbewahrungsplan je Log-Typ:** Audit-Log, Chat-Verlauf, ERP-Belege mit unterscheidbaren Aufbewahrungsfristen (GoBD/Steuer: 10 Jahre; Betriebs-Logs kuerzer); Pseudonymisierung von personenbezogenen Feldern in Betriebs-Logs (Secret-Masker existiert, Feldpseudonymisierung nicht).
  - **Getesteter Replay:** Aus einem Audit-Log-Eintrag den Dispatch rekonstruieren und als Test laufen lassen (Gegenstueck zur_receipt_ledger.verify_chain_integrity); der Test selbst ist der Nachweis, nicht nur die Kette.
  - **Ein-Seiten-Policy-Export:** Aus den aktiven Controls (Klassifizierung, Freigaben, Log, Egress) automatisch eine einseitige KI-Policy pro Organisation generieren — Zielgruppe: Geschaeftsfuehrung und externe Auditoren.
  - **KI-Inhalts-Kennzeichnung ueber den Chat hinaus:** Art. 50 AI Act (gilt seit 02.08.2026, Umsetzungsfrist fuer bestehende Tools 02.12.2026): agentenerstellte E-Mails und Belege im ERP/CRM-Fluss als KI-generiert markieren.
- **Bewerbungs-Screener häärten (Ergänzung, Quelle: eine aktuelle Recruiter-Umfrage, November 2026):** Laut Studie berichten Recruiter von versteckten Anweisungen in Bewerbungsunterlagen, die automatisierte Vorauswahl beeinflussen sollen. Für den Bewerber-Screener gilt deshalb: Bewerbungs-PDFs sind grundsätzlich unvertraute Eingabe (Prompt-Injection-Fläche); Detektion versteckter Anweisungen (Weißschrift, Textlayer, Metadaten) vor der Auswertung; jede Screening-Entscheidung mit nachvollziehbarer Begründung ins Audit-Log und an einen menschlichen Entscheider gekoppelt (Art. 22 DSGVO-Nachweis: keine vollautomatische Ablehnung).

- **Nicht-Ziel:** Rechtsberatung ersetzen; das Inventar beschreibt den Ist-Zustand der Konfiguration, die rechtliche Bewertung bleibt beim Betreiber/beratenden Dritten.

### Meilenstein 69: Policy-as-Code für Freigaben (YAML, Vendor-Limits, Telegram-Buttons, Freigabe-Tokens) (Geplant – Mittel)
- **Orientierung:** Ein Open-Source-Projekt fuer lokale Spend-Controls fuer KI-Agenten (Stand November 2026): Budget-/Freigabe-Regeln als eine editierbare Policy-Datei statt nur UI-Einstellungen; rolling 24h-Limits pro Vendor; Freigabequeue mit Approve/Deny-Buttons inkl. Messenger; signierte, kurzlebige Tokens fuer freigegebene Entscheidungen, die die ausfuehrende Stelle vor dem Handeln prueft.
- **Zu bauen:**
  - **Policy-Datei für `approval_policy_engine.py`:** Regeln (Ressource/Domain, Aktionen, maxAmount je Vorgang, maxDailyAmount rollend je Vendor, Verdict approved/pending/denied) in einer YAML-Datei, versionierbar und vom Betreiber editierbar; die Engine wertet sie deterministisch aus und begründet jede Entscheidung mit den passenden Regel-IDs.
  - **Vendor-Ebene im `cost_estimator.py`:** Tagesbudgets bisher je Agent/Aufgabe; ergänzend rollende 24h-Limits je Provider/Vendor, damit ein durchdrehendes Modell nicht das Tagesbudget eines Anbieters aufzehrt.
  - **Telegram-Freigabe mit Buttons:** Prüfen, ob die bestehende Telegram-Anbindung Freigaben nur meldet; Ziel sind Approve/Deny-Buttons direkt im Chat (nur die Taps des Berechtigten zählen), verzahnt mit dem Kanban-Four-Eyes-Gate (`decisions.py` bleibt der einzige Schreibpfad).
  - **Signierte Freigabe-Tokens:** Jede Freigabe erzeugt ein kurzlebiges, signiertes Token; die ausführende Komponente prüft es vor der Ausführung und vermerkt es im Receipt-Ledger. Damit ist „freigegeben“ maschinell prüfbar, nicht nur protokolliert.

### Meilenstein 70: Auto-Review-Runden, Validierungs-Agenten & „Braucht mich“-Panel (Geplant – Mittel)
- **Orientierung:** Ein Praxisbericht ueber Multi-Agent-Orchestrierung im taeglichen Betrieb (November 2026) — „Needs me“-Panel als eine Liste von allem, was auf den Menschen wartet; automatische Review-Runden (Schreib-Agent -> zwei Review-Agenten -> Befunde zurueck an den Autor -> erst dann liest der Mensch); Validierungs-Agent vor jedem Rollout-Gate (liest Code, nimmt Messwerte, verlinkt Belege fuer sein Urteil). Recovery-Prinzip eines Open-Source-Projekts fuer langlebige Agent-Workflows: unsichere extern wirksame Arbeit wird nach einem Abbruch nie stillschweigend wiederholt, sondern dem Menschen vorgelegt.
- **Zu bauen:**
  - **Auto-Review-Runden vor den Freigabegates:** Komplexe Pakete durchlaufen vor der menschlichen Freigabe standardmäßig eine oder zwei Agenten-Review-Runden (kritische Gegenprüfung ist mit dem 3-Stufen-SOUL-Modell vorhanden); Befunde gehen strukturiert an den erzeugenden Agenten zurück, die finale Historie landet im Audit-Log.
  - **Validierungs-Agent am Gate:** Vor Hochrisiko-Freigaben (Buchhaltung/ERP-Schreibvorgänge) nimmt ein Validierungs-Agent Belege auf (Belegrechnung, Prüfsummen, Kontostände) und verlinkt sie an der Freigabe, damit der Mensch eine geprüfte Entscheidung trifft statt einer nackten Anfrage.
  - **Einheitliches „Braucht mich“-Panel:** Die Triage-Inbox bündelt vollständig: offene Freigaben, Agentenrückfragen, fehlgeschlagene/neu laufende Tasks, unsichere Wiederholungen nach Abbruch. Eine Liste, keine vier Orte.
  - **Durable Runs / kein stiller Replay:** Nach einem Crash zwischen „Schritt geplant“ und „externer Wirkung ausgeführt“ (E-Mail-Versand, Zahlung, Buchung) wird der Schritt als „unsicher“ markiert und dem Menschen im Panel vorgelegt — nie automatisch wiederholt. Prüfauftrag: Verhalten von `dag_scheduler.py` / `mission_control.py` / `operations_api.py` nach Abbruch mitten im Dispatch.

### Meilenstein 71: Eval-Attestierung (Geplanter Fingerabdruck je Eval-Lauf) (Geplant – Niedrig)
- **Orientierung:** Ein Open-Source-Agent-Werkzeug (Stand November 2026) heftet an jedes Eval-Ergebnis einen SHA-256-Fingerprint der Dateien an, die das Verhalten bestimmen, und verifiziert ihn — ein Ergebnis ist nur aussagekraeftig, wenn feststeht, gegen welche Konfiguration es lief.
- **Zu bauen:** Vor jedem Lauf der Agent-Eval-Arena (M50) wird ein SHA-256-Fingerprint über die verhaltensbestimmenden Dateien (Agent-Profile/SOUL.md-Stufe, Prompts, Policy-Datei aus M69, Routing-Config) gebildet und mit dem Ergebnis gespeichert; der Vergleich zweier Eval-Läufe ist damit ein Vergleich zweier eindeutig identifizierter Konfigurationen. Verzahnt mit der bestehenden SHA-256-Infrastruktur (`audit_log.py`).

### Meilenstein 72: Modellabhängiges Task-Sizing & Skills auf Leihbasis (Geplant – Niedrig)
- **Orientierung:** Ein Open-Source-Plugin (MIT, Stand November 2026), das Frontier-Modelle planen und rezensieren laesst und lokale LLMs ausfuehren lassen. Zwei uebernehmbare Ideen: (1) Aufgaben werden passend zum Kontextfenster des Zielfahrzeugs zerschnitten und die Schnittgroesse korrigiert sich mit jedem abgeschlossenen Schritt; (2) jeder Agent bekommt nur die Skills, die seine Aufgabe braucht, und gibt sie nach Abschluss zurueck.
- **Zu bauen:**
  - **Modellabhängiges Task-Sizing im Dispatcher:** Komplexe Aufgaben werden beim Zerschneiden (`dag_scheduler.py` / `core_dispatcher.py`) an das Kontextfenster und das Leistungsprofil des vorgesehenen Modells angepasst (lokales 7B-Modell: kleinere Pakete als ein Cloud-Flaggschiff); nach jedem abgeschlossenen Schritt korrigiert der Dispatcher die Schnittgröße für den nächsten Schritt derselben Domäne.
  - **Skill-Verleih auf Task-Ebene:** Aus dem `hermes_skills_index` erhält ein Agent nur die Skills, die zu seiner Aufgabe passen (Attribut je Skill: passende Domänen/Aufgabentypen), und verliert sie nach Abschluss — schlanke Prompts, weniger Token, weniger Ablenkung. Ergänzt das bestehende 3-Stufen-SOUL-Prinzip um die Skill-Dimension.
- **Verhältnis zum Bestand:** Keine Konkurrenz — Komplementär. Das Plugin adressiert Coding-Agenten, ARCHON OS Business-Operations; beide bauen auf Hermes Agent und befeuern dieselbe Architekturidee (Frontier-Urteil lokal ausgeführt).

### Meilenstein 74: Freigabe-Gate 2.0 — Konsolidierung der Freigabe-Ebenen (Geplant – Hoch)
- **Ausgangslage:** Es gibt heute mehrere Freigabe-Flaechen: das Missions-Approval-Gate (Mission Control), die Policy-Engine-Freigaben (`approval_policy_engine`, Domains + Vier-Augen + Vertretungsmodus + Eskalations-Timeout) und das HITL-Gate am MCP-Gateway (Replay-geschuetzte `hitl_approval_id`-Zweiaufrufe). Funktional korrekt, aber drei ueberpruefte Ebenen, zwei Listen und uneinheitliche Texte — Freigaben muessen an einer Stelle landen und aussehen wie voneinander.
- **Zielzustand:**
  - **Ein „Braucht mich“-Panel:** alle ausstehenden Freigaben (Missions-, Policy- und HITL-Gate) in einer Liste mit Quelle, Domain, Betrag/Kontext und Ablaufzeit — entsprechend der Auto-Review-Vision aus M70.
  - **Einheitliche Freigabe-Semantik:** jeder Request erhaelt dieselben Pflichtfelder (wer beantragt, was, Risiko-Einordnung, was geschieht bei Freigabe/ Ablehnung/ Ablauf).
  - **Rollenklarheit:** beantragen duerfen alle Level, freigeben nur die im Organigramm zustaendigen Rollen; der Vertretungsmodus der Policy-Engine wird zum Muster fuer alle Ebenen.
  - **Audit-Kette:** jede Freigabe/Ablehnung landet unverzueglich im Hash-Chained-Log, inkl. Replay-Schutz wie am MCP-Gateway.
  - **Escalation:** Ablauf-Timeouts und Eskalationsregeln aus der Policy-Engine gelten einheitlich auch fuer Missions- und HITL-Requests.
- **Abhaengigkeiten:** baut auf M69 (Policy-as-Code) und M70 (Braucht-mich-Panel) auf; der Context-Hygiene-Trigger (M73) ist der erste Client dieses einheitlichen Musters.

### Meilenstein 75: Strikte Rollen- & Tool-Isolation bei Agenten-Delegation (Geplant – Sehr hoch)
- **Vorlage:** `hermes-teammates` (Multi-Agent-Organisationsprinzip).
- **Zielzustand:** Bei jeder Subagenten-Delegation über `core_dispatcher` / `delegate_task` werden ausschließlich die in `agent_profiles.json` hinterlegten `tools`, `skills` und das zugeordnete Modell an den Kind-Prozess übergeben. Parent-Rechte (z. B. `terminal`, `filesystem`-Write oder `mcp`) werden nicht implizit vererbt.

### Meilenstein 76: Verifizierte Kanban-Cards mit Token-Budget & Proof-Gate (Geplant – Sehr hoch)
- **Vorlage:** `crew` (Verified-Work-Coordinator).
- **Zielzustand:** Jede automatisch bearbeitete Kanban-Card erhält ein hartes Token-Budget, einen zugewiesenen Writer-Agenten sowie einen unabhängigen Verifier-Agenten. Ein Task wechselt erst auf `Done`, wenn das hinterlegte Proof-Kommando (Test/Check) mit Exit Code `0` abschließt.

### Meilenstein 77: Agenten-Workflow-DAGs mit Fan-Out/Quorum & Resume (Geplant – Sehr hoch)
- **Vorlage:** `hermes-workflows`.
- **Zielzustand:** Ausbau des Archon-Task-Schedulers um JSON-basierte Workflow-Graphen (DAGs) mit parallelen Fan-Out-Knoten, Quorum-Entscheidung, Human-/Machine-Freigabe-Gates und Fingerprint-basiertem Replay-Skip-Resume nach Abbrüchen.

### Meilenstein 78: Mission Control Kanban — Gantt-Timeline & Dependency-Graph (Geplant – Sehr hoch)
- **Vorlage:** `kanban-gantt`.
- **Zielzustand:** Drei einheitliche Sichten auf Archons zentrale `tasks`-SQLite-Datenbank: (1) Liste/Kanban-Board, (2) Gantt-Timeline (Start/Laufzeit/Deadline) und (3) Dependency-Graph (Aufgabenkarten mit Abhängigkeits-Pfeilen, Longest-Path-Layout).

### Meilenstein 79: Lokaler verschlüsselter Offline-Memory-Vault (`compartment`) (Geplant – Sehr hoch)
- **Vorlage:** `compartment` (lokale Datenschutz-Alternative, Cloud-Memory-Provider bewusst ausgeschlossen).
- **Zielzustand:** Integration eines AEAD-verschlüsselten, komplett offline laufenden lokalen Hybrid-/Vektor-Memory-Vaults mit lokalem Embedding-Modell und ohne externe API-Keys als datenschutzkonforme Zero-Egress-Ergänzung zum Obsidian Vault.

### Meilenstein 80: Hybrid-SOP-Runner — Script + Agenten-Urteil (`opensop`) (Geplant – Hoch)
- **Vorlage:** `opensop`.
- **Zielzustand:** Erweiterung der Business-Playbooks um hybride SOP-Dateien, die deterministische Script-Schritte (z. B. Validierung, Buchung, Export) strikt von Agenten-Schritten mit Ermessensspielraum trennen.

### Meilenstein 81: Cross-Model-Verifier & Test-Wächter (`shadow-army`) (Geplant – Hoch)
- **Vorlage:** `shadow-army`.
- **Zielzustand:** Vor dem Schließen einer Kanban-Card prüft eine zweite, unabhängige Modell-Familie das Ergebnis und schlägt Alarm, falls bestehende Test-Assertions gelöscht oder umgangen wurden (ergänzt M15/M76).

### Meilenstein 82: Subagenten- & Session-Receipts (`delegation-receipts` / `session-receipts`) (Geplant – Hoch)
- **Vorlage:** `delegation-receipts`, `session-receipts`.
- **Zielzustand:** Jeder Subagent liefert ein strukturiertes Abschluss-Receipt (Status, geänderte Dateien, Proof-Command). Jede Kanban-Card-Historie lässt sich inkl. Fehlversuchen und Retries als autarkes Offline-HTML-Belegdokument exportieren.

### Meilenstein 83: Agenten-Flugschreiber & Guardrail-Backtester (`flightlog` / `policy-backtester`) (Geplant – Hoch)
- **Vorlage:** `flightlog`, `policy-backtester`.
- **Zielzustand:** Automatische Erkennung „grün fehlgeschlagener“ Runs (versteckte Tool-Errors, Loops, Token-Spikes, Effort-Collapse) sowie ein Backtest-Harness, der neue Policy-Regeln vor Aktivierung gegen historische Tool-Calls prüft.

### Meilenstein 84: Prompt-Injection-Feuerübung (`injection-range`) (Geplant – Hoch)
- **Vorlage:** `injection-range`.
- **Zielzustand:** Automatisierte Test-Suite mit präparierten Dokumenten (versteckte HTML-Kommentare, Base64, Memory-Poisoning, Reply-Hijack) zur regelmäßigen Überprüfung des Dual-LLM-Guards (M23).

### Meilenstein 85: Best-of-N Coding-Worktrees (`joust` / `multiverse`) (Geplant – Mittel)
- **Vorlage:** `joust`, `multiverse`.
- **Zielzustand:** 2–6 Coding-Agenten bearbeiten denselben Task parallel in isolierten Git-Worktrees; automatisierte Tests bestimmen den besten Patch für den anschließenden Merge nach Freigabe.

### Meilenstein 86: Quota- & Quality-Escalation-Fallback im `AgentRouter` (`vibe-relay` / `calling-mom`) (Geplant – Hoch)
- **Vorlage:** `vibe-relay`, `calling-mom`, `lean-mode`.
- **Zielzustand:** Ergänzt den bestehenden `candidate_models`-Fehler-Fallback in `backend/agent_router.py` um (1) Quota-Threshold-Routing (bei unterschrittener Rest-Quota automatisch auf günstigen Executor routen) und (2) Cheap-First-Ausführung mit automatischer Eskalation an ein Frontier-Modell bei Blockaden oder fehlgeschlagenen Checks.

### Meilenstein 87: Externe Fach-Connectoren (`inkly`, `local-business-leads`, `hermes-issue-sync`, `ghl-command`) (Geplant – Mittel)
- **Vorlage:** `inkly`, `local-business-leads`, `hermes-issue-sync`, `hermes-issue-orchestrator`, `ghl-command`.
- **Zielzustand:** Gezielte Fach-Connectoren für eSignature-Workflows (`inkly`), B2B-Lead-Generierung (`local-business-leads`), 2-Wege-Sync mit Linear/Jira/GitHub-Issues sowie GoHighLevel-CRM (`ghl-command`).

### Meilenstein 88: Optionale Spezial-Erweiterungen (`flota` / `own-compute`, `kujo-hermes`, `riah-swipe`, `manners-meter`) (Geplant – Niedrig)
- **Vorlage:** `flota`, `own-compute`, `kujo-hermes`, `riah-swipe`, `manners-meter`.
- **Zielzustand:** Evaluierung bzw. optionale Anbindung von SSH-/Cluster-Workern (`flota`/`own-compute`), Kujo-Runtime (`kujo-hermes`), Swipe-Freigabe für generierte Medien (`riah-swipe`) und Tonalitäts-Metrik (`manners-meter`).

### Meilenstein 89: Information-Flow-Taint-Tracking & Session-Versiegelung (`airlock`) (Geplant – Sehr hoch)
- **Vorlage:** `airlock`.
- **Zielzustand:** Sobald eine Session untrusted Content liest (Webseiten, fremde MCP-Outputs, Kunden-Mails), versiegelt die Engine automatisch kritische Ausgänge (Nachrichten an Dritte, Network-Writes, Pushes/Deploys, Memory-Writes) als Ergänzung zu M23.

### Meilenstein 90: Signierte, ablaufende Tool-Warrants (`hermes-tenuo`) (Geplant – Hoch)
- **Vorlage:** `hermes-tenuo`.
- **Zielzustand:** Kryptografisch signierte, zeitlich begrenzte Tool-Permissions (Warrants) mit Parameter-Constraints pro Session, Cron-Job und delegiertem Task.

### Meilenstein 91: Präzedenzfall-Gedächtnis für Kanban-Rückfragen (`precedent-log`) (Geplant – Sehr hoch)
- **Vorlage:** `precedent-log`.
- **Zielzustand:** Menschliche Antworten auf blockierte Kanban-Fragen werden als dauerhafte Rulings gespeichert (inkl. Verfalls-/Widerrufslogik) und automatisch in passende künftige Worker-Prompts injiziert.

### Meilenstein 92: Deterministischer Workflow-Freeze & Replay (`freeze` / `workflow-record`) (Geplant – Hoch)
- **Vorlage:** `freeze`, `workflow-record`.
- **Zielzustand:** Aufzeichnung erfolgreicher Browser-/Tool-Sequenzen und Kompilierung in deterministische Python-Workflows zur exakten, tokenfreien Wiederholung.

### Meilenstein 93: Code-as-Orchestration & Tool-Output-Firewall (`codemode` / `toolaria`) (Geplant – Hoch)
- **Vorlage:** `codemode`, `toolaria`.
- **Zielzustand:** QuickJS-Sandbox zur Bündelung mehrerer MCP-Tool-Calls in einem einzigen Turn (`codemode`) sowie automatische Größenbegrenzung/Zusammenfassung übergroßer Tool-Outputs vor Kontext-Injection (`toolaria`, ergänzt M73).

### Meilenstein 94: Lossless Session-DAG & Multi-Perspektiven-Research (`hermes-lcm-x` / `storm-fusion-research`) (Geplant – Hoch)
- **Vorlage:** `hermes-lcm-x`, `storm-fusion-research`.
- **Zielzustand:** Verlustfreie lokale SQLite-Session-Historie als wiederherstellbarer Summary-DAG (`hermes-lcm-x`) sowie Multi-Perspektiven-Research-Panel mit Judge und Human-Gate für das Research Lab (M45).

### Meilenstein 95: Multi-User Urlaubs-/Vertretungs-Modus & Benutzer-spezifische Telegram-Kanäle (Geplant – Hoch)
- **Ausgangslage / Architektur-Vorgabe:** Bei einem Timeout oder aktiver Abwesenheit (Urlaubsmodus) dürfen HITL- oder 4-Augen-Freigabe-Entscheidungen **niemals automatisch an einen Agenten** delegiert werden.
- **Zielzustand:**
  - **Multi-User-Vertretungskette:** Freigaben eskalieren bei Timeout oder Urlaubsmodus ausschließlich an einen hinterlegten menschlichen Stellvertreter (Multi-User-RBAC-Rolle, kein Agent-Fallback).
  - **Eigene Telegram-Kanäle pro Benutzer:** Jeder Archon-OS-User kann einen eigenen Telegram-Chat/Bot-Kanal hinterlegen, sodass Freigabe-Anfragen, Timeouts und Vertretungs-Benachrichtigungen gezielt beim jeweils zuständigen oder vertretenden Menschen landen.

### Meilenstein 96: Visueller Ergebnis-Template- & Report-Designer (Drag & Drop Variablen-Pool + Typografie-Properties) (Geplant – Sehr hoch)
- **Ausgangslage:** Ergebnisse werden im Showroom und direkt in den Aufgaben/Teilaufgaben ausgegeben; aktuell fehlt ein visueller Editor, um Ausgabe-Layouts frei zu gestalten.
- **Zielzustand:**
  - **Zweigeteilter Designer (analog Formulareditor):** Links das Druck-/Ausgabe-Blatt (Canvas), rechts ein **Variablen-Pool**, in dem sämtliche verfügbaren Task-, Projekt-, Agenten-, Token-, Kosten-, Tool- und Ergebnis-Variablen als **Drag-&-Drop-Pills** liegen und direkt auf dem Blatt platziert werden können.
  - **Eigenschafts-Inspektor je Variable:** Jede platzierte Variable besitzt individuelle Style-Properties (**Schriftgröße, Schriftart/Font, Farbe, Gewicht, Ausrichtung, Abstände**), sodass eigene Ergebnis- und Berichts-Templates per Klick als Standard-Ausgabe für Aufgaben & Showroom gespeichert werden können.

### Meilenstein 97: Einheitliche Modal-, Header- & Blur-Overlay-UI-Überarbeitung (Geplant – Hoch)
- **Ausgangslage:** Einzelne Dialoge und Modals weichen in Breite, Höhe, Z-Index und Backdrop-Blur leicht voneinander ab.
- **Zielzustand:** Systemweite Vereinheitlichung aller Detail-Modals und Overlay-Dialoge nach dem Maßstab des **System Control Center** (einheitliche feste Größe, konsistente `backdrop-blur`-Abdeckung inklusive Header-Bereich, einheitliche Abstände und Typografie).

### Meilenstein 98: Vereinheitlichte API-Key- & OmniRoute-Scope-Verwaltung (Geplant – Hoch)
- **Ausgangslage:** Eingehende Archon-API-Tokens (`API-Keys & Zugriffs-Governance` mit `read_only` / `kanban_rw` / `agent_execute` / `admin_full` Scopes) und ausgehende LLM-Provider-Keys (OpenRouter, Google/Gemini, OmniRoute, Groq, OpenAI) liegen aktuell in getrennten Bereichen.
- **Zielzustand:** Konsolidierte API-Key-Verwaltung inklusive direkter Sichtbarkeit der konfigurierten Provider-Keys sowie Verknüpfung bzw. Vereinheitlichung der Scope-Steuerung mit OmniRoute.

### Meilenstein 99: Context-Compaction Audit, Modell-dynamische Fenster & UI-Steuerung (M73-Ausbau) (Geplant – Hoch)
- **Ausgangslage:** Session-Compaction ist in M73 (`archon/routers/context_meter.py`, `backend/context_compactor.py`) grundsätzlich implementiert (`auto_compact_pct` 85 %, `auto_compact_min_messages` 24, `[HIERARCHICAL_MEMORY_STATE]`), nutzt aber aktuell ein statisches Standard-Fenster (`DEFAULT_MAX_CONTEXT_TOKENS = 32000`) und bietet keine direkte Konfiguration im Settings-UI.
- **Zielzustand:**
  - **Modell-dynamisches Kontextfenster:** Automatische Anpassung von `max_context_tokens` an das jeweils aktive LLM-Modell (z. B. 128k / 200k / 1M) statt pauschalem 32k-Limit.
  - **Settings-UI & Transparenz:** Konfigurierbare Parameter (`enabled`, `trigger_token_threshold`, `auto_compact_pct`, `keep_recent_turns`) direkt im System Control Center sowie sichtbare Compaction-Marker mit Vorher/Nachher-Einsparung im Chatverlauf.
  - **Verzahnung mit M93 & M94:** Kombination mit der Tool-Output-Firewall (`toolaria`, M93) und verlustfreier Wiederherstellung über den Session-Summary-DAG (`hermes-lcm-x`, M94).

### Meilenstein 100: KPI-Dashboard für Output-Wirtschaftlichkeit (Geplant – Hoch)
- **Ausgangslage:** Kosten liegen bereits pro Task und pro Modell vor (Token-Budgets, geschätzte und tatsächliche Kosten, Budget-Warnung vor Task-Start). Ein Deliverable hängt über die Projekt-Vault-Struktur (`01_PROJEKTE/<id>`, Ordner `03_Endprodukte`) am Task. Was fehlt, ist die Aggregation zu einer Wirtschaftlichkeitsaussage pro Prozess: Welche Kosten stehen welchem Output gegenüber, und wie entwickelt sich das über die Zeit. Ausgangspunkt war das Fachgespräch mit Aleksandar Milincic (19.11.2026) zur Cost Attribution: Prozessgrenze = Task mit explizitem done plus Deliverable-Datei; die Bewertung des Outputs bleibt menschliches Urteil.
- **Zielzustand:**
  - **Erfassen:** Pro Prozess (Task mit Deliverable) werden Kosten (Tokens, Modell, geschätzt und tatsächlich), Aufwand und Deliverable-Typ automatisch erfasst. Tasks ohne Deliverable fallen in einen sichtbaren "General"-Posten (nicht zuordenbare Kosten).
  - **Aggregieren:** Rollup pro Projekt, pro Agenten-Profil und pro Zeitraum, aufbauend auf den vorhandenen Endpunkten des Operations- und Kanban-Bereichs statt neuer Parallel-Tabellen.
  - **Vergleichen:** Zeitreihen-Ansicht zur Wirtschaftlichkeit je Output-Typ (z. B. veröffentlichtes Video, gesendete Angebotsunterlage), damit Trends sichtbar werden, ob ein Output-Typ im Verhältnis zu seinem Aufwand trägt.
  - **Bewertung bewusst manuell:** Das Dashboard liefert die belegte Kosten- und Aufwandsseite. Die Wertseinschätzung des Outputs bleibt eine menschliche Eingabe (z. B. eine einfache Nutzenskala je Deliverable), konsistent zum Grundsatz, dass das System den Nachweis liefert, nicht das Urteil.

### Meilenstein 101: Kryptographische HITL-Verifizierung per Passkey / WebAuthn (FIDO2) (Implementiert – Basis)
- **Ausgangslage / Sicherheits-Ziel:** Bei sensiblen HITL-Freigaben (z. B. Zahlungen, Budget-Überschreitungen, Projektstarts, Berechtigungen) soll technisch ausgeschlossen sein, dass ein KI-Modell oder ein kompromittierter Prompt eine Freigabe selbst auslöst oder vortäuscht. Ein reiner API-Klick reicht dafür perspektivisch nicht aus.
- **Zielzustand (Optional & zweistufig konfigurierbar in `Autonomie & Freigaben` / Settings):**
  - **1. Master-Schalter (Optional):** Passkey-/WebAuthn-Pflicht grundsätzlich **ein- oder ausschaltbar** (Standard: optional aktivierbar pro Installation/Benutzer). Unterstützt werden Google Passkey, Windows Hello, Apple Touch ID/Face ID und Hardware-Keys (FIDO2/WebAuthn via `navigator.credentials.get()` + serverseitige Challenge-Response-Signaturprüfung), optional mit TOTP-Fallback.
  - **2. Granularer Geltungsbereich:** Bei aktivierter Verifizierung wählbar zwischen **Alle HITL-Freigaben** oder **selektiv je Kategorie/Trigger** (z. B. nur Zahlungen/Finanzen, nur Projektstart, nur Budget-Überschreitung, nur destruktive System-/Egress-Aktionen).
  - **GoBD-Nachweis:** Die signierte WebAuthn-Assertion (Credential-ID, Zeitstempel, Challenge-Hash) wird direkt in der manipulationssicheren SHA-256 Audit-Chain mitprotokolliert.
  - **Dokumentations-Pflicht:** Vollständige Aktualisierung der System- und Benutzerhandbücher (Setup auf `localhost` vs. HTTPS-Domain, Passkey-Registrierung, Recovery/Vertretungs-Flow nach M95).

### Meilenstein 102: Multi-Agent Workflow-Vorlagen-Studio (Visueller DAG-Runner & Starter-Workflows) (Implementiert)
- **Ausgangslage / Ziel:** Reine Prompt-Vorlagen decken nur Einzelaufträge ab. Echte Workflows verknüpfen mehrere spezialisierte Agenten-Instanzen (Sequenz, paralleles Fan-Out/Fan-In, HITL-Gates) mit klarer Vorschau vor dem Start und direkter Bridge in Kanban, DAW-Gantt, Dependency-Graph und optionale n8n-Webhooks.
- **Umgesetzte Architektur:**
  - **Registry & Materializer (`backend/workflow_templates.py`):** 4 kuratierte Multi-Instanz-Starter-Workflows (*Wiederkehrende Content-Pipeline*, *Deep-Research -> Parallel-Analyse -> Dossier*, *Lead-Recherche -> CRM-Qualifizierung -> Angebot*, *Feature-Audit -> Security & Tests -> Release*) plus Persistenz eigener Vorlagen in `config/workflow_templates.json`.
  - **API-Endpunkte (`archon/routers/v2_capabilities.py`):** `GET /api/v2/workflows/templates`, `POST /api/v2/workflows/templates`, `DELETE /api/v2/workflows/templates/{tpl_id}`, `POST /api/v2/workflows/templates/{tpl_id}/run` (legt verknüpfte Tasks + `task_links` + `kanban_meta.json` inkl. SOUL/Tool-Preset/HITL/Cron an und triggert optional einen n8n-Webhook).
  - **Visuelles DAG-Studio (`static/js/workflow_templates_studio.js`):** Integriert im Tab `n8n-Automation` mit Layer-basierter SVG-Knotenvorschau vor der Ausführung, Schritt-Inspektor, Variablen-Eingabe, eigenem Schritt-Editor und direktem Sprung in das Kanban-Board.
- **Dokumentation:** Siehe [WORKFLOW_TEMPLATES_GUIDE.md](WORKFLOW_TEMPLATES_GUIDE.md).

### Meilenstein 103: Treasury-, Wallet- & Passkey-gesichertes Zahlungs-Cockpit (Implementiert)
- **Ausgangslage / Ziel:** Zentrale Übersicht über Liquidität (Bankkonten, PayPal, Stripe, Krypto-Wallets *Watch-Only* und gedeckelte *Agent-Allowance*-Wallets), kategorisierte Ausgaben und eine unumgehbare Passkey-/HITL-Zahlungsfreigabe.
- **Sicherheits-Prinzip (Zero-Trust / Cornell-Yale-Schutz):** Ist Passkey-HITL (`payments`) aktiv, kann kein KI-Agent selbstständig Zahlungen ausführen oder Limits erhöhen — jede Ausgabe landet zwingend in der Freigabe-Queue und erfordert die menschliche WebAuthn-/Handy-Passkey-Signatur.
- **Implementierte Komponenten:**
  - `backend/treasury_engine.py` (SQLite WAL `data/treasury.db`, Idempotency-Keys, Empfänger-Allowlists, SHA-256 Hash-Chain)
  - API-Endpunkte in `archon/routers/v2_capabilities.py` (`/api/v2/treasury/*`)
  - Frontend-Cockpit `static/js/treasury_studio.js` im Subtab **Treasury** unter **Rechnungswesen & Finanzen**.
- **Dokumentation:** Siehe [TREASURY_PAYMENTS_GUIDE.md](TREASURY_PAYMENTS_GUIDE.md).

### Meilenstein 104: Operations-Kalender 2.0 (Eigene Kalender-Engine, Layer, CalDAV/Google/Outlook/.ics & Event-Bus) (Implementiert)
- **Ausgangslage / Ziel:** Ablösung des einfachen Listen-Kalenders durch einen vollwertigen Outlook-/Google-Calendar-Arbeitsplatz (ohne den separaten CRM-Kalender zu vermischen) — komplett in eigenem, direkt anpassbarem Vanilla-JS-Code ohne Fremdbibliothek.
- **Umgesetzte Architektur:**
  - **Frontend (`static/js/operations_calendar.js`):** Tag-/Wochen-/Monats-/Jahres-/Agenda-Ansicht mit Überlappungs-Spalten, Drag & Drop, Resize, Slot-Klick, Mini-Monatskalender, 6 ein-/ausblendbaren Farblayern (*Termine*, *Fokusblöcke*, *Kanban-Deadlines*, *Workflow-Cron-Jobs*, *ERP/Zahlungen*, *Externe Kalender*) und vollem Termindetail-Editor inkl. Serienterminen sowie Settings-Integration (`#settings-tab-comm`).
  - **Backend & Sync (`backend/operations_calendar.py`, `archon/routers/operations_calendar.py`):** `PATCH /events/{id}`, `.ics`-Import/Export, externe Kalender-Quellen (Google ICS, Outlook/M365 ICS, Apple/Nextcloud CalDAV) und KI-Fokuszeit-Finder (`/focus-slots`).
  - **Trigger-Bus-Anbindung:** `create_event`, `update_event`, `sync_source` und fällige Tagestickets (`calendar.due`) speisen automatisch den zentralen Event-Bus (`backend/workflow_scheduler.py`).
- **Dokumentation:** Siehe [OPERATIONS_CALENDAR_GUIDE.md](OPERATIONS_CALENDAR_GUIDE.md).

### Meilenstein 105: Event-Bus Governance (Trigger-Matrix, Rate-Limits, Loop-Schutz & Replay) (Implementiert)
- **Ausgangslage / Ziel:** Verständliche, zentrale Steuerung für alle über den Event-Bus verbundenen Module (Watchdog, Posteingang, Kalender, Research Lab, AI Boardroom, Freigaben, Treasury) nach Industriestandard (AWS EventBridge / Circuit-Breaker / DLQ-Replay).
- **Umgesetzte Architektur:**
  - **Policy-Matrix & Circuit-Breaker (`backend/workflow_scheduler.py`):** Tabelle `event_bus_policies` für `allow` / `require_hitl` / `deny` pro Quelle × Ziel-Domäne (`workflow`, `treasury`, `comms`, `system`), konfigurierbare Rate-Limits (`/min`), Loop-Schutz (`correlation_id`) und Event-Replay (`replay_workflow_event`).
  - **API & UI (`archon/routers/v2_capabilities.py`, `static/js/workflow_templates_studio.js`):** `/api/v2/workflows/event-policies`, `/events/{id}/replay` sowie der interaktive Tab **Trigger-Matrix (Rechte & Schutz)** direkt unter **Telemetrie & Logs → Event-Bus**.
- **Dokumentation:** Siehe [EVENT_BUS_GOVERNANCE_GUIDE.md](EVENT_BUS_GOVERNANCE_GUIDE.md).

### Meilenstein 106: SQLite-Datenbank-Konsolidierung (`28 → 3` Domänen-DBs) (Implementiert)
- **Ausgangslage / Ziel:** 28 verstreute SQLite-Einzeldateien erzeugten unnötigen File-Descriptor-Overhead, unübersichtliche Backups und Split-Brain-Risiken.
- **Umgesetzte Architektur:**
  - `backend/db_consolidation.py` & `backend/db_paths.py` führen alle Tabellen kollisionsfrei (`<legacy_stem>__<table>`), idempotent und mit automatischem Backup in `data/ops.db`, `data/business.db` und `data/memory.db` (jeweils WAL-Modus, `busy_timeout=5000`, `PRAGMA integrity_check`) zusammen.
  - Vollständige Einbindung in `backend/tenant_context.py` (`CONSOLIDATED_TENANT_DBS`) und `backend/db_backup_manager.py` (`DB_TARGETS`).
  - Admin-API: `GET /api/v2/system/db-consolidation/plan`, `POST /api/v2/system/db-consolidation/run`.

### Meilenstein 107: Multi-Channel Content-Maschine v1 & v2 (LinkedIn, YouTube Longform & Shorts, TikTok, X/Threads) (Implementiert)
- **Ausgangslage / Ziel:** Archon OS soll neben der Unternehmenssteuerung als vollwertige Multi-Agenten-Content-Maschine arbeiten.
- **Umgesetzte Architektur (`backend/content_machine.py`, `archon/routers/content_machine.py`):**
  - **Repurposing-DAG (`run_campaign_repurpose_dag`):** `n_research` → `n_master_brief` → paralleles Fan-Out auf 5 Kanäle (`linkedin`, `youtube_longform`, `youtube_shorts`, `tiktok`, `x_threads`) → `n_editorial_gate` (HITL-Freigabe).
  - **Content-Maschine v2:** Deterministisches **Anti-AI-Slop- & Quality-Gate** (`evaluate_asset_quality`), **Quellen-Ingestion** (`POST /api/v2/content-machine/ingest` für URL mit SSRF-Schutz, Obsidian-Vault mit `path_jail` und Transkripte), **9:16-Video-Clip-Matrix** (`POST /api/v2/content-machine/campaigns/{id}/clip-matrix`), **Publishing-Webhook-Bridge** (`dispatch-webhook`), **Due-Publish-Sweep** (`publish-due`) und Performance-Feedback-Loop (`record_asset_metrics` → `memory.db`).

### Meilenstein 108: Next.js 16 UI-Konsolidierung gegen Archon FastAPI (Implementiert)
- **Ausgangslage / Ziel:** Direkte Anbindung des Next.js-16-Frontends (`frontend/`) an Archon FastAPI ohne PocketBase-Abhängigkeit.
- **Umgesetzte Architektur:**
  - Server-seitiger Proxy `frontend/src/app/api/archon/[...path]/route.ts` und typisierter Client `frontend/src/lib/archon-api.ts`.
  - Neue Arbeitsplätze: `/content-studio` (`ContentMachineCockpit.tsx`), `/workflows` (`WorkflowDagCockpit.tsx`) und `/cockpit` (`ExecutiveCockpit.tsx` für Health, 28→3 DB-Status, Kanban, HITL-Freigaben, DAG-Runs, Content-Pipeline & CRM).

### Meilenstein 109: Code Mode — Token-Effizienz ohne Sicherheitsverlust (Geplant)
- **Ausgangslage / Ziel:** ~180–250 REST-Endpunkte + MCP-Tools verbrauchen als vollständige JSON-Schemas im Kontext der 70 Spezialisten unnötig viele Tokens.
- **Zweistufige Ziel-Architektur:**
  - **M109a (Deferred Tool/Endpoint Discovery):** 3 schlanke Meta-Tools (`search_capabilities`, `describe_capability`, `call_capability`) über `backend/tool_runtime.py` (~800–1.000 Token Footprint) unter Beibehaltung von JSON-Schema-Typing, M75/M89/M90 und RBAC.
  - **M109b (Isolierte Code-Sandbox + Capability-Broker):** Erst nach vollständiger Härtung von M75/M89/M90 und ausschließlich in echter Prozess-/Wasm-Isolation (kein FS/Env, `network_mode: none`), gekoppelt an einen Capability-Broker (Method+Path-Allowlist, Secret-Masking auf Write-Payloads, Code-Review-Pflicht via `PreDecision` für `write`/`destructive`).

### Meilenstein 110: Execution Hardening — Idempotency, Effect-Ledger, Leases & Plan-Validator (Abgeschlossen in v0.5.7)
- **Ziel:** Verhindern von Doppel-Effekten (z. B. doppelte E-Mails, Posts, Zahlungen) bei Timeouts/Restarts sowie deterministische DAG-Prüfung vor dem Start.
- **Kernbausteine:**
  - Harness-generierte Idempotency-Keys (`task_id:step_id:tool`) stabil über Retries (nie vom LLM erzeugt).
  - Effect-Ledger mit `PENDING → COMMITTED / FAILED / UNKNOWN` inkl. verpflichtender Reconciliation vor Retry nach `UNKNOWN`.
  - Pre-Execution Plan Validator (Zyklen, Schema, Input-Mapping, Budget, Deadline, RBAC, HITL-Pflicht) + harter `replan_count`-Deckel + Worker-Leases/Heartbeats.
- **Umsetzung (v0.5.7):** `backend/event_mesh.py` (`EffectLedger`, Outbox mit Idempotency-Key, Reconciliation aus `UNKNOWN`, DLQ), `backend/deadlock_supervisor.py` (atomare Leases, `os.kill(pid, 0)`-Liveness, CAS-Reset, 120-s-Schwelle), `backend/workflow_dag_runner.py` (`validate_dag_def()` mit Kahn-Toposort, `request_dag_replan()` mit Cap 2). Idempotency-Keys sind derzeit event-/asset-basiert; das kanonische Format `task_id:step_id:tool` ist noch offen.

### Meilenstein 111: Isolation & Resilience — Bulkheads, Tool-Output-Caps & Circuit-Breaker (Geplant)
- **Ziel:** Schutz von Kontextfenstern, Event-Loop und Provider-Quotas unter Last oder bei Drittanbieter-Ausfällen.
- **Kernbausteine:**
  - Getrennte Scheduling-Klassen (Interaktiver Chat vs. Background-DAGs vs. Eval-Läufe vs. Approval-Blocked).
  - Tool-Output-Größenlimits & Bulkheads pro Tool/Task (Wall-Clock, Call-Count, Token-Cap), damit z. B. 40-KB-Stacktraces nicht den LLM-Kontext vergiften.
  - Provider-Circuit-Breaker (Fehlerrate / 429-Quota / Latenz → Open) inkl. Fallback-Hierarchie und Backpressure-Propagierung.

### Meilenstein 112: OTel GenAI Tracing & Trace-to-Eval-Pipeline (Geplant)
- **Ziel:** Vollständige End-to-End-Beobachtbarkeit und systematische Regressionstests aus realen Produktiv-Runs.
- **Kernbausteine:**
  - Durchgängige `trace_id` vom API-Gateway über `backend/llm_kernel.py` bis zu Tool-Calls und DAG-Nodes (Kosten, Latenz, PII-redaktierte Payloads).
  - 1-Klick-Export von fehlgeschlagenen oder erfolgreichen Traces als deterministische Test-Fixtures in `backend/eval_gates.py`.

### Meilenstein 113: Content-Maschine Safety & Lifecycle Governance (Geplant)
- **Ziel:** Produktionsreife Marken-, Rechts- und Budget-Sicherheit für autonome Multi-Channel-Publikationen.
- **Kernbausteine:**
  - Dedizierter Moderation-/Brand-Safety-Second-Pass („Not this one“) vor Publish (Verleumdung, Markenrechte, unbelegte Claims).
  - Globaler Kill-Switch + tägliche Spend-/Publish-Caps pro Plattform und Modell.
  - Asset-Retirement & Update (Auffinden/Zurückziehen veralteter Assets), geplanter 30-Tage-Derivate-Schedule und Trennung zwischen Neugenerierung (volles Review) und reinem Crop.

### Meilenstein 114: Multi-Agent- & Content-Machine-Roadmap — Abschluss aller 28 Punkte (Abgeschlossen)
- **Ziel:** Die 2026er Audit-/Feature-Roadmaps (Abschnitt 6: Multi-Agenten-Orchestrierung, 12 Punkte; Abschnitt 7: Content-Machine, 16 Punkte) vollständig in den Produktionscode überführen — nicht nur Bausteine anlegen, sondern sie in Hot Paths verdrahten, härten und mit Regressionstests absichern.
- **Umsetzung in vier Batches:**
  - **A — Quick Wins:** CI `validate --strict` + SSOT-Drift-Check, Oracle-SSRF + dynamisches Datum, Research-Verdict-Key, decision_id bei manueller Freigabe, Kampagnen-Status `idea`, harte Kanal-/Fact-Check-Blocker, A/B-API, Feedback-Loop.
  - **B — Orchestrierung:** Event-Push statt 10-s-Polling (`subscribe_events`/`unsubscribe_events`, konfigurierbare Deadlines), zentrale Cancel-Kette Mission Control → Dispatch → DAG → Boardroom, deterministischer Konsens (Boardroom + Fan-in statt `aggregation_lisa`).
  - **C — Safety & Compliance:** Shared Task Queue mit Idempotenz/Priorität/CAS-Leases, Agent-Memory-Scope mit ACL/TTL inkl. Delegationsbindung, Plagiat-/Copyright-Gate, SEO-HITL statt Direkt-Publish.
  - **D — Vollendung:** Typisierte A2A-Envelope, Acceptance Criteria + Handoff-Kompression, Eval-/Promotion-Gates, Supervisor-Rollover, Research-Dossier, Editorial-Rollen/Historie, Skill-Injektion (`li-human`), GEO-Citation-Check, `idea`-Badge und Media-Handoff im Frontend.
- **Status:** 28/28 Punkte umgesetzt. Detailübersicht mit Datei- und Testreferenzen: `docs/system/MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md`.
- **Hinweis:** Die Regressionstests sind geschrieben, aber in der Entwicklungssession nicht ausgeführt worden (kein Python-Interpreter im Shell-Pfad); CI muss sie beim nächsten Lauf verifizieren.

## Ideen-Pool (beobachten, nicht geplant)

Themen, die im Blick bleiben, aber keinen Meilenstein und keinen Zeitslot haben. Sie werden erst dann zu Meilensteinen, wenn ein klarer Nutzen oder ein Community-Signal vorliegt.

- **Externe Website-MCP-Endpunkte (Policy-gesteuert):** Aktuelle Dienste (YC-Startups, Stand November 2026) verwandeln beliebige Websites in MCP-Server — fuer Agenten ein Universaladapter fuer Seiten ohne API. Potentiell anschlussfaehig ans MCP-Gateway (M48), aber mit Spannung zur Zero-Egress-Ausrichtung: Anfragen und uebermittelte Daten laufen dann durch einen Drittanbieter. Denkbar nur als Policy-gesteuerte Option fuer unkritische Domaenen (Recherche, Behoerdenformulare), niemals fuer Finanzen/Compliance.
