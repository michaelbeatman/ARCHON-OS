# -*- coding: utf-8 -*-
"""Remediation Welle 4 / W4-A — Distributed Tracing (F041, Domäne 16).

Regressionstests für H-16-1 … H-16-4 und die MED-Kontrakte. Alle Tests
schreiben ausschliesslich in temporäre Verzeichnisse (ARCHON_DATA_DIR),
nie gegen ./data — siehe INCIDENT_2026-11-25_LOGIN_OUTAGE.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Muss VOR dem Import von backend.db_paths/otel_tracer gesetzt sein.
_ARCHON_TEST_DATA = tempfile.mkdtemp(prefix="archon_w4a_")
os.environ.setdefault("ARCHON_DATA_DIR", _ARCHON_TEST_DATA)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture()
def temp_tracer(monkeypatch, tmp_path):
    """Tracer mit eigener Temp-DB; verhindert Schreiben in Produktions-DBs."""
    import backend.otel_tracer as ot

    tr = ot.OpenTelemetryTracer(db_path=str(tmp_path / "w4a_spans.db"))
    monkeypatch.setattr(ot, "tracer", tr)
    yield tr
    tr.shutdown(wait=True)


# ---------------------------------------------------------------------------
# H-16-1 — ehrlicher OTel-SDK-Status (keine halbe Lösung)
# ---------------------------------------------------------------------------

def test_h16_1_status_declares_no_otel_sdk(monkeypatch):
    from backend.otel_tracer import get_tracing_status

    for key in ("OTEL_EXPORTER_OTLP_ENDPOINT", "LANGFUSE_HOST",
                "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    status = get_tracing_status()
    assert status["otel_sdk"] is False
    assert status["otel_sdk_installed"] is False
    assert status["implementation"] == "w3c_trace_context_sqlite_recorder"
    assert "kein OTel-SDK" in status["implementation_note"]
    assert status["local_trace_db"] is True


def test_h16_1_no_sdk_pin_in_requirements():
    req = _src("requirements.txt")
    lock = _src("requirements.lock.txt")
    assert not re.search(r"^\s*opentelemetry-sdk\b", req, re.MULTILINE)
    assert not re.search(r"^\s*opentelemetry-sdk==", lock, re.MULTILINE)
    assert not re.search(r"^\s*opentelemetry-exporter-otlp-proto-http==", lock, re.MULTILINE)
    # Die bewusste Entscheidung ist dokumentiert, nicht verschwiegen.
    assert "kein OTel-SDK" in req or "KEIN OTel-SDK" in lock


# ---------------------------------------------------------------------------
# H-16-2 — Collector-Downstream, Tempo, Grafana, echter Compose-Default
# ---------------------------------------------------------------------------

def test_h16_2_collector_has_real_tempo_downstream():
    src = _src("config/otel-collector-config.yml")
    assert "otlphttp/downstream:" in src
    assert "endpoint: http://tempo:4318" in src
    pipelines = src.split("pipelines:", 1)[1]
    assert "traces/downstream:" in pipelines
    downstream = pipelines.split("traces/downstream:", 1)[1]
    assert "otlphttp/downstream" in downstream
    # Kein flüchtiger /tmp-Sink mehr ohne Volume.
    assert "path: /tmp/archon-otel-traces.json" not in src
    assert "OTEL_DOWNSTREAM_OTLP_ENDPOINT" not in src


def test_h16_2_compose_tempo_service_volume_and_real_default():
    import yaml

    compose = yaml.safe_load(_src("docker-compose.yml"))
    services = compose["services"]
    tempo = services["tempo"]
    assert tempo["image"].startswith("grafana/tempo:") and "@sha256:" in tempo["image"]
    assert "tempo_data:/var/tempo" in tempo["volumes"]
    assert "tracing" in tempo["profiles"]
    # Der Collector wartet auf ein gesundes Tempo (kein Export ins Leere).
    assert "tempo" in services["otel-collector"]["depends_on"]
    volumes = compose["volumes"]
    assert "tempo_data" in volumes and "otel_local_traces" in volumes
    assert "otel_local_traces:/var/lib/otel" in services["otel-collector"]["volumes"]
    env = services["archon-os"]["environment"]
    assert ("OTEL_EXPORTER_OTLP_ENDPOINT="
            "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://otel-collector:4318}") in env
    assert ("ARCHON_OTEL_COLLECTOR_DOWNSTREAM="
            "${ARCHON_OTEL_COLLECTOR_DOWNSTREAM:-tempo}") in env
    env_example = _src(".env.example")
    assert "OTEL_DOWNSTREAM_OTLP_ENDPOINT=" not in env_example
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318" in env_example


def test_h16_2_grafana_tempo_datasource_links_logs_and_metrics():
    import yaml

    docs = yaml.safe_load(_src("config/grafana/datasources/datasources.yml"))
    by_name = {d["name"]: d for d in docs["datasources"]}
    assert {"Prometheus", "Loki", "Tempo"}.issubset(by_name)
    tempo = by_name["Tempo"]
    assert tempo["type"] == "tempo"
    assert tempo["url"] == "http://tempo:3200"
    logs = tempo["jsonData"]["tracesToLogs"]
    metrics = tempo["jsonData"]["tracesToMetrics"]
    assert logs["datasourceUid"] == by_name["Loki"]["uid"]
    assert "trace_id" in logs["tags"] and logs["filterByTraceID"] is True
    assert metrics["datasourceUid"] == by_name["Prometheus"]["uid"]
    assert metrics["queries"]


# ---------------------------------------------------------------------------
# H-16-3 — n8n-MCP-Treiber: Kontext über Prozessgrenze + neue Signature
# ---------------------------------------------------------------------------

class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"queued":true}'


def test_h16_3_n8n_driver_injects_child_context_and_resigns(monkeypatch):
    import scripts.mcp_n8n_driver as drv

    monkeypatch.setenv("ARCHON_WEBHOOK_HMAC_SECRET", "w4a-test-secret")
    captured: dict = {}

    class _Opener:
        def open(self, req, timeout=None):
            captured["req"] = req
            return _FakeResponse()

    monkeypatch.setattr(drv.urllib.request, "build_opener", lambda *a, **k: _Opener())

    from backend import trace_context as tc
    tid, sid = tc.start_trace(tc.format_traceparent("a" * 32, "b" * 16))
    driver = drv.N8nMcpDriver(
        base_url="http://127.0.0.1:5678",
        incoming_traceparent=tc.format_traceparent(tid, sid),
    )
    res = driver.execute_webhook("archon-extract-article", {"url": "https://example.org"})
    assert res["status"] == "success"

    req = captured["req"]
    headers = {k.lower(): v for k, v in req.headers.items()}
    traceparent = headers["traceparent"]
    child_sid = traceparent.split("-")[2]
    assert traceparent.startswith(f"00-{tid}-")
    assert child_sid != sid

    body_bytes = req.data
    body = json.loads(body_bytes.decode("utf-8"))
    assert body["trace_id"] == tid
    assert body["span_id"] == child_sid
    assert res["trace_id"] == tid and res["span_id"] == child_sid

    # Signatur ueber den FINALEN (injizierten) Body — nicht ueber das Original.
    expected = hmac.new(b"w4a-test-secret", body_bytes, hashlib.sha256).hexdigest()
    assert headers["x-archon-webhook-signature"] == f"sha256={expected}"


def test_h16_3_meta_trace_context_is_accepted():
    import scripts.mcp_n8n_driver as drv

    ctx = drv._trace_context_from(
        {"traceContext": {"traceparent": "00-" + "c" * 32 + "-" + "d" * 16 + "-01"}}
    )
    assert ctx["trace_id"] == "c" * 32 and ctx["span_id"] == "d" * 16
    from_backend = drv._trace_context_from(
        {"traceContext": {"trace_id": "e" * 32, "span_id": "f" * 16}}
    )
    assert from_backend["traceparent"] == f"00-{'e' * 32}-{'f' * 16}-01"


# ---------------------------------------------------------------------------
# H-16-4 — serverseitiger PocketBase-Sync (CRM + Media-Inbox)
# ---------------------------------------------------------------------------

class _FakePBResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_h16_4_crm_pb_request_headers_trace_field_and_structured_errors(monkeypatch):
    import archon_crm_mcp as crm
    from backend import trace_context as tc

    tid, sid = tc.start_trace(tc.format_traceparent("1" * 32, "2" * 16))
    calls: list = []

    def fake_request(method, url, *, headers=None, timeout=None, json=None):
        calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json})
        if "perPage" in url:
            return _FakePBResponse({"items": [{"id": "rec-1"}]})
        return _FakePBResponse({"id": "rec-1"}, headers={"ETag": "rev-1"})

    monkeypatch.setattr(crm.requests, "request", fake_request)

    result = crm.get_all_contacts()
    assert result["status"] == "ok" and result["contacts"][0]["id"] == "rec-1"
    tp = calls[0]["headers"]["traceparent"]
    assert tp.startswith(f"00-{tid}-") and tp.split("-")[2] != sid

    assert crm.update_contact_email("rec-1", "a@example.org") is True
    patch_body = calls[1]["json"]
    assert patch_body["trace_id"] == tid
    assert "span_id" not in patch_body  # kein unbekanntes Collection-Feld

    assert crm.append_email_to_history("rec-1", {"messageId": "m-1"}) is True
    history_patch = [c for c in calls if c["method"] == "PATCH"][-1]["json"]
    assert history_patch["trace_id"] == tid

    # W2-B-Eskalation: Fehler ist KEIN leerer Erfolg.
    import requests
    def failing(*a, **k):
        raise requests.exceptions.Timeout("boom")
    monkeypatch.setattr(crm.requests, "request", failing)
    err = crm.get_all_contacts()
    assert err["status"] == "error" and err["error_code"] == "CRM_TIMEOUT"
    assert len(err) == 0  # Listen-Kompatibilitaet, aber sichtbarer Fehler


def test_h16_4_media_sync_adds_trace_field_and_headers(monkeypatch, tmp_path):
    import scripts.sync_inbox_to_pocketbase as sync
    from backend import trace_context as tc

    tid, sid = tc.start_trace(tc.format_traceparent("3" * 32, "4" * 16))
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"\x00\x00\x00ftyp")

    captured: dict = {}

    class _PBResponse:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id":"media-1"}'

    # D06/M2: pb_request() geht jetzt zwingend ueber
    # utils.safe_http.safe_http_request(..., public_only=True) und respektiert
    # POCKETBASE_ENABLED. Der Test fängt daher den zentralen HTTP-Helper ab.
    def _safe_request(url, *, method="GET", headers=None, data=None, **kwargs):
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        captured["data"] = data
        return 201, {}, b'{"id":"media-1"}'

    import utils.safe_http as safe_http
    monkeypatch.setattr(sync, "_pocketbase_enabled", lambda: True)
    monkeypatch.setattr(safe_http, "safe_http_request", _safe_request)
    monkeypatch.setattr(sync, "PB_URL", "http://127.0.0.1:8090")

    assert sync.upload_file(str(media)) is True
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers["traceparent"].startswith(f"00-{tid}-")
    assert headers["traceparent"].split("-")[2] != sid
    body = bytes(captured["data"]).decode("utf-8", errors="replace")
    assert f"name=\"trace_id\"\r\n\r\n{tid}\r\n" in body


# ---------------------------------------------------------------------------
# MED — Replay-Fixtures: echte Span-Typen + sichtbare Redaktionsfehler
# ---------------------------------------------------------------------------

def test_med_eval_gates_fixture_includes_delegation_and_gate_spans(temp_tracer, monkeypatch, tmp_path):
    import backend.eval_gates as eg
    from backend import trace_context as tc

    tid, _ = tc.start_trace()
    temp_tracer.start_trace("fixture.root", trace_id=tid)
    for span_type in ("llm", "agent", "tool", "delegation", "gate"):
        temp_tracer.record_span(tid, f"step.{span_type}", span_type)

    fixture = eg.build_fixture_from_trace(tid, db_path=str(tmp_path / "eval.db"))
    assert fixture is not None
    assert {s["type"] for s in fixture["steps"]} == {
        "llm", "agent", "tool", "delegation", "gate"
    }


def test_med_redaction_failure_is_counted(temp_tracer, monkeypatch):
    import backend.eval_gates as eg

    class _BrokenScrubber:
        def scrub_text(self, *a, **k):
            raise RuntimeError("scrubber down")

    monkeypatch.setitem(sys.modules, "backend.pii_scrubber", _BrokenScrubber())
    text = eg._redact_for_fixture("secret", "a" * 32)
    assert text == "[REDACTED_UNAVAILABLE]"
    assert temp_tracer._stage_failures.get("fixture-redaction-unavailable", 0) >= 1
