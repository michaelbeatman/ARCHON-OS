# -*- coding: utf-8 -*-
"""Re-Audit D16 / R-B6 (H6, H7, M2, M3): OTel-Sampling, Export-Kontext,
Log-/Loki-/Prometheus-Bruecke und kein synthetischer zweiter Root."""

from __future__ import annotations

import io
import json
import logging
import re
import sqlite3
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def tracer(tmp_path):
    from backend.otel_tracer import OpenTelemetryTracer

    tr = OpenTelemetryTracer(db_path=str(tmp_path / "reaudit_d16.db"))
    yield tr
    tr.shutdown(wait=True)


def _tp(tid: str, sid: str, sampled: bool = True) -> str:
    from backend import trace_context as tc

    return tc.format_traceparent(tid, sid, sampled=sampled)


def _payload_spans(tr, tree):
    return tr._build_otlp_payload(tree)["resourceSpans"][0]["scopeSpans"][0]["spans"]


def test_h6_unsampled_incoming_trace_creates_no_span_and_no_payload(tracer):
    from backend import trace_context as tc

    tid, sid = "a" * 32, "b" * 16
    tc.start_trace(_tp(tid, sid, sampled=False))
    assert tc.current_sampled() is False

    trace_id = tracer.start_trace("unsampled.root")
    assert trace_id == tid
    assert tracer.record_span(trace_id, "llm.call", "llm") == ""
    assert tracer.get_trace_tree(trace_id)["span_count"] == 0
    assert _payload_spans(tracer, tracer.get_trace_tree(trace_id)) == []
    assert tracer._record_stats["sampled_out"] >= 1


def test_h6_sampled_flag_is_persisted_and_exported(tracer):
    from backend import trace_context as tc

    tid, sid = "c" * 32, "d" * 16
    tc.start_trace(_tp(tid, sid, sampled=True))
    trace_id = tracer.start_trace("sampled.root")
    span_id = tracer.record_span(trace_id, "llm.call", "llm")
    assert re.fullmatch(r"[0-9a-f]{16}", span_id)

    tree = tracer.get_trace_tree(trace_id)
    attrs = json.loads(tree["spans"][0]["attributes_json"])
    assert attrs["archon.sampled"] is True

    span_out = _payload_spans(tracer, tree)[0]
    sampled_attrs = [a for a in span_out["attributes"] if a["key"] == "archon.sampled"]
    assert sampled_attrs and sampled_attrs[0]["value"]["boolValue"] is True


def test_payload_uses_persisted_flag_only(monkeypatch, tracer):
    from backend import trace_context as tc

    tc.start_trace(_tp("e" * 32, "f" * 16, sampled=True))
    tree = {
        "trace_id": "e" * 32,
        "name": "mixed",
        "start_time": "2026-11-24T10:00:00+00:00",
        "spans": [
            {"span_id": "1" * 16, "attributes_json": json.dumps({"archon.sampled": False})},
            {"span_id": "2" * 16, "attributes_json": "{}"},
        ],
    }
    spans = _payload_spans(tracer, tree)
    assert [s["spanId"] for s in spans] == ["2" * 16]
    assert all(a["value"]["boolValue"] for a in spans[0]["attributes"] if a["key"] == "archon.sampled")


def test_m2_export_thread_keeps_trace_context(monkeypatch, tracer):
    from backend import trace_context as tc

    class _NoopResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    tid, sid = "9" * 32, "8" * 16
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _NoopResponse())

    # Deterministischer Single-Worker-Pool, damit der Sentinel alle vorherigen
    # Exporte abschliesst.
    tracer._export_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="d16_test")
    seen: dict = {}
    original = tracer._build_otlp_payload

    def _spy(tree):
        seen["trace_id"] = tc.current_trace_id()
        seen["sampled"] = tc.current_sampled()
        return original(tree)

    monkeypatch.setattr(tracer, "_build_otlp_payload", _spy)

    tc.start_trace(_tp(tid, sid, sampled=False))
    trace_id = tracer.start_trace("context.root")
    # Explizit gesampelter Legacy-Span: der Export muss trotzdem den
    # unsampelten Request-Kontext des Aufrufers sehen.
    tracer.record_span(trace_id, "legacy.span", "llm", attributes={"archon.sampled": True})
    tracer.end_trace(trace_id)
    tracer._export_pool.submit(lambda: None).result()

    assert seen["trace_id"] == tid
    assert seen["sampled"] is False


def test_m3_no_random_second_root_in_otlp_fallback(tracer):
    empty = {"trace_id": "a" * 32, "name": "empty", "status": "OK", "spans": []}
    assert _payload_spans(tracer, empty) == []

    known = dict(empty, span_id="1" * 16)
    spans = _payload_spans(tracer, known)
    assert len(spans) == 1
    assert spans[0]["spanId"] == "1" * 16


def test_h7_trace_filter_injects_trace_id_and_promtail_matches():
    from backend import trace_context as tc
    from backend.trace_log_filter import TraceIdFilter

    tid, _ = tc.start_trace(_tp("4" * 32, "5" * 16, sampled=True))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    handler.addFilter(TraceIdFilter())
    log = logging.getLogger("d16.test.trace")
    log.handlers[:] = [handler]
    log.propagate = False
    log.setLevel(logging.INFO)
    log.info("dispatch done %s", 7)

    line = stream.getvalue().strip()
    assert f"[trace_id={tid}] dispatch done 7" in line
    assert handler.filters[0].inject_message is True

    promtail = (ROOT / "config" / "promtail" / "promtail-config.yml").read_text(encoding="utf-8")
    expression = re.search(r"expression:\s*'(.+)'", promtail).group(1)
    match = re.search(expression, line)
    assert match is not None
    assert match.group("trace_id") == tid


def test_h7_static_config_bridge_and_honest_langfuse(monkeypatch):
    from backend.otel_tracer import get_tracing_status

    promtail = (ROOT / "config" / "promtail" / "promtail-config.yml").read_text(encoding="utf-8")
    assert "(?P<trace_id>[0-9a-f]{32})" in promtail
    assert re.search(r"labels:\s*\n(?:\s+\w+:\s*\n)*\s+trace_id:", promtail)

    prometheus = (ROOT / "config" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    assert re.search(r"storage:\s*\n\s+exemplars:\s*\n\s+max_exemplars:\s*\d+", prometheus)

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "--enable-feature=exemplar-storage" in compose

    collector = (ROOT / "config" / "otel-collector-config.yml").read_text(encoding="utf-8")
    assert "langfuse:3000" not in collector
    assert "OTEL_DOWNSTREAM_OTLP_ENDPOINT" not in collector

    for key in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    status = get_tracing_status()
    assert status["langfuse_status"] == "not_configured"
    assert "langfuse-not-configured" in status["langfuse_note"]
