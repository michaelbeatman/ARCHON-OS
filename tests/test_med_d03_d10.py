"""Regressionstests fuer die MED-Funde aus reaudit/domain_03.md in
freigegebenen Dateien (db_backup_manager, vault, views_core, db_consolidation).

Kein Replay, keine Migration — nur statische und kleine Unit-Pruefungen der
konkreten Härtungen.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- D03/MED:
# db_backup_manager.py — Lock-Fenster bis os.replace()


def test_guard_held_through_replace_on_posix():
    src = _src("backend/db_backup_manager.py")
    assert "guard_held_through_replace" in src
    assert 'if os.name == "nt":' in src
    # Der Replace darf erst NACH der POSIX-Entscheidung kommen; der Guard
    # wird danach freigegeben, nicht schon vorher.
    decision = src.index("result[\"guard_held_through_replace\"]")
    replace = src.index("os.replace(tmp_path, target)", decision)
    release = src.index("_release_db_guard(guard)", replace)
    assert decision < replace < release


def test_release_db_guard_is_idempotent():
    from backend.db_backup_manager import _release_db_guard

    _release_db_guard(None)  # kein Fehler bei None
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("BEGIN EXCLUSIVE")
    _release_db_guard(conn)
    _release_db_guard(conn)  # zweiter Aufruf darf nicht werfen


# ---------------------------------------------------------------- D03/MED:
# db_backup_manager.py — Sidecar-Cleanup ohne TOCTOU, enger Scan-Root


def test_sidecar_cleanup_recheck_before_unlink_and_narrow_roots():
    src = _src("backend/db_backup_manager.py")
    assert "_CLEANUP_ROOTS" in src
    assert "try_acquire_loop_lock(\"sidecar_cleanup\"" in src
    # Der erneute exists()-Check steht vor dem unlink().
    recheck = src.index("if os.path.exists(os.path.join(dirpath, base)):")
    unlink = src.index("os.unlink(victim)", recheck)
    assert recheck < unlink


def test_sidecar_cleanup_keeps_active_and_removes_orphan(tmp_path):
    from backend.db_backup_manager import cleanup_orphaned_sidecars

    # aktive DB mit WAL-Sidecar -> darf nicht geloescht werden
    active = tmp_path / "live.db"
    sqlite3.connect(str(active)).close()
    (tmp_path / "live.db-wal").write_bytes(b"wal")

    # verwaistes Artefakt -> muss entfernt werden
    orphan = tmp_path / "gone.db.restore.20260101.tmp-wal"
    orphan.write_bytes(b"wal")

    res = cleanup_orphaned_sidecars(root_dir=str(tmp_path))
    assert (tmp_path / "live.db-wal").exists()
    assert not orphan.exists()
    assert orphan.name in [Path(p).name for p in res["removed"]]


# ---------------------------------------------------------------- D03/MED:
# archon/routers/vault.py — 409-Pruefung atomar mit dem Replace


def test_vault_atomic_write_rechecks_expected_mtime(tmp_path, monkeypatch):
    import archon.routers.vault as vault

    class _FakeLock:
        released = False

        def release(self):
            self.released = True

    fake = _FakeLock()
    monkeypatch.setattr(
        "backend.process_lock.try_acquire_loop_lock", lambda *a, **k: fake
    )

    target = tmp_path / "note.md"
    target.write_text("vom Client gelesen", encoding="utf-8")
    stale_mtime = target.stat().st_mtime - 10.0

    with pytest.raises(HTTPException) as exc:
        vault._atomic_write_text(
            str(target), "neuer inhalt", expected_mtime=stale_mtime
        )
    assert exc.value.status_code == 409
    assert target.read_text(encoding="utf-8") == "vom Client gelesen"
    assert fake.released is True
    # Kein Temp-Artefakt zurueckgeblieben
    assert list(tmp_path.glob(".vault_*.tmp")) == []


def test_vault_edit_passes_expected_values_into_atomic_write():
    src = _src("archon/routers/vault.py")
    assert "expected_mtime=expected_mtime" in src
    assert "expected_size=expected_size" in src
    # Pruefung liegt jetzt auch im Writer, nicht nur im Endpoint
    assert src.count("getmtime(real_path)") >= 1 or src.count("getmtime(path)") >= 1


# ---------------------------------------------------------------- D03/MED:
# views_core.py — atomare Writes + Pfad-Jail fuer Theme/CSS


def test_views_core_theme_writes_use_atomic_helpers():
    src = _src("views_core.py")
    assert "_runtime.atomic_write_json(THEME_OVERRIDES_FILE" in src
    assert "safe_path_within(\n                    target_css, [static_root]" in src
    assert "_atomic_write_text(safe_css," in src
    assert 'with open(THEME_OVERRIDES_FILE, "w"' not in src
    assert 'with open(target_css, "w"' not in src


def test_views_core_atomic_text_write(tmp_path):
    import views_core

    target = tmp_path / "custom_studio.css"
    views_core._atomic_write_text(str(target), "/* reset */\n")
    assert target.read_text(encoding="utf-8") == "/* reset */\n"
    assert list(tmp_path.glob(".tmp_*")) == []


# ---------------------------------------------------------------- D03/MED:
# db_consolidation.py — Rollback der Ziel-DBs bei DATENVERLUST


def test_consolidation_rolls_back_targets_before_abort(tmp_path):
    from backend.db_consolidation import (
        _rollback_targets_from_snapshots,
        _snapshot_target_for_rollback,
    )

    target = tmp_path / "ops.db"
    with sqlite3.connect(str(target)) as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('alt')")

    snap = _snapshot_target_for_rollback(
        str(target), str(tmp_path / "rollback"), "ops.db"
    )
    assert snap["existed_before"] is True

    # Teilmigration simulieren: alter Inhalt wird durch neuen ersetzt.
    with sqlite3.connect(str(target)) as conn:
        conn.execute("UPDATE t SET v = 'teil migriert'")

    restored = _rollback_targets_from_snapshots([snap])
    assert len(restored) == 1
    with sqlite3.connect(str(target)) as conn:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "alt"


def test_consolidation_data_loss_branch_uses_rollback():
    src = _src("backend/db_consolidation.py")
    branch = src.index("if data_loss:")
    rollback = src.index("_rollback_targets_from_snapshots(target_snapshots)", branch)
    raise_at = src.index("raise RuntimeError(", rollback)
    assert branch < rollback < raise_at
