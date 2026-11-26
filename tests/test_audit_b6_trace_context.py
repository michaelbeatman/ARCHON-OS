"""Audit B6: W3C Trace Context Kern und Audit-Korrelation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_w3c_parse_format_roundtrip():
    from backend import trace_context as tc

    trace_id, span_id = tc.new_ids()
    assert len(trace_id) == 32 and len(span_id) == 16
    header = tc.format_traceparent(trace_id, span_id)
    assert tc.parse_traceparent(header) == (trace_id, span_id)
    assert tc.parse_traceparent("00-" + "0" * 32 + "-" + span_id + "-01") is None
    assert tc.parse_traceparent("garbage") is None


def test_contextvars_inject_extract():
    from backend import trace_context as tc

    trace_id, span_id = tc.start_trace()
    assert tc.extract_headers({"TraceParent": tc.format_traceparent(trace_id, span_id)})
    injected = tc.inject_headers({"Authorization": "Bearer x"})
    assert injected["traceparent"].startswith("00-")
    assert injected["Authorization"] == "Bearer x"


def test_middleware_and_audit_wiring():
    from backend import trace_context as tc

    main_text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "TraceContextMiddleware" in main_text
    rt_text = (ROOT / "archon" / "services" / "runtime_endpoints.py").read_text(encoding="utf-8")
    assert "response_trace_headers" in rt_text
    assert "_response_trace_headers(dict(response.headers))" in rt_text
    assert 'response.headers["X-Trace-Id"]' not in rt_text

    tid, sid = tc.start_trace()
    headers = tc.response_trace_headers({"Content-Type": "application/json"})
    assert headers["X-Trace-Id"] == tid
    assert headers["traceparent"].startswith(f"00-{tid}-{sid}-")
    assert headers["Content-Type"] == "application/json"

    audit_text = (ROOT / "backend" / "audit_log.py").read_text(encoding="utf-8")
    assert "current_trace_id" in audit_text
    provider_text = (ROOT / "api_provider.py").read_text(encoding="utf-8")
    assert "inject_headers" in provider_text
