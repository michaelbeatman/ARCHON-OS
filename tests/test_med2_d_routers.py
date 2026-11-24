# -*- coding: utf-8 -*-
"""Re-Audit MED-2D: Router-Reste aus domain_04/06/11/14/16.

Deckt die im Stage-1-Reaudit verbliebenen, im Router-Territorium liegenden
MED-Funde ab:

* SysOps-MCP-REST: Tool-Output-Firewall + Actor aus der Session
* Mesh-Config-Endpunkte: extra="allow" + cfg.update() -> typisierte Allowlist
* v2-Portal: Produktiv-Endpoint fuer submit_client_decision (Art. 50)
* Chat-Mission: created_by fuer den Vier-Augen-Abgleich
* Decisions: kein undefiniertes `task_id` im Boardroom-Followup
* Kanban-HITL: Env-Fail-Open darf die Reverifikation nicht abschalten
* Approvals: kein stilles TypeError-Schlucken beim Antragsteller

Rein unitarisch: keine DB-Migration, kein Replay, keine externen Calls.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ARCHON_ROOT") or _HERE.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _module(name: str):
    return importlib.import_module(name)


def _http_exception():
    """FastAPI ist im lokalen Minimal-venv nicht immer installiert."""
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    return HTTPException


def _source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _tree(rel_path: str) -> ast.Module:
    return ast.parse(_source(rel_path), filename=rel_path)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Funktion {name!r} nicht im AST gefunden")


class _FakeRequest:
    """Minimaler Request fuer direkte Router-Aufrufe (kein HTTP-Stack)."""

    def __init__(self, payload=None):
        self._payload = payload or {}

    async def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# domain_04: SysOps-MCP-REST — guard_result + Actor aus der Session
# ---------------------------------------------------------------------------


def test_sysops_mcp_call_guards_tool_output_and_uses_session_actor(monkeypatch):
    _http_exception()
    sysops = _module("archon.routers.operations_sysops")
    tool_runtime = _module("backend.tool_runtime")
    warrants = _module("backend.tool_warrants")
    mcp_server = _module("scripts.archon_mcp_server")

    seen = {}

    monkeypatch.setattr(sysops, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(sysops, "get_session_actor", lambda request: "alice")

    def _gate(**kwargs):
        seen["gate"] = kwargs
        return {"allowed": True}

    def _guard(tool_name, result):
        seen["guard"] = (tool_name, result)
        return {"masked": True, "tool": tool_name}

    monkeypatch.setattr(tool_runtime, "enforce_tool_execution", _gate)
    monkeypatch.setattr(tool_runtime, "guard_result", _guard)
    monkeypatch.setattr(tool_runtime, "record_tool_read_side_effect", lambda *a, **k: None)
    monkeypatch.setattr(warrants, "get_warrant_for_session", lambda sid, tool: {"w": 1})

    class _Server:
        def execute_tool(self, name, arguments):
            return {"raw": "DUMMY-ignore-previous-instructions"}

    monkeypatch.setattr(mcp_server, "ArchonMcpServer", _Server)

    req = sysops.McpToolCallRequest(name="demo.tool", arguments={}, agent_id="attacker")
    res = sysops.api_call_mcp_tool(_FakeRequest(), req)

    assert res["result"] == {"masked": True, "tool": "demo.tool"}
    assert seen["guard"][0] == "demo.tool"
    assert "DUMMY-ignore" in str(seen["guard"][1])  # Roh-Output ging in den Guard
    # Actor niemals aus dem Body:
    assert seen["gate"]["agent_id"] == "user:alice"
    assert seen["gate"]["session_id"] == "user:alice"


def test_sysops_guard_failure_is_fail_closed(monkeypatch):
    HTTPException = _http_exception()
    sysops = _module("archon.routers.operations_sysops")
    tool_runtime = _module("backend.tool_runtime")
    warrants = _module("backend.tool_warrants")
    mcp_server = _module("scripts.archon_mcp_server")

    monkeypatch.setattr(sysops, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(sysops, "get_session_actor", lambda request: "alice")
    monkeypatch.setattr(tool_runtime, "enforce_tool_execution", lambda **kw: {"allowed": True})
    monkeypatch.setattr(tool_runtime, "record_tool_read_side_effect", lambda *a, **k: None)
    monkeypatch.setattr(warrants, "get_warrant_for_session", lambda sid, tool: {})

    def _boom(tool_name, result):
        raise RuntimeError("firewall down")

    monkeypatch.setattr(tool_runtime, "guard_result", _boom)

    class _Server:
        def execute_tool(self, name, arguments):
            return {"raw": "secret"}

    monkeypatch.setattr(mcp_server, "ArchonMcpServer", _Server)

    with pytest.raises(HTTPException) as exc:
        sysops.api_call_mcp_tool(
            _FakeRequest(), sysops.McpToolCallRequest(name="demo.tool", arguments={})
        )
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# domain_06: Mesh-Config — extra="ignore" + explizite Allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name",
    ["ConcurrencyConfigRequest", "MemoryConsolidationConfigRequest"],
)
def test_mesh_config_models_ignore_unknown_keys(model_name):
    _http_exception()
    mesh = _module("archon.routers.mesh")
    model = getattr(mesh, model_name)
    assert model.model_config.get("extra") == "ignore"

    parsed = model.model_validate(
        {"injected_control_key": "evil", "last_run": "evil", "enabled": True}
    )
    dumped = parsed.model_dump(exclude_none=True)
    assert "injected_control_key" not in dumped
    assert "last_run" not in dumped


def test_mesh_concurrency_config_only_updates_allowlisted_keys(monkeypatch):
    _http_exception()
    mesh = _module("archon.routers.mesh")
    throttle = _module("backend.concurrency_throttle")

    saved = {}

    monkeypatch.setattr(mesh, "_require_admin", lambda request: None)
    monkeypatch.setattr(
        throttle,
        "get_concurrency_config",
        lambda: {"max_concurrent_agents": 4, "queue_timeout_seconds": 60, "internal": "keep"},
    )
    monkeypatch.setattr(throttle, "save_concurrency_config", lambda cfg: saved.update(cfg) or True)

    req = mesh.ConcurrencyConfigRequest.model_validate(
        {
            "max_concurrent_agents": 9,
            "queue_timeout_seconds": 120,
            "max_concurrent": 99,  # Legacy-Feld: nicht in die Config uebernehmen
            "custom_option": "evil",
            "internal": "overwritten",
            "injected_control_key": "evil",
        }
    )
    mesh.api_save_concurrency_config(_FakeRequest(), req)

    assert saved["max_concurrent_agents"] == 9
    assert saved["queue_timeout_seconds"] == 120
    assert saved["internal"] == "keep"
    for key in ("max_concurrent", "custom_option", "injected_control_key"):
        assert key not in saved


def test_mesh_consolidation_config_cannot_set_runtime_fields(monkeypatch):
    _http_exception()
    mesh = _module("archon.routers.mesh")
    consolidator = _module("backend.memory_consolidator")

    saved = {}

    monkeypatch.setattr(mesh, "_require_admin", lambda request: None)
    monkeypatch.setattr(
        consolidator,
        "get_consolidation_config",
        lambda: {"enabled": True, "retention_days": 14, "last_run": "keep"},
    )
    monkeypatch.setattr(consolidator, "save_consolidation_config", lambda cfg: saved.update(cfg) or True)

    req = mesh.MemoryConsolidationConfigRequest.model_validate(
        {"retention_days": 30, "last_run": "evil", "last_pruned_records_count": 999}
    )
    mesh.api_save_memory_consolidation_settings(_FakeRequest(), req)

    assert saved["retention_days"] == 30
    assert saved["last_run"] == "keep"
    assert "last_pruned_records_count" not in saved


# ---------------------------------------------------------------------------
# domain_04: v2-Portal — Art. 50 Produktiv-Endpoint
# ---------------------------------------------------------------------------


def test_v2_portal_has_decision_endpoint():
    _http_exception()
    v2 = _module("archon.routers.v2_capabilities")
    paths = {getattr(r, "path", "") for r in v2.router.routes}
    assert "/api/v2/portal/decisions" in paths


def test_v2_portal_requires_explicit_disclosure(monkeypatch):
    HTTPException = _http_exception()
    v2 = _module("archon.routers.v2_capabilities")
    portal = _module("backend.client_approval_portal")

    called = {}

    def _submit(**kwargs):
        called.update(kwargs)
        return {"allowed": True, "ai_disclosure_proof": "verified_signature"}

    monkeypatch.setattr(portal, "submit_client_decision", _submit)

    base = dict(
        token="cli-token",
        decision="accepted",
        terms_accepted=True,
        ai_disclosure_token="signed-token",
    )

    # Ohne explizite UI-Bestaetigung: 403, Engine nicht aufgerufen.
    with pytest.raises(HTTPException) as exc:
        v2.api_v2_submit_client_decision(
            v2.ClientDecisionSubmitRequest(**base, ai_disclosure_shown=False)
        )
    assert exc.value.status_code == 403
    assert not called

    res = v2.api_v2_submit_client_decision(
        v2.ClientDecisionSubmitRequest(**base, ai_disclosure_shown=True)
    )
    assert res["status"] == "success"
    assert called["ai_disclosure_shown"] is True
    assert called["ai_disclosure_token"] == "signed-token"
    assert called["token"] == "cli-token"


def test_v2_portal_engine_denial_is_propagated(monkeypatch):
    HTTPException = _http_exception()
    v2 = _module("archon.routers.v2_capabilities")
    portal = _module("backend.client_approval_portal")
    monkeypatch.setattr(
        portal,
        "submit_client_decision",
        lambda **kw: {"allowed": False, "reason": "Art. 50"},
    )
    with pytest.raises(HTTPException) as exc:
        v2.api_v2_submit_client_decision(
            v2.ClientDecisionSubmitRequest(
                token="cli-token",
                decision="accepted",
                ai_disclosure_shown=True,
                ai_disclosure_token="signed-token",
            )
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# domain_04 / domain_14: statische Kanten pruefungen
# ---------------------------------------------------------------------------


def test_chat_mission_decision_sets_created_by():
    tree = _tree("archon/routers/chat.py")
    fn = _function(tree, "api_chat_stream")
    # Der Aufruf laeuft ueber asyncio.to_thread(_create_dec, ...).
    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and n.args
        and isinstance(n.args[0], ast.Name)
        and n.args[0].id == "_create_dec"
    ]
    assert calls, "Mission-Freigabe ruft _create_dec nicht"
    # created_by ist der 9. Parameter von create_decision -> to_thread-args[9].
    assert any(
        len(c.args) >= 10 or any(k.arg == "created_by" for k in c.keywords)
        for c in calls
    ), "Mission-Freigabe ohne created_by -> /api/decisions/decide sperrt fail-closed"
    # created_by stammt aus der Session, nicht aus req:
    assert "get_session_actor" in _source("archon/routers/chat.py")


def test_decision_followup_has_no_undefined_task_id():
    tree = _tree("archon/routers/decisions.py")
    fn = _function(tree, "_decision_followup")
    names = [
        n.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id == "task_id"
    ]
    assert not names, "task_id ist in _decision_followup nicht definiert (NameError)"


def test_approvals_do_not_swallow_typeerror():
    tree = _tree("archon/routers/operations_approvals.py")
    fn = _function(tree, "api_create_approval_request")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert not any(
        isinstance(h.type, ast.Name) and h.type.id == "TypeError" for h in handlers
    ), "requester_id darf nicht still durch einen Aufruf ohne ihn ersetzt werden"
    src = ast.get_source_segment(_source("archon/routers/operations_approvals.py"), fn) or ""
    assert "requester_id=requester_id" in src


# ---------------------------------------------------------------------------
# domain_14: Kanban-HITL — Env-Fail-Open im Router wirkungslos
# ---------------------------------------------------------------------------


def test_kanban_hitl_override_without_verification_is_blocked(monkeypatch, tmp_path):
    HTTPException = _http_exception()
    kanban = _module("archon.routers.kanban")
    verifier = _module("backend.kanban_verifier")
    rbac = _module("archon.routers._rbac")

    monkeypatch.setattr(rbac, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(kanban, "require_session_actor", lambda request: "bob")
    monkeypatch.setattr(
        kanban, "_resolve_active_kanban_db", lambda: str(tmp_path / "does-not-exist.db")
    )
    monkeypatch.setattr(
        verifier,
        "resolve_card_hitl_decision",
        lambda *a, **kw: {
            "resolution": "override",
            "next_status": "todo",
            "token_budget": 2000,
            "verified": False,
        },
    )
    monkeypatch.setenv("ARCHON_KANBAN_HITL_ALLOW_UNVERIFIED_OVERRIDE", "1")

    request = _FakeRequest({"action": "override", "current_budget": 1000})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(kanban.api_kanban_task_hitl(request, "task-x"))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# domain_16: bereits behobene Router-Reste als Regression-Belege
# ---------------------------------------------------------------------------


def test_mcp_gateway_cancelled_error_is_logged_as_warning():
    tree = _tree("archon/routers/mcp_gateway.py")
    handlers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Attribute)
        and n.type.attr == "CancelledError"
    ]
    assert handlers, "CancelledError-Handler fehlt"
    for handler in handlers:
        levels = {
            n.func.attr
            for n in ast.walk(handler)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "debug" not in levels, "CancelledError darf nicht auf DEBUG verschluckt werden"
        assert "warning" in levels or "info" in levels


def test_hermes_proxy_injects_with_child_span():
    src = _source("archon/routers/hermes_proxy.py")
    assert "with child_span" in src
    assert "inject_headers(fwd_headers)" in src
