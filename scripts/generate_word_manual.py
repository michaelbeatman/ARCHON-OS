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
# DETAILLIERTE DATENSTRUKTUR FÜR ALLE 14 SYSTEM-ANSICHTEN
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
             "• Flottenlast: Zeigt die Anzahl gleichzeitig arbeitender Agenten im Verhältnis zum Gesamt-Kader (z. B. 0 / 56 aktiv).\n"
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
        "title": "2. Operations – Kanban Board & Task-Engine",
        "subtitle": "Operative Steuerung, Aufgaben-Delegation, WIP-Limits & Obsidian-Verknüpfung",
        "concept": (
            "Das Operations-Kanban ist das schlagende Herz der operativen Ausführung in Archon OS. Jede geschäftliche Aufgabe "
            "wird hier als strukturierte Karte erfasst, einem Agenten zugewiesen und durch einen definierten Lebenszyklus geführt. "
            "Die Ansicht unterstützt flexible Filter, WIP-Limits (Work-in-Progress) gegen Überlastung und eine direkte Anbindung an Obsidian."
        ),
        "elements": [
            ("Die 5 Kanban-Spalten", 
             "• TO-DO: Warteschlange neuer oder delegierter Aufgaben vor Bearbeitungsbeginn.\n"
             "• IN BEARBEITUNG: Aufgaben, an denen ein Agent aktuell autonom arbeitet und Prompts/Tools ausführt.\n"
             "• REVIEW & QA: Fertiggestellte Entwürfe, die auf inhaltliche Prüfung oder deine Freigabe warten.\n"
             "• BLOCKIERT / ESKALATION: Aufgaben mit fehlenden Informationen, Rechten oder Tool-Fehlern (Eskalation zu Robert).\n"
             "• ABGESCHLOSSEN: Erfolgreich fertiggestellte Arbeiten inklusive Ablage der Ergebnisse im Vault."),
            ("Such- & Filter-Toolbar", 
             "Ermöglicht Volltextsuche nach Begriffen oder Task-IDs, Filterung nach verantwortlichem Agenten sowie Filterung nach Prioritätsstufen "
             "(P0 Kritisch bis P3 Normal). Über das Sortier-Menü sortierst du nach Priorität, Datum oder Titel."),
            ("WIP-Limit Steuerung (Work in Progress)", 
             "Direkt in der Toolbar konfigurierbar: Begrenze für jede Spalte die maximale Anzahl paralleler Aufgaben (z. B. max. 3 in Bearbeitung), "
             "um Agenten-Überlastung und Token-Spitzen zuverlässig zu verhindern."),
            ("Button '+ Neue Aufgabe'", 
             "Öffnet das Aufgaben-Erstellungsmodal. Hier definierst du Titel, ausführende Rolle, Priorität, ausführliche Instruktionen "
             "und optionale Zieldateien."),
            ("Archiv-Funktion (Toolbar rechts)", 
             "Verschiebt erledigte Karten per Klick in das historische Archiv, um das Board übersichtlich und reaktionsschnell zu halten.")
        ],
        "workflow": [
            "1. Klicke auf '+ Neue Aufgabe', wähle einen passenden Fachagenten (z. B. Wirtschaftsjurist) und formuliere den Auftrag.",
            "2. Verfolge auf dem Board, wie die Karte von 'To-Do' in 'In Bearbeitung' wechselt.",
            "3. Landet die Karte in 'Review & QA', öffne sie mit einem Klick: Du siehst das Zwischenergebnis und kannst es direkt über den Button 'In Obsidian öffnen' lokal begutachten.",
            "4. Ist das Ergebnis zufriedenstellend, ziehe die Karte auf 'Abgeschlossen' oder klicke auf 'Archivieren'."
        ],
        "best_practices": (
            "Setze realistische WIP-Limits (z. B. 2 bis 3 Tasks gleichzeitig). Sollte ein Task auf 'Blockiert' springen, prüfe im Task-Detail "
            "die Fehlermeldung – oft fehlt eine Datei oder ein API-Schlüssel."
        ),
        "starter_prompt": "Erstelle einen neuen Task im Operations-Board mit Priorität P1 für den Wirtschaftsjuristen zur Prüfung eines Dienstleistervertrags."
    },
    {
        "id": "org",
        "title": "3. Operations – Organisation & Ablaufdiagramm",
        "subtitle": "Interaktiver 2D-Hierarchiebaum, Berichtslinien & dynamische Umhängung",
        "concept": (
            "Dieser Sub-Tab innerhalb von Operations visualisiert die Aufbau- und Ablaufstruktur deines Unternehmens als lebendigen 2D-Graphen. "
            "Hier wird die unternehmerische Kaskade sichtbar: von der Eigentümer- und Bot-Ebene über Robert (CEO) bis zu den Fach-Leads und Spezialisten. "
            "Verbindungslinien stellen echte Weisungs- und Berichtswege dar, die das System für autonome Eskalationen nutzt."
        ),
        "elements": [
            ("Apex-Ebene (Ganz oben)", 
             "Repräsentiert die Systemspitze mit dem Default Orchestrator, dem Telegram-Bot-Gateway und Michael Keller (Master of the Universe)."),
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
        "title": "4. Eingang & Triage (Intake)",
        "subtitle": "Operative Triage: HITL-Freigabeprozess, E-Mail-Postfach & Telegram-Stream",
        "concept": (
            "Die Eingangszentrale ist die sichere Schnittstelle zwischen der Außenwelt und deinen Agenten. Alle eingehenden Signale – "
            "seien es Systemwarnungen, externe E-Mails oder Telegram-Nachrichten – laufen hier zusammen. Gleichzeitig dient diese Ansicht "
            "als Kontrollschleuse für den Human-in-the-Loop-Mechanismus (HITL), der riskante Aktionen vor der Ausführung stoppt."
        ),
        "elements": [
            ("Spalte 1: INTERN & SYSTEM", 
             "Dokumentiert Kernel-Statusmeldungen (Tickless Kernel Sleep aktiv, Port 8501 bereit), automatische Health-Checks "
             "und Systemhinweise in chronologischer Reihenfolge."),
            ("Spalte 2: E-MAIL POSTFACH (IMAP/SMTP)", 
             "Echtzeit-Synchronisierung mit deinem Postfach (archon.os.system@gmail.com, 180s Taktung). Zeigt Betreff, Absender und Inhalt. "
             "Erlaubt es, eingehende Nachrichten per Klick einem Agenten zur Analyse oder Beantwortung zuzuweisen."),
            ("Spalte 3: TELEGRAM STREAM", 
             "Live-Feed aller Konversationen über deinen Bot (@Beatman_bot). Jede Frage, jeder Befehl und die Antworten der Agenten "
             "werden hier in Echtzeit gespiegelt."),
            ("Triage- & Filterleiste (Oben)", 
             "Filtert die Ansicht nach Kategorien: Alle, Intern, E-Mail, Telegram. Über den Button 'Sync' wird eine sofortige "
             "Postfach-Abfrage manuell forciert."),
            ("Human-in-the-Loop (HITL) Freigabekarten", 
             "Plant ein Agent eine Schreibaktion (E-Mail versenden, Code pushen, Datei löschen), erscheint hier eine gelb markierte Freigabekarte. "
             "Erst wenn du auf 'Freigeben' klickst, wird die Aktion physisch ausgeführt.")
        ],
        "workflow": [
            "1. Sichte im E-Mail-Postfach eingehende Nachrichten von Kunden oder Partnern.",
            "2. Klicke auf eine Nachricht, um sie direkt an den passenden Agenten (z. B. Support oder Akquise) zu übergeben.",
            "3. Prüfe vor dem endgültigen Versand den generierten Antwortentwurf in der HITL-Freigabekarte und bestätige mit 'Freigeben'."
        ],
        "best_practices": (
            "Prüfe regelmäßig die HITL-Karten. Der Injektions- und E-Mail-Schutz verhindert verlässlich, dass schädliche Prompts aus eingehenden "
            "Mails unbemerkt Aktionen auf deinem System ausführen."
        ),
        "starter_prompt": "Welche neuen E-Mails sind im Eingang eingegangen und für welche liegt bereits ein Antwortentwurf vor?"
    },
    {
        "id": "kader",
        "title": "5. Agenten-Kader (Profile, Disposition & Rufnamen)",
        "subtitle": "Katalog aller 56 Spezialisten-Rollen, Prompts, Werkzeuge & Telegram-Direktrouting",
        "concept": (
            "Im Agenten-Kader verwaltest du das gesamte Personal deines digitalen Unternehmens. Jedes der 56 Profile verfügt über eine "
            "präzise Stellenbeschreibung, dedizierte Fach-Skills, Werkzeugberechtigungen und eine Modellzuweisung. Über das Feld "
            "'Rufname' kannst du jedem Agenten ein persönliches Telegram-Kürzel zuweisen, unter dem er direkt ansprechbar ist."
        ),
        "elements": [
            ("Linke Spalte: Schlanker Kader-Katalog", 
             "Durchsuchbare Liste aller 56 Profile. Filterbar nach Fachabteilungen (Strategie & Führung, IT, Marketing, Recht, Finanzen, Bau). "
             "Kompakte Kacheln mit Avatar, Stellenbezeichnung, Skill-Anzahl und Status (Aktiv / Standby)."),
            ("Persönlicher Name & Hermes-Handle", 
             "Eindeutige technische ID (z. B. default, robert, micha) zur systemweiten Adressierung."),
            ("Modell-Router / LLM-Provider", 
             "Legt fest, welches Sprachmodell diesen Agenten antreibt (z. B. auto/best-free für Standardaufgaben oder deepseek-reasoner für komplexe Logik)."),
            ("Aufgabenprofil & System-Prompts", 
             "Ausführliche Rollenanweisungen und Leitplanken, die das Verhalten, den Tonfall und die Fachkompetenz des Agenten steuern."),
            ("NEU: Rufname (/Kommando)", 
             "Eingabefeld im unteren Informationsblock (z. B. 'robert', 'micha', 'anwalt'). Trägst du hier einen Namen ein, "
             "kannst du diesen Agenten in Telegram direkt über /<rufname> ansprechen (z. B. '/robert Prüfe die Zahlen')."),
            ("Direkter Supervisor & Erfolgsquote", 
             "Verknüpft die Führungskraft für Eskalationen und zeigt verarbeitete Einsätze sowie die Erfolgsquote (nominal 100%).")
        ],
        "workflow": [
            "1. Wähle im linken Katalog einen Agenten aus (z. B. Robert).",
            "2. Passe bei Bedarf dessen Aufgabenprofil oder den System-Prompt an.",
            "3. Trage unten im Feld 'Rufname' das gewünschte Kürzel ein (z. B. 'robert') und klicke auf 'Speichern'.",
            "4. Sende in Telegram den Befehl '/robert Wie ist der aktuelle Status?' – Robert antwortet dir sofort persönlich."
        ],
        "best_practices": (
            "Nutze prägnante Rufnamen ohne Sonderzeichen. Wenn du mehreren Agenten denselben Rufnamen gibst, kannst du "
            "mit einem einzigen Telegram-Befehl eine ganze Gruppe gleichzeitig ansprechen."
        ),
        "starter_prompt": "Zeige mir das Profil von Robert, seinen hinterlegten System-Prompt und seinen aktuellen Rufnamen."
    },
    {
        "id": "showroom",
        "title": "6. Showroom (Projekt-Explorer & Artefakte)",
        "subtitle": "Zentrale Galerie aller Agenten-Ergebnisse, Dokumente, Medien & Sofort-Vorschau",
        "concept": (
            "Im Showroom landen alle fertigen Arbeitsergebnisse der Agenten. Er ist wie ein moderner Windows-Explorer aufgebaut "
            "und strukturiert alle Zwischenberichte, PDF-Dokumente, Code-Artefakte und Marktanalysen projektbezogen. Die integrierte "
            "Sofort-Vorschau rendert Markdown, HTML und Code direkt im Browser."
        ),
        "elements": [
            ("Projekt-Ordnerbaum (Linke Spalte)", 
             "Listet alle aktiven und archivierten Projekte chronologisch auf. Jeder Ordner unterteilt sich sauber in:\n"
             "• 01_Zwischenberichte: Vorab-Entwürfe und Recherche-Auszüge.\n"
             "• 02_Medien: Generierte Grafiken, Tabellen und Anhänge.\n"
             "• 03_Endprodukte: Abnahmebereite finale Dokumente und PDFs."),
            ("Sofort-Vorschau (Rechter Bereich)", 
             "Klick auf eine Datei öffnet eine formatierte Leseansicht mit voller Markdown- und Typografie-Unterstützung. "
             "Kein externes Programm erforderlich, um Ergebnisse zu prüfen."),
            ("Dateityp-Badges & Metadaten", 
             "Zeigt Dateigröße, Erstellungsdatum und Dateityp auf einen Blick an."),
            ("Aktionen: Download & Explorer-Öffnung", 
             "Dateien können mit einem Klick heruntergeladen oder direkt im lokalen Windows-Dateisystem geöffnet werden.")
        ],
        "workflow": [
            "1. Öffne den Projektordner des gewünschten Auftrags (z. B. Projektentwicklung Vakanz).",
            "2. Klicke auf ein Dokument (z. B. 00_Stenia Vakanz - Business Development.md).",
            "3. Lies den formatierten Bericht in der rechten Vorschau und lade ihn bei Bedarf als PDF/Dokument herunter."
        ],
        "best_practices": (
            "Alle im Showroom angezeigten Dokumente liegen parallel physisch in deinem Arbeitsbereich (`agent_workspace/builds`). "
            "Du kannst sie jederzeit mit externen Editoren weiterverarbeiten."
        ),
        "starter_prompt": "Welche Endprodukte wurden im Showroom für das jüngste Projekt abgelegt?"
    },
    {
        "id": "library",
        "title": "7. Zentralbibliothek (RAG & Knowledge Base)",
        "subtitle": "Kollektiver Wissensspeicher, Vektorsuche & semantischer Dokumentenindex",
        "concept": (
            "Die Zentralbibliothek ist das Langzeitgedächtnis deines Systems. Hier hinterlegtes Wissen steht allen 56 Agenten "
            "über semantische Vektorsuche (RAG – Retrieval Augmented Generation) zur Verfügung. Wenn ein Agent eine Fachaufgabe löst, "
            "schlägt er relevante Gesetze, Normen oder Firmenrichtlinien hier nach, ohne das Prompt-Fenster zu überlasten."
        ),
        "elements": [
            ("Semantischer RAG-Index", 
             "Indexiert Dokumente in logische Abschnitte (Chunks) und berechnet Vektor-Embeddings für blitzschnelle Ähnlichkeitssuche."),
            ("Dokumenten-Katalog & Kategorien", 
             "Strukturiert Wissen nach Themenbereichen: Unternehmensrichtlinien, Rechtstexte, technische Handbücher und Best Practices."),
            ("Suchleiste mit Vektorsuche", 
             "Findet relevante Passagen auch dann, wenn in der Suchanfrage nicht die exakten Wörter des Originaldokuments verwendet werden."),
            ("Synchronisierungs-Status", 
             "Zeigt an, ob alle Dokumente aktuell indexiert sind und meldet eventuell ausstehende Neuindizierungen.")
        ],
        "workflow": [
            "1. Lade neue Richtlinien oder Firmenvorgaben über den Bibliotheks-Dialog hoch.",
            "2. Das System parst den Text, berechnet Embeddings und aktualisiert den RAG-Index.",
            "3. Agenten greifen bei künftigen Aufgaben automatisch auf dieses Wissen zu, wenn das Thema relevant ist."
        ],
        "best_practices": (
            "Hinterlege hier unveränderliche Fakten, Compliance-Vorgaben und Standardverträge. Für persönliche Notizen und "
            "tägliche Arbeitsentwürfe nutze stattdessen das Second Brain (Obsidian)."
        ),
        "starter_prompt": "Welche Wissensdokumente sind aktuell in der Zentralbibliothek hinterlegt und abrufbar?"
    },
    {
        "id": "brain",
        "title": "8. Second Brain (Lokales Obsidian-Vault & OCR-Archiv)",
        "subtitle": "Zero-Latency Wissensmanagement, Auto-OCR für Fachbücher & Desktop-App Brücke",
        "concept": (
            "Das Second Brain verbindet Archon OS direkt mit deinem persönlichen lokalen Obsidian-Vault auf der Festplatte (`C:\\Mein Obsidian`). "
            "Es kombiniert blitzschnellen Dateizugriff ohne Cloud-Latenz mit einer intelligenten OCR-Pipeline für PDFs, Bebauungspläne und Bücher. "
            "Über den Button 'In Obsidian App öffnen' wechselst du nahtlos in deine gewohnte Schreibumgebung."
        ),
        "elements": [
            ("Vault-Auswahl & Statusanzeige (Kopfzeile)", 
             "Zeigt das aktive Vault an (`C:\\Mein Obsidian (Haupt-Vault)`). Daneben befindet sich der Button 'In Obsidian App öffnen', "
             "der die native Windows-Desktop-App per URI-Schema aufruft."),
            ("4 thematische Wissens-Kacheln", 
             "• 00_HR_Agenten: Personalakten, Skill-Definitionen und Leitlinien aller 56 Rollen.\n"
             "• 02_Wissensbibliothek: DIN-Normen, B-Pläne und digitalisierte Fachbücher.\n"
             "• Protokolle/: Sitzungsmitschriften, Aufgaben-Historie und Change-Logs.\n"
             "• 00_Notebook_Synthesen: Synthetisierte Erkenntnisse und Grounded-Retrieval-Dossiers."),
            ("Auto-OCR & Dokumenten-Erfasser (Mitte)", 
             "Drag-and-Drop Uploadbereich für PDF-, DOCX- oder TXT-Dateien. Extrahiert Texte, Tabellen und Gliederungen vollautomatisch, "
             "klassifiziert den Inhalt thematisch und speichert ihn als saubere Markdown-Datei im Vault ab."),
            ("Vault-Bestandsliste (Unten)", 
             "Durchsuchbare Übersicht aller im Vault vorhandenen Dokumente inklusive Angabe von Umfang, Format (OCR/MD) und Schnellaktionen.")
        ],
        "workflow": [
            "1. Ziehe ein neues Fachbuch oder ein Gutachten (PDF) in den Erfassungsbereich.",
            "2. Das System führt im Hintergrund die OCR-Texterkennung durch und legt die formatierte Markdown-Datei in '02_Wissensbibliothek' ab.",
            "3. Klicke oben rechts auf 'In Obsidian App öffnen', um das Dokument direkt in deiner Obsidian-Desktop-App zu bearbeiten oder zu verlinken."
        ],
        "best_practices": (
            "Halte dein lokales Vault gut strukturiert. Da Archon OS direkt auf das Dateisystem zugreift, sind Änderungen, "
            "die du in Obsidian tippst, sofort auch für alle Agenten sichtbar."
        ),
        "starter_prompt": "Welche Dokumente wurden zuletzt in der Wissensbibliothek des Obsidian-Vaults erfasst?"
    },
    {
        "id": "automation",
        "title": "9. Workflow-Engine (n8n Automation Mesh)",
        "subtitle": "Visuelle Hintergrund-Orchestrierung, Webhooks & deterministische Prozessketten",
        "concept": (
            "Während Hermes Aufgaben autonom durch freies Denken löst, kümmert sich n8n (Port 5678) um feste, wiederkehrende "
            "und deterministische Geschäftsprozesse. Es verbindet Archon OS über Webhooks mit Hunderten externer Dienste, "
            "führt zeitgesteuerte Cron-Jobs aus und automatisiert Routineaufgaben zuverlässig im Hintergrund."
        ),
        "elements": [
            ("Eingebetteter visueller Workflow-Editor", 
             "Ermöglicht das grafische Verknüpfen von Triggern, Bedingungsknoten, HTTP-Requests und Daten-Transformationen."),
            ("Archon System-Webhooks", 
             "Vorkonfigurierte Schnittstellen für Dokumenten-Rendering, CRM-Synchronisierung, periodische Markt-Scans und Telegram-Benachrichtigungen."),
            ("Button 'Im neuen Tab öffnen' (Oben rechts)", 
             "Öffnet die native n8n-Benutzeroberfläche im Vollbildmodus für komfortables Editieren komplexer Workflows."),
            ("Dauerhafte Anmeldung (Session-Persistenz)", 
             "Durch vorkonfigurierte JWT-Schlüssel bleibt die n8n-Sitzung im Hintergrund über Monate aktiv, ohne ständiges Neuanmelden.")
        ],
        "workflow": [
            "1. Wechsle in die Workflow-Engine und wähle einen bestehenden Flow (z. B. nächtlicher E-Mail-Report) oder erstelle einen neuen.",
            "2. Verbinde den Webhook-Trigger mit den gewünschten Verarbeitungsschritten.",
            "3. Aktiviere den Schalter 'Active', damit der Workflow ab sofort vollautomatisch im Hintergrund läuft."
        ],
        "best_practices": (
            "Nutze n8n für Prozesse, die exakt nach Schema F ablaufen müssen (z. B. 'Jeden Montag um 8 Uhr Daten sammeln und Bericht ablegen'). "
            "Nutze Hermes für Aufgaben, die kreative Problemlösung oder dynamische Entscheidungen erfordern."
        ),
        "starter_prompt": "Welche Webhooks stehen in n8n für Archon OS bereit und wie kann ein Agent einen Flow auslösen?"
    },
    {
        "id": "omniroute",
        "title": "10. LLM Gateway (OmniRoute AI Router)",
        "subtitle": "Multi-Provider KI-Routing, Kosten- & Latenzoptimierung, Provider-Failover",
        "concept": (
            "OmniRoute (Port 20128) entkoppelt Archon OS von einzelnen KI-Anbietern. Als intelligenter Proxy verteilt es Anfragen "
            "dynamisch auf Anthropic, OpenAI, DeepSeek, Google Gemini, Groq und lokale Modelle. Fällt ein Provider aus oder läuft in ein "
            "Rate-Limit, schaltet OmniRoute unterbrechungsfrei auf das nächste definierte Modell um."
        ),
        "elements": [
            ("Virtuelle Modell-Aliase", 
             "• auto/best-free: Wählt automatisch das schnellste und stabilste kostenfreie Modell.\n"
             "• best-reasoning: Routet komplexe Denkaufgaben an Spitzen-Reasoning-Modelle (DeepSeek R1, Claude Sonnet).\n"
             "• free-forever: Garantiert Null-Kosten-Betrieb über dauerhaft freie Kontingente."),
            ("Provider-Verbindungsstatus", 
             "Überwacht kontinuierlich die Antwortzeiten (Latenz) und die Verfügbarkeit aller hinterlegten API-Schlüssel."),
            ("Token- und Kosten-Telemetrie", 
             "Protokolliert Ein- und Ausgangs-Tokens jedes Modells und verhindert teure Fehlkonfigurationen."),
            ("Credential-Health Wächter", 
             "Prüft im Minutentakt die Gültigkeit von OAuth-Tokens (z. B. Google) und frischt auslaufende Tokens automatisch auf.")
        ],
        "workflow": [
            "1. Definiere in deinen Agenten-Profilen einfach den Alias 'auto/best-free' statt harter Modellnamen.",
            "2. OmniRoute wählt bei jedem Prompt das aktuell optimal verfügbare Modell aus.",
            "3. Kontrolliere im OmniRoute-Dashboard die Latenzen und den erfolgreichen Token-Durchsatz."
        ],
        "best_practices": (
            "Nutze für Routine-Agenten immer 'auto/best-free'. Reserviere teure Bezahlmodelle gezielt für Robert (CEO) "
            "oder komplexe Code-Refactorings."
        ),
        "starter_prompt": "Welche Sprachmodelle sind in OmniRoute aktuell als aktiv und betriebsbereit gemeldet?"
    },
    {
        "id": "guardian",
        "title": "11. Token Guard & Budgetwächter (Guardian)",
        "subtitle": "Kostenkontrolle, Schleifenschutz, Budget-Schranken & Modul-Zustände",
        "concept": (
            "Der Guardian ist der Sicherheits- und Finanzwächter deines Agenten-Betriebssystems. Er stellt sicher, dass kein Agent "
            "durch Programmierfehler in Endlosschleifen gerät oder das definierte Monatsbudget unbemerkt leersaugt. Bei Erreichen "
            "kritischer Limits greift der Wächter automatisch ein und blockiert weitere Anfragen."
        ),
        "elements": [
            ("Zentrale Verbrauchs-Kacheln", 
             "• Gesamte Tokens: Bisher verbrauchte Token-Menge (z. B. 1.034.982 Tokens über 6.892 Calls).\n"
             "• Kosten (USD): Gesamtausgaben (z. B. $39.86) im Vergleich zum Tages-Budget ($2.00).\n"
             "• Aktive Plugins: Anzahl scharfgeschalteter Sicherheitsmodule (z. B. 34 geladene Tools).\n"
             "• Top-Verursacher: Der Agent mit dem höchsten Verbrauch (z. B. root mit 702k Tokens)."),
            ("Token- & Kostenverlauf (Interaktiver Chart)", 
             "Visualisiert Verbrauchsspitzen und Ausgaben pro Tag. Erlaubt Filterung nach 24 Stunden, 7 Tagen, 30 Tagen oder Gesamtlaufzeit."),
            ("Verbrauch pro Agenten-Profil (Tabelle links)", 
             "Exakte Aufschlüsselung der Anrufe und Tokenmengen für jeden einzelnen Agenten (root, micha, telegram_bot etc.)."),
            ("Schutz-Schranken & Budgets (Rechtes Panel)", 
             "• Max Kontext: Schneidet Prompts bei Erreichen der Obergrenze (z. B. 32.000 Tokens) sicher ab.\n"
             "• Max Chat-Historie: Begrenzt den Verlauf auf die letzten N Nachrichten (Standard: 20).\n"
             "• Tages-Budget & Task-Limit: Blockiert Anfragen bei Überschreitung (Standard: $2.00 / Tag, max. $0.50 pro Task).\n"
             "• Max Steps / Task: Schleifenkiller – stoppt Agenten nach maximal 15 Schritten.\n"
             "• Session Timeout: Maximale Ausführungsdauer (60 Sekunden).")
        ],
        "workflow": [
            "1. Überprüfe in der Verlaufskurve, an welchen Tagen Verbrauchsspitzen aufgetreten sind.",
            "2. Identifiziere in der Tabelle den Agenten mit dem höchsten Token-Anteil.",
            "3. Passe bei Bedarf im rechten Panel das Tagesbudget oder das Step-Limit an und speichere die Schranken."
        ],
        "best_practices": (
            "Belasse das Step-Limit bei maximal 15 bis 20 Schritten. Sollte ein Agent für eine Aufgabe mehr Schritte benötigen, "
            "ist es fast immer sinnvoller, die Aufgabe in zwei kleinere Teilaufgaben zu zerlegen."
        ),
        "starter_prompt": "Wie hoch sind die aufgelaufenen Kosten im Guardian heute und welcher Agent hat die meisten Tokens verbraucht?"
    },
    {
        "id": "plugins",
        "title": "12. Erweiterungen & Modul-Zentrale (Plugins)",
        "subtitle": "Übersicht und Steuerung aller 34 modularen System- und Schutz-Erweiterungen",
        "concept": (
            "Archon OS basiert auf einer strikt modularen Plugin-Architektur. In dieser Zentrale steuerst du alle 34 installierten "
            "Erweiterungen. Sie reichen von Sicherheitsfiltern gegen Prompt-Injections über automatische Halluzinationsprüfungen "
            "bis hin zu E-Mail-Wächtern und Werkzeug-Treibern für Hermes."
        ),
        "elements": [
            ("Plugin-Status-Kacheln", 
             "Zeigt den Betriebszustand jedes Moduls (Aktiviert / Deaktiviert / Standby) inklusive Version und Latenz an."),
            ("Sicherheits- & Guard-Plugins", 
             "Module wie Injektions-Erkennung, E-Mail-Guard (Prüfung eingehender Mails auf bösartige Instruktionen) "
             "und Output-Validierung (Verhinderung von Halluzinationen)."),
            ("Funktions- & Integrations-Plugins", 
             "Module für JEV-Routing, automatisierte Obsidian-Vault-Synchronisation und MCP-Tool-Treiber."),
            ("Konfigurations-Modal", 
             "Klick auf ein Plugin öffnet dessen Parameter, Schwellenwerte und Sensitivitätsstufen.")
        ],
        "workflow": [
            "1. Durchsuche die Plugin-Liste nach der gewünschten Erweiterung (z. B. Email Guard).",
            "2. Schalte das Modul per Toggle-Switch aktiv oder passe die Sensitivität (niedrig/mittel/strikt) an.",
            "3. Kontrolliere im Log-Stream, ob das Modul Ereignisse registriert und filtert."
        ],
        "best_practices": (
            "Halte Sicherheits-Plugins wie den Email Guard und die Injektions-Erkennung immer aktiv, besonders wenn dein System "
            "externe E-Mails oder offene Telegram-Nachrichten empfängt."
        ),
        "starter_prompt": "Welche Sicherheits-Plugins sind derzeit aktiv und wie ist der Schwellenwert für die Injektionserkennung eingestellt?"
    },
    {
        "id": "research",
        "title": "13. Research Lab (Deep Search & Recherche)",
        "subtitle": "Multi-Engine Evidenz-Triangulation, Quellenabgleich & strukturierte Dossiers",
        "concept": (
            "Das Research Lab ist das Forschungs- und Analysezentrum deines Systems. Wenn komplexe Markt-, Rechts- oder "
            "Technologiefragen fundiert geklärt werden müssen, führen spezialisierte Research-Agenten hier mehrstufige Tiefenrecherchen durch. "
            "Dabei werden Quellen verglichen, Widersprüche aufgedeckt und strukturierte Dossiers erarbeitet."
        ),
        "elements": [
            ("Recherche-Auftragsmaske", 
             "Eingabefeld für die Forschungsfrage, Zielvorgaben, auszuschließende Quellen und den gewünschten Detaillierungsgrad."),
            ("Engine-Auswahl & Triangulation", 
             "Kombiniert verschiedene Suchquellen (Fachdatenbanken, Web-Search, Bibliotheks-RAG), um einseitige oder veraltete Ergebnisse auszuschließen."),
            ("Evidenz- & Quellenverzeichnis", 
             "Listet alle herangezogenen Primärquellen mit Link, Datum und Zuverlässigkeits-Score auf."),
            ("Dossier-Vorschau & Export", 
             "Rendert das fertige Recherche-Dokument sofort und ermöglicht die direkte Ablage im Showroom oder im Obsidian-Vault.")
        ],
        "workflow": [
            "1. Formuliere im Research Lab eine konkrete Frage (z. B. 'Aktuelle Förderprogramme für modulares Bauen in NRW 2026').",
            "2. Starte die Recherche; das System sammelt Quellen und trianguliert die Ergebnisse.",
            "3. Prüfe das generierte Dossier und speichere es per Klick direkt in deiner Obsidian-Wissensbibliothek ab."
        ],
        "best_practices": (
            "Formuliere Recherchefragen möglichst präzise mit Randbedingungen (Jahr, Region, Zielgruppe). Dadurch sinkt der Tokenverbrauch "
            "und die Qualität der Dossiers steigt dramatisch."
        ),
        "starter_prompt": "Starte eine strukturierte Recherche zu aktuellen Markttrends im Bereich Agentic AI und erstelle ein Dossier."
    },
    {
        "id": "log_stream",
        "title": "14. Telemetrie & Logs (Live-Stream & Audit)",
        "subtitle": "2-Spalten Live-Auditor, Container-Logs, Hash-Ketten & Fehlerdiagnose",
        "concept": (
            "Die Telemetrie- und Log-Ansicht gewährt dir einen ungeschönten Blick unter die Motorhaube von Archon OS. "
            "Sie kombiniert Live-Logs aller 11 Docker-Container mit kryptografischen Audit-Hashketten und dedizierten "
            "Agenten-Traces. Wenn ein Prozess unerwartet stoppt, findest du hier in Sekunden die exakte Ursache."
        ),
        "elements": [
            ("Linke Spalte: LOG AUDITOR EXPLORER", 
             "Listet alle aktiven Signalquellen mit Status-Badges auf. Über 3 Sub-Tabs schaltbar:\n"
             "• Container (11 Live): hermes, ARCHON-OS, n8n, Pocketbase, omniroute, docker-socket-proxy etc.\n"
             "• Agenten: Filtert Logs auf spezifische Rollen (z. B. robert, telegram_bot).\n"
             "• Hash-Audit: Zeigt die kryptografische Hash-Kette aller Transaktionen zur manipulationssicheren Nachverfolgung."),
            ("Rechte Spalte: Live Log-Stream", 
             "Formatierter Terminal-Stream mit automatischer Farbkodierung (INFO grün, WARN gelb, ERROR rot, CRITICAL magenta)."),
            ("Filter- & Pause-Leiste (Oben)", 
             "Erlaubt Volltextsuche innerhalb der Logs, Filterung nach Mindest-Schweregrad und das Pausieren des Auto-Scrolls bei der Fehlersuche."),
            ("Echtzeit-Synchronisierung", 
             "Streamt Logs ohne Seiten-Reload direkt aus den Docker-Sockets.")
        ],
        "workflow": [
            "1. Wähle im linken Explorer den Dienst aus, den du analysieren möchtest (z. B. hermes oder n8n).",
            "2. Filtere oben nach 'ERROR', um sofort eventuelle Fehlermeldungen oder Timeouts zu isolieren.",
            "3. Klicke auf 'Pause', um eine verdächtige Code-Zeile in Ruhe zu untersuchen und zu kopieren."
        ],
        "best_practices": (
            "Wirf bei unklaren Systemzuständen immer zuerst einen Blick in das hermes-Log. Da Hermes die zentrale Ausführungs-Engine ist, "
            "siehst du dort sofort, ob ein Tool-Aufruf fehlgeschlagen ist."
        ),
        "starter_prompt": "Prüfe die letzten 50 Log-Einträge des hermes-Containers auf Fehler oder Warnungen."
    }
]

print("1. Prüfe / Binde Screenshots ein...")
for v in VIEWS:
    img_name = f"{v['id']}.png"
    img_path = os.path.join(IMG_DIR, img_name)
    v["img_path"] = img_path
    if os.path.exists(img_path) and os.path.getsize(img_path) > 10000:
        print(f"  ✓ {v['id']} vorhanden ({round(os.path.getsize(img_path)/1024)} KB)")
    else:
        print(f"  ⚠️ Screenshot fehlt oder zu klein: {img_path}")

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
run_meta = meta_p.add_run("Stand: 14. Oktober 2026 | Release: 2.0 Enterprise | 56 Autonome Spezialisten-Rollen")
run_meta.font.name = "Calibri"
run_meta.font.size = Pt(9.5)
run_meta.font.color.rgb = COLOR_MUTED

intro_p = doc.add_paragraph()
intro_p.paragraph_format.space_after = Pt(16)
intro_p.paragraph_format.line_spacing = 1.15
intro_run = intro_p.add_run(
    "Dieses System-Handbuch richtet sich an Betreiber, Entscheider und Nutzer des Archon Agentic Operating Systems. "
    "Es vermittelt ein tiefgehendes Verständnis aller 14 Bedienoberflächen und ihrer technologischen Verzahnung. "
    "Ziel dieses Handbuchs ist es, dass jeder Anwender ohne Vorwissen in die Lage versetzt wird, Aufgaben autonom "
    "zu delegieren, Überwachungs- und Freigabeprozesse (HITL) sicher auszuführen und das Zusammenspiel zwischen "
    "Kanban-Board, Obsidian-Wissensbasis, Telegram-Steuerung und Hintergrund-Workflows voll auszuschöpfen."
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
    "2. Operations (Kanban & Task-Engine)\n"
    "3. Operations (Organisation & Flowchart)\n"
    "4. Eingang & Triage (HITL & Postfach)\n"
    "5. Agenten-Kader (Profile & Rufnamen)\n"
    "6. Showroom (Projekt-Explorer & Artefakte)\n"
    "7. Zentralbibliothek (RAG & Knowledge)"
).font.size = Pt(9.5)

p_r = cell_r.paragraphs[0]
p_r.paragraph_format.space_after = Pt(2)
r_th2 = p_r.add_run("Kognition, Automation & Governance:\n")
r_th2.font.bold = True
r_th2.font.size = Pt(10)
r_th2.font.color.rgb = COLOR_PRIMARY
p_r.add_run(
    "8. Second Brain (Obsidian Vault & OCR)\n"
    "9. Workflow-Engine (n8n Automation)\n"
    "10. LLM Gateway (OmniRoute AI Router)\n"
    "11. Token Guard (Guardian & Budgets)\n"
    "12. Erweiterungen (Plugin-Zentrale)\n"
    "13. Research Lab (Evidenz-Recherche)\n"
    "14. Telemetrie & Logs (Live-Audit Stream)"
).font.size = Pt(9.5)

doc.add_page_break()

# --- HAUPTTEILE: DIE 14 ANSICHTEN IM DETAIL ---
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

    # Screenshot einbetten
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
    r_eh = p_elem_h.add_run("Die wichtigsten Steuerelemente & Bereiche im Detail:")
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
    "Telegram über den geschützten E-Mail-Freigabeprozess bis hin zur vollautonomen Projektentwicklung und kaskadierenden "
    "Fehler-Eskalation im 24/7-Betrieb."
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
            "Du erhältst ein neues technisches Gutachten oder einen Bebauungsplan als 80-seitiges PDF. Du möchtest, dass alle 56 Agenten "
            "dieses Spezialwissen sofort beherrschen, ohne dass du ihnen die Fakten jedes Mal manuell in den Prompt kopieren musst."
        ),
        "steps": [
            "1. Du öffnest die Ansicht 'Second Brain' (C:\\Mein Obsidian) und ziehst das PDF per Drag & Drop in den Bereich 'PDF-Dokumente & Fachbücher erfassen'.",
            "2. Die integrierte Auto-OCR-Pipeline extrahiert vollautomatisch Fließtexte, Tabellen und Überschriften und übersetzt sie in sauberes Markdown.",
            "3. Das formatierte Dokument wird direkt im Ordner '02_Wissensbibliothek' deines lokalen Obsidian-Vaults auf der Festplatte abgelegt.",
            "4. Parallel dazu segmentiert der Ingestions-Dienst die Datei in logische Chunks und berechnet Vektor-Embeddings für den RAG-Index der Zentralbibliothek.",
            "5. Du klickst oben rechts auf 'In Obsidian App öffnen' – deine lokale Obsidian-Desktop-App springt auf und zeigt die formatierte Notiz.",
            "6. Stellt ein Nutzer künftig eine Frage zu diesem Bauprojekt, ruft der zuständige Agent (z. B. Bobby Brown, Bauleitung) die Fakten zielgenau per Vektorsuche ab."
        ],
        "modules": "Second Brain (Obsidian Vault) ➔ Auto-OCR Pipeline ➔ Markdown-Konverter ➔ Zentralbibliothek (RAG-Embeddings) ➔ Obsidian Desktop App",
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
            "4. Das Research Lab führt Evidenz-Triangulation durch und speichert Zwischenanalysen in '01_Zwischenberichte'.",
            "5. Robert führt alle Zulieferungen zusammen, erstellt ein 12-seitiges Gesamtdossier im Showroom ('03_Endprodukte') und schiebt den Task auf 'Review & QA'.",
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
    os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026_v3.docx")
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


