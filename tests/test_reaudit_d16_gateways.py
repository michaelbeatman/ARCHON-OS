"""Re-Audit R-B6 / D16 — Trace-Kontext an den Gateways.

Statische Absicherung der vier betroffenen Grenzen (Hermes, MCP inbound,
MCP-SSE-Frames, SSE -> Telegram) plus kleine Unit-Tests fuer Span-Forking und
Kontext-Extraktion. Kein Replay, keine Migration.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_TRACEPARENT_RE = re.compile(
    r"traceparent[\"']?\s*[:=]\s*[\"']?\s*(00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2})",
    re.IGNORECASE,
)


def _source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _reset_trace() -> None:
    from backend import trace_context as tc

    tc._current_trace.set("")
    tc._current_span.set("")
    tc._current_tracestate.set("")
    tc._current_sampled.set(None)


# ---------------------------------------------------------------------------
# Statische Belege
# ---------------------------------------------------------------------------


def test_hermes_proxy_injects_with_child_span():
    src = _source("archon/routers/hermes_proxy.py")
    assert "with child_span(incoming=incoming_tp):" in src
    child_at = src.index("with child_span(incoming=incoming_tp):")
    inject_at = src.index("fwd_headers = inject_headers(fwd_headers)")
    assert inject_at > child_at


def test_mcp_gateway_extracts_inbound_context_and_keeps_response_headers():
    src = _source("backend/mcp_gateway.py")
    assert "def bind_incoming_trace_context(headers" in src
    assert "extract_headers(headers)" in src
    assert "start_trace(" in src
    assert src.index("bind_incoming_trace_context(headers)") < src.index(
        "def get_tool_definitions"
    )
    router_src = _source("archon/routers/mcp_gateway.py")
    assert "_mcp_trace_headers()" in router_src


def test_sse_generator_opens_context_per_frame_and_logs_cancel_warning():
    src = _source("archon/routers/mcp_gateway.py")
    assert "def _sse_frame_trace()" in src
    assert "with child_span()" in src
    assert "traceparent=" in src  # Endpoint-Frame: traceparent in der data:-Zeile
    assert 'json.dumps(frame)' in src  # Keepalive-Frame: traceparent in der data:-Zeile
    assert "use_trace_context(" in src
    assert "except asyncio.CancelledError" in src
    assert "abgebrochen (trace_id=%s)" in src
    assert "_archon_exc_logger.warning(" in src
    assert "Ignorierte Ausnahme (Z.113)" not in src


def test_decisions_consume_sse_traceparent_and_telegram_has_child_span():
    src = _source("archon/routers/decisions.py")
    assert "def _consume_sse_trace(" in src
    assert "parse_traceparent(tp)" in src
    assert "with _consume_sse_trace(extra):" in src
    assert "with _consume_sse_trace(body):" in src
    tg_src = _source("telegram_notify.py")
    assert "with child_span():" in tg_src
    assert "inject_headers()" in tg_src


# ---------------------------------------------------------------------------
# Unit-Tests
# ---------------------------------------------------------------------------


def test_mcp_inbound_context_is_set(monkeypatch):
    from backend import trace_context as tc
    from backend.mcp_gateway import bind_incoming_trace_context

    _reset_trace()
    tid, sid = "a" * 32, "b" * 16
    tp = tc.format_traceparent(tid, sid)
    bind_incoming_trace_context({"traceparent": tp, "tracestate": "vendor=alpha"})

    assert tc.current_trace_id() == tid
    assert tc.current_span_id() == sid
    assert tc.current_tracestate() == "vendor=alpha"
    # Ungueltige Header duerfen eine aktive Kette nicht kapern.
    bind_incoming_trace_context({"traceparent": "garbage", "tracestate": "vendor=beta"})
    assert tc.current_trace_id() == tid
    _reset_trace()


def test_hermes_proxy_outbound_uses_new_span_id(monkeypatch):
    from starlette.requests import Request

    from archon.routers import hermes_proxy as hp
    from backend import trace_context as tc

    class _FakeResp:
        status_code = 200
        content = b'{"ok":true}'
        headers = {"Content-Type": "application/json"}

    captured: dict = {}

    class _FakeClient:
        async def request(self, method, url, headers=None, content=None):
            captured["headers"] = dict(headers or {})
            return _FakeResp()

    monkeypatch.setattr(hp, "_hermes_proxy_token", lambda: "tok-test")
    monkeypatch.setattr(hp, "_get_hermes_client", lambda: _FakeClient())

    incoming_tp = tc.format_traceparent("c" * 32, "d" * 16, sampled=True)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/static/hermes-webui/api/health",
        "query_string": b"",
        "headers": [
            (b"traceparent", incoming_tp.encode("ascii")),
            (b"tracestate", b"vendor=gamma"),
        ],
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    _reset_trace()
    resp = asyncio.run(hp.forward_to_hermes(Request(scope, _receive)))
    outbound = captured["headers"]["traceparent"]
    out_tid, out_sid = tc.parse_traceparent(outbound)

    assert resp.status_code == 200
    assert out_tid == "c" * 32
    assert out_sid != "d" * 16
    assert captured["headers"]["tracestate"] == "vendor=gamma"
    _reset_trace()


def test_sse_frames_have_distinct_span_ids_in_same_trace(monkeypatch):
    from starlette.requests import Request

    from archon.routers import mcp_gateway as mg
    from backend import trace_context as tc

    monkeypatch.setattr(mg, "_authenticate_mcp_request", lambda request: {})

    class _FakeAsyncio:
        CancelledError = asyncio.CancelledError

        @staticmethod
        async def sleep(_seconds):
            return None

    monkeypatch.setattr(mg, "asyncio", _FakeAsyncio)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp/sse",
        "query_string": b"",
        "headers": [],
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request(scope, _receive)
    req.is_disconnected = _fake_is_disconnected

    _reset_trace()
    root_tid = "e" * 32
    tc.start_trace(tc.format_traceparent(root_tid, "f" * 16))

    async def _two_frames():
        response = await mg.mcp_sse_stream(req)
        stream = response.body_iterator
        first = await stream.__anext__()
        second = await stream.__anext__()
        await stream.aclose()
        return response, first, second

    resp, first, second = asyncio.run(_two_frames())
    match1 = _TRACEPARENT_RE.search(first)
    match2 = _TRACEPARENT_RE.search(second)
    assert match1 and match2, (first, second)

    tp1, tp2 = match1.group(1), match2.group(1)
    parsed1, parsed2 = tc.parse_traceparent(tp1), tc.parse_traceparent(tp2)
    assert parsed1 and parsed2
    assert parsed1[0] == parsed2[0] == root_tid
    assert parsed1[1] != parsed2[1]
    assert resp.headers.get("X-Trace-Id") == root_tid
    _reset_trace()


async def _fake_is_disconnected() -> bool:
    return False


def test_runtime_broadcast_forks_span_per_event():
    from archon.core import runtime
    from backend import trace_context as tc

    _reset_trace()
    tc.start_trace(tc.format_traceparent("1" * 32, "2" * 16))
    ctx1 = runtime._sse_trace_context()
    ctx2 = runtime._sse_trace_context()
    assert tc.parse_traceparent(ctx1["traceparent"])
    assert ctx1["trace_id"] == ctx2["trace_id"] == "1" * 32
    assert ctx1["span_id"] != ctx2["span_id"]
    assert tc.current_span_id() == "2" * 16  # Kontext wiederhergestellt
    _reset_trace()


def test_decision_consumes_sse_traceparent_without_leaking_context():
    from archon.routers import decisions
    from backend import trace_context as tc

    _reset_trace()
    base_tp = tc.format_traceparent("3" * 32, "4" * 16)
    tc.start_trace(base_tp)
    incoming_tp = tc.format_traceparent("5" * 32, "6" * 16)

    with decisions._consume_sse_trace(
        {"data": {"traceparent": incoming_tp, "tracestate": "vendor=delta"}}
    ):
        assert tc.current_trace_id() == "5" * 32
        assert tc.current_span_id() == "6" * 16
        assert tc.current_tracestate() == "vendor=delta"

    assert tc.current_trace_id() == "3" * 32
    assert tc.current_span_id() == "4" * 16

    # Ungueltige Werte werden verworfen, ohne die Kette zu wechseln.
    with decisions._consume_sse_trace({"traceparent": "not-a-traceparent"}):
        assert tc.current_trace_id() == "3" * 32
    _reset_trace()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
