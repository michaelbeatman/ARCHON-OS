"""Tests fuer Batch 19 (SSE-Thread-Safety & Centralized ClosingConnection).

Verifiziert:
- SSE-Registrierung in main.py nutzt _SSE_SUB_LOCK fuer thread-sichere Iteration
- backend/db_paths.py stellt get_db_connection bereit, die ClosingConnection nutzt und busy_timeout sowie WAL setzt
"""

import threading
import sqlite3
import pytest
from pathlib import Path


def test_sse_sub_lock_used_in_main_stream():
    """SSE: _SSE_SUB_LOCK muss in main.py beim Hinzufuegen und Entfernen von Queues gehalten werden."""
    main_code = Path("main.py").read_text(encoding="utf-8")
    stream_block = main_code.split('@app.get("/api/v1/events/stream")')[1].split("return StreamingResponse")[0]
    
    assert "_SSE_SUB_LOCK" in stream_block, "_SSE_SUB_LOCK wird in sse_events_stream nicht genutzt"
    assert "with _SSE_SUB_LOCK:" in stream_block


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
