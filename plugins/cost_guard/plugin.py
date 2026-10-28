# -*- coding: utf-8 -*-
"""
plugins/cost_guard/plugin.py
============================
Kostenüberwachung & Budget-Schutz für LLM-Aufrufe.
"""

import os
import json
import datetime
from typing import Dict, Any
from backend.plugin_manager import BasePlugin


class CostGuardPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any], plugin_dir: str):
        super().__init__(manifest, plugin_dir)
        self.state_file = os.path.join(self.plugin_dir, "daily_burn.json")
        self._load_burn()

    def _load_burn(self):
        self.burn_data = {"date": datetime.date.today().isoformat(), "spent_usd": 0.0, "total_tokens": 0}
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == datetime.date.today().isoformat():
                        self.burn_data = data
            except Exception:
                pass

    def _save_burn(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.burn_data, f, indent=2)
        except Exception:
            pass

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "check_token_budget":
            budget = float(self.config.get("daily_budget_usd", 10.0))
            spent = float(self.burn_data.get("spent_usd", 0.0))
            remaining = max(0.0, budget - spent)
            percent = (spent / budget * 100) if budget > 0 else 0
            return {
                "status": "success",
                "date": self.burn_data.get("date"),
                "spent_usd": round(spent, 4),
                "budget_usd": round(budget, 2),
                "remaining_usd": round(remaining, 4),
                "percent_used": round(percent, 1),
                "is_exceeded": spent >= budget
            }
        raise ValueError(f"Unbekanntes Tool: {tool_name}")

    async def on_task_completed(self, task: Dict[str, Any], context: Dict[str, Any]) -> None:
        """Erfasst verbrauchte Tokens nach Abschluss eines Tasks."""
        tokens = context.get("tokens_used", 0)
        cost = context.get("cost_usd", 0.0)
        if tokens or cost:
            self.burn_data["total_tokens"] = self.burn_data.get("total_tokens", 0) + tokens
            self.burn_data["spent_usd"] = self.burn_data.get("spent_usd", 0.0) + cost
            self._save_burn()
