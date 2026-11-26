# -*- coding: utf-8 -*-
"""
backend/trajectory_budget.py — D13: ticketweite Trajectory-Budget-Invariante.

Eine einzige, stabile `trajectory_id` ist der Schluessel fuer
Lesen/Schreiben/Resume der Delegationskette, Hop-, Token- und Replan-Caps.
SQLite ONLY (keine Postgres-Migration, kein Coroutine-Replay).

HANDOFF (Dateien gehoeren anderen Agenten — hier nur Vertrag, nicht geaendert):
  * archon/core/delegation.py         : MUSS MAX_DELEGATION_DEPTH aus diesem Modul
                                         konsumieren (W3-D Ownership-Grenze —
                                         siehe audit_reports/fix_w3_d_*.md).
  * backend/agent_router.py           : allow_repeat=True verbraucht jetzt das
                                         gezaehlte repeat_budget statt die
                                         Zyklus-Erkennung abzuschalten.
  * archon/routers/chat.py            : Fan-out-Cap 5 + task_id/token_budget beim
                                        Task-Anlegen (Agent H: operations_api.py).
  * core_dispatcher.py                : Boardroom-Fenster >= max_steps+1 und
                                        guard_fail_closed (stattdessen
                                        `guard_window_size()` aus diesem Modul).
  * backend/flightlog_backtester.py   : Produktion `record_flight_event` im
                                        Tool-Chokepoint (tool_runtime.py).
  * backend/operations_api.py         : 6-h-Zombie-Reset mit Lease-Pruefung
                                        (stattdessen `zombie_eligible()` nutzen).
  * archon/routers/boardroom.py       : slots max_length=8, slots*rounds <= 48.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("archon.trajectory_budget")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILENAME = "ops.db"

# D13/F032: EINZIGE SSOT fuer die maximale Delegationstiefe. Der alte Wert 5
# und der dag-seitige Expand-Pfad auf 50 sind ersatzlos entfallen. Caps werden
# nur verschaeft, nie erweitert.
MAX_DELEGATION_DEPTH = 3
# Rueckwaertskompatibler Alias: gleicher Wert, keine zweite Wahrheit.
DEFAULT_MAX_HOPS = MAX_DELEGATION_DEPTH
DEFAULT_MAX_TOKENS = 200_000
DEFAULT_MAX_REPLANS = 2
DEFAULT_MAX_DELEGATIONS_PER_RESPONSE = 5
RESERVATION_TTL_SECONDS = 7200

# D13/MED: gezaehlte Wiederholungen statt Präfix-Whitelist. Pro
# (trajectory_id, agent_id, reason_key) sind DEFAULT_REPEAT_BUDGET Reentries
# erlaubt; danach greift CYCLE_DETECTED hart zu.
DEFAULT_REPEAT_BUDGET = 3
REPEAT_REASON_PREFIXES = ("tool:", "retry:", "replan:", "repair:")
# Wiederholungs-Klassen, die einen gemeinsamen Zaehler teilen (retry:1, retry:2, ...).
_SHARED_REPEAT_KEYS = frozenset({"retry", "replan", "repair"})

# D13-H1: root-lose Dispatches duerfen niemals pro Aufruf eine neue ID erhalten.
# Die Reihenfolge der Korrelation ist: explizit gebundener Root (Router/Session)
# -> task_id/session_id des Aufrufers -> W3C-Trace des Requests -> stabiler
# Fail-closed-Sentinel. `time.time_ns()` kommt hier bewusst NICHT mehr vor.
UNROOTED_TRAJECTORY_SEED = "unrooted"
_TRAJECTORY_ROOT_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    "archon_trajectory_root", default=""
)

_WRITE_LOCK = threading.RLock()


def resolve_trajectory_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return os.path.abspath(db_path)
    try:
        from backend.db_paths import resolve_db
        return resolve_db(DB_FILENAME)
    except Exception:
        return os.path.join(WORKSPACE_DIR, "data", DB_FILENAME)


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = resolve_trajectory_db_path(db_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        init_trajectory_tables(conn)
        yield conn
    finally:
        conn.close()


def init_trajectory_tables(conn: sqlite3.Connection) -> None:
    """Idempotentes SQLite-Schema — CHECK-Constraints verhindern Cap-Unterlauf."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS trajectory_budgets (
            trajectory_id TEXT PRIMARY KEY,
            root_ticket_id TEXT NOT NULL,
            max_hops INTEGER NOT NULL DEFAULT {MAX_DELEGATION_DEPTH},
            hops_used INTEGER NOT NULL DEFAULT 0,
            max_tokens INTEGER NOT NULL DEFAULT 200000,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            max_replans INTEGER NOT NULL DEFAULT 2,
            replans_used INTEGER NOT NULL DEFAULT 0,
            visited_agents TEXT NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'active',
            last_reason TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            CHECK (hops_used >= 0 AND hops_used <= max_hops),
            CHECK (replans_used >= 0 AND replans_used <= max_replans),
            CHECK (tokens_used >= 0 AND tokens_used <= max_tokens),
            CHECK (state IN ('active','blocked','completed','failed','released'))
        )
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(trajectory_budgets)").fetchall()}
    if "replans_used" not in cols:
        conn.execute("ALTER TABLE trajectory_budgets ADD COLUMN replans_used INTEGER NOT NULL DEFAULT 0")
    if "last_reason" not in cols:
        conn.execute("ALTER TABLE trajectory_budgets ADD COLUMN last_reason TEXT NOT NULL DEFAULT ''")
    # D13-M3: Reservierung vs. tatsaechlicher Verbrauch werden getrennt
    # vorgehalten, damit eine Gegenbuchung den Schätzwert sauber ersetzt.
    if "reserved_tokens" not in cols:
        conn.execute("ALTER TABLE trajectory_budgets ADD COLUMN reserved_tokens INTEGER NOT NULL DEFAULT 0")
    if "actual_tokens" not in cols:
        conn.execute("ALTER TABLE trajectory_budgets ADD COLUMN actual_tokens INTEGER NOT NULL DEFAULT 0")
    # D13/MED: gezaehltes Repeat-Budget pro (trajectory_id, agent_id, reason_key).
    # Ersatz fuer die alte Präfix-Whitelist, die tool:/retry:/replan:/repair:
    # pauschal von der Zyklus-Erkennung ausgenommen hat.
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS trajectory_repeat_budget (
            trajectory_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            reason_key TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            limit_count INTEGER NOT NULL DEFAULT {DEFAULT_REPEAT_BUDGET},
            PRIMARY KEY (trajectory_id, agent_id, reason_key)
        )
    """)
    # D13-M3: einzelne Token-Reservierungen (Schätzung) mit TTL. Der
    # Zentral-Chokepoint reserviert vor dem Provider-Call und settet/released
    # danach ueber budget_bank -> finalize_tokens(); ohne Abschluss verfällt
    # die Reservierung nach RESERVATION_TTL_SECONDS.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trajectory_token_reservations (
            reservation_id TEXT PRIMARY KEY,
            trajectory_id TEXT NOT NULL,
            agent_id TEXT NOT NULL DEFAULT '',
            source_key TEXT NOT NULL DEFAULT '',
            tokens_estimated INTEGER NOT NULL DEFAULT 0,
            tokens_actual INTEGER NOT NULL DEFAULT -1,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            settled_at REAL,
            CHECK (tokens_estimated >= 0),
            CHECK (status IN ('pending','settled','released','expired'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trajectory_res_pending "
        "ON trajectory_token_reservations(trajectory_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trajectory_root ON trajectory_budgets(root_ticket_id)"
    )
    conn.commit()


def clamp_max_hops(value: Optional[int]) -> int:
    """D13/F032: SSOT-konformer Hop-Cap. 0/'ungueltig' heisst 'nicht angegeben'.

    Ein Werte > MAX_DELEGATION_DEPTH wird auf die SSOT heruntergezogen und
    niemals nach oben durchgereicht — das ist die einzige erlaubte
    'Erweiterungs'-Richtung: keine.
    """
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return max(1, min(MAX_DELEGATION_DEPTH, n))


def _repeat_reason_key(reason: str) -> str:
    """Stabile Gruppen-ID fuer das Repeat-Budget.

    retry:1/retry:2 teilen sich einen Topf (sonst liefe der Retry-Cap ins
    Leere); tool:<name> bleibt pro Tool getrennt; allow_repeat bei llm_call:<a>
    nutzt den vollen Grund als Key.
    """
    text = str(reason or "").strip() or "generic"
    head, sep, tail = text.partition(":")
    if head in _SHARED_REPEAT_KEYS:
        return head
    if head == "tool":
        return f"tool:{tail.strip() or '_unknown'}" if sep else "tool"
    return text


def _repeat_budget(conn: sqlite3.Connection, tid: str, aid: str, key: str) -> Tuple[int, int]:
    row = conn.execute(
        "SELECT used, limit_count FROM trajectory_repeat_budget "
        "WHERE trajectory_id = ? AND agent_id = ? AND reason_key = ?",
        (tid, aid, key),
    ).fetchone()
    if not row:
        return 0, DEFAULT_REPEAT_BUDGET
    return max(0, int(row["used"] or 0)), max(0, int(row["limit_count"] or 0))


def _consume_repeat_budget(
    conn: sqlite3.Connection, tid: str, aid: str, key: str, used: int
) -> None:
    conn.execute(
        "INSERT INTO trajectory_repeat_budget (trajectory_id, agent_id, reason_key, used, limit_count) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(trajectory_id, agent_id, reason_key) DO UPDATE SET used = excluded.used",
        (tid, aid, key, used, DEFAULT_REPEAT_BUDGET),
    )


def set_repeat_budget(
    trajectory_id: str,
    agent_id: str,
    reason: str,
    limit: int,
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Expliziter, persistierter Repeat-Cap pro (Trajectory, Agent, Reason)."""
    tid = normalize_trajectory_id(trajectory_id)
    aid = str(agent_id or "").strip()
    key = _repeat_reason_key(reason)
    cap = max(0, int(limit or 0))
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO trajectory_repeat_budget (trajectory_id, agent_id, reason_key, used, limit_count) "
            "VALUES (?, ?, ?, 0, ?) "
            "ON CONFLICT(trajectory_id, agent_id, reason_key) DO UPDATE SET limit_count = excluded.limit_count",
            (tid, aid, key, cap),
        )
        conn.commit()
    return {"trajectory_id": tid, "agent_id": aid, "reason_key": key, "limit": cap}


def repeat_budget_status(
    trajectory_id: str,
    agent_id: str,
    reason: str,
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    tid = normalize_trajectory_id(trajectory_id)
    aid = str(agent_id or "").strip()
    key = _repeat_reason_key(reason)
    with _connect(db_path) as conn:
        used, cap = _repeat_budget(conn, tid, aid, key)
    return {"trajectory_id": tid, "agent_id": aid, "reason_key": key,
            "used": used, "limit": cap, "remaining": max(0, cap - used)}


def token_reservation_source_key(agent_id: str, estimated_tokens: int) -> str:
    """Gemeinsamer Schluessel zwischen BudgetBank- und Trajectory-Reservierung."""
    return f"{str(agent_id or '').strip()}:{max(0, int(estimated_tokens or 0))}"


def current_trajectory_root() -> str:
    """Aktiv gebundener Trajectory-Root (Router/Session) oder W3C-Trace-ID."""
    explicit = str(_TRAJECTORY_ROOT_CTX.get() or "").strip()
    if explicit:
        return explicit
    try:
        from backend.trace_context import current_trace_id
        trace = str(current_trace_id() or "").strip()
        if trace:
            return f"trace:{trace}"
    except Exception:
        pass
    return ""


def trajectory_root(scope: str, *parts: str) -> str:
    """Deterministischer, PII-freier Root fuer eine Dispatch-Kette.

    Der Root wird z. B. aus Session-ID, Root-Ticket oder Correlation-ID gebildet;
    gleiche Eingabe liefert ueber Prozesse hinweg dieselbe Trajectory.
    """
    scope_text = str(scope or "dispatch").strip() or "dispatch"
    joined = "|".join([scope_text, *(str(p or "") for p in parts)])
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"{scope_text}:{digest}"


def bind_trajectory_root(root: str) -> str:
    """Root im aktuellen Kontext verankern (to_thread kopiert den Context)."""
    value = str(root or "").strip()
    _TRAJECTORY_ROOT_CTX.set(value)
    return value


@contextmanager
def trajectory_root_scope(root: str) -> Iterator[str]:
    """Bindet einen Root fuer die Dauer des Blocks und stellt ihn danach wieder her."""
    token = _TRAJECTORY_ROOT_CTX.set(str(root or "").strip())
    try:
        yield str(root or "").strip()
    finally:
        _TRAJECTORY_ROOT_CTX.reset(token)


def trajectory_root_source(
    trajectory_id: Optional[str] = None,
    root_ticket_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Herkunft der Korrelation — fuer die Metrik `dispatch_without_trajectory_root`."""
    if trajectory_id and str(trajectory_id).startswith("traj-"):
        return "explicit"
    if str(root_ticket_id or "").strip():
        return "task"
    if str(session_id or "").strip():
        return "session"
    try:
        from backend.trace_context import current_trace_id
        if str(current_trace_id() or "").strip() and not str(_TRAJECTORY_ROOT_CTX.get() or "").strip():
            return "trace"
    except Exception:
        pass
    if str(_TRAJECTORY_ROOT_CTX.get() or "").strip():
        return "context"
    return "unrooted"


def stable_trajectory_id(root_ticket_id: str) -> str:
    """Deterministisch aus dem Root — A->B->A bleibt dieselbe ID.

    D13-H1: ohne Root wird der aktive Korrelationskontext (gebundener Root oder
    Trace-ID) benutzt; fehlt auch dieser, greift ein stabiler Sentinel. Es
    entsteht NIE mehr eine `anonymous:<time_ns>`-ID pro Aufruf.
    """
    base = str(root_ticket_id or "").strip() or current_trajectory_root() or UNROOTED_TRAJECTORY_SEED
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"traj-{digest}"


def normalize_trajectory_id(
    trajectory_id: Optional[str] = None,
    root_ticket_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    if trajectory_id and str(trajectory_id).startswith("traj-"):
        return str(trajectory_id)
    seed = (
        str(root_ticket_id or "").strip()
        or str(session_id or "").strip()
        or current_trajectory_root()
        or UNROOTED_TRAJECTORY_SEED
    )
    return stable_trajectory_id(seed)


def _audit(trajectory_id: str, msg: str, task_id: str = "") -> None:
    logger.warning("[TrajectoryBudget] %s | trajectory=%s ticket=%s", msg, trajectory_id, task_id)
    try:
        from archon.core.mission_control import mc_append_audit_sqlite
        mc_append_audit_sqlite("trajectory_budget", msg, task_id or trajectory_id or "_system")
    except Exception as exc:
        # F024/§0: Audit-Schreibfehler nie verschlucken.
        logger.error("[TrajectoryBudget] Audit-Schreibfehler: %s", exc, exc_info=exc)
        try:
            from backend.trace_context import note_local_trace_error
            note_local_trace_error("Trajectory-Audit-Schreibfehler", exc)
        except Exception:
            pass
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("trajectory_budget_blocked", {
            "trajectory_id": trajectory_id, "task_id": task_id, "reason": msg,
        })
    except Exception as exc:
        logger.warning("[TrajectoryBudget] Broadcast trajectory_budget_blocked fehlgeschlagen: %s", exc)


def get_trajectory(trajectory_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (trajectory_id,)
        ).fetchone()
        return dict(row) if row else None


def ensure_trajectory(
    trajectory_id: Optional[str] = None,
    root_ticket_id: Optional[str] = None,
    *,
    max_hops: Optional[int] = None,
    max_tokens: Optional[int] = None,
    max_replans: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Einmalige Wurzel-Reservierung. Caps werden nur verschärft, nie erweitert."""
    tid = normalize_trajectory_id(trajectory_id, root_ticket_id)
    root = str(root_ticket_id or trajectory_id or tid)
    now = time.time()
    # F032: auch der INSERT darf die SSOT nicht umgehen (frueher wurde hier
    # ungeklemmt 50 aus den DAG-Metadaten geschrieben).
    requested_hops = clamp_max_hops(max_hops)
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO trajectory_budgets "
            "(trajectory_id, root_ticket_id, max_hops, hops_used, max_tokens, tokens_used, "
            " max_replans, replans_used, visited_agents, state, last_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, 0, ?, 0, '[]', 'active', '', ?, ?)",
            (
                tid, root,
                requested_hops or MAX_DELEGATION_DEPTH,
                max(1, int(max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS)),
                max(0, int(max_replans if max_replans is not None else DEFAULT_MAX_REPLANS)),
                now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        updates: Dict[str, Any] = {}
        if requested_hops:
            updates["max_hops"] = min(int(row["max_hops"]), requested_hops)
        if max_tokens is not None:
            updates["max_tokens"] = min(int(row["max_tokens"]), max(1, int(max_tokens)))
        if max_replans is not None:
            updates["max_replans"] = min(int(row["max_replans"]), max(0, int(max_replans)))
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            try:
                conn.execute(
                    f"UPDATE trajectory_budgets SET {sets}, updated_at = ? WHERE trajectory_id = ?",
                    (*updates.values(), now, tid),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                raise
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        return dict(row)


def _block(conn: sqlite3.Connection, tid: str, reason: str) -> Dict[str, Any]:
    conn.execute(
        "UPDATE trajectory_budgets SET state = 'blocked', last_reason = ?, updated_at = ? "
        "WHERE trajectory_id = ? AND state = 'active'",
        (reason[:300], time.time(), tid),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
    ).fetchone()
    return dict(row) if row else {}


def reserve_hop(
    trajectory_id: str,
    agent_id: str = "",
    reason: str = "agent_switch",
    *,
    root_ticket_id: Optional[str] = None,
    db_path: Optional[str] = None,
    allow_repeat: bool = False,
) -> Dict[str, Any]:
    """Vor JEDEM Agentwechsel/Tool-Call/Retry/Replan atomar aufrufen.

    D13/F032: Reentries werden NICHT mehr pauschal durch ein Präfix
    (`tool:`, `retry:`, `replan:`, `repair:`) oder `allow_repeat` von der
    Zyklus-Erkennung ausgenommen. Sie verbrauchen ein gezaehltes
    `repeat_budget` pro (trajectory_id, agent_id, reason_key); ist es
    aufgebraucht, greift CYCLE_DETECTED. Ein echter Agentwechsel-Zyklus
    (A -> B -> A) bleibt sofort hart blockiert.

    Fail-closed: unbekannte Trajectory wird mit SSOT-Caps angelegt, eine
    blockierte Trajectory lässt keinen weiteren Hop zu.
    """
    tid = normalize_trajectory_id(trajectory_id, root_ticket_id)
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO trajectory_budgets "
            "(trajectory_id, root_ticket_id, max_hops, max_tokens, max_replans, "
            " visited_agents, state, last_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '[]', 'active', '', ?, ?)",
            (tid, str(root_ticket_id or tid), MAX_DELEGATION_DEPTH, DEFAULT_MAX_TOKENS,
             DEFAULT_MAX_REPLANS, time.time(), time.time()),
        )
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        if str(row["state"]) != "active":
            conn.rollback()
            return {
                "allowed": False, "reason": f"TRAJECTORY_{str(row['state']).upper()}",
                "trajectory_id": tid, "hops_used": int(row["hops_used"]),
                "max_hops": int(row["max_hops"]),
            }
        visited: List[str] = []
        try:
            loaded = json.loads(row["visited_agents"] or "[]")
            if isinstance(loaded, list):
                visited = [str(x) for x in loaded if x]
        except Exception:
            visited = []
        aid = str(agent_id or "").strip()
        reason_text = str(reason or "")
        is_qualified_visit = bool(
            aid and any(v == aid or v.startswith(f"{aid}::") for v in visited)
        )
        repeat_class = allow_repeat or reason_text.startswith(REPEAT_REASON_PREFIXES)
        # Wiederholungen sind KEINE Delegation: sie werden ausschliesslich ueber
        # das repeat_budget gedeckelt und belasten nicht max_hops (die SSOT
        # MAX_DELEGATION_DEPTH=3 gilt fuer echte Agentwechsel).
        counted_repeat = False
        if is_qualified_visit:
            if not repeat_class:
                # Echter Delegationszyklus (z. B. agent_switch A->B->A).
                blocked = _block(conn, tid, f"CYCLE_DETECTED:{aid}")
                _audit(tid, f"CYCLE_DETECTED via {aid} ({reason_text})", str(root_ticket_id or ""))
                return {"allowed": False, "reason": "CYCLE_DETECTED", "agent_id": aid,
                        "trajectory_id": tid, "hops_used": int(blocked.get("hops_used", 0)),
                        "max_hops": int(blocked.get("max_hops", MAX_DELEGATION_DEPTH))}
            rkey = _repeat_reason_key(reason_text)
            used, cap = _repeat_budget(conn, tid, aid, rkey)
            if used >= cap:
                blocked = _block(conn, tid, f"CYCLE_DETECTED:{aid}:repeat_budget_exhausted")
                _audit(tid, f"CYCLE_DETECTED repeat_budget ({used}/{cap}) via {aid} ({reason_text})",
                       str(root_ticket_id or ""))
                return {"allowed": False, "reason": "CYCLE_DETECTED", "detail": "REPEAT_BUDGET_EXCEEDED",
                        "agent_id": aid, "reason_key": rkey, "repeat_used": used, "repeat_limit": cap,
                        "trajectory_id": tid, "hops_used": int(blocked.get("hops_used", 0)),
                        "max_hops": int(blocked.get("max_hops", MAX_DELEGATION_DEPTH))}
            _consume_repeat_budget(conn, tid, aid, rkey, used + 1)
            counted_repeat = True
        hops_used = int(row["hops_used"] or 0)
        max_hops = int(row["max_hops"])
        if hops_used >= max_hops:
            blocked = _block(conn, tid, "DEPTH_EXCEEDED")
            _audit(tid, f"DEPTH_EXCEEDED ({hops_used}/{max_hops}) via {reason_text}", str(root_ticket_id or ""))
            return {"allowed": False, "reason": "DEPTH_EXCEEDED", "trajectory_id": tid,
                    "hops_used": hops_used, "max_hops": max_hops}
        if aid:
            if aid not in visited:
                visited.append(aid)
            # D13/MED: Tool-Calls als (agent_id, tool_name) im visited-Set
            # fuehren, damit A -> tool_x -> A als Zyklus sichtbar bleibt.
            if reason_text.startswith("tool:"):
                tool_name = reason_text.split(":", 1)[1].strip() or "_unknown"
                marker = f"{aid}::tool:{tool_name}"
                if marker not in visited:
                    visited.append(marker)
        new_hops = hops_used if counted_repeat else hops_used + 1
        conn.execute(
            "UPDATE trajectory_budgets SET hops_used = ?, visited_agents = ?, updated_at = ? "
            "WHERE trajectory_id = ?",
            (new_hops, json.dumps(visited, ensure_ascii=False), time.time(), tid),
        )
        conn.commit()
        return {"allowed": True, "reason": "ok", "trajectory_id": tid,
                "hops_used": new_hops, "max_hops": max_hops,
                "counted_repeat": counted_repeat, "visited_agents": visited}


def reserve_replan(
    trajectory_id: str,
    *,
    run_id: str = "",
    dag_def: Optional[Dict[str, Any]] = None,
    reason: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Replan-Cap pro Ticket, nicht pro run_id. Zaehler wird vom Run vererbt."""
    tid = normalize_trajectory_id(trajectory_id, run_id)
    inherited = 0
    if isinstance(dag_def, dict):
        try:
            inherited = max(0, int(dag_def.get("_replan_count") or 0))
        except (TypeError, ValueError):
            inherited = 0
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO trajectory_budgets "
            "(trajectory_id, root_ticket_id, max_hops, max_tokens, max_replans, "
            " visited_agents, state, last_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '[]', 'active', '', ?, ?)",
            (tid, str(run_id or tid), DEFAULT_MAX_HOPS, DEFAULT_MAX_TOKENS,
             DEFAULT_MAX_REPLANS, time.time(), time.time()),
        )
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        if str(row["state"]) != "active":
            conn.rollback()
            return {"allowed": False, "reason": "replan_cap_reached",
                    "replan_count": int(row["replans_used"]), "trajectory_id": tid}
        used = max(int(row["replans_used"] or 0), inherited)
        cap = int(row["max_replans"])
        if used >= cap:
            blocked = _block(conn, tid, "REPLAN_CAP_REACHED")
            _audit(tid, f"replan_cap_reached ({used}/{cap}) via {run_id}: {reason[:120]}", run_id)
            return {"allowed": False, "reason": "replan_cap_reached",
                    "replan_count": used, "max_replans": cap, "trajectory_id": tid,
                    "state": str(blocked.get("state") or "blocked")}
        conn.execute(
            "UPDATE trajectory_budgets SET replans_used = ?, updated_at = ? WHERE trajectory_id = ?",
            (used + 1, time.time(), tid),
        )
        conn.commit()
        return {"allowed": True, "reason": "ok", "replan_count": used + 1,
                "max_replans": cap, "trajectory_id": tid}


def inherit_replan_count(
    trajectory_id: str,
    run_id: str,
    dag_def: Optional[Dict[str, Any]] = None,
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Neuer run_id uebernimmt den Zaehler der bestehenden Trajectory."""
    tid = normalize_trajectory_id(trajectory_id, run_id)
    with _WRITE_LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT replans_used, state FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        used = int(row["replans_used"] or 0) if row else 0
        inherited = 0
        if isinstance(dag_def, dict):
            try:
                inherited = int(dag_def.get("_replan_count") or 0)
            except (TypeError, ValueError):
                inherited = 0
        used = max(used, inherited)
        if row:
            conn.execute(
                "UPDATE trajectory_budgets SET replans_used = ?, updated_at = ? WHERE trajectory_id = ?",
                (used, time.time(), tid),
            )
            conn.commit()
    return {"trajectory_id": tid, "replan_count": used,
            "state": str(row["state"]) if row else "active"}


def _ensure_trajectory_row(conn: sqlite3.Connection, tid: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO trajectory_budgets "
        "(trajectory_id, root_ticket_id, max_hops, max_tokens, max_replans, "
        " visited_agents, state, last_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, '[]', 'active', '', ?, ?)",
        (tid, tid, DEFAULT_MAX_HOPS, DEFAULT_MAX_TOKENS, DEFAULT_MAX_REPLANS,
         time.time(), time.time()),
    )


def _set_blocked(conn: sqlite3.Connection, tid: str, reason: str) -> None:
    """Wie `_block()`, aber OHNE commit — fuer laufende Transaktionen."""
    conn.execute(
        "UPDATE trajectory_budgets SET state = 'blocked', last_reason = ?, updated_at = ? "
        "WHERE trajectory_id = ? AND state = 'active'",
        (reason[:300], time.time(), tid),
    )


def _apply_token_delta(
    conn: sqlite3.Connection,
    tid: str,
    delta: int,
    *,
    set_total: bool,
    reason: str,
    reservation: bool = False,
    allow_blocked_state: bool = False,
) -> Dict[str, Any]:
    """Einzige Buchungslogik fuer tokens_used (transaktional)."""
    _ensure_trajectory_row(conn, tid)
    row = conn.execute(
        "SELECT tokens_used, max_tokens, reserved_tokens, state FROM trajectory_budgets WHERE trajectory_id = ?",
        (tid,),
    ).fetchone()
    used = int(row["tokens_used"] or 0)
    cap = int(row["max_tokens"])
    reserved = int(row["reserved_tokens"] or 0)
    if str(row["state"]) != "active" and not allow_blocked_state:
        return {"allowed": False, "reason": f"TRAJECTORY_{str(row['state']).upper()}",
                "tokens_used": used, "max_tokens": cap}
    if set_total:
        new_used = max(used, delta)
        overflow = delta > cap
    else:
        new_used = used + delta
        overflow = new_used > cap
    if overflow:
        _set_blocked(conn, tid, "TOKEN_CAP_REACHED")
        _audit(tid, f"TOKEN_CAP_REACHED ({used}+{delta}>{cap}) via {reason}")
        return {"allowed": False, "reason": "TOKEN_CAP_REACHED",
                "tokens_used": used, "max_tokens": cap, "state": "blocked",
                "blocked_now": True}
    new_reserved = reserved + delta if reservation else reserved
    conn.execute(
        "UPDATE trajectory_budgets SET tokens_used = ?, reserved_tokens = ?, "
        "actual_tokens = ?, updated_at = ? WHERE trajectory_id = ?",
        (new_used, new_reserved, delta if set_total else 0, time.time(), tid),
    )
    return {"allowed": True, "tokens_used": new_used, "max_tokens": cap,
            "reserved_tokens": new_reserved}


def _audit_reconciliation(
    tid: str, estimated: int, actual: int, outcome: str, reason: str
) -> None:
    """Pflicht-Audit: Schätzung vs. tatsächlicher Verbrauch (D13-M3)."""
    msg = (f"TOKEN_RECONCILIATION outcome={outcome} estimated={estimated} "
           f"actual={actual} reason={reason[:120]}")
    logger.info("[TrajectoryBudget] %s | trajectory=%s", msg, tid)
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="trajectory_budget",
            action="token_reconciliation",
            agent_id="system",
            payload={"trajectory_id": tid, "outcome": outcome,
                     "estimated": estimated, "actual": actual, "reason": str(reason)[:200]},
        )
    except Exception as exc:
        logger.error("[TrajectoryBudget] Reconciliation-Audit fehlgeschlagen: %s", exc)
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("trajectory_token_reconciled", {
            "trajectory_id": tid, "outcome": outcome,
            "estimated": estimated, "actual": actual,
        })
    except Exception:
        pass


def _finalize_reservation_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    actual_tokens: int,
    outcome: str,
    reason: str,
) -> Dict[str, Any]:
    """Setzt eine Reservierung gegen den echten Wert zurueck (eine Transaktion)."""
    status = {"settled": "settled", "released": "released", "expired": "expired"}.get(
        outcome, "released"
    )
    tid = str(row["trajectory_id"] or normalize_trajectory_id(str(row["trajectory_id"] or "")))
    est = max(0, int(row["tokens_estimated"] or 0))
    actual = max(0, int(actual_tokens or 0)) if outcome == "settled" else 0
    _ensure_trajectory_row(conn, tid)
    budget = conn.execute(
        "SELECT tokens_used, reserved_tokens, max_tokens FROM trajectory_budgets WHERE trajectory_id = ?",
        (tid,),
    ).fetchone()
    used = max(0, int(budget["tokens_used"] or 0) - est)
    reserved = max(0, int(budget["reserved_tokens"] or 0) - est)
    cap = int(budget["max_tokens"])
    new_used = used + actual
    # Ein echter Verbrauch ueber dem Cap wird gebucht (kein stilles Verlieren),
    # aber die Trajectory wird hart blockiert.
    if actual > cap:
        _set_blocked(conn, tid, "TOKEN_CAP_REACHED")
    conn.execute(
        "UPDATE trajectory_budgets SET tokens_used = ?, reserved_tokens = ?, "
        "actual_tokens = ?, updated_at = ? WHERE trajectory_id = ?",
        (new_used, reserved, actual, time.time(), tid),
    )
    conn.execute(
        "UPDATE trajectory_token_reservations SET status = ?, tokens_actual = ?, "
        "settled_at = ?, reason = ? WHERE reservation_id = ? AND status = 'pending'",
        (status, actual, time.time(), str(reason or "")[:200], str(row["reservation_id"])),
    )
    return {"reservation_id": str(row["reservation_id"]), "trajectory_id": tid,
            "estimated": est, "actual": actual, "outcome": outcome,
            "tokens_used": new_used, "max_tokens": cap}


def record_tokens(
    trajectory_id: str,
    tokens: int,
    *,
    db_path: Optional[str] = None,
    reason: str = "usage",
    set_total: bool = False,
) -> Dict[str, Any]:
    """Bucht Token-Verbrauch. Additiv oder als Abschluss-Total.

    `set_total=True` verhindert die Doppelbuchung: eine noch offene
    Reservierung derselben Trajectory wird zuerst gegen den echten Wert
    abgerechnet; der groessere Wert gewinnt, nie die Summe.
    """
    tid = normalize_trajectory_id(trajectory_id)
    delta = max(0, int(tokens or 0))
    reconciled: Dict[str, Any] = {}
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if set_total:
            pending = conn.execute(
                "SELECT * FROM trajectory_token_reservations "
                "WHERE trajectory_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                (tid,),
            ).fetchone()
            if pending:
                reconciled = _finalize_reservation_row(
                    conn, pending, delta, "settled", f"{reason}:set_total"
                )
        result = _apply_token_delta(
            conn, tid, delta, set_total=set_total, reason=reason,
            allow_blocked_state=set_total,
        )
        if result.get("allowed") or result.get("blocked_now"):
            conn.commit()
        else:
            conn.rollback()
    if reconciled:
        _audit_reconciliation(
            tid, int(reconciled["estimated"]), int(reconciled["actual"]),
            "settled", f"{reason}:set_total",
        )
    return result


def expire_stale_reservations(
    *,
    db_path: Optional[str] = None,
    now: Optional[float] = None,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """D13-M3: verfällt eine Reservierung ohne Abschluss, wird sie freigegeben."""
    cutoff = (float(now) if now is not None else time.time()) - int(
        ttl_seconds or RESERVATION_TTL_SECONDS
    )
    done: List[Dict[str, Any]] = []
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM trajectory_token_reservations WHERE status = 'pending' AND created_at < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            done.append(_finalize_reservation_row(conn, row, 0, "expired", "reservation_ttl"))
        conn.commit()
    for item in done:
        _audit_reconciliation(
            str(item["trajectory_id"]), int(item["estimated"]), 0,
            "expired", "reservation_ttl",
        )
    return {"expired": len(done), "reservations": done}


def reserve_tokens(
    trajectory_id: str,
    tokens: int,
    *,
    db_path: Optional[str] = None,
    reason: str = "dispatch",
    reservation_id: Optional[str] = None,
    source_key: Optional[str] = None,
    agent_id: str = "",
    skip_expiry: bool = False,
) -> Dict[str, Any]:
    """D13/MED+M3: atomare, TTL-begrenzte Reservierung VOR dem Provider-Call.

    Die Reservierung wird als eigene Zeile mit ID und `source_key`
    persistiert, damit `finalize_tokens()`/`release_tokens()` spaeter exakt
    gegen den echten Verbrauch abrechnen koennen (Schätzung vs. Actual).
    """
    tid = normalize_trajectory_id(trajectory_id)
    delta = max(0, int(tokens or 0))
    if not skip_expiry:
        expire_stale_reservations(db_path=db_path)
    rid = str(reservation_id or f"trajres-{uuid.uuid4().hex[:12]}")
    key = str(source_key or "").strip() or token_reservation_source_key(agent_id, delta)
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT status, tokens_estimated FROM trajectory_token_reservations WHERE reservation_id = ?",
            (rid,),
        ).fetchone()
        if existing and str(existing["status"]) == "pending":
            conn.rollback()
            return {"allowed": True, "trajectory_id": tid, "reservation_id": rid,
                    "estimated_tokens": int(existing["tokens_estimated"] or 0), "idempotent": True}
        result = _apply_token_delta(
            conn, tid, delta, set_total=False, reason=reason, reservation=True
        )
        if not result.get("allowed", False):
            # Cap-Ueberschreitung muss persistiert werden (blocked), sonst
            # koennen weitere Calls den Cap erneut pruefen und passieren.
            if result.get("blocked_now"):
                conn.commit()
            else:
                conn.rollback()
            return {**result, "trajectory_id": tid, "stage": "tokens"}
        conn.execute(
            "INSERT INTO trajectory_token_reservations "
            "(reservation_id, trajectory_id, agent_id, source_key, tokens_estimated, "
            " tokens_actual, status, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, -1, 'pending', ?, ?)",
            (rid, tid, str(agent_id or ""), key, delta, str(reason or "")[:200], time.time()),
        )
        conn.commit()
    return {**result, "trajectory_id": tid, "reservation_id": rid,
            "estimated_tokens": delta, "source_key": key}


def finalize_tokens(
    trajectory_id: str = "",
    *,
    reservation_id: str = "",
    source_key: str = "",
    actual_tokens: int = 0,
    outcome: str = "settled",
    reason: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Actual-Token-Abschluss einer Reservierung (kein Doppelbuchung)."""
    tid = normalize_trajectory_id(trajectory_id) if str(trajectory_id or "").strip() else ""
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = None
        if str(reservation_id or "").strip():
            row = conn.execute(
                "SELECT * FROM trajectory_token_reservations "
                "WHERE reservation_id = ? AND status = 'pending'",
                (str(reservation_id),),
            ).fetchone()
        if row is None and tid and str(source_key or "").strip():
            row = conn.execute(
                "SELECT * FROM trajectory_token_reservations "
                "WHERE trajectory_id = ? AND source_key = ? AND status = 'pending' "
                "ORDER BY created_at DESC LIMIT 1",
                (tid, str(source_key)),
            ).fetchone()
        if row is None:
            conn.rollback()
            return {"status": "not_found", "trajectory_id": tid,
                    "reservation_id": str(reservation_id or ""),
                    "source_key": str(source_key or "")}
        done = _finalize_reservation_row(
            conn, row, actual_tokens, outcome, reason
        )
        conn.commit()
    _audit_reconciliation(
        str(done["trajectory_id"]), int(done["estimated"]), int(done["actual"]),
        str(done["outcome"]), reason,
    )
    return {"status": "settled", **done}


def release_tokens(
    trajectory_id: str = "",
    *,
    reservation_id: str = "",
    source_key: str = "",
    reason: str = "dispatch_failed",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Gegenbuchung bei `blocked`/`error` — keine residuale Reservierung."""
    return finalize_tokens(
        trajectory_id, reservation_id=reservation_id, source_key=source_key,
        actual_tokens=0, outcome="released", reason=reason, db_path=db_path,
    )


def task_budget_meta_projection(
    trajectory_id: str,
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """D13/MED: echter Produzent für die `mc_task_meta`-Budget-Spiegelung.

    `enforce_task_budget_caps()` in mission_control.py prüft nur Paare, bei
    denen Cap UND Zähler im Meta liegen. Diese Projektion liefert beide aus
    der SSOT `trajectory_budgets` — inklusive des `replan_count`-Aliases.
    Damit ist der Alias kein Totcode mehr, sondern eine lesbare Kopie.
    """
    tid = normalize_trajectory_id(trajectory_id)
    row = get_trajectory(tid, db_path=db_path)
    if not row:
        return {}
    replans = int(row.get("replans_used") or 0)
    return {
        "trajectory_id": tid,
        "root_ticket_id": str(row.get("root_ticket_id") or ""),
        "max_hops": int(row.get("max_hops") or DEFAULT_MAX_HOPS),
        "hops_used": int(row.get("hops_used") or 0),
        "max_tokens": int(row.get("max_tokens") or DEFAULT_MAX_TOKENS),
        "tokens_used": int(row.get("tokens_used") or 0),
        "reserved_tokens": int(row.get("reserved_tokens") or 0),
        "actual_tokens": int(row.get("actual_tokens") or 0),
        "max_replans": int(row.get("max_replans") or DEFAULT_MAX_REPLANS),
        "replans_used": replans,
        "replan_count": replans,
        "trajectory_state": str(row.get("state") or "active"),
    }


def sync_task_budget_meta(
    trajectory_id: str,
    task_id: str = "",
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Schreibt die Budget-Projektion in `mc_task_meta` des Root-Tickets."""
    meta = task_budget_meta_projection(trajectory_id, db_path=db_path)
    target = str(task_id or meta.get("root_ticket_id") or "").strip()
    if meta and target and not target.startswith("traj-"):
        try:
            from archon.core.mission_control import mc_update_task_sqlite
            mc_update_task_sqlite(target, meta)
        except Exception as exc:
            logger.debug("[TrajectoryBudget] Task-Meta-Spiegelung fehlgeschlagen: %s", exc)
    return meta


def close_trajectory(
    trajectory_id: str,
    state: str = "completed",
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    final = state if state in ("completed", "failed", "released", "blocked") else "completed"
    tid = normalize_trajectory_id(trajectory_id)
    with _WRITE_LOCK, _connect(db_path) as conn:
        # R-B3 (Re-Audit D13): Ein bereits geblocktes Trajectory darf beim
        # Abschluss NICHT auf completed/failed gehoben werden. Sonst wird die
        # Cap-Invariante (HOP/REPLAN/TOKEN) durch den Run-Abschluss zerstoert.
        row = conn.execute(
            "SELECT state FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        current = str(row["state"]) if row else ""
        if current == "blocked" and final != "blocked":
            return {"trajectory_id": tid, "state": "blocked", "preserved": True, "requested": final}
        conn.execute(
            "UPDATE trajectory_budgets SET state = ?, updated_at = ? "
            "WHERE trajectory_id = ? AND state != 'blocked'",
            (final, time.time(), tid),
        )
        conn.commit()
    return {"trajectory_id": tid, "state": final}


def guard_window_size(policy: Optional[Dict[str, Any]] = None, default_max_steps: int = 15) -> int:
    """HANDOFF an core_dispatcher.py: Boardroom-Slice >= max_steps+1."""
    p = policy or {}
    try:
        max_steps = max(5, min(30, int(p.get("max_steps_per_task", default_max_steps))))
    except (TypeError, ValueError):
        max_steps = default_max_steps
    return max_steps + 1


def zombie_eligible(row: Dict[str, Any], now: Optional[float] = None) -> bool:
    """HANDOFF an operations_api.py: 6-h-Reset NUR bei abgelaufener Lease.

    `row` enthaeltstatus/claim_expires/claim_lock/pid. Ein noch lebender
    Worker (PID) oder eine aktive Lease schliesst den Reset aus.
    """
    current = time.time() if now is None else float(now)
    if str(row.get("status") or "") != "in_progress":
        return False
    lease = row.get("claim_expires")
    if lease is not None:
        try:
            if float(lease) >= current:
                return False
        except (TypeError, ValueError):
            return False
    if row.get("claim_lock"):
        pid = row.get("pid")
        if pid:
            try:
                import backend.deadlock_supervisor as _ds
                _pid_alive = getattr(_ds, "_pid_alive", None)
                if callable(_pid_alive) and _pid_alive(int(pid)):
                    return False
            except Exception:
                return False
    return True


def _run_regression_tests() -> None:
    """D13-Regression: A->B->A, Hop 4/3, Replan #3, Repeat-Budget.

    `python backend/trajectory_budget.py`.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "ops.db")
        # 1) A -> B -> A muss CYCLE_DETECTED liefern.
        tid = ensure_trajectory(max_hops=MAX_DELEGATION_DEPTH,
                                root_ticket_id="ticket-cycle", db_path=db)["trajectory_id"]
        reserve_hop(tid, "agent-a", "test", db_path=db)
        reserve_hop(tid, "agent-b", "test", db_path=db)
        cyc = reserve_hop(tid, "agent-a", "test", db_path=db)
        assert not cyc["allowed"] and cyc["reason"] == "CYCLE_DETECTED", cyc
        print("PASS 1: A->B->A -> CYCLE_DETECTED")
        # 2) Hop 4/3 muss DEPTH_EXCEEDED liefern (SSOT=3, kein Expand auf 50).
        tid2 = ensure_trajectory(max_hops=50, root_ticket_id="ticket-depth", db_path=db)
        assert int(tid2["max_hops"]) == MAX_DELEGATION_DEPTH, tid2
        tid2_id = tid2["trajectory_id"]
        for i in range(MAX_DELEGATION_DEPTH):
            assert reserve_hop(tid2_id, f"agent-{i}", "test", db_path=db)["allowed"]
        depth = reserve_hop(tid2_id, "agent-6", "test", db_path=db)
        assert not depth["allowed"] and depth["reason"] == "DEPTH_EXCEEDED", depth
        print("PASS 2: hop 4/3 -> DEPTH_EXCEEDED (50 auf SSOT geklemmt)")
        # 3) Replan #3 muss replan_cap_reached liefern (auch ueber neue run_id).
        tid3 = ensure_trajectory(max_replans=2, root_ticket_id="ticket-replan", db_path=db)["trajectory_id"]
        for i in range(2):
            assert reserve_replan(tid3, run_id=f"run-{i}", db_path=db)["allowed"]
        replan = reserve_replan(tid3, run_id="run-3", db_path=db)
        assert not replan["allowed"] and replan["reason"] == "replan_cap_reached", replan
        print("PASS 3: replan #3 -> replan_cap_reached (state=blocked)")
        # 4) Gezaehltes Repeat-Budget: llm_call mit allow_repeat ist NICHT mehr
        #    pauschal ausgenommen — der persistierte Zaehler greift (hier auf 1
        #    verschaeft, damit der Test innerhalb der SSOT-Tiefe bleibt).
        tid4 = ensure_trajectory(root_ticket_id="ticket-repeat", db_path=db)["trajectory_id"]
        set_repeat_budget(tid4, "agent-r", "llm_call:agent-r", 1, db_path=db)
        first = reserve_hop(tid4, "agent-r", "llm_call:agent-r", allow_repeat=True, db_path=db)
        second = reserve_hop(tid4, "agent-r", "llm_call:agent-r", allow_repeat=True, db_path=db)
        third = reserve_hop(tid4, "agent-r", "llm_call:agent-r", allow_repeat=True, db_path=db)
        assert first["allowed"] and second["allowed"], (first, second)
        assert third["reason"] == "CYCLE_DETECTED", third
        print("PASS 4: repeat-Budget 1 -> 3. llm_call CYCLE_DETECTED")


if __name__ == "__main__":
    _run_regression_tests()


__all__ = [
    "MAX_DELEGATION_DEPTH", "DEFAULT_MAX_HOPS", "DEFAULT_MAX_TOKENS", "DEFAULT_MAX_REPLANS",
    "DEFAULT_MAX_DELEGATIONS_PER_RESPONSE", "RESERVATION_TTL_SECONDS",
    "DEFAULT_REPEAT_BUDGET", "REPEAT_REASON_PREFIXES", "clamp_max_hops",
    "set_repeat_budget", "repeat_budget_status",
    "resolve_trajectory_db_path", "stable_trajectory_id", "normalize_trajectory_id",
    "current_trajectory_root", "trajectory_root", "bind_trajectory_root",
    "trajectory_root_scope", "trajectory_root_source", "token_reservation_source_key",
    "UNROOTED_TRAJECTORY_SEED",
    "ensure_trajectory", "get_trajectory", "reserve_hop", "reserve_replan",
    "inherit_replan_count", "record_tokens", "reserve_tokens", "finalize_tokens",
    "release_tokens", "expire_stale_reservations", "close_trajectory",
    "task_budget_meta_projection", "sync_task_budget_meta",
    "guard_window_size", "zombie_eligible", "init_trajectory_tables",
]
