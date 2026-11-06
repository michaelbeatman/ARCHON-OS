"""SQLite-Zugriff auf die Hermes-State-Datenbank.

Aus main.py ausgelagert (14 Referenzen im Modul). Liefert Verbindungen, die
sich beim Schliessen selbst aufraeumen (ClosingConnection), und setzt
busy_timeout, damit parallele Writer nicht sofort mit "database is locked"
abbrechen.
"""

from __future__ import annotations

import os
import sqlite3

class ClosingConnection(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


STATE_DB_PATH = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")


def _get_state_db():
    os.makedirs(os.path.dirname(STATE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(STATE_DB_PATH, timeout=15.0, factory=ClosingConnection)
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


def _get_profile_state_db(profile_name: str = "telegram_bot"):
    """Liefert die profil-spezifische SQLite-Datenbank (z. B. für telegram_bot)."""
    base_dir = os.path.dirname(STATE_DB_PATH)
    prof_path = os.path.join(base_dir, "profiles", profile_name, "state.db")
    if os.path.exists(prof_path):
        conn = sqlite3.connect(prof_path, timeout=15.0, factory=ClosingConnection)
        conn.execute("PRAGMA busy_timeout=15000;")
        return conn
    return None

__all__ = ["ClosingConnection", "STATE_DB_PATH", "_get_state_db", "_get_profile_state_db"]
