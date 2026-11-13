"""
backend/prompt_optimizer.py
Paket 5 (Feature 21): Automatischer Prompt-Optimizer (DSPy / TextGrad-Prinzip).
Analysiert wiederkehrende Fehlermuster, abgelehnte SLA-Lieferungen oder Korrekturschleifen einer
Agenten-Rolle und synthetisiert daraus präzise Härtungs-Direktiven (`[OPTIMIZED_GUARDRAIL_DIRECTIVE]`),
um den System-Prompt automatisch oder nach Freigabe nachzuschärfen.
"""

import os
import json
import uuid
import sqlite3

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
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("prompt_optimizer")
    except Exception:
        return {
            "enabled": True,
            "min_failures_to_trigger": 3,
            "auto_apply_patches": False,
            "max_rules_appended": 5
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_optimization_patches (
                patch_id TEXT PRIMARY KEY,
                agent_role TEXT,
                failure_count INTEGER,
                diagnosed_weaknesses_json TEXT,
                generated_directives_json TEXT,
                optimized_prompt TEXT,
                applied INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        conn.commit()


FAILURE_RULES_MAP = [
    ("json", "Gib Ergebnisse ausschließlich als valides JSON ohne einleitenden Fließtext oder Markdown-Codefences zurück."),
    ("timeout", "Zerlege große Schleifen in kompakte Schritte und vermeide blockierende Langläufer-Befehle."),
    ("hallucin", "Belege jede Faktenbehauptung zwingend mit einer konkreten Dokument-ID ([Quelle: ID]) aus dem Kontext."),
    ("path", "Prüfe vor jedem Dateizugriff die exakte Existenz des Pfades im erlaubten Arbeitsverzeichnis."),
    ("syntax", "Validiere generierten Python-/JS-Code vor der Rückgabe auf vollständige Klammerung und Einrückung.")
]


class PromptOptimizer:
    def __init__(self):
        _init_db()

    def optimize_role_prompt(
        self,
        agent_role: str,
        current_prompt: str,
        recent_failures: List[str]
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"optimized": False, "bypassed": True, "optimized_prompt": current_prompt}

        min_fail = int(cfg.get("min_failures_to_trigger", 3))
        max_rules = int(cfg.get("max_rules_appended", 5))
        auto_apply = bool(cfg.get("auto_apply_patches", False))

        if len(recent_failures) < min_fail:
            return {
                "optimized": False,
                "reason": f"Fehleranzahl ({len(recent_failures)}) unter Schwellenwert ({min_fail}).",
                "optimized_prompt": current_prompt
            }

        combined_err = " ".join(recent_failures).lower()
        directives: List[str] = []
        weaknesses: List[str] = []

        for keyword, directive in FAILURE_RULES_MAP:
            if keyword in combined_err and len(directives) < max_rules:
                weaknesses.append(keyword)
                directives.append(directive)

        if not directives:
            weaknesses.append("generic_quality_drift")
            directives.append("Prüfe alle Pflichtkriterien der Aufgabe vor Abschluss gegen die Abnahme-Checkliste.")

        patch_block = (
            "\n\n[OPTIMIZED_GUARDRAIL_DIRECTIVES — AUTO-TUNED VIA TEXTGRAD]:\n"
            + "\n".join(f"- {d}" for d in directives[:max_rules])
        )
        new_prompt = current_prompt.rstrip() + patch_block
        patch_id = f"popt-{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO prompt_optimization_patches
                (patch_id, agent_role, failure_count, diagnosed_weaknesses_json,
                 generated_directives_json, optimized_prompt, applied, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                patch_id, agent_role, len(recent_failures),
                json.dumps(weaknesses), json.dumps(directives, ensure_ascii=False),
                new_prompt, int(auto_apply), now_iso
            ))
            conn.commit()

        return {
            "optimized": True,
            "patch_id": patch_id,
            "agent_role": agent_role,
            "failure_count_analyzed": len(recent_failures),
            "diagnosed_weaknesses": weaknesses,
            "generated_directives": directives,
            "auto_applied": auto_apply,
            "optimized_prompt": new_prompt
        }


prompt_optimizer = PromptOptimizer()
