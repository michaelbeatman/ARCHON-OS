"""SQLite-Zugriff auf die Hermes-State-Datenbank.

Aus main.py ausgelagert (14 Referenzen im Modul). Liefert Verbindungen, die
sich beim Schliessen selbst aufraeumen (ClosingConnection), und setzt
busy_timeout, damit parallele Writer nicht sofort mit "database is locked"
abbrechen.
"""

from __future__ import annotations

import logging

_archon_exc_logger = logging.getLogger("state_db")

import os
import sqlite3
from typing import AsyncIterator


class ClosingConnection(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


from archon.core.paths import STATE_DB_PATH as _PATHS_STATE_DB_PATH

STATE_DB_PATH = _PATHS_STATE_DB_PATH if os.path.exists(_PATHS_STATE_DB_PATH) else os.path.expanduser("~/.hermes/state.db")
_STATE_WAL_INIT: set[str] = set()


def _configure_state_conn(conn: sqlite3.Connection, db_path: str) -> sqlite3.Connection:
    # D03/HIGH: 5000 ms ist die einzige SSOT; 15000 war Drift.
    from backend.db_paths import DB_BUSY_TIMEOUT_MS
    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA cache_size=-32000;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    abs_path = os.path.abspath(db_path)
    wal_enabled = os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes")
    if abs_path not in _STATE_WAL_INIT:
        try:
            if wal_enabled:
                conn.execute("PRAGMA journal_mode=WAL;")
            _STATE_WAL_INIT.add(abs_path)
        except Exception as _exc:
            _archon_exc_logger.debug("[state_db] Ignorierte Ausnahme (Z.42): %s", _exc)
    # D03/MED: synchronous ist verbindungsbezogen — JEDE Connection, nicht nur
    # die erste pro Pfad (auch nach Restore-Cache-Reset).
    if wal_enabled:
        conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _get_state_db():
    from backend.db_paths import DB_BUSY_TIMEOUT_MS
    os.makedirs(os.path.dirname(STATE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(
        STATE_DB_PATH, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, factory=ClosingConnection
    )
    return _configure_state_conn(conn, STATE_DB_PATH)


def _get_profile_state_db(profile_name: str = "telegram_bot"):
    """Liefert die profil-spezifische SQLite-Datenbank (z. B. für telegram_bot)."""
    base_dir = os.path.dirname(STATE_DB_PATH)
    prof_path = os.path.join(base_dir, "profiles", profile_name, "state.db")
    if os.path.exists(prof_path):
        from backend.db_paths import DB_BUSY_TIMEOUT_MS
        conn = sqlite3.connect(
            prof_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, factory=ClosingConnection
        )
        return _configure_state_conn(conn, prof_path)
    return None


async def get_state_db_dep() -> AsyncIterator[sqlite3.Connection]:
    """FastAPI-Dependency (A7-Pilot): frische, selbstschliessende State-DB-Verbindung.

    Semantik wie `with _get_state_db() as conn:` — `_get_state_db()` erzeugt bei
    jedem Aufruf eine NEUE Verbindung (factory=ClosingConnection). Es existiert
    also keine geteilte Verbindung, deren vorzeitiges Schliessen Schaden
    anrichten koennte; das `finally` schliesst dieselbe Verbindung, die der
    Handler benutzt.

    Bewusst ein ASYNC-Generator: ein sync-Generator liefe in FastAPIs
    Threadpool, waehrend der async-Handler im Event-Loop-Thread laeuft.
    sqlite3-Verbindungen sind standardmaessig an den erzeugenden Thread
    gebunden (check_same_thread=True) — die Route wuerde mit ProgrammingError
    scheitern.
    """
    conn = _get_state_db()
    try:
        yield conn
    finally:
        conn.close()


__all__ = (
    "ClosingConnection",
    "STATE_DB_PATH",
    "_get_state_db",
    "_get_profile_state_db",
    "get_state_db_dep",
)
