# -*- coding: utf-8 -*-
"""W4-D2 — Restpunkte aus Welle 4 (Domain 16, MED).

Abgedeckt:
  * Span-Produzenten delegation / tool / gate + Replay-Konsument
  * Exemplar-Korrelation pro (metric_name, series_labels)
  * Altfehler: n8n-_httpx_transport ohne inject_headers

Alle Tests arbeiten ausschliesslich mit ``tmp_path`` und monkeypatches.
Es wird NIE gegen ``./data`` geschrieben (siehe INCIDENT 2026-11-25).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Span-Produzenten (D16/MED)
# ---------------------------------------------------------------------------

def test_delegation_launch_records_delegation_span_with_parent():
    src = _source("archon/core/delegation.py")
    assert 'span_type="delegation"' in src
    assert "parent_span_id=_parent_span" in src
    assert "delegation.child_task_id" in src
    # Kein Self-Parenting: der Parent kommt aus dem aktiven Kontext, nicht
    # aus der neu erzeugten Span-ID.
    assert "_parent_span = str(current_span_id() or \"\")" in src
    assert "note_local_trace_error(\"delegation-span\"" in src


def test_tool_runtime_finalize_records_tool_span(monkeypatch):
    import backend.tool_runtime as tr
    from backend import trace_context as tc

    tid, _sid = tc.start_trace()
    captured = []

    class _FakeTracer:
        def record_span(self, trace_id, name, span_type, **kwargs):
            captured.append((trace_id, name, span_type, kwargs))

    import backend.otel_tracer as otel

    monkeypatch.setattr(otel, "tracer", _FakeTracer())
    # D12/H1: guard_result() liefert jetzt per Default das VOLLSTAENDIGE Urteil
    # (status/error_code/result), damit Konsumenten Firewall-Fehler nicht
    # versehentlich als Erfolg durchreichen.
    verdict = tr.guard_result("read_file", "harmloser Inhalt")
    hardened = verdict["result"] if isinstance(verdict, dict) else verdict
    # Der Firewall-Chokepoint haelt den Inhalt in Untrusted-Delimitern —
    # entscheidend ist hier nur, dass der Finalize einen echten tool-Span
    # mit dem richtigen Namen und Urteil geschrieben hat.
    assert isinstance(hardened, str) and "harmloser Inhalt" in hardened
    assert captured, "Tool-Finalize hat keinen Span produziert"
    _trace, name, span_type, kwargs = captured[-1]
    assert _trace == tid
    assert name == "tool.read_file"
    assert span_type == "tool"
    assert kwargs["attributes"]["tool.name"] == "read_file"
    assert kwargs["status"] == "OK"


def test_tool_runtime_blocked_call_records_error_span(monkeypatch):
    import backend.tool_runtime as tr
    from backend import trace_context as tc

    tc.start_trace()
    captured = []
    monkeypatch.setattr(
        tr, "_record_tool_span",
        lambda tool, **kwargs: captured.append((tool, kwargs)),
    )
    monkeypatch.setattr(
        "backend.delegation_isolation.policy_engine.decide",
        lambda **kw: {"allowed": False, "reason": "scope_denied", "gate": "rbac"},
    )
    out = tr.enforce_tool_execution(agent_id="a", tool_name="pay")
    assert out["allowed"] is False
    assert captured and captured[0][0] == "pay"
    assert captured[0][1]["status"] == "ERROR"


def test_dag_gate_nodes_get_gate_span_type():
    src = _source("backend/workflow_dag_runner.py")
    assert "requires_gate = ntype == \"gate\" or bool(node.get(\"require_hitl\"))" in src
    assert 'span_type="gate" if _is_gate else "agent"' in src
    assert '"gate.decision"' in src


def test_eval_fixture_filter_includes_new_span_types():
    src = _source("backend/eval_gates.py")
    assert '"delegation", "gate"' in src
    assert '"llm", "agent", "tool"' in src


def test_three_new_span_types_are_really_persisted(tmp_path, monkeypatch):
    """D16/MED/§0: Produzent + Effekt + Verifikation im echten Span-Recorder."""
    import sqlite3

    import backend.otel_tracer as otel
    from backend import trace_context as tc

    tracer = otel.OpenTelemetryTracer(db_path=str(tmp_path / "otel.db"))
    monkeypatch.setattr(otel, "tracer", tracer)
    tid, parent_sid = tc.start_trace()
    tracer.start_trace("test.root", "task-1", "agent-1", trace_id=tid)
    for span_type in ("delegation", "tool", "gate"):
        tracer.record_span(
            trace_id=tid,
            name=f"{span_type}.check",
            span_type=span_type,
            parent_span_id=parent_sid,
            attributes={"verification": "w4-d2"},
        )
    with sqlite3.connect(tracer.db_path) as conn:
        rows = conn.execute(
            "SELECT span_type, parent_span_id FROM otel_spans WHERE trace_id = ?", (tid,)
        ).fetchall()
    persisted = {row[0] for row in rows}
    assert {"delegation", "tool", "gate"} <= persisted
    assert all(row[1] == parent_sid for row in rows)


# ---------------------------------------------------------------------------
# 2. Replay-Konsument (D16/MED)
# ---------------------------------------------------------------------------

def test_replay_endpoint_is_wired_to_dispatcher_and_hitl():
    src = _source("archon/routers/v2_capabilities.py")
    assert '@router.post("/api/v2/eval/traces/{trace_id}/replay")' in src
    assert "replay_and_evaluate" in src
    assert "consume_hitl_proof_token" in src
    assert "require_admin_or_503(request)" in src
    assert "require_session_actor(request)" in src
    # Kein Fake-Executor: der Replay laeuft ueber den produktiven Dispatcher.
    assert "dispatch_to_omniroute_or_container" in src
    assert "REPLAY_DISPATCH_INVALID_RESULT" in src
    assert "asyncio.run(" in src


# ---------------------------------------------------------------------------
# 3. Exemplar-Korrelation (D16/MED)
# ---------------------------------------------------------------------------

_TID_ERROR = "a" * 32
_TID_OK = "b" * 32
_SID = "1" * 16


def test_exemplar_ring_buffer_is_keyed_by_metric_and_series(monkeypatch):
    import backend.metrics_collector as mc

    monkeypatch.setattr(mc, "_TRACE_EXEMPLARS", {})
    mc.record_trace_exemplar(
        "archon_agent_dispatches_total",
        trace_id=_TID_ERROR, span_id=_SID,
        labels={"route": "/api/x", "status": 500},
    )
    mc.record_trace_exemplar(
        "archon_agent_dispatches_total",
        trace_id=_TID_OK, span_id=_SID,
        labels={"route": "/api/y", "status": 200},
    )

    error_line = mc._exemplar_line("archon_agent_dispatches_total", 1, {"status": "error"})
    ok_line = mc._exemplar_line("archon_agent_dispatches_total", 2, {"status": "ok"})
    assert _TID_ERROR in error_line
    assert _TID_OK not in error_line
    assert _TID_OK in ok_line
    assert _TID_ERROR not in ok_line
    # Kein Fallback auf eine fremde Serie.
    assert mc._exemplar_line("archon_agent_dispatches_total", 0, {"status": "other"}) == ""


def test_unlabelled_metric_uses_empty_series_and_no_fake_exemplar(monkeypatch):
    import backend.metrics_collector as mc

    monkeypatch.setattr(mc, "_TRACE_EXEMPLARS", {})
    mc.record_trace_exemplar(
        "archon_tokens_total", trace_id=_TID_OK, span_id=_SID,
        labels={"span_type": "hop"},
    )
    line = mc._exemplar_line("archon_tokens_total", 42)
    assert _TID_OK in line
    assert mc._exemplar_line("archon_agent_dispatches_total", 0, {"status": "error"}) == ""


def test_render_attaches_exemplar_to_matching_status_series(monkeypatch):
    import backend.metrics_collector as mc

    monkeypatch.setattr(mc, "_TRACE_EXEMPLARS", {})
    mc.record_trace_exemplar(
        "archon_agent_dispatches_total",
        trace_id=_TID_ERROR, span_id=_SID,
        labels={"route": "/fail", "status": 503},
    )
    rendered = mc.MetricsCollector().generate_prometheus_metrics()
    ok_row = [ln for ln in rendered.splitlines() if ln.startswith('archon_agent_dispatches_total{status="ok"}')]
    err_row = [ln for ln in rendered.splitlines() if ln.startswith('archon_agent_dispatches_total{status="error"}')]
    assert len(ok_row) == 1 and len(err_row) == 1
    assert _TID_ERROR in err_row[0]
    assert _TID_ERROR not in ok_row[0]


# ---------------------------------------------------------------------------
# 4. Altfehler: n8n-Transport ohne Trace-Injektion
# ---------------------------------------------------------------------------

def test_httpx_transport_injects_trace_when_outbox_has_none(monkeypatch):
    import asyncio

    import core_dispatcher as cd
    from backend import trace_context as tc

    tid, _sid = tc.start_trace()
    captured: dict = {}

    class _FakeResp:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b'{"executionId":"exec-1"}'

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, target, content, headers):
            captured["headers"] = dict(headers)
            return _FakeResp()

    monkeypatch.setattr(cd.httpx, "AsyncClient", lambda **_kw: _FakeClient())

    async def _fake_emit(url, event_type, payload, **kwargs):
        transport = kwargs["transport"]
        # Simuliert den Outbox-Fehlerfall ohne traceparent — der Transport
        # muss dann selbst einen Child-Span injizieren.
        await transport(url, "POST", {"Content-Type": "application/json"}, b"{}", 1.0)
        return {
            "status": "delivered", "ack_confirmed": True, "http_status": 200,
            "response": '{"executionId":"exec-1"}', "outbox_id": 7,
        }

    import backend.event_mesh as em

    monkeypatch.setattr(em.event_mesh, "emit_outbound_event_async", _fake_emit)
    res = asyncio.run(cd.trigger_n8n_execution("proj", "title", "out.md", "content"))
    assert res["status"] == "success"
    tp = captured["headers"].get("traceparent", "")
    assert tp.startswith(f"00-{tid}-")
    assert tp.split("-")[2] != "0" * 16


def test_httpx_transport_keeps_outbox_span_when_present(monkeypatch):
    import asyncio

    import core_dispatcher as cd

    outbox_tp = f"00-{'c' * 32}-{'d' * 16}-01"
    captured: dict = {}

    class _FakeResp:
        status_code = 200
        headers = {}
        content = b"{}"

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, target, content, headers):
            captured["headers"] = dict(headers)
            return _FakeResp()

    monkeypatch.setattr(cd.httpx, "AsyncClient", lambda **_kw: _FakeClient())

    # Direkter Aufruf des verschachtelten Transports ueber den Outbox-Pfad:
    # der gesetzte traceparent darf NICHT geforkt werden.
    async def _fake_emit2(url, event_type, payload, **kwargs):
        await kwargs["transport"](
            url, "POST", {"Content-Type": "application/json", "traceparent": outbox_tp},
            b"{}", 1.0,
        )
        return {
            "status": "delivered", "ack_confirmed": True, "http_status": 200,
            "response": '{"executionId":"exec-2"}', "outbox_id": 8,
        }

    import backend.event_mesh as em

    monkeypatch.setattr(em.event_mesh, "emit_outbound_event_async", _fake_emit2)
    asyncio.run(cd.trigger_n8n_execution("proj", "title", "out.md", "content"))
    assert captured["headers"]["traceparent"] == outbox_tp
