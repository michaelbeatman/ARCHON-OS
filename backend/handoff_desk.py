"""
backend/handoff_desk.py
Standardisierter Agent-to-Agent Handoff-Desk (Pillar 2).
Erstellt bei Rollenübergaben (z. B. Researcher an Coder) ein formales Übergabe-Dokument
mit Prüfsumme, Annahmen und Akzeptanzkriterien gegen Informationsverlust.
"""

import os
import sys
import json
import sqlite3
import datetime
import hashlib
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class HandoffDesk:
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
                CREATE TABLE IF NOT EXISTS agent_handoffs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    deliverables_json TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT DEFAULT 'pending_acceptance',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP
                )
            """)
            conn.commit()

    def create_handoff(
        self,
        task_id: str,
        from_agent: str,
        to_agent: str,
        deliverables: Dict[str, Any],
        acceptance_criteria: str
    ) -> Dict[str, Any]:
        """Erzeugt ein manipulationssicheres Übergabe-Dokument."""
        h_id = f"handoff-{datetime.datetime.now().strftime('%m%d%H%M%S')}"
        deliv_str = json.dumps(deliverables, sort_keys=True, ensure_ascii=False)
        p_hash = hashlib.sha256(f"{task_id}:{from_agent}:{to_agent}:{deliv_str}".encode("utf-8")).hexdigest()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO agent_handoffs (id, task_id, from_agent, to_agent, deliverables_json, acceptance_criteria, payload_hash, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_acceptance', CURRENT_TIMESTAMP)
            """, (h_id, task_id, from_agent, to_agent, deliv_str, acceptance_criteria, p_hash))
            conn.commit()

        return {
            "status": "pending_acceptance",
            "handoff_id": h_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload_hash": p_hash,
            "message": f"Übergabe von '{from_agent}' an '{to_agent}' protokolliert. Quittung ausstehend."
        }

    def accept_handoff(self, handoff_id: str, receiving_agent: str) -> Dict[str, Any]:
        """Der Folge-Agent quittiert die fehlerfreie Übernahme."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_handoffs WHERE id = ?", (handoff_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": f"Übergabe {handoff_id} nicht gefunden."}

            item = dict(row)
            if item["to_agent"] != receiving_agent and receiving_agent != "hermes-orchestrator":
                return {"status": "error", "message": f"Agent {receiving_agent} ist nicht der autorisierte Empfänger."}

            conn.execute("""
                UPDATE agent_handoffs
                SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (handoff_id,))
            conn.commit()

            return {
                "status": "accepted",
                "handoff_id": handoff_id,
                "message": f"Übergabe von '{receiving_agent}' quittiert. Bearbeitung freigegeben."
            }

    def get_handoff(self, handoff_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_handoffs WHERE id = ?", (handoff_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["deliverables"] = json.loads(d["deliverables_json"])
            except Exception:
                d["deliverables"] = {}
            return d

handoff_desk = HandoffDesk()
