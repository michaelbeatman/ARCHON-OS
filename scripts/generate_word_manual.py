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

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = "/app/docs/system" if os.path.exists("/app/docs/system") else r"c:\.Antigravity-projekte\AgenticOS-2026\docs\system"
IMG_DIR = os.path.join(OUTPUT_DIR, "screenshots")
DOCX_PATH = os.path.join(OUTPUT_DIR, "ARCHON_OS_SYSTEM_HANDBUCH_2026.docx")

os.makedirs(IMG_DIR, exist_ok=True)

VIEWS = [
    {
        "id": "mission_control",
        "tab": "mission-control",
        "title": "1. Mission Control (Cockpit)",
        "subtitle": "Echtzeit-Monitoring, System-KPIs & HITL-Freigaben",
        "purpose": "Mission Control dient als übersichtlicher Leitstand zur Überwachung des Gesamtsystems. Hier werden KPIs (Flottenlast, TPM, Latenz) angezeigt und die Aufgaben aus dem Operations-Kanban in 5 Spalten gespiegelt. Operative Änderungen und neue Aufgaben werden direkt im Operations-Kanban oder im Agenten-Kader verwaltet.",
        "top_actions": [
            "Überwache die 5 System-Kacheln für Flottenlast, Token/min und Antwortlatenz.",
            "Sichte anstehende Freigaben in der Review-Spalte und bestätige oder stoppe sie.",
            "Wechsle für die Neuanlage oder detaillierte Bearbeitung von Aufgaben in das Operations-Kanban."
        ],
        "starter_prompt": "Welche Aufgaben stehen aktuell in Mission Control und welche benötigen meine persönliche Freigabe?"
    },
    {
        "id": "operations",
        "tab": "operations",
        "title": "2. Operations & Kanban Board",
        "subtitle": "Echtzeit-Leitstand und Flotten-Überwachung",
        "purpose": "Hier steuerst du den operativen Betrieb aller 56 Spezial-Agenten. Du siehst aktuelle System-KPIs, laufende Hintergrundprozesse, aktive Container und das zentrale Arbeits-Kanban.",
        "top_actions": [
            "Nutze 'Neuer Task', um einer Rolle einen Arbeitsauftrag mit Prompt-Studio zu erteilen.",
            "Verschiebe Karten per Drag-and-Drop zwischen To Do, In Progress, Review und Done.",
            "Öffne Karten im Detail-Modal, um Zwischenergebnisse direkt in der lokalen Obsidian-App zu öffnen."
        ],
        "starter_prompt": "Erkläre mir, wie ich im Operations-Dashboard einen neuen Task an den passenden Agenten delegiere und den Fortschritt überwache."
    },
    {
        "id": "inbox",
        "tab": "inbox",
        "title": "3. Eingang & Triage (Intake)",
        "subtitle": "Operative Triage: HITL-Freigaben, E-Mails & Telegram",
        "purpose": "Zentrale Schleuse für alle eingehenden Signale. Hier genehmigst du Aktionen (Human-in-the-Loop), sichtest E-Mails und verarbeitest Nachrichten.",
        "top_actions": [
            "Filtere nach HITL-Freigaben, um blockierte Schreib-Aktionen der Agenten zu bestätigen.",
            "Synchronisiere das E-Mail-Postfach oder binde neue E-Mails direkt an Kontakte an.",
            "Übergib Nachrichten per Klick an einen spezialisierten Agenten zur automatischen Beantwortung."
        ],
        "starter_prompt": "Wie funktioniert der HITL-Freigabeprozess im Posteingang und wie kann ich eine E-Mail direkt von einem Agenten beantworten lassen?"
    },
    {
        "id": "kader",
        "tab": "agent-profiles",
        "title": "4. Agenten-Kader (Rollen & Profile)",
        "subtitle": "Vollständiges Verzeichnis aller 56 Rollen & Profile",
        "purpose": "Katalog aller aktivierten Agenten-Profile mit Aufgabenprofil, System-Prompts, Zuständigkeiten, Werkzeugberechtigungen und individuellem Rufnamen (/Kommando).",
        "top_actions": [
            "Suche oder filtere nach Fachabteilungen (Geschäftsführung, IT, Marketing, Recht, Finanzen).",
            "Passe den 'Rufnamen' an, um den Agenten über Telegram direkt mit /<rufname> anzusprechen.",
            "Weise dem Agenten direkt eine autonome Aufgabe oder neue Fach-Skills zu."
        ],
        "starter_prompt": "Welcher Agent im Kader ist für rechtliche Prüfungen zuständig und welche Werkzeuge stehen ihm zur Verfügung?"
    },
    {
        "id": "org",
        "tab": "teambildung",
        "title": "5. Organigramm & Teams",
        "subtitle": "Interaktiver 2D-Organisationsbaum aller 56 Agenten",
        "purpose": "Visualisiert die hierarchischen Beziehungen, Berichtswege und Rollen aller Agenten im Unternehmen. Ermöglicht das Umhängen von Vorgesetzten und Neukonfigurieren.",
        "top_actions": [
            "Klicke auf einen Agentenknoten, um das Eigenschaftsfenster zu öffnen und Name, Vorgesetzten oder Modell anzupassen.",
            "Nutze das Mausrad zum Zoomen und die linke Maustaste zum Verschieben der Arbeitsfläche.",
            "Beobachte die Status-Badges (Online / Busy / Idle) für jeden Agenten in Echtzeit."
        ],
        "starter_prompt": "Wie ändere ich den Vorgesetzten eines Agenten im Organigramm und wie wird das Modell für eine Rolle hinterlegt?"
    },
    {
        "id": "crm",
        "tab": "crm",
        "title": "6. CRM & Kontakte (Twenty)",
        "subtitle": "Beziehungs- und Interaktionsmanagement",
        "purpose": "Speichert Kunden, Partner, Bewerber und Vakanzen inklusive lückenloser Nachrichten- und E-Mail-Historie auf Port 3005.",
        "top_actions": [
            "Importiere Kontakte aus LinkedIn oder synchronisiere mit Outlook / PocketBase.",
            "Klicke auf einen Kontakt, um den gesamten E-Mail- und Nachrichtenverlauf einzusehen.",
            "Lass einen Agenten automatische personalisierte E-Mails oder Angebote für diesen Kontakt generieren."
        ],
        "starter_prompt": "Wie kann ich einen Kontakt anlegen und den Agenten beauftragen, ein passendes Anschreiben für eine Vakanz zu verfassen?"
    },
    {
        "id": "showroom",
        "tab": "showroom",
        "title": "7. Showroom & Deliveries",
        "subtitle": "Zentrale Galerie aller Agenten-Ergebnisse & Dokumente",
        "purpose": "Hier landen alle fertiggestellten Berichte, PDF-Dokumente, Code-Artefakte und Analysen, die von Agenten erarbeitet wurden, übersichtlich strukturiert nach Windows-Explorer-Logik.",
        "top_actions": [
            "Vorschau von Markdown-Berichten und gerenderten HTML/PDF-Dokumenten.",
            "Herunterladen von erzeugten Dateien mit einem Klick.",
            "Filterung nach Typ (Code, Dokument, Analyse, Bild)."
        ],
        "starter_prompt": "Wo finde ich die von Agenten generierten PDFs und wie kann ich sie herunterladen oder weiterverarbeiten?"
    },
    {
        "id": "library",
        "tab": "library",
        "title": "8. Library & Knowledge Base",
        "subtitle": "Wissensspeicher, RAG-Index & Vault",
        "purpose": "Das kollektive Gedächtnis des Systems. Enthält Unternehmensrichtlinien, Gesetze, Fachwissen und Obsidian-Notizen, auf die alle Agenten zugreifen.",
        "top_actions": [
            "Durchsuche die Knowledge-Base nach Fachbegriffen oder Richtlinien.",
            "Synchronisiere das lokale Obsidian-Vault mit dem semantischen RAG-Index.",
            "Hinterlege neue Standard-Dokumente für die Wissensabfrage."
        ],
        "starter_prompt": "Wie synchronisiere ich neue Dokumente in den RAG-Index, damit die Agenten das Wissen sofort abrufen können?"
    },
    {
        "id": "brain",
        "tab": "brain",
        "title": "9. Second Brain & Lokales Obsidian Vault",
        "subtitle": "Zero-Latency Wissensmanagement & OCR-Archiv",
        "purpose": "Verbindet Archon OS direkt mit deinem lokalen Obsidian-Vault ('Mein Obsidian'). Dokumente, Notizen und Recherche-Ergebnisse werden hier in sauberer Markdown-Struktur abgelegt und durchsuchbar gemacht.",
        "top_actions": [
            "Wähle das aktive Vault aus (lokales Haupt-Vault oder Cloud/OneDrive).",
            "Lade Dokumente oder Fachbücher hoch, um sie automatisch per OCR zu indizieren.",
            "Öffne Dokumente direkt mit einem Klick in deiner lokalen Obsidian-Desktop-App."
        ],
        "starter_prompt": "Wie sind die Ordner im Obsidian-Vault strukturiert und wo legen Agenten ihre Recherche-Ergebnisse ab?"
    },
    {
        "id": "automation",
        "tab": "automation",
        "title": "10. n8n Automation Mesh",
        "subtitle": "Grafische Workflow-Engine & Webhook-Integration",
        "purpose": "Hier steuerst und erstellst du autonome Hintergrund-Workflows über n8n (Port 5678). Das System stellt Webhooks für Dokumenten-Rendering, CRM-Synchronisierung, Web-Recherche und Nachrichten-Versand bereit.",
        "top_actions": [
            "Erstelle oder passe Workflows mit visuellen Triggern und Knoten an.",
            "Nutze die 5 integrierten Archon-Webhooks für Datenaustausch und Automationen.",
            "Klicke auf 'Im neuen Tab öffnen', wenn du den n8n-Workflow-Editor im Vollbildmodus nutzen möchtest."
        ],
        "starter_prompt": "Welche Webhooks sind in n8n für Archon OS eingerichtet und wie kann ich einen neuen Workflow starten?"
    },
    {
        "id": "omniroute",
        "tab": "omniroute",
        "title": "11. OmniRoute AI Gateway",
        "subtitle": "Multi-Provider KI-Routing & Token-Telemetrie",
        "purpose": "OmniRoute fungiert als intelligentes Gateway für alle LLM-Anfragen. Es verteilt Prompts kosten- und latenzoptimiert auf Provider wie Anthropic, OpenAI, DeepSeek, Gemini und lokale Modelle.",
        "top_actions": [
            "Prüfe das Routing-Verhalten und die Latenzen der verschiedenen KI-Modelle.",
            "Konfiguriere API-Schlüssel, Fallback-Strategien und Token-Budgets.",
            "Nutze virtuelle Modell-Aliase wie 'best-reasoning' oder 'free-forever' in deinen Agenten-Profilen."
        ],
        "starter_prompt": "Wie funktioniert das Routing in OmniRoute und welche Modelle sind als Fallback hinterlegt?"
    },
    {
        "id": "guardian",
        "tab": "guardian",
        "title": "12. Guardian & Token Analytics",
        "subtitle": "Kostenkontrolle, Schleifenschutz & Wächter",
        "purpose": "Der Guardian überwacht Token-Verbrauch, API-Kosten und Ausführungszeiten. Er stoppt Endlosschleifen und warnt bei Überschreitung festgelegter Budgets.",
        "top_actions": [
            "Analysiere den Token-Verbrauch gefiltert nach Zeitraum (24h, 7 Tage, 30 Tage, Gesamt).",
            "Überprüfe Kosten pro Agent und Modell.",
            "Passe Sicherheits-Limits für maximale Token pro Anfrage oder Tag an."
        ],
        "starter_prompt": "Welcher Agent hat heute die meisten Tokens verbraucht und wie setze ich ein tägliches Ausgabenlimit?"
    },
    {
        "id": "plugins",
        "tab": "plugins",
        "title": "13. Erweiterungen & Modul-Zentrale",
        "subtitle": "Hermes Spezial-Plugins & Funktionserweiterungen",
        "purpose": "Übersicht und Schalter für alle 34 modularen Erweiterungen wie JEV-Routing, Injektionsschutz, E-Mail-Sync, RAG-Suche und automatische Dokumentenverarbeitung.",
        "top_actions": [
            "Aktiviere oder deaktiviere einzelne Module nach Bedarf.",
            "Passe Parameter und Schwellenwerte für spezifische Plugins an.",
            "Prüfe den Ladestatus und eventuelle Abhängigkeiten."
        ],
        "starter_prompt": "Welche Plugins sind derzeit aktiv und wie schütze ich das System vor Prompt-Injections?"
    },
    {
        "id": "research",
        "tab": "research",
        "title": "14. Research Lab",
        "subtitle": "Multi-Engine Recherche & Evidenz-Triangulation",
        "purpose": "Tiefenrecherche über verschiedene Web- und Fachquellen. Agenten sammeln Fakten, vergleichen Quellen und erstellen fundierte Dossiers zur direkten Ablage im Obsidian-Vault.",
        "top_actions": [
            "Starte gezielte Marktforschungs- oder Dokumentenrecherchen mit Quellenangaben.",
            "Wähle die Such-Engine und das zuständige Analyse-Modell.",
            "Sichte fertige Dossiers und überführe sie in den Showroom oder ins Vault."
        ],
        "starter_prompt": "Wie beauftrage ich eine strukturierte Marktanalyse im Research Lab?"
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
        url = f"http://localhost:8501/?tab={v['tab']}"
        cmd = [
            CHROME_PATH,
            "--headless",
            "--disable-gpu",
            f"--screenshot={img_path}",
            "--window-size=1600,900",
            url
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            print(f"  ✓ {v['id']} per Fallback generiert: {os.path.exists(img_path)}")
        except Exception as e:
            print(f"  ⚠️ Fehler bei {v['id']}: {e}")

print("2. Generiere Word-Dokument (ARCHON_OS_SYSTEM_HANDBUCH_2026.docx)...")
doc = Document()

# Seitenränder
for section in doc.sections:
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

# Farben
COLOR_PRIMARY = RGBColor(15, 23, 42)      # Slate 900
COLOR_ACCENT = RGBColor(14, 116, 144)     # Cyan 700
COLOR_MUTED = RGBColor(100, 116, 139)     # Slate 500
COLOR_BOX_BG = "F1F5F9"                  # Slate 100

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))

# --- TITELSEITE ---
title_p = doc.add_paragraph()
title_p.paragraph_format.space_before = Pt(40)
title_p.paragraph_format.space_after = Pt(6)
run_title = title_p.add_run("ARCHON AGENTIC OS 2026")
run_title.font.name = "Calibri"
run_title.font.size = Pt(28)
run_title.font.bold = True
run_title.font.color.rgb = COLOR_PRIMARY

sub_p = doc.add_paragraph()
sub_p.paragraph_format.space_after = Pt(24)
run_sub = sub_p.add_run("Offizielles System-Handbuch & Modul-Referenz")
run_sub.font.size = Pt(14)
run_sub.font.color.rgb = COLOR_ACCENT

meta_p = doc.add_paragraph()
meta_p.paragraph_format.space_after = Pt(30)
run_meta = meta_p.add_run("Stand: 14. Oktober 2026 | Version: 2.0 Enterprise | 56 Autonome Rollen")
run_meta.font.size = Pt(10)
run_meta.font.color.rgb = COLOR_MUTED

intro_p = doc.add_paragraph()
intro_p.paragraph_format.space_after = Pt(24)
intro_run = intro_p.add_run(
    "Dieses Dokument dient als praxisorientierte Einführung und Leitfaden für Nutzer und Administratoren "
    "des Archon Agentic Operating Systems. Es beschreibt jede Kern-Ansicht im Detail, listet die primären "
    "Handlungsabläufe auf und visualisiert die jeweilige Arbeitsoberfläche mit aktuellem Screenshot."
)
intro_run.font.size = Pt(11)

doc.add_page_break()

# --- HAUPTTEILE: DIE 14 ANSICHTEN ---
for idx, v in enumerate(VIEWS, 1):
    h = doc.add_paragraph()
    h.paragraph_format.space_before = Pt(18)
    h.paragraph_format.space_after = Pt(4)
    run_h = h.add_run(v["title"])
    run_h.font.name = "Calibri"
    run_h.font.size = Pt(18)
    run_h.font.bold = True
    run_h.font.color.rgb = COLOR_PRIMARY

    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(12)
    run_s = sub.add_run(v["subtitle"])
    run_s.font.size = Pt(11)
    run_s.font.italic = True
    run_s.font.color.rgb = COLOR_ACCENT

    # Screenshot einbetten
    if os.path.exists(v.get("img_path", "")):
        try:
            p_img = doc.add_paragraph()
            p_img.paragraph_format.space_after = Pt(12)
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.add_picture(v["img_path"], width=Inches(6.6))
        except Exception as e_img:
            print(f"Fehler beim Einbetten von {v['id']}: {e_img}")

    # Zweck / Beschreibung
    p_desc = doc.add_paragraph()
    p_desc.paragraph_format.space_before = Pt(8)
    p_desc.paragraph_format.space_after = Pt(8)
    r_lbl1 = p_desc.add_run("Zweck & Funktion: ")
    r_lbl1.font.bold = True
    p_desc.add_run(v["purpose"])

    # Wichtigste Aktionen
    p_act_lbl = doc.add_paragraph()
    p_act_lbl.paragraph_format.space_before = Pt(4)
    p_act_lbl.paragraph_format.space_after = Pt(2)
    r_act = p_act_lbl.add_run("Typische Handlungsabläufe:")
    r_act.font.bold = True

    for act in v["top_actions"]:
        p_bullet = doc.add_paragraph(style='List Bullet')
        p_bullet.paragraph_format.space_after = Pt(2)
        p_bullet.add_run(act)

    # Starter-Prompt Kasten
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, COLOR_BOX_BG)
    cell_p = cell.paragraphs[0]
    cell_p.paragraph_format.space_before = Pt(6)
    cell_p.paragraph_format.space_after = Pt(6)
    r_box_title = cell_p.add_run("💡 Empfohlener Einstiegs-Prompt an den Assistenten:\n")
    r_box_title.font.bold = True
    r_box_title.font.size = Pt(10)
    r_box_title.font.color.rgb = COLOR_ACCENT
    r_prompt = cell_p.add_run(f'"{v["starter_prompt"]}"')
    r_prompt.font.italic = True
    r_prompt.font.size = Pt(10)

    doc.add_paragraph().paragraph_format.space_after = Pt(14)
    if idx < len(VIEWS):
        doc.add_page_break()

doc.save(DOCX_PATH)
print(f"3. Handbuch erfolgreich gespeichert unter: {DOCX_PATH}")
