"""
backend/human_feedback_engine.py
Human-Feedback-Loop für Agenten-Ergebnisse & Qualitäts-Steuerung (Pillar 6 & 7).
Erfasst Daumen hoch/runter, Korrekturen und Bewertungen zu Agenten-Ergebnissen.
Leitet negative Bewertungen automatisiert als Regressionstests an eval_regression_runner
und als Fehlermuster an den prompt_optimizer weiter.
"""

import os
import sys
import json
import uuid
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class HumanFeedbackEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        try:
            from backend.eval_regression_runner import _init_db as init_eval_db
            init_eval_db()
        except Exception:
            pass

        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS human_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id TEXT UNIQUE NOT NULL,
                    task_id TEXT,
                    agent_id TEXT NOT NULL,
                    score INTEGER NOT NULL, -- +1 (Daumen hoch) oder -1 (Daumen runter)
                    comment TEXT,
                    corrected_text TEXT,
                    source TEXT DEFAULT 'kanban_card', -- 'kanban_card', 'chat', 'robert_review'
                    auto_eval_case_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_task ON human_feedback(task_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_agent ON human_feedback(agent_id);")
            conn.commit()

    def submit_feedback(
        self,
        agent_id: str,
        score: int,
        task_id: Optional[str] = None,
        comment: Optional[str] = None,
        corrected_text: Optional[str] = None,
        source: str = "kanban_card",
        task_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Speichert Nutzer-Feedback zu einem Task oder Agenten.
        Triggert bei Daumen runter (-1) automatisch einen Gold-Standard-Testfall
        sowie eine Überprüfung im Prompt-Optimizer.
        """
        feedback_id = f"fb-{uuid.uuid4().hex[:10]}"
        now_iso = datetime.datetime.now().isoformat()
        auto_eval_case_id = None

        # Falls Daumen runter: Automatisch Gold-Standard-Fall anlegen
        if score < 0:
            auto_eval_case_id = f"GOLD-FB-{feedback_id[3:9].upper()}"
            try:
                self._create_auto_gold_case(
                    case_id=auto_eval_case_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    task_prompt=task_prompt or comment or f"Task {task_id}",
                    comment=comment,
                    corrected_text=corrected_text
                )
            except Exception as e:
                print(f"[HumanFeedback] Fehler beim Erstellen des Eval-Falls: {e}", file=sys.stderr)

            # Prüfe, ob Prompt-Optimizer aktiviert werden soll
            try:
                self._check_prompt_optimizer_trigger(agent_id, comment or "Mangelhafte Qualität")
            except Exception as e:
                print(f"[HumanFeedback] Fehler beim Prompt-Optimizer Hook: {e}", file=sys.stderr)

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO human_feedback (
                    feedback_id, task_id, agent_id, score, comment,
                    corrected_text, source, auto_eval_case_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                feedback_id, task_id, agent_id, score, comment,
                corrected_text, source, auto_eval_case_id, now_iso
            ))
            conn.commit()

        return {
            "status": "success",
            "feedback_id": feedback_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "score": score,
            "auto_eval_case_id": auto_eval_case_id
        }

    def _create_auto_gold_case(
        self,
        case_id: str,
        agent_id: str,
        task_id: Optional[str],
        task_prompt: str,
        comment: Optional[str],
        corrected_text: Optional[str]
    ):
        """Erstellt einen Gold-Standard-Regressionstestfall in eval_gold_cases."""
        with self._get_conn() as conn:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            expected_keywords = []
            if corrected_text:
                # Nimm signifikante Wörter aus der Korrektur
                words = [w.strip() for w in corrected_text.split() if len(w.strip()) > 4]
                expected_keywords = words[:5]
            if not expected_keywords and comment:
                expected_keywords = [w.strip() for w in comment.split() if len(w.strip()) > 4][:3]

            forbidden_keywords = ["hallucination", "error", "unvollständig"]

            conn.execute("""
                INSERT OR REPLACE INTO eval_gold_cases (
                    case_id, category, input_prompt, expected_keywords_json, forbidden_keywords_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                case_id,
                f"agent_{agent_id}",
                task_prompt[:300],
                json.dumps(expected_keywords, ensure_ascii=False),
                json.dumps(forbidden_keywords, ensure_ascii=False),
                now_str
            ))
            conn.commit()

    def _check_prompt_optimizer_trigger(self, agent_id: str, reason: str):
        """Sammelt negative Bewertungen und stößt bei Bedarf den Prompt-Optimizer an."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT comment FROM human_feedback
                WHERE agent_id = ? AND score < 0
                ORDER BY created_at DESC LIMIT 5
            """, (agent_id,))
            neg_rows = cur.fetchall()
            failures = [r[0] for r in neg_rows if r[0]]
            if len(failures) < 3:
                return  # Schwellenwert noch nicht erreicht

        try:
            from backend.prompt_optimizer import PromptOptimizer
            opt = PromptOptimizer()
            opt.optimize_role_prompt(
                agent_role=agent_id,
                current_prompt=f"Rollen-Direktiven für {agent_id}",
                recent_failures=failures
            )
        except Exception:
            pass

    def get_stats(self) -> Dict[str, Any]:
        """Gibt globale Feedback-Statistiken und Agenten-Rankings zurück."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END), SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END) FROM human_feedback")
            tot_row = cur.fetchone()
            total = tot_row[0] or 0
            pos = tot_row[1] or 0
            neg = tot_row[2] or 0
            approval_rate = round((pos / total * 100), 1) if total > 0 else 100.0

            cur.execute("""
                SELECT agent_id, 
                       COUNT(*) as total_count,
                       SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END) as pos_count,
                       SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END) as neg_count
                FROM human_feedback
                GROUP BY agent_id
                ORDER BY total_count DESC
            """)
            agents_breakdown = [
                {
                    "agent_id": r["agent_id"],
                    "total": r["total_count"],
                    "positive": r["pos_count"],
                    "negative": r["neg_count"],
                    "approval_rate": round(r["pos_count"] / r["total_count"] * 100, 1) if r["total_count"] > 0 else 100.0
                }
                for r in cur.fetchall()
            ]

            return {
                "total_feedbacks": total,
                "positive": pos,
                "negative": neg,
                "approval_rate_pct": approval_rate,
                "agents": agents_breakdown
            }

    def get_task_feedback(self, task_id: str) -> List[Dict[str, Any]]:
        """Gibt alle Feedback-Einträge für einen konkreten Task zurück."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM human_feedback WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
            return [dict(r) for r in cur.fetchall()]

# Globales Singleton
feedback_engine = HumanFeedbackEngine()
