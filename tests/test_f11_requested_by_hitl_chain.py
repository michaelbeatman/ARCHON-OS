"""F11 (D04): requested_by-Kette am Tool-Chokepoint (HITL funktional, ohne Actor fail-closed)."""
from __future__ import annotations

import uuid

import pytest

from backend.session_taint_guard import mark_session_tainted, resolve_taint_approval
from backend.tool_runtime import enforce_tool_execution
from backend.tool_warrants import issue_warrant


def test_f11_tainted_tool_call_creates_pending_approval_with_actor_and_denies_without(monkeypatch):
    """Positiv- + Negativprobe fuer die gesamte requested_by-Kette durch enforce_tool_execution."""
    monkeypatch.setenv("ARCHON_WARRANT_SECRET", "f11-warrant-hmac-key")
    session_id = f"user:alice-{uuid.uuid4().hex[:8]}"
    tool_name = "mcp__mail__send"
    args = {"to": "partner@example.org", "subject": "Status"}

    # Session kontaminieren (M89) und gueltiges M90-Warrant ausstellen
    mark_session_tainted(session_id, source="external_web_read")
    warrant = issue_warrant(
        session_id=session_id,
        allowed_tools=[tool_name],
        ttl_seconds=300,
    )

    # 1. Negativprobe: ohne requested_by -> hart blockiert, KEINE pending-Freigabe angelegt
    denied_no_actor = enforce_tool_execution(
        agent_id=session_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        warrant=warrant,
    )
    assert denied_no_actor["allowed"] is False
    assert not denied_no_actor.get("approval_id")

    # 2. Positivprobe: mit verifiziertem requested_by -> pending-Freigabe angelegt
    pending = enforce_tool_execution(
        agent_id=session_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        warrant=warrant,
        requested_by="alice",
    )
    assert pending["allowed"] is False
    approval_id = pending.get("approval_id")
    assert approval_id, f"Erwartete approval_id im pending-Gate, erhalten: {pending}"

    # 3. 4-Augen-Negativprobe: Selbstfreigabe durch alice schlaegt fehl (PermissionError)
    with pytest.raises(PermissionError):
        resolve_taint_approval(approval_id, approved=True, reviewer="alice")

    # 4. Zweite Person (bob) gibt mit Passkey-Proof frei -> erneuter Aufruf erlaubt
    import backend.passkey_hitl as passkey_hitl

    monkeypatch.setattr(
        passkey_hitl,
        "consume_hitl_proof_token",
        lambda token, reviewer, *_a, **_kw: token == "valid-bob-proof" and reviewer == "bob",
    )
    second_res = resolve_taint_approval(
        approval_id, approved=True, reviewer="bob", passkey_proof="valid-bob-proof"
    )
    assert second_res is not None
    assert second_res.get("status") == "approved"

    allowed = enforce_tool_execution(
        agent_id=session_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
        requested_by="alice",
    )
    assert allowed["allowed"] is True
