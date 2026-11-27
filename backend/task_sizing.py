# -*- coding: utf-8 -*-
"""
backend/task_sizing.py
======================
M72 — Modellabhängiges Task-Sizing & Skills auf Leihbasis.

Zwei voneinander unabhängige, additive Bausteine:

1. ``resolve_context_window`` / ``size_chunks``: deterministische Zerlegung von
   Task-Text in Chunks, die in das Kontextfenster des Zielmodells passen. Die
   Fenster-SSOT bleibt M99 (``backend.context_compactor``); dieses Modul
   dupliziert keine Modellfamilien-Tabelle, es delegiert ausschließlich.

2. ``issue_skills`` / ``return_skills`` / ``leased_skills``: temporäre
   Skill-Zuweisung pro Task aus dem Skill-Index (``.agents/skills/``) im
   bestehenden ``kv_store`` der ``agentic_memory.db``. Es wird keine neue
   Tabelle und kein Schema in Lesepfaden eingeführt. Zuweisungen sind
   duplicates-frei, auf den Index beschränkt, TTL-begrenzt und werden bei
   ``finalize``/Exception sowie beim Ablauf automatisch zurückgegeben.

Die Budget-SSOT (``role_budget_engine``) bleibt unberührt: dieses Modul bucht
keine Tokens und keine Kosten, es schätzt und zerlegt nur.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, TypedDict

logger = logging.getLogger("archon.task_sizing")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(WORKSPACE_DIR, ".agents", "skills")

# M99-SSOT: Fenster und Fallback werden importiert, nie nachgebaut.
try:
    from backend.context_compactor import (
        DEFAULT_MAX_CONTEXT_TOKENS as FALLBACK_CONTEXT_WINDOW,
    )
    from backend.context_compactor import (
        MAX_CONTEXT_TOKENS as ABSOLUTE_WINDOW_CEILING,
    )
    from backend.context_compactor import (
        resolve_model_context_window as _resolve_m99,
    )
except Exception:  # pragma: no cover - nur bei defekter M99-Installation
    FALLBACK_CONTEXT_WINDOW = 32000
    ABSOLUTE_WINDOW_CEILING = 2_000_000
    _resolve_m99 = None  # type: ignore[assignment]

# Konservative Schranken: 4 Zeichen pro Token (wie M99), 20 % Reservierung für
# System-Prompt/Overhead und eine absolute Obergrenze für 1M-Fenster.
CHARS_PER_TOKEN = 4
SAFETY_RESERVE_PCT = 0.20
HARD_CHUNK_TOKEN_CEILING = 800_000
DEFAULT_OVERLAP_TOKENS = 128
MIN_CHUNK_TOKENS = 256

TASK_SKILL_LEASE_PREFIX = "task_sizing:skill_lease:"
_LEASE_LOCK = threading.RLock()


class ChunkInfo(TypedDict):
    """Ein einzelner, deterministisch erzeugter Text-Chunk."""

    index: int
    text: str
    char_start: int
    char_end: int
    estimated_tokens: int


class SizingResult(TypedDict):
    """Ergebnis von ``size_chunks`` inklusive Token-Schätzung."""

    model: str
    context_window: int
    max_chunk_tokens: int
    overlap_tokens: int
    total_chunks: int
    total_estimated_tokens: int
    original_estimated_tokens: int
    chunks: List[ChunkInfo]


class SkillLease(TypedDict):
    """Persistierter Leih-Vertrag im ``kv_store``."""

    task_id: str
    skill_ids: List[str]
    issued_at: str
    expires_at: str
    expires_ts: float


class LeaseResult(TypedDict):
    """Rückgabe von ``issue_skills`` / ``return_skills``."""

    task_id: str
    skill_ids: List[str]
    status: str
    expired: bool
    issued_at: str
    expires_at: str
    ttl_seconds: float
    rejected_skill_ids: List[str]


# ---------------------------------------------------------------------------
# 1. Modellabhängiges Task-Sizing (SSOT: M99)
# ---------------------------------------------------------------------------


def resolve_context_window(
    model: Optional[str] = None,
    *,
    provider_metadata: Optional[Dict[str, Any]] = None,
    configured_override: Optional[int] = None,
) -> int:
    """Ermittelt das Kontextfenster ausschließlich über die M99-SSOT.

    Bei Importfehler, Exception oder unplausiblem Wert gilt defensiv der
    sichere 32k-Fallback. Es gibt absichtlich keine eigene Modelltabelle.
    """
    resolver: Optional[Callable[..., int]] = _resolve_m99
    if resolver is None:
        return int(FALLBACK_CONTEXT_WINDOW)
    try:
        raw = resolver(
            model,
            provider_metadata=provider_metadata,
            configured_override=configured_override,
        )
        window = int(raw)
    except Exception as exc:
        logger.warning("[TaskSizing] M99-Fenster-SSOT nicht nutzbar, Fallback 32k: %s", exc)
        return int(FALLBACK_CONTEXT_WINDOW)
    if window <= 0 or window > int(ABSOLUTE_WINDOW_CEILING):
        return int(FALLBACK_CONTEXT_WINDOW)
    return window


def estimate_tokens(text: str) -> int:
    """Deterministische Token-Schätzung im selben Maßstab wie M99 (Zeichen/4)."""
    return max(1, len(str(text or "")) // CHARS_PER_TOKEN)


def _usable_chunk_tokens(
    context_window: int,
    max_chunk_tokens: Optional[int],
) -> int:
    """Kapazität je Chunk in Tokens — hart begrenzt, nie über dem Fenster."""
    window = max(1, int(context_window))
    reserve = 1.0 - SAFETY_RESERVE_PCT
    usable = int(window * reserve)
    usable = min(usable, HARD_CHUNK_TOKEN_CEILING, int(ABSOLUTE_WINDOW_CEILING))
    if max_chunk_tokens is not None:
        # Expliziter Aufrufer-Wert darf nur verschärfen, nie erweitern.
        usable = min(usable, max(1, int(max_chunk_tokens)))
    return max(MIN_CHUNK_TOKENS, min(usable, window))


def size_chunks(
    text: str,
    model: Optional[str] = None,
    *,
    overlap: int = DEFAULT_OVERLAP_TOKENS,
    provider_metadata: Optional[Dict[str, Any]] = None,
    configured_override: Optional[int] = None,
    max_chunk_tokens: Optional[int] = None,
) -> SizingResult:
    """Zerlegt ``text`` reproduzierbar in chunks passend zum Modellfenster.

    Der Overlap wird in Tokens angegeben, intern aber in Zeichen umgesetzt und
    gegen die Chunk-Größe geklemmt, damit der Vorwärtsfortschritt garantiert
    ist. Jeder Chunk trägt eine Token-Schätzung; die harte Obergrenze
    ``max_chunk_tokens`` wird niemals überschritten.
    """
    source = str(text or "")
    window = resolve_context_window(
        model,
        provider_metadata=provider_metadata,
        configured_override=configured_override,
    )
    capacity = _usable_chunk_tokens(window, max_chunk_tokens)

    # Overlap strikt kleiner als die Chunk-Kapazität → kein Stillstand.
    overlap_tokens = max(0, min(int(overlap or 0), capacity - 1))
    chunk_chars = capacity * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    chunks: List[ChunkInfo] = []
    start = 0
    length = len(source)
    while start < length:
        end = min(start + chunk_chars, length)
        chunk_text = source[start:end]
        chunks.append({
            "index": len(chunks),
            "text": chunk_text,
            "char_start": start,
            "char_end": end,
            "estimated_tokens": estimate_tokens(chunk_text),
        })
        if end >= length:
            break
        start = end - overlap_chars

    return {
        "model": str(model or ""),
        "context_window": window,
        "max_chunk_tokens": capacity,
        "overlap_tokens": overlap_tokens,
        "total_chunks": len(chunks),
        "total_estimated_tokens": sum(c["estimated_tokens"] for c in chunks),
        "original_estimated_tokens": estimate_tokens(source) if source else 0,
        "chunks": chunks,
    }


# ---------------------------------------------------------------------------
# 2. Skills auf Leihbasis (kv_store, TTL, Rückgabe)
# ---------------------------------------------------------------------------


def load_skill_index(skills_dir: Optional[str] = None) -> frozenset[str]:
    """Liest die installierten Skill-IDs aus ``.agents/skills/`` (fail-closed).

    Verzeichnisse und ``*.md``-Dateien gelten als Skill. Ist der Index nicht
    lesbar, wird eine leere Menge geliefert — damit werden niemals fremde
    Skills stillschweigend akzeptiert.
    """
    base = str(skills_dir or SKILLS_DIR)
    found: set[str] = set()
    try:
        entries = os.listdir(base)
    except OSError as exc:
        logger.debug("[TaskSizing] Skill-Index %s nicht lesbar: %s", base, exc)
        return frozenset()
    for entry in entries:
        if entry.startswith("."):
            continue
        full = os.path.join(base, entry)
        if os.path.isdir(full) or (os.path.isfile(full) and entry.lower().endswith(".md")):
            found.add(entry)
    return frozenset(found)


def _current_ts() -> float:
    """Uhrzeit-Injektionspunkt für deterministische TTL-Tests."""
    return time.time()


def _default_db_path() -> str:
    try:
        from backend.db_paths import resolve_db

        return str(resolve_db("agentic_memory.db"))
    except Exception as exc:
        logger.debug("[TaskSizing] DB-Auflösung fehlgeschlagen, Heimatpfad: %s", exc)
        return os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_kv_conn(db_path: Optional[str] = None) -> Any:
    from backend.db_paths import get_db_connection

    target = str(db_path).strip() if db_path and str(db_path).strip() else _default_db_path()
    return get_db_connection(target)


def _lease_key(task_id: str) -> str:
    return f"{TASK_SKILL_LEASE_PREFIX}{task_id}"


def _ensure_kv_table(conn: Any) -> None:
    """Nur im Schreibpfad: bestehende Tabelle unverändert weiternutzen."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv_store ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _load_lease(task_id: str, db_path: Optional[str] = None) -> Optional[SkillLease]:
    """Reiner Lesepfad — legt keine Tabelle an und mutiert kein Schema."""
    try:
        with _get_kv_conn(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM kv_store WHERE key = ?", (_lease_key(task_id),)
            ).fetchone()
        if not row or not row[0]:
            return None
        raw = json.loads(row[0])
        if not isinstance(raw, dict):
            return None
        skill_ids = [str(s) for s in (raw.get("skill_ids") or []) if str(s or "").strip()]
        return {
            "task_id": str(raw.get("task_id") or task_id),
            "skill_ids": skill_ids,
            "issued_at": str(raw.get("issued_at") or ""),
            "expires_at": str(raw.get("expires_at") or ""),
            "expires_ts": float(raw.get("expires_ts") or 0.0),
        }
    except Exception as exc:
        logger.debug("[TaskSizing] Lease %s nicht lesbar: %s", task_id, exc)
        return None


def _store_lease(lease: SkillLease, db_path: Optional[str] = None) -> None:
    with _get_kv_conn(db_path) as conn:
        _ensure_kv_table(conn)
        conn.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_lease_key(lease["task_id"]), json.dumps(lease, ensure_ascii=False)),
        )
        conn.commit()


def _drop_lease(task_id: str, db_path: Optional[str] = None) -> None:
    with _get_kv_conn(db_path) as conn:
        _ensure_kv_table(conn)
        conn.execute("DELETE FROM kv_store WHERE key = ?", (_lease_key(task_id),))
        conn.commit()


def _iso_from_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat()


def issue_skills(
    task_id: str,
    skill_ids: List[str],
    *,
    ttl_seconds: float,
    db_path: Optional[str] = None,
    skills_dir: Optional[str] = None,
) -> LeaseResult:
    """Weist einem Task Skills temporär zu (TTL, duplicates-frei, index-begrenzt).

    Unbekannte Skill-IDs werden verworfen und in ``rejected_skill_ids``
    gemeldet. Eine erneute Ausgabe ersetzt die bestehende Lease desselben
    Tasks atomar — es entstehen nie zwei Leases mit identischem Skill.
    """
    clean_task = str(task_id or "").strip()
    if not clean_task:
        raise ValueError("task_id_required")
    ttl = float(ttl_seconds)
    if ttl < 0:
        raise ValueError("ttl_seconds_must_not_be_negative")

    known = load_skill_index(skills_dir)
    accepted: List[str] = []
    rejected: List[str] = []
    for raw in list(skill_ids or []):
        sid = str(raw or "").strip()
        if not sid:
            continue
        if sid not in known:
            if sid not in rejected:
                rejected.append(sid)
            continue
        if sid not in accepted:
            accepted.append(sid)

    now = _current_ts()
    lease: SkillLease = {
        "task_id": clean_task,
        "skill_ids": accepted,
        "issued_at": _iso_from_ts(now),
        "expires_at": _iso_from_ts(now + ttl),
        "expires_ts": now + ttl,
    }
    with _LEASE_LOCK:
        _store_lease(lease, db_path)
    logger.info(
        "[TaskSizing] Skill-Lease %s: %d Skills, TTL %ss",
        clean_task, len(accepted), ttl,
    )
    return {
        "task_id": clean_task,
        "skill_ids": list(accepted),
        "status": "issued",
        "expired": False,
        "issued_at": lease["issued_at"],
        "expires_at": lease["expires_at"],
        "ttl_seconds": ttl,
        "rejected_skill_ids": rejected,
    }


def return_skills(task_id: str, *, db_path: Optional[str] = None) -> LeaseResult:
    """Gibt geliehene Skills zurück (idempotent) und löscht die Lease.

    Bei abgelaufener TTL ist die Rückgabe bereits automatisch erfolgt; der
    Status ``expired`` macht das für Audit-Zwecke sichtbar.
    """
    clean_task = str(task_id or "").strip()
    empty: LeaseResult = {
        "task_id": clean_task,
        "skill_ids": [],
        "status": "none",
        "expired": False,
        "issued_at": "",
        "expires_at": "",
        "ttl_seconds": 0.0,
        "rejected_skill_ids": [],
    }
    if not clean_task:
        return empty
    with _LEASE_LOCK:
        lease = _load_lease(clean_task, db_path)
        if lease is None:
            return empty
        expired = _current_ts() >= float(lease["expires_ts"] or 0.0)
        _drop_lease(clean_task, db_path)
    return {
        "task_id": clean_task,
        "skill_ids": list(lease["skill_ids"]),
        "status": "expired" if expired else "returned",
        "expired": expired,
        "issued_at": lease["issued_at"],
        "expires_at": lease["expires_at"],
        "ttl_seconds": 0.0,
        "rejected_skill_ids": [],
    }


def get_active_skills(task_id: str, *, db_path: Optional[str] = None) -> List[str]:
    """Aktuell gültige Skills — nach TTL-Ablauf leer (automatische Rückgabe)."""
    clean_task = str(task_id or "").strip()
    if not clean_task:
        return []
    with _LEASE_LOCK:
        lease = _load_lease(clean_task, db_path)
        if lease is None:
            return []
        if _current_ts() >= float(lease["expires_ts"] or 0.0):
            _drop_lease(clean_task, db_path)
            return []
        return list(lease["skill_ids"])


def finalize_task_skills(task_id: str, *, db_path: Optional[str] = None) -> LeaseResult:
    """Expliziter Finalize-Hook für Dispatcher/Pipeline (dünner Alias)."""
    return return_skills(task_id, db_path=db_path)


def purge_expired_leases(*, db_path: Optional[str] = None) -> int:
    """Räumt abgelaufene Leases im ``kv_store`` auf (TTL-Sweeper)."""
    removed = 0
    with _LEASE_LOCK:
        try:
            with _get_kv_conn(db_path) as conn:
                rows = conn.execute(
                    "SELECT key, value FROM kv_store WHERE key LIKE ?",
                    (f"{TASK_SKILL_LEASE_PREFIX}%",),
                ).fetchall()
        except Exception as exc:
            logger.debug("[TaskSizing] TTL-Sweep nicht möglich: %s", exc)
            return 0
        now = _current_ts()
        for key, value in rows:
            try:
                raw = json.loads(value)
                expires = float(raw.get("expires_ts") or 0.0)
            except Exception:
                expires = 0.0
            if expires and now < expires:
                continue
            with _get_kv_conn(db_path) as conn:
                conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
                conn.commit()
            removed += 1
    return removed


@contextmanager
def leased_skills(
    task_id: str,
    skill_ids: List[str],
    *,
    ttl_seconds: float,
    db_path: Optional[str] = None,
    skills_dir: Optional[str] = None,
) -> Iterator[List[str]]:
    """Kontextmanager: Ausgabe bei Eintritt, Rückgabe in ``finally``.

    Damit sind sowohl reguläres ``finalize`` als auch Exception-Pfade
    abgedeckt, ohne dass der Aufrufer die Rückgabe vergessen kann.
    """
    issued = issue_skills(
        task_id, skill_ids, ttl_seconds=ttl_seconds,
        db_path=db_path, skills_dir=skills_dir,
    )
    try:
        yield list(issued["skill_ids"])
    finally:
        return_skills(task_id, db_path=db_path)
