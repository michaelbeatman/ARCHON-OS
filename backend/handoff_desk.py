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
import sqlite3
import datetime
import hashlib
import secrets
from typing import Dict, Any, List, Optional

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
)


def _coerce_confidence(value: Any) -> float:
    """Confidence ist immer eine Zahl in [0.0, 1.0]; Default 1.0."""
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, conf))


def summarize_for_handoff(text: Any, limit: int = 2000) -> str:
    """Deterministische Kompression eines einzelnen Ergebnistextes.

    ``backend/context_compactor.py`` verdichtet Konversationslisten
    (``ContextCompactor.compact_messages``), bietet aber keinen Helfer für
    einen einzelnen Ergebnistext. Diese Variante behält Kopf und Ende und
    markiert die Auslassung explizit. Sie ist rein deterministisch, offline
    und verliert nie die vollständige Fassung in der Datenbank: Aufrufer
    speichern immer den ganzen Text in ``deliverables_json``.
    """
    raw = str(text or "")
    if limit <= 0 or len(raw) <= limit:
        return raw
    marker = (
        f"\n… [gekürzt: {len(raw) - limit} Zeichen; "
        "vollständiges Ergebnis in deliverables_json] …\n"
    )
    budget = max(0, int(limit) - len(marker))
    head = budget // 2
    tail = budget - head
    return raw[:head] + marker + (raw[-tail:] if tail else "")


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
                    attachments_json TEXT DEFAULT '[]'
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
        deliverables: Dict[str, Any],
        acceptance_criteria: str,
        *,
        message_id: Optional[str] = None,
        reply_to: Optional[str] = None,
        correlation_id: Optional[str] = None,
        confidence: float = 1.0,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Erzeugt ein manipulationssicheres, typisiertes A2A-Übergabe-Dokument."""
        # Sekunden-Stempel allein kollidiert bei mehreren Übergaben pro Sekunde.
        h_id = f"handoff-{datetime.datetime.now().strftime('%m%d%H%M%S')}-{secrets.token_hex(3)}"
        # Kopie statt Mutation des Aufrufers; altes Format hatte kein 'status'.
        deliv = dict(deliverables or {})
        deliv.setdefault("status", "unknown")
        deliv["result"] = str(deliv.get("result") or "")
        result_text = deliv["result"]
        deliv_str = json.dumps(deliv, sort_keys=True, ensure_ascii=False)
        p_hash = hashlib.sha256(f"{task_id}:{from_agent}:{to_agent}:{deliv_str}".encode("utf-8")).hexdigest()

        msg_id = str(message_id or f"msg-{secrets.token_hex(6)}")
        corr_id = str(correlation_id or f"task:{task_id}")
        reply = str(reply_to or "")
        conf = _coerce_confidence(confidence)
        att_json = json.dumps(list(attachments or []), sort_keys=True, ensure_ascii=False)

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO agent_handoffs (
                    id, task_id, from_agent, to_agent, deliverables_json,
                    acceptance_criteria, payload_hash, status, created_at,
                    message_id, reply_to, correlation_id, confidence, attachments_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_acceptance', CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
            """, (h_id, task_id, from_agent, to_agent, deliv_str, acceptance_criteria,
                  p_hash, msg_id, reply, corr_id, conf, att_json))
            conn.commit()

        return {
            "status": "pending_acceptance",
            "handoff_id": h_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload_hash": p_hash,
            "message_id": msg_id,
            "reply_to": reply,
            "correlation_id": corr_id,
            "confidence": conf,
            "attachments": list(attachments or []),
            # Batch D/2: kompakte Ansicht; das volle Ergebnis liegt in der DB.
            "summary": summarize_for_handoff(result_text),
            "message": f"Übergabe von '{from_agent}' an '{to_agent}' protokolliert. Quittung ausstehend."
        }

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

            # Batch D/2: keine bedingungslose Annahme mehr. deliverables und
            # Akzeptanzkriterien muessen vorhanden und nicht leer sein.
            try:
                deliverables = json.loads(item.get("deliverables_json") or "{}")
            except (TypeError, ValueError):
                deliverables = {}
            if not isinstance(deliverables, dict):
                deliverables = {}
            result = str(deliverables.get("result") or "").strip()
            status = str(deliverables.get("status") or "").strip()
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
            # Batch D/2: kompakte Ansicht on demand, voller Text in deliverables.
            d["summary"] = summarize_for_handoff(
                (d.get("deliverables") or {}).get("result", "")
            )
            return d

handoff_desk = HandoffDesk()
