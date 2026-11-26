"""F10c (D12): Silent-Failure-Guard fail-closed bei Audit-Schreibfehler."""
from __future__ import annotations

import pytest

import backend.audit_log as audit_mod
import backend.flightlog_backtester as fl_mod
import core_dispatcher


@pytest.mark.asyncio
async def test_f10c_silent_failure_guard_raises_on_audit_write_failure(monkeypatch):
    """Negativprobe: record_event wirft -> RuntimeError('audit_write_failed'), kein stilles Schlucken."""
    monkeypatch.setattr(
        fl_mod,
        "detect_silent_failures",
        lambda run_id, status, content: {
            "silent_failure": True,
            "flags": ["tool_loop:5"],
            "event_count": 5,
            "total_tokens": 900,
        },
    )
    monkeypatch.setattr(
        audit_mod.chained_audit_log,
        "record_event",
        lambda **_kw: (_ for _ in ()).throw(OSError("audit db locked")),
    )

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        await core_dispatcher._guard_silent_failures(
            {"status": "success", "content": "Alles erledigt"},
            agent_id="coder",
            task_id="task-f10c-neg",
        )


@pytest.mark.asyncio
async def test_f10c_silent_failure_guard_records_audit_and_blocks_on_success(monkeypatch):
    """Positivprobe: Audit-Write klappt -> Status blocked + signiertes Event protokolliert."""
    recorded = []

    monkeypatch.setattr(
        fl_mod,
        "detect_silent_failures",
        lambda run_id, status, content: {
            "silent_failure": True,
            "flags": ["token_spike:99999"],
            "event_count": 3,
            "total_tokens": 99999,
        },
    )
    monkeypatch.setattr(
        audit_mod.chained_audit_log,
        "record_event",
        lambda **kw: recorded.append(kw) or {"id": "evt-f10c-1"},
    )

    out = await core_dispatcher._guard_silent_failures(
        {"status": "success", "content": "Alles erledigt"},
        agent_id="coder",
        task_id="task-f10c-pos",
    )
    assert out["status"] == "blocked"
    assert out["error_code"] == "SILENT_FAILURE_DETECTED"
    assert len(recorded) == 1
    assert recorded[0]["category"] == "silent_failure"
    assert recorded[0]["action"] == "dispatch_blocked_by_silent_failure"
    assert recorded[0]["agent_id"] == "coder"
