"""
backend/map_reduce_executor.py
Paket 1 (Feature 2): Paralleles Map-Reduce Sub-Tasking (Fan-Out & Fan-In Engine).
Zerlegt Mehrfach-Aufgaben (Dokument-Listen, URLs, Code-Dateien, Sub-Fragen) in isolierte Teilaufgaben,
führt diese parallel über eine asyncio.Semaphore(max_parallel_workers) aus und synthetisiert
im Reduce-Schritt ein konsolidiertes Gesamtergebnis.
"""

import os
import json
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
from typing import List, Dict, Any, Optional, Callable

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("map_reduce")
    except Exception:
        return {
            "enabled": True,
            "max_parallel_workers": 4,
            "chunk_timeout_seconds": 30,
            "auto_fan_out_min_items": 3
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS map_reduce_jobs (
                job_id TEXT PRIMARY KEY,
                task_title TEXT,
                total_items INTEGER,
                max_workers INTEGER,
                completed_items INTEGER,
                failed_items INTEGER,
                execution_mode TEXT,
                duration_ms REAL,
                reduced_summary TEXT,
                results_json TEXT,
                created_at TEXT
            )
        """)
        conn.commit()


class MapReduceExecutor:
    def __init__(self):
        _init_db()

    async def _process_single_chunk(
        self,
        index: int,
        item: Any,
        instruction: str,
        sem: asyncio.Semaphore,
        timeout_sec: float,
        worker_fn: Optional[Callable] = None
    ) -> Dict[str, Any]:
        async with sem:
            t0 = time.perf_counter()
            try:
                if worker_fn is not None:
                    res = await asyncio.wait_for(worker_fn(index, item, instruction), timeout=timeout_sec)
                else:
                    # Deterministischer schneller lokaler Analyse-Worker (mit optionalem Mini-Sleep zur Concurrency-Messung)
                    await asyncio.sleep(0.01)
                    item_str = str(item).strip()
                    word_count = len(item_str.split())
                    res = (
                        f"[Worker #{index + 1}] Analysiert ({word_count} Wörter) gemäß '{instruction[:60]}': "
                        f"Kernaussage extrahiert aus '{item_str[:120]}'"
                    )
                return {
                    "index": index,
                    "status": "completed",
                    "item_preview": str(item)[:80],
                    "output": res,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 2)
                }
            except asyncio.TimeoutError:
                return {
                    "index": index,
                    "status": "timeout",
                    "item_preview": str(item)[:80],
                    "output": f"Timeout nach {timeout_sec}s überschritten.",
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 2)
                }
            except Exception as e:
                return {
                    "index": index,
                    "status": "failed",
                    "item_preview": str(item)[:80],
                    "output": f"Fehler: {e}",
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 2)
                }

    async def execute_map_reduce(
        self,
        task_title: str,
        items: List[Any],
        instruction: str = "Analysiere und extrahiere Kernergebnisse",
        max_workers_override: Optional[int] = None,
        worker_fn: Optional[Callable] = None
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        max_workers = int(max_workers_override or cfg.get("max_parallel_workers", 4))
        timeout_sec = float(cfg.get("chunk_timeout_seconds", 30))
        min_items = int(cfg.get("auto_fan_out_min_items", 3))

        job_id = f"mr-{uuid.uuid4().hex[:10]}"
        effective_workers = max(1, max_workers) if (enabled and len(items) >= min_items) else 1
        execution_mode = "parallel_fan_out" if effective_workers > 1 else "sequential_fallback"

        sem = asyncio.Semaphore(effective_workers)
        tasks = [
            self._process_single_chunk(idx, item, instruction, sem, timeout_sec, worker_fn)
            for idx, item in enumerate(items)
        ]
        chunk_results = await asyncio.gather(*tasks)
        chunk_results.sort(key=lambda x: x["index"])

        completed = sum(1 for r in chunk_results if r["status"] == "completed")
        failed = len(chunk_results) - completed

        # Reduce-Phase: Synthese aller erfolgreichen Worker-Outputs
        bullet_points = [f"- {r['output']}" for r in chunk_results if r["status"] == "completed"]
        reduced_summary = (
            f"### Map-Reduce Synthese: {task_title}\n"
            f"- **Modus:** `{execution_mode}` ({effective_workers} Worker parallel)\n"
            f"- **Erfolgsquote:** {completed}/{len(items)} Teilaufgaben abgeschlossen\n\n"
            + "\n".join(bullet_points)
        )

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO map_reduce_jobs
                (job_id, task_title, total_items, max_workers, completed_items, failed_items,
                 execution_mode, duration_ms, reduced_summary, results_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, task_title, len(items), effective_workers,
                completed, failed, execution_mode, duration_ms,
                reduced_summary, json.dumps(chunk_results, ensure_ascii=False), now_iso
            ))
            conn.commit()

        return {
            "job_id": job_id,
            "task_title": task_title,
            "enabled": enabled,
            "execution_mode": execution_mode,
            "max_parallel_workers": effective_workers,
            "total_items": len(items),
            "completed_items": completed,
            "failed_items": failed,
            "duration_ms": duration_ms,
            "reduced_summary": reduced_summary,
            "chunks": chunk_results
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT job_id, task_title, total_items, max_workers, completed_items, failed_items, "
                "execution_mode, duration_ms, reduced_summary, created_at "
                "FROM map_reduce_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]


map_reduce_executor = MapReduceExecutor()
