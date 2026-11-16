"""
backend/core_memory_manager.py
Paket 2 (Feature 9): 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (Pinned Working Memory vs. Archival Memory).
Verwaltet fest im System-Prompt angepinnte Arbeitsgedächtnis-Blöcke (z. B. `human_persona`, `system_persona`,
`active_project_facts`), die der Agent zur Laufzeit selbstständig via `append` oder `replace` aktualisieren kann.
"""

import os
import sqlite3

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
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


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
                tenant_id TEXT DEFAULT 'default'
            )
        """)
        for col, cdef in (("agent_id", "TEXT DEFAULT 'global'"), ("tenant_id", "TEXT DEFAULT 'default'")):
            try:
                conn.execute(f"ALTER TABLE core_memory_blocks ADD COLUMN {col} {cdef}")
            except sqlite3.OperationalError:
                pass
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

    def list_blocks(self, agent_id: str = "global", tenant_id: str = "default") -> Dict[str, Any]:
        cfg = _get_cfg()
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT block_key, block_title, content, pinned, updated_at, agent_id, tenant_id
                FROM core_memory_blocks
                WHERE COALESCE(tenant_id, 'default') = ?
                  AND (COALESCE(agent_id, 'global') = ? OR COALESCE(agent_id, 'global') = 'global')
                ORDER BY block_key
                """,
                (tenant_id, agent_id),
            ).fetchall()
            blocks = [dict(r) for r in rows]

        prompt_preview = self.compile_system_prompt_injection(agent_id=agent_id, tenant_id=tenant_id)
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
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"updated": False, "bypassed": True}

        max_chars = int(cfg.get("max_chars_per_block", 800))
        max_blocks = int(cfg.get("max_pinned_blocks", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        scoped_key = block_key if (agent_id == "global" and tenant_id == "default") else f"{tenant_id}:{agent_id}:{block_key}"

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
                INSERT INTO core_memory_blocks (block_key, block_title, content, pinned, updated_at, agent_id, tenant_id)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(block_key) DO UPDATE SET
                    block_title = excluded.block_title,
                    content = excluded.content,
                    updated_at = excluded.updated_at,
                    agent_id = excluded.agent_id,
                    tenant_id = excluded.tenant_id
            """, (scoped_key, title_final, new_content, now_iso, agent_id, tenant_id))
            conn.commit()

        return {
            "updated": True,
            "block_key": scoped_key,
            "mode": mode,
            "char_length": len(new_content),
            "truncated_to_quota": truncated
        }

    def compile_system_prompt_injection(self, agent_id: str = "global", tenant_id: str = "default") -> str:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)) or not bool(cfg.get("auto_inject_into_system_prompt", True)):
            return ""
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            rows = conn.execute(
                """
                SELECT block_key, block_title, content
                FROM core_memory_blocks
                WHERE pinned = 1
                  AND COALESCE(tenant_id, 'default') = ?
                  AND (COALESCE(agent_id, 'global') = ? OR COALESCE(agent_id, 'global') = 'global')
                ORDER BY block_key
                """,
                (tenant_id, agent_id),
            ).fetchall()
        if not rows:
            return ""
        from xml.sax.saxutils import escape as _xml_escape
        lines = ["<CORE_WORKING_MEMORY>"]
        for key, title, content in rows:
            safe_key = "".join(c if (c.isalnum() or c in "_-") else "_" for c in str(key or "block")) or "block"
            safe_title = _xml_escape(str(title or ""), {'"': "&quot;"})
            safe_content = _xml_escape(str(content or ""))
            lines.append(f'  <{safe_key} title="{safe_title}">{safe_content}</{safe_key}>')
        lines.append("</CORE_WORKING_MEMORY>")
        return "\n".join(lines)


core_memory_manager = CoreMemoryManager()
