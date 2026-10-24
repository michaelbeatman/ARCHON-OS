# -*- coding: utf-8 -*-
"""
Erweitert docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx um:
1. Kapitel 23: Zuverlässige Ausführung & Determinismus (Säule XIV — Paket 3: Features 11–15)
   inkl. Tabelle 23.1 direkt vor dem Komplett-Glossar.
2. Domäne XIV (Einträge 99–103) im Komplett-Glossar am Ende des Handbuchs im identischen Box-Design.
"""

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

    for p in doc.paragraphs:
        if "23. Zuverlässige Ausführung & Determinismus" in p.text:
            print("Chapter 23 already exists. Skipping duplicate insert.")
            return

    glossary_anchor = None
    for p in doc.paragraphs:
        if "Komplett-Glossar:" in p.text or ("Komplett-Glossar" in p.text and "Architektur-Enzyklopädie" in p.text):
            glossary_anchor = p
            break

    if glossary_anchor is not None:
        p_ch23 = doc.add_paragraph()
        set_p_spacing(p_ch23, 14, 6, 1.15)
        r_ch23 = p_ch23.add_run("23. Zuverlässige Ausführung & Determinismus / Durable Execution (Säule XIV — Paket 3)")
        set_run_font(r_ch23, "Aptos", 14.0, (26, 54, 93), bold=True)
        glossary_anchor._p.addprevious(p_ch23._p)

        p_intro = doc.add_paragraph()
        set_p_spacing(p_intro, 2, 6, 1.15)
        r_intro = p_intro.add_run(
            "Für produktionskritische Workflows müssen Agenten-Ausgaben streng typisiert sein, Langzeit-Prozesse auch über Neustarts hinweg "
            "fortgesetzt werden können und versehentliche Doppelausführungen ausgeschlossen sein. Säule XIV (Paket 3: Features 11–15) "
            "verankert diese fünf Durable-Execution-Garantien im Archon-Kernel und macht sie im System Control Center (Tab 'Hermes Core' -> Abschnitt 11) steuerbar."
        )
        set_run_font(r_intro, "Aptos", 10.0, (45, 55, 72))
        glossary_anchor._p.addprevious(p_intro._p)

        sub_items = [
            ("23.1 Structured Outputs & JSON-Schema-Garantie (backend/structured_output_enforcer.py): ",
             "Bereinigt fehlerhafte Modell-Ausgaben (Markdown-Fences, nachgestellte Kommata, fehlende schließende Klammern) automatisch und validiert "
             "sie gegen ein Pflichtfeld- und Typ-Schema inkl. automatischer Typ-Konvertierung und Default-Werten."),
            ("23.2 Durable Execution Checkpointing / Pause & Resume (backend/durable_checkpoint_manager.py): ",
             "Persistiert den exakten Fortschritt und Variablen-Zustand mehrstufiger Workflows nach jedem Schritt in SQLite ('durable_workflow_checkpoints'). "
             "Nach einem Container-Neustart oder Timeout setzt der Workflow nahtlos bei 'current_step_index + 1' auf."),
            ("23.3 Idempotency-Keys & Tool-Call-Deduplizierung (backend/idempotency_guard.py): ",
             "Berechnet für kritische Tool-Calls (E-Mail-Versand, Webhook, Buchung) einen deterministischen SHA-256-Payload-Hash ('idempotency_ledger'). "
             "Wiederholte Aufrufe innerhalb der Sperrfrist (Standard: 24h) werden blockiert und erhalten das gecachte Erstergebnis."),
            ("23.4 Dry-Run / Shadow-Mode für Agenten-Aufträge (backend/dry_run_simulator.py): ",
             "Fängt im Simulationsmodus alle schreibenden Datei-, Datenbank- und API-Operationen ab ('SHADOW_INTERCEPTED') und erstellt einen "
             "vollständigen Vorschau-Plan aller geplanten Mutationen bei 0 realen Seiteneffekten."),
            ("23.5 Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager (backend/dead_letter_queue.py): ",
             "Sammelt fehlgeschlagene Hintergrund-Jobs und Webhooks samt Fehler-Traceback in der Tabelle 'dead_letter_queue' und unterstützt "
             "automatische oder manuelle Replays mit exponentiellem Backoff (10s, 20s, 40s ...).")
        ]

        for title_s, body_s in sub_items:
            p_sub = doc.add_paragraph()
            set_p_spacing(p_sub, 4, 4, 1.15)
            rt = p_sub.add_run(title_s)
            set_run_font(rt, "Aptos", 10.0, (26, 54, 93), bold=True)
            rb = p_sub.add_run(body_s)
            set_run_font(rb, "Aptos", 9.5, (45, 55, 72))
            glossary_anchor._p.addprevious(p_sub._p)

        p_tbl_h = doc.add_paragraph()
        set_p_spacing(p_tbl_h, 6, 3, 1.15)
        r_th = p_tbl_h.add_run("Tabelle 23.1: Übersicht der Durable-Execution Module, Endpunkte & Settings (Paket 3)")
        set_run_font(r_th, "Aptos", 9.5, (43, 108, 176), bold=True)
        glossary_anchor._p.addprevious(p_tbl_h._p)

        headers = ["Modul / Datei", "REST-API Endpunkte", "Settings-Schalter & Schwellenwerte"]
        rows = [
            ["11. Structured Output Enforcer\n(backend/structured_output_enforcer.py)",
             "POST /api/execution/structured-output",
             "enabled (True), auto_repair_json (True),\nstrict_schema_validation (True), max_attempts (2)"],
            ["12. Durable Checkpoint Manager\n(backend/durable_checkpoint_manager.py)",
             "POST /api/execution/checkpoints/save\nGET /api/execution/checkpoints/resume/{id}\nGET /api/execution/checkpoints/list",
             "enabled (True), checkpoint_every_n_steps (1),\nauto_resume_on_boot (True), retention_days (14)"],
            ["13. Idempotency Guard\n(backend/idempotency_guard.py)",
             "POST /api/execution/idempotency/check",
             "enabled (True), block_duplicate_side_effects (True),\nttl_hours (24h)"],
            ["14. Dry-Run / Shadow Simulator\n(backend/dry_run_simulator.py)",
             "POST /api/execution/dry-run",
             "enabled (False), intercept_write_tools (True),\nintercept_external_apis (True), log_diffs (True)"],
            ["15. Dead-Letter-Queue (DLQ)\n(backend/dead_letter_queue.py)",
             "POST /api/execution/dlq/enqueue\nPOST /api/execution/dlq/replay\nGET /api/execution/dlq/list",
             "enabled (True), auto_replay_enabled (True),\nmax_replay_retries (3), backoff_base_seconds (10s)"]
        ]
        tbl_23 = create_styled_table(doc, headers, rows, [2.1, 2.3, 2.4])
        glossary_anchor._p.addprevious(tbl_23._tbl)

    # Append Domäne XIV (99–103) at the end of the Glossary
    p_dom = doc.add_paragraph()
    set_p_spacing(p_dom, 12, 4, 1.15)
    r_dom = p_dom.add_run("Domäne XIV: Zuverlässige Ausführung & Determinismus / Durable Execution (Paket 3)")
    set_run_font(r_dom, "Aptos", 11.5, (26, 54, 93), bold=True)

    glossary_items = [
        ("99. Structured Outputs & JSON-Schema-Garantie (backend/structured_output_enforcer.py)",
         "Sprachmodelle liefern manchmal ungültiges JSON (Markdown-Rahmen, fehlende Klammern oder falsche Datentypen), wodurch nachgelagerte Code-Pipelines abstürzen.",
         "Repariert Syntaxfehler im Roh-String automatisch und erzwingt alle Pflichtfelder und Datentypen des übergebenen Ziel-Schemas.",
         "Garantiert 100 % maschinenlesbare, typensichere JSON-Payloads zwischen Agenten und Backend-Schnittstellen."),
        ("100. Durable Execution Checkpointing / Pause & Resume (backend/durable_checkpoint_manager.py)",
         "Bricht ein 10-schrittiger Recherche- oder Build-Auftrag bei Schritt 8 durch einen Neustart ab, mussten bisher alle 7 Vorarbeiten teuer wiederholt werden.",
         "Sichert nach jedem abgeschlossenen Schritt den kompletten Variablen- und Fortschrittszustand transaktional in SQLite.",
         "Unterbrochene Langläufer setzen exakt am letzten gültigen Checkpoint wieder auf, ohne Arbeit oder Tokens doppelt zu verbrauchen."),
        ("101. Idempotency-Keys & Tool-Call-Deduplizierung (backend/idempotency_guard.py)",
         "Bei Netzwerk-Retries oder Agenten-Schleifen besteht die Gefahr, dass dieselbe E-Mail, Rechnung oder Webhook-Aktion mehrfach ausgelöst wird.",
         "Vergibt für jeden mutierenden Tool-Call einen SHA-256-Idempotency-Key im SQLite-Ledger und blockiert identische Folgeaufrufe innerhalb der TTL.",
         "Verhindert doppelte Außenwirkungen zuverlässig nach dem Vorbild moderner Zahlungs-Gateways (Stripe-Prinzip)."),
        ("102. Dry-Run / Shadow-Mode für Agenten-Aufträge (backend/dry_run_simulator.py)",
         "Neue oder komplexe Agenten-Aufträge möchte man vor der scharfen Ausführung oft erst ohne Risiko an echten Produktionsdaten testen.",
         "Fängt im Shadow-Mode alle schreibenden Datei-, Datenbank- und API-Befehle ab und protokolliert stattdessen einen detaillierten Mutations-Vorschauplan.",
         "Ermöglicht gefahrlose Trockenübungen und Risiko-Audits vor der endgültigen Freigabe."),
        ("103. Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager (backend/dead_letter_queue.py)",
         "Fehlgeschlagene Webhooks oder asynchrone Hintergrund-Jobs gehen bei kurzzeitigen Drittanbieter-Ausfällen ohne Auffangbecken spurlos verloren.",
         "Speichert jeden gescheiterten Job samt Original-Payload und Fehlergrund in der DLQ-Tabelle und wiederholt ihn mit exponentiellem Backoff.",
         "Kein Auftrag geht verloren; fehlgeschlagene Tasks lassen sich jederzeit einzeln oder gesammelt erneut abspielen.")
    ]

    for title_g, prob_g, mech_g, nutz_g in glossary_items:
        create_glossary_box(doc, title_g, prob_g, mech_g, nutz_g)
        p_sp = doc.add_paragraph()
        set_p_spacing(p_sp, 2, 4, 1.15)

    doc.save(DOC_PATH)
    print("Successfully added Chapter 23 and Glossary items 99-103 to ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx!")


if __name__ == "__main__":
    main()
