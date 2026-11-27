"""
backend/dead_letter_queue.py
Paket 3 (Feature 15): Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager.
Fängt fehlgeschlagene Hintergrund-Jobs, Webhook-Zustellungen und Sub-Agenten-Aufträge samt
Payload und Traceback in SQLite (`dead_letter_queue`) auf und ermöglicht Einzel- oder Batch-Replays
mit exponentiellem Backoff.
"""

import asyncio
import inspect
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, cast

logger = logging.getLogger("archon_os.dead_letter_queue")

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    _LEGACY_DB_PATH = _resolve_db("memory.db")
except Exception:
    _LEGACY_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "memory.db")

# F014 / H-06-1: DB_PATH bleibt der monkeypatchbare Default (bestehende Tests).
# Produktiv wird PRO AUFRUF ueber die SSOT mandantenisoliert aufgeloest.
DB_PATH = _LEGACY_DB_PATH

_LEGACY_SHARED_ENV = "ARCHON_LEDGER_LEGACY_SHARED_DB"

# Nur waehrend des Modul-Imports (Singleton-Schema) ist ein best-effort
# Fallback erlaubt; zur Laufzeit ist der Resolver fail-closed (F014).
_IMPORT_BOOTSTRAP = True


def _legacy_shared_allowed() -> bool:
    """Expliziter, dokumentierter Legacy-Modus fuer eine geteilte Ledger-DB."""
    return os.environ.get(_LEGACY_SHARED_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _db_path() -> str:
    """F014: mandantenisolierter DLQ-Pfad (SSOT: db_paths.resolve_tenant_db)."""
    if DB_PATH != _LEGACY_DB_PATH:
        return DB_PATH  # expliziter Override (Tests / bewusste Konfiguration)
    try:
        from backend.db_paths import resolve_tenant_db
        return resolve_tenant_db("memory.db")
    except Exception as exc:
        if _legacy_shared_allowed() or _IMPORT_BOOTSTRAP:
            logger.warning(
                "[F014] Tenant-Resolver unavailable (%s); best-effort legacy path: %s",
                "explicit legacy mode" if _legacy_shared_allowed() else "import bootstrap",
                exc,
            )
            return _LEGACY_DB_PATH
        raise RuntimeError(
            f"[F014] Tenant-DB resolution failed for dead letter queue: {exc}. "
            f"Set {_LEGACY_SHARED_ENV}=1 only for an explicitly accepted legacy deployment."
        ) from exc


def _current_tenant_id() -> str:
    """Aktiver Mandant (Request-Kontext vor Corporate-Default)."""
    try:
        from backend.tenant_context import _REQUEST_TENANT_VAR, sanitize_tenant_id
        tid = _REQUEST_TENANT_VAR.get()
        if tid:
            return sanitize_tenant_id(tid)
    except Exception:
        pass
    try:
        from backend.tenant_context import tenant_context
        return tenant_context.get_active_tenant_id()
    except Exception:
        return "default"


def _tenant_key(tenant_id: str, key: str) -> str:
    """Mandanten-Praefix fuer Dedup-/Idempotency-Keys (H-06-1)."""
    return f"{tenant_id}::{key}" if key else ""


def _tenant_sql(tenant_id: str) -> tuple[str, tuple[str, str]]:
    """F014: tenant-scoped WHERE-Klausel.

    Legacy-Zeilen mit leerem tenant_id gehoeren ausschliesslich dem
    Default-Mandanten — so koennen Bestandsdaten gelesen werden, ohne dass
    ein anderer Mandant fremde Zeilen sieht.
    """
    return (
        "(tenant_id = ? OR (COALESCE(tenant_id, '') = '' AND ? = 'default'))",
        (str(tenant_id), str(tenant_id)),
    )


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


_TRACE_COLS = ("trace_id", "span_id", "traceparent", "tracestate")


def _trace_fields(
    trace_id: str = "", span_id: str = "", traceparent: str = "", tracestate: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Trace-Kontext aus expliziten Argumenten, Payload oder aktuellem Kontext."""
    src = payload or {}
    out = {
        "trace_id": str(trace_id or src.get("trace_id") or ""),
        "span_id": str(span_id or src.get("span_id") or ""),
        "traceparent": str(traceparent or src.get("traceparent") or ""),
        "tracestate": str(tracestate or src.get("tracestate") or ""),
    }
    try:
        from backend import trace_context as tc
        if not out["trace_id"]:
            out["trace_id"] = tc.current_trace_id()
        if not out["span_id"]:
            out["span_id"] = tc.current_span_id()
        if not out["traceparent"] and out["trace_id"] and out["span_id"]:
            out["traceparent"] = tc.format_traceparent(out["trace_id"], out["span_id"])
        out["tracestate"] = tc.sanitize_tracestate(out["tracestate"] or tc.current_tracestate())
    except Exception as exc:
        logger.warning("[DLQ] Trace-Kontext nicht verfügbar: %s", exc)
    return out


_INITIALIZED_PATHS: set[str] = set()


def _ensure_db(tenant_id: Optional[str] = None) -> str:
    """D06-H1: DLQ-Schema im EXPLIZITEN Mandanten-Pfad sicherstellen.

    ``_db_path()`` löst über den Request-Mandanten auf. Ohne tenant_id bleibt
    das historische Verhalten (aktiver Mandant) unverändert; mit tenant_id
    wird der Kontext nur für die Pfadauflösung gebunden und sofort restored.
    """
    token: Any = None
    if tenant_id:
        from backend.tenant_context import reset_request_tenant, set_request_tenant
        token = set_request_tenant(tenant_id)
    try:
        path = _db_path()
        if path not in _INITIALIZED_PATHS:
            _init_db(path)
            _INITIALIZED_PATHS.add(path)
        return path
    finally:
        if token is not None:
            reset_request_tenant(token)


def _init_db(db_path: Optional[str] = None) -> str:
    db_path = db_path or _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=15.0, factory=_ArchonClosingConn) as conn:
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
            # D16: Trace-Kontext für Re-Injektion bei Replay (kein Coroutine-Replay).
            ("trace_id", "TEXT DEFAULT ''"),
            ("span_id", "TEXT DEFAULT ''"),
            ("traceparent", "TEXT DEFAULT ''"),
            ("tracestate", "TEXT DEFAULT ''"),
            # F014/H-06-1: Mandant als eigene Spalte (bestandskompatibel via ALTER).
            ("tenant_id", "TEXT DEFAULT ''"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE dead_letter_queue ADD COLUMN {col} {decl}")
        # F014: der alte globale Unique-Index auf idempotency_key allein hat
        # zwei Mandanten mit identischem Key gegenseitig unterdrueckt. Er wird
        # einmalig durch einen tenant-scoped Index ersetzt ( kein Datenverlust,
        # die Spalte bleibt unveraendert erhalten ).
        conn.execute("DROP INDEX IF EXISTS idx_dlq_idempotency")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_dlq_idempotency_tenant "
            "ON dead_letter_queue(tenant_id, idempotency_key) WHERE idempotency_key != ''"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_tenant ON dead_letter_queue(tenant_id)")
        # W4-B/Retention: created_at-Index fuer purge_integration_retention.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_created ON dead_letter_queue(created_at)")
        conn.commit()
    return db_path


# Registry job_type -> Executor. Ein Replay ist nur dann "echt", wenn fuer den
# job_type ein ausfuehrbarer Executor registriert ist. Ohne Executor wird der
# Replay abgelehnt (fail-closed) statt einfach eine Erfolgsmeldung zu erfinden.
_JOB_EXECUTORS: Dict[str, Callable[..., Any]] = {}

# C: Referenzen auf fire-and-forget Replay-Tasks. Ohne Registry kann ein
# Replay-Thread den Task verlieren und ein zweiter Replay denselben Job
# noch einmal zustellen (doppelte Webhooks/Mails).
_RUNNING_TASKS: "set[asyncio.Task[Any]]" = set()


def _track_replay_task(task: "asyncio.Task[Any]") -> None:
    """Task bis zum Abschluss halten und Ausnahmen sichtbar machen."""
    _RUNNING_TASKS.add(task)

    def _done(done_task: "asyncio.Task[Any]") -> None:
        _RUNNING_TASKS.discard(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            logger.error("[DLQ] Hintergrund-Replay fehlgeschlagen: %s", exc)

    task.add_done_callback(_done)


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
            from backend import trace_context as tc
            from backend.event_mesh import event_mesh
            src: Dict[str, Any] = {k: (item.get(k) or payload.get(k) or "") for k in _TRACE_COLS}
            trace = _trace_fields(payload=src)
            # Persistierten Kontext wiederherstellen; emit_outbound_event erzeugt
            # daraus den Child-Span und injiziert traceparent/tracestate erneut.
            with tc.use_trace_context(
                trace_id=trace["trace_id"],
                span_id=trace["span_id"],
                traceparent=trace["traceparent"],
                tracestate=trace["tracestate"],
            ):
                raw_payload = payload.get("payload")
                event_payload: Dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else payload
                return event_mesh.emit_outbound_event(
                    webhook_url=str(payload.get("target_url") or ""),
                    event_type=str(payload.get("event_type") or "webhook_delivery"),
                    payload=event_payload,
                    trace_columns=trace,
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
        coro = cast("Coroutine[Any, Any, Any]", result)
        if loop is not None and loop.is_running():
            # Aus async Kontext: nicht blockieren, Task im laufenden Loop fortfuehren.
            # C: Task referenzieren, damit er nicht GC-verloren geht und
            # Exceptions nicht unbemerkt bleiben.
            _track_replay_task(loop.create_task(coro))
            return {"status": "scheduled"}
        return asyncio.run(coro)
    return result


class DeadLetterQueueManager:
    def __init__(self):
        path = _init_db()
        _INITIALIZED_PATHS.add(path)

    def enqueue_failed_job(
        self,
        job_type: str,
        source_module: str,
        payload: Dict[str, Any],
        error_message: str,
        *,
        trace_id: str = "", span_id: str = "", traceparent: str = "", tracestate: str = "",
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"queued": False, "bypassed": True}

        tid = str(tenant_id or _current_tenant_id())
        dlq_id = f"dlq-{uuid.uuid4().hex[:10]}"
        max_retries = int(cfg.get("max_replay_retries", 3))
        base_backoff = int(cfg.get("backoff_base_seconds", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trace = _trace_fields(trace_id, span_id, traceparent, tracestate, payload)

        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO dead_letter_queue
                (dlq_id, job_type, source_module, payload_json, error_message,
                 retry_count, max_retries, next_backoff_seconds, status, created_at, last_replay_at,
                 trace_id, span_id, traceparent, tracestate, tenant_id)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'queued', ?, NULL, ?, ?, ?, ?, ?)
            """, (
                dlq_id, job_type, source_module,
                json.dumps(payload, ensure_ascii=False),
                error_message, max_retries, base_backoff, now_iso,
                trace["trace_id"], trace["span_id"], trace["traceparent"], trace["tracestate"], tid,
            ))
            conn.commit()

        return {
            "queued": True,
            "dlq_id": dlq_id,
            "job_type": job_type,
            "max_retries": max_retries,
            "next_backoff_seconds": base_backoff
        }

    def replay_job(
        self, dlq_id: str, simulate_success: bool = False, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replayed einen DLQ-Job.

        `simulate_success=False` (Default) ist der PRODUKTIVPFAD: der registrierte
        Executor fuer den job_type wird tatsaechlich ausgefuehrt. Nur explizites
        `simulate_success=True` ist der Demo-Pfad (z. B. Test-Endpoint) und darf
        nie als echter Erfolg interpretiert werden.
        """
        cfg = _get_cfg()
        base_backoff = int(cfg.get("backoff_base_seconds", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM dead_letter_queue WHERE dlq_id = ? AND {tenant_sql}",
                (dlq_id, *tenant_params),
            ).fetchone()
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
        claim_worker: Optional[str] = None
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
            # C: CAS-Claim nach dem Muster von claim_next(). Erst mit
            # gehaltenem Claim darf zugestellt und danach der Status
            # (insbesondere 'queued') geschrieben werden.
            claim_worker = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
            now_ts = datetime.now().timestamp()
            with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "UPDATE dead_letter_queue SET claimed_by = ?, claim_expires = ? "
                    "WHERE dlq_id = ? AND "
                    "(claimed_by = '' OR claimed_by IS NULL OR claim_expires IS NULL OR claim_expires <= ?)",
                    (claim_worker, now_ts + 120, dlq_id, now_ts),
                )
                claimed = int(cur.rowcount or 0) == 1
                conn.commit()
            if not claimed:
                return {
                    "replayed": False,
                    "status": "queued",
                    "error": f"DLQ-Eintrag '{dlq_id}' wird bereits von einem anderen Worker geclaimt.",
                    "job_type": row["job_type"],
                    "dlq_id": dlq_id,
                    "claim_conflict": True,
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
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            set_sql = (
                "retry_count = ?, status = ?, next_backoff_seconds = ?, next_try_at = ?, "
                "last_replay_at = ?, error_message = ?"
            )
            if claim_worker is not None:
                set_sql += ", claimed_by = '', claim_expires = 0"
            sql = f"UPDATE dead_letter_queue SET {set_sql} WHERE dlq_id = ?"
            params: List[Any] = [new_retry, new_status, next_backoff, next_try_at, now_iso, error_text, dlq_id]
            if claim_worker is not None:
                # C: Nur schreiben, wenn wir den Claim noch halten.
                sql += " AND claimed_by = ?"
                params.append(claim_worker)
            changed = conn.execute(sql, params).rowcount
            conn.commit()
            if claim_worker is not None and int(changed or 0) != 1:
                logger.warning("[DLQ] Claim für '%s' verloren; Status wurde nicht geschrieben.", dlq_id)

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
        trace_id: str = "", span_id: str = "", traceparent: str = "", tracestate: str = "",
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Legt einen Job in der Shared Queue ab (idempotent pro tenant_id + key)."""
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"queued": False, "bypassed": True}
        tid = str(tenant_id or _current_tenant_id())
        key = _tenant_key(tid, str(idempotency_key or ""))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            if key:
                existing = conn.execute(
                    "SELECT dlq_id, status FROM dead_letter_queue WHERE idempotency_key = ? AND tenant_id = ?",
                    (key, tid),
                ).fetchone()
                if existing is not None:
                    return {
                        "queued": False, "duplicate": True,
                        "dlq_id": existing["dlq_id"], "status": existing["status"],
                    }
            dlq_id = f"dlq-{uuid.uuid4().hex[:10]}"
            retries = int(max_retries if max_retries is not None else cfg.get("max_replay_retries", 3))
            trace = _trace_fields(trace_id, span_id, traceparent, tracestate, payload)
            conn.execute(
                "INSERT INTO dead_letter_queue "
                "(dlq_id, job_type, source_module, payload_json, error_message, retry_count, max_retries, "
                " next_backoff_seconds, status, created_at, last_replay_at, attempt, idempotency_key, priority, "
                " claimed_by, claim_expires, trace_id, span_id, traceparent, tracestate, tenant_id) "
                "VALUES (?, ?, ?, ?, '', 0, ?, ?, 'queued', ?, NULL, 0, ?, ?, '', 0, ?, ?, ?, ?, ?)",
                (
                    dlq_id, job_type, source_module,
                    json.dumps(payload, ensure_ascii=False), retries,
                    int(cfg.get("backoff_base_seconds", 10)), now_iso, key, int(priority),
                    trace["trace_id"], trace["span_id"], trace["traceparent"], trace["tracestate"], tid,
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
        tenant_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """CAS-Claim des naechsten faelligen Jobs (Work-Stealing nach Prioritaet).

        Ohne expliziten tenant_id bleibt der Claim DB-weite Worker (die
        physische Mandanten-DB ist unter FULL_TENANT_ISOLATION bereits die
        Grenze). Ein gesetzter tenant_id schraenkt den Claim hart ein.
        """
        now = datetime.now().timestamp()
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            sql = (
                "SELECT * FROM dead_letter_queue "
                "WHERE status = 'queued' AND (claimed_by = '' OR claim_expires <= ?) "
                "AND COALESCE(next_try_at, 0) <= ?"
            )
            params: List[Any] = [now, now]
            if tenant_id is not None:
                sql += " AND tenant_id = ?"
                params.append(str(tenant_id))
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

    def complete(
        self, dlq_id: str, result: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Erfolgreich verarbeiteten Job abschliessen und Lease freigeben."""
        tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            cur = conn.execute(
                "UPDATE dead_letter_queue SET status = 'completed', claimed_by = '', "
                f"claim_expires = 0, error_message = ? WHERE dlq_id = ? AND status != 'completed' AND {tenant_sql}",
                (json.dumps(result or {}, ensure_ascii=False), dlq_id, *tenant_params),
            )
            conn.commit()
            return int(cur.rowcount or 0) == 1

    def fail(
        self, dlq_id: str, error_message: str = "", tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fehlgeschlagenen Job zaehlen; nach max_retries Dead-Letter."""
        tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT retry_count, max_retries, attempt, next_backoff_seconds "
                f"FROM dead_letter_queue WHERE dlq_id = ? AND {tenant_sql}",
                (dlq_id, *tenant_params),
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
                f"last_replay_at = ?, error_message = ? WHERE dlq_id = ? AND {tenant_sql}",
                (
                    attempt, retry_count, "dead" if dead else "queued", next_try_at,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), error_message, dlq_id,
                    *tenant_params,
                ),
            )
            conn.commit()
        return {"failed": True, "dlq_id": dlq_id, "attempt": attempt,
                "status": "dead" if dead else "queued"}

    def list_dlq(
        self, status_filter: Optional[str] = None, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """F014: DLQ-Read ist immer auf den aktiven Mandanten begrenzt."""
        tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
        with sqlite3.connect(_ensure_db(tenant_id), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            if status_filter:
                total = conn.execute(
                    f"SELECT COUNT(*) FROM dead_letter_queue WHERE status = ? AND {tenant_sql}",
                    (status_filter, *tenant_params),
                ).fetchone()[0]
                rows = conn.execute(
                    f"SELECT * FROM dead_letter_queue WHERE status = ? AND {tenant_sql} "
                    "ORDER BY created_at DESC LIMIT 50",
                    (status_filter, *tenant_params),
                ).fetchall()
            else:
                total = conn.execute(
                    f"SELECT COUNT(*) FROM dead_letter_queue WHERE {tenant_sql}", tenant_params
                ).fetchone()[0]
                rows = conn.execute(
                    f"SELECT * FROM dead_letter_queue WHERE {tenant_sql} "
                    "ORDER BY created_at DESC LIMIT 50", tenant_params,
                ).fetchall()
            items = [dict(r) for r in rows]
        return {"total": total, "items": items}


dead_letter_queue_manager = DeadLetterQueueManager()

# F014: fail-closed zur Laufzeit (kein stiller Fallback auf die globale DB).
_IMPORT_BOOTSTRAP = False
