"""Re-Audit Etappe 1 — Regressionstests fuer R-B2/R-B3/R-B4 und die CI-Gates."""
from __future__ import annotations

from pathlib import Path

import backend.flightlog_backtester as fb
import backend.trace_context as tc
from backend.tool_runtime import _record_tool_flight_event
from backend.trajectory_budget import _connect, close_trajectory, ensure_trajectory, record_tokens

ROOT = Path(__file__).resolve().parents[1]


def _state(db: str, tid: str) -> str:
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT state FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
    return str(row[0]) if row else ""


def test_rb3_close_trajectory_preserves_blocked(tmp_path):
    """ Ein geblocktes Trajectory darf beim Abschluss nicht auf completed gehoben werden. """
    db = str(tmp_path / "traj.db")
    tid = ensure_trajectory(max_hops=5, root_ticket_id="stage1-blocked", db_path=db)["trajectory_id"]
    res = record_tokens(tid, 10**9, reason="stage1", db_path=db)
    assert res["allowed"] is False
    assert _state(db, tid) == "blocked"

    closed = close_trajectory(tid, "completed", db_path=db)
    assert closed["state"] == "blocked"
    assert closed.get("preserved") is True
    assert _state(db, tid) == "blocked"


def test_rb3_close_trajectory_normal_completion_still_works(tmp_path):
    db = str(tmp_path / "traj.db")
    tid = ensure_trajectory(max_hops=5, root_ticket_id="stage1-ok", db_path=db)["trajectory_id"]
    assert close_trajectory(tid, "completed", db_path=db)["state"] == "completed"
    assert _state(db, tid) == "completed"


def test_rb4_flightlog_uses_explicit_run_id(monkeypatch):
    """ Der Produzent muss den expliziten run_id verwenden, nicht die HTTP-Trace-ID. """
    captured: dict[str, str] = {}

    def fake_record(**kwargs):
        captured["run_id"] = kwargs["run_id"]

    monkeypatch.setattr(fb, "record_flight_event", fake_record)
    monkeypatch.setattr(tc, "current_trace_id", lambda: "trace-1")

    _record_tool_flight_event(
        tool_name="terminal", args={}, agent_id="coder", session_id="other-session",
        status="success", result={}, flightlog_run_id="dag-run-1",
    )
    assert captured["run_id"] == "dag-run-1"

    _record_tool_flight_event(
        tool_name="terminal", args={}, agent_id="coder", session_id="chat-session",
        status="success", result={},
    )
    assert captured["run_id"] == "chat-session"


def test_rb2_cost_import_is_real():
    src = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    assert "estimate_model_cost_usd" in src
    assert "import estimate_cost_usd" not in src


def test_ci_has_no_continue_on_error():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # Nur echte YAML-Keys zaehlen, keine erklaerenden Kommentare.
    active = "\n".join(line for line in ci.splitlines() if not line.lstrip().startswith("#"))
    assert "continue-on-error:" not in active
