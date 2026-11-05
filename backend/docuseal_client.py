"""
backend/docuseal_client.py
Archon OS DocuSeal E-Signature Integration Client.
Handles contract signing workflows, templates, submission creation, and status synchronisation with Kanban and CRM.
"""

import os
import sys
import time
import json
import sqlite3
import datetime
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


class DocuSealClient:
    def __init__(self):
        self.base_url = os.getenv("DOCUSEAL_URL", "http://127.0.0.1:3080").rstrip("/")
        self.internal_url = "http://docuseal:3000"
        self.api_key = os.getenv("DOCUSEAL_API_KEY", "archon_docuseal_key_2026")
        self.kanban_db = _resolve_db("kanban.db")
        self.memory_db = _resolve_db("agentic_memory.db")
        self._init_esign_tables()

    def _init_esign_tables(self):
        """Initialisiert die esign_contracts Tabelle in agentic_memory.db."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS esign_contracts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            submission_id TEXT UNIQUE NOT NULL,
                            template_id TEXT,
                            title TEXT NOT NULL,
                            signer_email TEXT NOT NULL,
                            signer_name TEXT,
                            status TEXT DEFAULT 'pending',
                            sign_url TEXT,
                            kanban_task_id TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            completed_at TIMESTAMP
                        )
                    """)
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Init Warning: {e}", file=sys.stderr)

    def create_submission(
        self,
        title: str,
        signer_email: str,
        signer_name: str,
        template_id: Optional[str] = None,
        kanban_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Erstellt eine neue Signaturanfrage (Submission) via DocuSeal API."""
        submission_id = f"sub_{int(time.time())}_{os.urandom(3).hex()}"
        sign_url = f"{self.base_url}/s/{submission_id}"

        # Versuche DocuSeal REST API aufzurufen
        payload = {
            "template_id": template_id or 1,
            "send_email": True,
            "submitters": [
                {
                    "email": signer_email,
                    "name": signer_name,
                    "role": "Signer"
                }
            ]
        }

        api_called = False
        for ep in [self.base_url, self.internal_url]:
            try:
                req = urllib.request.Request(
                    f"{ep}/api/submissions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-Auth-Token": self.api_key
                    }
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status in (200, 201):
                        data = json.loads(resp.read().decode("utf-8"))
                        submission_id = str(data.get("id") or submission_id)
                        sign_url = data.get("submitters", [{}])[0].get("embed_url") or sign_url
                        api_called = True
                        break
            except Exception:
                continue

        # In SQLite persistieren
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                    conn.execute("""
                        INSERT INTO esign_contracts (
                            submission_id, template_id, title, signer_email,
                            signer_name, status, sign_url, kanban_task_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        submission_id, str(template_id or "default"), title,
                        signer_email, signer_name, "sent", sign_url, kanban_task_id
                    ))
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Error inserting contract: {e}", file=sys.stderr)

        # Optional: Kanban-Task für Rechtsteam anlegen oder updaten
        if not kanban_task_id and os.path.exists(self.kanban_db):
            try:
                task_id = f"task-esign-{submission_id}"
                t_title = f"[E-Signatur] {title} ({signer_name})"
                t_body = (
                    f"Vertrag zur elektronischen Signatur versandt.\n\n"
                    f"- Unterzeichner: {signer_name} <{signer_email}>\n"
                    f"- Submission ID: {submission_id}\n"
                    f"- Signatur-Link: {sign_url}\n"
                    f"- Status: Ausstehend\n"
                )
                with sqlite3.connect(self.kanban_db, timeout=5.0) as conn:
                    conn.execute("""
                        INSERT INTO tasks (
                            id, title, body, assignee, status, priority, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        task_id, t_title, t_body, "legal_counsel", "ready", 2, "docuseal_client",
                        datetime.datetime.now().isoformat()
                    ))
                    conn.commit()
                kanban_task_id = task_id
            except Exception as e:
                print(f"[DocuSeal] Error creating Kanban task: {e}", file=sys.stderr)

        return {
            "status": "success",
            "submission_id": submission_id,
            "title": title,
            "signer_name": signer_name,
            "signer_email": signer_email,
            "sign_url": sign_url,
            "kanban_task_id": kanban_task_id,
            "api_dispatched": api_called
        }

    def handle_webhook_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Verarbeitet eingehende DocuSeal Webhooks (z. B. submission.completed)."""
        event_type = event_data.get("event_type") or event_data.get("type", "")
        data = event_data.get("data", {})
        sub_id = str(data.get("id") or data.get("submission_id", ""))

        if not sub_id:
            return {"status": "ignored", "reason": "No submission_id found"}

        now_iso = datetime.datetime.now().isoformat()
        kanban_task_id = None

        # 1. Update esign_contracts Status in DB
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT kanban_task_id FROM esign_contracts WHERE submission_id = ?", (sub_id,))
                    row = cur.fetchone()
                    if row:
                        kanban_task_id = row[0]
                    cur.execute("""
                        UPDATE esign_contracts
                        SET status = 'completed', completed_at = ?
                        WHERE submission_id = ?
                    """, (now_iso, sub_id))
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Webhook DB error: {e}", file=sys.stderr)

        # 2. Update Kanban-Task falls vorhanden
        if kanban_task_id and os.path.exists(self.kanban_db):
            try:
                with sqlite3.connect(self.kanban_db, timeout=5.0) as conn:
                    conn.execute("""
                        UPDATE tasks
                        SET status = 'done', completed_at = ?, result = 'Vollständig digital unterzeichnet via DocuSeal.'
                        WHERE id = ?
                    """, (now_iso, kanban_task_id))
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Webhook Kanban error: {e}", file=sys.stderr)

        # 3. Benachrichtigung absetzen
        try:
            from backend.notification_hub import get_notification_hub
            get_notification_hub().dispatch_notification(
                title="Vertrag unterzeichnet",
                message=f"DocuSeal Submission '{sub_id}' wurde erfolgreich unterzeichnet.",
                severity="INFO",
                category="legal_contract"
            )
        except Exception:
            pass

        return {
            "status": "processed",
            "event_type": event_type,
            "submission_id": sub_id,
            "kanban_task_updated": kanban_task_id
        }

    def list_contracts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Listet Signaturverträge auf."""
        if not os.path.exists(self.memory_db):
            return []
        try:
            with sqlite3.connect(f"file:{self.memory_db}?mode=ro&immutable=1", uri=True, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT submission_id, template_id, title, signer_email, signer_name,
                           status, sign_url, kanban_task_id, created_at, completed_at
                    FROM esign_contracts
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[DocuSeal] Error listing contracts: {e}", file=sys.stderr)
            return []


docuseal_client = DocuSealClient()
