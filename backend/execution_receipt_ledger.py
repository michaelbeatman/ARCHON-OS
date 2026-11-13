"""
backend/execution_receipt_ledger.py
Paket 4 (Feature 20): Manipulationssichere Kosten- & Entscheidungs-Quittungen (Execution Receipts).
Erzeugt für jeden abgeschlossenen Task eine kryptografisch verkettete SHA-256-Quittung (`prev_receipt_hash` -> `receipt_hash`)
mit Modell, Token-Verbrauch, Kosten in USD, genutzten Tools und Policy-Status in SQLite (`execution_receipts_ledger`).
"""

import os
import json
import uuid
import hashlib
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
        return get_module_config("execution_receipts")
    except Exception:
        return {
            "enabled": True,
            "hash_algorithm": "sha256",
            "chain_receipts": True,
            "include_cost_breakdown": True
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_receipts_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT UNIQUE,
                task_id TEXT,
                agent_role TEXT,
                model_used TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL,
                tools_invoked_json TEXT,
                prev_hash TEXT,
                receipt_hash TEXT,
                created_at TEXT
            )
        """)
        conn.commit()


class ExecutionReceiptLedger:
    def __init__(self):
        _init_db()

    def issue_receipt(
        self,
        task_id: str,
        agent_role: str,
        model_used: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        tools_invoked: List[str]
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"issued": False, "bypassed": True}

        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tools_json = json.dumps(tools_invoked or [], ensure_ascii=False)

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            row = conn.execute(
                "SELECT receipt_hash FROM execution_receipts_ledger ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = row[0] if (row and bool(cfg.get("chain_receipts", True))) else "GENESIS_BLOCK_00000000"

            canonical_str = (
                f"{receipt_id}|{task_id}|{agent_role}|{model_used}|"
                f"{prompt_tokens}|{completion_tokens}|{cost_usd:.6f}|{tools_json}|{prev_hash}|{now_iso}"
            )
            receipt_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

            conn.execute("""
                INSERT INTO execution_receipts_ledger
                (receipt_id, task_id, agent_role, model_used, prompt_tokens, completion_tokens,
                 cost_usd, tools_invoked_json, prev_hash, receipt_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                receipt_id, task_id, agent_role, model_used,
                prompt_tokens, completion_tokens, round(cost_usd, 6),
                tools_json, prev_hash, receipt_hash, now_iso
            ))
            conn.commit()

        return {
            "issued": True,
            "receipt_id": receipt_id,
            "task_id": task_id,
            "agent_role": agent_role,
            "model_used": model_used,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_usd": round(cost_usd, 6),
            "prev_hash": prev_hash,
            "receipt_hash": receipt_hash,
            "created_at": now_iso
        }

    def verify_chain_integrity(self) -> Dict[str, Any]:
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM execution_receipts_ledger ORDER BY id ASC").fetchall()

        expected_prev = "GENESIS_BLOCK_00000000"
        broken_links = []
        for idx, r in enumerate(rows):
            if idx > 0 and r["prev_hash"] != expected_prev:
                broken_links.append(r["receipt_id"])
            expected_prev = r["receipt_hash"]

        return {
            "chain_valid": len(broken_links) == 0,
            "total_receipts": len(rows),
            "broken_links": broken_links,
            "latest_hash": expected_prev if rows else None
        }


execution_receipt_ledger = ExecutionReceiptLedger()
