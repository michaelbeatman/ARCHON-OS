"""
backend/core_memory_manager.py
Paket 2 (Feature 9): 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (Pinned Working Memory vs. Archival Memory).
Verwaltet fest im System-Prompt angepinnte Arbeitsgedächtnis-Blöcke (z. B. `human_persona`, `system_persona`,
`active_project_facts`), die der Agent zur Laufzeit selbstständig via `append` oder `replace` aktualisieren kann.

Batch C: Agent-Memory-Scope (private/shared/project/global) mit ACL, TTL und Projektzuordnung.
Der Scope ist kanonisch in diesem Modul definiert; offline_memory_vault.py spiegelt die Konstanten bewusst
ohne Import, um Import-Seiteneffekte (DB-Initialisierung) zu vermeiden.
"""
import logging
_archon_exc_logger = logging.getLogger("core_memory_manager")

import json
import os
import sqlite3
import time

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from datetime import datetime
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


# --- Kanonische Scope-Definitionen (Batch C) --------------------------------
SCOPE_PRIVATE = "private"   # nur fuer den Eigentuemer-Agenten sichtbar
SCOPE_SHARED = "shared"     # Eigentuemer + in der ACL gelistete Principals
SCOPE_PROJECT = "project"   # alle Agenten mit identischer project_id
SCOPE_GLOBAL = "global"     # alle Agenten (Legacy-Standard)
VALID_MEMORY_SCOPES = (SCOPE_PRIVATE, SCOPE_SHARED, SCOPE_PROJECT, SCOPE_GLOBAL)


def normalize_scope(scope: Optional[str]) -> str:
    """Validiert einen Scope und liefert den kanonischen Wert (leer => global)."""
    if scope is None or str(scope).strip() == "":
        return SCOPE_GLOBAL
    value = str(scope).strip().lower()
    if value not in VALID_MEMORY_SCOPES:
        raise ValueError(
            f"Ungueltiger Memory-Scope: {scope!r} "
            f"(erlaubt: {', '.join(VALID_MEMORY_SCOPES)})"
        )
    return value


def _normalize_acl(acl: Optional[Any]) -> List[str]:
    """Akzeptiert JSON-String, Liste/Tuple/Set oder ein einzelnes Principal."""
    if not acl:
        return []
    if isinstance(acl, str):
        try:
            acl = json.loads(acl)
        except (ValueError, TypeError):
            return []
    if isinstance(acl, (list, tuple, set)):
        return [str(x) for x in acl if x is not None and str(x)]
    return [str(acl)]


def _expires_from_ttl(ttl_seconds: Optional[float]) -> float:
    """REAL-Zeitstempel aus TTL; 0 bedeutet 'kein Ablauf'."""
    if ttl_seconds is None:
        return 0.0
    try:
        ttl = float(ttl_seconds)
    except (TypeError, ValueError):
        return 0.0
    return time.time() + ttl if ttl > 0 else 0.0


def _is_expired(expires_at: Optional[float]) -> bool:
    """True, wenn der REAL-Zeitstempel in der Vergangenheit liegt."""
    try:
        value = float(expires_at or 0.0)
    except (TypeError, ValueError):
        return False
    return value > 0 and value <= time.time()


def _row_is_visible(
    row: Any,
    agent_id: str,
    project_id: str = "",
    scope_filter: Optional[str] = None,
) -> bool:
    """Zentrale Sichtbarkeitsregel fuer Scope, ACL, TTL und Legacy-Agent-Filter."""
    try:
        data = dict(row)
    except (TypeError, ValueError):
        return False

    if _is_expired(data.get("expires_at")):
        return False

    raw_scope = str(data.get("scope") or "").strip().lower()
    row_scope = raw_scope if raw_scope in VALID_MEMORY_SCOPES else SCOPE_GLOBAL
    if scope_filter is not None and row_scope != normalize_scope(scope_filter):
        return False

    owner = str(data.get("agent_id") or "global")
    requester = str(agent_id or "global")
    acl = _normalize_acl(data.get("acl_json"))

    if row_scope == SCOPE_PRIVATE:
        return requester == owner
    if row_scope == SCOPE_SHARED:
        return requester == owner or requester in acl
    if row_scope == SCOPE_PROJECT:
        row_project = str(data.get("project_id") or "")
        return (bool(project_id) and project_id == row_project) or requester == owner

    # explizit global => fuer alle sichtbar; migrierte Legacy-Zeilen behalten
    # die bisherige agent_id-Regel als Fallback.
    if int(data.get("scope_explicit") or 0) == 1:
        return True
    return owner == "global" or requester == owner


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("core_memory_tier")
    except Exception:
        return {
            "enabled": True,
            "max_pinned_blocks": 10,
            "max_chars_per_block": 800,
            "auto_inject_into_system_prompt": True
        }


# Spalten inkl. Migration fuer bestehende Datenbanken (Batch C).
_CORE_COLUMNS = (
    ("agent_id", "TEXT DEFAULT 'global'"),
    ("tenant_id", "TEXT DEFAULT 'default'"),
    ("scope", "TEXT DEFAULT 'global'"),
    ("acl_json", "TEXT DEFAULT '[]'"),
    ("expires_at", "REAL DEFAULT 0"),
    ("project_id", "TEXT DEFAULT ''"),
    ("scope_explicit", "INTEGER DEFAULT 0"),
)
_CORE_SELECT = (
    "block_key, block_title, content, pinned, updated_at, agent_id, tenant_id, "
    "scope, acl_json, expires_at, project_id, scope_explicit"
)


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_memory_blocks (
                block_key TEXT PRIMARY KEY,
                block_title TEXT,
                content TEXT,
                pinned INTEGER DEFAULT 1,
                updated_at TEXT,
                agent_id TEXT DEFAULT 'global',
                tenant_id TEXT DEFAULT 'default',
                scope TEXT DEFAULT 'global',
                acl_json TEXT DEFAULT '[]',
                expires_at REAL DEFAULT 0,
                project_id TEXT DEFAULT '',
                scope_explicit INTEGER DEFAULT 0
            )
        """)
        for col, cdef in _CORE_COLUMNS:
            try:
                conn.execute(f"ALTER TABLE core_memory_blocks ADD COLUMN {col} {cdef}")
            except sqlite3.OperationalError as _exc:
                _archon_exc_logger.debug("[core_memory_manager] Ignorierte Ausnahme (Z.63): %s", _exc)
        # Standard-Blöcke anlegen, falls noch leer
        count = conn.execute("SELECT COUNT(*) FROM core_memory_blocks").fetchone()[0]
        if count == 0:
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            defaults = [
                ("human_profile", "Nutzer- & Arbeitsprofil", "Bevorzugt präzise Umsetzung in Fünferschritten mit Settings-Schaltern und Handbuch-Synchronisation."),
                ("system_persona", "Archon OS Kernel-Direktive", "Autonomes Agenten-Betriebssystem mit Zero-Trust-Governance, Selbstheilung und Hybrid-Memory."),
                ("active_goals", "Aktuelle Projekt-Ziele", "Ausbau der 25 State-of-the-Art Enterprise-Features inkl. System-Handbuch und Komplett-Glossar.")
            ]
            conn.executemany(
                "INSERT INTO core_memory_blocks (block_key, block_title, content, pinned, updated_at) VALUES (?, ?, ?, 1, ?)",
                [(k, t, c, now_iso) for k, t, c in defaults]
            )
        conn.commit()


class CoreMemoryManager:
    def __init__(self):
        _init_db()

    def list_blocks(
        self,
        agent_id: str = "global",
        tenant_id: str = "default",
        scope: Optional[str] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        scope_filter = normalize_scope(scope) if scope is not None else None
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT {_CORE_SELECT}
                FROM core_memory_blocks
                WHERE COALESCE(tenant_id, 'default') = ?
                ORDER BY block_key
                """,
                (tenant_id,),
            ).fetchall()
            blocks = [
                dict(r) for r in rows
                if _row_is_visible(r, agent_id, project_id=project_id, scope_filter=scope_filter)
            ]

        prompt_preview = self.compile_system_prompt_injection(
            agent_id=agent_id, tenant_id=tenant_id, scope=scope, project_id=project_id
        )
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "max_pinned_blocks": int(cfg.get("max_pinned_blocks", 10)),
            "max_chars_per_block": int(cfg.get("max_chars_per_block", 800)),
            "total_blocks": len(blocks),
            "blocks": blocks,
            "compiled_system_prompt_block": prompt_preview
        }

    def upsert_block(
        self,
        block_key: str,
        content: str,
        block_title: str = "",
        mode: str = "replace",
        agent_id: str = "global",
        tenant_id: str = "default",
        scope: str = SCOPE_GLOBAL,
        acl: Optional[Any] = None,
        ttl_seconds: Optional[float] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"updated": False, "bypassed": True}

        scope = normalize_scope(scope)
        max_chars = int(cfg.get("max_chars_per_block", 800))
        max_blocks = int(cfg.get("max_pinned_blocks", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        expires_at = _expires_from_ttl(ttl_seconds)
        acl_json = json.dumps(_normalize_acl(acl), ensure_ascii=False)

        # Schluessel bleibt rueckwaertskompatibel; Scope/Projekt ergaenzen nur bei Bedarf.
        key_parts: List[str] = []
        if not (agent_id == "global" and tenant_id == "default"):
            key_parts.append(f"{tenant_id}:{agent_id}")
        if scope != SCOPE_GLOBAL:
            key_parts.append(scope)
        if project_id:
            key_parts.append(f"proj:{project_id}")
        scoped_key = ":".join(key_parts + [block_key]) if key_parts else block_key

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            existing = conn.execute(
                "SELECT block_title, content FROM core_memory_blocks WHERE block_key = ?",
                (scoped_key,)
            ).fetchone()

            if existing:
                title_final = block_title or existing[0]
                new_content = f"{existing[1].rstrip()}\n{content.strip()}" if mode == "append" else content.strip()
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM core_memory_blocks WHERE COALESCE(tenant_id, 'default') = ? AND COALESCE(agent_id, 'global') = ?",
                    (tenant_id, agent_id),
                ).fetchone()[0]
                if total >= max_blocks:
                    return {"updated": False, "reason": f"Max pinned blocks ({max_blocks}) erreicht."}
                title_final = block_title or block_key
                new_content = content.strip()

            truncated = False
            if len(new_content) > max_chars:
                new_content = new_content[:max_chars]
                truncated = True

            conn.execute("""
                INSERT INTO core_memory_blocks (
                    block_key, block_title, content, pinned, updated_at,
                    agent_id, tenant_id, scope, acl_json, expires_at, project_id, scope_explicit
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(block_key) DO UPDATE SET
                    block_title = excluded.block_title,
                    content = excluded.content,
                    updated_at = excluded.updated_at,
                    agent_id = excluded.agent_id,
                    tenant_id = excluded.tenant_id,
                    scope = excluded.scope,
                    acl_json = excluded.acl_json,
                    expires_at = excluded.expires_at,
                    project_id = excluded.project_id,
                    scope_explicit = excluded.scope_explicit
            """, (
                scoped_key, title_final, new_content, now_iso,
                agent_id, tenant_id, scope, acl_json, expires_at, project_id,
            ))
            conn.commit()

        return {
            "updated": True,
            "block_key": scoped_key,
            "mode": mode,
            "char_length": len(new_content),
            "truncated_to_quota": truncated,
            "scope": scope,
        }

    def compile_system_prompt_injection(
        self,
        agent_id: str = "global",
        tenant_id: str = "default",
        scope: Optional[str] = None,
        project_id: str = "",
    ) -> str:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)) or not bool(cfg.get("auto_inject_into_system_prompt", True)):
            return ""
        scope_filter = normalize_scope(scope) if scope is not None else None
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT {_CORE_SELECT}
                FROM core_memory_blocks
                WHERE pinned = 1
                  AND COALESCE(tenant_id, 'default') = ?
                  AND (COALESCE(agent_id, 'global') = ? OR COALESCE(agent_id, 'global') = 'global')
                ORDER BY block_key
                """,
                (tenant_id, agent_id),
            ).fetchall()
        visible = [
            r for r in rows
            if _row_is_visible(r, agent_id, project_id=project_id, scope_filter=scope_filter)
        ]
        if not visible:
            return ""
        from xml.sax.saxutils import escape as _xml_escape
        lines = ["<CORE_WORKING_MEMORY>"]
        for row in visible:
            key = row["block_key"]
            title = row["block_title"]
            content = row["content"]
            safe_key = "".join(c if (c.isalnum() or c in "_-") else "_" for c in str(key or "block")) or "block"
            safe_title = _xml_escape(str(title or ""), {'"': "&quot;"})
            safe_content = _xml_escape(str(content or ""))
            lines.append(f'  <{safe_key} title="{safe_title}">{safe_content}</{safe_key}>')
        lines.append("</CORE_WORKING_MEMORY>")
        return "\n".join(lines)


core_memory_manager = CoreMemoryManager()
