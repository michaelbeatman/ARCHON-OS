# -*- coding: utf-8 -*-
"""
backend/agent_eval_arena.py
===========================
Meilenstein 50: Agent-Eval- & Modell-Benchmark-Arena.

Lokales Referenz-Testdeck zum direkten Qualitaets-, Latenz- und Kostenvergleich
vor Modell- oder SOUL.md-Wechseln (persistiert in data/eval_arena.db).
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "eval_arena.db")

DEFAULT_GOLD_DECK: List[Dict[str, Any]] = [
    {"id": "eval_code_1", "domain": "coding", "prompt": "Schreibe eine reine Python-Funktion fuer Fibonacci mit Memoization.", "expected_keywords": ["def", "memo", "return"]},
    {"id": "eval_sec_1", "domain": "security", "prompt": "Nenne 3 Massnahmen gegen Prompt-Injection in Tool-Agents.", "expected_keywords": ["taint", "hitl", "sandbox"]},
    {"id": "eval_fin_1", "domain": "finance", "prompt": "Berechne Netto aus 119 EUR Brutto bei 19% USt.", "expected_keywords": ["100", "19"]},
    {"id": "eval_strat_1", "domain": "strategy", "prompt": "Formuliere eine kurze Make-or-Buy-Entscheidungsmatrix.", "expected_keywords": ["kosten", "risiko"]},
]


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                task_id TEXT NOT NULL,
                score REAL NOT NULL,
                latency_ms REAL NOT NULL,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def default_keyword_scorer(task: Dict[str, Any], output: str) -> float:
    kws = [k.lower() for k in (task.get("expected_keywords") or [])]
    if not kws:
        return 1.0 if (output or "").strip() else 0.0
    low = (output or "").lower()
    hits = sum(1 for k in kws if k in low)
    return round(hits / len(kws), 3)


async def run_eval_arena(
    models: List[str],
    runner_fn: Callable[[str, str], Awaitable[Dict[str, Any]]],
    tasks: Optional[List[Dict[str, Any]]] = None,
    scorer_fn: Optional[Callable[[Dict[str, Any], str], float]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    deck = tasks or DEFAULT_GOLD_DECK
    scorer = scorer_fn or default_keyword_scorer
    board: List[Dict[str, Any]] = []

    for model in models:
        scores = []
        latencies = []
        costs = []
        for task in deck:
            t0 = time.perf_counter()
            res = await runner_fn(model, task["prompt"])
            lat_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            txt = res.get("content", "") if isinstance(res, dict) else str(res)
            cost = float(res.get("cost_usd", 0.0)) if isinstance(res, dict) else 0.0
            sc = float(scorer(task, txt))
            scores.append(sc)
            latencies.append(lat_ms)
            costs.append(cost)
            with _connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO eval_runs (model, task_id, score, latency_ms, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (model, task["id"], sc, lat_ms, cost, time.time()),
                )
                conn.commit()

        board.append({
            "model": model,
            "avg_score": round(sum(scores) / max(1, len(scores)), 3),
            "avg_latency_ms": round(sum(latencies) / max(1, len(latencies)), 2),
            "total_cost_usd": round(sum(costs), 4),
            "tasks_run": len(deck),
        })

    board.sort(key=lambda x: (-x["avg_score"], x["avg_latency_ms"], x["total_cost_usd"]))
    return {
        "leaderboard": board,
        "winner_model": board[0]["model"] if board else None,
    }
