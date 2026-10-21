# -*- coding: utf-8 -*-
"""
Script to apply all approved grill-me updates to ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx:
1. Chapter 1: Expand Mission Control with bottom zone (Process Heartbeat, Tool Concurrency Table, Context Saturation, Token Activity Sparkline, Active Tasks, Artifact Modal).
2. Chapter 8: Expand n8n with official links (n8n.io, GitHub), CEO autonomy via n8n-automation-mesh MCP skill, port 5678.
3. Chapter 9: Expand OmniRoute with official links/references, settings location (System Control Center Tab 'Provider & Gateway'), fallback chains.
4. Restructure & Renumber:
   - Chapter 10 remains Token Guard
   - Move old Chapter 11 (Erweiterungen) to the end as Chapter 15: System Control Center & Einstellungen (with 15.1 - 15.7)
   - Renumber Research Lab -> Chapter 11
   - Renumber Telemetrie & Logs -> Chapter 12
   - Renumber Prompt Studio -> Chapter 13
   - Renumber CSS Live Studio -> Chapter 14
   - Insert new Chapter 15 before ANHANG
5. Remove Word comment range tags.
"""

import sys
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

DOC_PATH = r"docs\system\ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"

def set_run_font(run, font_name="Aptos", size_pt=10.5, color_rgb=(45, 55, 72), bold=False, italic=False):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.color.rgb = RGBColor(*color_rgb)
    run.bold = bold
    run.italic = italic

def set_p_spacing(p, before_pt=0, after_pt=4, line_spacing=1.15):
    p.paragraph_format.space_before = Pt(before_pt)
    p.paragraph_format.space_after = Pt(after_pt)
    p.paragraph_format.line_spacing = line_spacing

def add_callout_box(doc, icon_title, text):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    cell = tbl.rows[0].cells[0]
    cell.width = Inches(6.8)
    
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>')
    tcPr.append(shd)
    
    tcBorders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'  <w:top w:val="none"/>'
        f'  <w:left w:val="single" w:sz="24" w:space="0" w:color="2B6CB0"/>'
        f'  <w:bottom w:val="none"/>'
        f'  <w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(tcBorders)
    
    mar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'  <w:top w:w="120" w:type="dxa"/>'
        f'  <w:left w:w="180" w:type="dxa"/>'
        f'  <w:bottom w:w="120" w:type="dxa"/>'
        f'  <w:right w:w="180" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(mar)
    
    p = cell.paragraphs[0]
    p.style = "Normal"
    set_p_spacing(p, 2, 2, 1.15)
    r1 = p.add_run(icon_title + " ")
    set_run_font(r1, "Aptos", 9.5, (43, 108, 176), bold=True)
    r2 = p.add_run(text)
    set_run_font(r2, "Aptos", 9.5, (45, 55, 72))
    return tbl

print("Update script template ready.")
