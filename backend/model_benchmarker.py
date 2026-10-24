"""
backend/model_benchmarker.py
A/B-Modell-Benchmarking & Performance-Scorer (Pillar 5).
Sendet denselben Testauftrag parallel an zwei konfigurierte Modelle,
misst Latenz, Token-Verbrauch und Kosten und speichert historische Auswertungen.
"""

import os
import sys
import time
import json
import asyncio
import sqlite3
import datetime
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

def _init_benchmark_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_benchmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT NOT NULL,
                model_a TEXT NOT NULL,
                model_b TEXT NOT NULL,
                dur_a REAL,
                dur_b REAL,
                chars_a INTEGER,
                chars_b INTEGER,
                winner TEXT,
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

_init_benchmark_db()

async def run_model_benchmark(
    prompt: str,
    model_a: str = "deepseek/deepseek-chat",
    model_b: str = "anthropic/claude-3-5-sonnet",
    role: str = "Senior Analyst",
    system_prompt: str = "Antworte präzise und faktenbasiert."
) -> Dict[str, Any]:
    import core_dispatcher

    async def _measure_run(m_name: str):
        t0 = time.time()
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id="benchmarker",
                agent_name="Benchmark Worker",
                prompt=prompt,
                role=role,
                system_prompt=system_prompt,
                model=m_name
            )
            dur = time.time() - t0
            content = res.get("content", "")
            return {
                "model": m_name,
                "status": "success",
                "duration_seconds": round(dur, 2),
                "chars_generated": len(content),
                "tokens_estimate": round(len(content) / 4),
                "preview": content[:250] + ("..." if len(content) > 250 else "")
            }
        except Exception as e:
            return {
                "model": m_name,
                "status": "error",
                "duration_seconds": round(time.time() - t0, 2),
                "error": str(e)
            }

    # Parallel ausführen
    res_a, res_b = await asyncio.gather(_measure_run(model_a), _measure_run(model_b))

    dur_a = res_a.get("duration_seconds", 999)
    dur_b = res_b.get("duration_seconds", 999)
    faster_model = model_a if dur_a <= dur_b else model_b
    summary = f"Modell '{faster_model}' war schneller ({min(dur_a, dur_b)}s vs {max(dur_a, dur_b)}s)."

    # Persistent in SQLite hinterlegen
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        with conn:
            conn.execute("""
                INSERT INTO model_benchmarks 
                (prompt, model_a, model_b, dur_a, dur_b, chars_a, chars_b, winner, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                prompt[:500],
                model_a,
                model_b,
                dur_a,
                dur_b,
                res_a.get("chars_generated", 0),
                res_b.get("chars_generated", 0),
                faster_model,
                summary
            ))
            conn.commit()
        conn.close()
    except Exception as err:
        print(f"[ModelBenchmarker] Fehler beim Speichern des Benchmark-Ergebnisses: {err}", file=sys.stderr)

    return {
        "status": "success",
        "benchmark_prompt": prompt[:120],
        "model_a": res_a,
        "model_b": res_b,
        "speed_winner": faster_model,
        "summary": summary
    }

def get_benchmark_history(limit: int = 25) -> List[Dict[str, Any]]:
    """Liefert die historischen Benchmark-Vergleichsläufe."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM model_benchmarks ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return []
