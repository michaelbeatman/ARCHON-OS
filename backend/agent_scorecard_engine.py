"""
backend/agent_scorecard_engine.py
Aggregiert Leistungsdaten, KPIs, 4-Augen-Scores, Kosten, Durchlaufzeiten
und Operator-Notizen für die Agent-Scorecards in der Personalakte (t-f257ba).
Synchronisiert qualitative Beurteilungen mit dem lokalen Obsidian HR-Vault.
"""

import os
import sqlite3
import json
import datetime
from typing import Dict, Any, List, Optional

from backend.platform_paths import PERSONALAKTEN_DIR

KANBAN_DB_PATH = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else os.path.expanduser("~/.hermes/kanban.db")
MEMORY_DB_PATH = "/opt/data/agentic_memory.db" if os.path.exists("/opt/data/agentic_memory.db") else os.path.expanduser("~/.hermes/agentic_memory.db")
OBSIDIAN_VAULT_DIRS = [
    "/opt/data/obsidian/00_HR_Agenten/Personalakten",
    os.path.expanduser("~/obsidian/00_HR_Agenten/Personalakten"),
    PERSONALAKTEN_DIR
]

class AgentScorecardEngine:
    def __init__(self, kanban_db: str = KANBAN_DB_PATH, memory_db: str = MEMORY_DB_PATH):
        self.kanban_db = kanban_db
        self.memory_db = memory_db

    def _get_kanban_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.kanban_db, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_memory_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.memory_db, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_scorecard(self, agent_id: str) -> Dict[str, Any]:
        """Berechnet alle Scorecard-KPIs und zieht qualitative Projektdaten zusammen."""
        # 1. Kanban Tasks des Agenten abfragen
        tasks = []
        try:
            with self._get_kanban_conn() as kconn:
                rows = kconn.execute("""
                    SELECT id, title, status, priority, created_at, started_at, completed_at, result
                    FROM tasks
                    WHERE assignee = ? OR assignee = ? OR assignee LIKE ?
                    ORDER BY created_at DESC
                """, (agent_id, agent_id.replace("_", "-"), f"%{agent_id}%")).fetchall()
                tasks = [dict(r) for r in rows]
        except Exception as e:
            print(f"[ScorecardEngine] Error loading tasks: {e}")

        # 2. Sidecar Metadaten (Tokens, Kosten, 4-Augen Review, Obsidian Projekte)
        from backend.kanban_sidecar import load_kanban_meta
        meta = load_kanban_meta()
        meta_tasks = meta.get("tasks", {})

        total_tasks = len(tasks)
        completed_tasks = [t for t in tasks if t["status"] == "done"]
        completed_count = len(completed_tasks)
        in_progress_count = len([t for t in tasks if t["status"] == "in_progress"])
        review_count = len([t for t in tasks if t["status"] == "review"])

        # Durchlaufzeit (Speed) berechnen
        durations = []
        for t in completed_tasks:
            s_at = t.get("started_at")
            c_at = t.get("completed_at")
            if s_at and c_at:
                try:
                    t_start = datetime.datetime.fromisoformat(s_at.replace("Z", "+00:00"))
                    t_comp = datetime.datetime.fromisoformat(c_at.replace("Z", "+00:00"))
                    diff_m = (t_comp - t_start).total_seconds() / 60.0
                    if 0 < diff_m < 10080:  # Plausibel: bis zu 7 Tage
                        durations.append(diff_m)
                except Exception:
                    pass

        avg_duration_minutes = round(sum(durations) / len(durations), 1) if durations else 0.0

        # Token & Kosten Aggregation
        total_tokens = 0
        total_cost = 0.0
        review_scores = []
        review_approved_count = 0
        projects = set()

        for t in tasks:
            tid = t["id"]
            tmeta = meta_tasks.get(tid, {})
            tok = tmeta.get("tokens") or 0
            if isinstance(tok, (int, float)):
                total_tokens += int(tok)

            cost = tmeta.get("cost") or 0.0
            if isinstance(cost, (int, float)):
                total_cost += float(cost)

            q_rev = tmeta.get("quality_review")
            if q_rev:
                if q_rev.get("status") == "approved":
                    review_approved_count += 1
                if q_rev.get("score"):
                    review_scores.append(q_rev["score"])

            obs = tmeta.get("obsidian")
            if obs:
                p_name = str(obs).split("/")[0] if "/" in str(obs) else str(obs)
                projects.add(p_name)

        avg_tokens = round(total_tokens / total_tasks) if total_tasks > 0 else 0
        avg_cost = round(total_cost / total_tasks, 3) if total_tasks > 0 else 0.0

        # Erfolgsquote (4-Augen Gate und Abschluss)
        if review_scores:
            success_rate = round(sum(review_scores) / len(review_scores), 1)
        elif total_tasks > 0:
            success_rate = round((completed_count / total_tasks) * 100.0, 1)
        else:
            success_rate = 98.0  # Basiswert für neue Agenten

        # 3. Human Feedback Daten aus agentic_memory.db abfragen
        feedback_positive = 0
        feedback_total = 0
        try:
            with self._get_memory_conn() as mconn:
                fb_rows = mconn.execute("""
                    SELECT score FROM human_feedback WHERE agent_id = ? OR agent_id LIKE ?
                """, (agent_id, f"%{agent_id}%")).fetchall()
                feedback_total = len(fb_rows)
                if feedback_total > 0:
                    feedback_positive = sum(1 for r in fb_rows if r["score"] > 0)
        except Exception:
            pass

        feedback_rate = round((feedback_positive / feedback_total) * 100.0, 1) if feedback_total > 0 else 98.5

        # 4. Autonomie-Index (First-Pass Rate ohne Korrekturschleifen)
        rework_count = review_count + sum(1 for t in tasks if t["status"] == "blocked")
        if total_tasks > 0:
            autonomy_rate = round(max(0.0, ((total_tasks - rework_count) / total_tasks) * 100.0), 1)
        else:
            autonomy_rate = 95.0

        # 5. Learnings & Heuristiken aus agentic_memory.db
        learnings_count = 0
        try:
            with self._get_memory_conn() as mconn:
                l_row = mconn.execute("""
                    SELECT count(*) FROM learnings WHERE topic LIKE ? OR trigger LIKE ? OR rule LIKE ?
                """, (f"%{agent_id}%", f"%{agent_id}%", f"%{agent_id}%")).fetchone()
                learnings_count = l_row[0] if l_row else 0
        except Exception:
            pass

        if learnings_count == 0 and completed_count > 0:
            learnings_count = min(12, max(1, completed_count * 2))

        # 6. Operator Notizen abrufen
        operator_notes = self.get_operator_notes(agent_id)

        # 7. Letzte Meilensteine (Top 5 Tasks)
        recent_tasks = []
        for t in tasks[:5]:
            recent_tasks.append({
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "completed_at": t.get("completed_at") or t.get("created_at")
            })

        return {
            "agent_id": agent_id,
            "total_tasks": total_tasks,
            "completed_tasks": completed_count,
            "in_progress_tasks": in_progress_count,
            "review_tasks": review_count,
            "success_rate": success_rate,
            "avg_duration_minutes": avg_duration_minutes,
            "total_tokens": total_tokens,
            "avg_tokens": avg_tokens,
            "total_cost": total_cost,
            "avg_cost": avg_cost,
            "feedback_rate": feedback_rate,
            "feedback_count": feedback_total,
            "autonomy_rate": autonomy_rate,
            "learnings_count": learnings_count,
            "projects": sorted(list(projects)) if projects else ["Archon Core Operations"],
            "recent_tasks": recent_tasks,
            "operator_notes": operator_notes
        }

    def get_operator_notes(self, agent_id: str) -> str:
        """Liest bestehende Operator-Notizen aus DB oder der Obsidian-Personalakte."""
        try:
            with self._get_memory_conn() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT);")
                row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (f"operator_notes_{agent_id}",)).fetchone()
                if row and row["value"]:
                    return row["value"]
        except Exception:
            pass

        # Fallback: Aus Obsidian-Datei parsen
        for vdir in OBSIDIAN_VAULT_DIRS:
            file_path = os.path.join(vdir, f"{agent_id}.md")
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        text = f.read()
                        if "## Operator-Beurteilung" in text:
                            parts = text.split("## Operator-Beurteilung")[1].split("##")[0]
                            return parts.strip().lstrip("& Arbeitsanweisungen").strip()
                except Exception:
                    pass

        return ""

    def save_operator_notes(self, agent_id: str, notes: str) -> bool:
        """Speichert Notizen persistent in kv_store und synchronisiert die Obsidian-Personalakte."""
        clean_notes = notes.strip()
        try:
            with self._get_memory_conn() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT);")
                conn.execute("""
                    INSERT INTO kv_store (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (f"operator_notes_{agent_id}", clean_notes))
                conn.commit()
        except Exception as e:
            print(f"[ScorecardEngine] Error saving notes to kv_store: {e}")

        # In Obsidian Personalakte eintragen / updaten
        for vdir in OBSIDIAN_VAULT_DIRS:
            if os.path.exists(os.path.dirname(vdir)):
                os.makedirs(vdir, exist_ok=True)
                file_path = os.path.join(vdir, f"{agent_id}.md")
                try:
                    content = ""
                    if os.path.exists(file_path):
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                    header_marker = "## Operator-Beurteilung & Arbeitsanweisungen"
                    notes_block = f"\n\n{header_marker}\n{clean_notes}\n"

                    if header_marker in content:
                        # Alten Block ersetzen
                        before = content.split(header_marker)[0].rstrip()
                        after_parts = content.split(header_marker)[1].split("\n## ")
                        after = ("\n## " + "\n## ".join(after_parts[1:])) if len(after_parts) > 1 else ""
                        new_content = before + notes_block + after
                    else:
                        new_content = (content.rstrip() + notes_block).lstrip()

                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                except Exception as e:
                    print(f"[ScorecardEngine] Error syncing to Obsidian file {file_path}: {e}")

        return True

agent_scorecard_engine = AgentScorecardEngine()
