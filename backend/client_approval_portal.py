# -*- coding: utf-8 -*-
"""
backend/client_approval_portal.py
=================================
Meilenstein 42: Geteilte Kunden- & Mandanten-Links (Mini-Freigabe-Portal).

Erstellt passwortgeschuetzte, zeitlich begrenzte Freigabe-Links in SQLite WAL
(data/client_portal.db) fuer digitale Angebotsannahme mit ERP-Statuswechsel.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Iterator, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "client_portal.db")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_share_links (
                token TEXT PRIMARY KEY,
                offer_id TEXT NOT NULL,
                title TEXT NOT NULL,
                pw_salt TEXT DEFAULT '',
                pw_hash TEXT DEFAULT '',
                expires_at REAL NOT NULL,
                decision TEXT DEFAULT 'pending',
                erp_status TEXT DEFAULT 'Angebot',
                client_comment TEXT DEFAULT '',
                created_at REAL NOT NULL,
                decided_at REAL,
                -- Audit D04/MED: signierte Art.-50-Bestaetigung, nichtclientseitiges Boolean.
                ai_disclosure_sig TEXT DEFAULT ''
            )
        """)
        try:
            conn.execute("ALTER TABLE client_share_links ADD COLUMN ai_disclosure_sig TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def _hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()


def _disclosure_key(db_path: Optional[str] = None) -> bytes:
    """HMAC-Key fuer Art.-50-Bestaetigungen (Runtime-DB, nie im Git)."""
    env_key = os.environ.get("ARCHON_CLIENT_PORTAL_DISCLOSURE_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM portal_meta WHERE key = 'ai_disclosure_hmac'").fetchone()
        if row:
            return bytes.fromhex(row["value"])
        key = secrets.token_bytes(32)
        conn.execute(
            "INSERT OR REPLACE INTO portal_meta (key, value) VALUES ('ai_disclosure_hmac', ?)",
            (key.hex(),),
        )
        conn.commit()
        return key


def _disclosure_signature(token: str, key: bytes) -> str:
    return hmac.new(key, f"{token}|ai_disclosure_v1".encode("utf-8"), hashlib.sha256).hexdigest()


def create_share_link(
    offer_id: str,
    title: str,
    password: str = "",
    ttl_hours: int = 72,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    token = f"cli-{secrets.token_urlsafe(12)}"
    salt = secrets.token_hex(8) if password else ""
    pw_hash = _hash_pw(password, salt) if password else ""
    sig = _disclosure_signature(token, _disclosure_key(db_path))
    now = time.time()
    expires = now + max(1, int(ttl_hours)) * 3600
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO client_share_links (token, offer_id, title, pw_salt, pw_hash, expires_at, created_at, ai_disclosure_sig)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (token, offer_id, title, salt, pw_hash, expires, now, sig),
        )
        conn.commit()
    return {
        "token": token, "offer_id": offer_id, "expires_at": expires,
        "password_protected": bool(password),
        "ai_disclosure_token": sig,  # vom signierten UI-Dialog zu uebermitteln
    }


def verify_share_access(
    token: str,
    password: str = "",
    now_ts: Optional[float] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    now = now_ts if now_ts is not None else time.time()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM client_share_links WHERE token = ?", (token,)).fetchone()
    if not row:
        return {"allowed": False, "reason": "Link ungueltig."}
    if float(row["expires_at"]) <= now:
        return {"allowed": False, "reason": "Link abgelaufen."}
    if row["pw_hash"]:
        expected = _hash_pw(password or "", row["pw_salt"])
        if not hmac.compare_digest(expected, row["pw_hash"]):
            return {"allowed": False, "reason": "Falsches Passwort."}
    return {"allowed": True, "offer_id": row["offer_id"], "title": row["title"], "decision": row["decision"], "erp_status": row["erp_status"]}


def submit_client_decision(
    token: str,
    decision: str,
    comment: str = "",
    password: str = "",
    terms_accepted: bool = False,
    ai_disclosure_shown: bool = False,
    ai_disclosure_token: str = "",
    client_ip: str = "",
    document_sha256: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    access = verify_share_access(token, password=password, db_path=db_path)
    if not access["allowed"]:
        return access
    dec = (decision or "").strip().lower()
    if dec not in ("accepted", "changes_requested", "declined"):
        raise ValueError(f"Ungueltige Entscheidung: {decision}")
    if dec == "accepted" and not terms_accepted:
        return {"allowed": False, "reason": "Annahme erfordert explizite AGB-/Vertragsbestaetigung (terms_accepted=True)."}
    # Audit D04/MED: Default False + Ableitung aus signierter UI-Bestaetigung.
    # Ein freies Funktionsargument `ai_disclosure_shown=True` allein genuegt nicht.
    with _connect(db_path) as conn:
        sig_row = conn.execute(
            "SELECT ai_disclosure_sig FROM client_share_links WHERE token = ?", (token,)
        ).fetchone()
    stored_sig = str(sig_row["ai_disclosure_sig"] or "") if sig_row else ""
    expected_sig = _disclosure_signature(token, _disclosure_key(db_path))
    disclosed = bool(
        ai_disclosure_token
        and stored_sig
        and hmac.compare_digest(str(ai_disclosure_token), stored_sig)
        and hmac.compare_digest(stored_sig, expected_sig)
    )
    if not disclosed:
        legacy = os.environ.get("ARCHON_CLIENT_PORTAL_LEGACY_DISCLOSURE", "").strip().lower() in ("1", "true", "yes")
        if not (legacy and ai_disclosure_shown):
            return {"allowed": False, "reason": "EU AI Act Art. 50: KI-Transparenzhinweis muss per signierter UI-Bestaetigung (ai_disclosure_token) nachgewiesen werden."}
        disclosed = True
    erp_status = "Auftrag" if dec == "accepted" else ("Aenderung_gewuenscht" if dec == "changes_requested" else "Abgelehnt")
    proof_kind = "verified_signature" if hmac.compare_digest(str(ai_disclosure_token), stored_sig) else "legacy_break_glass"
    audit_comment = f"{comment} [ip={client_ip}; sha256={document_sha256}; ai_disclosure={proof_kind}]".strip()
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE client_share_links SET decision = ?, erp_status = ?, client_comment = ?, decided_at = ? WHERE token = ?",
            (dec, erp_status, audit_comment, time.time(), token),
        )
        conn.commit()
    return {
        "allowed": True,
        "token": token,
        "offer_id": access["offer_id"],
        "decision": dec,
        "erp_status": erp_status,
        "ai_disclosure_shown": disclosed,
        "ai_disclosure_proof": proof_kind,
        "document_sha256": document_sha256,
    }
