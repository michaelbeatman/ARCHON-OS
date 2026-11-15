"""
Tests für Meilenstein 29: Visueller Formular- & Beleg-Editor (Corporate/ERP)
- Pure-Python EPC-QR / GiroCode SVG & Vektor-PDF
- Gespeicherte Vorlagen-Layouts (Ränder, Logo, Falzmarken, GiroCode, Spalten, Mahnstufen)
- Platzhalter-Substitution ({{company.*}}, {{customer.*}}, {{doc.*}}) & XSS-Schutz
- Live-§ 14-UStG-Pflichtfeldprüfung
- A4-PDF-Download-Endpunkt (/api/corporate/render-pdf)
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

import backend.corporate_manager as corp_mod
from archon.routers import _rbac as rbac_mod
from archon.routers import auth as auth_router_mod
from archon.routers import corporate as corp_router_mod
from backend.qr_girocode import build_epc_qr_payload, generate_qr_matrix, render_qr_svg


@pytest.fixture()
def isolated_corp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> corp_mod.CorporateManager:
    profiles_file = tmp_path / "corporate_profiles.json"
    mgr = corp_mod.CorporateManager(filepath=str(profiles_file))
    monkeypatch.setattr(corp_mod, "corporate_manager", mgr)
    return mgr


@pytest.fixture()
def corp_client(isolated_corp: corp_mod.CorporateManager, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(corp_router_mod.router)
    monkeypatch.setattr(rbac_mod, "is_configured", lambda: True)
    monkeypatch.setattr(
        auth_router_mod,
        "get_current_user_from_request",
        lambda _req: {"role": "admin", "username": "pytest-admin"},
    )
    monkeypatch.setattr(corp_router_mod, "require_admin_or_503", lambda _req: None)
    return TestClient(app)


def test_qr_girocode_payload_and_svg_matrix():
    payload = build_epc_qr_payload(
        recipient_name="Archon Systems GmbH",
        iban="DE89 1007 0000 0123 4567 89",
        amount_eur=1499.5,
        bic="DEUTDEDDBER",
        reference="RE-2026-042",
        remittance_text="Ignored when reference is set",
    )
    lines = payload.split("\n")
    assert lines[0] == "BCD"
    assert lines[1] == "002"
    assert lines[3] == "SCT"
    assert lines[6] == "DE89100700000123456789"
    assert lines[7] == "EUR1499.50"
    assert lines[9] == "RE-2026-042"
    assert lines[10] == ""

    mat = generate_qr_matrix(payload)
    dim = len(mat)
    assert dim >= 29  # >= Version 3 for ~85-byte EPC payload
    # Top-left finder corner (7x7 outer ring should all be 1)
    assert all(mat[0][c] == 1 for c in range(7))
    assert all(mat[6][c] == 1 for c in range(7))
    assert mat[3][3] == 1  # Finder center
    assert mat[1][1] == 0  # Finder inner ring

    svg = render_qr_svg(payload, size_px=96, title="GiroCode <Test>")
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert root.attrib["width"] == "96"


def test_layout_persistence_placeholders_ustg_and_dunning(isolated_corp: corp_mod.CorporateManager):
    saved = isolated_corp.save_template_layout(
        "archon-systems",
        "invoice",
        {
            "margin_mm": 20,
            "footer_columns": 2,
            "show_logo": True,
            "show_girocode": True,
            "show_fold_marks": True,
            "header_style": "minimal",
            "intro_text": "Hallo {{customer.name}}, Rechnung {{doc.number}} über {{doc.gross_total}} bis {{doc.due_date}}.",
            "outro_text": "Unsere USt-IdNr.: {{company.vat_id}} <script>alert(1)</script>",
        },
    )
    assert saved["margin_mm"] == 20
    assert saved["footer_columns"] == 2
    assert saved["header_style"] == "minimal"

    # Company update preserves template_layouts
    comp = isolated_corp.get_company("archon-systems")
    comp["slogan"] = "Updated Slogan"
    isolated_corp.save_company(comp)
    reloaded = isolated_corp.get_template_layout("archon-systems", "invoice")
    assert reloaded["margin_mm"] == 20
    assert "{{customer.name}}" in reloaded["intro_text"]

    res = isolated_corp.render_template(
        template_type="invoice",
        company_id="archon-systems",
        custom={
            "invoice_num": "RE-2026-777",
            "due_date": "30.11.2026",
            "recipient_name": "Kunde <Alpha> GmbH",
            "recipient_street": "Hauptstr. 5",
            "recipient_city": "10117 Berlin",
        },
    )
    html_out = res["html"]
    assert "RE-2026-777" in html_out
    assert "30.11.2026" in html_out
    assert "DE345678901" in html_out
    assert "GIROCODE EPC-QR" in html_out
    assert "top:105mm" in html_out  # DIN 5008 Falzmarke
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert res["compliance"]["valid"] is True
    assert res["compliance"]["score_pct"] == 100

    # Incomplete company fails § 14 Abs. 4 Nr. 2 UStG check
    isolated_corp.save_company({
        "id": "no-tax-gmbh",
        "name": "NoTax GmbH",
        "address": {"street": "Weg 1", "postal_code": "10115", "city": "Berlin"},
        "tax": {"vat_id": "", "tax_number": ""},
    })
    bad_res = isolated_corp.render_template("invoice", company_id="no-tax-gmbh", custom={"invoice_num": "RE-1"})
    assert bad_res["compliance"]["valid"] is False
    tax_check = next(c for c in bad_res["compliance"]["checks"] if c["id"] == "tax_identifier")
    assert tax_check["ok"] is False

    # Dunning level 2 renders overdue fee + GiroCode
    dunning_res = isolated_corp.render_template(
        template_type="dunning",
        company_id="archon-systems",
        custom={
            "invoice_num": "RE-2026-777",
            "open_amount": 500.0,
            "layout": {"dunning_level": 2, "dunning_fee": 5.0},
        },
    )
    assert "ZWEITE MAHNUNG" in dunning_res["html"]
    assert "505.00 €" in dunning_res["html"]
    assert "GIROCODE EPC-QR" in dunning_res["html"]


def test_corporate_template_api_and_pdf_download(corp_client: TestClient):
    r_save = corp_client.post(
        "/api/corporate/template-layout",
        json={
            "company_id": "archon-systems",
            "template_type": "offer",
            "layout": {"margin_mm": 18, "footer_columns": 2, "show_fold_marks": True},
        },
    )
    assert r_save.status_code == 200
    assert r_save.json()["layout"]["margin_mm"] == 18

    r_get = corp_client.get("/api/corporate/template-layout?company_id=archon-systems&template_type=offer")
    assert r_get.status_code == 200
    assert r_get.json()["layout"]["footer_columns"] == 2

    r_pdf = corp_client.post(
        "/api/corporate/render-pdf",
        json={
            "template_type": "invoice",
            "company_id": "archon-systems",
            "custom": {
                "invoice_num": "RE-PDF-2026",
                "due_date": "15.12.2026",
                "recipient_name": "PDF Testkunde GmbH",
            },
        },
    )
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"].startswith("application/pdf")
    assert r_pdf.content.startswith(b"%PDF-1.7")
    reader = PdfReader(io.BytesIO(r_pdf.content))
    assert len(reader.pages) == 1
    extracted = reader.pages[0].extract_text() or ""
    assert "RE-PDF-2026" in extracted
    assert "PDF Testkunde GmbH" in extracted
