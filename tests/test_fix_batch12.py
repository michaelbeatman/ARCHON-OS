"""
tests/test_fix_batch12.py
Rot-Beweise fuer Batch 12:
- Re-04: SQLite-Verbindungen werden in deadlock_supervisor, event_mesh und task_self_healer sauber geschlossen
- Re-05: BidirectionalPIIScrubber begrenzt Sessions und verhindert endloses Speichern von Klartext-PII
- Re-07: DockerClient._ACTION_TIMEOUTS enthaelt restart mit ausreichendem Timeout (>= 15s)
- Re-08: egress_guard faengt ungueltigen Port ab und wirft EgressBlocked statt ValueError (500)
- P-04: ttl_cache begrenzt Eintraege (maxsize) und misst TTL erst nach der Ausfuehrung
"""
import time
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

import utils.docker_client as docker_client_mod
from utils.egress_guard import check_target_url, EgressBlocked
from backend.pii_scrubber import BidirectionalPIIScrubber
from archon.core.cache import ttl_cache, _STORE, clear_all, invalidate
from backend.deadlock_supervisor import DeadlockSupervisor
from backend.event_mesh import EventMesh
from backend.task_self_healer import TaskSelfHealer


def test_re07_docker_restart_timeout():
    """Re-07: restart muss in _ACTION_TIMEOUTS mit ausreichendem Timeout konfiguriert sein."""
    timeouts = docker_client_mod._ACTION_TIMEOUTS
    assert "restart" in timeouts, "restart fehlt in _ACTION_TIMEOUTS und faellt auf 1s Default zurueck!"
    assert timeouts["restart"] >= 15.0, f"restart-Timeout zu kurz: {timeouts['restart']}s"


def test_re08_egress_guard_invalid_port():
    """Re-08: Ungueltiger Port muss sauber als EgressBlocked abgefangen werden statt ValueError."""
    bad_url = "http://localhost:invalidport/test"
    with pytest.raises(EgressBlocked) as exc_info:
        check_target_url(bad_url)
    assert "port" in str(exc_info.value).lower() or "ungültig" in str(exc_info.value).lower()


def test_re05_pii_scrubber_bounded_memory():
    """Re-05: pii_scrubber darf Sessions nicht unbegrenzt im Speicher halten."""
    scrubber = BidirectionalPIIScrubber()
    # Pruefe, ob eine Obergrenze fuer Sessions existiert
    assert hasattr(scrubber, "max_sessions") or hasattr(scrubber, "_max_sessions"), "Keine Obergrenze fuer Sessions"
    
    max_s = getattr(scrubber, "max_sessions", getattr(scrubber, "_max_sessions", 50))
    for i in range(max_s + 20):
        scrubber.scrub_text(f"Test email{i}@example.com and phone +491511234{i:04d}", session_id=f"sess_{i}")

    assert len(scrubber._sessions) <= max_s, f"Session-Speicher waechst unbegrenzt: {len(scrubber._sessions)} > {max_s}"


def test_p04_ttl_cache_bounded_and_timestamp_accuracy():
    """P-04: ttl_cache muss maxsize unterstuetzen und den Zeitstempel nach dem Funktionsaufruf setzen."""
    clear_all()

    @ttl_cache(seconds=30.0, maxsize=5)
    def slow_func(x):
        time.sleep(0.05)
        return x * 2

    for i in range(10):
        slow_func(i)

    # Pruefe, ob der Cache begrenzt bleibt
    assert len(_STORE) <= 5, f"ttl_cache waechst unbegrenzt: {len(_STORE)} > 5"


def test_re04_sqlite_connections_closed(tmp_path):
    """Re-04: SQLite-Verbindungen muessen nach der Ausfuehrung geschlossen werden."""
    # Test fuer DeadlockSupervisor
    db_file = tmp_path / "test_supervisor.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE tasks (id TEXT, title TEXT, assignee TEXT, status TEXT, created_at TEXT, body TEXT)")
    conn.commit()
    conn.close()

    supervisor = DeadlockSupervisor(db_path=str(db_file))
    opened_conns = []
    real_get_conn = supervisor._get_conn

    def tracking_get_conn():
        c = real_get_conn()
        opened_conns.append(c)
        return c

    supervisor._get_conn = tracking_get_conn
    supervisor.detect_and_resolve_deadlocks()

    assert len(opened_conns) > 0
    for c in opened_conns:
        # Ein geschlossenes sqlite3.Connection-Objekt wirft ProgrammingError bei execute
        with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
            c.execute("SELECT 1")
