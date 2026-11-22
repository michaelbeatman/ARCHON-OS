"""Regressionstests fuer Outbox-CAS-Claim und DB-Konsolidierung."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_outbox_has_claim_columns(tmp_path):
    from backend.event_mesh import EventMesh

    mesh = EventMesh(db_path=str(tmp_path / "mesh.db"))
    with sqlite3.connect(str(tmp_path / "mesh.db")) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_mesh_outbox)").fetchall()}
    assert {"claimed_by", "claim_expires"} <= cols


def test_p2_outbox_claim_is_atomic(tmp_path):
    """Zwei Worker duerfen dieselbe Outbox-Zeile nicht gleichzeitig claimen."""
    from backend.event_mesh import EventMesh

    db = str(tmp_path / "mesh.db")
    mesh = EventMesh(db_path=db)
    idem = "cas-test-key"
    now = time.time()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO event_mesh_outbox "
            "(idempotency_key, target_url, event_type, payload_json, status, next_try_at, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (idem, "http://invalid.local/hook", "evt", "{}", "pending", now - 1, "2026-01-01"),
        )
        conn.commit()

    # Direkter CAS-Test (gleiche Logik wie process_outbox).
    def try_claim(worker):
        with sqlite3.connect(db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE event_mesh_outbox SET claimed_by = ?, claim_expires = ? "
                "WHERE status IN ('pending','delivery_failed') AND next_try_at <= ? "
                "AND (claimed_by IS NULL OR claim_expires IS NULL OR claim_expires <= ?)",
                (worker, time.time() + 120, time.time(), time.time()),
            )
            ok = cur.rowcount == 1
            conn.commit()
            return ok

    assert try_claim("worker-a") is True
    assert try_claim("worker-b") is False  # bereits geclaimt


def test_p2_consolidation_uses_full_schema_signature():
    from backend.db_consolidation import _full_schema_signature

    a = {"columns": ["id", "name"], "create_sql": "CREATE TABLE t (id TEXT, name TEXT)"}
    b = {"columns": ["id", "name"], "create_sql": "CREATE TABLE t (id INTEGER NOT NULL, name TEXT)"}
    # Gleiche Spaltennamen, aber異なる Typen ->不同的 Signatur -> kein stiller Merge.
    assert _full_schema_signature(a) != _full_schema_signature(b)
    c = {"columns": ["id", "name"], "create_sql": "CREATE TABLE t (id TEXT, name TEXT);"}
    assert _full_schema_signature(a) == _full_schema_signature(c)


def test_p2_schema_versions_are_readable(tmp_path):
    from backend.db_consolidation import get_schema_versions

    db = tmp_path / "business.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE x (id TEXT)")
        conn.execute("PRAGMA user_version = 1;")
        conn.commit()
    versions = get_schema_versions(target_dir=str(tmp_path))
    assert versions.get("business.db") == 1


def test_p2_litestream_has_no_nonexistent_dbs():
    txt = (REPO_ROOT / "config/litestream.yml").read_text(encoding="utf-8")
    active_paths = [ln.strip().split("path:", 1)[1].strip() for ln in txt.splitlines()
                    if ln.strip().startswith("- path:")]
    # Konsolidierung ist AKTIV: die 3 Domaenen-DBs werden repliziert.
    assert "/app/data/ops.db" in active_paths
    assert "/app/data/memory.db" in active_paths
    assert "/app/data/business.db" in active_paths
