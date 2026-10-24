"""
backend/task_self_healer.py
Autonome Task-Selbstheilung mit Git/Snapshot-Rollback (Pillar 1 & 6).
Überwacht fehlerhafte Task-Läufe, rollt fehlerhafte Datei-Patches automatisch zurück
und startet eine iterative Reparatur-Schleife (max. 3 Retries) vor der Eskalation ins HITL-Board.
"""

import os
import sys
import json
import sqlite3
import subprocess
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class TaskSelfHealer:
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
                CREATE TABLE IF NOT EXISTS task_healing_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    error_trace TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    rollback_success INTEGER DEFAULT 1,
                    repaired_successfully INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def rollback_git_changes(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Setzt nicht committete Änderungen über Git zurück."""
        cmd = f"git checkout -- {file_path}" if file_path else "git checkout -- ."
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=WORKSPACE_DIR, timeout=10)
            return {"status": "success" if res.returncode == 0 else "error", "output": res.stdout or res.stderr}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def attempt_self_healing(
        self,
        task_id: str,
        task_title: str,
        failed_code: str,
        error_output: str,
        worker_agent: str = "hermes-coder",
        affected_file: Optional[str] = None,
        attempt: int = 1,
        max_attempts: Optional[int] = None,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Führt einen geschlossenen Selbstheilungs-Durchlauf durch:
        1. Rollback der defekten Datei(en)
        2. Reflection & Code-Korrektur über LLM
        3. Protokollierung in task_healing_logs
        """
        auto_rollback = True
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("task_self_healer")
            if not cfg.get("enabled", True):
                return {"status": "disabled", "task_id": task_id, "message": "Task-Selbstheilung ist in den Einstellungen deaktiviert."}
            auto_rollback = bool(cfg.get("auto_git_rollback", True))
            if max_attempts is None:
                max_attempts = int(cfg.get("max_attempts", 3))
            if not model:
                model = cfg.get("escalation_model", "deepseek/deepseek-chat")
        except Exception:
            if max_attempts is None:
                max_attempts = 3
            if not model:
                model = "deepseek/deepseek-chat"

        # 1. Rollback
        rollback_res = self.rollback_git_changes(affected_file) if auto_rollback else {"status": "skipped"}
        rollback_ok = rollback_res.get("status") in ("success", "skipped")

        # 2. Reflection Prompt generieren
        healing_prompt = f"""Du bist der Auto-Repair & Self-Healing Supervisor von Archon OS.
Die Ausführung des folgenden Codes für Task '{task_title}' ist mit einem Fehler fehlgeschlagen.

FEHLER-OUTPUT / STACKTRACE:
{error_output[:2500]}

FEHLERHAFTER CODE / ENTWURF:
{failed_code[:3000]}

AUFGABE:
1. Analysiere präzise die Fehlerursache (Syntax, fehlender Import, NullPointer, falsche API).
2. Liefere die korrigierte, vollständige und lauffähige Version.
3. Begründe kurz die Behebung.

Antworte strukturiert mit der korrigierten Fassung."""

        import core_dispatcher
        repaired_code = ""
        repaired_ok = False
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id="self-healing-agent",
                agent_name="Self-Healing Supervisor",
                prompt=healing_prompt,
                role="Senior Auto-Repair Engineer",
                system_prompt="Du bist ein hochpräziser Reparatur-Ingenieur. Behebe den Fehler vollständig.",
                model=model
            )
            repaired_code = res.get("content", "")
            repaired_ok = bool(repaired_code and len(repaired_code) > 50)
        except Exception as err:
            repaired_code = f"Reparatur-Versuch fehlgeschlagen: {err}"

        # 3. Loggen
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO task_healing_logs 
                (task_id, attempt, error_trace, action_taken, rollback_success, repaired_successfully, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                task_id,
                attempt,
                error_output[:1000],
                f"Rollback {affected_file or 'alle'} + Reflection Prompt",
                1 if rollback_ok else 0,
                1 if repaired_ok else 0
            ))
            conn.commit()

        # 4. Wenn max_attempts erreicht und nicht repariert -> Task auf 'blocked' setzen
        if attempt >= max_attempts and not repaired_ok:
            try:
                from local_memory_bridge import LocalMemoryBridge
                bridge = LocalMemoryBridge()
                bridge.sync_task(
                    task_id=task_id,
                    title=f"[SELBSTHEILUNG FEHLGESCHLAGEN] {task_title}",
                    role=worker_agent,
                    status="blocked"
                )
            except Exception:
                pass

        return {
            "status": "repaired" if repaired_ok else "failed",
            "task_id": task_id,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "rollback_applied": rollback_ok,
            "repaired_code_preview": repaired_code[:300] + ("..." if len(repaired_code) > 300 else ""),
            "repaired_code": repaired_code,
            "next_action": "Task weiterführen" if repaired_ok else ("Wiederholen" if attempt < max_attempts else "Auf Blockiert gesetzt (HITL)")
        }

    def get_healing_logs(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Liefert die Historie der Selbstheilungs-Versuche."""
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM task_healing_logs ORDER BY id DESC LIMIT ?", (limit,))
                return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

task_self_healer = TaskSelfHealer()
