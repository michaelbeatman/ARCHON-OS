# -*- coding: utf-8 -*-
"""
Updates docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx:
1. Fixes subsection numbering in Chapter 18 (15.1..15.9 -> 18.1..18.9)
2. Adds 18.10 (Settings-Paket A: Gruppen 1-5) and 18.11 (Settings-Paket B: Gruppen 6-10)
   plus Table 18.2 documenting all 10 configurable Autonomy & Resilience groups.
3. Appends Glossary Item 88 (Zentrale Autonomie- & Schwellenwert-Steuerung) in the exact box layout.
"""

import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

DOC_PATH = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"

def set_run_font(run, font_name="Aptos", size_pt=10.0, color_rgb=(45, 55, 72), bold=False, italic=False):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.color.rgb = RGBColor(*color_rgb)
    run.bold = bold
    run.italic = italic

def set_p_spacing(p, before_pt=0, after_pt=4, line_spacing=1.15):
    p.paragraph_format.space_before = Pt(before_pt)
    p.paragraph_format.space_after = Pt(after_pt)
    p.paragraph_format.line_spacing = line_spacing

def create_styled_table(doc, headers, data, col_widths=None):
    tbl = doc.add_table(rows=len(data) + 1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False

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
            tcPr.append(parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                f'  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                f'  <w:left w:val="none"/><w:right w:val="none"/>'
                f'</w:tcBorders>'
            ))
            p = cell.paragraphs[0]
            set_p_spacing(p, 2, 2, 1.1)
            r = p.add_run(val)
            set_run_font(r, "Aptos", 9.0, (45, 55, 72))

    return tbl

def create_glossary_box(doc, title_str, problem_str, mechanik_str, nutzen_str):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    cell = tbl.rows[0].cells[0]
    cell.width = Inches(6.8)

    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>'))
    tcPr.append(parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'  <w:top w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        f'  <w:left w:val="single" w:sz="24" w:space="0" w:color="1A365D"/>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        f'  <w:right w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        f'</w:tcBorders>'
    ))
    tcPr.append(parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'  <w:top w:w="120" w:type="dxa"/><w:left w:w="160" w:type="dxa"/>'
        f'  <w:bottom w:w="120" w:type="dxa"/><w:right w:w="160" w:type="dxa"/>'
        f'</w:tcMar>'
    ))

    p0 = cell.paragraphs[0]
    set_p_spacing(p0, 2, 3, 1.15)
    r_title = p0.add_run(title_str)
    set_run_font(r_title, "Aptos", 10.0, (26, 54, 93), bold=True)

    for label, content in [("Problem: ", problem_str), ("Mechanik: ", mechanik_str), ("Nutzen: ", nutzen_str)]:
        p = cell.add_paragraph()
        set_p_spacing(p, 1, 2, 1.15)
        r_lbl = p.add_run(label)
        set_run_font(r_lbl, "Aptos", 9.0, (43, 108, 176), bold=True)
        r_txt = p.add_run(content)
        set_run_font(r_txt, "Aptos", 9.0, (45, 55, 72), bold=False)

    return tbl

def main():
    doc = Document(DOC_PATH)

    # Check if already updated
    for p in doc.paragraphs:
        if "18.10 Autonome Kernel-, Resilienz-" in p.text:
            print("Chapter 18 already contains 18.10. Skipping duplicate insert.")
            return

    # 1. Fix 15.1..15.9 -> 18.1..18.9 in Chapter 18 and find anchor paragraph
    p_anchor = None
    for i, p in enumerate(doc.paragraphs):
        for sub in range(1, 10):
            prefix = f"15.{sub} "
            if p.text.startswith(prefix):
                for r in p.runs:
                    if prefix in r.text:
                        r.text = r.text.replace(prefix, f"18.{sub} ", 1)
                        break
        if p.text.startswith("Tabelle 15.1:"):
            for r in p.runs:
                if "Tabelle 15.1:" in r.text:
                    r.text = r.text.replace("Tabelle 15.1:", "Tabelle 18.1:")
        if p.text.startswith("Praxis-Workflow (Schritt für Schritt):") and i > 630 and i < 660:
            p_anchor = p

    if p_anchor is not None:
        # Insert 18.10 and 18.11 + Table 18.2 right before Praxis-Workflow in Chapter 18
        sections = [
            ("18.10 Autonome Kernel-, Resilienz-, Sandbox- & Debugger-Steuerung (Settings-Paket A: Gruppen 1–5):\n",
             "Im Reiter 'Hermes Core' (Abschnitt 7) lassen sich alle Hintergrund-Wächter der Ausführungs-Engine einzeln ein-/ausschalten und über Schwellenwerte kalibrieren: "
             "(1) Concurrency & Deadlock-Wächter (Max Worker 1–16, Queue-Timeout, Stagnations-Limit in Sekunden, Auto-Recovery), "
             "(2) Loop-Killer, Circuit-Breaker & Token-Clipper (Max identische Runden, Jaccard-Ähnlichkeitsschwelle 0.70–0.99, Max Schritte pro Task), "
             "(3) Autonome Task-Selbstheilung & Git-Rollback (Hauptschalter, Auto-Git-Rollback bei Crash, Max Reparaturversuche 1–10, Reparatur-Modell), "
             "(4) Ephemeral Docker Sandbox (Isolations-Zwang, RAM-Limit in MB, CPU-Kerne, Timeout in Sekunden, Netzwerksperre) sowie "
             "(5) Time-Travel Debugger & Pre-Write Snapshots (Step-Tracing aktiv, automatische Gzip-Snapshots vor Schreibzugriffen, Ringpuffer-Größe)."),
            ("18.11 Governance, Schiedsgericht, War-Room, SLAs & Flotten-Hygiene (Settings-Paket B: Gruppen 6–10):\n",
             "Abschnitt 8 im Reiter 'Hermes Core' bündelt alle Zero-Trust- und Qualitäts-Gates: "
             "(6) Konsens-Gate & Schiedsgericht (Freigabe-Pflicht ab Priorität P1–P3, Modus Dual-Critic vs. 3er-Rat, 2/3-Mehrheit vs. Einstimmigkeit), "
             "(7) Virtueller War-Room & Pre-Mortem (Hauptschalter, automatischer Stresstest vor P3-Releases, Blockade-Schwelle MEDIUM/HIGH/CRITICAL), "
             "(8) SLA-Verträge & Handoff-Desk (Mindest-Lieferlänge in Zeichen, Max Turnaround in Minuten, Auto-Reject bei unvollständigen Pflichtfeldern), "
             "(9) Inbox-Watcher & Proaktives Morgen-Standup (Scan-Intervall in Sekunden, tägliche Briefing-Uhrzeit) sowie "
             "(10) Flotten-Selbstheilung, DB-Backups, Secret-Masker & Browser-Audit (Auto-Container-Restart, Echtzeit-Secret-Schwärzung, Playwright Screenshot-Beweissicherung, SQLite-Backup-Rotation in Tagen).")
        ]

        for head_txt, body_txt in sections:
            p_sec = doc.add_paragraph()
            set_p_spacing(p_sec, 6, 4, 1.15)
            r_h = p_sec.add_run(head_txt)
            set_run_font(r_h, "Aptos", 10.0, (26, 54, 93), bold=True)
            r_b = p_sec.add_run(body_txt)
            set_run_font(r_b, "Aptos", 9.5, (45, 55, 72), bold=False)
            p_anchor._p.addprevious(p_sec._p)

        p_tbl_title = doc.add_paragraph()
        set_p_spacing(p_tbl_title, 8, 2, 1.15)
        r_tt = p_tbl_title.add_run("Tabelle 18.2: Die 10 steuerbaren Autonomie- & Resilienz-Gruppen (settings.json / API)")
        set_run_font(r_tt, "Aptos", 9.5, (43, 108, 176), bold=True)
        p_anchor._p.addprevious(p_tbl_title._p)

        headers = ["Gruppe & Modul", "Schalter (An/Aus)", "Regelbare Schwellenwerte & Parameter"]
        rows = [
            ["1. Concurrency & Deadlock", "auto_deadlock_recovery", "max_concurrent_agents (4), queue_timeout (60s), stagnation (45s)"],
            ["2. Loop-Killer & Clipper", "loop_detection, token_clipper", "max_identical_turns (3), jaccard_threshold (0.90), max_steps (15)"],
            ["3. Task-Selbstheilung", "enabled, auto_git_rollback", "max_attempts (3), escalation_model (deepseek/deepseek-chat)"],
            ["4. Ephemeral Sandbox", "enabled, network_enabled", "memory_limit_mb (512), cpu_limit (1.0), timeout_seconds (30)"],
            ["5. Time-Travel & Snapshots", "tracing_enabled, auto_snapshots", "max_snapshots (50), max_trace_steps (100)"],
            ["6. Konsens-Schiedsgericht", "enabled", "min_priority (P3), mode (tri_agent_council), majority (2/3 | 3/3)"],
            ["7. Virtueller War-Room", "enabled, auto_pre_mortem", "block_threshold (MEDIUM | HIGH | CRITICAL), default_model"],
            ["8. SLA-Verträge & Handoff", "enabled, auto_reject_incomplete", "min_content_length (100 Zeichen), max_turnaround_minutes (60)"],
            ["9. Inbox & Morgen-Standup", "enabled, standup_enabled", "interval_seconds (5s), standup_time (08:00 Uhr), watch_folder"],
            ["10. Flotte, DB & Hygiene", "auto_restart, secret_mask, audit", "db_backup_keep_days (7 Tage), visual_browser_audit (Screenshots)"]
        ]
        tbl_18_2 = create_styled_table(doc, headers, rows, [1.8, 2.0, 3.0])
        p_anchor._p.addprevious(tbl_18_2._tbl)

    # 2. Append Glossary item 88 at the end of the document
    box_88 = create_glossary_box(
        doc,
        "88. Zentrale Autonomie- & Schwellenwert-Steuerung (backend/autonomy_settings.py)",
        "Feste Schwellenwerte im Programmcode verhindern eine schnelle Anpassung von Sicherheits-, Sandbox- und Resilienz-Regeln im laufenden Betrieb.",
        "Bündelt alle 10 Autonomie-Gruppen (Concurrency, Loop-Killer, Selbstheilung, Docker-Sandbox, Time-Travel-Snapshots, Konsens-Gate, War-Room, SLA-Verträge, Inbox/Standup und Flotten-Hygiene) in settings.json und synchronisiert sie über GET/POST /api/settings/autonomy-modules mit dem System Control Center.",
        "Jedes Schutz- und Autonomie-Modul lässt sich zur Laufzeit per Klick ein- oder ausschalten und exakt auf das gewünschte Risiko- und Ressourcenprofil feinjustieren."
    )
    p_sp = doc.add_paragraph()
    set_p_spacing(p_sp, 2, 4, 1.15)

    doc.save(DOC_PATH)
    print("Successfully updated ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx!")

if __name__ == "__main__":
    main()
