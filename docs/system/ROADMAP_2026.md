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
| **13** | **n8n Workflow-Mesh & Routine-Automation** | Hoch | Geplant | Vollständige n8n-Anbindung, Webhook-Trigger, zeitgesteuerte Routine-Workflows (Morning-Briefing, automatisierte Triage, Status-Berichte) |
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

### Meilenstein 12: Informationsquellen-Strategie (Offen)
- **Ausgangslage (Okt 2026):** Grokipedia ist als Standardquelle aktiv (KI-generiert, zaehlt nicht als unabhaengige Quelle in der Triangulation). Wikipedia lieferte im Test wegen Drosselung (HTTP 429) keine Treffer, ArXiv teils HTTP 500, DuckDuckGo zeitweise blockiert.
- **Gemeinsame Sitzung:** Welche Quellen braucht Archon je Fragetyp (Recht/Regulierung, Technik, Markt, Wissenschaft, Tagesaktuelles)? Welche Quelle gilt als amtlich, fachlich belastbar oder nur als Hinweis?
- **Zu klaeren:** Vertrauensstufen und Gewichtung in der Triangulation, Umgang mit KI-generierten Quellen (Grokipedia), Zuverlaessigkeit der Suche (Fallbacks, SearXNG selbst hosten, Tavily/Jina/Firecrawl mit Key), Rate-Limits und Caching der Treffer, Datenschutz bei Drittdiensten (z.B. Jina Reader erhaelt die URL).
- **Ergebnis:** Priorisierte Quellenliste, Konfiguration pro Fragetyp, Entscheidung zu kostenpflichtigen Providern.
- **Hintergrund:** Benchmark und Code-Analyse siehe `scratch/ii/` (ii-researcher-Vergleich, `research_engine_v2.py`).

---

### Meilenstein 13: n8n Workflow-Mesh & Routine-Automation
- **n8n Konnektivität & Health-Check:** Vollständige Kopplung von Archon OS an die lokale oder containerisierte n8n-Instanz über `scripts/mcp_n8n_driver.py` und Webhook-Endpoints.
- **Geplante Routine-Jobs (Cron):** Konfiguration automatisierter Abläufe (z. B. Morning-Briefing um 07:30 Uhr mit Triage neuer E-Mails und offenen Kanban-Tasks, wöchentlicher Backup- und System-Audit).
- **Zwei-Wege-Steuerung:** Triggerung von n8n-Szenarien direkt aus dem Agenten-Chat bzw. per Telegram-Befehl sowie Rückmeldung von n8n-Ergebnissen in das Kanban-Board.

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

