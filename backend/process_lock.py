"""Cross-Prozess-Locks für Hintergrund-Loops (W3).

`_LOOPS_STARTED` in main.py schützt nur vor einem doppelten Start im selben
Prozess. Bei mehreren Replicas liefen DB-Backup, IMAP-Sync und
Deadlock-Recovery mehrfach (doppelte Mails, doppelte Backups, DB-Locks).

Die Implementierung nutzt eine SQLite-EXCLUSIVE-Transaktion auf einer kleinen
Lock-DB. Der Lock wird vom OS freigegeben, wenn der Prozess stirbt — es gibt
keine stale Lockfiles und kein TTL-Rätselraten. Jeder Loop hält genau eine
Connection für seine gesamte Laufzeit.
"""

import asyncio
import functools
import glob
import hashlib
import logging
import os
import sqlite3
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("archon_os.process_lock")

# D07/MED (A9/A3-DELEGATED): eine Lock-Sackgasse ist kein normaler Zustand.
# main.py:/readyz liest diese Liste ueber get_loop_lock_failures().
_LOOP_LOCK_FAILURES: list = []


def get_loop_lock_failures() -> list:
    """Kopie der persistierten Sackgassen fuer den Readiness-Gate."""
    return list(_LOOP_LOCK_FAILURES)


def _record_loop_lock_failure(name: str, reason: str) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"loop": str(name), "reason": str(reason), "ts": time.time()}
    _LOOP_LOCK_FAILURES.append(entry)
    return entry


async def _escalate_loop_lock_failure(name: str) -> None:
    """HITL-Broadcast + DLQ-Eintrag — statt stiller Sackgasse."""
    detail = f"Exclusive-Loop '{name}': Prozess-Lock nicht verfügbar — Loop startet NICHT."
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("hitl_required", {
            "title": "Hintergrund-Loop nicht gestartet (Lock-Sackgasse)",
            "detail": detail,
            "source": "process_lock",
        })
    except Exception as exc:
        logger.error("[ExclusiveLoop] HITL-Broadcast fehlgeschlagen: %s", exc)
    try:
        from backend.dead_letter_queue import dead_letter_queue_manager as _dlq
        result = await asyncio.to_thread(
            _dlq.enqueue_task,
            "loop_lock_unavailable",
            "process_lock",
            {"loop": str(name), "reason": "lock_unavailable"},
            idempotency_key=f"loop_lock_unavailable:{name}",
        )
        if not result.get("queued"):
            logger.warning("[ExclusiveLoop] DLQ-Eintrag nicht queued: %s", result)
    except Exception as exc:
        logger.error("[ExclusiveLoop] DLQ-Eintrag fehlgeschlagen: %s", exc)


try:
    from backend.db_paths import resolve_db as _resolve_db
    _LOCK_DIR = os.path.dirname(_resolve_db("state.db"))
except Exception:
    _LOCK_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )


def cleanup_stale_lock_journals() -> list[str]:
    """Entfernt verwaiste `.loop_lock_*.db-journal`-Dateien (D03/MED).

    Ein Lock-Journal darf NUR entfernt werden, wenn niemand den Lock hält.
    Dazu wird mit timeout=0 ein EXCLUSIVE-Lock versucht: gelingt er, ist der
    vorherige Inhaber weg und das 512-Byte-Journal ist wirklich verwaist.
    """
    removed: list[str] = []
    try:
        journals = [
            p for p in glob.glob(os.path.join(_LOCK_DIR, ".loop_lock_*.db-journal"))
            if os.path.isfile(p)
        ]
    except Exception:
        return removed
    for journal in journals:
        lock_db = journal[: -len("-journal")]
        probe = None
        try:
            probe = sqlite3.connect(lock_db, timeout=0.0, isolation_level=None)
            probe.execute("BEGIN EXCLUSIVE")
            probe.execute("ROLLBACK")
            os.unlink(journal)
            removed.append(journal)
        except (sqlite3.OperationalError, OSError):
            # Anderer Prozess hält den Lock oder Datei bereits weg — nicht antasten.
            pass
        except Exception as exc:
            logger.debug("[LoopLock] Journal-Cleanup %s übersprungen: %s", journal, exc)
        finally:
            if probe is not None:
                try:
                    probe.close()
                except Exception:
                    pass
    return removed


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
        # D03/MED: nach Release das eigene Journal aufräumen, sofern es
        # existiert und kein anderer Prozess inzwischen den Lock hält.
        cleanup_stale_lock_journals()


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
                # D07/MED: laut loggen REICHT NICHT. Der nicht gestartete Loop
                # wird jetzt zusaetzlich eskaliert (HITL + DLQ) und in /readyz
                # gespiegelt. Kein raise, damit andere Loops weiterlaufen.
                logger.error("[ExclusiveLoop] Lock nicht verfügbar: Loop %s startet NICHT", name)
                _record_loop_lock_failure(name, "lock_unavailable")
                await _escalate_loop_lock_failure(name)
                return None
            try:
                return await fn(*args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator
