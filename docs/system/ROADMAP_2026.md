# Archon OS – Entwicklungs-Roadmap & Aufgabenliste

| ID | Meilenstein / Vorhaben | Priorität | Status | Kernfokus |
|---|---|---|---|---|
| **0** | **AI Boardroom finalisieren** | Hoch | Abgeschlossen | Polishing UI, Reset-Logik, PDF-Parsing via pypdf, Client-Disconnect-Handling, strukturierter Markdown-Export |
| **1** | **Updatesystem erarbeiten** | Hoch | Abgeschlossen | Versionierung, Git-Sync, automatisierte Pre-Update-Snapshots (SQLite & Configs), In-App 1-Klick Update & Rollback-Fähigkeit |
| **2** | **Steuerapp für Android** | Mittel | Geplant | PWA vs. Native Kotlin/Flutter-Client, Endpunkt-Sicherheit, Push-Benachrichtigungen, Dynamic DNS/Tailscale-Tunneling |
| **3** | **Multilingualität (i18n)** | Mittel | Abgeschlossen | 9 Weltsprachen (de, en, es, fr, pt, ru, ja, ko, zh), Locale-JSONs, dynamische DOM-Engine & Settings-Selector |
| **4** | **Multi-User & Kollaboration** | Mittel | Abgeschlossen | 3-Stufen-Rollenmodell (Admin, Operator, Viewer), PBKDF2-Auth, Sessions, Settings-Verwaltung & Topbar-Badge |
| **5** | **Funktionserweiterung / Pluginsystem** | Mittel | Abgeschlossen | Standardisierte Plugin-Schnittstelle (`backend/plugin_manager.py`), Manifeste (`plugin.json`), Lifecycle-Hooks, Registry-Integration & 3 Starter-Plugins |
| **6** | **Designkonzept-Überarbeitung** | Hoch | Geplant | Ergonomisches Designsystem, konsistente Typografie, modernisiertes UI-Layout, Dark/Light-Mode-Verfeinerung |
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
| **25** | **Operativer Operations-Kalender (ERP, Kanban & Agenten)** | Hoch | Geplant | Integriertes Zeitraster für Kanban-Deadlines, Zahlungsziele/Fristen, n8n-Cronjobs und reale Termine/Geburtstage für automatische Kontaktpflege |
| **26** | **Autonomous Computer-Use & PbD (Demo-to-Skill)** | Kritisch | Abgeschlossen | Vormachen & Lernen per Bot-Screen, Ghost-Cursor Anti-Detection (Bézier-Pfade, Bounding-Box Jitter), SoM-Visual-Grounding und a11y Observation-Pruning |
| **27** | **MCTS Action Trajectories & Deep Reasoning Gate** | Mittel | Abgeschlossen | Optionale Monte-Carlo-Baumsuche in Autonomie-Settings zur Voraus-Simulation heikler Handlungsstränge vor Ausführung |
| **28** | **ERP-Modul zum vollwertigen Kernsystem ausbauen** | Kritisch | Geplant | Von der aktuellen Basis-Stammdatenverwaltung zur E-Rechnung (XRechnung/ZUGFeRD), FinTS/PSD2-Bankabgleich, DATEV-Export, Bestandsbuchung & Beleg-Workflow |
| **29** | **Visueller Formular- & Beleg-Editor (im ERP-Modul)** | Hoch | Geplant | WYSIWYG-/Block-Editor für Angebote, Rechnungen, Mahnungen & Verträge inkl. § 14 UStG-Pflichtfeld-Prüfung, Briefbogen-Layouter und Live-PDF-Vorschau |
| **30** | **Interaktiver Setup-Wizard & Installationsprogramm** | Kritisch | Abgeschlossen | Geführter First-Run-Installer (GUI & CLI) mit Abfrage von Firmendaten, Mandantenstamm, API-Keys, lokalen LLM-Pfaden, IMAP/SMTP und Telegram-Bot-Setup |
| **31** | **Vollständige Englische Version (Global Edition)** | Kritisch | Abgeschlossen | Durchgehende Übersetzung aller 70 Spezialisten-Profile (`SOUL.md`), 832 Prompt-Templates, 55 Boardroom-Frameworks, UI-Masken und Dokumentation auf Englisch |
| **32** | **Telegram-Kommunikation & Gateway-Härtung** | Hoch | Geplant | Konfliktfreies Session-Handling, Inline-Freigabe-Buttons (HITL), Live-Status-Updates bei Langläufer-Tasks, zuverlässiges Agenten-Routing (`/robert`, `/anwalt`) |
| **33** | **Watchdog & Internet-Radar 2.0** | Hoch | Geplant | Semantisches Relevanz-Scoring (Signal vs. Noise), Selbstheilung defekter Scraper/RSS-Feeds, Dubletten-Sperre und automatische Task-Anlage bei Schwellenwerten |
| **34** | **Android-App (Mobile Command & Receipt Scanner)** | Mittel | Geplant | Mobile App für Direkt-Chat, Push-Freigaben (Approval Gates), Sprachnotizen und Kamera-Beleg-Scan direkt in die ERP-Buchhaltung |
| **35** | **GitHub-Präsentation & Public Launch Kit** | Hoch | Abgeschlossen | Zweisprachige Showcase-`README.md`, Architektur-Schaubilder, 90-Sekunden-Walkthrough-Video, One-Line-Installer und Security/License-Badges |
| **36** | **Ökosystem-Verzeichnisse & Community-Integrationen** | Hoch | Abgeschlossen | Offizielle Aufnahme in kuratierte Open-Source- und Self-Hosting-Kataloge (*Awesome-Selfhosted*, *Awesome-AI-Agents*, *Awesome-MCP-Servers*), Community-Blueprints & Integrations-Guides |
| **37** | **Zeiterfassung & Projekt-Nachkalkulation (Time-to-Invoice)** | Hoch | Geplant | Topbar-Stoppuhr & Projekt-Zeiterfassung, Soll-/Ist-Budgetabgleich und 1-Klick-Übernahme gebuchter Stunden als ERP-Rechnungspositionen |
| **38** | **Automatischer Vertrags-, Fristen- & Abo-Wächter** | Hoch | Geplant | Kündigungs-Radar im ERP für Verträge, Leasing & SaaS-Abos mit 30/14-Tage-Vorwarnung via Watchdog/Telegram und fertigem Kündigungsentwurf |
| **39** | **Lokaler Meeting- & Call-Copilot (Audio → Protokoll + Tasks)** | Hoch | Geplant | Lokale Gesprächsaufzeichnung (Whisper mit Sprecher-Trennung), automatische CRM-Aktennotiz und direkte Anlage erkannter To-Dos im Kanban-Board |
| **40** | **Vertrags-Diff & Redlining-Ansicht (Alt gegen Neu)** | Mittel | Geplant | Visueller Klausel-Vergleich für PDF/DOCX-Verungsversionen inkl. automatischer Risiko-Bewertung geänderter Passagen durch `commercial_jurist_contracts` |
| **41** | **Bi-direktionaler Kalender-Sync & Fokus-Blocker** | Hoch | Geplant | Echter 2-Wege-Sync (CalDAV / Google / Outlook) mit automatischer Blockierung freier Deep-Work-Zeitfenster für dringende Kanban-Deadlines |
| **42** | **Geteilte Kunden- & Mandanten-Links (Mini-Freigabe-Portal)** | Mittel | Geplant | Passwortgeschützte, zeitlich begrenzte Showroom-Links zur digitalen Angebotsannahme und Kommentierung mit direktem ERP-Statuswechsel (*Angebot → Auftrag*) |
| **43** | **Multi-Mandanten-Umschalter (Holding / Operative GmbH / SPV)** | Hoch | Geplant | Schnellumschalter in der Topbar für getrennte Datenbank-Kontexte, Nummernkreise, Briefbögen, Bankkonten und Steuernummern je Gesellschaft |
| **44** | **Fertige „1-Click Business Playbooks“ (Workflow-Rezepte)** | Hoch | Geplant | 10 sofort ausführbare End-to-End-Prozessrezepte für Einsteiger (Kunden-Onboarding, Monatsabschluss, Wettbewerbs-Teardown, Lastenheft-zu-Angebot) |
| **45** | **Research Lab zum Deep-Research-Labor ausbauen (Alpha → Produktiv)** | Hoch | Geplant | Mehrstufige Quellen-Triangulation (Trust-Tiers), Live-Citation-Check, ArXiv-/Patent-/Amtsregister-Connectoren, PDF-Dossier-Export & Vault-Auto-Ablage |
| **46** | **Open-Source Community-Hub, Sponsoring & Projekt-Portal** | Hoch | Geplant | Kanonische Dokumentations- und Architektur-Website, GitHub Sponsors & Enterprise-Support-Optionen, mehrsprachige Handbücher und transparente Release-Notes |
| **47** | **„Zero-Install“ Read-Only Live-Demo-Modus (`ARCHON_DEMO_MODE`)** | Hoch | Abgeschlossen | Gehärteter öffentlicher Demo-Mandant („Mittelstand Muster GmbH“) mit gesperrten Schreib-/Shell-/Egress-Pfaden und deterministischen Muster-Debatten ohne Token-Kosten |
| **48** | **Archon OS als nativer MCP-Server (`/mcp` Gateway)** | Hoch | Geplant | Scoped-API-Key- und HITL-geschützter Model-Context-Protocol-Endpunkt zur Nutzung aller 70 Spezialisten, Boardroom-Voten und Vault/CRM-Daten aus Claude Desktop, Cursor & VS Code |
| **49** | **EU AI Act Compliance-Engine & 1-Klick-Verfahrensdokumentation** | Kritisch | Geplant | Automatische Risikoklassifizierung je Spezialist (Anhang III / Art. 50), KI-Kompetenznachweis-Log (Art. 4) und prüferfertiger GoBD- & EU-AI-Act-Verfahrensdokumentations-PDF-Export |
| **50** | **Agent-Eval- & Modell-Benchmark-Arena** | Hoch | Geplant | Lokales Gold-Task-Testdeck (~25 Referenzfälle) zum direkten Qualitäts-, Halluzinations-, Latenz- und Kostenvergleich vor Modell- oder `SOUL.md`-Wechseln |
| **51** | **Portabler „Squad-Blueprint“-Paketmanager (`.archonpack`)** | Hoch | Geplant | 1-Klick-Export & -Import kompletter Fachabteilungen (Agenten-Profile, 3-Stufen-`SOUL.md`, Fach-Skills, Boardroom-Frameworks & n8n-Flows) für Community- und Branchen-Pakete |
| **52** | **Pre-Flight Cost-Estimator & „Shadow-Mode“** | Mittel | Geplant | Vorab-Token-/Kostenschätzung vor großen Delegations- und Boardroom-Ketten sowie passiver Parallel-Trockenlauf neuer Agenten neben echten Entscheidungen bis > 90 % Trefferquote |
| **53** | **„Epistemic Hygiene“-Wächter für den Obsidian-Vault** | Mittel | Geplant | Periodischer lokaler Embedding- und Konsistenz-Scan über Projekte & Wissensbibliothek zur Erkennung widersprüchlicher Zahlen, Konditionen und veralteter Rechts-/Vertragsstände |

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

### Meilenstein 28: ERP-Modul zum vollwertigen Kernsystem ausbauen (Geplant – Kritisch)
- **Vom Prototyp zum produktiven KMU-ERP:** Ausbau der aktuell noch rudimentären Stammdaten- und Belegtabellen zu einer durchgängigen kaufmännischen Prozesskette (*Lead → Angebot → Auftragsbestätigung → Lieferschein/Leistungsnachweis → Teil-/Schlussrechnung → Buchung → Zahlungsabgleich*).
- **E-Rechnungspflicht (XRechnung & ZUGFeRD 2.2):** Valider XML-/PDF/A-3-Export und -Import nach EN 16931 für den B2B-Geschäftsverkehr ab 2025/2026.
- **Bankkonten-Synchronisation (FinTS / HBCI / PSD2):** Automatischer Abruf von Bankumsätzen und KI-gestütztes Matching offener Posten (OPOS) gegen Ausgangs- und Eingangsrechnungen.
- **Steuerberater- & DATEV-Brücke:** Export buchungsfertiger Stapel im DATEV-Format (EXTF/CSV + digitale Belegbilder) für den Monatsabschluss (`finance_lead`).

### Meilenstein 29: Visueller Formular- & Beleg-Editor im ERP-Modul (Geplant – Hoch)
- **Interaktiver Vorlagen-Baukasten:** Ausbau von Kapitel `13.2 Formulare & Vorlagen` zu einem visuellen Editor für Briefbögen, Angebote, Rechnungen, Mahnungen und Verträge.
- **Dynamische Datenbindung & § 14 UStG-Check:** Platzhalter-System (`{{customer.name}}`, `{{invoice.items_table}}`, `{{company.vat_id}}`) mit automatischer Live-Prüfung aller umsatzsteuerlichen Pflichtangaben.
- **Echtzeit-PDF-Vorschau:** Nebeneinander-Ansicht von Layout-Einstellungen (Schriften, Ränder, Logo, Fußzeilen-Spalten, QR-GiroCode für Sofortüberweisung) und gerendertem A4-PDF.

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

### Meilenstein 43: Multi-Mandanten-Umschalter (Holding / Operative GmbH / SPV) (Geplant – Hoch)
- **Mandantenfähigkeit in einer Instanz:** Auswahl-Dropdown in der Topbar zum nahtlosen Wechsel zwischen mehreren eigenen Gesellschaften (z. B. Holding, operative GmbH, Immobilien-SPV oder Privatvermögen).
- **Strikte Kontext- & Nummernkreis-Trennung:** Jede Gesellschaft besitzt eigene ERP-Nummernkreise, Briefbögen, Steuernummern, Bankkonten, Kostenstellen und getrennte Buchhaltungs-Exporte bei gleichzeitigem Zugriff auf dieselbe 70-köpfige Spezialisten-Flotte.

### Meilenstein 44: Fertige „1-Click Business Playbooks“ – Workflow-Rezepte (Geplant – Hoch)
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

### Meilenstein 48: Archon OS als nativer MCP-Server (`/mcp` Gateway) (Geplant – Hoch)
- **Vom reinen MCP-Client zum zentralen Unternehmens-MCP-Hub:** Bereitstellung eines standardkonformen Model-Context-Protocol-Endpunkts (`/mcp` via Streamable HTTP / SSE), abgesichert über Scoped-API-Keys (M17) und die bestehenden Human-in-the-Loop-Freigabe-Gates.
- **Externe IDE- & Desktop-Anbindung:** Externe Clients wie *Claude Desktop*, *Cursor*, *Windsurf*, *VS Code* oder *Hermes Desktop* können direkt Archon-Spezialisten delegieren (`delegate_specialist`), ein mehrstimmiges AI-Boardroom-Votum einholen (`convene_boardroom`) oder kontrolliert Wissen aus Obsidian-Vault und ERP/CRM abfragen.
- **Granulare Tool-Freigabe pro API-Key:** Jeder verbundene MCP-Client sieht ausschließlich die ihm per Scope freigegebenen Fach-Agenten und Lese-/Schreib-Werkzeuge.

### Meilenstein 49: EU AI Act Compliance-Engine & 1-Klick-Verfahrensdokumentation (Geplant – Kritisch)
- **Automatische EU-AI-Act-Risikoklassifizierung je Spezialist:** Systematische Einstufung aller aktiven Agenten-Profile nach EU-KI-Verordnung (z. B. *Anhang-III-Hochrisiko* bei Personal-/Bewerbervorauswahl durch `hr_recruiter`, *Art.-50-Transparenzpflicht* bei externer Kommunikation/Content, *minimales Risiko* bei interner Analyse) inklusive Pflicht-Guardrails vor Aktivierung.
- **KI-Kompetenznachweis- & Governance-Register (Art. 4 EU AI Act):** Revisionssicheres Protokoll über freigegebene Modelle, System-Prompts (`SOUL.md`-Hashes), Datenabfluss-Regeln (Zero-Egress-Status) und eingewiesene Bediener.
- **1-Klick-PDF-Verfahrensdokumentation (GoBD + EU AI Act):** Automatischer Generator, der aus der realen Laufzeit-Konfiguration (`config/`, `agent_profiles.json`, `model_routing.json`) und der kryptografischen `audit_log.db` (M21) ein prüferfertiges Verfahrensdokumentations-PDF für Geschäftsführung, Beirat, Datenschutzbeauftragte und Wirtschaftsprüfer erzeugt.

### Meilenstein 50: Agent-Eval- & Modell-Benchmark-Arena (Pre-Live Regressions-Schutz) (Geplant – Hoch)
- **Kuratierter Gold-Standard-Prüfkatalog (~25 Referenz-Tasks):** Lokales Benchmark-Deck mit repräsentativen Unternehmensaufgaben (JSON-Delegationstreue, juristischer Klausel-Risikocheck, Deckungsbeitrags-/Margen-Kalkulation, DSGVO-Schwärzung, Zero-Hallucination-Faktentreue bei fehlenden Daten).
- **A/B-Modell- & SOUL-Vergleich vor Live-Schaltung:** Lässt bei Modellwechseln (z. B. neues lokales Ollama-/Qwen-/Llama-Modell) oder `SOUL.md`-Umbauten alte gegen neue Konfiguration automatisiert gegeneinander antreten.
- **Entscheidungs-Scorecard im Cockpit:** Direkter Vorher/Nachher-Ausweis von Qualitätsscore, Halluzinationsrate, Schema-Treue, Antwortlatenz und Kosten pro Aufgabe vor Produktivsetzung.

### Meilenstein 51: Portabler „Squad-Blueprint“-Paketmanager (`.archonpack`) (Geplant – Hoch)
- **Komplette Fachabteilungen als Einzelpaket bündeln:** 1-Klick-Export und signierter Import ganzer Spezialisten-Squads als portables `.archonpack`-Archiv (Agenten-Definitionen, 3-Stufen-`SOUL.md`, zugehörige Fach-Skills, passende Boardroom-Frameworks und optionale n8n-Workflow-Vorlagen).
- **Schlüsselfertige Branchen- & Domänen-Blueprints:** Ermöglicht sofort installierbare Fachpakete wie *„Pharma / GDP-Quality-Squad“*, *„Immobilien-Ankaufsprüfung & SPV-Analyse“*, *„Steuer- & Monatsabschluss-Vorbereitung“* oder *„E-Commerce Operations“*.
- **Abhängigkeits- & Sicherheits-Prüfung beim Import:** Vorab-Inspektion aller enthaltenen Prompts, Tool-Berechtigungen und benötigten MCP-Connectoren in einer Quarantäne-Vorschau vor Aktivierung im Kader.

### Meilenstein 52: Pre-Flight Cost-Estimator & „Shadow-Mode“ (Trockenlauf für Agenten) (Geplant – Mittel)
- **Pre-Flight-Kostenvoranschlag vor großen Ketten:** Transparente Vorab-Kalkulation vor Start mehrstufiger Delegationskaskaden oder 6-Phasen-Boardroom-Debatten (*„Geschätzt: ~48k Tokens ≈ 0,14 € · 4 lokale Zero-Cost-Agenten + 1 Cloud-Synthese“*) mit konfigurierbarer Kostenschwelle für Pflicht-Freigaben.
- **Passiver „Shadow-Mode“ für neue Agenten & Prompts:** Neue oder umgebaute Spezialisten lesen reale Eingänge, Tickets und Aufgaben im Hintergrund parallel mit und erzeugen interne Entwürfe, ohne nach außen senden oder Status mutieren zu dürfen.
- **Reifegrad-Freischaltung nach Trefferquote:** Das Cockpit legt den Shadow-Entwurf neben die reale menschliche Entscheidung und empfiehlt die Beförderung in den aktiven Betrieb erst ab einer gemessenen Übereinstimmungsquote (z. B. > 90 % über 20 Vorgänge).

### Meilenstein 53: „Epistemic Hygiene“-Wächter für den Obsidian-Vault (Geplant – Mittel)
- **Wöchentlicher Wissens-Konsistenz-Scan:** Lokaler Hintergrund-Job (Embeddings + regelbasierte Faktenextraktion) über `01_PROJEKTE` und `02_Wissensbibliothek`, der schleichende Widersprüche zwischen eigenen Notizen erkennt (z. B. abweichende Zinssätze, Stundensätze, Fristen oder Projektannahmen in verschiedenen Dokumenten).
- **Verfallsdatum- & Rechtsstand-Radar:** Markiert Notizen, Kalkulationen und Vorlagen mit abgelaufenen Vertragsständen, überholten Steuersätzen/Gesetzesfassungen oder verwaisten Querverweisen.
- **Saubere Bereinigungs-Tickets statt stiller Korrektur:** Legt erkannte Diskrepanzen mit exaktem Zitat-Paar (Dokument A vs. Dokument B) als prüfbares Klärungs-Ticket im Triage-/Kanban-Board an, ohne das Second Brain ungefragt umzuschreiben.




