# -*- coding: utf-8 -*-
import re
import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

DOC_PATH = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"
OUT_VORLAGE = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"
OUT_HANDBUCH = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx"

doc = docx.Document(DOC_PATH)

print(f"Ursprüngliche Absätze: {len(doc.paragraphs)}, Tabellen: {len(doc.tables)}, Body-Elemente: {len(doc._body._element)}")

# 1. Entferne Body-Elemente von Chapter 8 (Second Brain)
start_idx = None
end_idx = None

for i, child in enumerate(doc._body._element):
    if child.tag.endswith('p'):
        text = "".join(child.itertext()).strip()
        if text.startswith("8. Second Brain"):
            start_idx = i
        elif text.startswith("9. Workflow-Engine") and start_idx is not None and end_idx is None:
            end_idx = i
            break

print(f"Gefundener Bereich Chapter 8: Start={start_idx}, End={end_idx}")

if start_idx is not None and end_idx is not None:
    for i in range(end_idx - 1, start_idx - 1, -1):
        el = doc._body._element[i]
        doc._body._element.remove(el)
    print(f"Body-Elemente nach Entfernung: {len(doc._body._element)}")
else:
    print("Info: Chapter 8 (Second Brain) ist bereits vollständig entfernt.")

# 2. Definiere die exakten Kapitel-Titel (1 bis 15)
CHAPTER_RENAMES = [
    ("9. Workflow-Engine", "8. Workflow-Engine (n8n Automation Mesh)"),
    ("10. LLM Gateway", "9. LLM Gateway (OmniRoute AI Router)"),
    ("11. Token Guard", "10. Token Guard (Guardian & Budgetwächter)"),
    ("12. Erweiterungen", "11. Erweiterungen (Plugin- & MCP-Zentrale)"),
    ("13. Research Lab", "12. Research Lab (Deep Search & Wissensbeschaffung)"),
    ("14. Telemetrie & Logs", "13. Telemetrie & Logs (Live-Audit Stream)"),
    ("15. Spezial-Feature: Archon Prompt Studio", "14. Spezial-Feature: Archon Prompt Studio (1.079 Vorlagen & Fabric SOP)"),
    ("16. Spezial-Feature: Visual CSS Live Studio", "15. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector"),
]

# Liste aller 15 Kapitel-Präfixe für sichere Erkennung
MAIN_CHAPTER_PREFIXES = [
    "1. Mission Control",
    "2. Operations – Operative Projektsteuerung",
    "3. Operations – Organisation & Ablaufdiagramm",
    "4. Eingang & Triage",
    "5. Agenten-Kader & Flottenmanagement",
    "6. Showroom",
    "7. Zentralbibliothek & Wissensmanagement",
    "8. Workflow-Engine",
    "9. LLM Gateway",
    "10. Token Guard",
    "11. Erweiterungen",
    "12. Research Lab",
    "13. Telemetrie & Logs",
    "14. Spezial-Feature: Archon Prompt Studio",
    "15. Spezial-Feature: Visual CSS Live Studio"
]

COLOR_PRIMARY = RGBColor(15, 23, 42)       # Slate 900
COLOR_SECONDARY = RGBColor(51, 65, 85)     # Slate 700
COLOR_ACCENT = RGBColor(14, 116, 144)      # Cyan 700
COLOR_MUTED = RGBColor(100, 116, 139)      # Slate 500

for p_idx, p in enumerate(doc.paragraphs):
    txt = p.text.strip()

    # Text-Ersetzungen
    if "16 Fachmodule" in p.text:
        for r in p.runs:
            r.text = r.text.replace("16 Fachmodule", "15 Fachmodule")
    if "16 Bedienoberflächen" in p.text:
        for r in p.runs:
            r.text = r.text.replace("16 Bedienoberflächen", "15 Bedienoberflächen")
    if "16 spezialisierte" in p.text:
        for r in p.runs:
            r.text = r.text.replace("16 spezialisierte", "15 spezialisierte")
    if "16 Kapitel" in p.text:
        for r in p.runs:
            r.text = r.text.replace("16 Kapitel", "15 Kapitel")
    if "Obsidian Vault & Second Brain" in p.text:
        for r in p.runs:
            r.text = r.text.replace("Obsidian Vault & Second Brain", "Obsidian Vault & Zentralbibliothek")
    if "Second Brains" in p.text:
        for r in p.runs:
            r.text = r.text.replace("Second Brains", "Zentralbibliothek")
    if "Second Brain & RAG" in p.text:
        for r in p.runs:
            r.text = r.text.replace("Second Brain & RAG", "Zentralbibliothek & RAG")
    if "Second Brain" in p.text and not txt.startswith("8. Second Brain"):
        for r in p.runs:
            r.text = r.text.replace("Second Brain", "Zentralbibliothek")

    # Umnummerierung der Kapitel 9..16
    for old_pref, new_full in CHAPTER_RENAMES:
        if txt.startswith(old_pref):
            p.text = new_full
            txt = new_full
            break

    # 1. Kapitel-Überschriften formatieren (Heading 1)
    is_main_ch = False
    for pref in MAIN_CHAPTER_PREFIXES:
        if txt.startswith(pref):
            is_main_ch = True
            p.style = doc.styles['Heading 1']
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(2)
            for r in p.runs:
                r.font.name = "Calibri"
                r.font.size = Pt(14)
                r.font.bold = True
                r.font.color.rgb = COLOR_PRIMARY
            break

    if is_main_ch:
        continue

    # 2. Sub-Kapitel (z. B. 2.1, 2.2, 5.1 ... 7.3)
    if re.match(r"^\d+\.\d+\s+", txt):
        p.style = doc.styles['Heading 2']
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(2)
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(12)
            r.font.bold = True
            r.font.color.rgb = COLOR_PRIMARY
        continue

    # 3. Anhang & Use Cases
    if txt.startswith("ANHANG: 5 PRAXIS-USE-CASES"):
        p.style = doc.styles['Heading 1']
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(4)
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(16)
            r.font.bold = True
            r.font.color.rgb = COLOR_PRIMARY
        continue

    if re.match(r"^Use Case \d+:", txt):
        p.style = doc.styles['Heading 2']
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(2)
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(13)
            r.font.bold = True
            r.font.color.rgb = COLOR_PRIMARY
        continue

    # 4. Standard-Abschnittsüberschriften innerhalb von Kapiteln
    if txt == "Die wichtigsten Steuerelemente & Bereiche im Überblick:":
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(11)
            r.font.bold = True
            r.font.color.rgb = COLOR_PRIMARY
    elif txt == "Detaillierte Analyse der Unterbereiche & Funktionen:":
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(12)
            r.font.bold = True
            r.font.color.rgb = COLOR_ACCENT
    elif txt == "Praxis-Workflow (Schritt für Schritt):":
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(11)
            r.font.bold = True
            r.font.color.rgb = COLOR_PRIMARY
    elif txt.startswith("Kernkonzept & Architektur:"):
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(4)
    elif txt.startswith("💡 Praxistipp & Leitplanke:"):
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)

    # 5. Bilder zentrieren (außer dem Banner auf Seite 1, p[0])
    xml = p._p.xml
    if ('w:drawing' in xml or 'w:pict' in xml) and p_idx > 0:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(6)

# 3. Aktualisiere die Inhaltsübersichts-Tabelle (TOC)
for tbl in doc.tables:
    first_cell_txt = tbl.rows[0].cells[0].text if tbl.rows and tbl.rows[0].cells else ""
    if "Operative Steuerung" in first_cell_txt:
        print("Gefundene Inhaltsübersicht-Tabelle. Aktualisiere auf 15 Kapitel...")
        cell_l = tbl.cell(0, 0)
        cell_r = tbl.cell(0, 1)
        
        # Linke Spalte: Kapitel 1 bis 7
        cell_l.paragraphs[0].text = ""
        p_l = cell_l.paragraphs[0]
        p_l.paragraph_format.space_after = Pt(2)
        r_th1 = p_l.add_run("Operative Steuerung & Kognition:\n")
        r_th1.font.name = "Calibri"
        r_th1.font.bold = True
        r_th1.font.size = Pt(10)
        r_th1.font.color.rgb = COLOR_PRIMARY
        r_l_body = p_l.add_run(
            "1. Mission Control (Cockpit & Leitstand)\n"
            "2. Operations (Kanban, Orga & Funk)\n"
            "3. Operations (Organisation & Flowchart)\n"
            "4. Eingang & Triage (HITL & Postfach)\n"
            "5. Agenten-Kader (Profile, Routen & Subtabs)\n"
            "6. Showroom (Projekt-Explorer & Sandbox)\n"
            "7. Zentralbibliothek (RAG, Erfasser & Vault)"
        )
        r_l_body.font.name = "Calibri"
        r_l_body.font.size = Pt(9.5)
        r_l_body.font.color.rgb = COLOR_SECONDARY

        # Rechte Spalte: Kapitel 8 bis 15
        cell_r.paragraphs[0].text = ""
        p_r = cell_r.paragraphs[0]
        p_r.paragraph_format.space_after = Pt(2)
        r_th2 = p_r.add_run("Automation, Governance & Studios:\n")
        r_th2.font.name = "Calibri"
        r_th2.font.bold = True
        r_th2.font.size = Pt(10)
        r_th2.font.color.rgb = COLOR_PRIMARY
        r_r_body = p_r.add_run(
            "8. Workflow-Engine (n8n Automation Mesh)\n"
            "9. LLM Gateway (OmniRoute AI Router)\n"
            "10. Token Guard (Guardian & Budgets)\n"
            "11. Erweiterungen (Plugin- & MCP-Zentrale)\n"
            "12. Research Lab (Evidenz-Recherche)\n"
            "13. Telemetrie & Logs (Live-Audit Stream)\n"
            "14. Spezial: Archon Prompt Studio (1.079)\n"
            "15. Spezial: Visual CSS Live Studio (Alt + S)"
        )
        r_r_body.font.name = "Calibri"
        r_r_body.font.size = Pt(9.5)
        r_r_body.font.color.rgb = COLOR_SECONDARY

# Speichern
doc.save(OUT_VORLAGE)
doc.save(OUT_HANDBUCH)
print(f"Erfolgreich gespeichert: {OUT_VORLAGE} und {OUT_HANDBUCH}")
