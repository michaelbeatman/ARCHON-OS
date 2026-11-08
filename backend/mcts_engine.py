# -*- coding: utf-8 -*-
"""
backend/mcts_engine.py
======================
Monte Carlo Tree Search (MCTS) for Action Trajectories:
Ermöglicht Agenten bei komplexen, irreversiblen oder hochriskanten Aufgaben
(z. B. Finanzaktionen, Datenbankmigrationen, Systemänderungen), Handlungsstränge
vor der ersten Ausführung im Voraus gedanklich zu simulieren, Pfadrisiken
abzuwägen und den optimalen Aktionspfad (höchstes Q-Value) auszuwählen.
"""

import math
import random
import datetime
from typing import Dict, Any, List, Optional, Tuple


class MCTSNode:
    def __init__(self, action: str, parent: Optional['MCTSNode'] = None, description: str = ""):
        self.action = action
        self.description = description
        self.parent = parent
        self.children: List['MCTSNode'] = []
        self.visits = 0
        self.total_value = 0.0
        self.risk_score = 0.0  # 0.0 = sicher, 1.0 = extrem riskant
        self.estimated_tokens = 0
        self.details: Dict[str, Any] = {}

    @property
    def q_value(self) -> float:
        return self.total_value / self.visits if self.visits > 0 else 0.0

    def ucb1(self, exploration_weight: float = 1.414) -> float:
        if self.visits == 0:
            return float('inf')
        return self.q_value + exploration_weight * math.sqrt(math.log(self.parent.visits) / self.visits)


class MCTSEngine:
    def __init__(self, default_depth: int = 3, default_rollouts: int = 4, exploration_weight: float = 1.414):
        self.default_depth = default_depth
        self.default_rollouts = default_rollouts
        self.exploration_weight = exploration_weight

    def evaluate_trajectories(
        self,
        task_goal: str,
        candidate_actions: List[Dict[str, Any]],
        simulation_rollouts: Optional[int] = None,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Führt eine Monte-Carlo-Simulation über die Kandidatenaktionen durch.
        Jede Kandidatenaktion wird bewertet hinsichtlich:
        - Zielerreichung (Feasibility / Success Rate)
        - Risiko / Kollateralschaden (Safety)
        - Effizienz (Token- und Ressourcenaufwand)

        seed: Optionaler Seed für den Monte-Carlo-Noise. Ohne Seed bleibt die
        Simulation stochastisch (Produktivverhalten). Mit Seed sind Läufe
        reproduzierbar — nötig für stabile Tests bei knappen Q-Wert-Abständen.
        """
        rollouts = simulation_rollouts or self.default_rollouts
        rng = random.Random(seed) if seed is not None else random
        root = MCTSNode(action="ROOT", description=f"Task Goal: {task_goal}")
        root.visits = 1

        # 1. Expand Root mit Kandidaten
        for cand in candidate_actions:
            name = cand.get("name") or cand.get("action", "unknown_action")
            desc = cand.get("description", "")
            child = MCTSNode(action=name, parent=root, description=desc)
            child.details = cand
            child.estimated_tokens = cand.get("estimated_tokens", 500)
            
            # Heuristische Risiko-Ermittlung, falls kein expliziter risk_score angegeben ist
            risk = cand.get("risk_score")
            if risk is None:
                comb_text = f"{name} {desc}".lower()
                if any(w in comb_text for w in ["drop", "delete", "destroy", "wipe", "loeschen", "truncate", "format"]):
                    risk = 0.85
                elif any(w in comb_text for w in ["safe", "backup", "verify", "schrittweise", "dry_run"]):
                    risk = 0.1
                else:
                    risk = 0.2
            child.risk_score = risk
            root.children.append(child)

        # 2. Rollout & Simulation Loops
        simulated_paths = []
        for rollout_idx in range(rollouts):
            for child in root.children:
                # Simuliere Rollout-Wert
                value, sim_log = self._simulate_rollout(child, task_goal, rng)
                child.visits += 1
                child.total_value += value
                simulated_paths.append({
                    "rollout": rollout_idx + 1,
                    "action": child.action,
                    "simulated_value": round(value, 3),
                    "notes": sim_log
                })

        # 3. Best Action Selection (Höchster Q-Wert)
        best_child = max(root.children, key=lambda c: (c.q_value, -c.risk_score))
        
        evaluation_ranking = []
        for c in sorted(root.children, key=lambda x: x.q_value, reverse=True):
            evaluation_ranking.append({
                "action": c.action,
                "description": c.description,
                "q_value": round(c.q_value, 3),
                "visits": c.visits,
                "risk_score": round(c.risk_score, 2),
                "estimated_tokens": c.estimated_tokens,
                "recommended": (c == best_child)
            })

        return {
            "status": "success",
            "task_goal": task_goal,
            "best_action": best_child.action,
            "best_action_description": best_child.description,
            "highest_confidence_q": round(best_child.q_value, 3),
            "recommended_path": {
                "action": best_child.action,
                "description": best_child.description,
                "risk_score": round(best_child.risk_score, 2),
                "q_value": round(best_child.q_value, 3)
            },
            "ranking": evaluation_ranking,
            "total_simulations": rollouts * len(root.children),
            "simulated_at": datetime.datetime.now().isoformat()
        }

    def _simulate_rollout(self, node: MCTSNode, task_goal: str, rng=None) -> Tuple[float, str]:
        """Heuristische Simulation eines Handlungsstrangs."""
        # Basis-Erfolgswahrscheinlichkeit
        base_success = 0.85
        # Hohes Risiko drückt den Wert
        risk_penalty = node.risk_score * 0.4
        # Sehr hohe Token-Kosten geben minimalen Abzug
        token_penalty = min(0.15, (node.estimated_tokens / 10000.0) * 0.1)
        
        # Leichte Zufallsvarianz (Monte Carlo Noise)
        noise = (rng or random).uniform(-0.05, 0.05)
        
        score = max(0.0, min(1.0, base_success - risk_penalty - token_penalty + noise))
        log = f"Score: {score:.2f} (Risikomalus: -{risk_penalty:.2f}, Kostenmalus: -{token_penalty:.2f})"
        return score, log


# Singleton
_mcts_engine = None

def get_mcts_engine() -> MCTSEngine:
    global _mcts_engine
    if _mcts_engine is None:
        _mcts_engine = MCTSEngine()
    return _mcts_engine
