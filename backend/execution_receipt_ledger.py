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
import threading

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from datetime import datetime, timezone
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEDGER_LOCK = threading.RLock()

# HMAC statt nacktem SHA-256: mit DB-Schreibzugriff koennte sonst die gesamte
# Kette ab Block 1 neu signiert werden. Der Key kommt ausschliesslich aus der
# ENV (gleicher Zweck wie ARCHON_AUDIT_HMAC_KEY, aber eigener Namespace).
RECEIPT_HMAC_PREFIX = "hmac-sha256:"
# Audit 23.11.2026: eigener Key-Namespace mit Domain-Separation. Fällt nur
# zu Installationen ohne separaten Key zurück (Legacy-Kompatibilität).
_RECEIPT_KEY_ENV = "ARCHON_RECEIPT_HMAC_KEY"
_LEGACY_KEY_ENV = "ARCHON_AUDIT_HMAC_KEY"
_HMAC_DOMAIN = b"archon-receipt-chain:v1:"
_RECEIPT_EPOCHS_ENV = "ARCHON_RECEIPT_HMAC_EPOCHS"
_LEGACY_EPOCHS_ENV = "ARCHON_AUDIT_HMAC_EPOCHS"
_RECEIPT_EPOCH_FROM_ENV = "ARCHON_RECEIPT_HMAC_EPOCH_FROM"
_LEGACY_EPOCH_FROM_ENV = "ARCHON_AUDIT_HMAC_EPOCH_FROM"


def _receipt_epochs() -> list:
    """C (Audit): (from_block, key)-Epochen analog zu audit_log.py.

    Jeder Block wird mit dem Key verifiziert, der bei seinem Schreiben galt.
    Ohne Konfiguration gibt es genau eine Epoche ab Block 0 — damit bleiben
    alle bestehenden Quittungen nach diesem Fix unveraendert verifizierbar.
    Das JSON-Format entspricht ARCHON_AUDIT_HMAC_EPOCHS:
    ``[{"key": "...", "from_block": 1}, ...]``.
    """
    epochs: list = []
    raw = os.environ.get(_RECEIPT_EPOCHS_ENV, "").strip()
    if not raw:
        raw = os.environ.get(_LEGACY_EPOCHS_ENV, "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    key = str(item.get("key", "")).strip().encode("utf-8")
                    if key:
                        epochs.append((int(item.get("from_block", 0)), key))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Ungueltige Receipt-HMAC-Epochen: %s", exc)
    key = os.environ.get(_RECEIPT_KEY_ENV, "").strip()
    if key:
        from_env = _RECEIPT_EPOCH_FROM_ENV
    else:
        key = os.environ.get(_LEGACY_KEY_ENV, "").strip()
        from_env = _LEGACY_EPOCH_FROM_ENV
    if key:
        try:
            start = int(os.environ.get(from_env, "0") or 0)
        except ValueError:
            start = 0
        epochs.append((start, key.encode("utf-8")))
    try:
        return sorted(set(epochs))
    except Exception:
        return epochs


def _receipt_key_for_block(block_id) -> bytes:
    epochs = _receipt_epochs()
    if not epochs:
        return b""
    if block_id is None:
        return epochs[-1][1]
    try:
        block_num = int(block_id)
    except (TypeError, ValueError):
        return epochs[-1][1]
    usable = [key for start, key in epochs if start <= block_num]
    return usable[-1] if usable else b""


def _receipt_key() -> bytes:
    """Aktueller (juengster) Key — rueckwaerts kompatibel mit alten Aufrufern."""
    return _receipt_key_for_block(None)


def _receipt_digest(canonical: str, block_id=None) -> str:
    key = _receipt_key_for_block(block_id)
    payload = canonical.encode("utf-8")
    if key:
        import hmac as _hmac
        return RECEIPT_HMAC_PREFIX + _hmac.new(key, _HMAC_DOMAIN + payload, hashlib.sha256).hexdigest()
    # Rueckwaerts-Kompatibilitaet (Tests ohne ENV): alter SHA-256-Modus wird
    # in verify_chain_integrity explizit als 'unprotected' gemeldet.
    return hashlib.sha256(payload).hexdigest()
try:
    from backend.db_paths import resolve_db
    DB_PATH = resolve_db("agentic_memory.db")
except Exception:
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


def _init_db(db_path: str = None) -> None:
    target = db_path or DB_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with sqlite3.connect(target, timeout=15.0, factory=_ArchonClosingConn) as conn:
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
        # Append-only: UPDATE/DELETE an Quittungen muss fehlschlagen.
        try:
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS execution_receipts_no_update
                BEFORE UPDATE ON execution_receipts_ledger
                BEGIN SELECT RAISE(ABORT, 'execution receipts are append-only'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS execution_receipts_no_delete
                BEFORE DELETE ON execution_receipts_ledger
                BEGIN SELECT RAISE(ABORT, 'execution receipts are append-only'); END
            """)
        except Exception:
            pass
        conn.commit()


class ExecutionReceiptLedger:
    def __init__(self, db_path: str = None):
        self._lock = _LEDGER_LOCK
        self.db_path = db_path or DB_PATH
        _init_db(self.db_path)

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
            # I (Audit): Die Modul-Config allein darf die Quittungskette nicht
            # deaktivieren — sonst entsteht eine signierte Audit-Luecke.
            # Fail-closed, nur mit explizitem Opt-out.
            if os.environ.get("ARCHON_ALLOW_RECEIPT_BYPASS", "").strip().lower() == "true":
                return {"issued": False, "bypassed": True}

        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
        # GoBD: eindeutige UTC-Zeitreferenz mit Offset.
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        tools_json = json.dumps(tools_invoked or [], ensure_ascii=False)
        rounded_cost = round(float(cost_usd), 6)

        with getattr(self, "_lock", _LEDGER_LOCK):
            with sqlite3.connect(self.db_path, timeout=15.0, factory=_ArchonClosingConn) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT receipt_hash FROM execution_receipts_ledger ORDER BY id DESC LIMIT 1"
                ).fetchone()
                # Immer kryptografisch verketten, damit verify_chain_integrity nie an Config-Wechseln bricht
                prev_hash = row[0] if row else "GENESIS_BLOCK_00000000"
                # C (Audit): Block-ID an den Schreibpfad geben, damit bei einer
                # Key-Rotation derselbe Epochen-Key wie in
                # verify_chain_integrity() (r["id"]) verwendet wird.
                next_id = int(conn.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM execution_receipts_ledger"
                ).fetchone()[0])

                canonical_str = (
                    f"{receipt_id}|{task_id}|{agent_role}|{model_used}|"
                    f"{prompt_tokens}|{completion_tokens}|{rounded_cost:.6f}|{tools_json}|{prev_hash}|{now_iso}"
                )
                receipt_hash = _receipt_digest(canonical_str, next_id)

                conn.execute("""
                    INSERT INTO execution_receipts_ledger
                    (id, receipt_id, task_id, agent_role, model_used, prompt_tokens, completion_tokens,
                     cost_usd, tools_invoked_json, prev_hash, receipt_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    next_id, receipt_id, task_id, agent_role, model_used,
                    prompt_tokens, completion_tokens, rounded_cost,
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
            "cost_usd": rounded_cost,
            "prev_hash": prev_hash,
            "receipt_hash": receipt_hash,
            "created_at": now_iso
        }

    def verify_chain_integrity(self) -> Dict[str, Any]:
        # C3: immer die Instanz-DB pruefen, nicht die globale Standard-DB.
        with sqlite3.connect(self.db_path, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM execution_receipts_ledger ORDER BY id ASC").fetchall()

        expected_prev = "GENESIS_BLOCK_00000000"
        broken_links = []
        tampered_hashes = []
        for idx, r in enumerate(rows):
            rid = r["receipt_id"]
            if r["prev_hash"] != expected_prev:
                broken_links.append(rid)
            canonical_str = (
                f"{rid}|{r['task_id']}|{r['agent_role']}|{r['model_used']}|"
                f"{int(r['prompt_tokens'])}|{int(r['completion_tokens'])}|{float(r['cost_usd']):.6f}|"
                f"{r['tools_invoked_json']}|{r['prev_hash']}|{r['created_at']}"
            )
            stored = str(r["receipt_hash"] or "")
            if stored.startswith(RECEIPT_HMAC_PREFIX):
                # C (Audit): mit dem Key der Epoche des Blocks pruefen, nicht
                # mit dem aktuellen — sonst loest Rotation einen Fehlalarm aus.
                recomputed = _receipt_digest(canonical_str, r["id"])
            elif _receipt_key():
                # Audit 23.11.2026: bei aktivem eigenen HMAC-Key darf keine
                # Quittung ohne HMAC-Praefix akzeptiert werden (Downgrade).
                tampered_hashes.append(rid)
                expected_prev = stored
                continue
            else:
                # Legacy-Quittungen (vor HMAC-Einfuehrung) weiterhin pruefbar
                recomputed = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
            if stored != recomputed:
                tampered_hashes.append(rid)
            expected_prev = r["receipt_hash"]

        return {
            "chain_valid": len(broken_links) == 0 and len(tampered_hashes) == 0,
            "hmac_protected": bool(_receipt_key()),
            "total_receipts": len(rows),
            "broken_links": broken_links,
            "tampered_hashes": tampered_hashes,
            "latest_hash": expected_prev if rows else None
        }


execution_receipt_ledger = ExecutionReceiptLedger()
