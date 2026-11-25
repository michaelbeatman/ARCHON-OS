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
from typing import Dict, Any, Optional, Callable

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
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


def make_dispatcher_coro(
    prompt: str,
    model: str,
    agent_id: str = "hedge_worker",
    agent_name: str = "HedgeWorker",
    role: str = "Analyst",
) -> Callable:
    """Echte Provider-Coroutine fuer das Hedging (H-01-2/F042).

    Die Coroutine ruft den zentralen Dispatcher mit dem konkreten Modell und
    liefert dessen echte Response. Blockierte/leere Antworten werden als Fehler
    geworfen, damit der Hedger keinen synthetischen Gewinner erfindet.
    Ohne injizierte Coroutines bleibt der Aufruf ein explizit gekennzeichneter
    Demo-Simulator (``demo_only=True``).
    """
    async def _coro() -> str:
        import core_dispatcher

        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=agent_id,
            agent_name=agent_name,
            prompt=prompt,
            role=role,
            model=model,
            task_id=f"hedge-{model.replace('/', '-')}",
        )
        if not isinstance(res, dict) or res.get("status") != "success":
            reason = ""
            if isinstance(res, dict):
                reason = str(res.get("error") or res.get("error_code") or res.get("content") or "")[:200]
            raise RuntimeError(f"dispatcher_blocked: {reason or 'no successful response'}")
        content = str(res.get("content") or "")
        if not content.strip():
            raise RuntimeError("dispatcher returned empty content")
        return content

    return _coro


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
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
        # Ohne injizierte echte Coroutines ist dieser Call ein Demo-Simulat:
        # die "Antworten" sind synthetische Platzhalter, kein LLM-Ergebnis.
        demo_only = primary_coro_fn is None or fallback_coro_fn is None
        mode = "demo_only" if demo_only else "live_functions"
        enabled = bool(cfg.get("enabled", True))
        hedge_delay = float(
            hedge_delay_override if hedge_delay_override is not None else cfg.get("hedge_delay_seconds", 2.5)
        )
        fallback_model = str(fallback_model_override or cfg.get("fallback_model", "deepseek/deepseek-chat"))
        call_id = f"hedge-{uuid.uuid4().hex[:10]}"

        async def _run_primary():
            if primary_coro_fn is not None:
                text = await primary_coro_fn()
                if not str(text or "").strip():
                    raise RuntimeError("primary_coro_fn returned empty content")
                return text
            sim_wait = simulate_primary_latency_sec if simulate_primary_latency_sec is not None else 0.04
            await asyncio.sleep(sim_wait)
            return f"[Primary:{primary_model}] Antwort für: {prompt[:100]}"

        async def _run_fallback():
            if fallback_coro_fn is not None:
                text = await fallback_coro_fn()
                if not str(text or "").strip():
                    raise RuntimeError("fallback_coro_fn returned empty content")
                return text
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

        def _persist_hedge():
            with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
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

        await asyncio.to_thread(_persist_hedge)

        return {
            "call_id": call_id,
            "enabled": enabled,
            "status": "success" if str(result_text or "").strip() else "failed",
            "demo_only": demo_only,
            "mode": mode,
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
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
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
