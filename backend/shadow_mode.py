"""
backend/shadow_mode.py
======================
M52 — Pre-Flight Cost-Estimator (Ketten/Boardroom) & „Shadow-Mode“ Tracker.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

from archon.core.runtime import WORKSPACE_DIR
from backend.cost_estimator import estimate_prompt_cost

SHADOW_GRADUATION_THRESHOLD = 0.90
SHADOW_MIN_SAMPLES = 5


def estimate_chain_cost(
    steps: List[Dict[str, Any]],
    model_name: str = "deepseek/deepseek-chat",
    budget_usd: float = 0.50,
) -> Dict[str, Any]:
    """Schätzt Token- und USD-Kosten für eine ganze Playbook-/Boardroom-Kette."""
    breakdown: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_in_tokens = 0
    total_out_tokens = 0

    for idx, step in enumerate(steps):
        prompt = str(step.get("prompt") or step.get("prompt_template") or "")
        exp_out = int(step.get("expected_output_tokens") or 1000)
        est = estimate_prompt_cost(
            prompt=prompt,
            model_name=str(step.get("model") or model_name),
            expected_output_tokens=exp_out,
            task_budget_usd=budget_usd,
        )
        cost_val = float(est.get("estimated_cost_usd", 0.0))
        in_tok = int(est.get("estimated_input_tokens", max(1, len(prompt) // 4)))
        total_cost += cost_val
        total_in_tokens += in_tok
        total_out_tokens += exp_out
        breakdown.append({
            "step": idx + 1,
            "title": step.get("title") or f"Step {idx + 1}",
            "model": step.get("model") or model_name,
            "input_tokens": in_tok,
            "output_tokens": exp_out,
            "cost_usd": round(cost_val, 6),
        })

    return {
        "step_count": len(steps),
        "total_input_tokens": total_in_tokens,
        "total_output_tokens": total_out_tokens,
        "total_estimated_cost_usd": round(total_cost, 6),
        "budget_usd": budget_usd,
        "fits_budget": total_cost <= budget_usd,
        "breakdown": breakdown,
    }


class ShadowModeManager:
    """Passiver Parallel-Trockenlauf neuer Agenten bis > 90 % Trefferquote."""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        base = data_dir or os.path.join(WORKSPACE_DIR, "data")
        self.data_dir = os.path.realpath(base)
        os.makedirs(self.data_dir, exist_ok=True)
        self.store_file = os.path.join(self.data_dir, "shadow_mode_runs.json")
        self._lock = threading.RLock()

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.store_file):
            return []
        try:
            with open(self.store_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return []

    def _save(self, rows: List[Dict[str, Any]]) -> None:
        tmp = f"{self.store_file}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.store_file)

    def record_shadow_run(
        self,
        agent_id: str,
        task_id: str,
        shadow_decision: str,
    ) -> Dict[str, Any]:
        entry = {
            "shadow_id": f"shd_{uuid.uuid4().hex[:8]}",
            "agent_id": agent_id,
            "task_id": task_id,
            "shadow_decision": shadow_decision,
            "human_decision": None,
            "match_score": None,
            "status": "pending_evaluation",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self._lock:
            rows = self._load()
            rows.insert(0, entry)
            self._save(rows[:500])
        return entry

    def evaluate_shadow_run(
        self,
        shadow_id: str,
        human_decision: str,
        match_score: float,
    ) -> Dict[str, Any]:
        score = max(0.0, min(1.0, float(match_score)))
        with self._lock:
            rows = self._load()
            for r in rows:
                if r.get("shadow_id") == shadow_id:
                    r["human_decision"] = human_decision
                    r["match_score"] = round(score, 4)
                    r["status"] = "evaluated"
                    r["evaluated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    self._save(rows)
                    return r
        raise KeyError(f"Shadow-Run '{shadow_id}' nicht gefunden.")

    def get_agent_stats(self, agent_id: str) -> Dict[str, Any]:
        with self._lock:
            rows = [r for r in self._load() if r.get("agent_id") == agent_id]
        evaluated = [r for r in rows if r.get("status") == "evaluated" and r.get("match_score") is not None]
        avg_score = sum(float(r["match_score"]) for r in evaluated) / len(evaluated) if evaluated else 0.0
        ready = len(evaluated) >= SHADOW_MIN_SAMPLES and avg_score >= SHADOW_GRADUATION_THRESHOLD
        return {
            "agent_id": agent_id,
            "total_runs": len(rows),
            "evaluated_runs": len(evaluated),
            "avg_match_rate": round(avg_score, 4),
            "graduation_threshold": SHADOW_GRADUATION_THRESHOLD,
            "min_samples": SHADOW_MIN_SAMPLES,
            "ready_for_autopilot": ready,
        }


shadow_mode_manager = ShadowModeManager()
