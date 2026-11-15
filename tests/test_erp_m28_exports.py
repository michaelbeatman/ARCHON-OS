"""
Tests für Meilenstein 28: ERP-Kernsystem-Ausbau
- EN 16931 / XRechnung 3.0 UBL-2.1 XML Export
- DATEV EXTF Buchungsstapel CSV Export (SKR03 + CSV-Injection-Schutz)
- Automatische Lagerbestands-Abbuchung & Storno-Rückbuchung bei Rechnungen
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.erp_manager as erp_mod
from archon.routers import _rbac as rbac_mod
from archon.routers import auth as auth_router_mod
from archon.routers import erp as erp_router_mod


@pytest.fixture()
def isolated_erp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> erp_mod.ERPManager:
    tenants_dir = tmp_path / "tenants"
    tenants_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tenants_dir))
    mgr = erp_mod.ERPManager()
    monkeypatch.setattr(erp_mod, "erp_manager", mgr)
    return mgr


@pytest.fixture()
def erp_client(isolated_erp: erp_mod.ERPManager, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(erp_router_mod.router)
    monkeypatch.setattr(rbac_mod, "is_configured", lambda: True)
    monkeypatch.setattr(
        auth_router_mod,
        "get_current_user_from_request",
        lambda _req: {"role": "admin", "username": "pytest-admin"},
    )
    monkeypatch.setattr(erp_router_mod, "require_admin_or_503", lambda _req: None)
    return TestClient(app)


def test_inventory_stock_deducted_once_on_booking_and_restored_on_cancel(
    isolated_erp: erp_mod.ERPManager,
) -> None:
    cid = "m28-stock-test"
    ent = isolated_erp.save_entity(
        {
            "display_name": "Kunde Lager GmbH",
            "is_customer": 1,
            "street": "Musterweg 1",
            "postal_code": "10115",
            "city": "Berlin",
            "country_code": "DE",
        },
        company_id=cid,
    )
    itm = isolated_erp.save_item(
        {
            "item_no": "HW-100",
            "item_type": "product",
            "title": "Edge Appliance <Pro> & Co",
            "sales_price_net": 500.0,
            "tax_rate_pct": 19.0,
            "track_inventory": 1,
            "stock_qty": 10.0,
        },
        company_id=cid,
    )

    # 1. Draft invoice must NOT deduct stock yet
    draft_doc = isolated_erp.save_document(
        {
            "doc_type": "invoice",
            "status": "draft",
            "entity_id": ent["entity"]["id"],
            "lines": [{"item_id": itm["id"], "quantity": 3}],
        },
        company_id=cid,
    )
    items_after_draft = isolated_erp.list_items(company_id=cid)["items"]
    assert next(i for i in items_after_draft if i["id"] == itm["id"])["stock_qty"] == 10.0

    # 2. Booking deducts 3 units cleanly (10 -> 7)
    booked_doc = isolated_erp.save_document(
        {"id": draft_doc["id"], "status": "booked"},
        company_id=cid,
    )
    assert booked_doc["stock_deducted"] == 1
    items_after_book = isolated_erp.list_items(company_id=cid)["items"]
    assert next(i for i in items_after_book if i["id"] == itm["id"])["stock_qty"] == 7.0

    # 3. Marking as paid must NOT double-deduct
    paid_doc = isolated_erp.save_document(
        {"id": draft_doc["id"], "status": "paid"},
        company_id=cid,
    )
    assert paid_doc["status"] == "paid"
    items_after_paid = isolated_erp.list_items(company_id=cid)["items"]
    assert next(i for i in items_after_paid if i["id"] == itm["id"])["stock_qty"] == 7.0

    # 4. Cancelling booked invoice restores stock cleanly
    booked_2 = isolated_erp.save_document(
        {
            "doc_type": "invoice",
            "status": "booked",
            "entity_id": ent["entity"]["id"],
            "lines": [{"item_id": itm["id"], "quantity": 2}],
        },
        company_id=cid,
    )
    assert next(i for i in isolated_erp.list_items(company_id=cid)["items"] if i["id"] == itm["id"])["stock_qty"] == 5.0

    cancelled_2 = isolated_erp.save_document(
        {"id": booked_2["id"], "status": "cancelled"},
        company_id=cid,
    )
    assert cancelled_2["stock_deducted"] == 0
    assert next(i for i in isolated_erp.list_items(company_id=cid)["items"] if i["id"] == itm["id"])["stock_qty"] == 7.0


def test_xrechnung_ubl_xml_and_datev_extf_export_endpoints(
    isolated_erp: erp_mod.ERPManager,
    erp_client: TestClient,
) -> None:
    cid = "m28-export-test"
    ent = isolated_erp.save_entity(
        {
            "display_name": "=HYPERLINK(\"http://evil\") Amt & Partner GmbH",
            "is_customer": 1,
            "vat_id": "DE999888777",
            "leitweg_id": "04011000-12345-67",
            "street": "Behördenplatz 4",
            "postal_code": "10117",
            "city": "Berlin",
            "country_code": "DE",
            "billing_email": "rechnung@amt-partner.de",
        },
        company_id=cid,
    )
    doc = isolated_erp.save_document(
        {
            "doc_type": "invoice",
            "status": "booked",
            "entity_id": ent["entity"]["id"],
            "issue_date": "2026-11-15",
            "lines": [
                {
                    "title": "KI-Beratung & Audit <Q4>",
                    "quantity": 10,
                    "unit": "Std.",
                    "unit_price_net": 150.0,
                    "tax_rate_pct": 19.0,
                },
                {
                    "title": "Fachbuch Dokumentation",
                    "quantity": 2,
                    "unit": "Stk.",
                    "unit_price_net": 50.0,
                    "tax_rate_pct": 7.0,
                },
            ],
        },
        company_id=cid,
    )

    # 1. XRechnung UBL 2.1 XML endpoint
    xr_resp = erp_client.get(f"/api/erp/documents/{doc['id']}/xrechnung.xml?company_id={cid}")
    assert xr_resp.status_code == 200
    assert "xml" in xr_resp.headers["content-type"]
    root = ET.fromstring(xr_resp.text)
    ns: Dict[str, str] = {
        "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }
    assert "xrechnung_3.0" in root.findtext("cbc:CustomizationID", default="", namespaces=ns)
    assert root.findtext("cbc:BuyerReference", default="", namespaces=ns) == "04011000-12345-67"
    assert root.findtext("cbc:InvoiceTypeCode", default="", namespaces=ns) == "380"
    assert root.findtext("cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount", default="", namespaces=ns) == "1600.00"
    assert root.findtext("cac:LegalMonetaryTotal/cbc:PayableAmount", default="", namespaces=ns) == "1892.00"
    line_names = [el.text for el in root.findall("cac:InvoiceLine/cac:Item/cbc:Name", namespaces=ns)]
    assert "KI-Beratung & Audit <Q4>" in line_names

    # Missing document returns 404
    missing_resp = erp_client.get(f"/api/erp/documents/does-not-exist/xrechnung.xml?company_id={cid}")
    assert missing_resp.status_code == 404

    # 2. DATEV EXTF Buchungsstapel CSV endpoint
    dt_resp = erp_client.get(f"/api/erp/export/datev.csv?company_id={cid}")
    assert dt_resp.status_code == 200
    assert dt_resp.content.startswith(b"\xef\xbb\xbf")
    csv_lines = dt_resp.content.decode("utf-8-sig").splitlines()
    assert csv_lines[0].startswith('"EXTF";700;21;"Buchungsstapel"')
    assert ";8400;3;1511;" in "\n".join(csv_lines[2:])
    assert ";8300;2;1511;" in "\n".join(csv_lines[2:])
    assert "1785,00;S;" in "\n".join(csv_lines[2:])
    assert "107,00;S;" in "\n".join(csv_lines[2:])
    # Formula injection must remain neutralized inside quoted Buchungstext / no raw leading '= outside doc_num prefix
    assert all(not cell.startswith('"=') for line in csv_lines[2:] for cell in line.split(";"))

    # 3. ZUGFeRD 2.2 / Factur-X Hybrid PDF/A-3 endpoint (embeds factur-x.xml)
    zf_resp = erp_client.get(f"/api/erp/documents/{doc['id']}/zugferd.pdf?company_id={cid}")
    assert zf_resp.status_code == 200
    assert zf_resp.headers["content-type"] == "application/pdf"
    assert zf_resp.content.startswith(b"%PDF-1.7")
    assert b"factur-x.xml" in zf_resp.content
    assert b"fx:ConformanceLevel>EN 16931<" in zf_resp.content
    assert b"xrechnung_3.0" in zf_resp.content


def test_bank_statement_import_camt053_mt940_csv_and_opos_reconciliation(
    isolated_erp: erp_mod.ERPManager,
    erp_client: TestClient,
) -> None:
    cid = "m28-bank-test"
    ent = isolated_erp.save_entity(
        {
            "display_name": "Nordstern Digital AG",
            "is_customer": 1,
            "iban": "DE89370400440532013000",
        },
        company_id=cid,
    )
    inv_auto = isolated_erp.save_document(
        {
            "doc_type": "invoice",
            "doc_number": "RE-2026-0101",
            "status": "booked",
            "entity_id": ent["entity"]["id"],
            "lines": [{"title": "Audit", "quantity": 1, "unit_price_net": 1000.0, "tax_rate_pct": 19.0}],
        },
        company_id=cid,
    )
    inv_manual = isolated_erp.save_document(
        {
            "doc_type": "invoice",
            "doc_number": "RE-2026-0102",
            "status": "booked",
            "entity_id": ent["entity"]["id"],
            "lines": [{"title": "Retainer", "quantity": 1, "unit_price_net": 500.0, "tax_rate_pct": 19.0}],
        },
        company_id=cid,
    )

    # 1. XXE protection in CAMT.053 XML
    xxe_payload = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Document/>'
    r_xxe = erp_client.post(
        "/api/erp/bank/import",
        json={"company_id": cid, "content": xxe_payload, "format": "camt053"},
    )
    assert r_xxe.status_code == 400

    # 2. CAMT.053 XML import auto-matches RE-2026-0101 (1190.00 EUR) and marks invoice paid
    camt_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
  <BkToCstmrStmt>
    <Stmt>
      <Ntry>
        <Amt Ccy="EUR">1190.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2026-11-15</Dt></BookgDt>
        <ValDt><Dt>2026-11-15</Dt></ValDt>
        <NtryDtls>
          <TxDtls>
            <Refs><EndToEndId>E2E-101</EndToEndId></Refs>
            <RltdPties>
              <Dbtr><Nm>Nordstern Digital AG</Nm></Dbtr>
              <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
            </RltdPties>
            <RmtInf><Ustrd>Zahlung Rechnung RE-2026-0101</Ustrd></RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
    r_camt = erp_client.post(
        "/api/erp/bank/import",
        json={"company_id": cid, "content": camt_xml, "format": "auto", "auto_mark_paid": True},
    )
    assert r_camt.status_code == 200
    d_camt = r_camt.json()
    assert d_camt["imported"] == 1
    assert d_camt["matched"] == 1
    assert d_camt["auto_paid"] == 1
    assert isolated_erp.get_document(inv_auto["id"], company_id=cid)["status"] == "paid"

    # Re-importing same CAMT.053 deduplicates cleanly via SHA-256 hash
    r_dup = erp_client.post(
        "/api/erp/bank/import",
        json={"company_id": cid, "content": camt_xml, "format": "camt053"},
    )
    assert r_dup.status_code == 200
    assert r_dup.json()["imported"] == 0
    assert r_dup.json()["duplicates_skipped"] == 1

    # 3. MT940 & CSV parsing + manual OPOS match for RE-2026-0102
    mt940_text = "\n".join([
        ":20:STARTUMS",
        ":61:2611151115C595,00NTRF",
        ":86:166?31DE89370400440532013000?32Nordstern Digital AG Abschlag Projekt",
    ])
    mt_parsed = isolated_erp.parse_bank_statement(mt940_text, fmt="auto")
    assert len(mt_parsed) == 1
    assert mt_parsed[0]["source_format"] == "mt940"
    assert mt_parsed[0]["amount"] == 595.0

    csv_text = "\n".join([
        "Buchungstag;Auftraggeber;IBAN;Betrag;Währung;Verwendungszweck",
        "15.11.2026;Unbekannt GmbH;DE11111111111111111111;595,00;EUR;Abschlag November",
    ])
    r_csv = erp_client.post(
        "/api/erp/bank/import",
        json={"company_id": cid, "content": csv_text, "format": "csv", "auto_mark_paid": False},
    )
    assert r_csv.status_code == 200
    csv_tx_id = r_csv.json()["transactions"][0]["id"]

    r_match = erp_client.post(
        f"/api/erp/bank/transactions/{csv_tx_id}/match",
        json={"company_id": cid, "doc_id": inv_manual["id"], "mark_paid": True},
    )
    assert r_match.status_code == 200
    assert r_match.json()["document"]["status"] == "paid"
    assert r_match.json()["transaction"]["match_status"] == "paid_applied"
