# -*- coding: utf-8 -*-
"""W5-Koordinator-Nachverdrahtung: D10-M8, D16-M3, D16-M4.

Kein Replay, keine PostgreSQL-Migration. DB-Isolation via conftest.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ---------------------------------------------------------------------------
# D10-M8 — Zero-Egress-Netz hart an /readyz melden
# ---------------------------------------------------------------------------


def test_ensure_worker_network_fails_closed_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.llm_egress_guard as guard

    monkeypatch.setattr(
        guard, "inspect_worker_network_isolation",
        lambda _name: {"exists": False, "internal_no_internet_route": False},
    )
    with pytest.raises(RuntimeError, match="worker_zero_egress_network_unavailable"):
        guard.ensure_worker_zero_egress_network("archon-worker-zero-egress_net")


def test_ensure_worker_network_fails_closed_when_not_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.llm_egress_guard as guard

    monkeypatch.setattr(
        guard, "inspect_worker_network_isolation",
        lambda _name: {"exists": True, "internal_no_internet_route": False},
    )
    with pytest.raises(RuntimeError, match="worker_zero_egress_network_not_internal"):
        guard.ensure_worker_zero_egress_network("archon-sandbox_net")


def test_readyz_reports_failed_zero_egress_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.services.health_probes as probes
    import archon.services.shutdown_clients as clients

    monkeypatch.setitem(
        clients._ZERO_EGRESS_NETWORK_STATUS,
        "status", "failed",
    )
    monkeypatch.setitem(
        clients._ZERO_EGRESS_NETWORK_STATUS,
        "detail", "RuntimeError: network unavailable",
    )
    monkeypatch.setattr(probes, "_READINESS_PROBE_READY", {"ok": True})

    class _Conn:
        def __enter__(self) -> "_Conn":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, *_args: object) -> None:
            return None

    def _get_state_db() -> _Conn:
        return _Conn()

    problems = probes.run_readiness_sync_checks(_get_state_db)
    assert any("zero_egress_worker_net" in p for p in problems), problems


# ---------------------------------------------------------------------------
# D16-M3 — span_id im LLM-Audit und im Dispatcher-Hop
# ---------------------------------------------------------------------------


def test_log_completed_llm_dispatch_passes_explicit_span_id() -> None:
    from backend.llm_egress_guard import log_completed_llm_dispatch

    captured: dict[str, Any] = {}

    class _Audit:
        def record_llm_dispatch(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"id": "evt"}

    log_completed_llm_dispatch(
        agent_id="a", provider="p", model="m", target_endpoint="http://localhost",
        trace_id="a" * 32, span_id="b" * 16, audit_logger=_Audit(),
    )
    assert captured["span_id"] == "b" * 16


def test_dispatcher_audits_carry_hop_span_id() -> None:
    src = (Path(REPO_ROOT) / "core_dispatcher.py").read_text(encoding="utf-8")
    assert "active_span_id = current_span_id()" in src
    assert src.count("span_id=active_span_id") >= 2
