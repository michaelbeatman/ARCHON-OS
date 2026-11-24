# -*- coding: utf-8 -*-
"""Re-Audit D16 (R-B6): Receipts, Sampling-Flag, Audit-Bruecke.

Rein implementierende Regressionstests: keine Migration, kein Replay.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRACE_ID = "a" * 32
SPAN_ID = "b" * 16
TRACEPARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"


def _set_context(tc, sampled: bool = True):
    """Deterministischer, gemockter Request-Kontext (wie eingehender traceparent)."""
    return tc.use_trace_context(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        traceparent=tc.format_traceparent(TRACE_ID, SPAN_ID, sampled),
        sampled=sampled,
    )


def test_receipt_trace_id_equals_audit_trace_id_after_dispatch(tmp_path, monkeypatch):
    """Receipt und Audit-Event tragen nach dem Dispatch dieselbe W3C-Trace-ID."""
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "d16-audit-key-" + "c" * 48)
    # parentbased_traceidratio mit ratio 0: ohne explizites Flag wuerde die
    # Sampling-Entscheidung im Dispatch auf 00 kippen.
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0")

    from backend import audit_log, execution_receipt_ledger as erl
    from backend import llm_kernel, trace_context as tc
    import core_dispatcher

    ledger = erl.ExecutionReceiptLedger(db_path=str(tmp_path / "receipts.db"))
    audit_db = str(tmp_path / "audit.db")
    audit = audit_log.ChainedAuditLog(db_path=audit_db)

    observed: dict = {}

    async def _fake_otel_start(*args, **kwargs):
        return None  # kein zweiter (OTel-)Root; aktiver W3C-Kontext bleibt

    async def _fake_otel_noop(*args, **kwargs):
        return None

    async def _fake_dispatch(**kwargs):
        # Das Audit-Event entsteht im Dispatcher — ohne explizite trace_id.
        event = audit.record_event(
            category="llm_dispatch",
            action="llm_call_dispatched",
            agent_id="coder",
            payload={"provider": "local", "model": "test-model"},
        )
        observed["sampled"] = tc.current_sampled()
        observed["traceparent"] = tc.inject_headers()["traceparent"]
        observed["event_id"] = event["event_id"]
        return {"status": "ok", "content": "done", "model": "test-model"}

    monkeypatch.setattr(llm_kernel, "_otel_start", _fake_otel_start)
    monkeypatch.setattr(llm_kernel, "_otel_span", _fake_otel_noop)
    monkeypatch.setattr(llm_kernel, "_otel_end", _fake_otel_noop)
    monkeypatch.setattr(
        core_dispatcher, "dispatch_to_omniroute_or_container", _fake_dispatch
    )

    with _set_context(tc, sampled=True):
        result = asyncio.run(llm_kernel.dispatch_llm(agent_id="coder", prompt="test"))
        receipt = ledger.issue_receipt(
            "task-1", "coder", "test-model", 10, 5, 0.001, ["read"]
        )

    with sqlite3.connect(audit_db) as conn:
        audit_trace_id = conn.execute(
            "SELECT trace_id FROM audit_log WHERE id = ?", (observed["event_id"],)
        ).fetchone()[0]

    assert result["trace_id"] == TRACE_ID
    assert receipt["issued"] is True
    assert receipt["trace_id"] == audit_trace_id == TRACE_ID
    assert receipt["span_id"] == SPAN_ID
    assert receipt["traceparent"] == TRACEPARENT

    # M1: incoming `...-01` bleibt trotz ratio=0 gesampelt.
    assert observed["sampled"] is True
    assert observed["traceparent"].endswith("-01")

    # Globale Head-Anker aus der Standard-DB gehoeren nicht zu dieser Test-DB;
    # die lokale Kette und der Export-Pfad werden deshalb direkt geprueft.
    assert ledger._verify_chain_integrity_raw()["chain_valid"] is True
    verify = ledger.verify_chain_integrity()
    assert verify["trace_context"][0]["trace_id"] == TRACE_ID


def test_legacy_receipt_table_gets_columns_idempotently(tmp_path, monkeypatch):
    """Bestands-DB ohne Trace-Spalten: ALTER ist idempotent, Kette bleibt gueltig."""
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "d16-legacy-key-" + "d" * 48)
    from backend import execution_receipt_ledger as erl

    db = str(tmp_path / "legacy_receipts.db")
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE execution_receipts_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT UNIQUE, task_id TEXT, agent_role TEXT,
                model_used TEXT, prompt_tokens INTEGER, completion_tokens INTEGER,
                cost_usd REAL, tools_invoked_json TEXT, prev_hash TEXT,
                receipt_hash TEXT, created_at TEXT
            )
        """)
        conn.commit()

    erl._init_db(db)
    erl._init_db(db)  # zweiter Lauf darf nicht scheitern

    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(execution_receipts_ledger)"
        ).fetchall()}
    assert {"trace_id", "span_id", "traceparent"} <= cols

    from backend import trace_context as tc

    with _set_context(tc):
        receipt = erl.ExecutionReceiptLedger(db_path=db).issue_receipt(
            "legacy-1", "coder", "model", 10, 5, 0.001, ["read"]
        )
    assert receipt["issued"] is True
    assert receipt["trace_id"] == TRACE_ID
    ledger = erl.ExecutionReceiptLedger(db_path=db)
    assert ledger._verify_chain_integrity_raw()["chain_valid"] is True
    assert ledger.verify_chain_integrity()["trace_context"][0]["trace_id"] == TRACE_ID


def test_audit_picks_trace_id_from_receipt_or_event_context(tmp_path, monkeypatch):
    """Background-Audit ohne Kontext: trace_id kommt aus dem Receipt-Payload."""
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "d16-bridge-key-" + "e" * 48)
    from backend import audit_log, trace_context as tc

    audit_db = str(tmp_path / "audit_bridge.db")
    audit = audit_log.ChainedAuditLog(db_path=audit_db)
    ambient = tc.current_trace_id()

    # Kein Kontext, aber ein Receipt im Payload -> keine neue Root-ID.
    event = audit.record_event(
        category="receipt_bridge",
        action="receipt_issued",
        agent_id="system",
        payload={"task_id": "t-1", "receipt": {"trace_id": TRACE_ID, "span_id": SPAN_ID}},
    )
    with sqlite3.connect(str(tmp_path / "audit_bridge.db")) as conn:
        assert conn.execute(
            "SELECT trace_id FROM audit_log WHERE id = ?", (event["event_id"],)
        ).fetchone()[0] == TRACE_ID

    # traceparent im Event-Kontext reicht ebenfalls aus.
    event2 = audit.record_event(
        category="receipt_bridge",
        action="receipt_issued",
        agent_id="system",
        payload={"event": {"traceparent": TRACEPARENT}},
    )
    with sqlite3.connect(str(tmp_path / "audit_bridge.db")) as conn:
        assert conn.execute(
            "SELECT trace_id FROM audit_log WHERE id = ?", (event2["event_id"],)
        ).fetchone()[0] == TRACE_ID

    # Ohne Payload-Kontext wird hoechstens der bereits aktive Kontext
    # uebernommen — niemals eine neue Root-ID erfunden.
    event3 = audit.record_event(
        category="receipt_bridge", action="noop", agent_id="system", payload={}
    )
    with sqlite3.connect(audit_db) as conn:
        assert conn.execute(
            "SELECT trace_id FROM audit_log WHERE id = ?", (event3["event_id"],)
        ).fetchone()[0] == ambient


def test_session_receipt_carries_trace_context():
    """Delegations-Receipt + HTML-Export enthalten trace_id/span_id/traceparent."""
    from backend import session_receipts as sr, trace_context as tc

    with _set_context(tc):
        rec = sr.build_delegation_receipt("t-1", "coder", "done")
        html = sr.render_offline_html_receipt("t-1", "Test", "Auftrag", [])

    assert rec["trace_id"] == TRACE_ID
    assert rec["span_id"] == SPAN_ID
    assert rec["traceparent"] == TRACEPARENT
    assert TRACE_ID in html
    assert SPAN_ID in html
    assert TRACEPARENT in html


def test_note_local_trace_error_uses_one_central_api(tmp_path, monkeypatch):
    """M4: alle Aufrufer landen in der zentralen Fehlerzaehlung."""
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "d16-error-key-" + "f" * 48)
    import backend.otel_tracer as ot
    from backend import llm_kernel, trace_context as tc, workflow_dag_runner as wdr

    real = ot.OpenTelemetryTracer(db_path=str(tmp_path / "otel.db"))
    monkeypatch.setattr(ot, "tracer", real)
    before = dict(real._record_stats)

    tc.note_local_trace_error("stage-a", RuntimeError("a"))
    llm_kernel._note_trace_error("stage-b", RuntimeError("b"))
    wdr.note_local_trace_error("stage-c", RuntimeError("c"))

    assert real._record_stats["failures"] == before["failures"] + 3
    assert "stage-c" in real._record_stats["last_error"]


def test_no_local_note_fallback_and_no_rewritten_context():
    """Statisch: keine divergierenden Fallbacks mehr im Produktivpfad."""
    wdr_text = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    llm_text = (ROOT / "backend" / "llm_kernel.py").read_text(encoding="utf-8")

    assert "from backend.trace_context import note_local_trace_error" in wdr_text
    assert "except (ImportError, AttributeError)" not in wdr_text
    assert "from backend.trace_context import note_local_trace_error" in llm_text
    assert 'getattr(_tc, "note_local_trace_error"' not in llm_text
    assert "use_trace_context(trace_id=active_trace)" not in llm_text
    assert "sampled=ctx_sampled" in llm_text
