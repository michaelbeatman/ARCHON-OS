"""M67 — Host-seitige Zustandsführung in der bestehenden ``agentic_memory.db``.

Der Job-Zustand wandert aus der wachsenden Chat-Historie in den Host: ein
versionsgeführter Datensatz in der bereits vorhandenen ``kv_store``-Tabelle.
Es wird bewusst KEINE neue Tabelle angelegt. ``backend/db_paths.resolve_db``
bleibt die einzige Autorität für den Datenbankpfad.

Da ``agentic_memory.db`` nicht in den physisch isolierten Mandanten-DBs
(``tenant_context``) geführt wird, erfolgt die Mandantentrennung über einen
sanitisierten, hierarchischen ``kv_store``-Key. Keys sind damit deterministisch,
nicht vom Benutzer/Prompt kontrollierbar und für andere Mandanten unsichtbar.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, fields
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from backend.db_paths import get_db_connection, resolve_db

logger = logging.getLogger("archon.host_state_store")

STATE_KEY_PREFIX = "m67/host_state/v1"
MAX_SESSION_ID_CHARS = 200
MAX_JOB_ID_CHARS = 200
MAX_STATUS_CHARS = 64
MAX_TEXT_CHARS = 4000
MAX_STEPS = 64
MAX_RESULTS = 32
MAX_RESULT_KEYS = 32

_KV_DDL = "CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)"
_SESSION_KEY_RE = re.compile(r"[^A-Za-z0-9_.:-]")
_TENANT_KEY_RE = re.compile(r"[^a-zA-Z0-9_-]")


class HostStateError(RuntimeError):
    """Ungültiger oder nicht lesbarer Host-Zustand (fail-closed)."""


class HostStateConflict(HostStateError):
    """VersionUneinigkeit — ein veralteter Schreibzugriff wurde verweigert."""


class HostStateCorrupt(HostStateError):
    """Gespeicherter Zustand entspricht nicht dem erwarteten Format."""


def _tenant_key_part(tenant_id: Optional[str]) -> str:
    """Mandantenanteil des Keys — identisch mit ``tenant_context.sanitize_tenant_id``."""
    try:
        from backend.tenant_context import sanitize_tenant_id

        result = sanitize_tenant_id(tenant_id)
    except Exception:
        raw = str(tenant_id or "default").strip()
        result = _TENANT_KEY_RE.sub("_", raw).strip("_") or "default"
    return str(result or "default")[:128]


def _session_key_part(session_id: Optional[str]) -> str:
    """Sitzungsanteil des Keys; Sonderzeichen werden deterministisch ersetzt."""
    raw = str(session_id or "").strip()[:MAX_SESSION_ID_CHARS]
    cleaned = _SESSION_KEY_RE.sub("_", raw).strip("_")
    if not cleaned:
        raise HostStateError("session_id fehlt oder ist ungültig")
    return cleaned


def state_key(session_id: str, tenant_id: Optional[str] = None) -> str:
    """Deterministischer, mandanten- und sitzungsgebundener ``kv_store``-Key."""
    return f"{STATE_KEY_PREFIX}/{_tenant_key_part(tenant_id)}/{_session_key_part(session_id)}"


def _clipped(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 12)] + "[GEKÜRZT]"


def _bounded_dict_list(value: Any, limit: int, key_limit: int, text_limit: int) -> Tuple[Dict[str, Any], ...]:
    """Begrenzt Listeneinträge deterministisch — der Zustand darf nicht wachsen."""
    if not isinstance(value, (list, tuple)):
        return ()
    out: List[Dict[str, Any]] = []
    for item in list(value)[:limit]:
        if not isinstance(item, Mapping):
            continue
        entry: Dict[str, Any] = {}
        for key, val in list(item.items())[:key_limit]:
            entry[_clipped(key, 64)] = _clipped(val, text_limit)
        out.append(entry)
    return tuple(out)


@dataclass(frozen=True)
class HostState:
    """Unveränderlicher, versionierter Momentaufnahme des Host-Job-Zustands."""

    session_id: str
    job_id: str
    version: int
    status: str = "pending"
    goal: str = ""
    next_action: str = ""
    steps: Tuple[Dict[str, Any], ...] = ()
    results: Tuple[Dict[str, Any], ...] = ()
    tenant_id: str = "default"
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialisierbare, bewusst begrenzte Darstellung (keine Chat-Historie)."""
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "job_id": self.job_id,
            "version": self.version,
            "status": self.status,
            "goal": self.goal,
            "next_action": self.next_action,
            "steps": [dict(entry) for entry in self.steps[:MAX_STEPS]],
            "results": [dict(entry) for entry in self.results[:MAX_RESULTS]],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> HostState:
        """Streng typisierte Rekonstruktion; ungültige Daten werden abgelehnt."""
        if not isinstance(raw, Mapping):
            raise HostStateCorrupt("host_state muss ein Objekt sein")
        session_id = str(raw.get("session_id") or "").strip()[:MAX_SESSION_ID_CHARS]
        if not session_id or _session_key_part(session_id) != session_id:
            # Nur kanonische IDs zulassen — verhindert Key-/Pfad-Tricks.
            raise HostStateError("Ungültige session_id im Host-Zustand")
        version = raw.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise HostStateCorrupt("Ungültige Version im Host-Zustand")
        try:
            updated_at = float(raw.get("updated_at") or 0.0)
        except (TypeError, ValueError) as exc:
            raise HostStateCorrupt("Ungültiger Zeitstempel im Host-Zustand") from exc
        return cls(
            session_id=session_id,
            job_id=_clipped(raw.get("job_id") or "", MAX_JOB_ID_CHARS),
            version=version,
            status=_clipped(raw.get("status") or "pending", MAX_STATUS_CHARS),
            goal=_clipped(raw.get("goal") or "", MAX_TEXT_CHARS),
            next_action=_clipped(raw.get("next_action") or "", MAX_TEXT_CHARS),
            steps=_bounded_dict_list(raw.get("steps"), MAX_STEPS, 12, 400),
            results=_bounded_dict_list(raw.get("results"), MAX_RESULTS, MAX_RESULT_KEYS, 800),
            tenant_id=_tenant_key_part(raw.get("tenant_id")),
            updated_at=max(0.0, updated_at),
        )


def initial_state(
    session_id: str,
    job_id: str,
    goal: str = "",
    *,
    tenant_id: Optional[str] = None,
    status: str = "pending",
) -> HostState:
    """Erzeugt einen frischen Zustand (Version 1) ohne Chat-Historie."""
    return HostState(
        session_id=session_id,
        job_id=job_id,
        version=1,
        status=status,
        goal=goal,
        tenant_id=_tenant_key_part(tenant_id),
        updated_at=time.time(),
    )


class HostStateStore:
    """Versionierter, atomarer Zustandsspeicher auf der bestehenden kv_store."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        # Expliziter Pfad nur für Tests/Injektion; produktiv immer SSOT-Resolver.
        self._db_path = str(db_path) if db_path else resolve_db("agentic_memory.db")

    def _connect(self) -> sqlite3.Connection:
        conn = get_db_connection(self._db_path)
        conn.execute(_KV_DDL)
        return conn

    @staticmethod
    def _decode(raw_value: Any, *, tenant_id: str) -> HostState:
        try:
            payload = json.loads(str(raw_value))
        except (TypeError, ValueError) as exc:
            raise HostStateCorrupt("Host-Zustand ist kein gültiges JSON") from exc
        state = HostState.from_dict(payload)
        # Verteidigung in der Tiefe: ein fremder Mandant darf nie lesen/überschreiben.
        if state.tenant_id != tenant_id:
            raise HostStateError("Mandantenkonflikt beim Host-Zustand")
        return state

    def load(self, session_id: str, tenant_id: Optional[str] = None) -> Optional[HostState]:
        """Liest den Zustand; ``None`` bedeutet: noch kein Zustand vorhanden."""
        tid = _tenant_key_part(tenant_id)
        key = state_key(session_id, tid)
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return self._decode(row[0], tenant_id=tid)

    def save(self, state: HostState) -> HostState:
        """Speichert einen neuen Zustand; veraltete Versionen werden abgelehnt."""
        normalized = HostState.from_dict(state.to_dict())
        key = state_key(normalized.session_id, normalized.tenant_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
                if row is not None:
                    existing = self._decode(row[0], tenant_id=normalized.tenant_id)
                    if normalized.version <= existing.version:
                        raise HostStateConflict(
                            f"Veraltete Host-State-Version {normalized.version} <= {existing.version}"
                        )
                conn.execute(
                    "INSERT INTO kv_store (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(normalized.to_dict(), sort_keys=True, ensure_ascii=False)),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return normalized

    def advance(
        self,
        session_id: str,
        expected_version: int,
        mutate: Callable[[HostState], HostState],
        *,
        tenant_id: Optional[str] = None,
    ) -> HostState:
        """Compare-and-Swap: Mutation NUR bei exakt passender Version."""
        tid = _tenant_key_part(tenant_id)
        key = state_key(session_id, tid)
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise HostStateError("expected_version muss eine Ganzzahl sein")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
                current = self._decode(row[0], tenant_id=tid) if row is not None else None
                if current is None:
                    raise HostStateConflict("Kein Host-Zustand zum Fortschreiben vorhanden")
                if current.version != expected_version:
                    raise HostStateConflict(
                        f"Host-State-Version {current.version} != erwartet {expected_version}"
                    )
                mutated = mutate(current)
                if not isinstance(mutated, HostState):
                    raise HostStateError("mutate muss einen HostState zurückgeben")
                data = mutated.to_dict()
                data.update(
                    {
                        "session_id": current.session_id,
                        "tenant_id": current.tenant_id,
                        "version": expected_version + 1,
                        "updated_at": time.time(),
                    }
                )
                candidate = HostState.from_dict(data)
                conn.execute(
                    "UPDATE kv_store SET value = ? WHERE key = ?",
                    (json.dumps(candidate.to_dict(), sort_keys=True, ensure_ascii=False), key),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return candidate


def state_fields() -> Tuple[str, ...]:
    """Bekannte Felder — für Diagnose/Tests, ohne Zustandswerte zu exponieren."""
    return tuple(f.name for f in fields(HostState))


__all__ = (
    "HostState",
    "HostStateError",
    "HostStateConflict",
    "HostStateCorrupt",
    "HostStateStore",
    "initial_state",
    "state_key",
    "state_fields",
    "STATE_KEY_PREFIX",
)
