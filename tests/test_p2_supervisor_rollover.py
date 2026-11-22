"""Regressionstests: Supervisor-Rollover aus der Org-Hierarchie."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_escalation_chain_walks_to_apex():
    from backend.supervisor_rollover import escalation_chain

    chain = escalation_chain("senior_fullstack_engineer")
    assert chain[0] == "system_architect_orchestrator"
    assert "executive_decision_architect" in chain


def test_p2_rollover_skips_failed_supervisor():
    from backend.supervisor_rollover import (
        clear_state, failed_agents, mark_agent_recovered,
        on_supervisor_failure, resolve_supervisor,
    )

    clear_state()
    try:
        before = resolve_supervisor("senior_fullstack_engineer")
        assert before == "system_architect_orchestrator"

        result = on_supervisor_failure(
            "senior_fullstack_engineer", before, reason="heartbeat_TIMEOUT"
        )
        assert result["failed_supervisor"] == before
        assert result["new_supervisor"] != before
        assert result["chain"]
        assert failed_agents().get(before) == "heartbeat_TIMEOUT"

        mark_agent_recovered(before)
        assert resolve_supervisor("senior_fullstack_engineer") == before
    finally:
        clear_state()
