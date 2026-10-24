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
DB_TARGETS = [
    os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db"),
    os.path.join(WORKSPACE_DIR, "data", "kanban.db") if os.path.exists(os.path.join(WORKSPACE_DIR, "data", "kanban.db")) else os.path.expanduser("~/.hermes/kanban.db"),
    os.path.join(WORKSPACE_DIR, "data", "state.db") if os.path.exists(os.path.join(WORKSPACE_DIR, "data", "state.db")) else os.path.expanduser("~/.hermes/state.db")
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

        try:
            conn = sqlite3.connect(db_path, timeout=15.0)
            conn.execute("PRAGMA optimize;")
            conn.execute("VACUUM;")
            conn.close()
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

    return {
        "status": "success",
        "optimized_databases_count": len(results),
        "total_freed_bytes": total_freed_bytes,
        "details": results
    }
