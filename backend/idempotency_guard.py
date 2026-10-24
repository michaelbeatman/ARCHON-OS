"""
backend/idempotency_guard.py
Paket 3 (Feature 13): Idempotency-Keys & Tool-Call-Deduplizierung.
Verhindert, dass bei Retries, Netzwerk-Timeouts oder Agenten-Schleifen kritische Seiteneffekte
(E-Mail-Versand, Webhook-Call, Datenbank-Buchung) doppelt ausgeführt werden.
"""

import os
import json
import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("idempotency_guard")
    except Exception:
        return {
            "enabled": True,
            "ttl_hours": 24,
            "block_duplicate_side_effects": True
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                tool_name TEXT,
                payload_hash TEXT,
                result_json TEXT,
                duplicate_blocks_count INTEGER DEFAULT 0,
                created_at TEXT,
                expires_at TEXT
            )
        """)
        conn.commit()


class IdempotencyGuard:
    def __init__(self):
        _init_db()

    def check_or_register(
        self,
        tool_name: str,
        params: Dict[str, Any],
        explicit_key: Optional[str] = None,
        execution_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        block_dups = bool(cfg.get("block_duplicate_side_effects", True))
        ttl_hours = int(cfg.get("ttl_hours", 24))

        canonical_params = json.dumps(params, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(f"{tool_name}::{canonical_params}".encode("utf-8")).hexdigest()
        idem_key = explicit_key or f"idem-{payload_hash[:20]}"

        if not enabled:
            return {
                "allowed": True,
                "duplicate_detected": False,
                "bypassed": True,
                "idempotency_key": idem_key
            }

        now = datetime.now()
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_iso = (now + timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("DELETE FROM idempotency_ledger WHERE expires_at < ?", (now_iso,))
            existing = conn.execute(
                "SELECT * FROM idempotency_ledger WHERE idempotency_key = ?",
                (idem_key,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE idempotency_ledger SET duplicate_blocks_count = duplicate_blocks_count + 1 WHERE idempotency_key = ?",
                    (idem_key,)
                )
                conn.commit()
                return {
                    "allowed": not block_dups,
                    "duplicate_detected": True,
                    "blocked": block_dups,
                    "idempotency_key": idem_key,
                    "tool_name": tool_name,
                    "original_executed_at": existing["created_at"],
                    "duplicate_blocks_count": existing["duplicate_blocks_count"] + 1,
                    "cached_result": json.loads(existing["result_json"] or "{}")
                }

            conn.execute("""
                INSERT INTO idempotency_ledger
                (idempotency_key, tool_name, payload_hash, result_json, duplicate_blocks_count, created_at, expires_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
            """, (
                idem_key,
                tool_name,
                payload_hash,
                json.dumps(execution_result or {"status": "executed_once"}, ensure_ascii=False),
                now_iso,
                exp_iso
            ))
            conn.commit()

        return {
            "allowed": True,
            "duplicate_detected": False,
            "blocked": False,
            "idempotency_key": idem_key,
            "tool_name": tool_name,
            "expires_at": exp_iso
        }


idempotency_guard = IdempotencyGuard()
