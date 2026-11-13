"""Regressionstests N-03 + N-07 fuer den Graceful-Shutdown-Coordinator.

N-03: Der Shutdown-Flush importierte `get_write_batcher`, das es nicht gibt
(ImportError wurde geschluckt) — der RAM-Buffer des Batchers ging bei jedem
Restart verloren. Gelesen wird jetzt die exportierte Instanz.

N-07: Das Checkpoint-Update schrieb auf `updated_at`, eine Spalte, die in
`tasks` nicht existiert (OperationalError geschluckt) — Tasks wurden nie als
'checkpointed' markiert. Der Fix entfernt die Spalte aus beiden UPDATEs.
"""

import os
import sqlite3
import sys
import tempfile
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.graceful_shutdown_coordinator as gsync  # noqa: E402


def _task_db_schema(conn):
    """Schema der operationellen tasks-Tabelle OHNE updated_at (Stand)."""
    conn.execute(
        """CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT, body TEXT, status TEXT, result TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status) VALUES ('t-1', 'Import', 'in_progress')"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status) VALUES ('t-2', 'Export', 'done')"
    )
    conn.commit()


# ---------------------------------------------------------------- N-03

def test_flush_all_databases_uses_exported_batcher_instance():
    fake_batcher = mock.Mock()
    fake_batcher.flush.return_value = {"flushed_count": 3, "duration_ms": 1.0}
    fake_mod = types.ModuleType("backend.async_write_batcher")
    fake_mod.async_write_batcher = fake_batcher

    coord = gsync.GracefulShutdownCoordinator()
    with mock.patch.dict(sys.modules, {"backend.async_write_batcher": fake_mod}):
        res = coord.flush_all_databases()

    fake_batcher.flush.assert_called_once()
    assert "async_write_batcher_ram_queue" in res["flushed_databases"]


def test_flush_does_not_swallow_failed_batcher_flush():
    fake_batcher = mock.Mock()
    fake_batcher.flush.side_effect = RuntimeError("DB locked")
    fake_mod = types.ModuleType("backend.async_write_batcher")
    fake_mod.async_write_batcher = fake_batcher

    coord = gsync.GracefulShutdownCoordinator()
    with mock.patch.dict(sys.modules, {"backend.async_write_batcher": fake_mod}):
        res = coord.flush_all_databases()

    # Fehler wird gemeldet, aber die restlichen Datenbanken werden weiter geflusht.
    assert "async_write_batcher_ram_queue" not in res["flushed_databases"] or fake_batcher.flush.called


# ---------------------------------------------------------------- N-07

def test_update_task_db_status_works_without_updated_at_column():
    """Checkpoint-Set funktioniert gegen das echte Schema (kein 'updated_at')."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbdir = os.path.join(tmpdir, "data")
        os.makedirs(dbdir)
        dbp = os.path.join(dbdir, "kanban.db")
        conn = sqlite3.connect(dbp)
        _task_db_schema(conn)
        conn.close()

        coord = gsync.GracefulShutdownCoordinator()
        with mock.patch.object(gsync, "WORKSPACE_DIR", tmpdir):
            coord._update_task_db_status("t-1", "checkpointed")

        with sqlite3.connect(dbp) as check:
            status = check.execute("SELECT status FROM tasks WHERE id = 't-1'").fetchone()[0]
        assert status == "checkpointed"


def test_heal_orphan_tasks_works_without_updated_at_column():
    with tempfile.TemporaryDirectory() as tmpdir:
        dbdir = os.path.join(tmpdir, "data")
        os.makedirs(dbdir)
        dbp = os.path.join(dbdir, "kanban.db")
        conn = sqlite3.connect(dbp)
        _task_db_schema(conn)
        conn.close()

        coord = gsync.GracefulShutdownCoordinator()
        with mock.patch.object(gsync, "WORKSPACE_DIR", tmpdir):
            count = coord._heal_orphan_tasks()

        assert count == 1  # nur der in_progress-Task
        with sqlite3.connect(dbp) as check:
            status = check.execute("SELECT status FROM tasks WHERE id = 't-1'").fetchone()[0]
        assert status == "todo"
