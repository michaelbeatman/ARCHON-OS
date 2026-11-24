"""
backend/handoff_desk.py
Standardisierter Agent-to-Agent Handoff-Desk (Pillar 2).
Erstellt bei Rollenübergaben (z. B. Researcher an Coder) ein formales Übergabe-Dokument
mit Prüfsumme, Annahmen und Akzeptanzkriterien gegen Informationsverlust.

Batch D/1+D/2: Vollständiges, typisiertes A2A-Envelope (message_id, reply_to,
correlation_id, confidence, attachments) und validierte Annahme mit
deterministischer Ergebnis-Kompression. Das *vollständige* Ergebnis bleibt
immer in ``deliverables_json`` — die Kompression betrifft nur die Ansicht.
"""

import os
import sys
import json
import hmac
import sqlite3
import datetime
import hashlib
import secrets
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

# Rueckwaertskompatible Defaults fuer die A2A-Envelope-Spalten (Migration in
# _init_db). Bestehende Zeilen behalten damit gueltige Werte.
_A2A_COLUMNS = (
    ("message_id", "TEXT DEFAULT ''"),
    ("reply_to", "TEXT DEFAULT ''"),
    ("correlation_id", "TEXT DEFAULT ''"),
    ("confidence", "REAL DEFAULT 1.0"),
    ("attachments_json", "TEXT DEFAULT '[]'"),
    ("trace_id", "TEXT DEFAULT ''"),
    ("session_id", "TEXT DEFAULT ''"),
)

# D11/S-11.3: ein einziger, fester Marker fuer alle Kuerzungen in der Handoff-Kette.
TRUNCATION_MARKER_TEMPLATE = "… [gekürzt: {n} Zeichen; vollständig in {artifact}] …"
HANDOFF_HMAC_PREFIX = "hmac-sha256:"
HANDOFF_HMAC_ENV = "ARCHON_HANDOFF_HMAC_KEY"
HANDOFF_HMAC_FALLBACK_ENV = "ARCHON_AUDIT_HMAC_KEY"


def mark_truncated(text: Any, limit: int, *, artifact: str = "Vollversion in Datenbank/Artefakt") -> str:
    """Kuerzt nie still: jeder Schnitt traegt einen festen, maschinenlesbaren Marker.

    Kopf und Ende bleiben erhalten (deterministisch, offline). Der Marker nennt
    die Anzahl verworfener Zeichen und den Ort der vollstaendigen Fassung.
    """
    raw = str(text or "")
    if limit <= 0 or len(raw) <= limit:
        return raw
    marker = TRUNCATION_MARKER_TEMPLATE.format(n=len(raw) - int(limit), artifact=artifact)
    budget = max(0, int(limit) - len(marker))
    head = budget // 2
    tail = budget - head
    return raw[:head] + marker + (raw[-tail:] if tail else "")


class HandoffEnvelope(BaseModel):
    """D11/S-11.1: schema-validierter A2A-Envelope (Pydantic v2, extra=forbid)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., min_length=1)
    from_agent: str = Field(..., min_length=1)
    to_agent: str = Field(..., min_length=1)
    deliverables: Dict[str, Any]
    acceptance_criteria: str
    # Pflichtfelder: der Aufrufer muss sie explizit setzen (Create-Helfer
    # befuellt sie aus Trace-Kontext bzw. task_id, falls nicht uebergeben).
    message_id: str = Field(..., min_length=1)
    reply_to: str
    correlation_id: str = Field(..., min_length=1)
    trace_id: str
    session_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    attachments: List[str] = Field(default_factory=list)


class HandoffDeliverables(BaseModel):
    """Minimal-Schema der Ergebnisdaten, die eine Annahme erlauben."""

    model_config = ConfigDict(extra="allow")

    result: str = ""
    status: str = ""


def _handoff_hmac_key() -> bytes:
    """HMAC-Key ausschliesslich aus der ENV (analog zur Audit-Kette)."""
    key = os.environ.get(HANDOFF_HMAC_ENV, "").strip().encode("utf-8")
    if not key:
        key = os.environ.get(HANDOFF_HMAC_FALLBACK_ENV, "").strip().encode("utf-8")
    if not key:
        raise RuntimeError(
            "[HandoffDesk] HMAC-Key fehlt: ARCHON_HANDOFF_HMAC_KEY bzw. "
            "ARCHON_AUDIT_HMAC_KEY muss gesetzt sein (kein nacktes SHA-256)."
        )
    return key


def _sign_envelope(envelope: HandoffEnvelope) -> str:
    """HMAC-SHA256 ueber die kanonische Envelope ( manipulationsevident )."""
    canonical = envelope.model_dump(mode="json")
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hmac.new(_handoff_hmac_key(), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{HANDOFF_HMAC_PREFIX}{digest}"


def _coerce_confidence(value: Any) -> float:
    """Confidence ist immer eine Zahl in [0.0, 1.0]; Default 1.0."""
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, conf))


def summarize_for_handoff(text: Any, limit: int = 2000, *, artifact: str = "deliverables_json") -> str:
    """Deterministische Kompression eines einzelnen Ergebnistextes.

    ``backend/context_compactor.py`` verdichtet Konversationslisten
    (``ContextCompactor.compact_messages``), bietet aber keinen Helfer für
    einen einzelnen Ergebnistext. Diese Variante behält Kopf und Ende und
    markiert die Auslassung explizit. Sie ist rein deterministisch, offline
    und verliert nie die vollständige Fassung in der Datenbank: Aufrufer
    speichern immer den ganzen Text in ``deliverables_json``.
    """
    return mark_truncated(text, limit, artifact=artifact)


class HandoffDesk:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_handoffs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    deliverables_json TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT DEFAULT 'pending_acceptance',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP,
                    message_id TEXT DEFAULT '',
                    reply_to TEXT DEFAULT '',
                    correlation_id TEXT DEFAULT '',
                    confidence REAL DEFAULT 1.0,
                    attachments_json TEXT DEFAULT '[]',
                    trace_id TEXT DEFAULT '',
                    session_id TEXT DEFAULT ''
                )
            """)
            # Batch D/1: additive Migration — keine Zerstoerung bestehender Zeilen.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_handoffs)").fetchall()}
            for col_name, col_decl in _A2A_COLUMNS:
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE agent_handoffs ADD COLUMN {col_name} {col_decl}")
            conn.commit()

    def create_handoff(
        self,
        task_id: str,
        from_agent: str,
        to_agent: str,
        deliverables: Any,
        acceptance_criteria: str,
        *,
        message_id: Optional[str] = None,
        reply_to: Optional[str] = None,
        correlation_id: Optional[str] = None,
        confidence: float = 1.0,
        attachments: Optional[List[str]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Erzeugt ein manipulationssicheres, Pydantic-validiertes A2A-Dokument."""
        # Sekunden-Stempel allein kollidiert bei mehreren Übergaben pro Sekunde.
        h_id = f"handoff-{datetime.datetime.now().strftime('%m%d%H%M%S')}-{secrets.token_hex(3)}"
        # Rueckwaertskompatibel: Dict *oder* HandoffEnvelope werden akzeptiert.
        if isinstance(deliverables, HandoffEnvelope):
            source = deliverables.model_dump()
            deliv = dict(source.get("deliverables") or {})
            acceptance_criteria = acceptance_criteria or source.get("acceptance_criteria", "")
            message_id = message_id or source.get("message_id")
            reply_to = reply_to if reply_to is not None else source.get("reply_to")
            correlation_id = correlation_id or source.get("correlation_id")
            trace_id = trace_id or source.get("trace_id")
            session_id = session_id or source.get("session_id")
            confidence = source.get("confidence", confidence)
            attachments = attachments if attachments is not None else source.get("attachments")
        else:
            deliv = dict(deliverables or {})
        # Kopie statt Mutation des Aufrufers; altes Format hatte kein 'status'.
        deliv.setdefault("status", "unknown")
        deliv["result"] = str(deliv.get("result") or "")
        result_text = deliv["result"]

        active_trace = ""
        try:
            from backend.trace_context import current_trace_id
            active_trace = str(current_trace_id() or "")
        except Exception:
            pass
        envelope = HandoffEnvelope.model_validate({
            "task_id": str(task_id or ""),
            "from_agent": str(from_agent or ""),
            "to_agent": str(to_agent or ""),
            "deliverables": deliv,
            "acceptance_criteria": str(acceptance_criteria or ""),
            "message_id": str(message_id or f"msg-{secrets.token_hex(6)}"),
            "reply_to": str(reply_to or ""),
            "correlation_id": str(correlation_id or f"task:{task_id}"),
            "trace_id": str(trace_id or active_trace or ""),
            "session_id": str(session_id or ""),
            "confidence": _coerce_confidence(confidence),
            "attachments": [str(x) for x in (attachments or [])],
        })
        env_data = envelope.model_dump()
        deliv_str = json.dumps(env_data["deliverables"], sort_keys=True, ensure_ascii=False)
        att_json = json.dumps(env_data["attachments"], sort_keys=True, ensure_ascii=False)
        p_hash = _sign_envelope(envelope)

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO agent_handoffs (
                    id, task_id, from_agent, to_agent, deliverables_json,
                    acceptance_criteria, payload_hash, status, created_at,
                    message_id, reply_to, correlation_id, confidence, attachments_json,
                    trace_id, session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_acceptance', CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
            """, (h_id, envelope.task_id, envelope.from_agent, envelope.to_agent,
                  deliv_str, envelope.acceptance_criteria, p_hash, envelope.message_id,
                  envelope.reply_to, envelope.correlation_id, envelope.confidence,
                  att_json, envelope.trace_id, envelope.session_id))
            conn.commit()

        return {
            "status": "pending_acceptance",
            "handoff_id": h_id,
            "task_id": envelope.task_id,
            "from_agent": envelope.from_agent,
            "to_agent": envelope.to_agent,
            "payload_hash": p_hash,
            "message_id": envelope.message_id,
            "reply_to": envelope.reply_to,
            "correlation_id": envelope.correlation_id,
            "trace_id": envelope.trace_id,
            "session_id": envelope.session_id,
            "confidence": envelope.confidence,
            "attachments": envelope.attachments,
            "envelope": env_data,
            # Batch D/2: kompakte Ansicht; das volle Ergebnis liegt in der DB.
            "summary": summarize_for_handoff(result_text, artifact="deliverables_json"),
            "message": f"Übergabe von '{envelope.from_agent}' an '{envelope.to_agent}' protokolliert. Quittung ausstehend."
        }

    @staticmethod
    def _envelope_from_row(item: Dict[str, Any]) -> HandoffEnvelope:
        """Rekonstruiert den validierten Envelope aus einer SQLite-Zeile."""
        try:
            deliverables = json.loads(item.get("deliverables_json") or "{}")
        except (TypeError, ValueError) as exc:
            raise ValueError("deliverables_json ist kein JSON-Objekt") from exc
        if not isinstance(deliverables, dict):
            raise ValueError("deliverables_json ist kein JSON-Objekt")
        try:
            attachments = json.loads(item.get("attachments_json") or "[]")
        except (TypeError, ValueError):
            attachments = []
        if not isinstance(attachments, list):
            attachments = []
        return HandoffEnvelope.model_validate({
            "task_id": str(item.get("task_id") or ""),
            "from_agent": str(item.get("from_agent") or ""),
            "to_agent": str(item.get("to_agent") or ""),
            "deliverables": deliverables,
            "acceptance_criteria": str(item.get("acceptance_criteria") or ""),
            "message_id": str(item.get("message_id") or ""),
            "reply_to": str(item.get("reply_to") or ""),
            "correlation_id": str(item.get("correlation_id") or ""),
            "trace_id": str(item.get("trace_id") or ""),
            "session_id": str(item.get("session_id") or ""),
            "confidence": _coerce_confidence(item.get("confidence")),
            "attachments": [str(x) for x in attachments],
        })

    @staticmethod
    def verify_envelope(envelope: HandoffEnvelope, stored_hash: str) -> bool:
        """Constant-time Vergleich des HMAC gegen die gespeicherte Envelope."""
        stored = str(stored_hash or "")
        if not stored.startswith(HANDOFF_HMAC_PREFIX):
            return False  # alters SHA-256-Format ist nicht mehr vertrauenswuerdig
        return hmac.compare_digest(_sign_envelope(envelope), stored)

    def verify_payload_hash(self, handoff_id: str) -> bool:
        """Oeffentlicher Pruefpfad fuer Manipulationen an einer Übergabe."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_handoffs WHERE id = ?", (handoff_id,)
            ).fetchone()
            if not row:
                return False
            item = dict(row)
            return self.verify_envelope(
                self._envelope_from_row(item), str(item.get("payload_hash") or "")
            )

    def accept_handoff(self, handoff_id: str, receiving_agent: str) -> Dict[str, Any]:
        """Der Folge-Agent quittiert die fehlerfreie Übernahme (validiert)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_handoffs WHERE id = ?", (handoff_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": f"Übergabe {handoff_id} nicht gefunden."}

            item = dict(row)
            if item["to_agent"] != receiving_agent and receiving_agent != "hermes-orchestrator":
                return {"status": "error", "message": f"Agent {receiving_agent} ist nicht der autorisierte Empfänger."}

            # D11: HMAC vor jeder Annahme pruefen — manipulierte Envelopes
            # duerfen nie als "accepted" durchgewinkt werden.
            try:
                envelope = self._envelope_from_row(item)
                if not self.verify_envelope(envelope, str(item.get("payload_hash") or "")):
                    return {"status": "error", "message": f"Übergabe {handoff_id}: payload_hash ungueltig (Manipulation oder fehlender HMAC-Key)."}
                deliverables = HandoffDeliverables.model_validate(envelope.deliverables)
                result = deliverables.result.strip()
                status = deliverables.status.strip()
            except (ValidationError, ValueError, RuntimeError) as exc:
                return {"status": "error", "message": f"Übergabe {handoff_id}: Envelope-Schema ungueltig ({exc})."}
            if not result:
                return {"status": "error", "message": f"Übergabe {handoff_id} enthält kein Ergebnis (deliverables.result leer)."}
            if not status:
                return {"status": "error", "message": f"Übergabe {handoff_id} enthält keinen Status (deliverables.status leer)."}
            criteria = str(item.get("acceptance_criteria") or "").strip()
            if not criteria:
                return {"status": "error", "message": f"Übergabe {handoff_id} hat keine Akzeptanzkriterien."}

            conn.execute("""
                UPDATE agent_handoffs
                SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (handoff_id,))
            conn.commit()

            return {
                "status": "accepted",
                "handoff_id": handoff_id,
                "message": f"Übergabe von '{receiving_agent}' quittiert. Bearbeitung freigegeben."
            }

    def get_handoff(self, handoff_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_handoffs WHERE id = ?", (handoff_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["deliverables"] = json.loads(d["deliverables_json"])
            except Exception:
                d["deliverables"] = {}
            # Batch D/1: Anhaenge als Liste, nicht als rohen JSON-String.
            try:
                d["attachments"] = json.loads(d.get("attachments_json") or "[]")
            except Exception:
                d["attachments"] = []
            if not isinstance(d["attachments"], list):
                d["attachments"] = []
            d["confidence"] = _coerce_confidence(d.get("confidence"))
            d["message_id"] = str(d.get("message_id") or "")
            d["reply_to"] = str(d.get("reply_to") or "")
            d["correlation_id"] = str(d.get("correlation_id") or "")
            d["trace_id"] = str(d.get("trace_id") or "")
            d["session_id"] = str(d.get("session_id") or "")
            try:
                d["envelope"] = self._envelope_from_row(d).model_dump()
            except (ValidationError, ValueError):
                d["envelope"] = None
            # Batch D/2: kompakte Ansicht on demand, voller Text in deliverables.
            d["summary"] = summarize_for_handoff(
                (d.get("deliverables") or {}).get("result", ""),
                artifact="deliverables_json",
            )
            return d

handoff_desk = HandoffDesk()
