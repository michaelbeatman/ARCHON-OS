# -*- coding: utf-8 -*-
"""M111 — Isolation & Resilience.

Prueft die drei Sulen: Bulkheads mit echter Ueberlast-Ablehnung, harte
Tool-Output-Caps vor der Kontext-Injektion und den Provider-Circuit-Breaker
inkl. Fallback-Hierarchie/Backpressure. Zusaetzlich wird die M109-Key-Rotation
und die Fail-Closed-RBAC-Invariante abgesichert.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, cast

import pytest
from fastapi import HTTPException

from backend.provider_circuit_breaker import (
    DEFAULT_FALLBACK_CHAIN,
    BreakerState,
    ProviderCircuitBreaker,
    normalize_provider_name,
)
from backend.scheduling_bulkheads import (
    SCHEDULING_CLASSES,
    BulkheadConfig,
    BulkheadLease,
    SchedulingBulkhead,
    current_scheduling_class,
    set_scheduling_class,
)
from backend.tool_output_firewall import (
    TOOL_OUTPUT_CAPS,
    guard_tool_output_for_context,
    resolve_tool_output_cap,
)


@pytest.fixture(autouse=True)
def _deterministic_injection_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein echter LLM-Klassifikator in Firewall-Tests (deterministisch/schnell)."""
    import local_security_guard

    def _clean(text: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "verdict": "safe",
            "is_safe": True,
            "source_id": str(kwargs.get("source_id") or ""),
            "llm_verdict": "safe",
            "llm_classification_executed": True,
        }

    monkeypatch.setattr(local_security_guard, "quarantine_external_text", _clean)


def _unit_bulkheads() -> SchedulingBulkhead:
    return SchedulingBulkhead(
        configs={cls: BulkheadConfig(capacity=1, max_queue=1) for cls in SCHEDULING_CLASSES}
    )


# ---------------------------------------------------------------------------
# 1 — Bulkheads: Kapazitaet und Queue pro Klasse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scheduling_class", list(SCHEDULING_CLASSES))
def test_capacity_overflow_rejects_only_its_own_class(scheduling_class: str) -> None:
    bulkhead = _unit_bulkheads()
    first = bulkhead.try_acquire(scheduling_class, "first")
    second = bulkhead.try_acquire(scheduling_class, "second")

    assert first.granted is True
    assert second.granted is False
    assert second.backpressure is True
    assert second.error_code == "BULKHEAD_CAPACITY_EXHAUSTED"
    assert second.retry_after_seconds > 0

    other = next(c for c in SCHEDULING_CLASSES if c != scheduling_class)
    assert bulkhead.try_acquire(other, "other").granted is True

    snap = bulkhead.snapshot()
    assert snap[scheduling_class]["active"] == 1
    assert snap[scheduling_class]["rejected"] == 1
    assert snap[scheduling_class]["backpressure_active"] is True

    first.release()
    first.release()  # idempotent
    assert bulkhead.try_acquire(scheduling_class, "third").granted is True


def test_async_queue_is_bounded_and_backpressures() -> None:
    async def _scenario() -> None:
        bulkhead = _unit_bulkheads()
        held = bulkhead.try_acquire("eval", "held")
        assert held.granted is True
        waiting = asyncio.create_task(bulkhead.acquire("eval", "waiting", wait_seconds=0.5))
        await asyncio.sleep(0)  # Waiter registrieren

        overflow = await bulkhead.acquire("eval", "overflow", wait_seconds=0.01)
        assert overflow.granted is False
        assert overflow.error_code == "BULKHEAD_QUEUE_FULL"
        assert overflow.backpressure is True

        held.release()
        granted = await waiting
        assert granted.granted is True
        granted.release()
        assert bulkhead.snapshot()["eval"]["active"] == 0

    asyncio.run(_scenario())


def test_queue_timeout_releases_waiter_without_slot_leak() -> None:
    async def _scenario() -> None:
        bulkhead = _unit_bulkheads()
        held = bulkhead.try_acquire("chat", "held")
        rejected = await bulkhead.acquire("chat", "timeout", wait_seconds=0.01)
        assert rejected.granted is False
        assert rejected.error_code == "BULKHEAD_QUEUE_TIMEOUT"
        snap = bulkhead.snapshot()["chat"]
        assert snap["queued"] == 0
        assert snap["timed_out"] == 1
        assert snap["active"] == 1
        held.release()
        assert bulkhead.snapshot()["chat"]["active"] == 0

    asyncio.run(_scenario())


def test_scheduling_class_context_is_task_local() -> None:
    assert set_scheduling_class("background_dag") == "background_dag"
    assert current_scheduling_class() == "background_dag"
    assert set_scheduling_class("chat") == "chat"
    assert current_scheduling_class() == "chat"


# ---------------------------------------------------------------------------
# 2 — Tool-Output-Caps vor der Kontext-Injektion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scheduling_class", list(SCHEDULING_CLASSES))
def test_output_cap_enforced_before_injection(scheduling_class: str) -> None:
    cap = resolve_tool_output_cap(scheduling_class)
    guarded = guard_tool_output_for_context(
        "web_fetch", "X" * (cap * 2), scheduling_class=scheduling_class,
    )
    assert guarded["status"] == "ok"
    assert guarded["truncated"] is True
    assert len(guarded["output"]) <= cap
    assert "TOOL-OUTPUT-CAP" in guarded["output"]
    assert guarded["output"].startswith("--- BEGIN UNTRUSTED TOOL OUTPUT ---")
    assert guarded["output"].endswith("--- END UNTRUSTED TOOL OUTPUT ---")
    assert guarded["security"]["output_cap_applied"] is True


def test_class_caps_are_configurable_and_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TOOL_OUTPUT_CAPS["eval"] < TOOL_OUTPUT_CAPS["chat"] < TOOL_OUTPUT_CAPS["background_dag"]
    monkeypatch.setenv("ARCHON_TOOL_OUTPUT_CAP_EVAL", "512")
    assert resolve_tool_output_cap("eval") == 512
    assert resolve_tool_output_cap("eval", max_chars=333) == 333


def test_audit_content_truncation_is_never_silent() -> None:
    cap = resolve_tool_output_cap("eval")
    raw = "audit_event: beleg-12345\n" + ("Y" * (cap * 2))
    guarded = guard_tool_output_for_context("audit_read", raw, scheduling_class="eval")
    assert len(guarded["output"]) <= cap
    assert guarded["audit_truncation_visible"] is True
    assert "AUDIT-INHALT AUSGELASSEN" in guarded["output"]
    assert guarded["audit_content_sha256_prefix"]
    assert guarded["security"]["audit_truncation_visible"] is True


# ---------------------------------------------------------------------------
# 3 — Circuit-Breaker: Zustandsmaschine, Fallback, Backpressure
# ---------------------------------------------------------------------------

def test_breaker_opens_probes_and_closes() -> None:
    breaker = ProviderCircuitBreaker(threshold=2, cooldown_seconds=0.05)
    assert breaker.allow("omniroute") is True
    breaker.record_failure("omniroute")
    assert breaker.state("omniroute") is BreakerState.CLOSED

    breaker.record_failure("omniroute")
    assert breaker.state("omniroute") is BreakerState.OPEN
    assert breaker.allow("omniroute") is False
    bp = breaker.backpressure("omniroute")
    assert bp["backpressure_active"] is True
    assert bp["state"] == "open"
    assert bp["retry_after_seconds"] > 0
    assert breaker.snapshot()["omniroute"]["state"] == "open"

    time.sleep(0.06)
    assert breaker.state("omniroute") is BreakerState.HALF_OPEN
    assert breaker.allow("omniroute") is True
    assert breaker.allow("omniroute") is False  # genau EIN Probe
    breaker.record_success("omniroute")
    assert breaker.state("omniroute") is BreakerState.CLOSED
    assert breaker.allow("omniroute") is True
    assert breaker.backpressure("omniroute")["backpressure_active"] is False


def test_failed_probe_reopens_breaker() -> None:
    breaker = ProviderCircuitBreaker(threshold=1, cooldown_seconds=0.01)
    breaker.record_failure("openrouter")
    time.sleep(0.02)
    assert breaker.allow("openrouter") is True
    breaker.record_failure("openrouter")
    assert breaker.state("openrouter") is BreakerState.OPEN


def test_fallback_hierarchy_skips_open_providers() -> None:
    breaker = ProviderCircuitBreaker(threshold=1, cooldown_seconds=30.0)
    assert normalize_provider_name("Ollama") == "local"

    chosen, plan = breaker.select_provider("omniroute")
    assert chosen == "omniroute"
    assert tuple(plan["chain"]) == DEFAULT_FALLBACK_CHAIN

    breaker.record_failure("omniroute")
    chosen, plan = breaker.select_provider("omniroute")
    assert chosen == "openrouter"
    assert plan["skipped"][0]["provider"] == "omniroute"

    breaker.record_failure("openrouter")
    chosen, plan = breaker.select_provider("omniroute")
    assert chosen == "local"

    breaker.record_failure("local")
    chosen, plan = breaker.select_provider("omniroute")
    assert chosen is None
    assert plan["backpressure_active"] is True
    assert len(plan["skipped"]) == 3
    assert plan["retry_after_seconds"] > 0


def test_readonly_fallback_plan_does_not_consume_probe() -> None:
    breaker = ProviderCircuitBreaker(threshold=1, cooldown_seconds=0.01)
    breaker.record_failure("omniroute")
    time.sleep(0.02)
    assert breaker.state("omniroute") is BreakerState.HALF_OPEN

    chosen, _ = breaker.select_provider("omniroute")
    assert chosen == "openrouter"  # HALF_OPEN wird im read-only Plan uebergangen
    assert breaker.state("omniroute") is BreakerState.HALF_OPEN
    assert breaker.allow("omniroute") is True  # Probe ist noch frei


# ---------------------------------------------------------------------------
# 4 — Dispatcher-Hooks, M109-Invariante, RBAC
# ---------------------------------------------------------------------------

def test_dispatcher_rejects_on_bulkhead_backpressure(monkeypatch: pytest.MonkeyPatch) -> None:
    import core_dispatcher
    from backend import scheduling_bulkheads as sb

    class _Rejecting:
        async def acquire(self, scheduling_class: str, owner_id: str = "") -> BulkheadLease:
            return BulkheadLease(
                scheduling_class=sb.normalize_scheduling_class(scheduling_class),
                owner_id=owner_id,
                granted=False,
                error_code="BULKHEAD_CAPACITY_EXHAUSTED",
                detail="test-overload",
                backpressure=True,
                retry_after_seconds=0.25,
            )

        def release(self, lease: BulkheadLease) -> None:
            return None

    monkeypatch.setattr(sb, "scheduling_bulkheads", _Rejecting())
    res = asyncio.run(core_dispatcher.dispatch_to_omniroute_or_container(
        agent_id="m111-agent", agent_name="M111", prompt="Hallo", task_id="m111-reject",
    ))
    assert res["status"] == "blocked"
    assert res["error_code"] == "BULKHEAD_CAPACITY_EXHAUSTED"
    assert res["backpressure"] is True
    assert res["retry_after_seconds"] == 0.25


def test_dispatcher_releases_bulkhead_slot_on_early_block(monkeypatch: pytest.MonkeyPatch) -> None:
    import core_dispatcher
    from backend import scheduling_bulkheads as sb

    real = _unit_bulkheads()

    class _Counting:
        def __init__(self) -> None:
            self.released = 0

        async def acquire(self, scheduling_class: str, owner_id: str = "") -> BulkheadLease:
            return real.try_acquire(scheduling_class, owner_id)

        def release(self, lease: BulkheadLease) -> None:
            self.released += 1
            real.release(lease)

    stub = _Counting()
    monkeypatch.setattr(sb, "scheduling_bulkheads", stub)

    def _deny_budget(**kwargs: Any) -> Dict[str, Any]:
        return {"allowed": False, "error_code": "ROLE_BUDGET_EXCEEDED", "reason": "m111-test"}

    monkeypatch.setattr("backend.role_budget_engine.budget_bank.reserve", _deny_budget)
    res = asyncio.run(core_dispatcher.dispatch_to_omniroute_or_container(
        agent_id="m111-agent", agent_name="M111", prompt="Hallo", task_id="m111-release",
    ))
    assert res["status"] == "blocked"
    assert res["error"] == "ROLE_BUDGET_EXCEEDED"
    assert stub.released == 1
    assert real.snapshot()["chat"]["active"] == 0


def test_m109_omniroute_key_hot_rotation_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    import core_dispatcher

    monkeypatch.setenv("OMNIROUTE_API_KEY", "m111_initial_123456")
    assert core_dispatcher.refresh_cached_provider_keys()["omniroute_key_present"] is True
    assert core_dispatcher._get_omniroute_api_key() == "m111_initial_123456"

    monkeypatch.setenv("OMNIROUTE_API_KEY", "m111_rotated_999999")
    core_dispatcher.refresh_cached_provider_keys()
    assert core_dispatcher.OMNIROUTE_API_KEY == "m111_rotated_999999"
    assert core_dispatcher._get_omniroute_api_key() == "m111_rotated_999999"

    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setattr("api_provider.collect_keys", lambda: {})
    assert core_dispatcher.refresh_cached_provider_keys()["omniroute_key_present"] is False
    assert core_dispatcher.OMNIROUTE_API_KEY == ""
    assert core_dispatcher._get_omniroute_api_key() == ""


def test_rbac_guards_stay_fail_closed() -> None:
    from backend import rbac_guards

    saved = dict(rbac_guards._GUARDS)
    try:
        for name in saved:
            rbac_guards._GUARDS[name] = None
        dummy = cast(Any, None)
        with pytest.raises(HTTPException) as admin_exc:
            rbac_guards.require_admin_or_503(dummy)
        assert admin_exc.value.status_code == 503
        with pytest.raises(HTTPException) as write_exc:
            rbac_guards.forbid_viewer_writes(dummy)
        assert write_exc.value.status_code == 503
        with pytest.raises(RuntimeError):
            rbac_guards.get_current_user_from_request(dummy)
    finally:
        rbac_guards._GUARDS.clear()
        rbac_guards._GUARDS.update(saved)
