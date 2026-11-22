"""Regressionstests fuer den Durable Execution Kernel."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_kernel_cas_claim_and_fencing(tmp_path):
    from backend.durable_execution_kernel import (
        DurableExecutionKernel, COMPLETED, PENDING, RUNNING,
        InvalidTransitionError, StaleFencingTokenError,
    )

    kernel = DurableExecutionKernel(db_path=str(tmp_path / "durable.db"))
    claim = kernel.claim("run-1", ttl_seconds=300, dag_fingerprint="{}")
    assert claim["claimed"] is True
    token = claim["fencing_token"]

    # Ein zweiter Worker darf denselben Run nicht gleichzeitig claimen.
    assert kernel.claim("run-1")["claimed"] is False

    # Ungueltige Transition (RUNNING -> PENDING) wird hart abgelehnt.
    with pytest.raises(InvalidTransitionError):
        kernel.transition("run-1", PENDING, token)

    # Veralteter Token darf nichts schreiben.
    with pytest.raises(StaleFencingTokenError):
        kernel.append_command("run-1", "node_done", {"n": 1}, "stale-token")
    with pytest.raises(StaleFencingTokenError):
        kernel.transition("run-1", COMPLETED, "stale-token")

    # Command-Log + Checkpoint + gueltige Transition.
    kernel.append_command("run-1", "node_started", {"node": "n1"}, token)
    kernel.checkpoint("run-1", 1, {"result": "ok"}, token)
    assert kernel.transition("run-1", COMPLETED, token)["to"] == COMPLETED

    state = kernel.get_state("run-1")
    assert state["state"] == COMPLETED
    assert state["state_data"] == {"result": "ok"}
    assert state["checkpoint_step"] == 1

    commands = kernel.command_log("run-1")
    types = [c["command_type"] for c in commands]
    assert "node_started" in types
    assert "checkpoint" in types
    assert "state_transition" in types
    assert [c["seq"] for c in commands] == sorted(c["seq"] for c in commands)


def test_kernel_renew_and_lease_expiry(tmp_path):
    from backend.durable_execution_kernel import DurableExecutionKernel, RUNNING

    kernel = DurableExecutionKernel(db_path=str(tmp_path / "lease.db"))
    claim = kernel.claim("run-2", ttl_seconds=30)
    token = claim["fencing_token"]
    assert kernel.renew("run-2", token, ttl_seconds=300) is True

    state = kernel.get_state("run-2")
    assert state["state"] == RUNNING
    assert state["claim_expires"] > claim["expires_at"]


def test_resume_wires_durable_kernel():
    src = (REPO_ROOT / "backend/workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "from backend.durable_execution_kernel import durable_kernel" in src
    assert "kernel.claim(" in src
    assert "kernel.transition(" in src
