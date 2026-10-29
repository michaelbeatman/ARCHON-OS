# Archon OS – Entwicklungs-Roadmap & Aufgabenliste

| ID | Meilenstein / Vorhaben | Priorität | Status | Kernfokus |
|---|---|---|---|---|
| **0** | **AI Boardroom finalisieren** | Hoch | Abgeschlossen | Polishing UI, Reset-Logik, PDF-Parsing via pypdf, Client-Disconnect-Handling, strukturierter Markdown-Export |
| **1** | **Updatesystem erarbeiten** | Hoch | Abgeschlossen | Versionierung, Git-Sync, automatisierte Pre-Update-Snapshots (SQLite & Configs), In-App 1-Klick Update & Rollback-Fähigkeit |
| **2** | **Steuerapp für Android** | Mittel | Geplant | PWA vs. Native Kotlin/Flutter-Client, Endpunkt-Sicherheit, Push-Benachrichtigungen, Dynamic DNS/Tailscale-Tunneling |
| **3** | **Multilingualität (i18n)** | Mittel | Geplant | Mehrsprachigkeit für UI-Strings, lokalisierte System-Prompts, Sprachumschaltung de/en |
| **4** | **Multi-User & Kollaboration** | Mittel | Geplant | RBAC-Rollenmodell, Benutzer-Authentifizierung (JWT/OAuth), Sitzungs- und Workspace-Isolation |
| **5** | **Funktionserweiterung / Pluginsystem** | Mittel | Abgeschlossen | Standardisierte Plugin-Schnittstelle (`backend/plugin_manager.py`), Manifeste (`plugin.json`), Lifecycle-Hooks, Registry-Integration & 3 Starter-Plugins |
| **6** | **Designkonzept-Überarbeitung** | Hoch | Geplant | Ergonomisches Designsystem, konsistente Typografie, modernisiertes UI-Layout, Dark/Light-Mode-Verfeinerung |
| **7** | **LinkedIn-Import im CRM (Bugfix & Dedup)** | Dringend | Abgeschlossen | 1.722 Duplikate bei 908 Kontakten bereinigt, CRM-Route & Import-Dedupe zeitzonen- und sender-unabhängig gehärtet |
| **8** | **Obere Icons prüfen & korrigieren** | Hoch | Abgeschlossen | Audit aller oberen Navigations- und Subview-Icons, Behebung doppelter Icons, Korrektur des Kanban-Icons |
| **9** | **Redesign der oberen Leiste & Avatar-Überlappung** | Hoch | Abgeschlossen | Vereinheitlichung nach dem Vorbild "AI Mastermind · Übersicht", Klärung & CSS-Konzept für überlappende Avatare im Kader |
| **10** | **Eingang (Inbox) Funktionsprüfung & Re-Architektur** | Hoch | Abgeschlossen | Suchleiste unter den Header mit Filter-/Markierungstools; linker Balken fokussiert auf markierte/angepinnte Items |
| **11** | **Tokenguard: Zeitraum-Skalierungsleiste für Grafen** | Normal | Abgeschlossen | Interaktive Steuerleiste zur flexiblen Skalierung des Zeitraums (24h, 7T, 30T, 90T, Gesamt) für Verbrauchs-Chart |
| **12** | **Informationsquellen-Strategie (Research Lab)** | Hoch | Offen | Gemeinsame Bestandsaufnahme und Bewertung aller Wissensquellen (Grokipedia, Wikipedia, Fachportale, amtliche Quellen, ArXiv, Websuche): Vertrauensstufen, Rolle KI-generierter Quellen, Kosten/Limits, Quellen-Priorisierung je Fragetyp |
| **13** | **n8n Workflow-Mesh & Routine-Automation** | Hoch | Abgeschlossen | Vollständige n8n-Anbindung, Webhook-Trigger, zeitgesteuerte Routine-Workflows (Morning-Briefing 07:30 Uhr Mo-Fr, Weekly Maintenance So 23:00 Uhr, stündlicher RSS-Scan) |
| **14** | **Telegram Voice-Pipeline (Voice-to-Text & Audio)** | Hoch | Abgeschlossen | Whisper-Transkription eingehender Telegram-Sprachnachrichten, Delegation an Ziel-Agenten, Sprachausgabe via edge-tts |
| **15** | **Kanban Qualitäts-Gate (4-Augen-Review vor Done)** | Hoch | Abgeschlossen | Automatischer Peer-Review-Prüfschritt vor Verschieben auf "Done", Prüfung auf Vollständigkeit & Belege, Re-Iterationsschleife |
| **16** | **Interaktive Showroom-Sandbox & Live-Runner** | Normal | Abgeschlossen | Sichere Ausführung von generiertem Code (Python-Datenanalyse, HTML/JS-Rechner) direkt im Showroom mit interaktiven Testdaten |

---

## Detaillierte Arbeitspakete

### Meilenstein 0: AI Boardroom finalisieren (Abgeschlossen)
- **UI & Ergonomie:** 3-Tab-Architektur (Übersicht, Debatte, Live), Reset-Logik für Standard-Slots, Markdown-Export.
- **Backend & Streaming:** Client-Disconnect-Abbruch via SSE, Bereinigung von Platzhaltermodellen auf `deepseek-chat`.
- **Dokumenten-Pipeline:** Automatisches Extrahieren von PDF- und Textinhalten per Backend (`/api/boardroom/parse-attachment` via `pypdf`).

### Meilenstein 1: Updatesystem erarbeiten (Abgeschlossen)
- **Sync & Release-Lifecycle:** Automatisierte Update-Pipeline zwischen Entwicklungsrechner und Homeserver (`backend/system_updater.py`).
- **In-App 1-Klick-Update:** Eigener Tab *System-Update & Server-Sync* in den Systemeinstellungen mit Status-Anzeige, Commit-Differenz und Installations-Button.
- **Datenintegrität & Snapshots:** Konsistente Online-Snapshots aller Datenbanken (`agent_os.db`, `agentic_memory.db`, `kanban.db`, `state.db`) und Konfigurationen vor jedem Git-Pull.
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

### Meilenstein 4: Multi-User-Architektur
- **Identitäts- & Sitzungsmanagement:** Benutzerkonten mit sicherer Authentifizierung (Session-Tokens, 2FA-Option).
- **Rechte & Rollen (RBAC):** Unterscheidung zwischen Admin-, Operator- und Viewer-Rechten.
- **Daten-Isolation:** Benutzerbezogene Chats, Gedächtnisspeicher und History-Filterung bei gemeinsamen Ressourcen.

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

