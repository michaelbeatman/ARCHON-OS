"""
backend/event_mesh.py
Event-Driven Inbound & Outbound Webhook-Bus für Archon OS.
Ermöglicht externen Systemen (n8n, GitHub, Webhook-Dienste),
Ereignisse direkt einzuspeisen und autonome Workflows zu triggern.
"""

import os
import sys
import json
import sqlite3
import datetime
import urllib.request
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class EventMesh:
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
                CREATE TABLE IF NOT EXISTS event_mesh_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT DEFAULT 'processed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def ingest_inbound_event(self, channel: str, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Nimmt ein externes Webhook-Ereignis (z. B. von n8n oder GitHub) entgegen."""
        now_iso = datetime.datetime.now().isoformat()
        payload_str = json.dumps(payload, ensure_ascii=False)

        # 1. Protokollieren
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO event_mesh_log (channel, event_type, direction, payload_json, status, created_at)
                VALUES (?, ?, 'inbound', ?, 'processed', CURRENT_TIMESTAMP)
            """, (channel, event_type, payload_str))
            conn.commit()
            evt_id = cur.lastrowid

        # 2. Wenn es ein n8n-Trigger ist -> Aufgabe in Kanban erstellen
        task_id = None
        if "task" in event_type.lower() or channel == "n8n":
            task_id = f"evt-{channel}-{datetime.datetime.now().strftime('%m%d%H%M%S')}"
            try:
                from local_memory_bridge import LocalMemoryBridge
                bridge = LocalMemoryBridge()
                bridge.sync_task(
                    task_id=task_id,
                    title=payload.get("title", f"Event aus {channel}: {event_type}"),
                    role="hermes-orchestrator",
                    status="todo"
                )
            except Exception:
                pass

        return {
            "status": "success",
            "event_id": evt_id,
            "channel": channel,
            "event_type": event_type,
            "kanban_task_id": task_id,
            "message": f"Ereignis aus Kanal '{channel}' erfolgreich im Event-Mesh verarbeitet."
        }

    def emit_outbound_event(self, webhook_url: str, event_type: str, payload: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        """Sendet einen Outbound-Event-Webhook an ein externes Ziel (z. B. n8n)."""
        payload_str = json.dumps(payload, ensure_ascii=False)
        req_data = payload_str.encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=req_data,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                res_body = resp.read().decode("utf-8", errors="ignore")[:300]
                status_str = "delivered"
        except Exception as e:
            status_code = 500
            res_body = str(e)
            status_str = "delivery_failed"

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO event_mesh_log (channel, event_type, direction, payload_json, status, created_at)
                VALUES (?, ?, 'outbound', ?, ?, CURRENT_TIMESTAMP)
            """, (webhook_url, event_type, payload_str, status_str))
            conn.commit()

        return {
            "status": status_str,
            "http_status": status_code,
            "target_url": webhook_url,
            "response": res_body
        }

    def scan_inbox_directory(self, inbox_dir: Optional[str] = None) -> Dict[str, Any]:
        """Prüft das Posteingangs-Verzeichnis auf neue Dokumente und erzeugt Event-Mesh-Einträge."""
        target_dir = inbox_dir or os.path.join(WORKSPACE_DIR, "data", "inbox")
        if not os.path.exists(target_dir):
            return {"status": "ok", "scanned_files": 0, "events_created": 0}

        created = []
        for fname in os.listdir(target_dir):
            fpath = os.path.join(target_dir, fname)
            if os.path.isfile(fpath) and not fname.startswith("."):
                fsize = os.path.getsize(fpath)
                evt = self.ingest_inbound_event(
                    channel="file_watcher",
                    event_type="document_received",
                    payload={"file_name": fname, "file_path": fpath, "file_size": fsize, "title": f"Posteingang: {fname}"}
                )
                created.append(evt)

        return {
            "status": "success",
            "inbox_directory": target_dir,
            "scanned_files": len(created),
            "events_created": len(created),
            "events": created
        }

    def list_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM event_mesh_log ORDER BY id DESC LIMIT ?", (limit,))
            res = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["payload"] = json.loads(d["payload_json"])
                except Exception:
                    d["payload"] = {}
                res.append(d)
            return res

event_mesh = EventMesh()
