# -*- coding: utf-8 -*-
"""
backend/trajectory_budget.py — D13: ticketweite Trajectory-Budget-Invariante.

Eine einzige, stabile `trajectory_id` ist der Schluessel fuer
Lesen/Schreiben/Resume der Delegationskette, Hop-, Token- und Replan-Caps.
SQLite ONLY (keine Postgres-Migration, kein Coroutine-Replay).

HANDOFF (Dateien gehoeren anderen Agenten — hier nur Vertrag, nicht geaendert):
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

import datetime
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("archon.trajectory_budget")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILENAME = "ops.db"

DEFAULT_MAX_HOPS = 5
DEFAULT_MAX_TOKENS = 200_000
DEFAULT_MAX_REPLANS = 2
DEFAULT_MAX_DELEGATIONS_PER_RESPONSE = 5
RESERVATION_TTL_SECONDS = 7200

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trajectory_budgets (
            trajectory_id TEXT PRIMARY KEY,
            root_ticket_id TEXT NOT NULL,
            max_hops INTEGER NOT NULL DEFAULT 5,
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trajectory_root ON trajectory_budgets(root_ticket_id)"
    )
    conn.commit()


def stable_trajectory_id(root_ticket_id: str) -> str:
    """Deterministisch aus dem Root-Ticket — A->B->A bleibt dieselbe ID."""
    base = str(root_ticket_id or "").strip()
    if not base:
        base = f"anonymous:{time.time_ns()}:{threading.get_ident()}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"traj-{digest}"


def normalize_trajectory_id(
    trajectory_id: Optional[str] = None,
    root_ticket_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    if trajectory_id and str(trajectory_id).startswith("traj-"):
        return str(trajectory_id)
    seed = str(root_ticket_id or "").strip() or str(session_id or "").strip()
    return stable_trajectory_id(seed)


def _audit(trajectory_id: str, msg: str, task_id: str = "") -> None:
    logger.warning("[TrajectoryBudget] %s | trajectory=%s ticket=%s", msg, trajectory_id, task_id)
    try:
        from archon.core.mission_control import mc_append_audit_sqlite
        mc_append_audit_sqlite("trajectory_budget", msg, task_id or trajectory_id or "_system")
    except Exception as exc:
        logger.debug("[TrajectoryBudget] Audit-Schreibfehler: %s", exc)
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("trajectory_budget_blocked", {
            "trajectory_id": trajectory_id, "task_id": task_id, "reason": msg,
        })
    except Exception:
        pass


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
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO trajectory_budgets "
            "(trajectory_id, root_ticket_id, max_hops, hops_used, max_tokens, tokens_used, "
            " max_replans, replans_used, visited_agents, state, last_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, 0, ?, 0, '[]', 'active', '', ?, ?)",
            (
                tid, root,
                max(1, int(max_hops if max_hops is not None else DEFAULT_MAX_HOPS)),
                max(1, int(max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS)),
                max(0, int(max_replans if max_replans is not None else DEFAULT_MAX_REPLANS)),
                now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        updates: Dict[str, Any] = {}
        if max_hops is not None:
            updates["max_hops"] = min(int(row["max_hops"]), max(1, int(max_hops)))
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

    Fail-closed: unbekannte Trajectory wird mit Default-Caps angelegt, eine
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
            (tid, str(root_ticket_id or tid), DEFAULT_MAX_HOPS, DEFAULT_MAX_TOKENS,
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
        # D13: Ein Retry/Replan/Tool-Call desselben Knotens ist KEIN Delegationszyklus.
        # Zyklen sind A->B->A (Agentwechsel); Wiederholungen zaehlen nur als Hop.
        _is_repeat = allow_repeat or str(reason or "").startswith(("retry:", "replan:", "repair:", "tool:"))
        if aid and aid in visited and not _is_repeat:
            blocked = _block(conn, tid, f"CYCLE_DETECTED:{aid}")
            _audit(tid, f"CYCLE_DETECTED via {aid} ({reason})", str(root_ticket_id or ""))
            return {"allowed": False, "reason": "CYCLE_DETECTED", "agent_id": aid,
                    "trajectory_id": tid, "hops_used": int(blocked.get("hops_used", 0)),
                    "max_hops": int(blocked.get("max_hops", DEFAULT_MAX_HOPS))}
        hops_used = int(row["hops_used"] or 0)
        max_hops = int(row["max_hops"])
        if hops_used >= max_hops:
            blocked = _block(conn, tid, "DEPTH_EXCEEDED")
            _audit(tid, f"DEPTH_EXCEEDED ({hops_used}/{max_hops}) via {reason}", str(root_ticket_id or ""))
            return {"allowed": False, "reason": "DEPTH_EXCEEDED", "trajectory_id": tid,
                    "hops_used": hops_used, "max_hops": max_hops}
        if aid and aid not in visited:
            visited.append(aid)
        conn.execute(
            "UPDATE trajectory_budgets SET hops_used = ?, visited_agents = ?, updated_at = ? "
            "WHERE trajectory_id = ?",
            (hops_used + 1, json.dumps(visited, ensure_ascii=False), time.time(), tid),
        )
        conn.commit()
        return {"allowed": True, "reason": "ok", "trajectory_id": tid,
                "hops_used": hops_used + 1, "max_hops": max_hops,
                "visited_agents": visited}


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


def record_tokens(
    trajectory_id: str,
    tokens: int,
    *,
    db_path: Optional[str] = None,
    reason: str = "usage",
    set_total: bool = False,
) -> Dict[str, Any]:
    """Bucht Token-Verbrauch. Additiv (Reservierung) oder als Abschluss-Total.

    D13/MED: `set_total=True` verhindert die Doppelbuchung, wenn vorab schon
    `reserve_tokens()` atomar reserviert hat — der groessere der beiden Werte
    gewinnt, nie die Summe.
    """
    tid = normalize_trajectory_id(trajectory_id)
    delta = max(0, int(tokens or 0))
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO trajectory_budgets "
            "(trajectory_id, root_ticket_id, max_hops, max_tokens, max_replans, "
            " visited_agents, state, last_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '[]', 'active', '', ?, ?)",
            (tid, tid, DEFAULT_MAX_HOPS, DEFAULT_MAX_TOKENS, DEFAULT_MAX_REPLANS,
             time.time(), time.time()),
        )
        row = conn.execute(
            "SELECT * FROM trajectory_budgets WHERE trajectory_id = ?", (tid,)
        ).fetchone()
        used = int(row["tokens_used"] or 0)
        cap = int(row["max_tokens"])
        if set_total:
            new_used = max(used, delta)
            overflow = delta > cap
        else:
            new_used = used + delta
            overflow = new_used > cap
        if overflow:
            blocked = _block(conn, tid, "TOKEN_CAP_REACHED")
            _audit(tid, f"TOKEN_CAP_REACHED ({used}+{delta}>{cap}) via {reason}")
            return {"allowed": False, "reason": "TOKEN_CAP_REACHED",
                    "tokens_used": used, "max_tokens": cap,
                    "state": str(blocked.get("state") or "blocked")}
        conn.execute(
            "UPDATE trajectory_budgets SET tokens_used = ?, updated_at = ? WHERE trajectory_id = ?",
            (new_used, time.time(), tid),
        )
        conn.commit()
        return {"allowed": True, "tokens_used": new_used, "max_tokens": cap}


def reserve_tokens(
    trajectory_id: str,
    tokens: int,
    *,
    db_path: Optional[str] = None,
    reason: str = "dispatch",
) -> Dict[str, Any]:
    """D13/MED: atomare Token-Reservierung VOR einem teuren Dispatch.

    Wie `reserve_hop()`: BEGIN IMMEDIATE, hartes Cap, bei Ueberlauf `blocked`
    und Audit. Damit bleibt `tokens_used` waehrend des Runs nicht konstant 0.
    """
    return record_tokens(
        trajectory_id, tokens, db_path=db_path, reason=reason, set_total=False
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
    """D13-Regression: A->B->A, 6 Hops, Replan #3. `python backend/trajectory_budget.py`."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "ops.db")
        # 1) A -> B -> A muss CYCLE_DETECTED liefern.
        tid = ensure_trajectory(max_hops=5, root_ticket_id="ticket-cycle", db_path=db)["trajectory_id"]
        reserve_hop(tid, "agent-a", "test", db_path=db)
        reserve_hop(tid, "agent-b", "test", db_path=db)
        cyc = reserve_hop(tid, "agent-a", "test", db_path=db)
        assert not cyc["allowed"] and cyc["reason"] == "CYCLE_DETECTED", cyc
        print("PASS 1: A->B->A -> CYCLE_DETECTED")
        # 2) 6. Hop muss DEPTH_EXCEEDED liefern.
        tid2 = ensure_trajectory(max_hops=5, root_ticket_id="ticket-depth", db_path=db)["trajectory_id"]
        for i in range(5):
            assert reserve_hop(tid2, f"agent-{i}", "test", db_path=db)["allowed"]
        depth = reserve_hop(tid2, "agent-6", "test", db_path=db)
        assert not depth["allowed"] and depth["reason"] == "DEPTH_EXCEEDED", depth
        print("PASS 2: hop 6/5 -> DEPTH_EXCEEDED")
        # 3) Replan #3 muss replan_cap_reached liefern (auch ueber neue run_id).
        tid3 = ensure_trajectory(max_replans=2, root_ticket_id="ticket-replan", db_path=db)["trajectory_id"]
        for i in range(2):
            assert reserve_replan(tid3, run_id=f"run-{i}", db_path=db)["allowed"]
        replan = reserve_replan(tid3, run_id="run-3", db_path=db)
        assert not replan["allowed"] and replan["reason"] == "replan_cap_reached", replan
        print("PASS 3: replan #3 -> replan_cap_reached (state=blocked)")
    print("ALL 3 REGRESSION TESTS PASSED")


if __name__ == "__main__":
    _run_regression_tests()


__all__ = [
    "DEFAULT_MAX_HOPS", "DEFAULT_MAX_TOKENS", "DEFAULT_MAX_REPLANS",
    "DEFAULT_MAX_DELEGATIONS_PER_RESPONSE", "RESERVATION_TTL_SECONDS",
    "resolve_trajectory_db_path", "stable_trajectory_id", "normalize_trajectory_id",
    "ensure_trajectory", "get_trajectory", "reserve_hop", "reserve_replan",
    "inherit_replan_count", "record_tokens", "reserve_tokens", "close_trajectory",
    "task_budget_meta_projection", "sync_task_budget_meta",
    "guard_window_size", "zombie_eligible", "init_trajectory_tables",
]
