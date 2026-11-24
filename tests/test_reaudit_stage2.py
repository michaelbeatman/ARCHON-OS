"""Re-Audit Etappe 2 — R-B1: verifizierter Snapshot-Rollback (D03)."""
from __future__ import annotations

import sqlite3

import backend.system_updater as su


def test_rb1_corrupt_snapshot_does_not_replace_live_db(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    snapshots = tmp_path / "snapshots"
    snap_dir = snapshots / "bad"
    snap_dir.mkdir(parents=True)

    live = workspace / "live.db"
    conn = sqlite3.connect(live)
    try:
        conn.execute("CREATE TABLE marker (v TEXT)")
        conn.execute("INSERT INTO marker VALUES ('original')")
        conn.commit()
    finally:
        conn.close()

    # Gueltiges Snapshot, aber mit FK-Verletzung -> muss vor os.replace() scheitern.
    bad = snap_dir / "live.db"
    conn = sqlite3.connect(bad)
    try:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO child VALUES (1, 999)")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(su, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(su, "SNAPSHOT_DIR", str(snapshots))

    result = su.rollback_snapshot("bad")

    assert result["status"] == "error"
    assert result["verified_databases"] == []
    assert result["pre_restore_copies"], "vor dem Replace muss eine Safety-Kopie existieren"

    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT v FROM marker").fetchone()[0] == "original"


def test_rb1_valid_snapshot_is_verified_before_replace(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    snapshots = tmp_path / "snapshots"
    snap_dir = snapshots / "good"
    snap_dir.mkdir(parents=True)

    live = workspace / "live.db"
    conn = sqlite3.connect(live)
    try:
        conn.execute("CREATE TABLE marker (v TEXT)")
        conn.execute("INSERT INTO marker VALUES ('old')")
        conn.commit()
    finally:
        conn.close()

    good = snap_dir / "live.db"
    conn = sqlite3.connect(good)
    try:
        conn.execute("CREATE TABLE marker (v TEXT)")
        conn.execute("INSERT INTO marker VALUES ('restored')")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(su, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(su, "SNAPSHOT_DIR", str(snapshots))

    result = su.rollback_snapshot("good")

    assert result["status"] == "success"
    assert "live.db" in result["verified_databases"]
    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT v FROM marker").fetchone()[0] == "restored"
