"""Regressionstests: Cancel-Token-Kette Mission Control → Dispatch → DAG → Boardroom."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_p2_boardroom_disconnect_cancels_dispatch():
    src = _src("archon/routers/boardroom.py")
    assert "from backend.cancellation import clear_scope, get_child_token" in src
    assert 'get_child_token("boardroom", f"boardroom:' in src
    assert "cancel_token=cancel_token" in src
    assert 'cancel_token.cancel("client_disconnect")' in src
    assert "clear_scope(cancel_token.scope)" in src


def test_p2_mission_control_cancel_endpoint_and_children():
    src = _src("archon/routers/mission_control.py")
    assert 'from backend.cancellation import cancel_scope, get_child_token, get_token' in src
    assert '@router.post("/api/mission-control/tasks/{task_id}/cancel")' in src
    assert 'cancel_scope(f"task:{task_id}", why)' in src
    assert 'get_child_token(f"task:{req.task_id}", f"dispatch:{req.task_id}")' in src
    assert 'get_child_token(f"task:{req.task_id}", f"run:{req.task_id}")' in src
    assert 'broadcast_event("task_cancelled"' in src


def test_p2_dag_runner_honours_cancel_token():
    src = _src("backend/workflow_dag_runner.py")
    assert "cancel_token: Optional[Any] = None" in src
    assert '_get_cancel_token(f"run:{rid}")' in src
    assert "cancel_token.check()" in src
    assert "_t.cancel()" in src


def test_p2_dispatch_checks_cancel_token_before_llm_call():
    src = _src("archon/core/orchestration.py")
    assert '_get_cancel_token(f"dispatch:{task_id}")' in src
    assert "# Echter LLM-Dispatch — vorher Cancel-Token pruefen." in src
    assert "cancel_token.check()" in src
