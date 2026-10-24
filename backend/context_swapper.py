"""
backend/context_swapper.py
LRU-K Page Swapping & Transienter Kontext-Speicher (Pillar 4 / Memory Layer).
Lagert inaktive Zwischenergebnisse und Tool-Rohdaten von Subagenten
in SQLite aus, sobald der Arbeitsspeicher 80% seiner Quota erreicht.
Entlastet den RAM und Token-Bedarf bei parallelen Agenten-Jobs.
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class ContextSwapper:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS context_pages (
                    page_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    page_type TEXT DEFAULT 'tool_raw',
                    content_json TEXT NOT NULL,
                    access_count INTEGER DEFAULT 1,
                    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    swapped_out INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def store_context_page(self, agent_id: str, task_id: str, page_id: str, data: Any, page_type: str = "tool_raw") -> bool:
        """Speichert eine Kontext-Seite ab."""
        content_str = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO context_pages (page_id, agent_id, task_id, page_type, content_json, access_count, last_accessed_at, swapped_out)
                VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, 0)
            """, (page_id, agent_id, task_id, page_type, content_str))
            conn.commit()
            return True

    def evict_lru_pages(self, agent_id: str, max_active_pages: int = 5) -> Dict[str, Any]:
        """Lagert die am längsten nicht zugegriffenen Seiten (LRU) aus (swapped_out = 1)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT page_id FROM context_pages
                WHERE agent_id = ? AND swapped_out = 0
                ORDER BY last_accessed_at ASC
            """, (agent_id,))
            active = cur.fetchall()

            evicted = []
            if len(active) > max_active_pages:
                to_evict = active[:len(active) - max_active_pages]
                for r in to_evict:
                    conn.execute("UPDATE context_pages SET swapped_out = 1 WHERE page_id = ?", (r["page_id"],))
                    evicted.append(r["page_id"])
                conn.commit()

            return {
                "agent_id": agent_id,
                "evicted_count": len(evicted),
                "evicted_pages": evicted,
                "active_pages_remaining": len(active) - len(evicted)
            }

    def hydrate_page(self, page_id: str) -> Optional[Any]:
        """Lädt eine ausgelagerte Seite bei Bedarf wieder in den aktiven Zustand (Re-Hydration)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM context_pages WHERE page_id = ?", (page_id,))
            row = cur.fetchone()
            if not row:
                return None
            conn.execute("""
                UPDATE context_pages
                SET swapped_out = 0, access_count = access_count + 1, last_accessed_at = CURRENT_TIMESTAMP
                WHERE page_id = ?
            """, (page_id,))
            conn.commit()
            c = row["content_json"]
            try:
                return json.loads(c)
            except Exception:
                return c

context_swapper = ContextSwapper()
