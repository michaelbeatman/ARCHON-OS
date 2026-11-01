"""
System Handbuch Generator - Hybrid Master Edition
Builds docs/SYSTEM_HANDBUCH.md:
- Chapters 1 to 16 follow user's exact structure with concise explanations and cross-references.
- Chapter 3 includes full 57-agent roster.
- Appendices I, II, III preserved from Word template.
- Appendices IV & V contain the UNABRIDGED full-text markdown guides from docs/security/ and docs/system/.
"""

import os
import sys
import json
import re

DOCS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DOCS_DIR not in sys.path:
    sys.path.insert(0, DOCS_DIR)

from backend.document_parser import document_parser

DOCX_FILE = os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")
TARGET_MD = os.path.join(DOCS_DIR, "docs", "SYSTEM_HANDBUCH.md")


def load_agent_roster():
    inv_file = os.path.join(DOCS_DIR, "data", "eu_ai_act_inventory.json")
    prof_file = os.path.join(DOCS_DIR, "data", "agent_profiles.json")

    inventory = []
    if os.path.exists(inv_file):
        with open(inv_file, "r", encoding="utf-8") as f:
            inventory = json.load(f)

    profiles = []
    if os.path.exists(prof_file):
        with open(prof_file, "r", encoding="utf-8") as f:
            profiles = json.load(f)

    prof_map = {p.get("id"): p for p in profiles}
    by_cat = {}
    for a in inventory:
        cat = a.get("category", "7. Tech, Software & Data")
        by_cat.setdefault(cat, []).append(a)

    return by_cat, prof_map


def read_guide(rel_path):
    full_path = os.path.join(DOCS_DIR, rel_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return f"*(Dokument {rel_path} nicht gefunden)*"


def build_handbuch_hybrid():
    print(f"Parsing DOCX source: {DOCX_FILE}...")
    res = document_parser.parse_docx(DOCX_FILE)
    full_text = res.get("text", "")

    # Locate core text blocks from Word doc
    idx_vorwort = full_text.find("Vorwort: Was ist Archon OS")
    idx_cap1 = full_text.find("1. Mission Control (Cockpit & Leitstand)")
    idx_cap2 = full_text.find("2. Operations – Operative Projektsteuerung & Funk")
    idx_cap3 = full_text.find("3. Eingang & Triage (HITL-Gatekeeper & Postfach)")
    idx_cap4 = full_text.find("4. Agenten-Kader & Flottenmanagement")
    idx_cap5 = full_text.find("5. Showroom (Projekt-Explorer & Artefakt-Galerie)")
    idx_cap6 = full_text.find("6. Zentralbibliothek & Wissensmanagement")
    idx_cap7 = full_text.find("7. AI Mastermind & Boardroom (3-Tab-Architektur & 34 Frameworks)")
    idx_cap8 = full_text.find("8. LLM Gateway (OmniRoute AI Router)")
    idx_cap9 = full_text.find("9. Token Guard (Guardian & Budgetwächter)")
    idx_cap10 = full_text.find("10. Research Lab (Deep Search & Wissensbeschaffung)")
    idx_cap11 = full_text.find("11. Telemetrie & Logs (Live-Audit Stream)")
    idx_cap12 = full_text.find("12. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)")
    idx_cap13 = full_text.find("13. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector")
    idx_cap14 = full_text.find("14. Design System Lab & AppShell-Architekt")
    idx_cap15 = full_text.find("15. System Control Center & Einstellungen")
    idx_anhang1 = full_text.find("ANHANG I:")
    idx_anhang2 = full_text.find("ANHANG II:")
    idx_anhang3 = full_text.find("ANHANG III:")

    vorwort_text = full_text[idx_vorwort:idx_cap1].strip() if idx_vorwort != -1 and idx_cap1 != -1 else ""
    text_mc = full_text[idx_cap1:idx_cap2].strip() if idx_cap1 != -1 and idx_cap2 != -1 else ""
    text_ops = full_text[idx_cap2:idx_cap3].strip() if idx_cap2 != -1 and idx_cap3 != -1 else ""
    text_inbox = full_text[idx_cap3:idx_cap4].strip() if idx_cap3 != -1 and idx_cap4 != -1 else ""
    text_showroom = full_text[idx_cap5:idx_cap6].strip() if idx_cap5 != -1 and idx_cap6 != -1 else ""
    text_library = full_text[idx_cap6:idx_cap7].strip() if idx_cap6 != -1 and idx_cap7 != -1 else ""
    text_mastermind = full_text[idx_cap7:idx_cap8].strip() if idx_cap7 != -1 and idx_cap8 != -1 else ""
    text_guardian = full_text[idx_cap9:idx_cap10].strip() if idx_cap9 != -1 and idx_cap10 != -1 else ""
    text_research = full_text[idx_cap10:idx_cap11].strip() if idx_cap10 != -1 and idx_cap11 != -1 else ""
    text_telemetrie = full_text[idx_cap11:idx_cap12].strip() if idx_cap11 != -1 and idx_cap12 != -1 else ""
    text_prompt = full_text[idx_cap12:idx_cap13].strip() if idx_cap12 != -1 and idx_cap13 != -1 else ""
    text_css = full_text[idx_cap13:idx_cap14].strip() if idx_cap13 != -1 and idx_cap14 != -1 else ""
    text_settings = full_text[idx_cap15:full_text.find("16. Autonome Resilienz")].strip() if idx_cap15 != -1 else ""
    
    text_anhang1 = full_text[idx_anhang1:idx_anhang2].strip() if idx_anhang1 != -1 and idx_anhang2 != -1 else ""
    text_anhang2 = full_text[idx_anhang2:idx_anhang3].strip() if idx_anhang2 != -1 and idx_anhang3 != -1 else ""
    text_anhang3 = full_text[idx_anhang3:].strip() if idx_anhang3 != -1 else ""

    by_cat, prof_map = load_agent_roster()

    md = []

    # Title & Metadata
    md.append("""# ARCHON AGENTIC OS 2026
## Offizielles System-Handbuch, Modul-Referenz & Praxisführer

> **System-Version:** v0.3.6 (Sentinel) / v0.3.7  
> **Klassifizierung:** Intern / Streng Vertraulich (GoBD & ISO 27001 konform)  
> **Stand:** 31. Oktober 2026  
> **Geltungsbereich:** Gesamtes Archon OS Ökosystem (57 Fachagenten, 14 Fachmodule, Daemon-Kernel, Governance & Spezialleitfäden)

---

## Inhaltsverzeichnis

- **Vorwort: Was ist Archon OS und wie arbeitet man damit?**
- **1. Operations – Operative Projektsteuerung & Funk**
  - 1.1 Mission Control
  - 1.2 Kanban
  - 1.3 Organisation
  - 1.4 n8n Automatisierung
  - 1.5 Kommunikation
- **2. Posteingang & Ereignis-Stream**
  - 2.1 Übersicht
  - 2.2 Webhooks
  - 2.3 Intern
  - 2.4 E-Mail
  - 2.5 Messenger
  - 2.6 Freigaben
- **3. Agenten-Kader**
  - 3.1 Übersicht
  - 3.2 Chat
  - 3.3 Fähigkeiten
  - 3.4 Operation
  - 3.5 Soul
  - 3.6 Personalakte
  - 3.7 Marktplatz
  - 3.8 Der vollständige Flotten-Kader: Alle 57 Spezialisten nach Fachdomänen
- **4. Showroom**
  - 4.1 Explorer
  - 4.2 Berichte
  - 4.3 Medien
  - 4.4 Endprodukte
- **5. Internet**
  - 5.1 Radar
  - 5.2 Korb
  - 5.3 Quellen
  - 5.4 Optionen
- **6. Research Lab**
  - 6.1 Labor
  - 6.2 Dossiers
  - 6.3 Quellen
- **7. Zentralbibliothek**
  - 7.1 RAG Index
  - 7.2 Erfasser
  - 7.3 Obsidian
- **8. Decision Engine**
  - 8.1 Übersicht
  - 8.2 Debatte
  - 8.3 Live
- **9. Rechnungswesen**
  - 9.1 Belege
  - 9.2 Analytics
  - 9.3 Verträge
  - 9.4 Mahnwesen
- **10. Approval-Policies**
  - 10.1 Finanzen
  - 10.2 E-Mail
  - 10.3 System & IT
- **11. Corporate**
  - 11.1 Stammdaten
  - 11.2 Formulare & Vorlagen
- **12. Token Guard**
  - 12.1 Übersicht
  - 12.2 Sessions
  - 12.3 Drosselung
- **13. Telemetrie & Logs**
  - 13.1 Container
  - 13.2 Agenten
  - 13.3 Audit
- **14. System Control Center**
  - 14.1 Hermes Core
  - 14.2 Autonomie & Module
  - 14.3 Container & Dienste
  - 14.4 Provider & Gateway
  - 14.5 API-Keys & Access
  - 14.6 Methodik
  - 14.7 Plugins
  - 14.8 Kommunikation
  - 14.9 Design
  - 14.10 Systemupdate
- **15. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)**
- **16. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector**
- **Anhang I: 5 Praxis-Use-Cases**
- **Anhang II: Archon OS Komplett-Glossar (118 Module + Upgrades)**
- **Anhang III: Decision Engine & Boardroom (55 Lösungs-Frameworks)**
- **Anhang IV: Spezial-Leitfäden: IT-Sicherheit & Compliance (Volltext)**
  - IV.1 DSGVO / GDPR Compliance für Agenten-Systeme
  - IV.2 GoBD & ISO 27001 Revisionssicheres Audit-Logging
  - IV.3 Dual-LLM Prompt-Injection Guard
  - IV.4 API-Keys, Berechtigungs-Scopes & Rate-Limits
  - IV.5 Secrets-Management & Key-Rotation
  - IV.6 Lokales Privacy-Routing & Zero-Data-Leakage
  - IV.7 Reverse Proxy, SSL/TLS & SSO-Authentifizierung
  - IV.8 Break-Glass Recovery & Notfallzugriff
  - IV.9 E-Mail Approval Queue & Human-in-the-Loop Policies
  - IV.10 Approval Policies & Schwellenwert-Governance
  - IV.11 Notification Policy & Quiet Hours
  - IV.12 Config Validation & Linting
- **Anhang V: Technische Betriebs- & Integrationshandbücher (Volltext)**
  - V.1 Archon MCP Server & Tool-Treiber Entwicklung
  - V.2 Dunning Engine & Automatisches Mahnwesen
  - V.3 DocuSeal E-Signatur & Vertragsunterzeichnung
  - V.4 Telegram Receipt OCR & Belegdigitalisierung
  - V.5 Agenten-Scorecards & HR-Personalakten
  - V.6 Human Feedback Loop & Kontinuierliche Optimierung
  - V.7 Kanban Bulk Actions & Massenoperationen
  - V.8 Live Streaming mit SSE & WebSockets
  - V.9 LLM Tracing mit Langfuse
  - V.10 Prompt Registry & Canary Releases
  - V.11 Modell-Finetuning & Lokale Gewichtung
  - V.12 Prometheus & Grafana Systemüberwachung
  - V.13 Zentrales Logging mit Grafana Loki
  - V.14 Metabase BI-Dashboard & Geschäftsanalytik
  - V.15 Litestream SQLite Replikation & Disaster Recovery
  - V.16 Automatisierte Restore-Tests & Integritätsprüfung
  - V.17 Chaos Resilience & Störungs-Simulation
  - V.18 Ansible Infrastruktur-Automatisierung
  - V.19 CI/CD Pipeline & E2E-Testing
  - V.20 Systemarchitektur & Technisches Audit 2026
  - V.21 Archon OS Strategische Roadmap 2026

---
""")

    # VORWORT
    md.append("## Vorwort: Was ist Archon OS und wie arbeitet man damit?\n")
    md.append(vorwort_text)
    md.append("\n\n---\n")

    # 1. OPERATIONS
    md.append("""## 1. Operations – Operative Projektsteuerung & Funk

### 1.1 Mission Control
Mission Control ist das zentrale Cockpit und der operative Leitstand von Archon OS. Es bietet die aggregierte Übersicht über Systemlast, Flottenaktivität und offene Prioritäten.
""" + text_mc.replace("1. Mission Control (Cockpit & Leitstand)", "").strip() + """

### 1.2 Kanban
Das Kanban-Board bildet die Steuerzentrale für alle laufenden, geplanten und abgeschlossenen Aufgaben.
""" + text_ops.replace("2. Operations – Operative Projektsteuerung & Funk", "").strip() + """

> 📖 **Vertiefender Leitfaden:** Siehe die vollständige Spezifikation zu Massenoperationen im Board in [Anhang V.7: Kanban Bulk Actions](#v7-kanban-bulk-actions--massenoperationen).

- **Deal-Pipeline & Vertriebs-Integration (`t-5b159d`):** Phasensteuerung für Leads, Proposals, Verhandlungen und Abschlüsse mit automatischer Win-Rate- und Forecast-Berechnung.

### 1.3 Organisation
Visualisiert die Aufbau- und Ablaufstruktur der Organisation als interaktiven Graphen:
- **Apex & Führungs-Ebene:** Michael Keller und das Telegram Gateway an der Spitze; Robert (Executive Decision Architect) als zentraler Koordinator.
- **C-Suite & Lead-Agenten:** Fachbereichsleiter für Recht, Finanzen, Technologie, Marketing und HR.
- **Fachspezialisten:** Operative Ausführer, die über klare Eskalations- und Übergabepfade miteinander vernetzt sind.

### 1.4 n8n Automatisierung
Die integrierte n8n Workflow-Engine (Port 5678) verbindet deterministische Cron-Trigger mit kognitiven Agenten-Workflows:
- Zeitgesteuerte Datenabgleiche (z. B. morgendlicher Pressespiegel um 06:30 Uhr).
- Automatische Task-Erstellung im Kanban-Board bei externen Webhook-Events.
- Ausfallsichere Warteschlangen bei temporärer Unerreichbarkeit externer APIs.

### 1.5 Kommunikation
Der Funkverkehr-Monitor erlaubt die Echtzeit-Einsicht in die interne Agenten-zu-Agenten-Kommunikation:
- Transparente Verfolgung von Kontextübergaben zwischen Spezialisten.
- Frühzeitiges Erkennen von Klärungsbedarf oder Widersprüchen ohne manuelles Nachfragen.
""")
    md.append("\n---\n")

    # 2. POSTEINGANG & EREIGNIS-STREAM
    md.append("""## 2. Posteingang & Ereignis-Stream

### 2.1 Übersicht
Der zentrale Eingangskanal bündelt alle eingehenden Signale, Arbeitsaufträge und externen Ereignisse.
""" + text_inbox.replace("3. Eingang & Triage (HITL-Gatekeeper & Postfach)", "").strip() + """

> 📖 **Vertiefender Leitfaden:** Zur automatischen Absicherung gegen bösartige Eingaben siehe [Anhang IV.3: Dual-LLM Prompt-Injection Guard](#iv3-dual-llm-prompt-injection-guard).

### 2.2 Webhooks
Schnittstelle für externe Event-Quellen (GitHub, Stripe, Typeform, Web-Crawler):
- Validierung eingehender Payloads über HMAC-SHA256 Signaturen (`t-803095`).
- Automatische Umwandlung in strukturierte Triage-Tickets im Eingang.

### 2.3 Intern
Systeminterne Benachrichtigungen und Alarmmeldungen:
- Watchdog-Events (z. B. Deadlock-Erkennung, Speichergrenzen).
- Eskalationen aus Hintergrundprozessen an den Operator.

### 2.4 E-Mail
Zwei-Wege-E-Mail-Integration mit Auto-Enrichment:
- Direkter MAPI-Abgleich mit lokal geöffnetem Microsoft Outlook sowie IMAP/SMTP-Servern.
- Automatische Zuordnung von E-Mails zu Kontakten und Vorgängen.
- Prüfung ausgehender Entwürfe durch den Human-in-the-Loop Gatekeeper vor dem Versand.

### 2.5 Messenger
Mobile Anbindung via Telegram Gateway:
- Sprach- und Textnachrichten vom Smartphone direkt in den Posteingang.
- Rufnamen-Routing (z. B. `/anwalt`, `/steuer`, `/robert`) zur direkten Adressierung von Fachrollen.
- Zu Ruhezeiten und Push-Regeln siehe [Anhang IV.11: Notification Policy & Quiet Hours](#iv11-notification-policy--quiet-hours).

### 2.6 Freigaben
Dedizierte Ansicht für genehmigungspflichtige Aktionen (Human-in-the-Loop):
- Freigabekarten mit Diff-Ansicht für Code, E-Mail-Texte oder Transaktionen.
- Ein-Klick-Freigabe, Ablehnung mit Notiz oder In-Place Textkorrektur.

> 📖 **Vertiefender Leitfaden:** Siehe den ungekürzten Leitfaden in [Anhang IV.9: E-Mail Approval Queue](#iv9-e-mail-approval-queue--human-in-the-loop-policies).
""")
    md.append("\n---\n")

    # 3. AGENTEN-KADER
    md.append("""## 3. Agenten-Kader

Der Agenten-Kader ist die Personalabteilung und das operative Einstellungszentrum deines Systems. Hier verwaltest du alle 57 Spezialisten-Profile (inklusive Root-Orchestrator), weist Sprachmodelle dynamisch zu, bearbeitest Verhaltensrichtlinien in der SOUL.md und konfigurierst persönliche Rufnamen für den direkten Messenger-Zugriff via Telegram.

### 3.1 Übersicht
- Vollständiger Katalog aller Fachagenten mit Suchleiste, Domänen-Filter und Statusanzeige (Aktiv, Favoriten, Alle).
- Detailansicht mit Stammdaten, Handle, Rollenbezeichnung und Provider-/Modell-Auswahl.
- Hot-Swap Fähigkeit: Modellwechsel greifen im laufenden Betrieb ohne Neustart.

### 3.2 Chat
- 1:1 Direkt-Dialog mit dem ausgewählten Agenten zum Testen und Kalibrieren.
- Markdown-Rendering, Code-Highlighting und manuelle Schieberegler für Temperature und Top-P.

### 3.3 Fähigkeiten
- Tool- und Skill-Matrix: Zuweisung konkreter Werkzeuge (Web-Search, PDF-Reader, Code-Sandbox, Terminal, Dateisystem).
- Rechtevergabe nach dem Prinzip der geringsten Berechtigung (Least Privilege).

### 3.4 Operation
- Übersicht aller aktuell zugewiesenen und historisch erledigten Aufgaben des Agenten.
- Transparente Leistungshistorie, Token-Verbrauch und Verknüpfung zu erzeugten Showroom-Artefakten.
- Zur kontinuierlichen Leistungsbewertung siehe [Anhang V.6: Human Feedback Loop](#v6-human-feedback-loop--kontinuierliche-optimierung).

### 3.5 Soul
- Inline-Editor für die System-Prompts (`SOUL.md`) des Agenten.
- Definition von Tonalität, Verhaltensregeln, ethischen Leitplanken und expliziten Negativ-Regeln (Was darf der Agent keinesfalls tun?).

### 3.6 Personalakte
- Formelles HR-Dossier des Agenten mit fachlichem Werdegang, Zertifizierungen und Kompetenzprofil.
- Hinterlegung firmenspezifischer Standard Operating Procedures (SOPs), an die sich der Agent bei allen Ausführungen halten muss.

> 📖 **Vertiefender Leitfaden:** Siehe den vollständigen Leitfaden zur Personalaktenführung in [Anhang V.5: Agenten-Scorecards & Personalakten](#v5-agenten-scorecards--hr-personalakten).

### 3.7 Marktplatz
- Import und Export vorkonfigurierter Rollen-Pakete als portable JSON/Markdown-Dateien.
- Schnelle Erweiterung des Kaders bei Erschließung neuer Geschäftsbereiche.

### 3.8 Der vollständige Flotten-Kader: Alle 57 Spezialisten nach Fachdomänen

Das Gesamtsystem umfasst 57 spezialisierte Rollenprofile, die nach den 7 strategischen Kernbereichen gegliedert und nach dem EU AI Act klassifiziert sind:
""")

    for cat_name in sorted(by_cat.keys()):
        agent_list = by_cat[cat_name]
        md.append(f"\n#### Domäne: {cat_name} ({len(agent_list)} Spezialisten)\n")
        md.append("| Agenten-Name | Handle / ID | Modell / Provider | EU AI Act Klasse | Kernfunktion & Zweck |")
        md.append("|---|---|---|---|---|")
        for a in agent_list:
            aid = a.get("agent_id")
            p = prof_map.get(aid, {})
            name = a.get("agent_name", aid)
            model = a.get("underlying_model", "omniroute / auto/best-free")
            risk = a.get("risk_tier", "MINIMAL_RISK")
            purpose = (a.get("primary_purpose") or p.get("description") or "").replace("\n", " ").strip()
            if len(purpose) > 130:
                purpose = purpose[:127] + "..."
            md.append(f"| **{name}** | `{aid}` | {model} | `{risk}` | {purpose} |")

    md.append("\n---\n")

    # 4. SHOWROOM
    md.append("""## 4. Showroom

Der Showroom ist die Artefakt-Galerie und der Projekt-Explorer für alle von Agenten autonom erzeugten Arbeitsergebnisse.
""" + text_showroom.replace("5. Showroom (Projekt-Explorer & Artefakt-Galerie)", "").strip() + """

### 4.1 Explorer
- Baum- und Kachelansicht aller erzeugten Dateien geordnet nach Projekten, Datum und Typ.
- Metadaten-Inspektor mit ausführendem Agenten, Entstehungszeitpunkt und zugehörigem Kanban-Task.

### 4.2 Berichte
- Aufbereitete Recherche-Reports, Business-Cases, Entscheidungsvorlagen und Analysedossiers.
- Integrierter Markdown- und HTML-Viewer für formatierte Textausgaben.

### 4.3 Medien
- Generierte Visualisierungen, Diagramme (Mermaid), UI-Mockups und Mediendateien.
- Schnelle Vorschau ohne externe Betrachterprogramme.

### 4.4 Endprodukte
- Zur Auslieferung freigegebene Dokumente, Code-Pakete oder exportfähige PDF-Dateien.
- Isolierte Sandbox-Ausführung für dynamische Web-Apps und Code-Artefakte.
""")
    md.append("\n---\n")

    # 5. INTERNET
    md.append("""## 5. Internet

Der Internet-Watchdog ist das autonome Frühwarn- und Aufklärungssystem von Archon OS.

### 5.1 Radar
- Live-Stream gescannter Webseiten, Branchen-Feeds, Amtsblätter und sozialer Kanäle.
- Automatische Erkennung relevanter Signale anhand vordefinierter Suchmuster und Vektor-Ähnlichkeiten.

### 5.2 Korb
- Sammelstelle für interessante Fundstücke, Artikel und Dokumente vor der formellen Übernahme in die Bibliothek.
- Schnelle Triage: Verwerfen, zur Tiefenrecherche vormerken oder sofort in den Obsidian Vault überführen.

### 5.3 Quellen
- Verwaltung der kontinuierlich überwachten URLs, RSS-Feeds, APIs und News-Portale.
- Konfigurierbare Scan-Intervalle und Prioritätsstufen.

### 5.4 Optionen
- Crawler-Einstellungen: Headless-Browser Rendering (Playwright), Proxy-Konfiguration und Respektierung von Rate-Limits.
- Schwellenwerte für die automatische Alarmierung bei kritischen Markt- oder Sicherheitsereignissen.
""")
    md.append("\n---\n")

    # 6. RESEARCH LAB
    md.append("""## 6. Research Lab

Das Research Lab dient der tiefgehenden, evidenzbasierten Wissensbeschaffung und komplexen Marktanalysen.
""" + text_research.replace("10. Research Lab (Deep Search & Wissensbeschaffung)", "").strip() + """

### 6.1 Labor
- Konfiguration von Forschungsfragen, Suchtiefe (Quick Scan vs. Deep Research) und Quellenrestriktionen.
- Verfolgung des Live-Suchlaufs mit Zwischenergebnissen und extrahierten Schlüsselzitaten.

### 6.2 Dossiers
- Automatisch synthetisierte Forschungsberichte mit Quellenverzeichnis, Gegenüberstellung von Pro-/Contra-Argumenten und Kernaussagen.
- Exportierbar als strukturierte Markdown-Dokumente für die Zentralbibliothek.

### 6.3 Quellen
- Transparente Dokumentation aller herangezogenen Primär- und Sekundärquellen inklusive Vertrauenswürdigkeits-Score.
- Erkennung von Widersprüchen zwischen unterschiedlichen Quellenberichten.
""")
    md.append("\n---\n")

    # 7. ZENTRALBIBLIOTHEK
    md.append("""## 7. Zentralbibliothek

Die Zentralbibliothek ist das Wissensgedächtnis von Archon OS. Sie kombiniert semantische Vektorsuche, automatische Dokumenten-Ingestion und den lokalen Obsidian Vault.
""" + text_library.replace("6. Zentralbibliothek & Wissensmanagement", "").strip() + """

### 7.1 RAG Index
- AnythingLLM-Anbindung (Port 3001) für semantische Ähnlichkeitssuche über den gesamten Unternehmensdatenbestand.
- Vektor-Indizierung von Richtlinien, Verträgen, Fachliteratur und historischen Projekten.

### 7.2 Erfasser
- Drag & Drop Dokumenten-Upload mit integrierter Docling / Unstructured Extraktionspipeline (`t-539b65`).
- Automatische Umwandlung von Tabellen, Scans und PDFs in sauberes GitHub-Flavored Markdown.

### 7.3 Obsidian
- Direkter Zugriff auf den lokalen Markdown-Vault (`02_Wissensbibliothek`).
- Verknüpfung von Notizen über Wikilinks (`[[Begriff]]`) zu einem navigierbaren Wissensnetzwerk.
""")
    md.append("\n---\n")

    # 8. DECISION ENGINE
    md.append("""## 8. Decision Engine

Die Decision Engine (AI Mastermind) ermöglicht strukturierte Vorstandssitzungen, Risikoabwägungen und Meta-Reasoning über C-Level Agententeams.
""" + text_mastermind.replace("7. AI Mastermind & Boardroom (3-Tab-Architektur & 34 Frameworks)", "").strip() + """

### 8.1 Übersicht
- Archiv aller bisher durchgeführten Debatten, Beschlüsse und Strategie-Memos.
- Suche nach vergangenen Entscheidungsbegründungen zur Wahrung unternehmerischer Kontinuität.

### 8.2 Debatte
- Auswahl aus 55 vordefinierten Denkframeworks (z. B. Pre-Mortem Analysis, 6 Thinking Hats, Red Team vs. Blue Team, Cynefin).
- Festlegung von Fragestellung, Anhängen, Chairman und teilnehmenden C-Suite Spezialisten.

### 8.3 Live
- Modulares Streaming der Debattenrunden mit Thesen, Gegenargumenten und Schiedsgerichtsbeschluss.
- Automatische Erstellung eines finalen Board-Memos mit Handlungsentscheidung und Aufgabenübernahme in Operations.

> 📖 **Vertiefender Leitfaden:** Zur Streaming-Architektur über SSE siehe [Anhang V.8: Live Streaming mit SSE & WebSockets](#v8-live-streaming-mit-sse--websockets).
""")
    md.append("\n---\n")

    # 9. RECHNUNGSWESEN
    md.append("""## 9. Rechnungswesen

Das Modul Rechnungswesen bildet das kaufmännische Fundament von Archon OS.

### 9.1 Belege
- Revisionssichere Erfassung und Digitalisierung von Eingangs- und Ausgangsbelegen nach GoBD-Grundsätzen.
- Automatische Auslesung von Rechnungsnummer, Ausstellungsdatum, Leistungszeitraum, Netto- und Steuerbeträgen.

> 📖 **Vertiefender Leitfaden:** Siehe die mobile Belegdigitalisierung in [Anhang V.4: Telegram Receipt OCR](#v4-telegram-receipt-ocr--belegdigitalisierung) und die Audit-Spezifikation in [Anhang IV.2: GoBD & ISO 27001 Audit-Logging](#iv2-gobd--iso-27001-revisionssicheres-audit-logging).

### 9.2 Analytics
- Kaufmännische Kennzahlen: Umsatzentwicklung, operative Ausgaben (OpEx), API-Kosten und Deckungsbeiträge.
- Budgetüberwachung je Kostenstelle und Projekt.
- Zur tieferen Metabase-BI-Anbindung siehe [Anhang V.14: Metabase BI-Dashboard](#v14-metabase-bi-dashboard--geschäftsanalytik).

### 9.3 Verträge
- Automatisches Vertrags- und Fristenmanagement (`t-0a2171`):
  - Heuristisches Parsen von Vertragstexten nach Kündigungsfristen, Verlängerungsklauseln und Zahlungszielen.
  - Automatisches Telegram-Alerting bei Fristen <= 14 Tagen.
  - Kanban-Aufgabenerstellung zur rechtzeitigen Prüfung oder Kündigung.

> 📖 **Vertiefender Leitfaden:** Zur rechtsverbindlichen digitalen Unterzeichnung siehe [Anhang V.3: DocuSeal E-Signatur](#v3-docuseal-e-signatur--vertragsunterzeichnung).

### 9.4 Mahnwesen
- Überwachung offener Forderungen mit Fälligkeitsstufen.
- Automatische Generierung rechtssicherer Zahlungserinnerungen und Mahnungen nach deutschem BGB.

> 📖 **Vertiefender Leitfaden:** Siehe die vollständige Spezifikation der Mahnstufen in [Anhang V.2: Dunning Engine & Mahnwesen](#v2-dunning-engine--automatisches-mahnwesen).
""")
    md.append("\n---\n")

    # 10. APPROVAL-POLICIES
    md.append("""## 10. Approval-Policies

Approval-Policies definieren die Governance-Leitplanken und bestimmen, ab welchen Risikoschwellen Agenten eigenständig handeln dürfen oder eine menschliche Freigabe erforderlich ist.

### 10.1 Finanzen
- Wertgrenzen für autonome Einkäufe, Tool-Subscriptions und Budgetallokationen.
- Dual-Control (Vier-Augen-Prinzip) für Zahlungsfreigaben über definierten Schwellenbeträgen.

### 10.2 E-Mail
- Genehmigungspflicht für externe E-Mail-Kommunikation mit Neukontakten, Behörden oder Großkunden.
- Diff-Prüfung vor dem Absenden zur Verhinderung unbeabsichtigter Zusageerklärungen.

### 10.3 System & IT
- Schutz vor zerstörerischen Aktionen: Server-Neustarts, Container-Updates, Datenbankschema-Migrationen und Produktiv-Deployments.
- Integrierte automatische Datenklassifizierung nach ISO 27001 / BSI (`t-53315b`) mit Übertragungsstopp bei streng vertraulichen Daten.

> 📖 **Vertiefender Leitfaden:** Siehe den ungekürzten Leitfaden in [Anhang IV.10: Approval Policies](#iv10-approval-policies--schwellenwert-governance) und [Anhang IV.1: DSGVO Compliance](#iv1-dsgvo--gdpr-compliance-für-agenten-systeme).
""")
    md.append("\n---\n")

    # 11. CORPORATE
    md.append("""## 11. Corporate

Das Corporate Hub zentralisiert alle rechtlichen, steuerlichen und visuellen Stammdaten des Unternehmens und stellt eine mandantenfähige Vorlagen-Engine bereit.

### 11.1 Stammdaten
- **Multi-Company Management:** Verwalte mehrere Unternehmen oder Tochtergesellschaften über das Dropdown-Menü mit jeweils separaten Stammdaten.
- **Rechtliche Daten:** Offizieller Firmenname, Rechtsform, Anschrift, Kontaktdaten und vertretungsberechtigte Geschäftsführer.
- **Register & Steuern:** Registergericht, Handelsregisternummer (HRB), Steuernummer, USt-IdNr. und § 19 UStG-Regelung.
- **Bankverbindung:** Geschäftskonto (IBAN, BIC, Bankname).
- **Corporate Design:** Primär- und Sekundärfarben mit Color-Picker, Logo-Pfad und Schriftartenauswahl.

### 11.2 Formulare & Vorlagen
- **Interaktives Vorlagen-Studio mit Live-Vorschau:**
  - **DIN 5008 Geschäftsbrief:** Offizieller Briefkopf mit Faltmarken, Anschriftfeld, Bezugszeichenzeile und HGB-Fußzeile.
  - **Ausgangsrechnung (§ 14 UStG):** Automatische Berechnung von Positionen, Nettobetrag, 19% Umsatzsteuer und Bruttoendbetrag sowie Zahlungsziel.
  - **Geheimhaltungsvereinbarung (NDA):** Rechtssicherer Vertraulichkeitsvertrag zur Wahrung von Betriebs- und Geschäftsgeheimnissen.
- **Druck & PDF-Export:** Erzeugung druckfertiger A4-Dokumente per Klick via `window.print()`.
""")
    md.append("\n---\n")

    # 12. TOKEN GUARD
    md.append("""## 12. Token Guard

Der Token Guard (Guardian) schützt vor unkontrollierten API-Kosten und überwacht Modell-Quotas in Echtzeit.
""" + text_guardian.replace("9. Token Guard (Guardian & Budgetwächter)", "").strip() + """

### 12.1 Übersicht
- Live-Verbrauch nach Agenten, Modellen und Providern im Verhältnis zum Tages- und Monatsbudget.
- Farbcodierte Budgetampel für rasche Statusbeurteilung.

### 12.2 Sessions
- Detailanalyse einzelner Aufgaben und Sitzungen mit Token-Aufschlüsselung (Prompt- vs. Completion-Tokens).
- Identifikation ineffizienter Schleifen oder überlanger Kontextfenster.

### 12.3 Drosselung
- Automatische Soft-Limits (Warnung bei 80% Budget) und Hard-Limits (Stop bei 100%).
- Intelligente Downgrade-Kaskade auf kostenlose Modelle (`auto/best-free`) bei Budgetengpässen.

> 📖 **Vertiefender Leitfaden:** Siehe Rate-Limits und Token-Scopes in [Anhang IV.4: API-Keys & Scopes](#iv4-api-keys-berechtigungs-scopes--rate-limits) und [Anhang IV.6: Lokales Privacy Routing](#iv6-lokales-privacy-routing--zero-data-leakage).
""")
    md.append("\n---\n")

    # 13. TELEMETRIE & LOGS
    md.append("""## 13. Telemetrie & Logs

Der Telemetrie- und Audit-Stream protokolliert alle Systemvorgänge lückenlos zur Fehlersuche und Compliance-Nachweisführung.
""" + text_telemetrie.replace("11. Telemetrie & Logs (Live-Audit Stream)", "").strip() + """

### 13.1 Container
- Health-Monitoring der 13 Docker-Container mit Latenzen (Ping ms), RAM- und CPU-Auslastung.
- Live-Log-Stream einzelner Container zur schnellen Diagnose von Verbindungsproblemen.

> 📖 **Vertiefender Leitfaden:** Siehe [Anhang V.12: Prometheus & Grafana](#v12-prometheus--grafana-systemüberwachung) und [Anhang V.13: Central Logging mit Loki](#v13-zentrales-logging-mit-grafana-loki).

### 13.2 Agenten
- Detailliertes Trace-Logging aller Agentenaktivitäten (Prompt-Eingaben, Denkprozesse, Tool-Aufrufe und Rückmeldungen).
- Filterbar nach Agent, Log-Level (DEBUG bis CRITICAL) und Zeitfenster.
- Zur tiefen Tracing-Anbindung siehe [Anhang V.9: LLM Tracing mit Langfuse](#v9-llm-tracing-mit-langfuse).

### 13.3 Audit
- Krypto-verkettetes, manipulationssicheres Audit-Log für alle ausgeführten Systembefehle.
- Unterstützung für geordneten Server-Shutdown via `GracefulShutdownCoordinator` (`t-12113b`) mit Task-Draining und sicherem WAL-Flush.
""")
    md.append("\n---\n")

    # 14. SYSTEM CONTROL CENTER
    md.append("""## 14. System Control Center

Das System Control Center (Settings) ist die zentrale Schaltstelle zur Konfiguration aller Basiskomponenten, Schnittstellen und Sicherheitsrichtlinien.
""" + text_settings.replace("15. System Control Center & Einstellungen", "").strip() + """

### 14.1 Hermes Core
- Konfiguration des Hintergrund-Daemons auf Port 8420.
- Steuerung von Task-Queues, Watchdog-Intervallen (30s) und Event-Loops.
- Zum Notfallbetrieb siehe [Anhang IV.8: Break-Glass Recovery](#iv8-break-glass-recovery--notfallzugriff) und [Anhang V.17: Chaos Resilience](#v17-chaos-resilience--störungs-simulation).

### 14.2 Autonomie & Module
- Aktivierung und Deaktivierung autonomer Hintergrund-Daemons (z. B. nächtliche Speicherkonsolidierung, Standup-Reports).
- Steuerung flüchtiger Sandbox-Container für Code-Ausführungen (`t-a42e5d`).

### 14.3 Container & Dienste
- Live-Statusmatrix aller 13 Docker-Container inklusive Neustart-Schaltflächen.
- Überwachung der internen Docker-Socket-Bridge.
- Zu Replikation und Reverse-Proxy siehe [Anhang V.15: Litestream](#v15-litestream-sqlite-replikation--disaster-recovery) und [Anhang IV.7: Reverse Proxy & SSO](#iv7-reverse-proxy-ssltls--sso-authentifizierung).

### 14.4 Provider & Gateway
- Verwaltung des Multi-Provider LLM-Gateways (OmniRoute auf Port 20128).
- Konfiguration von Fallback-Kaskaden (Primary -> Secondary -> Local FreeLLM).
- Zum Fine-Tuning eigener Modelle siehe [Anhang V.11: Modell-Finetuning](#v11-modell-finetuning--lokale-gewichtung).

### 14.5 API-Keys & Access
- Verschlüsselter Schlüssel-Tresor für alle externen KI- und Cloud-Anbieter (OpenRouter, Google, OpenAI, Groq).
- Rechtebeschränkungen und Gültigkeitsprüfungen.
- Siehe [Anhang IV.5: Secrets Management & Rotation](#iv5-secrets-management--key-rotation).

### 14.6 Methodik
- Aktivierung und Anpassung der 55 Lösungs-Frameworks für die Decision Engine.
- Definition standardisierter Argumentationsschemata.

### 14.7 Plugins
- MCP-Treiberverwaltung (Model Context Protocol) zur Anbindung externer Datenquellen und Werkzeuge.
- Sandboxed Ausführung externer Erweiterungen.
- Siehe [Anhang V.1: Archon MCP Server Guide](#v1-archon-mcp-server--tool-treiber-entwicklung).

### 14.8 Kommunikation
- Konfiguration des mobilen Telegram-Bots, Webhook-Endpunkten und Mail-Servern.
- Sprach-Pipeline für mobile Voice-Nachrichten.

### 14.9 Design
- Globale Theme-Steuerung (Dark / Light Mode, Akzentfarben, Typografie und Rahmengrößen).

### 14.10 Systemupdate
- Revisionssicheres Update-System mit GitHub-Sync, Integritätsprüfungen und automatischem Pre-Commit Testlauf.
- Siehe [Anhang V.18: Ansible Infrastruktur](#v18-ansible-infrastruktur-automatisierung), [Anhang V.19: CI/CD Pipeline](#v19-cicd-pipeline--e2e-testing) und [Anhang V.16: Restore Tests](#v16-automatisierte-restore-tests--integritätsprüfung).
""")
    md.append("\n---\n")

    # 15. PROMPT STUDIO
    md.append("""## 15. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)
""" + text_prompt.replace("12. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)", "").strip() + """

> 📖 **Vertiefender Leitfaden:** Siehe Prompt-Versionierung und Canary-Tests in [Anhang V.10: Prompt Registry & Canary Releases](#v10-prompt-registry--canary-releases).
""")
    md.append("\n---\n")

    # 16. CSS LIVE STUDIO
    md.append("""## 16. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector
""" + text_css.replace("13. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector", "").strip())
    md.append("\n\n---\n")

    # ANHÄNGE I, II, III
    md.append("# ANHÄNGE\n")
    md.append("## " + text_anhang1 + "\n\n---\n")
    md.append("## " + text_anhang2 + "\n\n---\n")
    md.append("## " + text_anhang3 + "\n\n---\n")

    # ANHANG IV: UNABRIDGED SECURITY & COMPLIANCE GUIDES
    md.append("""## ANHANG IV: SPEZIAL-LEITFÄDEN: IT-SICHERHEIT & COMPLIANCE

In diesem Anhang sind alle 12 spezialisierten Sicherheits-, Datenschutz- und Compliance-Leitfäden im vollen Wortlaut abgedruckt.

---

### IV.1 DSGVO / GDPR Compliance für Agenten-Systeme
""" + read_guide("docs/system/GDPR_COMPLIANCE_GUIDE.md") + """

---

### IV.2 GoBD & ISO 27001 Revisionssicheres Audit-Logging
""" + read_guide("docs/security/GOBD_ISO27001_AUDIT_LOG_GUIDE.md") + """

---

### IV.3 Dual-LLM Prompt-Injection Guard
""" + read_guide("docs/security/DUAL_LLM_PROMPT_INJECTION_GUARD_GUIDE.md") + """

---

### IV.4 API-Keys, Berechtigungs-Scopes & Rate-Limits
""" + read_guide("docs/security/API_KEYS_SCOPES_RATELIMITS_GUIDE.md") + """

---

### IV.5 Secrets-Management & Key-Rotation
""" + read_guide("docs/security/SECRETS_MANAGEMENT_UND_ROTATION.md") + """

---

### IV.6 Lokales Privacy-Routing & Zero-Data-Leakage
""" + read_guide("docs/security/LOCAL_LLM_PRIVACY_ROUTING_GUIDE.md") + """

---

### IV.7 Reverse Proxy, SSL/TLS & SSO-Authentifizierung
""" + read_guide("docs/security/REVERSE_PROXY_SSO_GUIDE.md") + """

---

### IV.8 Break-Glass Recovery & Notfallzugriff
""" + read_guide("docs/security/BREAK_GLASS_RECOVERY_GUIDE.md") + """

---

### IV.9 E-Mail Approval Queue & Human-in-the-Loop Policies
""" + read_guide("docs/system/EMAIL_APPROVAL_QUEUE_GUIDE.md") + """

---

### IV.10 Approval Policies & Schwellenwert-Governance
""" + read_guide("docs/system/APPROVAL_POLICIES_GUIDE.md") + """

---

### IV.11 Notification Policy & Quiet Hours
""" + read_guide("docs/system/NOTIFICATION_POLICY_QUIET_HOURS_GUIDE.md") + """

---

### IV.12 Config Validation & Linting
""" + read_guide("docs/system/CONFIG_VALIDATION_GUIDE.md") + """

---
""")

    # ANHANG V: UNABRIDGED SYSTEM & OPERATION GUIDES
    md.append("""## ANHANG V: TECHNISCHE BETRIEBS- & INTEGRATIONS-HANDBÜCHER

In diesem Anhang sind alle 21 technischen Betriebs-, Infrastruktur- und Integrationshandbücher im vollen Wortlaut abgedruckt.

---

### V.1 Archon MCP Server & Tool-Treiber Entwicklung
""" + read_guide("docs/system/ARCHON_MCP_SERVER_GUIDE.md") + """

---

### V.2 Dunning Engine & Automatisches Mahnwesen
""" + read_guide("docs/system/DUNNING_ENGINE_GUIDE.md") + """

---

### V.3 DocuSeal E-Signatur & Vertragsunterzeichnung
""" + read_guide("docs/system/ESIGN_DOCUSEAL_GUIDE.md") + """

---

### V.4 Telegram Receipt OCR & Belegdigitalisierung
""" + read_guide("docs/system/TELEGRAM_RECEIPT_OCR_GUIDE.md") + """

---

### V.5 Agenten-Scorecards & HR-Personalakten
""" + read_guide("docs/system/AGENT_SCORECARDS_PERSONALAKTE_GUIDE.md") + """

---

### V.6 Human Feedback Loop & Kontinuierliche Optimierung
""" + read_guide("docs/system/HUMAN_FEEDBACK_LOOP_GUIDE.md") + """

---

### V.7 Kanban Bulk Actions & Massenoperationen
""" + read_guide("docs/system/KANBAN_BULK_ACTIONS_GUIDE.md") + """

---

### V.8 Live Streaming mit SSE & WebSockets
""" + read_guide("docs/system/LIVE_STREAMING_SSE_WEBSOCKET_GUIDE.md") + """

---

### V.9 LLM Tracing mit Langfuse
""" + read_guide("docs/system/LLM_TRACING_LANGFUSE_GUIDE.md") + """

---

### V.10 Prompt Registry & Canary Releases
""" + read_guide("docs/system/PROMPT_REGISTRY_CANARY_GUIDE.md") + """

---

### V.11 Modell-Finetuning & Lokale Gewichtung
""" + read_guide("docs/system/MODEL_FINETUNING_GUIDE.md") + """

---

### V.12 Prometheus & Grafana Systemüberwachung
""" + read_guide("docs/system/PROMETHEUS_GRAFANA_MONITORING_GUIDE.md") + """

---

### V.13 Zentrales Logging mit Grafana Loki
""" + read_guide("docs/system/CENTRAL_LOGGING_LOKI_GUIDE.md") + """

---

### V.14 Metabase BI-Dashboard & Geschäftsanalytik
""" + read_guide("docs/system/BI_DASHBOARD_METABASE_GUIDE.md") + """

---

### V.15 Litestream SQLite Replikation & Disaster Recovery
""" + read_guide("docs/system/LITESTREAM_REPLICATION_GUIDE.md") + """

---

### V.16 Automatisierte Restore-Tests & Integritätsprüfung
""" + read_guide("docs/system/AUTOMATED_RESTORE_TEST_GUIDE.md") + """

---

### V.17 Chaos Resilience & Störungs-Simulation
""" + read_guide("docs/system/CHAOS_RESILIENCE_GUIDE.md") + """

---

### V.18 Ansible Infrastruktur-Automatisierung
""" + read_guide("docs/system/ANSIBLE_INFRASTRUCTURE_GUIDE.md") + """

---

### V.19 CI/CD Pipeline & E2E-Testing
""" + read_guide("docs/system/CI_PIPELINE_E2E_TESTING_GUIDE.md") + """

---

### V.20 Systemarchitektur & Technisches Audit 2026
""" + read_guide("docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md") + """

---

### V.21 Archon OS Strategische Roadmap 2026
""" + read_guide("docs/system/ROADMAP_2026.md") + """
""")

    final_content = "\n".join(md)
    print(f"Writing complete hybrid master handbuch to {TARGET_MD} (Length: {len(final_content)} chars)...")
    with open(TARGET_MD, "w", encoding="utf-8") as f:
        f.write(final_content)
    print("SUCCESS: Hybrid Master Handbuch successfully built!")


if __name__ == "__main__":
    build_handbuch_hybrid()
