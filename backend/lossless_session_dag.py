# -*- coding: utf-8 -*-
"""
backend/lossless_session_dag.py
==============================
Meilenstein 94: Lossless Session-DAG & Multi-Perspektiven-Research
(hermes-lcm-x & storm-fusion-research-Pattern).

F011 / W1 / BLOCKER B-11 (Remediation 25.11.2026):
  * Produzent: ``record_turns()`` und ``compact_conversation_turns()`` werden im
    PRODUKTIVPFAD gerufen (``agent_router._enforce_token_guard_unlocked`` und
    ``backend/context_compactor.py``) — nicht mehr nur aus Tests.
  * Verlustfrei: ``expand_summary_node()`` löst Summaries rekursiv über
    ``lcm_turns`` UND ``lcm_summaries`` auf (verschachtelte Summaries werden
    einbezogen); ``search_lossless_history()`` durchsucht die UNION beider
    Tabellen (tenant-scoped).
  * Persistenz: konsolidierte ``memory.db`` über ``db_paths.resolve_db()``,
    ``busy_timeout``/WAL aus der SSOT, ``tenant_id`` in beiden Tabellen,
    HMAC-SHA256-Integritätsnachweis je Summary (analog ``handoff_desk``).
  * Art. 17: ``delete_tenant_lossless_data()`` /
    ``anonymize_subject_in_lossless_history()`` (re-signiert Summaries).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger("archon.lossless_session_dag")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TENANT_ID = "default"

# HMAC-Key-SSOT: eigener Env-Key, sonst die beiden etablierten Key-Quellen
# (analog backend/handoff_desk.py::_handoff_hmac_key). Kein Platzhalter-Fallback.
LCM_HMAC_ENV = "ARCHON_LCM_HMAC_KEY"
LCM_HMAC_FALLBACK_ENVS = ("ARCHON_HANDOFF_HMAC_KEY", "ARCHON_AUDIT_HMAC_KEY")
LCM_HMAC_PREFIX = "hmac-sha256:"
MAX_EXPANSION_DEPTH = 64
ANONYMIZATION_MARKER = "[ANONYMISIERT_DSGVO_ART17]"

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_INITIALIZED: set[str] = set()


class LosslessIntegrityError(RuntimeError):
    """ Summary-HMAC ungültig → fail-closed, kein verdichteter Inhalt ausliefern. """


# ---------------------------------------------------------------------------
# Persistenz: konsolidierte memory.db, SSOT für busy_timeout/WAL, Tenant-Spalte
# ---------------------------------------------------------------------------

def _default_db_path() -> str:
    """Einziger Pfad-SSOT: die konsolidierte, tenant-aware ``memory.db``."""
    from backend.db_paths import resolve_db
    return resolve_db("memory.db")


def _open(path: str) -> sqlite3.Connection:
    """Verbindung ausschließlich über die db_paths-SSOT (busy_timeout/WAL)."""
    from backend.db_paths import get_db_connection
    conn = get_db_connection(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lcm_turns (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            dedup_key TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lcm_summaries (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            child_turn_ids_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            integrity_hmac TEXT NOT NULL DEFAULT ''
        )
    """)
    # Migration bestehender Tabellen: ALTER statt CREATE IF NOT EXISTS (eine
    # bereits vorhandene Tabelle bekommt sonst keine neuen Spalten).
    migrations = (
        ("lcm_turns", (("tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                       ("dedup_key", "TEXT NOT NULL DEFAULT ''"))),
        ("lcm_summaries", (("tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                           ("integrity_hmac", "TEXT NOT NULL DEFAULT ''"))),
    )
    for table, columns in migrations:
        existing = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lcm_turns_scope "
        "ON lcm_turns(tenant_id, session_id, seq)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lcm_summaries_scope "
        "ON lcm_summaries(tenant_id, session_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lcm_turns_dedup "
        "ON lcm_turns(tenant_id, session_id, dedup_key)"
    )
    conn.commit()


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = os.path.abspath(db_path or _default_db_path())
    with _SCHEMA_LOCK:
        if path not in _SCHEMA_INITIALIZED:
            conn = _open(path)
            try:
                _ensure_schema(conn)
                _SCHEMA_INITIALIZED.add(path)
            finally:
                conn.close()
    conn = _open(path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tenant-/Session-Kontext (an der Übergabekante abgeleitet, nie erfunden)
# ---------------------------------------------------------------------------

def _effective_tenant(tenant_id: Optional[str] = None) -> str:
    if tenant_id and str(tenant_id).strip():
        return str(tenant_id).strip()
    try:
        from backend.tenant_context import tenant_context
        return str(tenant_context.get_active_tenant_id() or DEFAULT_TENANT_ID)
    except Exception:
        return DEFAULT_TENANT_ID


def derive_tenant_id(messages: Optional[List[Dict[str, Any]]]) -> str:
    """Mandant aus der Nachrichtenkette, sonst aktiver Tenant-Kontext."""
    for msg in messages or []:
        if isinstance(msg, dict):
            tenant = msg.get("tenant_id") or msg.get("company_id")
            if tenant:
                return str(tenant)
    return _effective_tenant()


def derive_session_id(
    messages: Optional[List[Dict[str, Any]]],
    *,
    tenant_id: Optional[str] = None,
) -> str:
    """Deterministische Session-ID einer Nachrichtenkette (idempotent).

    Explizite Korrelationsfelder haben Vorrang und behalten den stabilen
    Vertrag ``session:<id>``. Ohne diese Felder wird der Fingerprint ueber die
    GESAMTE Kette inklusive Mandanten-Salz gebildet. Frueher wurden nur
    System-Prompt und erster User-Turn gehasht — zwei verschiedene Sessions
    mit gleichem Anfang wurden dadurch zusammengefuehrt (Cross-Session-Bleed,
    D11-M3). ``tenant_id`` ist optional, damit die vorhandenen Aufrufer
    unverändert funktionieren.
    """
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        for key in ("session_id", "conversation_id", "chat_id", "thread_id"):
            value = msg.get(key)
            if value:
                return f"session:{value}"

    salt = str(tenant_id or "")
    if not salt:
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            tenant = msg.get("tenant_id") or msg.get("company_id")
            if tenant:
                salt = str(tenant)
                break
    if not salt:
        salt = str(_effective_tenant() or "")

    parts: List[str] = [f"tenant:{salt}"]
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = str(_content_to_text(msg.get("content")))
        parts.append(f"{role}:{content[:2000]}")
        # Explizite Chaos-/Lauf-Korrelation zusaetzlich salzen. Eine
        # message_id taucht hier bewusst NICHT auf: sie wechselt pro Turn
        # und wuerde die Idempotenz zerstoeren.
        for key in ("turn_id", "task_id", "run_id", "request_id"):
            value = msg.get(key)
            if value:
                parts.append(f"{key}={value}")
                break
    base = "|".join(parts)
    if not base.strip("|"):
        base = "agent-router:default"
    return "ar-" + hashlib.sha256(base.encode("utf-8", "replace")).hexdigest()[:24]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(content)


# ---------------------------------------------------------------------------
# HMAC / Integritätsnachweis für Summaries
# ---------------------------------------------------------------------------

def _hmac_key() -> bytes:
    key = os.environ.get(LCM_HMAC_ENV, "").strip().encode("utf-8")
    if not key:
        for env_name in LCM_HMAC_FALLBACK_ENVS:
            key = os.environ.get(env_name, "").strip().encode("utf-8")
            if key:
                break
    if not key:
        raise RuntimeError(
            "[LosslessSessionDAG] HMAC-Key fehlt: ARCHON_LCM_HMAC_KEY bzw. "
            "ARCHON_HANDOFF_HMAC_KEY / ARCHON_AUDIT_HMAC_KEY muss gesetzt sein."
        )
    return key


def _canonical_summary_payload(
    session_id: str, tenant_id: str, summary_text: str, child_ids: List[str]
) -> str:
    payload = {
        "v": 1,
        "session_id": str(session_id),
        "tenant_id": str(tenant_id),
        "summary_text": str(summary_text),
        "child_ids": [str(x) for x in child_ids],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sign_summary(session_id: str, tenant_id: str, summary_text: str, child_ids: List[str]) -> str:
    digest = hmac.new(
        _hmac_key(),
        _canonical_summary_payload(session_id, tenant_id, summary_text, child_ids).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{LCM_HMAC_PREFIX}{digest}"


def _verify_summary(row: sqlite3.Row) -> None:
    expected = _sign_summary(
        row["session_id"],
        row["tenant_id"],
        row["summary_text"],
        json.loads(str(row["child_turn_ids_json"] or "[]")),
    )
    if not hmac.compare_digest(str(row["integrity_hmac"] or ""), expected):
        raise LosslessIntegrityError(
            f"[LosslessSessionDAG] Integritätsverletzung an Summary {row['id']}: "
            "HMAC stimmt nicht mit dem kanonischen Payload überein."
        )


def verify_summary_integrity(
    summary_id: str, db_path: Optional[str] = None, tenant_id: Optional[str] = None
) -> bool:
    """False bei fehlender oder manipulierter Summary (kein stilles Ignore)."""
    tenant = _effective_tenant(tenant_id)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, session_id, summary_text, child_turn_ids_json, integrity_hmac, tenant_id "
            "FROM lcm_summaries WHERE id = ? AND tenant_id = ?",
            (summary_id, tenant),
        ).fetchone()
        if not row:
            return False
        try:
            _verify_summary(row)
            return True
        except LosslessIntegrityError as exc:
            logger.error("[LosslessSessionDAG] %s", exc)
            return False


# ---------------------------------------------------------------------------
# Produzent: echte Turns & echte Compaction-Knoten
# ---------------------------------------------------------------------------

def append_turn(
    session_id: str,
    role: str,
    content: str,
    db_path: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """Expliziter Turn-Append (Rückwärtskompatibel; neu tenant-scoped)."""
    tid = f"turn-{secrets.token_hex(10)}"
    tenant = _effective_tenant(tenant_id)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM lcm_turns "
            "WHERE tenant_id = ? AND session_id = ?",
            (tenant, session_id),
        ).fetchone()
        seq = int(row["m"]) + 1
        conn.execute(
            "INSERT INTO lcm_turns (id, session_id, seq, role, content, created_at, tenant_id, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, session_id, seq, str(role), _content_to_text(content), time.time(), tenant, f"manual-{tid}"),
        )
        conn.commit()
    return tid


def record_turns(
    session_id: str,
    messages: Optional[List[Dict[str, Any]]],
    tenant_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[str]:
    """Idempotente Aufnahme einer Nachrichtenkette in die lossless Historie.

    Jeder echte Session-Turn wird genau einmal gespeichert; der Determinismus
    des ``dedup_key`` verhindert Duplikate bei wiederholten Dispatches.
    Rückgabe: Turn-IDs in Nachrichtenreihenfolge (``""`` bei leeren Inhalten).
    """
    tenant = _effective_tenant(tenant_id)
    ids: List[str] = []
    with _connect(db_path) as conn:
        for idx, msg in enumerate(messages or []):
            if not isinstance(msg, dict):
                ids.append("")
                continue
            role = str(msg.get("role") or "user")
            text = str(_content_to_text(msg.get("content")))
            if not text.strip():
                ids.append("")
                continue
            # D11-M3: Position und explizite Turn-Korrelation gehoeren in den
            # Key. ``tenant|session|role|text`` liess zwei inhaltlich identische
            # Turns derselben Session zu einem Knoten kollabieren. Die exakte
            # wiederholte Dispatch derselben Kette bleibt idempotent (gleicher
            # idx), waehrend echte Wiederholungen eigenstaendige Turns werden.
            explicit = ""
            for key in ("turn_id", "message_id", "id"):
                value = msg.get(key)
                if value:
                    explicit = str(value)
                    break
            dedup = hashlib.sha256(
                f"{tenant}|{session_id}|{idx}|{explicit}|{role}|{text}".encode("utf-8", "replace")
            ).hexdigest()[:24]
            existing = conn.execute(
                "SELECT id FROM lcm_turns WHERE tenant_id = ? AND session_id = ? AND dedup_key = ?",
                (tenant, session_id, dedup),
            ).fetchone()
            if existing:
                ids.append(str(existing["id"]))
                continue
            seq = int(conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM lcm_turns "
                "WHERE tenant_id = ? AND session_id = ?",
                (tenant, session_id),
            ).fetchone()["m"]) + 1
            tid = f"turn-{hashlib.sha256(dedup.encode('utf-8')).hexdigest()[:16]}"
            conn.execute(
                "INSERT INTO lcm_turns (id, session_id, seq, role, content, created_at, tenant_id, dedup_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, session_id, seq, role, text, time.time(), tenant, dedup),
            )
            ids.append(tid)
        conn.commit()
    return ids


def compact_range_to_summary(
    session_id: str,
    turn_ids: List[str],
    summary_text: str,
    db_path: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """Verknüpft Turns UND verschachtelte Summaries als Kinder eines Summary-Knotens.

    Child-IDs, die weder in ``lcm_turns`` noch in ``lcm_summaries`` liegen,
    werden fail-closed abgewiesen (keine Phantom-Kanten im lossless DAG).
    """
    tenant = _effective_tenant(tenant_id)
    children = [str(x) for x in (turn_ids or []) if x]
    sid = f"sum-{secrets.token_hex(10)}"
    signature = _sign_summary(session_id, tenant, summary_text, children)
    with _connect(db_path) as conn:
        for child in children:
            found = conn.execute(
                "SELECT 1 FROM lcm_turns WHERE id = ? AND tenant_id = ? AND session_id = ?",
                (child, tenant, session_id),
            ).fetchone()
            if not found:
                found = conn.execute(
                    "SELECT 1 FROM lcm_summaries WHERE id = ? AND tenant_id = ? AND session_id = ?",
                    (child, tenant, session_id),
                ).fetchone()
            if not found:
                raise ValueError(
                    f"[LosslessSessionDAG] unbekannter Child-Knoten {child} "
                    f"(tenant={tenant}, session={session_id})"
                )
        conn.execute(
            "INSERT INTO lcm_summaries "
            "(id, session_id, summary_text, child_turn_ids_json, created_at, tenant_id, integrity_hmac) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, session_id, str(summary_text), json.dumps(children), time.time(), tenant, signature),
        )
        conn.commit()
    return sid


def compact_conversation_turns(
    session_id: str,
    older_messages: Optional[List[Dict[str, Any]]],
    summary_text: str,
    tenant_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Produzenten-Helfer für den echten Chokepoint: Turns + Summary in einem Schritt."""
    tenant = _effective_tenant(tenant_id)
    ids = [i for i in record_turns(session_id, older_messages, tenant_id=tenant, db_path=db_path) if i]
    if not ids:
        return ""
    return compact_range_to_summary(session_id, ids, summary_text, db_path=db_path, tenant_id=tenant)


# ---------------------------------------------------------------------------
# Konsument: verlustfreie Expansion & UNION-Suche
# ---------------------------------------------------------------------------

def expand_summary_node(
    summary_id: str, db_path: Optional[str] = None, tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Rekursive Expansion über ``lcm_turns`` UND ``lcm_summaries``.

    Verschachtelte Summaries werden als eigene Knoten (``kind='summary'``)
    zurückgegeben und ihrerseits aufgelöst. Zyklen werden über ``visited``
    abgeschnitten; manipulierte Summaries lösen ``LosslessIntegrityError`` aus.
    """
    tenant = _effective_tenant(tenant_id)
    out: List[Dict[str, Any]] = []
    visited: set[str] = set()

    with _connect(db_path) as conn:
        root = conn.execute(
            "SELECT id, session_id, summary_text, child_turn_ids_json, integrity_hmac, tenant_id "
            "FROM lcm_summaries WHERE id = ? AND tenant_id = ?",
            (summary_id, tenant),
        ).fetchone()
        if not root:
            return []
        _verify_summary(root)
        root_session = str(root["session_id"])

        def _walk(children: List[str], depth: int) -> None:
            if depth > MAX_EXPANSION_DEPTH:
                raise RuntimeError(
                    f"[LosslessSessionDAG] Maximaltiefe {MAX_EXPANSION_DEPTH} überschritten (Zyklus?)"
                )
            for child in children:
                cid = str(child)
                if cid in visited:
                    continue
                visited.add(cid)
                turn_row = conn.execute(
                    "SELECT id, seq, role, content, tenant_id FROM lcm_turns "
                    "WHERE id = ? AND tenant_id = ? AND session_id = ?",
                    (cid, tenant, root_session),
                ).fetchone()
                if turn_row:
                    out.append({
                        "kind": "turn",
                        "id": str(turn_row["id"]),
                        "seq": int(turn_row["seq"]),
                        "role": str(turn_row["role"]),
                        "content": str(turn_row["content"]),
                        "tenant_id": str(turn_row["tenant_id"]),
                    })
                    continue
                summary_row = conn.execute(
                    "SELECT id, session_id, summary_text, child_turn_ids_json, integrity_hmac, tenant_id "
                    "FROM lcm_summaries WHERE id = ? AND tenant_id = ? AND session_id = ?",
                    (cid, tenant, root_session),
                ).fetchone()
                if summary_row:
                    _verify_summary(summary_row)
                    out.append({
                        "kind": "summary",
                        "id": str(summary_row["id"]),
                        "seq": 0,
                        "role": "summary",
                        "content": str(summary_row["summary_text"]),
                        "summary_text": str(summary_row["summary_text"]),
                        "tenant_id": str(summary_row["tenant_id"]),
                    })
                    _walk(json.loads(str(summary_row["child_turn_ids_json"] or "[]")), depth + 1)
                    continue
                raise ValueError(
                    f"[LosslessSessionDAG] Child {cid} nicht gefunden "
                    f"(tenant={tenant}, session={root_session})"
                )

        _walk(json.loads(str(root["child_turn_ids_json"] or "[]")), 0)
    return out


def search_lossless_history(
    session_id: str, query: str, db_path: Optional[str] = None, tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Suche über die UNION aus Turns UND Summaries (immer tenant-scoped)."""
    tenant = _effective_tenant(tenant_id)
    pattern = f"%{(query or '').strip()}%"
    out: List[Dict[str, Any]] = []
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT 'turn' AS kind, id, session_id, seq, role, content,
                   '' AS summary_text, '' AS integrity_hmac, '' AS child_turn_ids_json,
                   created_at, tenant_id
            FROM lcm_turns
            WHERE tenant_id = ? AND session_id = ? AND content LIKE ?
            UNION ALL
            SELECT 'summary' AS kind, id, session_id, 0 AS seq, 'summary' AS role,
                   summary_text AS content, summary_text AS summary_text,
                   integrity_hmac, child_turn_ids_json, created_at, tenant_id
            FROM lcm_summaries
            WHERE tenant_id = ? AND session_id = ? AND summary_text LIKE ?
            ORDER BY created_at ASC, seq ASC
            """,
            (tenant, session_id, pattern, tenant, session_id, pattern),
        ).fetchall()
        for row in rows:
            item: Dict[str, Any] = {
                "kind": str(row["kind"]),
                "id": str(row["id"]),
                "seq": int(row["seq"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "tenant_id": str(row["tenant_id"]),
            }
            if str(row["kind"]) == "summary":
                item["summary_text"] = str(row["summary_text"])
                _verify_summary(row)
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Art. 17 DSGVO: Löschung / Anonymisierung (kein stiller Fallback)
# ---------------------------------------------------------------------------

def delete_tenant_lossless_data(
    tenant_id: str, session_id: Optional[str] = None, db_path: Optional[str] = None
) -> Dict[str, int]:
    """Harte Löschung eines Mandanten (oder nur einer Session) aus beiden Tabellen."""
    tenant = _effective_tenant(tenant_id)
    with _connect(db_path) as conn:
        if session_id:
            turns = conn.execute(
                "DELETE FROM lcm_turns WHERE tenant_id = ? AND session_id = ?",
                (tenant, session_id),
            ).rowcount
            summaries = conn.execute(
                "DELETE FROM lcm_summaries WHERE tenant_id = ? AND session_id = ?",
                (tenant, session_id),
            ).rowcount
        else:
            turns = conn.execute("DELETE FROM lcm_turns WHERE tenant_id = ?", (tenant,)).rowcount
            summaries = conn.execute("DELETE FROM lcm_summaries WHERE tenant_id = ?", (tenant,)).rowcount
        conn.commit()
    return {"turns": int(turns), "summaries": int(summaries)}


def anonymize_subject_in_lossless_history(
    identifier: str,
    tenant_id: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Art. 17: case-insensitive Schwärzung inkl. Neu-Signatur aller Summaries."""
    term = str(identifier or "").strip()
    if len(term) < 3:
        raise ValueError("Suchbegriff muss mindestens 3 Zeichen lang sein.")
    tenant = _effective_tenant(tenant_id)
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    result: Dict[str, Any] = {
        "tenant_id": tenant,
        "identifier_hash": hashlib.sha256(term.encode("utf-8")).hexdigest(),
        "dry_run": bool(dry_run),
        "mode": "anonymize",
        "turns": 0,
        "summaries": 0,
    }
    with _connect(db_path) as conn:
        turn_rows = conn.execute(
            "SELECT id, content FROM lcm_turns WHERE tenant_id = ? AND content LIKE ?",
            (tenant, f"%{term}%"),
        ).fetchall()
        summary_rows = conn.execute(
            "SELECT id, session_id, summary_text, child_turn_ids_json, integrity_hmac, tenant_id "
            "FROM lcm_summaries WHERE tenant_id = ? AND summary_text LIKE ?",
            (tenant, f"%{term}%"),
        ).fetchall()
        hit_turns = [r for r in turn_rows if pattern.search(str(r["content"]))]
        hit_summaries = [r for r in summary_rows if pattern.search(str(r["summary_text"]))]
        result["turns"] = len(hit_turns)
        result["summaries"] = len(hit_summaries)
        if not dry_run:
            for row in hit_turns:
                conn.execute(
                    "UPDATE lcm_turns SET content = ? WHERE id = ? AND tenant_id = ?",
                    (ANONYMIZATION_MARKER, row["id"], tenant),
                )
            for row in hit_summaries:
                children = json.loads(str(row["child_turn_ids_json"] or "[]"))
                conn.execute(
                    "UPDATE lcm_summaries SET summary_text = ?, integrity_hmac = ? "
                    "WHERE id = ? AND tenant_id = ?",
                    (
                        ANONYMIZATION_MARKER,
                        _sign_summary(row["session_id"], tenant, ANONYMIZATION_MARKER, children),
                        row["id"],
                        tenant,
                    ),
                )
            conn.commit()
    return result


# ---------------------------------------------------------------------------
# Multi-Perspektiven-Research (unverändert)
# ---------------------------------------------------------------------------

async def run_storm_panel(
    question: str,
    seats: List[str],
    seat_runner: Callable[[str, str], Awaitable[str]],
    judge_runner: Callable[[str, Dict[str, str]], Awaitable[str]],
) -> Dict[str, Any]:
    """Multi-Perspektiven-Research-Panel mit parallelen Seats, Judge & Human-Gate."""
    seat_answers = await asyncio.gather(*(seat_runner(seat, question) for seat in seats))
    perspectives = dict(zip(seats, seat_answers))
    synthesis = await judge_runner(question, perspectives)
    return {
        "question": question,
        "perspectives": perspectives,
        "synthesis": synthesis,
        "requires_human_gate": True,
    }
