"""Cross-Prozess-Locks für Hintergrund-Loops (W3).

`_LOOPS_STARTED` in main.py schützt nur vor einem doppelten Start im selben
Prozess. Bei mehreren Replicas liefen DB-Backup, IMAP-Sync und
Deadlock-Recovery mehrfach (doppelte Mails, doppelte Backups, DB-Locks).

Die Implementierung nutzt eine SQLite-EXCLUSIVE-Transaktion auf einer kleinen
Lock-DB. Der Lock wird vom OS freigegeben, wenn der Prozess stirbt — es gibt
keine stale Lockfiles und kein TTL-Rätselraten. Jeder Loop hält genau eine
Connection für seine gesamte Laufzeit.
"""

import functools
import os
import sqlite3
from typing import Optional

try:
    from backend.db_paths import resolve_db as _resolve_db
    _LOCK_DIR = os.path.dirname(_resolve_db("state.db"))
except Exception:
    _LOCK_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )


class LoopLock:
    def __init__(self, conn: sqlite3.Connection, path: str):
        self._conn = conn
        self._path = path

    def release(self) -> None:
        try:
            self._conn.execute("ROLLBACK")
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


def try_acquire_loop_lock(name: str, timeout: float = 0.3) -> Optional[LoopLock]:
    """Gibt den Lock zurück oder None, wenn ein anderer Prozess ihn hält."""
    safe = "".join(c for c in str(name) if c.isalnum() or c in "-_") or "default"
    path = os.path.join(_LOCK_DIR, f".loop_lock_{safe}.db")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
        conn.execute("BEGIN EXCLUSIVE")
        return LoopLock(conn, path)
    except sqlite3.OperationalError:
        try:
            conn.close()
        except Exception:
            pass
        return None
    except Exception:
        return None


def exclusive_loop(name: str):
    """Dekorator: führt die.coroutine nur aus, wenn der Prozess den Lock hält."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            lock = try_acquire_loop_lock(name)
            if lock is None:
                return None
            try:
                return await fn(*args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator
