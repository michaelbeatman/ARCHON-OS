"""
backend/erp_zugferd_pdf.py
=========================
M28 — Abhängigkeitsfreier Pure-Python ZUGFeRD 2.2 / Factur-X Hybrid-PDF-Generator.

Erzeugt ein druckfertiges DIN-A4-Rechnungs-PDF (PDF 1.7 Basis mit EmbeddedFiles/AF
nach ISO 19005-3 / Factur-X EN 16931), das den vollständigen EN-16931-XML-Datensatz
(`factur-x.xml`) samt XMP-Metadaten als maschinenlesbaren Anhang einbettet.
"""

from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("erp_zugferd_pdf")

import datetime
import functools
import hashlib
import os
import struct
import textwrap
import zlib
from typing import Any, Dict, List, Optional, Tuple

from backend.compliance_pdf import _winansi_bytes

PAGE_W = 595.28
PAGE_H = 841.89
MARGIN_L = 44.0
MARGIN_R = 44.0
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


def _as_dict(value: Any) -> Dict[str, Any]:
    """Gibt ein Dict unverändert zurück, sonst ein leeres Dict (Typ-Narrowing fuer mypy)."""
    return value if isinstance(value, dict) else {}


_TTF_CANDIDATES: Dict[str, Tuple[str, List[str]]] = {
    "F1": (
        "LiberationSans",
        [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            # Windows: PDF/A-3b braucht eingebettete Fonts auch auf dem Host.
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
        ],
    ),
    "F2": (
        "LiberationSans-Bold",
        [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf"),
        ],
    ),
    "F3": (
        "LiberationMono",
        [
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "consola.ttf"),
        ],
    ),
}


@functools.lru_cache(maxsize=1)
def _get_srgb_icc_bytes() -> bytes:
    """Liefert ein gültiges sRGB-ICC-Profil für PDF/A-3b /OutputIntents."""
    for icc_path in (
        "/usr/share/ghostscript/10.06.0/iccprofiles/esrgb.icc",
        "/usr/share/ghostscript/10.06.0/iccprofiles/default_rgb.icc",
        "/usr/share/color/icc/colord/sRGB.icc",
    ):
        if os.path.exists(icc_path):
            try:
                with open(icc_path, "rb") as fh:
                    raw = fh.read()
                if len(raw) >= 128:
                    return raw
            except Exception as _exc:
                _archon_exc_logger.debug("[erp_zugferd_pdf] Ignorierte Ausnahme (Z.72): %s", _exc)
    try:
        from PIL import ImageCms
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return b""


@functools.lru_cache(maxsize=8)
def _load_ttf_font_spec(slot: str) -> Optional[Dict[str, Any]]:
    """Liest TrueType-Metriken und Rohdaten für PDF/A-3b Font-Einbettung."""
    base_name, paths = _TTF_CANDIDATES.get(slot, ("", []))
    font_path = next((p for p in paths if os.path.exists(p)), None)
    if not font_path:
        return None
    try:
        with open(font_path, "rb") as fh:
            data = fh.read()
        num_tables = struct.unpack(">H", data[4:6])[0]
        tables: Dict[str, Tuple[int, int]] = {}
        for i in range(num_tables):
            off = 12 + i * 16
            tag = data[off : off + 4].decode("latin1")
            t_off, t_len = struct.unpack(">II", data[off + 8 : off + 16])
            tables[tag] = (t_off, t_len)
        head_off = tables["head"][0]
        units_per_em = struct.unpack(">H", data[head_off + 18 : head_off + 20])[0] or 1000
        xmin, ymin, xmax, ymax = struct.unpack(">hhhh", data[head_off + 36 : head_off + 44])
        hhea_off = tables["hhea"][0]
        ascent, descent = struct.unpack(">hh", data[hhea_off + 4 : hhea_off + 8])
        num_hmetrics = struct.unpack(">H", data[hhea_off + 34 : hhea_off + 36])[0]
        hmtx_off = tables["hmtx"][0]
        advances = [
            struct.unpack(">H", data[hmtx_off + i * 4 : hmtx_off + i * 4 + 2])[0]
            for i in range(num_hmetrics)
        ]
        cmap_off = tables["cmap"][0]
        num_sub = struct.unpack(">H", data[cmap_off + 2 : cmap_off + 4])[0]
        sub_off = None
        for i in range(num_sub):
            pid, eid, rel = struct.unpack(">HHI", data[cmap_off + 4 + i * 8 : cmap_off + 12 + i * 8])
            if (pid, eid) in ((3, 1), (0, 3), (3, 10)):
                fmt = struct.unpack(">H", data[cmap_off + rel : cmap_off + rel + 2])[0]
                if fmt == 4:
                    sub_off = cmap_off + rel
                    break
        if sub_off is None:
            return None
        seg_cnt = struct.unpack(">H", data[sub_off + 6 : sub_off + 8])[0] // 2
        end_codes = struct.unpack(f">{seg_cnt}H", data[sub_off + 14 : sub_off + 14 + seg_cnt * 2])
        start_codes = struct.unpack(f">{seg_cnt}H", data[sub_off + 16 + seg_cnt * 2 : sub_off + 16 + seg_cnt * 4])
        id_deltas = struct.unpack(f">{seg_cnt}h", data[sub_off + 16 + seg_cnt * 4 : sub_off + 16 + seg_cnt * 6])
        ro_base = sub_off + 16 + seg_cnt * 6
        id_ros = struct.unpack(f">{seg_cnt}H", data[ro_base : ro_base + seg_cnt * 2])

        def _gid(cp: int) -> int:
            for idx in range(seg_cnt):
                if start_codes[idx] <= cp <= end_codes[idx]:
                    if id_ros[idx] == 0:
                        return (cp + id_deltas[idx]) & 0xFFFF
                    g_off = ro_base + idx * 2 + id_ros[idx] + 2 * (cp - start_codes[idx])
                    val = struct.unpack(">H", data[g_off : g_off + 2])[0]
                    return (val + id_deltas[idx]) & 0xFFFF if val else 0
            return 0

        scale = 1000.0 / float(units_per_em)
        widths = []
        for code in range(32, 256):
            ch = bytes([code]).decode("cp1252", errors="replace")
            g = _gid(ord(ch))
            aw = advances[min(g, len(advances) - 1)] if advances else int(units_per_em * 0.5)
            widths.append(int(round(aw * scale)))

        cap_height = int(round(ascent * scale * 0.8))
        return {
            "base_name": base_name,
            "bbox": [int(round(v * scale)) for v in (xmin, ymin, xmax, ymax)],
            "ascent": int(round(ascent * scale)),
            "descent": int(round(descent * scale)),
            "cap_height": cap_height,
            "widths": widths,
            "raw_len": len(data),
            "compressed": zlib.compress(data, level=6),
        }
    except Exception:
        return None


def _txt_cmd(font: str, size: float, x: float, y: float, text: str) -> bytes:
    return (
        f"BT /{font} {size:.1f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm (".encode("ascii")
        + _winansi_bytes(text)
        + b") Tj ET"
    )


def _right_txt_cmd(font: str, size: float, right_x: float, y: float, text: str) -> bytes:
    # Approximation für Helvetica/Courier bei rechtsbündigen Spalten
    approx_w = len(str(text or "")) * size * (0.50 if font != "F3" else 0.60)
    x = max(MARGIN_L, right_x - approx_w)
    return _txt_cmd(font, size, x, y, text)


def _format_money(val: Any, currency: str = "EUR") -> str:
    try:
        num = float(val or 0.0)
    except (TypeError, ValueError):
        num = 0.0
    s = f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}"


def _build_xmp_facturx_metadata(doc_num: str, issue_iso: str, doc_type: str = "invoice") -> bytes:
    fx_doc_type = "INVOICE"
    guideline_id = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
    xmp = f"""<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
      <pdfaid:part>3</pdfaid:part>
      <pdfaid:conformance>B</pdfaid:conformance>
    </rdf:Description>
    <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title><rdf:Alt><rdf:li xml:lang="de">ZUGFeRD E-Rechnung {doc_num}</rdf:li></rdf:Alt></dc:title>
      <dc:date><rdf:Seq><rdf:li>{issue_iso}</rdf:li></rdf:Seq></dc:date>
    </rdf:Description>
    <rdf:Description rdf:about=""
        xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/"
        xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#"
        xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
      <pdfaExtension:schemas>
        <rdf:Bag>
          <rdf:li rdf:parseType="Resource">
            <pdfaSchema:schema>Factur-X PDFA Extension Schema</pdfaSchema:schema>
            <pdfaSchema:namespaceURI>urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#</pdfaSchema:namespaceURI>
            <pdfaSchema:prefix>fx</pdfaSchema:prefix>
            <pdfaSchema:property>
              <rdf:Seq>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>DocumentFileName</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>name of the embedded XML invoice file</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>DocumentType</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>INVOICE</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>Version</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>The actual version of the Factur-X XML schema</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>ConformanceLevel</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>The conformance level of the embedded Factur-X data</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>GuidelineSpecifiedDocumentContextParameter</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>EN 16931 / XRechnung GuidelineID</pdfaProperty:description>
                </rdf:li>
              </rdf:Seq>
            </pdfaSchema:property>
          </rdf:li>
        </rdf:Bag>
      </pdfaExtension:schemas>
    </rdf:Description>
    <rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
      <fx:DocumentType>{fx_doc_type}</fx:DocumentType>
      <fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>
      <fx:Version>1.0</fx:Version>
      <fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>
      <fx:GuidelineSpecifiedDocumentContextParameter>
        <fx:GuidelineID>{guideline_id}</fx:GuidelineID>
      </fx:GuidelineSpecifiedDocumentContextParameter>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""
    return xmp.encode("utf-8")


def _serialize_pdf_objects(objects: List[bytes], info_obj_num: int, doc_id_seed: str = "archon-pdfa3") -> bytes:
    """Serialisiert nummerierte PDF-Objekte (1..N) inklusive xref-Tabelle, Trailer und /ID."""
    buf = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
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

    # Kein kryptografischer Zweck (PDF-/ID-Stabilität) — explizit markieren.
    fid = hashlib.md5(doc_id_seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    buf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_obj_num} 0 R /ID [<{fid}> <{fid}>] >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(buf)


def build_zugferd_invoice_pdf(
    doc: Dict[str, Any],
    seller: Dict[str, Any],
    buyer: Dict[str, Any],
    embedded_xml: str,
) -> bytes:
    """Erstellt ein ZUGFeRD-2.2-/Factur-X-Hybrid-PDF inklusive eingebettetem `factur-x.xml`."""
    doc_num = str(doc.get("doc_number") or doc.get("id") or "RE-0001")
    doc_type = str(doc.get("doc_type") or "invoice")
    heading = "GUTSCHRIFT (ZUGFeRD 2.2)" if doc_type == "credit_note" else "RECHNUNG (ZUGFeRD 2.2 / EN 16931)"
    currency = str(doc.get("currency") or "EUR").upper()
    issue_date = str(doc.get("issue_date") or datetime.date.today().isoformat())[:10]
    due_date = str(doc.get("due_date") or issue_date)[:10]

    seller_addr = _as_dict(seller.get("address"))
    seller_tax = _as_dict(seller.get("tax"))
    seller_bank = _as_dict(seller.get("bank"))
    seller_contact = _as_dict(seller.get("contact"))
    seller_reg = _as_dict(seller.get("registry"))
    service_date = str(doc.get("service_date") or issue_date)[:10]

    seller_name = str(seller.get("name") or "Archon Systems GmbH")
    seller_line = (
        f"{seller_name} | {seller_addr.get('street', '')} | "
        f"{seller_addr.get('postal_code', '')} {seller_addr.get('city', '')}"
    )

    cmds: List[bytes] = []

    # Kopfband
    cmds.append(b"0.07 0.09 0.14 rg")
    cmds.append(f"0 {PAGE_H - 58:.2f} {PAGE_W:.2f} 58 re f".encode("ascii"))
    cmds.append(b"0.01 0.52 0.78 rg")
    cmds.append(f"0 {PAGE_H - 61:.2f} {PAGE_W:.2f} 3 re f".encode("ascii"))
    cmds.append(b"1 1 1 rg")
    cmds.append(_txt_cmd("F2", 14.0, MARGIN_L, PAGE_H - 27.0, seller_name))
    cmds.append(b"0.78 0.84 0.93 rg")
    cmds.append(_txt_cmd("F1", 8.5, MARGIN_L, PAGE_H - 44.0, heading))
    cmds.append(_right_txt_cmd("F3", 9.5, PAGE_W - MARGIN_R, PAGE_H - 28.0, f"Beleg-Nr: {doc_num}"))

    # Absenderzeile + Empfängerblock
    y = PAGE_H - 92.0
    cmds.append(b"0.42 0.45 0.52 rg")
    cmds.append(_txt_cmd("F1", 7.5, MARGIN_L, y, seller_line))
    y -= 16.0
    cmds.append(b"0.08 0.10 0.14 rg")
    buyer_lines = [
        str(buyer.get("display_name") or "Kunde"),
        str(buyer.get("street") or ""),
        f"{buyer.get('postal_code', '')} {buyer.get('city', '')}".strip(),
        str(buyer.get("country_code") or "DE"),
    ]
    for bl in [x for x in buyer_lines if x]:
        cmds.append(_txt_cmd("F2" if bl == buyer_lines[0] else "F1", 10.0, MARGIN_L, y, bl))
        y -= 13.5

    # Metadaten rechts
    regime_raw = str(doc.get("tax_regime") or "standard_19")
    regime_labels = {
        "standard_19": "Regelbesteuerung (19%)",
        "reduced_7": "Ermäßigt (7%)",
        "small_business": "§ 19 UStG (Kleinunternehmer)",
        "reverse_charge": "§ 13b UStG (Reverse Charge)",
        "intra_eu": "§ 4 Nr. 1b UStG (Innergem.)",
    }
    meta_y = PAGE_H - 108.0
    meta_x = PAGE_W - 210.0
    meta_rows = [
        ("Belegnummer:", doc_num),
        ("Belegdatum:", issue_date),
        ("Leistungsdatum:", service_date),
        ("Fällig bis:", due_date),
        ("USt-Regime:", regime_labels.get(regime_raw, regime_raw)),
    ]
    if buyer.get("leitweg_id"):
        meta_rows.append(("Leitweg-ID:", str(buyer["leitweg_id"])))
    if buyer.get("debtor_no"):
        meta_rows.append(("Debitoren-Nr:", str(buyer["debtor_no"])))
    for k, v in meta_rows:
        cmds.append(b"0.42 0.45 0.52 rg")
        cmds.append(_txt_cmd("F1", 8.5, meta_x, meta_y, k))
        cmds.append(b"0.08 0.10 0.14 rg")
        cmds.append(_txt_cmd("F2", 8.5, meta_x + 74.0, meta_y, v[:26]))
        meta_y -= 13.0

    # Positions-Tabelle (mehrseitig, kein Abschneiden bei vielen Positionen)
    def _append_table_header(target_cmds: List[bytes], start_y: float) -> float:
        target_cmds.append(b"0.93 0.95 0.98 rg")
        target_cmds.append(f"{MARGIN_L:.2f} {start_y - 4:.2f} {CONTENT_W:.2f} 18 re f".encode("ascii"))
        target_cmds.append(b"0.08 0.10 0.14 rg")
        target_cmds.append(_txt_cmd("F2", 8.5, MARGIN_L + 4, start_y + 1, "Pos"))
        target_cmds.append(_txt_cmd("F2", 8.5, MARGIN_L + 32, start_y + 1, "Beschreibung"))
        target_cmds.append(_right_txt_cmd("F2", 8.5, MARGIN_L + 315, start_y + 1, "Menge"))
        target_cmds.append(_right_txt_cmd("F2", 8.5, MARGIN_L + 395, start_y + 1, "Einzel netto"))
        target_cmds.append(_right_txt_cmd("F2", 8.5, MARGIN_L + 445, start_y + 1, "USt %"))
        target_cmds.append(_right_txt_cmd("F2", 8.5, PAGE_W - MARGIN_R - 4, start_y + 1, "Gesamt netto"))
        return start_y - 20.0

    def _start_continuation_page(page_num: int) -> Tuple[List[bytes], float]:
        c: List[bytes] = []
        c.append(b"0.07 0.09 0.14 rg")
        c.append(f"0 {PAGE_H - 40:.2f} {PAGE_W:.2f} 40 re f".encode("ascii"))
        c.append(b"1 1 1 rg")
        c.append(_txt_cmd("F2", 10.5, MARGIN_L, PAGE_H - 25.0, f"{seller_name}  -  {heading}"))
        c.append(_right_txt_cmd("F3", 9.0, PAGE_W - MARGIN_R, PAGE_H - 25.0, f"Beleg-Nr: {doc_num}  |  Seite {page_num}"))
        return c, _append_table_header(c, PAGE_H - 72.0)

    y = min(y, meta_y) - 24.0
    y = _append_table_header(cmds, y)

    pages_cmds: List[List[bytes]] = [cmds]
    lines = doc.get("lines") or []
    for idx, ln in enumerate(lines, start=1):
        if y < 120.0:
            cmds, y = _start_continuation_page(len(pages_cmds) + 1)
            pages_cmds.append(cmds)

        pos = str(ln.get("pos_no") or idx)
        title = str(ln.get("title") or "Leistung")
        wrapped = textwrap.wrap(title, width=44) or [title]
        qty_str = f"{float(ln.get('quantity') or 1.0):.2f} {ln.get('unit') or 'Stk.'}"
        unit_p = _format_money(ln.get("unit_price_net"), currency)
        vat_p = f"{float(ln.get('tax_rate_pct') or 0.0):.0f}%"
        net_p = _format_money(ln.get("line_net"), currency)

        cmds.append(b"0.08 0.10 0.14 rg")
        cmds.append(_txt_cmd("F1", 8.5, MARGIN_L + 4, y, pos))
        cmds.append(_txt_cmd("F2", 8.5, MARGIN_L + 32, y, wrapped[0]))
        cmds.append(_right_txt_cmd("F1", 8.5, MARGIN_L + 315, y, qty_str))
        cmds.append(_right_txt_cmd("F1", 8.5, MARGIN_L + 395, y, unit_p))
        cmds.append(_right_txt_cmd("F1", 8.5, MARGIN_L + 445, y, vat_p))
        cmds.append(_right_txt_cmd("F2", 8.5, PAGE_W - MARGIN_R - 4, y, net_p))
        y -= 13.0
        for extra in wrapped[1:3]:
            cmds.append(b"0.35 0.39 0.46 rg")
            cmds.append(_txt_cmd("F1", 8.0, MARGIN_L + 32, y, extra))
            y -= 11.0
        cmds.append(b"0.86 0.89 0.93 RG 0.5 w")
        cmds.append(f"{MARGIN_L:.2f} {y + 6:.2f} m {PAGE_W - MARGIN_R:.2f} {y + 6:.2f} l S".encode("ascii"))
        y -= 6.0

    # Summenblock benötigt ~65 pt + Fußbereich 95 pt -> bei Bedarf auf neue Schlussseite
    if y < 165.0:
        cmds = []
        cmds.append(b"0.07 0.09 0.14 rg")
        cmds.append(f"0 {PAGE_H - 40:.2f} {PAGE_W:.2f} 40 re f".encode("ascii"))
        c_title = f"{seller_name}  -  {heading}"
        cmds.append(b"1 1 1 rg")
        cmds.append(_txt_cmd("F2", 10.5, MARGIN_L, PAGE_H - 25.0, c_title))
        cmds.append(_right_txt_cmd("F3", 9.0, PAGE_W - MARGIN_R, PAGE_H - 25.0, f"Beleg-Nr: {doc_num}  |  Seite {len(pages_cmds) + 1}"))
        pages_cmds.append(cmds)
        y = PAGE_H - 80.0

    # Summenblock
    is_small_biz = (regime_raw == "small_business") or bool(seller_tax.get("small_business"))
    y -= 14.0
    sum_x = PAGE_W - 210.0
    cmds.append(b"0.08 0.10 0.14 rg")
    cmds.append(_txt_cmd("F1", 9.5, sum_x, y, "Summe Netto:"))
    cmds.append(_right_txt_cmd("F1", 9.5, PAGE_W - MARGIN_R - 4, y, _format_money(doc.get("amount_net"), currency)))
    y -= 14.0
    vat_label = "USt (§ 19 UStG):" if is_small_biz else "Umsatzsteuer:"
    cmds.append(_txt_cmd("F1", 9.5, sum_x, y, vat_label))
    cmds.append(_right_txt_cmd("F1", 9.5, PAGE_W - MARGIN_R - 4, y, _format_money(doc.get("tax_amount"), currency)))
    y -= 16.0
    cmds.append(_txt_cmd("F2", 11.0, sum_x, y, "Gesamtbetrag:"))
    cmds.append(_right_txt_cmd("F2", 11.0, PAGE_W - MARGIN_R - 4, y, _format_money(doc.get("amount_gross"), currency)))
    if is_small_biz:
        y -= 15.0
        cmds.append(b"0.32 0.36 0.44 rg")
        cmds.append(_txt_cmd("F1", 8.0, MARGIN_L, y, "Hinweis: Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung)."))

    # Zahlungshinweis & Fußzeile (§ 35a GmbHG / § 125a HGB Pflichtangaben)
    iban = str(seller_bank.get("iban") or "")
    bic = str(seller_bank.get("bic") or "")
    reg_court = str(seller_reg.get("court") or "")
    reg_num = str(seller_reg.get("number") or "")
    reg_dirs = str(seller_reg.get("managing_directors") or "")
    reg_line = "  |  ".join(x for x in (reg_court, reg_num, f"GF: {reg_dirs}" if reg_dirs else "") if x)
    cmds.append(b"0.32 0.36 0.44 rg")
    cmds.append(_txt_cmd("F1", 8.5, MARGIN_L, 78.0, f"Bankverbindung: IBAN {iban}  |  BIC {bic}  |  Verwendungszweck: {doc_num}"))
    cmds.append(_txt_cmd("F1", 7.5, MARGIN_L, 64.0, f"USt-IdNr.: {seller_tax.get('vat_id', '')}  |  Steuernr.: {seller_tax.get('tax_number', '')}  |  Kontakt: {seller_contact.get('email', '')}"))
    if reg_line:
        cmds.append(_txt_cmd("F1", 7.0, MARGIN_L, 52.0, reg_line))
    for p_cmds in pages_cmds:
        p_cmds.append(b"0.01 0.52 0.78 rg")
        p_cmds.append(_txt_cmd("F2", 7.5, MARGIN_L, 38.0, "Eingebettete EN-16931-/Factur-X-/ZUGFeRD-2.2-CII-XML-Strukturdaten: factur-x.xml"))

    xml_bytes = embedded_xml.encode("utf-8")
    xmp_bytes = _build_xmp_facturx_metadata(doc_num, issue_date, doc_type=doc_type)

    # Feste Basis-Objekte (1..9), optional FontDescriptor/FontFile2 + OutputIntent, danach Seiten:
    # 1: Catalog, 2: Pages, 3..5: Fonts (F1, F2, F3), 6: EmbeddedFile, 7: Filespec, 8: XMP, 9: Info
    objects: List[bytes] = [b"", b"", b"", b"", b"", b"", b"", b"", b""]
    extra_objects: List[bytes] = []

    def _alloc_obj(body: bytes) -> int:
        extra_objects.append(body)
        return 9 + len(extra_objects)

    font_fallbacks = {
        "F1": b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        "F2": b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        "F3": b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
    }
    for slot_idx, slot in enumerate(("F1", "F2", "F3"), start=2):
        spec = _load_ttf_font_spec(slot)
        if spec:
            ff_stream = (
                f"<< /Length {len(spec['compressed'])} /Length1 {spec['raw_len']} /Filter /FlateDecode >>\nstream\n".encode("ascii")
                + spec["compressed"]
                + b"\nendstream"
            )
            ff_num = _alloc_obj(ff_stream)
            bx = spec["bbox"]
            fd_num = _alloc_obj(
                (
                    f"<< /Type /FontDescriptor /FontName /{spec['base_name']} /Flags 32 "
                    f"/FontBBox [{bx[0]} {bx[1]} {bx[2]} {bx[3]}] "
                    f"/ItalicAngle 0 /Ascent {spec['ascent']} /Descent {spec['descent']} "
                    f"/CapHeight {spec['cap_height']} /StemV 80 /FontFile2 {ff_num} 0 R >>"
                ).encode("ascii")
            )
            widths_str = " ".join(str(w) for w in spec["widths"])
            objects[slot_idx] = (
                f"<< /Type /Font /Subtype /TrueType /BaseFont /{spec['base_name']} "
                f"/FirstChar 32 /LastChar 255 /Widths [{widths_str}] "
                f"/FontDescriptor {fd_num} 0 R /Encoding /WinAnsiEncoding >>"
            ).encode("ascii")
        else:
            objects[slot_idx] = font_fallbacks[slot]

    icc_raw = _get_srgb_icc_bytes()
    output_intents_entry = ""
    if icc_raw:
        icc_comp = zlib.compress(icc_raw, level=6)
        icc_num = _alloc_obj(
            f"<< /N 3 /Alternate /DeviceRGB /Length {len(icc_comp)} /Filter /FlateDecode >>\nstream\n".encode("ascii")
            + icc_comp
            + b"\nendstream"
        )
        oi_num = _alloc_obj(
            (
                f"<< /Type /OutputIntent /S /GTS_PDFA1 /OutputConditionIdentifier (sRGB IEC61966-2.1) "
                f"/RegistryName (http://www.color.org) /Info (sRGB IEC61966-2.1) /DestOutputProfile {icc_num} 0 R >>"
            ).encode("ascii")
        )
        output_intents_entry = f" /OutputIntents [{oi_num} 0 R]"
    else:
        oi_num = _alloc_obj(
            b"<< /Type /OutputIntent /S /GTS_PDFA1 /OutputConditionIdentifier (sRGB IEC61966-2.1) /RegistryName (http://www.color.org) /Info (sRGB IEC61966-2.1) >>"
        )
        output_intents_entry = f" /OutputIntents [{oi_num} 0 R]"

    objects.extend(extra_objects)

    first_page_obj = len(objects) + 1
    kids_refs = " ".join(f"{first_page_obj + (i * 2)} 0 R" for i in range(len(pages_cmds)))
    objects[0] = (
        f"<< /Type /Catalog /Pages 2 0 R /Metadata 8 0 R /Lang (de-DE){output_intents_entry} "
        f"/Names << /EmbeddedFiles << /Names [(factur-x.xml) 7 0 R] >> >> /AF [7 0 R] >>"
    ).encode("ascii")
    objects[1] = f"<< /Type /Pages /Kids [{kids_refs}] /Count {len(pages_cmds)} >>".encode("ascii")
    objects[5] = (
        f"<< /Type /EmbeddedFile /Subtype /text#2Fxml /Params << /Size {len(xml_bytes)} >> /Length {len(xml_bytes)} >>\nstream\n".encode("ascii")
        + xml_bytes
        + b"\nendstream"
    )
    objects[6] = b"<< /Type /Filespec /F (factur-x.xml) /UF (factur-x.xml) /Desc (ZUGFeRD 2.2 / Factur-X EN 16931 XML Invoice) /AFRelationship /Alternative /EF << /F 6 0 R /UF 6 0 R >> >>"
    objects[7] = f"<< /Type /Metadata /Subtype /XML /Length {len(xmp_bytes)} >>\nstream\n".encode("ascii") + xmp_bytes + b"\nendstream"
    objects[8] = b"<< /Title (" + _winansi_bytes(f"ZUGFeRD Rechnung {doc_num}") + b") /Producer (Archon OS ERP M28) /Creator (Archon OS) >>"

    for idx, p_cmds in enumerate(pages_cmds):
        stream_bytes = b"\n".join(p_cmds)
        content_obj_num = first_page_obj + (idx * 2) + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents {content_obj_num} 0 R >>".encode("ascii")
        )
        objects.append(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream"
        )

    return _serialize_pdf_objects(objects, info_obj_num=9, doc_id_seed=f"{doc_num}:{issue_date}:{len(xml_bytes)}")


def _draw_qr_pdf_cmds(matrix: List[List[int]], x: float, y: float, target_pt: float) -> List[bytes]:
    """Rendert eine QR-Code-Matrix als scharfe PDF-Vektorrechtecke (ISO 32000)."""
    dim = len(matrix)
    if dim <= 0:
        return []
    mod = target_pt / float(dim)
    cmds: List[bytes] = [b"q 1 1 1 rg"]
    cmds.append(f"{x - 3:.2f} {y - 3:.2f} {target_pt + 6:.2f} {target_pt + 6:.2f} re f".encode("ascii"))
    cmds.append(b"0.06 0.09 0.16 rg")
    for r, row in enumerate(matrix):
        ry = y + target_pt - (r + 1) * mod
        for c, cell in enumerate(row):
            if cell:
                rx = x + c * mod
                cmds.append(f"{rx:.2f} {ry:.2f} {mod + 0.05:.2f} {mod + 0.05:.2f} re f".encode("ascii"))
    cmds.append(b"Q")
    return cmds


def build_corporate_template_pdf(rendered: Dict[str, Any]) -> bytes:
    """Erstellt ein druckfertiges DIN-A4-PDF für beliebige Vorlagen-Studio-/Beleg-Daten (M29)."""
    meta = _as_dict(rendered.get("pdf_meta"))
    layout = _as_dict(rendered.get("layout"))
    margin_mm = float(layout.get("margin_mm") or 15.0)
    margin_pt = max(24.0, min(85.0, margin_mm * 72.0 / 25.4))
    right_edge = PAGE_W - margin_pt

    doc_title = str(meta.get("doc_title") or rendered.get("template_type") or "BELEG").upper()
    doc_num = str(meta.get("doc_number") or "-")
    company_name = str(meta.get("company_name") or rendered.get("company_name") or "Archon Systems GmbH")
    company_addr = str(meta.get("company_address") or "")
    company_tax = str(meta.get("company_tax") or "")
    company_bank = str(meta.get("company_bank") or "")
    rec_lines = [str(x) for x in (meta.get("recipient_lines") or []) if str(x or "").strip()]
    currency = str(meta.get("currency") or "EUR")

    cmds: List[bytes] = []

    # Optional DIN 5008 Falz- & Lochmarken links (105 mm / 148.5 mm / 210 mm ab Oberkante)
    if layout.get("show_fold_marks", True):
        cmds.append(b"0.65 0.69 0.76 RG 0.5 w")
        for mm_from_top, tick_len in ((105.0, 12.0), (148.5, 16.0), (210.0, 12.0)):
            y_mark = PAGE_H - (mm_from_top * 72.0 / 25.4)
            cmds.append(f"8.00 {y_mark:.2f} m {8.00 + tick_len:.2f} {y_mark:.2f} l S".encode("ascii"))

    # Kopfzeile
    cmds.append(b"0.07 0.09 0.14 rg")
    cmds.append(f"0 {PAGE_H - 58:.2f} {PAGE_W:.2f} 58 re f".encode("ascii"))
    cmds.append(b"0.31 0.27 0.90 rg")
    cmds.append(f"0 {PAGE_H - 61:.2f} {PAGE_W:.2f} 3 re f".encode("ascii"))
    cmds.append(b"1 1 1 rg")
    cmds.append(_txt_cmd("F2", 14.0, margin_pt, PAGE_H - 27.0, company_name))
    cmds.append(b"0.78 0.84 0.93 rg")
    cmds.append(_txt_cmd("F1", 8.5, margin_pt, PAGE_H - 44.0, doc_title))
    if doc_num and doc_num != "-":
        cmds.append(_right_txt_cmd("F3", 9.5, right_edge, PAGE_H - 28.0, f"Beleg-Nr: {doc_num}"))

    # Absender & Empfänger
    y = PAGE_H - 92.0
    cmds.append(b"0.42 0.45 0.52 rg")
    cmds.append(_txt_cmd("F1", 7.5, margin_pt, y, company_addr))
    y -= 16.0
    cmds.append(b"0.08 0.10 0.14 rg")
    for idx, rl in enumerate(rec_lines):
        cmds.append(_txt_cmd("F2" if idx == 0 else "F1", 10.0, margin_pt, y, rl))
        y -= 13.5

    # Metadaten rechts
    meta_y = PAGE_H - 108.0
    meta_x = max(margin_pt + 220.0, PAGE_W - margin_pt - 180.0)
    for k, v in (meta.get("meta_pairs") or []):
        cmds.append(b"0.42 0.45 0.52 rg")
        cmds.append(_txt_cmd("F1", 8.5, meta_x, meta_y, str(k)))
        cmds.append(b"0.08 0.10 0.14 rg")
        cmds.append(_txt_cmd("F2", 8.5, meta_x + 74.0, meta_y, str(v)[:26]))
        meta_y -= 13.0

    y = min(y, meta_y) - 20.0
    subject = str(meta.get("subject") or "")
    if subject:
        cmds.append(b"0.08 0.10 0.14 rg")
        cmds.append(_txt_cmd("F2", 11.5, margin_pt, y, subject[:90]))
        y -= 18.0

    intro = str(meta.get("intro_text") or "").strip()
    if intro:
        cmds.append(b"0.22 0.27 0.35 rg")
        for line in intro.splitlines():
            for wline in (textwrap.wrap(line, width=88) or [""]):
                if y < 140.0:
                    break
                cmds.append(_txt_cmd("F1", 9.0, margin_pt, y, wline))
                y -= 12.0
        y -= 8.0

    items = meta.get("items") or []
    if items and y > 180.0:
        cmds.append(b"0.93 0.95 0.98 rg")
        cmds.append(f"{margin_pt:.2f} {y - 4:.2f} {right_edge - margin_pt:.2f} 18 re f".encode("ascii"))
        cmds.append(b"0.08 0.10 0.14 rg")
        cmds.append(_txt_cmd("F2", 8.5, margin_pt + 4, y + 1, "Pos"))
        cmds.append(_txt_cmd("F2", 8.5, margin_pt + 32, y + 1, "Bezeichnung"))
        cmds.append(_right_txt_cmd("F2", 8.5, right_edge - 150, y + 1, "Menge"))
        cmds.append(_right_txt_cmd("F2", 8.5, right_edge - 75, y + 1, "Einzel"))
        cmds.append(_right_txt_cmd("F2", 8.5, right_edge - 4, y + 1, "Gesamt"))
        y -= 20.0

        for idx, item in enumerate(items, start=1):
            if y < 160.0:
                break
            desc = str(item.get("desc") or "")
            wrapped = textwrap.wrap(desc, width=48) or [desc]
            qty_str = f"{item.get('qty', 1)} {item.get('unit', 'Stk')}"
            unit_str = _format_money(item.get("price", 0.0), currency)
            line_str = _format_money(item.get("line_net", 0.0), currency)

            cmds.append(b"0.08 0.10 0.14 rg")
            cmds.append(_txt_cmd("F1", 8.5, margin_pt + 4, y, str(item.get("pos", idx))))
            cmds.append(_txt_cmd("F2", 8.5, margin_pt + 32, y, wrapped[0]))
            cmds.append(_right_txt_cmd("F1", 8.5, right_edge - 150, y, qty_str))
            cmds.append(_right_txt_cmd("F1", 8.5, right_edge - 75, y, unit_str))
            cmds.append(_right_txt_cmd("F2", 8.5, right_edge - 4, y, line_str))
            y -= 13.0
            for extra in wrapped[1:3]:
                cmds.append(b"0.35 0.39 0.46 rg")
                cmds.append(_txt_cmd("F1", 8.0, margin_pt + 32, y, extra))
                y -= 11.0
            cmds.append(b"0.86 0.89 0.93 RG 0.5 w")
            cmds.append(f"{margin_pt:.2f} {y + 6:.2f} m {right_edge:.2f} {y + 6:.2f} l S".encode("ascii"))
            y -= 6.0

        y -= 12.0
        sum_x = max(margin_pt + 220.0, right_edge - 180.0)
        cmds.append(b"0.08 0.10 0.14 rg")
        cmds.append(_txt_cmd("F1", 9.5, sum_x, y, "Nettobetrag:"))
        cmds.append(_right_txt_cmd("F1", 9.5, right_edge - 4, y, _format_money(meta.get("net_total"), currency)))
        y -= 14.0
        cmds.append(_txt_cmd("F1", 9.5, sum_x, y, "Umsatzsteuer:"))
        cmds.append(_right_txt_cmd("F1", 9.5, right_edge - 4, y, _format_money(meta.get("tax_amount"), currency)))
        y -= 16.0
        cmds.append(_txt_cmd("F2", 11.0, sum_x, y, "Gesamtbetrag:"))
        cmds.append(_right_txt_cmd("F2", 11.0, right_edge - 4, y, _format_money(meta.get("gross_total"), currency)))
        y -= 18.0

    outro = str(meta.get("outro_text") or "").strip()
    if outro and y > 115.0:
        cmds.append(b"0.22 0.27 0.35 rg")
        for line in outro.splitlines():
            for wline in (textwrap.wrap(line, width=68 if meta.get("epc_qr_payload") else 88) or [""]):
                if y < 95.0:
                    break
                cmds.append(_txt_cmd("F1", 8.5, margin_pt, y, wline))
                y -= 11.5

    # Vector EPC-QR GiroCode unten links oberhalb Fußzeile
    epc_payload = str(meta.get("epc_qr_payload") or "")
    if epc_payload and layout.get("show_girocode", True):
        try:
            from backend.qr_girocode import generate_qr_matrix
            qr_mat = generate_qr_matrix(epc_payload)
            cmds.extend(_draw_qr_pdf_cmds(qr_mat, x=right_edge - 70.0, y=82.0, target_pt=66.0))
            cmds.append(b"0.32 0.36 0.44 rg")
            cmds.append(_txt_cmd("F2", 7.0, right_edge - 70.0, 73.0, "GiroCode EPC-QR"))
        except Exception as _exc:
            _archon_exc_logger.debug("[erp_zugferd_pdf] Ignorierte Ausnahme (Z.733): %s", _exc)

    # Fußzeile
    cmds.append(b"0.86 0.89 0.93 RG 0.5 w")
    cmds.append(f"{margin_pt:.2f} 64.00 m {right_edge:.2f} 64.00 l S".encode("ascii"))
    cmds.append(b"0.38 0.42 0.49 rg")
    cmds.append(_txt_cmd("F1", 7.5, margin_pt, 50.0, f"{company_name} | {company_addr}"))
    cmds.append(_txt_cmd("F1", 7.5, margin_pt, 39.0, company_tax))
    if layout.get("show_bank_footer", True) and company_bank:
        cmds.append(_txt_cmd("F1", 7.5, margin_pt, 28.0, company_bank))

    page_stream = b"\n".join(cmds)
    objects: List[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [6 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents 7 0 R >>".encode("ascii"),
        f"<< /Length {len(page_stream)} >>\nstream\n".encode("ascii") + page_stream + b"\nendstream",
        b"<< /Title (" + _winansi_bytes(f"{doc_title} {doc_num}") + b") /Producer (Archon OS Formular-Editor M29) /Creator (Archon OS) >>",
    ]
    return _serialize_pdf_objects(objects, info_obj_num=8)
