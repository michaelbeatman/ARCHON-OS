# -*- coding: utf-8 -*-
"""Remediation Welle 2 / W2-B — Silent-Failure-Schutz (F021, Domäne 12).

Regressionstests für H-12-1 … H-12-5 und die MED-Funde (Flight-Event,
epistemic_hygiene, deep_research_lab). Kein Test wird gelöscht oder geskippt;
alle externen Systeme werden gemockt.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _allow(monkeypatch):
    from backend import tool_runtime

    monkeypatch.setattr(
        tool_runtime, "enforce_tool_execution",
        lambda **kwargs: {"allowed": True, "tool": kwargs.get("tool_name")},
    )
    monkeypatch.setattr(tool_runtime, "record_tool_read_side_effect", lambda *a, **k: None)


def _fake_plugin(monkeypatch, result, *, exported=True):
    import backend.plugin_manager as pm_mod

    class FakePM:
        def get_all_exported_tools(self):
            return [{"name": "terminal"}] if exported else []

        async def execute_plugin_tool(self, name, args):
            return result

    monkeypatch.setattr(pm_mod, "get_plugin_manager", lambda: FakePM())


def _capture_flight(monkeypatch, db_path):
    import backend.flightlog_backtester as fb

    captured = []
    real = fb.record_flight_event

    def capture(**kwargs):
        captured.append(dict(kwargs))
        real(db_path=str(db_path), **kwargs)

    monkeypatch.setattr(fb, "record_flight_event", capture)
    return captured


# ---------------------------------------------------------------------------
# H-12-1 — Firewall-Status im Tool-Chokepoint (Plugin + MCP)
# ---------------------------------------------------------------------------

def test_h12_1_plugin_empty_result_becomes_error(monkeypatch, tmp_path):
    from backend import tool_runtime
    from backend.flightlog_backtester import detect_silent_failures

    _allow(monkeypatch)
    _fake_plugin(monkeypatch, None)
    db = tmp_path / "flight.db"
    events = _capture_flight(monkeypatch, db)

    res = asyncio.run(tool_runtime.execute_agent_tool(
        tool_name="terminal", session_id="s1",
        flightlog_run_id="w2b-plugin-empty",
    ))
    assert res["status"] == "error"
    assert res["error_code"] == "EMPTY_TOOL_RESULT"
    assert "TOOL-FEHLER" in str(res.get("result"))
    assert events and events[0]["tool_ok"] is False
    assert events[0]["error_code"] == "EMPTY_TOOL_RESULT"

    diag = detect_silent_failures(
        "w2b-plugin-empty", final_status="success",
        final_output="X" * 300, db_path=str(db),
    )
    assert diag["silent_failure"] is True
    assert any(f.startswith("hidden_tool_errors:") for f in diag["flags"])
    assert any(f.startswith("empty_tool_result:") for f in diag["flags"])


def test_h12_1_mcp_empty_result_becomes_error(monkeypatch, tmp_path):
    from backend import tool_runtime
    import scripts.archon_mcp_server as amcp

    _allow(monkeypatch)
    _fake_plugin(monkeypatch, None, exported=False)
    events = _capture_flight(monkeypatch, tmp_path / "flight.db")

    class FakeServer:
        def execute_tool(self, name, args):
            return None

    monkeypatch.setattr(amcp, "ArchonMcpServer", FakeServer)
    res = asyncio.run(tool_runtime.execute_agent_tool(
        tool_name="crm__read", session_id="s2",
        flightlog_run_id="w2b-mcp-empty",
    ))
    assert res["status"] == "error"
    assert res["error_code"] == "EMPTY_TOOL_RESULT"
    assert events and events[0]["tool_ok"] is False


def test_h12_1_guard_result_with_status_passes_firewall_verdict():
    from backend.tool_runtime import guard_result

    assert guard_result("terminal", None, with_status=True)["status"] == "error"
    ok = guard_result("terminal", {"value": "hello"}, with_status=True)
    assert ok["status"] == "ok"
    assert ok["result"]["value"] != "hello"  # in Untrusted-Delimiter gewrappt


# ---------------------------------------------------------------------------
# H-12-2 — sichtbarer Fehlermarker statt "", alle Leerwert-Formen
# ---------------------------------------------------------------------------

def test_h12_2_all_empty_shapes_are_visible_errors():
    from backend.tool_output_firewall import guard_tool_output, is_empty_tool_result
    from backend.tool_runtime import guard_result

    for empty in (None, "", "   ", {}, [], 0):
        assert is_empty_tool_result(empty) is True
        assert guard_tool_output("terminal", empty)["status"] == "error"
        guarded = str(guard_result("terminal", empty))
        assert "[TOOL-FEHLER" in guarded
        assert "EMPTY_TOOL_RESULT" in guarded

    # False ist ein gueltiges Boolean-Ergebnis, kein Fehler.
    assert is_empty_tool_result(False) is False


def test_h12_2_long_final_output_does_not_hide_empty_tool(tmp_path):
    from backend.flightlog_backtester import detect_silent_failures, record_flight_event

    db = str(tmp_path / "flight.db")
    record_flight_event(
        "w2b-long", "coder", "terminal", tool_ok=False,
        error_code="EMPTY_TOOL_RESULT", db_path=db,
    )
    diag = detect_silent_failures(
        "w2b-long", final_status="success",
        final_output="Sehr langer halluzinierter Finaltext. " * 20,
        db_path=db,
    )
    assert diag["silent_failure"] is True
    assert diag["empty_tool_results"] == 1
    assert any(f.startswith("hidden_tool_errors:") for f in diag["flags"])


# ---------------------------------------------------------------------------
# H-12-3 — Injection-Klassifikator-Exception fail-closed
# ---------------------------------------------------------------------------

def test_h12_3_classifier_exception_discards_raw_text(monkeypatch):
    import local_security_guard
    from backend.tool_output_firewall import guard_tool_output
    from backend.tool_runtime import guard_result

    def boom(*args, **kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(local_security_guard, "quarantine_external_text", boom)
    raw = "MEIN_ROHTEXT_MARKER_12345"

    guarded = guard_tool_output("web_fetch", raw)
    assert guarded["status"] == "error"
    assert guarded["error_code"] == "TOOL_OUTPUT_CLASSIFICATION_ERROR"
    assert raw not in str(guarded)

    via_chokepoint = guard_result("web_fetch", raw)
    assert raw not in str(via_chokepoint)
    assert "TOOL-FEHLER" in str(via_chokepoint)


# ---------------------------------------------------------------------------
# H-12-4 — n8n-Webhook: leerer/ungueltiger Body bei 2xx ist ein Fehler
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_webhook_transport(monkeypatch, body: bytes):
    import utils.egress_guard as eg
    import utils.safe_http as sh
    import urllib.request as ur

    monkeypatch.setenv("ARCHON_WEBHOOK_HMAC_SECRET", "test-secret")
    monkeypatch.setattr(eg, "check_target_url", lambda url, **kwargs: url)
    monkeypatch.setattr(sh, "webhook_signature_headers", lambda data: {})

    class FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(body)

    monkeypatch.setattr(ur, "build_opener", lambda *a, **k: FakeOpener())


def test_h12_4_empty_webhook_body_is_error(monkeypatch):
    from scripts.mcp_n8n_driver import N8nMcpDriver

    _patch_webhook_transport(monkeypatch, b"")
    res = N8nMcpDriver(base_url="http://n8n-test:5678")._http_post_json(
        "http://n8n-test:5678/webhook/x", {"a": 1}
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMPTY_WEBHOOK_BODY"


def test_h12_4_invalid_webhook_json_is_error(monkeypatch):
    from scripts.mcp_n8n_driver import N8nMcpDriver

    _patch_webhook_transport(monkeypatch, b"not json at all")
    res = N8nMcpDriver(base_url="http://n8n-test:5678")._http_post_json(
        "http://n8n-test:5678/webhook/x", {"a": 1}
    )
    assert res["status"] == "error"
    assert res["error_code"] == "INVALID_WEBHOOK_JSON"
    assert "not json at all" in res["data"]["raw_response"]


def test_h12_4_execute_webhook_never_acks_empty_body(monkeypatch):
    from scripts import mcp_n8n_driver as driver_mod

    monkeypatch.setattr(driver_mod.time, "sleep", lambda *a, **k: None)
    driver = driver_mod.N8nMcpDriver(base_url="http://n8n-test:5678")
    monkeypatch.setattr(driver, "_http_post_json", lambda *a, **k: {
        "status": "error", "error_code": "EMPTY_WEBHOOK_BODY",
        "status_code": 200, "error": "empty",
    })
    res = driver.execute_webhook("archon-test", {"a": 1}, max_retries=3)
    assert res["status"] == "error"
    assert res["error_code"] == "EMPTY_WEBHOOK_BODY"


# ---------------------------------------------------------------------------
# H-12-5 — CRM-Fehler sind keine leere Kontaktliste
# ---------------------------------------------------------------------------

def test_h12_5_crm_structured_results(monkeypatch):
    import requests
    from scripts import archon_crm_mcp as crm

    def fake_get(exc_or_response):
        def _get(url, timeout):
            if isinstance(exc_or_response, Exception):
                raise exc_or_response
            return exc_or_response
        return _get

    class Response:
        def __init__(self, payload, status=200, valid_json=True):
            self.status_code = status
            self._payload = payload
            self._valid_json = valid_json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

        def json(self):
            if not self._valid_json:
                raise ValueError("bad json")
            return self._payload

    monkeypatch.setattr(crm.requests, "get", fake_get(requests.exceptions.Timeout("timeout")))
    timed_out = crm.get_all_contacts()
    assert timed_out["status"] == "error"
    assert timed_out["error_code"] == "CRM_TIMEOUT"
    assert len(timed_out) == 0

    monkeypatch.setattr(crm.requests, "get", fake_get(Response({"items": []})))
    empty = crm.get_all_contacts()
    assert empty["status"] == "ok"
    assert empty["contacts"] == []

    monkeypatch.setattr(crm.requests, "get", fake_get(Response({})))
    missing = crm.get_all_contacts()
    assert missing["status"] == "error"
    assert missing["error_code"] == "MISSING_CRM_ITEMS"

    monkeypatch.setattr(crm.requests, "get", fake_get(Response(None, valid_json=False)))
    broken = crm.get_all_contacts()
    assert broken["error_code"] == "INVALID_CRM_JSON"

    monkeypatch.setattr(crm.requests, "get", fake_get(Response(None, status=503)))
    http_error = crm.get_all_contacts()
    assert http_error["error_code"] == "CRM_HTTP_ERROR"


def test_h12_5_cli_reports_error_status(monkeypatch, capsys):
    import requests
    from scripts import archon_crm_mcp as crm

    def boom(url, timeout):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(crm.requests, "get", boom)
    code = crm.main(["--get-contacts"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["status"] == "error"
    assert payload["error_code"] == "CRM_CONNECTION_ERROR"


# ---------------------------------------------------------------------------
# MED — Flight-Schreibfehler, epistemic hygiene, deep research
# ---------------------------------------------------------------------------

def test_med_flight_write_failure_is_an_error(monkeypatch, tmp_path):
    from backend import tool_runtime

    _allow(monkeypatch)
    _fake_plugin(monkeypatch, {"ok": True})
    monkeypatch.setattr(tool_runtime, "_record_tool_flight_event", lambda **kw: False)

    res = asyncio.run(tool_runtime.execute_agent_tool(
        tool_name="terminal", session_id="s3",
        flightlog_run_id="w2b-flight-fail",
    ))
    assert res["status"] == "error"
    assert res["error_code"] == "FLIGHTLOG_WRITE_FAILED"
    assert res["original_status"] == "success"


def test_med_epistemic_hygiene_reports_unreadable_files(monkeypatch, tmp_path):
    from backend.epistemic_hygiene import scan_vault_epistemic_hygiene

    good = tmp_path / "Gut.md"
    good.write_text("Preis: 100 EUR\n[[Verlinkung]]\n", encoding="utf-8")
    bad = tmp_path / "Gesperrt.md"
    bad.write_text("Preis: 999 EUR\n", encoding="utf-8")

    real_open = builtins.open

    def guarded_open(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(bad):
            raise OSError("permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    res = scan_vault_epistemic_hygiene(vault_path=str(tmp_path))
    assert res["status"] != "success"
    assert res["partial"] is True
    assert res["scanned_files"] == 1
    assert any("Gesperrt.md" in err for err in res["read_errors"])
    assert res["hygiene_score"] is None


def test_med_deep_research_uses_hostname_and_verifies(monkeypatch, tmp_path):
    from backend.deep_research_lab import (
        classify_source_tier, compile_research_dossier, triangulate_sources,
    )

    # Substring im Query darf keinen Trust-Tier vortaeuschen.
    assert classify_source_tier("https://evil.example/?ref=arxiv.org") == "tier3_web"
    assert classify_source_tier("https://arxiv.org/abs/1") == "tier1_primary"
    assert classify_source_tier("https://arxiv.org.evil.example/x") == "tier3_web"

    sources = [
        {"title": "Alpha Studie", "url": "https://a.example.org/paper"},
        {"title": "Beta Studie", "url": "https://b.example.org/paper"},
    ]
    failing = lambda url: {"ok": False, "error": "unreachable"}
    tri = triangulate_sources(sources, verify=True, fetcher=failing)
    assert tri["corroborated"] is False
    assert tri["confidence"] is None
    assert tri["unverified"] is True
    assert tri["status"] == "needs_human_review"

    working = lambda url: {
        "ok": True,
        "text": "Alpha Studie Beta Studie enthalten belastbare Daten.",
    }
    tri_ok = triangulate_sources(sources, verify=True, fetcher=working)
    assert tri_ok["corroborated"] is True
    assert tri_ok["confidence"] is not None
    assert tri_ok["confidence"] > 0
    assert tri_ok["status"] == "verified"

    dossier = compile_research_dossier(
        "Testthema", "Zwei Quellen bestaetigen.", sources,
        vault_dir=str(tmp_path), verify=True, fetcher=failing,
    )
    assert "UNVERIFIZIERT" in dossier["markdown"]
    assert dossier["triangulation"]["confidence"] is None


def test_structured_output_enforcer_never_fills_facts():
    from backend.structured_output_enforcer import structured_output_enforcer

    no_schema = structured_output_enforcer.validate_and_enforce('{"a": 1}')
    assert no_schema["valid"] is False
    empty = structured_output_enforcer.validate_and_enforce("", {"a": "int"})
    assert empty["valid"] is False
    missing = structured_output_enforcer.validate_and_enforce("{}", {"a": "int"})
    assert missing["valid"] is False
    assert missing["data"] == {}
