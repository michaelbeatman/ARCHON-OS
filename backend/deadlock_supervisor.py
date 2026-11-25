"""
backend/deadlock_supervisor.py
Deadlock- & Stagnations-Wächter für parallele Subagenten (Pillar 1 & 2).
Erkennt zirkuläre Abhängigkeiten und stagnierende Tasks im Kanban/Scheduler.
Löst Blockaden nach konfigurierbarer Inaktivität autonom auf.
"""
import logging
_archon_exc_logger = logging.getLogger("deadlock_supervisor")

import os
import sys
import sqlite3
import datetime
import time
import uuid
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    KANBAN_DB = _resolve_db("kanban.db")
except Exception:
    KANBAN_DB = os.path.join(WORKSPACE_DIR, "data", "kanban.db")

def _to_dt(value) -> Optional[datetime.datetime]:
    """Wandelt einen Zeitstempel (Epoch-Float/Int oder ISO-String) in datetime um.

    N-06: die Kanban-DB deklariert created_at als INTEGER/Epoch; andere Quellen
    liefern ISO-Strings. fromisoformat allein uebersprang jede Zeile.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value))
    s = str(value).strip()
    try:
        return datetime.datetime.fromtimestamp(float(s))
    except ValueError as _exc:
        _archon_exc_logger.debug("[deadlock_supervisor] Ignorierte Ausnahme (Z.34): %s", _exc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


# Ein laufender LLM-Call darf 90 s dauern (agent_router timeout). Der alte
# 45-s-Stagnations-Reset hat solche Tasks als "deadlock" markiert und parallel
# erneut gestartet → doppelte E-Mails/Zahlungen. Lease TTL liegt daher darüber.
MIN_LEASE_TTL_SECONDS = 120


class DeadlockSupervisor:
    def __init__(self, db_path: str = KANBAN_DB):
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _pid_alive(pid: Any) -> bool:
        """Plattform-sichere Liveness-Prüfung.

        WICHTIG: ``os.kill(pid, 0)`` ist auf Windows KEIN harmloser
        Existenz-Check. Dort ist ``0 == signal.CTRL_C_EVENT``; der Aufruf
        stellt tatsächlich ein Ctrl+C an den Zielprozess zu (oder schlägt
        fehl), woraufhin der Supervisor den Worker fälschlich als "tot"
        markiert und den Task reaktiviert. Der 30-s-Loop könnte so laufende
        Agenten alle 30 Sekunden unterbrechen.

        Wir verwenden daher psutil (Runtime-Dependency aus requirements.txt).
        Nur wenn psutil nicht verfügbar ist, gibt es einen POSIX-Fallback;
        unter Windows gilt im Zweifel "lebendig", niemals "tot".
        """
        try:
            value = int(pid)
        except (TypeError, ValueError):
            return False
        if value <= 0:
            return False
        try:
            import psutil
            return bool(psutil.pid_exists(value))
        except Exception:  # pragma: no cover - psutil ist Runtime-Dependency
            if os.name == "nt":
                return True
            try:
                os.kill(value, 0)
                return True
            except (OSError, ValueError):
                return False

    def _ensure_lease_columns(self, conn) -> None:
        """P0-6: MC-`tasks` hatte urspruenglich keine Claim-Spalten.

        Ohne diese Migration scheiterte acquire_lease mit
        `no such column: claim_lock` und war deshalb produktiv Totcode.
        """
        try:
            cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        except sqlite3.OperationalError:
            return
        if not cols:
            return
        wanted = {
            "claim_lock": "TEXT",
            "claim_expires": "REAL",
            "worker_pid": "INTEGER",
            "last_heartbeat_at": "REAL",
            "worker_started_at": "REAL",
        }
        for name, typ in wanted.items():
            if name not in cols:
                try:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {typ}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()

    def acquire_lease(
        self,
        task_id: str,
        worker_pid: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Atomare Lease: nur wer den Claim hält, darf den Task ausführen."""
        now = time.time()
        ttl = max(MIN_LEASE_TTL_SECONDS, int(ttl_seconds or MIN_LEASE_TTL_SECONDS))
        expires = now + ttl
        token = f"{worker_pid or os.getpid()}:{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        try:
            self._ensure_lease_columns(conn)
            # P0-6: Ein Task, der nicht in der tasks-Tabelle liegt (z. B.
            # isolierte Tests, alternative Store-Implementierungen), kann
            # nicht gelockt werden — das darf aber KEIN "anderer Worker"
            # bedeuten und den Dispatch blockieren.
            task_exists = conn.execute(
                "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
            ).fetchone() is not None
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET claim_lock = ?, claim_expires = ?, worker_pid = ?, "
                    "last_heartbeat_at = ?, "
                    "worker_started_at = CASE WHEN worker_started_at IS NULL THEN ? ELSE worker_started_at END "
                    "WHERE id = ? AND status IN ('todo', 'in_progress') "
                    "AND (claim_lock IS NULL OR claim_expires IS NULL OR claim_expires <= ?)",
                    (token, expires, worker_pid or os.getpid(), now, now, task_id, now),
                )
                acquired = int(cur.rowcount or 0) == 1
                conn.commit()
            return {
                "acquired": acquired,
                "lease_token": token,
                "expires_at": expires,
                "task_exists": task_exists,
            }
        finally:
            conn.close()

    def heartbeat(self, task_id: str, lease_token: str, ttl_seconds: Optional[int] = None) -> bool:
        now = time.time()
        ttl = max(MIN_LEASE_TTL_SECONDS, int(ttl_seconds or MIN_LEASE_TTL_SECONDS))
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET last_heartbeat_at = ?, claim_expires = ? "
                    "WHERE id = ? AND claim_lock = ?",
                    (now, now + ttl, task_id, lease_token),
                )
                ok = int(cur.rowcount or 0) == 1
                conn.commit()
            return ok
        finally:
            conn.close()

    def release_lease(self, task_id: str, lease_token: str) -> bool:
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET claim_lock = NULL, claim_expires = NULL, worker_pid = NULL "
                    "WHERE id = ? AND claim_lock = ?",
                    (task_id, lease_token),
                )
                ok = int(cur.rowcount or 0) == 1
                conn.commit()
            return ok
        finally:
            conn.close()

    def detect_and_resolve_deadlocks(self, stagnation_threshold_seconds: Optional[int] = None) -> Dict[str, Any]:
        """
        Prüft laufende Tasks auf Blockaden und Stagnation.
        Setzt hängende Tasks nach Timeout kontrolliert zurück auf 'todo' mit Backoff.
        """
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("concurrency")
            if not cfg.get("auto_deadlock_recovery", True):
                return {"status": "disabled", "resolved_count": 0, "resolved_tasks": [], "message": "Deadlock-Recovery ist in den Einstellungen deaktiviert."}
            if stagnation_threshold_seconds is None:
                stagnation_threshold_seconds = int(cfg.get("stagnation_threshold_seconds", 45))
        except Exception:
            if stagnation_threshold_seconds is None:
                stagnation_threshold_seconds = 45
        # Nie unter die maximale LLM-Call-Dauer + Puffer (siehe MIN_LEASE_TTL).
        stagnation_threshold_seconds = max(int(stagnation_threshold_seconds), MIN_LEASE_TTL_SECONDS)

        if not os.path.exists(self.db_path):
            return {"status": "no_db", "resolved_count": 0, "stagnant_tasks": []}

        now = datetime.datetime.now()
        resolved = []

        conn = self._get_conn()
        try:
            with conn:
                cur = conn.cursor()
                # N-06: 'last_heartbeat_at' existiert nicht in jedem Schema —
                # Spalte optional ermitteln.
                cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
                has_heartbeat = "last_heartbeat_at" in cols
                has_claim_lock = "claim_lock" in cols
                has_worker_pid = "worker_pid" in cols
                has_claim_expires = "claim_expires" in cols
                sel = "id, title, assignee, status, created_at, body"
                if has_heartbeat:
                    sel += ", last_heartbeat_at"
                if has_claim_expires:
                    sel += ", claim_expires"
                if has_worker_pid:
                    sel += ", worker_pid"
                cur.execute(
                    f"SELECT {sel} FROM tasks WHERE status IN ('in_progress', 'blocked')"
                )
                active_tasks = cur.fetchall()

                for t in active_tasks:
                    t_id = t["id"]
                    # N-06: kanban.db speichert created_at als INTEGER (Epoch),
                    # nicht als ISO-String — fromisoformat warf, das except
                    # uebersprang jede Zeile: "Keine Deadlocks" fuer immer.
                    c_at = _to_dt(t["created_at"])
                    if c_at is None:
                        continue

                    # Stagnation ab dem LETZTEN Heartbeat messen, nicht ab
                    # Erstellung: ein legitim langer Task mit lebendem Worker
                    # wurde vorher auf 'todo' zurueckgesetzt, waehrend er noch
                    # claim_lock/worker_pid hielt (Doppelausfuehrung).
                    if has_heartbeat and t["last_heartbeat_at"]:
                        last_beacon = _to_dt(t["last_heartbeat_at"])
                        if last_beacon is not None:
                            c_at = max(c_at, last_beacon)

                    # M110 Lease/Liveness: ein noch lebender Worker wird NIE
                    # zurückgesetzt — sonst läuft ein 90-s-LLM-Call doppelt.
                    pid = t["worker_pid"] if has_worker_pid else None
                    if self._pid_alive(pid):
                        # I: Im Single-Prozess-Container ist der Worker-PID
                        # IMMER alive (gleicher Prozess wie Supervisor). Ohne
                        # Heartbeat-Prüfung würden Leases endlos verlängert.
                        # Fail-closed: nur ein frischer Heartbeat verlängert.
                        hb_fresh = False
                        if has_heartbeat and t["last_heartbeat_at"]:
                            last_hb = _to_dt(t["last_heartbeat_at"])
                            if last_hb is not None:
                                hb_fresh = (now - last_hb).total_seconds() <= MIN_LEASE_TTL_SECONDS
                        if hb_fresh:
                            if has_claim_expires:
                                conn.execute(
                                    "UPDATE tasks SET claim_expires = ? WHERE id = ?",
                                    (time.time() + MIN_LEASE_TTL_SECONDS, t_id),
                                )
                            continue
                        _archon_exc_logger.warning(
                            "[deadlock_supervisor] Task %s: PID %s lebt, aber Heartbeat "
                            "fehlt oder ist älter als %ss — Lease wird NICHT verlängert "
                            "(fail-closed).",
                            t_id, pid, MIN_LEASE_TTL_SECONDS,
                        )
                    expires = float(t["claim_expires"] or 0) if has_claim_expires else 0.0
                    if expires > time.time():
                        # Lease von einem anderen Prozess gehalten.
                        continue

                    age_sec = (now - c_at).total_seconds()
                    if age_sec > stagnation_threshold_seconds:
                        body_txt = t["body"] or ""
                        prior_resets = body_txt.count("[STAGNATION-RESOLVED:")
                        if prior_resets >= 3:
                            new_status = "failed"
                            new_body = body_txt + f"\n\n[DEADLOCK-ESCALATED: Maximale Reaktivierungen ({prior_resets}) nach {int(age_sec)}s Blockade erreicht.]"
                        else:
                            new_status = "todo"
                            new_body = body_txt + f"\n\n[STAGNATION-RESOLVED: Task nach {int(age_sec)}s Blockade vom Supervisor reaktiviert.]"
                        set_parts = ["status = ?", "body = ?"]
                        params = [new_status, new_body]
                        if has_claim_lock:
                            set_parts.append("claim_lock = NULL")
                        if has_worker_pid:
                            set_parts.append("worker_pid = NULL")
                        params.append(t_id)
                        # CAS: nur zurücksetzen, wenn die Lease immer noch
                        # abgelaufen ist — ein paralleler Worker darf nicht
                        # überschrieben werden.
                        if has_claim_expires:
                            set_clause = f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ? AND status IN ('in_progress','blocked') AND (claim_expires IS NULL OR claim_expires <= ?)"
                            params.append(time.time())
                        else:
                            set_clause = f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ? AND status IN ('in_progress','blocked')"
                        cur_reset = conn.execute(set_clause, params)
                        if int(cur_reset.rowcount or 0) != 1:
                            continue
                        resolved.append({
                            "task_id": t_id,
                            "title": t["title"],
                            "assignee": t["assignee"],
                            "stagnant_seconds": int(age_sec),
                            "new_status": new_status,
                        })
                conn.commit()

            return {
                "status": "success",
                "resolved_count": len(resolved),
                "resolved_tasks": resolved,
                "stagnation_threshold_seconds": stagnation_threshold_seconds,
                "message": f"{len(resolved)} stagnierende(r) Task(s) aufgelöst und reaktiviert." if resolved else "Keine Deadlocks oder Stagnationen festgestellt."
            }
        except Exception as e:
            return {"status": "error", "message": str(e), "resolved_count": 0}
        finally:
            conn.close()

deadlock_supervisor = DeadlockSupervisor()
