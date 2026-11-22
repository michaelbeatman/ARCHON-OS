"""
backend/durable_execution_kernel.py
====================================
Minimaler Durable-Execution-Kernel fuer Archon OS.

Loesst strukturell (nicht punktuell):
  * A5 — Checkpoint-Resume war eine Sackgasse (nur lesend, kein Executor).
  * A6 — Prozesslokale Locks (_RUN_LOCKS, _MC_ASYNC_LOCK) bei mehreren Workern.
  * A2 — Leases/Heartbeats existierten, waren aber nicht verdrahtet.

Der Kernel ist bewusst klein: klassische Zustandsmaschine, append-only
Command-Log und CAS-Claims mit Fencing-Token. Er wird in
``workflow_dag_runner.resume_workflow_run`` und im Mission-Control-Pfad
verdrahtet, statt ein weiteres unbenutztes Modul zu sein.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("archon.durable_execution")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


# Explizite Zustandsmaschine statt ad-hoc Statusstrings.
PENDING = "PENDING"
RUNNING = "RUNNING"
PAUSED = "PAUSED"
SUSPENDED = "SUSPENDED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

VALID_TRANSITIONS: Dict[str, set] = {
    PENDING: {RUNNING, CANCELLED},
    RUNNING: {PAUSED, SUSPENDED, COMPLETED, FAILED, CANCELLED},
    PAUSED: {RUNNING, CANCELLED, FAILED},
    SUSPENDED: {RUNNING, CANCELLED, FAILED},
    COMPLETED: set(),
    FAILED: {PENDING},          # expliziter, erneuter Versuch
    CANCELLED: set(),
}

TERMINAL_STATES = frozenset({COMPLETED, FAILED, CANCELLED})


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


class InvalidTransitionError(ValueError):
    """Eine Transition verletzt die Zustandsmaschine."""


class StaleFencingTokenError(PermissionError):
    """Ein veralteter Fencing-Token versucht einen geschuetzten Zustand zu aendern."""


class DurableExecutionKernel:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with _connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS durable_executions (
                    run_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    fencing_token TEXT NOT NULL,
                    claim_expires REAL NOT NULL,
                    dag_fingerprint TEXT DEFAULT '',
                    checkpoint_step INTEGER DEFAULT 0,
                    state_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS durable_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    command_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fencing_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(run_id, seq)
                )
            """)
            conn.commit()

    # ---------------------------------------------------------------- Claim
    def claim(
        self,
        run_id: str,
        ttl_seconds: int = 300,
        dag_fingerprint: str = "",
        fencing_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """CAS-Claim: genau ein Worker darf einen Run ausfuehren.

        Ein bestehender, noch gueltiger Claim wird abgelehnt. Ein abgelaufener
        Claim darf uebernommen werden — der neue Fencing-Token entwertet
        jeden spaeteren Schreibversuch des alten Workers.
        """
        token = fencing_token or f"{os.getpid()}:{uuid.uuid4().hex[:12]}"
        now = time.time()
        expires = now + max(30, int(ttl_seconds))
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, fencing_token, claim_expires FROM durable_executions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO durable_executions "
                    "(run_id, state, fencing_token, claim_expires, dag_fingerprint, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run_id, RUNNING, token, expires, dag_fingerprint, now, now),
                )
                conn.commit()
                return {"claimed": True, "fencing_token": token, "state": RUNNING, "expires_at": expires}
            if (
                row["state"] in TERMINAL_STATES
                or (row["claim_expires"] > now and row["fencing_token"] != token)
            ):
                conn.rollback()
                return {"claimed": False, "state": row["state"], "reason": "already_claimed_or_terminal"}
            conn.execute(
                "UPDATE durable_executions SET state = ?, fencing_token = ?, claim_expires = ?, "
                "dag_fingerprint = ?, updated_at = ? WHERE run_id = ?",
                (RUNNING, token, expires, dag_fingerprint or row["dag_fingerprint"], now, run_id),
            )
            conn.commit()
        return {"claimed": True, "fencing_token": token, "state": RUNNING, "expires_at": expires}

    def renew(self, run_id: str, fencing_token: str, ttl_seconds: int = 300) -> bool:
        now = time.time()
        with _connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE durable_executions SET claim_expires = ?, updated_at = ? "
                "WHERE run_id = ? AND fencing_token = ? AND state = ?",
                (now + max(30, int(ttl_seconds)), now, run_id, fencing_token, RUNNING),
            )
            conn.commit()
            return int(cur.rowcount or 0) == 1

    def release(self, run_id: str, fencing_token: str) -> bool:
        with _connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE durable_executions SET claim_expires = 0, updated_at = ? "
                "WHERE run_id = ? AND fencing_token = ?",
                (time.time(), run_id, fencing_token),
            )
            conn.commit()
            return int(cur.rowcount or 0) == 1

    # ---------------------------------------------------------------- Log / State
    def append_command(
        self,
        run_id: str,
        command_type: str,
        payload: Dict[str, Any],
        fencing_token: str,
    ) -> Dict[str, Any]:
        """Append-only Command-Log mit Fencing und fortlaufender Seq."""
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT fencing_token FROM durable_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row and row["fencing_token"] != fencing_token:
                conn.rollback()
                raise StaleFencingTokenError(
                    f"Fencing-Token fuer Run '{run_id}' ist veraltet — Schreibzugriff verweigert."
                )
            nxt = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM durable_commands WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO durable_commands "
                "(run_id, seq, command_type, payload_json, fencing_token, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, nxt, command_type,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), fencing_token, time.time()),
            )
            conn.commit()
        return {"status": "appended", "run_id": run_id, "seq": int(nxt)}

    def transition(
        self,
        run_id: str,
        to_state: str,
        fencing_token: str,
        *,
        reason: str = "",
        state_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validierte Zustandsaenderung + Command-Log in EINER Transaktion."""
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, fencing_token FROM durable_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Durable-Run '{run_id}' nicht gefunden.")
            if row["fencing_token"] != fencing_token:
                conn.rollback()
                raise StaleFencingTokenError(
                    f"Fencing-Token fuer Run '{run_id}' ist veraltet."
                )
            current = str(row["state"])
            if to_state not in VALID_TRANSITIONS.get(current, set()):
                conn.rollback()
                raise InvalidTransitionError(
                    f"Ungueltige Transition {current} → {to_state} fuer Run '{run_id}'."
                )
            nxt = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM durable_commands WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO durable_commands "
                "(run_id, seq, command_type, payload_json, fencing_token, created_at) "
                "VALUES (?, ?, 'state_transition', ?, ?, ?)",
                (run_id, nxt,
                 json.dumps({"from": current, "to": to_state, "reason": reason}, ensure_ascii=False),
                 fencing_token, time.time()),
            )
            if state_json is not None:
                conn.execute(
                    "UPDATE durable_executions SET state = ?, state_json = ?, updated_at = ? "
                    "WHERE run_id = ?",
                    (to_state, json.dumps(state_json, ensure_ascii=False, sort_keys=True), time.time(), run_id),
                )
            else:
                conn.execute(
                    "UPDATE durable_executions SET state = ?, updated_at = ? WHERE run_id = ?",
                    (to_state, time.time(), run_id),
                )
            conn.commit()
        return {"status": "transitioned", "from": current, "to": to_state, "seq": int(nxt)}

    # ---------------------------------------------------------------- Checkpoint
    def checkpoint(
        self,
        run_id: str,
        step_index: int,
        state_json: Dict[str, Any],
        fencing_token: str,
    ) -> Dict[str, Any]:
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT fencing_token FROM durable_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row and row["fencing_token"] != fencing_token:
                conn.rollback()
                raise StaleFencingTokenError(f"Fencing-Token fuer '{run_id}' veraltet.")
            conn.execute(
                "UPDATE durable_executions SET checkpoint_step = ?, state_json = ?, updated_at = ? "
                "WHERE run_id = ?",
                (int(step_index), json.dumps(state_json, ensure_ascii=False, sort_keys=True), time.time(), run_id),
            )
            nxt = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM durable_commands WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO durable_commands "
                "(run_id, seq, command_type, payload_json, fencing_token, created_at) "
                "VALUES (?, ?, 'checkpoint', ?, ?, ?)",
                (run_id, nxt,
                 json.dumps({"step": int(step_index), "keys": sorted(state_json.keys())}, ensure_ascii=False),
                 fencing_token, time.time()),
            )
            conn.commit()
        return {"status": "checkpointed", "step": int(step_index), "seq": int(nxt)}

    def suspend(
        self,
        run_id: str,
        fencing_token: str,
        checkpoint_step: int,
        state_json: Dict[str, Any],
        *,
        reason: str = "",
    ) -> Dict[str, Any]:
        """RUNNING → SUSPENDED mit Checkpoint. Fail-closed bei falschem Token."""
        self.checkpoint(run_id, checkpoint_step, state_json, fencing_token)
        return self.transition(
            run_id, SUSPENDED, fencing_token,
            reason=reason or "suspended_with_checkpoint",
            state_json=state_json,
        )

    def resume_context(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Liefert alles, was fuer ein pragmatisches Resume noetig ist.

        Kein Coroutinen-Replay: der DAG-Runner nutzt die persistierten
        ``workflow_node_states`` (Fingerprint + Output) und ueberspringt
        bereits abgeschlossene Knoten ueber den Fingerprint-Cache.
        """
        state = self.get_state(run_id)
        if not state:
            return None
        return {
            "run_id": run_id,
            "state": state["state"],
            "checkpoint_step": state["checkpoint_step"],
            "state_data": state["state_data"],
            "fencing_token": state["fencing_token"],
            "claim_expires": state["claim_expires"],
            "commands": self.command_log(run_id),
        }

    def resume_suspended(
        self,
        run_id: str,
        fencing_token: Optional[str] = None,
        *,
        ttl_seconds: int = 300,
    ) -> Dict[str, Any]:
        """SUSPENDED → RUNNING, validiert gegen den gespeicherten Checkpoint.

        Pragmatisch: es wird kein Coroutinen-Zustand wiederhergestellt. Der
        Aufrufer (DAG-Runner) verwendet ``checkpoint_step`` + die persistierten
        Node-Outputs, um ab dem letzten abgeschlossenen Schritt weiterzulaufen.

        Ein abgelaufener Claim darf einen neuen Fencing-Token erhalten — der
        Token des alten Workers wird damit entwertet (A2/A6).
        """
        now = time.time()
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, fencing_token, claim_expires, checkpoint_step, state_json "
                "FROM durable_executions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Durable-Run '{run_id}' nicht gefunden.")
            if str(row["state"]) != SUSPENDED:
                conn.rollback()
                raise InvalidTransitionError(
                    f"Resume nur aus SUSPENDED moeglich (aktuell: {row['state']})."
                )
            if fencing_token and fencing_token == row["fencing_token"]:
                token = fencing_token
            elif float(row["claim_expires"] or 0) <= now:
                token = f"{os.getpid()}:{uuid.uuid4().hex[:12]}"
            else:
                conn.rollback()
                raise StaleFencingTokenError(
                    f"Claim fuer '{run_id}' ist noch aktiv — Resume mit neuem Token gesperrt."
                )

            nxt = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM durable_commands WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO durable_commands "
                "(run_id, seq, command_type, payload_json, fencing_token, created_at) "
                "VALUES (?, ?, 'resume', ?, ?, ?)",
                (run_id, nxt,
                 json.dumps({"from": SUSPENDED, "to": RUNNING, "step": row["checkpoint_step"]}, ensure_ascii=False),
                 token, now),
            )
            conn.execute(
                "UPDATE durable_executions SET state = ?, fencing_token = ?, claim_expires = ?, "
                "updated_at = ? WHERE run_id = ?",
                (RUNNING, token, now + max(30, int(ttl_seconds)), now, run_id),
            )
            conn.commit()
        try:
            step_data = json.loads(row["state_json"] or "{}")
        except Exception:
            step_data = {}
        return {
            "status": "resumed",
            "run_id": run_id,
            "fencing_token": token,
            "resume_from_step": int(row["checkpoint_step"] or 0) + 1,
            "state_data": step_data,
            "seq": int(nxt),
        }

    def get_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        with _connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM durable_executions WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["state_data"] = json.loads(data.pop("state_json") or "{}")
            except Exception:
                data["state_data"] = {}
            return data

    def command_log(self, run_id: str) -> List[Dict[str, Any]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT seq, command_type, payload_json, created_at FROM durable_commands "
                "WHERE run_id = ? ORDER BY seq ASC", (run_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.pop("payload_json") or "{}")
            except Exception:
                d["payload"] = {}
            out.append(d)
        return out


durable_kernel = DurableExecutionKernel()
