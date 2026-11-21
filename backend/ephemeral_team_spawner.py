"""
backend/ephemeral_team_spawner.py
Paket 5 (Feature 24): Dynamisches Ephemeral-Team-Spawning (Ad-hoc Task-Force).
Analysiert eine komplexe Projektaufgabe, stellt automatisch eine passgenaue temporäre Task-Force
aus Spezialisten-Rollen zusammen (max. `max_team_size`), weist Teilverantwortungen zu und löst
das Team nach Projektabschluss (`auto_dissolve_on_complete`) wieder sauber auf.
"""

import asyncio
import os
import json
import logging
import uuid
import sqlite3

logger = logging.getLogger("archon.ephemeral_team_spawner")

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from datetime import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db
    DB_PATH = resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("ephemeral_teams")
    except Exception:
        return {
            "enabled": True,
            "max_team_size": 4,
            "auto_dissolve_on_complete": True
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ephemeral_task_forces (
                team_id TEXT PRIMARY KEY,
                mission_title TEXT,
                members_json TEXT,
                status TEXT,
                created_at TEXT,
                dissolved_at TEXT
            )
        """)
        conn.commit()


SPECIALIST_CATALOG = [
    ("security", {"role_id": "sec_auditor", "title": "Zero-Trust Security Auditor", "focus": "RBAC, PII & Egress-Prüfung"}),
    ("frontend", {"role_id": "ui_engineer", "title": "Frontend & Design Specialist", "focus": "HTML/JS/CSS & Browser-Audit"}),
    ("datenbank", {"role_id": "db_architect", "title": "SQLite & RAG Architect", "focus": "FTS5, WAL-Mode & Schema"}),
    ("api", {"role_id": "backend_lead", "title": "FastAPI Systems Lead", "focus": "REST-Endpunkte & Concurrency"}),
    ("test", {"role_id": "qa_verifier", "title": "Regression & Eval Engineer", "focus": "End-to-End & Gold-Dataset Tests"})
]


class EphemeralTeamSpawner:
    def __init__(self):
        _init_db()

    def spawn_task_force(
        self,
        mission_title: str,
        mission_brief: str,
        *,
        execute_dag: bool = False,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        max_size = int(cfg.get("max_team_size", 4))
        auto_dissolve = bool(cfg.get("auto_dissolve_on_complete", True))

        text_low = f"{mission_title} {mission_brief}".lower()
        selected_members: List[Dict[str, str]] = [
            {"role_id": "squad_commander", "title": "Ephemeral Squad Lead", "focus": "Koordination & Synthese"}
        ]

        for kw, spec in SPECIALIST_CATALOG:
            if kw in text_low and len(selected_members) < max_size:
                selected_members.append(spec)

        # Auffüllen bis mindestens 3 Mitglieder, falls wenige Keywords genannt wurden
        for _, spec in SPECIALIST_CATALOG:
            if len(selected_members) >= min(3, max_size):
                break
            if spec not in selected_members:
                selected_members.append(spec)

        team_id = f"squad-{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        final_status = "completed_and_dissolved" if auto_dissolve else "active"
        dissolved_at = now_iso if auto_dissolve else None

        # Optionale Ausfuehrung ueber die zentrale Workflow-DAG-Engine (Fan-Out + Synthese)
        dag_run: Optional[Dict[str, Any]] = None
        if enabled and execute_dag:
            try:
                from backend.workflow_dag_runner import run_workflow_dag

                specialists = [m for m in selected_members if m["role_id"] != "squad_commander"] or selected_members
                nodes: List[Dict[str, Any]] = []
                for idx, member in enumerate(specialists):
                    nodes.append({
                        "id": f"n_spec_{idx + 1}",
                        "type": "task",
                        "agent_id": member["role_id"],
                        "title": member["title"],
                        "prompt": f"Mission: {mission_title}\nAuftrag: {mission_brief}\nDein Fokus: {member['focus']}",
                        "depends_on": [],
                    })
                nodes.append({
                    "id": "n_squad_synthesis",
                    "type": "task",
                    "agent_id": "squad_commander",
                    "title": "Ephemeral Squad Lead Synthese",
                    "prompt": f"Synthetisiere die Ergebnisse der Task-Force fuer '{mission_title}'.",
                    "depends_on": [n["id"] for n in nodes],
                })
                dag_def = {"workflow_id": team_id, "nodes": nodes, "edges": []}
                eff_exec = (
                    (lambda n, u: {"status": "success", "agent_id": n.get("agent_id"), "content": f"[Task-Force {n.get('title')}] OK"})
                    if dry_run
                    else None
                )
                dag_run = asyncio.run(run_workflow_dag(dag_def=dag_def, executor_fn=eff_exec))
            except Exception as dag_exc:
                logger.warning(f"[EphemeralTeamSpawner] DAG-Dispatch fuer {team_id} uebersprungen: {dag_exc}")

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO ephemeral_task_forces
                (team_id, mission_title, members_json, status, created_at, dissolved_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                team_id, mission_title,
                json.dumps(selected_members, ensure_ascii=False),
                final_status, now_iso, dissolved_at
            ))
            conn.commit()

        res: Dict[str, Any] = {
            "team_id": team_id,
            "enabled": enabled,
            "mission_title": mission_title,
            "team_size": len(selected_members),
            "max_team_size": max_size,
            "members": selected_members,
            "status": final_status,
            "auto_dissolved": auto_dissolve,
        }
        if dag_run is not None:
            res["workflow_run_id"] = dag_run.get("run_id")
            res["dag_status"] = dag_run.get("status")
        return res


ephemeral_team_spawner = EphemeralTeamSpawner()
