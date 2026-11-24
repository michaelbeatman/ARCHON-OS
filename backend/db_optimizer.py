"""
backend/db_optimizer.py
Autonomer SQLite Vacuum & Fragmentierungs-Optimizer (Pillar 4 / Storage Hygiene).
Prüft Datenbanken, führt VACUUM und PRAGMA optimize durch und gibt ungenutzten
Speicherplatz auf der Festplatte wieder frei.
"""
import logging

_archon_exc_logger = logging.getLogger("db_optimizer")

import glob
import os
import sqlite3
import sys
from typing import Any, Dict, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_target(filename: str, legacy_subpath: str) -> str:
    try:
        from backend.db_paths import resolve_db
        return resolve_db(filename)
    except Exception:
        ws_path = os.path.join(WORKSPACE_DIR, "data", filename)
        return ws_path if os.path.exists(ws_path) else os.path.expanduser(legacy_subpath)


DB_TARGETS = [
    _resolve_target("agentic_memory.db", "~/.hermes/agentic_memory.db"),
    _resolve_target("kanban.db", "~/.hermes/kanban.db"),
    _resolve_target("state.db", "~/.hermes/state.db"),
    _resolve_target("contracts.db", "~/.hermes/contracts.db"),
    _resolve_target("deals.db", "~/.hermes/deals.db"),
    _resolve_target("corporate.db", "~/.hermes/corporate.db"),
]

def optimize_all_databases() -> Dict[str, Any]:
    """WAL-Checkpoint, VACUUM und optimize unter cross-prozess Wartungslock."""
    # D03/MED: Wartung darf nicht in laufende Writer hineingreifen. Ohne
    # cross-prozess Lock erzeugte VACUUM/SQLITE_BUSY still verlorene Arbeit.
    try:
        from backend.process_lock import try_acquire_loop_lock
        lock = try_acquire_loop_lock("db_maintenance", timeout=1.0)
    except Exception as exc:
        return {
            "status": "error", "error": f"Wartungslock nicht verfuegbar: {exc}",
            "optimized_databases_count": 0, "total_freed_bytes": 0, "details": [],
        }
    if lock is None:
        return {
            "status": "skipped",
            "error": "Wartungslock gehalten — Optimierung uebersprungen",
            "optimized_databases_count": 0, "total_freed_bytes": 0, "details": [],
        }

    results: List[Dict[str, Any]] = []
    total_freed_bytes = 0
    try:
        from backend.db_paths import APP_DATA_DIR, DB_BUSY_TIMEOUT_MS
        tenant_paths = set(
            glob.glob(os.path.join(APP_DATA_DIR, "tenants", "*", "*.db"))
            + glob.glob(os.path.join(WORKSPACE_DIR, "data", "tenants", "*", "*.db"))
        )
        tenant_dbs = sorted(os.path.abspath(p) for p in tenant_paths)
        seen = set()
        targets: List[str] = []
        for p in list(DB_TARGETS) + tenant_dbs:
            ap = os.path.abspath(p)
            if ap not in seen and os.path.exists(ap):
                seen.add(ap)
                targets.append(ap)

        for db_path in targets:
            if not os.path.exists(db_path):
                continue
            db_name = os.path.basename(db_path)
            size_before = os.path.getsize(db_path)
            conn = None
            try:
                conn = sqlite3.connect(db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0)
                conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
                conn.execute("PRAGMA foreign_keys = ON;")
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                except sqlite3.Error as exc:
                    # D03/MED: BUSY ist ein Fehler im Result, kein DEBUG-Rauschen.
                    results.append({
                        "db_name": db_name, "status": "error",
                        "error": f"wal_checkpoint: {exc}",
                    })
                    continue
                conn.execute("PRAGMA optimize;")
                conn.execute("VACUUM;")
                conn.close()
                conn = None
                size_after = os.path.getsize(db_path)
                diff = max(0, size_before - size_after)
                total_freed_bytes += diff
                results.append({
                    "db_name": db_name,
                    "status": "optimized",
                    "size_before_bytes": size_before,
                    "size_after_bytes": size_after,
                    "freed_bytes": diff,
                })
            except Exception as exc:
                results.append({"db_name": db_name, "status": "error", "error": str(exc)})
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception as _exc:
                        _archon_exc_logger.debug(
                            "[db_optimizer] Ignorierte Ausnahme beim Close: %s", _exc
                        )
    finally:
        lock.release()

    error_count = sum(1 for r in results if r.get("status") == "error")
    return {
        "status": "error" if error_count else "success",
        "optimized_databases_count": len(results),
        "error_count": error_count,
        "total_freed_bytes": total_freed_bytes,
        "details": results,
    }
