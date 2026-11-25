"""W1-A (F010/F013) — Audit-Integrität, Anker-Rotation, Auth-Events, Receipt-Key.

Regressionstests für die D05-Remediation. Kein Test verlässt tmp_path/ENV;
produktive DB/Ankerdateien werden nicht verändert.
"""
from __future__ import annotations

import json
import sqlite3

import pytest


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    # WICHTIG: Singleton (und sein Anker-Thread) vor dem ENV-Patch anlegen,
    # sonst schreibt der globale Logger in unsere temporäre Ankerdatei.
    import backend.audit_log  # noqa: F401

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "w1-a-audit-key")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_ANCHOR_KEY", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_ANCHOR_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_ANCHOR_EPOCH_FROM", raising=False)
    monkeypatch.setenv("ARCHON_ALLOW_INSECURE_AUDIT_DEV", "1")
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_PATH", str(tmp_path / "anchor.log"))
    return tmp_path


def _log(tmp_path, name="audit.db"):
    from backend.audit_log import ChainedAuditLog

    return ChainedAuditLog(db_path=str(tmp_path / name))


# ---------------------------------------------------------------------------
# H-05-1: Anker-Signatur bleibt nach Audit-Key-Rotation verifizierbar
# ---------------------------------------------------------------------------
def test_anchor_epoch_marker_survives_audit_key_rotation(audit_env, monkeypatch):
    anchor = str(audit_env / "anchor.log")
    log = _log(audit_env)
    try:
        log.record_event("sys", "OP1", "agent_a", {"n": 1})
        log._write_anchor(anchor)
        lines_before = open(anchor, encoding="utf-8").read().splitlines()
        assert len(lines_before[0].split("\t")) == 5  # Epochen-Marker

        monkeypatch.setenv(
            "ARCHON_AUDIT_HMAC_EPOCHS",
            json.dumps([{"key": "w1-a-audit-key", "from_block": 1}]),
        )
        monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "w1-a-rotated-key")
        monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "2")
        log.record_event("sys", "OP2", "agent_a", {"n": 2})
        log._write_anchor(anchor)

        res = log.verify_integrity()
        assert res["valid"] is True, res
        assert res["anchor_verified"] is True
    finally:
        log.stop_anchor_worker()


def test_dedicated_anchor_key_is_independent_of_audit_rotation(audit_env, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_KEY", "w1-a-dedicated-anchor-key")
    anchor = str(audit_env / "anchor2.log")
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_PATH", anchor)
    log = _log(audit_env, "audit2.db")
    try:
        log.record_event("sys", "OP1", "agent_a", {"n": 1})
        log._write_anchor(anchor)

        monkeypatch.setenv(
            "ARCHON_AUDIT_HMAC_EPOCHS",
            json.dumps([{"key": "w1-a-audit-key", "from_block": 1}]),
        )
        monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "totally-different-audit-key")
        monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "2")
        log.record_event("sys", "OP2", "agent_a", {"n": 2})
        log._write_anchor(anchor)

        res = log.verify_integrity()
        assert res["valid"] is True, res
        assert res["anchor_verified"] is True
    finally:
        log.stop_anchor_worker()


# ---------------------------------------------------------------------------
# D05/MED: OTel-Korrelationsspalten gegen signierten Payload prüfen
# ---------------------------------------------------------------------------
def test_correlation_column_tampering_is_detected(audit_env):
    log = _log(audit_env, "corr.db")
    try:
        log.record_event(
            "sys", "OP", "agent_a", {"n": 1},
            trace_id="tr-ok", session_id="sess-ok", correlation_id="corr-ok",
        )
        dbp = str(audit_env / "corr.db")
        conn = sqlite3.connect(dbp)
        conn.execute("DROP TRIGGER audit_log_no_update")
        conn.execute("UPDATE audit_log SET trace_id='tr-FOREIGN' WHERE id=1")
        conn.commit()
        conn.close()

        res = log.verify_integrity()
        assert res["valid"] is False
        assert "trace_id" in res["reason"]
        assert res["corrupted_id"] == 1
    finally:
        log.stop_anchor_worker()


# ---------------------------------------------------------------------------
# MED: Approval-Trigger sperrt jetzt ALLE Spalten; Detection bleibt aktiv
# ---------------------------------------------------------------------------
def test_approval_chain_blocks_any_column_update_and_still_detects_forced_tamper(tmp_path):
    from backend.approval_policy_engine import ApprovalPolicyEngine

    dbp = str(tmp_path / "approval.db")
    eng = ApprovalPolicyEngine(db_path=dbp)
    conn = sqlite3.connect(dbp)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE approval_policy_audit_chain SET new_value='MANIPULIERT' WHERE id=1"
            )
        # Erkennungspfad (R-30) bleibt intakt, wenn der Trigger bewusst entfernt
        # wurde (z. B. Forensik/Angriffssimulation).
        conn.execute("DROP TRIGGER approval_chain_no_hash_update")
        conn.execute(
            "UPDATE approval_policy_audit_chain SET new_value='MANIPULIERT' WHERE id=1"
        )
        conn.commit()
    finally:
        conn.close()
    res = eng.verify_audit_integrity()
    assert res["valid"] is False
    assert res.get("broken_at_id") == 1


# ---------------------------------------------------------------------------
# F024: einheitlicher Pflicht-Audit-Helper
# ---------------------------------------------------------------------------
def test_require_audit_event_raises_on_write_failure(audit_env, monkeypatch):
    import backend.audit_log as al

    def _boom(*_a, **_kw):
        raise sqlite3.OperationalError("db offline")

    monkeypatch.setattr(al.chained_audit_log, "record_event", _boom)
    with pytest.raises(RuntimeError, match="audit_write_failed"):
        al._require_audit_event("security", "probe", "agent", {"x": 1})


# ---------------------------------------------------------------------------
# D05/MED: isolated secondary DBs must not inherit global head anchors
# ---------------------------------------------------------------------------
def test_secondary_chain_anchor_is_scoped_to_source_db(audit_env, monkeypatch):
    """Ein isolierter Verify darf nicht mit fremden Zentral-Ankern scheitern."""
    from backend import audit_log as al
    from backend.email_draft_engine import EmailDraftEngine, verify_email_draft_chain

    dbp = str(audit_env / "email.db")
    eng = EmailDraftEngine(db_path=dbp)
    eng._log_audit("draft-w1", "DRAFT_CREATED", {"subject": "x"}, created_by="admin")

    # Simulierter fremder Anker aus der Zentralkette (kein Schreiben in die
    # echte Produktiv-DB!). Das db_path-Filter muss ihn herausfiltern.
    foreign = [{
        "id": 1, "head": "f" * 64, "count": 999, "db_path": "",
    }]

    def _scoped_anchors(chain, limit=20, *, db_path=None):
        # Nur der Default-Pfad (Produktiv-DB) sieht Legacy-Anker ohne db_path.
        if chain != "email_draft_audit_log" or db_path:
            return []
        return foreign

    monkeypatch.setattr(al, "get_chain_anchors", _scoped_anchors)
    res = verify_email_draft_chain(dbp)
    assert res["valid"] is True, res
    assert res["anchor_verified"] is None


# ---------------------------------------------------------------------------
# D05/MED: Receipt-Key getrennt / Legacy ehrlich gemeldet
# ---------------------------------------------------------------------------
def test_receipt_legacy_key_is_reported_not_protected(audit_env, monkeypatch):
    from backend import execution_receipt_ledger as erl

    monkeypatch.delenv("ARCHON_RECEIPT_HMAC_KEY", raising=False)
    monkeypatch.delenv("ARCHON_RECEIPT_HMAC_EPOCHS", raising=False)
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "legacy-audit-key")
    erl.DB_PATH = str(audit_env / "receipt.db")
    erl._init_db()
    ledger = erl.ExecutionReceiptLedger()
    ledger.issue_receipt("t-w1", "coder", "local", 10, 5, 0.001, ["read"])

    legacy = ledger.verify_chain_integrity()
    assert legacy["hmac_protected"] is False
    assert legacy["domain_separated"] is False
    assert legacy["key_source"] == "legacy_audit_key"

    monkeypatch.setenv("ARCHON_RECEIPT_HMAC_KEY", "dedicated-receipt-key")
    dedicated = ledger.verify_chain_integrity()
    assert dedicated["key_source"] == "dedicated_receipt_key"


# ---------------------------------------------------------------------------
# H-05-4: failed cancel audit call has agent_id + visible audit_status
# ---------------------------------------------------------------------------
def test_failed_cancel_audit_call_has_agent_id(audit_env, monkeypatch):
    import backend.audit_log as al
    import core_dispatcher as cd

    calls = []

    def _capture(*args, **kwargs):
        calls.append(kwargs)
        return {"event_id": 77}

    monkeypatch.setattr(al.chained_audit_log, "record_event", _capture)
    entry = cd._record_failed_cancel("task-w1", "cancel_timeout")
    assert calls, "record_event wurde nicht aufgerufen"
    assert calls[0]["agent_id"] == "system"
    assert calls[0]["category"] == "recovery"
    assert calls[0]["action"] == "cancel_failed"
    assert "audit_status" not in calls[0]["payload"]
    assert entry["audit_status"] == "ok"
    assert entry["audit_event_id"] == 77

    def _boom(*_a, **_kw):
        raise RuntimeError("db offline")

    monkeypatch.setattr(al.chained_audit_log, "record_event", _boom)
    failed = cd._record_failed_cancel("task-w1", "cancel_timeout")
    assert failed["audit_status"] == "error"


# ---------------------------------------------------------------------------
# H-05-3: Auth-Events ohne Klartext-PII/Secrets
# ---------------------------------------------------------------------------
def test_auth_actor_context_hashes_ip_and_user_agent(audit_env):
    from backend.audit_log import audit_actor_context

    ctx = audit_actor_context(
        ip_address="192.168.44.12", user_agent="Mozilla/5.0 SecretAgent"
    )
    assert "192.168.44.12" not in json.dumps(ctx)
    assert "SecretAgent" not in json.dumps(ctx)
    assert len(ctx["client_ip_hash"]) == 32
    assert len(ctx["user_agent_hash"]) == 32


def test_auth_event_writes_signed_category_auth(audit_env, monkeypatch):
    import backend.audit_log as al
    from archon.routers.auth import _audit_auth_event

    captured = []
    monkeypatch.setattr(al, "_require_audit_event", lambda *a, **kw: captured.append((a, kw)))
    _audit_auth_event(
        "login_success", actor="alice",
        user_id="usr_1", role="admin", reason="credentials_valid",
        password="super-secret",  # darf nie ins Payload gelangen
    )
    assert captured
    args, _kw = captured[0]
    assert args[0] == "auth"
    assert args[1] == "login_success"
    assert args[2] == "alice"
    assert "password" not in args[3]
    assert "user_id" in args[3]


# ---------------------------------------------------------------------------
# B-05: Fail-Fast-Hook + globales AUDIT_COMPROMISED-Flag
# ---------------------------------------------------------------------------
def test_integrity_fail_fast_hook_raises_and_marks_flag(monkeypatch):
    import main as app_main

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(
        app_main, "_verify_all_audit_chains",
        lambda: {"Zentrale Audit-Kette": {"valid": False, "reason": "manipuliert", "corrupted_id": 7}},
    )
    try:
        with pytest.raises(RuntimeError, match="fail-closed"):
            app_main._assert_audit_integrity()
        assert app_main._AUDIT_COMPROMISED["compromised"] is True
        assert "manipuliert" in app_main._AUDIT_COMPROMISED["reason"]
        assert "_assert_audit_integrity" in app_main._FAIL_FAST_HOOKS
    finally:
        app_main._AUDIT_COMPROMISED.update(
            compromised=False, reason="", chains=[], ts=0.0
        )
