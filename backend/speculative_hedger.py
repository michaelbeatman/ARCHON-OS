"""
backend/speculative_hedger.py
Paket 1 (Feature 3): Speculative Fast-Routing & Latenz-Hedging.
Überwacht die Antwortzeit des primären LLM-Providers. Antwortet der Primär-Call nicht innerhalb von
`hedge_delay_seconds` (Standard: 2.5s), wird automatisch ein paralleler Hedge-Request an das
schnelle Fallback-Modell gestartet. Wer zuerst antwortet, gewinnt; der langsamere Task wird abgebrochen.
"""

import os
import time
import uuid
import asyncio
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, Callable

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("speculative_hedger")
    except Exception:
        return {
            "enabled": True,
            "hedge_delay_seconds": 2.5,
            "fallback_model": "deepseek/deepseek-chat",
            "max_hedged_calls_per_minute": 20
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS speculative_hedge_logs (
                call_id TEXT PRIMARY KEY,
                primary_model TEXT,
                fallback_model TEXT,
                hedge_triggered INTEGER,
                winning_source TEXT,
                winning_model TEXT,
                total_latency_ms REAL,
                hedge_delay_seconds REAL,
                created_at TEXT
            )
        """)
        conn.commit()


class SpeculativeHedger:
    def __init__(self):
        _init_db()

    async def execute_hedged_call(
        self,
        prompt: str,
        primary_model: str = "openai/gpt-4o",
        fallback_model_override: Optional[str] = None,
        hedge_delay_override: Optional[float] = None,
        simulate_primary_latency_sec: Optional[float] = None,
        simulate_fallback_latency_sec: float = 0.05,
        primary_coro_fn: Optional[Callable] = None,
        fallback_coro_fn: Optional[Callable] = None
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        hedge_delay = float(
            hedge_delay_override if hedge_delay_override is not None else cfg.get("hedge_delay_seconds", 2.5)
        )
        fallback_model = str(fallback_model_override or cfg.get("fallback_model", "deepseek/deepseek-chat"))
        call_id = f"hedge-{uuid.uuid4().hex[:10]}"

        async def _run_primary():
            if primary_coro_fn is not None:
                return await primary_coro_fn()
            sim_wait = simulate_primary_latency_sec if simulate_primary_latency_sec is not None else 0.04
            await asyncio.sleep(sim_wait)
            return f"[Primary:{primary_model}] Antwort für: {prompt[:100]}"

        async def _run_fallback():
            if fallback_coro_fn is not None:
                return await fallback_coro_fn()
            await asyncio.sleep(simulate_fallback_latency_sec)
            return f"[Hedged-Fallback:{fallback_model}] Schnelle Ersatz-Antwort für: {prompt[:100]}"

        primary_task = asyncio.create_task(_run_primary())
        hedge_triggered = False
        winning_source = "primary"
        winning_model = primary_model

        if not enabled:
            result_text = await primary_task
        else:
            done, _ = await asyncio.wait({primary_task}, timeout=hedge_delay)
            if primary_task in done:
                result_text = primary_task.result()
            else:
                # Primärer Call überschreitet hedge_delay -> Spekulativen Parallel-Call zünden
                hedge_triggered = True
                fallback_task = asyncio.create_task(_run_fallback())
                done_race, pending_race = await asyncio.wait(
                    {primary_task, fallback_task},
                    return_when=asyncio.FIRST_COMPLETED
                )
                winner = done_race.pop()
                for p in pending_race:
                    p.cancel()
                result_text = winner.result()
                if winner is fallback_task:
                    winning_source = "hedged_fallback"
                    winning_model = fallback_model

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.execute("""
                INSERT INTO speculative_hedge_logs
                (call_id, primary_model, fallback_model, hedge_triggered, winning_source,
                 winning_model, total_latency_ms, hedge_delay_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                call_id, primary_model, fallback_model, int(hedge_triggered),
                winning_source, winning_model, total_ms, hedge_delay, now_iso
            ))
            conn.commit()

        return {
            "call_id": call_id,
            "enabled": enabled,
            "hedge_triggered": hedge_triggered,
            "winning_source": winning_source,
            "winning_model": winning_model,
            "primary_model": primary_model,
            "fallback_model": fallback_model,
            "hedge_delay_seconds": hedge_delay,
            "total_latency_ms": total_ms,
            "response": result_text
        }

    def get_stats(self) -> Dict[str, Any]:
        cfg = _get_cfg()
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS total_calls,
                    COALESCE(SUM(hedge_triggered), 0) AS total_hedges,
                    COALESCE(SUM(CASE WHEN winning_source = 'hedged_fallback' THEN 1 ELSE 0 END), 0) AS fallback_wins,
                    ROUND(COALESCE(AVG(total_latency_ms), 0), 2) AS avg_latency_ms
                FROM speculative_hedge_logs
            """).fetchone()
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "hedge_delay_seconds": float(cfg.get("hedge_delay_seconds", 2.5)),
            "fallback_model": str(cfg.get("fallback_model", "deepseek/deepseek-chat")),
            "total_calls": row[0] if row else 0,
            "total_hedges_triggered": row[1] if row else 0,
            "fallback_wins": row[2] if row else 0,
            "avg_latency_ms": row[3] if row else 0.0
        }


speculative_hedger = SpeculativeHedger()
