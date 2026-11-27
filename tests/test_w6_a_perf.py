# -*- coding: utf-8 -*-
"""W6-A (Performance) — D08-H1 Regressionstests.

D08-H1 (HIGH 8): Die synchrone Idempotency-Pruefung (SQLite, timeout=15)
im ``async``-DAG-Retry blockierte den Event-Loop. Der Fix legt Claim und
Record hinter eine Thread-Grenze (``asyncio.to_thread``) und sichert den
Abschluss im ``finally`` mit ``asyncio.shield`` gegen Cancel/Timeout.

Alle Tests laufen durch den PRODUKTIVPFAD ``_exec_with_retry_and_timeout``
(inkl. echtem Retry-Pfad); nur der Idempotency-Guard wird gemockt.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from backend.workflow_dag_runner import _exec_with_retry_and_timeout

_IDEM_KEY = "w6a-idem-key"
_GUARD = "backend.idempotency_guard.idempotency_guard"
_AUDIT = "backend.workflow_dag_runner._recovery_audit"


async def _ok_executor(node: Dict[str, Any], _upstream: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "success", "content": "ok", "node_id": node.get("id")}


def _node(max_retries: int = 0) -> Dict[str, Any]:
    return {"id": "w6a-node", "max_retries": max_retries}


# ---------------------------------------------------------------------------
# D08-H1 — Thread-Grenze: Claim/Record laufen nicht im Event-Loop
# ---------------------------------------------------------------------------


async def test_d08_h1_idempotency_io_runs_off_loop_and_retry_path_survives():
    """Echter Retry-Pfad: 2 Claims + 1 Record, alle im Worker-Thread.

    Der Guard blockiert waehrend des Claims auf einem threading.Event. Ein
    Heartbeat im Event-Loop muss waehrenddessen weiter ticken (Proxy fuer
    /livez und den SSE-Bus). Ein Watchdog-Thread gibt den Guard frei, damit
    der Test auch bei regressive Code nicht haengen bleibt.
    """
    main_thread = threading.current_thread()
    guard_threads: List[threading.Thread] = []
    checks: List[int] = []
    records: List[Dict[str, Any]] = []
    check_entered = threading.Event()
    check_release = threading.Event()
    ticks = 0
    stop_ticks = threading.Event()

    def _check(scope: str, params: Dict[str, Any], explicit_key: str | None = None) -> Dict[str, Any]:
        guard_threads.append(threading.current_thread())
        checks.append(int(params.get("attempt", -1)))
        check_entered.set()
        assert check_release.wait(timeout=3.0), "Claim-Release nicht gesetzt"
        return {"blocked": False}

    def _record(key: str, result: Dict[str, Any]) -> bool:
        guard_threads.append(threading.current_thread())
        records.append({"key": key, "result": result})
        return True

    attempts = 0

    async def _flaky_executor(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"status": "error", "error": "transient", "node_id": node.get("id")}
        return await _ok_executor(node, upstream)

    def _release_watchdog() -> None:
        time.sleep(0.4)
        check_release.set()

    watchdog = threading.Thread(target=_release_watchdog, daemon=True)
    watchdog.start()
    try:
        guard = MagicMock()
        guard.check_or_register.side_effect = _check
        guard.record_execution_result.side_effect = _record
        with patch(_GUARD, guard), patch(_AUDIT):
            runner = asyncio.create_task(_exec_with_retry_and_timeout(
                _flaky_executor, _node(max_retries=1), {}, idempotency_key=_IDEM_KEY
            ))
            await asyncio.to_thread(check_entered.wait, 3.0)
            assert check_entered.is_set(), "Idempotency-Claim wurde nicht erreicht"

            # Event-Loop muss waehrend des blockierten Claims responsiv bleiben.
            # Der Watchdog gibt den Claim erst nach 0.4 s frei — der Heartbeat
            # muss also innerhalb von 0.25 s deutlich weiterlaufen.
            async def _heartbeat() -> None:
                nonlocal ticks
                deadline = time.monotonic() + 0.25
                while not stop_ticks.is_set() and time.monotonic() < deadline:
                    ticks += 1
                    await asyncio.sleep(0.002)

            await asyncio.wait_for(_heartbeat(), timeout=1.0)
            stop_ticks.set()
            out = await asyncio.wait_for(runner, timeout=6.0)
    finally:
        stop_ticks.set()
        check_release.set()

    assert ticks >= 3, f"Event-Loop war waehrend des Claims blockiert (ticks={ticks})"
    assert guard_threads, "Guard wurde nicht aufgerufen"
    assert all(t is not main_thread for t in guard_threads), (
        "Idempotency-IO lief im Event-Loop statt im Worker-Thread"
    )
    assert checks == [0, 1], f"Retry-Claims fehlen: {checks}"
    assert len(records) == 1 and records[0]["key"] == _IDEM_KEY
    assert attempts == 2
    assert out["status"] == "success"


# ---------------------------------------------------------------------------
# D08-H1 — shield im finally: Cancel verliert den Claim nicht
# ---------------------------------------------------------------------------


async def test_d08_h1_cancel_during_record_still_finalizes_claim():
    """Cancel waehrend des Records: Shield im finally schreibt ihn zu Ende."""
    guard = MagicMock()
    guard.check_or_register.return_value = {"blocked": False}
    record_entered = threading.Event()
    record_release = threading.Event()
    recorded: List[Dict[str, Any]] = []

    def _record(key: str, result: Dict[str, Any]) -> bool:
        recorded.append({"key": key, "result": result})
        record_entered.set()
        assert record_release.wait(timeout=3.0), "Record-Release nicht gesetzt"
        return True

    guard.record_execution_result.side_effect = _record
    with patch(_GUARD, guard), patch(_AUDIT):
        runner = asyncio.create_task(_exec_with_retry_and_timeout(
            _ok_executor, _node(), {}, idempotency_key=_IDEM_KEY
        ))
        await asyncio.to_thread(record_entered.wait, 3.0)
        assert record_entered.is_set(), "Record wurde nicht erreicht"

        runner.cancel()
        await asyncio.sleep(0)  # CancelledError zustellen lassen
        record_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(runner, timeout=3.0)

    assert len(recorded) == 1, "Idempotency-Record ging beim Cancel verloren"
    assert recorded[0]["key"] == _IDEM_KEY
    assert recorded[0]["result"]["status"] == "success"


async def test_d08_h1_cancel_during_check_keeps_claim_and_blocks_executor():
    """Cancel waehrend des Claims: Claim wird registriert, Executor startet nicht."""
    guard = MagicMock()
    check_entered = threading.Event()
    check_release = threading.Event()
    checks: List[str] = []
    called: List[str] = []

    def _check(scope: str, params: Dict[str, Any], explicit_key: str | None = None) -> Dict[str, Any]:
        checks.append(str(explicit_key))
        check_entered.set()
        assert check_release.wait(timeout=3.0), "Claim-Release nicht gesetzt"
        return {"blocked": False}

    guard.check_or_register.side_effect = _check

    async def _exec(node: Dict[str, Any], _upstream: Dict[str, Any]) -> Dict[str, Any]:
        called.append(node["id"])
        return await _ok_executor(node, _upstream)

    with patch(_GUARD, guard), patch(_AUDIT):
        runner = asyncio.create_task(_exec_with_retry_and_timeout(
            _exec, _node(), {}, idempotency_key=_IDEM_KEY
        ))
        await asyncio.to_thread(check_entered.wait, 3.0)
        assert check_entered.is_set(), "Claim wurde nicht erreicht"

        runner.cancel()
        await asyncio.sleep(0)
        check_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(runner, timeout=3.0)

    assert checks == [_IDEM_KEY], "Claim wurde beim Cancel nicht zu Ende gefuehrt"
    assert called == [], "Executor lief trotz abgebrochenem Claim (fail-open)"


# ---------------------------------------------------------------------------
# D08-H1 — Fail-Closed-Vertrag aus D07-M4 bleibt durch die Thread-Grenze intakt
# ---------------------------------------------------------------------------


async def test_d08_h1_check_error_blocks_without_executor():
    called: List[str] = []
    guard = MagicMock()
    guard.check_or_register.side_effect = RuntimeError("Idempotency-DB gesperrt")

    async def _exec(node: Dict[str, Any], _upstream: Dict[str, Any]) -> Dict[str, Any]:
        called.append(node["id"])
        return await _ok_executor(node, _upstream)

    with patch(_GUARD, guard), patch(_AUDIT):
        out = await _exec_with_retry_and_timeout(
            _exec, _node(), {}, idempotency_key=_IDEM_KEY
        )

    assert called == [], "Executor lief ohne erfolgreichen Claim"
    assert out["error"] == "IDEMPOTENCY_UNAVAILABLE"
    assert out["needs_human"] is True


async def test_d08_h1_record_error_marks_node_error():
    guard = MagicMock()
    guard.check_or_register.return_value = {"blocked": False}
    guard.record_execution_result.side_effect = RuntimeError("Idempotency-DB gesperrt")
    with patch(_GUARD, guard), patch(_AUDIT):
        out = await _exec_with_retry_and_timeout(
            _ok_executor, _node(), {}, idempotency_key=_IDEM_KEY
        )

    assert out["status"] == "error"
    assert out["error"] == "IDEMPOTENCY_RECORD_FAILED"
    assert out["needs_human"] is True


# ---------------------------------------------------------------------------
# W5-Erbe: Zero-Egress-Readyz-Check in health_probes.py darf nicht verloren gehen
# ---------------------------------------------------------------------------


def test_w6_a_zero_egress_readyz_check_preserved(monkeypatch: Any) -> None:
    import archon.services.health_probes as hp
    import archon.services.shutdown_clients as sc

    class _Conn:
        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def __enter__(self) -> "_Conn":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    monkeypatch.setattr(hp, "_READINESS_PROBE_READY", {"ok": True}, raising=False)
    monkeypatch.setattr(
        sc, "_ZERO_EGRESS_NETWORK_STATUS",
        {"status": "failed", "detail": "NETWORKS=0"},
        raising=False,
    )
    monkeypatch.setattr(
        "backend.config_validator.validator.validate_all",
        lambda *_a, **_k: {"valid": True},
    )
    monkeypatch.setattr("backend.process_lock.get_loop_lock_failures", lambda: [])

    problems = hp.run_readiness_sync_checks(lambda: _Conn())
    assert any("zero_egress_worker_net" in p for p in problems), (
        "W5-Zero-Egress-Check fehlt in /readyz"
    )
