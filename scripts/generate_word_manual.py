# -*- coding: utf-8 -*-
import os
import time
import subprocess
import json
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

OUTPUT_DIR = "/app/docs/system" if os.path.exists("/app/docs/system") else r"c:\.Antigravity-projekte\AgenticOS-2026\docs\system"
IMG_DIR = os.path.join(OUTPUT_DIR, "screenshots")
DOCX_PATH = os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026.docx")

os.makedirs(IMG_DIR, exist_ok=True)

# -------------------------------------------------------------
# DETAILLIERTE DATENSTRUKTUR FÜR ALLE 16 SYSTEM-ANSICHTEN & STUDIOS
# -------------------------------------------------------------
VIEWS = [
    {
        "id": "mission_control",
        "title": "1. Mission Control (Cockpit & Leitstand)",
        "subtitle": "Echtzeit-Telemetrie, Flottenlast, Kostenkontrolle & HITL-Freigabemonitor",
        "concept": (
            "Mission Control fungiert als oberster Beobachtungs- und Überwachungsleitstand des gesamten Agentic OS. "
            "Wichtig: Diese Ansicht ist primär für das Monitoring und den schnellen Überblick ausgelegt – neue Aufgaben "
            "werden im Operations-Kanban angelegt oder via Telegram beauftragt. Das Cockpit führt alle vitalen Systemparameter "
            "zusammen und spiegelt das operative Arbeitsaufkommen in einer kompakten Projektionsansicht."
        ),
        "elements": [
            ("5 vitale KPI-Kacheln (Kopfzeile)", 
             "• Flottenlast: Zeigt die Anzahl gleichzeitig arbeitender Agenten im Verhältnis zum Gesamt-Kader (z. B. 0 / 54 aktiv).\n"
             "• Durchsatz (TPM): Überwacht die erzeugten Tokens pro Minute gegenüber dem definierten Schwellenwert (z. B. 2M TPM Limit).\n"
             "• Kostenwächter: Kumulierte Tageskosten in USD mit farblicher Warnanzeige bei Annäherung an das Tageslimit ($5.00).\n"
             "• Stabilität: Erfolgsquote aller Tool- und Modellausführungen (100% nominal bedeutet fehlerfreie Ausführung).\n"
             "• Approval Gate: Zähler für blockierte Aktionen, die auf deine manuelle Human-in-the-Loop-Freigabe warten."),
            ("Workflow & Approval Board", 
             "Spiegelt die 5 Spalten des Operations-Boards (To-Do, In Bearbeitung, Review & QA, Blockiert, Abgeschlossen) wider. "
             "Hier siehst du sofort, ob Aufgaben in der Review-Spalte auf Freigabe warten oder ob ein Prozess blockiert ist."),
            ("Aktiver Agenten-Kader & Worker-Status", 
             "Listet die aktuell verfügbaren Schlüsselrollen (z. B. Default Orchestrator, Michael Keller) inklusive Status "
             "(Bereitschaft / Standby) und hinterlegtem Modell-Alias."),
            ("Live-Audit & Telemetrie-Stream", 
             "Rechter Feed mit sekundengenauen Systemereignissen: Dokumentiert Synthese-Zyklen, Promptfoo-Governance-Prüfungen, "
             "Freigabestopps und Prozessübergaben lückenlos im Klartext."),
            ("Process Heartbeat (Footer)", 
             "Zeigt den Daemon-Zustand (Tickless Kernel Sleep aktiv), Tool-Belegungsquoten (z. B. Web-Search, Code-Gen) "
             "sowie den aktuellen Kontextpuffer des Standard-Modells an.")
        ],
        "workflow": [
            "1. Kontrolliere zu Arbeitsbeginn die KPI-Kacheln auf Auffälligkeiten (Kostenstand und Approval Gate).",
            "2. Steht der Zähler bei 'Approval Gate' auf > 0, wechsle in die Review-Spalte oder den Eingang, um die anstehende Schreibaktion zu prüfen.",
            "3. Beobachte im Live-Audit, welche Agenten autonom arbeiten und ob alle Worker nominal reagieren."
        ],
        "best_practices": (
            "Nutze Mission Control für den schnellen Überblick während des Betriebs. Für Eingriffe in Aufgaben, Priorisierungen "
            "oder Detailanalysen wechsle immer direkt in das Operations-Kanban."
        ),
        "starter_prompt": "Gib mir eine Zusammenfassung des aktuellen System-Status laut Mission Control: Wie viele Agenten sind aktiv und gibt es blockierte Freigaben?"
    },
    {
        "id": "operations",
        "title": "2. Operations – Operative Projektsteuerung & Funk",
        "subtitle": "Kanban Board, Organisation/Ablaufdiagramm & Interne Agenten-Kommunikation",
        "concept": (
            "Operations ist das operative Zentrum von Archon OS. Hier laufen die drei Säulen der täglichen Wertschöpfung "
            "zusammen: Das Kanban Board zur Verwaltung des Aufgaben-Lebenszyklus, das Organigramm zur Definition von "
            "Berichtslinien und Eskalationspfaden, sowie der interne Funkverkehr (Communication) für die inter-agentische Abstimmung."
        ),
        "elements": [
            ("Drei integrierte Arbeitsbereiche (Kopfzeile)", 
             "Über die horizontalen Kacheln wechselst du nahtlos zwischen Kanban, Organisation und Kommunikation."),
            ("Button '+ Neue Aufgabe'", 
             "Öffnet das Aufgaben-Erstellungsmodal zur direkten Zuweisung an Rollen inklusive Priorität und Instruktionen."),
            ("Sync-Button (Aktualisieren)", 
             "Synchronisiert den aktuellen Board- und Funkstatus mit der zentralen kanban.db.")
        ],
        "subsections": [
            {
                "subtitle": "2.1 Kanban Board & Task-Engine",
                "img_id": "operations",
                "concept": (
                    "Jede geschäftliche Aufgabe wird im Board als strukturierte Karte geführt, einem Fachagenten zugewiesen "
                    "und durchläuft die Spalten To-Do, In Bearbeitung, Review & QA, Blockiert und Abgeschlossen. "
                    "WIP-Limits (Work-in-Progress) verhindern Token-Spitzen und Überlastung."
                ),
                "elements": [
                    ("Die 5 Lebenszyklus-Spalten", "To-Do (Warteschlange), In Bearbeitung (aktive Ausführung), Review & QA (Prüfung), Blockiert (Eskalation), Abgeschlossen (Erledigt)."),
                    ("WIP-Limit Konfiguration", "Begrenze in der Toolbar die maximale Kartenzahl pro Spalte (z. B. max. 3 Tasks gleichzeitig in Bearbeitung)."),
                    ("Toolbar mit Filtern & Archiv", "Volltextsuche, Filter nach verantwortlichem Agenten, Filter nach Priorität (P0 bis P3) sowie Klick-Archivierung erledigter Aufgaben.")
                ],
                "workflow": [
                    "1. Erstelle eine neue Karte für eine Rolle oder empfange eine via Telegram delegierte Aufgabe.",
                    "2. Beobachte, wie der Agent die Karte autonom bearbeitet und bei Fertigstellung nach 'Review & QA' schiebt.",
                    "3. Öffne die Karte, prüfe das Ergebnis (oder nutze 'In Obsidian öffnen') und ziehe sie auf 'Abgeschlossen'."
                ],
                "tip": "Sollte ein Task auf 'Blockiert' springen, prüfe im Task-Detail die Ursache – oft fehlt ein Parameter oder ein API-Key."
            },
            {
                "subtitle": "2.2 Organisation & Ablaufdiagramm (Organigramm)",
                "img_id": "org",
                "concept": (
                    "Visualisiert die Aufbau- und Ablaufstruktur deines Unternehmens als interaktiven 2D-Graphen. "
                    "Die Verbindungslinien definieren echte Weisungs- und Berichtswege für autonome Eskalationen: "
                    "von der Apex-Ebene über Robert (CEO) bis zu den Fach-Leads und Spezialisten."
                ),
                "elements": [
                    ("Apex & CEO-Ebene", "Michael Keller und Telegram Gateway ganz oben; Robert als zentraler Executive Decision Architect darunter."),
                    ("Lead- & Spezialisten-Kacheln", "Abteilungsleiter für Tech, Recht, Marketing etc. mit ihren jeweils unterstellten Fach-Agenten."),
                    ("Interaktive Werkzeuge", "Modus-Umschaltung (Flowchart vs. Team-Karten), dynamisches Ziehen neuer Verbindungslinien, 'Hierarchie speichern' und 'Am Raster ausrichten'.")
                ],
                "workflow": [
                    "1. Klicke auf eine Agenten-Kachel, um Rollenprofil, Modell und aktuelle Auslastung einzusehen.",
                    "2. Ziehe Verbindungspunkte neu, um Fachrollen einer anderen Führungskraft zuzuordnen.",
                    "3. Klicke auf 'Hierarchie speichern', um die neuen Eskalationspfade aktiv zu schalten."
                ],
                "tip": "Wenn ein Spezialist bei einer Aufgabe blockiert ist, eskaliert das System automatisch an den hier hinterlegten Supervisor."
            },
            {
                "subtitle": "2.3 Interne Kommunikation (Agenten-Funk)",
                "img_id": "ops_comm",
                "concept": (
                    "Der interne Kommunikationskanal dient als Abhörzentrale für den automatischen Datenaustausch zwischen den Agenten. "
                    "Hier siehst du im Klartext, wie Teilaufträge zwischen Abteilungen übergeben werden, ohne dass dein persönlicher Chat überflutet wird."
                ),
                "elements": [
                    ("Kanalliste (Linke Spalte)", "Strukturiert nach Agenten, Teams und Domänen (z. B. #allgemein, #tech-dev, #legal, #marketing)."),
                    ("Nachrichten-Feed (Rechte Spalte)", "Chronologischer Stream aller Inter-Agenten-Nachrichten und Status-Meldungen direkt aus kanban.db.")
                ],
                "workflow": [
                    "1. Wähle links einen Kanal aus, um den Funkverkehr einer bestimmten Fachgruppe zu isolieren.",
                    "2. Verfolge, wie Robert einem Spezialisten Kontext bereitstellt oder wie zwei Agenten Ergebnisse abgleichen."
                ],
                "tip": "Nutze die interne Kommunikation zur Fehlersuche, wenn bei komplexen Mehretappen-Aufgaben Unklarheiten zwischen Agenten entstehen."
            }
        ],
        "workflow": [
            "1. Kontrolliere im Kanban-Board offene Tasks und weise neue Aufgaben gezielt zu.",
            "2. Prüfe im Organigramm, ob alle Spezialisten der richtigen Führungskraft zugeordnet sind.",
            "3. Wirf einen Blick in die interne Kommunikation, um autonome Absprachen zwischen Agenten zu verfolgen."
        ],
        "best_practices": "Halte die Spalte 'In Bearbeitung' durch strikte WIP-Limits schlank. Verknüpfe neue Fachrollen immer mit einem klaren Supervisor im Organigramm.",
        "starter_prompt": "Erstelle eine P1-Aufgabe im Kanban für Dr. Maximilian von W. zur Prüfung von Lizenzklauseln und weise Robert als Supervisor zu."
    },
    {
        "id": "org",
        "title": "3. Operations – Organisation & Ablaufdiagramm (Detail)",
        "subtitle": "Interaktiver 2D-Hierarchiebaum, Berichtslinien & dynamische Umhängung",
        "concept": (
            "Dieser Sub-Tab innerhalb von Operations visualisiert die Aufbau- und Ablaufstruktur deines Unternehmens als lebendigen 2D-Graphen. "
            "Hier wird die unternehmerische Kaskade sichtbar: von der Eigentümer- und Bot-Ebene über Robert (CEO) bis zu den Fach-Leads und Spezialisten. "
            "Verbindungslinien stellen echte Weisungs- und Berichtswege dar, die das System für autonome Eskalationen nutzt."
        ),
        "elements": [
            ("Apex-Ebene (Ganz oben)", 
             "Repräsentiert die Systemspitze mit dem Default Orchestrator, dem Telegram-Bot-Gateway und Michael Keller."),
            ("CEO & Orchestrator (Robert)", 
             "Robert (Executive Decision Architect) fungiert als zentraler Dreh- und Angelpunkt: Er nimmt strategische Anweisungen entgegen, "
             "zerlegt komplexe Vorgaben und verteilt Teilaufgaben an die Fachabteilungen."),
            ("Lead-Ebene (Abteilungsleiter)", 
             "Führungskräfte wie Dr. Robert Neumann (Software & Cloud), Dr. Maximilian von W. (Recht), Bobby Brown (Bauleitung), "
             "Katharina Völker (Marketing) und Dirk Hagemann (Logistik) koordinieren ihre Teams."),
            ("Spezialisten-Ebene (Fach-Agenten)", 
             "Detaillierte Fachprofile (z. B. Pricing & Margin Governance, Database Performance, DSGVO-Audit, PR-Texter, Product Requirements), "
             "die konkrete Werkzeuge ausführen."),
            ("Interaktive Werkzeuge & Schalter (Kopfzeile)", 
             "• Ansichtsmodus: Umschalten zwischen interaktivem Flowchart-Baum und kompakten Team-Karten.\n"
             "• Verbindungspunkte: Durch Ziehen von Verbindungspunkten lassen sich Vorgesetzte und Berichtswege dynamisch neu verknüpfen.\n"
             "• 'Hierarchie speichern': Übernimmt die geänderten Berichtslinien dauerhaft in die Konfiguration.\n"
             "• 'Am Raster ausrichten': Richtet alle Knoten für perfekte Übersichtlichkeit symmetrisch aus.")
        ],
        "workflow": [
            "1. Zoome mit dem Mausrad in das Organigramm und verschiebe die Ansicht mit gedrückter linker Maustaste.",
            "2. Klicke auf eine Agenten-Kachel (z. B. Robert), um dessen Rollenprofil, Modell und aktuelle Auslastung einzusehen.",
            "3. Um eine Fachrolle einer anderen Führungskraft zuzuordnen, ziehe den Verbindungspunkt von der Spezialisten-Kachel auf den neuen Lead.",
            "4. Klicke oben rechts auf 'Hierarchie speichern', um die neue Berichtsstruktur aktiv zu schalten."
        ],
        "best_practices": (
            "Nutze die Hierarchie, um Eskalationspfade abzusichern. Wenn ein Spezialist bei einer Aufgabe blockiert ist, eskaliert das System "
            "immer automatisch an den im Organigramm verknüpften Supervisor."
        ),
        "starter_prompt": "Zeige mir alle Agenten, die aktuell Robert als direktem Supervisor unterstellt sind, und prüfe deren Modell-Zuweisung."
    },
    {
        "id": "inbox",
        "title": "4. Eingang & Triage (HITL-Gatekeeper & Postfach)",
        "subtitle": "3-Spalten-Zentrale: Human-in-the-Loop Freigaben, E-Mail-Postfach & Telegram-Stream",
        "concept": (
            "Die Eingang & Triage Ansicht ist das operative Nadelöhr für alle eingehenden Signale von außen sowie für kritische "
            "Aktionen von innen. Das System trennt hier streng zwischen harmlosen Lese-Operationen und folgenreichen Schreib-Operationen "
            "(z. B. E-Mail-Versand, Code-Deployment oder Datenbank-Änderungen). Diese Ansicht garantiert, dass kein Agent eigenmächtig "
            "kritische Handlungen vollzieht, ohne deine ausdrückliche Bestätigung erhalten zu haben."
        ),
        "elements": [
            ("Spalte 1: Human-in-the-Loop Freigaben (HITL)", 
             "Hier landen alle blockierten Tool-Aufrufe mit gelber Warnmarkierung. Du siehst exakt: Welcher Agent will welche Aktion "
             "mit welchen Parametern ausführen? Mit 'Freigeben' wird die Aktion physisch ausgeführt, mit 'Ablehnen' verworfen."),
            ("Spalte 2: E-Mail Postfach & Auto-Triage", 
             "Synchronisiert ein- und ausgehende geschäftliche E-Mails via IMAP/SMTP. Neue Mails werden automatisch auf Dringlichkeit "
             "gescannt und können direkt per Klick an einen zuständigen Fach-Agenten zur Beantwortung übergeben werden."),
            ("Spalte 3: Telegram Stream (Live-Chat)", 
             "Spiegelt den gesamten Live-Dialog zwischen dir und dem Telegram-Bot (@Beatman_bot). Hier siehst du Befehle wie /robert "
             "oder /anwalt und die Antworten der Agenten in Echtzeit synchronisiert."),
            ("Mail-Sync & Status-Controls (Header)", 
             "Button 'Sync': Löst den sofortigen Mail-Abruf aus. Anzeige des Triage-Status (Nominal / Wartend).")
        ],
        "workflow": [
            "1. Prüfe Spalte 1 auf anstehende Freigabekarten. Lies den vorgeschlagenen Befehl oder Textentwurf durch.",
            "2. Klicke auf 'Freigeben', wenn der Entwurf passt, oder 'Ablehnen' mit einer Korrektur-Notiz.",
            "3. Sichte in Spalte 2 neue Mails. Klicke auf 'Delegieren', um die Mail z. B. Katharina Völker (Marketing/Sales) zuzuweisen.",
            "4. Verfolge in Spalte 3 den Chatverlauf von deinem Smartphone."
        ],
        "best_practices": (
            "Behalte die HITL-Spalte im Blick: Wenn ein Agent auf deine Freigabe wartet, pausiert sein Task im Kanban-Board. "
            "Durch zügige Freigaben hältst du den operativen Workflow flüssig."
        ),
        "starter_prompt": "Welche Freigaben stehen aktuell in der HITL-Spalte an und welche E-Mails sind in den letzten 24 Stunden eingegangen?"
    },
    {
        "id": "kader",
        "title": "5. Agenten-Kader & Flottenmanagement",
        "subtitle": "Katalog-Filterung, KI-Routenwahl & die 7 Fach-Reiter im Agenten-Cockpit",
        "concept": (
            "Der Agenten-Kader ist die Personalabteilung und das operative Einstellungszentrum deines Systems. "
            "Hier verwaltest du alle 54 Spezialisten-Profile, weist Sprachmodelle dynamisch zu, bearbeitest Verhaltensrichtlinien "
            "in der SOUL.md und konfigurierst persönliche Rufnamen für den direkten Messenger-Zugriff via Telegram."
        ),
        "elements": [
            ("Linke Spalte: Katalog & Schnellfilter", "Suche, Domänen-Auswahl, die drei Filter-Tabs (Aktiv, Favoriten, Alle) und Buttons für Neu, Speichern und Löschen."),
            ("Rechte Spalte: Agenten-Cockpit", "Großer Header mit Avatar-Verwaltung, Rollenbezeichnung, Provider- und Modell-Dropdowns sowie die 7 Icon-Kacheln für die Fach-Reiter."),
            ("OmniRoute Gateway Widget (Footer links)", "Zeigt den Status des lokalen LLM-Gateways an und erlaubt das Starten, Stoppen und Verwalten von KI-Routen.")
        ],
        "subsections": [
            {
                "subtitle": "5.0 Katalog-Verwaltung & Filter (Aktiv, Favoriten, Alle)",
                "img_id": "kader",
                "concept": (
                    "Der linke Katalog bietet schnellen Zugriff auf den gesamten Personalstamm. Die drei Filter-Reiter "
                    "strukturieren den Überblick: 'Aktiv' zeigt aktuell geladene Rollen, 'Favoriten' bietet Schnellzugriff "
                    "auf deine wichtigsten täglichen Berater, und 'Alle' listet das gesamte Spektrum aller Fachbereiche."
                ),
                "elements": [
                    ("Tab 'Aktiv'", "Filtert auf alle Agenten, die derzeit im Systemspeicher initialisiert oder mit offenen Tasks belegt sind."),
                    ("Tab 'Favoriten'", "Persönliche Auswahlliste deiner meistgenutzten Agenten (z. B. Robert, Michael Keller, Wirtschaftsjurist)."),
                    ("Tab 'Alle'", "Vollständiger Zugriff auf alle 54 Profile quer durch alle 7 Domänen."),
                    ("Domänen-Dropdown", "Filtert gezielt nach Strategie, Handel, Recht, Immobilien, Medien, Vertrieb oder Tech.")
                ],
                "workflow": [
                    "1. Nutze das Suchfeld oder das Domänen-Menü, um einen Spezialisten schnell zu finden.",
                    "2. Klicke auf ein Profil, um dessen vollständiges Cockpit auf der rechten Seite zu laden."
                ],
                "tip": "Markiere Schlüsselrollen als Favoriten, um im Alltag ohne langes Scrollen direkt auf sie zugreifen zu können."
            },
            {
                "subtitle": "5.1 Modell-Wechsel & Provider-Wahl (KI-Routenwahl)",
                "img_id": "kader",
                "concept": (
                    "Jeder Agent kann mit einem individuellen Sprachmodell betrieben werden. Über die Dropdowns im Header "
                    "oder im Chat-Tab wechselst du den KI-Provider und das Zielmodell unterbrechungsfrei während des Betriebs."
                ),
                "elements": [
                    ("Provider-Dropdown", "Wahl zwischen OpenRouter, Google AI (Gemini), OmniRoute, Groq, OpenAI und NVIDIA NIM."),
                    ("Modell-Dropdown", "Auswahl des konkreten Modells (z. B. 'auto/best-free' für kostenlose intelligente Routen, Claude 3.5 Sonnet für komplexe Analysen oder Gemini Flash für Höchstgeschwindigkeit)."),
                    ("Hot-Swap", "Änderungen werden sofort wirksam – ein Neustart des Systems oder Daemons ist nicht erforderlich.")
                ],
                "workflow": [
                    "1. Wähle im Header des Agenten den gewünschten Provider (z. B. OpenRouter).",
                    "2. Wähle das passende Modell aus der Liste.",
                    "3. Klicke links unten auf 'Speichern', um die Modell-Zuordnung dauerhaft im Profil zu sichern."
                ],
                "tip": "Nutze für Routineaufgaben 'auto/best-free' über OmniRoute, um API-Kosten zu minimieren, und schalte nur für strategische Meilensteine auf Premium-Modelle um."
            },
            {
                "subtitle": "5.2 Übersicht (360°-Dossier & Rufname)",
                "img_id": "kader",
                "concept": (
                    "Das 360°-Dossier fasst die Kernstammdaten zusammen. Hier hinterlegst du den persönlichen Rufnamen, "
                    "über den der Agent direkt in Telegram angesprochen werden kann (z. B. /robert oder /anwalt)."
                ),
                "elements": [
                    ("Persönlicher Name & Handle", "Vollständiger Name (z. B. Alexander Richter) und systemweites Hermes-Handle."),
                    ("Stellenbeschreibung & Domäne", "Fachliche Rollenbezeichnung und Zuordnung zur primären Unternehmensdomäne."),
                    ("Eingabefeld 'Rufname'", "Logische Verknüpfung für Messenger: Gibst du hier 'anwalt' ein, reagiert der Agent auf '/anwalt' in Telegram."),
                    ("Kognitive Parameter", "Konfiguration von Temperature und Top-P für die Kreativität bzw. Exaktheit der Antworten.")
                ],
                "workflow": [
                    "1. Trage im Feld 'Rufname' das gewünschte Kürzel ein (z. B. 'robert' oder 'steuer').",
                    "2. Klicke auf 'Speichern'. Ab sofort leitet das Telegram-Gateway Nachrichten mit diesem Präfix an diesen Agenten."
                ],
                "tip": "Vergib kurze, prägnante Rufnamen ohne Sonderzeichen, um die Smartphone-Eingabe maximal komfortabel zu halten."
            },
            {
                "subtitle": "5.3 Direkt-Chat",
                "img_id": "kader_chat",
                "concept": (
                    "Ermöglicht den unmittelbaren 1:1-Dialog mit dem ausgewählten Spezialisten direkt im Browser, "
                    "inklusive Parameter-Feinjustierung und Streaming-Antworten."
                ),
                "elements": [
                    ("Chat-Verlauf & Eingabezeile", "Vollwertige Chat-Oberfläche mit Markdown-Unterstützung und Code-Highlighting."),
                    ("Parameter-Slider", "Schieberegler für Temperature und Kontextlänge für Ad-hoc-Experimente.")
                ],
                "workflow": [
                    "1. Wechsle auf den Reiter 'Chat'.",
                    "2. Stelle eine konkrete Fachfrage an den Spezialisten und beurteile dessen Rollenverhalten."
                ],
                "tip": "Ideal zum Kalibrieren und Testen von Agenten, bevor sie im Kanban-Board auf echte Kundenaufgaben losgelassen werden."
            },
            {
                "subtitle": "5.4 Fähigkeiten (Skills & Tool-Sets)",
                "img_id": "kader_skills",
                "concept": (
                    "Hier weist du dem Agenten konkrete Werkzeuge und Schnittstellen zu (z. B. Web-Search, PDF-Reader, Code-Execution oder E-Mail-Versand)."
                ),
                "elements": [
                    ("Skill-Katalog mit Checkboxen", "Aktivieren oder Deaktivieren einzelner Tool-Module per Mausklick."),
                    ("Berechtigungsstufen", "Einschränkung von zerstörerischen Werkzeugen auf den Read-Only Modus.")
                ],
                "workflow": [
                    "1. Prüfe die aktivierten Skills des Agenten.",
                    "2. Aktiviere zusätzliche Tools, wenn der Agent z. B. Zugriff auf die Websuche oder das Dateisystem benötigt."
                ],
                "tip": "Vergib Werkzeuge nach dem Prinzip der geringsten Rechte (Least Privilege), um unerwünschte Nebeneffekte zu vermeiden."
            },
            {
                "subtitle": "5.5 Operations (Zugeordnete Tasks & Historie)",
                "img_id": "kader_operations",
                "concept": (
                    "Zeigt alle Aufgaben aus dem Kanban-Board, die diesem spezifischen Agenten aktuell zugewiesen sind oder in der Vergangenheit erledigt wurden."
                ),
                "elements": [
                    ("Aktive Tasks", "Karten in Bearbeitung inklusive Fortschritt und Token-Verbrauch."),
                    ("Erledigte Aufgaben", "Historischer Leistungsnachweis und abgelegte Artefakte.")
                ],
                "workflow": [
                    "1. Überprüfe die Auslastung des Agenten vor Zuweisung neuer Großaufträge.",
                    "2. Springe per Klick direkt in die verknüpfte Task-Karte im Operations-Board."
                ],
                "tip": "Nutze diesen Reiter, um Engpässe bei einzelnen Spezialisten sofort zu erkennen."
            },
            {
                "subtitle": "5.6 SOUL (System Prompt & Verhaltens-Direktiven)",
                "img_id": "kader_soul",
                "concept": (
                    "Die 'Seele' des Agenten: Hier wird der System-Prompt definiert, der Tonalität, Verhaltensregeln, ethische Leitplanken "
                    "und Denkweisen des Spezialisten festlegt."
                ),
                "elements": [
                    ("Inline-Markdown-Editor", "Direkte Bearbeitung der SOUL.md mit Syntax-Unterstützung."),
                    ("Prompt-Vorschau", "Live-Rendering des finalen System-Prompts inklusive injizierter Variablen.")
                ],
                "workflow": [
                    "1. Passe die Verhaltensrichtlinien im Editor an (z. B. 'Antworte stets nach deutschem HGB').",
                    "2. Klicke auf 'Speichern', um die Direktiven sofort im Profil zu verankern."
                ],
                "tip": "Formuliere klare 'Negativ-Regeln' (was der Agent keinesfalls tun darf), um Halluzinationen wirksam zu unterbinden."
            },
            {
                "subtitle": "5.7 Personalakte (Dossier & SOP)",
                "img_id": "kader_personalakte",
                "concept": (
                    "Das formelle HR-Dossier des Agenten im Markdown-Format: Enthält Ausbildung, Werdegang, Standard Operating Procedures (SOPs) "
                    "und Qualitätsstandards für seine Arbeitsergebnisse."
                ),
                "elements": [
                    ("Dossier-Viewer & Editor", "Umfangreiche Personalakte zur Dokumentation der Kompetenzen."),
                    ("SOP-Abschnitte", "Konkrete Arbeitsanweisungen, wie Prüfberichte oder Gutachten aufgebaut sein müssen.")
                ],
                "workflow": [
                    "1. Hinterlege firmenspezifische Vorlagen und Qualitätskriterien in der Personalakte.",
                    "2. Der Agent zieht diese Vorgaben bei jeder Aufgabenbearbeitung als Referenz heran."
                ],
                "tip": "Pflege hier unternehmensspezifische Standards ein – so arbeiten neue Agenten sofort konform zu deinen Firmenrichtlinien."
            },
            {
                "subtitle": "5.8 Talent-Marktplatz",
                "img_id": "kader_marketplace",
                "concept": (
                    "Erlaubt den Import und Export von Agenten-Profilen als JSON/Markdown-Pakete, um Rollen zwischen Projekten "
                    "oder aus Vorlagen-Katalogen auszutauschen."
                ),
                "elements": [
                    ("Rollen-Katalog", "Vorgefertigte Profile für spezielle Branchen (z. B. Modulbau, E-Commerce, Krypto-Compliance)."),
                    ("Export-Funktion", "Sichert das vollständige Profil inklusive Skills und SOUL als portable Datei.")
                ],
                "workflow": [
                    "1. Wähle ein Profil aus dem Katalog, um einen neuen Spezialisten mit einem Klick zu installieren.",
                    "2. Exportiere eigene bewährte Profile zur Sicherung oder Wiederverwendung."
                ],
                "tip": "Nutze den Marktplatz, um deine Flotte bei neuen Geschäftszweigen schnell um erfahrene Rollen-Setups zu erweitern."
            }
        ],
        "workflow": [
            "1. Wähle links einen Agenten (z. B. Robert) oder klicke auf 'Neu', um ein Profil anzulegen.",
            "2. Passe im Header den Provider und das Sprachmodell an.",
            "3. Hinterlege unter 'Übersicht' den gewünschten Rufnamen für Telegram.",
            "4. Kalibriere Direktiven in 'SOUL' und Fähigkeiten in 'Skills', danach klicke auf 'Speichern'."
        ],
        "best_practices": "Überprüfe regelmäßig die Modell-Zuweisung. Routine-Rollen sollten auf kostengünstigen Modellen laufen, strategische Leads auf Spitzenmodellen.",
        "starter_prompt": "Öffne das Profil von Robert (Executive Decision Architect) und zeige mir seine SOUL-Direktiven sowie den hinterlegten Rufnamen."
    },
    {
        "id": "showroom",
        "title": "6. Showroom (Projekt-Explorer & Artefakt-Galerie)",
        "subtitle": "Verwaltung von Arbeitsergebnissen, Code-Artefakten & Python-Sandbox",
        "concept": (
            "Der Showroom ist die Ausstellungs- und Prüfhalle für alle fertigen Arbeitsergebnisse, die deine Agenten erzeugt haben. "
            "Statt unübersichtlicher Chat-Verläufe findest du hier sauber katalogisierte Artefakte: von fertigen HTML-Apps über generierte "
            "Diagramme bis hin zu mehrseitigen Strategie-Dossiers. Die integrierte Python-Sandbox erlaubt die gefahrlose Ausführung von Skripten."
        ),
        "elements": [
            ("Artefakt-Katalog & Filter", 
             "Listet alle erzeugten Dateien geordnet nach Datum, Ersteller-Agent und Projekt. Filterung nach Dokumenten, Code, Bildern und Daten."),
            ("Workspace Vault Reader", 
             "Ermöglicht die strukturierte Inspektion von Projektordnern direkt im Browser mit Vorschaufunktion für Markdown, JSON und HTML."),
            ("Python-Sandbox (Sub-Tab)", 
             "Isolierte Laufzeitumgebung, in der erzeugter Python-Code direkt ausgeführt und visualisiert werden kann, ohne das Host-System zu gefährden."),
            ("Download & Export Buttons", 
             "Erlaubt den sofortigen Download einzelner Artefakte oder ganzer Projekt-Bundles als ZIP-Archiv.")
        ],
        "workflow": [
            "1. Nach Fertigstellung eines Tasks im Kanban-Board wechsle in den Showroom.",
            "2. Wähle das neu erzeugte Artefakt aus der Liste aus.",
            "3. Begutachte die Live-Vorschau (z. B. eine interaktive Kalkulationstabelle oder einen Bericht).",
            "4. Führe bei Bedarf Code-Artefakte in der Sandbox aus oder lade das Dokument herunter."
        ],
        "best_practices": (
            "Nutze den Showroom für finale Qualitätsprüfungen. Wenn ein Dokument hier fehlerfrei gerendert wird, "
            "ist es bereit für den Kunden- oder Partnerkontakt."
        ),
        "starter_prompt": "Zeige mir alle im Showroom abgelegten Artefakte der letzten 48 Stunden und öffne das jüngste Strategiedokument."
    },
    {
        "id": "library",
        "title": "7. Zentralbibliothek & Wissensmanagement",
        "subtitle": "RAG-Index (AnythingLLM), Dokumenten-Erfasser (Auto-OCR) & Obsidian-Vault",
        "concept": (
            "Die Zentralbibliothek ist das kollektive Gedächtnis deiner Organisation. Sie vereint semantische Vektorsuche (RAG), "
            "automatisierte Dokumenten-Ingestion mit OCR und die Verwaltung deines lokalen Obsidian-Vaults unter einer konsistenten Oberfläche. "
            "Hier abgelegtes Wissen steht allen 54 Agenten sofort für fundierte Antworten zur Verfügung."
        ),
        "elements": [
            ("Drei integrierte Sub-Tabs (Header)", "RAG Index, Dokumenten-Erfasser und Obsidian Vault."),
            ("Hilfe- & Sync-Schalter", "Kontext-Hilfe und manuelle Synchronisation des Dokumentenbestands.")
        ],
        "subsections": [
            {
                "subtitle": "7.1 RAG Wissens-Index (AnythingLLM)",
                "img_id": "library",
                "concept": (
                    "Eingebettete Schnittstelle zu AnythingLLM für semantische Vektorsuche und Grounded Retrieval. "
                    "Dokumente werden in Vektoren übersetzt; Agenten rufen exakte Textstellen passend zu Benutzerfragen ab."
                ),
                "elements": [
                    ("Workspace-Verwaltung", "Strukturierung des Wissens nach Projekten oder Firmenbereichen."),
                    ("Vektordatenbank-Status", "Überwachung der indizierten Dokumentenfragmente und Embedding-Modelle.")
                ],
                "workflow": [
                    "1. Wähle den gewünschten Workspace aus.",
                    "2. Teste semantische Abfragen direkt im Chat-Interface von AnythingLLM."
                ],
                "tip": "Halte Workspaces thematisch getrennt, um die Treffergenauigkeit bei Fachfragen zu maximieren."
            },
            {
                "subtitle": "7.2 Dokumenten-Erfasser (File Ingest & Auto-OCR)",
                "img_id": "library_erfasser",
                "concept": (
                    "Der zentrale Upload-Trichter für neue Fachliteratur, Pläne, Verträge und Gutachten. "
                    "PDF-, DOCX- und Textdateien werden per Drag & Drop hochgeladen, durch den Docling-Dienst per Auto-OCR "
                    "in sauberes Markdown konvertiert und vollautomatisch im Obsidian-Vault sowie im RAG-Index abgelegt."
                ),
                "elements": [
                    ("4 Core Hubs", "00_HR_Agenten, 02_Wissensbibliothek, Protokolle/, 00_Notebook_Synthesen."),
                    ("Upload-Dropzone", "Zieht Dateien per Drag & Drop hinein; automatische Themenklassifikation wählbar."),
                    ("Tabelle der Werke", "Übersicht aller erfassten Dokumente mit Volltextsuche, Kategorie-Filtern und OCR-Status.")
                ],
                "workflow": [
                    "1. Ziehe ein PDF (z. B. ein 80-seitiges Gutachten) in die Dropzone.",
                    "2. Wähle eine Kategorie oder nutze 'Automatisch erkennen'.",
                    "3. Klicke auf 'Jetzt erfassen & in Vault einlesen'. Der Fortschrittsbalken visualisiert den OCR-Lauf.",
                    "4. Das Werk erscheint sofort in der Tabelle und steht allen Agenten zur Verfügung."
                ],
                "tip": "Dank Auto-OCR werden auch gescannte Dokumente und Tabellen zuverlässig in durchsuchbares Markdown übersetzt."
            },
            {
                "subtitle": "7.3 Obsidian Vault (Dateibaum & Notiz-Viewer)",
                "img_id": "library_vault",
                "concept": (
                    "Direkter Einblick in deinen physischen Obsidian-Ordner auf der Festplatte. "
                    "Erlaubt das Durchsuchen, Filtern und Lesen aller Markdown-Notizen und Protokolle direkt im Browser."
                ),
                "elements": [
                    ("Dateibaum (Linke Spalte)", "Hierarchische Ordneransicht aller Notizen mit Schnellfilter und Auf-/Zuklapp-Buttons."),
                    ("Markdown-Viewer (Rechte Spalte)", "Formatierte Leseansicht der ausgewählten Notiz mit Pfadanzeige.")
                ],
                "workflow": [
                    "1. Nutze die Suchleiste über dem Dateibaum, um eine Notiz nach Stichworten zu filtern.",
                    "2. Klicke auf eine Datei, um ihren Inhalt sofort im rechten Viewer zu lesen."
                ],
                "tip": "Alle hier sichtbaren Notizen liegen als Standard-Dateien auf deiner Festplatte – du kannst sie jederzeit mit externen Editoren öffnen."
            }
        ],
        "workflow": [
            "1. Lade neue Fachdokumente im Dokumenten-Erfasser per Drag & Drop hoch.",
            "2. Verfolge die automatische OCR-Umwandlung und Vektor-Indizierung.",
            "3. Kontrolliere im Obsidian Vault, ob die Markdown-Datei sauber abgelegt wurde.",
            "4. Deine Agenten nutzen dieses Wissen ab sofort vollautomatisch bei der Beantwortung von Aufgaben."
        ],
        "best_practices": "Pflege Fachliteratur strukturiert in den passenden Kategorien ein. So bleibt die Vektor-Suche schnell und hochpräzise.",
        "starter_prompt": "Welche Fachbücher sind aktuell in '02_Wissensbibliothek' erfasst und wie viele Dokumente enthält der RAG-Index?"
    },
    {
        "id": "brain",
        "title": "8. Second Brain (Wissens-Galaxie & Notiz-Graph)",
        "subtitle": "3D-Wissensgraph, semantische Vernetzung & Quartz Notiz-Synthesen",
        "concept": (
            "Das Second Brain visualisiert das gesammelte Unternehmenswissen als lebendiges, dreidimensionales "
            "Netzwerk. Während traditionelle Ordnerstrukturen starr sind, zeigt die Wissens-Galaxie, wie Agenten-Profile, "
            "Aufgaben, DIN-Normen und Protokolle semantisch miteinander verknüpft sind. Wissenslücken und isolierte "
            "Informationsinseln werden auf einen Blick erkennbar."
        ),
        "elements": [
            ("3D Force-Directed Graph (Galaxie)", 
             "Interaktives 3D-Universum deiner Notizen: Knoten repräsentieren Dokumente (farblich codiert nach Typ: "
             "Personalakten = Gelb, Wissensnotizen = Cyan, Core-System = Blau). Kanten stellen Hyperlinks und semantische Verwandtschaften dar."),
            ("Graph-Steuerung & Filterleiste", 
             "Erlaubt das Zoomen, Rotieren und Filtern nach Knotentypen (z. B. nur Agenten oder nur Fachbücher anzeigen). "
             "Schieberegler für Knotenabstand und Gravitation."),
            ("Detail-Inspektor (Rechte Sidebar)", 
             "Klickst du auf einen Knoten, öffnet sich eine Vorschau mit Zusammenfassung, Verknüpfungen und direktem Sprung in die Quelldatei."),
            ("Quartz- & Synthese-Modus (Sub-Tabs)", 
             "Ermöglicht das Umschalten auf die 2D-Quartz-Publikationsansicht oder den Synthese-Berichtsgenerator.")
        ],
        "workflow": [
            "1. Navigiere mit der Maus durch die 3D-Galaxie (Linksklick: Rotieren, Rechtsklick: Verschieben, Scrollen: Zoomen).",
            "2. Klicke auf einen zentralen Knoten (z. B. 'Robert' oder eine DIN-Norm), um dessen Vernetzung zu analysieren.",
            "3. Nutze die Filterknöpfe oben, um isolierte Cluster ohne Querverweise aufzuspüren.",
            "4. Öffne im Detail-Inspektor die verknüpfte Markdown-Notiz zur vertiefenden Lektüre."
        ],
        "best_practices": (
            "Achte darauf, dass neue Dokumente durch Wikilinks ([[Dokumentname]]) mit bestehenden Konzepten verknüpft werden. "
            "Je dichter das Netzwerk vernetzt ist, desto intelligenter kombinieren die Agenten Querverweise."
        ),
        "starter_prompt": "Zeige mir im Second Brain alle Notizen, die direkt mit dem Thema 'Modulbau' und 'Recht' verknüpft sind."
    },
    {
        "id": "automation",
        "title": "9. Workflow-Engine (n8n Automation Mesh)",
        "subtitle": "Eingebettete Low-Code Automatisierung, Event-Trigger & Cron-Jobs",
        "concept": (
            "Die Workflow-Engine bindet die vollwertige Low-Code Automatisierungsplattform n8n nahtlos in Archon OS ein. "
            "Hier erstellst du autonome Hintergrundprozesse: von zeitgesteuerten Cron-Jobs (z. B. morgendlicher News-Scan) "
            "über Webhook-Trigger (z. B. Rechnungs-Eingang) bis hin zu mehrstufigen Eskalationsketten. Agenten können Workflows "
            "aktiv auslösen oder als ausführende Knotenpunkte innerhalb von n8n agieren."
        ),
        "elements": [
            ("Vollwertige n8n Canvas-Oberfläche", 
             "Direkt im System eingebetteter visueller Workflow-Editor mit hunderten fertigen Schnittstellen-Knoten."),
            ("Archon-Spezifische Node-Bibliothek", 
             "Eigene Knoten zur direkten Interaktion mit dem Agenten-Kader, zum Erstellen von Kanban-Tasks und zum Abfragen der Zentralbibliothek."),
            ("Webhook- & Event-Eingänge", 
             "Lauscht auf externe Ereignisse aus CRM, E-Mail-Servern, GitHub-Repositories oder Web-Formularen."),
            ("Execution History & Debugger", 
             "Lückenlose Nachverfolgung jedes Workflow-Laufs mit Ein- und Ausgabewerten zur sekundenschnellen Fehleranalyse.")
        ],
        "workflow": [
            "1. Erstelle einen neuen Workflow und platziere einen Trigger-Knoten (z. B. 'Schedule' für tägliche Ausführung).",
            "2. Verknüpfe den Trigger mit einem 'Archon Agent Node' und wähle die gewünschte Rolle (z. B. Marktanalyst).",
            "3. Leite das Ergebnis an einen Benachrichtigungs-Knoten (z. B. Telegram Push) oder das Operations-Kanban weiter.",
            "4. Aktiviere den Workflow per Kippschalter – er läuft ab sofort vollautonom im Docker-Netzwerk."
        ],
        "best_practices": (
            "Nutze n8n für alle deterministischen Routineabläufe (Daten abholen, filtern, transformieren). "
            "Schalte Agenten nur an den Stellen dazwischen, an denen echte kognitive Bewertung oder Textverständnis erforderlich ist."
        ),
        "starter_prompt": "Welche n8n-Workflows sind aktuell aktiv und wann lief der letzte automatische Hintergrund-Job?"
    },
    {
        "id": "omniroute",
        "title": "10. LLM Gateway (OmniRoute AI Router)",
        "subtitle": "Multi-Provider KI-Routing, Kosten-Optimierung & Ausfallsicherheit",
        "concept": (
            "OmniRoute ist das intelligente Schienennetz für alle kognitiven Abfragen in Archon OS. Statt fest an einen einzigen "
            "KI-Hersteller gebunden zu sein, entkoppelt OmniRoute die Agenten vollständig von der Modell-Infrastruktur. "
            "Das Gateway routet jede Anfrage dynamisch nach Kriterien wie Kosten, Geschwindigkeit und Verfügbarkeit – "
            "inklusive unterbrechungsfreiem automatischem Failover bei Ausfällen eines Anbieters."
        ),
        "elements": [
            ("Multi-Provider Anbindung", 
             "Zentrale Verwaltung der API-Schlüssel für OpenRouter, OpenAI, Anthropic, Google Gemini, Groq, Mistral und lokale LLMs."),
            ("Intelligente Routing-Profile", 
             "• auto/best-free: Wählt automatisch das leistungsfähigste kostenlose Modell mit Restkontingent.\n"
             "• code-heavy: Leitet Programmieraufgaben an spezialisierte Codemodelle weiter.\n"
             "• creative-reasoning: Nutzt Spitzenmodelle (Claude 3.5 Sonnet / GPT-4o) für strategische Synthesen."),
            ("Echtzeit-Latenz- & Fehlermonitor", 
             "Visualisiert Antwortzeiten in Millisekunden und Fehlerraten pro Provider mit automatischem Circuit-Breaker."),
            ("Kosten- & Budget-Drossel", 
             "Verhindert überraschende Rechnungen durch harte Obergrenzen pro Modell und Tag.")
        ],
        "workflow": [
            "1. Kontrolliere im OmniRoute-Dashboard die Latenzen und Verfügbarkeiten der konfigurierten Provider.",
            "2. Passe bei Bedarf die Standard-Route an (z. B. 'auto/best-free' für maximal budgetschonenden Betrieb).",
            "3. Sollte ein Anbieter (z. B. durch ein Rate-Limit) ausfallen, beobachte, wie OmniRoute transparent auf den Fallback wechselt."
        ],
        "best_practices": (
            "Lasse Standard-Aufgaben über kostenlose Routen laufen. Hinterlege immer mindestens einen stabilen Fallback-Provider "
            "(z. B. Google Gemini Flash oder Groq), damit das Gesamtsystem auch bei API-Aussetzern nicht stoppt."
        ),
        "starter_prompt": "Welcher LLM-Provider bietet aktuell die geringste Latenz und wie viele Anfragen wurden heute über OmniRoute geroutet?"
    },
    {
        "id": "guardian",
        "title": "11. Token Guard (Guardian & Budgetwächter)",
        "subtitle": "Kosten-Leitplanken, Raten-Limits, Endlosschleifenschutz & Safety Controls",
        "concept": (
            "Der Guardian ist der Sicherheitschef und Budgetwächter des Betriebssystems. Autonome Agenten bergen "
            "ohne strenge Leitplanken das Risiko von Endlosschleifen oder unkontrolliertem Token-Verbrauch. "
            "Der Guardian überwacht jede Transaktion in Echtzeit, erzwingt Budgetgrenzen und schaltet Prozesse "
            "bei Fehlverhalten hart ab, bevor finanzielle Schäden entstehen können."
        ),
        "elements": [
            ("Budget-Obergrenzen (Hard- & Soft-Limits)", 
             "Definiere maximale Tages-, Wochen- und Monatsbudgets in USD. Bei Erreichen des Soft-Limits erfolgen Warnungen; "
             "das Hard-Limit sperrt weitere API-Aufrufe verlässlich ab."),
            ("Loop-Killer & Rekursionsschutz", 
             "Erkennt, wenn ein Agent in eine Endlosschleife gerät (z. B. wiederholte identische Tool-Aufrufe ohne Fortschritt), "
             "stoppt den Prozess nach 15 Schritten automatisch und setzt den Task auf 'Blockiert'."),
            ("Prompt Injection Scanner", 
             "Untersucht eingehende externe Texte (z. B. Mails oder Webseiten) auf manipulative Steuerbefehle und markiert verdächtige Inhalte."),
            ("Globaler Notfall-Kill-Switch", 
             "Roter Not-Aus-Schalter in der Kopfzeile: Stoppt alle aktuell laufenden Agenten-Prozesse augenblicklich mit einem Klick.")
        ],
        "workflow": [
            "1. Überprüfe die Auslastungsanzeige des heutigen Tagesbudgets.",
            "2. Konfiguriere die Alarmschwellen für automatische Benachrichtigungen via Telegram.",
            "3. Sollte der Schleifenkiller ausgelöst werden, prüfe im Vorfall-Logbuch, welcher Agent den Stopp verursacht hat."
        ],
        "best_practices": (
            "Setze das Tageslimit zu Beginn konservativ (z. B. $3.00 bis $5.00). Du kannst das Limit bei Großprojekten "
            "jederzeit mit einem Klick anheben, bist aber dauerhaft vor versehentlichen Ausreißern geschützt."
        ),
        "starter_prompt": "Wie hoch ist der aktuelle Stand des Tagesbudgets im Token Guard und gab es heute ausgelöste Schutzabschaltungen?"
    },
    {
        "id": "plugins",
        "title": "12. Erweiterungen (Plugin- & MCP-Zentrale)",
        "subtitle": "Model Context Protocol Treiber, Tool-Berechtigungen & Schnittstellen",
        "concept": (
            "Die Plugin-Zentrale verwaltet die Werkzeugkiste deines Systems nach dem modernen Model Context Protocol (MCP) Standard. "
            "MCP fungiert als universeller Treiber-Standard: Hier bindest du externe Software, Datenbanken, lokale Dateisystem-Werkzeuge "
            "oder Web-Scraper modular an. Agenten erhalten nur Zugriff auf genau die Tools, die du für ihre jeweilige Rolle freigeschaltet hast."
        ),
        "elements": [
            ("Installierte MCP-Treiber", 
             "Kacheln für angebundene Werkzeuge wie Filesystem-Tools, Web-Search (Brave/Google), Telegram-Bot, E-Mail-Guard und ChromaDB."),
            ("Aktivierungs- & Sicherheits-Kippschalter", 
             "Jedes Tool kann einzeln aktiviert, pausiert oder auf den reinen Lese-Modus beschränkt werden."),
            ("Berechtigungs-Matrix (Scopes)", 
             "Festlegung, welche Fachabteilung (z. B. nur IT oder nur Recht) ein bestimmtes Plugin nutzen darf."),
            ("Plugin-Status & Latenzüberwachung", 
             "Zeigt an, ob die Verbindung zum lokalen oder externen MCP-Server nominal besteht.")
        ],
        "workflow": [
            "1. Sichte im Plugin-Manager die verfügbaren und installierten MCP-Treiber.",
            "2. Aktiviere ein neues Werkzeug (z. B. 'Web-Research') per Kippschalter.",
            "3. Öffne die Konfiguration, trage bei Bedarf Umgebungsvariablen oder API-Schlüssel ein und teste die Verbindung.",
            "4. Weise das Tool im Agenten-Kader gezielt den Rollen zu, die es produktiv benötigen."
        ],
        "best_practices": (
            "Schränke Schreib-Werkzeuge (z. B. E-Mail-Versand oder Datei-Löschung) immer strikt ein und kopple sie "
            "im Zweifel stets an das Human-in-the-Loop Freigabeverfahren im Eingang."
        ),
        "starter_prompt": "Welche MCP-Plugins sind aktuell aktiv und welche Rollen haben Berechtigung für Web-Search-Tools?"
    },
    {
        "id": "research",
        "title": "13. Research Lab (Deep Search & Wissensbeschaffung)",
        "subtitle": "Evidenzbasierte Recherche, Quellen-Triangulation & Synthese-Berichte",
        "concept": (
            "Das Research Lab ist das wissenschaftliche Forschungszentrum deines Unternehmens. Wenn komplexe Fragen auftauchen, "
            "die nicht allein aus dem internen Wissensbestand beantwortet werden können, wird das Research Lab aktiv. "
            "Es steuert mehrstufige Suchprozesse, vergleicht divergierende Quellen (Triangulation), filtert Desinformation heraus "
            "und destilliert die Ergebnisse in saubere Berichte mit vollständigem Quellennachweis."
        ),
        "elements": [
            ("Recherche-Auftragsmaske", 
             "Hier formulierst du die Forschungsfrage, bestimmst die Suchtiefe (Oberflächlich, Standard, Deep Research) und wählst Zieldomänen."),
            ("Quellen-Monitor & Evidenz-Score", 
             "Zeigt gescannte Webseiten, PDF-Dokumente und Fachportale inklusive eines Vertrauenswürdigkeits-Index an."),
            ("Live-Synthese Protokoll", 
             "Dokumentiert Schritt für Schritt, wie Hypothesen geprüft, Teilergebnisse verifiziert und Gegenevidenzen abgewogen werden."),
            ("Dossier-Export (Markdown / PDF)", 
             "Überträgt das fertige Recherche-Dossier mit einem Klick in den Showroom und in die Zentralbibliothek.")
        ],
        "workflow": [
            "1. Formuliere eine präzise Recherchefrage (z. B. 'Aktuelle Fördermittel für Modulbauweise in NRW 2026').",
            "2. Wähle die Suchtiefe 'Deep Research' und starte den Lauf.",
            "3. Verfolge im Live-Protokoll, wie der Recherche-Agent Quellen filtert und Kernzitate extrahiert.",
            "4. Lies das fertige Synthese-Dossier gegen und exportiere es in den Obsidian-Vault deines Second Brain."
        ],
        "best_practices": (
            "Formuliere Forschungsfragen möglichst spezifisch mit Randbedingungen (z. B. Region, Jahr, Branche). "
            "Das spart Token-Kosten und liefert hochgradig verwertbare Handlungsempfehlungen."
        ),
        "starter_prompt": "Starte einen Research-Lauf zum Thema 'Bauordnung NRW Novelle 2026: Wesentliche Änderungen für Genehmigungsverfahren'."
    },
    {
        "id": "log_stream",
        "title": "14. Telemetrie & Logs (Live-Audit Stream)",
        "subtitle": "Sekundengenaues Audit, System-Telemetrie & kryptografischer Trace-Feed",
        "concept": (
            "Telemetrie & Logs ist das unbestechliche Flugschreiber-System von Archon OS. Jede einzelne Aktion – vom kleinsten "
            "API-Ping über Tool-Ausführungen bis hin zu Benutzerfreigaben – wird hier sekundengenau erfasst und manipulationssicher "
            "protokolliert. Sollte ein unerwartetes Verhalten auftreten, liefert dieser Stream die vollständige Diagnose-Kette zur schnellen Ursachenanalyse."
        ),
        "elements": [
            ("Drei spezialisierte Log-Quellen (Sub-Tabs)", 
             "• Container-Logs: Physische stdout/stderr Ausgaben der 11 Docker-Container.\n"
             "• Agenten-Logs: Konsolenausgaben und Denkprozesse der Hermes-Agenten.\n"
             "• Audit-Trail: Revisionssicherer Hash-Chain Log aller geschäftlichen Freigaben."),
            ("Such- & Filterleiste", 
             "Echtzeit-Filterung nach Log-Level (DEBUG, INFO, WARN, ERROR), Container-Namen oder Schlüsselbegriffen."),
            ("Auto-Scroll & Pausieren", 
             "Fixiert den Stream bei der Analyse eines Fehlers, ohne den laufenden Datenfluss im Hintergrund zu unterbrechen."),
            ("Download & Export", 
             "Exportiert den gefilterten Protokoll-Auszug zur externen Analyse oder Archivierung.")
        ],
        "workflow": [
            "1. Bei Auffälligkeiten in Mission Control wechsle in den Log-Stream.",
            "2. Filter nach dem Level 'ERROR' oder dem Namen des betroffenen Agenten.",
            "3. Analysiere den Stacktrace und den vorangegangenen Prompt, um die Fehlerquelle exakt zu lokalisieren.",
            "4. Nutze die Erkenntnisse, um Prompts oder Tool-Berechtigungen im Kader nachzujustieren."
        ],
        "best_practices": (
            "Nutze den Audit-Trail für die Compliance-Dokumentation. Dank der kryptografischen Verkettung kannst du jederzeit "
            "lückenlos nachweisen, wer welche Aktion zu welchem Zeitpunkt freigegeben hat."
        ),
        "starter_prompt": "Zeige mir alle Warnungen und Fehler (WARN, ERROR) im Log-Stream der letzten 2 Stunden."
    },
    {
        "id": "prompt_studio",
        "title": "15. Spezial-Feature: Archon Prompt Studio (1.079 Vorlagen & Fabric SOP)",
        "subtitle": "Enterprise Prompt-Engineering, 255+ Fabric Patterns & 5-Felder-Struktur",
        "concept": (
            "Das Archon Prompt Studio ist ein hochkarätiges Prompt-Engineering-Werkzeug direkt im Herzen des Betriebssystems. "
            "Es löst das größte Problem bei der Arbeit mit LLMs: vage, unvollständige oder inkonsistente Instruktionen. "
            "Das Studio bündelt 1.079 praxiserprobte Enterprise-Vorlagen und über 255 Fabric Standard Operating Procedures (SOPs). "
            "Seine modulare 5-Felder-Architektur zwingt jede Aufgabenstellung in eine mathematisch präzise Form (Rolle, Kontext, "
            "Aufgabe, Ausgabeformat, Restriktionen). Das Modul ist so performant und nützlich konzipiert, dass es als eigenständiges "
            "Produkt oder als Chrome-Extension herausgelöst werden könnte."
        ),
        "elements": [
            ("Katalog & Kategorien-Filter (1.079 Vorlagen)", 
             "Filtert nach Fachdisziplinen wie Strategie, Recht, Coding, Marketing, Datenanalyse und Fabric-Mustern."),
            ("Die 5-Felder-Formel für perfekte Prompts", 
             "• 1. Rolle (Wer agiert?): z. B. 'Senior Compliance Officer'.\n"
             "• 2. Kontext (Was ist die Ausgangslage?): Firmenhintergrund, Stakeholder, Zielgruppe.\n"
             "• 3. Aufgabe (Was exakt ist zu tun?): Präziser Handlungsauftrag im Aktiv.\n"
             "• 4. Format (Wie soll das Ergebnis aussehen?): Tabelle, Markdown-Dossier, JSON-Schema, Executive Summary.\n"
             "• 5. Constraints & Negativ-Regeln (Was darf nicht sein?): Keine Annahmen, deutsches HGB, max. 500 Wörter."),
            ("Live-Preview & Variablen-Injektion", 
             "Rendert den finalen Prompt in Echtzeit während der Eingabe und markiert Platzhalter farblich."),
            ("Aktions-Buttons: 'In Aufgabe übernehmen' & 'In Chat übernehmen'", 
             "Überträgt den fertigen Prompt mit einem einzigen Klick direkt in das Kanban-Taskmodal oder den Agenten-Chat.")
        ],
        "workflow": [
            "1. Klicke im Operations-Board bei '+ Neue Aufgabe' oder im Agenten-Chat auf 'Prompt Studio (1.079)'.",
            "2. Wähle ein Fabric-Muster (z. B. 'extract_wisdom' oder 'write_legal_opinion') oder eine Enterprise-Vorlage.",
            "3. Passe die 5 Felder an deine konkreten Projektdaten an.",
            "4. Klicke auf 'In Aufgabe übernehmen' – der perfekt formatierte Prompt landet sofort im Aufgaben-Formular."
        ],
        "best_practices": (
            "Nutze die 5-Felder-Struktur konsequent bei allen komplexen Delegationen. Die Ergebnisse der Agenten "
            "werden dadurch dramatisch präziser, fehlerfreier und bedürfen kaum manueller Nacharbeit."
        ),
        "starter_prompt": "Öffne das Prompt Studio und zeige mir die 5 besten Vorlagen für die Due-Diligence-Prüfung von Verträgen."
    },
    {
        "id": "css_studio",
        "title": "16. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector",
        "subtitle": "Echtzeit-Design-Studio, In-Place DOM-Inspector & Design-Token Management",
        "concept": (
            "Das Visual CSS Live Studio (Tastenkürzel: Alt + S) ist das Design- und Anpassungszentrum von Archon OS. "
            "Es erlaubt dir, das gesamte Erscheinungsbild der Benutzeroberfläche in Echtzeit direkt im laufenden Betrieb "
            "zu inspizieren, zu vermessen und anzupassen – ohne Neustart, ohne Code-Kompilierung und ohne Neuladen der Seite. "
            "Änderungen an Farben, Schriften, Abständen oder Rahmen werden sofort sichtbar und im Browser persistent gespeichert."
        ),
        "elements": [
            ("In-Place DOM-Inspector (Fadenkreuz-Modus)", 
             "Klicke auf ein beliebiges UI-Element im Bildschirm: Das Studio springt sofort an die entsprechende Stelle im CSS-Baum "
             "und zeigt Padding, Margin, Schriftarten und Farbwerte an."),
            ("Farb- & Typography-Regler", 
             "Schieberegler und Farbwähler für Primärfarben, Akzente, Rahmen-Stärken, Rundungen und Schriftgrößen."),
            ("Theme-Presets & Dark/Light Synchronisation", 
             "Ermöglicht den nahtlosen Wechsel zwischen verschiedenen Farbstimmungen und stellt sicher, dass Kontraste stets WCAG-konform bleiben."),
            ("CSS Export & Reset", 
             "Exportiert deine individuellen Anpassungen als saubere `custom_studio.css` oder setzt auf das offizielle Werksprofil zurück.")
        ],
        "workflow": [
            "1. Drücke zu einem beliebigen Zeitpunkt auf deiner Tastatur die Tastenkombination 'Alt + S' (oder klicke auf das Paletten-Icon links unten).",
            "2. Das CSS Live Studio klappt rechts als elegantes Panel auf.",
            "3. Aktiviere den Inspektor und klicke auf eine Karte oder einen Button, den du anpassen möchtest.",
            "4. Verändere Farbton oder Rundung – die Oberfläche aktualisiert sich im selben Sekundenbruchteil.",
            "5. Schließe das Studio mit erneutem 'Alt + S' – deine Einstellungen bleiben dauerhaft erhalten."
        ],
        "best_practices": (
            "Nutze das CSS Studio, um die Kontraste optimal an deine Lichtverhältnisse am Arbeitsplatz anzupassen. "
            "Über die Export-Funktion kannst du dein Firmen-Farbschema sauber in die Quellcode-Repositorys übernehmen."
        ),
        "starter_prompt": "Öffne das Visual CSS Live Studio und passe die Akzentfarbe der Navigation an."
    }
]

# -------------------------------------------------------------
# 1. SCREENSHOTS PRÜFEN & ZUWEISEN
# -------------------------------------------------------------
print("1. Prüfe / Binde Screenshots ein...")
for v in VIEWS:
    local_img = os.path.join(IMG_DIR, f"{v['id']}.png")
    if os.path.exists(local_img):
        sz_kb = os.path.getsize(local_img) // 1024
        print(f"  ✓ {v['id']} vorhanden ({sz_kb} KB)")
        v["img_path"] = local_img
    else:
        print(f"  ⚠️ {v['id']}.png FEHLT in {IMG_DIR}!")

# -------------------------------------------------------------
# 2. WORD-DOKUMENT INITIALISIEREN & DESIGN KONFIGURIEREN
# -------------------------------------------------------------
print("2. Generiere ausführliches Word-Dokument (ARCHON_OS_SYSTEM_HANDBUCH_2026.docx)...")
doc = Document()

# Seitenränder optimiert für Lesbarkeit und Bildbreite
for section in doc.sections:
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)

# Farbpalette (Professional Slate & Cyber Cyan)
COLOR_PRIMARY = RGBColor(15, 23, 42)       # Slate 900
COLOR_SECONDARY = RGBColor(51, 65, 85)     # Slate 700
COLOR_ACCENT = RGBColor(14, 116, 144)      # Cyan 700
COLOR_MUTED = RGBColor(100, 116, 139)      # Slate 500
COLOR_BORDER_HEX = "CBD5E1"                # Slate 300
COLOR_BOX_BG = "F8FAFC"                   # Slate 50
COLOR_CALLOUT_BG = "F0FDF4"               # Light Green / Slate

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

# --- TITELSEITE ---
title_p = doc.add_paragraph()
title_p.paragraph_format.space_before = Pt(36)
title_p.paragraph_format.space_after = Pt(4)
run_title = title_p.add_run("ARCHON AGENTIC OS 2026")
run_title.font.name = "Calibri"
run_title.font.size = Pt(28)
run_title.font.bold = True
run_title.font.color.rgb = COLOR_PRIMARY

sub_p = doc.add_paragraph()
sub_p.paragraph_format.space_after = Pt(20)
run_sub = sub_p.add_run("Offizielles System-Handbuch, Modul-Referenz & Praxisführer")
run_sub.font.name = "Calibri"
run_sub.font.size = Pt(13)
run_sub.font.bold = True
run_sub.font.color.rgb = COLOR_ACCENT

meta_p = doc.add_paragraph()
meta_p.paragraph_format.space_after = Pt(24)
run_meta = meta_p.add_run("Stand: 14. Oktober 2026 | Release: 2.0 Enterprise | 54 Autonome Spezialisten-Rollen | 16 Fachmodule")
run_meta.font.name = "Calibri"
run_meta.font.size = Pt(9.5)
run_meta.font.color.rgb = COLOR_MUTED

intro_p = doc.add_paragraph()
intro_p.paragraph_format.space_after = Pt(16)
intro_p.paragraph_format.line_spacing = 1.15
intro_run = intro_p.add_run(
    "Dieses System-Handbuch richtet sich an Betreiber, Entscheider und Nutzer des Archon Agentic Operating Systems. "
    "Es vermittelt ein tiefgehendes Verständnis aller 16 Bedienoberflächen und Spezial-Studios und ihrer technologischen Verzahnung. "
    "Ziel dieses Handbuchs ist es, dass jeder Anwender ohne Vorwissen in die Lage versetzt wird, Aufgaben autonom "
    "zu delegieren, Überwachungs- und Freigabeprozesse (HITL) sicher auszuführen und das Zusammenspiel zwischen "
    "Kanban-Board, Obsidian-Wissensbasis, Telegram-Steuerung, Hintergrund-Workflows und Prompt-Studio voll auszuschöpfen."
)
intro_run.font.name = "Calibri"
intro_run.font.size = Pt(11)
intro_run.font.color.rgb = COLOR_SECONDARY

# Inhaltsübersicht als kompakte Tabelle
tbl_toc = doc.add_table(rows=1, cols=2)
tbl_toc.alignment = WD_TABLE_ALIGNMENT.CENTER
cell_l = tbl_toc.cell(0, 0)
cell_r = tbl_toc.cell(0, 1)
set_cell_background(cell_l, "F1F5F9")
set_cell_background(cell_r, "F1F5F9")
set_cell_margins(cell_l, 120, 120, 180, 180)
set_cell_margins(cell_r, 120, 120, 180, 180)

p_l = cell_l.paragraphs[0]
p_l.paragraph_format.space_after = Pt(2)
r_th1 = p_l.add_run("Operative Steuerung & Disposition:\n")
r_th1.font.bold = True
r_th1.font.size = Pt(10)
r_th1.font.color.rgb = COLOR_PRIMARY
p_l.add_run(
    "1. Mission Control (Cockpit & Leitstand)\n"
    "2. Operations (Kanban, Orga & Funk)\n"
    "3. Operations (Organisation & Flowchart)\n"
    "4. Eingang & Triage (HITL & Postfach)\n"
    "5. Agenten-Kader (Profile, Routen & Subtabs)\n"
    "6. Showroom (Projekt-Explorer & Sandbox)\n"
    "7. Zentralbibliothek (RAG, Erfasser & Vault)\n"
    "8. Second Brain (Obsidian Vault & OCR)"
).font.size = Pt(9.5)

p_r = cell_r.paragraphs[0]
p_r.paragraph_format.space_after = Pt(2)
r_th2 = p_r.add_run("Automation, Governance & Studios:\n")
r_th2.font.bold = True
r_th2.font.size = Pt(10)
r_th2.font.color.rgb = COLOR_PRIMARY
p_r.add_run(
    "9. Workflow-Engine (n8n Automation)\n"
    "10. LLM Gateway (OmniRoute AI Router)\n"
    "11. Token Guard (Guardian & Budgets)\n"
    "12. Erweiterungen (Plugin-Zentrale)\n"
    "13. Research Lab (Evidenz-Recherche)\n"
    "14. Telemetrie & Logs (Live-Audit Stream)\n"
    "15. Spezial: Prompt Studio (1.079 Vorlagen)\n"
    "16. Spezial: Visual CSS Live Studio (Alt + S)"
).font.size = Pt(9.5)

doc.add_page_break()

# -------------------------------------------------------------
# VORWORT 1: AUSFÜHRLICHE EINFÜHRUNG (CA. 1 DIN A4 SEITE)
# -------------------------------------------------------------
p_vw1_h = doc.add_paragraph()
p_vw1_h.paragraph_format.space_before = Pt(16)
p_vw1_h.paragraph_format.space_after = Pt(4)
r_vw1_h = p_vw1_h.add_run("1. Vorwort: Was ist Archon OS und wie arbeitet man damit?")
r_vw1_h.font.name = "Calibri"
r_vw1_h.font.size = Pt(18)
r_vw1_h.font.bold = True
r_vw1_h.font.color.rgb = COLOR_PRIMARY

p_vw1_sub = doc.add_paragraph()
p_vw1_sub.paragraph_format.space_after = Pt(14)
r_vw1_sub = p_vw1_sub.add_run("Ein Leitfaden für die autonome Wertschöpfung in vernetzten Organisationen")
r_vw1_sub.font.name = "Calibri"
r_vw1_sub.font.size = Pt(11)
r_vw1_sub.font.italic = True
r_vw1_sub.font.color.rgb = COLOR_ACCENT

p_vw1_body1 = doc.add_paragraph()
p_vw1_body1.paragraph_format.space_after = Pt(10)
p_vw1_body1.paragraph_format.line_spacing = 1.15
r_vw1_b1 = p_vw1_body1.add_run(
    "Wer sich mit Archon OS beschäftigt, blickt nicht auf eine simple Chat-Oberfläche oder ein isoliertes Programmier-Tool. "
    "Archon OS ist ein vollwertiges kognitives Betriebssystem für das moderne Unternehmen. Es verbindet 54 spezialisierte "
    "Fachagenten, autonome Hintergrunddienste (Daemons), deterministische Workflow-Pipelines und strenge Sicherheits-Gatekeeper "
    "zu einer integrierten Arbeitsumgebung. Das erklärte Ziel: Wiederkehrende Grundaufgaben des operativen Alltags vollkommen "
    "selbstständig abzuwickeln, während strategische Großaufträge transparent gesteuert, aufgeteilt und überwacht werden."
)
r_vw1_b1.font.name = "Calibri"
r_vw1_b1.font.size = Pt(10)
r_vw1_b1.font.color.rgb = COLOR_SECONDARY

# Die vier Säulen als strukturierte Box
p_s_h = doc.add_paragraph()
p_s_h.paragraph_format.space_before = Pt(6)
p_s_h.paragraph_format.space_after = Pt(6)
r_sh = p_s_h.add_run("Die vier operativen Säulen des Systems im täglichen Einsatz:")
r_sh.font.name = "Calibri"
r_sh.font.size = Pt(11)
r_sh.font.bold = True
r_sh.font.color.rgb = COLOR_PRIMARY

pillars = [
    ("1. Das mobile Steuerpult (Telegram / Messenger)", 
     "Unterwegs agiert dein Smartphone als Funkgerät. Über persönliche Rufnamen (z. B. '/robert', '/anwalt', '/micha') gibst du "
     "Direktbefehle an einzelne Fachleute oder beauftragst Robert mit umfassenden Projekten. Das System antwortet binnen Sekunden, "
     "schlägt Zwischenschritte vor und spiegelt alle Dialoge zur revisionssicheren Dokumentation synchron in die Zentrale."),
    
    ("2. Der visuelle Leitstand (Web-Browser Cockpit)", 
     "Am Desktop hast du über 16 spezialisierte Ansichten und Studios die volle Kontrolle. Du verfolgst den Lebenszyklus von Aufgaben im "
     "Kanban-Board, überwachst Kosten und Token-Verbrauch in Echtzeit in Mission Control, sichtet E-Mails im Eingang und gibst "
     "kritische Aktionen vor ihrer tatsächlichen Ausführung über das Human-in-the-Loop-Verfahren (HITL) frei."),
    
    ("3. Das physische Langzeitgedächtnis (Obsidian Vault & Second Brain)", 
     "Alle Arbeitsergebnisse, Notizen, Gutachten und Protokolle werden nicht in proprietären Cloud-Silos weggesperrt, sondern "
     "als offene, zukunftssichere Markdown-Dateien direkt auf deiner lokalen Festplatte abgelegt. Du kannst jede Notiz jederzeit "
     "parallel in der nativen Obsidian-Desktop-App bearbeiten. Ein 80-seitiges PDF-Gutachten wird per Auto-OCR in Sekunden erfasst "
     "und steht sofort allen 54 Agenten als Vektor-Wissen zur Verfügung."),
    
    ("4. Der Maschinenraum (Docker & Daemon-Architektur)", 
     "Unter der Haube arbeiten elf robuste Container im Verbund: Der Asyncio-Kernel (Port 8420) koordiniert die Prozesse, der Watchdog "
     "beendet blockierte Tasks, n8n triggert zeitgesteuerte Cron-Workflows, OmniRoute fängt Modell-Ausfälle automatisch per Failover ab, "
     "und der Guardian stellt sicher, dass kein Budget überschritten wird.")
]

for title, desc in pillars:
    p_pil = doc.add_paragraph(style='List Bullet')
    p_pil.paragraph_format.space_before = Pt(2)
    p_pil.paragraph_format.space_after = Pt(4)
    p_pil.paragraph_format.line_spacing = 1.1
    r_pt = p_pil.add_run(f"{title}: ")
    r_pt.font.bold = True
    r_pt.font.size = Pt(9.5)
    r_pt.font.color.rgb = COLOR_PRIMARY
    r_pd = p_pil.add_run(desc)
    r_pd.font.size = Pt(9.5)
    r_pd.font.color.rgb = COLOR_SECONDARY

p_vw1_body2 = doc.add_paragraph()
p_vw1_body2.paragraph_format.space_before = Pt(6)
p_vw1_body2.paragraph_format.space_after = Pt(10)
p_vw1_body2.paragraph_format.line_spacing = 1.15
r_vw1_b2 = p_vw1_body2.add_run(
    "Wie liest man dieses Handbuch?\n"
    "Jedes der 16 Kapitel widmet sich einer dezidierten Bedienoberfläche oder einem Spezial-Studio. Alle Kapitel folgen einer einheitlichen Struktur: "
    "Kernkonzept, Steuerelemente im Detail, Schritt-für-Schritt-Workflow, Praxistipp und konkreter Muster-Prompt. "
    "Komplexe Oberflächen mit mehreren Reitern (wie der Agenten-Kader, Operations oder die Zentralbibliothek) sind in feingliedrige "
    "Unterkapitel unterteilt, jeweils illustriert mit einem hochauflösenden Screenshot des jeweiligen Subtabs. Wer das Zusammenspiel in der "
    "Praxis erleben möchte, findet im Anhang fünf detailliert durchgerechnete Use Cases von der einfachen Rechtsauskunft bis zur 24/7-Hintergrundüberwachung."
)
r_vw1_b2.font.name = "Calibri"
r_vw1_b2.font.size = Pt(10)
r_vw1_b2.font.color.rgb = COLOR_SECONDARY

doc.add_page_break()

# -------------------------------------------------------------
# VORWORT 2: DIE PHILOSOPHISCHE FRAGE (IST DAS EIN OS?)
# -------------------------------------------------------------
p_vw2_h = doc.add_paragraph()
p_vw2_h.paragraph_format.space_before = Pt(16)
p_vw2_h.paragraph_format.space_after = Pt(4)
r_vw2_h = p_vw2_h.add_run("2. Vorwort: Die philosophische Frage: Ist das wirklich ein „OS“?")
r_vw2_h.font.name = "Calibri"
r_vw2_h.font.size = Pt(18)
r_vw2_h.font.bold = True
r_vw2_h.font.color.rgb = COLOR_PRIMARY

p_vw2_sub = doc.add_paragraph()
p_vw2_sub.paragraph_format.space_after = Pt(14)
r_vw2_sub = p_vw2_sub.add_run("Vom einfachen Coding-Assistenten zum kybernetischen Unternehmens-Betriebssystem")
r_vw2_sub.font.name = "Calibri"
r_vw2_sub.font.size = Pt(11)
r_vw2_sub.font.italic = True
r_vw2_sub.font.color.rgb = COLOR_ACCENT

p_vw2_b1 = doc.add_paragraph()
p_vw2_b1.paragraph_format.space_after = Pt(10)
p_vw2_b1.paragraph_format.line_spacing = 1.15
r_vw2_1 = p_vw2_b1.add_run(
    "Die Zweifel sind verständlich, wenn man bei dem Begriff „OS“ primär an Windows, macOS oder Linux denkt – also an Systeme, "
    "die Festplattenblöcke verwalten, Peripheriegeräte per USB ansteuern und reine CPU-Threads takten.\n\n"
    "Gleichzeitig greift die ursprüngliche Bezeichnung „Agent OS for Agentic Coding“ inzwischen viel zu kurz. Das System "
    "schreibt zwar auch Code (über das Research Lab oder Prompts), aber der funktionale Schwerpunkt hat sich längst verschoben: "
    "Sie steuern damit ein virtuelles Unternehmen inklusive Rollenverteilung, Organigramm, Dokumentenerfassung, Mail-Triage und Kommunikationskanälen."
)
r_vw2_1.font.name = "Calibri"
r_vw2_1.font.size = Pt(10)
r_vw2_1.font.color.rgb = COLOR_SECONDARY

# Tabelle: Klassisches OS vs. Archon OS
tbl_comp = doc.add_table(rows=5, cols=3)
tbl_comp.alignment = WD_TABLE_ALIGNMENT.CENTER
headers = ["Klassisches OS (z. B. Linux)", "Archon OS (Ist-Zustand)", "Informatische Einordnung"]

for col_idx, text in enumerate(headers):
    cell = tbl_comp.cell(0, col_idx)
    set_cell_background(cell, "1E293B")
    set_cell_margins(cell, 80, 80, 100, 100)
    p = cell.paragraphs[0]
    r = p.add_run(text)
    r.font.bold = True
    r.font.size = Pt(9.5)
    r.font.color.rgb = RGBColor(255, 255, 255)

comp_rows = [
    ("Prozessmanagement & Scheduler\n(CPU-Zeit zuweisen, Statuszyklen, Task-Killing)",
     "Daemon & Watchdog (Port 8420): Task-Queue, Status (pending -> in_progress -> completed), Watchdog terminiert hängende Prozesse.",
     "1:1 OS-Prinzip"),
    ("Hardware-Abstraktion & Treiber\n(HAL übersetzt Befehle, Treiber steuern Hardware)",
     "OmniRoute & MCP-Server: OmniRoute abstrahiert LLM-Rechenkerne (OpenAI, Anthropic, Google). MCP-Server fungieren als Treiber für Tools, Mail & Web.",
     "1:1 OS-Prinzip"),
    ("Speicher-Hierarchie & Paging\n(L1/L2 Cache, RAM vs. Swap/Disk)",
     "Transiente RAM-Prompts vs. Persistent Storage: Kontextfenster-Kurzzeitgedächtnis, ausgelagert in SQLite (kanban.db), ChromaDB & Obsidian Vault.",
     "1:1 OS-Prinzip"),
    ("IPC & Security\n(Inter-Process-Comms, Ringschutz, User-Rechte)",
     "Telegram/Kanban-Funkverkehr, Guardian Token Guard, HITL-Gatekeeper: Inter-Agenten-Nachrichten und kryptografisch geschützte Freigaben.",
     "1:1 OS-Prinzip")
]

for row_idx, (c1, c2, c3) in enumerate(comp_rows, 1):
    cell_a = tbl_comp.cell(row_idx, 0)
    cell_b = tbl_comp.cell(row_idx, 1)
    cell_c = tbl_comp.cell(row_idx, 2)
    bg = "F8FAFC" if row_idx % 2 == 1 else "FFFFFF"
    for cl in (cell_a, cell_b, cell_c):
        set_cell_background(cl, bg)
        set_cell_margins(cl, 60, 60, 90, 90)
    cell_a.paragraphs[0].add_run(c1).font.size = Pt(9)
    cell_b.paragraphs[0].add_run(c2).font.size = Pt(9)
    r_c = cell_c.paragraphs[0].add_run(c3)
    r_c.font.size = Pt(9)
    r_c.font.bold = True
    r_c.font.color.rgb = COLOR_ACCENT

p_vw2_post = doc.add_paragraph()
p_vw2_post.paragraph_format.space_before = Pt(12)
p_vw2_post.paragraph_format.space_after = Pt(10)
p_vw2_post.paragraph_format.line_spacing = 1.15
r_vw2_post = p_vw2_post.add_run(
    "Wo Archon über ein klassisches OS hinausgeht:\n"
    "Ein traditionelles Betriebssystem hat keine Ahnung vom geschäftlichen Sinn der Software, die darauf ausgeführt wird. "
    "Archon implementiert dagegen eine tiefe organisatorische Semantik:\n"
    "• Personalakten & Rollenverteilung: Agenten sind keine namenlosen Threads, sondern Spezialisten mit definierten Zuständigkeiten (Recht, Steuern, Vertrieb, CEO).\n"
    "• Entscheidungshierarchien: Robert fungiert als Executive Decision Architect, der Aufgaben zerlegt, delegiert und überwacht.\n"
    "• Workflow-Orchestrierung: Aufgaben wandern von der Mail-Inbox über die Guardian-Freigabe ins Kanban-Board.\n\n"
    "Wie man das System präzise nennen kann:\n"
    "1. Agentic Enterprise OS (AEOS): Ein Betriebssystem nicht für einen einzelnen Programmierer, sondern für die operative Steuerung eines autonomen digitalen Unternehmens.\n"
    "2. Autonomous Operations System (AOS): Betont die Abwicklung von Geschäftsprozessen, Hintergrund-Daemons und Multi-Agenten-Koordination.\n"
    "3. Executive Cybernetic System: In Anlehnung an Stafford Beers Viable System Model (Kybernetik zur Unternehmensführung über vernetzte Steuerkreise).\n\n"
    "Fazit: Der Begriff OS ist technisch völlig legitim, weil Prozessverwaltung, Hardware-Abstraktion (Modell-Routing), IPC und Speicherhierarchie "
    "real als Kernel-Dienste laufen. Der Zusatz sollte jedoch nicht mehr „Coding“, sondern „Enterprise“ oder „Operations“ lauten."
)
r_vw2_post.font.name = "Calibri"
r_vw2_post.font.size = Pt(10)
r_vw2_post.font.color.rgb = COLOR_SECONDARY

doc.add_page_break()

# -------------------------------------------------------------
# HAUPTTEILE: DIE 16 ANSICHTEN & STUDIOS IM DETAIL (MIT SUBSECTIONS & SCREENSHOTS)
# -------------------------------------------------------------
for idx, v in enumerate(VIEWS, 1):
    # Kapitel-Überschrift
    h = doc.add_paragraph()
    h.paragraph_format.space_before = Pt(14)
    h.paragraph_format.space_after = Pt(2)
    run_h = h.add_run(v["title"])
    run_h.font.name = "Calibri"
    run_h.font.size = Pt(16)
    run_h.font.bold = True
    run_h.font.color.rgb = COLOR_PRIMARY

    # Untertitel
    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(10)
    run_s = sub.add_run(v["subtitle"])
    run_s.font.name = "Calibri"
    run_s.font.size = Pt(10.5)
    run_s.font.italic = True
    run_s.font.color.rgb = COLOR_ACCENT

    # Haupt-Screenshot einbetten (falls vorhanden)
    if os.path.exists(v.get("img_path", "")):
        try:
            p_img = doc.add_paragraph()
            p_img.paragraph_format.space_before = Pt(2)
            p_img.paragraph_format.space_after = Pt(8)
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.add_picture(v["img_path"], width=Inches(6.7))
        except Exception as e_img:
            print(f"Fehler beim Einbetten von {v['id']}: {e_img}")

    # 1. Kernkonzept & Architektur
    p_conc = doc.add_paragraph()
    p_conc.paragraph_format.space_before = Pt(6)
    p_conc.paragraph_format.space_after = Pt(6)
    p_conc.paragraph_format.line_spacing = 1.15
    r_conc_lbl = p_conc.add_run("Kernkonzept & Architektur:\n")
    r_conc_lbl.font.name = "Calibri"
    r_conc_lbl.font.size = Pt(11)
    r_conc_lbl.font.bold = True
    r_conc_lbl.font.color.rgb = COLOR_PRIMARY
    r_conc_text = p_conc.add_run(v["concept"])
    r_conc_text.font.name = "Calibri"
    r_conc_text.font.size = Pt(10)
    r_conc_text.font.color.rgb = COLOR_SECONDARY

    # 2. Schlüsselelemente & Bedienung im Detail
    p_elem_h = doc.add_paragraph()
    p_elem_h.paragraph_format.space_before = Pt(6)
    p_elem_h.paragraph_format.space_after = Pt(4)
    r_eh = p_elem_h.add_run("Die wichtigsten Steuerelemente & Bereiche im Überblick:")
    r_eh.font.name = "Calibri"
    r_eh.font.size = Pt(11)
    r_eh.font.bold = True
    r_eh.font.color.rgb = COLOR_PRIMARY

    for title, desc in v["elements"]:
        p_el = doc.add_paragraph(style='List Bullet')
        p_el.paragraph_format.space_before = Pt(2)
        p_el.paragraph_format.space_after = Pt(4)
        p_el.paragraph_format.line_spacing = 1.1
        r_et = p_el.add_run(f"{title}: ")
        r_et.font.bold = True
        r_et.font.size = Pt(9.5)
        r_et.font.color.rgb = COLOR_PRIMARY
        r_ed = p_el.add_run(desc)
        r_ed.font.size = Pt(9.5)
        r_ed.font.color.rgb = COLOR_SECONDARY

    # WENN SUBSECTIONS VORHANDEN SIND: RENDERE JEDES SUBKAPITEL MIT EIGENEM SCREENSHOT!
    if "subsections" in v:
        p_sub_intro = doc.add_paragraph()
        p_sub_intro.paragraph_format.space_before = Pt(10)
        p_sub_intro.paragraph_format.space_after = Pt(4)
        r_si = p_sub_intro.add_run("Detaillierte Analyse der Unterbereiche & Funktionen:")
        r_si.font.name = "Calibri"
        r_si.font.size = Pt(12)
        r_si.font.bold = True
        r_si.font.color.rgb = COLOR_ACCENT

        for sub_sec in v["subsections"]:
            p_stitle = doc.add_paragraph()
            p_stitle.paragraph_format.space_before = Pt(10)
            p_stitle.paragraph_format.space_after = Pt(2)
            r_st = p_stitle.add_run(sub_sec["subtitle"])
            r_st.font.name = "Calibri"
            r_st.font.size = Pt(12)
            r_st.font.bold = True
            r_st.font.color.rgb = COLOR_PRIMARY

            # Sub-Screenshot einbetten (falls für diesen Subtab vorhanden)
            sub_img_id = sub_sec.get("img_id", "")
            if sub_img_id:
                sub_img_path = os.path.join(IMG_DIR, f"{sub_img_id}.png")
                if os.path.exists(sub_img_path):
                    try:
                        p_simg = doc.add_paragraph()
                        p_simg.paragraph_format.space_before = Pt(2)
                        p_simg.paragraph_format.space_after = Pt(6)
                        p_simg.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        doc.add_picture(sub_img_path, width=Inches(6.4))
                    except Exception as e_simg:
                        print(f"Fehler beim Einbetten von Sub-Screenshot {sub_img_id}: {e_simg}")

            p_sconc = doc.add_paragraph()
            p_sconc.paragraph_format.space_after = Pt(4)
            p_sconc.paragraph_format.line_spacing = 1.1
            r_sc = p_sconc.add_run(sub_sec["concept"])
            r_sc.font.name = "Calibri"
            r_sc.font.size = Pt(9.5)
            r_sc.font.color.rgb = COLOR_SECONDARY

            for e_title, e_desc in sub_sec.get("elements", []):
                p_se = doc.add_paragraph(style='List Bullet')
                p_se.paragraph_format.space_before = Pt(1)
                p_se.paragraph_format.space_after = Pt(2)
                r_set = p_se.add_run(f"• {e_title}: ")
                r_set.font.bold = True
                r_set.font.size = Pt(9)
                r_sed = p_se.add_run(e_desc)
                r_sed.font.size = Pt(9)
                r_sed.font.color.rgb = COLOR_SECONDARY

            if "workflow" in sub_sec:
                p_swf = doc.add_paragraph()
                p_swf.paragraph_format.space_before = Pt(2)
                p_swf.paragraph_format.space_after = Pt(2)
                r_swfl = p_swf.add_run("Arbeitsablauf: ")
                r_swfl.font.bold = True
                r_swfl.font.size = Pt(9)
                r_swfl.font.color.rgb = COLOR_PRIMARY
                r_swft = p_swf.add_run(" ➔ ".join(sub_sec["workflow"]))
                r_swft.font.size = Pt(9)
                r_swft.font.color.rgb = COLOR_SECONDARY

            if "tip" in sub_sec:
                p_stip = doc.add_paragraph()
                p_stip.paragraph_format.space_before = Pt(2)
                p_stip.paragraph_format.space_after = Pt(4)
                r_stl = p_stip.add_run("Praxistipp: ")
                r_stl.font.bold = True
                r_stl.font.size = Pt(9)
                r_stl.font.color.rgb = COLOR_ACCENT
                r_stt = p_stip.add_run(sub_sec["tip"])
                r_stt.font.size = Pt(9)
                r_stt.font.color.rgb = COLOR_SECONDARY

    # 3. Praxis-Workflow Schritt für Schritt
    p_wf_h = doc.add_paragraph()
    p_wf_h.paragraph_format.space_before = Pt(6)
    p_wf_h.paragraph_format.space_after = Pt(4)
    r_wfh = p_wf_h.add_run("Praxis-Workflow (Schritt für Schritt):")
    r_wfh.font.name = "Calibri"
    r_wfh.font.size = Pt(11)
    r_wfh.font.bold = True
    r_wfh.font.color.rgb = COLOR_PRIMARY

    for step in v["workflow"]:
        p_step = doc.add_paragraph()
        p_step.paragraph_format.space_before = Pt(1)
        p_step.paragraph_format.space_after = Pt(3)
        p_step.paragraph_format.line_spacing = 1.1
        r_step = p_step.add_run(step)
        r_step.font.name = "Calibri"
        r_step.font.size = Pt(9.5)
        r_step.font.color.rgb = COLOR_SECONDARY

    # 4. Wichtige Hinweise & Best Practices
    p_bp = doc.add_paragraph()
    p_bp.paragraph_format.space_before = Pt(6)
    p_bp.paragraph_format.space_after = Pt(8)
    p_bp.paragraph_format.line_spacing = 1.1
    r_bplbl = p_bp.add_run("💡 Praxistipp & Leitplanke: ")
    r_bplbl.font.name = "Calibri"
    r_bplbl.font.bold = True
    r_bplbl.font.size = Pt(9.5)
    r_bplbl.font.color.rgb = COLOR_ACCENT
    r_bptext = p_bp.add_run(v["best_practices"])
    r_bptext.font.name = "Calibri"
    r_bptext.font.size = Pt(9.5)
    r_bptext.font.color.rgb = COLOR_SECONDARY

    # 5. Einstiegs-Prompt Infobox
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, COLOR_BOX_BG)
    set_cell_margins(cell, 100, 100, 150, 150)
    cell_p = cell.paragraphs[0]
    cell_p.paragraph_format.space_before = Pt(4)
    cell_p.paragraph_format.space_after = Pt(4)
    r_box_title = cell_p.add_run("🤖 Beispiel-Befehl / Prompt an den Assistenten für diesen Bereich:\n")
    r_box_title.font.name = "Calibri"
    r_box_title.font.bold = True
    r_box_title.font.size = Pt(9.5)
    r_box_title.font.color.rgb = COLOR_ACCENT
    r_prompt = cell_p.add_run(f'"{v["starter_prompt"]}"')
    r_prompt.font.name = "Calibri"
    r_prompt.font.italic = True
    r_prompt.font.size = Pt(9.5)
    r_prompt.font.color.rgb = COLOR_PRIMARY

    # Abstand & Seitenumbruch
    doc.add_paragraph().paragraph_format.space_after = Pt(10)
    doc.add_page_break()

# -------------------------------------------------------------
# ANHANG: 5 PRAXIS-USE-CASES (VON EINFACH BIS HOCHKOMPLEX)
# -------------------------------------------------------------
p_app_h = doc.add_paragraph()
p_app_h.paragraph_format.space_before = Pt(20)
p_app_h.paragraph_format.space_after = Pt(4)
r_app_h = p_app_h.add_run("ANHANG: 5 PRAXIS-USE-CASES")
r_app_h.font.name = "Calibri"
r_app_h.font.size = Pt(20)
r_app_h.font.bold = True
r_app_h.font.color.rgb = COLOR_PRIMARY

p_app_sub = doc.add_paragraph()
p_app_sub.paragraph_format.space_after = Pt(16)
r_app_sub = p_app_sub.add_run("Schritt-für-Schritt Einsatzszenarien für den operativen Unternehmensalltag")
r_app_sub.font.name = "Calibri"
r_app_sub.font.size = Pt(12)
r_app_sub.font.italic = True
r_app_sub.font.color.rgb = COLOR_ACCENT

p_app_intro = doc.add_paragraph()
p_app_intro.paragraph_format.space_after = Pt(16)
p_app_intro.paragraph_format.line_spacing = 1.15
r_app_in = p_app_intro.add_run(
    "Die folgenden fünf Anwendungsfälle demonstrieren das Zusammenspiel der Systemmodule in der täglichen Praxis. "
    "Sie sind bewusst nach steigendem Komplexitätsgrad gestaffelt: von der sekundenschnellen Ad-hoc-Auskunft via "
    "Telegram-Rufname über teilautonome Workflows mit Freigabepflicht bis zur vollautonomen 24/7-Hintergrundüberwachung."
)
r_app_in.font.name = "Calibri"
r_app_in.font.size = Pt(10.5)
r_app_in.font.color.rgb = COLOR_SECONDARY

USE_CASES = [
    {
        "num": "Use Case 1",
        "level": "Komplexitätsstufe 1: Gering (Ad-hoc Direktdialog)",
        "title": "Telegram-Direktansprache über persönliche Rufnamen (/anwalt, /robert)",
        "scenario": (
            "Du bist unterwegs und benötigst ohne Zeitverzug eine rechtliche Ersteinschätzung, eine Definition oder den aktuellen "
            "Systemstatus. Du möchtest keinen formalen Task im Kanban anlegen, sondern direkt per Smartphone-Chat eine fundierte Antwort erhalten."
        ),
        "steps": [
            "1. Du öffnest die Telegram-App auf deinem Smartphone und startest den Chat mit deinem Bot (@Beatman_bot).",
            "2. Du sendest den Befehl mit dem hinterlegten Rufnamen des gewünschten Agenten: '/anwalt Müssen Überstunden laut aktuellem Arbeitsrecht zwingend erfasst werden?'.",
            "3. Das Telegram-Gateway von Archon OS erkennt das Präfix '/anwalt', schlägt im Agenten-Kader nach und leitet die Nachricht sofort an Dr. Maximilian von W. (Wirtschaftsjurist) weiter.",
            "4. Der juristische Fach-Agent greift auf sein Rollenprofil und das hinterlegte Modell (OmniRoute auto/best-free) zu, formuliert die Auskunft und sendet sie innerhalb von 3 Sekunden direkt in deinen Telegram-Chat.",
            "5. Der Dialog wird synchron im Dashboard unter 'Eingang & Triage' (Spalte 3: Telegram Stream) zur lückenlosen Dokumentation gespiegelt."
        ],
        "modules": "Telegram Bot (@Beatman_bot) ➔ Rufnamen-Router ➔ Fach-Agent (Hermes) ➔ OmniRoute AI Gateway ➔ Eingang (Triage Stream)",
        "command": "/anwalt Müssen Überstunden laut aktuellem Arbeitsrecht zwingend erfasst werden?",
        "tip": "Ideal für schnelle Auskünfte ohne bürokratischen Vorlauf. Der Rufname umgeht jegliche Umwege und spart das manuelle Anlegen von Task-Karten."
    },
    {
        "num": "Use Case 2",
        "level": "Komplexitätsstufe 2: Mittel (E-Mail Triage & HITL-Freigabe)",
        "title": "Eingehende Partner-E-Mail: Triage, Antwortentwurf & Human-in-the-Loop Freigabe",
        "scenario": (
            "Eine geschäftliche E-Mail mit einer Kooperationsanfrage geht im Firmenpostfach ein. Ein Fachagent soll einen passenden "
            "Antwortentwurf vorbereiten, der jedoch aus Sicherheitsgründen keinesfalls blind versendet werden darf, sondern deiner Freigabe bedarf."
        ),
        "steps": [
            "1. Das E-Mail-Postfach synchronisiert alle 180 Sekunden über IMAP; die neue Mail erscheint in 'Eingang & Triage' (Spalte 2: E-Mail Postfach).",
            "2. Das Plugin 'Email Guard' scannt den E-Mail-Text vollautomatisch auf bösartige Prompt-Injections und Phishing-Muster.",
            "3. Du sichtest die Mail im Eingang und delegierst sie per Klick an Katharina Völker (Lead Go-to-Market).",
            "4. Die Agentin formuliert unter Einbeziehung von Unternehmensleitlinien aus der Zentralbibliothek einen professionellen Antwortentwurf.",
            "5. Da der E-Mail-Versand eine externe Schreibaktion darstellt, blockiert der Human-in-the-Loop (HITL) Wächter den Versand: Im Eingang erscheint eine gelb markierte Freigabekarte.",
            "6. Du liest den Entwurf kurz gegen, nimmst bei Bedarf eine kleine Textanpassung vor und klickst auf 'Freigeben' – erst jetzt geht die E-Mail über SMTP physisch an den Absender raus."
        ],
        "modules": "Eingang & Triage (IMAP/SMTP) ➔ Email-Guard Plugin ➔ Hermes Agent ➔ Zentralbibliothek (RAG) ➔ HITL-Approval Gate",
        "command": "Analysiere die jüngste Kooperations-E-Mail im Eingang und erstelle einen passenden Antwortentwurf für meine Freigabe.",
        "tip": "Das HITL-Gate schützt dich davor, dass Agenten unkontrolliert oder voreilig E-Mails an echte Kunden oder Partner versenden."
    },
    {
        "num": "Use Case 3",
        "level": "Komplexitätsstufe 3: Gehoben (Wissens-Ingestion & OCR)",
        "title": "Wissensaufbau: 80-seitiges PDF-Gutachten per Auto-OCR ins Second Brain & RAG",
        "scenario": (
            "Du erhältst ein neues technisches Gutachten oder einen Bebauungsplan als 80-seitiges PDF. Du möchtest, dass alle 54 Agenten "
            "dieses Spezialwissen sofort beherrschen, ohne dass du ihnen die Fakten jedes Mal manuell in den Prompt kopieren musst."
        ),
        "steps": [
            "1. Du öffnest die Ansicht 'Zentralbibliothek' (Sub-Tab: Dokumenten-Erfasser) und ziehst das PDF per Drag & Drop in den Upload-Bereich.",
            "2. Die integrierte Auto-OCR-Pipeline (Docling) extrahiert vollautomatisch Fließtexte, Tabellen und Überschriften und übersetzt sie in sauberes Markdown.",
            "3. Das formatierte Dokument wird direkt im Ordner '02_Wissensbibliothek' deines lokalen Obsidian-Vaults auf der Festplatte abgelegt.",
            "4. Parallel dazu segmentiert der Ingestions-Dienst die Datei in logische Chunks und berechnet Vektor-Embeddings für den RAG-Index der Zentralbibliothek.",
            "5. Du wechselst in den Sub-Tab 'Obsidian Vault' – der integrierte Markdown-Viewer zeigt die formatierte Notiz sofort an.",
            "6. Stellt ein Nutzer künftig eine Frage zu diesem Bauprojekt, ruft der zuständige Agent (z. B. Bobby Brown, Bauleitung) die Fakten zielgenau per Vektorsuche ab."
        ],
        "modules": "Zentralbibliothek (Dokumenten-Erfasser) ➔ Auto-OCR Pipeline (Docling) ➔ Markdown-Konverter ➔ AnythingLLM (RAG) ➔ Obsidian Vault",
        "command": "Extrahiere die Kernaussagen des neu erfassten Gutachtens in 02_Wissensbibliothek und liste alle relevanten Baugrenzen auf.",
        "tip": "Durch die Ablage im lokalen Obsidian-Vault hast du alle Daten dauerhaft als offenes Markdown auf deiner eigenen Festplatte gesichert."
    },
    {
        "num": "Use Case 4",
        "level": "Komplexitätsstufe 4: Hoch (Autonome Projekt-Delegation)",
        "title": "Strategische Projektentwicklung: Delegation durch Robert (CEO), Research Lab & Kanban",
        "scenario": (
            "Ein komplexer Großauftrag soll erarbeitet werden: 'Standort- und Baurechtsanalyse Münster für modulares Bauen'. "
            "Die Aufgabe erfordert Webrecherche, juristische Prüfung und bautechnische Kalkulation."
        ),
        "steps": [
            "1. Du sendest Robert via Telegram den Befehl: '/robert Erstelle eine vollumfängliche Standort- und Baurechtsanalyse Münster für modulares Bauen'.",
            "2. Robert (Executive Decision Architect) nimmt die Gesamtaufgabe entgegen und zerlegt sie im Operations-Board in 3 Teilaufgaben:\n"
            "   • Teilaufgabe A an das Research Lab: Recherche von Marktdaten, Mietniveaus und Grundstückspreisen in Münster.\n"
            "   • Teilaufgabe B an Dr. Maximilian von W.: Juristische Prüfung von Bebauungsplan-Vorgaben und Genehmigungspfaden.\n"
            "   • Teilaufgabe C an Bobby Brown (Bauleiter): Analyse modularer Bauweisen und Schnittstellenkalkulation.",
            "3. Im Operations-Board wandern alle drei Teilkarten von 'To-Do' in 'In Bearbeitung'. Das WIP-Limit verhindert Systemüberlastung.",
            "4. Das Research Lab führt Evidenz-Triangulation durch und speichert Zwischenanalysen im Showroom.",
            "5. Robert führt alle Zulieferungen zusammen, erstellt ein mehrseitiges Gesamtdossier im Showroom und schiebt den Task auf 'Review & QA'.",
            "6. Du erhältst eine Benachrichtigung auf Telegram, öffnest die Task-Karte und begutachtest das fertige Endprodukt über den Button 'In Obsidian öffnen'."
        ],
        "modules": "Telegram Bot ➔ Robert (CEO) ➔ Operations-Kanban (WIP-Limits) ➔ Research Lab ➔ Fach-Leads ➔ Showroom ➔ Obsidian Vault",
        "command": "/robert Erstelle eine strukturierte Standort- und Baurechtsanalyse Münster für modulares Bauen inklusive rechtlicher Prüfung.",
        "tip": "Robert fungiert als dein digitaler Geschäftsführer: Er entlastet dich vollständig von der manuellen Koordination einzelner Fach-Spezialisten."
    },
    {
        "num": "Use Case 5",
        "level": "Komplexitätsstufe 5: Sehr hoch (24/7 Automation & Failover)",
        "title": "Vollautonome Hintergrundüberwachung, OmniRoute-Failover & Notfall-Eskalation",
        "scenario": (
            "Archon OS soll rund um die Uhr im Hintergrund arbeiten, Branchenausschreibungen scannen, externe API-Ausfälle selbstständig "
            "abfangen und im Falle von Endlosschleifen oder Störungen kontrolliert an dich eskalieren."
        ),
        "steps": [
            "1. Die n8n Workflow-Engine triggert jeden Werktag um 06:30 Uhr über einen Cron-Knoten einen autonomen Scan-Workflow.",
            "2. Ein Recherche-Agent scannt definierte Branchenportale und Portale nach neuen Ausschreibungen im Bereich Modulbau.",
            "3. Mitten im Suchlauf fällt der primäre LLM-Anbieter aus (Rate-Limit / HTTP 429).",
            "4. Das OmniRoute Gateway erkennt den Ausfall binnen 180 ms, wechselt unterbrechungsfrei auf das hinterlegte Fallback-Modell und setzt den Lauf fort.",
            "5. Sollte ein fehlerhafter Tool-Aufruf in eine Endlosschleife geraten, greift nach exakt 15 Schritten der Guardian-Schleifenkiller: Er stoppt den Prozess hart, setzt den Task auf 'Blockiert / Eskalation' und alarmiert Robert.",
            "6. Robert fasst den Vorfall zusammen und sendet dir eine Notfall-Meldung per Telegram-Push. Im Telemetrie-Log-Stream ist der Vorfall sekundengenau mit kryptografischer Hash-Kette dokumentiert."
        ],
        "modules": "n8n Workflow-Engine (Cron) ➔ OmniRoute AI Gateway (Failover) ➔ Guardian (Schleifenschutz) ➔ Operations-Kanban ➔ Telegram-Push ➔ Log-Audit",
        "command": "Richte in n8n einen täglichen Workflow ein, der um 06:30 Uhr Ausschreibungen scannt und bei Fehlern an Robert eskaliert.",
        "tip": "Dank OmniRoute-Failover und Guardian-Schleifenschutz läuft dein System auch dann stabil und budgetsicher weiter, wenn externe KI-Server ausfallen."
    }
]

for uc in USE_CASES:
    p_uc_title = doc.add_paragraph()
    p_uc_title.paragraph_format.space_before = Pt(14)
    p_uc_title.paragraph_format.space_after = Pt(2)
    r_uc_t = p_uc_title.add_run(f"{uc['num']}: {uc['title']}")
    r_uc_t.font.name = "Calibri"
    r_uc_t.font.size = Pt(14)
    r_uc_t.font.bold = True
    r_uc_t.font.color.rgb = COLOR_PRIMARY

    p_uc_lvl = doc.add_paragraph()
    p_uc_lvl.paragraph_format.space_after = Pt(8)
    r_uc_l = p_uc_lvl.add_run(f"⚡ {uc['level']}")
    r_uc_l.font.name = "Calibri"
    r_uc_l.font.size = Pt(10)
    r_uc_l.font.bold = True
    r_uc_l.font.color.rgb = COLOR_ACCENT

    p_scen = doc.add_paragraph()
    p_scen.paragraph_format.space_before = Pt(2)
    p_scen.paragraph_format.space_after = Pt(6)
    p_scen.paragraph_format.line_spacing = 1.15
    r_scen_lbl = p_scen.add_run("Ausgangslage & Zielsetzung:\n")
    r_scen_lbl.font.bold = True
    r_scen_lbl.font.size = Pt(10)
    r_scen_lbl.font.color.rgb = COLOR_PRIMARY
    r_scen_t = p_scen.add_run(uc["scenario"])
    r_scen_t.font.size = Pt(9.5)
    r_scen_t.font.color.rgb = COLOR_SECONDARY

    p_flow_lbl = doc.add_paragraph()
    p_flow_lbl.paragraph_format.space_before = Pt(4)
    p_flow_lbl.paragraph_format.space_after = Pt(4)
    r_fl = p_flow_lbl.add_run("Ablauf im System (Schritt für Schritt):")
    r_fl.font.bold = True
    r_fl.font.size = Pt(10)
    r_fl.font.color.rgb = COLOR_PRIMARY

    for step in uc["steps"]:
        p_st = doc.add_paragraph()
        p_st.paragraph_format.space_before = Pt(1)
        p_st.paragraph_format.space_after = Pt(3)
        p_st.paragraph_format.line_spacing = 1.1
        r_st = p_st.add_run(step)
        r_st.font.size = Pt(9.5)
        r_st.font.color.rgb = COLOR_SECONDARY

    p_mod = doc.add_paragraph()
    p_mod.paragraph_format.space_before = Pt(4)
    p_mod.paragraph_format.space_after = Pt(4)
    r_mod_lbl = p_mod.add_run("Beteiligte System-Module: ")
    r_mod_lbl.font.bold = True
    r_mod_lbl.font.size = Pt(9.5)
    r_mod_lbl.font.color.rgb = COLOR_PRIMARY
    r_mod_t = p_mod.add_run(uc["modules"])
    r_mod_t.font.size = Pt(9.5)
    r_mod_t.font.color.rgb = COLOR_ACCENT

    # Box für Befehl & Tipp
    tbl_uc = doc.add_table(rows=1, cols=1)
    tbl_uc.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell_uc = tbl_uc.cell(0, 0)
    set_cell_background(cell_uc, COLOR_BOX_BG)
    set_cell_margins(cell_uc, 80, 80, 140, 140)
    p_box = cell_uc.paragraphs[0]
    p_box.paragraph_format.space_before = Pt(4)
    p_box.paragraph_format.space_after = Pt(4)
    r_cmd_lbl = p_box.add_run("Muster-Befehl / Telegram-Kommando:\n")
    r_cmd_lbl.font.bold = True
    r_cmd_lbl.font.size = Pt(9)
    r_cmd_lbl.font.color.rgb = COLOR_ACCENT
    r_cmd = p_box.add_run(f'"{uc["command"]}"\n\n')
    r_cmd.font.italic = True
    r_cmd.font.size = Pt(9.5)
    r_cmd.font.color.rgb = COLOR_PRIMARY
    r_tip_lbl = p_box.add_run("💡 Praxistipp: ")
    r_tip_lbl.font.bold = True
    r_tip_lbl.font.size = Pt(9)
    r_tip_lbl.font.color.rgb = COLOR_ACCENT
    r_tip = p_box.add_run(uc["tip"])
    r_tip.font.size = Pt(9)
    r_tip.font.color.rgb = COLOR_SECONDARY

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

# --- MEHRFACH-SPEICHERUNG (SICHER GEGEN WORD-SPERREN) ---
targets = [
    DOCX_PATH,
    os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026_v2.docx"),
    os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026_v3.docx"),
    os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026_v4.docx"),
    os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026_v5.docx")
]

saved_files = []
for t in targets:
    try:
        doc.save(t)
        saved_files.append(t)
        print(f"✓ Erfolgreich gespeichert: {t}")
    except Exception as e:
        print(f"⚠️ Übersprungen (gesperrt oder Schreibfehler): {t} ({e})")

print(f"3. Handbuch-Generierung abgeschlossen. Gespeicherte Versionen: {len(saved_files)}")
