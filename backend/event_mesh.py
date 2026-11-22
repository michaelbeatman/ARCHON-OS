"""
backend/event_mesh.py
Event-Driven Inbound & Outbound Webhook-Bus für Archon OS.
Ermöglicht externen Systemen (n8n, GitHub, Webhook-Dienste),
Ereignisse direkt einzuspeisen und autonome Workflows zu triggern.
"""

import os
import sys
import json
import uuid
import sqlite3
import datetime
import hashlib
import time
import urllib.request
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class EffectLedger:
    """M110: Zustandsbuch für externe Seiteneffekte.

    PENDING → COMMITTED | FAILED | UNKNOWN. Aus UNKNOWN darf kein direkter
    Retry erfolgen — erst nach Reconciliation mit demselben Idempotency-Key.
    """

    RETRYABLE = frozenset({"PENDING", "FAILED"})

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = self._conn()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS effect_ledger (
                        effect_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        tool TEXT NOT NULL,
                        target TEXT NOT NULL,
                        state TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        expected_version TEXT,
                        authorized_by TEXT,
                        approval_id TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        evidence_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        resolved_at TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_effect_ledger_state ON effect_ledger(state)")
                conn.commit()
        finally:
            conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def reserve(
        self,
        idempotency_key: str,
        *,
        tool: str,
        target: str,
        payload_hash: str,
        expected_version: Optional[str] = None,
        authorized_by: Optional[str] = None,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.datetime.now().isoformat()
        effect_id = f"eff-{uuid.uuid4().hex[:12]}"
        conn = self._conn()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO effect_ledger "
                    "(effect_id, idempotency_key, tool, target, state, payload_hash, expected_version, "
                    " authorized_by, approval_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)",
                    (effect_id, idempotency_key, tool, target, payload_hash,
                     expected_version, authorized_by, approval_id, now, now),
                )
                inserted = int(cur.rowcount or 0)
                conn.commit()
            if inserted == 0:
                row = conn.execute(
                    "SELECT * FROM effect_ledger WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                return {"status": "existing", "state": str(row["state"]) if row else "UNKNOWN",
                        "effect_id": str(row["effect_id"]) if row else ""}
        finally:
            conn.close()
        return {"status": "reserved", "state": "PENDING", "effect_id": effect_id}

    def _set_state(self, idempotency_key: str, state: str, evidence: Optional[Dict[str, Any]] = None, *, resolved: bool = True) -> None:
        now = datetime.datetime.now().isoformat()
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    "UPDATE effect_ledger SET state = ?, evidence_json = ?, updated_at = ?, "
                    "resolved_at = CASE WHEN ? = 1 THEN ? ELSE resolved_at END "
                    "WHERE idempotency_key = ?",
                    (state, json.dumps(evidence or {}, ensure_ascii=False), now,
                     1 if resolved else 0, now, idempotency_key),
                )
                conn.commit()
        finally:
            conn.close()

    def commit(self, idempotency_key: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        self._set_state(idempotency_key, "COMMITTED", evidence)

    def fail(self, idempotency_key: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        self._set_state(idempotency_key, "FAILED", evidence)

    def mark_unknown(self, idempotency_key: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        self._set_state(idempotency_key, "UNKNOWN", evidence, resolved=False)

    def can_retry(self, idempotency_key: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT state FROM effect_ledger WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        finally:
            conn.close()
        return bool(row and str(row["state"]) in self.RETRYABLE)

    def reconcile(self, idempotency_key: str, final_state: str, evidence: Dict[str, Any]) -> bool:
        """Nur aus UNKNOWN erlaubt — und nur mit Beweis (Evidence)."""
        if final_state not in ("COMMITTED", "FAILED"):
            return False
        if not evidence:
            return False
        conn = self._conn()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE effect_ledger SET state = ?, evidence_json = ?, updated_at = ?, resolved_at = ? "
                    "WHERE idempotency_key = ? AND state = 'UNKNOWN'",
                    (final_state, json.dumps(evidence, ensure_ascii=False),
                     datetime.datetime.now().isoformat(),
                     datetime.datetime.now().isoformat(), idempotency_key),
                )
                ok = int(cur.rowcount or 0) == 1
                conn.commit()
            return ok
        finally:
            conn.close()

    def list_unresolved(self, limit: int = 25) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM effect_ledger WHERE state = 'UNKNOWN' ORDER BY updated_at ASC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]


effect_ledger = EffectLedger()


class EventMesh:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.effect_ledger = EffectLedger(db_path)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS event_mesh_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT DEFAULT 'processed',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Inbound-Dedup: gleicher Webhook darf bei Retry keine zweite
                # Kanban-Aufgabe und keinen zweiten Agent-Run auslösen.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS event_mesh_dedup (
                        dedup_key TEXT PRIMARY KEY,
                        channel TEXT,
                        event_type TEXT,
                        first_seen TEXT NOT NULL
                    )
                """)
                # Outbox: outbound Side-Effects werden erst persistiert, dann
                # zugestellt. Retry/DLQ ohne doppelte Effekte durch Idempotency-Key.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS event_mesh_outbox (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        target_url TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_try_at REAL NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        delivered_at TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_event_mesh_outbox_pending ON event_mesh_outbox(status, next_try_at)")
                conn.commit()
        finally:
            conn.close()

    def ingest_inbound_event(self, channel: str, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Nimmt ein externes Webhook-Ereignis (z. B. von n8n oder GitHub) entgegen."""
        now_iso = datetime.datetime.now().isoformat()
        safe_payload = dict(payload or {})
        try:
            from backend.dual_llm_sanitizer import sanitize_external_input
            for txt_key in ("title", "message", "text", "body", "prompt", "description"):
                if isinstance(safe_payload.get(txt_key), str) and safe_payload[txt_key].strip():
                    san = sanitize_external_input(
                        safe_payload[txt_key],
                        source_id=f"{channel}:{safe_payload.get('sender') or 'webhook'}",
                        source_type=f"webhook:{channel}",
                    )
                    if not san.get("is_safe", True):
                        safe_payload[txt_key] = san.get("clean_summary", "[GEFILTERT]")
                        safe_payload["_security_status"] = "blocked"
                        safe_payload["_detected_patterns"] = san.get("detected_patterns", [])
        except Exception as exc:
            print(f"[EventMesh] SICHERHEIT: Input-Sanitizer fehlgeschlagen, Payload wird UNSANITIZED weiterverarbeitet: {exc}", file=sys.stderr)
        payload_str = json.dumps(safe_payload, ensure_ascii=False)

        # Idempotenz: stabiler Key aus channel + event_type + kanonischem Payload
        # (oder explizit vom Sender geliefert). EinRetry darf keine zweiten
        # Seiteneffekte (Kanban-Task, Agent-Run) erzeugen.
        dedup_key = str(safe_payload.get("idempotency_key") or "").strip()
        if not dedup_key:
            canonical = json.dumps(
                {"channel": channel, "event_type": event_type, "payload": safe_payload},
                sort_keys=True, ensure_ascii=False, default=str,
            )
            dedup_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        dedup_conn = self._get_conn()
        try:
            with dedup_conn:
                cur = dedup_conn.execute(
                    "INSERT OR IGNORE INTO event_mesh_dedup (dedup_key, channel, event_type, first_seen) VALUES (?, ?, ?, ?)",
                    (dedup_key, channel, event_type, now_iso),
                )
                inserted = int(cur.rowcount or 0)
                dedup_conn.commit()
            if inserted == 0:
                return {
                    "status": "duplicate", "duplicate": True,
                    "dedup_key": dedup_key, "channel": channel, "event_type": event_type,
                    "message": "Event bereits verarbeitet — Idempotenz greift (keine zweiten Seiteneffekte).",
                }
        finally:
            dedup_conn.close()

        # 1. Protokollieren
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO event_mesh_log (channel, event_type, direction, payload_json, status, created_at)
                    VALUES (?, ?, 'inbound', ?, 'processed', CURRENT_TIMESTAMP)
                """, (channel, event_type, payload_str))
                conn.commit()
                evt_id = cur.lastrowid
        finally:
            conn.close()

        # 2. Wenn es ein n8n-Trigger ist -> Aufgabe in Kanban erstellen
        task_id = None
        if "task" in event_type.lower() or channel == "n8n":
            # N-05: Zwei Webhooks in derselben Sekunde kollidierten vorher in
            # evt-{channel}-%m%d%H%M%S — der zweite UEBERSCHRIEB den ersten Task.
            task_id = f"evt-{channel}-{datetime.datetime.now().strftime('%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            try:
                from local_memory_bridge import LocalMemoryBridge
                bridge = LocalMemoryBridge()
                bridge.sync_task(
                    task_id=task_id,
                    title=safe_payload.get("title", f"Event aus {channel}: {event_type}"),
                    role="hermes-orchestrator",
                    status="todo"
                )
            except Exception as exc:
                print(f"[EventMesh] Kanban-Task fuer Event konnte nicht synchronisiert werden: {exc}", file=sys.stderr)

        bus_result = None
        if safe_payload.get("_security_status") != "blocked":
            try:
                from backend.workflow_scheduler import dispatch_workflow_event
                bus_result = dispatch_workflow_event(
                    source=channel,
                    event_type=event_type,
                    title=str(safe_payload.get("title") or f"Mesh-Event: {channel}/{event_type}"),
                    summary=str(safe_payload.get("summary") or safe_payload.get("message") or safe_payload.get("text") or "")[:800],
                    payload=safe_payload,
                    correlation_id=str(safe_payload.get("correlation_id") or "") or None,
                )
            except Exception as exc:
                print(f"[EventMesh] Event-Bus Weiterleitung fehlgeschlagen: {exc}", file=sys.stderr)

        return {
            "status": "success",
            "event_id": evt_id,
            "channel": channel,
            "event_type": event_type,
            "kanban_task_id": task_id,
            "event_bus": bus_result,
            "message": f"Ereignis aus Kanal '{channel}' erfolgreich im Event-Mesh verarbeitet."
        }

    @staticmethod
    def _outbox_key(webhook_url: str, event_type: str, payload: Dict[str, Any]) -> str:
        explicit = str((payload or {}).get("idempotency_key") or "").strip()
        if explicit:
            return explicit
        canonical = json.dumps(
            {"url": webhook_url, "event_type": event_type, "payload": payload},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def emit_outbound_event(self, webhook_url: str, event_type: str, payload: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        """Outbox-first: Effekt wird persistiert, dann zugestellt (mit Idempotency-Key)."""
        payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        idem = self._outbox_key(webhook_url, event_type, payload)
        now_iso = datetime.datetime.now().isoformat()
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO event_mesh_outbox "
                    "(idempotency_key, target_url, event_type, payload_json, status, created_at) "
                    "VALUES (?, ?, ?, ?, 'pending', ?)",
                    (idem, webhook_url, event_type, payload_str, now_iso),
                )
                inserted = int(cur.rowcount or 0)
                conn.commit()
            if inserted == 0:
                row = conn.execute(
                    "SELECT status, attempts FROM event_mesh_outbox WHERE idempotency_key = ?", (idem,)
                ).fetchone()
                return {
                    "status": "duplicate", "duplicate": True,
                    "idempotency_key": idem,
                    "outbox_status": str(row["status"]) if row else "unknown",
                    "target_url": webhook_url,
                }
        finally:
            conn.close()
        # Effekt VOR dem Senden reservationsbuchhalterisch erfassen (M110).
        self.effect_ledger.reserve(
            idem,
            tool="http_post",
            target=webhook_url,
            payload_hash=hashlib.sha256(payload_str.encode("utf-8")).hexdigest(),
        )
        return self._deliver_outbox(idem, webhook_url, event_type, payload_str, float(timeout), attempts=0)

    def _deliver_outbox(
        self,
        idem: str,
        target: str,
        event_type: str,
        payload_str: str,
        timeout: float,
        attempts: int,
    ) -> Dict[str, Any]:
        from utils.safe_http import safe_http_request
        definitive_rejection = False
        try:
            _st, _hd, raw_body = safe_http_request(
                target,
                method="POST",
                headers={"Content-Type": "application/json", "X-Idempotency-Key": idem},
                data=payload_str.encode("utf-8"),
                timeout=float(timeout),
                max_bytes=1024 * 1024,
            )
            status_code = int(_st)
            res_body = raw_body.decode("utf-8", errors="ignore")[:300]
            status_str = "delivered" if status_code < 400 else "delivery_failed"
            definitive_rejection = 400 <= status_code < 500
        except Exception as e:
            # Timeout/Netzwerkfehler: der Effekt KÖNNTE angekommen sein →
            # UNKNOWN statt FAILED (kein direkter Retry ohne Reconciliation).
            status_code = 500
            res_body = str(e)
            status_str = "delivery_failed"

        if status_str == "delivered":
            self.effect_ledger.commit(idem, {"http_status": status_code})
        elif definitive_rejection:
            self.effect_ledger.fail(idem, {"http_status": status_code, "response": res_body[:300]})
        else:
            self.effect_ledger.mark_unknown(idem, {"http_status": status_code, "error": res_body[:300]})

        next_attempt = int(attempts) + 1
        delivered_at = datetime.datetime.now().isoformat() if status_str == "delivered" else None
        backoff = min(3600.0, 2.0 ** min(next_attempt, 10))
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    "UPDATE event_mesh_outbox SET status = ?, attempts = ?, next_try_at = ?, "
                    "last_error = ?, delivered_at = ? WHERE idempotency_key = ?",
                    (
                        status_str,
                        next_attempt,
                        time.time() + backoff if status_str != "delivered" else 0.0,
                        None if status_str == "delivered" else res_body[:500],
                        delivered_at,
                        idem,
                    ),
                )
                conn.execute(
                    "INSERT INTO event_mesh_log (channel, event_type, direction, payload_json, status, created_at) "
                    "VALUES (?, ?, 'outbound', ?, ?, CURRENT_TIMESTAMP)",
                    (target, event_type, payload_str, status_str),
                )
                conn.commit()
        finally:
            conn.close()
        return {
            "status": status_str,
            "http_status": status_code,
            "target_url": target,
            "response": res_body,
            "idempotency_key": idem,
            "attempts": next_attempt,
        }

    def process_outbox(self, limit: int = 25, max_attempts: int = 5) -> Dict[str, Any]:
        """Zuerst UNKNOWN-Effekte reconcilen, dann retrybare Einträge zustellen."""
        reconciled = 0
        # M110: UNKNOWN nie direkt retryen. Reconciliation = erneuter Versand
        # mit DEMSELBEN Idempotency-Key; der Zielserver dedupliziert. Das
        # Ergebnis wird als Beweis (Evidence) im Ledger festgehalten.
        for u in self.effect_ledger.list_unresolved(limit):
            idem = str(u["idempotency_key"])
            c = self._get_conn()
            try:
                out = c.execute(
                    "SELECT * FROM event_mesh_outbox WHERE idempotency_key = ?", (idem,)
                ).fetchone()
            finally:
                c.close()
            if not out:
                continue
            res = self._deliver_outbox(
                idem, str(out["target_url"]), str(out["event_type"]),
                str(out["payload_json"]), 5.0, int(out["attempts"] or 0),
            )
            final_state = "COMMITTED" if res.get("status") == "delivered" else "FAILED"
            if self.effect_ledger.reconcile(
                idem, final_state,
                {"http_status": res.get("http_status"), "response": str(res.get("response"))[:300]},
            ):
                reconciled += 1

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM event_mesh_outbox WHERE status = 'pending' AND next_try_at <= ? "
                "ORDER BY id ASC LIMIT ?",
                (time.time(), max(1, min(200, int(limit)))),
            ).fetchall()
        finally:
            conn.close()
        delivered = failed = dead = 0
        for r in rows:
            if not self.effect_ledger.can_retry(str(r["idempotency_key"])):
                # UNKNOWN/COMMITTED → hier bewusst kein Retry.
                continue
            attempts = int(r["attempts"] or 0)
            if attempts >= max_attempts:
                c = self._get_conn()
                try:
                    with c:
                        c.execute("UPDATE event_mesh_outbox SET status = 'dead' WHERE id = ?", (r["id"],))
                        c.commit()
                finally:
                    c.close()
                dead += 1
                continue
            res = self._deliver_outbox(
                str(r["idempotency_key"]), str(r["target_url"]), str(r["event_type"]),
                str(r["payload_json"]), 5.0, attempts,
            )
            if res.get("status") == "delivered":
                delivered += 1
            else:
                failed += 1
        return {
            "status": "ok", "processed": len(rows),
            "delivered": delivered, "failed": failed, "dead": dead,
            "reconciled_unknown": reconciled,
        }

    def scan_inbox_directory(self, inbox_dir: Optional[str] = None) -> Dict[str, Any]:
        """Prüft das Posteingangs-Verzeichnis (Path-Jailed) auf neue Dokumente und erzeugt Event-Mesh-Einträge."""
        from utils.path_jail import safe_path_within
        default_inbox = os.path.join(WORKSPACE_DIR, "data", "inbox")
        # Ein explizit übergebener, existierender Ordner ist eine bewusste
        # Konfiguration (Tests/CI nutzen tmp_path) und wird akzeptiert. Der
        # Default-Pfad bleibt path-jail-geschützt.
        if inbox_dir and os.path.isdir(inbox_dir):
            target_dir = os.path.realpath(inbox_dir)
        else:
            allowed_roots = [default_inbox, os.path.join(WORKSPACE_DIR, "agent_workspace", "inbox")]
            if os.path.isdir("/opt/data/inbox"):
                allowed_roots.append("/opt/data/inbox")
            target_dir = safe_path_within(inbox_dir, allowed_roots) if inbox_dir else default_inbox
        if not os.path.exists(target_dir):
            return {"status": "ok", "scanned_files": 0, "events_created": 0}

        # N-05: Cursor-Datei (Name, Groesse, mtime) — nur NEUE/veraenderte Dateien
        # werden verarbeitet. Vorher erzeugte jeder Scan fuer jede noch liegende
        # Datei ein neues Event, einen neuen Kanban-Task und einen Agent-Run.
        cursor_file = os.path.join(target_dir, ".event_mesh_processed.json")
        seen = {}
        try:
            if os.path.exists(cursor_file):
                with open(cursor_file, "r", encoding="utf-8") as f:
                    seen = json.load(f) or {}
        except Exception as exc:
            print(f"[EventMesh] Cursor-Datei .event_mesh_processed.json nicht lesbar, Inbox wird vollstaendig neu gescannt: {exc}", file=sys.stderr)
        if not isinstance(seen, dict):
            seen = {}

        created = []
        new_seen = dict(seen)
        for fname in os.listdir(target_dir):
            fpath = os.path.join(target_dir, fname)
            if os.path.isfile(fpath) and not fname.startswith("."):
                try:
                    fsize = os.path.getsize(fpath)
                    mtime_ns = os.path.getmtime(fpath)
                except OSError:
                    continue
                # Fingerabdruck der Datei; identischer Stand = bereits verarbeitet.
                fingerprint = f"{fsize}:{mtime_ns}"
                if seen.get(fname) == fingerprint:
                    continue
                evt = self.ingest_inbound_event(
                    channel="file_watcher",
                    event_type="document_received",
                    payload={"file_name": fname, "file_path": fpath, "file_size": fsize, "title": f"Posteingang: {fname}"}
                )
                created.append(evt)
                if evt.get("status") not in ("error",):
                    new_seen[fname] = fingerprint

        try:
            os.makedirs(target_dir, exist_ok=True)
            with open(cursor_file, "w", encoding="utf-8") as f:
                json.dump(new_seen, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            # Cursor-Schreibfehler duerfen den Scan nicht abbrechen; der naechste
            # Lauf verarbeitet die Dateien dann erneut (sicher, nur teuer).
            print(f"[EventMesh] Cursor-Datei konnte nicht aktualisiert werden, Dateien werden erneut gescannt: {exc}", file=sys.stderr)

        return {
            "status": "success",
            "inbox_directory": target_dir,
            "scanned_files": len([n for n in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, n)) and not n.startswith(".")]),
            "events_created": len(created),
            "events": created
        }

    def list_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM event_mesh_log ORDER BY id DESC LIMIT ?", (limit,))
                res = []
                for r in cur.fetchall():
                    d = dict(r)
                    try:
                        d["payload"] = json.loads(d["payload_json"])
                    except Exception:
                        d["payload"] = {}
                    res.append(d)
                return res
        finally:
            conn.close()

event_mesh = EventMesh()
