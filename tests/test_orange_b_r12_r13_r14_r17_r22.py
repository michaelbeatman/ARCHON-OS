"""Regressionstests R-12, R-13, R-14, R-17, R-22.

R-12: hermes_updater darf einen fehlgeschlagenen Container-Recreate nicht
     als erfolgreiches Update melden.
R-13: mission_control-Artefakt-Endpoint liefert 404 statt erfundenen Bericht.
R-14: boardroom-history erfindet keine Sample-Debatten und schreibt im GET.
R-17: privacy_router blockiert sensible Payloads fail-closed.
R-22: Mahnfreigabe prueft Rechnungsstatus und Stufenfolge.
"""

import json
import os
import sqlite3
import sys
import tempfile
import types
from unittest import mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------- R-12

def test_apply_hermes_update_honest_error_when_recreate_failed():
    import backend.hermes_updater as hu

    class _FakeDockerCli:
        def post(self, *a, **k):
            return (200, '{}')   # Pull + Tag OK

    def _fake_recreate(docker_cli, container, image):
        return False, "Image-Crash beim Start"

    def _fake_installed(force_check=False):
        return {"version": "v1.2.3", "installed_sha": "abc123", "installed_sha_short": "abc123"}

    with mock.patch.object(hu, "_make_docker_client", return_value=_FakeDockerCli()), \
         mock.patch.object(hu, "recreate_container_with_new_image", side_effect=_fake_recreate), \
         mock.patch.object(hu, "get_installed_hermes_info", side_effect=_fake_installed):
        res = hu.apply_hermes_update(channel="latest", auto_restart=True)

    assert res["status"] == "error"
    assert "NICHT neu erstellt" in res["message"]
    assert res["container_restarted"] is False


def test_apply_hermes_update_success_when_recreate_ok():
    import backend.hermes_updater as hu

    class _FakeDockerCli:
        def post(self, *a, **k):
            return (200, '{}')

    def _fake_recreate(docker_cli, container, image):
        return True, "ok"

    def _fake_installed(force_check=False):
        return {"version": "v2.0.0", "installed_sha": "def456", "installed_sha_short": "def456"}

    with mock.patch.object(hu, "_make_docker_client", return_value=_FakeDockerCli()), \
         mock.patch.object(hu, "recreate_container_with_new_image", side_effect=_fake_recreate), \
         mock.patch.object(hu, "get_installed_hermes_info", side_effect=_fake_installed):
        res = hu.apply_hermes_update(channel="latest", auto_restart=True)

    assert res["status"] == "success"
    assert res["container_restarted"] is True


# ---------------------------------------------------------------- R-13

def test_mission_control_artifact_missing_returns_404():
    from archon.routers import mission_control as mc

    data = {"tasks": [{"id": "t-1", "title": "T", "artifact_path": "/pfad/die/es/nicht/gibt.md"}]}
    with mock.patch.object(mc, "_load_mission_control_data", return_value=data):
        with pytest.raises(HTTPException) as e:
            import asyncio
            asyncio.run(mc.get_mission_control_task_artifact("t-1"))
    assert e.value.status_code == 404


# ---------------------------------------------------------------- R-14

def test_boardroom_history_empty_when_no_store(tmp_path):
    from archon.routers import boardroom as br

    target = tmp_path / "boardroom_history.json"
    with mock.patch.object(br, "BOARDROOM_HISTORY_FILE", str(target)), \
         mock.patch.object(br, "_load_json", side_effect=lambda p, d: d if not os.path.exists(p) else None), \
         mock.patch.object(br, "_save_json") as save_mock:
        hist = br.load_boardroom_history()

    assert hist == []
    save_mock.assert_not_called()  # kein Schreib-Seiteneffekt im GET


def test_boardroom_history_no_samples_anywhere():
    import ast
    from archon.routers import boardroom as br
    src = ast.parse(open(br.__file__, encoding="utf-8").read())
    assert not any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and "deb_sample" in n.value
        for n in ast.walk(src)
    )


# ---------------------------------------------------------------- R-17

def test_route_sensitive_payload_blocks_when_local_down_no_eu_fallback():
    from backend.privacy_router import route_sensitive_payload

    cfg = {
        "sensitive_local_routing": True,
        "sensitive_categories": ["finance", "contracts", "hr", "finanzen"],
        "fallback_to_eu": True,
        "mistral_api_key": "",
        "local_llm_url": "http://127.0.0.1:11434/v1",
        "local_llm_model": "llama3.2",
    }
    with mock.patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         mock.patch("backend.privacy_router.check_local_llm_status", return_value={"available": False}):
        res = route_sensitive_payload("finance", [], default_provider="groq", default_model="gpt-x")

    assert res["blocked"] is True
    assert res["provider"] is None


def test_route_sensitive_payload_local_ok_still_routes():
    from backend.privacy_router import route_sensitive_payload

    cfg = {
        "sensitive_local_routing": True,
        "sensitive_categories": ["finanzen"],
        "local_llm_url": "http://127.0.0.1:11434/v1",
        "local_llm_model": "llama3.2",
    }
    with mock.patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         mock.patch("backend.privacy_router.check_local_llm_status", return_value={"available": True}):
        res = route_sensitive_payload("finanzen", [], default_provider="groq", default_model="gpt-x")

    assert res["routed"] is True
    assert res["provider"] == "local"


# ---------------------------------------------------------------- R-22

def _dunning_memory_db():
    tmpdir = tempfile.mkdtemp(prefix="orangeb_r22_")
    dbp = os.path.join(tmpdir, "agentic_memory.db")
    conn = sqlite3.connect(dbp)
    conn.execute("""CREATE TABLE invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        customer_email TEXT NOT NULL,
        recipient_address TEXT,
        invoice_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        amount_net REAL NOT NULL,
        tax_amount REAL NOT NULL,
        amount_gross REAL NOT NULL,
        currency TEXT DEFAULT 'EUR',
        status TEXT DEFAULT 'open',
        last_reminder_date TEXT,
        dunning_level INTEGER DEFAULT 0,
        dunning_fee REAL DEFAULT 0.0,
        kanban_task_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE dunning_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dunning_id TEXT UNIQUE NOT NULL,
        invoice_id TEXT NOT NULL,
        level INTEGER NOT NULL,
        issued_date TEXT NOT NULL,
        deadline_date TEXT NOT NULL,
        fee REAL DEFAULT 0.0,
        interest REAL DEFAULT 0.0,
        total_claim REAL NOT NULL,
        status TEXT DEFAULT 'draft',
        draft_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()
    return dbp


def _seed_dunning(dbp, inv_status="open", inv_level=0, dunning_status="draft", level=3):
    conn = sqlite3.connect(dbp)
    conn.execute(
        "INSERT INTO invoices (invoice_id, customer_name, customer_email, invoice_date, due_date, amount_net, tax_amount, amount_gross, status, dunning_level) "
        "VALUES ('RE-2026-0001', 'Kunde', 'k@x.de', '2026-10-01', '2026-10-15', 100, 19, 119, ?, ?)",
        (inv_status, inv_level),
    )
    conn.execute(
        "INSERT INTO dunning_history (dunning_id, invoice_id, level, issued_date, deadline_date, fee, interest, total_claim, status) "
        "VALUES ('MAHN-1', 'RE-2026-0001', ?, '2026-11-01', '2026-11-08', 0, 0, 119, ?)",
        (level, dunning_status),
    )
    conn.commit()
    conn.close()


def test_dunning_refuses_paid_invoice():
    from backend.dunning_engine import DunningEngine

    dbp = _dunning_memory_db()
    _seed_dunning(dbp, inv_status="paid", inv_level=0)
    eng = DunningEngine.__new__(DunningEngine)
    eng.memory_db = dbp
    eng.kanban_db = ""
    with pytest.raises(ValueError, match="paid"):
        eng.approve_and_send_dunning("MAHN-1")


def test_dunning_refuses_level_skip():
    from backend.dunning_engine import DunningEngine

    dbp = _dunning_memory_db()
    _seed_dunning(dbp, inv_status="open", inv_level=1, level=3)
    eng = DunningEngine.__new__(DunningEngine)
    eng.memory_db = dbp
    eng.kanban_db = ""
    with pytest.raises(ValueError, match="Stufe 2"):
        eng.approve_and_send_dunning("MAHN-1")


def test_dunning_allows_proper_progression():
    from backend.dunning_engine import DunningEngine

    dbp = _dunning_memory_db()
    _seed_dunning(dbp, inv_status="open", inv_level=2, level=3)
    eng = DunningEngine.__new__(DunningEngine)
    eng.memory_db = dbp
    eng.kanban_db = ""
    res = eng.approve_and_send_dunning("MAHN-1")
    assert res["status"] == "success"
    assert res["dunning_id"] == "MAHN-1"
