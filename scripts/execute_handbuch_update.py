# -*- coding: utf-8 -*-
"""
Executes all approved updates on ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx:
1. Chapter 1 (Mission Control):
   - Detailed KPI metric cards
   - Detailed Workflow & Approval Board (5 columns with HITL gate)
   - Active Process Inspection Bar (Slot A Heartbeat & 120s Watchdog, Slot B Concurrency Slots with limits, Slot C Context Saturation & LRU-K buffer)
   - Rolling Token-Aktivitaets-Band (15-min SVG sparkline, average and peak)
   - Active Tasks Box & Artefakt-Vorschau Modal
   - Live-Audit & Telemetrie-Stream
   - Table 1.1: Vitalparameter, Concurrency-Limits & Schwellenwerte
2. Chapter 8 (n8n Automation Mesh):
   - Official Links (n8n.io, github.com/n8n-io/n8n)
   - Docker container on Port 5678
   - CEO Autonomy & FastMCP control via n8n-automation-mesh skill
   - Architecture & integration infobox
3. Chapter 9 (OmniRoute AI Router):
   - High-performance proxy architecture on Port 8000
   - Configuration locations: System Control Center Tab 'Provider & Gateway' and config/
   - Model combinations & Fallback cascades (GLM-4.7 Flash -> Gemini 2.5 Flash -> Claude 3.5 Sonnet -> Llama 3.3 70B)
   - Official links, latency monitoring and infobox
4. Renumbering and Placement:
   - Removes old Chapter 11 (Erweiterungen)
   - Chapter 12 -> 11. Research Lab (Deep Search & Wissensbeschaffung)
   - Chapter 13 -> 12. Telemetrie & Logs (Live-Audit Stream)
   - Chapter 14 -> 13. Spezial-Feature: Archon Prompt Studio (1.079 Vorlagen & Fabric SOP)
   - Chapter 15 -> 14. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector
   - Inserts new Chapter 15 before ANHANG:
     15. System Control Center & Einstellungen (Zentrale System-Administration)
     with subsections 15.1 to 15.7 (Hermes Core, Container & Dienste, Provider & Gateway,
     Methodiken, Plugins & MCP-Zentrale, Kommunikation, Design), workflow, praxistipp, and prompt callout.
5. Cleans XML comment tags.
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

def create_callout_box(doc, icon_title, text):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    cell = tbl.rows[0].cells[0]
    cell.width = Inches(6.8)
    
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>'))
    tcPr.append(parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'  <w:top w:val="none"/>'
        f'  <w:left w:val="single" w:sz="24" w:space="0" w:color="2B6CB0"/>'
        f'  <w:bottom w:val="none"/>'
        f'  <w:right w:val="none"/>'
        f'</w:tcBorders>'
    ))
    tcPr.append(parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'  <w:top w:w="120" w:type="dxa"/>'
        f'  <w:left w:w="180" w:type="dxa"/>'
        f'  <w:bottom w:w="120" w:type="dxa"/>'
        f'  <w:right w:w="180" w:type="dxa"/>'
        f'</w:tcMar>'
    ))
    
    p = cell.paragraphs[0]
    p.style = "Normal"
    set_p_spacing(p, 2, 2, 1.15)
    r1 = p.add_run(icon_title + " ")
    set_run_font(r1, "Aptos", 9.5, (43, 108, 176), bold=True)
    r2 = p.add_run(text)
    set_run_font(r2, "Aptos", 9.5, (45, 55, 72))
    return tbl

def create_styled_table(doc, headers, data, col_widths=None):
    tbl = doc.add_table(rows=len(data) + 1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    
    # Header row
    hdr_row = tbl.rows[0]
    trPr = hdr_row._tr.get_or_add_trPr()
    trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    for idx, heading in enumerate(headers):
        cell = hdr_row.cells[idx]
        if col_widths and idx < len(col_widths):
            cell.width = Inches(col_widths[idx])
        tcPr = cell._tc.get_or_add_tcPr()
        tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="1A365D"/>'))
        tcPr.append(parse_xml(
            f'<w:tcMar {nsdecls("w")}>'
            f'  <w:top w:w="120" w:type="dxa"/><w:left w:w="140" w:type="dxa"/>'
            f'  <w:bottom w:w="120" w:type="dxa"/><w:right w:w="140" w:type="dxa"/>'
            f'</w:tcMar>'
        ))
        p = cell.paragraphs[0]
        set_p_spacing(p, 2, 2, 1.1)
        r = p.add_run(heading)
        set_run_font(r, "Aptos", 9.5, (255, 255, 255), bold=True)
        
    # Data rows
    for r_idx, row_data in enumerate(data):
        row = tbl.rows[r_idx + 1]
        bg_color = "F8FAFC" if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row_data):
            cell = row.cells[c_idx]
            if col_widths and c_idx < len(col_widths):
                cell.width = Inches(col_widths[c_idx])
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_color}"/>'))
            tcPr.append(parse_xml(
                f'<w:tcMar {nsdecls("w")}>'
                f'  <w:top w:w="100" w:type="dxa"/><w:left w:w="140" w:type="dxa"/>'
                f'  <w:bottom w:w="100" w:type="dxa"/><w:right w:w="140" w:type="dxa"/>'
                f'</w:tcMar>'
            ))
            borders = parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                f'  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                f'  <w:left w:val="none"/><w:right w:val="none"/>'
                f'</w:tcBorders>'
            )
            tcPr.append(borders)
            p = cell.paragraphs[0]
            set_p_spacing(p, 2, 2, 1.1)
            r = p.add_run(val)
            set_run_font(r, "Aptos", 9.0, (45, 55, 72))
            
    return tbl

def clean_comments(doc):
    body = doc._body._element
    comments_tags = body.xpath('.//w:commentRangeStart | .//w:commentRangeEnd | .//w:commentReference')
    for tag in comments_tags:
        parent = tag.getparent()
        if parent is not None:
            parent.remove(tag)
    print(f"Cleaned {len(comments_tags)} comment tags from XML.")

def main():
    doc = Document(DOC_PATH)
    clean_comments(doc)
    
    # -------------------------------------------------------------
    # 1. EXPAND CHAPTER 1 (Mission Control)
    # -------------------------------------------------------------
    print("Updating Chapter 1: Mission Control...")
    mc_start = None
    mc_workflow = None
    mc_praxis = None
    
    for i, p in enumerate(doc.paragraphs):
        if p.text.startswith("1. Mission Control"):
            mc_start = i
        elif p.text.startswith("Workflow & Approval Board:") and mc_start is not None and mc_workflow is None:
            mc_workflow = i
        elif p.text.startswith("Praxis-Workflow (Schritt für Schritt):") and mc_start is not None and mc_praxis is None:
            mc_praxis = i
            break
            
    if mc_workflow and mc_praxis:
        # We replace the text from mc_workflow to mc_praxis with the comprehensive breakdown
        # First, remove existing paragraphs between mc_workflow and mc_praxis
        p_anchor = doc.paragraphs[mc_praxis]
        
        # Elements to insert before mc_praxis
        new_sections = [
            ("Workflow & Approval Board (5 Spalten & HITL-Freigabe):",
             "Spiegelt den operativen Lebenszyklus der Aufgaben in fünf dynamischen Spalten wider (To-Do, In Bearbeitung, Review & QA, Blockiert, Abgeschlossen). Aufgaben in der Review-Spalte blockieren automatisch systemkritische Tool-Aktionen (z. B. Schreibzugriffe auf Produktivdateien, Mailversand oder API-Löschungen), bis du sie im Cockpit manuell prüfst und freigibst."),
            
            ("Active Process Inspection Bar (3-Slot-Maschinenraum im Footer):",
             "Der untere Balken liefert eine lückenlose Diagnose der internen Systemvitalität in drei synchronisierten Modulen:\n"
             "• Slot A – Process Heartbeat & Watchdog: Überwacht den asynchronen Hintergrund-Daemon (Port 8420). Ein pulsierender Indikator bestätigt den nominalen Zustand. Bei Leerlauf schaltet der Kernel in den energiesparenden 'Tickless Sleep'. Der Watchdog-Timer (120 s Timeout) fängt hängende Prozesse automatisch ab und startet Worker bei Bedarf neu.\n"
             "• Slot B – Tool Concurrency Slots: Zeigt die Auslastung paralleler Werkzeuge in Echtzeit (z. B. web_search [0/5], code_gen [0/2], obsidian [1/3]). Die integrierte Hashmap-Sperre verhindert API-Rate-Limits und blockiert kollidierende Schreibzugriffe.\n"
             "• Slot C – Context Saturation & Speicherdruck: Misst die Belegung des aktiven LLM-Kontextfensters (z. B. deepseek-v4-flash: 18k / 128k Tokens belegt, 110k Puffer). Erreicht die Sättigung 80%, greift automatisch die LRU-K Eviction-Policy, um Kontextüberläufe zu verhindern."),
            
            ("Rolling Token-Aktivitäts-Band (15-Minuten-Sparkline):",
             "Ein hochauflösendes Live-SVG-Flussband visualisiert den Durchsatz der letzten 15 Minuten. Die Anzeige weist den gleitenden Durchschnitt (Ø Tok/min) sowie Lastspitzen (Peak Tok/min) aus. Unerwartete Ausschläge deuten auf Rekursionsschleifen oder umfangreiche Code-Analysen hin und können sofort gestoppt werden."),
            
            ("Aktiver Agenten-Kader & Aktive Aufgaben (Rechte Flanke):",
             "• Kader-Statusliste: Schnellsicht auf die 51 vorkonfigurierten Profile inklusive Bereitschaftszustand (Standby / Aktiv / Blockiert) und hinterlegtem Modell-Alias.\n"
             "• Aktive Aufgaben: Zeigt laufende Worker-Prozesse inklusive Startzeitpunkt, ausführendem Agenten und aktuellem Einzelschritt."),
            
            ("Direktes Artefakt-Vorschau-Modal:",
             "Ein Klick auf eine fertige Aufgabe in der Spalte 'Abgeschlossen' öffnet ohne Seitenwechsel das Artefakt-Modal. Das generierte Ergebnis (z. B. Markdown-Berichte in /opt/data/obsidian/Projects/...) kann sofort im Volltext gelesen, geprüft und kopiert werden."),
            
            ("Live-Audit & Telemetrie-Stream:",
             "Der rechte Syslog-Feed dokumentiert alle Ereignisse sekundengenau im Monospace-Klartext: Tool-Invocations, Promptfoo-Sicherheitsprüfungen, HITL-Freigabestopps und Prozessübergaben bleiben revisionssicher nachvollziehbar.")
        ]
        
        # Remove old paragraphs from mc_workflow to mc_praxis - 1
        paras_to_remove = []
        for idx in range(mc_workflow, mc_praxis):
            paras_to_remove.append(doc.paragraphs[idx])
        for p in paras_to_remove:
            p._p.getparent().remove(p._p)
            
        # Now insert new sections before p_anchor
        for title, text in new_sections:
            p_head = doc.add_paragraph()
            p_head.style = "Normal"
            set_p_spacing(p_head, 6, 2, 1.15)
            r_head = p_head.add_run(title)
            set_run_font(r_head, "Aptos", 10.5, (26, 54, 93), bold=True)
            p_anchor._p.addprevious(p_head._p)
            
            p_body = doc.add_paragraph()
            p_body.style = "Normal"
            set_p_spacing(p_body, 0, 4, 1.15)
            r_body = p_body.add_run(text)
            set_run_font(r_body, "Aptos", 10.0, (45, 55, 72))
            p_anchor._p.addprevious(p_body._p)
            
        # Add Table 1.1: Vitalparameter & Concurrency Limits before p_anchor
        p_tbl_lbl = doc.add_paragraph()
        p_tbl_lbl.style = "Normal"
        set_p_spacing(p_tbl_lbl, 8, 2, 1.15)
        r_tbl_lbl = p_tbl_lbl.add_run("Tabelle 1.1: Vitalparameter, Concurrency-Limits & Schwellenwerte in Mission Control")
        set_run_font(r_tbl_lbl, "Aptos", 9.5, (43, 108, 176), bold=True)
        p_anchor._p.addprevious(p_tbl_lbl._p)
        
        table_headers = ["Parameter / Kachel", "Nominalwert / Schwellenwert", "Bedeutung & Schutzmechanismus"]
        table_data = [
            ["Flottenlast", "0 – 10 aktiv (Limit 51)", "Überwacht parallel arbeitende Worker; verhindert Thread-Starvation und Host-Überlastung."],
            ["Durchsatz (TPM)", "< 500k Tok/min (Limit 2.000.000)", "Schützt vor Überschreitung der LLM-Provider Quotas und Drosselung."],
            ["Kostenwächter", "< $3.00 kumuliert (Hard Limit $5.00/Tag)", "Echtzeit-Budgetbremse: Blockiert bei Annäherung weitere kostspielige Abfragen."],
            ["Stabilität", "100% nominal (Fehlerquote < 1.0%)", "Erfolgsquote aller Tool- und Modellausführungen; löst bei Fehlern Fallback-Routen aus."],
            ["Approval Gate", "0 ausstehend (Farbe: Grün)", "Zeigt blockierte Aktionen; bei > 0 ist eine manuelle HITL-Prüfung erforderlich."],
            ["Tool Concurrency", "Web [5], Code [2], Obsidian [3]", "Hashmap-Locks verhindern Kollisionen und parallele Rate-Limit-Überschreitungen."],
            ["Context Saturation", "< 80% des Kontextfensters", "Visualisiert Kontextpuffer; löst bei 80% automatisches LRU-K Paging in SQLite aus."]
        ]
        tbl_vital = create_styled_table(doc, table_headers, table_data, [1.5, 2.2, 3.1])
        p_anchor._p.addprevious(tbl_vital._tbl)
        
        p_sep = doc.add_paragraph()
        set_p_spacing(p_sep, 2, 6, 1.15)
        p_anchor._p.addprevious(p_sep._p)

    # -------------------------------------------------------------
    # 2. EXPAND CHAPTER 8 (n8n Automation Mesh)
    # -------------------------------------------------------------
    print("Updating Chapter 8: n8n Automation Mesh...")
    n8n_start = None
    n8n_praxis = None
    for i, p in enumerate(doc.paragraphs):
        if p.text.startswith("8. Workflow-Engine"):
            n8n_start = i
        elif p.text.startswith("Praxis-Workflow (Schritt für Schritt):") and n8n_start is not None:
            n8n_praxis = i
            break
            
    if n8n_start and n8n_praxis:
        p_anchor = doc.paragraphs[n8n_praxis]
        # Remove old text between n8n_start + 2 and n8n_praxis
        paras_to_remove = []
        for idx in range(n8n_start + 2, n8n_praxis):
            paras_to_remove.append(doc.paragraphs[idx])
        for p in paras_to_remove:
            p._p.getparent().remove(p._p)
            
        n8n_content = [
            ("Kernkonzept & Architektur:",
             "Die Workflow-Engine bindet die Open-Source Automatisierungsplattform n8n (Offizielle Website: https://n8n.io | Repository: https://github.com/n8n-io/n8n) als lokales Docker-Mesh nahtlos in Archon OS ein. Auf Port 5678 betrieben, schließt n8n die Lücke zwischen generativer KI und deterministischer Unternehmens-IT: Während LLMs über Heuristiken entscheiden, führt n8n wiederkehrende Schnittstellenprozesse (z. B. CRM-Sync, Webhook-Dispatching, PDF-Verarbeitung) absolut fehlerfrei und regelbasiert aus."),
            
            ("CEO-Autonomie & MCP-Steuerung (n8n-automation-mesh):",
             "Der leitende CEO-Agent sowie berechtigte Operatoren sind dank des integrierten Skills 'n8n-automation-mesh' in der Lage, n8n direkt aus dem Chat oder per Telegram-Funkbefehl vollständig zu steuern. Über standardisierte FastMCP-Webhook-Tools kann der Agent:\n"
             "• Bestehende Workflow-Ketten aktivieren, pausieren oder auf Abruf triggern,\n"
             "• Ausführungsmetriken und Fehlerprotokolle in Echtzeit abfragen,\n"
             "• Neue Integrationsszenarien anhand von JSON-Vorlagen dynamisch provisionieren,\n"
             "• Asynchrone Benachrichtigungen an das Operations-Kanban oder mobile Endgeräte senden."),
            
            ("Die wichtigsten Steuerelemente & Bereiche im Überblick:",
             "• Vollwertige n8n Canvas-Oberfläche: Direkt im Archon-Frame eingebetteter Node-Editor mit über 400 fertigen API-Konnektoren (Slack, Google Workspace, PostgreSQL, GitHub u. v. m.).\n"
             "• Archon FastMCP Node-Bridge: Dedizierte HTTP- und Webhook-Knoten, über die Workflows Ereignisse direkt an den Hermes-Kernel oder spezialisierte Fachagenten übergeben.\n"
             "• Webhook- & Event-Eingänge: Lauscht im Hintergrund auf externe Trigger aus E-Mail-Servern, Lead-Formularen oder Webhooks und überführt sie in strukturierte System-Tasks.\n"
             "• Execution History & Debugger: Lückenlose Historie jedes Einzellaufs mit Ein- und Ausgabedaten zur sekundenschnellen Fehleranalyse.")
        ]
        
        for title, text in n8n_content:
            p_head = doc.add_paragraph()
            p_head.style = "Normal"
            set_p_spacing(p_head, 6, 2, 1.15)
            r_head = p_head.add_run(title)
            set_run_font(r_head, "Aptos", 10.5, (26, 54, 93), bold=True)
            p_anchor._p.addprevious(p_head._p)
            
            p_body = doc.add_paragraph()
            p_body.style = "Normal"
            set_p_spacing(p_body, 0, 4, 1.15)
            r_body = p_body.add_run(text)
            set_run_font(r_body, "Aptos", 10.0, (45, 55, 72))
            p_anchor._p.addprevious(p_body._p)
            
        # Add Infobox table
        info_headers = ["Architektur-Parameter", "Konfiguration & Endpunkte", "Operativer Nutzen"]
        info_data = [
            ["Deployment", "Docker Container (agent-os-n8n)", "Isolierte Ausführungsumgebung ohne Abhängigkeiten auf dem Host."],
            ["Port & Web-UI", "Port 5678 (http://localhost:5678)", "Voller Zugriff auf den visuellen Canvas-Editor im Browser."],
            ["MCP-Integration", "Skill: n8n-automation-mesh", "Ermöglicht dem CEO-Agenten die autonome Ausführung per FastMCP."],
            ["Webhook-Eingang", "http://localhost:5678/webhook/...", "Reaktiver Empfang externer Signale (z. B. CRM-Leads, GitHub-Hooks)."]
        ]
        p_tbl_lbl = doc.add_paragraph()
        p_tbl_lbl.style = "Normal"
        set_p_spacing(p_tbl_lbl, 6, 2, 1.15)
        r_tbl_lbl = p_tbl_lbl.add_run("Tabelle 8.1: Technische Eckdaten der n8n Workflow-Engine")
        set_run_font(r_tbl_lbl, "Aptos", 9.5, (43, 108, 176), bold=True)
        p_anchor._p.addprevious(p_tbl_lbl._p)
        
        tbl_n8n = create_styled_table(doc, info_headers, info_data, [1.6, 2.5, 2.7])
        p_anchor._p.addprevious(tbl_n8n._tbl)
        
        p_sep = doc.add_paragraph()
        set_p_spacing(p_sep, 2, 4, 1.15)
        p_anchor._p.addprevious(p_sep._p)

    # -------------------------------------------------------------
    # 3. EXPAND CHAPTER 9 (OmniRoute AI Router)
    # -------------------------------------------------------------
    print("Updating Chapter 9: OmniRoute AI Router...")
    omni_start = None
    omni_praxis = None
    for i, p in enumerate(doc.paragraphs):
        if p.text.startswith("9. LLM Gateway"):
            omni_start = i
        elif p.text.startswith("Praxis-Workflow (Schritt für Schritt):") and omni_start is not None:
            omni_praxis = i
            break
            
    if omni_start and omni_praxis:
        p_anchor = doc.paragraphs[omni_praxis]
        paras_to_remove = []
        for idx in range(omni_start + 2, omni_praxis):
            paras_to_remove.append(doc.paragraphs[idx])
        for p in paras_to_remove:
            p._p.getparent().remove(p._p)
            
        omni_content = [
            ("Kernkonzept & Architektur:",
             "OmniRoute ist das intelligente Hochleistungs-Gateway (Standard-Port 8000) für alle Modellanfragen in Archon OS. Es entkoppelt den Agentenkern vollständig von einzelnen Modellanbietern und standardisiert die Kommunikation nach dem OpenAI-kompatiblen Schema. Fällt ein Anbieter aus oder greift ein Rate-Limit, schaltet OmniRoute in Millisekunden auf definierte Sekundärrouten um – für den Anwender völlig transparent und unterbrechungsfrei."),
            
            ("Wo APIs & Modellkombinationen eingestellt werden:",
             "Die Konfiguration der API-Schlüssel und Modell-Routen erfolgt zentral über zwei Wege:\n"
             "1. Grafisch im System Control Center (Tab 'Provider & Gateway'): Hier werden API-Keys für OpenRouter, Google AI (Gemini), Groq, OpenAI und Anthropic hinterlegt. Über den Button 'Verbindung testen' lässt sich die Latenz jedes Providers vor der Freigabe prüfen.\n"
             "2. Dateibasiert über das Kernel-Verzeichnis: In config/hermes_config.yaml und der lokalen Schlüsselverwaltung können Provider-Hierarchien und benutzerdefinierte Modell-Kombinationen dauerhaft festgeschrieben werden."),
            
            ("Dynamische Fallback-Kaskaden & Kombinationen:",
             "Um maximale Ausfallsicherheit bei minimalen Kosten zu gewährleisten, arbeitet OmniRoute mit priorisierten Fallback-Ketten:\n"
             "• Primärstufe: GLM-4.7 Flash / auto/best-free – Maximale Geschwindigkeit bei $0.00 Kosten für Routine-Aufgaben und Vorfilterung.\n"
             "• Sekundärstufe: Google Gemini 2.5 Flash – Hohe Zuverlässigkeit und gigantischer Kontextpuffer für umfangreiche Text-Synthesen.\n"
             "• Tertiärstufe: Anthropic Claude 3.5 Sonnet – Hochpräzises Reasoning für Architektur-, Code- und Vertragsanalysen.\n"
             "• Souveränes Notfall-Fallback: Lokales Llama 3.3 70B über Ollama/vLLM – Greift bei totalem Internet- oder Cloud-Ausfall."),
            
            ("Die wichtigsten Steuerelemente & Bereiche im Überblick:",
             "• Multi-Provider Vault: Verschlüsselte Verwaltung aller Provider-Schlüssel an einem zentralen Ort.\n"
             "• Latenz- & Fehlermonitor: Visualisiert Antwortzeiten (in ms) und HTTP-Fehlercodes (429, 500) zur Früherkennung von Provider-Störungen.\n"
             "• Automatischer Circuit Breaker: Trennt instabile Endpunkte temporär ab und leitet Anfragen ohne Token-Verlust um.")
        ]
        
        for title, text in omni_content:
            p_head = doc.add_paragraph()
            p_head.style = "Normal"
            set_p_spacing(p_head, 6, 2, 1.15)
            r_head = p_head.add_run(title)
            set_run_font(r_head, "Aptos", 10.5, (26, 54, 93), bold=True)
            p_anchor._p.addprevious(p_head._p)
            
            p_body = doc.add_paragraph()
            p_body.style = "Normal"
            set_p_spacing(p_body, 0, 4, 1.15)
            r_body = p_body.add_run(text)
            set_run_font(r_body, "Aptos", 10.0, (45, 55, 72))
            p_anchor._p.addprevious(p_body._p)
            
        # Add Infobox table
        info_headers = ["Gateway-Merkmal", "Spezifikation & Pfad", "Funktion im Live-Betrieb"]
        info_data = [
            ["Gateway Service", "Port 8000 (http://localhost:8000/v1)", "Zentraler Proxy-Endpunkt für alle LLM-Aufrufe."],
            ["Konfigurationsort", "System Control Center -> 'Provider & Gateway'", "Grafische Schlüsselverwaltung und Latenzprüfung."],
            ["Config-Datei", "config/hermes_config.yaml", "Dateibasierte Definition von Modell-Kombinationen."],
            ["Health-Check", "http://localhost:8000/health", "Liefert Uptime und Provider-Verfügbarkeiten für den Watchdog."]
        ]
        p_tbl_lbl = doc.add_paragraph()
        p_tbl_lbl.style = "Normal"
        set_p_spacing(p_tbl_lbl, 6, 2, 1.15)
        r_tbl_lbl = p_tbl_lbl.add_run("Tabelle 9.1: Technische Eckdaten des OmniRoute AI Routers")
        set_run_font(r_tbl_lbl, "Aptos", 9.5, (43, 108, 176), bold=True)
        p_anchor._p.addprevious(p_tbl_lbl._p)
        
        tbl_omni = create_styled_table(doc, info_headers, info_data, [1.6, 2.5, 2.7])
        p_anchor._p.addprevious(tbl_omni._tbl)
        
        p_sep = doc.add_paragraph()
        set_p_spacing(p_sep, 2, 4, 1.15)
        p_anchor._p.addprevious(p_sep._p)

    # -------------------------------------------------------------
    # 4. REMOVE OLD CHAPTER 11 & RENUMBER 12->11, 13->12, 14->13, 15->14
    # -------------------------------------------------------------
    print("Restructuring and renumbering chapters...")
    body = doc._body._element
    
    # Locate child indices of headings in body
    heading_indices = {}
    for idx, child in enumerate(body):
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = docx.text.paragraph.Paragraph(child, doc)
            if p.style.name.startswith("Heading 1"):
                heading_indices[p.text.strip().split("\n")[0]] = idx
                
    print("Found headings in body:", heading_indices)
    
    idx_ch11_old = None
    idx_ch12_old = None
    idx_anhang = None
    
    for text, idx in heading_indices.items():
        if text.startswith("11. Erweiterungen"):
            idx_ch11_old = idx
        elif text.startswith("12. Research Lab"):
            idx_ch12_old = idx
        elif text.startswith("ANHANG:"):
            idx_anhang = idx
            
    print(f"Indices: Ch11_old={idx_ch11_old}, Ch12_old={idx_ch12_old}, ANHANG={idx_anhang}")
    
    if idx_ch11_old is not None and idx_ch12_old is not None:
        # Elements between idx_ch11_old and idx_ch12_old are the old Chapter 11
        # Remove them in reverse order
        for i in range(idx_ch12_old - 1, idx_ch11_old - 1, -1):
            body.remove(body[i])
        print("Removed old Chapter 11 elements.")
        
    # Renumber the remaining chapters
    for p in doc.paragraphs:
        if p.text.startswith("12. Research Lab"):
            p.text = p.text.replace("12. Research Lab", "11. Research Lab")
            print("Renumbered to 11. Research Lab")
        elif p.text.startswith("13. Telemetrie & Logs"):
            p.text = p.text.replace("13. Telemetrie & Logs", "12. Telemetrie & Logs")
            print("Renumbered to 12. Telemetrie & Logs")
        elif p.text.startswith("14. Spezial-Feature: Archon Prompt Studio"):
            p.text = p.text.replace("14. Spezial-Feature: Archon Prompt Studio", "13. Spezial-Feature: Archon Prompt Studio")
            print("Renumbered to 13. Spezial-Feature: Archon Prompt Studio")
        elif p.text.startswith("15. Spezial-Feature: Visual CSS Live Studio"):
            p.text = p.text.replace("15. Spezial-Feature: Visual CSS Live Studio", "14. Spezial-Feature: Visual CSS Live Studio")
            print("Renumbered to 14. Spezial-Feature: Visual CSS Live Studio")

    # -------------------------------------------------------------
    # 5. INSERT NEW CHAPTER 15: System Control Center & Einstellungen
    # -------------------------------------------------------------
    print("Inserting new Chapter 15: System Control Center & Einstellungen...")
    p_anhang = None
    for p in doc.paragraphs:
        if p.text.startswith("ANHANG:"):
            p_anhang = p
            break
            
    if p_anhang:
        # Create all elements for Chapter 15
        ch15_elements = []
        
        # Heading 1
        p_h1 = doc.add_paragraph()
        p_h1.style = "Heading 1"
        set_p_spacing(p_h1, 18, 4, 1.15)
        r_h1 = p_h1.add_run("15. System Control Center & Einstellungen")
        set_run_font(r_h1, "Aptos Display", 18.0, (26, 54, 93), bold=True)
        ch15_elements.append(p_h1)
        
        # Subtitle
        p_sub = doc.add_paragraph()
        p_sub.style = "Normal"
        set_p_spacing(p_sub, 0, 8, 1.15)
        r_sub = p_sub.add_run("Zentrale System-Administration, Daemon-Kernel, Multi-Provider-Verwaltung & MCP-Zentrale")
        set_run_font(r_sub, "Aptos", 11.0, (74, 85, 104), italic=True)
        ch15_elements.append(p_sub)
        
        # Visual description
        p_desc = doc.add_paragraph()
        p_desc.style = "Normal"
        set_p_spacing(p_desc, 0, 6, 1.15)
        r_desc = p_desc.add_run("Das System Control Center (aufrufbar über das Zahnrad-Symbol oben rechts in Mission Control oder über das App-Menü) bündelt alle operativen und architektonischen Konfigurationsbereiche von Archon OS in einem modularen Vollbild-Dialog. Anstelle verstreuter Konfigurationsdateien bietet das Control Center sieben übersichtliche Fachreiter:")
        set_run_font(r_desc, "Aptos", 10.5, (45, 55, 72))
        ch15_elements.append(p_desc)
        
        # Subsections 15.1 - 15.7
        subsections = [
            ("15.1 Hermes Core (Kernel & Scheduler):",
             "Verwaltet den zentralen Hintergrund-Daemon auf Port 8420. Hier kontrollierst du den 'Tickless Kernel Sleep' (automatische Takt-Absenkung bei Inaktivität) und den 120-Sekunden-Watchdog für automatische Crash-Recovery. Über Quick-Select-Kacheln wechselst du mit einem Klick das primäre Sprachmodell (GLM-5.3, Gemini 2.5 Flash, Claude 3.5 Sonnet, Llama 3.3 70B). Ein integrierter YAML-Live-Editor erlaubt direkte Anpassungen an der hermes_config.yaml mit sofortiger Syntaxprüfung."),
            
            ("15.2 Container & Dienste (Docker-Mesh & Systemstatus):",
             "Überwacht den Zustand aller elf Docker-Container im Archon-Netzwerk (Hermes, PocketBase, n8n, Quartz, OmniRoute, Guardian etc.). Einzelne Dienste können bei Bedarf isoliert neu gestartet werden. Zudem stehen Diagnose-Werkzeuge bereit, um den Guardian-Token-Cache zu bereinigen oder einen autorisierten Daten-Reset durchzuführen."),
            
            ("15.3 Provider & Gateway (Multi-Provider Management):",
             "Der zentrale Schlüssel-Tresor für alle kognitiven Schnittstellen (OpenRouter, Google AI, Groq, OpenAI, Anthropic, OmniRoute). Neben der sicheren Eingabe von API-Keys bietet dieser Reiter integrierte Latenztests zur Ermittlung der schnellsten Antwortzeiten sowie die grafische Konfiguration von Ausfall-Kaskaden."),
            
            ("15.4 Methodiken (35 Base Frameworks & Prompt-SOPs):",
             "Verwaltet die 35 im System verankerten Standard-Frameworks (Fabric-Muster, C-Level-Rollen, SWAT-Strategie, Six Sigma, Risk Assessment). Du kannst bestehende Vorlagen anpassen, unternehmenseigene Workflows hinzufügen oder das Gesamtsystem jederzeit auf die Werkseinstellungen zurücksetzen."),
            
            ("15.5 Plugins & MCP-Zentrale (Model Context Protocol Treiber):",
             "Die standardisierte Schnittstellen-Zentrale für Werkzeuge nach dem Model Context Protocol (MCP). Hier aktivierst oder pausierst du FastMCP-Treiber für das lokale Dateisystem, Websuche (Brave/DuckDuckGo), E-Mail-Sync, Git und Shell-Runner. Granulare Berechtigungs-Scopes stellen sicher, dass Schreibzugriffe nur mit expliziter Freigabe erfolgen."),
            
            ("15.6 Kommunikation (Telegram, CRM-Mail & Webhooks):",
             "Konfiguriert alle mobilen und externen Kommunikationskanäle: Hinterlegung des Telegram-Bot-Tokens und autorisierter Chat-IDs für den Fernzugriff, Einrichtung des E-Mail-Abgleichs für das integrierte CRM (IMAP/SMTP) sowie Bereitstellung eingehender Webhook-Endpunkte für externe Drittsysteme."),
            
            ("15.7 Design (Theme-Engine & Corporate Identity):",
             "Steuert das visuelle Erscheinungsbild von Archon OS: Umschaltung zwischen Dark- und Light-Theme, Upload des Firmenlogos (für Kopfzeile und PDF-Exporte) sowie Definition der Primär- und Akzentfarben. Änderungen synchronisieren sich nahtlos mit dem Visual CSS Live Studio.")
        ]
        
        for sub_title, sub_text in subsections:
            p_s = doc.add_paragraph()
            p_s.style = "Normal"
            set_p_spacing(p_s, 6, 2, 1.15)
            r_st = p_s.add_run(sub_title + "\n")
            set_run_font(r_st, "Aptos", 10.5, (26, 54, 93), bold=True)
            r_tx = p_s.add_run(sub_text)
            set_run_font(r_tx, "Aptos", 10.0, (45, 55, 72))
            ch15_elements.append(p_s)
            
        # Table of Settings Tabs
        p_tbl_lbl = doc.add_paragraph()
        p_tbl_lbl.style = "Normal"
        set_p_spacing(p_tbl_lbl, 8, 2, 1.15)
        r_tbl_lbl = p_tbl_lbl.add_run("Tabelle 15.1: Übersicht der 7 Einstellungsbereiche im System Control Center")
        set_run_font(r_tbl_lbl, "Aptos", 9.5, (43, 108, 176), bold=True)
        ch15_elements.append(p_tbl_lbl)
        
        tab_headers = ["Reiter / Bereich", "Zuständigkeit & Funktionen", "Standard-Konfiguration"]
        tab_data = [
            ["Hermes Core", "Kernel-Scheduler, Watchdog (120s), Model Quick-Select, YAML-Editor", "Port 8420, Tickless Sleep aktiv"],
            ["Container & Dienste", "Überwachung der 11 Docker-Container, Service-Restart, Cache-Reset", "11/11 Dienste nominal im Mesh"],
            ["Provider & Gateway", "API-Keys für OpenRouter, Gemini, Groq, Anthropic; Latenzprüfung", "OmniRoute AI Router (Port 8000)"],
            ["Methodiken", "Verwaltung von 35 Analyse- & Prompt-Frameworks; eigene SOPs anlegen", "35 Standard Base Frameworks"],
            ["Plugins & MCP", "FastMCP-Treiber (Filesystem, Web-Search, CRM, Tools), Scopes", "Read-Only default, Schreibschutz aktiv"],
            ["Kommunikation", "Telegram-Bot-Token, Chat-IDs, CRM-Mail-Sync (IMAP), Webhooks", "Telegram Polling aktiv, HITL-Notruf"],
            ["Design", "Dark/Light Theme, Firmenlogo-Upload, Farbschemata, CSS-Sync", "Archon Slate Dark Mode aktiv"]
        ]
        tbl_settings = create_styled_table(doc, tab_headers, tab_data, [1.6, 2.7, 2.5])
        
        # Praxis-Workflow
        p_wf_head = doc.add_paragraph()
        p_wf_head.style = "Normal"
        set_p_spacing(p_wf_head, 8, 2, 1.15)
        r_wf_head = p_wf_head.add_run("Praxis-Workflow (Schritt für Schritt):")
        set_run_font(r_wf_head, "Aptos", 10.5, (26, 54, 93), bold=True)
        ch15_elements.append(p_wf_head)
        
        wf_steps = [
            "1. Öffne das System Control Center über das Zahnrad-Symbol in der Kopfzeile oder über die Tastenkombination.",
            "2. Wähle im Reiter 'Provider & Gateway' deinen bevorzugten LLM-Anbieter und hinterlege den entsprechenden API-Schlüssel.",
            "3. Überprüfe im Reiter 'Container & Dienste', ob alle 11 Kernkomponenten nominal laufen.",
            "4. Schalte im Reiter 'Plugins' die benötigten MCP-Werkzeuge für deine Agenten frei.",
            "5. Hinterlege im Reiter 'Kommunikation' deinen Telegram-Bot-Token, um Archon OS von unterwegs per Smartphone zu steuern."
        ]
        for step in wf_steps:
            p_step = doc.add_paragraph()
            p_step.style = "Normal"
            set_p_spacing(p_step, 1, 2, 1.15)
            r_step = p_step.add_run(step)
            set_run_font(r_step, "Aptos", 10.0, (45, 55, 72))
            ch15_elements.append(p_step)
            
        # Praxistipp
        p_tip = doc.add_paragraph()
        p_tip.style = "Normal"
        set_p_spacing(p_tip, 6, 4, 1.15)
        r_tip = p_tip.add_run("💡 Praxistipp & Leitplanke: ")
        set_run_font(r_tip, "Aptos", 9.5, (43, 108, 176), bold=True)
        r_tip_t = p_tip.add_run("Nutze nach jeder Änderung an Provider-Schlüsseln oder Container-Zuweisungen den 'Test'-Button im jeweiligen Reiter, bevor du die Änderungen live in den Produktionsbetrieb übernimmst. Für tiefgreifende Kernel-Anpassungen steht im Reiter 'Hermes Core' jederzeit der YAML-Live-Editor mit automatischer Backup-Erstellung bereit.")
        set_run_font(r_tip_t, "Aptos", 9.5, (45, 55, 72))
        ch15_elements.append(p_tip)
        
        # Prompt callout box
        tbl_prompt = create_callout_box(
            doc,
            "🤖 Beispiel-Befehl / Prompt an den Assistenten für diesen Bereich:",
            '"Öffne das System Control Center und zeige mir den Status der Container sowie den aktuell eingestellten Standard-Provider im Hermes Core."'
        )
        
        # Insert all ch15_elements before p_anhang
        for el in ch15_elements:
            p_anhang._p.addprevious(el._p)
            
        p_anhang._p.addprevious(tbl_settings._tbl)
        
        p_sep2 = doc.add_paragraph()
        set_p_spacing(p_sep2, 4, 8, 1.15)
        p_anhang._p.addprevious(p_sep2._p)
        
        p_anhang._p.addprevious(tbl_prompt._tbl)
        
        p_sep3 = doc.add_paragraph()
        set_p_spacing(p_sep3, 8, 14, 1.15)
        p_anhang._p.addprevious(p_sep3._p)
        
        print("Successfully inserted Chapter 15 before ANHANG.")

    doc.save(DOC_PATH)
    print("Document successfully updated and saved to:", DOC_PATH)

if __name__ == "__main__":
    main()
