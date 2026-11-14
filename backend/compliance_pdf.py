"""
backend/compliance_pdf.py
=========================
M49 — Abhängigkeitsfreier Pure-Python DIN-A4 PDF-1.4-Generator für die
kombinierte GoBD- & EU-AI-Act-Verfahrensdokumentation.

Eigenschaften:
- 0 externe Laufzeitabhängigkeiten (funktioniert direkt im gehärteten Container ohne reportlab/weasyprint).
- Volle deutsche Umlaut- & Sonderzeichen-Unterstützung via `/WinAnsiEncoding` (`cp1252`: äöüßÄÖÜ§€–•).
- Mehrseitiges DIN-A4-Layout mit Corporate-Kopfzeile, Kapitelstruktur, Kennzahlen-Kacheln,
  mehrspaltigen Tabellen mit Zeilenumbruch, Seitennummerierung ("Seite X von Y") und
  kryptografischem SHA-256-Prüfvermerk im GoBD-Audit-Log.
"""

from __future__ import annotations

import datetime
import hashlib
import textwrap
from typing import Any, Dict, List, Sequence, Tuple

PAGE_W = 595.28  # DIN A4 Breite in pt
PAGE_H = 841.89  # DIN A4 Höhe in pt
MARGIN_L = 42.0
MARGIN_R = 42.0
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
TOP_START_Y = PAGE_H - 68.0
BOTTOM_LIMIT_Y = 54.0


def _winansi_bytes(text: str) -> bytes:
    """Konvertiert Unicode-Text sicher nach CP1252 (WinAnsiEncoding) und escaped PDF-String-Trenner."""
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2212": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2713": "OK",
        "\u2714": "OK",
        "\u2717": "X",
    }
    cleaned = str(text or "")
    for src, dst in replacements.items():
        cleaned = cleaned.replace(src, dst)
    raw = cleaned.encode("cp1252", errors="replace")
    out = bytearray()
    for b in raw:
        if b in (0x28, 0x29, 0x5C):  # ( ) \
            out.append(0x5C)
            out.append(b)
        elif b < 32:
            out.append(0x20)
        else:
            out.append(b)
    return bytes(out)


class _PDFDocumentBuilder:
    """Schlanker, deterministischer Mehrseiten-PDF-1.4-Writer mit Tabellen- und Umbruchlogik."""

    def __init__(self, doc_title: str, tenant_label: str, document_id: str) -> None:
        self.doc_title = doc_title
        self.tenant_label = tenant_label
        self.document_id = document_id
        self.pages: List[List[bytes]] = []
        self.y = TOP_START_Y
        self._new_page()

    def _new_page(self) -> None:
        cmds: List[bytes] = []
        # Dezenter oberer Markenstreifen (Dunkelanthrazit + Rot/Amber-Akzentlinie)
        cmds.append(b"0.09 0.10 0.14 rg")
        cmds.append(f"0 {PAGE_H - 42:.2f} {PAGE_W:.2f} 42 re f".encode("ascii"))
        cmds.append(b"0.86 0.18 0.18 rg")
        cmds.append(f"0 {PAGE_H - 44.5:.2f} {PAGE_W:.2f} 2.5 re f".encode("ascii"))

        # Kopfzeilen-Text
        cmds.append(b"1 1 1 rg")
        cmds.append(self._text_cmd("F2", 9.5, MARGIN_L, PAGE_H - 25.0, self.doc_title))
        right_hdr = f"{self.tenant_label}  |  {self.document_id}"
        cmds.append(b"0.82 0.85 0.90 rg")
        cmds.append(self._text_cmd("F1", 8.0, PAGE_W - MARGIN_R - len(right_hdr) * 3.9, PAGE_H - 25.0, right_hdr))
        cmds.append(b"0 0 0 rg")

        self.pages.append(cmds)
        self.y = TOP_START_Y

    @staticmethod
    def _text_cmd(font: str, size: float, x: float, y: float, text: str) -> bytes:
        esc = _winansi_bytes(text)
        return f"BT /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td (".encode("ascii") + esc + b") Tj ET"

    def _ensure_space(self, needed_pt: float) -> None:
        if self.y - needed_pt < BOTTOM_LIMIT_Y:
            self._new_page()

    def add_spacer(self, pt: float = 8.0) -> None:
        self.y -= pt
        if self.y < BOTTOM_LIMIT_Y:
            self._new_page()

    def add_title_banner(self, main_title: str, subtitle: str, meta_lines: Sequence[str]) -> None:
        box_h = 68.0 + len(meta_lines) * 12.0
        self._ensure_space(box_h + 10)
        top_y = self.y
        cmds = self.pages[-1]
        cmds.append(b"0.96 0.97 0.99 rg")
        cmds.append(f"{MARGIN_L:.2f} {top_y - box_h:.2f} {CONTENT_W:.2f} {box_h:.2f} re f".encode("ascii"))
        cmds.append(b"0.86 0.18 0.18 rg")
        cmds.append(f"{MARGIN_L:.2f} {top_y - box_h:.2f} 3.5 {box_h:.2f} re f".encode("ascii"))

        cmds.append(b"0.08 0.10 0.15 rg")
        cmds.append(self._text_cmd("F2", 14.0, MARGIN_L + 12, top_y - 20, main_title))
        cmds.append(b"0.30 0.34 0.42 rg")
        cmds.append(self._text_cmd("F1", 9.5, MARGIN_L + 12, top_y - 35, subtitle))

        cy = top_y - 52
        cmds.append(b"0.15 0.18 0.24 rg")
        for line in meta_lines:
            cmds.append(self._text_cmd("F1", 8.5, MARGIN_L + 12, cy, line))
            cy -= 12.0
        cmds.append(b"0 0 0 rg")
        self.y = top_y - box_h - 14.0

    def add_section_heading(self, title: str) -> None:
        self._ensure_space(34.0)
        self.y -= 6.0
        cmds = self.pages[-1]
        cmds.append(b"0.10 0.12 0.18 rg")
        cmds.append(self._text_cmd("F2", 11.5, MARGIN_L, self.y, title))
        self.y -= 5.0
        cmds.append(b"0.86 0.18 0.18 RG 0.8 w")
        cmds.append(f"{MARGIN_L:.2f} {self.y:.2f} m {PAGE_W - MARGIN_R:.2f} {self.y:.2f} l S".encode("ascii"))
        cmds.append(b"0 0 0 rg 0 0 0 RG")
        self.y -= 13.0

    def add_paragraph(self, text: str, font: str = "F1", size: float = 9.0, indent: float = 0.0) -> None:
        max_chars = max(40, int((CONTENT_W - indent) / (size * 0.50)))
        lines = textwrap.wrap(text, width=max_chars) or [""]
        line_h = size + 3.5
        for ln in lines:
            self._ensure_space(line_h)
            self.pages[-1].append(b"0.14 0.16 0.20 rg")
            self.pages[-1].append(self._text_cmd(font, size, MARGIN_L + indent, self.y, ln))
            self.y -= line_h
        self.y -= 3.0

    def add_kv_grid(self, rows: Sequence[Tuple[str, str]], col1_w: float = 165.0) -> None:
        col2_w = CONTENT_W - col1_w
        max_chars_val = max(30, int(col2_w / 4.6))
        for k, v in rows:
            wrapped = textwrap.wrap(str(v or "-"), width=max_chars_val) or ["-"]
            row_h = max(15.0, len(wrapped) * 11.5 + 4.0)
            self._ensure_space(row_h)
            cmds = self.pages[-1]
            cmds.append(b"0.88 0.90 0.93 RG 0.4 w")
            cmds.append(f"{MARGIN_L:.2f} {self.y - row_h + 10:.2f} m {PAGE_W - MARGIN_R:.2f} {self.y - row_h + 10:.2f} l S".encode("ascii"))
            cmds.append(b"0.22 0.25 0.32 rg")
            cmds.append(self._text_cmd("F2", 8.5, MARGIN_L + 2, self.y, k))
            cmds.append(b"0.10 0.12 0.16 rg")
            vy = self.y
            for wline in wrapped:
                cmds.append(self._text_cmd("F1", 8.5, MARGIN_L + col1_w, vy, wline))
                vy -= 11.5
            self.y -= row_h
        self.y -= 6.0

    def add_table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        col_widths: Sequence[float],
        font_size: float = 7.6,
    ) -> None:
        def _draw_header() -> None:
            hdr_h = 16.0
            self._ensure_space(hdr_h + 14.0)
            cmds = self.pages[-1]
            cmds.append(b"0.14 0.17 0.24 rg")
            cmds.append(f"{MARGIN_L:.2f} {self.y - 11.0:.2f} {CONTENT_W:.2f} {hdr_h:.2f} re f".encode("ascii"))
            cmds.append(b"1 1 1 rg")
            cx = MARGIN_L + 4.0
            for h_text, cw in zip(headers, col_widths):
                cmds.append(self._text_cmd("F2", font_size + 0.3, cx, self.y - 6.5, h_text))
                cx += cw
            cmds.append(b"0 0 0 rg")
            self.y -= hdr_h

        _draw_header()
        line_h = font_size + 2.8

        for r_idx, row in enumerate(rows):
            wrapped_cols: List[List[str]] = []
            max_lines = 1
            for cell, cw in zip(row, col_widths):
                c_chars = max(8, int((cw - 6.0) / (font_size * 0.51)))
                w = textwrap.wrap(str(cell or ""), width=c_chars) or [""]
                wrapped_cols.append(w)
                if len(w) > max_lines:
                    max_lines = len(w)

            row_h = max_lines * line_h + 5.0
            if self.y - row_h < BOTTOM_LIMIT_Y:
                self._new_page()
                _draw_header()

            cmds = self.pages[-1]
            if r_idx % 2 == 1:
                cmds.append(b"0.965 0.972 0.985 rg")
                cmds.append(f"{MARGIN_L:.2f} {self.y - row_h + 4.5:.2f} {CONTENT_W:.2f} {row_h:.2f} re f".encode("ascii"))

            cmds.append(b"0.86 0.88 0.92 RG 0.35 w")
            cmds.append(
                f"{MARGIN_L:.2f} {self.y - row_h + 4.5:.2f} m {PAGE_W - MARGIN_R:.2f} {self.y - row_h + 4.5:.2f} l S".encode("ascii")
            )

            cmds.append(b"0.12 0.14 0.18 rg")
            cx = MARGIN_L + 4.0
            for col_lines, cw in zip(wrapped_cols, col_widths):
                ly = self.y - 4.5
                for ln in col_lines:
                    cmds.append(self._text_cmd("F1", font_size, cx, ly, ln))
                    ly -= line_h
                cx += cw
            self.y -= row_h
        self.y -= 8.0

    def finalize_bytes(self) -> bytes:
        total_pages = len(self.pages)
        today_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

        # Fußzeile mit Gesamtseitenzahl auf jeder Seite ergänzen
        for idx, cmds in enumerate(self.pages, start=1):
            cmds.append(b"0.80 0.83 0.88 RG 0.5 w")
            cmds.append(f"{MARGIN_L:.2f} 38.00 m {PAGE_W - MARGIN_R:.2f} 38.00 l S".encode("ascii"))
            cmds.append(b"0.42 0.45 0.52 rg")
            left_ft = f"GoBD & EU AI Act Verfahrensdokumentation  |  Erstellt: {today_str}  |  Vertraulich"
            right_ft = f"Seite {idx} von {total_pages}"
            cmds.append(self._text_cmd("F1", 7.5, MARGIN_L, 26.0, left_ft))
            cmds.append(self._text_cmd("F2", 7.5, PAGE_W - MARGIN_R - 58.0, 26.0, right_ft))

        # Objekt-Aufbau:
        # 1: Catalog, 2: Pages, 3: Font F1 (Helvetica), 4: Font F2 (Helvetica-Bold), 5: Font F3 (Courier)
        # Danach je Seite: Page-Objekt + Content-Stream-Objekt
        objects: List[bytes] = []

        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        page_obj_ids = [6 + i * 2 for i in range(total_pages)]
        kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
        objects.append(f"<< /Type /Pages /Kids [{kids_str}] /Count {total_pages} >>".encode("ascii"))
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")

        for i, cmds in enumerate(self.pages):
            content_id = 7 + i * 2
            stream_data = b"\n".join(cmds)
            page_dict = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
            content_obj = (
                f"<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
                + stream_data
                + b"\nendstream"
            )
            objects.append(page_dict)
            objects.append(content_obj)

        # Info-Dictionary als letztes Objekt
        info_id = len(objects) + 1
        objects.append(
            b"<< /Title ("
            + _winansi_bytes(self.doc_title)
            + b") /Producer (Archon OS Compliance Engine M49) /Creator (Archon OS) >>"
        )

        buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = [0]
        for obj_num, body in enumerate(objects, start=1):
            offsets.append(len(buf))
            buf.extend(f"{obj_num} 0 obj\n".encode("ascii"))
            buf.extend(body)
            buf.extend(b"\nendobj\n")

        xref_pos = len(buf)
        buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        buf.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

        buf.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
                "ascii"
            )
        )
        return bytes(buf)


def build_verfahrensdokumentation_pdf(snapshot: Dict[str, Any]) -> Tuple[bytes, str]:
    """
    Erzeugt aus dem Live-Compliance-Snapshot ein prüferfertiges mehrseitiges PDF
    nach GoBD (Rz. 151 ff.) und Verordnung (EU) 2024/1689 (EU AI Act).
    Liefert `(pdf_bytes, pdf_sha256)`.
    """
    comp = snapshot.get("company") or {}
    comp_name = str(comp.get("name") or "Standard-Mandant")
    legal_form = str(comp.get("legal_form") or "")
    entity_type = str(comp.get("entity_type") or "operative_gmbh")
    doc_id = str(snapshot.get("document_id") or "VD-ARCHON")
    version = str(snapshot.get("system_version") or "v0.5.2.1")
    gen_at = str(snapshot.get("generated_at") or "")
    tid = str(snapshot.get("tenant_id") or "default")

    pdf = _PDFDocumentBuilder(
        doc_title="Verfahrensdokumentation nach GoBD & EU AI Act (VO 2024/1689)",
        tenant_label=comp_name,
        document_id=doc_id,
    )

    # Deckblock / Management Summary
    pdf.add_title_banner(
        main_title="Verfahrensdokumentation nach GoBD & EU AI Act",
        subtitle=(
            "Kombinierte System-, Betriebs-, Datenschutz- und KI-Governance-Dokumentation "
            "für Wirtschaftsprüfer, Finanzbehörden (Z3) und Aufsichtsstellen"
        ),
        meta_lines=[
            f"Mandant / Rechtsträger: {comp_name} ({entity_type.upper()})  |  Mandanten-ID: {tid}",
            f"System-Release: Archon OS {version}  |  Dokument-ID: {doc_id}  |  Stand: {gen_at}",
            f"Snapshot-Integritäts-Hash (SHA-256): {snapshot.get('snapshot_sha256', '')}",
        ],
    )

    # Kapitel 1: Allgemeine Beschreibung & Unternehmensstamm (GoBD Rz. 151-153)
    pdf.add_section_heading("1. Allgemeine Beschreibung & Mandantenstamm (GoBD Rz. 151-153)")
    addr = comp.get("address") or {}
    reg = comp.get("registry") or {}
    tax = comp.get("tax") or {}
    bank = comp.get("bank") or {}
    addr_str = f"{addr.get('street', '')}, {addr.get('postal_code', '')} {addr.get('city', '')} ({addr.get('country', 'DE')})".strip(", ")

    pdf.add_kv_grid(
        [
            ("Unternehmen / Rechtsträger", f"{comp_name} {legal_form}".strip()),
            ("Gesellschaftstyp (M43)", entity_type),
            ("Geschäftsanschrift", addr_str or "-"),
            ("Handelsregister & Vertretung", f"{reg.get('court', '-')} | {reg.get('number', '-')} | GF: {reg.get('managing_directors', '-')}"),
            ("Steuernummer / USt-IdNr.", f"St.-Nr.: {tax.get('tax_number', '-')}  |  USt-IdNr.: {tax.get('vat_id', '-')}"),
            ("Bankverbindung", f"{bank.get('bank_name', '-')}  |  IBAN: {bank.get('iban', '-')}"),
            ("Eingesetztes Kernsystem", f"Archon OS ({version}) — Selbstgehostetes Multi-Agenten- & KMU-ERP-Betriebssystem"),
        ]
    )

    # Kapitel 2: Physische Mandanten-DB-Isolation & Nummernkreise (M43 / GoBD / DSGVO)
    pdf.add_section_heading("2. Technische Systemdokumentation & Mandantentrennung (M43)")
    pdf.add_paragraph(
        "Gemäß DSGVO-Trennungsgebot und GoBD-Ordnungsmäßigkeit verwaltet Archon OS geschäftskritische "
        "Datenbestände in physisch separierten SQLite-WAL-Datenbanken pro Gesellschaft unter "
        "data/tenants/<mandant>/ mit getrennten, atomaren Beleg-Nummernkreisen."
    )

    dbs = (snapshot.get("db_isolation") or {}).get("databases") or {}
    ranges = snapshot.get("number_ranges") or {}
    db_rows = []
    for db_name, info in dbs.items():
        kb = f"{(info.get('size_bytes', 0) / 1024.0):.1f} KB"
        db_rows.append([
            db_name,
            str(info.get("mode", "isolated")),
            "VORHANDEN" if info.get("exists") else "INITIALISIERT",
            kb,
            str(info.get("active_path", info.get("path", ""))),
        ])
    pdf.add_table(
        headers=["Datenbank", "Modus", "Status", "Größe", "Aktiver Dateipfad"],
        rows=db_rows,
        col_widths=[72.0, 68.0, 72.0, 52.0, CONTENT_W - 264.0],
    )

    range_rows = []
    for dtype, rinfo in ranges.items():
        range_rows.append([
            dtype,
            str(rinfo.get("prefix", "")),
            str(rinfo.get("next_seq", 1)),
            str(rinfo.get("padding", 4)),
        ])
    if range_rows:
        pdf.add_table(
            headers=["Belegtyp", "Nummernkreis-Präfix", "Nächste Laufnummer", "Stellen"],
            rows=range_rows,
            col_widths=[110.0, 190.0, 110.0, CONTENT_W - 410.0],
        )

    # Kapitel 3: Betriebsdokumentation, IKS, Datenschutz-Routing & GoBD-Hashkette
    pdf.add_section_heading("3. Internes Kontrollsystem (IKS), Zero-Egress & GoBD-Audit-Log (M21/M22)")
    priv = snapshot.get("privacy_routing") or {}
    audit = snapshot.get("audit_chain") or {}
    guard = snapshot.get("guardrails") or {}

    chain_ok = "VERIFIZIERT & UNVERSEHRT (0 Manipulationen)" if audit.get("valid") else f"PRÜFFehler: {audit.get('error', 'Prüfung erforderlich')}"
    pdf.add_kv_grid(
        [
            ("GoBD SHA-256 Hashkette (M21)", chain_ok),
            ("Geprüfte Audit-Blöcke", str(audit.get("checked_blocks", audit.get("total_entries", 0)))),
            ("Aktueller Merkle-Head-Hash", str(audit.get("head_hash", "0" * 64))),
            ("Sensibles Lokal-Routing (Zero-Egress)", "AKTIV" if priv.get("sensitive_local_routing") else "BEREIT (On-Demand / EU-Fallback)"),
            ("Lokaler LLM-Endpunkt / Modell", f"{priv.get('local_llm_url', '-')}  ({priv.get('local_llm_model', '-')})"),
            ("Geschützte Datenkategorien", ", ".join(priv.get("sensitive_categories") or [])),
            ("Prompt-Injection-Abwehr (M23)", "Dual-LLM Quarantäne-Sanitizer + Pfad-Jail + Non-Root Container (UID 1000)"),
            ("EU-AI-Act Guardrail-Prüfstatus", "ALLE PFLICHT-GUARDRAILS AKTIV" if guard.get("all_guardrails_passed") else f"{len(guard.get('violations', []))} Hinweise"),
        ]
    )

    # Kapitel 4: EU AI Act Risikoklassifizierungs-Register (Verordnung (EU) 2024/1689)
    pdf.add_section_heading("4. EU AI Act KI-Systemregister & SOUL-Prompt-Prüfsummen (VO 2024/1689)")
    stats = snapshot.get("ai_act_stats") or {}
    pdf.add_paragraph(
        f"Gesamtzahl registrierter Spezialisten: {stats.get('total_agents', 0)}  |  "
        f"Anhang-III-Hochrisiko (Art. 6): {stats.get('high_risk_count', 0)}  |  "
        f"Art.-50-Transparenzpflicht: {stats.get('transparency_risk_count', 0)}  |  "
        f"Art.-95-Minimalrisiko: {stats.get('minimal_risk_count', 0)}  |  "
        f"Gepinnte SOUL-SHA-256-Hashes: {stats.get('soul_hashes_pinned', 0)}"
    )

    inv_rows = []
    for item in snapshot.get("ai_act_inventory") or []:
        tier_short = {
            "HIGH_RISK": "HIGH RISK (Anh. III)",
            "SPECIFIC_TRANSPARENCY": "TRANSPARENZ (Art. 50)",
            "MINIMAL_RISK": "MINIMAL (Art. 95)",
        }.get(item.get("risk_tier", ""), item.get("risk_tier", ""))
        oversight_short = str(item.get("human_oversight_measure", "")).split("(")[0].strip()
        soul_short = str(item.get("soul_sha256", ""))[:12]
        inv_rows.append([
            str(item.get("agent_id", "")),
            str(item.get("agent_name", "")),
            tier_short,
            oversight_short,
            soul_short,
        ])

    pdf.add_table(
        headers=["Spezialisten-ID", "Bezeichnung / Rolle", "EU AI Act Klasse", "Aufsichts-Gate", "SOUL-SHA256"],
        rows=inv_rows,
        col_widths=[115.0, 145.0, 96.0, 88.0, CONTENT_W - 444.0],
        font_size=7.0,
    )

    # Kapitel 5: Art. 4 EU AI Act KI-Kompetenznachweis-Register & Prüfvermerk
    pdf.add_section_heading("5. KI-Kompetenznachweis-Register (Art. 4 EU AI Act) & Freigabevermerk")
    pdf.add_paragraph(
        "Nachweis der gemäß Art. 4 Verordnung (EU) 2024/1689 eingewiesenen Bediener und "
        "Aufsichtsverantwortlichen für Human-in-the-Loop-Freigaben:"
    )

    lit_rows = []
    for entry in snapshot.get("literacy_register") or []:
        lit_rows.append([
            str(entry.get("person_name", "")),
            str(entry.get("role", "")),
            str(entry.get("training_module", "")),
            f"{entry.get('completed_at', '')} bis {entry.get('valid_until', '')}",
            str(entry.get("certificate_sha256", ""))[:12],
        ])

    pdf.add_table(
        headers=["Name / Funktionsträger", "Rolle", "Schulungs- & Kompetenzmodul", "Gültigkeit", "Nachweis-Hash"],
        rows=lit_rows,
        col_widths=[115.0, 95.0, 155.0, 78.0, CONTENT_W - 443.0],
        font_size=7.3,
    )

    pdf.add_spacer(10.0)
    pdf.add_paragraph(
        "Prüf- und Freigabevermerk: Dieses Dokument wurde maschinell und unverändert aus der laufenden "
        "Konfiguration, den physisch isolierten Mandanten-Datenbanken und dem kryptografisch verketteten "
        "GoBD-Revisionsprotokoll von Archon OS erzeugt.",
        font="F2",
        size=8.5,
    )
    pdf.add_spacer(18.0)
    pdf.add_paragraph(
        "________________________________________          ________________________________________",
        font="F1",
        size=8.5,
    )
    pdf.add_paragraph(
        "Ort, Datum / Geschäftsführung                     Datenschutz / Revision / Wirtschaftsprüfer",
        font="F1",
        size=8.0,
    )

    pdf_bytes = pdf.finalize_bytes()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, pdf_sha256
