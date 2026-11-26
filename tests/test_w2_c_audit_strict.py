"""Remediation W2-C (Security/Audit) — D04-M1, D04-M2, D12-M5.

Regressionstests gegen verschluckte Audit-Schreibfehler und fail-open
Trust-Registry:

- D04-M1: ``resolve_taint_approval()`` schreibt den signierten Audit-Event
  VOR dem Status-Commit; bei Auditfehler bleibt die Freigabe ``pending``
  und ist nicht einlösbar (``RuntimeError("audit_write_failed")``).
- D04-M2 / D12-M5: ``load_trusted_sources()`` liefert bei Registry-Fehler
  eine LEERE Liste + ``trust_verification_error`` (kein ``VERIFIED_SENDER``);
  ``toggle_trusted_source()`` eskaliert Auditfehler und nimmt den Toggle
  zurück.

Kein Replay, keine PostgreSQL-Migration (NEVER_DO_LIST §5).
"""

import builtins
import json
import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import backend.audit_log as audit_log  # noqa: E402
import backend.dual_llm_sanitizer as dls  # noqa: E402
import backend.session_taint_guard as taint  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pending_approval(db_path: str, tool: str = "pay") -> str:
    """Taintet eine Session und parkt einen kritischen Egress (HITL)."""
    taint.mark_session_tainted("sess-w2c", source="external-web", db_path=db_path)
    res = taint.check_egress_tool_call(
        "sess-w2c", tool, {"amount": 10},
        requested_by="alice", db_path=db_path,
    )
    assert res["requires_hitl"] is True
    assert res["approval_id"]
    return res["approval_id"]


def _status(db_path: str, approval_id: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM taint_hitl_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    return str(row[0]) if row else ""


def _audit_raises(exc: BaseException):
    def _record(*_args, **_kwargs):
        raise exc
    return _record


@pytest.fixture(autouse=True)
def _strict_default(monkeypatch):
    """ARCHON_AUDIT_STRICT ist Default 1 — explizit je Test setzen."""
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "1")


# ---------------------------------------------------------------------------
# D04-M1 — session_taint_guard.resolve_taint_approval()
# ---------------------------------------------------------------------------

def test_resolve_taint_approval_audit_failure_raises_and_keeps_pending(tmp_path, monkeypatch):
    db = str(tmp_path / "taint.sqlite")
    approval_id = _pending_approval(db)
    monkeypatch.setattr(
        "backend.passkey_hitl.consume_hitl_proof_token", lambda *a, **k: True
    )
    monkeypatch.setattr(
        audit_log.chained_audit_log, "record_event",
        _audit_raises(OSError("audit disk full")),
    )

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        taint.resolve_taint_approval(
            approval_id, True, reviewer="bob", db_path=db, passkey_proof="proof-1"
        )

    # Kein Statuswechsel → Freigabe bleibt pending und nicht einlösbar.
    assert _status(db, approval_id) == "pending"
    check = taint.check_egress_tool_call(
        "sess-w2c", "pay", {"amount": 10},
        approval_id=approval_id, db_path=db,
    )
    assert check["allowed"] is False
    assert check.get("hitl_approved") is not True


def test_resolve_taint_approval_audit_event_precedes_status_commit(tmp_path, monkeypatch):
    db = str(tmp_path / "taint.sqlite")
    approval_id = _pending_approval(db)
    observed = {}
    monkeypatch.setattr(
        "backend.passkey_hitl.consume_hitl_proof_token", lambda *a, **k: True
    )

    def _audit(category, action, agent_id, payload, **kwargs):
        # Zweite Connection sieht im WAL-Modus den noch uncommitted Stand.
        with sqlite3.connect(db) as conn:
            observed["status_at_audit"] = conn.execute(
                "SELECT status FROM taint_hitl_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()[0]
        observed["payload"] = payload

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", _audit)

    res = taint.resolve_taint_approval(
        approval_id, True, reviewer="bob", db_path=db, passkey_proof="proof-1"
    )

    assert observed["status_at_audit"] == "pending"
    assert observed["payload"]["requested_by"] == "alice"
    assert observed["payload"]["reviewer"] == "bob"
    assert observed["payload"]["approved"] is True
    assert res["status"] == "approved"  # type: ignore[index]
    assert _status(db, approval_id) == "approved"


def test_resolve_taint_approval_approved_is_consumable_after_successful_audit(tmp_path, monkeypatch):
    db = str(tmp_path / "taint.sqlite")
    approval_id = _pending_approval(db)
    monkeypatch.setattr(
        "backend.passkey_hitl.consume_hitl_proof_token", lambda *a, **k: True
    )
    events = []

    def _audit(*_args, **kwargs):
        events.append(kwargs)

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", _audit)

    res = taint.resolve_taint_approval(
        approval_id, True, reviewer="bob", db_path=db, passkey_proof="proof-1"
    )
    assert res["status"] == "approved"  # type: ignore[index]
    assert any(e.get("action") == "taint_hitl_resolved" for e in events)
    assert any(e.get("payload", {}).get("requested_by") == "alice" for e in events)

    check = taint.check_egress_tool_call(
        "sess-w2c", "pay", {"amount": 10},
        approval_id=approval_id, db_path=db,
    )
    assert check["allowed"] is True
    assert check["hitl_approved"] is True


def test_resolve_taint_approval_non_strict_optout_records_error(tmp_path, monkeypatch):
    """ARCHON_AUDIT_STRICT=0 ist der einzige Opt-out (Fehler bleibt sichtbar)."""
    monkeypatch.setenv("ARCHON_AUDIT_STRICT", "0")
    db = str(tmp_path / "taint.sqlite")
    approval_id = _pending_approval(db)
    monkeypatch.setattr(
        "backend.passkey_hitl.consume_hitl_proof_token", lambda *a, **k: True
    )
    monkeypatch.setattr(
        audit_log.chained_audit_log, "record_event",
        _audit_raises(OSError("audit disk full")),
    )

    res = taint.resolve_taint_approval(
        approval_id, True, reviewer="bob", db_path=db, passkey_proof="proof-1"
    )
    assert res["status"] == "approved"  # type: ignore[index]
    assert taint._AUDIT_ERROR_COUNTS.get("taint_hitl_resolved", 0) >= 1


# ---------------------------------------------------------------------------
# D12-M5 / D04-M2 — dual_llm_sanitizer Trust-Registry
# ---------------------------------------------------------------------------

def test_load_trusted_sources_read_error_is_empty_with_error(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    trust_file.write_text("{dies ist kein JSON", encoding="utf-8")
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))

    result = dls.load_trusted_sources()
    assert list(result) == []
    assert result.trust_verification_error
    assert result.verified is False
    assert dls.is_trusted_source("intern@archon.local") is False
    assert dls.is_trusted_source("micha@archon.os") is False


def test_load_trusted_sources_open_error_is_fail_closed(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    trust_file.write_text('["boss@example.com"]', encoding="utf-8")
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))

    real_open = builtins.open

    def _failing_open(file, *args, **kwargs):
        if str(file) == str(trust_file):
            raise OSError("permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _failing_open)

    result = dls.load_trusted_sources()
    assert list(result) == []
    assert "trust_registry_unreadable" in result.trust_verification_error  # type: ignore[operator]
    assert dls.is_trusted_source("boss@example.com") is False


def test_missing_registry_is_no_hardcoded_whitelist(tmp_path, monkeypatch):
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(tmp_path / "absent.json"))
    result = dls.load_trusted_sources()
    assert list(result) == []
    assert result.trust_verification_error == "trust_registry_missing"
    for source in ("intern@archon.local", "system@archon.os", "micha@archon.os"):
        assert dls.is_trusted_source(source) is False


def test_sanitize_external_input_no_verified_sender_on_registry_error(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    trust_file.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))
    monkeypatch.setattr(
        "local_security_guard.quarantine_external_text",
        lambda *a, **k: {"verdict": "safe", "llm_verdict": "safe", "llm_classification_executed": True},
    )
    # Audit-Event darf in diesem Test nicht in die echte Kette schreiben.
    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", lambda *a, **k: None)

    res = dls.sanitize_external_input(
        "Rechnung Nr. 42 vom Lieferanten.", source_id="intern@archon.local"
    )
    assert res["is_trusted"] is False
    assert res["extracted_facts"].get("trust_status") != "VERIFIED_SENDER"
    assert "VERIFIED_SENDER" not in json.dumps(res, ensure_ascii=False)


def test_verified_sender_only_for_successful_registry(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    trust_file.write_text(json.dumps(["boss@example.com"]), encoding="utf-8")
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))
    monkeypatch.setattr(
        "local_security_guard.quarantine_external_text",
        lambda *a, **k: {"verdict": "safe", "llm_verdict": "safe", "llm_classification_executed": True},
    )
    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", lambda *a, **k: None)

    assert dls.load_trusted_sources().verified is True
    assert dls.is_trusted_source("boss@example.com") is True
    res = dls.sanitize_external_input(
        "Rechnung Nr. 42 vom Lieferanten.", source_id="boss@example.com"
    )
    assert res["extracted_facts"]["trust_status"] == "VERIFIED_SENDER"


def test_toggle_trusted_source_audit_failure_raises_and_reverts(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    original = ["alice@example.com"]
    trust_file.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))
    monkeypatch.setattr(
        audit_log.chained_audit_log, "record_event",
        _audit_raises(OSError("audit disk full")),
    )

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        dls.toggle_trusted_source("mallory@example.com", operator="admin")

    # Toggle zurückgenommen: Datei und Whitelist unverändert.
    assert json.loads(trust_file.read_text(encoding="utf-8")) == original
    assert dls.is_trusted_source("mallory@example.com") is False
    assert dls.is_trusted_source("alice@example.com") is True
    assert dls._AUDIT_ERROR_COUNTS.get("sender_trust_toggled", 0) >= 1


def test_toggle_trusted_source_audit_before_file_write(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))
    observed = {}

    def _audit(category, action, agent_id, payload, **kwargs):
        observed["file_at_audit"] = (
            trust_file.read_text(encoding="utf-8") if trust_file.exists() else None
        )

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", _audit)

    res = dls.toggle_trusted_source("boss@example.com", operator="admin")
    assert res["is_trusted"] is True
    assert observed["file_at_audit"] is None  # Audit VOR der Registry-Änderung
    assert dls.is_trusted_source("boss@example.com") is True


def test_toggle_trusted_source_refuses_unverifiable_registry(tmp_path, monkeypatch):
    trust_file = tmp_path / "trusted_sources.json"
    trust_file.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(dls, "TRUSTED_SOURCES_FILE", str(trust_file))

    with pytest.raises(RuntimeError, match="trust_registry_unverified"):
        dls.toggle_trusted_source("boss@example.com", operator="admin")
    assert trust_file.read_text(encoding="utf-8") == "{broken"
