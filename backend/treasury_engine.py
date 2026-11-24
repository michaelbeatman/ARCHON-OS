"""
backend/treasury_engine.py — M103: Treasury, Wallets, Bankkonten & Passkey-gesichertes Zahlungs-Ledger

Architektur nach Industriestandard (Stripe Agent Toolkit / Coinbase AgentKit / x402 / Cornell-Yale Guardrails):
- Strikte Trennung: Hauptkonten & Main-Wallets (`watch_only` / `passkey_hitl`) sind fuer Agenten tabu.
- Deterministischer Policy-Kernel (kein LLM): Prueft Idempotenz, Empfaenger-Allowlist, Einzel-/Tageslimit.
- Bei aktiviertem Passkey/HITL (`passkey_hitl.is_passkey_required(..., "payments")`) kann kein Agent selbst zahlen;
  jede Ausgabe erfordert zwingend menschliche Verifizierung (z. B. Handy-Passkey / WebAuthn).
- Manipulationssicheres Ausgaben-Ledger mit SHA-256 Hash-Chain in SQLite WAL (`data/treasury.db`).
"""
from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("treasury_engine")

import hashlib
import math
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREASURY_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "treasury.db")


def _resolve_treasury_db() -> str:
    try:
        from backend.db_paths import resolve_db
        return resolve_db("treasury.db")
    except Exception:
        return TREASURY_DB_PATH


def _get_conn() -> sqlite3.Connection:
    db_path = _resolve_treasury_db()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_treasury_db() -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS treasury_accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                account_type TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'EUR',
                balance REAL NOT NULL DEFAULT 0.0,
                identifier TEXT DEFAULT '',
                custody_mode TEXT NOT NULL DEFAULT 'passkey_hitl',
                per_tx_limit REAL NOT NULL DEFAULT 0.0,
                daily_limit REAL NOT NULL DEFAULT 0.0,
                allowlist_json TEXT NOT NULL DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS treasury_transactions (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                direction TEXT NOT NULL DEFAULT 'out',
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'EUR',
                category TEXT NOT NULL DEFAULT 'Sonstiges',
                recipient TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                workflow_run_id TEXT DEFAULT '',
                receipt_id TEXT DEFAULT '',
                idempotency_key TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending_approval',
                requested_by TEXT NOT NULL DEFAULT 'user',
                approved_by TEXT DEFAULT '',
                passkey_verified INTEGER NOT NULL DEFAULT 0,
                policy_note TEXT DEFAULT '',
                prev_hash TEXT NOT NULL DEFAULT '',
                entry_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                executed_at TEXT DEFAULT ''
            )
            """
        )
        # M43-Mandantentrennung (Audit v3 1.3.7): company_id nachtraeglich auf beide Tabellen
        for _tbl in ("treasury_accounts", "treasury_transactions"):
            try:
                conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN company_id TEXT NOT NULL DEFAULT 'default'")
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits

        # A (Audit): Append-only. Nur in der Schema-Init — keine Daten werden
        # veraendert. DELETE ist generell verboten; UPDATE darf ausschliesslich
        # die legitimen Freigabefelder beruehren (approve_payment/reject_payment).
        # Alle in den Hash eingehenden Spalten bleiben damit unveraenderlich.
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS treasury_tx_no_tamper
            BEFORE UPDATE OF id, account_id, direction, amount, currency,
                             recipient, category, purpose, workflow_run_id,
                             receipt_id, idempotency_key, company_id,
                             requested_by, prev_hash, entry_hash, created_at
            ON treasury_transactions
            BEGIN
                SELECT RAISE(ABORT, 'treasury_transactions hash fields are append-only');
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS treasury_tx_no_delete
            BEFORE DELETE ON treasury_transactions
            BEGIN
                SELECT RAISE(ABORT, 'treasury_transactions is append-only');
            END
        """)
        conn.commit()
    finally:
        conn.close()


def _legacy_entry_hash(prev_hash: str, row_dict: Dict[str, Any]) -> str:
    """Hash-Format bestehender Ketten (Lauf-5 K-01): nacktes SHA-256."""
    payload = json.dumps(
        {
            "prev": prev_hash,
            "id": row_dict.get("id"),
            "account_id": row_dict.get("account_id"),
            "direction": row_dict.get("direction"),
            "amount": row_dict.get("amount"),
            "currency": row_dict.get("currency"),
            "recipient": row_dict.get("recipient"),
            "created_at": row_dict.get("created_at"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _treasury_epoch_cutoff() -> int:
    """Erster Block, der mit dem aktuellen HMAC-Key signiert wurde.

    F-026: Treasury nutzt TEXT-IDs ('tx-...'), daher wird die 1-basierte Position
    in der Append-only-Kette als numerische Block-ID verwendet. Blöcke vor dem
    Cutoff werden beim Verifizieren mit dem Legacy-Key (None) geprüft.
    """
    try:
        return int(os.environ.get("ARCHON_TREASURY_HMAC_EPOCH_FROM", "0") or 0)
    except (TypeError, ValueError):
        return 0


def _compute_entry_hash(prev_hash: str, row_dict: Dict[str, Any], block_id=None) -> str:
    """Lauf-5 K-01: HMAC-SHA256 + company_id im signierten Payload.

    'status' bleibt bewusst ausgenommen: approve/reject aendert den Status per
    UPDATE und wuerde sonst jeden Hash brechen. A (Audit): Die Status-,
    Approver- und Passkey-Flags werden deshalb als signierte Events im
    zentralen, append-only Audit-Log erfasst (payment_approved /
    payment_rejected inkl. tx_id, amount, currency, recipient, approver,
    passkey_verified, status). Das erhaelt die Verifizierbarkeit bestehender
    Legacy-Ketten, deren Hashes diese Felder nicht enthalten. Zustaetzlich
    blockieren die Trigger in init_treasury_db() Aenderungen aller
    hashrelevanten Spalten sowie DELETE.
    """
    payload = json.dumps(
        {
            "prev": prev_hash,
            "id": row_dict.get("id"),
            "company_id": row_dict.get("company_id", "default"),
            "account_id": row_dict.get("account_id"),
            "direction": row_dict.get("direction"),
            "amount": row_dict.get("amount"),
            "currency": row_dict.get("currency"),
            "recipient": row_dict.get("recipient"),
            "idempotency_key": row_dict.get("idempotency_key", ""),
            "created_at": row_dict.get("created_at"),
        },
        sort_keys=True,
    )
    from backend.audit_log import _chain_hash
    # F-026: block_id an die Epochenwahl weitergeben — ohne ID würde nach einer
    # Key-Rotation der juengste Key auch fuer alte Bloecke benutzt und die Kette
    # faelschlich als manipuliert gemeldet.
    return _chain_hash(payload, block_id)


def _last_hash(conn: sqlite3.Connection) -> str:
    # id statt created_at: manipulierte Zeitstempel duerfen nicht bestimmen,
    # an welchem Block die Kette fortgesetzt wird (K-01).
    row = conn.execute(
        "SELECT entry_hash FROM treasury_transactions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return str(row["entry_hash"]) if row and row["entry_hash"] else "GENESIS"


def verify_treasury_chain(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Lauf-5 K-01: Verifikation der Finanz-Hashkette (Legacy + HMAC-Bloecke)."""
    from backend.audit_log import HMAC_PREFIX, _hmac_epochs, _verify_hash
    conn = sqlite3.connect(db_path, timeout=10.0) if db_path else _get_conn()
    if db_path:
        conn.row_factory = sqlite3.Row
    try:
        has_tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='treasury_transactions'"
        ).fetchone()
        if not has_tbl:
            return {"valid": True, "count": 0, "message": "Treasury-Kette ist leer."}
        rows = conn.execute("SELECT * FROM treasury_transactions ORDER BY id ASC").fetchall()
        if not rows:
            return {"valid": True, "count": 0, "message": "Treasury-Kette ist leer."}
        prev_hash = "GENESIS"
        hmac_blocks = 0
        hmac_positions: List[int] = []
        for idx, r in enumerate(rows):
            if str(r["prev_hash"]) != prev_hash:
                return {
                    "valid": False, "broken_at_id": r["id"],
                    "message": f"Treasury-Kettenbruch bei ID {r['id']}.",
                }
            stored = str(r["entry_hash"] or "")
            if stored.startswith(HMAC_PREFIX):
                hmac_blocks += 1
                hmac_positions.append(idx)
                payload = json.dumps(
                    {
                        "prev": r["prev_hash"],
                        "id": r["id"],
                        "company_id": r["company_id"],
                        "account_id": r["account_id"],
                        "direction": r["direction"],
                        "amount": r["amount"],
                        "currency": r["currency"],
                        "recipient": r["recipient"],
                        "idempotency_key": r["idempotency_key"],
                        "created_at": r["created_at"],
                    },
                    sort_keys=True,
                )
                # F-026: 1-basierte Kettenposition als Block-ID (identisch zum
                # Schreibpfad). Bloecke vor ARCHON_TREASURY_HMAC_EPOCH_FROM
                # falling back auf den Legacy-Key, damit Rotation die Kette
                # nicht bricht.
                bid = idx + 1
                ok = _verify_hash(payload, stored, bid)
                if not ok and bid < _treasury_epoch_cutoff():
                    ok = _verify_hash(payload, stored, None)
                if not ok:
                    return {
                        "valid": False, "broken_at_id": r["id"],
                        "message": f"Treasury-Payload-Manipulation bei ID {r['id']}.",
                    }
            elif _legacy_entry_hash(r["prev_hash"], dict(r)) != stored:
                return {
                    "valid": False, "broken_at_id": r["id"],
                    "message": f"Treasury-Legacy-Hash ungueltig bei ID {r['id']}.",
                }
            prev_hash = stored
        key_active = bool(_hmac_epochs())
        if key_active and hmac_positions:
            # B (Audit): Ein Plain-SHA-Block NACH dem ersten HMAC-Block ist ein
            # Downgrade (K-1-Angriff): der Angreifer setzt entry_hash eines
            # HMAC-Blocks auf _legacy_entry_hash() und wuerde sonst akzeptiert.
            # Treasury-IDs sind Texte, darum die Position in der Kette statt
            # einer numerischen ID (analog api_key_manager.first_hmac_id).
            first_hmac_pos = hmac_positions[0]
            if any(
                not str(r["entry_hash"] or "").startswith(HMAC_PREFIX)
                for r in rows[first_hmac_pos + 1:]
            ):
                return {
                    "valid": False, "count": len(rows), "hmac_active": True,
                    "hmac_blocks": hmac_blocks,
                    "message": (
                        "HMAC-Signatur auf nacktes SHA-256 zurueckgesetzt "
                        "(Block nach erstem HMAC-Block)."
                    ),
                }
        if hmac_blocks and not key_active:
            return {
                "valid": False, "count": len(rows), "hmac_active": False,
                "message": "HMAC-Bloecke ohne passenden ARCHON_AUDIT_HMAC_KEY.",
            }
        return {
            "valid": True, "count": len(rows), "hmac_active": key_active,
            "hmac_blocks": hmac_blocks, "latest_hash": prev_hash,
        }
    finally:
        conn.close()


def _row_to_account(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["active"] = bool(d.get("active"))
    try:
        d["allowlist"] = json.loads(d.pop("allowlist_json", "[]") or "[]")
    except Exception:
        d["allowlist"] = []
    return d


def _row_to_tx(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["passkey_verified"] = bool(d.get("passkey_verified"))
    return d


def upsert_account(payload: Dict[str, Any]) -> Dict[str, Any]:
    init_treasury_db()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("account_name_required")

    acc_type = str(payload.get("account_type") or "bank").strip().lower()
    if acc_type not in {"bank", "paypal", "stripe", "crypto_treasury", "crypto_agent_allowance"}:
        acc_type = "bank"

    custody_mode = str(payload.get("custody_mode") or "").strip().lower()
    if custody_mode not in {"watch_only", "passkey_hitl", "allowance_capped"}:
        custody_mode = "watch_only" if acc_type == "crypto_treasury" else "passkey_hitl"

    allowlist = payload.get("allowlist") or []
    if isinstance(allowlist, str):
        allowlist = [x.strip() for x in allowlist.split(",") if x.strip()]

    acc_id = str(payload.get("id") or f"acc-{uuid.uuid4().hex[:8]}").strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO treasury_accounts (
                id, name, account_type, currency, balance, identifier, custody_mode,
                per_tx_limit, daily_limit, allowlist_json, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                account_type=excluded.account_type,
                currency=excluded.currency,
                balance=excluded.balance,
                identifier=excluded.identifier,
                custody_mode=excluded.custody_mode,
                per_tx_limit=excluded.per_tx_limit,
                daily_limit=excluded.daily_limit,
                allowlist_json=excluded.allowlist_json,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            (
                acc_id,
                name,
                acc_type,
                str(payload.get("currency") or "EUR").strip().upper()[:10],
                float(payload.get("balance") or 0.0),
                str(payload.get("identifier") or "").strip(),
                custody_mode,
                float(payload.get("per_tx_limit") or 0.0),
                float(payload.get("daily_limit") or 0.0),
                json.dumps(allowlist, ensure_ascii=False),
                1 if payload.get("active", True) else 0,
                now_iso,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM treasury_accounts WHERE id = ?", (acc_id,)).fetchone()
        return _row_to_account(row)
    finally:
        conn.close()


def delete_account(acc_id: str) -> bool:
    init_treasury_db()
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM treasury_accounts WHERE id = ?", (acc_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _today_spent(conn: sqlite3.Connection, account_id: str) -> float:
    today_prefix = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0.0) FROM treasury_transactions
        WHERE account_id = ? AND direction = 'out' AND status = 'executed' AND executed_at LIKE ?
        """,
        (account_id, f"{today_prefix}%"),
    ).fetchone()
    return float(row[0] if row else 0.0)


def request_payment(payload: Dict[str, Any], actor_id: str = "admin") -> Dict[str, Any]:
    init_treasury_db()
    account_id = str(payload.get("account_id") or "").strip()
    if not account_id:
        raise ValueError("account_id_required")

    amount = float(payload.get("amount") or 0.0)
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("amount_must_be_positive")

    direction = "in" if str(payload.get("direction") or "out").lower() == "in" else "out"
    recipient = str(payload.get("recipient") or "").strip()
    purpose = str(payload.get("purpose") or "").strip()
    category = str(payload.get("category") or "Sonstiges").strip()
    requested_by = str(payload.get("requested_by") or actor_id or "user").strip()
    idem_key = str(payload.get("idempotency_key") or f"idem-{uuid.uuid4().hex[:12]}").strip()

    from backend.passkey_hitl import is_passkey_required

    # Mandantenkontext VOR der Pruefung auflösen (vorher: NameError in Z.269)
    # und niemals ein Dict stringifizieren (vorher: company_id="{"id": ...}").
    try:
        from backend.tenant_context import tenant_context as _tc
        from backend.tenant_context import sanitize_tenant_id as _sanitize

        _company = getattr(_tc, "get_active_company", lambda: None)()
        if isinstance(_company, dict):
            _company = _company.get("id") or _company.get("tenant_id") or ""
        active_company = _sanitize(str(_company or getattr(_tc, "get_active_tenant_id", lambda: "default")() or "default"))
    except Exception:
        active_company = "default"

    passkey_enforced = is_passkey_required(actor_id, category="payments")

    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")  # Audit v3 1.3.7: serialisiert gleichzeitige Buchungen (Double-Spend-Schutz)
        existing_idem = conn.execute(
            "SELECT * FROM treasury_transactions WHERE idempotency_key = ?",
            (idem_key,),
        ).fetchone()
        if existing_idem:
            return _row_to_tx(existing_idem)

        acc_row = conn.execute("SELECT * FROM treasury_accounts WHERE id = ?", (account_id,)).fetchone()
        if not acc_row:
            raise KeyError("account_not_found")
        acc_company = str(acc_row["company_id"]) if "company_id" in acc_row.keys() else "default"
        if acc_company not in ("", "default") and active_company not in ("", "default") and acc_company != active_company:
            conn.close()
            raise KeyError("account_not_in_active_company")
        acc = _row_to_account(acc_row)

        now_iso = datetime.now(timezone.utc).isoformat()
        tx_id = f"tx-{uuid.uuid4().hex[:10]}"
        policy_note = ""
        status = "pending_approval"
        executed_at = ""
        passkey_verified = 0

        if direction == "in":
            status = "executed"
            executed_at = now_iso
            policy_note = "Zahlungseingang verbucht"
            conn.execute(
                "UPDATE treasury_accounts SET balance = balance + ?, updated_at = ? WHERE id = ?",
                (amount, now_iso, account_id),
            )
        else:
            is_agent = requested_by.lower().startswith("agent") or bool(payload.get("is_agent_request"))
            if acc["custody_mode"] == "watch_only":
                status = "pending_approval"
                policy_note = "Watch-Only Treasury: Ausfuehrung nur manuell nach Freigabe"
            elif passkey_enforced or acc["custody_mode"] == "passkey_hitl" or is_agent:
                # Wenn Passkey/HITL aktiv ist, koennen Agenten NICHTS selbst ausfuehren
                if acc["custody_mode"] == "allowance_capped" and not passkey_enforced:
                    allowlist = [x.lower() for x in acc.get("allowlist") or []]
                    spent_today = _today_spent(conn, account_id)
                    in_allowlist = not allowlist or recipient.lower() in allowlist
                    within_tx = acc["per_tx_limit"] <= 0 or amount <= acc["per_tx_limit"]
                    within_day = acc["daily_limit"] <= 0 or (spent_today + amount) <= acc["daily_limit"]
                    if in_allowlist and within_tx and within_day and acc["balance"] >= amount:
                        status = "executed"
                        executed_at = now_iso
                        policy_note = "Agent-Allowance innerhalb Cap & Allowlist ausgefuehrt"
                        conn.execute(
                            "UPDATE treasury_accounts SET balance = balance - ?, updated_at = ? WHERE id = ?",
                            (amount, now_iso, account_id),
                        )
                    else:
                        status = "pending_approval"
                        policy_note = "Allowance-Cap / Allowlist ueberschritten -> HITL-Freigabe erforderlich"
                else:
                    status = "pending_approval"
                    policy_note = "Passkey-/HITL-Schutz aktiv: Agent darf nicht selbst ausfuehren (Handy-Freigabe noetig)"
            elif payload.get("execute_immediately") and acc["balance"] >= amount:
                status = "executed"
                executed_at = now_iso
                policy_note = "Direktbuchung durch Benutzer"
                conn.execute(
                    "UPDATE treasury_accounts SET balance = balance - ?, updated_at = ? WHERE id = ?",
                    (amount, now_iso, account_id),
                )

        prev_h = _last_hash(conn)
        tx_obj = {
            "id": tx_id,
            "account_id": account_id,
            "direction": direction,
            "amount": amount,
            "currency": acc["currency"],
            "category": category,
            "recipient": recipient,
            "purpose": purpose,
            "workflow_run_id": str(payload.get("workflow_run_id") or "").strip(),
            "receipt_id": str(payload.get("receipt_id") or "").strip(),
            "idempotency_key": idem_key,
            "status": status,
            "requested_by": requested_by,
            "approved_by": actor_id if status == "executed" and not payload.get("is_agent_request") else "",
            "passkey_verified": passkey_verified,
            "policy_note": policy_note,
            "prev_hash": prev_h,
            "created_at": now_iso,
            "executed_at": executed_at,
        }
        tx_obj["company_id"] = active_company
        # F-026: stabile 1-basierte Blocknummer als Schluessel-Epochen-Anker.
        _next_block_id = int(conn.execute(
            "SELECT COUNT(*) FROM treasury_transactions"
        ).fetchone()[0]) + 1
        tx_obj["entry_hash"] = _compute_entry_hash(prev_h, tx_obj, _next_block_id)

        conn.execute(
            """
            INSERT INTO treasury_transactions (
                id, account_id, direction, amount, currency, category, recipient, purpose,
                workflow_run_id, receipt_id, idempotency_key, status, requested_by, approved_by,
                passkey_verified, policy_note, prev_hash, entry_hash, created_at, executed_at, company_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx_obj["id"], tx_obj["account_id"], tx_obj["direction"], tx_obj["amount"],
                tx_obj["currency"], tx_obj["category"], tx_obj["recipient"], tx_obj["purpose"],
                tx_obj["workflow_run_id"], tx_obj["receipt_id"], tx_obj["idempotency_key"],
                tx_obj["status"], tx_obj["requested_by"], tx_obj["approved_by"],
                tx_obj["passkey_verified"], tx_obj["policy_note"], tx_obj["prev_hash"],
                tx_obj["entry_hash"], tx_obj["created_at"], tx_obj["executed_at"],
                tx_obj.get("company_id", "default"),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if tx_obj["status"] == "pending_approval":
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="approval",
                event_type="payment_requested",
                title=f"Zahlungsfreigabe: {amount:.2f} {tx_obj['currency']} an {recipient or 'Empfaenger'}",
                summary=purpose or category,
                payload={"tx_id": tx_id, "amount": amount, "currency": tx_obj["currency"]},
                correlation_id=f"payreq-{tx_id}",
            )
        except Exception as _exc:
            _archon_exc_logger.debug("[treasury_engine] Ignorierte Ausnahme (Z.355): %s", _exc)

    return {**tx_obj, "passkey_verified": bool(tx_obj["passkey_verified"])}


def approve_payment(tx_id: str, approver_id: str = "admin", passkey_verified: bool = False) -> Dict[str, Any]:
    init_treasury_db()
    from backend.passkey_hitl import is_passkey_required

    if is_passkey_required(approver_id, category="payments") and not passkey_verified:
        raise PermissionError("passkey_verification_required")

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        tx_row = conn.execute("SELECT * FROM treasury_transactions WHERE id = ?", (tx_id,)).fetchone()
        if not tx_row:
            conn.rollback()
            raise KeyError("transaction_not_found")
        tx = _row_to_tx(tx_row)
        if tx["status"] != "pending_approval":
            conn.rollback()
            return tx

        acc_row = conn.execute("SELECT * FROM treasury_accounts WHERE id = ?", (tx["account_id"],)).fetchone()
        if not acc_row:
            conn.rollback()
            raise KeyError("account_not_found")

        if tx["direction"] == "out" and float(acc_row["balance"]) < float(tx["amount"]):
            conn.rollback()
            raise ValueError("insufficient_balance")

        if tx["direction"] == "out":
            # Allowlist/Caps koennen sich seit dem Request geändert haben oder
            # durch andere Freigaben überschritten worden sein. Erneut prüfen,
            # sonst wird eine zwischenzeitlich über Limit liegende Zahlung
            # trotzdem ausgeführt.
            acc = _row_to_account(acc_row)
            if acc.get("custody_mode") == "allowance_capped":
                allowlist = [str(x).lower() for x in (acc.get("allowlist") or [])]
                amount = float(tx["amount"])
                recipient_lc = str(tx.get("recipient") or "").lower()
                spent_today = _today_spent(conn, tx["account_id"])
                if (
                    (allowlist and recipient_lc not in allowlist)
                    or (float(acc.get("per_tx_limit") or 0) > 0 and amount > float(acc["per_tx_limit"]))
                    or (float(acc.get("daily_limit") or 0) > 0 and spent_today + amount > float(acc["daily_limit"]))
                ):
                    conn.rollback()
                    raise ValueError("policy_limit_exceeded_at_approval")
            conn.execute(
                "UPDATE treasury_accounts SET balance = balance - ?, updated_at = ? WHERE id = ?",
                (tx["amount"], now_iso, tx["account_id"]),
            )
        else:
            conn.execute(
                "UPDATE treasury_accounts SET balance = balance + ?, updated_at = ? WHERE id = ?",
                (tx["amount"], now_iso, tx["account_id"]),
            )

        cur = conn.execute(
            """
            UPDATE treasury_transactions
            SET status = 'executed', approved_by = ?, passkey_verified = ?, executed_at = ?, policy_note = ?
            WHERE id = ? AND status = 'pending_approval'
            """,
            (
                approver_id,
                1 if passkey_verified else 0,
                now_iso,
                "Freigegeben per Passkey (Handy/FIDO2)" if passkey_verified else "Freigegeben (HITL)",
                tx_id,
            ),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return _row_to_tx(conn.execute("SELECT * FROM treasury_transactions WHERE id = ?", (tx_id,)).fetchone())
        conn.commit()
        updated = _row_to_tx(conn.execute("SELECT * FROM treasury_transactions WHERE id = ?", (tx_id,)).fetchone())
    finally:
        conn.close()

    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="treasury",
            action="payment_approved",
            agent_id=approver_id,
            payload={
                "tx_id": tx_id,
                "amount": updated["amount"],
                "currency": updated["currency"],
                "recipient": updated.get("recipient", ""),
                "status": updated["status"],
                "approved_by": approver_id,
                "passkey_verified": passkey_verified,
                "entry_hash": updated.get("entry_hash", ""),
            },
        )
    except Exception as _exc:
        _archon_exc_logger.debug("[treasury_engine] Audit-Log fuer payment_approved fehlgeschlagen: %s", _exc)

    try:
        from backend.workflow_scheduler import dispatch_workflow_event
        dispatch_workflow_event(
            source="approval",
            event_type="payment_approved",
            title=f"Zahlung freigegeben: {updated['amount']:.2f} {updated['currency']} ({updated['recipient']})",
            summary=updated.get("purpose", ""),
            payload={"tx_id": tx_id, "approver": approver_id, "passkey_verified": passkey_verified},
            correlation_id=f"payapr-{tx_id}",
        )
    except Exception as _exc:
        _archon_exc_logger.debug("[treasury_engine] Ignorierte Ausnahme (Z.422): %s", _exc)
    return updated


def reject_payment(tx_id: str, rejected_by: str = "admin", reason: str = "") -> Dict[str, Any]:
    init_treasury_db()
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM treasury_transactions WHERE id = ?", (tx_id,)).fetchone()
        if not row:
            conn.rollback()
            raise KeyError("transaction_not_found")
        if str(row["status"]) != "pending_approval":
            conn.rollback()
            raise ValueError(f"Zahlung '{tx_id}' ist bereits '{row['status']}' und kann nicht abgelehnt werden.")
        conn.execute(
            "UPDATE treasury_transactions SET status = 'rejected', approved_by = ?, policy_note = ? WHERE id = ? AND status = 'pending_approval'",
            (rejected_by, reason or "Abgelehnt durch Benutzer", tx_id),
        )
        conn.commit()
        updated = _row_to_tx(conn.execute("SELECT * FROM treasury_transactions WHERE id = ?", (tx_id,)).fetchone())
    finally:
        conn.close()

    # A (Audit): Statuswechsel signiert im zentralen append-only Log erfassen
    # (analog approve_payment), damit reject/approve nicht unbemerkt bleibt.
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="treasury",
            action="payment_rejected",
            agent_id=rejected_by,
            payload={
                "tx_id": tx_id,
                "amount": updated["amount"],
                "currency": updated["currency"],
                "recipient": updated.get("recipient", ""),
                "status": updated["status"],
                "approved_by": rejected_by,
                "passkey_verified": bool(updated.get("passkey_verified")),
                "entry_hash": updated.get("entry_hash", ""),
            },
        )
    except Exception as _exc:
        _archon_exc_logger.debug("[treasury_engine] Audit-Log fuer payment_rejected fehlgeschlagen: %s", _exc)
    return updated


def get_treasury_overview(user_id: str = "admin") -> Dict[str, Any]:
    init_treasury_db()
    from backend.passkey_hitl import is_passkey_required

    conn = _get_conn()
    try:
        accounts = [_row_to_account(r) for r in conn.execute("SELECT * FROM treasury_accounts ORDER BY updated_at DESC").fetchall()]
        txs = [_row_to_tx(r) for r in conn.execute("SELECT * FROM treasury_transactions ORDER BY created_at DESC LIMIT 150").fetchall()]

        liquidity_by_currency: Dict[str, float] = {}
        liquidity_by_type: Dict[str, float] = {}
        for a in accounts:
            if not a["active"]:
                continue
            cur = a["currency"]
            liquidity_by_currency[cur] = round(liquidity_by_currency.get(cur, 0.0) + float(a["balance"]), 2)
            t = a["account_type"]
            liquidity_by_type[t] = round(liquidity_by_type.get(t, 0.0) + float(a["balance"]), 2)

        spend_by_category: Dict[str, float] = {}
        total_spent = 0.0
        for tx in txs:
            if tx["direction"] == "out" and tx["status"] == "executed":
                cat = tx["category"] or "Sonstiges"
                spend_by_category[cat] = round(spend_by_category.get(cat, 0.0) + float(tx["amount"]), 2)
                total_spent = round(total_spent + float(tx["amount"]), 2)

        pending_approvals = [tx for tx in txs if tx["status"] == "pending_approval"]

        return {
            "accounts": accounts,
            "transactions": txs,
            "pending_approvals": pending_approvals,
            "liquidity_by_currency": liquidity_by_currency,
            "liquidity_by_type": liquidity_by_type,
            "spend_by_category": spend_by_category,
            "total_spent": total_spent,
            "passkey_payments_required": is_passkey_required(user_id, category="payments"),
        }
    finally:
        conn.close()
