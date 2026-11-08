import os
import json
import sqlite3
import datetime
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.requests import Request
from starlette.responses import Response


def _make_dummy_request(role: str = "admin", path: str = "/") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "state": {
            "user": {
                "id": "usr_admin",
                "username": "admin",
                "role": role,
                "permissions": {},
            }
        },
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_m01_assets_serves_local_file_without_n8n():
    """M-01: /assets/custom.css muss lokale Datei liefern und nicht an n8n forwarden."""
    import main as main_mod

    req = _make_dummy_request("admin", path="/assets/custom.css")
    # n8n forwarder mocken um zu pruefen, ob er faelschlich aufgerufen wird
    mock_forward = AsyncMock(return_value=Response(status_code=502))
    with patch.object(main_mod, "forward_to_n8n", mock_forward):
        # Rufe den Handler fuer /assets/{path:path} auf
        res = await main_mod.n8n_assets_proxy(req, path="custom.css")
        assert res.status_code == 200
        assert mock_forward.call_count == 0


def test_m04_target_category_cannot_traverse(tmp_path):
    """M-04: target_category mit ../ darf nicht ausserhalb der Wissensbibliothek schreiben."""
    from utils.batch_library_importer import process_document

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    doc = tmp_path / "test.txt"
    doc.write_text("Test content for extraction")

    # Boesartige Kategorie
    res = process_document(str(doc), str(vault_dir), target_category="../../escaped_dir")
    # Es darf kein Verzeichnis ausserhalb von 02_Wissensbibliothek angelegt worden sein
    bib_dir = vault_dir / "02_Wissensbibliothek"
    escaped_dir = tmp_path / "escaped_dir"
    assert not escaped_dir.exists(), f"Directory {escaped_dir} was created outside vault!"


def test_m05_contracts_history_not_shadowed_by_contract_id():
    """M-05: /api/contracts/history darf nicht durch {contract_id} verdeckt werden."""
    import archon.routers.contracts as contracts_mod

    # Pruefe die Reihenfolge der Routes im Router:
    # 'api/contracts/history' muss VOR 'api/contracts/{contract_id}' stehen
    history_idx = -1
    item_idx = -1
    for idx, route in enumerate(contracts_mod.router.routes):
        path = getattr(route, "path", "")
        if path == "/api/contracts/history":
            history_idx = idx
        elif path == "/api/contracts/{contract_id}":
            item_idx = idx

    assert history_idx != -1
    assert item_idx != -1
    assert history_idx < item_idx, f"history route (idx {history_idx}) is shadowed by contract_id route (idx {item_idx})"


def test_r01_profile_delete_twice_does_not_bypass_gate(tmp_path, monkeypatch):
    """R-01: Zweiter DELETE-Aufruf darf Profil nicht ohne Bestaetigung loeschen."""
    import archon.services.profiles_service as prof_svc

    # Setup temp dirs
    base_dir = tmp_path / "profiles"
    base_dir.mkdir()
    agent_dir = base_dir / "test-agent"
    agent_dir.mkdir()
    (agent_dir / "profile.json").write_text('{"id": "test-agent"}')

    gates_state = {"gates": []}

    monkeypatch.setattr(prof_svc, "get_hermes_profiles_base_dirs", lambda: [str(base_dir)])
    monkeypatch.setattr(prof_svc, "agent_profiles_json_path", lambda: str(tmp_path / "agent_profiles.json"))
    monkeypatch.setattr(prof_svc, "_load_permission_gates", lambda: gates_state)
    def _mock_create_gate(kind, desc, req_by, payload):
        g = {"id": "gate_123", "kind": kind, "status": "pending", "payload": payload}
        gates_state["gates"].append(g)
        return g
    monkeypatch.setattr(prof_svc, "_create_permission_gate", _mock_create_gate)

    # 1. Erster Aufruf: Erzeugt Gate
    res1 = prof_svc.delete_profile("test-agent")
    assert res1.get("status") == "pending_owner_approval"
    assert agent_dir.exists(), "Profile was deleted on first call!"

    # 2. Zweiter Aufruf (bevor Gate bestaetigt ist): DARF NICHT LOESCHEN
    res2 = prof_svc.delete_profile("test-agent")
    assert res2.get("status") == "pending_owner_approval", f"Second call returned: {res2}"
    assert agent_dir.exists(), "R-01 BUG: Profile was deleted on second call without approval!"


def test_r02_crash_recovery_does_not_reset_recent_tasks(tmp_path, monkeypatch):
    """R-02: Crash-Recovery darf laufende Tasks mit aktuellem ISO-Timestamp nicht auf todo zuruecksetzen."""
    import backend.operations_api as ops_mod

    db_path = tmp_path / "kanban_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            status TEXT,
            started_at TEXT,
            created_at TEXT
        )
    """)
    # Task gestartet vor 10 Minuten
    ten_mins_ago = (datetime.datetime.now() - datetime.timedelta(minutes=10)).isoformat()
    conn.execute("INSERT INTO tasks (id, title, status, started_at, created_at) VALUES ('t1', 'Recent Task', 'in_progress', ?, ?)",
                 (ten_mins_ago, ten_mins_ago))
    # Task gestartet vor 10 Stunden (sollte recovered werden)
    ten_hours_ago = (datetime.datetime.now() - datetime.timedelta(hours=10)).isoformat()
    conn.execute("INSERT INTO tasks (id, title, status, started_at, created_at) VALUES ('t2', 'Old Task', 'in_progress', ?, ?)",
                 (ten_hours_ago, ten_hours_ago))
    conn.commit()
    conn.close()

    monkeypatch.setattr(ops_mod, "KANBAN_DB_PATH", str(db_path))
    monkeypatch.setattr(ops_mod, "_KANBAN_JOURNAL_INIT", False)

    # _get_kanban_connection triggert Crash-Recovery beim ersten Aufruf
    test_conn = ops_mod._get_kanban_connection()
    cur = test_conn.cursor()

    cur.execute("SELECT status FROM tasks WHERE id = 't1'")
    t1_status = cur.fetchone()[0]

    cur.execute("SELECT status FROM tasks WHERE id = 't2'")
    t2_status = cur.fetchone()[0]
    test_conn.close()

    assert t2_status == "todo", "Alte Task (10h) muss auf todo gesetzt werden"
    assert t1_status == "in_progress", f"R-02 BUG: Frische Task (10min) wurde faelschlich auf {t1_status} zurueckgesetzt!"
