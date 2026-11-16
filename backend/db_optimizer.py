"""
backend/db_optimizer.py
Autonomer SQLite Vacuum & Fragmentierungs-Optimizer (Pillar 4 / Storage Hygiene).
Prüft Datenbanken, führt VACUUM und PRAGMA optimize durch und gibt ungenutzten
Speicherplatz auf der Festplatte wieder frei.
"""

import os
import sys
import sqlite3
from typing import Dict, Any, List

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
]

def optimize_all_databases() -> Dict[str, Any]:
    """Führt VACUUM und PRAGMA optimize auf allen SQLite-Datenbanken aus."""
    results = []
    total_freed_bytes = 0

    for db_path in DB_TARGETS:
        if not os.path.exists(db_path):
            continue

        db_name = os.path.basename(db_path)
        size_before = os.path.getsize(db_path)

        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=15.0)
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
                "freed_bytes": diff
            })
        except Exception as e:
            results.append({
                "db_name": db_name,
                "status": "error",
                "error": str(e)
            })
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return {
        "status": "success",
        "optimized_databases_count": len(results),
        "total_freed_bytes": total_freed_bytes,
        "details": results
    }
