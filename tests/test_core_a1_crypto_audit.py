"""Strang A (Core) A1 Regression Tests: sign_block, signed anchor, trace_id/session_id,
secondary chain downgrade detection, treasury rowid order, passkey resource binding.
Referenz: d05 F-01, F-02, F-08, F-09, F-11, F-14, F-18; d04 Passkey-Binding.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_sign_block_fail_closed_without_hmac_key(monkeypatch):
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    from backend import audit_log
    audit_log._faudit_enforce_cache = None
    with pytest.raises(RuntimeError, match="ARCHON_AUDIT_HMAC_KEY"):
        audit_log.sign_block("payload-without-key")
    with pytest.raises(RuntimeError, match="ARCHON_AUDIT_HMAC_KEY"):
        audit_log._chain_hash("payload-without-key")
    # Explicit legacy verification opt-in still works
    legacy = audit_log.sign_block("payload-without-key", allow_legacy=True)
    assert len(legacy) == 64 and not legacy.startswith(audit_log.HMAC_PREFIX)


def test_audit_log_trace_session_columns_and_signed_anchor_tail_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "test-a1-hmac-key-32bytes-minimum-ok")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_LEGACY_MAX_BLOCK", raising=False)
    anchor_file = str(tmp_path / "anchor.log")
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_PATH", anchor_file)
    monkeypatch.setenv("ENVIRONMENT", "production")

    from backend.audit_log import ChainedAuditLog

    dbp = str(tmp_path / "audit.db")
    log = ChainedAuditLog(db_path=dbp)
    try:
        ev1 = log.record_event("sys", "OP1", "agent_a", {"k": 1}, trace_id="tr-111", session_id="sess-222")
        ev2 = log.record_event("sys", "OP2", "agent_a", {"k": 2}, trace_id="tr-111", session_id="sess-222")
        assert ev1["event_id"] == 1 and ev2["event_id"] == 2
        log._write_anchor(anchor_file)

        # Verify columns persisted
        conn = sqlite3.connect(dbp)
        row = conn.execute("SELECT trace_id, session_id FROM audit_log WHERE id=1").fetchone()
        conn.close()
        assert row == ("tr-111", "sess-222")

        res_ok = log.verify_integrity()
        assert res_ok["valid"] is True
        assert res_ok["anchor_verified"] is True
        assert res_ok["triggers_intact"] is True

        # Simulate Tail-Deletion of block 2 (drop trigger + delete block 2)
        conn = sqlite3.connect(dbp)
        conn.execute("DROP TRIGGER audit_log_no_delete")
        conn.execute("DELETE FROM audit_log WHERE id = 2")
        conn.commit()
        conn.close()

        res_tail = log.verify_integrity()
        assert res_tail["valid"] is False
        assert res_tail["corrupted_id"] == "audit_anchor"
    finally:
        log.stop_anchor_worker()


def test_passkey_resource_binding_rejects_empty_bound_resource():
    import time
    from backend import passkey_hitl

    tok = "pk_test_unbound_proof_a1"
    with passkey_hitl._LOCK:
        passkey_hitl._PROOF_TOKENS[tok] = {
            "user_id": "usr_test",
            "category": "payments",
            "uv_verified": True,
            "action": "Zahlung freigeben",
            "resource": "",
            "expires_at": time.time() + 120,
        }
    # Must NOT allow approving a specific tx_id with an unbound proof!
    assert passkey_hitl.consume_hitl_proof_token(
        tok, "usr_test", "payments", action="Zahlung freigeben", resource="tx-123456"
    ) is False
