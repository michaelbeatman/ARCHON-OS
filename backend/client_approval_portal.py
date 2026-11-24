# -*- coding: utf-8 -*-
"""
backend/client_approval_portal.py
=================================
Meilenstein 42: Geteilte Kunden- & Mandanten-Links (Mini-Freigabe-Portal).

Erstellt passwortgeschuetzte, zeitlich begrenzte Freigabe-Links in SQLite WAL
(data/client_portal.db) fuer digitale Angebotsannahme mit ERP-Statuswechsel.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
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
                ai_disclosure_sig TEXT DEFAULT '',
                -- D04/MED: Einmal-Nonce/Session-Bindung des Tokens + Einmal-Verbrauch.
                ai_disclosure_nonce TEXT DEFAULT '',
                ai_disclosure_session TEXT DEFAULT '',
                ai_disclosure_consumed INTEGER DEFAULT 0
            )
        """)
        try:
            conn.execute("ALTER TABLE client_share_links ADD COLUMN ai_disclosure_sig TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        for _col, _ddl in (
            ("ai_disclosure_nonce", "TEXT DEFAULT ''"),
            ("ai_disclosure_session", "TEXT DEFAULT ''"),
            ("ai_disclosure_consumed", "INTEGER DEFAULT 0"),
        ):
            try:
                conn.execute(f"ALTER TABLE client_share_links ADD COLUMN {_col} {_ddl}")
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


def _disclosure_signature(token: str, key: bytes, nonce: str = "", session: str = "") -> str:
    """D04/MED: ``HMAC(key, token|nonce|session|ai_disclosure_v1)``.

    Ein statisches, pro Link bereits bei der Erzeugung an den Ersteller
    zurueckgegebenes Token liess sich einfach kopieren und als „Bestaetigung"
    ausgeben. Mit Nonce/Session ist das Token nur im Kontext der konkreten
    Client-Bestaetigung gueltig. Links ohne Nonce behalten aus Kompatibilitaet
    das alte Format (bestehende DB-Zeilen werden nicht ungueltig).
    """
    if nonce or session:
        msg = f"{token}|{nonce}|{session}|ai_disclosure_v1"
    else:
        msg = f"{token}|ai_disclosure_v1"
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def create_share_link(
    offer_id: str,
    title: str,
    password: str = "",
    ttl_hours: int = 72,
    db_path: Optional[str] = None,
    disclosure_session: str = "",
) -> Dict[str, Any]:
    token = f"cli-{secrets.token_urlsafe(12)}"
    salt = secrets.token_hex(8) if password else ""
    pw_hash = _hash_pw(password, salt) if password else ""
    # D04/MED: Token an Einmal-Nonce + Session binden. Die Session kann vom
    # verifizierten Client-Kontext stammen (A8 UI); ohne Session bleibt die
    # serverseitig erzeugte Nonce die Bindung.
    nonce = secrets.token_urlsafe(18)
    session = str(disclosure_session or "").strip()
    sig = _disclosure_signature(token, _disclosure_key(db_path), nonce, session)
    now = time.time()
    expires = now + max(1, int(ttl_hours)) * 3600
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO client_share_links
            (token, offer_id, title, pw_salt, pw_hash, expires_at, created_at,
             ai_disclosure_sig, ai_disclosure_nonce, ai_disclosure_session, ai_disclosure_consumed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (token, offer_id, title, salt, pw_hash, expires, now, sig, nonce, session),
        )
        conn.commit()
    return {
        "token": token, "offer_id": offer_id, "expires_at": expires,
        "password_protected": bool(password),
        "ai_disclosure_token": sig,  # vom signierten UI-Dialog zu uebermitteln
        "ai_disclosure_nonce": nonce,
        "ai_disclosure_session": session,
    }


def verify_share_access(
    token: str,
    password: str = "",
    now_ts: Optional[float] = None,
    db_path: Optional[str] = None,
    *,
    issue_disclosure_challenge: bool = False,
    disclosure_session: str = "",
) -> Dict[str, Any]:
    """Prueft den Link und liefert die Art.-50-Challenge fuer den UI-Dialog.

    ``issue_disclosure_challenge=True`` dreht die Nonce und gibt einen neuen,
    an Nonce+Session gebundenen Token aus (Einmal-Verbrauch). Der UI-Konsument
    (A8/frontend) muss diesen Wert nach expliziter Bestaetigung zuruecksenden.
    """
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
        nonce = str(row["ai_disclosure_nonce"] or "")
        session = str(row["ai_disclosure_session"] or "")
        sig = str(row["ai_disclosure_sig"] or "")
        if issue_disclosure_challenge:
            nonce = secrets.token_urlsafe(18)
            session = str(disclosure_session or session).strip()
            sig = _disclosure_signature(token, _disclosure_key(db_path), nonce, session)
            conn.execute(
                "UPDATE client_share_links SET ai_disclosure_nonce = ?, ai_disclosure_session = ?, "
                "ai_disclosure_sig = ?, ai_disclosure_consumed = 0 WHERE token = ?",
                (nonce, session, sig, token),
            )
            conn.commit()
    return {
        "allowed": True,
        "offer_id": row["offer_id"],
        "title": row["title"],
        "decision": row["decision"],
        "erp_status": row["erp_status"],
        "ai_disclosure_token": sig,
        "ai_disclosure_nonce": nonce,
        "ai_disclosure_session": session,
    }


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
    ai_disclosure_nonce: str = "",
    ai_disclosure_session: str = "",
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
    # Die Legacy-Break-Glass-Env (ARCHON_CLIENT_PORTAL_LEGACY_DISCLOSURE) wurde
    # entfernt: ein booleanes Flag durfte nie die Signaturpruefung ersetzen.
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT ai_disclosure_sig, ai_disclosure_nonce, ai_disclosure_session, "
            "ai_disclosure_consumed FROM client_share_links WHERE token = ?",
            (token,),
        ).fetchone()
    stored_sig = str(row["ai_disclosure_sig"] or "") if row else ""
    stored_nonce = str(row["ai_disclosure_nonce"] or "") if row else ""
    stored_session = str(row["ai_disclosure_session"] or "") if row else ""
    consumed = bool(row["ai_disclosure_consumed"]) if row else True
    key = _disclosure_key(db_path)
    # Nur wenn der Aufrufer Nonce/Session mitliefert (neuer UI-Flow) greift die
    # strenge Kette. Bestehende Aufrufer ohne diese Parameter behalten das
    # kompatible Format; der Produktiv-Endpoint (v2_capabilities) verlangt
    # unabhaengig davon ai_disclosure_shown=True.
    nonce_bound = bool(ai_disclosure_nonce or ai_disclosure_session)
    if nonce_bound:
        # D04/MED: neue, nonce/session-gebundene Kette. Der UI-Konsument muss
        # ai_disclosure_shown explizit setzen UND die vom Server nach dem
        # Oeffnen des Links ausgestellte Nonce/Session zuruecksenden.
        proof_kind = "nonce_session_bound"
        if (
            not ai_disclosure_shown
            or not stored_nonce
            or not hmac.compare_digest(str(ai_disclosure_nonce or ""), stored_nonce)
            or str(ai_disclosure_session or "").strip() != stored_session
            or consumed
        ):
            return {
                "allowed": False,
                "reason": (
                    "EU AI Act Art. 50: KI-Transparenzhinweis muss im Client-Dialog "
                    "explizit bestaetigt und der an Nonce/Session gebundene Token "
                    "zurueckgegeben werden (Einmal-Verbrauch)."
                ),
            }
        expected_sig = _disclosure_signature(token, key, stored_nonce, stored_session)
    else:
        # Kompatibilitaetspfad: Signatur mit den gespeicherten Werten pruefen
        # (alte Links ohne Nonce fallen auf das Legacy-Format zurueck).
        proof_kind = "verified_signature"
        expected_sig = _disclosure_signature(token, key, stored_nonce, stored_session)
    disclosed = bool(
        ai_disclosure_token
        and stored_sig
        and hmac.compare_digest(str(ai_disclosure_token), stored_sig)
        and hmac.compare_digest(stored_sig, expected_sig)
        and not consumed
    )
    if not disclosed:
        return {
            "allowed": False,
            "reason": (
                "EU AI Act Art. 50: KI-Transparenzhinweis muss per signierter "
                "UI-Bestaetigung (ai_disclosure_token) nachgewiesen werden."
            ),
        }
    erp_status = "Auftrag" if dec == "accepted" else ("Aenderung_gewuenscht" if dec == "changes_requested" else "Abgelehnt")
    audit_comment = (
        f"{comment} [ip={client_ip}; sha256={document_sha256}; ai_disclosure={proof_kind}; "
        f"nonce_bound={nonce_bound}; session={stored_session[:32]}]"
    ).strip()
    with _connect(db_path) as conn:
        # Einmal-Verbrauch atomar: nur die erste Bestaetigung zaehlt (CAS).
        cur = conn.execute(
            "UPDATE client_share_links SET decision = ?, erp_status = ?, client_comment = ?, "
            "decided_at = ?, ai_disclosure_consumed = 1 "
            "WHERE token = ? AND ai_disclosure_consumed = 0",
            (dec, erp_status, audit_comment, time.time(), token),
        )
        if cur.rowcount != 1:
            return {
                "allowed": False,
                "reason": "EU AI Act Art. 50: Bestaetigung bereits verbraucht (Einmal-Token).",
            }
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
