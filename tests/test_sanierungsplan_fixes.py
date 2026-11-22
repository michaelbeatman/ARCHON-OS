"""Regressionstests für den Sanierungsplan 2026 (Sicherheit, Compliance, Core-Pipeline, Performance)."""
from __future__ import annotations

import asyncio
import datetime
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_core_settings_bearer_header_does_not_proxy_to_hermes(tmp_path, monkeypatch):
    from archon.routers import core_settings
    import main as app_main

    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"gateway_url": "http://localhost:20128/v1"}', encoding="utf-8")
    monkeypatch.setattr(core_settings, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(core_settings, "_require_admin", lambda req: {"role": "admin"})

    proxied = {"called": False}

    async def _fake_forward(_req):
        proxied["called"] = True
        return {"proxied": True}

    monkeypatch.setattr(app_main, "forward_to_hermes", _fake_forward)

    app = FastAPI()
    app.include_router(core_settings.router)
    app.dependency_overrides[core_settings._forbid_viewer_writes] = lambda: None
    client = TestClient(app)

    r_get = client.get("/api/settings", headers={"Authorization": "Bearer local-admin-token"})
    assert r_get.status_code == 200
    assert r_get.json()["gateway_url"] == "http://localhost:20128/v1"
    assert proxied["called"] is False

    r_post = client.post(
        "/api/settings",
        json={"gateway_url": "http://localhost:20128/v1", "custom_flag": True},
        headers={"Authorization": "Bearer local-admin-token"},
    )
    assert r_post.status_code == 200
    assert proxied["called"] is False


def test_execution_receipt_ledger_detects_payload_tampering(tmp_path, monkeypatch):
    from backend import execution_receipt_ledger as erl

    db_file = tmp_path / "receipts.db"
    monkeypatch.setattr(erl, "DB_PATH", str(db_file))
    erl._init_db()
    ledger = erl.ExecutionReceiptLedger()

    issued = ledger.issue_receipt(
        task_id="task-1",
        agent_role="coder",
        model_used="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.0125,
        tools_invoked=["read_file"],
    )
    assert issued["issued"] is True

    valid_res = ledger.verify_chain_integrity()
    assert valid_res["chain_valid"] is True
    assert valid_res["tampered_hashes"] == []

    # Manipuliere Kosten nachträglich ohne prev_hash zu ändern
    conn = sqlite3.connect(str(db_file))
    conn.execute("UPDATE execution_receipts_ledger SET cost_usd = 999.0 WHERE receipt_id = ?", (issued["receipt_id"],))
    conn.commit()
    conn.close()

    tampered_res = ledger.verify_chain_integrity()
    assert tampered_res["chain_valid"] is False
    assert issued["receipt_id"] in tampered_res["tampered_hashes"]


def test_erp_manager_gobd_blocks_booked_reversion_and_gates_pocketbase(tmp_path, monkeypatch):
    from backend.erp_manager import ERPManager

    mgr = ERPManager()

    # Isoliere Tenant-DB auf tmp_path
    db_file = tmp_path / "erp.db"

    def _tmp_get_conn(company_id=None):
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        return conn, "test-tenant"

    monkeypatch.setattr(mgr, "_get_conn", _tmp_get_conn)

    conn, _ = _tmp_get_conn()
    conn.executescript("""
        CREATE TABLE crm_entities (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            legal_form TEXT,
            debtor_no TEXT,
            vat_id TEXT,
            billing_email TEXT,
            street TEXT,
            postal_code TEXT,
            city TEXT,
            country TEXT
        );
        CREATE TABLE crm_contacts (
            id TEXT PRIMARY KEY,
            entity_id TEXT,
            full_name TEXT,
            email TEXT,
            is_billing_recipient INTEGER DEFAULT 0,
            is_primary INTEGER DEFAULT 0
        );
        CREATE TABLE erp_documents (
            id TEXT PRIMARY KEY,
            doc_type TEXT,
            entity_id TEXT,
            contact_id TEXT,
            status TEXT,
            recipient_snapshot_json TEXT,
            paid_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE erp_document_lines (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            pos_no INTEGER
        );
        CREATE TABLE erp_sync_config (
            id INTEGER PRIMARY KEY,
            pocketbase_url TEXT,
            collection_name TEXT,
            sync_enabled INTEGER
        );
        INSERT INTO crm_entities (id, display_name) VALUES ('ent-1', 'Test GmbH');
        INSERT INTO erp_documents (id, doc_type, entity_id, status) VALUES ('doc-1', 'invoice', 'ent-1', 'booked');
        INSERT INTO erp_documents (id, doc_type, entity_id, status) VALUES ('doc-2', 'invoice', 'ent-1', 'paid');
        INSERT INTO erp_sync_config VALUES (1, 'http://127.0.0.1:8090', 'kontakte', 1);
    """)
    conn.close()

    with pytest.raises(ValueError, match="GoBD"):
        mgr.save_document({"id": "doc-1", "status": "draft"}, company_id="test-tenant")

    with pytest.raises(ValueError, match="GoBD"):
        mgr.save_document({"id": "doc-2", "status": "booked"}, company_id="test-tenant")

    monkeypatch.setenv("POCKETBASE_ENABLED", "false")
    disabled_res = mgr.sync_with_pocketbase(company_id="test-tenant")
    assert disabled_res["status"] == "disabled"


def test_dunning_engine_level1_fee_zero_and_level2_statutory_interest(tmp_path):
    from backend.dunning_engine import DunningEngine

    db_file = tmp_path / "dunning.db"
    db_file.touch()
    due_date = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
    inv_date = (datetime.date.today() - datetime.timedelta(days=34)).isoformat()

    engine = DunningEngine()
    engine.memory_db = str(db_file)
    engine.kanban_db = str(tmp_path / "no_kanban.db")
    engine._init_tables()

    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        INSERT INTO invoices (invoice_id, customer_name, customer_email, invoice_date, due_date, amount_net, tax_amount, amount_gross, status)
        VALUES ('RE-2026-001', 'Acme GmbH', 'ap@acme.example', ?, ?, 1000.0, 190.0, 1190.0, 'open')
    """, (inv_date, due_date))
    conn.commit()
    conn.close()

    lvl1 = engine.generate_dunning_draft("RE-2026-001", level=1)
    assert lvl1["fee"] == 0.0
    assert lvl1["interest"] == 0.0

    from backend.dunning_engine import calculate_statutory_interest

    lvl2 = engine.generate_dunning_draft("RE-2026-001", level=2)
    expected_interest = calculate_statutory_interest(
        1190.0,
        datetime.date.fromisoformat(due_date),
        datetime.date.today(),
        is_b2b=True,
    )
    assert lvl2["fee"] == 5.0
    assert lvl2["interest"] == expected_interest


def test_crm_service_gdpr_defaults_opt_in_false(tmp_path, monkeypatch):
    from backend import crm_service

    db_file = tmp_path / "crm.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE kontakte (
            id TEXT PRIMARY KEY,
            name TEXT,
            unternehmen TEXT,
            rolle TEXT,
            email TEXT,
            telefon_1 TEXT,
            telefon_2 TEXT,
            linkedin_url TEXT,
            status TEXT,
            rating INTEGER,
            region TEXT,
            Webseite TEXT,
            adresse TEXT,
            naechster_schritt TEXT,
            vernetzt_am TEXT,
            naechster_termin TEXT,
            einladung_zurueckgezogen_am TEXT,
            kommentar TEXT,
            RollenVerteilungzuordnung TEXT,
            LinkedInheader TEXT,
            Linkedin_info TEXT,
            profilbild TEXT,
            tags TEXT,
            nachrichtenverlauf TEXT,
            created TEXT,
            updated TEXT,
            dsgvo_opt_email INTEGER DEFAULT 0,
            dsgvo_opt_phone INTEGER DEFAULT 0,
            dsgvo_opt_postal INTEGER DEFAULT 0,
            dsgvo_opt_out INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

    def _tmp_conn(_cid=None):
        c = sqlite3.connect(str(db_file))
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(crm_service, "_get_pb_conn", _tmp_conn)
    svc = crm_service.CRMService()
    created = svc.save_contact(None, {"name": "Max Mustermann", "email": "max@example.com"})
    exported = svc.export_gdpr(created["id"])
    assert exported is not None
    assert exported["gdpr_status"]["consents"]["email_marketing"] is False
    assert exported["gdpr_status"]["consents"]["phone_marketing"] is False


def test_llm_egress_guard_sanitizes_cloud_payload_and_enforces_firewall(tmp_path, monkeypatch):
    from backend import llm_egress_guard as leg

    # 1. Payload-Sanitizer maskiert Cloud-Payloads ohne Input zu mutieren
    dummy_key = "sk-" + "1234567890abcdefghijklmnop"
    orig_payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": f"Mein Key ist {dummy_key} und Mail max@example.com"}],
    }
    sanitized_cloud = leg.sanitize_outbound_llm_payload(orig_payload, agent_id="researcher", is_local=False)
    assert sanitized_cloud is not None
    assert dummy_key not in sanitized_cloud["messages"][0]["content"]
    assert dummy_key in orig_payload["messages"][0]["content"]

    local_payload = leg.sanitize_outbound_llm_payload(orig_payload, agent_id="researcher", is_local=True)
    assert local_payload["messages"][0]["content"] == orig_payload["messages"][0]["content"]

    # 2. Firewall lässt interne/freigegebene Hosts durch und blockiert unbekannte externe Domains
    monkeypatch.setattr(leg.chained_audit_log, "record_llm_dispatch", lambda **kw: {"ok": True, **kw})
    assert leg.enforce_egress_firewall_for_url("http://omniroute:20128/v1/chat/completions")["allowed"] is True
    assert leg.enforce_egress_firewall_for_url("http://127.0.0.1:11434/v1/chat/completions")["allowed"] is True

    with patch("backend.egress_firewall.egress_firewall.check_url", return_value={"allowed": False, "blocked": True, "reason": "Domain nicht freigegeben"}):
        with pytest.raises(leg.ZeroEgressBlockedError):
            leg.enforce_egress_firewall_for_url("https://evil-exfil.example.com/v1/chat", agent_id="researcher")


def test_email_draft_engine_status_counts_and_legal_routes(tmp_path, monkeypatch):
    from backend import email_draft_engine as ede
    from archon.routers import system as sys_router
    from archon.routers import voice as voice_router

    db_file = tmp_path / "drafts.db"
    engine = ede.EmailDraftEngine(db_path=str(db_file))
    counts = engine.get_status_counts()
    assert set(("pending", "approved", "sent", "snoozed", "rejected", "total")).issubset(counts.keys())
    assert counts["total"] == sum(counts[k] for k in ("pending", "approved", "sent", "snoozed", "rejected"))

    app = FastAPI()
    app.include_router(sys_router.router)
    app.include_router(voice_router.router)
    app.dependency_overrides[voice_router._forbid_viewer_writes] = lambda: None
    client = TestClient(app)

    r_imp = client.get("/api/legal/impressum")
    assert r_imp.status_code == 200
    assert "Impressum" in r_imp.text

    r_dsg = client.get("/api/legal/datenschutz")
    assert r_dsg.status_code == 200
    assert "DSGVO" in r_dsg.text

    monkeypatch.setattr(voice_router, "require_admin_or_503", lambda req: {"role": "admin"})
    with patch("backend.voice_pipeline.transcribe_audio_bytes", return_value="Hallo Archon Test"):
        r_tr = client.post(
            "/api/voice/transcribe",
            files={"file": ("test.webm", b"RIFF0000", "audio/webm")},
            data={"language": "de"},
        )
    assert r_tr.status_code == 200
    assert r_tr.json()["text"] == "Hallo Archon Test"


def test_showroom_file_actions_enforce_path_jail(tmp_path, monkeypatch):
    """Sprint-2: Trash/Restore/Purge erzwingen safe_path_within auf Projects bzw. Papierkorb."""
    from fastapi import HTTPException
    import views_core

    vault = tmp_path / "vault"
    projects = vault / "Projects"
    trash = projects / "Papierkorb"
    outside = tmp_path / "secret.txt"
    outside.write_text("do not touch", encoding="utf-8")
    target = projects / "demo.md"
    projects.mkdir(parents=True, exist_ok=True)
    target.write_text("# Demo", encoding="utf-8")

    monkeypatch.setattr(views_core, "resolve_obsidian_vault_dir", lambda: str(vault))
    monkeypatch.setattr(views_core, "require_admin_or_503", lambda _req: {"role": "admin"})

    with pytest.raises(HTTPException) as ei_del:
        asyncio.run(views_core.delete_showroom_file(None, views_core.FileActionPayload(filepath=str(outside))))
    assert ei_del.value.status_code == 403

    with pytest.raises(HTTPException) as ei_res:
        asyncio.run(views_core.restore_showroom_file(None, views_core.FileActionPayload(filepath=str(target))))
    assert ei_res.value.status_code == 403

    with pytest.raises(HTTPException) as ei_purge:
        asyncio.run(views_core.purge_showroom_file(None, views_core.FileActionPayload(filepath=str(target))))
    assert ei_purge.value.status_code == 403

    res_del = asyncio.run(views_core.delete_showroom_file(None, views_core.FileActionPayload(filepath=str(target))))
    assert res_del["status"] == "success"
    trashed = trash / "demo.md"
    assert trashed.exists() and not target.exists()

    res_res = asyncio.run(views_core.restore_showroom_file(None, views_core.FileActionPayload(filepath=str(trashed))))
    assert res_res["status"] == "success"
    restored = Path(res_res["target_path"])
    assert restored.exists()

    asyncio.run(views_core.delete_showroom_file(None, views_core.FileActionPayload(filepath=str(restored))))
    res_purge = asyncio.run(views_core.purge_showroom_file(None, views_core.FileActionPayload(filepath=str(trashed))))
    assert res_purge["status"] == "success"
    assert not trashed.exists()


def test_run_showroom_code_sandbox_and_path_jail(tmp_path, monkeypatch):
    """Sprint-2: run_showroom_code blockiert Traversal und isoliert Host-Secrets im Python -I Sandbox-Run."""
    from fastapi import HTTPException
    import views_core

    monkeypatch.setattr(views_core, "require_admin_or_503", lambda _req: {"role": "admin"})
    monkeypatch.setattr(views_core, "resolve_obsidian_vault_dir", lambda: str(tmp_path / "vault"))
    monkeypatch.setattr(views_core, "WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("ARCHON_TEST_SECRET_TOKEN", "TOP_SECRET_VALUE_999")

    with pytest.raises(HTTPException) as ei:
        asyncio.run(views_core.run_showroom_code(
            None,
            views_core.CodeRunPayload(filepath="/etc/passwd", code=""),
        ))
    assert ei.value.status_code == 403

    # Ohne Docker ist die Sandbox korrekt fail-closed (S6-Hardening): es
    # wird KEIN Code auf dem Host ausgefuehrt. Der Test prune, dass die
    # Antwort weder Code noch Secret durchscheuern laesst.
    from fastapi import HTTPException
    try:
        res = asyncio.run(views_core.run_showroom_code(
            None,
            views_core.CodeRunPayload(
                code="import os\nprint(os.environ.get('ARCHON_TEST_SECRET_TOKEN', 'CLEAN'))",
                language="python",
            ),
        ))
    except HTTPException as exc:
        assert exc.status_code == 501
        return
    assert res["status"] in ("error", "timeout")
    assert "TOP_SECRET_VALUE_999" not in res.get("stdout", "")


def test_gdpr_paginated_export_and_case_insensitive_erase(tmp_path):
    """Sprint-2: Art. 15 paginierter Voll-Export > 100 Treffer & Art. 17 Case-Insensitive Redaction."""
    from backend.gdpr_compliance_engine import GDPRComplianceEngine

    state_db = tmp_path / "state.db"
    kanban_db = tmp_path / "kanban.db"
    conn_s = sqlite3.connect(str(state_db))
    conn_s.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp TEXT)")
    for i in range(250):
        name_variant = "MAX MUSTERMANN" if i % 2 == 0 else "max mustermann"
        conn_s.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (f"s-{i}", "user", f"Nachricht {i} von {name_variant}", "2026-11-15T10:00:00"),
        )
    conn_s.commit()
    conn_s.close()

    conn_k = sqlite3.connect(str(kanban_db))
    conn_k.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT, created_at TEXT, result TEXT)")
    conn_k.execute(
        "INSERT INTO tasks (id, title, body, assignee, status, created_at, result) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("t-1", "Anfrage max mustermann", "Kontakt MAX MUSTERMANN pruefen", "agent", "done", "2026-11-15", "Erledigt fuer Max Mustermann"),
    )
    conn_k.commit()
    conn_k.close()

    memory_db = tmp_path / "memory.db"
    sqlite3.connect(str(memory_db)).close()

    engine = GDPRComplianceEngine()
    engine.state_db = str(state_db)
    engine.kanban_db = str(kanban_db)
    engine.memory_db = str(memory_db)
    engine.obsidian_dir = str(tmp_path / "no_obs")
    engine._init_audit_table()

    exp = engine.export_subject_data("Max Mustermann")
    assert len(exp["sources"]["chat_messages"]) == 250
    assert exp["sources"]["chat_messages_truncated"] is False
    assert exp["is_truncated"] is False
    assert exp["sources"]["chat_messages_total_count"] == 250

    erased = engine.erase_subject_data("Max Mustermann", dry_run=False, anonymize=True)
    assert erased["affected"]["chat_messages"] == 250
    assert erased["affected"]["kanban_tasks"] == 1

    conn_k_chk = sqlite3.connect(str(kanban_db))
    row = conn_k_chk.execute("SELECT title, body, result FROM tasks WHERE id = 't-1'").fetchone()
    conn_k_chk.close()
    assert all("mustermann" not in (col or "").lower() for col in row)
    assert all("[ANONYMISIERT_DSGVO_ART17]" in (col or "") for col in row)


def test_precompiled_tailwind_css_replaces_runtime_cdn():
    """M57: Statisches Tailwind-CSS ersetzt das Laufzeit-JIT-CDN in index.html & hermes-hud."""
    root = Path(__file__).resolve().parent.parent
    index_html = (root / "static" / "index.html").read_text(encoding="utf-8")
    hud_html = (root / "static" / "hermes-hud" / "index.html").read_text(encoding="utf-8")
    css_path = root / "static" / "css" / "tailwind.generated.css"

    assert css_path.exists(), "tailwind.generated.css fehlt"
    css = css_path.read_text(encoding="utf-8")
    assert len(css) > 50_000
    assert ".hidden" in css and ".flex" in css
    assert ".font-sans" in css and ".font-mono" in css
    assert r".dark\:" in css

    assert "tailwind.cdn.js" not in index_html
    assert "tailwind.config =" not in index_html
    tw_pos = index_html.find("/static/css/tailwind.generated.css")
    custom_pos = index_html.find("/static/custom.css")
    assert 0 <= tw_pos < custom_pos

    assert "cdn.tailwindcss.com" not in hud_html
    assert "unpkg.com/lucide" not in hud_html
    assert "fonts.googleapis.com" not in hud_html
    assert "/static/css/tailwind.generated.css" in hud_html
    assert "/static/vendor/lucide.min.js" in hud_html


def test_modals_have_wcag_dialog_roles_and_a11y_script():
    """M57: Alle aktiven Modals/Drawer tragen role='dialog' aria-modal='true' & modal_a11y.js wird geladen."""
    import re

    root = Path(__file__).resolve().parent.parent
    index_html = (root / "static" / "index.html").read_text(encoding="utf-8")
    a11y_js = root / "static" / "js" / "modal_a11y.js"

    assert a11y_js.exists()
    assert "/static/js/modal_a11y.js" in index_html

    files = [root / "static" / "index.html"] + sorted((root / "static" / "views").glob("*.html"))
    dialog_count = 0
    for f in files:
        content = f.read_text(encoding="utf-8")
        dialog_count += len(re.findall(r'role="dialog"[^>]*aria-modal="true"|aria-modal="true"[^>]*role="dialog"', content))

    assert dialog_count >= 39, f"Erwartet >= 39 WCAG-Dialoge, gefunden: {dialog_count}"


def test_erp_studio_i18n_keys_present_in_all_locales():
    """M57: Alle erpT()-Schlüssel aus erp_studio.js sind vollständig in allen 11 Locale-Katalogen."""
    import json
    import re

    root = Path(__file__).resolve().parent.parent
    erp_js = (root / "static" / "erp_studio.js").read_text(encoding="utf-8")
    js_keys = set(re.findall(r'erpT\(\s*"ui\.erp_studio\.([a-z0-9_]+)"', erp_js))
    assert len(js_keys) >= 120

    locales_dir = root / "static" / "locales"
    de_section = json.loads((locales_dir / "de.json").read_text(encoding="utf-8"))["ui"]["erp_studio"]
    ph_re = re.compile(r"\{[a-z0-9_]+\}")

    for lang in ("de", "en", "es", "fr", "it", "ja", "ko", "nl", "pt", "ru", "zh"):
        data = json.loads((locales_dir / f"{lang}.json").read_text(encoding="utf-8"))
        section = data.get("ui", {}).get("erp_studio", {})
        missing = js_keys - set(section.keys())
        assert not missing, f"{lang}.json fehlen ui.erp_studio-Keys: {sorted(missing)}"
        for key in js_keys:
            val = section[key]
            assert isinstance(val, str) and val.strip(), f"Leerer Wert in {lang}.ui.erp_studio.{key}"
            assert set(ph_re.findall(val)) == set(ph_re.findall(de_section[key])), (
                f"Platzhalter-Abweichung in {lang}.ui.erp_studio.{key}"
            )
