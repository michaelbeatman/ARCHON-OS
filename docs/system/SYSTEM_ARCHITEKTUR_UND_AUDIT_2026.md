# AgenticOS-2026 (Archon OS) – Vollständige Systemanalyse & Architektur-Dokumentation

*Stand: 14. Oktober 2026 | Antigravity Engine 2.0 Audit*
*Maschinenlesbares Gegenstück:* [`docs/system/system_architecture_spec.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/docs/system/system_architecture_spec.json)

---

## 1. Systemübersicht & Topologie

AgenticOS-2026 (Archon OS) ist ein modulares, containerisiertes Betriebssystem für autonome Multi-Agenten-Netzwerke. Das System verbindet eine FastAPI-basierte Steuerzentrale (Port 8501) mit spezialisierten Sub-Diensten für LLM-Routing, Workflow-Automatisierung, relationale Datenspeicherung und Agenten-Zustandsverwaltung.

### 1.1 Aktive Container-Landschaft (Docker Runtime)

| Container | Host-Port | Interne Rolle | Status | Datenpfad / Volume |
| :--- | :--- | :--- | :--- | :--- |
| **ARCHON-OS** | `:8501` | Zentrales Gateway, FastAPI Monolith & Frontend UI | **UP** | `./` (Bind-Mount), `/app/data` |
| **omniroute** | `:20128` | Multi-Provider LLM-Router (OpenAI, Anthropic, Gemini, Groq, DeepSeek) | **HEALTHY** | `omniroute-data` |
| **hermes** | `:8644` (-> `:8642`) | Autonomer Agenten-Daemon, Session-State & Task-Execution | **UP** | `~/.hermes`, `kanban.db` |
| **Pocketbase** | `:8090` | Relationale Datenbank für CRM, Kontakte, Korrespondenz & Kalender | **UP** | `./pocketbase/pb_data` |
| **Pocketbase-Media** | `:8092` | Asset-, Audio- & Medien-Speicher | **UP** | `./pocketbase-media` |
| **CRM** | `:3005` | Dediziertes Web-Frontend für Vertrieb & Kontaktverwaltung | **UP** | `./CRM` |
| **n8n** | `:5678` | Event-Trigger & Low-Code Workflow-Automatisierung | **UP** | `n8n_data` |
| **docker-socket-proxy** | `:2375` (intern) | Abgesicherter Zugriff auf die Docker-API für Subagenten | **UP** | `/var/run/docker.sock` |
| **anything-llm** | `:3001` | Lokale RAG-Engine & Vektorspeicher für Wissensarchive | **HEALTHY** | internes Storage |
| **freellmapi** | `:3002` | Fallback-Proxy für kostenfreie LLM-Endpunkte | **HEALTHY** | intern |
| **hermes-dashboard** | `:9119` | Visualisierungs-Dashboard für Hermes-Sitzungen | **UP** | intern / proxy `:9120` |

---

## 2. Speicher-Architektur & Persistenzschichten

Das System nutzt eine getrennte Persistenzstrategie:

1. **SQLite WAL-Datenbanken (Transaktional & Systemzustand):**
   - [`data/agentic_memory.db`](file:///c:/.Antigravity-projekte/AgenticOS-2026/data/agentic_memory.db): Zentraler Zustandsspeicher mit Write-Ahead-Logging (WAL). Enthält die 5 Standardtabellen: `user_profile`, `learnings`, `kv_store`, `tasks` und `conversations`.
   - `/opt/data/kanban.db`: Hermes Task-Queue & Kanban-Boards (`tasks`, `task_comments`, `task_events`, `task_links`). **Single Source of Truth** für alle operativen Aufgaben.
   - `/opt/data/state.db`: Hermes Sitzungshistorie, Prompt-Kontexte und Interaktionslogs.
   - `pocketbase/pb_data`: SQLite-Datenbank der CRM-Instanz für Kontakte, Nachrichtenverläufe und Bewerbungen.

2. **JSON-Deklarationen & Sidecar-Dateien:**
   - [`agent_profiles.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/agent_profiles.json): 57 vollständige Agenten-Profile mit System-Prompts, Tool-Scopes, Avataren und Modell-Routings.
   - [`config/kanban_meta.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/kanban_meta.json): Sidecar-Metadaten (WIP-Limits, Obsidian-Verknüpfungen, Tags). Geschützt durch prozessweiten Mutex und atomaren Dateiaustausch via [`backend/kanban_sidecar.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/backend/kanban_sidecar.py).
   - [`config/org_hierarchy.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/org_hierarchy.json): Interaktives Ablaufdiagramm (56 Knoten, 55 Berichtslinien).
   - [`config/teams.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/teams.json): Zuordnung der 6 Fachbereiche (Strategie, Tech, Recht, Immobilien, Growth, Operations).

---

## 3. Workflow-Engine & Board-Architektur

### 3.1 Operations Kanban als Single Source of Truth
Die operative Steuerung (Aufgabenerstellung, Zuordnung, Bearbeitung, Review und Abschluss) läuft vollständig über das **Operations Kanban** (`kanban.db`).
- 5 Standard-Spalten: `To-Do`, `In Bearbeitung`, `Review & QA`, `Blockiert`, `Abgeschlossen`.
- Spaltenkörper besitzen eine dezente 10 %-Tönung der jeweiligen Header-Farbe (`rgba(..., 0.10)`), um optische Klarheit zu schaffen.

### 3.2 Mission Control als Live-Projektion (Monitoring)
Die Startseite **Mission Control** dient als reines Monitoring-Cockpit:
- Liest live aus `kanban.db` (keine parallele Datenwelt mehr).
- 7/12-Board links zur Beobachtung des aktuellen Durchlaufs.
- 5/12-Seitenleiste rechts mit einer dedizierten Box für **Aktive Aufgaben** (`in_progress` mit Live-Stoppuhr) sowie Flottenlast und Kostenwächter.
- Aufgabenanlage und -bearbeitung erfolgen gezielt in Operations Kanban oder im Agentenkader.

### 3.3 Delegation, Synthese & Governance-Kaskade
1. **Strategische Aufgabenteilung:** Chef-Stratege Robert (`executive_decision_architect`) zerlegt komplexe Vorhaben in Teilaufgaben für Fachagenten.
2. **Fan-in-Synchronisation:** Sobald alle Teilaufgaben den Status `completed` erreichen, startet die Synthese automatisch. Der Prozess wird durch einen Prozess-Lock (`_MC_DATA_LOCK`) geschützt, um Doppelstarts durch parallele Fertigmeldungen zu verhindern.
3. **Synthese-Qualitätsprüfung (Marker-Kontrakt):** Lisa (`aggregation_lisa`) bündelt die Fachberichte. Die Ausgabe wird auf das Vorhandensein des Markers `SYNTHESE-BEREIT` geprüft. Fehlt der Marker, greift eine automatische Reparatur-Schleife.
4. **Strikte Robert-Freigabe:** Robert prüft den konsolidierten Bericht. Nur eine explizite Freigabe in der ersten Zeile (`FREIGABE`) schließt das Projekt ab. Alle anderen Rückmeldungen wandern zur manuellen Prüfung in die `review`-Spalte des Kanban-Boards.

---

## 4. Kommunikations- und Triage-Eingang (Inbox & Telegram)

- **Posteingang (Triage):** Dreispaltige Übersicht in [`views/view_inbox.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/views/view_inbox.py):
  1. *Intern:* System-Logs, Docker-Events, Approval-Gates.
  2. *E-Mail:* Aus Posteo/IMAP synchronisierte Nachrichten (`/opt/data/inbox/emails/`).
  3. *Telegram:* Echtzeit-Stream eingehender Benutzernachrichten (`/opt/data/inbox/telegram/`).
- **Telegram-Integration:** Der Hermes-Telegram-Adapter ([`scripts/patches/hermes_telegram_adapter.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/scripts/patches/hermes_telegram_adapter.py)) ist als Volume-Mount im Hermes-Container eingebunden:
  - Spiegelt eingehende Nachrichten automatisch als strukturierte JSON-Dokumente in das Archon-Postfach.
  - Nutzt für interaktive HITL-Entscheidungsbuttons (Freigeben / Ablehnen) sauberes HTML-Escaping, um Transportfehler auszuschließen.

---

## 5. Ist-Analyse gegen die 7 Antigravity-Säulen

| Säule | Vorgabe | Aktueller Zustand | Status |
| :--- | :--- | :--- | :--- |
| **1. Kernel & Scheduling** | Daemon auf Port 8420, Tickless Sleep, Watchdog 30s | Watchdog läuft in eigenem Thread (`watchdog_daemon.py`); App läuft primär auf Port 8501 via Uvicorn. | **Teilweise** |
| **2. Prozessmodell** | Subagenten als Prozesse, Task-Zustände, Crash-Recovery, Concurrency Throttle | 57 Profile aktiv; Tasks über SQLite nachverfolgt; Hermes-Dispatcher begrenzt Worker-Prozesse. | **Erfüllt** |
| **3. Device Driver (MCP)** | MCP Server-Ecosystem, `mcp__{server}__{tool}`, Lock-Scheduler | MCP-Treiber für CRM (`archon_crm_mcp.py`) und n8n aktiv; Werkzeugaufrufe über Docker-Proxy abgesichert. | **Teilweise** |
| **4. Dateisystem & RAM** | SQLite WAL, 5 Tabellen, atomare Sidecars | Vollständig mit WAL in SQLite, `kanban_sidecar.py` für Metadaten-Atomarität und Obsidian-Vault-Ablage. | **Erfüllt** |
| **5. Hardware-Routing** | Multi-Provider Routing über OmniRoute, Logit-Snapshots | OmniRoute läuft stabil auf Port 20128 und verteilt Anfragen dynamisch auf OpenAI, Anthropic, Gemini und freie Endpunkte. | **Erfüllt** |
| **6. Governance & Sicherheit** | RBAC, HITL-Approval, manipulationssicheres Audit-Log, Injection-Filter | 25 Prompt-Injection-Muster in [`local_security_guard.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/local_security_guard.py) aktiv; HITL-Schranken auf Board und Telegram aktiv. | **Erfüllt** |
| **7. Selbst-Evolution** | Dynamisches Laden & Testen neuer Skills | [`core_skills_engine.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/core_skills_engine.py) kann Skills generieren und automatisiert testen. | **Teilweise** |

---

## 6. Zusammenfassung & Nächste Optimierungsschritte

1. **Vollständige Vereinheitlichung der Datenzugriffe:**
   - Ausmusterung verbliebener Hilfszugriffe auf `mission_control_data.json` zugunsten nativer SQLite-Abfragen auf `kanban.db` (`task_links`).
2. **Kryptografische Hash-Kette für das Audit-Log:**
   - Chaining aller getroffenen Entscheidungen (`hash = SHA256(prev_hash + timestamp + payload)`) zur lückenlosen Nachvollziehbarkeit.
3. **Ausbau der automatisierten E2E-Testsuiten:**
   - Kontinuierliche Regressionstests für den gesamten Lebenszyklus: Telegram-Eingang -> Triage-Inbox -> Task-Erstellung -> Delegation -> Fan-in-Synthese -> Freigabe.
