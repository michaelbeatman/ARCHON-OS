"""Epochen-Migration der email_draft_audit_log-Kette (block_id).

Smoke-Tests:
  (a) Legacy-Bloecke (altes Verfahren, ohne ID) bleiben valid
  (b) neue Bloecke mit ID sind valid und werden id-bewusst signiert
  (c) Manipulation wird erkannt
  (d) Key-Rotation mit Epoche: alte und neue Bloecke bleiben valid
  (e) CUTOFF-ENV wird respektiert; prev_hash-Kette ueber den CUTOFF bricht nicht
"""
import json

import pytest

from backend.email_draft_engine import (
    EmailDraftEngine,
    verify_email_draft_chain,
    GENESIS_HASH,
    _EMAIL_DRAFT_CUTOFF_ENV,
)
from backend.audit_log import _chain_hash


@pytest.fixture
def email_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "email-migration-test-key")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY_LEGACY", "email-migration-test-key")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", raising=False)
    monkeypatch.delenv(_EMAIL_DRAFT_CUTOFF_ENV, raising=False)
    engine = EmailDraftEngine(db_path=str(tmp_path / "email.db"))
    return engine


def _insert_legacy(conn, *, block_id, draft_id, action, details_json, created_by, created_at, prev_hash):
    """Exakt das alte Verfahren: _chain_hash(canonical) OHNE block_id."""
    canonical = f"{prev_hash}|{draft_id}|{action}|{details_json}|{created_by}|{created_at}"
    block_hash = _chain_hash(canonical)
    conn.execute(
        """INSERT INTO email_draft_audit_log
           (id, draft_id, action, details, prev_hash, block_hash, created_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (block_id, draft_id, action, details_json, prev_hash, block_hash, created_at, created_by),
    )
    return block_hash


def test_a_legacy_blocks_stay_valid(email_chain):
    with email_chain._get_conn() as conn:
        h1 = _insert_legacy(
            conn, block_id=1, draft_id="draft_legacy_1", action="DRAFT_CREATED",
            details_json='{"subject": "alt"}', created_by="admin",
            created_at="2026-01-01T00:00:00Z", prev_hash=GENESIS_HASH,
        )
        h2 = _insert_legacy(
            conn, block_id=2, draft_id="draft_legacy_1", action="DRAFT_EDITED",
            details_json='{"subject": "neu"}', created_by="admin",
            created_at="2026-01-01T00:01:00Z", prev_hash=h1,
        )
        conn.commit()

    result = verify_email_draft_chain(email_chain.db_path)
    assert result["valid"] is True
    assert result["count"] == 2
    assert result["latest_hash"] == h2


def test_b_new_blocks_with_id_are_valid(email_chain):
    email_chain._log_audit("draft_new", "DRAFT_CREATED", {"subject": "neu"}, created_by="admin")
    email_chain._log_audit("draft_new", "DRAFT_EDITED", {"subject": "edit"}, created_by="admin")

    with email_chain._get_conn() as conn:
        rows = conn.execute(
            "SELECT id, block_hash, prev_hash, details, created_at FROM email_draft_audit_log ORDER BY id"
        ).fetchall()
    assert [r["id"] for r in rows] == [1, 2]
    for r in rows:
        canonical = (
            f"{r['prev_hash']}|draft_new|"
            f"{'DRAFT_CREATED' if r['id'] == 1 else 'DRAFT_EDITED'}|"
            f"{r['details']}|admin|{r['created_at']}"
        )
        assert r["block_hash"] == _chain_hash(canonical, r["id"])

    result = verify_email_draft_chain(email_chain.db_path)
    assert result["valid"] is True
    assert result["count"] == 2


def test_c_manipulation_is_invalid(email_chain, tmp_path):
    email_chain._log_audit("draft_new", "DRAFT_CREATED", {"subject": "neu"}, created_by="admin")
    email_chain._log_audit("draft_new", "DRAFT_EDITED", {"subject": "edit"}, created_by="admin")

    with email_chain._get_conn() as conn:
        # Append-only-Trigger sind Teil des Produkts; im isolierten Test-DB
        # entfernen, um eine manipulierte Zeile simulieren zu koennen.
        conn.execute("DROP TRIGGER IF EXISTS email_draft_audit_no_update")
        conn.execute("UPDATE email_draft_audit_log SET action = 'TAMPERED' WHERE id = 1")
        conn.commit()

    result = verify_email_draft_chain(email_chain.db_path)
    assert result["valid"] is False
    assert result["broken_at_id"] == 1


def test_d_key_rotation_with_epoch_keeps_legacy_and_new_valid(email_chain, monkeypatch):
    # 1) Legacy-Block (altes Verfahren) und erster id-bewusster Block mit K1.
    with email_chain._get_conn() as conn:
        h1 = _insert_legacy(
            conn, block_id=1, draft_id="draft_rot", action="DRAFT_CREATED",
            details_json='{"subject": "legacy"}', created_by="admin",
            created_at="2026-01-01T00:00:00Z", prev_hash=GENESIS_HASH,
        )
        conn.commit()
    email_chain._log_audit("draft_rot", "DRAFT_EDITED", {"subject": "k1"}, created_by="admin")

    # 2) Rotation: K1 gilt ab Block 1, K2 ab Block 3 (= CUTOFF).
    monkeypatch.setenv(
        "ARCHON_AUDIT_HMAC_EPOCHS",
        json.dumps([{"key": "email-migration-test-key", "from_block": 1}]),
    )
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "email-rotated-key")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "3")
    monkeypatch.setenv(_EMAIL_DRAFT_CUTOFF_ENV, "3")

    email_chain._log_audit("draft_rot", "DRAFT_APPROVED_SENT", {"subject": "k2"}, created_by="admin")

    result = verify_email_draft_chain(email_chain.db_path)
    assert result["valid"] is True
    assert result["cutoff"] == 3
    assert result["count"] == 3
    assert result["latest_hash"] != h1


def test_e_cutoff_default_and_cross_cutoff_link(email_chain, monkeypatch):
    with email_chain._get_conn() as conn:
        _insert_legacy(
            conn, block_id=1, draft_id="draft_mix", action="DRAFT_CREATED",
            details_json='{}', created_by="admin",
            created_at="2026-01-01T00:00:00Z", prev_hash=GENESIS_HASH,
        )
        conn.commit()
    # Neuer Block (id=2) haengt am prev_hash des Legacy-Blocks (id=1).
    email_chain._log_audit("draft_mix", "DRAFT_EDITED", {"subject": "mix"}, created_by="admin")

    result = verify_email_draft_chain(email_chain.db_path)
    assert result["valid"] is True
    # Ohne ENV: MAX(id)+1 = 3 -> alle vorhandenen Bloecke sind Legacy,
    # werden aber zusaetzlich id-bewusst geprueft.
    assert result["cutoff"] == 3

    monkeypatch.setenv(_EMAIL_DRAFT_CUTOFF_ENV, "2")
    result_env = verify_email_draft_chain(email_chain.db_path)
    assert result_env["valid"] is True
    assert result_env["cutoff"] == 2
