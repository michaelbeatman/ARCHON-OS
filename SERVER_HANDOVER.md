# 🚀 Archon OS (AgenticOS 2026) — Server Handover & Deployment Guide

> **Zielgruppe:** Antigravity AI-Agent auf dem Homeserver  
> **Projekt:** Archon OS 2026 / Agentic Operating System  
> **Version / Stand:** Iteration 0.3 — 24. Oktober 2026 (Ready for Server Deployment)

---

## 1. Übersicht & Systemarchitektur

Archon OS 2026 ist ein agentisches Betriebssystem (Agentic OS), basierend auf einer 7-Säulen-Architektur:
1. **Kernel & Scheduling:** Asyncio Event-Loop, Watchdog Daemon (30s Überwachung), tickless scheduling.
2. **Process Model:** Subagenten als isolierte Prozesse mit deklarativen Manifesten und Status-Tracking.
3. **Device Driver:** MCP-Server Ökosystem für dynamische Tool-Bindings.
4. **Filesystem & Memory:** SQLite im WAL-Modus (`data/agentic_memory.db`) für non-blocking Writes mit den 5 Standardtabellen (`tasks`, `conversations`, `learnings`, `kv_store`, `user_profile`).
5. **Hardware Abstraction & Routing:** Multi-Provider AI-Routing (`core_dispatcher.py` & `backend/agent_router.py`).
6. **Governance & Zero-Trust:** Audit-Logging (`backend/audit_log.py`), RBAC-Jail (`backend/agent_rbac_jail.py`), Egress-Firewall und Consensus-Gates.
7. **Selbst-Evolution:** Laufzeit-Skill-Management (`.agents/skills/` und `backend/skill_synthesizer.py`).

### Kernkomponenten & Ports
- **Archon OS Hauptserver:** FastAPI / Uvicorn auf Port `8420` (`http://localhost:8420` oder `http://<HOMESERVER-IP>:8420`)
- **Watchdog Daemon:** `watchdog_daemon.py` zur präemptiven Task-Überwachung (30s Takt)
- **Zentraldatenbank:** `data/agentic_memory.db` (SQLite WAL)
- **Systemkonfiguration:** `settings.json` (SSOT für alle 36 Systemmodule)
- **Frontend AppShell:** Single-Page-Applikation unter `static/index.html` mit modularen HTML-Views (`static/views/`)
- **Externe Sidecars (optional):**
  - **AnythingLLM (RAG Index):** Port `3001`
  - **n8n (Workflow Engine):** Port `5678`
  - **PocketBase (CRM / Media):** Port `8090`
  - **Obsidian Vault:** Synchronisiertes Verzeichnis des Nutzers

---

## 2. Neuerungen & Highlights in Iteration 0.3

1. **36 Enterprise Backend-Module (`backend/`):**
   - Vollständige Suite industrieller Schutz- und Optimierungsmodule: Concurrency Throttle, Circuit Breaker, Consensus Gate, Audit Log, Deadlock Supervisor, Egress Firewall, Token Clipper, Memory Consolidator, RAG Bridge, Task Self-Healer und War Room Simulator.
   - Alle Module werden zentral über `settings.json` und die neue System-Settings API gesteuert.

2. **Archon Prompt Studio (1.079 Vorlagen & SOPs):**
   - 824 parametrisierte Enterprise-Prompts, vollständig im Clean-Room-Verfahren auf Deutsch re-authored und frei von Fremdmarken oder Fremd-URLs.
   - 255 kuratierte Fabric SOP-Analysemuster (Daniel Miessler, MIT-Lizenz) nahtlos integriert.
   - Offizielle Lizenzdokumentation in `THIRD_PARTY_LICENSES.md`.

3. **Persistente Systemeinstellungen:**
   - Modell-Auswahl (Default Model) und Autonomie-Level werden sofort in `settings.json` gespeichert und überleben Server-Neustarts und Container-Rebuilds.

4. **UI-Design — Taktile Formular-Mulde:**
   - Alle Eingabefelder, Textareas und Dropdown-Menüs verfügen über einen inneren Schatten (`shadow-inner`) für maximale visuelle Tiefenwirkung und taktile Usability.

5. **Dokumentation & Glossar 2026:**
   - Umfassendes Word-Handbuch (`docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx`) und System-Glossar (`docs/ARCHON_OS_SYSTEM_GLOSSAR_2026.docx`) mit Trade-Off-Matrix (Problem, Lösung, Kosten/Trade-Off) für jedes Modul.

---

## 3. Schritt-für-Schritt Einrichtung auf dem Homeserver

Führe als Antigravity-Agent auf dem Homeserver folgende Schritte aus:

### Schritt 1: Workspace vorbereiten & entpacken
Entpacke das übertragene Archiv `AgenticOS-2026_Homeserver_Deploy_v0.3.zip` in das gewünschte Zielverzeichnis (z. B. `/opt/agenticos-2026` oder `~/AgenticOS-2026` oder `D:\AgenticOS-2026`).

```bash
cd AgenticOS-2026
ls -la
```

### Schritt 2: Automatisierte Einrichtung ausführen

**Unter Linux / macOS:**
```bash
chmod +x setup_homeserver.sh
./setup_homeserver.sh
```

**Unter Windows (PowerShell als Administrator):**
```powershell
.\setup_homeserver.ps1
```

*Das Skript erstellt automatisch das Virtual Environment `.venv`, installiert alle Pakete aus `requirements.txt`, legt bei Bedarf `.env` an und validiert die Datenbankverbindung.*

### Schritt 3: Umgebungsvariablen (.env) konfigurieren
Prüfe die Datei `.env`:
- `PORT=8420`
- `HOST=0.0.0.0` (für Zugriff im Heimnetz)
- API-Keys eintragen: OpenAI, Anthropic, Gemini, DeepSeek, OmniRoute, Composio, Telegram etc.

### Schritt 4: Server starten

**Manueller Teststart:**
```bash
source .venv/bin/activate       # Auf Linux/macOS
# bzw. .\.venv\Scripts\activate # Auf Windows

python main.py
```
Der Server lauscht auf `http://0.0.0.0:8420`.

**Hintergrund-Betrieb / Daemon:**
```bash
# Archon OS Hauptserver
nohup python main.py > server.log 2>&1 &

# Watchdog Daemon (überwacht alle 30s hängende Tasks)
nohup python watchdog_daemon.py > watchdog.log 2>&1 &
```

---

## 4. Verifikations-Checkliste

1. **HTTP Status 200 auf Haupt-App:**
   ```bash
   curl -I http://localhost:8420/
   ```
2. **API Status & Health:**
   ```bash
   curl -s http://localhost:8420/api/system/status
   ```
3. **Archon Prompt Studio (1.079 Vorlagen):**
   ```bash
   curl -s http://localhost:8420/api/templates/catalog | grep -o '"templates":\[[^]]*\]' | head -c 100
   ```
4. **Settings-Persistenz:**
   Prüfe, ob `settings.json` im Arbeitsverzeichnis liegt und lesbar ist.

---

## 5. Support & Notizen

- **Git-Repository:** Die vollständige Git-Historie bis zum Release-Commit `v0.3` liegt als `AgenticOS-2026_GitBundle_v0.3.bundle` bei. Ein frischer Clone kann jederzeit mit `git clone AgenticOS-2026_GitBundle_v0.3.bundle AgenticOS-2026` erzeugt werden.
- **Obsidian Sync:** Der Nutzer synchronisiert seinen Obsidian Vault eigenständig. Falls Pfade abweichen, den Pfad in `config/system_settings.json` oder via Einstellungen anpassen.
