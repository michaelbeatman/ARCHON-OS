"""
backend/async_write_batcher.py
Paket 1 (Feature 5): SQLite Connection-Pool & Async Write-Batching.
Puffert hochfrequente Telemetrie-, Audit- und Trace-Schreibzugriffe im RAM und schreibt sie
gebündelt in einer einzigen SQLite-WAL-Transaktion auf die Festplatte (`batch_size` Standard: 25,
`flush_interval_seconds` Standard: 2.0s). Reduziert Disk-I/O und SQLite-Lock-Contention um ~80 %.
"""

import os
import json
import time
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
import threading
from collections import deque
from datetime import datetime
from types import MappingProxyType
from typing import Dict, Any, List, Deque, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

_CFG_TTL = 5.0
# D08/S-8.4: harte Retention fuer die gebündelte Telemetrie-Tabelle. Ohne
# Begrenzung waechst sie linear und der Statistik-Endpoint wird mit der Zeit
# langsamer. Konfigurierbar via `retention_max_rows` im write_batcher-Modul.
_DEFAULT_MAX_ROWS = 100_000
_CFG_CACHE_LOCK = threading.Lock()
# F-059: Ein EINZIGER unveraenderlicher Wert. Die Referenz-Zuweisung ist atomar,
# damit parallele Reader (Event-Loop + FastAPI-Threadpool) nie ein teils
# aktualisiertes Cache-Paar (ts/cfg) sehen.
_CFG_CACHE = MappingProxyType({"ts": 0.0, "cfg": None})


def _get_cfg() -> Dict[str, Any]:
    global _CFG_CACHE
    now = time.monotonic()
    cached = _CFG_CACHE
    cfg = cached["cfg"]
    if cfg is not None and (now - cached["ts"]) < _CFG_TTL:
        return cfg

    # Double-Check unter Lock: bei einem TTL-Miss baut genau EIN Thread den
    # Cache neu (Single-Flight), alle anderen warten und lesen danach das
    # fertige Ergebnis statt den Import/get_module_config parallel auszufuehren.
    with _CFG_CACHE_LOCK:
        cached = _CFG_CACHE
        now = time.monotonic()
        cfg = cached["cfg"]
        if cfg is not None and (now - cached["ts"]) < _CFG_TTL:
            return cfg
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("write_batcher")
        except Exception:
            cfg = {
                "enabled": True,
                "batch_size": 25,
                "flush_interval_seconds": 2.0,
                "max_queue_size": 1000
            }
        _CFG_CACHE = MappingProxyType({"ts": now, "cfg": cfg})
        return cfg


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batched_telemetry_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                source_module TEXT,
                payload_json TEXT,
                created_at TEXT,
                flushed_at TEXT
            )
        """)
        conn.commit()


class AsyncWriteBatcher:
    def __init__(self):
        _init_db()
        self._lock = threading.Lock()
        self._buffer: Deque[Dict[str, Any]] = deque()
        self._total_enqueued = 0
        self._total_flushed_events = 0
        self._total_batch_commits = 0
        self._last_flush_time = time.time()
        #Materialisierter, bounded Zaehler statt COUNT(*)-Full-Scan in get_stats().
        self._persisted_in_db: Optional[int] = None

    def enqueue(self, event_type: str, source_module: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        batch_size = int(cfg.get("batch_size", 25))
        flush_interval = float(cfg.get("flush_interval_seconds", 2.0))
        max_queue = int(cfg.get("max_queue_size", 1000))

        entry = {
            "event_type": event_type,
            "source_module": source_module,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        should_flush = False
        with self._lock:
            # FRUEHER: popleft() —aelteste Events wurden genau bei hoher Last
            # still verworfen (Audit-/Telemetrie-Luecke). Jetzt Backpressure:
            # bei vollem Puffer wird sofort der gesamte Puffer geschrieben,
            # bevor weitergepuffert wird. Kein Event geht verloren.
            queue_full = len(self._buffer) >= max_queue
            self._buffer.append(entry)
            self._total_enqueued += 1

            elapsed = time.time() - self._last_flush_time
            if queue_full or not enabled or len(self._buffer) >= batch_size or elapsed >= flush_interval:
                should_flush = True

        flush_result = None
        if should_flush:
            flush_result = self.flush()

        return {
            "enqueued": True,
            "batching_enabled": enabled,
            "buffer_size": len(self._buffer),
            "auto_flushed": should_flush,
            "flush_result": flush_result
        }

    def flush(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            if not self._buffer:
                return {"flushed_count": 0, "duration_ms": 0.0}
            batch = list(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.time()

        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg = _get_cfg()
        max_rows = max(1, int(cfg.get("retention_max_rows", _DEFAULT_MAX_ROWS)))
        try:
            with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                #Einmalige, auf max_rows begrenzte Baseline (bestehende DBs).
                baseline = self._persisted_in_db
                if baseline is None:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM (SELECT id FROM batched_telemetry_events LIMIT ?)",
                        (max_rows,),
                    ).fetchone()
                    baseline = int(row[0] if row else 0)
                conn.executemany("""
                    INSERT INTO batched_telemetry_events
                    (event_type, source_module, payload_json, created_at, flushed_at)
                    VALUES (?, ?, ?, ?, ?)
                """, [
                    (item["event_type"], item["source_module"], item["payload_json"], item["created_at"], now_iso)
                    for item in batch
                ])
                #Retention im selben Batch: aelteste Zeilen fallen unter die
                #konfigurierte Hoechstzahl (kein Drainer/Replay noetig).
                conn.execute(
                    "DELETE FROM batched_telemetry_events WHERE id NOT IN "
                    "(SELECT id FROM batched_telemetry_events ORDER BY id DESC LIMIT ?)",
                    (max_rows,),
                )
                conn.commit()
        except Exception as e:
            with self._lock:
                self._buffer.extendleft(reversed(batch))
            raise e

        with self._lock:
            self._total_flushed_events += len(batch)
            self._total_batch_commits += 1
            self._persisted_in_db = min(baseline + len(batch), max_rows)

        return {
            "flushed_count": len(batch),
            "batch_commits_total": self._total_batch_commits,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

    def get_stats(self) -> Dict[str, Any]:
        cfg = _get_cfg()
        with self._lock:
            buf_len = len(self._buffer)
            enq = self._total_enqueued
            flushed = self._total_flushed_events
            commits = self._total_batch_commits
            persisted = self._persisted_in_db or 0

        io_reduction_pct = round((1.0 - (commits / max(1, flushed))) * 100, 1) if flushed > 0 else 0.0
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "batch_size": int(cfg.get("batch_size", 25)),
            "flush_interval_seconds": float(cfg.get("flush_interval_seconds", 2.0)),
            "pending_in_ram_buffer": buf_len,
            "total_enqueued": enq,
            "total_flushed_events": flushed,
            "total_batch_commits": commits,
            "persisted_in_db": persisted,
            "estimated_io_reduction_pct": max(0.0, io_reduction_pct)
        }


async_write_batcher = AsyncWriteBatcher()
