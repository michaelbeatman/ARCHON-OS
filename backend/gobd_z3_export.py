"""GoBD Z3 Datenträgerüberlassung (GDPdU / IDEA Beschreibungsstandard).

Erzeugt ein prüferfertiges ZIP-Archiv mit:
- `index.xml` (GDPdU/GoBD-Metadatenbeschreibung aller Tabellen & Spalten)
- `erp_documents.csv` (Rechnungen, Gutschriften, Angebote mit Festschreibungsdaten)
- `erp_document_lines.csv` (Positionsdetails inkl. Rabatten & Steuersätzen)
- `crm_entities.csv` (Debitoren-/Kreditorenstamm)
- `audit_log.csv` (Revisionssicheres SHA-256 Hashketten-Protokoll)
- `MANIFEST_SHA256.txt` (SHA-256-Prüfsummen aller Paketdateien)
"""

from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("gobd_z3_export")

import datetime
import hashlib
import io
import os
import re
import sqlite3
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as _xml_escape

_PURE_SIGNED_NUM_RE = re.compile(r"^[+-]\d+(?:[.,]\d+)?$")


def _csv_cell(val: Any) -> str:
    raw = str(val if val is not None else "")
    # Normalize embedded line breaks so each CSV record stays on one CRLF line,
    # while preserving leading \t / \r for formula-injection detection.
    s = raw.replace("\r\n", " ").replace("\n", " ")
    leading = s.lstrip(" ")
    if leading:
        first = leading[0]
        if first in ("=", "@", "\t", "\r"):
            s = "'" + s
        elif first in ("+", "-") and not _PURE_SIGNED_NUM_RE.fullmatch(leading.strip()):
            s = "'" + s
    s = s.replace("\r", " ").strip(" ")
    return '"' + s.replace('"', '""') + '"'


def _num_de(val: Any, decimals: int = 2) -> str:
    try:
        num = float(val if val is not None else 0.0)
    except (TypeError, ValueError):
        num = 0.0
    return f"{num:.{decimals}f}".replace(".", ",")


def _rows_to_csv(headers: List[str], rows: List[List[str]]) -> bytes:
    lines = [";".join(headers)]
    for row in rows:
        lines.append(";".join(row))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


_GOBDU_TABLE_DEFS: List[Tuple[str, str, str, List[Tuple[str, str, Optional[str]]]]] = [
    (
        "erp_documents.csv",
        "ERP-Belege",
        "Ausgangs- und Eingangsbelege inkl. Festschreibungszeitpunkt (GoBD)",
        [
            ("id", "AlphaNumeric", None),
            ("doc_type", "AlphaNumeric", None),
            ("doc_number", "AlphaNumeric", None),
            ("status", "AlphaNumeric", None),
            ("entity_id", "AlphaNumeric", None),
            ("source_doc_id", "AlphaNumeric", None),
            ("issue_date", "Date", "YYYY-MM-DD"),
            ("service_date", "Date", "YYYY-MM-DD"),
            ("due_date", "Date", "YYYY-MM-DD"),
            ("currency", "AlphaNumeric", None),
            ("tax_regime", "AlphaNumeric", None),
            ("amount_net", "Numeric", "2"),
            ("tax_amount", "Numeric", "2"),
            ("amount_gross", "Numeric", "2"),
            ("booked_at", "AlphaNumeric", None),
            ("paid_at", "AlphaNumeric", None),
            ("recipient_snapshot_json", "AlphaNumeric", None),
        ],
    ),
    (
        "erp_document_lines.csv",
        "ERP-Belegpositionen",
        "Einzelpositionen der Belege inkl. Steuersatz und Rabatt",
        [
            ("id", "AlphaNumeric", None),
            ("document_id", "AlphaNumeric", None),
            ("pos_no", "Numeric", "0"),
            ("title", "AlphaNumeric", None),
            ("quantity", "Numeric", "2"),
            ("unit", "AlphaNumeric", None),
            ("unit_price_net", "Numeric", "2"),
            ("discount_pct", "Numeric", "2"),
            ("tax_rate_pct", "Numeric", "2"),
            ("line_net", "Numeric", "2"),
            ("line_tax", "Numeric", "2"),
            ("line_gross", "Numeric", "2"),
        ],
    ),
    (
        "crm_entities.csv",
        "Geschäftspartner",
        "Debitoren- und Kreditorenstammdaten",
        [
            ("id", "AlphaNumeric", None),
            ("display_name", "AlphaNumeric", None),
            ("debtor_no", "AlphaNumeric", None),
            ("creditor_no", "AlphaNumeric", None),
            ("vat_id", "AlphaNumeric", None),
            ("tax_number", "AlphaNumeric", None),
            ("street", "AlphaNumeric", None),
            ("postal_code", "AlphaNumeric", None),
            ("city", "AlphaNumeric", None),
            ("country_code", "AlphaNumeric", None),
            ("billing_email", "AlphaNumeric", None),
        ],
    ),
    (
        "audit_log.csv",
        "GoBD-Audit-Hashkette",
        "Unveränderliches SHA-256 Revisionsprotokoll",
        [
            ("id", "Numeric", "0"),
            ("timestamp", "AlphaNumeric", None),
            ("company_id", "AlphaNumeric", None),
            ("category", "AlphaNumeric", None),
            ("action", "AlphaNumeric", None),
            ("agent_id", "AlphaNumeric", None),
            ("provider", "AlphaNumeric", None),
            ("model", "AlphaNumeric", None),
            ("payload_json", "AlphaNumeric", None),
            ("prev_hash", "AlphaNumeric", None),
            ("current_hash", "AlphaNumeric", None),
        ],
    ),
]


def _build_index_xml(company_name: str, company_id: str, created_date: str) -> bytes:
    table_xml_parts: List[str] = []
    for url, t_name, desc, cols in _GOBDU_TABLE_DEFS:
        col_parts: List[str] = []
        for cname, ctype, param in cols:
            if ctype == "Date":
                type_xml = f"<Date><Format>{_xml_escape(param or 'YYYY-MM-DD')}</Format></Date>"
            elif ctype == "Numeric":
                acc = int(param or 0)
                type_xml = f"<Numeric><Accuracy>{acc}</Accuracy></Numeric>" if acc > 0 else "<Numeric/>"
            else:
                type_xml = "<AlphaNumeric/>"
            col_parts.append(
                f"        <VariableColumn>\n"
                f"          <Name>{_xml_escape(cname)}</Name>\n"
                f"          {type_xml}\n"
                f"        </VariableColumn>"
            )

        table_xml_parts.append(
            f"    <Table>\n"
            f"      <URL>{_xml_escape(url)}</URL>\n"
            f"      <Name>{_xml_escape(t_name)}</Name>\n"
            f"      <Description>{_xml_escape(desc)}</Description>\n"
            f"      <UTF8/>\n"
            f"      <DecimalSymbol>,</DecimalSymbol>\n"
            f"      <DigitGroupingSymbol>.</DigitGroupingSymbol>\n"
            f"      <SkipNumOfRecords>1</SkipNumOfRecords>\n"
            f"      <VariableLength>\n"
            f"        <ColumnDelimiter>;</ColumnDelimiter>\n"
            f"        <RecordDelimiter>&#13;&#10;</RecordDelimiter>\n"
            f"        <TextEncapsulator>&quot;</TextEncapsulator>\n"
            f"{chr(10).join(col_parts)}\n"
            f"      </VariableLength>\n"
            f"    </Table>"
        )

    xml_str = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<DataSet>\n'
        '  <Version>1.0</Version>\n'
        '  <DataSupplier>\n'
        f'    <Name>{_xml_escape(company_name)}</Name>\n'
        '    <Location>Deutschland</Location>\n'
        f'    <Comment>{_xml_escape(f"Archon OS GoBD Z3-Export ({company_id}) erstellt am {created_date}")}</Comment>\n'
        '  </DataSupplier>\n'
        '  <Media>\n'
        '    <Name>Archon OS GoBD Z3 Datenträgerüberlassung</Name>\n'
        f'{chr(10).join(table_xml_parts)}\n'
        '  </Media>\n'
        '</DataSet>\n'
    )
    return xml_str.encode("utf-8")


def build_gobd_z3_archive(
    company_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Tuple[str, bytes, str]:
    """Erstellt ein vollständiges GoBD-Z3-ZIP-Paket inkl. index.xml und SHA-256-Manifest."""
    from backend.erp_manager import erp_manager

    conn, cid = erp_manager._get_conn(company_id)
    try:
        company_name = cid
        try:
            from backend.corporate_manager import corporate_manager
            comp = corporate_manager.get_company(cid)
            if isinstance(comp, dict) and comp.get("name"):
                company_name = str(comp["name"])
        except Exception as _exc:
            _archon_exc_logger.debug("[gobd_z3_export] Ignorierte Ausnahme (Z.212): %s", _exc)

        doc_clauses = ["1=1"]
        doc_params: List[Any] = []
        if date_from:
            doc_clauses.append("issue_date >= ?")
            doc_params.append(str(date_from)[:10])
        if date_to:
            doc_clauses.append("issue_date <= ?")
            doc_params.append(str(date_to)[:10])

        docs = conn.execute(
            f"SELECT id, doc_type, doc_number, status, entity_id, source_doc_id, issue_date, service_date, due_date, "
            f"currency, tax_regime, amount_net, tax_amount, amount_gross, booked_at, paid_at, recipient_snapshot_json "
            f"FROM erp_documents WHERE {' AND '.join(doc_clauses)} ORDER BY issue_date ASC, id ASC",
            doc_params,
        ).fetchall()
        doc_ids = {str(r["id"]) for r in docs}

        doc_rows = [
            [
                _csv_cell(r["id"]),
                _csv_cell(r["doc_type"]),
                _csv_cell(r["doc_number"]),
                _csv_cell(r["status"]),
                _csv_cell(r["entity_id"]),
                _csv_cell(r["source_doc_id"] or ""),
                _csv_cell(str(r["issue_date"] or "")[:10]),
                _csv_cell(str(r["service_date"] or "")[:10]),
                _csv_cell(str(r["due_date"] or "")[:10]),
                _csv_cell(r["currency"] or "EUR"),
                _csv_cell(r["tax_regime"] or ""),
                _num_de(r["amount_net"], 2),
                _num_de(r["tax_amount"], 2),
                _num_de(r["amount_gross"], 2),
                _csv_cell(r["booked_at"] or ""),
                _csv_cell(r["paid_at"] or ""),
                _csv_cell(r["recipient_snapshot_json"] or "{}"),
            ]
            for r in docs
        ]

        all_lines = conn.execute(
            "SELECT id, document_id, pos_no, title, quantity, unit, unit_price_net, discount_pct, "
            "tax_rate_pct, line_net, line_tax, line_gross FROM erp_document_lines ORDER BY document_id ASC, pos_no ASC"
        ).fetchall()
        line_rows = [
            [
                _csv_cell(r["id"]),
                _csv_cell(r["document_id"]),
                str(int(r["pos_no"] or 0)),
                _csv_cell(r["title"]),
                _num_de(r["quantity"], 2),
                _csv_cell(r["unit"]),
                _num_de(r["unit_price_net"], 2),
                _num_de(r["discount_pct"], 2),
                _num_de(r["tax_rate_pct"], 2),
                _num_de(r["line_net"], 2),
                _num_de(r["line_tax"], 2),
                _num_de(r["line_gross"], 2),
            ]
            for r in all_lines
            if not (date_from or date_to) or str(r["document_id"]) in doc_ids
        ]

        entities = conn.execute(
            "SELECT id, display_name, debtor_no, creditor_no, vat_id, tax_number, street, postal_code, "
            "city, country_code, billing_email FROM crm_entities ORDER BY id ASC"
        ).fetchall()
        entity_rows = [
            [
                _csv_cell(r["id"]),
                _csv_cell(r["display_name"]),
                _csv_cell(r["debtor_no"] or ""),
                _csv_cell(r["creditor_no"] or ""),
                _csv_cell(r["vat_id"] or ""),
                _csv_cell(r["tax_number"] or ""),
                _csv_cell(r["street"] or ""),
                _csv_cell(r["postal_code"] or ""),
                _csv_cell(r["city"] or ""),
                _csv_cell(r["country_code"] or "DE"),
                _csv_cell(r["billing_email"] or ""),
            ]
            for r in entities
        ]
    finally:
        conn.close()

    audit_rows: List[List[str]] = []
    try:
        from backend.audit_log import chained_audit_log
        aconn = chained_audit_log._get_conn()
        try:
            arows = aconn.execute(
                "SELECT id, timestamp, company_id, category, action, agent_id, provider, model, "
                "payload_json, prev_hash, current_hash "
                "FROM audit_log WHERE company_id = ? ORDER BY id ASC",
                (cid,),
            ).fetchall()
            for r in arows:
                audit_rows.append([
                    str(int(r["id"])),
                    _csv_cell(r["timestamp"]),
                    _csv_cell(r["company_id"] or cid),
                    _csv_cell(r["category"]),
                    _csv_cell(r["action"]),
                    _csv_cell(r["agent_id"]),
                    _csv_cell(r["provider"] or ""),
                    _csv_cell(r["model"] or ""),
                    _csv_cell(r["payload_json"] or "{}"),
                    _csv_cell(r["prev_hash"]),
                    _csv_cell(r["current_hash"]),
                ])
        finally:
            aconn.close()
    except Exception as _exc:
        _archon_exc_logger.debug("[gobd_z3_export] Ignorierte Ausnahme (Z.328): %s", _exc)

    schema_headers = {
        url: [col[0] for col in cols]
        for url, _t_name, _desc, cols in _GOBDU_TABLE_DEFS
    }

    today_iso = datetime.date.today().isoformat()
    files: Dict[str, bytes] = {
        "index.xml": _build_index_xml(company_name, cid, today_iso),
        "erp_documents.csv": _rows_to_csv(schema_headers["erp_documents.csv"], doc_rows),
        "erp_document_lines.csv": _rows_to_csv(schema_headers["erp_document_lines.csv"], line_rows),
        "crm_entities.csv": _rows_to_csv(schema_headers["crm_entities.csv"], entity_rows),
        "audit_log.csv": _rows_to_csv(schema_headers["audit_log.csv"], audit_rows),
    }

    manifest_lines = [f"# Archon OS GoBD Z3 Manifest ({cid}) - {today_iso}"]
    for fname in sorted(files):
        digest = hashlib.sha256(files[fname]).hexdigest()
        manifest_lines.append(f"{digest}  {fname}")
    files["MANIFEST_SHA256.txt"] = ("\n".join(manifest_lines) + "\n").encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            zf.writestr(fname, content)
    zip_bytes = buf.getvalue()
    zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    out_filename = f"Archon_GoBD_Z3_{cid}_{today_iso}.zip"
    return out_filename, zip_bytes, zip_sha256
