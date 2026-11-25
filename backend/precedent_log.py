# -*- coding: utf-8 -*-
"""
backend/precedent_log.py
========================
Meilenstein 91: Praezedenzfall-Gedaechtnis fuer Kanban-Rueckfragen
(precedent-log-Pattern, strikt pro Mandant/Projekt isoliert).

Speichert menschliche Antworten auf blockierte Kanban-Fragen als dauerhafte
Rulings innerhalb desselben Mandanten/Projekts und injiziert passende Rulings
automatisch in kuenftige Worker-Prompts.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import re
import secrets
import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("precedent_log")
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "precedents.db")

_STOPWORDS = frozenset({
    "der", "die", "das", "und", "oder", "fuer", "mit", "von", "auf", "ein", "eine",
    "the", "and", "for", "with", "from", "into", "this", "that", "task", "kanban",
})


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS precedents (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL DEFAULT '',
                question_pattern TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT '',
                ruling_text TEXT NOT NULL,
                created_by TEXT DEFAULT 'human',
                created_at REAL NOT NULL,
                expires_at REAL,
                revoked INTEGER NOT NULL DEFAULT 0,
                hit_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_precedents_scope ON precedents(tenant_id, project_id, revoked)"
        )
        conn.commit()
        yield conn
    finally:
        conn.close()


def canonical_tenant_id(value: Any) -> str:
    """D11/MED: `tenant` (Kanban-Spalte) und `tenant_id` (Präzedenz-Spalte)
    sind zwei Namen für denselben Mandanten. Ein Default darf niemals einen
    aktiven Mandanten überschreiben (sonst fremde Rulings im Worker-Prompt).
    """
    raw = str(value or "").strip()
    if raw and raw.lower() not in ("none", "null", "unknown"):
        return raw
    try:
        from backend.tenant_context import tenant_context
        active = str(tenant_context.get_active_tenant_id() or "").strip()
        if active:
            return active
    except Exception as exc:
        logger.warning("[PrecedentLog] Tenant-Kontext nicht lesbar: %s", exc)
    return "default"


def resolve_task_tenant_id(task: Any) -> str:
    """Einziger Kanoniker für den Mandanten eines Kanban-Tasks.

    Für `backend/operations_api.py` (W3-B) bereitgestellt: dort wird heute
    nur `t_dict.get("tenant_id")` gelesen, die Tabelle heisst aber `tenant`.
    """
    if not isinstance(task, dict):
        return canonical_tenant_id(None)
    # Die physische Kanban-Spalte `tenant` ist die SSOT; ein mitgeschlepptes
    # `tenant_id` aus einem Handler-Payload darf sie nicht überschreiben.
    return canonical_tenant_id(
        task.get("tenant") or task.get("tenant_id") or task.get("company_id")
    )


def _extract_keywords(text: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9äöüß_-]{3,}", (text or "").lower())
    seen = []
    for t in tokens:
        if t not in _STOPWORDS and t not in seen:
            seen.append(t)
    return seen[:25]


def record_precedent(
    tenant_id: str,
    project_id: str,
    question: str,
    ruling_text: str,
    created_by: str = "human",
    expires_at: Optional[float] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Speichert ein neues Ruling strikt unter (tenant_id, project_id)."""
    t_id = canonical_tenant_id(tenant_id)
    p_id = (project_id or "").strip()
    pid = f"prec-{secrets.token_hex(5)}"
    kw = ",".join(_extract_keywords(f"{question} {ruling_text}"))
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO precedents
                (id, tenant_id, project_id, question_pattern, keywords, ruling_text, created_by, created_at, expires_at, revoked, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (pid, t_id, p_id, (question or "").strip(), kw, (ruling_text or "").strip(), created_by, now, expires_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM precedents WHERE id = ?", (pid,)).fetchone()
        return dict(row)


def find_matching_precedents(
    tenant_id: str,
    project_id: str,
    task_text: str,
    limit: int = 5,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Sucht passende aktive Rulings strikt innerhalb desselben Mandanten & Projekts.
    Kein Uebertrag zwischen Mandanten oder fremden Projekten.
    """
    t_id = canonical_tenant_id(tenant_id)
    p_id = (project_id or "").strip()
    now = time.time()
    task_kws = set(_extract_keywords(task_text))

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM precedents
            WHERE tenant_id = ? AND project_id = ? AND revoked = 0
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC
            """,
            (t_id, p_id, now),
        ).fetchall()

        scored = []
        for r in rows:
            d = dict(r)
            p_kws = set(k for k in (d.get("keywords") or "").split(",") if k)
            overlap = len(task_kws & p_kws) if task_kws and p_kws else 0
            if overlap > 0 or not task_kws:
                d["_score"] = overlap
                scored.append(d)

        scored.sort(key=lambda x: (-x["_score"], -x["created_at"]))
        top = scored[:limit]
        if top:
            ids = [x["id"] for x in top]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"UPDATE precedents SET hit_count = hit_count + 1 WHERE id IN ({placeholders})", ids)
            conn.commit()
        return top


def format_precedents_for_prompt(precedents: List[Dict[str, Any]]) -> str:
    if not precedents:
        return ""
    lines = ["\n\n[PRECEDENT RULINGS — Verbindliche Entscheidungen fuer dieses Projekt]:"]
    for p in precedents:
        lines.append(f"- Frage: {p['question_pattern']} -> Ruling ({p['id']}): {p['ruling_text']}")
    return "\n".join(lines) + "\n"


def revoke_precedent(
    precedent_id: str,
    tenant_id: str,
    db_path: Optional[str] = None,
) -> bool:
    t_id = canonical_tenant_id(tenant_id)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE precedents SET revoked = 1 WHERE id = ? AND tenant_id = ?",
            (precedent_id, t_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_precedents(
    tenant_id: str,
    project_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    t_id = canonical_tenant_id(tenant_id)
    with _connect(db_path) as conn:
        if project_id is not None:
            rows = conn.execute(
                "SELECT * FROM precedents WHERE tenant_id = ? AND project_id = ? ORDER BY created_at DESC",
                (t_id, project_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM precedents WHERE tenant_id = ? ORDER BY created_at DESC",
                (t_id,),
            ).fetchall()
        return [dict(r) for r in rows]
