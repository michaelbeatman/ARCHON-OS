# -*- coding: utf-8 -*-
"""Regressionstests zu den MED-Funden aus reaudit/domain_16.md + domain_01.md.

Scope dieses Subagenten: ausschliesslich diese neue Testdatei sowie die
Ownership-Dateien (Collector-Config, Trace-Log-Filter, Config-/Secrets-Skripte).
Gesperrte Produktivdateien werden nicht verändert; die Tests dokumentieren und
verifizieren nur den Stand der MED-Funde.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# D01/MED — nachweislich ehrliche (fail-closed) Pfade
# ---------------------------------------------------------------------------

def test_d01_m1_eval_gate_fails_closed_on_quality_error(monkeypatch):
    """Ein interner Fehler des Anti-Slop-Checks darf keine Freigabe erzeugen."""
    import backend.content_machine as cm
    from backend.eval_gates import _evaluate_text_item

    def _boom(_asset):
        raise RuntimeError("quality backend unavailable")

    monkeypatch.setattr(cm, "evaluate_asset_quality", _boom)
    res = _evaluate_text_item(
        {"id": "med-d01-m1", "min_score": 0.0},
        "Wir sichern die Liquiditaet und senken operative Kosten nachhaltig.",
        latency_ms=1.0,
        cost_usd=0.0,
    )
    assert res["passed"] is False
    assert res["anti_slop_score"] == 0.0
    assert any("Anti-Slop" in f for f in res["failures"])


def test_d01_m5_empty_tool_result_is_an_error():
    """None/leerer Tool-Output wird nicht zum Literal 'None' im LLM-Kontext."""
    from backend.tool_output_firewall import guard_tool_output

    guarded = guard_tool_output("terminal", None)
    assert guarded["status"] == "error"
    assert guarded["error"] == "EMPTY_TOOL_RESULT"
    assert guarded["output"] == ""
    assert "None" not in guarded["output"]
    assert guard_tool_output("terminal", "   \n")["status"] == "error"
    assert guard_tool_output("terminal", "echter Output")["status"] == "ok"


def test_d01_m5_batch_keeps_empty_result_error_status():
    """Der Batch-Orchestrator darf den Guard-Status nicht mit 'ok' ueberschreiben."""
    from backend.tool_output_firewall import run_batch_tool_calls

    async def _executor(_name, _args):
        return None

    result = asyncio.run(run_batch_tool_calls([{"tool": "terminal", "args": {}}], _executor))
    assert result[0]["status"] == "error"
    assert result[0]["error"] == "EMPTY_TOOL_RESULT"


def test_d01_m4_mission_capture_has_no_prognosed_subagent_count():
    """Beim Capture ist subagents_count 0 + Quellenmarker, keine Prognose 3/1."""
    src = _src("archon/routers/mission_control.py")
    assert '"subagents_count": 0' in src
    assert '"subagents_count_source": "none_yet"' in src
    # Die Triageschaetzung ist explizit als `estimated_*` markiert, nicht als
    # gemessener `subagents_count`-Wert.
    assert 'estimated_subagents = 3 if' in src


def test_d01_m7_eval_release_is_declared_advisory():
    """release_approved ist ein Diagnosewert ohne Promotion-Konsument."""
    src = _src("backend/eval_regression_runner.py")
    assert '"advisory_only": True' in src
    assert '"release_gate_consumer": None' in src


# ---------------------------------------------------------------------------
# D16/MED — bereits verdrahteter SSE-Frame-Kontext (nur Verifikation)
# ---------------------------------------------------------------------------

def test_d16_m5_sse_generator_opens_own_trace_context():
    """SSE-Frames tragen einen eigenen Child-Span; CancelledError ist sichtbar."""
    src = _src("archon/routers/mcp_gateway.py")
    generator = src[src.index("async def _event_generator"):]
    assert "_sse_frame_trace()" in generator
    assert "traceparent=" in generator
    assert "asyncio.CancelledError" in generator
    assert "_archon_exc_logger.warning(" in generator


# ---------------------------------------------------------------------------
# Eigene Ownership — Observability-Invarianten (D16)
# ---------------------------------------------------------------------------

def test_owned_collector_config_has_no_dead_default_downstream():
    src = _src("config/otel-collector-config.yml")
    assert "${OTEL_DOWNSTREAM_OTLP_ENDPOINT:-http://langfuse" not in src
    assert "file/traces-local" in src
    assert "exporters: [debug, file/traces-local]" in src


def test_owned_collector_config_drops_unsampled_spans():
    src = _src("config/otel-collector-config.yml")
    assert "filter/unsampled" in src
    assert "attributes[\"archon.sampled\"] == false" in src
    assert "filter/unsampled" in src.split("pipelines:", 1)[1]


def test_owned_trace_log_filter_injects_valid_trace_id():
    from backend.trace_context import use_trace_context
    from backend.trace_log_filter import TraceIdFilter

    tid = "a" * 32
    tp = f"00-{tid}-{'b' * 16}-01"
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    with use_trace_context(traceparent=tp):
        assert TraceIdFilter().filter(record) is True
    assert record.trace_id == tid
    assert "hello" in record.getMessage()
