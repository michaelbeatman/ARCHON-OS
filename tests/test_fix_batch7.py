import os
import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from starlette.requests import Request
from starlette.exceptions import HTTPException


def _make_dummy_request(role: str = "admin") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
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
async def test_r24_reopen_task_clears_completed_and_started_at(tmp_path, monkeypatch):
    """R-24: Task auf todo zuruecksetzen muss completed_at und started_at loeschen."""
    import backend.operations_api as ops_mod

    db_path = tmp_path / "kanban_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            assignee TEXT,
            status TEXT,
            priority INTEGER,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_events (
            task_id TEXT,
            kind TEXT,
            payload TEXT,
            created_at TEXT
        )
    """)
    conn.execute("INSERT INTO tasks (id, title, assignee, status, priority, started_at, completed_at) VALUES ('task-1', 'Done Task', 'coder', 'done', 1, '2026-11-08T10:00:00', '2026-11-08T11:00:00')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(ops_mod, "KANBAN_DB_PATH", str(db_path))

    # Reopen to 'todo'
    req = ops_mod.TaskStatusUpdateRequest(status="todo")
    await ops_mod.update_task_status("task-1", req)

    # Pruefe DB: completed_at muss NULL sein!
    conn2 = sqlite3.connect(str(db_path))
    cur = conn2.cursor()
    cur.execute("SELECT status, started_at, completed_at FROM tasks WHERE id = 'task-1'")
    st, started, completed = cur.fetchone()
    conn2.close()

    assert st == "todo"
    assert completed is None, f"R-24 BUG: completed_at wurde nicht geloescht: {completed}"
    assert started is None, f"R-24 BUG: started_at wurde bei Reopen auf todo nicht geloescht: {started}"


def test_r25_failed_tasks_do_not_appear_in_todo_column(tmp_path, monkeypatch):
    """R-25: Tasks mit Status 'failed' duerfen nicht in der todo-Spalte landen."""
    import backend.operations_api as ops_mod

    db_path = tmp_path / "kanban_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            priority INTEGER,
            created_by TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            model_override TEXT,
            provider_override TEXT,
            block_kind TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_comments (id INTEGER PRIMARY KEY, task_id TEXT);
    """)
    conn.execute("""
        CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
    """)
    conn.execute("INSERT INTO tasks (id, title, status, priority, created_at) VALUES ('t-fail', 'Abgestuerzter Job', 'failed', 2, '2026-11-08T12:00:00')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(ops_mod, "KANBAN_DB_PATH", str(db_path))

    res = ops_mod.get_kanban_tasks(archived=False)
    cols = res["columns"]

    todo_ids = [t["id"] for t in cols.get("todo", [])]
    assert "t-fail" not in todo_ids, "R-25 BUG: failed task erschien in columns['todo']!"


def test_r26_bot_screen_abort_blocks_interaction(monkeypatch):
    """R-26: Nach Notfall-Abbruch muss interact blockiert werden (409 Conflict)."""
    import backend.operations_api as ops_mod
    from archon.routers import _rbac

    monkeypatch.setattr(_rbac, "_checker", lambda r: {"role": "admin"})
    monkeypatch.setattr("backend.operations_api.require_admin_or_503", lambda r: {"role": "admin"})

    req = _make_dummy_request("admin")
    # Loese Notfall-Abbruch aus
    ops_mod.abort_bot_screen_execution(req)

    # Nachfolgender Interaktionsversuch muss abgewiesen werden
    action = ops_mod.ScreenInteractionModel(action="click", x=100, y=200)
    with pytest.raises(HTTPException) as exc_info:
        ops_mod.interact_with_bot_screen(req, action)
    assert exc_info.value.status_code == 409


def test_r27_container_action_raises_http_exception_on_docker_error(monkeypatch):
    """R-27: Container-Aktion muss bei Docker-Fehler einen HTTP-Fehler werfen (kein 200 OK)."""
    import main as main_mod
    from utils.docker_client import DockerError

    def mock_fail(cname, action):
        raise DockerError(500, "Docker daemon socket connection refused")

    monkeypatch.setattr(main_mod.docker_client, "container_action", mock_fail)
    monkeypatch.setattr(main_mod, "require_admin", lambda r: {"role": "admin"})

    req = _make_dummy_request("admin")
    with pytest.raises(HTTPException) as exc_info:
        main_mod.api_docker_start({"container_name": "my-container"}, req)
    assert exc_info.value.status_code in (500, 502)


@pytest.mark.asyncio
async def test_r28_post_kanban_syncs_to_db(tmp_path, monkeypatch):
    """R-28: POST /api/kanban muss in die SQLite-DB schreiben, damit GET /api/kanban es sieht."""
    import main as main_mod

    db_path = tmp_path / "kanban.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            priority INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    cards_json_path = tmp_path / "kanban_cards.json"

    monkeypatch.setattr(main_mod, "KANBAN_CARDS_FILE", str(cards_json_path))
    monkeypatch.setattr(main_mod, "atomic_write_json", lambda path, data: None)
    monkeypatch.setattr(main_mod, "HERMES_HOME", str(tmp_path))

    # Mock request
    cards_payload = [
        {"id": "card-99", "title": "Synced Task", "description": "From POST API", "assignee": "coder", "status": "todo", "priority": 2}
    ]

    mock_request = _make_dummy_request("admin")
    mock_request.json = AsyncMock(return_value=cards_payload)

    # Rufe POST auf
    res = await main_mod.api_save_kanban(mock_request)
    assert res.get("status") == "success", f"POST /api/kanban fehlgeschlagen: {res}"

    # Pruefe DB: Task muss in DB existieren!
    conn2 = sqlite3.connect(str(db_path))
    cur = conn2.cursor()
    cur.execute("SELECT title FROM tasks WHERE id = 'card-99'")
    row = cur.fetchone()
    conn2.close()

    assert row is not None, "R-28 BUG: POST /api/kanban hat nicht in kanban.db geschrieben!"
    assert row[0] == "Synced Task"


def test_r29_cost_estimator_does_not_assume_unknown_model_is_free():
    """R-29: Unbekannte Modelle (z.B. gpt-5.1) duerfen nicht mit $0.00 kalkuliert werden."""
    from backend.cost_estimator import estimate_prompt_cost

    res = estimate_prompt_cost(
        prompt="Sehr langer Prompt " * 200,
        model_name="openai/gpt-5.1-turbo",
        expected_output_tokens=1000
    )

    assert res["estimated_cost_usd"] > 0.0, "R-29 BUG: Unbekanntes Modell wurde als gratis ($0.00) gewertet!"
