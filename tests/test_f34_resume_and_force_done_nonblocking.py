"""F34 (D08): DAG-Resume-Pfad und Force-done-Audit in asyncio.to_thread / run_in_executor."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import operations_kanban_crud as crud
from backend import workflow_dag_runner as dag_mod


def test_f34_force_done_audit_is_non_blocking_and_returns_503_on_audit_failure(monkeypatch):
    """Force-done ruft require_four_eyes_override & _require_audit_event in to_thread; Audit-Fehler -> 503."""
    import backend.audit_log as audit_mod

    def _slow_override(**_kw):
        time.sleep(0.15)
        return {"approval_id": "apr-f34"}

    def _slow_audit(*_a, **_kw):
        time.sleep(0.15)
        raise RuntimeError("audit_write_failed")

    fake_deps = SimpleNamespace(
        valid_kanban_statuses={"backlog", "in_progress", "review", "done"},
        current_quality_review=lambda _tid: {"verdict": "rejected"},
        task_created_by=lambda _tid: "creator_a",
        task_status=lambda _tid: "review",
        require_four_eyes_override=_slow_override,
        update_task_status_db=lambda *_a, **_kw: {},
    )
    monkeypatch.setattr(crud, "_deps", lambda: fake_deps)
    monkeypatch.setattr(audit_mod, "_require_audit_event", _slow_audit)

    req = crud.TaskStatusUpdateRequest(
        status="done",
        force=True,
        reason="emergency override",
        passkey_proof_token="tok",
        approval_id="apr-f34",
    )

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        async def _call_update():
            with pytest.raises(HTTPException) as exc_info:
                await crud.update_task_status_impl("t-f34", "admin_b", req)
            assert exc_info.value.status_code == 503

        await asyncio.gather(_call_update(), _heartbeat())
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

    asyncio.run(_run())


def test_f34_resume_suspended_is_non_blocking(monkeypatch, tmp_path):
    """resume_suspended_workflow_run lagert resume_context / DB-Read / resume_suspended in to_thread aus."""
    import backend.durable_execution_kernel as dek

    db_path = str(tmp_path / "dag_f34.db")
    with dag_mod._connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS workflow_node_states "
            "(run_id TEXT, node_id TEXT, status TEXT, output_json TEXT)"
        )
        conn.commit()

    def _slow_ctx(_rid):
        time.sleep(0.15)
        return {"state": dek.SUSPENDED, "fencing_token": "ft-1"}

    def _slow_resume(_rid, _ft):
        time.sleep(0.15)
        return {"resume_from_step": 1, "fencing_token": "ft-2"}

    async def _fake_resume_run(**_kw):
        return {"status": "completed", "outputs": {}}

    monkeypatch.setattr(dek.durable_kernel, "resume_context", _slow_ctx)
    monkeypatch.setattr(dek.durable_kernel, "resume_suspended", _slow_resume)
    monkeypatch.setattr(dag_mod, "resume_workflow_run", _fake_resume_run)

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        res, _ = await asyncio.gather(
            dag_mod.resume_suspended_workflow_run("run-f34", db_path=db_path),
            _heartbeat(),
        )
        assert res["status"] == "completed"
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

    asyncio.run(_run())
