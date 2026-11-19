# -*- coding: utf-8 -*-
"""
backend/watchdog_radar_v2.py
============================
Meilenstein 33: Watchdog & Internet-Radar 2.0.

- Semantisches Relevanz-Scoring (Signal vs. Noise)
- Dubletten-Sperre ueber SHA-256 in SQLite WAL (data/watchdog_v2.db)
- Selbstheilung defekter Quellen (Auto-Fallback-URL nach Fehlversuchen)
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "watchdog_v2.db")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_signals (
                sig_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                score REAL NOT NULL,
                seen_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_health (
                source_id TEXT PRIMARY KEY,
                fail_count INTEGER NOT NULL DEFAULT 0,
                active_url TEXT NOT NULL,
                fallback_url TEXT DEFAULT ''
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def score_signal_relevance(title: str, body: str, keywords: List[str], threshold: float = 0.35) -> Dict[str, Any]:
    text = f"{title} {body}".lower()
    kws = [k.lower().strip() for k in keywords if k.strip()]
    if not kws:
        return {"score": 0.5, "is_signal": True}
    hits = sum(1 for k in kws if re.search(rf"\b{re.escape(k)}\b", text) or k in text)
    score = round(min(1.0, hits / max(1, min(len(kws), 4))), 3)
    return {"score": score, "is_signal": score >= threshold, "matched_keywords": hits}


def register_signal_if_new(url: str, title: str, score: float, db_path: Optional[str] = None) -> bool:
    sig_hash = hashlib.sha256(f"{url.strip()}|{title.strip()}".encode("utf-8")).hexdigest()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT sig_hash FROM seen_signals WHERE sig_hash = ?", (sig_hash,)).fetchone()
        if row:
            return False
        conn.execute(
            "INSERT INTO seen_signals (sig_hash, url, score, seen_at) VALUES (?, ?, ?, ?)",
            (sig_hash, url, score, time.time()),
        )
        conn.commit()
    return True


def record_source_health(
    source_id: str,
    primary_url: str,
    fallback_url: str,
    ok: bool,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT fail_count, active_url FROM source_health WHERE source_id = ?", (source_id,)).fetchone()
        fails = 0 if ok else (int(row["fail_count"]) + 1 if row else 1)
        active = primary_url if ok else (fallback_url if fails >= 2 and fallback_url else (row["active_url"] if row else primary_url))
        conn.execute(
            """
            INSERT INTO source_health (source_id, fail_count, active_url, fallback_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET fail_count=excluded.fail_count, active_url=excluded.active_url
            """,
            (source_id, fails, active, fallback_url),
        )
        conn.commit()
    return {"source_id": source_id, "fail_count": fails, "active_url": active, "healed_to_fallback": (not ok and fails >= 2 and bool(fallback_url))}
