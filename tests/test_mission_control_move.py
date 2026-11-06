"""
Tests für den Move-Handler des Mission-Control-Routers.

Der Handler schrieb früher erst am Ende und hielt dabei keinen Lock über die
Lese-Ändere-Schreibe-Kette; parallele Moves überschrieben einander. Nach dem
Umbau läuft der Zustandswechsel atomar im Thread-Pool, Seiteneffekte (Synthese,
Ausführung) erst danach.

Geprüft werden die fachlichen Zweige UND die Nebenläufigkeit.
"""

import asyncio
import json
import os
import sys

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import archon.core.mission_control as mc  # noqa: E402
import archon.routers.mission_control as mcr  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "mission_control_data.json"
    path.write_text(json.dumps({
        "tasks": [
            {"id": "t1", "title": "Eins", "agent_name": "Micha", "status": "approval"},
            {"id": "t2", "title": "Zwei", "agent_name": "Sandy", "status": "backlog"},
            {
                "id": "t3", "title": "Entwurf", "agent_name": "Lisa", "status": "approval",
                "synthesis_draft_path": "/tmp/draft.md", "parent_project_id": "p1",
            },
        ],
        "audit_logs": [],
    }), encoding="utf-8")
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(path))

    calls = {"execute": [], "finalize": [], "fan_in": [], "ticker": []}

    async def _execute(task_id):
        calls["execute"].append(task_id)

    async def _finalize(*args, **kwargs):
        calls["finalize"].append((args, kwargs))

    async def _fan_in(pid):
        calls["fan_in"].append(pid)

    monkeypatch.setitem(mcr._DEPS, "execute", _execute)
    monkeypatch.setitem(mcr._DEPS, "finalize_approval", _finalize)
    monkeypatch.setitem(mcr._DEPS, "fan_in", _fan_in)
    monkeypatch.setitem(mcr._DEPS, "sync_obsidian", lambda task: "/tmp/obs/bericht.md")
    monkeypatch.setitem(mcr._DEPS, "telemetry", lambda: {})
    monkeypatch.setattr(mcr, "add_ticker", lambda *a, **k: calls["ticker"].append(a))
    monkeypatch.setattr(mcr, "broadcast_event", lambda *a, **k: None)
    monkeypatch.setattr(mcr, "_MC_STATE_CACHE", {"ts": 0.0, "data": None})

    return path, calls


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _task(path, tid):
    return next(t for t in _read(path)["tasks"] if t["id"] == tid)


# ---------------------------------------------------------------- Zweige

@pytest.mark.asyncio
async def test_move_to_in_progress_sets_fields_and_executes(store):
    path, calls = store
    resp = await mcr.move_mission_control_task(mcr.TaskMoveRequest(task_id="t1", target_status="in_progress"))

    assert resp["status"] == "ok"
    task = _task(path, "t1")
    assert task["status"] == "in_progress"
    assert "started_at" in task and "active_tool" in task
    await asyncio.sleep(0)          # create_task ausführen lassen
    assert calls["execute"] == ["t1"]


@pytest.mark.asyncio
async def test_move_to_completed_sets_artifact_and_summary(store):
    path, calls = store
    resp = await mcr.move_mission_control_task(
        mcr.TaskMoveRequest(task_id="t2", target_status="completed", result_summary="Fertig.")
    )

    assert resp["task"]["status"] == "completed"
    task = _task(path, "t2")
    assert task["artifact_path"] == "/tmp/obs/bericht.md"
    assert task["result_summary"] == "Fertig."


@pytest.mark.asyncio
async def test_move_dismissed_removes_task(store):
    path, _ = store
    resp = await mcr.move_mission_control_task(mcr.TaskMoveRequest(task_id="t2", target_status="dismissed"))

    assert resp["message"] == "Task verworfen."
    assert "t2" not in {t["id"] for t in _read(path)["tasks"]}


@pytest.mark.asyncio
async def test_move_unknown_task_raises_404(store):
    with pytest.raises(HTTPException) as err:
        await mcr.move_mission_control_task(mcr.TaskMoveRequest(task_id="gibtsnicht", target_status="completed"))
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_completed_with_draft_triggers_finalize_and_fan_in(store):
    path, calls = store
    await mcr.move_mission_control_task(
        mcr.TaskMoveRequest(task_id="t3", target_status="completed", result_summary="Freigegeben.")
    )

    assert _task(path, "t3")["synthesis_finalized"] is True
    assert len(calls["finalize"]) == 1
    args, kwargs = calls["finalize"][0]
    assert args[0] == "p1"                      # parent_project_id
    assert "daten" not in kwargs                # laedt selbst frisch
    await asyncio.sleep(0)
    assert calls["fan_in"] == ["p1"]


# ---------------------------------------------------------------- Nebenläufigkeit

@pytest.mark.asyncio
async def test_parallel_moves_do_not_overwrite_each_other(store):
    """Zwei gleichzeitige Moves auf verschiedene Tasks müssen beide überleben.

    Mit dem alten load/save-Muster verlor der zweite Schreiber den ersten.
    """
    path, _ = store
    await asyncio.gather(
        mcr.move_mission_control_task(mcr.TaskMoveRequest(task_id="t1", target_status="completed")),
        mcr.move_mission_control_task(mcr.TaskMoveRequest(task_id="t2", target_status="in_progress")),
    )

    assert _task(path, "t1")["status"] == "completed"
    assert _task(path, "t2")["status"] == "in_progress"
