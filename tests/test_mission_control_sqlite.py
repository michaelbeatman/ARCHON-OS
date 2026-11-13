"""Tests für die Ablösung von mission_control_data.json durch kanban.db (SQLite).

Verifiziert ohne jede JSON-Datei:
1. Einmalige Migration bestehender JSON-Tasks & Audit-Logs nach kanban.db + .bak-Archivierung.
2. Capture, Move (in_progress, completed, dismissed) und Artifact direkt über kanban.db.
3. Delegation-Bridge (task_links + project_id) & Fan-In Synthese-Auslösung über kanban.db.
4. Nebenläufige update_mission_control_data()-Calls auf kanban.db ohne Lost Updates.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import archon.core.mission_control as mc  # noqa: E402
import archon.core.orchestration as orch  # noqa: E402
import archon.routers.mission_control as mcr  # noqa: E402


@pytest.fixture
def sqlite_env(tmp_path, monkeypatch):
    """Stellt eine frische kanban.db ohne mission_control_data.json bereit."""
    db_file = tmp_path / "kanban.db"
    fake_default_json = tmp_path / "nonexistent_default_mc.json"
    monkeypatch.setattr(mc, "KANBAN_DB_PATH", str(db_file))
    monkeypatch.setattr(mc, "_DEFAULT_MISSION_CONTROL_FILE", str(fake_default_json))
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(fake_default_json))
    monkeypatch.setattr(mc, "_MIGRATION_DONE", True)
    monkeypatch.setattr(mc, "_MC_STATE_CACHE", {"ts": 0.0, "data": None})
    monkeypatch.setattr(mcr, "_MC_STATE_CACHE", mc._MC_STATE_CACHE)
    return db_file, tmp_path


def test_migration_imports_json_into_kanban_and_creates_bak(tmp_path, monkeypatch):
    db_file = tmp_path / "kanban.db"
    json_file = tmp_path / "mission_control_data.json"
    json_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "proj-1",
                        "title": "Elternprojekt",
                        "agent_id": "robert",
                        "agent_name": "Robert",
                        "status": "active",
                        "phase": "in_progress",
                        "plan": ["Schritt A", "Schritt B"],
                    },
                    {
                        "id": "sub-1",
                        "title": "Teilaufgabe 1",
                        "agent_id": "sandy",
                        "agent_name": "Sandy",
                        "status": "completed",
                        "parent_project_id": "proj-1",
                        "result_summary": "Teilbericht fertig",
                    },
                ],
                "audit_logs": [
                    {"time": "12:00:00", "source": "Test", "msg": "Historischer Eintrag"}
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(mc, "KANBAN_DB_PATH", str(db_file))
    monkeypatch.setattr(mc, "_DEFAULT_MISSION_CONTROL_FILE", str(json_file))
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(json_file))
    monkeypatch.setattr(mc, "_MIGRATION_DONE", False)

    state = mc._load_mission_control_data()

    assert not json_file.exists(), "mission_control_data.json muss nach .bak verschoben sein"
    assert (tmp_path / "mission_control_data.json.bak").exists()
    assert state["source"] == "kanban.db"

    ids = {t["id"] for t in state["tasks"]}
    assert {"proj-1", "sub-1"} <= ids

    sub = next(t for t in state["tasks"] if t["id"] == "sub-1")
    assert sub["status"] == "completed"
    assert sub["parent_project_id"] == "proj-1"
    assert state["audit_logs"][0]["msg"] == "Historischer Eintrag"

    conn = sqlite3.connect(db_file)
    try:
        links = conn.execute("SELECT parent_id, child_id FROM task_links").fetchall()
        assert ("proj-1", "sub-1") in links
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_capture_move_and_dismiss_persist_in_kanban_db(sqlite_env, monkeypatch):
    db_file, tmp_path = sqlite_env
    art = tmp_path / "report.md"
    art.write_text("# Abschlussbericht\nAlles erledigt.", encoding="utf-8")

    monkeypatch.setitem(mcr._DEPS, "execute", lambda tid: asyncio.sleep(0))
    monkeypatch.setitem(mcr._DEPS, "finalize_approval", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setitem(mcr._DEPS, "fan_in", lambda pid: asyncio.sleep(0))
    monkeypatch.setitem(mcr._DEPS, "sync_obsidian", lambda task: str(art))
    monkeypatch.setitem(mcr._DEPS, "telemetry", lambda: {"today_cost": 1.23, "tokens_last_15m": 420})
    monkeypatch.setattr(mcr, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(mcr, "broadcast_event", lambda *a, **k: None)

    cap = await mcr.capture_mission_control_task(mcr.NewTaskCaptureRequest(title="SQLite Migration prüfen"))
    tid = cap["task"]["id"]

    res_state = await mcr.get_mission_control_state()
    assert any(t["id"] == tid for t in res_state["tasks"])
    assert res_state["telemetry"]["tokens_last_15m"] == 420

    mv = await mcr.move_mission_control_task(
        mcr.TaskMoveRequest(task_id=tid, target_status="completed", result_summary="Verifiziert.")
    )
    assert mv["task"]["artifact_path"] == str(art)

    loaded_art = await mcr.get_mission_control_task_artifact(tid)
    assert "Abschlussbericht" in loaded_art["content"]

    dm = await mcr.move_mission_control_task(
        mcr.TaskMoveRequest(task_id=tid, target_status="dismissed")
    )
    assert dm["status"] == "ok"
    assert mc.mc_get_task_sqlite(tid) is None
    assert not (tmp_path / "nonexistent_default_mc.json").exists()


@pytest.mark.asyncio
async def test_delegation_link_and_fan_in_work_purely_in_sqlite(sqlite_env):
    db_file, _ = sqlite_env

    # Child-Task anlegen (wie durch operations/delegation)
    mc.mc_capture_task_sqlite(
        {"id": "child-1", "title": "Teilaufgabe A", "agent_id": "sandy", "agent_name": "Sandy", "status": "in_progress"}
    )
    mc.mc_capture_task_sqlite(
        {"id": "child-2", "title": "Teilaufgabe B", "agent_id": "micha", "agent_name": "Micha", "status": "in_progress"}
    )

    mc.mc_link_subtask_sqlite(
        "proj-fanin",
        "child-1",
        parent_defaults={"title": "Fan-In Gesamtprojekt", "agent_id": "robert", "agent_name": "Robert", "status": "active"},
    )
    mc.mc_link_subtask_sqlite("proj-fanin", "child-2")

    p_id, p_title = mc.mc_get_parent_context_sqlite("child-1")
    assert p_id == "proj-fanin"
    assert p_title == "Fan-In Gesamtprojekt"

    triggered = []

    async def fake_cascade(pid: str):
        triggered.append(pid)

    # Erst child-1 fertig -> noch keine Synthese
    mc.mc_update_task_sqlite("child-1", {"status": "completed", "result_summary": "A ok"})
    await orch._fan_in_maybe_start_synthesis("proj-fanin", run_cascade=fake_cascade)
    await asyncio.sleep(0)
    assert triggered == []

    # Jetzt child-2 fertig -> Synthese startet genau einmal
    mc.mc_update_task_sqlite("child-2", {"status": "completed", "result_summary": "B ok"})
    await orch._fan_in_maybe_start_synthesis("proj-fanin", run_cascade=fake_cascade)
    await orch._fan_in_maybe_start_synthesis("proj-fanin", run_cascade=fake_cascade)
    await asyncio.sleep(0)
    assert triggered == ["proj-fanin"]


def test_sqlite_concurrent_updates_have_no_lost_writes(sqlite_env):
    mc.mc_capture_task_sqlite({"id": "seed", "title": "Seed", "status": "backlog"})

    def worker(idx: int):
        for j in range(5):
            mc.update_mission_control_data(
                lambda d: d.__setitem__("counter", d.get("counter", 0) + 1)
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
        assert not t.is_alive()

    state = mc._load_mission_control_data()
    assert state["counter"] == 50
