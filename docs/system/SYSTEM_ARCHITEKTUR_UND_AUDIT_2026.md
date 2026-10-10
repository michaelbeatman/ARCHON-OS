# AgenticOS-2026 (Archon OS) – Vollständige Systemanalyse & Architektur-Dokumentation

*Stand: Oktober 2026 | Antigravity Engine 2.0 Audit*
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

---

## 2. Speicher-Architektur & Persistenzschichten

Das System nutzt eine getrennte Persistenzstrategie:

1. **SQLite WAL-Datenbanken (Transaktional & Systemzustand):**
   - [`data/agentic_memory.db`](file:///c:/.Antigravity-projekte/AgenticOS-2026/data/agentic_memory.db): Zentraler Zustandsspeicher mit Write-Ahead-Logging (WAL). Enthält die 5 Standardtabellen: `user_profile`, `learnings`, `kv_store`, `tasks` und `conversations`.
   - `/opt/data/kanban.db`: Hermes Task-Queue & Kanban-Boards (`tasks`, `task_comments`, `task_events`, `task_links`).
   - `/opt/data/state.db`: Hermes Sitzungshistorie, Prompt-Kontexte und Interaktionslogs.
   - `pocketbase/pb_data`: SQLite-Datenbank der CRM-Instanz für Kontakte, Nachrichtenverläufe und Bewerbungen.

2. **JSON-Deklarationen (Single Source of Truth):**
   - [`agent_profiles.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/agent_profiles.json): 56 vollständige Agenten-Profile mit System-Prompts, Tool-Scopes, Avataren und Modell-Routings.
   - [`config/org_hierarchy.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/org_hierarchy.json): Interaktives Ablaufdiagramm (56 Knoten, 55 Berichtslinien, Canvas 3200 × 4000 px).
   - [`config/teams.json`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/teams.json): Zuordnung der 6 Fachbereiche (Strategie, Tech, Recht, Immobilien, Growth, Operations).

---

## 3. Ist-Analyse gegen die 7 Antigravity-Säulen

| Säule | Vorgabe | Aktueller Zustand | Status |
| :--- | :--- | :--- | :--- |
| **1. Kernel & Scheduling** | Daemon auf Port 8420, Tickless Sleep, Watchdog 30s | Watchdog läuft in eigenem Thread (`watchdog_daemon.py`, 60s); App läuft primär auf Port 8501 via Uvicorn. | **Teilweise** |
| **2. Prozessmodell** | Subagenten als Prozesse, Task-Zustände, Crash-Recovery, Concurrency Throttle | 56 Agentenprofile aktiv; Tasks werden über SQLite nachverfolgt; Concurrency-Drossel (Semaphore) noch nicht global verdrahtet. | **Teilweise** |
| **3. Device Driver (MCP)** | MCP Server-Ecosystem, `mcp__{server}__{tool}`, Lock-Scheduler | MCP-Treiber für CRM (`archon_crm_mcp.py`) und n8n aktiv; Lock-Scheduler für Tool-Ratenbegrenzung fehlt. | **Teilweise** |
| **4. Dateisystem & RAM** | SQLite WAL, 5 Tabellen, LRU-K Eviction bei 80% Quota | Vollständig in [`local_memory_bridge.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/local_memory_bridge.py) mit WAL und Decay-Logik implementiert. | **Erfüllt** |
| **5. Hardware-Routing** | Multi-Provider Routing über OmniRoute, Logit-Snapshots | OmniRoute läuft stabil auf Port 20128 und verteilt Anfragen dynamisch auf OpenAI, Anthropic, Gemini und lokale Modelle. | **Erfüllt** |
| **6. Governance & Sicherheit** | RBAC, HITL-Approval, manipulationssicheres Hash-Chain Audit-Log, Injection-Filter | 25 Prompt-Injection-Muster in [`local_security_guard.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/local_security_guard.py) aktiv; kryptografische Hash-Kette und strikte Nutzer-Rechtegruppen fehlen noch. | **Teilweise** |
| **7. Selbst-Evolution** | Dynamisches Laden & Testen neuer Skills | [`core_skills_engine.py`](file:///c:/.Antigravity-projekte/AgenticOS-2026/core_skills_engine.py) kann Skills generieren und automatisiert mit Pytest testen. | **Teilweise** |

---

## 4. Live-Funktionsprüfung (Ergebnisse des Smoke-Tests)

- **Erfolgreich geprüfte Kern-Endpunkte:**
  - `/health` und `/api/system/health`: 200 OK (System-Status & Hermes-Verbindung grün)
  - `/api/v1/services`: 200 OK (alle 10 Container registriert)
  - `/api/operations/org-chart` & `/api/operations/org-hierarchy`: 200 OK (alle 56 Agenten und 55 Verbindungen live geladen)
  - `/api/operations/kanban/tasks`: 200 OK (Task-Pipeline ansprechbar)
  - `/api/views/inbox/items` & `/api/views/library/vault/tree`: 200 OK (Posteingang & Obsidian-Vault intakt)
  - `/api/guardian/stats` & `/api/v1/hud/telemetry`: 200 OK (Telemetrie und Kostenwächter aktiv)
- **Laufzeit-Hinweis:**
  - Der Aufruf `/api/agents/profiles` benötigte beim ersten Initialisieren über 5 Sekunden, da alle 56 Profile frisch gegen die Platten-Caches abgeglichen wurden. Eine Caching-Optimierung im RAM verhindert diesen Timeout bei Folgeaufrufen.

---

## 5. Konkrete Vorschläge für neue Funktionen und Mechanismen

1. **Globaler Concurrency Throttle (Asyncio Semaphore):**
   - Verhindert Systemabstürze oder 99% CPU-Spitzen, indem maximal 4–6 LLM-intensive Agenten gleichzeitig Berechnungen ausführen dürfen; weitere Tasks warten in einer FIFO-Warteschlange.
2. **Kryptografische Hash-Kette für das Audit-Log (Blockchain-Lite):**
   - Jede Entscheidung und jeder Tool-Aufruf erhält einen SHA-256-Hash, der den vorherigen Hash einbindet (`hash = SHA256(prev_hash + timestamp + payload)`). Macht alle Agenten-Handlungen revisionssicher und manipulationsfest.
3. **Dedicated Telegram-Bot Singleton Lock:**
   - Ein dateibasierter oder Redis-gestützter Lock-Mechanismus für das Profil `telegram_bot`. Verhindert, dass konkurrierende Container-Instanzen denselben Telegram-Polling-Token abrufen und Konflikte erzeugen.
4. **Codebase-Bereinigung & Auslagerung:**
   - Verschieben der ca. 30 Test-Screenshots, temporären Skripte (`build_batch*.py`) und veralteten `.bak`-Dateien in ein geordnetes Archivverzeichnis, um die Repository-Größe zu halbieren.
