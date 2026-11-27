# -*- coding: utf-8 -*-
"""W5-F: trace_id/span_id/traceparent ueber Delegation, Audit, Log und Vault.

Rein implementierende Regressionstests (Produzent → Konsument → Effekt →
Verifikation). Keine PostgreSQL-Migration, kein Coroutine-/Event-Replay,
keine echten Secrets — alle Keys sind neutrale Placeholder.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRACE_ID = "a" * 32
SPAN_ID = "b" * 16
TRACEPARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"


def _ctx(tc, trace_id: str = TRACE_ID, span_id: str = SPAN_ID):
    return tc.use_trace_context(
        trace_id=trace_id,
        span_id=span_id,
        traceparent=tc.format_traceparent(trace_id, span_id, True),
        sampled=True,
    )


def _stub_delegation_server_helpers(monkeypatch, d) -> None:
    """DB-freie, deterministische Server-Werte (Trace-SSOT bleibt echt)."""
    monkeypatch.setattr(d, "_server_tenant_id", lambda: "default")
    monkeypatch.setattr(d, "_server_taint_status", lambda session: "unknown")
    monkeypatch.setattr(d, "_server_budget_remaining_tokens", lambda tid: 0)
    monkeypatch.setattr(
        d,
        "_server_budget_allocation",
        lambda tid: {"complexity_weight": 1.0, "budget_share_pct": 0.0, "token_budget": 0},
    )


# ---------------------------------------------------------------------------
# D16-M2 — signierte Delegations-Payload + created-Event + Resume
# ---------------------------------------------------------------------------


def test_m2_server_overwrites_client_trace_context_and_signs_it(monkeypatch):
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w5f-dlg-key-" + "c" * 48)
    from archon.core import delegation as d
    from backend import trace_context as tc

    _stub_delegation_server_helpers(monkeypatch, d)
    foreign_tp = "00-" + "f" * 32 + "-" + "e" * 16 + "-01"
    with _ctx(tc):
        ctx = d._server_delegation_trace_context({
            "trace_id": "f" * 32,
            "span_id": "e" * 16,
            "traceparent": foreign_tp,
        })
    assert ctx == {"trace_id": TRACE_ID, "span_id": SPAN_ID, "traceparent": TRACEPARENT}

    with _ctx(tc):
        payload = d.canonicalize_delegation_payload({
            "ziel_agent": "coder",
            "auftrag": "Fix W5-F",
            "trace_id": "f" * 32,
            "span_id": "e" * 16,
            "traceparent": foreign_tp,
        }, task_id="t-w5f-m2")
    assert payload["trace_id"] == TRACE_ID
    assert payload["span_id"] == SPAN_ID
    assert payload["traceparent"] == TRACEPARENT
    assert d.verify_delegation_payload(payload) is True
    tampered = dict(payload)
    tampered["span_id"] = "c" * 16
    assert d.verify_delegation_payload(tampered) is False


def test_m2_legacy_signature_without_span_fields_still_verifies(monkeypatch):
    """In-flight Delegationen von vor dem Fix bleiben verifizierbar."""
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w5f-dlg-key-" + "c" * 48)
    from archon.core import delegation as d

    legacy = {"ziel_agent": "coder", "auftrag": "x", "trace_id": TRACE_ID}
    legacy["payload_signature"] = d.sign_delegation_payload(legacy)
    assert d.verify_delegation_payload(legacy) is True
    # Leere neue Felder (Schema-Defaults) ändern den signierten Umfang nicht.
    with_empty = dict(legacy, span_id="", traceparent="")
    assert d.verify_delegation_payload(with_empty) is True
    # Ein gesetzter Wert ist dagegen signiert und nicht manipulierbar.
    with_span = dict(legacy, span_id=SPAN_ID, traceparent=TRACEPARENT)
    assert d.verify_delegation_payload(with_span) is False


def test_m2_created_event_json_keeps_trace_after_signature_check(monkeypatch):
    """Der als created-Event gespeicherte JSON-String ist die SSOT für Resume."""
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w5f-dlg-key-" + "c" * 48)
    from archon.core import delegation as d
    from backend import trace_context as tc

    _stub_delegation_server_helpers(monkeypatch, d)
    with _ctx(tc):
        produced = d.canonicalize_delegation_payload(
            {"ziel_agent": "coder", "auftrag": "x"}, task_id="t-w5f-event"
        )
    stored = json.dumps(produced, ensure_ascii=False, default=str)
    loaded = d.load_verified_delegation_payload(
        stored, require_signature=True, task_id="t-w5f-event"
    )
    assert loaded["trace_id"] == TRACE_ID
    assert loaded["span_id"] == SPAN_ID
    assert loaded["traceparent"] == TRACEPARENT


def test_m2_resume_watcher_inherits_persisted_trace(monkeypatch):
    """Der Resume-Pfad setzt den Kontext VOR dem Spawn des Watchers."""
    import backend.operations_api as ops
    import backend.trajectory_budget as tb
    from archon.core import delegation as d
    from backend import trace_context as tc

    row = ("task-w5f-resume", "coder", "proj", json.dumps({
        "via": "delegation_engine_v2",
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "traceparent": TRACEPARENT,
        "trajectory_id": "traj-w5f",
        "delegator": "robert",
    }))

    class _FakeConn:
        def execute(self, *args, **kwargs):
            return self

        def fetchall(self):
            return [row]

        def close(self):
            return None

    captured: dict = {}

    def _fake_spawn(coro, name=""):
        captured["trace_id"] = tc.current_trace_id()
        captured["span_id"] = tc.current_span_id()
        coro.close()  # kein "never awaited"
        return None

    monkeypatch.setattr(ops, "_get_kanban_connection", lambda: _FakeConn())
    monkeypatch.setattr(tb, "normalize_trajectory_id", lambda *a: "traj-w5f")
    monkeypatch.setattr(tb, "get_trajectory", lambda tid: {"visited_agents": "[]"})
    monkeypatch.setattr(tb, "ensure_trajectory", lambda *a: None)
    monkeypatch.setattr(d, "_put_chain", lambda *a, **k: None)
    monkeypatch.setattr(d, "_ACTIVE_WATCHERS", set())
    monkeypatch.setattr(d, "_spawn_background", _fake_spawn)

    with _ctx(tc, trace_id="c" * 32, span_id="d" * 16):
        n = asyncio.run(d.resume_pending_delegation_watchers())

    assert n == 1
    assert captured == {"trace_id": TRACE_ID, "span_id": SPAN_ID}


# ---------------------------------------------------------------------------
# D16-M3 — Audit-Log: span_id Spalte, HMAC, Index, Fallback
# ---------------------------------------------------------------------------


def test_m3_audit_persists_signed_span_id_and_index(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "w5f-audit-key-" + "d" * 48)
    from backend import audit_log as al
    from backend import trace_context as tc

    db = str(tmp_path / "audit.db")
    log = al.ChainedAuditLog(db_path=db)
    with _ctx(tc):
        ev = log.record_llm_dispatch(
            agent_id="coder",
            provider="local",
            model="test-model",
            target_endpoint="http://127.0.0.1:11434/v1/chat/completions",
            trace_id=TRACE_ID,
            span_id=SPAN_ID,
        )

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT trace_id, span_id, payload_json FROM audit_log WHERE id = ?",
            (ev["event_id"],),
        ).fetchone()
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_audit_log_span_id'"
        ).fetchone()

    assert row[0] == TRACE_ID
    assert row[1] == SPAN_ID
    # span_id liegt im signierten payload_json (raw_str enthält payload_str).
    assert json.loads(row[2])["span_id"] == SPAN_ID
    assert index is not None
    assert log.verify_integrity()["valid"] is True


def test_m3_explicit_span_wins_over_active_span(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "w5f-audit-key-" + "d" * 48)
    from backend import audit_log as al
    from backend import trace_context as tc

    log = al.ChainedAuditLog(db_path=str(tmp_path / "audit2.db"))
    explicit = "e" * 16
    with _ctx(tc):
        ev_explicit = log.record_event(
            category="system", action="probe_explicit", agent_id="system",
            payload={}, trace_id=TRACE_ID, span_id=explicit,
        )
        ev_fallback = log.record_event(
            category="system", action="probe_fallback", agent_id="system", payload={}
        )
    with sqlite3.connect(log.db_path) as conn:
        explicit_span = conn.execute(
            "SELECT span_id FROM audit_log WHERE id = ?", (ev_explicit["event_id"],)
        ).fetchone()[0]
        fallback_span = conn.execute(
            "SELECT span_id FROM audit_log WHERE id = ?", (ev_fallback["event_id"],)
        ).fetchone()[0]
    assert explicit_span == explicit
    assert fallback_span == SPAN_ID


def test_m3_legacy_audit_db_gets_span_id_column(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "w5f-audit-key-" + "d" * 48)
    from backend import audit_log as al

    db = str(tmp_path / "legacy-audit.db")
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, category TEXT NOT NULL,
                action TEXT NOT NULL, event_type TEXT, agent_id TEXT NOT NULL,
                company_id TEXT DEFAULT 'default', provider TEXT DEFAULT '',
                model TEXT DEFAULT '', target_host TEXT DEFAULT '',
                target_endpoint TEXT DEFAULT '', egress_zone TEXT DEFAULT '',
                trace_id TEXT DEFAULT '', session_id TEXT DEFAULT '',
                correlation_id TEXT DEFAULT '', payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL, current_hash TEXT NOT NULL
            )
        """)
    log = al.ChainedAuditLog(db_path=db)
    assert "span_id" in log.cols
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_audit_log_span_id'"
        ).fetchone()
    assert "span_id" in cols
    assert idx is not None


# ---------------------------------------------------------------------------
# D16-M4 — Log-Brücke: Record + Prefix + Promtail-Label
# ---------------------------------------------------------------------------


def test_m4_log_filter_injects_span_id_and_does_not_double_prefix():
    from backend import trace_context as tc
    from backend.trace_log_filter import TraceIdFilter

    trace_filter = TraceIdFilter()
    record = logging.LogRecord(
        "w5f", logging.INFO, "p.py", 1, "hello %s", ("world",), None
    )
    with _ctx(tc):
        assert trace_filter.filter(record) is True
    assert getattr(record, "trace_id", "") == TRACE_ID
    assert getattr(record, "span_id", "") == SPAN_ID
    expected = f"[trace_id={TRACE_ID} span_id={SPAN_ID}] hello world"
    assert record.getMessage() == expected

    trace_filter.filter(record)
    assert record.getMessage() == expected

    plain = logging.LogRecord("w5f", logging.INFO, "p.py", 2, "plain", (), None)
    trace_filter.filter(plain)
    assert getattr(plain, "trace_id", "") == ""
    assert getattr(plain, "span_id", "") == ""
    assert plain.getMessage() == "plain"


def test_m4_promtail_regex_extracts_span_label():
    cfg = (ROOT / "config" / "promtail" / "promtail-config.yml").read_text(
        encoding="utf-8"
    )
    match = re.search(r"expression: '([^']+)'", cfg)
    assert match is not None
    pattern = re.compile(match.group(1))
    line_with_span = (
        f"2026-11-27 10:00:00 - backend.trace - INFO - "
        f"[trace_id={TRACE_ID} span_id={SPAN_ID}] dispatch ok"
    )
    parsed = pattern.match(line_with_span)
    assert parsed is not None
    assert parsed.group("trace_id") == TRACE_ID
    assert parsed.group("span_id") == SPAN_ID

    legacy_line = (
        f"2026-11-27 10:00:00 - backend.trace - INFO - "
        f"[trace_id={TRACE_ID}] dispatch ok"
    )
    legacy = pattern.match(legacy_line)
    assert legacy is not None
    assert not legacy.group("span_id")
    assert re.search(r"^\s+span_id:\s*$", cfg, re.MULTILINE) is not None


# ---------------------------------------------------------------------------
# D16-M5 — Vault-Dossier + Kanban-Sidecar: Trace-Frontmatter
# ---------------------------------------------------------------------------


def test_m5_dossier_writes_validated_trace_frontmatter(tmp_path):
    from dossier_builder import build_dossier_from_report

    out = tmp_path / "dossier"
    html_path = build_dossier_from_report(
        "Review W5-F", "# Ergebnis", str(out), "t1_review",
        ref_id="t1", quelle="Archon-Delegation",
        trace_id=TRACE_ID, span_id=SPAN_ID, traceparent=TRACEPARENT,
    )
    assert html_path and Path(html_path).exists()
    sidecar = out / "t1_review.trace.md"
    assert sidecar.exists()
    content = sidecar.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert f'trace_id: "{TRACE_ID}"' in content
    assert f'span_id: "{SPAN_ID}"' in content
    assert f'traceparent: "{TRACEPARENT}"' in content
    html = Path(html_path).read_text(encoding="utf-8")
    assert TRACE_ID in html and SPAN_ID in html

    # Ungueltige IDs erzeugen kein leeres Sidecar (Rueckwaertskompatibilitaet).
    out2 = tmp_path / "dossier2"
    build_dossier_from_report("x", "y", str(out2), "x", trace_id="not-hex")
    assert not (out2 / "x.trace.md").exists()


def test_m5_kanban_sidecar_stores_trace_without_losing_data(tmp_path, monkeypatch):
    from backend import kanban_sidecar as ks

    monkeypatch.setattr(ks, "KANBAN_META_FILE", str(tmp_path / "kanban_meta.json"))
    monkeypatch.setattr(ks, "_cross_process_lock", contextlib.nullcontext)

    stored = ks.set_task_trace_context(
        "task-w5f", trace_id=TRACE_ID, span_id=SPAN_ID,
        traceparent=TRACEPARENT, source="delegation_review",
    )
    assert stored["trace_id"] == TRACE_ID
    meta = ks.load_kanban_meta()
    assert meta["tasks"]["task-w5f"]["trace"]["traceparent"] == TRACEPARENT

    # Idempotent: eine zweite, teilweise Aktualisierung behaelt span_id.
    ks.set_task_trace_context("task-w5f", trace_id="f" * 32)
    meta = ks.load_kanban_meta()
    trace = meta["tasks"]["task-w5f"]["trace"]
    assert trace["trace_id"] == "f" * 32
    assert trace["span_id"] == SPAN_ID
    assert ks.set_task_trace_context("task-w5f", trace_id="ungueltig") is None


def test_m5_delegation_caller_wires_vault_and_resume_context():
    """Statischer Vertrag: Produktivpfad nutzt die neuen Parameter/Helfer."""
    source = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    dossier_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_dossier_from_report"
    ]
    assert dossier_calls
    keywords = {kw.arg for kw in dossier_calls[0].keywords}
    assert {"trace_id", "span_id", "traceparent"}.issubset(keywords)

    resume = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "resume_pending_delegation_watchers"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resume_trace_context"
        for node in ast.walk(resume)
    )
