# -*- coding: utf-8 -*-
"""W3-A — Router/Dispatcher-Orchestrierung (D02-H1, D02-M2, D05-M1, D12-M6).

Alle Tests sind offline und deterministisch. Es werden keine echten LLM-,
n8n-, Docker- oder SQLite-Schreibpfade ausgeführt; betroffene Produzenten
werden gezielt gemockt. Ziel ist der Nachweis, dass Fehlerpfade nicht mehr
als Erfolg quittiert werden und beide Routing-Chokepoints dieselbe
Klassifikation verwenden.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import types

import pytest

import backend.agent_router as agent_router
import backend.execution_receipt_ledger as receipt_ledger
import backend.execution_routing_guard as guard
import backend.fleet_self_healing as fleet
import core_dispatcher as dispatcher


def _n8n(**kwargs):
    """Minimaler gemockter n8n-Produzent."""
    return {"status": "unconfirmed"}


# ---------------------------------------------------------------------------
# D02-H1 — n8n `unconfirmed`/`blocked` ist KEIN Erfolg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result, expected_code",
    [
        ({"status": "unconfirmed"}, "N8N_DELIVERY_UNCONFIRMED"),
        ({"status": "blocked", "error_code": "N8N_POLICY_BLOCK"}, "N8N_POLICY_BLOCK"),
        ({"status": "warning"}, "N8N_DELIVERY_UNCONFIRMED"),
        ({}, "N8N_DELIVERY_UNCONFIRMED"),
    ],
)
def test_n8n_unconfirmed_is_blocked(monkeypatch, result, expected_code):
    calls = {}

    def fake_trigger(**kwargs):
        calls.update(kwargs)
        return result

    monkeypatch.setattr(dispatcher, "trigger_n8n_execution", fake_trigger)
    messages = [{"role": "user", "content": "Gleiche Mails ab"}]

    verdict = asyncio.run(
        agent_router.AgentRouter()._check_deterministic_execution_layer(
            messages, "master_chat", "t-n8n"
        )
    )

    assert verdict is not None
    assert verdict["blocked"] is True
    assert verdict["error_code"] == expected_code
    assert "ausgeführt" not in str(verdict.get("text", ""))
    assert calls["target_action"] == "webhook_crm"


def test_n8n_confirmed_success_still_reports_execution(monkeypatch):
    monkeypatch.setattr(
        dispatcher,
        "trigger_n8n_execution",
        lambda **kwargs: {"status": "success", "execution_id": "exec-1"},
    )
    verdict = asyncio.run(
        agent_router.AgentRouter()._check_deterministic_execution_layer(
            [{"role": "user", "content": "Gleiche Mails ab"}], "master_chat", "t-n8n-ok"
        )
    )
    assert verdict["blocked"] is False  # type: ignore[index]
    assert "ausgeführt" in verdict["text"]  # type: ignore[index]


def test_stream_does_not_emit_success_text_for_unconfirmed_n8n(monkeypatch):
    monkeypatch.setattr(dispatcher, "trigger_n8n_execution", _n8n)

    async def collect():
        return [
            chunk
            async for chunk in agent_router.AgentRouter().stream_chat_completion(
                messages=[{"role": "user", "content": "Gleiche Mails ab"}],
                provider="unused",
                model="unused",
                api_keys={},
                task_id="t-n8n-stream",
            )
        ]

    chunks = asyncio.run(collect())
    assert len(chunks) == 1
    assert chunks[0].startswith("ERROR: ")
    assert "N8N_DELIVERY_UNCONFIRMED" in chunks[0]
    assert "ausgeführt" not in chunks[0]


def test_analysis_context_never_triggers_n8n(monkeypatch):
    called = []

    def fake_trigger(**kwargs):
        called.append(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(dispatcher, "trigger_n8n_execution", fake_trigger)
    verdict = asyncio.run(
        agent_router.AgentRouter()._check_deterministic_execution_layer(
            [{"role": "user", "content": "Analysiere die USt-Split-Logik"}],
            "master_chat",
            "t-analysis",
        )
    )
    assert verdict is None  # probabilistischer Agent, kein 0-Token-Pfad
    assert called == []


# ---------------------------------------------------------------------------
# D02-M2 — EIN kanonischer Klassifikations-Chokepoint
# ---------------------------------------------------------------------------


def test_messages_and_prompt_produce_same_decision():
    messages = [
        {"role": "system", "content": "Du bist Archon."},
        {"role": "user", "content": "Gleiche Mails ab"},
    ]
    prompt = "Du bist Archon.\nGleiche Mails ab"
    from_messages = guard.classify_execution_request(messages=messages)
    from_prompt = guard.classify_execution_request(prompt=prompt)
    assert (from_messages["layer"], from_messages["rule_id"]) == (
        from_prompt["layer"],
        from_prompt["rule_id"],
    )
    assert from_messages["layer"] == "deterministic_n8n"


def test_directive_in_older_message_is_not_lost():
    messages = [{"role": "user", "content": "Gleiche Mails ab"}]
    messages += [
        {"role": "user", "content": f"Zwischenfrage {i}"} for i in range(8)
    ]
    verdict = guard.classify_execution_request(messages=messages)
    assert verdict["layer"] == "deterministic_n8n"
    assert verdict["rule_id"] == "det_n8n_email_crm_sync"


@pytest.mark.parametrize(
    "text",
    [
        "Analysiere die USt-Split-Logik",
        "Beschreibe den Docker Backup-Prozess",
        "Erkläre den USt-Split",
        "Interpretiere den RSS-Scan",
    ],
)
def test_analysis_context_overrides_deterministic_keyword(text):
    verdict = guard.classify_execution_request(prompt=text)
    assert verdict["layer"] == "probabilistic_agent"


def test_explicit_directive_wins_over_analysis_context():
    verdict = guard.classify_execution_request(
        prompt="Analysiere kurz die Lage. ACTION: WEBHOOK_CRM"
    )
    assert verdict["rule_id"] == "explicit_n8n_directive"


def test_router_uses_canonical_helper(monkeypatch):
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return {"layer": "probabilistic_agent", "rule_id": "default_probabilistic_agent"}

    monkeypatch.setattr(guard, "classify_execution_request", spy)
    messages = [{"role": "user", "content": "irgendein Auftrag"}]
    verdict = asyncio.run(
        agent_router.AgentRouter()._check_deterministic_execution_layer(
            messages, "master_chat", "t-helper"
        )
    )
    assert verdict is None
    assert seen["messages"] == messages


def test_both_chokepoints_reference_the_canonical_helper():
    router_src = inspect.getsource(
        agent_router.AgentRouter._check_deterministic_execution_layer
    )
    # Der Dispatcher delegiert an _dispatch_to_omniroute_or_container_impl;
    # der kanonische Helper wird in dieser Implementierung aufgerufen.
    dispatcher_src = inspect.getsource(
        dispatcher._dispatch_to_omniroute_or_container_impl
    )
    for source in (router_src, dispatcher_src):
        assert "classify_execution_request" in source
        assert "classify_execution_layer(" not in source
        assert "[:160]" not in source


# ---------------------------------------------------------------------------
# D05-M1 — Audit-/Receipt-Schreibfehler nie als Erfolg quittieren
# ---------------------------------------------------------------------------


def _break_receipt(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("receipt db unavailable")

    monkeypatch.setattr(
        receipt_ledger.execution_receipt_ledger, "issue_receipt", boom
    )


def test_receipt_failure_is_hard_error_when_strict(monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "1")
    _break_receipt(monkeypatch)
    with pytest.raises(RuntimeError, match="audit_write_failed"):
        agent_router._issue_execution_receipt(task_id="t-audit", tools_invoked=[])


def test_receipt_failure_opt_out_stays_visible(monkeypatch, caplog):
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "0")
    _break_receipt(monkeypatch)
    with caplog.at_level("ERROR", logger="agent_router"):
        agent_router._issue_execution_receipt(task_id="t-audit-optout", tools_invoked=[])
    assert "fehlgeschlagen" in caplog.text


def test_fleet_audit_failure_blocks_success(monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "1")
    monkeypatch.setattr(fleet, "resolve_container_target", lambda name: "fake-n8n")

    class FakeDockerClient:
        def restart_container(self, target):
            return {"status": "ok"}

    monkeypatch.setattr(fleet, "_docker_client", lambda: FakeDockerClient())

    import backend.audit_log as audit_log

    def boom(**kwargs):
        raise RuntimeError("audit db unavailable")

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", boom)

    # Kein echter Notification-Hub im Test.
    hub_module = types.ModuleType("backend.notification_hub")

    class FakeHub:
        def dispatch_notification(self, **kwargs):
            return None

    hub_module.notification_hub = FakeHub()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backend.notification_hub", hub_module)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        fleet.restart_service_container("n8n")


def test_fleet_audit_failure_is_flagged_when_not_strict(monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "0")
    monkeypatch.setattr(fleet, "resolve_container_target", lambda name: "fake-n8n")

    class FakeDockerClient:
        def restart_container(self, target):
            return {"status": "ok"}

    monkeypatch.setattr(fleet, "_docker_client", lambda: FakeDockerClient())

    import backend.audit_log as audit_log

    def boom(**kwargs):
        raise RuntimeError("audit db unavailable")

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", boom)

    hub_module = types.ModuleType("backend.notification_hub")

    class FakeHub:
        def dispatch_notification(self, **kwargs):
            return None

    hub_module.notification_hub = FakeHub()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backend.notification_hub", hub_module)

    result = fleet.restart_service_container("n8n")
    assert result["audit_write_failed"] is True
    assert result["audit_status"] == "error"


# ---------------------------------------------------------------------------
# D12-M6 — Budget-Settlement-/Semantic-Cache-Fehler sichtbar machen
# ---------------------------------------------------------------------------


def test_budget_settlement_failure_marks_dispatch_as_error(monkeypatch):
    audit_calls = []
    monkeypatch.setattr(
        dispatcher,
        "_audit_dispatch_failure",
        lambda action, detail, **extra: audit_calls.append((action, extra)),
    )
    result = {"status": "success", "content": "Antwort"}
    dispatcher._mark_budget_settlement_failed(
        result, RuntimeError("settle db down"), agent_id="test-agent"
    )
    assert result["status"] == "error"
    assert result["error_code"] == "BUDGET_SETTLEMENT_FAILED"
    assert result["budget_status"] == "paused_budget"
    assert "settle db down" in result["error"]
    assert audit_calls[0][0] == "budget_settlement_failed"
    assert audit_calls[0][1]["agent_id"] == "test-agent"


def test_settlement_failure_resets_success_flag_in_dispatcher():
    source = inspect.getsource(dispatcher.dispatch_to_omniroute_or_container)
    call_pos = source.index("_mark_budget_settlement_failed(res, rec_exc")
    assert "is_ok = False" in source[call_pos : call_pos + 200]


def test_semantic_cache_failure_is_visible():
    result = {"status": "success", "content": "Antwort"}
    dispatcher._mark_cache_store_failed(result, RuntimeError("cache db down"))
    assert result["cache_unverified"] is True
    assert result["status"] == "success"  # Cache ist kein harter Fehler
