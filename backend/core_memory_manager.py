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
                updated_at TEXT
            )
        """)
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

    def list_blocks(self) -> Dict[str, Any]:
        cfg = _get_cfg()
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT block_key, block_title, content, pinned, updated_at FROM core_memory_blocks ORDER BY block_key"
            ).fetchall()
            blocks = [dict(r) for r in rows]

        prompt_preview = self.compile_system_prompt_injection()
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "max_pinned_blocks": int(cfg.get("max_pinned_blocks", 10)),
            "max_chars_per_block": int(cfg.get("max_chars_per_block", 800)),
            "total_blocks": len(blocks),
            "blocks": blocks,
            "compiled_system_prompt_block": prompt_preview
        }

    def upsert_block(self, block_key: str, content: str, block_title: str = "", mode: str = "replace") -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"updated": False, "bypassed": True}

        max_chars = int(cfg.get("max_chars_per_block", 800))
        max_blocks = int(cfg.get("max_pinned_blocks", 10))
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            existing = conn.execute(
                "SELECT block_title, content FROM core_memory_blocks WHERE block_key = ?",
                (block_key,)
            ).fetchone()

            if existing:
                title_final = block_title or existing[0]
                new_content = f"{existing[1].rstrip()}\n{content.strip()}" if mode == "append" else content.strip()
            else:
                total = conn.execute("SELECT COUNT(*) FROM core_memory_blocks").fetchone()[0]
                if total >= max_blocks:
                    return {"updated": False, "reason": f"Max pinned blocks ({max_blocks}) erreicht."}
                title_final = block_title or block_key
                new_content = content.strip()

            truncated = False
            if len(new_content) > max_chars:
                new_content = new_content[:max_chars]
                truncated = True

            conn.execute("""
                INSERT INTO core_memory_blocks (block_key, block_title, content, pinned, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(block_key) DO UPDATE SET
                    block_title = excluded.block_title,
                    content = excluded.content,
                    updated_at = excluded.updated_at
            """, (block_key, title_final, new_content, now_iso))
            conn.commit()

        return {
            "updated": True,
            "block_key": block_key,
            "mode": mode,
            "char_length": len(new_content),
            "truncated_to_quota": truncated
        }

    def compile_system_prompt_injection(self) -> str:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)) or not bool(cfg.get("auto_inject_into_system_prompt", True)):
            return ""
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            rows = conn.execute(
                "SELECT block_key, block_title, content FROM core_memory_blocks WHERE pinned = 1 ORDER BY block_key"
            ).fetchall()
        if not rows:
            return ""
        lines = ["<CORE_WORKING_MEMORY>"]
        for key, title, content in rows:
            lines.append(f"  <{key} title=\"{title}\">{content}</{key}>")
        lines.append("</CORE_WORKING_MEMORY>")
        return "\n".join(lines)


core_memory_manager = CoreMemoryManager()
