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
import hashlib
import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger("archon_os.process_lock")

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
    conn = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
        conn.execute("BEGIN EXCLUSIVE")
        return LoopLock(conn, path)
    except sqlite3.OperationalError as exc:
        # E: Kein stilles Returns mehr — ein nicht gestarteter Loop muss im
        # Log sichtbar sein. "Lebender" Lock anderer Prozess = erwartbar.
        logger.warning(
            "[LoopLock] Lock '%s' nicht verfügbar (Timeout %ss): %s — Loop startet NICHT.",
            safe, timeout, exc,
        )
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return None
    except Exception as exc:
        logger.error(
            "[LoopLock] Unerwarteter Fehler beim Lock '%s': %s — Loop startet NICHT.",
            safe, exc,
        )
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return None


def acquire_restore_lock(target_path: str, timeout: float = 0.3) -> LoopLock:
    """Cross-Prozess-Gate für einen Restore auf einer bestimmten Zieldatenbank.

    C07/Option B: der SQLite-EXCLUSIVE-Guard direkt auf der Ziel-DB kann unter
    Windows nicht über `os.replace()` hinweg gehalten werden. Dieses Gate
    liegt deshalb auf einer separaten Lock-DB (OS-verwaltet, keine stale
    Files) und serialisiert Restores über Prozessgrenzen hinweg.
    """
    digest = hashlib.sha256(os.path.abspath(str(target_path)).encode("utf-8")).hexdigest()[:12]
    lock = try_acquire_loop_lock(f"restore_{digest}", timeout=timeout)
    if lock is None:
        raise RuntimeError(
            "Restore abgelehnt: fuer diese Datenbank laeuft bereits ein anderer "
            "Restore-Prozess (Cross-Prozess-Lock)."
        )
    return lock


def exclusive_loop(name: str):
    """Dekorator: führt die.coroutine nur aus, wenn der Prozess den Lock hält."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            lock = try_acquire_loop_lock(name)
            if lock is None:
                # E: main.py startet den Loop sonst lautlos nie — laut loggen,
                # aber nicht raisen, damit andere Loops weiterlaufen.
                logger.error("[ExclusiveLoop] Lock nicht verfügbar: Loop %s startet NICHT", name)
                return None
            try:
                return await fn(*args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator
