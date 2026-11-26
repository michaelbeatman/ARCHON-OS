"""v0.6 Pre-Flight P0 (MED-2) & P2 (MED-1) Regressionstests."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

import archon.services.background_loops as bl
import backend.audit_log as audit_mod
import backend.workflow_dag_runner as wdr


@pytest.mark.asyncio
async def test_v06_p0_cancel_background_tasks_records_all_failures_and_cleans_list_on_audit_error(monkeypatch):
    """P0/MED-2: audit_write_failed bei Task 1 darf Task 2 und _BACKGROUND_TASKS-Cleanup nicht ueberspringen."""
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "1")
    bl._BACKGROUND_TASKS.clear()
    bl._FAILED_CANCELS.clear()

    async def _crash_on_cancel(msg: str) -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise ValueError(msg)

    t1 = asyncio.create_task(_crash_on_cancel("t1_fail"), name="bg_task_1")
    t2 = asyncio.create_task(_crash_on_cancel("t2_fail"), name="bg_task_2")
    bl._BACKGROUND_TASKS.extend([t1, t2])
    await asyncio.sleep(0.01)

    deps = SimpleNamespace(
        get_rag_sync_process=lambda: None,
        set_rag_sync_process=lambda _v: None,
    )
    monkeypatch.setattr(bl, "_resolve_deps", lambda: deps)
    monkeypatch.setattr(
        audit_mod.chained_audit_log,
        "record_event",
        lambda **_kw: (_ for _ in ()).throw(OSError("audit db down")),
    )

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        await bl._cancel_background_tasks()

    # Beide fehlgeschlagenen Tasks muessen erfasst UND _BACKGROUND_TASKS bereinigt sein
    recorded_names = [entry["task"] for entry in bl._FAILED_CANCELS]
    assert "bg_task_1" in recorded_names
    assert "bg_task_2" in recorded_names
    assert bl._BACKGROUND_TASKS == []


@pytest.mark.asyncio
async def test_v06_p2_dag_resume_cleanup_future_is_tracked_and_drainable(monkeypatch, tmp_path):
    """P2/MED-1: _on_resume_done trackt das Executor-Future; drain_pending_resume_cleanups() wartet deterministisch."""
    db_path = str(tmp_path / "dag_med1.db")
    orig_connect = wdr._connect
    now = time.time()
    run_id = "run-v06-med1"
    with orig_connect(db_path) as con:
        con.execute(
            "INSERT INTO workflow_runs (run_id, workflow_id, status, created_at, updated_at) "
            "VALUES (?, 'wf-1', 'running', ?, ?)",
            (run_id, now, now),
        )
        con.commit()

    async def _boom_resume(**_kw):
        raise RuntimeError("boom during resume")

    def _slow_connect(p=None):
        time.sleep(0.15)
        return orig_connect(p)

    monkeypatch.setattr(wdr, "resume_workflow_run", _boom_resume)
    monkeypatch.setattr(wdr, "_connect", _slow_connect)

    wdr.schedule_workflow_resume(run_id=run_id, db_path=db_path)
    await asyncio.sleep(0.03)
    drained = await wdr.drain_pending_resume_cleanups(timeout=3.0)
    assert drained >= 1

    with orig_connect(db_path) as con:
        status = con.execute(
            "SELECT status FROM workflow_runs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    assert status == "failed"


@pytest.mark.asyncio
async def test_v06_p0_timeout_path_still_records_failed_cancels(monkeypatch):
    """RT1/1B: wait_for-Timeout verwirft gather-Results; beendete Tasks duerfen nicht still verschwinden."""
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "1")
    bl._BACKGROUND_TASKS.clear()
    bl._FAILED_CANCELS.clear()

    async def _crash_on_cancel(msg: str) -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise ValueError(msg)

    t1 = asyncio.create_task(_crash_on_cancel("t1_fail"), name="bg_task_1")
    t2 = asyncio.create_task(_crash_on_cancel("t2_fail"), name="bg_task_2")
    bl._BACKGROUND_TASKS.extend([t1, t2])
    await asyncio.sleep(0.01)

    deps = SimpleNamespace(
        get_rag_sync_process=lambda: None,
        set_rag_sync_process=lambda _v: None,
    )
    monkeypatch.setattr(bl, "_resolve_deps", lambda: deps)
    monkeypatch.setattr(
        audit_mod.chained_audit_log,
        "record_event",
        lambda **_kw: (_ for _ in ()).throw(OSError("audit db down")),
    )

    async def _timeout_wait_for(aw, timeout=None):
        aw.cancel()
        try:
            await aw
        except BaseException:
            pass
        await asyncio.sleep(0.02)  # cancelled Children finish their raise
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _timeout_wait_for)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        await bl._cancel_background_tasks()

    names = [entry["task"] for entry in bl._FAILED_CANCELS]
    assert "bg_task_1" in names
    assert "bg_task_2" in names
    assert bl._BACKGROUND_TASKS == []
