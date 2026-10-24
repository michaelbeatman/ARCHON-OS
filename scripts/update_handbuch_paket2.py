# -*- coding: utf-8 -*-
"""
Erweitert docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx um:
1. Kapitel 22: Moderne Gedächtnis- & RAG-Architektur (Säule XIII — Paket 2: Features 6–10)
   inkl. Tabelle 22.1 direkt vor dem Komplett-Glossar.
2. Domäne XIII (Einträge 94–98) im Komplett-Glossar am Ende des Handbuchs im identischen Box-Design.
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
        if "22. Moderne Gedächtnis- & RAG-Architektur" in p.text:
            print("Chapter 22 already exists. Skipping duplicate insert.")
            return

    glossary_anchor = None
    for p in doc.paragraphs:
        if "Komplett-Glossar:" in p.text or ("Komplett-Glossar" in p.text and "Architektur-Enzyklopädie" in p.text):
            glossary_anchor = p
            break

    if glossary_anchor is not None:
        p_ch22 = doc.add_paragraph()
        set_p_spacing(p_ch22, 14, 6, 1.15)
        r_ch22 = p_ch22.add_run("22. Moderne Gedächtnis- & RAG-Architektur (Säule XIII — Paket 2)")
        set_run_font(r_ch22, "Aptos", 14.0, (26, 54, 93), bold=True)
        glossary_anchor._p.addprevious(p_ch22._p)

        p_intro = doc.add_paragraph()
        set_p_spacing(p_intro, 2, 6, 1.15)
        r_intro = p_intro.add_run(
            "Reine Vektor-Ähnlichkeitssuche übersieht häufig exakte Fehlercodes, Ticket-IDs oder mehrstufige Beziehungen zwischen Systemkomponenten. "
            "Säule XIII (Paket 2: Features 6–10) erweitert das Gedächtnis von Archon OS um fünf moderne Wissens- und Beleg-Schichten, "
            "die im System Control Center (Tab 'Hermes Core' -> Abschnitt 10) einzeln schaltbar und konfigurierbar sind."
        )
        set_run_font(r_intro, "Aptos", 10.0, (45, 55, 72))
        glossary_anchor._p.addprevious(p_intro._p)

        sub_items = [
            ("22.1 Hybrid-Search mit BM25 (SQLite FTS5) + Vektor-RAG + Reciprocal Rank Fusion (backend/hybrid_search_engine.py): ",
             "Kombiniert die invertierte Volltextsuche SQLite FTS5 (BM25-Ranking für exakte Fachbegriffe und Codes) mit semantischen Vektor-Ähnlichkeiten "
             "über die Reciprocal-Rank-Fusion-Formel: score(d) = w_bm25 / (k + rank_bm25) + w_vec / (k + rank_vec)."),
            ("22.2 Lokaler Knowledge-Graph / Entitäten- & Beziehungs-Tripel (backend/knowledge_graph_store.py): ",
             "Speichert gerichtete Wissens-Tripel (Subjekt -> Prädikat -> Objekt) samt Konfidenzscore in SQLite, extrahiert Beziehungen automatisch "
             "aus Freitext und traversiert Nachbarschafts-Subgraphen über bis zu max_traversal_hops (Standard: 2) Ebenen."),
            ("22.3 Agentic Corrective RAG / CRAG (backend/corrective_rag.py): ",
             "Prüft abgerufene Dokumente vor der Antwortgenerierung auf ihre tatsächliche Relevanz zur Nutzerfrage. Unterschreitet der beste Treffer "
             "relevance_threshold (Standard: 0.45), verwirft CRAG irrelevante Chunks, erweitert die Suchanfrage automatisch um Domänen-Synonyme und führt bis zu max_rewrite_attempts (Standard: 2) Korrekturschleifen aus."),
            ("22.4 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (backend/core_memory_manager.py): ",
             "Trennt das Langzeit-Archiv von fest im System-Prompt verankerten Arbeitsgedächtnis-Blöcken (<CORE_WORKING_MEMORY>: human_profile, system_persona, active_goals), "
             "die der Agent zur Laufzeit selbstständig via append oder replace aktualisieren kann."),
            ("22.5 Automatisches Citation- & Quellen-Pinning (backend/citation_pinner.py): ",
             "Verknüpft jede Faktenaussage einer Agenten-Antwort automatisch mit der belegenden Dokument-ID ([Quelle: DOC-ID]), berechnet die Beleg-Abdeckungsquote "
             "(min_citation_coverage_pct, Standard: 60 %) und hängt ein verifiziertes Quellenverzeichnis an.")
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
        r_th = p_tbl_h.add_run("Tabelle 22.1: Übersicht der Hybrid-Memory & RAG-Module, Endpunkte & Settings (Paket 2)")
        set_run_font(r_th, "Aptos", 9.5, (43, 108, 176), bold=True)
        glossary_anchor._p.addprevious(p_tbl_h._p)

        headers = ["Modul / Datei", "REST-API Endpunkte", "Settings-Schalter & Schwellenwerte"]
        rows = [
            ["6. Hybrid-Search Engine\n(backend/hybrid_search_engine.py)",
             "POST /api/memory/hybrid-index\nPOST /api/memory/hybrid-search",
             "enabled (True), rrf_k (60),\nbm25_weight (0.5), top_k (5)"],
            ["7. Knowledge-Graph Store\n(backend/knowledge_graph_store.py)",
             "POST /api/memory/knowledge-graph/triple\nPOST /api/memory/knowledge-graph/ingest\nGET /api/memory/knowledge-graph/subgraph",
             "enabled (True), auto_extract_triples (True),\nmax_traversal_hops (2), min_confidence (0.70)"],
            ["8. Corrective RAG (CRAG)\n(backend/corrective_rag.py)",
             "POST /api/memory/crag-retrieve",
             "enabled (True), relevance_threshold (0.45),\nauto_query_rewrite (True), max_attempts (2)"],
            ["9. 2-Stufen Core-Memory\n(backend/core_memory_manager.py)",
             "GET /api/memory/core-blocks\nPOST /api/memory/core-blocks",
             "enabled (True), max_pinned_blocks (10),\nmax_chars_per_block (800), auto_inject (True)"],
            ["10. Citation Pinner\n(backend/citation_pinner.py)",
             "POST /api/memory/pin-citations",
             "enabled (True), require_inline_citations (True),\nmin_citation_coverage_pct (60%), footer (True)"]
        ]
        tbl_22 = create_styled_table(doc, headers, rows, [2.0, 2.3, 2.5])
        glossary_anchor._p.addprevious(tbl_22._tbl)

    # Append Domäne XIII (94–98) at the end of the Glossary
    p_dom = doc.add_paragraph()
    set_p_spacing(p_dom, 12, 4, 1.15)
    r_dom = p_dom.add_run("Domäne XIII: Moderne Gedächtnis- & RAG-Architektur (Paket 2)")
    set_run_font(r_dom, "Aptos", 11.5, (26, 54, 93), bold=True)

    glossary_items = [
        ("94. Hybrid-Search mit BM25 FTS5 & Reciprocal Rank Fusion (backend/hybrid_search_engine.py)",
         "Reine Vektorsuche findet semantisch ähnliche Texte, scheitert jedoch oft an exakten Fehlercodes, Funktionsnamen oder Seriennummern.",
         "Kombiniert SQLite FTS5 Volltext-Ranking (BM25) und Cosine-Vektor-Ähnlichkeit über Reciprocal Rank Fusion (RRF).",
         "Vereint exakte Keyword-Treffer und semantisches Verständnis in einer einzigen, hochpräzisen Trefferliste."),
        ("95. Lokaler Knowledge-Graph / Tripel-Speicher (backend/knowledge_graph_store.py)",
         "Flache Text-Chunks erfassen keine strukturierten Abhängigkeiten (wer verwaltet welches System oder welche Komponente nutzt welchen Dienst).",
         "Extrahiert und speichert Subjekt-Prädikat-Objekt-Tripel mit Konfidenzscore in SQLite und ermöglicht mehrstufige Graph-Traversierungen (Multi-Hop).",
         "Agenten erkennen System- und Organisationszusammenhänge über mehrere Ebenen hinweg."),
        ("96. Agentic Corrective RAG / CRAG (backend/corrective_rag.py)",
         "Klassisches RAG reicht irrelevante Suchtreffer ungeprüft an das Sprachmodell weiter und provoziert dadurch Fehlantworten.",
         "Bewertet jeden abgerufenen Dokument-Chunk gegen einen Relevanz-Schwellenwert (0.45) und führt bei schwachen Treffern automatisch ein Query-Rewrite mit Synonym-Expansion durch.",
         "Filtert Wissensrauschen vor der Antwortgenerierung heraus und erhöht die Trefferqualität bei unklaren Fragen."),
        ("97. 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (backend/core_memory_manager.py)",
         "Wichtige Nutzerpräferenzen und Projektziele gehen verloren, sobald sie aus dem kurzlebigen Chat-Fenster herausfallen.",
         "Verankert editierbare Pinned-Working-Memory-Blöcke (<CORE_WORKING_MEMORY>) dauerhaft im System-Prompt, getrennt vom großen Archiv-Speicher.",
         "Garantiert ein permanentes, vom Agenten selbst pflegbares Kerngedächtnis über beliebig viele Sitzungen hinweg."),
        ("98. Automatisches Citation- & Quellen-Pinning (backend/citation_pinner.py)",
         "Ohne direkte Quellenverweise ist für den Nutzer nicht überprüfbar, aus welchem Dokument eine Faktenaussage des Agenten stammt.",
         "Ordnet Sätze der Antwort per Token-Overlap den abgerufenen Quell-Dokumenten zu, fügt Inline-Belege ([Quelle: ID]) ein und prüft die Mindest-Belegquote.",
         "Macht jede Aussage revisionssicher nachvollziehbar und deckt unbelegte Behauptungen sofort auf.")
    ]

    for title_g, prob_g, mech_g, nutz_g in glossary_items:
        create_glossary_box(doc, title_g, prob_g, mech_g, nutz_g)
        p_sp = doc.add_paragraph()
        set_p_spacing(p_sp, 2, 4, 1.15)

    doc.save(DOC_PATH)
    print("Successfully added Chapter 22 and Glossary items 94-98 to ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx!")


if __name__ == "__main__":
    main()
