"""
backend/tool_permission_manager.py
Human-in-the-Loop Berechtigungsverwaltung für autonome Tool-Installationen durch Robert.
Wenn Robert oder ein Subagent ein fehlendes Tool/Paket benötigt:
1. Robert erstellt ein Installations-Gesuch (Status: pending_permission).
2. Der Benutzer erhält eine Benachrichtigung und kann genehmigen oder ablehnen.
3. Erst nach ausdrücklicher Genehmigung führt Robert die Installation im System aus.
"""

import os
import sys
import json
import sqlite3
import datetime
import subprocess
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class ToolPermissionManager:
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
                CREATE TABLE IF NOT EXISTS tool_permissions (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    tool_type TEXT NOT NULL,
                    reason TEXT,
                    command_to_run TEXT,
                    requested_by TEXT DEFAULT 'Robert (Lead Orchestrator)',
                    status TEXT DEFAULT 'pending_permission',
                    log_output TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP
                )
            """)
            conn.commit()

    def propose_tool_installation(self, tool_name: str, tool_type: str = "pip", reason: str = "", command: str = None, requested_by: str = "Robert (Lead Orchestrator)") -> Dict[str, Any]:
        """Robert reicht einen Antrag zur Installation eines neuen Tools ein."""
        req_id = f"tool-perm-{datetime.datetime.now().strftime('%m%d%H%M%S')}"
        if not command:
            if tool_type == "pip":
                command = f"{sys.executable} -m pip install {tool_name}"
            elif tool_type == "npm":
                command = f"npm install -g {tool_name}"
            else:
                command = f"# Manueller Installationsbefehl fuer {tool_name}"

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO tool_permissions (id, tool_name, tool_type, reason, command_to_run, requested_by, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending_permission', CURRENT_TIMESTAMP)
            """, (req_id, tool_name, tool_type, reason, command, requested_by))
            conn.commit()

        return {
            "status": "pending_permission",
            "permission_id": req_id,
            "tool_name": tool_name,
            "tool_type": tool_type,
            "command": command,
            "message": f"Robert hat die Installation von '{tool_name}' beantragt. Benutzer-Genehmigung ausstehend."
        }

    def list_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if status:
                cur.execute("SELECT * FROM tool_permissions WHERE status = ? ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM tool_permissions ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def resolve_proposal(self, permission_id: str, action: str = "grant") -> Dict[str, Any]:
        """Benutzer genehmigt ('grant') oder verweigert ('reject') die Installation."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tool_permissions WHERE id = ?", (permission_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": f"Antrag {permission_id} nicht gefunden."}

            item = dict(row)
            if action.lower() != "grant":
                conn.execute("""
                    UPDATE tool_permissions
                    SET status = 'rejected', resolved_at = CURRENT_TIMESTAMP, log_output = 'Vom Benutzer abgelehnt.'
                    WHERE id = ?
                """, (permission_id,))
                conn.commit()
                return {"status": "rejected", "permission_id": permission_id, "tool_name": item["tool_name"]}

            # Benutzer hat genehmigt -> Robert führt die Installation nun autonom aus!
            cmd = item.get("command_to_run")
            now_iso = datetime.datetime.now().isoformat()
            try:
                import shlex
                cmd_args = shlex.split(cmd) if isinstance(cmd, str) else cmd
                proc = subprocess.run(cmd_args, shell=False, capture_output=True, text=True, timeout=120)
                output = f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                final_status = "installed" if proc.returncode == 0 else "failed"
            except Exception as exc:
                output = f"Execution Exception: {str(exc)}"
                final_status = "failed"

            conn.execute("""
                UPDATE tool_permissions
                SET status = ?, resolved_at = CURRENT_TIMESTAMP, log_output = ?
                WHERE id = ?
            """, (final_status, output, permission_id))
            conn.commit()

            return {
                "status": final_status,
                "permission_id": permission_id,
                "tool_name": item["tool_name"],
                "log": output[:600]
            }

tool_permission_manager = ToolPermissionManager()
