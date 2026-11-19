# -*- coding: utf-8 -*-
"""
backend/time_tracking_invoice.py
================================
Meilenstein 37: Zeiterfassung & Projekt-Nachkalkulation (Time-to-Invoice).

Start/Stop-Timer in SQLite WAL (data/time_tracking.db), Soll-/Ist-Budgetabgleich
und 1-Klick-Export gebuchter Stunden als ERP-Rechnungspositionen.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "time_tracking.db")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS time_entries (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_id TEXT DEFAULT '',
                description TEXT DEFAULT '',
                hourly_rate_eur REAL NOT NULL DEFAULT 120.0,
                started_at REAL NOT NULL,
                stopped_at REAL,
                duration_hours REAL NOT NULL DEFAULT 0.0
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def start_timer(
    project_id: str,
    task_id: str = "",
    description: str = "",
    hourly_rate_eur: float = 120.0,
    started_at: Optional[float] = None,
    db_path: Optional[str] = None,
) -> str:
    eid = f"tm-{secrets.token_hex(5)}"
    ts = started_at if started_at is not None else time.time()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO time_entries (id, project_id, task_id, description, hourly_rate_eur, started_at) VALUES (?, ?, ?, ?, ?, ?)",
            (eid, project_id, task_id, description, float(hourly_rate_eur), ts),
        )
        conn.commit()
    return eid


def stop_timer(
    entry_id: str,
    stopped_at: Optional[float] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    end_ts = stopped_at if stopped_at is not None else time.time()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        dur_h = round(max(0.01, (end_ts - float(row["started_at"])) / 3600.0), 4)
        conn.execute(
            "UPDATE time_entries SET stopped_at = ?, duration_hours = ? WHERE id = ?",
            (end_ts, dur_h, entry_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(updated)


def compute_project_budget_variance(
    project_id: str,
    budget_hours: float,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT duration_hours, hourly_rate_eur FROM time_entries WHERE project_id = ? AND stopped_at IS NOT NULL",
            (project_id,),
        ).fetchall()
    actual_h = round(sum(float(r["duration_hours"]) for r in rows), 2)
    total_eur = round(sum(float(r["duration_hours"]) * float(r["hourly_rate_eur"]) for r in rows), 2)
    return {
        "project_id": project_id,
        "budget_hours": float(budget_hours),
        "actual_hours": actual_h,
        "variance_hours": round(float(budget_hours) - actual_h, 2),
        "over_budget": actual_h > float(budget_hours),
        "billable_total_eur": total_eur,
    }


def export_invoice_line_items(project_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, task_id, description, duration_hours, hourly_rate_eur FROM time_entries WHERE project_id = ? AND stopped_at IS NOT NULL",
            (project_id,),
        ).fetchall()
    return [
        {
            "entry_id": r["id"],
            "description": r["description"] or f"Projektarbeit ({r['task_id'] or project_id})",
            "quantity_hours": float(r["duration_hours"]),
            "unit_price_eur": float(r["hourly_rate_eur"]),
            "net_total_eur": round(float(r["duration_hours"]) * float(r["hourly_rate_eur"]), 2),
        }
        for r in rows
    ]
