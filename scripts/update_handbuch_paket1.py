# -*- coding: utf-8 -*-
"""
Erweitert docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx um:
1. Kapitel 21: Performance-Core, Durchsatz-Skalierung & Token-Effizienz (Säule XII — Paket 1: Features 1–5)
   inkl. Tabelle 21.1 direkt vor dem Komplett-Glossar.
2. Domäne XII (Einträge 89–93) im Komplett-Glossar am Ende des Handbuchs im identischen Box-Design.
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
        if "21. Performance-Core, Durchsatz-Skalierung & Token-Effizienz" in p.text:
            print("Chapter 21 already exists. Skipping duplicate insert.")
            return

    # Find anchor before Komplett-Glossar
    glossary_anchor = None
    for p in doc.paragraphs:
        if "Komplett-Glossar:" in p.text or "Komplett-Glossar" in p.text and "Architektur-Enzyklopädie" in p.text:
            glossary_anchor = p
            break

    if glossary_anchor is not None:
        # Heading Chapter 21
        p_ch21 = doc.add_paragraph()
        set_p_spacing(p_ch21, 14, 6, 1.15)
        r_ch21 = p_ch21.add_run("21. Performance-Core, Durchsatz-Skalierung & Token-Effizienz (Säule XII — Paket 1)")
        set_run_font(r_ch21, "Aptos", 14.0, (26, 54, 93), bold=True)
        glossary_anchor._p.addprevious(p_ch21._p)

        p_intro = doc.add_paragraph()
        set_p_spacing(p_intro, 2, 6, 1.15)
        r_intro = p_intro.add_run(
            "Um Archon OS bei hoher Agentenlast maximal schnell, skalierbar und kosteneffizient zu betreiben, "
            "ergänzt Säule XII (Paket 1: Features 1–5) fünf Hochleistungs-Mechanismen auf Kernel-, Router- und Datenbankebene. "
            "Alle fünf Module sind im System Control Center (Tab 'Hermes Core' -> Abschnitt 9) einzeln schaltbar und über Schwellenwerte steuerbar."
        )
        set_run_font(r_intro, "Aptos", 10.0, (45, 55, 72))
        glossary_anchor._p.addprevious(p_intro._p)

        sub_items = [
            ("21.1 Semantisches Prompt- & Response-Caching (backend/semantic_cache.py): ",
             "Speichert normalisierte Prompts samt L2-normiertem Wort-/3-Gramm-Frequenzvektor in der SQLite-Tabelle 'semantic_response_cache'. "
             "Erreicht eine neue Anfrage eine Cosine-Ähnlichkeit >= similarity_threshold (Standard: 0.95), liefert der Cache die Antwort in unter 10 Millisekunden bei 0 Token-Kosten."),
            ("21.2 Paralleles Map-Reduce Sub-Tasking / Fan-Out & Fan-In (backend/map_reduce_executor.py): ",
             "Zerlegt große Mehrfach-Aufgaben (Dokument-Batches, Code-Dateien, Prüflisten) ab auto_fan_out_min_items (Standard: 3) in parallele Worker-Coroutinen, "
             "gesteuert über eine asyncio.Semaphore(max_parallel_workers, Standard: 4), und führt die Teilergebnisse im Reduce-Schritt zusammen."),
            ("21.3 Speculative Fast-Routing & Latenz-Hedging (backend/speculative_hedger.py): ",
             "Überwacht die Antwortzeit des primären LLM-Modells. Überschreitet der Call hedge_delay_seconds (Standard: 2.5s), startet das System automatisch einen "
             "parallelen Hedge-Request an das schnelle Fallback-Modell (z. B. deepseek/deepseek-chat). Die schnellere Antwort gewinnt, der langsamere Task wird abgebrochen."),
            ("21.4 Dynamisches Context-Compaction & Hierarchisches Summarizing (backend/context_compactor.py): ",
             "Verdichtet lange Sitzungsverläufe ab trigger_token_threshold (Standard: 6.000 Tokens) automatisch in einen strukturierten [HIERARCHICAL_MEMORY_STATE]-Block "
             "(Ziele, Entscheidungen, Dateipfade, Fehler/Fixes), während die jüngsten keep_recent_turns (Standard: 4) unverändert bleiben. Spart 65–80 % Kontext-Tokens."),
            ("21.5 SQLite WAL Connection-Pool & Async Write-Batching (backend/async_write_batcher.py): ",
             "Puffert hochfrequente Telemetrie-, Trace- und Audit-Events im RAM und schreibt sie gebündelt (batch_size Standard: 25 oder nach flush_interval_seconds Standard: 2.0s) "
             "in einer einzigen SQLite-WAL-Transaktion auf die Festplatte. Reduziert Disk-I/O und Datenbank-Sperren um rund 80 %.")
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
        r_th = p_tbl_h.add_run("Tabelle 21.1: Übersicht der Performance-Core Module, Endpunkte & Settings (Paket 1)")
        set_run_font(r_th, "Aptos", 9.5, (43, 108, 176), bold=True)
        glossary_anchor._p.addprevious(p_tbl_h._p)

        headers = ["Modul / Datei", "REST-API Endpunkte", "Settings-Schalter & Schwellenwerte"]
        rows = [
            ["1. Semantic Cache\n(backend/semantic_cache.py)",
             "POST /api/cache/semantic-lookup\nPOST /api/cache/semantic-store\nGET /api/cache/semantic-stats",
             "enabled (True), similarity_threshold (0.95),\nttl_hours (24h), max_entries (500)"],
            ["2. Map-Reduce Executor\n(backend/map_reduce_executor.py)",
             "POST /api/execution/map-reduce\nGET /api/execution/map-reduce/history",
             "enabled (True), max_parallel_workers (4),\nchunk_timeout_seconds (30s), min_items (3)"],
            ["3. Speculative Hedger\n(backend/speculative_hedger.py)",
             "POST /api/router/hedged-completion\nGET /api/router/hedged-stats",
             "enabled (True), hedge_delay_seconds (2.5s),\nfallback_model (deepseek/deepseek-chat)"],
            ["4. Context Compactor\n(backend/context_compactor.py)",
             "POST /api/memory/compact-context",
             "enabled (True), trigger_token_threshold (6000),\nkeep_recent_turns (4), ratio (0.30)"],
            ["5. Async Write-Batcher\n(backend/async_write_batcher.py)",
             "POST /api/system/write-batcher/enqueue\nPOST /api/system/write-batcher/flush\nGET /api/system/write-batcher/stats",
             "enabled (True), batch_size (25 Events),\nflush_interval_seconds (2.0s), max_queue (1000)"]
        ]
        tbl_21 = create_styled_table(doc, headers, rows, [2.0, 2.3, 2.5])
        glossary_anchor._p.addprevious(tbl_21._tbl)

    # Append Domäne XII (89–93) at the end of the Glossary
    p_dom = doc.add_paragraph()
    set_p_spacing(p_dom, 12, 4, 1.15)
    r_dom = p_dom.add_run("Domäne XII: Performance-Core, Durchsatz-Skalierung & Token-Effizienz (Paket 1)")
    set_run_font(r_dom, "Aptos", 11.5, (26, 54, 93), bold=True)

    glossary_items = [
        ("89. Semantisches Prompt- & Response-Caching (backend/semantic_cache.py)",
         "Wiederkehrende oder leicht umformulierte Agenten-Anfragen verursachen unnötige LLM-API-Kosten und sekundenlange Wartezeiten.",
         "Berechnet für jeden Prompt einen SHA-256-Hash sowie einen L2-normalisierten Wort-/3-Gramm-Vektor in SQLite und liefert bei einer Cosine-Ähnlichkeit >= 0.95 sofort den gespeicherten Response-Treffer.",
         "Antwortzeiten unter 10 Millisekunden und 100 % Token-Ersparnis bei semantisch identischen Anfragen."),
        ("90. Paralleles Map-Reduce Sub-Tasking / Fan-Out & Fan-In (backend/map_reduce_executor.py)",
         "Sequenzielle Abarbeitung vieler Einzeldokumente oder Teilfragen führt zu linearem Zeitwachstum und langen Wartezeiten.",
         "Teilt Listen-Aufträge automatisch auf bis zu N parallele Asyncio-Worker (Semaphore-gesteuert) auf und führt die Teilergebnisse im Reduce-Schritt zusammen.",
         "Vervielfacht den Durchsatz bei Dokumenten-, Recherche- und Code-Batch-Analysen ohne Überlastung der Event-Loop."),
        ("91. Speculative Fast-Routing & Latenz-Hedging (backend/speculative_hedger.py)",
         "Einzelne langsame Cloud-Requests (Tail-Latency-Spikes) blockieren die gesamte Agenten-Ausführung.",
         "Startet nach Ablauf von hedge_delay_seconds (z. B. 2.5s) automatisch einen parallelen Ersatz-Call auf einem schnellen Fallback-Modell und übernimmt das zuerst eintreffende Ergebnis.",
         "Eliminiert Hänger durch langsame API-Endpunkte und stabilisiert die Antwortzeiten im 99. Perzentil."),
        ("92. Dynamisches Context-Compaction & Hierarchisches Summarizing (backend/context_compactor.py)",
         "Lange Agenten-Sitzungen blähen das Kontextfenster auf, verlangsamen den Prompt-Prefill und erhöhen die Kosten pro Turn drastisch.",
         "Extrahiert ab einem einstellbaren Token-Schwellenwert alle harten Fakten (Ziele, Dateipfade, Entscheidungen, Fehler) in einen kompakten [HIERARCHICAL_MEMORY_STATE]-Block und behält nur die jüngsten Runden im Volltext.",
         "Spart 65–80 % Kontext-Tokens bei langen Sessions ohne Verlust wichtiger Projektdaten."),
        ("93. SQLite WAL Connection-Pool & Async Write-Batching (backend/async_write_batcher.py)",
         "Hunderte einzelne SQLite-INSERTs bei parallelen Agenten-Läufen erzeugen Disk-I/O-Spitzen und 'database is locked'-Konflikte.",
         "Sammelt Telemetrie- und Audit-Ereignisse in einem Thread-sicheren RAM-Ringpuffer und schreibt sie gebündelt via executemany() im WAL-Modus.",
         "Reduziert Festplatten-Schreibzugriffe um rund 80 % und hält die Haupt-Event-Loop frei von Blockaden.")
    ]

    for title_g, prob_g, mech_g, nutz_g in glossary_items:
        create_glossary_box(doc, title_g, prob_g, mech_g, nutz_g)
        p_sp = doc.add_paragraph()
        set_p_spacing(p_sp, 2, 4, 1.15)

    doc.save(DOC_PATH)
    print("Successfully added Chapter 21 and Glossary items 89-93 to ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx!")


if __name__ == "__main__":
    main()
