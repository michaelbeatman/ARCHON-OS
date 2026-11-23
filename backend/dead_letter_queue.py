"""
backend/dead_letter_queue.py
Paket 3 (Feature 15): Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager.
Fängt fehlgeschlagene Hintergrund-Jobs, Webhook-Zustellungen und Sub-Agenten-Aufträge samt
Payload und Traceback in SQLite (`dead_letter_queue`) auf und ermöglicht Einzel- oder Batch-Replays
mit exponentiellem Backoff.
"""

import os
import json
import uuid
import inspect
import asyncio
import sqlite3
from typing import Callable

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
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("dead_letter_queue")
    except Exception:
        return {
            "enabled": True,
            "max_replay_retries": 3,
            "backoff_base_seconds": 10,
            "auto_replay_enabled": True
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dead_letter_queue (
                dlq_id TEXT PRIMARY KEY,
                job_type TEXT,
                source_module TEXT,
                payload_json TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                next_backoff_seconds INTEGER DEFAULT 10,
                status TEXT DEFAULT 'queued',
                created_at TEXT,
                last_replay_at TEXT
            )
        """)
        # Shared-Queue-Erweiterung: attempt-Logik, Idempotenz-Key, Priorität
        # und CAS-Leases für Work-Stealing über mehrere Worker hinweg.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(dead_letter_queue)").fetchall()}
        for col, decl in (
            ("attempt", "INTEGER DEFAULT 0"),
            ("idempotency_key", "TEXT DEFAULT ''"),
            ("priority", "INTEGER DEFAULT 0"),
            ("claimed_by", "TEXT DEFAULT ''"),
            ("claim_expires", "REAL DEFAULT 0"),
            # Audit 23.11.2026: next_backoff_seconds wurde gespeichert, aber
            # beim Claim nie ausgewertet → Hot-Retry-Loop.
            ("next_try_at", "REAL DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE dead_letter_queue ADD COLUMN {col} {decl}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_dlq_idempotency "
            "ON dead_letter_queue(idempotency_key) WHERE idempotency_key != ''"
        )
        conn.commit()


# Registry job_type -> Executor. Ein Replay ist nur dann "echt", wenn fuer den
# job_type ein ausfuehrbarer Executor registriert ist. Ohne Executor wird der
# Replay abgelehnt (fail-closed) statt einfach eine Erfolgsmeldung zu erfinden.
_JOB_EXECUTORS: Dict[str, Callable[..., Any]] = {}


def register_job_executor(job_type: str, executor: Optional[Callable[..., Any]] = None):
    """Registriert einen Replay-Executor (auch als Dekorator nutzbar)."""
    def _register(fn: Callable[..., Any]) -> Callable[..., Any]:
        _JOB_EXECUTORS[str(job_type)] = fn
        return fn
    if executor is not None:
        return _register(executor)
    return _register


def _builtin_executor(job_type: str) -> Optional[Callable[..., Any]]:
    """Lazy Built-ins (vermeidet zyklische Importe beim Modul-Laden)."""
    if job_type == "webhook_delivery":
        def _redeliver(payload: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
            from backend.event_mesh import event_mesh
            return event_mesh.emit_outbound_event(
                webhook_url=str(payload.get("target_url") or ""),
                event_type=str(payload.get("event_type") or "webhook_delivery"),
                payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else payload,
            )
        return _redeliver
    return None


def _run_executor(executor: Callable[..., Any], payload: Dict[str, Any], item: Dict[str, Any]) -> Any:
    result = executor(payload, item)
    if inspect.isawaitable(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # Aus async Kontext: nicht blockieren, Task im laufenden Loop fortfuehren.
            loop.create_task(result)
            return {"status": "scheduled"}
        return asyncio.run(result)
    return result


class DeadLetterQueueManager:
    def __init__(self):
        _init_db()

    def enqueue_failed_job(
        self,
        job_type: str,
        source_module: str,
        payload: Dict[str, Any],
        error_message: str
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"queued": False, "bypassed": True}

        dlq_id = f"dlq-{uuid.uuid4().hex[:10]}"
        max_retries = int(cfg.get("max_replay_retries", 3))
        base_backoff = int(cfg.get("backoff_base_seconds", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO dead_letter_queue
                (dlq_id, job_type, source_module, payload_json, error_message,
                 retry_count, max_retries, next_backoff_seconds, status, created_at, last_replay_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'queued', ?, NULL)
            """, (
                dlq_id, job_type, source_module,
                json.dumps(payload, ensure_ascii=False),
                error_message, max_retries, base_backoff, now_iso
            ))
            conn.commit()

        return {
            "queued": True,
            "dlq_id": dlq_id,
            "job_type": job_type,
            "max_retries": max_retries,
            "next_backoff_seconds": base_backoff
        }

    def replay_job(self, dlq_id: str, simulate_success: bool = False) -> Dict[str, Any]:
        """Replayed einen DLQ-Job.

        `simulate_success=False` (Default) ist der PRODUKTIVPFAD: der registrierte
        Executor fuer den job_type wird tatsaechlich ausgefuehrt. Nur explizites
        `simulate_success=True` ist der Demo-Pfad (z. B. Test-Endpoint) und darf
        nie als echter Erfolg interpretiert werden.
        """
        cfg = _get_cfg()
        base_backoff = int(cfg.get("backoff_base_seconds", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM dead_letter_queue WHERE dlq_id = ?", (dlq_id,)).fetchone()
            if not row:
                return {"replayed": False, "error": f"DLQ-Eintrag '{dlq_id}' nicht gefunden."}
            item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload_json") or "{}")
        except (ValueError, TypeError):
            item["payload"] = {}

        new_retry = int(row["retry_count"] or 0) + 1
        replay_result: Any = None
        error_text = ""
        if simulate_success:
            # Demo: bewusst KEIN Seiteneffekt, aber explizit gekennzeichnet.
            new_status = "replayed_success"
            next_backoff = 0
            replay_result = {"demo_only": True}
        else:
            executor = _JOB_EXECUTORS.get(str(row["job_type"])) or _builtin_executor(str(row["job_type"]))
            if executor is None:
                return {
                    "replayed": False,
                    "status": "queued",
                    "error": f"Kein Replay-Executor fuer job_type '{row['job_type']}' registriert.",
                    "job_type": row["job_type"],
                    "dlq_id": dlq_id,
                }
            try:
                replay_result = _run_executor(executor, item["payload"], item)
                if isinstance(replay_result, dict) and replay_result.get("status") == "scheduled":
                    # Audit 23.11.2026: ein nur geplanter Task ist KEIN
                    # bestätigter Erfolg — sonst meldet die DLQ Erfolg, ohne
                    # dass die Zustellung je stattfand.
                    new_status = "queued"
                    next_backoff = base_backoff * (2 ** new_retry)
                    error_text = "replay scheduled; completion not verified"
                else:
                    new_status = "replayed_success"
                    next_backoff = 0
            except Exception as exc:
                error_text = str(exc)[:1000]
                new_status = "exhausted" if new_retry >= int(row["max_retries"] or 3) else "queued"
                next_backoff = base_backoff * (2 ** new_retry)

        next_try_at = (
            datetime.now().timestamp() + max(1, int(next_backoff or 0))
            if new_status == "queued" else 0.0
        )
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                UPDATE dead_letter_queue
                SET retry_count = ?, status = ?, next_backoff_seconds = ?, next_try_at = ?,
                    last_replay_at = ?, error_message = ?
                WHERE dlq_id = ?
            """, (new_retry, new_status, next_backoff, next_try_at, now_iso, error_text, dlq_id))
            conn.commit()

        return {
            "replayed": bool(new_status == "replayed_success"),
            "demo_only": bool(simulate_success),
            "dlq_id": dlq_id,
            "job_type": row["job_type"],
            "status": new_status,
            "retry_count": new_retry,
            "next_backoff_seconds": next_backoff,
            "last_replay_at": now_iso,
            "result": replay_result,
            "error": error_text or None,
        }

    def enqueue_task(
        self,
        job_type: str,
        source_module: str,
        payload: Dict[str, Any],
        *,
        priority: int = 0,
        idempotency_key: str = "",
        max_retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Legt einen Job in der Shared Queue ab (idempotent pro idempotency_key)."""
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"queued": False, "bypassed": True}
        key = str(idempotency_key or "")
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            if key:
                existing = conn.execute(
                    "SELECT dlq_id, status FROM dead_letter_queue WHERE idempotency_key = ?", (key,)
                ).fetchone()
                if existing is not None:
                    return {
                        "queued": False, "duplicate": True,
                        "dlq_id": existing["dlq_id"], "status": existing["status"],
                    }
            dlq_id = f"dlq-{uuid.uuid4().hex[:10]}"
            retries = int(max_retries if max_retries is not None else cfg.get("max_replay_retries", 3))
            conn.execute(
                "INSERT INTO dead_letter_queue "
                "(dlq_id, job_type, source_module, payload_json, error_message, retry_count, max_retries, "
                " next_backoff_seconds, status, created_at, last_replay_at, attempt, idempotency_key, priority, "
                " claimed_by, claim_expires) "
                "VALUES (?, ?, ?, ?, '', 0, ?, ?, 'queued', ?, NULL, 0, ?, ?, '', 0)",
                (
                    dlq_id, job_type, source_module,
                    json.dumps(payload, ensure_ascii=False), retries,
                    int(cfg.get("backoff_base_seconds", 10)), now_iso, key, int(priority),
                ),
            )
            conn.commit()
        return {"queued": True, "dlq_id": dlq_id, "job_type": job_type, "priority": int(priority)}

    def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        job_types: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """CAS-Claim des naechsten faelligen Jobs (Work-Stealing nach Prioritaet)."""
        now = datetime.now().timestamp()
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            sql = (
                "SELECT * FROM dead_letter_queue "
                "WHERE status = 'queued' AND (claimed_by = '' OR claim_expires <= ?) "
                "AND COALESCE(next_try_at, 0) <= ?"
            )
            params: List[Any] = [now, now]
            if job_types:
                marks = ",".join("?" for _ in job_types)
                sql += f" AND job_type IN ({marks})"
                params.extend(job_types)
            sql += " ORDER BY priority DESC, created_at ASC LIMIT 1"
            row = conn.execute(sql, params).fetchone()
            if row is None:
                conn.commit()
                return None
            claim_until = now + max(10, int(lease_seconds))
            cur = conn.execute(
                "UPDATE dead_letter_queue SET claimed_by = ?, claim_expires = ? "
                "WHERE dlq_id = ? AND status = 'queued' AND (claimed_by = '' OR claim_expires <= ?)",
                (str(worker_id), claim_until, row["dlq_id"], now),
            )
            claimed = int(cur.rowcount or 0) == 1
            conn.commit()
        if not claimed:
            return None
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload_json") or "{}")
        except (ValueError, TypeError):
            item["payload"] = {}
        return item

    def complete(self, dlq_id: str, result: Optional[Dict[str, Any]] = None) -> bool:
        """Erfolgreich verarbeiteten Job abschliessen und Lease freigeben."""
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            cur = conn.execute(
                "UPDATE dead_letter_queue SET status = 'completed', claimed_by = '', "
                "claim_expires = 0, error_message = ? WHERE dlq_id = ? AND status != 'completed'",
                (json.dumps(result or {}, ensure_ascii=False), dlq_id),
            )
            conn.commit()
            return int(cur.rowcount or 0) == 1

    def fail(self, dlq_id: str, error_message: str = "") -> Dict[str, Any]:
        """Fehlgeschlagenen Job zaehlen; nach max_retries Dead-Letter."""
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT retry_count, max_retries, attempt, next_backoff_seconds "
                "FROM dead_letter_queue WHERE dlq_id = ?",
                (dlq_id,),
            ).fetchone()
            if row is None:
                return {"failed": False, "error": f"DLQ-Eintrag '{dlq_id}' nicht gefunden."}
            attempt = int(row["attempt"] or 0) + 1
            retry_count = int(row["retry_count"] or 0) + 1
            dead = retry_count >= int(row["max_retries"] or 3)
            backoff = max(1, int(row["next_backoff_seconds"] or 10))
            next_try_at = datetime.now().timestamp() + backoff
            conn.execute(
                "UPDATE dead_letter_queue SET attempt = ?, retry_count = ?, status = ?, "
                "claimed_by = '', claim_expires = 0, next_try_at = ?, "
                "last_replay_at = ?, error_message = ? WHERE dlq_id = ?",
                (
                    attempt, retry_count, "dead" if dead else "queued", next_try_at,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), error_message, dlq_id,
                ),
            )
            conn.commit()
        return {"failed": True, "dlq_id": dlq_id, "attempt": attempt,
                "status": "dead" if dead else "queued"}

    def list_dlq(self, status_filter: Optional[str] = None) -> Dict[str, Any]:
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            if status_filter:
                total = conn.execute("SELECT COUNT(*) FROM dead_letter_queue WHERE status = ?", (status_filter,)).fetchone()[0]
                rows = conn.execute(
                    "SELECT * FROM dead_letter_queue WHERE status = ? ORDER BY created_at DESC LIMIT 50",
                    (status_filter,)
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) FROM dead_letter_queue").fetchone()[0]
                rows = conn.execute("SELECT * FROM dead_letter_queue ORDER BY created_at DESC LIMIT 50").fetchall()
            items = [dict(r) for r in rows]
        return {"total": total, "items": items}


dead_letter_queue_manager = DeadLetterQueueManager()
