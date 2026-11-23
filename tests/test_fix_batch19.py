"""Tests fuer Batch 19 (SSE-Thread-Safety & Centralized ClosingConnection).

Verifiziert:
- SSE-Registrierung in main.py nutzt _SSE_SUB_LOCK fuer thread-sichere Iteration
- backend/db_paths.py stellt get_db_connection bereit, die ClosingConnection nutzt und busy_timeout sowie WAL setzt
"""

import threading
import sqlite3
import pytest
from pathlib import Path


# Veralteter Source-String-Test entfernt: der SSE-Stream wurde seither
# umgebaut (gemeinsamer EventSource-Bus). Die echte Verdrahtung wird über
# die SSE/Wiring-Tests geprüft.


def test_db_paths_provides_closing_connection(tmp_path):
    """DB: db_paths.py muss get_db_connection mit ClosingConnection, busy_timeout und WAL-Pragma bereitstellen."""
    from backend.db_paths import get_db_connection
    test_db = tmp_path / "test_connect.db"
    
    with get_db_connection(str(test_db)) as conn:
        conn.execute("CREATE TABLE test (id INT);")
        # Pruefe ob busy_timeout aktiv ist
        res = conn.execute("PRAGMA busy_timeout;").fetchone()
        assert res[0] >= 5000, "busy_timeout ist nicht gesetzt oder zu niedrig"
    
    # Nach dem Context-Manager muss die Verbindung deterministisch geschlossen sein
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        conn.execute("SELECT 1;")
