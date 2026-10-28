# Archon OS – Systemarchitektur & Betriebshandbuch

Dieses Handbuch dokumentiert die technische Infrastruktur, Schnittstellen und Arbeitsabläufe von Archon OS. Es dient als Referenz für Systemarchitektur, tägliche Bedienung und Notfallmaßnahmen.

---

# Teil 1: Technische Systemarchitektur

## 1. Topologie & Container-Infrastruktur

Archon OS läuft als verteiltes System aus 13 Docker-Containern im internen Netzwerk `agenticos-network`.

```mermaid
flowchart TD
    subgraph Host["Host-System (Windows / Ubuntu)"]
        Browser["Web-Browser (Benutzer)"]
        LocalData["Persistente Verzeichnisse (SQLite, Obsidian Vault, Logs)"]
    end

    subgraph CoreNetwork["Docker-Netzwerk: agenticos-network"]
        ArchonOS["ARCHON-OS (Port 8501)\nFastAPI Backend + UI"]
        DockerProxy["docker-socket-proxy (Port 2375)\nDocker API Bridge"]
        
        Hermes["hermes (Port 8644/8642)\nAgent Execution Engine"]
        HermesDash["hermes-dashboard (Port 9119)\nReact / Vite Management UI"]
        
        Paperclip["paperclip-orchestrator (Port 3180)\nTask Queue & Backup Scheduler"]
        OmniRoute["omniroute (Port 20128)\nMulti-Model LLM Gateway"]
        
        PocketBase["Pocketbase (Port 8090)\nCRM & Metadaten"]
        PocketMedia["Pocketbase-Media (Port 8092)\nMediendateien"]
        CRMFront["CRM (Port 3005)\nNext.js Interface"]
        
        N8N["n8n (Port 5678)\nWorkflow Automation"]
        AnythingLLM["anything-llm (Port 3001)\nRAG & Knowledge Base"]
        FreeLLM["freellmapi (Port 3002)\nLokales Inferenz-Fallback"]
    end

    Browser -->|HTTP 8501| ArchonOS
    Browser -->|HTTP 3005| CRMFront
    Browser -->|HTTP 9119| HermesDash
    Browser -->|HTTP 5678| N8N

    ArchonOS -->|REST| DockerProxy
    ArchonOS -->|HTTP / Exec| Hermes
    ArchonOS -->|REST / SQLite| PocketBase
    ArchonOS -->|HTTP 20128| OmniRoute
    ArchonOS -->|Webhooks| N8N
    ArchonOS -->|Dateizugriff| LocalData
```

### Port-Matrix aller Dienste

| Container | Externer Port | Interner Port | Protokoll | Funktion |
|---|---|---|---|---|
| `ARCHON-OS` | `8501` | `8501` | HTTP / WS | Haupt-Backend (FastAPI), Web-UI, Dispatcher, Session-Management |
| `docker-socket-proxy` | `2375` | `2375` | HTTP (REST) | Abgesicherter Zugriff auf den Docker-Socket |
| `hermes` | `8644` | `8642` | HTTP / Exec | Autonome Agenten-Ausführung, Tool-Aufrufe, Poller-Prozess |
| `hermes-dashboard` | `9119` | `80` | HTTP | Status-Dashboard für Hermes-Agenten |
| `paperclip-orchestrator` | `3180` | `3180` | HTTP | Task-Orchestrierung, SQLite-Backup-Cronjob |
| `omniroute` | `20128` | `20128` | HTTP | OpenAI-kompatibler Router für LLM-Provider |
| `anything-llm` | `3001` | `3001` | HTTP | Vektor-Suche, Dokumenten-Indexierung |
| `n8n` | `5678` | `5678` | HTTP / Webhook | Automatisierungs-Pipelines, Trigger |
| `Pocketbase` | `8090` | `8090` | HTTP / REST | CRM-Datenbank (Kontakte, Termine, MediaBoard) |
| `Pocketbase-Media` | `8092` | `8090` | HTTP | Mediendateien und Bild-Uploads |
| `CRM` | `3005` | `3000` | HTTP | CRM-Oberfläche (Next.js) |
| `freellmapi` | `3002` | `3002` | HTTP | Lokaler API-Adapter für freie LLMs |

---

## 2. Datenhaltung & Speicherarchitektur

Archon OS trennt flüchtigen Arbeitsspeicher von persistenten Speichermedien:

```mermaid
flowchart LR
    subgraph RAM["RAM (Flüchtiger Kontext)"]
        ContextWindow["LLM Context Window"]
        ActiveTasks["In-Memory Task Queue"]
        TreeCache["Showroom Tree Cache (15s TTL)"]
    end

    subgraph Disk["Persistente Speicherung (Disk)"]
        AgentOSDB[("agent_os.db\n(WAL-Modus)")]
        MemoryDB[("agentic_memory.db\n(WAL-Modus)")]
        PocketDB[("pb_data/data.db\n(PocketBase)")]
        ObsidianVault["Obsidian Vault\n(/opt/data/obsidian/Projects)"]
        AuditLogs["Audit- & Systemlogs\n(/opt/data/logs)"]
    end

    RAM -->|Sync / Flush| Disk
```

1. **SQLite im WAL-Modus (`agent_os.db`, `agentic_memory.db`):**
   - Write-Ahead-Logging verhindert Lese-Schreib-Sperren bei gleichzeitigen Agenten-Schreiboperationen.
   - Enthält Tabellen: `tasks`, `conversations`, `learnings`, `kv_store`, `user_profile`.
2. **PocketBase (`data.db` auf Port 8090):**
   - Hält relationale Datensätze für CRM-Kontakte, Interaktionshistorien, Verknüpfungen und Media-Elemente.
3. **Obsidian Vault (`Projects/`):**
   - Dateibasiertes Langzeitgedächtnis für strukturierte Projektergebnisse. Jedes Projekt enthält zwingend:
     - `PROJEKT.md`: Metadaten, Ziel, Status und beteiligte Agenten.
     - `01_Zwischenberichte/`: Entwürfe, Agenten-Recherchen, Statusberichte.
     - `02_Medien/`: Generierte Bilder, Diagramme, Datensätze.
     - `03_Endprodukte/`: Abgenommene Endergebnisse und PDFs.

---

## 3. Modell-Routing & Hardware-Abstraktion

Aufrufe an Sprachmodelle laufen über den Router (`core_dispatcher.py` / `omniroute`):

```mermaid
sequenceDiagram
    participant User as Benutzer / Agent
    participant Dispatcher as core_dispatcher.py
    participant OmniRoute as OmniRoute (Port 20128)
    participant Provider as Provider (Ollama / OpenRouter / Anthropic)

    User->>Dispatcher: Task-Anfrage (Prompt + Skill-Anforderung)
    Dispatcher->>Dispatcher: Modell-Routing anhand von Kosten & Komplexität
    Dispatcher->>OmniRoute: POST /v1/chat/completions (OpenAI-Format)
    OmniRoute->>Provider: Request an Ziel-Modell
    Provider-->>OmniRoute: Token-Stream
    OmniRoute-->>Dispatcher: Response
    Dispatcher-->>User: Ergebnis + Audit-Log-Eintrag
```

- **Lokale Modelle:** Werden priorisiert für Standard-Klassifizierungen, Dateiprüfungen und RAG-Aufgaben via Ollama/FreeLLM angesprochen.
- **Remote-Modelle:** Anspruchsvolle Architekturaufgaben oder Deep-Research-Mandate routet das System an Claude 3.5 Sonnet oder GPT-4o via API-Key.

---

# Teil 2: Operative Funktionsanleitung (How-To)

## 1. Master Chat & Telegram-Integration

Der Master Chat ist die zentrale Schnittstelle zur Echtzeit-Kommunikation mit dem primären Agenten.

### Nutzung des Web-Interfaces
1. Öffne im Browser `http://127.0.0.1:8501`.
2. Klicke in der linken Seitenleiste auf **Master Chat**.
3. **Session-Auswahl:** Oben links befindet sich das Dropdown aller aktiven Chat-Sitzungen (`/api/chat/sessions`).
4. **Live-Streaming:** Der Chat streamt Token live via SSE (Server-Sent Events) in die UI.

### Telegram-Bot-Verbindung
Der Telegram-Bot synchronisiert Nachrichten mit der Session `Telegram Bot (Live-Stream)`:
- Eingehende Telegram-Nachrichten werden automatisch als User-Prompt in die Session übernommen.
- Antworten des Agenten fließen über den Poller im `hermes`-Container direkt zurück in den Telegram-Chat.
- **Session-ID:** `20260828_131801_1284dd5a` oder dynamisch per Chat-ID `telegram_<ID>`.

---

## 2. Eingang (Inbox) & E-Mail-Synchronisation

Das Modul **Eingang** empfängt Mails und ordnet sie bestehenden Kontakten zu.

### Manueller Sync per Terminal
Um den E-Mail-Abruf sofort auszulösen:
```bash
# Direkt über den API-Endpunkt
curl.exe -X POST http://127.0.0.1:8501/api/v1/inbox/emails/sync

# Oder über das Python-Skript im Container
docker exec ARCHON-OS python scripts/archon_crm_mcp.py --fetch-mails
```

### Automatischer Ablauf
1. `backend/email_service.py` verbindet sich via IMAP mit `imap.gmail.com:993`.
2. Neue, ungelesene Nachrichten werden geladen.
3. Die Absenderadresse wird gegen die PocketBase-Collection `kontakte` geprüft:
   - **Treffer:** Nachricht wird in das Array `nachrichtenverlauf` des Kontakts geschrieben.
   - **Kein Treffer:** Die Nachricht verbleibt im Posteingang zur manuellen Zuordnung.

---

## 3. Agenten-Kader & Profile

Agenten sind als isolierte Einheiten definiert und besitzen spezifische Rollen und Tool-Freigaben.

### Konfigurationsdateien
- `agents.json`: Hauptliste aller registrierten Systemagenten.
- `agent_profiles.json`: Detaillierte Rollenbeschreibungen, Systemprompts und Fachbereiche.
- `roles.json`: Berechtigungsstufen und Tool-Zuweisungen.

### Einen neuen Agenten hinzufügen
1. Öffne `agents.json`.
2. Ergänze einen neuen Eintrag nach folgendem Muster:
```json
{
  "id": "code_auditor",
  "name": "Code Auditor",
  "role": "Sicherheits- und Codequalitätsprüfung",
  "model": "claude-3-5-sonnet",
  "tools": ["read_file", "run_command", "git_status"],
  "status": "active"
}
```
3. Lade die Seite neu (`Strg + F5`). Der Agent erscheint im Menü **Agenten-Kader**.

---

## 4. Showroom & Obsidian-Ablage

Der Showroom stellt Projektergebnisse, Zwischenberichte und Medien übersichtlich dar.

### Ordnerstruktur für Projekte
Jedes Projekt im Showroom basiert auf einem Ordner unter `/opt/data/obsidian/Projects/<projektname>/`:

```text
Projects/
└── mein-neues-projekt/
    ├── PROJEKT.md               <-- Projektmetadaten (Titel, Status, Datum)
    ├── 01_Zwischenberichte/     <-- Markdown-Dateien der Entwurfsphase
    ├── 02_Medien/               <-- Bilder (.png, .jpg), Diagramme
    └── 03_Endprodukte/          <-- Finale .md Dokumente oder .pdf Berichte
```

### Datei-Vorschau im Browser
- **Markdown (`.md`):** Wird direkt gerendert.
- **Bilder (`.png`, `.jpg`, `.svg`):** Werden inline über Base64-Data-URLs geladen.
- **PDFs (`.pdf`):** Werden über den integrierten PDF-Viewer im iFrame geöffnet.

---

## 5. Hermes & Hintergrund-Workflows

`hermes` führt zeitintensive Hintergrundaufgaben autark aus.

### Task starten
Ein Task wird per UI oder REST-Call übergeben:
```bash
curl.exe -X POST http://127.0.0.1:8501/api/tasks/dispatch \
  -H "Content-Type: application/json" \
  -d '{"agent": "researcher", "task": "Marktrecherche zu modularem Bauen"}'
```

### Überwachung & Watchdog
- Der Watchdog-Daemon läuft im 30-Sekunden-Intervall.
- Tasks im Zustand `in_progress`, die länger als das definierte Timeout keine Heartbeats senden, werden markiert und neu zugewiesen.
- Logs einsehen:
```bash
docker logs --tail 50 hermes
```

---

## 6. Backup & Wiederherstellung

### Automatisches Backup
`paperclip-orchestrator` führt stündlich automatisierte Backups der SQLite-Datenbanken aus. Die Archive landen unter `/opt/data/backups/`.

### Manuelles Komplett-Backup durchführen
Führe auf dem Host-System folgendes aus:
```powershell
# 1. Sicherung der SQLite-Datenbanken im WAL-Modus
docker exec ARCHON-OS sqlite3 /app/agent_os.db ".backup '/app/data/backups/agent_os_manual.bak'"
docker exec ARCHON-OS sqlite3 /app/agentic_memory.db ".backup '/app/data/backups/agentic_memory_manual.bak'"

# 2. Sicherung des Obsidian Vaults
Compress-Archive -Path "c:\.Antigravity-projekte\obsidian\*" -DestinationPath "c:\.Antigravity-projekte\backup_obsidian_$(Get-Date -Format 'yyyyMMdd_HHmmss').zip"
```

---

## 7. Internet-Watchdog & Triage-Körbchen

Der Internet-Watchdog überwacht Webquellen, RSS-Feeds und regulatorische Änderungen. Er fungiert als vorgeschaltetes Radar, damit das operative Kanban-Board nicht mit ungefilterten Rohdaten überflutet wird.

### Grundprinzipien
1. **Kein automatischer Kanban-Müll (`auto_kanban_sync: false`):**
   - Netzfunde werden im Watchdog-Dashboard gesammelt und vorbewertet.
   - Erst durch manuelle Triage oder das Sammelkörbchen wird ein Fund zur echten Aufgabe im Kanban-Board (`ready`).
2. **Einzelfall-Aktionen:**
   - **📱 Als LinkedIn-Post generieren:** Übergibt den Fund direkt an die Persona `storyteller_ghostwriter`.
   - **📊 Strategische Analyse für Robert:** Übergibt den Fund an `executive_decision_architect`.
   - **✍️ Eigenes Prompting:** Öffnet ein Eingabefenster für spezifische Anweisungen.
3. **Das Sammelkörbchen (Basket):**
   - Funde lassen sich per Klick (`+ Korb`) in ein Zwischenlager legen.
   - Sobald die konfigurierte Schwelle (`basket_threshold`, z. B. 3 Funde) erreicht ist, bündelt ein Klick auf *Paket an Ghostwriter senden* oder *Paket an Robert senden* alle markierten Quellen zu einem gemeinsamen Synthese-Task.
4. **Prio-Keywords (Sofortalarm via Telegram):**
   - Suchbegriffe wie `KfW`, `Förderstopp`, `BauGB`, `GEG` oder `Groq` lösen beim Auffinden sofort eine priorisierte Push-Nachricht auf Telegram aus.
   - Der Alarm enthält direkte Aktions-Buttons zur sofortigen Weiterleitung an den passenden Agenten.
5. **Rollen- & Profilschutz:**
   - Das Ändern von Watchdog-Zielen, Intervallen, Schwellenwerten und Prio-Keywords ist reserviert für Leitungs-Profile ab Robert aufwärts (`executive_decision_architect`, `micha`, `default`).

---

## 8. Telegram-Dokumenten-Pipeline & HITL-Freigaben

Archon OS liefert fundierte Dossiers und Berichte nicht als unleserlichen Markdown-Fließtext aus, sondern über eine zweistufige Dokumenten-Pipeline.

### Auslieferungsformate
- **Dossier als HTML:** Enthält typografisch aufbereitete Überschriften, Tabellen und Quellennachweise für die Desktop- und Browseransicht.
- **Dossier als PDF:** Wird im Container mit ReportLab als sauberes A4-Dokument mit Kopfzeile, Metadaten und strukturierter Gliederung erzeugt.
- **MIME-Type Übertragung:** Die Telegram-Schnittstelle (`telegram_notify.py`) übermittelt PDFs mit `application/pdf`, wodurch Telegram auf Mobilgeräten den nativen PDF-Betrachter öffnet und Abstürze durch fehlerhafte Text-Header verhindert werden.

### Telegram-Bedienung & Buttons
Wenn eine Benachrichtigung oder ein Bericht in Telegram eintrifft:
- **Dokument lesen:** Tippe direkt auf die Datei-Blase (`.pdf` oder `.html`), um den Volltext zu öffnen.
- **`[ 📋 Details ]`:** Fragt den aktuellen Ausführungsstatus des zugehörigen Kanban-Tasks im Backend ab.
- **`[ ✅ Erlauben ]` / `[ ❌ Verbieten ]`:** Sendet eine Human-in-the-Loop (HITL) Entscheidung an das System zurück, um blockierte oder sensible Aktionen freizugeben.

---

## 9. Release-Lifecycle, Updatesystem & GitHub-Sync

Das Updatesystem (`backend/system_updater.py`) synchronisiert den Code-Stand zwischen Entwicklungsrechner und Produktivserver.

### Architektur des Update-Workflows
1. **GitHub-Synchronisation (Push):**
   - In den Einstellungen (Settings > Updates) überträgt die Schaltfläche **„Änderungen zu GitHub pushen“** den aktuellen Entwicklungsstand auf das Remote-Repository.
   - Der Endpoint `/api/v1/system/update/push` führt `git add -A`, `git commit` und `git push` im Container aus.
   - Um Timeouts auf Docker-Bind-Mounts (Windows 9P/virtiofs) zu vermeiden, nutzt Git optimierte Parameter (`-c core.checkstat=minimal`, `-c core.trustctime=false`, `-c core.fileMode=false`, `-c core.autocrlf=true`).

2. **Server-Update (Pull):**
   - Auf dem Produktivserver prüft Archon OS neue Commits (`/api/v1/system/update/check`).
   - Vor der Installation (`/api/v1/system/update/apply`) sichert das System automatisch SQLite-Datenbanken (`agent_os.db`, `agentic_memory.db`) und Konfigurationsdateien in `data/snapshots/`.
   - Nach erfolgreichem `git pull` startet der Container den Dienst neu.

3. **Rollback-Schutz:**
   - Schlägt ein Update oder Migrationstest fehl, stellt die Rollback-Funktion (`/api/v1/system/update/rollback`) den vorherigen Git-Commit und die Datenbank-Snapshots wieder her.

---

## 10. Autonome Tiefenrecherche & Reflexionsschleife v2

Das Research Lab (`backend/research_engine.py`) führt mehrstufige Recherchen durch, wenn einfache Suchanfragen für komplexe Frage- und Marktlagen nicht ausreichen.

### Recherche-Ablauf
1. **Planung & Query-Generierung:**
   - Die Anfrage wird in 3 bis 5 gezielte Teilfragen zerlegt.
   - Ein SSRF-Filter (`_is_safe_url`) blockiert Zugriffe auf interne Netzwerkbereiche (Localhost, RFC 1918 Adressen, Metadaten-Endpunkte).

2. **Evidenz-Sammlung mit Multiprovider-Fallback:**
   - Primäre Suche über Grokipedia / SearXNG.
   - Automatischer Fallback auf Jina Reader API bei Rate-Limits oder Timeout.
   - Parallelisierung von Web-Extraktionen mit Token-Begrenzung pro Dokument.

3. **Reflexionsschleife (Re-Search Loop):**
   - Nach der ersten Analyse bewertet der Reflexions-Prompter Widersprüche und Lücken.
   - Bei Informationsdefiziten generiert die Engine autonome Nachfolge-Suchläufe (bis zu 3 Zyklen), bis die Belege konsistent sind.

4. **Synthese & Vault-Ablage:**
   - Fertige Dossiers enthalten strukturierte Abschnitte, Kernaussagen und Quellenverweise.
   - Die Engine speichert das Ergebnis direkt in `data/obsidian_vault/02_Wissensbibliothek/` und generiert bei Bedarf HTML- und PDF-Exportdateien für Telegram.

---

## 11. Standardisiertes Pluginsystem & Runtime-Hooks

Das Pluginsystem (`backend/plugin_manager.py`) trennt Kernfunktionen von modularen Erweiterungen.

### Verzeichnisstruktur eines Plugins
Jedes Plugin liegt in einem eigenen Unterverzeichnis in `plugins/<plugin_id>/`:
- `plugin.json`: Deklaratives Manifest mit Name, Version, Autor, Berechtigungen und Konfigurationsparametern.
- `plugin.py`: Python-Klasse abgeleitet von `BasePlugin` mit Lebenszyklus- und Tool-Hooks.

### Lebenszyklus & Hooks
1. **Lifecycle-Hooks:**
   - `on_load()`: Initialisierung beim Systemstart.
   - `on_enable()`: Aktivierung über UI oder API (`/api/v1/plugins/{id}/toggle`).
   - `on_disable()`: Geordnetes Abschalten von Hintergrundthreads oder Ressourcen.
   - `on_unload()`: Bereinigung vor Hot-Reload (`/api/v1/plugins/{id}/reload`).

2. **Tool- und Message-Hooks:**
   - `before_tool_execute(tool_name, params)`: Überprüft oder modifiziert Parameter vor dem Tool-Aufruf. Plugins können destruktive Aktionen blockieren.
   - `after_tool_execute(tool_name, result)`: Prüft Rückgaben, filtert sensible Schlüssel (z. B. API-Tokens) oder reichert Daten an.
   - `on_message_received(message)` / `on_task_completed(task)`: Reagiert auf System-Events.

### Enthaltene Starter-Plugins
- **System Metrics (`plugins/system_metrics/`):** Liefert Telemetriedaten (CPU-, RAM-, Disk-Auslastung) über das Tool `get_system_telemetry`.
- **Security Audit Hook (`plugins/security_audit_hook/`):** Fängt gefährliche Shell-Befehle (z. B. `rm -rf /`) vor der Ausführung ab und maskiert Secrets (`sk-...`, `ghp_...`) in Tool-Rückgaben.
- **Cost Guard (`plugins/cost_guard/`):** Überwacht das tägliche Token-Budget und blockiert LLM-Aufrufe bei Überschreitung des definierten Limits.

### Konfiguration im Dashboard
In den Einstellungen (Settings > Plugins) können alle installierten Plugins per Klick aktiviert, deaktiviert oder neu geladen werden. Der Status wird persistent in `data/plugins_state.json` gesichert.

---

# Teil 3: Operatives Runbook & Schnellbehebung

### Schnellbefehle im Fehlerfall

#### 1. Container-Status prüfen
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

#### 2. ARCHON-OS neu starten (nach Code-Änderungen)
```bash
docker restart ARCHON-OS
```

#### 3. Logs live mitverfolgen
```bash
# Backend-Logs
docker logs -f ARCHON-OS

# Hermes-Agenten-Logs
docker logs -f hermes
```

#### 4. Datenbank-Integritätsprüfung (SQLite)
```bash
docker exec ARCHON-OS sqlite3 /app/agent_os.db "PRAGMA integrity_check;"
docker exec ARCHON-OS sqlite3 /app/agentic_memory.db "PRAGMA integrity_check;"
```
*Erwartetes Ergebnis:* `ok`

#### 5. E-Mail- und CRM-Verbindung testen
```bash
# E-Mail Sync anstoßen
curl.exe -s -X POST http://127.0.0.1:8501/api/v1/inbox/emails/sync

# PocketBase-Status prüfen
curl.exe -s http://127.0.0.1:8090/api/health
```

#### 6. Docker-Socket-Proxy testen
```bash
curl.exe -s http://127.0.0.1:2375/version
```
