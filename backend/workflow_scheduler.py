"""
backend/workflow_scheduler.py — Cron- & Watchdog-Workflow-Scheduler (M102b)

Verwaltet zeitgesteuerte (Cron mit Startzeitpunkt, Endzeitpunkt, Start-/Endbedingungen)
sowie Watchdog-getriggerte Workflow-Automationen in SQLite WAL (`data/workflow_schedules.db`).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_SCHEDULES_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "workflow_schedules.db")
SCHEDULES_DB_PATH = _DEFAULT_SCHEDULES_DB_PATH

logger = logging.getLogger("backend.workflow_scheduler")

# D07/F7: SSE-Broadcast-Fehler waren bisher `except Exception: pass` — der
# einzige Live-Stream-Effekt des Event-Bus verschwand ohne jede Spur. Zaehler
# + Telemetrie-Event liefern jetzt den §0-Verifikationsteil (Metrik + Test).
_EVENT_BUS_BROADCAST_FAILED = 0
_EVENT_BUS_BROADCAST_FAILED_LOCK = threading.Lock()


def event_bus_broadcast_failed_count() -> int:
    """Metrik `event_bus_broadcast_failed` — Anzahl fehlgeschlagener SSE-Broadcasts."""
    with _EVENT_BUS_BROADCAST_FAILED_LOCK:
        return _EVENT_BUS_BROADCAST_FAILED


def _record_event_bus_broadcast_failed(event_id: str, source: str, exc: BaseException) -> None:
    global _EVENT_BUS_BROADCAST_FAILED
    with _EVENT_BUS_BROADCAST_FAILED_LOCK:
        _EVENT_BUS_BROADCAST_FAILED += 1
    logger.warning(
        "[WorkflowScheduler] SSE-Event-Broadcast event_id=%s source=%s fehlgeschlagen: %s",
        event_id, source, exc,
    )
    try:
        _enqueue_telemetry("event_bus_broadcast_failed", {
            "event_id": event_id,
            "source": source,
            "detail": f"{type(exc).__name__}: {exc}"[:500],
        })
    except Exception as telemetry_exc:
        logger.error(
            "[WorkflowScheduler] Telemetrie event_bus_broadcast_failed fehlgeschlagen: %s",
            telemetry_exc,
        )


# ---------------------------------------------------------------------------
# W4-B / D06: zustandsbehafteter Event-Bus-Circuit-Breaker pro (source,target).
# Der vorherige "Circuit-Breaker" war nur ein gleitendes 1-Minuten-Fenster.
# Vorbild: backend/provider_circuit_breaker.py::ProviderCircuitBreaker.allow()
# inkl. verwaister Probe-Expiry (ein Probe, kein Thundering Herd).
# ---------------------------------------------------------------------------
_TRACE_EVENT_COLS = ("trace_id", "span_id", "traceparent", "tracestate")
_EVENT_BUS_CIRCUIT_THRESHOLD = max(
    1, int(os.environ.get("ARCHON_EVENT_BUS_CIRCUIT_THRESHOLD", "3") or 3)
)
_EVENT_BUS_CIRCUIT_COOLDOWN_SEC = max(
    1.0, float(os.environ.get("ARCHON_EVENT_BUS_CIRCUIT_COOLDOWN_SEC", "30") or 30)
)
_EVENT_BUS_CIRCUIT_OPEN_TOTAL: Dict[Tuple[str, str], int] = {}
_EVENT_BUS_CIRCUIT_BLOCKED_TOTAL: Dict[Tuple[str, str], int] = {}
_EVENT_BUS_CIRCUIT_LOCK = threading.Lock()


def event_bus_circuit_open_total() -> Dict[str, int]:
    """Metrik `event_bus_circuit_open_total{source,target}` als Zaehler-Map."""
    with _EVENT_BUS_CIRCUIT_LOCK:
        return {f"{src}|{tgt}": n for (src, tgt), n in _EVENT_BUS_CIRCUIT_OPEN_TOTAL.items()}


def event_bus_circuit_blocked_total() -> Dict[str, int]:
    """Anzahl der wegen OPEN/HALF_OPEN-Probe abgewiesenen Events."""
    with _EVENT_BUS_CIRCUIT_LOCK:
        return {f"{src}|{tgt}": n for (src, tgt), n in _EVENT_BUS_CIRCUIT_BLOCKED_TOTAL.items()}


class EventBusCircuitBreaker:
    """OPEN/HALF_OPEN/CLOSED pro (tenant, source, target), thread-safe.

    Drei aufeinanderfolgende `rate_limited`-Ereignisse oeffnen den Breaker fuer
    `cooldown` Sekunden. Danach darf genau EIN Probe durch; bleibt dieser
    Probe ohne record_success/record_rate_limited (verwaist), verfällt er nach
    einer Cooldown-Zeit und darf erneut gestartet werden.
    """

    def __init__(
        self, threshold: int = _EVENT_BUS_CIRCUIT_THRESHOLD,
        cooldown_seconds: float = _EVENT_BUS_CIRCUIT_COOLDOWN_SEC,
    ) -> None:
        self.threshold = max(1, int(threshold))
        self.cooldown = float(cooldown_seconds)
        self._state: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    @staticmethod
    def _key(source: str, target: str, tenant_id: str) -> Tuple[str, str, str]:
        return (str(tenant_id or "default"), str(source or "unknown"), str(target or "all"))

    def allow(self, source: str, target: str, tenant_id: str = "default") -> bool:
        key = self._key(source, target, tenant_id)
        with _EVENT_BUS_CIRCUIT_LOCK:
            st = self._state.get(key)
            if not st:
                return True
            open_until = float(st.get("open_until") or 0.0)
            if open_until <= 0:
                return True
            now = time.time()
            if now < open_until:
                _EVENT_BUS_CIRCUIT_BLOCKED_TOTAL[(key[1], key[2])] = (
                    _EVENT_BUS_CIRCUIT_BLOCKED_TOTAL.get((key[1], key[2]), 0) + 1
                )
                return False
            if st.get("probing"):
                probe_at = float(st.get("probe_at") or 0.0)
                if probe_at and (now - probe_at) > self.cooldown:
                    # verwaister Probe: kein record_success/record_failure
                    # erreicht (z. B. abgebrochener Task) -> erneut erlaubt.
                    st["probing"] = False
                    st["probe_at"] = 0.0
                else:
                    _EVENT_BUS_CIRCUIT_BLOCKED_TOTAL[(key[1], key[2])] = (
                        _EVENT_BUS_CIRCUIT_BLOCKED_TOTAL.get((key[1], key[2]), 0) + 1
                    )
                    return False
            st["probing"] = True
            st["probe_at"] = now
            return True

    def record_rate_limited(self, source: str, target: str, tenant_id: str = "default") -> None:
        key = self._key(source, target, tenant_id)
        with _EVENT_BUS_CIRCUIT_LOCK:
            st = self._state.setdefault(key, {
                "state": "CLOSED", "consecutive": 0, "open_until": 0.0,
                "probing": False, "probe_at": 0.0,
            })
            st["consecutive"] = int(st.get("consecutive") or 0) + 1
            st["probing"] = False
            st["probe_at"] = 0.0
            if st["consecutive"] >= self.threshold:
                st["state"] = "OPEN"
                st["open_until"] = time.time() + self.cooldown
                pair = (key[1], key[2])
                _EVENT_BUS_CIRCUIT_OPEN_TOTAL[pair] = (
                    _EVENT_BUS_CIRCUIT_OPEN_TOTAL.get(pair, 0) + 1
                )
                logger.warning(
                    "[EventBus] Circuit OPEN: source=%s target=%s tenant=%s "
                    "(%d aufeinanderfolgende rate_limited, cooldown=%.1fs)",
                    key[1], key[2], key[0], st["consecutive"], self.cooldown,
                )

    def record_success(self, source: str, target: str, tenant_id: str = "default") -> None:
        key = self._key(source, target, tenant_id)
        with _EVENT_BUS_CIRCUIT_LOCK:
            self._state[key] = {
                "state": "CLOSED", "consecutive": 0, "open_until": 0.0,
                "probing": False, "probe_at": 0.0,
            }

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with _EVENT_BUS_CIRCUIT_LOCK:
            return {"/".join(k): dict(v) for k, v in self._state.items()}


event_bus_breaker = EventBusCircuitBreaker()


@contextlib.contextmanager
def _workflow_event_trace(trace_columns: Optional[Dict[str, Any]] = None):
    """Outbound-Child-Span fuer den Event-Bus oder Wiederherstellung bei Handoff.

    W4-B/D16: ``dispatch_workflow_event`` erzeugt einen eigenen Child-Span;
    der Event-Mesh-Handoff uebergibt die persistierten Trace-Spalten, statt
    nur ``correlation_id`` zu reichen.
    """
    try:
        from backend import trace_context as tc
    except Exception as exc:
        logger.warning("[WorkflowScheduler] trace_context nicht verfügbar: %s", exc)
        yield {k: "" for k in _TRACE_EVENT_COLS}
        return
    explicit = {k: str((trace_columns or {}).get(k) or "") for k in _TRACE_EVENT_COLS}
    if any(explicit.values()):
        with tc.use_trace_context(
            trace_id=explicit["trace_id"], span_id=explicit["span_id"],
            traceparent=explicit["traceparent"], tracestate=explicit["tracestate"],
        ):
            yield explicit
        return
    with tc.child_span() as (trace_id, span_id, _parent_sid):
        yield {
            "trace_id": trace_id,
            "span_id": span_id,
            "traceparent": tc.format_traceparent(trace_id, span_id, tc.should_sample()),
            "tracestate": tc.sanitize_tracestate(tc.current_tracestate()),
        }


def _current_tenant_id() -> str:
    """F014: aktiver Mandant (Request-Kontext vor Corporate-Default)."""
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


def _tenant_sql(tenant_id: str, column: str = "tenant_id") -> tuple[str, tuple[str, str]]:
    """F014: tenant-scoped WHERE-Klausel (Legacy-Zeilen nur fuer Default)."""
    return (
        f"({column} = ? OR (COALESCE({column}, '') = '' AND ? = 'default'))",
        (str(tenant_id), str(tenant_id)),
    )


def _tenant_prefix(tenant_id: str, value: str) -> str:
    """Mandanten-Praefix fuer correlation_id / schedule-id (H-06-1)."""
    return f"{tenant_id}::{value}" if value else ""


def _resolve_schedules_db_path() -> str:
    if SCHEDULES_DB_PATH != _DEFAULT_SCHEDULES_DB_PATH:
        return SCHEDULES_DB_PATH
    try:
        from backend.db_paths import resolve_db
        return resolve_db("workflow_schedules.db")
    except Exception:
        return SCHEDULES_DB_PATH


def _get_conn() -> sqlite3.Connection:
    db_file = _resolve_schedules_db_path()
    os.makedirs(os.path.dirname(db_file) or ".", exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schedules_db() -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_schedules (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                trigger_type TEXT NOT NULL DEFAULT 'cron',
                cron_expr TEXT NOT NULL DEFAULT '',
                start_at TEXT DEFAULT '',
                end_at TEXT DEFAULT '',
                start_condition TEXT NOT NULL DEFAULT 'always',
                end_condition TEXT NOT NULL DEFAULT 'none',
                max_runs INTEGER DEFAULT NULL,
                run_count INTEGER NOT NULL DEFAULT 0,
                watchdog_keyword TEXT DEFAULT '',
                inputs_json TEXT NOT NULL DEFAULT '{}',
                n8n_webhook_url TEXT DEFAULT '',
                last_run_at TEXT DEFAULT '',
                next_run_at TEXT DEFAULT '',
                last_run_id TEXT DEFAULT '',
                last_status TEXT DEFAULT 'idle',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT '',
                trace_id TEXT DEFAULT '',
                span_id TEXT DEFAULT '',
                traceparent TEXT DEFAULT '',
                tracestate TEXT DEFAULT ''
            )
            """
        )
        # F014/H-06-1 + W4-B/D16: Bestands-DBs werden verlustfrei um
        # company_id/tenant_id und die vier Trace-Spalten erweitert
        # (CREATE IF NOT EXISTS aendert bestehende Tabellen nicht).
        for table in ("workflow_schedules", "workflow_events"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col in ("company_id", "tenant_id"):
                if cols and col not in cols:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                    )
            if table == "workflow_events":
                for col in _TRACE_EVENT_COLS:
                    if cols and col not in cols:
                        conn.execute(f"ALTER TABLE workflow_events ADD COLUMN {col} TEXT DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_events_tenant_corr "
            "ON workflow_events(tenant_id, source, correlation_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_schedules_tenant "
            "ON workflow_schedules(tenant_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _init_policies_table() -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_bus_policies (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                policy TEXT NOT NULL DEFAULT 'deny',
                max_per_min INTEGER NOT NULL DEFAULT 20,
                note TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _expand_cron_field(expr: str, min_v: int, max_v: int) -> Set[int]:
    out: Set[int] = set()
    for part in str(expr or "*").split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = max(1, int(step_str))
        else:
            base = part
        if base == "*":
            lo, hi = min_v, max_v
        elif "-" in base:
            a, b = base.split("-", 1)
            lo, hi = max(min_v, int(a)), min(max_v, int(b))
        else:
            val = int(base)
            lo, hi = val, val
        for v in range(lo, hi + 1, step):
            if min_v <= v <= max_v:
                out.add(v)
    return out or set(range(min_v, max_v + 1))


def parse_cron_next(cron_expr: str, after_dt: Optional[datetime] = None) -> Optional[str]:
    raw = (cron_expr or "").strip()
    if not raw:
        return None
    aliases = {
        "@every_5m": "*/5 * * * *",
        "@every_15m": "*/15 * * * *",
        "@hourly": "0 * * * *",
        "@daily": "0 8 * * *",
        "@weekly": "0 8 * * 1",
    }
    raw = aliases.get(raw.lower(), raw)
    parts = raw.split()
    if len(parts) != 5:
        return None
    try:
        mins = _expand_cron_field(parts[0], 0, 59)
        hours = _expand_cron_field(parts[1], 0, 23)
        doms = _expand_cron_field(parts[2], 1, 31)
        months = _expand_cron_field(parts[3], 1, 12)
        dows = _expand_cron_field(parts[4], 0, 6)
    except Exception:
        return None

    base = (after_dt or datetime.now(timezone.utc)).replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Maximal 366 Tage vorausschauen (527.040 Minuten, aber stunden-/tageweise springen)
    cur = base
    limit = base + timedelta(days=366)
    while cur <= limit:
        if cur.month not in months:
            cur = (cur.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1, hour=0, minute=0)
            continue
        # Python weekday: Mon=0..Sun=6 -> Cron: Sun=0..Sat=6
        cron_dow = (cur.weekday() + 1) % 7
        # Vixie-Cron-Standard fuer dom/dow: wenn BEIDE Felder beschraenkt sind
        # (keines ist '*'), wird ODER-verknuepft; wenn eines '*' ist, zaehlt
        # nur das andere Feld.
        #   '0 8 1 * 1'  -> 1. des Monats ODER jeder Montag um 08:00
        #   '0 8 * * 1'  -> nur jeder Montag um 08:00
        #   '0 8 1 * *'  -> nur am 1. des Monats um 08:00
        dom_is_star = len(doms) == 31
        dow_is_star = len(dows) == 7
        if dom_is_star and dow_is_star:
            day_match = True
        elif dom_is_star:
            day_match = cron_dow in dows
        elif dow_is_star:
            day_match = cur.day in doms
        else:
            day_match = (cur.day in doms) or (cron_dow in dows)
        if not day_match:
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cur.hour not in hours:
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        if cur.minute in mins:
            return cur.isoformat()
        cur += timedelta(minutes=1)
    return None


def _parse_iso(val: Optional[str]) -> Optional[datetime]:
    txt = (val or "").strip()
    if not txt:
        return None
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled"))
    try:
        d["inputs"] = json.loads(d.pop("inputs_json", "{}") or "{}")
    except Exception:
        d["inputs"] = {}
    return d


def list_schedules(
    template_id: Optional[str] = None, tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """F014: Schedule-Reads sind auf den aktiven Mandanten begrenzt."""
    init_schedules_db()
    tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
    conn = _get_conn()
    try:
        if template_id:
            rows = conn.execute(
                f"SELECT * FROM workflow_schedules WHERE template_id = ? AND {tenant_sql} "
                "ORDER BY created_at DESC",
                (template_id, *tenant_params),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM workflow_schedules WHERE {tenant_sql} ORDER BY created_at DESC",
                tenant_params,
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def upsert_schedule(payload: Dict[str, Any]) -> Dict[str, Any]:
    init_schedules_db()
    template_id = str(payload.get("template_id") or "").strip()
    if not template_id:
        raise ValueError("template_id_required")

    tenant_id = str(
        payload.get("tenant_id") or payload.get("company_id") or _current_tenant_id()
    )
    company_id = str(payload.get("company_id") or tenant_id)
    sid = str(payload.get("id") or f"sched-{uuid.uuid4().hex[:8]}").strip()
    # F014: PK bleibt id — nicht-default Mandanten erhalten einen praefigierten
    # id-Wert, damit gleiche IDs zweier Mandanten nicht kollidieren. Bestehende
    # Default-Schedules behalten ihre IDs unveraendert.
    if tenant_id not in ("", "default") and not sid.startswith(f"{tenant_id}::"):
        sid = _tenant_prefix(tenant_id, sid)
    trigger_type = str(payload.get("trigger_type") or "cron").strip()
    if trigger_type not in {"cron", "watchdog", "cron_and_watchdog", "inbox", "research", "boardroom", "calendar", "approval", "any_event"}:
        trigger_type = "cron"

    cron_expr = str(payload.get("cron_expr") or "").strip()
    start_at = str(payload.get("start_at") or "").strip()
    end_at = str(payload.get("end_at") or "").strip()
    start_condition = str(payload.get("start_condition") or "always").strip()
    end_condition = str(payload.get("end_condition") or "none").strip()
    max_runs_raw = payload.get("max_runs")
    max_runs = int(max_runs_raw) if max_runs_raw not in (None, "", 0, "0") else None
    enabled = 1 if payload.get("enabled", True) else 0
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}

    now = datetime.now(timezone.utc)
    start_dt = _parse_iso(start_at)
    anchor = start_dt if (start_dt and start_dt > now) else now
    next_run = parse_cron_next(cron_expr, anchor - timedelta(minutes=1)) if (enabled and cron_expr and "cron" in trigger_type) else ""

    conn = _get_conn()
    try:
        tenant_sql, tenant_params = _tenant_sql(tenant_id)
        existing = conn.execute(
            f"SELECT run_count, created_at FROM workflow_schedules WHERE id = ? AND {tenant_sql}",
            (sid, *tenant_params),
        ).fetchone()
        run_count = int(existing["run_count"]) if existing else 0
        created_at = existing["created_at"] if existing else now.isoformat()
        conn.execute(
            """
            INSERT INTO workflow_schedules (
                id, template_id, title, enabled, trigger_type, cron_expr,
                start_at, end_at, start_condition, end_condition, max_runs, run_count,
                watchdog_keyword, inputs_json, n8n_webhook_url, next_run_at, created_at,
                company_id, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                template_id=excluded.template_id,
                title=excluded.title,
                enabled=excluded.enabled,
                trigger_type=excluded.trigger_type,
                cron_expr=excluded.cron_expr,
                start_at=excluded.start_at,
                end_at=excluded.end_at,
                start_condition=excluded.start_condition,
                end_condition=excluded.end_condition,
                max_runs=excluded.max_runs,
                watchdog_keyword=excluded.watchdog_keyword,
                inputs_json=excluded.inputs_json,
                n8n_webhook_url=excluded.n8n_webhook_url,
                next_run_at=excluded.next_run_at
            """,
            (
                sid,
                template_id,
                str(payload.get("title") or template_id).strip(),
                enabled,
                trigger_type,
                cron_expr,
                start_at,
                end_at,
                start_condition,
                end_condition,
                max_runs,
                run_count,
                str(payload.get("watchdog_keyword") or "").strip(),
                json.dumps(inputs, ensure_ascii=False),
                str(payload.get("n8n_webhook_url") or "").strip(),
                next_run or "",
                created_at,
                company_id,
                tenant_id,
            ),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        row = conn.execute("SELECT * FROM workflow_schedules WHERE id = ?", (sid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_schedule(schedule_id: str, tenant_id: Optional[str] = None) -> bool:
    init_schedules_db()
    tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
    conn = _get_conn()
    try:
        cur = conn.execute(
            f"DELETE FROM workflow_schedules WHERE id = ? AND {tenant_sql}",
            (schedule_id, *tenant_params),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _has_open_workflow_run(template_id: str) -> bool:
    try:
        from backend.kanban_sidecar import load_kanban_meta
        from backend.operations_api import _get_active_kanban_db_path

        meta = load_kanban_meta().get("tasks", {})
        matching_tids = [tid for tid, tm in meta.items() if isinstance(tm, dict) and tm.get("workflow_tpl_id") == template_id]
        if not matching_tids:
            return False
        db_path = _get_active_kanban_db_path()
        if not os.path.exists(db_path):
            return False
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            placeholders = ",".join("?" for _ in matching_tids)
            row = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE id IN ({placeholders}) AND status IN ('todo', 'in_progress', 'backlog', 'ready')",
                matching_tids,
            ).fetchone()
            return bool(row and row[0] > 0)
        finally:
            conn.close()
    except Exception:
        return False


def _execute_schedule_row(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime, extra_inputs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    sched = _row_to_dict(row)
    sid = sched["id"]
    tpl_id = sched["template_id"]

    start_dt = _parse_iso(sched.get("start_at"))
    if start_dt and now < start_dt:
        return None

    end_dt = _parse_iso(sched.get("end_at"))
    if end_dt and now > end_dt:
        conn.execute("UPDATE workflow_schedules SET enabled = 0, last_status = 'expired' WHERE id = ?", (sid,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        return None

    if sched.get("end_condition") == "max_runs" and sched.get("max_runs") and sched["run_count"] >= int(sched["max_runs"]):
        conn.execute("UPDATE workflow_schedules SET enabled = 0, last_status = 'completed_max_runs' WHERE id = ?", (sid,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        return None

    if sched.get("start_condition") == "no_active_run" and _has_open_workflow_run(tpl_id):
        conn.execute("UPDATE workflow_schedules SET last_status = 'skipped_active_run' WHERE id = ?", (sid,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        return None

    merged_inputs = {**(sched.get("inputs") or {}), **(extra_inputs or {})}
    try:
        from backend.workflow_templates import launch_workflow_run

        res = launch_workflow_run(
            tpl_id=tpl_id,
            inputs=merged_inputs,
            cron_schedule=sched.get("cron_expr") or None,
            n8n_webhook_url=sched.get("n8n_webhook_url") or None,
        )
        new_count = sched["run_count"] + 1
        next_run = parse_cron_next(sched.get("cron_expr") or "", now) if ("cron" in sched["trigger_type"] and sched.get("cron_expr")) else ""
        should_disable = (
            sched.get("end_condition") == "max_runs"
            and sched.get("max_runs")
            and new_count >= int(sched["max_runs"])
        )
        conn.execute(
            """
            UPDATE workflow_schedules
            SET run_count = ?, last_run_at = ?, next_run_at = ?, last_run_id = ?, last_status = ?, enabled = ?
            WHERE id = ?
            """,
            (
                new_count,
                now.isoformat(),
                next_run or "",
                res.get("run_id", ""),
                "completed_max_runs" if should_disable else "triggered",
                0 if should_disable else 1,
                sid,
            ),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        return res
    except Exception as exc:
        disable_on_err = sched.get("end_condition") == "on_error_stop"
        conn.execute(
            "UPDATE workflow_schedules SET last_status = ?, enabled = ? WHERE id = ?",
            (f"error: {str(exc)[:120]}", 0 if disable_on_err else 1, sid),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()
        return None


_RETENTION_LAST_TS: Optional[datetime] = None
_RETENTION_INTERVAL_MIN = 30
_RETENTION_DAYS = 14
_RETENTION_MAX_ROWS = 5000
_CONTENT_FEEDBACK_LAST_TS: Optional[datetime] = None
_CONTENT_PUBLISH_LAST_TS: Optional[datetime] = None


def _run_content_publish_sweep(now: datetime) -> None:
    """P1: Alle 5 min faellige, HITL-freigegebene Assets automatisch publizieren.

    Vorher existierte publish_scheduled_due_assets() nur als manueller Endpoint —
    ein 'scheduled'-Asset blieb dauerhaft liegen, solange niemand den Button
    geklickt hat (harte Sackgasse der Content-Pipeline).
    """
    global _CONTENT_PUBLISH_LAST_TS
    if _CONTENT_PUBLISH_LAST_TS is not None and (now - _CONTENT_PUBLISH_LAST_TS) < timedelta(minutes=5):
        return
    _CONTENT_PUBLISH_LAST_TS = now
    try:
        from backend.content_machine import (
            get_default_publish_webhook_url,
            publish_scheduled_due_assets,
        )
        # Ohne Ziel-URL markierte der Sweep das Asset nur als 'published',
        # ohne es tatsaechlich auszuliefern. Die URL kommt zentral aus ENV
        # (ARCHON_CONTENT_PUBLISH_WEBHOOK) oder settings.json.
        res = publish_scheduled_due_assets(
            webhook_url=get_default_publish_webhook_url() or None
        )
        if res.get("errors"):
            logger.warning(
                "[WorkflowScheduler] Content-Publish-Sweep mit Fehlern: %s",
                res["errors"][:3],
            )
    except Exception as exc:
        logger.warning(f"[WorkflowScheduler] Content-Publish-Sweep fehlgeschlagen: {exc}")


def _run_content_feedback_sweep(now: datetime) -> None:
    """Alle 6h: 48h/7d-Performance-Rueckfluss der Content-Maschine in FTS5-Memory einspeisen."""
    global _CONTENT_FEEDBACK_LAST_TS
    if _CONTENT_FEEDBACK_LAST_TS is not None and (now - _CONTENT_FEEDBACK_LAST_TS) < timedelta(hours=6):
        return
    _CONTENT_FEEDBACK_LAST_TS = now
    try:
        from backend.content_machine import sweep_content_performance_feedback
        sweep_content_performance_feedback(hours_min=48)
    except Exception as exc:
        logger.debug(f"[WorkflowScheduler] Content-Feedback-Sweep uebersprungen: {exc}")


def _run_workflow_events_retention(conn: sqlite3.Connection, now: datetime) -> None:
    """Gedrosselt (alle 30 Min): alte Events loeschen + hartes Zeilenlimit."""
    global _RETENTION_LAST_TS
    if _RETENTION_LAST_TS is not None and (now - _RETENTION_LAST_TS) < timedelta(minutes=_RETENTION_INTERVAL_MIN):
        return
    _RETENTION_LAST_TS = now
    try:
        cutoff = (now - timedelta(days=_RETENTION_DAYS)).isoformat()
        deleted_old = conn.execute(
            "DELETE FROM workflow_events WHERE created_at < ?", (cutoff,)
        ).rowcount
        cnt = conn.execute("SELECT COUNT(*) FROM workflow_events").fetchone()[0]
        deleted_overflow = 0
        if cnt > _RETENTION_MAX_ROWS:
            deleted_overflow = conn.execute(
                "DELETE FROM workflow_events WHERE id NOT IN "
                "(SELECT id FROM workflow_events ORDER BY created_at DESC LIMIT ?)",
                (_RETENTION_MAX_ROWS,),
            ).rowcount
        conn.commit()
        if deleted_old or deleted_overflow:
            logger.info(f"[WorkflowScheduler] Retention: {deleted_old} alte + {deleted_overflow} ueberzaehlige Events geloescht")
    except Exception as exc:
        logger.warning(f"[WorkflowScheduler] Retention-Cleanup fehlgeschlagen (ignoriert): {exc}")
        try:
            conn.rollback()
        except Exception as _exc:
            logger.debug("[workflow_scheduler] Ignorierte Ausnahme (Z.571): %s", _exc)


# ---------------------------------------------------------------------------
# W4-B / D06: zentrale 14-Tage-Retention fuer alle Integrations-Tabellen.
# Der 30-s-Drainer raeumt mit (gedrosselt wie _run_workflow_events_retention).
# ---------------------------------------------------------------------------
_INTEGRATION_RETENTION_LAST_TS: Optional[datetime] = None
_INTEGRATION_RETENTION_INTERVAL_MIN = 30
_INTEGRATION_RETENTION_DELETED_TOTAL: Dict[str, int] = {}
_INTEGRATION_RETENTION_LOCK = threading.Lock()


def integration_retention_deleted_total() -> Dict[str, int]:
    """Metrik `integration_retention_deleted_total{table}`."""
    with _INTEGRATION_RETENTION_LOCK:
        return dict(_INTEGRATION_RETENTION_DELETED_TOTAL)


def purge_integration_retention(
    days: int = _RETENTION_DAYS,
    now: Optional[datetime] = None,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Loescht veraltete Integrations-Zeilen (nur abgeschlossene Zustaende).

    Betroffen: event_mesh_log, event_mesh_outbox (delivered/dead),
    event_mesh_dedup (first_seen), effect_ledger (resolved_at) und
    dead_letter_queue (completed). Offene Eintraege bleiben unberuehrt.
    """
    global _INTEGRATION_RETENTION_LAST_TS
    cur = now or datetime.now(timezone.utc)
    if (
        not force and _INTEGRATION_RETENTION_LAST_TS is not None
        and (cur - _INTEGRATION_RETENTION_LAST_TS) < timedelta(minutes=_INTEGRATION_RETENTION_INTERVAL_MIN)
    ):
        return {"status": "throttled", "deleted": {}}
    _INTEGRATION_RETENTION_LAST_TS = cur
    cutoff_dt = (cur - timedelta(days=max(1, int(days)))).replace(tzinfo=None)
    cutoff_iso = cutoff_dt.isoformat()
    cutoff_space = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    deleted: Dict[str, int] = {}
    errors: List[str] = []

    def _purge_db(db_path: str, specs) -> None:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            for table, column, extra_where, params in specs:
                sql = (
                    f"DELETE FROM {table} WHERE ({column} < ? OR {column} < ?)"
                    + (f" AND {extra_where}" if extra_where else "")
                )
                deleted[table] = int(conn.execute(sql, (cutoff_iso, cutoff_space, *params)).rowcount or 0)
            conn.commit()
        finally:
            conn.close()

    try:
        from backend import event_mesh as _em

        _purge_db(_em._db_path(), [
            ("event_mesh_log", "created_at", None, ()),
            ("event_mesh_outbox", "created_at", "status IN ('delivered', 'dead')", ()),
            ("event_mesh_dedup", "first_seen", None, ()),
            ("effect_ledger", "resolved_at", "resolved_at IS NOT NULL", ()),
        ])
    except Exception as exc:
        errors.append(f"event_mesh: {exc}")
        logger.warning("[WorkflowScheduler] Integrations-Retention (Ledger) fehlgeschlagen: %s", exc)
    try:
        from backend import dead_letter_queue as _dlq

        _purge_db(_dlq._db_path(), [
            ("dead_letter_queue", "created_at", "status = 'completed'", ()),
        ])
    except Exception as exc:
        errors.append(f"dead_letter_queue: {exc}")
        logger.warning("[WorkflowScheduler] Integrations-Retention (DLQ) fehlgeschlagen: %s", exc)

    with _INTEGRATION_RETENTION_LOCK:
        for table, count in deleted.items():
            if count:
                _INTEGRATION_RETENTION_DELETED_TOTAL[table] = (
                    _INTEGRATION_RETENTION_DELETED_TOTAL.get(table, 0) + count
                )
    if any(deleted.values()):
        logger.info("[WorkflowScheduler] Integrations-Retention (14 d) geloescht: %s", deleted)
    return {
        "status": "error" if errors else "ok",
        "deleted": deleted,
        "errors": errors,
        "cutoff": cutoff_iso,
    }


def _calendar_event_already_handled(
    conn: sqlite3.Connection, corr_id: str, today_start_iso: str,
    tenant_id: Optional[str] = None,
) -> bool:
    """True, wenn fuer (source='calendar', correlation_id, tenant) HEUTE bereits
    ein Event existiert (jeder Status zaehlt als 'schon behandelt')."""
    tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
    row = conn.execute(
        f"SELECT 1 FROM workflow_events WHERE source = 'calendar' AND correlation_id = ? "
        f"AND created_at >= ? AND {tenant_sql} LIMIT 1",
        (corr_id, today_start_iso, *tenant_params),
    ).fetchone()
    return bool(row)


def evaluate_due_schedules(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    init_schedules_db()
    cur_now = now or datetime.now(timezone.utc)
    _run_content_publish_sweep(cur_now)
    _run_content_feedback_sweep(cur_now)
    triggered: List[Dict[str, Any]] = []
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_schedules WHERE enabled = 1 AND trigger_type IN ('cron', 'cron_and_watchdog')"
        ).fetchall()
        for row in rows:
            next_dt = _parse_iso(row["next_run_at"])
            if not next_dt:
                computed = parse_cron_next(row["cron_expr"] or "", cur_now - timedelta(minutes=1))
                if computed:
                    conn.execute("UPDATE workflow_schedules SET next_run_at = ? WHERE id = ?", (computed, row["id"]))
                    conn.commit()
                    next_dt = _parse_iso(computed)
            if next_dt and cur_now >= next_dt:
                # Atomarer Claim (CAS): nur der Tick/Prozess, der next_run_at
                # genau vom gelesenen Wert fortschreibt, führt den Schedule aus.
                # Ohne CAS triggern zwei Ticks oder ein Manual-Endpoint denselben
                # Schedule mehrfach (doppelte Webhooks/LLM-Kosten).
                old_next = str(row["next_run_at"] or "")
                new_next = parse_cron_next(row["cron_expr"] or "", cur_now) or (
                    cur_now + timedelta(days=365)
                ).isoformat()
                claim = conn.execute(
                    "UPDATE workflow_schedules SET next_run_at = ?, last_status = 'claiming' "
                    "WHERE id = ? AND next_run_at = ?",
                    (new_next, row["id"], old_next),
                )
                conn.commit()
                if int(claim.rowcount or 0) != 1:
                    logger.debug(f"[WorkflowScheduler] Schedule '{row['id']}' wurde bereits von einem anderen Tick geclaimt.")
                    continue
                res = _execute_schedule_row(conn, row, cur_now)
                if res:
                    triggered.append(res)

        cal_subs = conn.execute(
            "SELECT COUNT(*) FROM workflow_schedules WHERE enabled = 1 AND trigger_type IN ('calendar', 'any_event')"
        ).fetchone()
        if cal_subs and cal_subs[0] > 0:
            try:
                _run_workflow_events_retention(conn, cur_now)
                from backend.operations_calendar import operations_calendar

                today_str = cur_now.date().isoformat()
                today_start_iso = datetime(cur_now.year, cur_now.month, cur_now.day, tzinfo=timezone.utc).isoformat()
                cal_events = operations_calendar.list_events(start_date=today_str, end_date=today_str)
                cal_tenant = _current_tenant_id()
                for cev in cal_events:
                    cid = _tenant_prefix(cal_tenant, f"cal-{cev.get('id', '')}-{today_str}")
                    if _calendar_event_already_handled(conn, cid, today_start_iso, tenant_id=cal_tenant):
                        continue  # Heute schon behandelt -> kein weiteres DB-Write (auch kein skipped_loop-Event)
                    ev_res = dispatch_workflow_event(
                        source="calendar",
                        event_type="due",
                        title=str(cev.get("title") or "Kalender-Termin"),
                        summary=f"Quelle: {cev.get('source', '')} | Kategorie: {cev.get('category', '')}",
                        payload={"date": cev.get("date"), "time": cev.get("time", ""), "category": cev.get("category", "")},
                        correlation_id=cid,
                        tenant_id=cal_tenant,
                    )
                    triggered.extend(ev_res.get("triggered") or [])
            except Exception as exc:
                logger.warning(f"[WorkflowScheduler] WARNUNG evaluate_due_schedules: Kalender-Event-Abruf fehlgeschlagen (Fallback: uebersprungen): {exc}")
        return triggered
    finally:
        conn.close()


def _create_hitl_decision(
    event_id: str,
    src: str,
    event_type: str,
    title: str,
    summary: str,
    corr: str,
    target_dom: str,
) -> None:
    """Pragmatisch: legt fuer ein require_hitl-Event eine Freigabe-Decision an.
    Misslingt das, bleibt es trotzdem beim Status 'awaiting_hitl' protokolliert."""
    try:
        from archon.routers.decisions import create_decision

        res = create_decision(
            typ="mission_freigabe",
            titel=f"HITL-Freigabe: {title or event_type}"[:180],
            kurzfassung=(summary or f"Event-Bus require_hitl: {src}/{event_type} (Ziel-Domain: {target_dom})")[:600],
            ref_id=event_id,
            extra={"event_bus": {"event_id": event_id, "source": src, "event_type": event_type, "correlation_id": corr, "target_domain": target_dom}},
            # A6/D04: Vier-Augen-Fail-Closed verlangt einen zuordenbaren Ersteller.
            # Dieser Hintergrund-Workflow hat keine interaktive Session; der
            # dokumentierte Service-Principal ist der verantwortliche Produzent.
            created_by="workflow-scheduler-service",
        )
        if res:
            logger.info(f"[WorkflowScheduler] HITL-Decision angelegt fuer Event {event_id} ({src}/{event_type})")
        else:
            logger.warning(f"[WorkflowScheduler] HITL-Decision fuer Event {event_id} lieferte kein Ergebnis (Status bleibt 'awaiting_hitl')")
    except Exception as exc:
        logger.warning(f"[WorkflowScheduler] HITL-Decision fuer Event {event_id} fehlgeschlagen: {exc}")


def _enqueue_telemetry(event_type: str, payload: Dict[str, Any]) -> None:
    """Optionaler Hook in den Async-Write-Batcher (Finding 8).

    Der Batcher hatte keinen einzigen Produzenten. Alle hier erzeugten
    Telemetrie-Events fliessen jetzt tatsaechlich in den Batcher (und von dort
    gebuendelt in `batched_telemetry_events`). Ein Batcher-Ausfall darf nie den
    Workflow-Dispatch selbst blockieren.
    """
    try:
        from backend.async_write_batcher import async_write_batcher
        async_write_batcher.enqueue(event_type, "backend.workflow_scheduler", payload)
    except Exception as exc:
        logger.debug("[WorkflowScheduler] Telemetrie-Hook nicht verfuegbar: %s", exc)


def dispatch_workflow_event(
    source: str,
    event_type: str,
    title: str = "",
    summary: str = "",
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    bypass_hitl: bool = False,
    tenant_id: Optional[str] = None,
    trace_columns: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Oeffentlicher Einstieg: Outbound-Child-Span + Trace-Kontext (W4-B/D16)."""
    init_schedules_db()
    _init_policies_table()
    with _workflow_event_trace(trace_columns) as trace_cols:
        return _dispatch_workflow_event_impl(
            source=source, event_type=event_type, title=title, summary=summary,
            payload=payload, correlation_id=correlation_id, bypass_hitl=bypass_hitl,
            tenant_id=tenant_id, trace_columns=trace_cols,
        )


def _dispatch_workflow_event_impl(
    source: str,
    event_type: str,
    title: str = "",
    summary: str = "",
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    bypass_hitl: bool = False,
    tenant_id: Optional[str] = None,
    trace_columns: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Zentraler Event-Bus für Watchdog, Posteingang, Research Lab und AI Boardroom.

    F014: Dedup/Rate-Limit/Correlation sind pro Mandant — zwei Mandanten mit
    identischem correlation_id unterdruecken sich nicht gegenseitig.
    W4-B: Circuit-Breaker pro (source,target) und Trace-Spalten an allen
    workflow_events-Zeilen.
    """
    init_schedules_db()
    _init_policies_table()
    now = datetime.now(timezone.utc)
    event_id = f"evt-{uuid.uuid4().hex[:10]}"
    src = str(source or "manual").strip().lower()
    tid = str(tenant_id or _current_tenant_id())
    company_id = str((payload or {}).get("company_id") or (payload or {}).get("tenant_id") or tid) if isinstance(payload, dict) else tid
    tenant_sql, tenant_params = _tenant_sql(tid)
    corr = str(correlation_id or "").strip()
    if corr and not corr.startswith(f"{tid}::"):
        corr = _tenant_prefix(tid, corr)
    payload_dict = payload if isinstance(payload, dict) else {}
    trace_cols = {k: str((trace_columns or {}).get(k) or "") for k in _TRACE_EVENT_COLS}

    source_triggers = {
        "watchdog": ("watchdog", "cron_and_watchdog", "any_event"),
        "inbox": ("inbox", "any_event"),
        "research": ("research", "any_event"),
        "boardroom": ("boardroom", "any_event"),
        "calendar": ("calendar", "any_event"),
        "approval": ("approval", "any_event"),
    }.get(src, ("any_event",))

    conn = _get_conn()
    try:
        if corr:
            dup = conn.execute(
                f"SELECT id FROM workflow_events WHERE correlation_id = ? AND source = ? "
                f"AND {tenant_sql} LIMIT 1",
                (corr, src, *tenant_params),
            ).fetchone()
            if dup:
                conn.execute(
                    """
                    INSERT INTO workflow_events
                    (id, source, event_type, title, summary, payload_json, correlation_id, status,
                     created_at, company_id, tenant_id, trace_id, span_id, traceparent, tracestate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'skipped_loop', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, src, event_type, title, summary, json.dumps(payload_dict, ensure_ascii=False),
                     corr, now.isoformat(), company_id, tid,
                     trace_cols["trace_id"], trace_cols["span_id"],
                     trace_cols["traceparent"], trace_cols["tracestate"]),
                )
                conn.commit()
                return {"event_id": event_id, "status": "skipped_loop", "triggered": []}

        # W4-B: Policy-Konfiguration + zustandsbehafteter Breaker pro
        # (source,target). Bei OPEN/HALF_OPEN-Probe wird sofort (ohne
        # Event-Scan, ohne Trigger) abgeblockt und protokolliert.
        pol_rows = conn.execute("SELECT * FROM event_bus_policies WHERE source = ?", (src,)).fetchall()
        pol_map = {r["target"]: dict(r) for r in pol_rows}
        targets = [str(t) for t in pol_map if t != "all"] or list(EVENT_BUS_TARGETS)
        open_targets = [t for t in targets if not event_bus_breaker.allow(src, t, tid)]
        if open_targets:
            circuit_payload = dict(payload_dict)
            circuit_payload["circuit_open_targets"] = open_targets
            conn.execute(
                """
                INSERT INTO workflow_events
                (id, source, event_type, title, summary, payload_json, correlation_id, status,
                 created_at, company_id, tenant_id, trace_id, span_id, traceparent, tracestate)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'circuit_open', ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, src, event_type, title, summary,
                 json.dumps(circuit_payload, ensure_ascii=False), corr, now.isoformat(),
                 company_id, tid, trace_cols["trace_id"], trace_cols["span_id"],
                 trace_cols["traceparent"], trace_cols["tracestate"]),
            )
            conn.commit()
            return {
                "event_id": event_id, "status": "circuit_open", "triggered": [],
                "circuit_target": open_targets[0],
            }

        # Skipping-Status-Namen ('skipped_loop','rate_limited','deduped')
        # zaehlen NICHT als Traffic, sonst loest der Breaker sich selbst aus.
        one_min_ago = (now - timedelta(minutes=1)).isoformat()
        recent_cnt = conn.execute(
            "SELECT COUNT(*) FROM workflow_events WHERE source = ? AND created_at >= ? "
            f"AND status NOT IN ('skipped_loop', 'rate_limited', 'deduped', 'circuit_open') "
            f"AND {tenant_sql}",
            (src, one_min_ago, *tenant_params),
        ).fetchone()[0]
        all_rule = pol_map.get("all")
        max_pm = int(all_rule["max_per_min"] or 20) if all_rule else max([int(r["max_per_min"] or 20) for r in pol_rows] or [20])
        if recent_cnt >= max_pm:
            for target in targets:
                event_bus_breaker.record_rate_limited(src, target, tid)
            conn.execute(
                """
                INSERT INTO workflow_events
                (id, source, event_type, title, summary, payload_json, correlation_id, status,
                 created_at, company_id, tenant_id, trace_id, span_id, traceparent, tracestate)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'rate_limited', ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, src, event_type, title, summary, json.dumps(payload_dict, ensure_ascii=False),
                 corr, now.isoformat(), company_id, tid,
                 trace_cols["trace_id"], trace_cols["span_id"],
                 trace_cols["traceparent"], trace_cols["tracestate"]),
            )
            conn.commit()
            return {"event_id": event_id, "status": "rate_limited", "triggered": []}
        # Erfolgreich am Breaker vorbei: CLOSED (auch ein HALF_OPEN-Probe).
        for target in targets:
            event_bus_breaker.record_success(src, target, tid)

        placeholders = ",".join("?" for _ in source_triggers)
        rows = conn.execute(
            f"SELECT * FROM workflow_schedules WHERE enabled = 1 "
            f"AND trigger_type IN ({placeholders}) AND {tenant_sql}",
            (*source_triggers, *tenant_params),
        ).fetchall()

        haystack = f"{title} {summary} {json.dumps(payload_dict, ensure_ascii=False)}".lower()
        matched_ids: List[str] = []
        triggered_runs: List[Dict[str, Any]] = []
        blocked_by_policy = False
        awaiting_hitl = False

        for row in rows:
            kw_raw = (row["watchdog_keyword"] or "").strip()
            keywords = [k.strip().lower() for k in kw_raw.split(",") if k.strip()]
            if keywords and not any(k in haystack for k in keywords):
                continue
            target_dom = _infer_target_domain(row["template_id"])
            rule = pol_map.get(target_dom) or pol_map.get("all") or _default_policy_for(src, target_dom)
            if rule["policy"] == "deny":
                blocked_by_policy = True
                continue
            if not bypass_hitl and rule["policy"] == "require_hitl":
                # HITL-Policy: Event laeuft NICHT ungebremselt in Runs —
                # stattdessen wird es als 'awaiting_hitl' protokolliert und
                # pragmatisch eine Freigabe-Decision angelegt.
                awaiting_hitl = True
                _create_hitl_decision(event_id, src, event_type, title, summary, corr, target_dom)
                continue
            matched_ids.append(row["id"])
            extra = {
                "topic": str(title or event_type),
                "event_source": src,
                "event_type": event_type,
                "event_summary": str(summary or "")[:800],
                "policy_mode": rule["policy"],
            }
            for k, v in payload_dict.items():
                if isinstance(v, (str, int, float)):
                    extra[f"event_{k}"] = v
            # W4-B/D16: Trace-Kontext an den Workflow-Run weitergeben
            # (Outbound-Child), nicht nur correlation_id.
            for k in _TRACE_EVENT_COLS:
                if trace_cols.get(k):
                    extra[f"event_{k}"] = trace_cols[k]
            res = _execute_schedule_row(conn, row, now, extra_inputs=extra)
            if res:
                triggered_runs.append(res)

        status = "triggered" if triggered_runs else (
            "blocked_policy" if blocked_by_policy
            else ("awaiting_hitl" if awaiting_hitl
                  else ("matched_skipped" if matched_ids else "no_match"))
        )
        conn.execute(
            """
            INSERT INTO workflow_events (
                id, source, event_type, title, summary, payload_json, correlation_id,
                matched_schedule_ids_json, triggered_run_ids_json, status, created_at,
                company_id, tenant_id, trace_id, span_id, traceparent, tracestate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                src,
                str(event_type or "event"),
                str(title or "")[:300],
                str(summary or "")[:1000],
                json.dumps(payload_dict, ensure_ascii=False),
                corr,
                json.dumps(matched_ids),
                json.dumps([r.get("run_id") for r in triggered_runs if r.get("run_id")]),
                status,
                now.isoformat(),
                company_id,
                tid,
                trace_cols["trace_id"],
                trace_cols["span_id"],
                trace_cols["traceparent"],
                trace_cols["tracestate"],
            ),
        )
        conn.commit()
        try:
            from archon.core.runtime import broadcast_event
            broadcast_event("event_bus", {
                "event_id": event_id,
                "source": src,
                "event_type": str(event_type or "event"),
                "title": str(title or "")[:200],
                "status": status,
                "triggered": [r.get("run_id") for r in triggered_runs if r.get("run_id")],
            })
        except Exception as exc:
            _record_event_bus_broadcast_failed(event_id, src, exc)
        _enqueue_telemetry("workflow_event", {
            "event_id": event_id,
            "source": src,
            "event_type": str(event_type or "event"),
            "status": status,
            "tenant_id": tid,
            "triggered": [r.get("run_id") for r in triggered_runs if r.get("run_id")],
        })
        return {"event_id": event_id, "status": status, "triggered": triggered_runs}
    finally:
        conn.close()


def list_workflow_events(
    limit: int = 100, source: Optional[str] = None, tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """F014: Event-Bus-Reads sind auf den aktiven Mandanten begrenzt."""
    init_schedules_db()
    tenant_sql, tenant_params = _tenant_sql(str(tenant_id or _current_tenant_id()))
    conn = _get_conn()
    try:
        if source and source != "all":
            rows = conn.execute(
                f"SELECT * FROM workflow_events WHERE source = ? AND {tenant_sql} "
                "ORDER BY created_at DESC LIMIT ?",
                (source, *tenant_params, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM workflow_events WHERE {tenant_sql} ORDER BY created_at DESC LIMIT ?",
                (*tenant_params, int(limit)),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for jf in ("payload_json", "matched_schedule_ids_json", "triggered_run_ids_json"):
                try:
                    d[jf.replace("_json", "")] = json.loads(d.pop(jf, "null") or "null")
                except Exception:
                    d[jf.replace("_json", "")] = None
            out.append(d)
        return out
    finally:
        conn.close()


def dispatch_watchdog_triggers(
    findings: List[Dict[str, Any]], tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not findings:
        return []
    triggered: List[Dict[str, Any]] = []
    tid = str(tenant_id or _current_tenant_id())
    for f in findings:
        ev_res = dispatch_workflow_event(
            source="watchdog",
            event_type="finding",
            title=f"{f.get('title', 'Watchdog-Fund')} ({f.get('link', '')})".strip(),
            summary=f.get("summary", ""),
            payload={"category": f.get("category", ""), "link": f.get("link", "")},
            correlation_id=str(f.get("id") or f.get("link") or ""),
            tenant_id=tid,
        )
        triggered.extend(ev_res.get("triggered") or [])
    return triggered


EVENT_BUS_SOURCES = ["watchdog", "inbox", "calendar", "research", "boardroom", "approval", "manual"]
EVENT_BUS_TARGETS = ["workflow", "treasury", "comms", "system"]


def _infer_target_domain(template_id: str) -> str:
    low = (template_id or "").lower()
    if any(k in low for k in ("invoice", "cost", "dunning", "pay", "dropshipping_order", "tax", "treasury")):
        return "treasury"
    if any(k in low for k in ("email", "outreach", "newsletter", "social", "influencer", "followup")):
        return "comms"
    if any(k in low for k in ("code_review", "compliance", "release", "security")):
        return "system"
    return "workflow"


def _default_policy_for(source: str, target: str) -> Dict[str, Any]:
    if source == "watchdog" and target in ("treasury", "system"):
        return {"source": source, "target": target, "policy": "deny", "max_per_min": 20, "note": "Standard-Schutz: Watchdog darf keine Finanzen/Systeme triggern"}
    if source in ("inbox", "calendar") and target == "treasury":
        return {"source": source, "target": target, "policy": "require_hitl", "max_per_min": 20, "note": "Standard-Schutz: Zahlungen erfordern HITL-Freigabe"}
    # H1 (Audit 23.11.2026): echte Default-Deny-Policy. Same-Domain-Events
    # bleiben erlaubt (kein Rechte-Uebergang), alle domänenuebergreifenden
    # Kombinationen brauchen eine explizite Freigabe via upsert_event_policy.
    if source == target:
        return {"source": source, "target": target, "policy": "allow", "max_per_min": 20, "note": "Same-Domain erlaubt (kein Rechte-Uebergang)"}
    return {"source": source, "target": target, "policy": "deny", "max_per_min": 20, "note": "Default-Deny: explizite Freigabe erforderlich"}


def list_event_policies() -> List[Dict[str, Any]]:
    init_schedules_db()
    _init_policies_table()
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM event_bus_policies").fetchall()
        saved = {(r["source"], r["target"]): dict(r) for r in rows}
        out: List[Dict[str, Any]] = []
        for src in EVENT_BUS_SOURCES:
            for tgt in EVENT_BUS_TARGETS:
                out.append(saved.get((src, tgt)) or _default_policy_for(src, tgt))
        return out
    finally:
        conn.close()


def upsert_event_policy(source: str, target: str, policy: str, max_per_min: int = 20, note: str = "") -> Dict[str, Any]:
    init_schedules_db()
    _init_policies_table()
    src = str(source or "").strip().lower()
    tgt = str(target or "").strip().lower()
    # H1: unbekannte/fehlerhafte Werte duerfen nie still zu "allow" werden.
    pol = str(policy or "deny").strip().lower()
    if pol not in {"allow", "require_hitl", "deny"}:
        pol = "deny"
    pid = f"{src}__{tgt}"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO event_bus_policies (id, source, target, policy, max_per_min, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                policy=excluded.policy,
                max_per_min=excluded.max_per_min,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (pid, src, tgt, pol, max(1, int(max_per_min or 20)), str(note or "").strip(), now_iso),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM event_bus_policies WHERE id = ?", (pid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def replay_workflow_event(
    event_id: str, bypass_hitl: bool = False, tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    init_schedules_db()
    tid = str(tenant_id or _current_tenant_id())
    tenant_sql, tenant_params = _tenant_sql(tid)
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT * FROM workflow_events WHERE id = ? AND {tenant_sql}",
            (event_id, *tenant_params),
        ).fetchone()
        if not row:
            raise KeyError("event_not_found")
        payload = json.loads(row["payload_json"] or "{}")
        replay_tenant = str(row["tenant_id"] or tid)
        if bypass_hitl and row["status"] == "awaiting_hitl":
            conn.execute(
                f"UPDATE workflow_events SET status = 'hitl_approved' WHERE id = ? AND {tenant_sql}",
                (event_id, *tenant_params),
            )
            conn.commit()
    finally:
        conn.close()
    return dispatch_workflow_event(
        source=row["source"],
        event_type=f"{row['event_type']}_replay",
        title=row["title"],
        summary=row["summary"],
        payload=payload,
        correlation_id=None,
        bypass_hitl=bypass_hitl,
        tenant_id=replay_tenant,
    )


def approve_and_replay_hitl_event(
    event_id: str, tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Gibt ein per require_hitl pausiertes Event frei und startet die passenden Workflows."""
    return replay_workflow_event(event_id, bypass_hitl=True, tenant_id=tenant_id)


async def workflow_scheduler_background_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            await asyncio.to_thread(evaluate_due_schedules)
        except Exception as exc:
            logger.error(f"[WorkflowScheduler] Loop-Fehler: {exc}")
        # Outbox-Retry: fehlgeschlagene Webhooks werden im Hintergrund
        # erneut zugestellt (mit Idempotency-Key, nach 5 Versuchen → DLQ).
        outbox: Dict[str, Any] = {}
        try:
            from backend.event_mesh import event_mesh
            outbox = await asyncio.to_thread(event_mesh.process_outbox)
            if outbox.get("processed") or outbox.get("dead"):
                logger.info(f"[WorkflowScheduler] Outbox: {outbox}")
        except Exception as exc:
            logger.warning(f"[WorkflowScheduler] Outbox-Retry fehlgeschlagen: {exc}")
        # Shared Queue: frueher gab es fuer die DLQ keinen produktiven
        # Consumer — fehlgeschlagene Delegationen blieben ewig 'queued'.
        dlq_result: Dict[str, Any] = {}
        try:
            dlq_result = await _drain_shared_queue()
        except Exception as exc:
            logger.warning(f"[WorkflowScheduler] DLQ-Drain fehlgeschlagen: {exc}")
            dlq_result = {"error": str(exc)[:300]}
        # W4-B: 14-Tage-Retention der Integrations-Tabellen (intern gedrosselt).
        retention: Dict[str, Any] = {}
        try:
            retention = await asyncio.to_thread(purge_integration_retention)
        except Exception as exc:
            logger.warning(f"[WorkflowScheduler] Integrations-Retention fehlgeschlagen: {exc}")
        _enqueue_telemetry("scheduler_cycle", {
            "outbox_processed": outbox.get("processed", 0),
            "outbox_dead": outbox.get("dead", 0),
            "dlq_handled": dlq_result.get("handled", 0),
            "dlq_failed": dlq_result.get("failed", 0),
            "dlq_unhandled": dlq_result.get("unhandled", 0),
            "integration_retention_deleted": sum((retention.get("deleted") or {}).values()),
        })
        await asyncio.sleep(30)


async def _handle_delegation_result(payload: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Echter Handler: re-dispatched eine fehlgeschlagene Delegation.

    Der DLQ-Eintrag enthaelt task_id/agent_id. Wir starten den Kanban-Task
    erneut (die gleiche Ausfuehrung, die die Delegation urspruenglich nutzta)
    und reaktivieren zusaetzlich den Watcher, damit das Ergebnis zurueck zur
    Sub-Session fliesst.
    """
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("delegation_result ohne task_id — kein Re-Dispatch moeglich.")

    from backend.operations_api import _execute_kanban_task_async, _get_kanban_connection
    conn = _get_kanban_connection()
    try:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    status = str(row[0]) if row else ""
    if not row:
        raise KeyError(f"Kanban-Task '{task_id}' nicht gefunden — Delegation nicht wiederholbar.")
    # Nicht in eine laufende/abgeschlossene Ausfuehrung greifen (idempotent).
    if status in ("in_progress", "done", "review"):
        return {"redispatched": False, "reason": f"task_status={status}", "task_id": task_id}

    await _execute_kanban_task_async(task_id)
    try:
        from archon.core.delegation import resume_pending_delegation_watchers
        await resume_pending_delegation_watchers()
    except Exception as exc:
        logger.debug("[WorkflowScheduler] Delegations-Watcher-Reaktivierung: %s", exc)
    return {"redispatched": True, "task_id": task_id, "agent_id": payload.get("agent_id")}


async def _handle_workflow_resume(payload: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Echter Handler fuer Startup-Recovery-Checkpoints: Workflow-Restart."""
    run_id = str(payload.get("run_id") or item.get("task_id") or "").strip()
    if not run_id:
        raise ValueError("workflow_resume ohne run_id.")
    from backend.workflow_dag_runner import resume_workflow_run
    result = await resume_workflow_run(run_id=run_id)
    return {"run_id": run_id, "status": result.get("status"), "resume_from_step": payload.get("resume_from_step")}


async def _handle_webhook_delivery(payload: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Echter Konsument fuer dead-Outbox-Einträge (Audit 23.11.2026).

    Der Producer (event_mesh.process_outbox) enqueut `webhook_delivery`; ohne
    Handler endete der Job in der DLQ dauerhaft dead, statt erneut zugestellt
    zu werden. Der vorhandene Replay-Executor wird wiederverwendet.
    """
    from backend.dead_letter_queue import _builtin_executor
    executor = _builtin_executor("webhook_delivery")
    if executor is None:
        raise RuntimeError("Kein Webhook-Replay-Executor registriert.")
    return await asyncio.to_thread(executor, payload, item)


_SHARED_QUEUE_HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "delegation_result": _handle_delegation_result,
    "workflow_resume": _handle_workflow_resume,
    "webhook_delivery": _handle_webhook_delivery,
}


async def _drain_shared_queue(max_jobs: int = 5) -> Dict[str, Any]:
    """Claimt und bearbeitet faellige DLQ-Jobs (CAS + Lease, echter Handler je job_type)."""
    from backend.dead_letter_queue import dead_letter_queue_manager as dlq

    handled = failed = unhandled = 0
    for _ in range(max_jobs):
        item = await asyncio.to_thread(dlq.claim_next, "workflow_scheduler", lease_seconds=120)
        if not item:
            break
        job_type = str(item.get("job_type") or "")
        payload = item.get("payload") or {}
        try:
            from archon.core.runtime import add_ticker, broadcast_event
            broadcast_event("delegation_failed", {
                "dlq_id": item.get("dlq_id"),
                "job_type": job_type,
                "payload": payload,
            })
            add_ticker(
                "Shared Queue",
                f"Job '{job_type}' aus {item.get('source_module') or 'unbekannt'} — "
                f"Task {payload.get('task_id', '?')}: {str(payload.get('status', ''))[:60]}",
            )

            handler = _SHARED_QUEUE_HANDLERS.get(job_type)
            if handler is None:
                # Kein Handler => KEIN complete(): der Job bleibt sichtbar und
                # wird nach Backoff erneut versucht bzw. nach max_retries dead.
                unhandled += 1
                await asyncio.to_thread(
                    dlq.fail, item["dlq_id"], f"unhandled_job_type:{job_type}"
                )
                logger.warning("[WorkflowScheduler] Kein Handler fuer DLQ-Job-Typ '%s' (dlq=%s).", job_type, item.get("dlq_id"))
                continue

            result = await handler(payload, item)
            await asyncio.to_thread(
                dlq.complete,
                item["dlq_id"],
                {"handled_by": "workflow_scheduler", "handler": job_type, "result": result},
            )
            handled += 1
        except Exception as exc:
            failed += 1
            logger.warning("[WorkflowScheduler] DLQ-Job %s fehlgeschlagen: %s", item.get("dlq_id"), exc)
            await asyncio.to_thread(dlq.fail, item["dlq_id"], str(exc)[:500])
    return {"handled": handled, "failed": failed, "unhandled": unhandled}
