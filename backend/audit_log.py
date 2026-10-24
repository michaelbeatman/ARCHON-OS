"""
backend/audit_log.py
Kryptografisch verkettetes Audit-Log (Pillar 6 / Zero-Trust & Revisionssicherheit).
Jeder signifikante System- oder Agenten-Eingriff (Tool-Aufruf, Dateiänderung,
Berechtigung, Modell-Routing) wird in einer Append-Only SQLite-Tabelle mit
SHA-256 Hashverkettung (Blockchain-Prinzip) manipulationssicher protokolliert.
"""

import os
import sys
import json
import hashlib
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
GENESIS_HASH = "0" * 64

class ChainedAuditLog:
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
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def record_event(self, event_type: str, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Fügt ein neues manipulationssicheres Ereignis an die Hashkette an."""
        payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        now_iso = datetime.datetime.now().isoformat()

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1")
            last_row = cur.fetchone()
            prev_hash = last_row["current_hash"] if last_row else GENESIS_HASH

            # Hash-Berechnung: SHA256(prev_hash + event_type + agent_id + payload + timestamp)
            hash_input = f"{prev_hash}:{event_type}:{agent_id}:{payload_str}:{now_iso}"
            current_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            cur.execute("""
                INSERT INTO audit_log (event_type, agent_id, payload_json, prev_hash, current_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_type, agent_id, payload_str, prev_hash, current_hash, now_iso))
            conn.commit()
            event_id = cur.lastrowid

            return {
                "event_id": event_id,
                "event_type": event_type,
                "prev_hash": prev_hash,
                "current_hash": current_hash,
                "created_at": now_iso
            }

    def verify_integrity(self) -> Dict[str, Any]:
        """Prüft die gesamte Hashkette von Anfang bis Ende auf Manipulationen."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, event_type, agent_id, payload_json, prev_hash, current_hash, created_at FROM audit_log ORDER BY id ASC")
            rows = cur.fetchall()

            if not rows:
                return {"valid": True, "total_events": 0, "message": "Audit-Log ist leer."}

            expected_prev = GENESIS_HASH
            for idx, r in enumerate(rows):
                # 1. Prüfe Kettenglied
                if r["prev_hash"] != expected_prev:
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "error": f"Hashketten-Bruch an Eintrag {r['id']}: Vorheriger Hash stimmt nicht überein."
                    }
                # 2. Prüfe Inhalts-Hash
                hash_input = f"{r['prev_hash']}:{r['event_type']}:{r['agent_id']}:{r['payload_json']}:{r['created_at']}"
                calculated = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
                if calculated != r["current_hash"]:
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "error": f"Signatur-Verletzung an Eintrag {r['id']}: Daten wurden nachträglich manipuliert."
                    }
                expected_prev = r["current_hash"]

            return {
                "valid": True,
                "total_events": len(rows),
                "latest_hash": expected_prev,
                "message": f"Audit-Log integer: Alle {len(rows)} Ereignisse sind kryptografisch intakt."
            }

    def list_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
            res = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["payload"] = json.loads(d["payload_json"])
                except Exception:
                    d["payload"] = {}
                res.append(d)
            return res

chained_audit_log = ChainedAuditLog()
