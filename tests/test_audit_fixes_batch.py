"""Regressionstests für Audit-Batch (Block 1: Security/RBAC/SSRF/Telemetry, Block 2: GoBD/ZUGFeRD/BGB/Backup/DSGVO)."""

import datetime
import gzip
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


OPERATOR_USER = {"id": "usr_op_audit", "username": "lisa", "role": "operator", "permissions": {}}
ADMIN_USER = {"id": "usr_ad_audit", "username": "admin", "role": "admin", "permissions": {}}


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/studio/upload-bg"),
        ("POST", "/api/themes/dark"),
        ("DELETE", "/api/themes/dark"),
        ("POST", "/api/design/themes"),
        ("DELETE", "/api/design/themes/custom-1"),
        ("POST", "/api/theme"),
        ("POST", "/api/theme/live-overrides"),
        ("POST", "/api/theme/bake-into-main-design"),
        ("DELETE", "/api/theme/live-overrides"),
        ("POST", "/api/decisions/decide"),
        ("POST", "/api/telegram/relay"),
        ("POST", "/api/guardian/cache/clear"),
        ("DELETE", "/api/deals/deal-test-1"),
        ("DELETE", "/api/v1/deals/deal-test-1"),
    ],
)
def test_operator_blocked_with_403_on_hardened_admin_routes(monkeypatch, method, path):
    import main as app_main

    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(app_main.auth_service, "verify_session", lambda _tok: dict(OPERATOR_USER))

    client = TestClient(app_main.app)
    resp = client.request(method, path, headers={"Authorization": "Bearer op-token"})
    assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}: {resp.text}"


def test_theme_path_traversal_rejected_with_400(monkeypatch):
    import main as app_main
    from archon.routers.theme import _safe_theme_path

    with pytest.raises(HTTPException) as exc:
        _safe_theme_path("../../etc/passwd")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc2:
        _safe_theme_path("bad.name")
    assert exc2.value.status_code == 400

    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(app_main.auth_service, "verify_session", lambda _tok: dict(ADMIN_USER))
    client = TestClient(app_main.app)
    resp = client.delete("/api/themes/bad.name", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 400


def test_hud_telemetry_runs_without_profiles_base_attribute_error(monkeypatch):
    import main as app_main

    assert not hasattr(app_main, "HERMES_PROFILES_BASE")
    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: False)
    client = TestClient(app_main.app)
    resp = client.get("/api/v1/hud/telemetry")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "timestamp" in payload and "consciousness" in payload


def test_research_engine_ssrf_guard_and_jina_disable(monkeypatch):
    import research_engine_v2 as re2

    blocked_urls = [
        "http://127.0.0.1/admin",
        "http://0177.0.0.1/admin",
        "http://2130706433/admin",
        "http://0x7f.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://omniroute/v1/models",
        "http://internal-db.internal/health",
        "http://nas.local/share",
        "ftp://8.8.8.8/file",
        "http://user:pass@8.8.8.8/",
    ]
    for url in blocked_urls:
        assert re2._is_safe_url(url) is False, f"SSRF guard unexpectedly allowed {url}"

    assert re2._is_safe_url("https://8.8.8.8/dns-query") is True

    monkeypatch.setenv("ARCHON_DISABLE_JINA_SCRAPE", "1")
    assert re2.scrape_jina("https://8.8.8.8/") == ""


def test_api_key_manager_pepper_hmac_and_legacy_fallback(tmp_path, monkeypatch):
    from backend.api_key_manager import ApiKeyManager

    db_file = str(tmp_path / "api_keys.db")
    monkeypatch.delenv("ARCHON_API_KEY_PEPPER", raising=False)
    mgr = ApiKeyManager(db_path=db_file)

    legacy_created = mgr.create_key("legacy-test", ["read_only"], created_by="admin")
    legacy_raw = legacy_created["raw_token"]
    ok_leg, _, _ = mgr.validate_and_consume(legacy_raw, required_scope="read_only")
    assert ok_leg is True

    monkeypatch.setenv("ARCHON_API_KEY_PEPPER", "super-secret-pepper-2026")
    peppered_created = mgr.create_key("peppered-test", ["read_only"], created_by="admin")
    peppered_raw = peppered_created["raw_token"]

    with sqlite3.connect(db_file) as conn:
        stored_hash = conn.execute(
            "SELECT key_hash FROM api_keys WHERE key_id = ?",
            (peppered_created["key_id"],),
        ).fetchone()[0]
    assert stored_hash != ApiKeyManager._legacy_hash_token(peppered_raw)

    ok_pep, _, _ = mgr.validate_and_consume(peppered_raw, required_scope="read_only")
    ok_leg2, _, _ = mgr.validate_and_consume(legacy_raw, required_scope="read_only")
    assert ok_pep is True
    assert ok_leg2 is True


def test_local_memory_bridge_evict_rejects_unknown_table(tmp_path):
    from local_memory_bridge import LocalMemoryBridge

    bridge = LocalMemoryBridge(db_path=str(tmp_path / "mem.db"))
    res = bridge.evict_stale_memories(threshold=0.1, table="sqlite_master")
    assert res["status"] == "error"
    assert "Invalid table" in res["message"]


def test_erp_gobd_immutability_and_cancelled_reactivation_guard(tmp_path, monkeypatch):
    import backend.erp_manager as erp_mod

    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tmp_path / "tenants"))
    erp = erp_mod.ERPManager()
    cid = "gobd-guard-test"

    ent = erp.save_entity({"display_name": "Kunde GmbH", "is_customer": 1}, company_id=cid)
    draft = erp.save_document(
        {
            "doc_type": "invoice",
            "status": "draft",
            "entity_id": ent["entity"]["id"],
            "lines": [{"title": "Beratung", "quantity": 1, "unit_price_net": 500.0, "tax_rate_pct": 19.0}],
        },
        company_id=cid,
    )
    booked = erp.save_document({"id": draft["id"], "status": "booked"}, company_id=cid)
    assert booked["booked_at"]

    # Zurückstufen auf draft oder Überschreiben von Positionen muss GoBD-blockiert werden
    with pytest.raises(ValueError):
        erp.save_document({"id": booked["id"], "status": "draft"}, company_id=cid)

    tamper_res = erp.save_document(
        {
            "id": booked["id"],
            "status": "booked",
            "lines": [{"title": "Manipulation", "quantity": 1, "unit_price_net": 1.0, "tax_rate_pct": 19.0}],
        },
        company_id=cid,
    )
    assert tamper_res["amount_gross"] == 595.0
    assert tamper_res["lines"][0]["title"] == "Beratung"

    cancelled = erp.save_document({"id": booked["id"], "status": "cancelled"}, company_id=cid)
    assert cancelled["status"] == "cancelled"

    with pytest.raises(ValueError):
        erp.save_document({"id": cancelled["id"], "status": "booked"}, company_id=cid)


def test_zugferd_cii_xml_and_multipage_pdf_rendering(tmp_path, monkeypatch):
    import backend.erp_manager as erp_mod

    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tmp_path / "tenants"))
    erp = erp_mod.ERPManager()
    cid = "cii-multipage-test"

    ent = erp.save_entity(
        {
            "display_name": "Multipage Kunde AG",
            "is_customer": 1,
            "vat_id": "DE123456789",
            "street": "Teststraße 12",
            "postal_code": "80331",
            "city": "München",
            "country_code": "DE",
            "billing_email": "ap@multipage.example",
        },
        company_id=cid,
    )
    lines = [
        {
            "title": f"Leistungspaket Nummer {idx}",
            "quantity": 1,
            "unit": "Stk.",
            "unit_price_net": 100.0,
            "tax_rate_pct": 19.0,
        }
        for idx in range(1, 46)
    ]
    doc = erp.save_document(
        {
            "doc_type": "invoice",
            "status": "booked",
            "entity_id": ent["entity"]["id"],
            "issue_date": "2026-11-15",
            "lines": lines,
        },
        company_id=cid,
    )

    xml_doc_no, xml_str = erp.export_zugferd_cii_xml(doc["id"], company_id=cid)
    assert xml_doc_no.startswith("RE-")
    root = ET.fromstring(xml_str)
    assert root.tag.endswith("CrossIndustryInvoice")
    assert "urn:cen.eu:en16931:2017" in xml_str

    pdf_doc_no, pdf_bytes = erp.export_zugferd_pdf(doc["id"], company_id=cid)
    assert pdf_doc_no == xml_doc_no
    assert pdf_bytes.startswith(b"%PDF-1.7")
    assert b"<rsm:CrossIndustryInvoice" in pdf_bytes
    assert b"Leistungspaket Nummer 45" in pdf_bytes
    count_match = re.search(rb"/Type\s*/Pages\b[^>]*/Count\s+(\d+)", pdf_bytes)
    assert count_match is not None and int(count_match.group(1)) >= 2


def test_dunning_statutory_interest_split_periods():
    from backend.dunning_engine import calculate_statutory_interest

    # H1 2026 Basiszinssatz = 1.27 % -> B2B (+9 pp) = 10.27 %, B2C (+5 pp) = 6.27 %
    assert calculate_statutory_interest(
        1000.0, datetime.date(2026, 1, 1), datetime.date(2026, 1, 11), is_b2b=True
    ) == round(1000.0 * 0.1027 * (10 / 365.0), 2)
    assert calculate_statutory_interest(
        1000.0, datetime.date(2026, 1, 1), datetime.date(2026, 1, 11), is_b2b=False
    ) == round(1000.0 * 0.0627 * (10 / 365.0), 2)

    # Halbjahreswechsel 2025-07-01: 10 Tage bei 11.27 % (2.27+9) + 10 Tage bei 10.27 % (1.27+9)
    split_val = calculate_statutory_interest(
        1000.0, datetime.date(2025, 6, 21), datetime.date(2025, 7, 11), is_b2b=True
    )
    expected_split = round(1000.0 * (0.1127 * (10 / 365.0) + 0.1027 * (10 / 365.0)), 2)
    assert split_val == expected_split


def test_db_backup_and_gdpr_erasure_include_tenant_dbs(tmp_path, monkeypatch):
    import backend.db_backup_manager as backup_mod
    import backend.gdpr_compliance_engine as gdpr_mod

    tmp_ws = tmp_path / "ws"
    tenant_dir = tmp_ws / "data" / "tenants" / "t-gdpr"
    tenant_dir.mkdir(parents=True)
    tenant_db = tenant_dir / "erp.db"

    with sqlite3.connect(str(tenant_db)) as conn:
        conn.execute(
            "CREATE TABLE crm_entities (id TEXT PRIMARY KEY, display_name TEXT, billing_email TEXT, phone_main TEXT, street TEXT, iban TEXT, notes TEXT)"
        )
        conn.execute(
            "CREATE TABLE crm_contacts (id TEXT PRIMARY KEY, entity_id TEXT, first_name TEXT, last_name TEXT, full_name TEXT, email TEXT, phone TEXT, mobile TEXT, linkedin_url TEXT, notes TEXT)"
        )
        conn.execute(
            "INSERT INTO crm_entities VALUES ('e1', 'Erika Mustermann', 'erika@example.org', '0170-1234', 'Musterweg 1', 'DE89370400440532013000', 'VIP')"
        )
        conn.execute(
            "INSERT INTO crm_contacts VALUES ('c1', 'e1', 'Erika', 'Mustermann', 'Erika Mustermann', 'erika@example.org', '0170-1234', '0170-1234', 'https://linkedin.com/in/erika', 'Notiz')"
        )
        conn.commit()

    monkeypatch.setattr(backup_mod, "WORKSPACE_DIR", str(tmp_ws))
    backup_dir = tmp_path / "backups"
    bm = backup_mod.DBBackupManager(backup_dir=str(backup_dir))
    res_bk = bm.checkpoint_and_backup()
    assert res_bk["status"] == "success"
    gz_files = list(backup_dir.glob("tenant_t-gdpr__erp.db_*.db.gz"))
    assert len(gz_files) == 1
    with gzip.open(gz_files[0], "rb") as gz:
        assert gz.read(16).startswith(b"SQLite format 3")

    monkeypatch.setattr(gdpr_mod, "__file__", str(tmp_ws / "backend" / "gdpr_compliance_engine.py"))
    tmp_mem_db = tmp_path / "gdpr_mem.db"
    tmp_mem_db.touch()
    engine = gdpr_mod.GDPRComplianceEngine()
    engine.memory_db = str(tmp_mem_db)
    engine._init_audit_table()
    engine.kanban_db = str(tmp_path / "nonexistent_kanban.db")
    engine.state_db = str(tmp_path / "nonexistent_state.db")
    engine.obsidian_dir = str(tmp_path / "nonexistent_obsidian")

    res_erase = engine.erase_subject_data("erika@example.org", dry_run=False, anonymize=True)
    assert res_erase["affected"].get("tenant_records", 0) >= 2

    with sqlite3.connect(str(tenant_db)) as conn:
        ent_row = conn.execute("SELECT display_name, billing_email FROM crm_entities WHERE id='e1'").fetchone()
        cnt_row = conn.execute("SELECT full_name, email FROM crm_contacts WHERE id='c1'").fetchone()
    assert "erika@example.org" not in str(ent_row)
    assert "erika@example.org" not in str(cnt_row)


def test_containers_read_file_tail_limits_bytes_and_lines(tmp_path):
    from archon.routers.containers import _read_file_tail

    big_log = tmp_path / "huge.log"
    with open(big_log, "w", encoding="utf-8") as fh:
        for i in range(6000):
            fh.write(f"2026-11-15 INFO Zeile Nummer {i:05d} mit etwas Fuelltext fuer Groesse\n")

    tail = _read_file_tail(str(big_log), max_lines=5, max_bytes=4096)
    assert len(tail) == 5
    assert "05995" in tail[0]
    assert "05999" in tail[-1]


def test_tool_permission_manager_blocks_arbitrary_binaries(tmp_path):
    from backend.tool_permission_manager import ToolPermissionManager

    db_file = str(tmp_path / "perm.db")
    mgr = ToolPermissionManager(db_path=db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO tool_permissions (id, tool_name, tool_type, reason, command_to_run, status) VALUES ('p1', 'evil', 'bash', 'test', 'bash -c \"touch /tmp/pwned\"', 'pending_permission')"
        )
        conn.execute(
            "INSERT INTO tool_permissions (id, tool_name, tool_type, reason, command_to_run, status) VALUES ('p2', 'evilpy', 'pip', 'test', 'python3 -c \"print(1)\"', 'pending_permission')"
        )
        conn.commit()

    res1 = mgr.resolve_proposal("p1", "grant")
    res2 = mgr.resolve_proposal("p2", "grant")
    assert res1["status"] == "failed"
    assert "Sicherheits-Block" in res1["log"]
    assert res2["status"] == "failed"
    assert "Sicherheits-Block" in res2["log"]


def test_epc_girocode_currency_enforcement():
    from backend.qr_girocode import build_epc_qr_payload

    payload = build_epc_qr_payload(
        recipient_name="Archon GmbH",
        iban="DE89370400440532013000",
        amount_eur=199.50,
        bic="COBADEFFXXX",
        reference="RE-2026-99",
    )
    assert "EUR199.50" in payload
    assert "COBADEFFXXX" in payload

    with pytest.raises(ValueError, match="EUR"):
        build_epc_qr_payload(
            recipient_name="Archon GmbH",
            iban="DE89370400440532013000",
            amount_eur=199.50,
            currency="USD",
        )


def test_research_http_get_blocks_unsafe_redirect(monkeypatch):
    import research_engine_v2 as re2

    class _FakeResp:
        status_code = 302
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _FakeClient:
        def stream(self, *_args, **_kwargs):
            return _FakeResp()

    monkeypatch.setattr(re2, "_get_http_client", lambda: _FakeClient())
    with pytest.raises(ValueError, match="SSRF-Schutz"):
        re2._http_get("https://8.8.8.8/start")


def test_proxy_web_ui_blocks_operator(monkeypatch):
    import main as app_main

    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(app_main.auth_service, "verify_session", lambda _tok: dict(OPERATOR_USER))
    client = TestClient(app_main.app)
    resp = client.get(
        "/api/proxy?url=http://localhost:8501/",
        headers={"Authorization": "Bearer op-token"},
    )
    assert resp.status_code == 403


def test_hermes_webui_has_no_external_cdn_and_vendors_exist():
    webui_dir = os.path.join(ROOT, "static", "hermes-webui")
    for rel in ("index.html", "boot.js", "ui.js", "sw.js", "terminal.js"):
        txt = open(os.path.join(webui_dir, rel), "r", encoding="utf-8").read()
        assert "cdn.jsdelivr.net" not in txt, f"Externes CDN noch in {rel}"

    expected_vendor_files = [
        "vendor/xterm/5.3.0/xterm.css",
        "vendor/xterm/5.3.0/xterm.js",
        "vendor/xterm-addon-fit/0.8.0/xterm-addon-fit.js",
        "vendor/xterm-addon-web-links/0.9.0/xterm-addon-web-links.js",
        "vendor/prismjs/1.29.0/themes/prism-tomorrow.min.css",
        "vendor/prismjs/1.29.0/themes/prism.min.css",
        "vendor/prismjs/1.29.0/components/prism-core.min.js",
        "vendor/prismjs/1.29.0/plugins/autoloader/prism-autoloader.min.js",
        "vendor/pdfjs-dist/4.9.155/build/pdf.min.mjs",
        "vendor/pdfjs-dist/4.9.155/build/pdf.worker.min.mjs",
        "vendor/mermaid/10.9.3/mermaid.min.js",
    ]
    for vf in expected_vendor_files:
        p = os.path.join(webui_dir, vf)
        assert os.path.isfile(p) and os.path.getsize(p) > 500, f"Vendor fehlt/leer: {vf}"


def test_save_all_agent_profiles_writes_ssot_without_roles_clones(tmp_path, monkeypatch):
    import archon.core.profiles as prof_mod

    app_root = tmp_path / "repo"
    mem_dir = tmp_path / "mem"
    app_root.mkdir()
    mem_dir.mkdir()
    monkeypatch.setattr(prof_mod, "APP_ROOT", str(app_root))
    monkeypatch.setattr(prof_mod, "MEMORY_DIR", str(mem_dir))
    monkeypatch.chdir(app_root)

    prof_mod.save_all_agent_profiles([{"id": "alpha", "name": "Alpha"}])
    assert (app_root / "agent_profiles.json").exists()
    assert not (mem_dir / "roles.json").exists()
    assert not (app_root / "agent_workspace" / "roles.json").exists()


def test_hermes_config_uses_app_root_for_agent_profiles():
    import inspect
    import archon.routers.hermes_config as hc

    src = inspect.getsource(hc)
    assert 'os.path.join(APP_ROOT, "agent_profiles.json")' in src
    assert 'os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")' not in src


def test_org_hierarchy_matches_70_ssot_profiles_without_warnings():
    import json
    from pathlib import Path
    from backend.config_validator import ConfigValidator

    root = Path(__file__).resolve().parents[1]
    profiles = json.loads((root / "agent_profiles.json").read_text(encoding="utf-8"))
    hier = json.loads((root / "config" / "org_hierarchy.json").read_text(encoding="utf-8"))
    profile_ids = {p["id"] for p in profiles}
    node_ids = {n["id"] for n in hier.get("nodes", [])}

    assert node_ids == profile_ids
    validator = ConfigValidator(str(root))
    errors, warnings, _stats = validator.validate_org_hierarchy(profile_ids)
    assert errors == []
    assert warnings == []
