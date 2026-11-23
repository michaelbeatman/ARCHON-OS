"""P0-Regression: HMAC-Signatur darf nicht durch nacktes SHA-256 ersetzt werden.

Angriff (Audit 23.11.2026, K-1): Angreifer mit DB-Schreibzugriff entfernt die
HMAC-Praefixe und signiert die gesamte Kette mit ungesalzenem SHA-256 neu.
verify_integrity() meldete trotzdem valid=True, weil die Fail-Closed-Bedingung
nur `hmac_blocks and not key_active` prüfte.
"""

import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_hmac_chain_downgrade_to_plain_sha_is_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "p0-downgrade-test-key")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_LEGACY_MAX_BLOCK", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_ANCHOR_PATH", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    from backend.audit_log import ChainedAuditLog

    dbp = str(tmp_path / "audit.db")
    log = ChainedAuditLog(db_path=dbp)
    log.record_event("test", "ACTION_A", "agent1", {"x": 1})
    log.record_event("test", "ACTION_B", "agent1", {"x": 2})

    baseline = log.verify_integrity()
    assert baseline["valid"] is True
    assert baseline["hmac_blocks"] == 2

    # Angreifer: Trigger entfernen, alle Bloecke mit PLAIN SHA-256 neu signieren.
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
    ).fetchall():
        conn.execute(f"DROP TRIGGER {name}")

    prev = "0" * 64
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
    for row in rows:
        company_id = row["company_id"] if "company_id" in row.keys() else ""
        raw = (
            f"{prev}|{row['timestamp']}|{row['category']}|{row['action']}|"
            f"{row['agent_id']}|{company_id}|{row['payload_json']}"
        )
        forged = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        conn.execute(
            "UPDATE audit_log SET prev_hash = ?, current_hash = ? WHERE id = ?",
            (prev, forged, row["id"]),
        )
        prev = forged
    conn.commit()
    conn.close()

    result = log.verify_integrity()
    assert result["valid"] is False, (
        "HMAC-Key ist aktiv, aber alle Bloecke wurden auf nacktes SHA-256 "
        "umgestellt — das darf nicht als valide gelten"
    )
