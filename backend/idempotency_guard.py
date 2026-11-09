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
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                tool_name TEXT,
                payload_hash TEXT,
                result_json TEXT,
                duplicate_blocks_count INTEGER DEFAULT 0,
                created_at TEXT,
                expires_at TEXT,
                status TEXT DEFAULT 'pending',
                executed_at TEXT
            )
        """)
        # N-04: Migration fuer Bestands-Datenbanken (Spalte status/executed_at).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(idempotency_ledger)").fetchall()}
        if cols and "status" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN status TEXT DEFAULT 'pending'")
        if cols and "executed_at" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN executed_at TEXT")
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

            # N-04 (Race-Fix): INSERT OR IGNORE + Ruecklesen statt SELECT->INSERT.
            # Zwei gleichzeitige Aufrufe mit gleichem Key liefen vorher beide in
            # den zweiten INSERT -> IntegrityError -> 500 statt Duplikat-Block.
            cur = conn.execute("""
                INSERT OR IGNORE INTO idempotency_ledger
                (idempotency_key, tool_name, payload_hash, result_json, duplicate_blocks_count, created_at, expires_at, status)
                VALUES (?, ?, ?, NULL, 0, ?, ?, 'pending')
            """, (idem_key, tool_name, payload_hash, now_iso, exp_iso))
            if cur.rowcount > 0:
                # Erster Anruf: mit echtem Resultat sofort als executed registrieren.
                if execution_result:
                    conn.execute("""
                        UPDATE idempotency_ledger
                        SET status = 'executed', result_json = ?, executed_at = ?
                        WHERE idempotency_key = ?
                    """, (json.dumps(execution_result, ensure_ascii=False), now_iso, idem_key))
                conn.commit()
                return {
                    "allowed": True,
                    "duplicate_detected": False,
                    "blocked": False,
                    "idempotency_key": idem_key,
                    "tool_name": tool_name,
                    "status": "executed" if execution_result else "pending_registered",
                    "expires_at": exp_iso
                }

            existing = conn.execute(
                "SELECT * FROM idempotency_ledger WHERE idempotency_key = ?",
                (idem_key,)
            ).fetchone()

            if existing["status"] == "executed":
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

            # N-04: Der erste Versuch ist noch PENDING (Ausfuehrung nicht
            # abgeschlossen oder fehlgeschlagen). Ein Retry wird ZUGELASSEN,
            # bekommt aber KEIN erfundenes Ergebnis (frueher: Platzhalter
            # {"status": "executed_once"} fuer 24 h) und die Laufzeit wird
            # erneuert. Erst ein reales Ergebnis (record_execution_result)
            # macht den Key zum echten Duplikat-Filter.
            conn.execute(
                "UPDATE idempotency_ledger SET created_at = ?, expires_at = ? WHERE idempotency_key = ?",
                (now_iso, exp_iso, idem_key)
            )
            if execution_result:
                conn.execute("""
                    UPDATE idempotency_ledger
                    SET status = 'executed', result_json = ?, executed_at = ?
                    WHERE idempotency_key = ?
                """, (json.dumps(execution_result, ensure_ascii=False), now_iso, idem_key))
            conn.commit()
            return {
                "allowed": True,
                "duplicate_detected": False,
                "blocked": False,
                "previous_attempt_pending": True,
                "idempotency_key": idem_key,
                "tool_name": tool_name,
                "status": "executed" if execution_result else "pending_registered",
                "expires_at": exp_iso
            }

    def record_execution_result(self, key: str, result: Dict[str, Any]) -> bool:
        """Verbucht ein reales Ausfuehrungsergebnis (Phase 2, N-04).

        Erst ab hier gilt der Key als ausgefuehrt — Retries vorher sind
        Versuche, kein erfundener Erfolg.
        """
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            cur = conn.execute("""
                UPDATE idempotency_ledger
                SET status = 'executed', result_json = ?, executed_at = ?
                WHERE idempotency_key = ? AND status != 'executed'
            """, (json.dumps(result, ensure_ascii=False), now_iso, key))
            conn.commit()
        return cur.rowcount > 0

    def invalidate_key(self, key: str) -> bool:
        """Loescht einen Key nach FEHLGESCHLAGENER Ausfuehrung (Phase 2b, N-04),
        damit ein Retry frisch registrieren kann.
        """
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            cur = conn.execute(
                "DELETE FROM idempotency_ledger WHERE idempotency_key = ?", (key,)
            )
            conn.commit()
        return cur.rowcount > 0


idempotency_guard = IdempotencyGuard()
