"""Epochen-Migration der gdpr_audit_log-Kette (block_id).

Smoke-Tests:
  (a) Legacy-Quittungen (altes Verfahren, ohne ID) bleiben valid
  (b) neue Quittungen mit ID sind valid und werden id-bewusst signiert
  (c) Manipulation wird erkannt
  (d) Key-Rotation mit Epoche: alte und neue Bloecke bleiben valid
  (e) CUTOFF-ENV wird respektiert; prev_hash-Kette ueber den CUTOFF bricht nicht
"""
import json
import sqlite3

import pytest

from backend.gdpr_compliance_engine import (
    GDPRComplianceEngine,
    verify_gdpr_audit_chain,
    _GDPR_CUTOFF_ENV,
)
from backend.audit_log import _chain_hash


@pytest.fixture
def gdpr_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "gdpr-migration-test-key")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", raising=False)
    monkeypatch.delenv(_GDPR_CUTOFF_ENV, raising=False)
    db = tmp_path / "gdpr.db"
    sqlite3.connect(str(db)).close()
    engine = GDPRComplianceEngine()
    engine.memory_db = str(db)
    engine._init_audit_table()
    return engine


def _insert_legacy(conn, *, block_id, receipt_id, ts, id_hash, count, details_str, prev_hash):
    """Exakt das alte Verfahren: _chain_hash(canonical) OHNE block_id.

    Der timestamp wird mit dem exakten Wert aus dem kanonischen String
    gespeichert (vor dem Fix nutzte die Tabelle SQLite-CURRENT_TIMESTAMP).
    """
    canonical = f"{receipt_id}|ERASE_ART17|{ts}|{id_hash}|{count}|{details_str}|{prev_hash}"
    block_hash = _chain_hash(canonical)
    conn.execute(
        """INSERT INTO gdpr_audit_log
           (id, receipt_id, timestamp, action, identifier_hash, records_affected,
            details_json, prev_hash, hash)
           VALUES (?, ?, ?, 'ERASE_ART17', ?, ?, ?, ?, ?)""",
        (block_id, receipt_id, ts, id_hash, count, details_str, prev_hash, block_hash),
    )
    return block_hash


def test_a_legacy_receipts_stay_valid(gdpr_engine):
    with sqlite3.connect(gdpr_engine.memory_db) as conn:
        h1 = _insert_legacy(
            conn, block_id=1, receipt_id="gdpr-rcpt-legacy-1",
            ts="2026-01-01T00:00:00Z", id_hash="a" * 64, count=2,
            details_str='{"mode": "anonymize", "breakdown": {}}', prev_hash="GENESIS",
        )
        h2 = _insert_legacy(
            conn, block_id=2, receipt_id="gdpr-rcpt-legacy-2",
            ts="2026-01-01T00:01:00Z", id_hash="b" * 64, count=5,
            details_str='{"mode": "purge", "breakdown": {}}', prev_hash=h1,
        )
    result = verify_gdpr_audit_chain(gdpr_engine.memory_db)
    assert result["valid"] is True
    assert result["count"] == 2
    assert result["latest_hash"] == h2


def test_b_new_receipts_with_id_are_valid(gdpr_engine):
    gdpr_engine._write_audit_receipt("legacy@example.com", 3, {"kanban_tasks": 3}, "anonymize")
    gdpr_engine._write_audit_receipt("legacy@example.com", 1, {"chat_messages": 1}, "purge")

    with sqlite3.connect(gdpr_engine.memory_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM gdpr_audit_log ORDER BY id").fetchall()
    assert [r["id"] for r in rows] == [1, 2]
    for r in rows:
        canonical = (
            f"{r['receipt_id']}|ERASE_ART17|{r['timestamp']}|"
            f"{r['identifier_hash']}|{int(r['records_affected'])}|"
            f"{r['details_json']}|{r['prev_hash']}"
        )
        assert r["hash"] == _chain_hash(canonical, r["id"])
    assert verify_gdpr_audit_chain(gdpr_engine.memory_db)["valid"] is True


def test_c_manipulation_is_invalid(gdpr_engine):
    gdpr_engine._write_audit_receipt("legacy@example.com", 3, {"kanban_tasks": 3}, "anonymize")
    with sqlite3.connect(gdpr_engine.memory_db) as conn:
        conn.execute("DROP TRIGGER IF EXISTS gdpr_audit_no_update")
        conn.execute("UPDATE gdpr_audit_log SET details_json = '{\"mode\": \"TAMPERED\"}' WHERE id = 1")
        conn.commit()
    result = verify_gdpr_audit_chain(gdpr_engine.memory_db)
    assert result["valid"] is False
    assert result["broken_at_id"] == 1


def test_d_key_rotation_with_epoch_keeps_legacy_and_new_valid(gdpr_engine, monkeypatch):
    with sqlite3.connect(gdpr_engine.memory_db) as conn:
        h1 = _insert_legacy(
            conn, block_id=1, receipt_id="gdpr-rcpt-legacy-1",
            ts="2026-01-01T00:00:00Z", id_hash="a" * 64, count=2,
            details_str='{"mode": "anonymize", "breakdown": {}}', prev_hash="GENESIS",
        )
    gdpr_engine._write_audit_receipt("legacy@example.com", 3, {"kanban_tasks": 3}, "anonymize")

    # Rotation: K1 gilt ab Block 1, K2 ab Block 3 (= CUTOFF).
    monkeypatch.setenv(
        "ARCHON_AUDIT_HMAC_EPOCHS",
        json.dumps([{"key": "gdpr-migration-test-key", "from_block": 1}]),
    )
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "gdpr-rotated-key")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "3")
    monkeypatch.setenv(_GDPR_CUTOFF_ENV, "3")

    gdpr_engine._write_audit_receipt("legacy@example.com", 7, {"chat_messages": 7}, "purge")

    result = verify_gdpr_audit_chain(gdpr_engine.memory_db)
    assert result["valid"] is True
    assert result["cutoff"] == 3
    assert result["count"] == 3
    assert result["latest_hash"] != h1


def test_e_cutoff_default_and_cross_cutoff_link(gdpr_engine, monkeypatch):
    with sqlite3.connect(gdpr_engine.memory_db) as conn:
        _insert_legacy(
            conn, block_id=1, receipt_id="gdpr-rcpt-legacy-1",
            ts="2026-01-01T00:00:00Z", id_hash="a" * 64, count=2,
            details_str='{}', prev_hash="GENESIS",
        )
    gdpr_engine._write_audit_receipt("legacy@example.com", 4, {"kanban_tasks": 4}, "anonymize")

    result = verify_gdpr_audit_chain(gdpr_engine.memory_db)
    assert result["valid"] is True
    assert result["cutoff"] == 3

    monkeypatch.setenv(_GDPR_CUTOFF_ENV, "2")
    result_env = verify_gdpr_audit_chain(gdpr_engine.memory_db)
    assert result_env["valid"] is True
    assert result_env["cutoff"] == 2
