"""
backend/dry_run_simulator.py
Paket 3 (Feature 14): Dry-Run / Shadow-Mode für Agenten-Aufträge.
Simuliert einen kompletten Agenten-Lauf inklusive geplanter Datei-Änderungen, Datenbank-Schreibzugriffe
und externer API-Calls als Trockenübung ohne reale Seiteneffekte. Erzeugt einen detaillierten
Shadow-Execution-Plan zur Vorab-Freigabe.
"""

import os
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("dry_run_shadow")
    except Exception:
        return {
            "enabled": False,
            "intercept_write_tools": True,
            "intercept_external_apis": True,
            "log_simulated_diffs": True
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_dry_run_logs (
                simulation_id TEXT PRIMARY KEY,
                task_title TEXT,
                total_actions INTEGER,
                intercepted_mutations INTEGER,
                risk_level TEXT,
                simulated_plan_json TEXT,
                created_at TEXT
            )
        """)
        conn.commit()


WRITE_OR_MUTATION_TOOLS = {
    "write_file", "edit_file", "delete_file", "execute_bash", "send_email",
    "trigger_webhook", "git_push", "db_update", "crm_delete"
}


class DryRunSimulator:
    def __init__(self):
        _init_db()

    def simulate_task_plan(
        self,
        task_title: str,
        proposed_actions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        intercept_writes = bool(cfg.get("intercept_write_tools", True))
        intercept_apis = bool(cfg.get("intercept_external_apis", True))

        sim_id = f"shadow-{uuid.uuid4().hex[:10]}"
        simulated_steps = []
        intercepted_count = 0

        for idx, act in enumerate(proposed_actions, start=1):
            tool = str(act.get("tool", "unknown_tool"))
            target = str(act.get("target", ""))
            is_mutation = tool in WRITE_OR_MUTATION_TOOLS or any(
                k in tool.lower() for k in ("write", "delete", "send", "push", "update", "exec")
            )
            intercepted = is_mutation and (intercept_writes or intercept_apis)
            if intercepted:
                intercepted_count += 1

            simulated_steps.append({
                "step": idx,
                "tool": tool,
                "target": target,
                "side_effect_prevented": intercepted,
                "execution_mode": "SHADOW_INTERCEPTED" if intercepted else "READ_ONLY_SAFE",
                "preview_diff": f"[DRY-RUN PREVIEW] Würde '{tool}' auf '{target}' ausführen (0 reale Bytes verändert)."
            })

        risk = "HIGH" if intercepted_count >= 3 else ("MEDIUM" if intercepted_count >= 1 else "LOW")
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.execute("""
                INSERT INTO shadow_dry_run_logs
                (simulation_id, task_title, total_actions, intercepted_mutations, risk_level, simulated_plan_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sim_id, task_title, len(proposed_actions), intercepted_count,
                risk, json.dumps(simulated_steps, ensure_ascii=False), now_iso
            ))
            conn.commit()

        return {
            "simulation_id": sim_id,
            "task_title": task_title,
            "global_shadow_mode_active": bool(cfg.get("enabled", False)),
            "total_actions": len(proposed_actions),
            "intercepted_mutations": intercepted_count,
            "real_side_effects_executed": 0,
            "risk_level": risk,
            "simulated_steps": simulated_steps
        }


dry_run_simulator = DryRunSimulator()
