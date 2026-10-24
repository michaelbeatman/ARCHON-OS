# -*- coding: utf-8 -*-
"""
Erweitert docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx um:
1. Kapitel 25: Selbst-Optimierung, Evaluation & Schwarm-Intelligenz (Säule XVI — Paket 5: Features 21–25)
   inkl. Tabelle 25.1 direkt vor dem Komplett-Glossar.
2. Domäne XVI (Einträge 109–113) im Komplett-Glossar am Ende des Handbuchs im identischen Box-Design.
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
        if "25. Selbst-Optimierung, Evaluation & Schwarm-Intelligenz" in p.text:
            print("Chapter 25 already exists. Skipping duplicate insert.")
            return

    glossary_anchor = None
    for p in doc.paragraphs:
        if "Komplett-Glossar:" in p.text or ("Komplett-Glossar" in p.text and "Architektur-Enzyklopädie" in p.text):
            glossary_anchor = p
            break

    if glossary_anchor is not None:
        p_ch25 = doc.add_paragraph()
        set_p_spacing(p_ch25, 14, 6, 1.15)
        r_ch25 = p_ch25.add_run("25. Selbst-Optimierung, Evaluation & Schwarm-Intelligenz (Säule XVI — Paket 5)")
        set_run_font(r_ch25, "Aptos", 14.0, (26, 54, 93), bold=True)
        glossary_anchor._p.addprevious(p_ch25._p)

        p_intro = doc.add_paragraph()
        set_p_spacing(p_intro, 2, 6, 1.15)
        r_intro = p_intro.add_run(
            "Den Abschluss der 25 State-of-the-Art-Erweiterungen bildet Säule XVI (Paket 5: Features 21–25). "
            "Sie befähigt Archon OS, aus Fehlern automatisch präzisere System-Prompts abzuleiten, neue Konfigurationen "
            "vorab gegen Gold-Standard-Testfälle zu prüfen, Modelle nach Echtzeit-Erfolgsquote zu routen, temporäre "
            "Spezialisten-Teams zu bilden und den Host-Server vor Ressourcen-Überlastung zu schützen (System Control Center -> Abschnitt 13)."
        )
        set_run_font(r_intro, "Aptos", 10.0, (45, 55, 72))
        glossary_anchor._p.addprevious(p_intro._p)

        sub_items = [
            ("25.1 Automatischer Prompt-Optimizer nach DSPy/TextGrad-Prinzip (backend/prompt_optimizer.py): ",
             "Analysiert ab min_failures_to_trigger (Standard: 3) fehlgeschlagene Aufträge einer Agentenrolle, diagnostiziert die "
             "Schwachstellen (z. B. JSON-Syntax, Pfadfehler, fehlende Quellenbelege) und generiert gezielte Guardrail-Direktiven."),
            ("25.2 Gold-Standard Regression-Test-Suite / Eval-Runner (backend/eval_regression_runner.py): ",
             "Prüft Prompt- oder Modell-Updates gegen hinterlegte Referenzfälle ('eval_gold_cases') auf erwartete Pflichtbegriffe "
             "und verbotene Ausgaben. Fällt die Bestehensquote unter min_pass_rate_pct (Standard: 90 %), wird das Update blockiert."),
            ("25.3 Multi-Armed Bandit Modell-Router (backend/bandit_model_router.py): ",
             "Berechnet aus realen Erfolgsquoten und Antwortlatenzen in 'bandit_model_stats' laufend den Bandit-Reward-Score "
             "jedes Sprachmodells und routet Aufträge bevorzugt auf den aktuell zuverlässigsten und schnellsten Provider."),
            ("25.4 Dynamisches Ephemeral-Team-Spawning (backend/ephemeral_team_spawner.py): ",
             "Stellt für vielschichtige Missionen automatisch eine temporäre Task-Force aus bis zu max_team_size (Standard: 4) "
             "Spezialisten (Security Auditor, UI Engineer, DB Architect, QA Verifier) zusammen und löst das Team nach Abschluss wieder auf."),
            ("25.5 Live-Ressourcen-Protector & Host-Backpressure (backend/resource_backpressure.py): ",
             "Überwacht CPU-Auslastung (max_cpu_pct: 85 %), RAM-Belegung (max_ram_pct: 85 %) und freien Festplattenspeicher (min_free_disk_gb: 2.0 GB). "
             "Bei Lastspitzen schaltet das System automatisch auf Backpressure ('pause_low_priority'), um Systemabstürze zu verhindern.")
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
        r_th = p_tbl_h.add_run("Tabelle 25.1: Übersicht der Selbst-Optimierungs- & Schwarm-Module, Endpunkte & Settings (Paket 5)")
        set_run_font(r_th, "Aptos", 9.5, (43, 108, 176), bold=True)
        glossary_anchor._p.addprevious(p_tbl_h._p)

        headers = ["Modul / Datei", "REST-API Endpunkte", "Settings-Schalter & Schwellenwerte"]
        rows = [
            ["21. Prompt-Optimizer (TextGrad)\n(backend/prompt_optimizer.py)",
             "POST /api/evolution/optimize-prompt",
             "enabled (True), min_failures_to_trigger (3),\nauto_apply_patches (False), max_rules (5)"],
            ["22. Eval-Regression-Suite\n(backend/eval_regression_runner.py)",
             "POST /api/evolution/eval-suite/run",
             "enabled (True), min_pass_rate_pct (90%),\nblock_deploy_on_regression (True)"],
            ["23. Bandit Modell-Router\n(backend/bandit_model_router.py)",
             "POST /api/router/bandit-outcome\nGET /api/router/bandit-select",
             "enabled (True), exploration_epsilon (0.15),\nsuccess_weight (0.60), latency_weight (0.40)"],
            ["24. Ephemeral Team Spawner\n(backend/ephemeral_team_spawner.py)",
             "POST /api/swarm/spawn-ephemeral-team",
             "enabled (True), max_team_size (4),\nauto_dissolve_on_complete (True)"],
            ["25. Resource Backpressure\n(backend/resource_backpressure.py)",
             "GET /api/system/resource-backpressure",
             "enabled (True), max_cpu_pct (85%),\nmax_ram_pct (85%), min_free_disk_gb (2.0 GB)"]
        ]
        tbl_25 = create_styled_table(doc, headers, rows, [2.1, 2.3, 2.4])
        glossary_anchor._p.addprevious(tbl_25._tbl)

    # Append Domäne XVI (109–113) at the end of the Glossary
    p_dom = doc.add_paragraph()
    set_p_spacing(p_dom, 12, 4, 1.15)
    r_dom = p_dom.add_run("Domäne XVI: Selbst-Optimierung, Evaluation & Schwarm-Intelligenz (Paket 5)")
    set_run_font(r_dom, "Aptos", 11.5, (26, 54, 93), bold=True)

    glossary_items = [
        ("109. Automatischer Prompt-Optimizer nach DSPy/TextGrad-Prinzip (backend/prompt_optimizer.py)",
         "Statische System-Prompts wiederholen dieselben Fehler immer wieder, solange kein Mensch manuell nachbessert.",
         "Wertet reale Fehler-Logs einer Rolle aus, erkennt systematische Schwächen und generiert gezielte Guardrail-Zusatzregeln für den System-Prompt.",
         "Agenten lernen kontinuierlich aus gescheiterten Läufen und härten ihre Instruktionen selbstständig."),
        ("110. Gold-Standard Regression-Test-Suite / Eval-Runner (backend/eval_regression_runner.py)",
         "Eine vermeintlich kleine Änderung am System-Prompt oder Modell kann bestehende Sicherheits- oder Formatregeln unbemerkt verschlechtern.",
         "Führt vor der Übernahme neuer Einstellungen automatisierte Gold-Standard-Testfälle aus und prüft Bestehensquote sowie verbotene Muster.",
         "Verhindert Qualitäts-Regressionen im Produktivbetrieb durch ein objektives Quality-Gate."),
        ("111. Multi-Armed Bandit Modell-Router (backend/bandit_model_router.py)",
         "Feste Modell-Zuweisungen reagieren nicht darauf, wenn ein Cloud-Provider plötzlich langsamer wird oder erhöhte Fehlerraten zeigt.",
         "Bepunktet jedes Modell laufend nach realer Erfolgsquote (60 %) und Geschwindigkeit (40 %) und wählt dynamisch den besten Kandidaten.",
         "Maximiert Antwortqualität und Tempo automatisch anhand echter Laufzeit-Telemetrie."),
        ("112. Dynamisches Ephemeral-Team-Spawning (backend/ephemeral_team_spawner.py)",
         "Ein einzelner Generalisten-Agent ist bei großen Querschnittsaufgaben (Architektur + UI + Security + QA) schnell überfordert.",
         "Rekrutiert passend zum Missions-Briefing eine temporäre Spezialisten-Task-Force und löst sie nach erledigter Mission wieder auf.",
         "Bündelt Spezialwissen bedarfsgerecht ohne dauerhaften Ressourcen-Overhead."),
        ("113. Live-Ressourcen-Protector & Host-Backpressure (backend/resource_backpressure.py)",
         "Parallele Container, Browser-Audits und lokale Prozesse können bei Lastspitzen den Host-RAM oder die CPU überlasten (OOM-Kill).",
         "Überwacht CPU-, RAM- und Disk-Metriken in Echtzeit und drosselt niedrig priorisierte Hintergrund-Tasks ab 85 % Auslastung automatisch.",
         "Schützt den Server zuverlässig vor Abstürzen durch Überlastung und hält kritische Kernprozesse jederzeit reaktionsfähig.")
    ]

    for title_g, prob_g, mech_g, nutz_g in glossary_items:
        create_glossary_box(doc, title_g, prob_g, mech_g, nutz_g)
        p_sp = doc.add_paragraph()
        set_p_spacing(p_sp, 2, 4, 1.15)

    doc.save(DOC_PATH)
    print("Successfully added Chapter 25 and Glossary items 109-113 to ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx!")


if __name__ == "__main__":
    main()
