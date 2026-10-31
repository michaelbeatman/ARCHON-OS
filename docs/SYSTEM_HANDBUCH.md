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

### Telegram Voice-Pipeline & Sprachausgabe
Die Sprachverarbeitung (`backend/voice_pipeline.py`) erweitert Archon OS um mobile Sprachsteuerung:
- **Voice-to-Text Ingestion (`POST /api/telegram/voice-relay`):** Sprachnachrichten (`.ogg`/Opus) werden empfangen und über Whisper (Groq, OpenAI oder Gemini) transkribiert.
- **Intent- & Rufnamen-Erkennung:** Sprichst du einen Agenten im Sprachmemo direkt an (z. B. „Robert, prüfe bitte...“ oder „/anwalt“), wird der Auftrag automatisch an dessen Rollenprofil übergeben.
- **Sprachantwort via edge-tts:** Das System synthetisiert die Antwort mit der deutschen neuronalen Stimme `de-DE-ConradNeural` und übermittelt sie als native Audioblase via `sendVoice` an dein Smartphone.

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

### Interaktive Code-Sandbox & Live-Runner
Der Showroom (`views_core.py` & `static/views/view_showroom.html`) erlaubt das direkte Ausführen von Skripten:
- **Sandbox-Ausführung (`POST /api/views/showroom/run-code`):** Bei Auswahl von Python- oder Code-Dateien blendet der Viewer die Schaltfläche **„Sandbox Run“** ein.
- **Terminal-Konsole:** Ein ausklappbares Terminal zeigt Exit-Code, Ausführungszeit in Millisekunden sowie `STDOUT` und `STDERR` in Echtzeit an.
- **Sicherheits-Isolation:** Skripte laufen in einem flüchtigen Scratch-Ordner mit einem festen Timeout von 12 Sekunden.

---

## 5. Operations, Kanban & Hintergrund-Workflows

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

### Kanban Qualitäts-Gate (4-Augen-Review)
Das Qualitäts-Gate (`backend/operations_api.py`) sichert Arbeitsergebnisse ab, bevor eine Aufgabe auf `done` verschoben werden kann:
- **Unabhängiger Prüfer:** Katharina Völk (QM/Compliance) oder Robert prüft das Ergebnis automatisch auf Vollständigkeit, Substanz und Handlungsfähigkeit (`POST /api/operations/kanban/tasks/{task_id}/quality-review`).
- **Status-Sperre:** Bei Mängeln (`changes_requested`) verbleibt der Task in `review` mit dem Badge `⚠ 4-Augen: Nachbesserung`. Das Verschieben nach `done` wird serverseitig abgewiesen, bis Mängel behoben sind oder der Operator eine manuelle Freigabe erteilt.

### Autonome Tiefenrecherche & Reflexionsschleife v2
Das Research Lab (`backend/research_engine.py`) führt mehrstufige Analysen durch:
- **Re-Search Loop:** Zerlegt komplexe Aufgaben in 3–5 Teilfragen, bewertet Lücken und startet bei Bedarf bis zu 3 autonome Nachfolge-Suchläufe.
- **Fallback-Kette & SSRF-Schutz:** Grokipedia und SearXNG mit Fallback auf Jina Reader API; Schutzfilter gegen Zugriffe auf lokale Netzwerkbereiche (RFC 1918) und Cloud-Metadaten.

---

## 6. Backup, Updatesystem & Plugins

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

### Release-Lifecycle, Updatesystem & GitHub-Sync
Das Updatesystem (`backend/system_updater.py`) synchronisiert Entwicklungsrechner und Produktivserver:
- **GitHub-Push aus den Settings:** Ein Klick auf *„Änderungen zu GitHub pushen“* (`POST /api/v1/system/update/push`) committed und pusht den aktuellen Stand über Docker-optimierte Git-Parameter (`-c core.checkstat=minimal`).
- **Pre-Update Snapshots & Rollback:** Vor jedem Pull (`POST /api/v1/system/update/apply`) sichert das System alle SQLite-Datenbanken konsistent in `data/snapshots/`. Im Fehlerfall stellt `POST /api/v1/system/update/rollback` den alten Zustand wieder her.

### Standardisiertes Pluginsystem & Runtime-Hooks
Das modulare Pluginsystem (`backend/plugin_manager.py`) trennt Erweiterungen vom Systemkern:
- **Verzeichnisstruktur:** Jedes Plugin liegt unter `plugins/<plugin_id>/` mit Manifest `plugin.json` und Implementierung `plugin.py`.
- **Hooks:** Lifecycle-Hooks (`on_load`, `on_enable`, `on_disable`) und Tool-Interzeptoren (`before_tool_execute`, `after_tool_execute`).
- **Starter-Plugins:** `system_metrics` (Hardware-Telemetrie), `security_audit_hook` (Befehlsfilter & Secret-Maskierung) und `cost_guard` (Token-Budgetüberwachung).

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

## 9. API-Token & Key-Sicherheit mit Scopes und Rate-Limits

Die Schnittstelle `backend/api_auth.py` schützt externe Endpunkte und Automationsdienste:
- **Feingranulare Scopes:** API-Keys werden mit spezifischen Berechtigungen ausgestellt (`read:tasks`, `write:tasks`, `execute:agent`, `admin:system`). Ein reiner Monitoring-Client kann somit niemals Systembefehle ausführen.
- **Token-Bucket Rate-Limiting:** Jeder Schlüssel besitzt ein konfigurierbares Aufruflimit (z. B. 60 Requests pro Minute) mit automatischem Sliding-Window Schutz gegen Denial-of-Service.
- **Verwaltung im UI:** Im System Control Center unter **API-Tokens & Sicherheit** können Schlüssel erzeugt, Berechtigungen zugewiesen und kompromittierte Keys mit einem Klick widerrufen werden.

---

## 10. E-Mail-Freigabe-Queue & 4-Augen-Versand

Um unkontrollierten E-Mail-Versand durch autonome Agenten auszuschließen, leitet `backend/email_draft_queue.py` alle generierten Nachrichten in eine Freigabe-Warteschlange:
- **Freigabestufen:** Entwürfe erhalten den Status `pending_approval`. Der Operator prüft Betreff, Empfänger und Volltext im Postfach unter dem Reiter **Entwürfe & Freigaben**.
- **Human-in-the-Loop Aktionen:**
  - `[Freigeben & Senden]`: Übergibt die Nachricht an den SMTP-Dienst und dokumentiert die Transaktion im Audit-Log.
  - `[Überarbeiten]`: Übergibt den Text mit Korrekturhinweisen zurück an den verfassenden Agenten.
  - `[Verwerfen]`: Löscht den Entwurf unwiderruflich.

---

## 11. Kanban-Mehrfachaktionen & 10-Minuten-Undo

Zur effizienten Steuerung großer Aufgabenmengen unterstützt das operative Board (`backend/operations_api.py`) Sammeloperationen mit zeitlich begrenzter Reversibilität:
- **Mehrfachauswahl (Bulk Actions):** Durch Checkboxen an den Task-Karten können mehrere Aufgaben gleichzeitig in eine andere Spalte verschoben, einem neuen Agenten zugewiesen oder gelöscht werden.
- **10-Minuten-Undo Puffer:** Nach jeder Sammelaktion speichert das System einen konsistenten JSON-Snapshot der betroffenen Tasks in `kanban.db` und blendet ein persistentes Toast-Fenster mit dem Button **„Rückgängig“** ein. 
- Ein Klick stellt den exakten vorherigen Spalten- und Zuweisungsstatus innerhalb des 10-Minuten-Zeitfensters wieder her.

---

## 12. Agent-Scorecards & Obsidian-Synchronisation in der Personalakte

Der Reiter **Personalakte** im Agenten-Kader visualisiert die operative Leistungsfähigkeit jedes Agenten anhand von 8 Kennzahlen (`backend/agent_scorecards.py`):
1. **Erfolgsrate (%):** Anteil erfolgreich abgeschlossener Tasks ohne Fehlversuche.
2. **Token-Effizienz:** Durchschnittlicher Token-Verbrauch pro gelöster Aufgabe.
3. **Kostenakkumulation (€):** Angefallene Modellkosten über alle Einsätze.
4. **Latenz & Reaktionszeit:** Durchschnittliche Dauer bis zum ersten Tool-Aufruf.
5. **Tool-Zuverlässigkeit (%):** Quote fehlerfreier Tool-Ausführungen.
6. **HITL-Feedback Score:** Historische Quote genehmigter vs. abgelehnter Freigaben.
7. **Pünktlichkeit & Deadlines:** Quote eingehaltene vs. überschrittene Bearbeitungszeiten.
8. **Gesamt-Aufgabenvolumen:** Gesamtzahl bearbeiteter Tickets.

**Obsidian-Integration:** Jede Leistungsakte wird automatisch mit dem Obsidian Vault unter `/opt/data/obsidian/Personalakten/<agent_id>.md` synchronisiert. Leistungsnotizen und Beurteilungen können dort direkt formuliert und in Archon OS eingeblendet werden.

---

## 13. Revisionssicheres GoBD & ISO 27001 Audit-Log mit SHA-256 Hashkette

Das Governance-Modul (`backend/audit_log.py`) zeichnet alle sicherheits-, finanz- und prozessrelevanten Aktionen manipulationssicher auf:
- **Kryptografische Hashkette:** Jeder Eintrag enthält den SHA-256 Hash des vorherigen Eintrags sowie seiner eigenen Nutzdaten. Eine nachträgliche Manipulation bricht die Kette und wird sofort lokalisiert.
- **Prüfer-Export (1-Klick):** Über die Ansicht **Telemetrie & Logs** kann der vollständige Prüfbericht nach GoBD- und ISO/IEC 27001-Standard als strukturierte `JSON`- oder `CSV`-Datei exportiert werden.
- **Integritätsprüfung per API:** `/api/governance/audit-log/verify` prüft in Echtzeit, ob die Kette lückenlos und unversehrt ist.

---

## 14. Datenschutz-Routing (Zero Egress) & Lokale LLMs mit DSGVO-Statusleuchten

Für sensible Geschäftsbereiche (Rechnungen, Verträge, CRM-Kontakte, HR-Akten) erzwingt `backend/privacy_router.py` den Schutz vor Drittland-Übertragungen:
- **Automatische On-Premise Erkennung:** Prüft lokale Inferenzserver (LM Studio auf Port 1234, Ollama auf Port 11434) mit synchronem 0,3s Socket-Check ohne DNS-Verzögerung.
- **EU-Fallback:** Steht keine lokale GPU zur Verfügung, greift das System auf europäische DSGVO-Provider (z. B. Mistral AI mit Rechenzentren in Frankreich) zurück.
- **Echtzeit-Statusleuchten (Sidebar Footer):**
  - `LOKAL`: **Grün** (Lokale Engine bereit & Zero-Egress aktiv), **Gelb** (Engine erreichbar, Routing inaktiv), **Grau** (Keine lokale Engine).
  - `DSGVO`: **Grün** (Zero-Egress oder EU-Mistral aktiv), **Rot** (Schutz inaktiv; Datenübertragung ins Drittland möglich).

---

## 15. Dual-LLM Guard gegen Prompt Injection & [T]-Trusted Badges

Zum Schutz vor indirekter Prompt Injection in unstrukturierten externen Daten (E-Mails, Scrapes, PDFs) implementiert `backend/dual_llm_sanitizer.py` eine 2-Stufen-Quarantäne:
- **Stufe 1 (Quarantäne):** Eingehende Fremddaten werden durch ein isoliertes, unprivilegiertes Sprachmodell ohne Werkzeugzugriff neutralisiert und auf Jailbreak-Muster analysiert.
- **Stufe 2 (Werkzeug-Agent):** Erst nach Freigabe erhält der primäre Arbeitsagent (z. B. Robert) die bereinigten Fakten als passive Daten-Payload.
- **`[T]`-Trusted Source Toggle:** In der Inbox und im Master Chat erlaubt der kleine interaktive Badge `[T]` vertrauenswürdige Absender (gespeichert in `data/trusted_sources.json`) mit einem Klick freizuschalten, um vertraute interne Absender ohne Verzögerung direkt zuzustellen.

---

## 16. Notfallzugang & Verschlüsseltes Break-Glass Protocol

Das Katastrophen- und Nachfolgeprotokoll (`scripts/break_glass_recovery.py`) stellt sicher, dass das System auch bei Komplettausfall des Betreibers oder der Docker-Infrastruktur handlungsfähig bleibt:
- **Zero-Dependency Authenticated Encryption:** Nutzt ausschließlich Python 3 Standardbibliotheken mit PBKDF2 (200.000 Runden HMAC-SHA256) und Counter-Modus Keystream-Verschlüsselung.
- **Tresor-Archiv:** Sichert alle kritischen Secrets (`.env`), Konfigurationen und SQLite-Datenbanken verschlüsselt in `data/backups/break_glass_vault.enc`.
- **Notfall-Wiederherstellung:** Ein autorisierter Notfall-Operator kann im Ernstfall über das Host-Terminal mit dem ausgedruckten 64-stelligen Masterkey (`BREAK_GLASS_RECOVERY_KIT.md`) alle Daten in Sekundenschnelle ohne Docker wiederherstellen:
  ```bash
  python scripts/break_glass_recovery.py --restore --key <MASTERKEY>
  ```

---

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

#### 7. Audit-Log Integritätsprüfung (GoBD / ISO 27001)
```bash
curl.exe -s http://127.0.0.1:8501/api/governance/audit-log/verify
```
*Erwartetes Ergebnis:* `{"status": "valid", "tampered_records": 0, ...}`

#### 8. Datenschutz-Routing & Lokale LLM Erkennung
```bash
curl.exe -s http://127.0.0.1:8501/api/llm-providers/privacy-status
```
*Gibt zurück, ob LM Studio (Port 1234) oder Ollama (Port 11434) aktiv sind und ob Zero-Egress aktiv ist.*

#### 9. Notfall-Tresor Status prüfen (Break-Glass)
```bash
python scripts/break_glass_recovery.py --status
```
*Prüft Vorhandensein und Timestamp des verschlüsselten Tresors `data/backups/break_glass_vault.enc`.*

---

# Anhang: System-Glossar (Kernansichten & Mechaniken)

Referenz aller Kernansichten, Spezial-Studios und System-Mechaniken von Archon OS (inklusive Version v0.3.5).

### I. Die 20 System-Ansichten & Spezial-Studios

1. **Mission Control (Monitoring-Cockpit & Leitstand)**
   * **Problem:** Fehlender Gesamtüberblick über Flottenlast, TPM-Durchsatz, Kosten und blockierte Freigaben.
   * **Mechanik:** Bündelt 5 KPI-Kacheln, Board-Projektion, Active Process Inspection Bar (3-Slot-Footer), 15-Minuten-Token-Aktivitätsband und Live-Audit-Stream.
   * **Nutzen:** Verzögerungsfreie 360°-Überwachung des gesamten Systems auf einem Bildschirm.

2. **Operations – Kanban Board & Task-Engine**
   * **Problem:** Aufgaben gehen in reinen Chat-Verläufen unter und lassen sich weder steuern noch auditieren.
   * **Mechanik:** 5 Lebenszyklus-Spalten auf `kanban.db` (Single Source of Truth) mit WIP-Limits, Prioritätsfiltern (P0–P3), Zeiterfassung und Obsidian-Sync. Integriert das 4-Augen Qualitäts-Gate vor `done` (1–100% Score). **Neu:** Unterstützt Mehrfachauswahl (Bulk Actions: Verschieben, Zuweisen, Löschen) mit 10-Minuten-Undo Puffer über persistente Snapshots.
   * **Nutzen:** Verhindert unfertige Arbeitsstände im `done`-Status und erlaubt schnelles Korrigieren versehentlicher Massenänderungen.

3. **Operations – Interaktives 2D-Organigramm & Berichtslinien**
   * **Problem:** Flache Agentenlisten bieten keine Hierarchie für Eskalationen oder Vertretungsregeln.
   * **Mechanik:** Visualisiert 56 Knoten und 55 Berichtslinien als 2D-Graph (Apex -> CEO Robert -> Fach-Leads -> Spezialisten) mit Drag & Drop und Speicherung in `config/org_hierarchy.json`.
   * **Nutzen:** Definiert verbindliche Eskalations- und Delegationsketten.

4. **Operations – Interne Agenten-Kommunikation (Funkverkehr)**
   * **Problem:** Fehlende Nachvollziehbarkeit bei agentenübergreifender Zusammenarbeit im Hintergrund.
   * **Mechanik:** Live-Mitschnitt des A2A-Nachrichtenaustauschs zwischen Hermes-Kern und Subagenten.
   * **Nutzen:** Volle Transparenz über Zwischenergebnisse und Absprachen.

5. **Eingang & Triage (3-Spalten HITL-Gatekeeper & Postfach)**
   * **Problem:** Unkontrollierte externe Impulse stören laufende Kernprozesse oder schleusen Injection-Angriffe ein.
   * **Mechanik:** 3-Spalten-Triage mit Vorprüfung, Sentiment-Analyse, Prioritäts-Klassifizierung und Freigabe-Buttons. **Neu:** Enthält die E-Mail-Freigabe-Queue für ausgehende Entwürfe (`backend/email_draft_queue.py`), Dual-LLM Quarantäne gegen Prompt Injection und interaktive `[T]`-Trusted Source Badges neben Absendern zum Whitelisting vertrauenswürdiger Kontakte.
   * **Nutzen:** Kontrollierter Datenfluss nach außen und sicherer Schutz vor bösartigen Fremdanweisungen.

6. **Agenten-Kader & Flottenmanagement (8-Reiter-Cockpit)**
   * **Problem:** Agentenkonfigurationen und Systemprompts waren verteilt und schwer wartbar.
   * **Mechanik:** 8 Reiter für Kaderübersicht, Personalakten, Rollen, Soul-Engine, Skills, Marktplatz, Funk und Modellzuweisungen. **Neu:** Der Reiter **Personalakte** visualisiert 8 standardisierte Leistungskennzahlen (Erfolgsrate, Tokens, Kosten, Latenz, Tool-Zuverlässigkeit, Feedback, Pünktlichkeit, Aufgabenvolumen) mit direkter Synchronisation in den Obsidian Vault (`Personalakten/<agent>.md`).
   * **Nutzen:** Vollständige Transparenz über Leistungs- und Kostenhistorie aller 57 Agenten.

7. **Master Chat (Dual-Mode Workspace & Multi-Session-Sidebar)**
   * **Problem:** Kein schneller Wechsel zwischen 1:1-Dialog, Gruppenchat und Missions-Auftrag.
   * **Mechanik:** Dual-Mode ('Direkt' vs. 'Mission'), Multi-File-Upload, Screen-Capture, Reasoning-Budget (0 bis 16k Tokens) und Session-Historie. Telegram Voice-Pipeline mit Whisper/Gemini und edge-tts. **Neu:** Integrierter `[T]`-Trusted Source Toggle neben dem Moduswähler für Quarantäne-Bypass bei vertrauenswürdigen Eingaben.
   * **Nutzen:** Durchgängige Arbeitsfläche für Text-, Bild- und Sprachinteraktion.

8. **AI Mastermind & Boardroom (55 Methodik-Frameworks)**
   * **Problem:** Komplexe Entscheidungen werden oft einseitig oder ohne Methodik getroffen.
   * **Mechanik:** 55 strukturierte Frameworks (SWOT, Six Thinking Hats, Pre-Mortem, AHP, etc.) mit Multi-Agenten-Debatte.
   * **Nutzen:** Objektive, methodisch abgesicherte Entscheidungsvorlagen.

9. **Showroom (Projekt-Explorer, Artefakt-Galerie & Python-Sandbox)**
   * **Problem:** Generierte Deliverables (HTML, Berichte, Skripte) gehen im Chat-Verlauf verloren.
   * **Mechanik:** Katalogisiert Arbeitsergebnisse nach Ersteller, Typ und Datum mit Markdown-/HTML-Rendering. Interaktiver Live-Runner zur direkten Code-Ausführung im Browser mit 12s Timeout, isoliertem Scratch-Verzeichnis und Terminal-Drawer.
   * **Nutzen:** Deliverables und Skripte direkt im Showroom ohne Konsolenwechsel prüfen und ausführen.

10. **Zentralbibliothek & 2nd Brain (RAG, Auto-OCR & Obsidian-Vault)**
    * **Problem:** Silowissen in Dokumenten ohne zentrale semantische Suchbarkeit.
    * **Mechanik:** RAG-Pipeline zu AnythingLLM (Port 3001), 3-stufige Ordnerstruktur in `obsidian_vault` und Auto-OCR.
    * **Nutzen:** Semantisch durchsuchbares Unternehmensgedächtnis mit Live-Sync.

11. **Workflow-Engine (n8n Automation Mesh auf Port 5678)**
    * **Problem:** Komplexe Trigger-Action-Ketten überfordern lineare Chat-Agenten.
    * **Mechanik:** Visueller Workflow-Editor für Cron-Jobs, API-Connectors und Webhook-Ketten. Routinen für Morning-Briefing (07:30 Uhr), Maintenance (So 23:00 Uhr) und stündlichen News-Scan.
    * **Nutzen:** Autonome zeitgesteuerte Hintergrundroutinen ohne manuelles Zutun.

12. **LLM Gateway & Datenschutz-Router (OmniRoute & Zero Egress)**
    * **Problem:** Abhängigkeit von einzelnen LLM-Providern und Risiko des Drittland-Datentransfers für sensible Geschäftsdaten.
    * **Mechanik:** Dynamisches Multi-Provider Routing mit Fallback-Kaskaden. **Neu:** Datenschutz-Routing (`backend/privacy_router.py`) leitet sensible Datenkategorien (Finanzen, Verträge, CRM, HR) prioritär an lokale Engines (LM Studio / Ollama) oder DSGVO-zertifizierten EU-Fallback (Mistral AI). Permanente Echtzeit-Indikatoren (`LOKAL` & `DSGVO`) in der Sidebar-Fußzeile.
    * **Nutzen:** Höchste Ausfallsicherheit, optimierte Kosten und lückenlose DSGVO-Konformität.

13. **Token Guard (Guardian & Token Analytics)**
    * **Problem:** Unerwartete Kostenspitzen durch ausufernde Kontextfenster und Loops.
    * **Mechanik:** 3 Sub-Views, Hard-Clipper (32k/20 Turns), Context-Swapper und Verbrauchs-Alerts.
    * **Nutzen:** Transparente Kostenkontrolle und Budget-Schutz.

14. **Erweiterungen & Modul-Zentrale (Pluginsystem)**
    * **Problem:** Systemfähigkeiten ließen sich bisher nicht isoliert zur Laufzeit erweitern.
    * **Mechanik:** Standardisiertes Pluginsystem unter `plugins/<plugin_id>/plugin.json` mit 4 Lifecycle-Hooks und 2 Tool-Interzeptoren inklusive Starter-Plugins (System Metrics, Security Audit Hook, Cost Guard).
    * **Nutzen:** Modulare Laufzeit-Erweiterungen ohne Kernel-Code-Eingriffe.

15. **Research Lab (Deep Search & Evidenz-Triangulation)**
    * **Problem:** Einfache Internetsuchen liefern oberflächliche, ungeprüfte Einzeltreffer ohne Nachvollziehbarkeit.
    * **Mechanik:** Mehrstufiges Forschungs-Cockpit mit Quellen-Monitor und Evidenz-Score. Kuratierte Informationsquellen-Strategie mit 15 verifizierten Quellen und Zitationspflicht.
    * **Nutzen:** Wissenschaftlich und wirtschaftlich belastbare, triangulierte Dossiers mit lückenlosem Primärquellen-Nachweis.

16. **Telemetrie & Revisions-Log (GoBD / ISO 27001 Audit-Stream)**
    * **Problem:** Manipulierbare oder unvollständige System-Logs erfüllen keine gesetzlichen Nachweispflichten.
    * **Mechanik:** **Neu:** Revisionssicheres Audit-Log (`backend/audit_log.py`) mit kryptografischer SHA-256 Hashkette (Merkle-Prinzip), lückenloser Nachvollziehbarkeit von Finanz- und Freigabeprozessen, Manipulationserkennung (`/verify`), Kategorie-Filterung und 1-Klick Prüfbericht-Export (JSON/CSV).
    * **Nutzen:** Vollständige Compliance für GoBD-, ISO 27001- und EU AI Act-Audits.

17. **Spezial-Studio: Archon Prompt Studio (1.079 Vorlagen & Fabric SOP)**
    * **Problem:** Unstrukturierte Prompts führen zu inkonsistenten Agenten-Ergebnissen.
    * **Mechanik:** Durchsuchbare Vorlagenbibliothek mit 1.079 Fabric-Patterns und System-Prompt-Generatoren.
    * **Nutzen:** Sofort einsatzbereite, praxiserprobte Prompt-Schablonen.

18. **Spezial-Studio: Visual CSS Live Studio & In-Place Transform Gizmo (Alt + S)**
    * **Problem:** UI-Anpassungen erfordern zeitraubende Code-Edits und Container-Neustarts.
    * **Mechanik:** Live-CSS-Editor im Browser mit visuellem Gizmo und direktem Speichern in `custom.css`.
    * **Nutzen:** Design-Anpassungen in Echtzeit ohne Entwicklungsunterbrechung.

19. **Spezial-Studio: Design System Lab & AppShell Architekt**
    * **Problem:** Inkonsistente UI-Komponenten und Layout-Brüche zwischen Ansichten.
    * **Mechanik:** 15 standardisierte Komponenten, Farbtoken und AppShell-Layout-Presets.
    * **Nutzen:** Einheitliche Gestaltung und schnelle Erstellung neuer Ansichten.

20. **System Control Center & Notfallzugang (Settings & Break-Glass)**
    * **Problem:** Systemeinstellungen waren verteilt; bei Betreiberausfall drohte Datenverlust.
    * **Mechanik:** 8 Administrations-Reiter und Omnibox (`Strg + K`). 1-Klick Updatesystem mit Pre-Update Snapshots. **Neu:** API-Key Verwaltung mit Scopes und Rate-Limits (`backend/api_auth.py`), Section 15 für den verschlüsselten Notfall-Tresor (Break-Glass Protocol via `scripts/break_glass_recovery.py`) mit PBKDF2-200k Keystream-Verschlüsselung für Katastrophen-Wiederherstellung.
    * **Nutzen:** Zentrale Systemkontrolle, gesicherte API-Schnittstellen und garantierter Weiterbetrieb im Notfall.

