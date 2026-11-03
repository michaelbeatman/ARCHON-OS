# Archon Agentic OS 2026

Autonomes, multi-agentenbasiertes Betriebssystem für Unternehmen und Gründer. Kombiniert 57 spezialisierte KI-Fachagenten, strukturierte AI-Boardroom-Debatten, interaktiven Computer-Use mit Programming by Demonstration (PbD), lokale DSGVO-Datenhaltung und autonome Selbst-Evolution.

---

## Schnellstart: 1-Click Installation (Windows, Mac, Linux)

### Voraussetzungen
- **Docker Desktop** (unter Windows mit aktiviertem WSL2-Backend): [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)

### Installation unter Windows (1-Click)
1. Repository klonen oder als ZIP entpacken.
2. Doppelklick auf die Datei **`setup.bat`** (oder Rechtsklick auf `setup.ps1` -> *Mit PowerShell ausführen*).
3. Das Skript prüft Docker, legt Standard-Ordner und `.env` an, startet die Container und öffnet das Dashboard automatisch im Standard-Browser:
   ```text
   http://localhost:8501
   ```

*Für den täglichen Start nach der Erstinstallation genügt ein Doppelklick auf `start.bat`. Zum Beenden dient `stop.bat`.*

### Installation unter Linux / macOS
```bash
# 1. Repository klonen
git clone https://github.com/michaelbeatman/Agentic-Archon-Os.git
cd Agentic-Archon-Os

# 2. Konfiguration vorbereiten
cp .env.example .env

# 3. Cluster starten
docker compose up -d

# 4. Dashboard im Browser öffnen
open http://localhost:8501   # bzw. xdg-open unter Linux
```

---

## System-Dienste und Port-Übersicht

Nach dem Start laufen drei koordinierte Container:

| Dienst | Port | Funktion |
|---|---|---|
| **ARCHON-OS** | `8501` | Zentrales Web-Dashboard, FastAPI-Backend, SQLite-Datenbanken & REST-APIs |
| **Hermes Core** | `8644` | Autonomes Agenten-Gateway, WebSocket-Stream & Cron-Scheduling |
| **n8n Automation** | `5678` | Visuelle Workflow-Engine für Webhooks, CRM-Sync und Hintergrund-Jobs |

---

## Kern-Module & System-Säulen

### 1. Agentenkader: 57 Spezialisten in 11 Domänen
Das Gesamtsystem deckt alle Unternehmensbereiche mit festen Profilen und System-Prompts (`SOUL.md`) ab:
- **Geschäftsführung & Strategie:** Master Orchestrator (Default), Robert (Strategic Copilot), Micha (Owner), Board Secretary
- **Recht, Finanzen & Steuern:** Tax & Holding Advisor, General Counsel, Compliance Guardian, Liquiditätsplaner
- **Software & Infrastruktur:** Fullstack Engineer, DevOps Operator, Security Auditor, Database Architect
- **Marketing, Vertrieb & CRM:** Growth Strategist, Funnel Optimizer, CRM Manager, Content Creator
- **Forschung & Produkt:** Deep Research Specialist, Product Owner, UX Researcher

### 2. AI-Boardroom: Mehrperspektivische Entscheidungsfindung
Bei strategischen Richtungsentscheidungen, Budgetfreigaben oder Risikoanalysen startet der AI-Boardroom eine strukturierte 6-Phasen-Debatte:
- **Phasen:** Problem-Framing $\rightarrow$ Isolierte Agenten-Perspektiven $\rightarrow$ Kritiker-Kreuzverhör $\rightarrow$ Synthese $\rightarrow$ Konsens-Abstimmung $\rightarrow$ Verbindliches Vorstandsmemo.
- **Archivierung:** Automatische Ablage der Memos in der Decision-Engine-Historie und im Obsidian-Vault.

### 3. Bot Screen: Autonomous Computer-Use & Programming by Demonstration (PbD)
Ermöglicht Agenten das visuelle Steuern von Webseiten und Web-Apps im virtuellen Desktop (CDP 9222):
- **Programming by Demonstration (PbD):** Über den Button `[ 🔴 Vormachen & Aufnehmen ]` vollzieht der Bediener eine Aufgabe im Portal (z. B. Jobbörse, ERP) einmalig manuell. Das System schneidet Klicks, Eingaben und begleitende Sprach-/Textkommentare mit und synthetisiert daraus automatisch ein wiederverwendbares Skill-Paket (`SKILL.md`) und ein Python-Skript.
- **Anti-Bot Trajektorien (Ghost-Cursor):** Mausbewegungen folgen biomechanischen Bézier-Kurven mit Fitts's Law Geschwindigkeitsdämpfung. Klickkoordinaten erhalten einen Gauss-verteilten Versatz innerhalb der Ziel-Schaltfläche (Bounding-Box Jitter), und Tastaturanschläge variieren zwischen 50ms und 180ms, um Anti-Bot-WAFs zu umgehen.
- **Observation Pruning (a11y Tree):** Der Schalter `[ 🌲 a11y Pruning: -85% ]` filtert bis zu 90% des DOM-Mülls (Tracking-Pixel, SVGs, tiefe Layout-Divs) heraus und übergibt Modellen einen kompakten, semantischen Accessibility-Tree.
- **Sicherheits-Gate & Notfall-Stopp:** Autorisierungs-Kippschalter zur Übergabe an den Agenten und roter `[ 🛑 Notfall-Stopp ]`-Button für den sofortigen Kontrollentzug.

### 4. Autonome Selbst-Evolution & Heuristische Suche
- **Voyager Tooling:** Fehlt einem Agenten ein Werkzeug zur Lösung einer Teilaufgabe, generiert er den Python-Code selbst, testet ihn in einer isolierten Sandbox mit Assertions, behebt Tracebacks autonom und bindet das Werkzeug fest ins System ein.
- **Monte Carlo Tree Search (MCTS):** Simuliert vor irreversiblen oder hochriskanten Aktionen alternative Handlungsstränge, berechnet $Q$-Werte und wählt den sichersten Pfad. Standardmäßig token-sparend konfigurierbar.
- **Speculative Pre-fetching:** Reagiert auf Tippeingaben im Chat und lädt CRM-Kontakte oder ERP-Belege spekulativ in den RAM-Cache (<5ms Latenz).
- **Just-in-Time Personas:** Generiert flüchtige Spezialisten für seltene Nischenaufgaben und entfernt sie nach getaner Arbeit rückstandsfrei aus dem Speicher.

### 5. Multi-Agenten-Gruppenchat & Kommunikations-Leitstand
Der Funkverkehr in Operations trennt die Agenten-Interaktion in drei dedizierte Kanäle:
- `#all-stream`: Gesamtüberblick aller System- und Agentenereignisse in Echtzeit.
- `#boardroom`: Reines Transkript der strategischen Debatten zwischen den Führungsagenten.
- `#projekte-tasks`: Vorgangsbezogene Abstimmungen zu laufenden Kanban-Karten.

### 6. Datenschutz, Zero-Trust & DSGVO-Sicherheit
- **Physische Daten-Isolation:** Mandantenbezogene SQLite-Datenbanken (`data/tenants/<mandant>/`) mit Write-Ahead Logging (WAL-Modus).
- **Dual-LLM Prompt-Injection Guard:** Strikte Quarantäne für externe Webinhalte und Mails vor der Weitergabe an Agenten mit Werkzeugrechten.
- **Egress-Firewall & PII-Scrubber:** Automatische Schwärzung von sensiblen Kundendaten und Ausführungskontrolle für externe Netzaufrufe.
- **Master-Sync Schutz:** Schreibzugriffe auf das zentrale GitHub-Repository sind an kryptografische Master-Tokens gebunden; Arbeitsinstanzen dritter Nutzer laufen im isolierten Read-Only-Clientmodus.

---

## Verzeichnisstruktur

```text
AgenticOS-2026/
├── backend/                  # Kern-Module (FastAPI, Autonomie, Security, ERP)
│   ├── computer_use_pbd.py   # PbD-Engine, Ghost-Cursor & a11y Pruner
│   ├── self_evolving_tooling.py # Voyager-Loop & dynamische Werkzeuge
│   ├── mcts_engine.py        # Monte Carlo Tree Search Trajektorien
│   ├── speculative_prefetcher.py # Sub-5ms RAM-Cache Vorlader
│   ├── jit_persona_engine.py # Flüchtige Ad-hoc Spezialisten
│   ├── operations_api.py     # Operations-, Kanban- & Bot-Screen-Routen
│   └── dual_llm_sanitizer.py # Quarantäne gegen Prompt Injection
├── static/                   # Benutzeroberfläche (Single Page Application)
│   ├── views/                # HTML-Templates (Agentenkader, Operations, etc.)
│   ├── js/                   # Frontend-Logik (Mauszeiger, PbD, Chat)
│   └── css/                  # Styling & Frosted-Glass-Overlays
├── scripts/                  # Wartungs-, Sync- und Validierungs-Skripte
│   └── dynamic_tools/        # Autonom synthetisierte Voyager-Werkzeuge
├── .agents/skills/           # Registrierte Skills mit SKILL.md-Manifesten
├── data/                     # Lokale Datenbanken (Kanban, ERP, Tenants)
├── docs/                     # System-Handbuch & Architektur-Spezifikationen
│   └── SYSTEM_HANDBUCH.md    # Vollständiges System-Handbuch (300+ Seiten)
├── docker-compose.yml        # Multi-Container-Orchestrierung
├── setup.bat                 # 1-Click-Installer für Windows
├── start.bat                 # Schneller Start für den Alltag
├── stop.bat                  # Geordnetes Herunterfahren
└── settings.json             # Modul-Schwellenwerte & Autonomie-Richtlinien
```

---

## System-Handbuch & Weiterführende Dokumentation

Die vollständige Dokumentation mit detaillierten Anleitungen zu allen 19 Modulen, API-Endpunkten und SOPs befindet sich unter:

* **[Offizielles System-Handbuch](docs/SYSTEM_HANDBUCH.md)**
* **[Entwicklungs-Roadmap 2026](docs/system/ROADMAP_2026.md)**

---

## Lizenz & Vertraulichkeit

Dieses Projekt ist urheberrechtlich geschützt. Entwickelt für die private und geschäftliche Agenten-Orchestrierung von Michael Keller. Alle Rechte vorbehalten.
