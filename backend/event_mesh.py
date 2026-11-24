"""
backend/event_mesh.py
Event-Driven Inbound & Outbound Webhook-Bus für Archon OS.
Ermöglicht externen Systemen (n8n, GitHub, Webhook-Dienste),
Ereignisse direkt einzuspeisen und autonome Workflows zu triggern.
"""

import os
import sys
import contextlib
import json
import uuid
import sqlite3
import datetime
import hashlib
import time
import urllib.request
import logging
import random
from typing import Dict, Any, List, Optional

logger = logging.getLogger("archon_os.event_mesh")

# Re-Audit D05/M: verschluckte GoBD-Audit-Fehler sind messbar zu machen
# (Vorbild backend/egress_firewall.py:_AUDIT_ERROR_COUNTS).
_AUDIT_ERROR_COUNTS: Dict[str, int] = {}


def get_audit_error_counts() -> Dict[str, int]:
    """Lesender Zugriff auf die Audit-Schreibfehler-Zaehler (Status/Test)."""
    return dict(_AUDIT_ERROR_COUNTS)


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _webhook_target_host(url: str) -> str:
    """Nur den Hostnamen fuer Audit-Metadaten — nie Query/Parameter (Tokens)."""
    try:
        from urllib.parse import urlparse
        return (urlparse(str(url or "")).hostname or "unknown").lower()
    except Exception:
        return "unknown"


def _audit_webhook_event(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """D5/F-08: Webhook-Inbound/Outbox in die Zentralkette (append-only).

    Fail-closed: die Zustell-/Verarbeitungsentscheidung ist bereits getroffen.
    Ein Audit-Fehler darf keine Exception in den Ledger-/Outbox-Flow werfen;
    er wird geloggt und im Result-Feld sichtbar gemacht. Protokolliert werden
    nur IDs/Status/Metadaten — niemals Payload, URL-Query oder Signaturheader.
    """
    try:
        from backend.audit_log import chained_audit_log

        event = chained_audit_log.record_event(
            category="webhook",
            action=action,
            agent_id=str(payload.get("actor") or "event_mesh"),
            payload=payload,
        )
        return {"audit_status": "recorded", "audit_event_id": event.get("event_id")}
    except Exception as exc:
        # D05/M: ERROR + Zaehler statt eines blossen Result-Feldes, damit der
        # GoBD-Verlust auch ohne Result-Inspection sichtbar/verfolgbar bleibt.
        _AUDIT_ERROR_COUNTS[action] = _AUDIT_ERROR_COUNTS.get(action, 0) + 1
        logger.error(
            "[GoBD-Audit] '%s' fehlgeschlagen (count=%d): %s",
            action, _AUDIT_ERROR_COUNTS[action], exc,
        )
        return {
            "audit_status": "error",
            "audit_error": type(exc).__name__,
            "audit_error_count": _AUDIT_ERROR_COUNTS[action],
        }


_TRACE_COLS = ("trace_id", "span_id", "traceparent", "tracestate")


@contextlib.contextmanager
def _outbound_child_span() -> Any:
    """D16: Outbound-Hook — ein eigener Child-Span pro Systemgrenze."""
    try:
        from backend import trace_context as tc
    except Exception as exc:
        logger.warning("[EventMesh] trace_context nicht verfügbar: %s", exc)
        yield {}
        return
    with tc.child_span() as (tid, sid, _parent_sid):
        yield {
            "trace_id": tid,
            "span_id": sid,
            "traceparent": tc.format_traceparent(tid, sid, tc.should_sample()),
            "tracestate": tc.sanitize_tracestate(tc.current_tracestate()),
        }


def _restored_trace_columns(cols: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Nur gültige, gespeicherte Trace-Werte weiterverwenden (Retry/DLQ)."""
    out = {k: str((cols or {}).get(k) or "") for k in _TRACE_COLS}
    if out["traceparent"]:
        try:
            from backend.trace_context import parse_traceparent
            if not parse_traceparent(out["traceparent"]):
                out["traceparent"] = ""
        except Exception:
            out["traceparent"] = ""
    return out


def _row_trace_columns(row: Any) -> Dict[str, Any]:
    """Liest Trace-Spalten aus sqlite3.Row oder Dict (auch ältere Zeilen)."""
    data = dict(row) if not isinstance(row, dict) else row
    return _restored_trace_columns({k: data.get(k) for k in _TRACE_COLS})


def _traced_payload_str(payload: Dict[str, Any], trace: Dict[str, Any]) -> str:
    """Payload mit dem persistierten Trace-Kontext non-destruktiv anreichern."""
    try:
        from backend import trace_context as tc
        with tc.use_trace_context(
            trace_id=trace.get("trace_id"), span_id=trace.get("span_id"),
            traceparent=trace.get("traceparent"), tracestate=trace.get("tracestate"),
        ):
            data = tc.inject_payload(payload)
    except Exception as exc:
        logger.warning("[EventMesh] Payload-Trace fehlgeschlagen: %s", exc)
        data = dict(payload or {})
        if trace.get("trace_id") and "trace_id" not in data:
            data["trace_id"] = trace["trace_id"]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


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
                        delivered_at TEXT,
                        trace_id TEXT,
                        span_id TEXT,
                        traceparent TEXT,
                        tracestate TEXT
                    )
                """)
                # P2: CAS-Claim gegen parallele Worker. Ohne Claim lesen zwei
                # Prozesse dieselbe Zeile und posten denselben Webhook doppelt.
                # D16: Trace-Spalten bestandskompatibel per ALTER (keine Migration).
                cols = {r[1] for r in conn.execute("PRAGMA table_info(event_mesh_outbox)").fetchall()}
                for col, decl in (
                    ("claimed_by", "TEXT"), ("claim_expires", "REAL"),
                    ("trace_id", "TEXT"), ("span_id", "TEXT"),
                    ("traceparent", "TEXT"), ("tracestate", "TEXT"),
                ):
                    if cols and col not in cols:
                        conn.execute(f"ALTER TABLE event_mesh_outbox ADD COLUMN {col} {decl}")
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
            # KRITISCH (Audit 23.11.2026): ein fehlgeschlagener Sanitizer darf
            # NEVER fail-open. Kein Log, kein Kanban-Task, kein Event-Bus.
            logger.error("[EventMesh] Sanitizer fehlgeschlagen — Event blockiert: %s", exc)
            blocked_key = hashlib.sha256(json.dumps(
                {"channel": channel, "event_type": event_type, "payload": safe_payload},
                sort_keys=True, ensure_ascii=False, default=str,
            ).encode("utf-8")).hexdigest()
            return {
                "status": "blocked",
                "blocked": True,
                "channel": channel,
                "event_type": event_type,
                "reason": "input_sanitizer_unavailable",
                **_audit_webhook_event("webhook_received", {
                    "direction": "inbound",
                    "channel": channel,
                    "event_type": event_type,
                    "idempotency_key": blocked_key,
                    "status": "blocked",
                    "reason": "input_sanitizer_unavailable",
                }),
            }
        payload_str = json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))

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
                    **_audit_webhook_event("webhook_received", {
                        "direction": "inbound",
                        "channel": channel,
                        "event_type": event_type,
                        "idempotency_key": dedup_key,
                        "status": "duplicate",
                    }),
                }
        finally:
            dedup_conn.close()

        side_effect_errors: List[str] = []

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
                side_effect_errors.append(f"kanban_task: {exc}")
                logger.error("[EventMesh] Kanban-Task fuer Event fehlgeschlagen: %s", exc)

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
                side_effect_errors.append(f"event_bus: {exc}")
                logger.error("[EventMesh] Event-Bus Weiterleitung fehlgeschlagen: %s", exc)

        if side_effect_errors:
            # KRITISCH (Audit 23.11.2026): Dedup-Eintrag zurücknehmen, sonst
            # wird einRetry als 'duplicate' abgewiesen und der Effekt fehlt
            # dauerhaft.
            try:
                dd = self._get_conn()
                with dd:
                    dd.execute("DELETE FROM event_mesh_dedup WHERE dedup_key = ?", (dedup_key,))
                dd.close()
            except Exception as exc:
                logger.error("[EventMesh] Dedup-Rollback fehlgeschlagen: %s", exc)
            return {
                "status": "partial_failure",
                "partial_failure": True,
                "errors": side_effect_errors,
                "event_id": evt_id,
                "channel": channel,
                "event_type": event_type,
                "dedup_key": dedup_key,
                **_audit_webhook_event("webhook_received", {
                    "direction": "inbound",
                    "channel": channel,
                    "event_type": event_type,
                    "idempotency_key": dedup_key,
                    "event_id": evt_id,
                    "status": "partial_failure",
                    "security_status": str(safe_payload.get("_security_status") or "ok"),
                }),
            }

        return {
            "status": "success",
            "event_id": evt_id,
            "channel": channel,
            "event_type": event_type,
            "kanban_task_id": task_id,
            "event_bus": bus_result,
            "message": f"Ereignis aus Kanal '{channel}' erfolgreich im Event-Mesh verarbeitet.",
            **_audit_webhook_event("webhook_received", {
                "direction": "inbound",
                "channel": channel,
                "event_type": event_type,
                "idempotency_key": dedup_key,
                "event_id": evt_id,
                "status": "success",
                "security_status": str(safe_payload.get("_security_status") or "ok"),
                "kanban_created": bool(task_id),
            }),
        }

    @staticmethod
    def _outbox_key(webhook_url: str, event_type: str, payload: Dict[str, Any]) -> str:
        clean = {k: v for k, v in (payload or {}).items() if k not in _TRACE_COLS}
        explicit = str(clean.get("idempotency_key") or "").strip()
        if explicit:
            return explicit
        canonical = json.dumps(
            {"url": webhook_url, "event_type": event_type, "payload": clean},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def emit_outbound_event(
        self, webhook_url: str, event_type: str, payload: Dict[str, Any], timeout: float = 5.0,
        *, trace_columns: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Outbox-first: Effekt wird persistiert, dann zugestellt (mit Idempotency-Key).

        D16: Der Trace-Kontext wird in der Outbox gespeichert und bei Retry/DLQ
        re-injiziert. ``trace_columns`` wird von DLQ-Replays übergeben.
        """
        base_payload = dict(payload or {})
        # Idempotenz bleibt stabil: Trace-Felder zählen nicht zum Payload-Key.
        idem = self._outbox_key(webhook_url, event_type, base_payload)
        if trace_columns is None:
            with _outbound_child_span() as stored:
                trace = _restored_trace_columns(stored)
        else:
            trace = _restored_trace_columns(trace_columns)
        # H5: kompakte Serialisierung, damit der n8n-Empfaenger mit
        # JSON.stringify() exakt denselben Bytes-String signiert.
        payload_str = _traced_payload_str(base_payload, trace)
        now_iso = datetime.datetime.now().isoformat()
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO event_mesh_outbox "
                    "(idempotency_key, target_url, event_type, payload_json, status, created_at, "
                    " trace_id, span_id, traceparent, tracestate) "
                    "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                    (
                        idem, webhook_url, event_type, payload_str, now_iso,
                        trace["trace_id"], trace["span_id"], trace["traceparent"], trace["tracestate"],
                    ),
                )
                inserted = int(cur.rowcount or 0)
                conn.commit()
            # DLQ-Replay (trace_columns gesetzt) deliveries bewusst erneut —
            # gleicher Idempotency-Key, aber wiederhergestellter Trace-Kontext.
            if inserted == 0 and trace_columns is None:
                row = conn.execute(
                    "SELECT status, attempts FROM event_mesh_outbox WHERE idempotency_key = ?", (idem,)
                ).fetchone()
                return {
                    "status": "duplicate", "duplicate": True,
                    "idempotency_key": idem,
                    "outbox_status": str(row["status"]) if row else "unknown",
                    "target_url": webhook_url,
                    **_audit_webhook_event("webhook_delivered", {
                        "direction": "outbound",
                        "event_type": event_type,
                        "idempotency_key": idem,
                        "status": "duplicate",
                        "outbox_status": str(row["status"]) if row else "unknown",
                        "target_host": _webhook_target_host(webhook_url),
                        "http_status": 0,
                    }),
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
        return self._deliver_outbox(
            idem, webhook_url, event_type, payload_str, float(timeout), attempts=0,
            trace_columns=trace,
        )

    def _deliver_outbox(
        self,
        idem: str,
        target: str,
        event_type: str,
        payload_str: str,
        timeout: float,
        attempts: int,
        update_ledger: bool = True,
        trace_columns: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # P0-7b: Bei der UNKNOWN-Reconciliation darf _deliver_outbox den
        # Ledger-Zustand NICHT selbst aendern — sonst trifft reconcile() mit
        # WHERE state='UNKNOWN' auf 0 Zeilen und der Fall bleibt ungeklaert.
        from utils.safe_http import safe_http_request, webhook_signature_headers
        definitive_rejection = False
        retry_after_sec = 0.0
        try:
            body_bytes = payload_str.encode("utf-8")
            headers = {"Content-Type": "application/json", "X-Idempotency-Key": idem}
            # D16: Re-Injektion des persistierten Kontexts als Child-Span —
            # der Drainer läuft ohne Request-Kontext (Retry/DLQ inklusive).
            trace = _restored_trace_columns(trace_columns)
            try:
                from backend import trace_context as tc
                with tc.use_trace_context(
                    trace_id=trace["trace_id"], span_id=trace["span_id"],
                    traceparent=trace["traceparent"], tracestate=trace["tracestate"],
                ):
                    with tc.child_span(incoming=trace["traceparent"] or None):
                        headers = tc.inject_headers(headers)
            except Exception as exc:
                logger.warning("[EventMesh] Trace-Header fehlgeschlagen: %s", exc)
            headers.update(webhook_signature_headers(body_bytes))
            _st, _hd, raw_body = safe_http_request(
                target,
                method="POST",
                headers=headers,
                data=body_bytes,
                timeout=float(timeout),
                max_bytes=1024 * 1024,
            )
            status_code = int(_st)
            res_body = raw_body.decode("utf-8", errors="ignore")[:300]
            # G: Retry-After (vom Server vorgegebene Wartezeit) respektieren.
            ra = _hd.get("retry-after") if isinstance(_hd, dict) else None
            if ra:
                try:
                    retry_after_sec = max(0.0, float(ra))
                except (TypeError, ValueError):
                    pass  # HTTP-Datum o. a.: nicht interpretierbar → Jitter-Backoff
            status_str = "delivered" if status_code < 400 else ("dead" if 400 <= status_code < 500 else "delivery_failed")
            definitive_rejection = 400 <= status_code < 500
        except Exception as e:
            # Timeout/Netzwerkfehler: der Effekt KÖNNTE angekommen sein →
            # UNKNOWN statt FAILED (kein direkter Retry ohne Reconciliation).
            status_code = 500
            res_body = str(e)
            status_str = "delivery_failed"

        if update_ledger:
            if status_str == "delivered":
                self.effect_ledger.commit(idem, {"http_status": status_code})
            elif definitive_rejection:
                self.effect_ledger.fail(idem, {"http_status": status_code, "response": res_body[:300]})
            else:
                self.effect_ledger.mark_unknown(idem, {"http_status": status_code, "error": res_body[:300]})

        next_attempt = int(attempts) + 1
        delivered_at = datetime.datetime.now().isoformat() if status_str == "delivered" else None
        # G: Jitter verhindert Thundering Herd bei parallelen Workern.
        backoff = min(3600.0, (2.0 ** min(next_attempt, 10)) * random.uniform(0.75, 1.25))
        if retry_after_sec > 0:
            backoff = min(3600.0, max(backoff, retry_after_sec * random.uniform(0.75, 1.25)))
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    "UPDATE event_mesh_outbox SET status = ?, attempts = ?, next_try_at = ?, "
                    "last_error = ?, delivered_at = ? WHERE idempotency_key = ?",
                    (
                        status_str,
                        next_attempt,
                        time.time() + backoff if status_str == "delivery_failed" else 0.0,
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
            **_audit_webhook_event("webhook_delivered", {
                "direction": "outbound",
                "event_type": event_type,
                "idempotency_key": idem,
                "status": status_str,
                "http_status": status_code,
                "target_host": _webhook_target_host(target),
                "attempts": next_attempt,
                "ledger_updated": bool(update_ledger),
            }),
        }

    def process_outbox(self, limit: int = 25, max_attempts: int = 5) -> Dict[str, Any]:
        """Zuerst UNKNOWN-Effekte reconcilen, dann retrybare Einträge zustellen."""
        reconciled = 0
        worker_id = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
        claim_ttl = 120.0
        unknown_claimed_skipped = 0
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
            # F: CAS-Claim auch für UNKNOWN-Zeilen — sonst stellt ein
            # paralleler process_outbox()-Lauf denselben HTTP-Call doppelt zu.
            c = self._get_conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                cur = c.execute(
                    "UPDATE event_mesh_outbox SET claimed_by = ?, claim_expires = ? "
                    "WHERE idempotency_key = ? "
                    "AND (claimed_by IS NULL OR claim_expires IS NULL OR claim_expires <= ?)",
                    (worker_id, time.time() + claim_ttl, idem, time.time()),
                )
                got_claim = int(cur.rowcount or 0) == 1
                c.commit()
            finally:
                c.close()
            if not got_claim:
                unknown_claimed_skipped += 1
                continue
            try:
                res = self._deliver_outbox(
                    idem, str(out["target_url"]), str(out["event_type"]),
                    str(out["payload_json"]), 5.0, int(out["attempts"] or 0),
                    update_ledger=False,  # P0-7b: Ledger bleibt UNKNOWN bis reconcile()
                    trace_columns=_row_trace_columns(out),
                )
                final_state = "COMMITTED" if res.get("status") == "delivered" else "FAILED"
                if self.effect_ledger.reconcile(
                    idem, final_state,
                    {"http_status": res.get("http_status"), "response": str(res.get("response"))[:300]},
                ):
                    reconciled += 1
            finally:
                self._release_outbox_claim(int(out["id"]), worker_id)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                # P0-7a: 'delivery_failed' war Endstatus statt Retry-Zustand —
                # der erste 5xx/Timeout wurde nie erneut zugestellt.
                "SELECT * FROM event_mesh_outbox WHERE status IN ('pending', 'delivery_failed') "
                "AND next_try_at <= ? ORDER BY id ASC LIMIT ?",
                (time.time(), max(1, min(200, int(limit)))),
            ).fetchall()
        finally:
            conn.close()
        delivered = failed = dead = claimed_skipped = 0
        for r in rows:
            # P2: atomarer CAS-Claim — genau ein Worker darf diese Zeile
            # zustellen. Ein abgelaufener Claim (abgestuerzter Worker) darf
            # uebernommen werden.
            c = self._get_conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                cur = c.execute(
                    "UPDATE event_mesh_outbox SET claimed_by = ?, claim_expires = ? "
                    "WHERE id = ? AND status IN ('pending', 'delivery_failed') "
                    "AND next_try_at <= ? "
                    "AND (claimed_by IS NULL OR claim_expires IS NULL OR claim_expires <= ?)",
                    (worker_id, time.time() + claim_ttl, r["id"], time.time(), time.time()),
                )
                got_claim = int(cur.rowcount or 0) == 1
                c.commit()
            finally:
                c.close()
            if not got_claim:
                claimed_skipped += 1
                continue

            if not self.effect_ledger.can_retry(str(r["idempotency_key"])):
                # UNKNOWN/COMMITTED → hier bewusst kein Retry. Claim freigeben.
                self._release_outbox_claim(r["id"], worker_id)
                continue
            attempts = int(r["attempts"] or 0)
            if attempts >= max_attempts:
                c = self._get_conn()
                try:
                    with c:
                        c.execute(
                            "UPDATE event_mesh_outbox SET status = 'dead', claimed_by = NULL, claim_expires = NULL WHERE id = ?",
                            (r["id"],),
                        )
                        c.commit()
                finally:
                    c.close()
                dead += 1
                # D5/F-08: auch das endgueltige Aufgeben (DLQ) ist ein
                # signiertes Delivery-Ereignis — kein stilles Verschwinden.
                _audit_webhook_event("webhook_delivered", {
                    "direction": "outbound",
                    "event_type": str(r["event_type"] or ""),
                    "idempotency_key": str(r["idempotency_key"] or ""),
                    "status": "dead",
                    "outbox_id": int(r["id"]),
                    "attempts": attempts,
                    "target_host": _webhook_target_host(str(r["target_url"] or "")),
                    "http_status": 0,
                })
                # Ein 'dead'-Outbox-Eintrag darf nicht einfach vergessen werden:
                # mit demselben Idempotency-Key in die DLQ stellen, damit der
                # Shared-Queue-Consumer ihn erneut zustellen/replayen kann.
                try:
                    from backend.dead_letter_queue import dead_letter_queue_manager as _dlq
                    try:
                        dead_payload = json.loads(str(r["payload_json"] or "{}"))
                    except (ValueError, TypeError):
                        dead_payload = {}
                    _dlq.enqueue_task(
                        job_type="webhook_delivery",
                        source_module="backend.event_mesh",
                        payload={
                            "outbox_id": r["id"],
                            "target_url": str(r["target_url"] or ""),
                            "event_type": str(r["event_type"] or ""),
                            "payload": dead_payload,
                            "attempts": attempts,
                            "last_error": str(r["last_error"] or "")[:500],
                            **_row_trace_columns(r),
                        },
                        priority=2,
                        idempotency_key=str(r["idempotency_key"] or f"outbox-dead-{r['id']}"),
                    )
                except Exception as exc:
                    logger.warning("[EventMesh] DLQ-Enqueue fuer dead-Outbox %s fehlgeschlagen: %s", r["id"], exc)
                continue
            res = self._deliver_outbox(
                str(r["idempotency_key"]), str(r["target_url"]), str(r["event_type"]),
                str(r["payload_json"]), 5.0, attempts,
                trace_columns=_row_trace_columns(r),
            )
            # Claim nach Zustellung freigeben (Erfolg wie Fehler — der Status
            # in _deliver_outbox entscheidet ueber Retry).
            self._release_outbox_claim(r["id"], worker_id)
            if res.get("status") == "delivered":
                delivered += 1
            else:
                failed += 1
        return {
            "status": "ok", "processed": len(rows),
            "delivered": delivered, "failed": failed, "dead": dead,
            "reconciled_unknown": reconciled,
            "claimed_skipped": claimed_skipped,
            "unknown_claimed_skipped": unknown_claimed_skipped,
        }

    def _release_outbox_claim(self, row_id: int, worker_id: str) -> None:
        """Gibt einen Claim nur fuer den eigenen Worker frei."""
        try:
            c = self._get_conn()
            try:
                with c:
                    c.execute(
                        "UPDATE event_mesh_outbox SET claimed_by = NULL, claim_expires = NULL "
                        "WHERE id = ? AND claimed_by = ?",
                        (row_id, worker_id),
                    )
                    c.commit()
            finally:
                c.close()
        except Exception as exc:
            logger.warning("[EventMesh] Claim-Release fehlgeschlagen: %s", exc)

    def scan_inbox_directory(
        self,
        inbox_dir: Optional[str] = None,
        *,
        channel: str = "file_watcher",
    ) -> Dict[str, Any]:
        """Prüft das Posteingangs-Verzeichnis (Path-Jailed) auf neue Dokumente und erzeugt Event-Mesh-Einträge.

        Einzige Dedup-Strategie ist die Cursor-Datei `.event_mesh_processed.json`.
        `channel` erlaubt es dem Inbox-Watcher, denselben Scan unter `inbox`
        laufen zu lassen (statt einen zweiten, konkurrierenden Scanner zu betreiben).
        """
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
                    channel=channel or "file_watcher",
                    event_type="document_received",
                    payload={"file_name": fname, "file_path": fpath, "file_size": fsize, "title": f"Posteingang: {fname}"}
                )
                evt = dict(evt)
                # Datei-Kontext zurueckgeben, damit der Inbox-Watcher nur
                # verschieben muss, statt den Scanner zu duplizieren.
                evt["file_name"] = fname
                evt["file_path"] = fpath
                evt["file_size"] = fsize
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
