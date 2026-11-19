# -*- coding: utf-8 -*-
"""
backend/worktree_joust.py
=========================
Meilenstein 85: Best-of-N Coding-Worktrees (joust & multiverse-Pattern).

Verwaltet isolierte Git-Worktree-Pfade pro Contender und bewertet die
Ergebnisse anhand von Test-Status, Exit-Code und Diff-Groesse.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List


def plan_joust_worktrees(repo_dir: str, task_id: str, contenders: int = 3) -> List[Dict[str, str]]:
    count = max(2, min(6, int(contenders)))
    base = os.path.join(repo_dir, ".worktrees")
    return [
        {
            "contender": f"contender_{i}",
            "branch": f"joust/{task_id}/c{i}",
            "path": os.path.join(base, f"joust_{task_id}_c{i}"),
        }
        for i in range(1, count + 1)
    ]


def create_joust_worktrees(repo_dir: str, task_id: str, contenders: int = 3, base_ref: str = "HEAD") -> List[Dict[str, str]]:
    specs = plan_joust_worktrees(repo_dir, task_id, contenders)
    created: List[Dict[str, str]] = []
    for sp in specs:
        os.makedirs(os.path.dirname(sp["path"]), exist_ok=True)
        subprocess.run(
            ["git", "-C", repo_dir, "worktree", "add", "-b", sp["branch"], sp["path"], base_ref],
            check=True,
            capture_output=True,
            text=True,
        )
        created.append(sp)
    return created


def score_joust_contenders(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Waehlt den besten Contender (Tests bestanden > kleinerer sauberer Diff > Laufzeit)."""
    ranked = sorted(
        results,
        key=lambda r: (
            0 if r.get("tests_passed") else 1,
            0 if int(r.get("exit_code", 1)) == 0 else 1,
            int(r.get("diff_lines", 999999)),
            float(r.get("duration_s", 999999.0)),
        ),
    )
    winner = ranked[0] if ranked and ranked[0].get("tests_passed") else None
    return {"winner": winner, "ranked": ranked, "requires_human_merge_approval": True}
