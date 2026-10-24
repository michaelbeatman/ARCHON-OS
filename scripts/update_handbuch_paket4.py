# -*- coding: utf-8 -*-
"""
Erweitert docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx um:
1. Kapitel 24: Sicherheit, Datenschutz & Enterprise-Governance (Säule XV — Paket 4: Features 16–20)
   inkl. Tabelle 24.1 direkt vor dem Komplett-Glossar.
2. Domäne XV (Einträge 104–108) im Komplett-Glossar am Ende des Handbuchs im identischen Box-Design.
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
        if "24. Sicherheit, Datenschutz & Enterprise-Governance" in p.text:
            print("Chapter 24 already exists. Skipping duplicate insert.")
            return

    glossary_anchor = None
    for p in doc.paragraphs:
        if "Komplett-Glossar:" in p.text or ("Komplett-Glossar" in p.text and "Architektur-Enzyklopädie" in p.text):
            glossary_anchor = p
            break

    if glossary_anchor is not None:
        p_ch24 = doc.add_paragraph()
        set_p_spacing(p_ch24, 14, 6, 1.15)
        r_ch24 = p_ch24.add_run("24. Sicherheit, Datenschutz & Enterprise-Governance / Guardrails (Säule XV — Paket 4)")
        set_run_font(r_ch24, "Aptos", 14.0, (26, 54, 93), bold=True)
        glossary_anchor._p.addprevious(p_ch24._p)

        p_intro = doc.add_paragraph()
        set_p_spacing(p_intro, 2, 6, 1.15)
        r_intro = p_intro.add_run(
            "Im Enterprise-Einsatz müssen personenbezogene Kundendaten vor dem Versand an externe Cloud-LLMs geschützt, "
            "unautorisierte Netzwerk-Exfiltrationen unterbunden, Dateisystem-Rechte pro Agentenrolle beschränkt und alle "
            "Kosten- und Entscheidungsflüsse manipulationssicher protokolliert werden. Säule XV (Paket 4: Features 16–20) "
            "implementiert diese fünf Schutzschichten und macht sie im System Control Center (Tab 'Hermes Core' -> Abschnitt 12) steuerbar."
        )
        set_run_font(r_intro, "Aptos", 10.0, (45, 55, 72))
        glossary_anchor._p.addprevious(p_intro._p)

        sub_items = [
            ("24.1 Bidirektionaler PII-Scrubber & Re-Hydration / DSGVO (backend/pii_scrubber.py): ",
             "Maskiert E-Mail-Adressen, Telefonnummern und IBANs vor dem Cloud-LLM-Aufruf durch Sitzungs-Platzhalter ([EMAIL_1], [PHONE_1], [IBAN_1]) "
             "und setzt die Klartextdaten nach dem Eintreffen der Modell-Antwort lokal wieder ein."),
            ("24.2 Egress-Firewall & Domain-Allowlisting für Agenten (backend/egress_firewall.py): ",
             "Prüft jede ausgehende URL eines Agenten gegen die erlaubte Domain-Allowlist (allowed_domains), blockiert unbekannte Drittserver "
             "sowie direkte IP-Aufrufe (block_raw_ip_egress) und protokolliert alle Verbindungsversuche in 'egress_firewall_logs'."),
            ("24.3 Granulare Agenten-RBAC & Datei-Scope-Jails (backend/agent_rbac_jail.py): ",
             "Weist jeder Agentenrolle (researcher, frontend_dev, backend_architect, kernel_admin) erlaubte Werkzeuge und Pfad-Präfixe zu. "
             "Zugriffe auf '.env', SSH-Schlüssel, Systemordner ('/etc', 'C:/Windows') oder Path-Traversal ('..') werden deterministisch abgewiesen."),
            ("24.4 Deterministischer Output-Linter & Policy-Checker (backend/output_policy_linter.py): ",
             "Prüft und bereinigt Modell-Antworten in unter 5 ms vor der Anzeige: entfernt verbotene KI-Floskeln (Anti-AI-Slop) und "
             "blockiert destruktive Shell-Kommandos ('rm -rf /', 'DROP TABLE')."),
            ("24.5 Manipulationssichere Kosten- & Entscheidungs-Quittungen (backend/execution_receipt_ledger.py): ",
             "Erstellt für jeden abgeschlossenen Auftrag eine kryptografisch verkettete SHA-256-Quittung ('prev_hash' -> 'receipt_hash') "
             "inklusive Modell, Token-Anzahl, USD-Kosten und genutzter Tools in der Tabelle 'execution_receipts_ledger'.")
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
        r_th = p_tbl_h.add_run("Tabelle 24.1: Übersicht der Security- & Governance-Module, Endpunkte & Settings (Paket 4)")
        set_run_font(r_th, "Aptos", 9.5, (43, 108, 176), bold=True)
        glossary_anchor._p.addprevious(p_tbl_h._p)

        headers = ["Modul / Datei", "REST-API Endpunkte", "Settings-Schalter & Schwellenwerte"]
        rows = [
            ["16. Bidirektionaler PII-Scrubber\n(backend/pii_scrubber.py)",
             "POST /api/security/pii-scrub\nPOST /api/security/pii-rehydrate",
             "enabled (True), scrub_emails/phones/ibans (True),\nauto_rehydrate_response (True)"],
            ["17. Egress-Firewall\n(backend/egress_firewall.py)",
             "POST /api/security/egress-check\nGET /api/security/egress-logs",
             "enabled (True), block_raw_ip_egress (True),\nallowed_domains (Kommaliste)"],
            ["18. Agenten-RBAC & Path-Jails\n(backend/agent_rbac_jail.py)",
             "POST /api/security/rbac-check",
             "enabled (True), enforce_path_jail (True),\nblock_dotenv_access (True), block_system_dirs (True)"],
            ["19. Output-Policy-Linter\n(backend/output_policy_linter.py)",
             "POST /api/security/lint-output",
             "enabled (True), strip_ai_slop_phrases (True),\nblock_destructive_commands (True), auto_clean (True)"],
            ["20. Execution Receipt Ledger\n(backend/execution_receipt_ledger.py)",
             "POST /api/security/receipts/issue\nGET /api/security/receipts/verify",
             "enabled (True), chain_receipts (True),\nhash_algorithm (sha256), include_cost (True)"]
        ]
        tbl_24 = create_styled_table(doc, headers, rows, [2.1, 2.3, 2.4])
        glossary_anchor._p.addprevious(tbl_24._tbl)

    # Append Domäne XV (104–108) at the end of the Glossary
    p_dom = doc.add_paragraph()
    set_p_spacing(p_dom, 12, 4, 1.15)
    r_dom = p_dom.add_run("Domäne XV: Sicherheit, Datenschutz & Enterprise-Governance / Guardrails (Paket 4)")
    set_run_font(r_dom, "Aptos", 11.5, (26, 54, 93), bold=True)

    glossary_items = [
        ("104. Bidirektionaler PII-Scrubber & Re-Hydration (backend/pii_scrubber.py)",
         "Werden E-Mails, Telefonnummern oder IBANs im Klartext an externe Cloud-LLMs übertragen, drohen DSGVO-Verstöße und ungewollter Datenabfluss.",
         "Ersetzt sensible Personendaten vor dem API-Aufruf lokal durch Platzhalter ([EMAIL_1], [IBAN_1]) und tauscht diese in der eintreffenden Antwort wieder gegen die echten Werte aus.",
         "Cloud-Modelle sehen niemals echte Personendaten, während der Nutzer vor Ort dennoch vollständige Dokumente und Antworten erhält."),
        ("105. Egress-Firewall & Domain-Allowlisting für Agenten (backend/egress_firewall.py)",
         "Über versteckte Prompt-Injections in Webseiten könnten Agenten angewiesen werden, interne Daten per HTTP-Request an fremde Angreifer-Server zu senden.",
         "Prüft jede ausgehende Ziel-URL gegen die konfigurierte Domain-Allowlist und blockiert unautorisierte Hosts sowie rohe IPv4-Adressen.",
         "Unterbindet Daten-Exfiltration auf Netzwerkebene selbst bei manipulierten Eingaben."),
        ("106. Granulare Agenten-RBAC & Datei-Scope-Jails (backend/agent_rbac_jail.py)",
         "Wenn jeder Sub-Agent vollen Schreibzugriff auf das gesamte Projektverzeichnis besitzt, kann ein Frontend-Agent versehentlich Backend-Kernel-Dateien oder .env-Schlüssel überschreiben.",
         "Bindet jede Agentenrolle an eine feste Werkzeugliste und ein erlaubtes Verzeichnis-Jail (z. B. static/ für Frontend-Agenten).",
         "Setzt das Prinzip minimaler Rechte (Least Privilege) für jeden einzelnen Prozess im Betriebssystem durch."),
        ("107. Deterministischer Output-Linter & Policy-Checker (backend/output_policy_linter.py)",
         "Sprachmodelle verfallen gelegentlich trotz System-Prompt in künstliche KI-Floskeln oder generieren riskante Shell-Snippets.",
         "Scannt den generierten Text in Echtzeit mittels regulärer Ausdrücke, entfernt Sycophancy-Opener/AI-Slop und entschärft destruktive Befehle.",
         "Sichert sprachliche Präzision und technische Sicherheit ohne zusätzlichen LLM-Prüfaufruf."),
        ("108. Manipulationssichere Execution Receipts / SHA-256-Quittungen (backend/execution_receipt_ledger.py)",
         "Für Compliance-Audits (EU AI Act / ISO 42001) reichen einfache Text-Logs nicht aus, da sie nachträglich verändert werden können.",
         "Verkettet jede Task-Abrechnung (Modell, Tokens, USD-Kosten, ausgeführte Tools) mit dem SHA-256-Hash des Vorgängereintrags in einer Blockchain-ähnlichen Kette.",
         "Jede nachträgliche Manipulation an Kosten- oder Entscheidungsprotokollen fällt bei der Integritätsprüfung sofort auf.")
    ]

    for title_g, prob_g, mech_g, nutz_g in glossary_items:
        create_glossary_box(doc, title_g, prob_g, mech_g, nutz_g)
        p_sp = doc.add_paragraph()
        set_p_spacing(p_sp, 2, 4, 1.15)

    doc.save(DOC_PATH)
    print("Successfully added Chapter 24 and Glossary items 104-108 to ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx!")


if __name__ == "__main__":
    main()
