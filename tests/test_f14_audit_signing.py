"""F14 (D05): tool.allowed und Shutdown-Cancel ueber _require_audit_event signieren."""
from __future__ import annotations

import uuid

import pytest

from archon.services import background_loops as bl
from backend.audit_log import chained_audit_log
from backend.tool_runtime import enforce_tool_execution
from backend.tool_warrants import issue_warrant


def test_f14_tool_allowed_is_signed_in_audit_chain_and_fails_closed_on_write_error(tmp_path, monkeypatch):
    """Positiv- + Negativprobe: tool.allowed erzeugt gueltigen Audit-Block; Write-Fehler blockiert."""
    import backend.audit_log as audit_mod

    monkeypatch.setenv("ARCHON_WARRANT_SECRET", "f14-warrant-secret")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "f14-audit-hmac-key")
    monkeypatch.setenv("ARCHON_ALLOW_INSECURE_AUDIT_DEV", "1")
    fresh_log = audit_mod.ChainedAuditLog(db_path=str(tmp_path / "f14_audit.db"))
    monkeypatch.setattr(audit_mod, "chained_audit_log", fresh_log)

    session_id = f"user:f14-{uuid.uuid4().hex[:8]}"
    tool_name = "mcp__mail__send"
    warrant = issue_warrant(session_id=session_id, allowed_tools=[tool_name], ttl_seconds=300)

    # 1. Positivprobe: erlaubter Tool-Call landet als `tool_allowed` in category='tool_runtime'
    res = enforce_tool_execution(
        agent_id=session_id,
        session_id=session_id,
        tool_name=tool_name,
        args={"q": "archon"},
        warrant=warrant,
        requested_by="f14-tester",
    )
    assert res["allowed"] is True, res
    res_events = fresh_log.list_events(category="tool_runtime", limit=50)
    events = res_events["entries"] if isinstance(res_events, dict) else res_events
    matched = [
        e for e in events
        if e.get("action") == "tool_allowed"
        and e.get("agent_id") == session_id
    ]
    assert matched, f"Kein signiertes tool_allowed-Event gefunden in: {events[:5]}"
    assert matched[0].get("current_hash")
    integrity = fresh_log.verify_integrity()
    assert integrity["valid"] is True, integrity

    # 2. Negativprobe: record_event wirft Fehler -> enforce_tool_execution gibt allowed=False zurueck
    def _boom(*_a, **_kw):
        raise RuntimeError("sqlite_readonly")

    monkeypatch.setattr(fresh_log, "record_event", _boom)
    blocked = enforce_tool_execution(
        agent_id=session_id,
        session_id=session_id,
        tool_name=tool_name,
        args={"q": "archon"},
        warrant=warrant,
        requested_by="f14-tester",
    )
    assert blocked["allowed"] is False
    assert blocked["gate"] == "audit_write_failed"


def test_f14_record_failed_cancel_sets_audit_status_and_raises_in_strict(monkeypatch):
    """Shutdown-Cancel-Audit markiert audit_status='ok'/'error' und eskaliert im Strict-Mode."""
    bl._FAILED_CANCELS.clear()

    # 1. Positivprobe: erfolgreiches Audit -> audit_status='ok'
    ok_entry = bl._record_failed_cancel("loop_demo", "timeout_after_cancel(10s)")
    assert ok_entry["audit_status"] == "ok"

    # 2. Negativprobe (Strict=0): audit_status='error', kein stilles 'ok'
    def _boom(*_a, **_kw):
        raise RuntimeError("disk_full")

    monkeypatch.setattr(chained_audit_log, "record_event", _boom)
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "0")
    err_entry = bl._record_failed_cancel("loop_demo_2", "timeout_after_cancel(10s)")
    assert err_entry["audit_status"] == "error"
    assert "audit_write_failed" in err_entry.get("audit_error", "")

    # 3. Negativprobe (Strict=1): wirft hart RuntimeError('audit_write_failed')
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "1")
    with pytest.raises(RuntimeError, match="audit_write_failed"):
        bl._record_failed_cancel("loop_demo_3", "timeout_after_cancel(10s)")
    assert bl._FAILED_CANCELS[-1]["audit_status"] == "error"
