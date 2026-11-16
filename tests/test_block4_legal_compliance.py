"""Tests für Block 4 — Recht & Compliance 2026 (GoBD Z3, ERP/E-Rechnung/PDF-A3b/DATEV, DSGVO/BEG IV/DDG/MStV, Mahnwesen/DocuSeal/Verträge)."""

from __future__ import annotations

import datetime
import io
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_gobd_z3_strict_tenant_audit_csv_escaping_and_xml_schema(tmp_path, monkeypatch):
    import backend.audit_log as audit_mod
    import backend.erp_manager as erp_mod
    from backend.gobd_z3_export import _csv_cell, build_gobd_z3_archive

    # 1. CSV Formula Escaping ohne Verfälschung regulärer Zahlen
    assert _csv_cell("-123.45") == '"-123.45"'
    assert _csv_cell("+42,50") == '"+42,50"'
    assert _csv_cell("=SUM(A1)") == '"\'=SUM(A1)"'
    assert _csv_cell("@cmd") == '"\'@cmd"'
    assert _csv_cell("+1+1") == '"\'+1+1"'
    assert _csv_cell("\t=1") == '"\'\t=1"'
    assert _csv_cell("\r=1") == '"\' =1"'

    tdir = tmp_path / "tenants"
    tdir.mkdir()
    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tdir))

    # Isoliertes Audit-Log mit 2 Mandanten
    alog = audit_mod.ChainedAuditLog(db_path=str(tmp_path / "audit.db"))
    monkeypatch.setattr(audit_mod, "chained_audit_log", alog)
    alog.record_event("FINANCE", "INVOICE_BOOKED", "agent-a", {"company_id": "tenant-a", "doc": "RE-1"})
    alog.record_event("FINANCE", "SECRET_OTHER_TENANT", "agent-b", {"company_id": "tenant-b", "doc": "RE-2"})

    ent = erp_mod.erp_manager.save_entity({"display_name": "Prüfer GmbH", "is_customer": 1}, company_id="tenant-a")
    doc = erp_mod.erp_manager.save_document(
        {
            "doc_type": "invoice",
            "status": "booked",
            "entity_id": ent["entity"]["id"],
            "issue_date": "2026-05-01",
            "lines": [{"title": "Beratung", "quantity": 1, "unit_price_net": 100.0, "tax_rate_pct": 19.0}],
        },
        company_id="tenant-a",
    )

    _, zip_bytes, _ = build_gobd_z3_archive(company_id="tenant-a")
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        audit_csv = zf.read("audit_log.csv").decode("utf-8-sig")
        assert "INVOICE_BOOKED" in audit_csv
        assert "SECRET_OTHER_TENANT" not in audit_csv

        docs_csv = zf.read("erp_documents.csv").decode("utf-8-sig")
        header_cols = docs_csv.splitlines()[0].split(";")
        assert "source_doc_id" in header_cols
        assert "recipient_snapshot_json" in header_cols
        assert doc["doc_number"] in docs_csv

        idx_root = ET.fromstring(zf.read("index.xml"))
        for table_el in idx_root.findall(".//Table"):
            url = table_el.findtext("URL")
            xml_cols = [vc.findtext("Name") for vc in table_el.findall(".//VariableColumn")]
            csv_header = zf.read(url).decode("utf-8-sig").splitlines()[0].split(";")
            assert xml_cols == csv_header


def test_erp_storno_draft_numbers_paid_timestamps_br_s9_skonto_small_biz_pdfa3_datev(tmp_path, monkeypatch):
    import pypdf
    import backend.corporate_manager as corp_mod
    import backend.erp_manager as erp_mod

    tdir = tmp_path / "tenants"
    tdir.mkdir()
    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tdir))
    mgr = erp_mod.ERPManager()
    cid = "compliance-42"

    # USt-IdNr. Validierung
    with pytest.raises(ValueError, match="USt-IdNr"):
        mgr.save_entity({"display_name": "Bad VAT", "is_customer": 1, "vat_id": "DE123"}, company_id=cid)

    ent = mgr.save_entity(
        {
            "display_name": "Skonto Kunde GmbH",
            "is_customer": 1,
            "vat_id": "de 123456789",
            "skonto_pct": 2.0,
            "skonto_days": 7,
            "street": "Testweg 1",
            "postal_code": "10115",
            "city": "Berlin",
            "country_code": "DE",
        },
        company_id=cid,
    )["entity"]
    assert ent["vat_id"] == "DE123456789"

    # Entwurf erhält ENTWURF-..., erst bei Buchung echte RE-...
    draft = mgr.save_document(
        {
            "doc_type": "invoice",
            "status": "draft",
            "entity_id": ent["id"],
            "lines": [
                {"title": "Pos 1", "quantity": 1, "unit_price_net": 10.02, "tax_rate_pct": 19.0},
                {"title": "Pos 2", "quantity": 1, "unit_price_net": 10.02, "tax_rate_pct": 19.0},
            ],
        },
        company_id=cid,
    )
    assert draft["doc_number"].startswith("ENTWURF-")
    # BR-S-9: 20.04 * 0.19 = 3.8076 -> 3.81 (nicht 1.90 + 1.90 = 3.80), BR-CO-13: 20.04 + 3.81 = 23.85
    assert draft["amount_net"] == 20.04
    assert draft["tax_amount"] == 3.81
    assert draft["amount_gross"] == 23.85

    booked = mgr.save_document({"id": draft["id"], "status": "booked"}, company_id=cid)
    assert booked["doc_number"].startswith("RE-")
    assert booked["booked_at"]

    # Direkt als 'paid' angelegte Rechnung setzt booked_at + paid_at
    direct_paid = mgr.save_document(
        {
            "doc_type": "invoice",
            "status": "paid",
            "entity_id": ent["id"],
            "lines": [{"title": "Sofortzahlung", "quantity": 1, "unit_price_net": 100.0, "tax_rate_pct": 19.0}],
        },
        company_id=cid,
    )
    assert direct_paid["booked_at"]
    assert direct_paid["paid_at"]

    # Echtes GoBD-Storno erzeugt credit_note (Typ 381) mit negativen Beträgen und source_doc_id
    storno_res = mgr.cancel_document(booked["id"], reason="Fehlbuchung", company_id=cid)
    storno = storno_res["storno_document"]
    assert storno is not None
    assert storno["doc_type"] == "credit_note"
    assert storno["source_doc_id"] == booked["id"]
    assert storno["amount_net"] == -20.04
    assert storno["tax_amount"] == -3.81
    assert storno["amount_gross"] == -23.85
    assert storno_res["cancelled_document"]["amount_gross"] == 23.85  # Ausgangsbeleg unverändert

    # XRechnung UBL CreditNote (381) & BR-DE-18 Skonto
    _, ubl_381 = mgr.export_xrechnung_xml(storno["id"], company_id=cid)
    ubl_root = ET.fromstring(ubl_381)
    assert ubl_root.tag.endswith("}CreditNote")
    assert ">381<" in ubl_381
    assert f"<cbc:ID>{booked['doc_number']}</cbc:ID>" in ubl_381
    assert "#SKONTO#TAGE=7#PROZENT=2.00#" in ubl_381

    _, cii_381 = mgr.export_zugferd_cii_xml(storno["id"], company_id=cid)
    assert "<ram:TypeCode>381</ram:TypeCode>" in cii_381
    assert "#SKONTO#TAGE=7#PROZENT=2.00#" in cii_381

    # DATEV EXTF: Feld 21 = 0 (Festschreibung), Feld 22 = "EUR", S und H für Ausgangsrechnung + Storno
    datev = mgr.export_datev_extf_csv(company_id=cid)
    lines_csv = datev.splitlines()
    extf_fields = lines_csv[0].split(";")
    assert extf_fields[20] == "0"
    assert extf_fields[21] == '"EUR"'
    assert any(f"23,85;S;" in l and booked["doc_number"] in l for l in lines_csv[2:])
    assert any(f"23,85;H;" in l and storno["doc_number"] in l for l in lines_csv[2:])

    # PDF/A-3b: /OutputIntents, Embedded TrueType Fonts, fx:GuidelineID
    _, pdf_bytes = mgr.export_zugferd_pdf(booked["id"], company_id=cid)
    assert b"/OutputIntents" in pdf_bytes
    assert b"/OutputConditionIdentifier (sRGB IEC61966-2.1)" in pdf_bytes
    assert b"/FontFile2" in pdf_bytes
    assert b"fx:GuidelineSpecifiedDocumentContextParameter" in pdf_bytes
    assert b"fx:GuidelineID" in pdf_bytes
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1

    # Kleinunternehmer (§ 19 UStG) -> CategoryCode E / VATEX-EU-AE / SKR03 8195
    monkeypatch.setattr(
        corp_mod.corporate_manager,
        "get_company",
        lambda _cid=None: {
            "id": cid,
            "name": "Klein GmbH",
            "address": {"street": "A 1", "postal_code": "10115", "city": "Berlin", "country": "DE"},
            "contact": {"email": "k@example.de", "phone": "123"},
            "tax": {"vat_id": "", "tax_number": "12/345/67890", "small_business": True},
            "bank": {"iban": "DE89370400440532013000", "bic": "COBADEFFXXX"},
        },
    )
    ku_doc = mgr.save_document(
        {
            "doc_type": "invoice",
            "status": "booked",
            "entity_id": ent["id"],
            "lines": [{"title": "Workshop", "quantity": 1, "unit_price_net": 200.0, "tax_rate_pct": 19.0}],
        },
        company_id=cid,
    )
    assert ku_doc["tax_regime"] == "small_business"
    assert ku_doc["tax_amount"] == 0.0
    _, ku_xml = mgr.export_xrechnung_xml(ku_doc["id"], company_id=cid)
    assert "<cbc:ID>E</cbc:ID>" in ku_xml
    assert "VATEX-EU-AE" in ku_xml
    assert ";8195;;" in mgr.export_datev_extf_csv(company_id=cid)


def test_gdpr_word_boundary_beg_iv_vvt_and_legal_endpoints(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.gdpr_compliance_engine as gdpr_mod
    from archon.routers import system as sys_router

    ws = tmp_path / "ws"
    tdir = ws / "data" / "tenants" / "t1"
    tdir.mkdir(parents=True)
    obs_dir = ws / "obsidian_vault" / "Kontakte"
    obs_dir.mkdir(parents=True)

    mem_db = tmp_path / "mem.db"
    kanban_db = tmp_path / "kanban.db"
    state_db = tmp_path / "state.db"

    with sqlite3.connect(str(kanban_db)) as conn:
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT, created_at TEXT, result TEXT)")
        conn.execute("INSERT INTO tasks VALUES ('t1', 'Anfrage Anna', 'Details', 'a', 'open', '2026-01-01', '')")
        conn.execute("INSERT INTO tasks VALUES ('t2', 'Anfrage Susanna aus Annaberg', 'Fremddaten', 'a', 'open', '2026-01-01', '')")
        conn.commit()
    with sqlite3.connect(str(state_db)) as conn:
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp TEXT)")
        conn.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', 'Mail von tim@a.de', '2026-01-01')")
        conn.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s2', 'user', 'Mail von victim@a.de und tim@a.de.org', '2026-01-01')")
        conn.commit()
    with sqlite3.connect(str(mem_db)) as conn:
        conn.execute("CREATE TABLE receipts (id INTEGER PRIMARY KEY, receipt_id TEXT, source TEXT, sender TEXT, merchant TEXT, receipt_date TEXT, category TEXT, details_json TEXT, created_at TEXT)")
        conn.execute("INSERT INTO receipts VALUES (1, 'rc-new', 'mail', 'Anna', 'Shop', '2026-02-01', 'Rechnung', '{}', '2026-02-01')")
        conn.execute("INSERT INTO receipts VALUES (2, 'rc-old', 'mail', 'Anna', 'Shop', '2015-02-01', 'Rechnung', '{}', '2015-02-01')")
        conn.commit()
    with sqlite3.connect(str(tdir / "crm.db")) as conn:
        conn.execute("CREATE TABLE kontakte (id TEXT PRIMARY KEY, name TEXT, email TEXT, telefon_1 TEXT, telefon_2 TEXT, unternehmen TEXT, kommentar TEXT, nachrichtenverlauf TEXT, linkedin_url TEXT, adresse TEXT, naechster_schritt TEXT)")
        conn.execute("INSERT INTO kontakte VALUES ('k1', 'Anna Schmidt', 'tim@a.de', '', '', 'Firma', '', '', '', '', '')")
        conn.commit()

    (obs_dir / "anna.md").write_text("Notiz über Anna in Berlin", encoding="utf-8")

    monkeypatch.setattr(gdpr_mod, "__file__", str(ws / "backend" / "gdpr_compliance_engine.py"))
    eng = gdpr_mod.GDPRComplianceEngine()
    eng.memory_db = str(mem_db)
    eng.kanban_db = str(kanban_db)
    eng.state_db = str(state_db)
    eng.obsidian_dir = str(ws / "obsidian_vault")
    eng._init_audit_table()

    # Exakte Wortgrenzen + Pflichttexte Art. 15
    exp_anna = eng.export_subject_data("Anna")
    assert len(exp_anna["sources"]["kanban_tasks"]) == 1
    assert exp_anna["sources"]["kanban_tasks"][0]["id"] == "t1"
    assert len(exp_anna["sources"]["tenant_records"]) == 1
    assert len(exp_anna["sources"]["receipts"]) == 2
    assert "supervisory_authority_complaint" in exp_anna["mandatory_art15_disclosures"]
    assert "automated_decision_making" in exp_anna["mandatory_art15_disclosures"]

    exp_mail = eng.export_subject_data("tim@a.de")
    assert len(exp_mail["sources"]["chat_messages"]) == 1

    # BEG IV: rc-new (2026 -> 8J bis 2034) wird gesperrt, rc-old (2015 -> bis 2023 abgelaufen) gelöscht
    erased = eng.erase_subject_data("Anna", dry_run=False, anonymize=True)
    assert erased["affected"]["legal_hold_restricted"] == 1
    assert erased["affected"]["receipts"] == 1
    assert erased["affected"]["obsidian_notes"] == 1
    with sqlite3.connect(str(kanban_db)) as conn:
        susanna = conn.execute("SELECT title FROM tasks WHERE id='t2'").fetchone()[0]
    assert susanna == "Anfrage Susanna aus Annaberg"

    # Art. 30 VVT
    vvt = eng.export_processing_register(fmt="csv")
    assert vvt["activity_count"] >= 5
    assert "vvt-finance-gobd" in vvt["csv"]

    # Legal Endpoints (§ 5 DDG, § 18 Abs. 2 MStV, Art. 13 DSGVO)
    app = FastAPI()
    app.include_router(sys_router.router)
    client = TestClient(app)
    imp = client.get("/api/legal/impressum")
    assert imp.status_code == 200
    assert "§ 5 DDG" in imp.text
    assert "§ 18 Abs. 2 MStV" in imp.text
    assert "Archon Systems" in imp.text
    dsg = client.get("/api/legal/datenschutz")
    assert dsg.status_code == 200
    assert "Art. 13 Abs. 1 lit. b DSGVO" in dsg.text
    assert "Art. 22 DSGVO" in dsg.text


def test_dunning_b2b_once_b2c_no_40_docuseal_offline_and_contract_bgb_deadlines(tmp_path, monkeypatch):
    from backend import dunning_engine as de
    from backend.contract_manager import ContractManager, ContractParser
    from backend.docuseal_client import DocuSealClient
    from backend.email_draft_engine import EmailDraftEngine

    # 1. Dunning: B2C keine 40 EUR; B2B max. 1x 40 EUR + SMTP-Hook
    mem_db = str(tmp_path / "dunning_mem.db")
    Path(mem_db).touch()
    ed = EmailDraftEngine(db_path=mem_db)
    monkeypatch.setattr("backend.email_draft_engine.email_draft_engine", ed)
    monkeypatch.setattr(de, "_resolve_db", lambda name: mem_db if name == "agentic_memory.db" else str(tmp_path / name))
    eng = de.DunningEngine()

    b2c = eng.create_invoice("Max Privat", "max@example.de", 100.0, due_days=-20, invoice_date="2026-08-01", is_b2b=False)
    b2c_draft = eng.generate_dunning_draft(b2c["invoice_id"], level=2, include_b2b_pauschale=True)
    assert b2c_draft["fee"] != 40.0
    assert "288 Abs. 5" not in b2c_draft["body_text"]

    b2b = eng.create_invoice("Firma AG", "ap@firma.de", 1000.0, due_days=-35, invoice_date="2026-08-01", is_b2b=True)
    d1 = eng.generate_dunning_draft(b2b["invoice_id"], level=1)
    with patch("backend.email_service.send_email", return_value={"status": "sent", "recipient": "ap@firma.de"}) as m_smtp:
        res1 = eng.approve_and_send_dunning(d1["dunning_id"])
        assert res1["smtp_status"] == "sent"
        assert m_smtp.called

    d2 = eng.generate_dunning_draft(b2b["invoice_id"], level=2, include_b2b_pauschale=True)
    assert d2["fee"] == 40.0
    eng.approve_and_send_dunning(d2["dunning_id"])

    d3 = eng.generate_dunning_draft(b2b["invoice_id"], level=3, include_b2b_pauschale=True)
    assert d3["fee"] == 0.0  # Nicht erneut 40 EUR!
    assert d3["total_claim"] == round(1190.0 + 40.0 + d3["interest"], 2)

    # 2. DocuSeal: Offline draft_offline, empty event_type abgelehnt, signed PDF Archivierung
    ds = DocuSealClient()
    ds.memory_db = mem_db
    ds.kanban_db = str(tmp_path / "no_kanban.db")
    ds._init_esign_tables()
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        sub = ds.create_submission("NDA", "s@example.de", "Signer", company_id="t-docu")
        assert sub["status"] == "draft_offline"

    rej = ds.handle_webhook_event({"event_type": "", "data": {"id": sub["submission_id"]}})
    assert rej["status"] == "rejected"

    mock_pdf_resp = MagicMock()
    mock_pdf_resp.status = 200
    mock_pdf_resp.read.return_value = b"%PDF-1.7\n%signed"
    mock_pdf_resp.__enter__ = lambda s: s
    mock_pdf_resp.__exit__ = lambda s, *a: False
    with patch("backend.docuseal_client.WORKSPACE_DIR", str(tmp_path)), \
         patch("urllib.request.urlopen", return_value=mock_pdf_resp):
        ok = ds.handle_webhook_event(
            {
                "event_type": "submission.completed",
                "data": {
                    "id": sub["submission_id"],
                    "documents": [{"url": "http://127.0.0.1:3080/files/signed.pdf"}],
                },
            }
        )
        assert ok["status"] == "processed"
        assert ok["signed_document_path"] and Path(ok["signed_document_path"]).exists()

    # 3. ContractManager: BGB §§ 187, 188 Fristen & renewed in KPIs
    assert ContractManager.calculate_deadline("2026-12-31", 90, "months") == "2026-09-30"
    assert ContractManager.calculate_deadline("2026-03-31", 30, "months") == "2026-02-28"
    assert ContractManager.calculate_deadline("2026-12-31", 90, "end_of_quarter") == "2026-09-30"
    parsed_q = ContractParser.parse("Kündigungsfrist 3 Monate zum Quartalsende.")
    assert parsed_q["notice_period_type"] == "end_of_quarter"

    import backend.contract_manager as cm_mod
    cm_db = tmp_path / "contracts.db"
    monkeypatch.setattr(cm_mod, "_resolve_contracts_db_path", lambda _cid=None: str(cm_db))
    cm_mod.init_contracts_db()
    ContractManager.create_or_update(
        {
            "id": "ct-ren-kpi",
            "contract_name": "Renewed Vertrag",
            "partner_name": "Partner",
            "end_date": "2026-12-31",
            "notice_period_days": 90,
            "notice_period_type": "months",
            "cost_amount": 100.0,
            "billing_cycle": "monatlich",
            "status": "renewed",
        }
    )
    stats = ContractManager.get_stats()
    assert stats["active_contracts"] >= 1
    assert stats["monthly_fixcosts"] >= 100.0
