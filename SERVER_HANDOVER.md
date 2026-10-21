# 🚀 AgenticOS / Archon OS — Server Handover & Deployment Guide

> **Zielgruppe:** Antigravity AI-Agent auf dem Homeserver  
> **Projekt:** Archon OS 2026 / Agentic Operating System  
> **Stand:** 21. Oktober 2026 (Ready for Server Deployment)

---

## 1. Übersicht & Systemarchitektur

Archon OS 2026 ist ein agentisches Betriebssystem (Agentic OS), basierend auf einer 7-Säulen-Architektur:
1. **Kernel & Scheduling:** Asyncio Event-Loop, Watchdog Daemon (30s Überwachung), tickless scheduling.
2. **Process Model:** Subagenten als isolierte Prozesse mit deklarativen Manifesten und Status-Tracking.
3. **Device Driver:** MCP-Server Ökosystem für dynamische Tool-Bindings.
4. **Filesystem & Memory:** SQLite im WAL-Modus (`data/agentic_memory.db`) für non-blocking Writes mit den 5 Standardtabellen (`tasks`, `conversations`, `learnings`, `kv_store`, `user_profile`).
5. **Hardware Abstraction & Routing:** Multi-Provider AI-Routing (`core_dispatcher.py`).
6. **Governance & Zero-Trust:** Audit-Logging und RBAC-Rollen (`roles.json`).
7. **Selbst-Evolution:** Laufzeit-Skill-Management (`.agents/skills/` und `templates/skills/`).

### Kernkomponenten & Ports
- **Archon OS Hauptserver:** FastAPI / Uvicorn auf Port `8420` (`http://localhost:8420` oder Host-IP)
- **Watchdog Daemon:** `watchdog_daemon.py` zur präemptiven Task-Überwachung
- **Zentraldatenbank:** `data/agentic_memory.db` (SQLite WAL)
- **Frontend AppShell:** Single-Page-Applikation unter `static/index.html` mit modularen HTML-Views (`static/views/`)
- **Externe Sidecars (optional):**
  - **AnythingLLM (RAG Index):** Port `3001`
  - **n8n (Workflow Engine):** Port `5678`
  - **PocketBase (CRM / Media):** Port `8090`
  - **Obsidian Vault:** Wird vom Nutzer separat übertragen

---

## 2. Letzte Weiterentwicklungen & UI-Status (Wichtig!)

Die Benutzeroberfläche wurde vollständig auf das einheitliche **~120px Header-Card Design** (`os-island`) harmonisiert:
- **Mission Control (Cockpit):** Dashboard mit Operations-Vorschau und 120px Header.
- **Eingang (Unified Inbox):** 120px Header mit 4 Modul-Kacheln (Intern, E-Mail, Messenger, Webhooks).
- **Agentenkader:** 120px Header mit Status-Dot, Kacheln für Übersicht, Personalakte, Skills, Soul, Marktplatz.
- **Zentralbibliothek:** 120px Header mit neu freigestellten, hochauflösenden Icons:
  - `library_rag.png` (RAG Index)
  - `library_erfasser.png` (Erfassungsmodul)
  - `library_vault.png` (Obsidian Vault mit Tresor-Grafik)
- **Showroom (Projekt-Explorer):** Angepasst auf 120px Header Card mit Explorer-Suche und 4 Fokus-Kacheln (`marketplace.png`, `skills.png`, `paperclip.png`, `soul.png`).
- **Design Studio & Theme Customizer:** 15 Module im Theme-Editor (`config/design_themes.json`) konfigurierbar.
- **Asset-Pfade:** Alle Icons liegen in `static/img/cadre_icons/` und sind vollständig getrackt.

---

## 3. Schritt-für-Schritt Einrichtung auf dem Homeserver

Führe als Antigravity-Agent auf dem Homeserver folgende Schritte aus:

### Schritt 1: Workspace vorbereiten & entpacken
Entpacke das übertragene Archiv in das gewünschte Projektverzeichnis (z. B. `/opt/agenticos-2026` oder `~/AgenticOS-2026` oder `D:\AgenticOS-2026`).

```bash
cd AgenticOS-2026
ls -la
```

### Schritt 2: Python Virtual Environment erstellen
Erstelle eine frische, systemeigene Python-Umgebung (empfohlen: Python 3.11 oder 3.12):

```bash
python3 -m venv .venv
source .venv/bin/activate       # Auf Linux/macOS
# bzw. .venv\Scripts\activate   # Auf Windows
```

### Schritt 3: Abhängigkeiten installieren
Installiere alle Abhängigkeiten über die aktualisierte `requirements.txt`:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Schritt 4: Umgebungskonfiguration (.env)
Überprüfe die Datei `.env`. Falls nicht vorhanden, kopiere `.env.example`:

```bash
cp .env.example .env
```

Passe die Werte an:
- `PORT=8420`
- `HOST=0.0.0.0` (damit das OS im Heimnetz erreichbar ist)
- API-Keys für LLM-Provider eintragen (OpenAI, Anthropic, Gemini, OmniRoute, Composio, Telegram falls genutzt)

### Schritt 5: Obsidian Vault anbinden
Der Nutzer überträgt seinen Obsidian Vault separat auf den Homeserver.
- Prüfe in `config/system_settings.json` oder `data/` den Pfad zum Obsidian Vault.
- Standard-Pfade:
  - Entweder relativer Ordner `./obsidian_vault`
  - Oder absoluter Pfad zum synchronisierten Vault des Nutzers.
- Sobald der Vault liegt, stellt der Dateibaum im Showroom und in der Zentralbibliothek alle Notizen sofort dar.

### Schritt 6: Datenbank & Integrität prüfen
Prüfe die SQLite-Datenbank:

```bash
python -c "import sqlite3; con = sqlite3.connect('data/agentic_memory.db'); print('Tables:', [r[0] for r in con.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall()]); con.close()"
```

Die Tabellen `tasks`, `conversations`, `learnings`, `kv_store` und `user_profile` sollten vorhanden sein.

### Schritt 7: Server & Watchdog starten

**Manueller Teststart:**
```bash
python main.py
```
Der Server lauscht standardmäßig auf `http://0.0.0.0:8420`.

**Hintergrund-Betrieb (z. B. via systemd auf Linux):**
Erstelle zwei Service-Units oder starte im Hintergrund:

```bash
# Server im Hintergrund
nohup python main.py > server.log 2>&1 &

# Watchdog Daemon im Hintergrund
nohup python watchdog_daemon.py > watchdog.log 2>&1 &
```

*(Auf Linux-Homeservern wird eine systemd-Unit für Autostart nach Reboot empfohlen).*

---

## 4. Verifikations-Checkliste für Antigravity

Nach dem Start auf dem Server prüfe folgende Punkte:

1. **HTTP Status 200 auf Haupt-App:**
   ```bash
   curl -I http://localhost:8420/
   ```
2. **API Status & Health:**
   ```bash
   curl -s http://localhost:8420/api/system/status
   ```
3. **Statische Assets & Icons:**
   ```bash
   curl -I http://localhost:8420/static/img/cadre_icons/library_rag.png
   curl -I http://localhost:8420/static/img/cadre_icons/library_vault.png
   curl -I http://localhost:8420/static/img/cadre_icons/n8n.png
   ```
4. **View Mounts:**
   Prüfe, ob `/static/views/operations_view.html`, `/static/views/library_view.html`, `/static/views/inbox_view.html` und `/static/views/view_showroom.html` erreichbar sind.

---

## 5. Dateistruktur & Wichtige Pfade

```
AgenticOS-2026/
├── main.py                     # Kern-Server (FastAPI, Port 8420)
├── watchdog_daemon.py          # Watchdog-Hintergrundprozess
├── core_dispatcher.py          # Task- und LLM-Dispatcher
├── local_memory_bridge.py      # SQLite Memory Manager
├── apollo_voice_engine.py      # Voice/Audio Pipeline
├── requirements.txt            # Python-Paketliste
├── .env                        # Umgebungsvariablen & API-Keys
├── config/                     # Systemkonfigurationen & Agenten
│   ├── agents.json             # Agenten-Definitionen
│   ├── design_themes.json      # CSS Theme & Modul-Styling
│   └── org_hierarchy.json      # Organigramm-Hierarchie
├── data/                       # Persistenter Systemstatus
│   └── agentic_memory.db       # Primäre SQLite-Datenbank (WAL)
├── static/                     # Frontend
│   ├── index.html              # AppShell
│   ├── custom.css              # Globale OS-Styles & Kacheln
│   ├── custom_studio.css       # Visual Live CSS Studio
│   ├── views/                  # Modulare View-Templates
│   │   ├── library_view.html   # Zentralbibliothek (120px Header)
│   │   ├── inbox_view.html     # Eingang (120px Header)
│   │   ├── view_showroom.html  # Showroom / Explorer (120px Header)
│   │   ├── operations_view.html# Kanban & Operations
│   │   └── ...
│   └── img/cadre_icons/        # Freigestellte Kader- & Modul-Icons
└── templates/ & .agents/       # Agenten-Manifeste & Skills
```

---

## 6. Support & Notizen

- **Obsidian Sync:** Der Nutzer synchronisiert seinen Obsidian Vault eigenständig. Falls Pfade abweichen, den Pfad in `config/system_settings.json` oder via System-Einstellungen Modal anpassen.
- **Git-Historie:** Die lokale Arbeitskopie ist auf Stand `main` committet.
- Bei Fragen oder Anpassungen kann der Homeserver-Agent direkt auf dieses Dokument aufbauen.
