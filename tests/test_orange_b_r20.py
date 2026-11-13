"""Regressionstest R-20 (+ F-01): Kanban-KPIs muessen ISO-Zeitstempel verarbeiten.

Alle Zeitstempel von operations_api sind ISO-Strings ("2026-11-08T09:00:00").
`float(iso_string)` wirft ValueError -> avg_cycle_hours war immer None und
done_7d immer 0. F-01 ist dieselbe Stelle (Z. 1753/1765) und wird hier
mit abgedeckt.
"""

import datetime
import os
import sqlite3
import sys
from unittest import mock

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import backend.operations_api as ops  # noqa: E402


def test_parse_kanban_ts_handles_iso_and_epoch():
    assert ops._parse_kanban_ts("2026-11-08T09:00:00") is not None
    assert ops._parse_kanban_ts(1770000000.0) == 1770000000.0
    assert ops._parse_kanban_ts("1770000000") == 1770000000.0  # epoch als String
    assert ops._parse_kanban_ts("2026-11-08T09:00:00Z") is not None
    assert ops._parse_kanban_ts(None) is None
    assert ops._parse_kanban_ts("kaputt") is None


def test_kanban_stats_fills_kpis_from_iso_rows():
    now = datetime.datetime.now()
    started = (now - datetime.timedelta(hours=4)).isoformat()
    completed_recent = (now - datetime.timedelta(hours=2)).isoformat()
    completed_old = (now - datetime.timedelta(days=20)).isoformat()

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE tasks (
            id TEXT PRIMARY KEY, status TEXT, created_at TEXT,
            started_at TEXT, completed_at TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO tasks VALUES ('a', 'done', ?, ?, ?)",
        ((now - datetime.timedelta(days=1)).isoformat(), started, completed_recent),
    )
    conn.execute(
        "INSERT INTO tasks VALUES ('b', 'archived', ?, ?, ?)",
        ((now - datetime.timedelta(days=21)).isoformat(),
         (now - datetime.timedelta(days=21)).isoformat(),
         completed_old),
    )

    with mock.patch.object(ops, "_get_kanban_connection", return_value=conn):
        stats = ops.kanban_stats()

    assert stats["avg_cycle_hours"] is not None
    assert 0 < stats["avg_cycle_hours"] < 14  # a: ~2h, b: ~24h → Mittel < 14h
    assert stats["done_7d"] == 1               # nur die aktuelle, nicht die 20 Tage alte
    assert stats["blocked"] == 0
