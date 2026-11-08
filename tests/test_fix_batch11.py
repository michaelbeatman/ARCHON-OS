"""
tests/test_fix_batch11.py
Rot-Beweise fuer Batch 11:
- N-10: sync_obsidian laeuft NICHT unter _MC_DATA_LOCK
- N-11: Task- und Debate-IDs sind kollisionsfrei (kein time.time() % 10000)
- N-12: task_self_healer setzt nur explizite, gepruefte Dateien zurueck (kein git checkout -- .)
- N-13 & D-22: CRM-Nachrichten sind kollisionsfrei und threadsicher
"""
import time
import uuid
import datetime
import pytest
import asyncio
from unittest.mock import MagicMock, patch

from archon.core.mission_control import _MC_DATA_LOCK, _load_mission_control_data, _write_mc_atomic
from archon.routers.mission_control import (
    move_mission_control_task,
    capture_mission_control_task,
    TaskMoveRequest,
    NewTaskCaptureRequest,
    _DEPS,
)
from archon.routers.boardroom import (
    api_run_boardroom,
    api_stream_boardroom,
    BoardroomRequest,
)
from backend.task_self_healer import TaskSelfHealer
from backend.crm_service import CRMService, CRM_SQLITE_PATH


@pytest.mark.asyncio
async def test_n10_sync_obsidian_outside_mc_lock(monkeypatch, tmp_path):
    """N-10: sync_obsidian darf NIEMALS unter dem globalen _MC_DATA_LOCK ausgefuehrt werden."""
    fake_tasks = {
        "tasks": [
            {
                "id": "task-test-sync",
                "title": "Obsidian Lock Test Task",
                "status": "in_progress",
                "agent_name": "Test Agent",
            }
        ],
        "audit_logs": [],
    }

    # Patch data store
    monkeypatch.setattr("archon.core.mission_control._load_mission_control_data", lambda: dict(fake_tasks))
    monkeypatch.setattr("archon.core.mission_control._write_mc_atomic", lambda d: fake_tasks.update(d))

    was_locked_during_sync = None

    def fake_sync(task):
        nonlocal was_locked_during_sync
        # Pruefe, ob der aufrufende Thread den Lock haelt
        was_locked_during_sync = _MC_DATA_LOCK._is_owned()
        return "/tmp/fake_vault_doc.md"

    monkeypatch.setitem(_DEPS, "sync_obsidian", fake_sync)

    req = TaskMoveRequest(task_id="task-test-sync", target_status="completed")
    res = await move_mission_control_task(req)

    assert res["status"] == "ok"
    assert was_locked_during_sync is False, "sync_obsidian lief UNTER dem _MC_DATA_LOCK!"


@pytest.mark.asyncio
async def test_n11_task_ids_collision_free(monkeypatch):
    """N-11: Bei schnellen Aufrufen in derselben Sekunde muessen Task-IDs eindeutig sein."""
    # Friere time.time() ein, um gleichzeitige Aufrufe zu simulieren
    fixed_time = 1770000000.123
    monkeypatch.setattr(time, "time", lambda: fixed_time)

    dummy_data = {"tasks": [], "audit_logs": []}
    monkeypatch.setattr("archon.routers.mission_control.update_mission_control_data", lambda f: f(dummy_data))
    monkeypatch.setattr("archon.routers.mission_control.broadcast_event", lambda ev, payload: None)

    req1 = NewTaskCaptureRequest(title="Task Alpha")
    req2 = NewTaskCaptureRequest(title="Task Beta")

    res1 = await capture_mission_control_task(req1)
    res2 = await capture_mission_control_task(req2)

    id1 = res1["task"]["id"]
    id2 = res2["task"]["id"]

    assert id1 != id2, f"Task-IDs kollidieren in derselben Sekunde: {id1} == {id2}"
    assert len(id1) > len("task-0000"), "Task-ID hat kein kollisionssicheres Suffix"


@pytest.mark.asyncio
async def test_n11_boardroom_debate_ids_collision_free(monkeypatch, tmp_path):
    """N-11: Boardroom-Debatten in derselben Sekunde muessen eindeutige IDs haben."""
    fixed_time = 1770000000.123
    monkeypatch.setattr(time, "time", lambda: fixed_time)

    # Mock dependencies
    saved_history = []
    monkeypatch.setattr("archon.routers.boardroom.save_boardroom_history_item", lambda item: saved_history.append(item))
    monkeypatch.setattr("archon.routers.boardroom.OBSIDIAN_VAULT_DIR", str(tmp_path))
    monkeypatch.setattr("archon.routers.boardroom.add_ticker", lambda *args: None)
    from archon.routers import boardroom
    monkeypatch.setitem(boardroom._DEPS, "load_roles", lambda: [])
    monkeypatch.setitem(boardroom._DEPS, "api_get_hermes_profiles", lambda: [])

    async def fake_dispatch(*args, **kwargs):
        return {"transcript": "text", "synthesis": "synth", "rounds_completed": 1, "chairman": {"name": "Moderator"}}

    monkeypatch.setattr("core_dispatcher.run_boardroom_debate", fake_dispatch)

    req = BoardroomRequest(task="Test Strategiefrage", rounds=1)

    res1 = await api_run_boardroom(req)
    res2 = await api_run_boardroom(req)

    hist_id1 = res1["history_id"]
    hist_id2 = res2["history_id"]

    assert hist_id1 != hist_id2, f"Debatten-IDs kollidieren: {hist_id1} == {hist_id2}"


def test_n12_task_self_healer_safety(tmp_path):
    """N-12: task_self_healer setzt nur explizite, gepruefte Dateien zurueck und ignoriert leere Pfade."""
    db_file = tmp_path / "test_healing.db"
    healer = TaskSelfHealer(db_path=str(db_file))

    # Aufruf mit None / leerem String
    res_none = healer.rollback_git_changes(None)
    assert res_none["status"] == "skipped"

    res_empty = healer.rollback_git_changes("")
    assert res_empty["status"] == "skipped"

    # Verbotene Pfade
    res_dot = healer.rollback_git_changes(".")
    assert res_dot["status"] == "error"

    res_traversal = healer.rollback_git_changes("../etc/passwd")
    assert res_traversal["status"] == "error"


def test_n13_d22_crm_messages_collision_free_and_atomic(monkeypatch, tmp_path):
    """N-13 & D-22: CRM-Nachrichten in derselben Sekunde muessen unterschiedliche IDs haben."""
    # SQLite Test-DB anlegen
    import sqlite3
    db_path = tmp_path / "test_crm.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE kontakte (
            id TEXT PRIMARY KEY,
            name TEXT,
            nachrichtenverlauf TEXT,
            updated TEXT
        )
    """)
    conn.execute("INSERT INTO kontakte (id, name, nachrichtenverlauf, updated) VALUES ('c1', 'Max Mustermann', '[]', '')")
    conn.commit()
    conn.close()

    monkeypatch.setattr("backend.crm_service.CRM_SQLITE_PATH", str(db_path))
    fixed_time = 1770000000.123
    fixed_dt = datetime.datetime.fromtimestamp(fixed_time)

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_dt
        @classmethod
        def utcnow(cls):
            return fixed_dt

    monkeypatch.setattr("backend.crm_service.datetime.datetime", FixedDateTime)

    crm = CRMService()
    res1 = crm.add_contact_message("c1", "Erste Nachricht")
    res2 = crm.add_contact_message("c1", "Zweite Nachricht")

    msg_id1 = res1["message"]["id"]
    msg_id2 = res2["message"]["id"]

    assert msg_id1 != msg_id2, f"CRM-Nachrichten-IDs kollidieren: {msg_id1} == {msg_id2}"
    assert res2["total_messages"] == 2
