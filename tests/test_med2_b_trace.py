"""Re-Audit MED-Nachschub (Stage B/Trace): D05 Versions-Platzhalter,
D05 Audit-Schreibfehler-Sichtbarkeit und D16 Sampling-/Exportfehler.

Kein Migration/Replay. Alle Tests arbeiten mit temporaeren DBs und
monkeypatchten ENV/Logger.
"""

from __future__ import annotations

import logging
import os

import pytest


# ---------------------------------------------------------------------------
# D16/M1 — use_trace_context darf eine aktive Sampling-Entscheidung nicht
# neu wuerfeln (parentbased_traceidratio: -01 darf nicht auf -00 kippen).
# ---------------------------------------------------------------------------

def test_use_trace_context_preserves_active_sampled_flag(monkeypatch):
    from backend import trace_context as tc

    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0")
    tid, _ = tc.start_trace(sampled=True)
    assert tc.current_sampled() is True

    with tc.use_trace_context(trace_id=tid) as (bound_tid, _sid):
        assert bound_tid == tid
        assert tc.current_sampled() is True  # nicht neu gewuerfelt

    # Ein echter neuer Root (ohne Parent) darf weiterhin nach Ratio entscheiden.
    monkeypatch.setattr(tc, "current_trace_id", lambda: "")
    with tc.use_trace_context(trace_id="") as (_t, _s):
        assert tc.current_sampled() is False


# ---------------------------------------------------------------------------
# D16/H4 — frueher verschluckte Fehler in start_trace/end_trace zaehlen jetzt
# in get_tracing_status()["record_stats"]["failures"].
# ---------------------------------------------------------------------------

def test_start_trace_context_error_is_counted(monkeypatch, tmp_path):
    from backend import otel_tracer as ot
    from backend import trace_context as tc

    def _boom():
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(tc, "current_trace_id", _boom)
    tracer = ot.OpenTelemetryTracer(db_path=str(tmp_path / "otel.db"))
    before = tracer._record_stats["failures"]

    tracer.start_trace("probe")

    assert tracer._record_stats["failures"] == before + 1
    assert "start_trace-context" in tracer._record_stats["last_error"]


def test_end_trace_bad_start_time_is_counted(tmp_path):
    from backend.otel_tracer import OpenTelemetryTracer

    tracer = OpenTelemetryTracer(db_path=str(tmp_path / "otel.db"))
    tid = tracer.start_trace("probe")
    conn = tracer._get_conn()
    conn.execute("UPDATE otel_traces SET start_time = 'kein-datum' WHERE trace_id = ?", (tid,))
    conn.commit()
    conn.close()
    before = tracer._record_stats["failures"]

    tracer.end_trace(tid, status="OK")

    assert tracer._record_stats["failures"] == before + 1
    assert "end_trace-duration" in tracer._record_stats["last_error"]


# ---------------------------------------------------------------------------
# D05/M — Audit-Schreibfehler auf DEBUG/WARNING waren unsichtbar.
# ---------------------------------------------------------------------------

def test_fleet_self_healing_audit_failure_is_visible(monkeypatch, caplog):
    from backend import fleet_self_healing as fsh

    class _Client:
        def restart_container(self, _name):
            return b""

    monkeypatch.setattr(fsh, "_docker_client", lambda: _Client())

    class _Audit:
        def record_event(self, **_kwargs):
            raise RuntimeError("audit down")

    monkeypatch.setattr("backend.audit_log.chained_audit_log", _Audit())

    class _Hub:
        def dispatch_notification(self, **_kwargs):
            return None

    monkeypatch.setattr("backend.notification_hub.notification_hub", _Hub())

    counts_before = fsh.get_audit_error_counts().get("FLEET_SELF_HEALING_RESTART", 0)
    with caplog.at_level(logging.ERROR, logger="archon.fleet_self_healing"):
        result = fsh.restart_service_container("n8n")

    assert result["audit_write_failed"] is True
    assert result["audit_status"] == "error"
    assert fsh.get_audit_error_counts().get("FLEET_SELF_HEALING_RESTART", 0) == counts_before + 1
    assert any("FLEET_SELF_HEALING_RESTART" in r.message for r in caplog.records)


def test_event_mesh_webhook_audit_error_is_counted(monkeypatch, caplog):
    from backend import event_mesh as em

    class _Audit:
        def record_event(self, **_kwargs):
            raise RuntimeError("audit down")

    monkeypatch.setattr("backend.audit_log.chained_audit_log", _Audit())
    counts_before = em.get_audit_error_counts().get("webhook_probe", 0)

    with caplog.at_level(logging.ERROR, logger="archon_os.event_mesh"):
        result = em._audit_webhook_event("webhook_probe", {})

    assert result["audit_status"] == "error"
    assert result["audit_error_count"] == counts_before + 1
    assert em.get_audit_error_counts()["webhook_probe"] == counts_before + 1
    assert any("webhook_probe" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# D05/M — "unknown" ist kein gueltiger Prompt-/Canary-Nachweis.
# ---------------------------------------------------------------------------

def _make_proof(tmp_path, *, prompt_version="", canary_version=""):
    from backend.audit_log import ChainedAuditLog

    alog = ChainedAuditLog(db_path=str(tmp_path / "audit.db"))
    alog.record_llm_dispatch(
        agent_id="probe_agent",
        provider="local",
        model="llama3.2",
        target_endpoint="http://127.0.0.1:11434/v1/chat/completions",
        prompt_version=prompt_version,
        canary_version=canary_version,
    )
    return alog


def test_unknown_versions_never_accepted_in_production(monkeypatch, tmp_path):
    from backend.audit_log import ChainedAuditLog

    monkeypatch.setenv("ENVIRONMENT", "production")
    alog = ChainedAuditLog(db_path=str(tmp_path / "audit.db"))
    with pytest.raises(RuntimeError, match="unknown"):
        alog.record_llm_dispatch(
            agent_id="probe_agent",
            provider="local",
            model="llama3.2",
            target_endpoint="http://127.0.0.1:11434/v1/chat/completions",
            prompt_version="unknown",
            canary_version="unknown",
        )


def test_verify_rejects_placeholder_version_in_production(monkeypatch, tmp_path):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    alog = _make_proof(tmp_path, prompt_version="v1", canary_version="0")
    # Nach dem Wechsel in Produktion muss verify wegen des Platzhalters
    # scheitern (nicht nur wegen des fehlenden externen Ankers).
    alog.record_llm_dispatch(
        agent_id="probe_agent",
        provider="local",
        model="llama3.2",
        target_endpoint="http://127.0.0.1:11434/v1/chat/completions",
        prompt_version="unknown",
        canary_version="0",
    )
    monkeypatch.setenv("ENVIRONMENT", "production")

    result = alog.verify_integrity()
    assert result["valid"] is False
    assert "Platzhalter" in result["reason"]
    assert "unknown" in result["reason"]


def test_verify_reports_unverified_versions_outside_production(monkeypatch, tmp_path):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ARCHON_AUDIT_LEGACY_MAX_BLOCK", "0")
    alog = _make_proof(tmp_path, prompt_version="unknown", canary_version="0")

    result = alog.verify_integrity()
    assert result["valid"] is True  # Rueckwaerts-Kompatibilitaet (Dev/Test)
    assert result["llm_dispatch_records"] == 1
    assert result["unverified_version_blocks"] == [1]
