# -*- coding: utf-8 -*-
"""M109 Red-Team & Verification: Code-Mode Discovery, Broker und Sandbox.

Hartes Setup: alle Tests injizieren Fake-Engine, Fake-Audit-Sink und
Fake-Executor. Es wird bewusst KEINE echte Audit-/Approval-DB beschrieben.
Die Sandbox laeuft in eigenen Prozessen mit leerer Environment.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend import code_mode_discovery as discovery
from backend.code_mode_capability_broker import (
    SENSITIVE_KEY_PARTS,
    CapabilityBroker,
    _is_sensitive_key,
    mask_broker_response,
)
from backend.code_mode_discovery import (
    CODE_MODE_META_TOOLS,
    Capability,
    acall_capability,
    call_capability,
    describe_capability,
    register_capability,
    search_capabilities,
    validate_arguments,
)
from backend.code_mode_sandbox import (
    SANDBOX_ALLOWED_MODULES,
    SandboxViolation,
    execute_code,
    validate_sandbox_source,
)
from backend.credential_masking import mask_secret
from backend.secret_masker import mask_sensitive_text

READ_CAP = "archon__list_tasks"
WRITE_CAP = "archon__create_task"
DESTRUCTIVE_CAP = "m109test__delete_item"


# ---------------------------------------------------------------------------
# Fakes (keine DB, keine echte Freigabe, kein echter Tool-Aufruf)
# ---------------------------------------------------------------------------


class FakeEngine:
    """Minimaler Ersatz fuer approval_policy_engine.approval_engine."""

    def __init__(self, requests: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.requests: Dict[str, Dict[str, Any]] = dict(requests or {})
        self.enqueued: List[Dict[str, Any]] = []

    def evaluate_and_enqueue(self, **kwargs: Any) -> Dict[str, Any]:
        self.enqueued.append(kwargs)
        return {"request_id": "REQ-TEST", "status": "pending"}

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        return self.requests.get(str(request_id))


def make_audit_sink(
    events: List[Dict[str, Any]], *, fail: bool = False
) -> Any:
    """Fake-Sink mit exakt der Signatur von ``_require_audit_event``."""

    def _sink(
        category: str,
        action: str,
        agent_id: str,
        payload: Any,
        **kwargs: Any,
    ) -> Dict[str, int]:
        if fail:
            raise RuntimeError("audit sink unavailable")
        events.append({
            "category": category,
            "action": action,
            "agent_id": agent_id,
            "payload": payload,
            "kwargs": kwargs,
        })
        return {"event_id": 1}

    return _sink


class FakeExecutor:
    """Async-Executor: wird vom Broker korrekt awaited."""

    def __init__(self, response: Optional[Dict[str, Any]] = None) -> None:
        self.response: Dict[str, Any] = (
            response if response is not None else {"status": "success", "result": {"ok": True}}
        )
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


@pytest.fixture
def broker_factory(destructive_cap: Capability) -> Any:
    """Erzeugt Broker + Fakes; Default-Allowlist deckt die Registry-Caps ab."""

    def _make(
        *,
        allowlist: Tuple[str, ...] = (READ_CAP, WRITE_CAP, DESTRUCTIVE_CAP),
        allowed_routes: Optional[List[Tuple[str, str]]] = None,
        requests: Optional[Dict[str, Dict[str, Any]]] = None,
        audit_fail: bool = False,
        response: Optional[Dict[str, Any]] = None,
    ) -> Tuple[CapabilityBroker, List[Dict[str, Any]], FakeEngine, FakeExecutor]:
        events: List[Dict[str, Any]] = []
        engine = FakeEngine(requests)
        executor = FakeExecutor(response)
        broker = CapabilityBroker(
            allowlist,
            allowed_routes=allowed_routes,
            engine=engine,
            audit_sink=make_audit_sink(events, fail=audit_fail),
            executor=executor,
        )
        return broker, events, engine, executor

    return _make


@pytest.fixture(scope="module")
def destructive_cap() -> Capability:
    """Eigene destruktive Capability mit eindeutigem Präfix."""
    cap = Capability(
        name=DESTRUCTIVE_CAP,
        method="TOOL",
        path=DESTRUCTIVE_CAP,
        category="general",
        risk_level="destructive",
        summary="M109-Test-Capability zum Löschen eines Eintrags.",
        parameters={
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
            "additionalProperties": False,
        },
    )
    register_capability(cap)
    return cap


@pytest.fixture
def strict_cap() -> Capability:
    """Capability mit additionalProperties=False fuer Strict-Validierung."""
    cap = Capability(
        name="m109test__strict_args",
        method="TOOL",
        path="m109test__strict_args",
        category="general",
        risk_level="read",
        summary="M109-Test-Capability mit strikter Argument-Schema-Prüfung.",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
    )
    register_capability(cap)
    return cap


class SpyBroker:
    """Zeichnet sync und async Broker-Aufrufe auf."""

    def __init__(self) -> None:
        self.sync_calls: List[Tuple[Any, ...]] = []
        self.async_calls: List[Tuple[Any, ...]] = []

    def invoke_sync(self, name: str, arguments: Any = None, **kwargs: Any) -> Dict[str, Any]:
        self.sync_calls.append((name, arguments, kwargs))
        return {"status": "success", "result": {"source": "spy"}}

    async def invoke(self, name: str, arguments: Any = None, **kwargs: Any) -> Dict[str, Any]:
        self.async_calls.append((name, arguments, kwargs))
        return {"status": "success", "result": {"source": "spy-async"}}


class BridgeBroker:
    """Fake-Broker mit invoke_sync fuer die Sandbox-JSONL-Bridge."""

    def __init__(self, response: Optional[Dict[str, Any]] = None) -> None:
        self.response: Dict[str, Any] = response or {
            "status": "success",
            "result": {"tasks": [{"id": 1}]},
            "error": None,
            "error_code": None,
            "request_id": None,
            "masked": True,
        }
        self.calls: List[Tuple[str, Any]] = []

    def invoke_sync(self, name: str, arguments: Any = None, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append((name, arguments))
        return self.response


# ---------------------------------------------------------------------------
# A) Token-Footprint / Deferred Discovery
# ---------------------------------------------------------------------------


def test_meta_tools_token_footprint() -> None:
    payload = json.dumps(CODE_MODE_META_TOOLS, ensure_ascii=False)
    tokens = len(payload) // 4
    assert 700 <= tokens <= 1000, f"Token-Footprint ausserhalb des Zielbereichs: {tokens}"

    from backend.tool_runtime import get_code_mode_meta_tools

    assert get_code_mode_meta_tools() == CODE_MODE_META_TOOLS
    names = [tool["name"] for tool in CODE_MODE_META_TOOLS]
    assert names == ["search_capabilities", "describe_capability", "call_capability"]
    assert len(set(names)) == 3


def test_search_briefs_never_dump_schemas() -> None:
    hits = search_capabilities("task")
    assert hits
    brief_keys = {"name", "method", "path", "risk_level", "summary"}
    for hit in hits:
        assert set(hit.keys()) == brief_keys
        assert "parameters" not in hit
        assert "inputSchema" not in hit


def test_describe_capability_delivers_parameters_and_unknown_code() -> None:
    detail = describe_capability(READ_CAP)
    assert detail["name"] == READ_CAP
    assert "parameters" in detail
    assert isinstance(detail["parameters"], dict)
    assert detail["approval_required"] is False
    assert describe_capability(WRITE_CAP)["approval_required"] is True
    unknown = describe_capability("m109test__does_not_exist")
    assert unknown["error"] == "UNKNOWN_CAPABILITY"


def test_validation_bool_is_not_integer() -> None:
    check = validate_arguments(READ_CAP, {"limit": True})
    assert check["ok"] is False
    assert check["error"] == "INVALID_TYPE"


def test_validation_missing_required() -> None:
    check = validate_arguments(WRITE_CAP, {})
    assert check["ok"] is False
    assert check["error"] == "MISSING_REQUIRED"


def test_validation_unknown_property_with_additional_properties_false(strict_cap: Capability) -> None:
    check = validate_arguments(strict_cap, {"count": 2, "extra": "x"})
    assert check["ok"] is False
    assert check["error"] == "UNKNOWN_PROPERTY"
    assert validate_arguments(strict_cap, {"count": 2})["ok"] is True


def test_validation_defaults_are_supplemented() -> None:
    check = validate_arguments(READ_CAP, {})
    assert check["ok"] is True
    assert check["arguments"] == {"status": "all", "limit": 20}


def test_search_limit_clamp_and_risk_filter() -> None:
    total = len(discovery.all_capabilities())
    assert len(search_capabilities("", limit=0)) == 1
    assert len(search_capabilities("", limit=-5)) == 1
    assert len(search_capabilities("", limit=999)) == min(50, total)
    # Bewusst falscher Typ: die Runtime muss ihn robust auf den Default clampen.
    assert len(search_capabilities("", limit="broken")) == min(15, total)  # type: ignore[arg-type]

    reads = search_capabilities("", risk_level="read", limit=50)
    assert reads
    assert {hit["risk_level"] for hit in reads} == {"read"}
    assert search_capabilities("", risk_level="bogus") == []


def test_call_capability_validation_short_circuits_broker() -> None:
    spy = SpyBroker()
    result = call_capability(WRITE_CAP, {}, broker=spy)
    assert result["status"] == "error"
    assert result["error_code"] == "SCHEMA_VALIDATION_FAILED"
    assert spy.sync_calls == []


def test_call_capability_success_passes_validated_arguments() -> None:
    spy = SpyBroker()
    result = call_capability(READ_CAP, {"status": "done"}, broker=spy)
    assert result["status"] == "success"
    assert len(spy.sync_calls) == 1
    assert spy.sync_calls[0][0] == READ_CAP
    assert spy.sync_calls[0][1] == {"status": "done", "limit": 20}


def test_acall_capability_uses_async_invoke() -> None:
    spy = SpyBroker()
    result = asyncio.run(acall_capability(READ_CAP, {}, broker=spy))
    assert result["result"]["source"] == "spy-async"
    assert len(spy.async_calls) == 1
    assert spy.sync_calls == []


# ---------------------------------------------------------------------------
# B) Broker-Sicherheit (ausschliesslich Fakes)
# ---------------------------------------------------------------------------


def test_sensitive_key_detection() -> None:
    for key in ("api_key", "API-KEY", "accessToken", "password", "client_secret", "authorization"):
        assert _is_sensitive_key(key) is True
    for key in ("monkey", "author", "keyword", "title", "status"):
        assert _is_sensitive_key(key) is False
    assert SENSITIVE_KEY_PARTS


def test_capability_not_allowlisted_is_audited(broker_factory: Any) -> None:
    broker, events, _, executor = broker_factory(allowlist=(READ_CAP,))
    result = broker.invoke_sync("archon__search_crm_contacts", {})
    assert result["status"] == "blocked"
    assert result["error_code"] == "CAPABILITY_NOT_ALLOWLISTED"
    assert executor.calls == []
    assert any(
        event["action"] == "capability_blocked"
        and event["payload"].get("error_code") == "CAPABILITY_NOT_ALLOWLISTED"
        for event in events
    )


def test_known_capability_wrong_route_is_blocked(broker_factory: Any) -> None:
    broker, events, _, executor = broker_factory(
        allowed_routes=[("GET", READ_CAP)]
    )
    result = broker.invoke_sync(READ_CAP, {"status": "all"})
    assert result["error_code"] == "CAPABILITY_NOT_ALLOWLISTED"
    assert executor.calls == []
    assert any(event["action"] == "capability_blocked" for event in events)


@pytest.mark.parametrize("bypass_key", [
    "method", "path", "url", "endpoint", "capability", "broker", "target",
])
def test_broker_bypass_arguments_are_rejected(
    broker_factory: Any, bypass_key: str
) -> None:
    broker, events, _, executor = broker_factory()
    result = broker.invoke_sync(READ_CAP, {"status": "all", bypass_key: "DELETE /admin"})
    assert result["status"] == "blocked"
    assert result["error_code"] == "BROKER_ARGUMENT_REJECTION"
    assert executor.calls == []
    assert any(event["payload"].get("error_code") == "BROKER_ARGUMENT_REJECTION" for event in events)


def test_nested_bypass_argument_is_rejected(broker_factory: Any) -> None:
    broker, _, _, executor = broker_factory()
    result = broker.invoke_sync(READ_CAP, {"status": "all", "filter": {"url": "http://evil"}})
    assert result["error_code"] == "BROKER_ARGUMENT_REJECTION"
    assert executor.calls == []


def test_read_capability_succeeds_and_is_masked(broker_factory: Any) -> None:
    response = {"status": "success", "result": {"tasks": []}}
    broker, events, _, executor = broker_factory(response=response)
    result = broker.invoke_sync(READ_CAP, {"status": "all"})
    assert result["status"] == "success"
    assert result["masked"] is True
    assert result["result"] == response
    assert len(executor.calls) == 1
    assert executor.calls[0]["tool_name"] == READ_CAP
    assert any(
        event["action"] == "capability_allowed"
        and event["category"] == "code_mode"
        for event in events
    )


@pytest.mark.parametrize("cap_name,arguments", [
    (WRITE_CAP, {"title": "M109 test"}),
    (DESTRUCTIVE_CAP, {"item_id": "item-1"}),
])
def test_write_without_approval_requires_predecision(
    broker_factory: Any, cap_name: str, arguments: Dict[str, Any]
) -> None:
    broker, events, engine, executor = broker_factory()
    result = broker.invoke_sync(cap_name, arguments)
    assert result["status"] == "blocked"
    assert result["error_code"] == "PREDECISION_REQUIRED"
    assert result["request_id"] == "REQ-TEST"
    assert executor.calls == []
    assert engine.enqueued
    assert any(
        event["action"] == "predecision_denied"
        and event["payload"].get("error_code") == "PREDECISION_REQUIRED"
        for event in events
    )


@pytest.mark.parametrize("request_id,approval_request", [
    ("PENDING-1", {
        "status": "pending", "domain": "code_mode",
        "reference_id": WRITE_CAP, "requester_id": "human-requester",
    }),
    ("UNKNOWN-1", None),
    ("CROSS-1", {
        "status": "approved", "domain": "code_mode",
        "reference_id": "archon__update_task_status",
        "requester_id": "human-requester", "first_approver": "approver-bob",
    }),
    ("WRONG-DOMAIN-1", {
        "status": "approved", "domain": "erp",
        "reference_id": WRITE_CAP,
        "requester_id": "human-requester", "first_approver": "approver-bob",
    }),
])
def test_invalid_approval_ids_are_denied(
    broker_factory: Any,
    request_id: str,
    approval_request: Optional[Dict[str, Any]],
) -> None:
    requests = {request_id: approval_request} if approval_request is not None else {}
    broker, events, _, executor = broker_factory(requests=requests)
    result = broker.invoke_sync(
        WRITE_CAP, {"title": "M109 test"},
        approval_id=request_id, requester="human-requester",
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "PREDECISION_DENIED"
    assert executor.calls == []
    assert any(
        event["action"] == "predecision_denied"
        and event["payload"].get("error_code") == "PREDECISION_DENIED"
        for event in events
    )


def test_valid_code_mode_approval_allows_execution(broker_factory: Any) -> None:
    requests = {
        "APPROVED-1": {
            "status": "approved",
            "domain": "code_mode",
            "reference_id": WRITE_CAP,
            "requester_id": "human-requester",
            "first_approver": "approver-bob",
        }
    }
    broker, _, _, executor = broker_factory(requests=requests)
    result = broker.invoke_sync(
        WRITE_CAP, {"title": "M109 test"},
        approval_id="APPROVED-1", requester="human-requester",
    )
    assert result["status"] == "success"
    assert result["request_id"] == "APPROVED-1"
    assert len(executor.calls) == 1


def test_self_approval_is_denied(broker_factory: Any) -> None:
    requests = {
        "SELF-1": {
            "status": "approved",
            "domain": "code_mode",
            "reference_id": WRITE_CAP,
            "requester_id": "human-requester",
            "first_approver": "human-requester",
        }
    }
    broker, events, _, executor = broker_factory(requests=requests)
    result = broker.invoke_sync(
        WRITE_CAP, {"title": "M109 test"},
        approval_id="SELF-1", requester="human-requester",
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "PREDECISION_DENIED"
    assert executor.calls == []
    assert any(event["action"] == "predecision_denied" for event in events)


def test_secret_leak_is_masked_in_response_and_audit(broker_factory: Any) -> None:
    secret = "supersecretvalue123"
    bearer = "Bearer " + "sk-" + "abcdefghijklmnopqrstuvwxyz12345"
    response = {
        "status": "success",
        "result": {"api_key": secret, "message": bearer},
    }
    broker, events, _, executor = broker_factory(response=response)
    result = broker.invoke_sync(READ_CAP, {"status": "all"})
    assert result["status"] == "success"
    assert result["masked"] is True
    assert result["result"]["result"]["api_key"] == mask_secret(secret)
    assert result["result"]["result"]["message"] == mask_sensitive_text(bearer)[0]

    response_json = json.dumps(result, ensure_ascii=False)
    audit_json = json.dumps(events, ensure_ascii=False, default=str)
    assert secret not in response_json
    assert secret not in audit_json
    assert bearer not in response_json
    assert bearer not in audit_json
    assert len(executor.calls) == 1


def test_audit_sink_failure_is_fail_closed(broker_factory: Any) -> None:
    broker, _, _, executor = broker_factory(audit_fail=True)
    result = broker.invoke_sync(WRITE_CAP, {"title": "M109 test"})
    assert result["status"] == "error"
    assert result["error_code"] == "AUDIT_WRITE_FAILED"
    assert executor.calls == []
    assert "audit sink unavailable" not in json.dumps(result, ensure_ascii=False)


def test_mask_broker_response_is_recursive() -> None:
    secret = "supersecretvalue123"
    masked = mask_broker_response({"items": [{"api_token": secret}, {"title": "ok"}]})
    assert masked["items"][0]["api_token"] == mask_secret(secret)
    assert masked["items"][1]["title"] == "ok"


# ---------------------------------------------------------------------------
# C) Sandbox-Escape-Versuche
# ---------------------------------------------------------------------------


def test_sandbox_happy_path() -> None:
    result = execute_code("print(1+1)", timeout_seconds=1.0)
    assert result.ok is True
    assert result.stdout.strip() == "2"
    assert result.exit_code == 0
    assert result.timed_out is False


@pytest.mark.parametrize("code", [
    "import os; print(os.environ)",
    "print(open('.env').read())",
    "print(open('C:/Users/micha/.env').read())",
    "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
    "import subprocess; subprocess.run(['calc.exe'])",
    "print(__import__('os'))",
    "from os import environ; print(environ)",
])
def test_static_escape_attempts_are_rejected(code: str) -> None:
    result = execute_code(code, timeout_seconds=0.5)
    assert result.ok is False
    assert "SANDBOX_VIOLATION" in result.error


def test_validate_sandbox_source_raises_without_leaking_source() -> None:
    with pytest.raises(SandboxViolation) as exc_info:
        validate_sandbox_source("import os; print(os.environ['SUPER_SECRET_VALUE_123'])")
    assert "SUPER_SECRET_VALUE_123" not in str(exc_info.value)


def test_sandbox_allowed_modules_are_hard_limited() -> None:
    assert SANDBOX_ALLOWED_MODULES == frozenset({"json", "math"})
    result = execute_code("import json; print(json.dumps({'a': 1}))", timeout_seconds=1.0)
    assert result.ok is True
    assert result.stdout.strip() == '{"a": 1}'


def test_infinite_loop_hits_timeout() -> None:
    result = execute_code("while True: pass", timeout_seconds=0.5)
    assert result.timed_out is True
    assert result.ok is False
    assert "TIMEOUT" in result.error


def test_output_truncation_is_marked_and_capped() -> None:
    small = execute_code("print('X'*200000)", timeout_seconds=1.0, max_output_bytes=1024)
    assert small.ok is True
    assert "[OUTPUT_TRUNCATED]" in small.stdout
    assert len(small.stdout) <= 1024

    default = execute_code("print('X'*200000)", timeout_seconds=1.0)
    assert default.ok is True
    assert "[OUTPUT_TRUNCATED]" in default.stdout
    assert len(default.stdout) <= 65536


def test_sandbox_process_has_no_environment_and_no_builtins_escape() -> None:
    # Statische AST-Pruefung und minimale Builtins verhindern __import__/os.
    assert "SANDBOX_VIOLATION" in execute_code(
        "print(__import__('os'))", timeout_seconds=0.5
    ).error
    assert "SANDBOX_VIOLATION" in execute_code(
        "import os", timeout_seconds=0.5
    ).error


# ---------------------------------------------------------------------------
# D) Capability-Bridge in der Sandbox
# ---------------------------------------------------------------------------


def test_capability_bridge_returns_masked_response() -> None:
    secret = "supersecretvalue123"
    fake = BridgeBroker({
        "status": "success",
        "result": {"api_key": secret, "tasks": [{"id": 1}]},
        "error": None,
        "error_code": None,
        "request_id": None,
        "masked": True,
    })
    code = "print(_call_capability('archon__list_tasks', {'status':'all'}))"
    result = execute_code(
        code,
        broker=fake,
        allowed_capabilities=(READ_CAP,),
        timeout_seconds=2.0,
    )
    assert result.ok is True, result.error
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == READ_CAP
    assert secret not in result.stdout
    assert mask_secret(secret) in result.stdout
    assert "masked" in result.stdout and "True" in result.stdout


def test_capability_bridge_blocks_non_allowlisted_capability() -> None:
    fake = BridgeBroker()
    code = "print(_call_capability('archon__create_task', {'title':'x'}))"
    result = execute_code(
        code,
        broker=fake,
        allowed_capabilities=(READ_CAP,),
        timeout_seconds=2.0,
    )
    assert result.ok is True, result.error
    assert "CAPABILITY_NOT_ALLOWLISTED" in result.stdout
    assert fake.calls == []


def test_capability_bridge_without_broker_returns_no_broker() -> None:
    code = "print(_call_capability('archon__list_tasks', {}))"
    result = execute_code(
        code,
        broker=None,
        allowed_capabilities=(READ_CAP,),
        timeout_seconds=2.0,
    )
    assert result.ok is True, result.error
    assert "NO_BROKER" in result.stdout
