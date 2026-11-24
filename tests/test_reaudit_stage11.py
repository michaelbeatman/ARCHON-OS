"""Re-Audit Etappe 11 — D13: Fan-out-Cap, Router-Hop, Replan-Setzer, Budget."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_d13_fanout_cap_wired_in_chat():
    src = (ROOT / "archon" / "routers" / "chat.py").read_text(encoding="utf-8")
    block = src.split("payloads, invalid_blocks = _parse_delegation_blocks(", 1)[1][:200]
    assert "fanout_cap=DEFAULT_MAX_DELEGATIONS_PER_RESPONSE" in block


def test_d13_router_hop_no_traj_prefix_gate():
    src = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    assert 'if str(task_id or "").startswith("traj-"):' not in src
    assert "normalize_trajectory_id(" in src
    assert "allow_repeat=True" in src
    assert "task_id=session_id" in (ROOT / "archon" / "routers" / "chat.py").read_text(encoding="utf-8")


def test_d13_reserve_hop_allow_repeat(tmp_path):
    from backend.trajectory_budget import normalize_trajectory_id, reserve_hop
    db = str(tmp_path / "t.db")
    tid = normalize_trajectory_id(None, root_ticket_id="ticket-hops")
    for _ in range(2):
        assert reserve_hop(tid, "coder", "llm_call:coder", db_path=db, allow_repeat=True)["allowed"]
    # Ohne allow_repeat ist die Wiederholung desselben Agenten ein Zyklus.
    assert reserve_hop(tid, "coder", "llm_call:coder", db_path=db)["reason"] == "CYCLE_DETECTED"


def test_d13_no_budget_minting():
    src = (ROOT / "archon" / "core" / "orchestration.py").read_text(encoding="utf-8")
    assert "* 60000" not in src
    assert '* 0.08' not in src
    assert "kein Budget-Minting" in src


def test_d13_max_hops_from_ticket_metadata():
    src = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    assert 'dag_def.get("max_hops")' in src
    assert "max_hops=(_max_hops_cfg or None)" in src
    assert "min(50" in src


def test_d13_replan_endpoint_wired():
    src = (ROOT / "archon" / "routers" / "execution.py").read_text(encoding="utf-8")
    assert '@router.post("/api/execution/dag/replan")' in src
    assert "request_dag_replan(" in src
