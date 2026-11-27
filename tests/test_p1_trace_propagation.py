# -*- coding: utf-8 -*-
"""
P1 Distributed Tracing Tests (D16):
- W3C traceparent / child_span / inject_payload
- OTelTracer W3C 32-hex/16-hex IDs, parent_span_id, OTLP /v1/traces JSON, status
- Outbound traceparent + trace_id propagation across dispatcher, agent_router,
  llm_egress_guard, n8n webhook, hermes_proxy & operations_dag status endpoint.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


def _span_id_of(traceparent: str) -> str:
    """Child-Span aus einem W3C-traceparent lesen (P1: eigene Kausalkante)."""
    parts = str(traceparent or "").split("-")
    assert len(parts) == 4, f"ungueltiges traceparent: {traceparent!r}"
    return parts[2]


def test_trace_context_child_span_and_inject_payload():
    from backend import trace_context as tc

    root_tid, root_sid = tc.start_trace()
    assert len(root_tid) == 32
    assert len(root_sid) == 16

    with tc.child_span() as (tid, sid, parent_sid):
        assert tid == root_tid
        assert len(sid) == 16
        assert sid != root_sid
        assert parent_sid == root_sid
        payload = tc.inject_payload({"action": "publish"})
        assert payload["trace_id"] == root_tid
        assert payload["span_id"] == sid

    assert tc.current_trace_id() == root_tid
    assert tc.current_span_id() == root_sid


def test_otel_tracer_uses_w3c_ids_and_builds_otlp_payload(tmp_path, monkeypatch):
    from backend import trace_context as tc
    from backend.otel_tracer import OpenTelemetryTracer, get_tracing_status

    db_file = str(tmp_path / "otel_p1.db")
    tr = OpenTelemetryTracer(db_path=db_file)

    incoming_tid = "a" * 32
    incoming_sid = "b" * 16
    tc.start_trace(tc.format_traceparent(incoming_tid, incoming_sid))

    tr_id = tr.start_trace("test.root", task_id="task-p1")
    assert tr_id == incoming_tid

    sp_id = tr.record_span(
        trace_id=tr_id,
        name="llm.call",
        span_type="llm",
        agent_id="senior_coder",
        model="deepseek-chat",
        input_tokens=10,
        output_tokens=20,
        duration_ms=42.5,
    )
    assert len(sp_id) == 16
    tr.end_trace(tr_id, status="OK")

    tree = tr.get_trace_tree(tr_id)
    assert tree is not None
    assert tree["span_count"] == 1
    assert tree["spans"][0]["parent_span_id"] == incoming_sid

    otlp = tr._build_otlp_payload(tree)
    span_out = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span_out["traceId"] == incoming_tid
    assert span_out["spanId"] == sp_id
    assert span_out["parentSpanId"] == incoming_sid

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    st = get_tracing_status()
    assert st["configured"] is True
    assert st["otlp_configured"] is True
    assert st["target"] == "otlp"


def test_n8n_execution_injects_trace_id_and_traceparent(monkeypatch):
    import core_dispatcher as cd
    from backend import trace_context as tc

    tid, sid = tc.start_trace()
    captured = {}

    class _FakeResp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, content=None, headers=None, **kwargs):
            captured["url"] = url
            captured["body"] = json.loads(content.decode("utf-8"))
            captured["headers"] = dict(headers or {})
            return _FakeResp()

    monkeypatch.setattr(cd.httpx, "AsyncClient", lambda *a, **kw: _FakeClient())
    res = asyncio.run(
        cd.trigger_n8n_execution(
            parent_project_id="proj-1",
            title="Test",
            final_report_path="out.md",
            content="hello",
        )
    )
    # HTTP 200 ohne executionId ist keine bestaetigte Ausfuehrung mehr — kein
    # Fake-'warning'/success, sondern explizit 'unconfirmed'.
    assert res["status"] == "unconfirmed"
    assert res["error_code"] == "N8N_DELIVERY_UNCONFIRMED"
    # P1: der Hop erzeugt jetzt einen eigenen Child-Span (kein Self-Parenting).
    child_sid = _span_id_of(captured["headers"]["traceparent"])
    assert child_sid != sid
    assert captured["body"]["trace_id"] == tid
    assert captured["body"]["span_id"] == child_sid
    assert captured["headers"]["traceparent"].startswith(f"00-{tid}-{child_sid}-")


def test_agent_router_injects_traceparent_and_records_audit_trace_id(tmp_path, monkeypatch):
    import datetime
    import sqlite3

    import backend.role_budget_engine as rbe
    from backend import privacy_router as pr
    from backend import trace_context as tc
    from backend.agent_router import AgentRouter
    from backend.audit_log import ChainedAuditLog

    tid, sid = tc.start_trace()
    alog = ChainedAuditLog(db_path=str(tmp_path / "router_p1.db"))
    monkeypatch.setattr("backend.llm_egress_guard.chained_audit_log", alog)

    # W3-D/F032: der Chat-Pfad ist fail-closed ohne registriertes Task-Cap.
    # Der Test prueft Trace-Header/Audit-Korrelation, nicht das Budget-Gate —
    # daher hier eine echte Allokation in einer Temp-DB anlegen.
    budget_db = str(tmp_path / "router_p1_budget.db")
    rbe.init_budget_tables(db_path=budget_db)
    monkeypatch.setattr(rbe.budget_bank, "db_path", budget_db)
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(budget_db) as conn:
        conn.execute(
            "INSERT INTO task_budget_allocations "
            "(task_id, agent_id, token_budget, tokens_used, cost_limit_eur, cost_used_eur, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, 0.0, ?, ?)",
            ("test-p1-trace", "software_architect", 50000, 100.0, now, now),
        )
        conn.commit()

    cfg = dict(pr.DEFAULT_PRIVACY_CONFIG)
    cfg["zero_egress_strict"] = False
    cfg["sensitive_local_routing"] = False

    router = AgentRouter()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {}
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"choices": [{"message": {"content": "OK"}}]}

    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         patch("backend.llm_egress_guard.get_privacy_config", return_value=cfg), \
         patch.object(router, "_get_shared_client", return_value=fake_client), \
         patch.object(router, "_daily_spend_usd", return_value=(0.0, True)), \
         patch("backend.compliance_engine.compliance_engine.check_activation_allowed", return_value={"allowed": True}):
        out = asyncio.run(
            router.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                provider="openai",
                model="gpt-4o-mini",
                api_keys={"OPENAI_API_KEY": "sk-test-dummy"},
                agent_id="software_architect",
                role="Engineering",
                task_id="test-p1-trace",
            )
        )
    assert out == "OK"
    sent_headers = fake_client.post.call_args.kwargs["headers"]
    child_sid = _span_id_of(sent_headers["traceparent"])
    assert child_sid != sid
    assert sent_headers["traceparent"].startswith(f"00-{tid}-{child_sid}-")
    import sqlite3
    with sqlite3.connect(alog.db_path) as con:
        rows = con.execute("SELECT trace_id FROM audit_log WHERE category = 'llm_dispatch'").fetchall()
    assert rows and rows[0][0] == tid


def test_hermes_proxy_propagates_traceparent(monkeypatch):
    from starlette.requests import Request

    from archon.routers import hermes_proxy as hp
    from backend import trace_context as tc

    class _FakeResp:
        status_code = 200
        content = b'{"ok":true}'
        headers = {"Content-Type": "application/json"}

    captured = {}

    class _FakeClient:
        async def request(self, method, url, headers=None, content=None):
            captured["headers"] = dict(headers or {})
            return _FakeResp()

    monkeypatch.setattr(hp, "_hermes_proxy_token", lambda: "tok-test")
    monkeypatch.setattr(hp, "_get_hermes_client", lambda: _FakeClient())

    incoming_tp = tc.format_traceparent("c" * 32, "d" * 16)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/static/hermes-webui/api/health",
        "query_string": b"",
        "headers": [(b"traceparent", incoming_tp.encode("ascii"))],
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request(scope, _receive)
    tc._current_trace.set("")
    tc._current_span.set("")
    resp = asyncio.run(hp.forward_to_hermes(req))
    assert resp.status_code == 200
    child_sid = _span_id_of(captured["headers"].get("traceparent", ""))
    assert child_sid != "d" * 16
    assert captured["headers"]["traceparent"].startswith(f"00-{'c' * 32}-{child_sid}-")
    assert resp.headers.get("traceparent") == captured["headers"]["traceparent"]


def test_operations_dag_tracing_status_endpoint(admin_rbac_bypass):
    from fastapi.testclient import TestClient

    import main as app_main

    client = TestClient(app_main.app)
    r = client.get("/api/operations/traces/otel/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("configured", "not_configured")
    assert body["local_trace_db"] is True
