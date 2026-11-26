# -*- coding: utf-8 -*-
"""W2-E — Silent-Failure-Schutz: Firewall-Vertrag & Konsens-Persistenz.

Regressionstests zu D12-H1, D12-M1, D12-M2/M3. Alle externen Abhaengigkeiten
(LLM-Klassifikator, Dispatcher, Plugin-Manager, SQLite) werden gemockt; es gibt
keine Replays, keine PostgreSQL-Migration und keine echten Netzwerk-Calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _safe_classifier(monkeypatch):
    """Der Klassifikator ist hier immer verfuegbar und meldet 'safe'.

    Ohne diesen Stub haengt der Test von einer lokalen LLM-/Audit-Kette ab und
    jedes Ergebnis waere `TOOL_OUTPUT_CLASSIFICATION_ERROR`.
    """
    import local_security_guard as lsg

    monkeypatch.setattr(
        lsg, "quarantine_external_text",
        lambda *args, **kwargs: {
            "verdict": "safe", "llm_verdict": "SAFE",
            "llm_classification_executed": True,
        },
    )


class _FakeRequest:
    async def json(self):
        return {}


def _error_verdict(code: str = "EMPTY_TOOL_RESULT") -> dict:
    return {
        "status": "error", "error": code, "error_code": code,
        "result": f"[TOOL-FEHLER: {code}]", "empty_fields": ["result.result"],
    }


# ---------------------------------------------------------------------------
# D12-H1 — guard_result() ist der Pflicht-Chokepoint
# ---------------------------------------------------------------------------


def test_guard_result_default_returns_full_verdict():
    from backend.tool_runtime import guard_result

    verdict = guard_result("read_file", {"value": "hello"})
    assert isinstance(verdict, dict)
    assert "status" in verdict and "error_code" in verdict
    assert verdict["status"] == "ok"
    assert "hello" in str(verdict["result"])
    assert verdict["empty_fields"] == []


def test_guard_result_detects_empty_nested_leaf():
    from backend.tool_runtime import guard_result

    verdict = guard_result("terminal", {"status": "success", "result": ""})
    assert verdict["status"] == "error"
    assert verdict["error_code"] == "EMPTY_TOOL_RESULT"
    assert verdict["empty_fields"]


def test_guard_result_detects_empty_nested_container():
    from backend.tool_runtime import guard_result

    verdict = guard_result("api", {"status": "success", "payload": {"body": {}}})
    assert verdict["status"] == "error"
    assert verdict["error_code"] == "EMPTY_TOOL_RESULT"
    assert any("body" in field for field in verdict["empty_fields"])


def test_guard_result_keeps_legitimate_empty_collections():
    from backend.tool_runtime import guard_result

    verdict = guard_result("search", {"status": "success", "count": 0, "items": []})
    assert verdict["status"] == "ok"
    assert verdict["empty_fields"] == []


def test_guard_result_classifier_failure_is_visible(monkeypatch):
    import local_security_guard as lsg
    from backend.tool_runtime import guard_result

    def boom(*args, **kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(lsg, "quarantine_external_text", boom)
    raw = "MEIN_ROHTEXT_MARKER_12345"
    verdict = guard_result("web_fetch", raw)
    assert verdict["status"] == "error"
    assert verdict["error_code"] == "TOOL_OUTPUT_CLASSIFICATION_ERROR"
    assert raw not in str(verdict)
    assert "TOOL-FEHLER" in str(verdict["result"])


def test_guard_result_with_status_false_is_explicit_opt_out_only():
    from backend.tool_runtime import guard_result

    legacy = guard_result("read_file", "Inhalt", with_status=False)
    assert isinstance(legacy, str)
    assert "Inhalt" in legacy


def test_guard_result_payload_unwraps_verdict():
    from backend.tool_runtime import guard_result_payload

    assert guard_result_payload({"status": "ok", "result": {"a": 1}}) == {"a": 1}
    # Injizierte Legacy-Guards ohne Urteil bleiben unveraendert.
    assert guard_result_payload({"masked": True}) == {"masked": True}


# ---------------------------------------------------------------------------
# D12-H1 — MCP tools/call
# ---------------------------------------------------------------------------


def test_mcp_tools_call_marks_firewall_error_as_is_error(monkeypatch):
    import backend.mcp_gateway as mg
    import backend.tool_runtime as tr
    import backend.tool_warrants as tw
    import scripts.archon_mcp_server as amcp

    monkeypatch.setattr(mg, "is_demo_mode", lambda: False)
    monkeypatch.setattr(mg.ArchonMcpGateway, "_check_hitl_gate", lambda self, *a: (True, None))
    monkeypatch.setattr(tr, "enforce_tool_execution", lambda **kw: {"allowed": True})
    monkeypatch.setattr(tr, "record_tool_read_side_effect", lambda *a, **k: None)
    monkeypatch.setattr(tr, "guard_result", lambda name, res, *, with_status=True: _error_verdict())
    monkeypatch.setattr(tr, "guard_result_payload", lambda v: v.get("result"))
    monkeypatch.setattr(tw, "get_warrant_for_session", lambda *a, **k: {})

    class _Server:
        def execute_tool(self, name, args):
            return {"status": "success", "result": ""}

    monkeypatch.setattr(amcp, "ArchonMcpServer", _Server)

    resp, _sid = mg.ArchonMcpGateway().handle_jsonrpc(
        {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "archon__list_tasks", "arguments": {}},
        },
        {"key_id": "k", "scopes": ["read_only", "admin_full"]},
    )
    rpc_result = resp["result"]  # type: ignore[index]
    assert rpc_result["isError"] is True
    assert rpc_result["error_code"] == "EMPTY_TOOL_RESULT"
    assert "EMPTY_TOOL_RESULT" in rpc_result["content"][0]["text"]


def test_mcp_tools_call_accepts_string_result_without_attribute_error(monkeypatch):
    import backend.mcp_gateway as mg

    monkeypatch.setattr(
        mg.ArchonMcpGateway, "execute_tool",
        lambda self, name, args, key_info: (0, "einfacher Text"),
    )
    resp, _sid = mg.ArchonMcpGateway().handle_jsonrpc(
        {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "archon__list_tasks", "arguments": {}},
        },
        {"key_id": "k", "scopes": ["read_only"]},
    )
    assert resp["result"]["isError"] is False  # type: ignore[index]
    assert "einfacher Text" in resp["result"]["content"][0]["text"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# D12-H1 — Plugin-REST / SysOps-REST
# ---------------------------------------------------------------------------


def test_plugin_rest_escalates_firewall_error(monkeypatch):
    HTTPException = pytest.importorskip("fastapi").HTTPException
    import archon.routers.plugins as plugins
    import backend.plugin_manager as pm_mod
    import backend.tool_runtime as tr
    import backend.tool_warrants as tw

    monkeypatch.setattr(plugins, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(plugins, "get_session_actor", lambda request: "alice")
    monkeypatch.setattr(tw, "get_warrant_for_session", lambda *a, **k: {})
    monkeypatch.setattr(tr, "enforce_tool_execution", lambda **kw: {"allowed": True})
    monkeypatch.setattr(tr, "record_tool_read_side_effect", lambda *a, **k: None)

    class _PM:
        async def execute_plugin_tool(self, name, args):
            return {"status": "success", "result": ""}

    monkeypatch.setattr(pm_mod, "get_plugin_manager", lambda: _PM())

    def _guard(name, result, *, with_status=True):
        assert with_status is True, "Plugin-Pfad muss den Pflichtvertrag nutzen"
        return _error_verdict("TOOL_OUTPUT_CLASSIFICATION_ERROR")

    monkeypatch.setattr(tr, "guard_result", _guard)
    monkeypatch.setattr(tr, "guard_result_payload", lambda v: v.get("result"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(plugins.api_execute_plugin_tool(
            _FakeRequest(), plugins.PluginToolExecuteRequest(tool_name="demo.tool")  # type: ignore[arg-type]
        ))
    assert exc.value.status_code >= 400
    assert exc.value.detail["error_code"] == "TOOL_OUTPUT_CLASSIFICATION_ERROR"


def test_sysops_rest_escalates_firewall_error(monkeypatch):
    HTTPException = pytest.importorskip("fastapi").HTTPException
    import archon.routers.operations_sysops as sysops
    import backend.tool_runtime as tr
    import backend.tool_warrants as tw
    import scripts.archon_mcp_server as amcp

    monkeypatch.setattr(sysops, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(sysops, "get_session_actor", lambda request: "alice")
    monkeypatch.setattr(tw, "get_warrant_for_session", lambda *a, **k: {})
    monkeypatch.setattr(tr, "enforce_tool_execution", lambda **kw: {"allowed": True})
    monkeypatch.setattr(tr, "record_tool_read_side_effect", lambda *a, **k: None)

    class _Server:
        def execute_tool(self, name, args):
            return {"status": "success", "result": ""}

    monkeypatch.setattr(amcp, "ArchonMcpServer", _Server)
    # Default von guard_result() ist jetzt das Urteil; auch ein 2-Argument-
    # Legacy-Guard darf nicht zu einem hartcodierten Erfolg fuehren.
    monkeypatch.setattr(tr, "guard_result", lambda name, result: _error_verdict())
    monkeypatch.setattr(tr, "guard_result_payload", lambda v: v.get("result"))

    with pytest.raises(HTTPException) as exc:
        sysops.api_call_mcp_tool(
            _FakeRequest(), sysops.McpToolCallRequest(name="demo.tool", arguments={})  # type: ignore[arg-type,call-arg]
        )
    assert exc.value.status_code >= 400
    assert exc.value.detail["error_code"] == "EMPTY_TOOL_RESULT"


# ---------------------------------------------------------------------------
# D12-M1 — Structured-Output-Bypass ist kein Erfolg
# ---------------------------------------------------------------------------


def test_disabled_schema_validator_is_never_valid(monkeypatch):
    import backend.autonomy_settings as settings
    from backend.structured_output_enforcer import structured_output_enforcer

    monkeypatch.setattr(
        settings, "get_module_config",
        lambda name: {
            "enabled": False, "auto_repair_json": True,
            "strict_schema_validation": True, "max_repair_attempts": 2,
        },
    )
    out = structured_output_enforcer.validate_and_enforce('{"score": 1}', {"score": "int"})
    assert out["valid"] is False
    assert out["bypassed"] is True
    assert out["error"] == "structured_output_validation_disabled"


def test_strict_schema_disabled_is_never_valid(monkeypatch):
    import backend.autonomy_settings as settings
    from backend.structured_output_enforcer import structured_output_enforcer

    monkeypatch.setattr(
        settings, "get_module_config",
        lambda name: {
            "enabled": True, "auto_repair_json": True,
            "strict_schema_validation": False, "max_repair_attempts": 2,
        },
    )
    out = structured_output_enforcer.validate_and_enforce('{"score": 1}', {"score": "int"})
    assert out["valid"] is False
    assert out["bypassed"] is True


# ---------------------------------------------------------------------------
# D12-M2/M3 — Konsens: Persistenz, Scores, Risiken, Historie
# ---------------------------------------------------------------------------


def _stub_dispatcher(monkeypatch, payload):
    import backend.autonomy_settings as settings

    async def _dispatch(**kwargs):
        return {"content": json.dumps(payload)}

    monkeypatch.setitem(
        sys.modules, "core_dispatcher",
        types.SimpleNamespace(dispatch_to_omniroute_or_container=_dispatch),
    )
    monkeypatch.setattr(
        settings, "get_module_config",
        lambda name: {"enabled": True, "majority_rule": "two_thirds", "default_model": "test"},
    )


def test_consensus_persistence_failure_blocks_approval(monkeypatch):
    from backend import consensus_gate as cg

    _stub_dispatcher(monkeypatch, {
        "approved": True, "score": 9, "verdict": "APPROVED",
        "critique": "solide", "risks": [],
    })
    monkeypatch.setattr(
        cg, "_record_decision",
        lambda *a, **k: (False, "CONSENSUS_PERSISTENCE_FAILED"),
    )
    res = asyncio.run(cg.review_task_output("t-1", "Titel", "Ergebnis"))
    assert res["status"] == "error"
    assert res["error_code"] == "CONSENSUS_PERSISTENCE_FAILED"
    assert res["approved"] is False
    assert res["persisted"] is False


def test_tri_agent_persistence_failure_blocks_approval(monkeypatch):
    from backend import consensus_gate as cg

    _stub_dispatcher(monkeypatch, {
        "juror": "QA", "approved": True, "score": 9, "reason": "ok",
    })
    monkeypatch.setattr(cg, "_record_decision", lambda *a, **k: (True, None))
    ok = asyncio.run(cg.run_tri_agent_council("t-2", "Titel", "Ergebnis"))
    assert ok["status"] == "success"
    assert ok["approved"] is True

    monkeypatch.setattr(
        cg, "_record_decision",
        lambda *a, **k: (False, "CONSENSUS_PERSISTENCE_FAILED"),
    )
    failed = asyncio.run(cg.run_tri_agent_council("t-3", "Titel", "Ergebnis"))
    assert failed["status"] == "error"
    assert failed["error_code"] == "CONSENSUS_PERSISTENCE_FAILED"
    assert failed["approved"] is False


def test_missing_risks_are_not_fabricated(monkeypatch):
    from backend import consensus_gate as cg

    _stub_dispatcher(monkeypatch, {
        "approved": True, "score": 9, "verdict": "APPROVED", "critique": "solide",
    })
    monkeypatch.setattr(cg, "_record_decision", lambda *a, **k: (True, None))
    res = asyncio.run(cg.review_task_output("t-4", "Titel", "Ergebnis"))
    assert res["risks"] is None
    assert "risks" in res["unverified_fields"]
    assert res["evaluation_failed"] is True
    assert res["needs_human_review"] is True
    assert res["approved"] is False
    assert res["status"] == "needs_human_review"


def test_missing_juror_score_is_not_weighted_with_seven(monkeypatch):
    from backend import consensus_gate as cg

    _stub_dispatcher(monkeypatch, {
        "juror": "QA", "approved": True, "reason": "ok",  # score fehlt
    })
    monkeypatch.setattr(cg, "_record_decision", lambda *a, **k: (True, None))
    res = asyncio.run(cg.run_tri_agent_council("t-5", "Titel", "Ergebnis"))
    assert res["avg_score"] is None
    assert res["status"] != "success"
    assert res["needs_human_review"] is True
    assert res["evaluation_failed"] is True
    assert res["approved"] is False
    assert "juror[0].score" in res["unverified_fields"]


def test_consensus_history_reports_structured_error(monkeypatch):
    from backend import consensus_gate as cg

    def boom(*args, **kwargs):
        raise RuntimeError("db nicht lesbar")

    monkeypatch.setattr(cg.sqlite3, "connect", boom)
    res = cg.get_consensus_history()
    assert isinstance(res, dict)
    assert res["status"] == "error"
    assert res["error_code"] == "CONSENSUS_HISTORY_READ_FAILED"
    assert res["history"] == []


def test_consensus_history_ok_reports_status(monkeypatch):
    from backend import consensus_gate as cg

    # Eine gemeinsame `:memory:`-Verbindung, sonst sieht der Leser eine andere
    # (leere) Datenbank als der Schreiber.
    conn = cg.sqlite3.connect(":memory:")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consensus_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, task_title TEXT,
                mode TEXT, approved INTEGER, verdict TEXT, avg_score REAL,
                votes_json TEXT, critique TEXT, created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO consensus_decisions (votes_json) VALUES (?)", ("not json",)
        )
    monkeypatch.setattr(cg.sqlite3, "connect", lambda *a, **k: conn)
    res = cg.get_consensus_history()
    assert res["status"] == "ok"
    assert res["count"] == 1
    assert res["history"][0]["votes_parse_error"] is True
