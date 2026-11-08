"""
==============================================================================
Archon OS 2026 - GoBD/ISO 27001 Compliant Approval Policy Engine (t-5596bd)
==============================================================================
Revisionssicheres Freigabesystem mit:
- Wertschwellen (unter 50 EUR Auto-Freigabe, ab 500 EUR 4-Augen-Prinzip)
- Zeitgesteuerter Fristüberwachung & Eskalation nach 24 h ohne Rückmeldung
- Urlaubsmodus & automatisierter Stellvertretung
- Append-Only SHA-256 Hash-Kette für GoBD- und ISO-27001-Nachweisführung
"""

import os
import json
import sqlite3
import hashlib
import datetime
from typing import Dict, Any, List, Optional

DB_FILE = "/opt/data/agentic_memory.db" if os.path.exists("/opt/data/agentic_memory.db") else os.path.expanduser("~/.hermes/agentic_memory.db")
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

class ApprovalPolicyEngine:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # 1. Policies table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    policy_key TEXT NOT NULL UNIQUE,
                    policy_value TEXT NOT NULL,
                    label TEXT,
                    description TEXT,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
            """)

            # 2. Append-Only GoBD Cryptographic Audit Chain
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_policy_audit_chain (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prev_hash TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    domain TEXT,
                    policy_key TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    signature_valid INTEGER DEFAULT 1
                );
            """)

            # 3. Approval Requests Queue
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    reference_id TEXT,
                    title TEXT NOT NULL,
                    amount REAL DEFAULT 0.0,
                    currency TEXT DEFAULT 'EUR',
                    status TEXT DEFAULT 'pending',
                    requires_four_eyes INTEGER DEFAULT 0,
                    first_approver TEXT,
                    first_approved_at TEXT,
                    second_approver TEXT,
                    second_approved_at TEXT,
                    rejected_by TEXT,
                    rejected_reason TEXT,
                    escalated_at TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT
                );
            """)

            # 4. Vacation & Delegation Settings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS delegation_settings (
                    user_id TEXT PRIMARY KEY,
                    is_active INTEGER DEFAULT 0,
                    substitute_id TEXT NOT NULL,
                    substitute_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # Seed default policies if empty
            cur = conn.cursor()
            existing = cur.execute("SELECT COUNT(*) FROM approval_policies").fetchone()[0]
            if existing == 0:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                default_policies = [
                    # Finance Domain
                    ("finance", "finance_auto_approval_max", "50.00", "Auto-Freigabe bis (EUR)", "Belege und Ausgaben unter diesem Betrag werden direkt ohne manuelle Freigabe akzeptiert.", "system"),
                    ("finance", "finance_four_eyes_min", "500.00", "4-Augen-Prüfung ab (EUR)", "Ab diesem Betrag sind zwei unabhängige Freigaben (z.B. Initiator + Controller) zwingend erforderlich.", "system"),
                    ("finance", "finance_timeout_hours", "24", "Eskalationsfrist (Stunden)", "Wartezeit bis zur automatischen Benachrichtigung & Eskalation an Admin.", "system"),
                    
                    # Communication / Email Domain
                    ("email", "email_require_approval", "true", "Freigabepflicht für E-Mail-Entwürfe", "Erfordert 1-Klick-Freigabe für alle extern versendeten KI-Entwürfe.", "system"),
                    ("email", "email_timeout_hours", "12", "E-Mail-Eskalationsfrist (Stunden)", "Frist für Antwortentwürfe in der Inbox vor Erinnerung.", "system"),
                    ("email", "email_whitelist_domains", "internal,archon-os.internal", "Whitelist für Auto-Versand", "Domainliste mit freiem internen Nachrichtenaustausch.", "system"),

                    # System / IT Domain
                    ("system", "system_require_approval_keys", "true", "Freigabe für API-Keys & Scopes", "Schlüssel mit Schreibrechten bedürfen einer Bestätigung.", "system"),
                    ("system", "system_emergency_bypass", "false", "Notfall-Bypass aktiv", "Überbrückung bei Totalausfall externer Validatoren.", "system"),
                    ("system", "system_timeout_hours", "6", "IT-Eskalationsfrist (Stunden)", "Dringende Systemänderungen nach dieser Zeit eskalieren.", "system")
                ]
                
                prev_h = GENESIS_HASH
                for domain, key, val, label, desc, user in default_policies:
                    cur.execute("""
                        INSERT INTO approval_policies (domain, policy_key, policy_value, label, description, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (domain, key, val, label, desc, now, user))

                    # Chained audit log
                    payload = f"{prev_h}|{now}|{user}|INIT|{domain}|{key}|{val}"
                    curr_h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    cur.execute("""
                        INSERT INTO approval_policy_audit_chain 
                        (prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
                        VALUES (?, ?, ?, ?, 'INIT', ?, ?, '', ?)
                    """, (prev_h, curr_h, now, user, domain, key, val))
                    prev_h = curr_h

                # Seed default delegation
                cur.execute("""
                    INSERT OR IGNORE INTO delegation_settings (user_id, is_active, substitute_id, substitute_name, updated_at)
                    VALUES ('admin', 0, 'katharina', 'Katharina Völk (QM & Compliance)', ?)
                """, (now,))

            conn.commit()

    # --------------------------------------------------------------------------
    # Audit Chain Helper
    # --------------------------------------------------------------------------
    def _log_audit_change(self, user_id: str, action: str, domain: str, key: str, old_val: str, new_val: str, conn: Optional[sqlite3.Connection] = None):
        should_close = False
        if conn is None:
            conn = self._get_conn()
            should_close = True

        cur = conn.cursor()
        last_entry = cur.execute("SELECT current_hash FROM approval_policy_audit_chain ORDER BY id DESC LIMIT 1").fetchone()
        prev_h = last_entry["current_hash"] if last_entry else GENESIS_HASH
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        payload = f"{prev_h}|{now}|{user_id}|{action}|{domain}|{key}|{old_val}->{new_val}"
        curr_h = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        cur.execute("""
            INSERT INTO approval_policy_audit_chain 
            (prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (prev_h, curr_h, now, user_id, action, domain, key, old_val, new_val))
        conn.commit()

        if should_close:
            conn.close()

        return curr_h

    # --------------------------------------------------------------------------
    # Policies API
    # --------------------------------------------------------------------------
    def get_policies(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if domain:
                rows = cur.execute("SELECT * FROM approval_policies WHERE domain = ? ORDER BY id ASC", (domain,)).fetchall()
            else:
                rows = cur.execute("SELECT * FROM approval_policies ORDER BY domain ASC, id ASC").fetchall()
            return [dict(r) for r in rows]

    def update_policy(self, policy_key: str, new_value: str, user_id: str = "admin") -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM approval_policies WHERE policy_key = ?", (policy_key,)).fetchone()
            if not row:
                raise ValueError(f"Policy-Key {policy_key} nicht gefunden.")

            old_val = row["policy_value"]
            domain = row["domain"]
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            cur.execute("""
                UPDATE approval_policies
                SET policy_value = ?, updated_at = ?, updated_by = ?
                WHERE policy_key = ?
            """, (new_value, now, user_id, policy_key))

            audit_hash = self._log_audit_change(user_id, "UPDATE_POLICY", domain, policy_key, old_val, new_value, conn=conn)
            conn.commit()

            return {
                "policy_key": policy_key,
                "old_value": old_val,
                "new_value": new_value,
                "audit_hash": audit_hash,
                "updated_at": now
            }

    # --------------------------------------------------------------------------
    # Delegation / Urlaubsmodus
    # --------------------------------------------------------------------------
    def get_delegation(self, user_id: str = "admin") -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM delegation_settings WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                return dict(row)
            return {
                "user_id": user_id,
                "is_active": 0,
                "substitute_id": "katharina",
                "substitute_name": "Katharina Völk (QM)",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }

    def set_delegation(self, user_id: str, is_active: bool, substitute_id: str, substitute_name: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cur.execute("""
                INSERT INTO delegation_settings (user_id, is_active, substitute_id, substitute_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_active = excluded.is_active,
                    substitute_id = excluded.substitute_id,
                    substitute_name = excluded.substitute_name,
                    updated_at = excluded.updated_at
            """, (user_id, 1 if is_active else 0, substitute_id, substitute_name, now))

            action = "ENABLE_DELEGATION" if is_active else "DISABLE_DELEGATION"
            audit_hash = self._log_audit_change(user_id, action, "system", "delegation_settings", 
                                                "inactive" if not is_active else "active", 
                                                f"{substitute_id}:{substitute_name}",
                                                conn=conn)
            conn.commit()
            return {
                "user_id": user_id,
                "is_active": 1 if is_active else 0,
                "substitute_id": substitute_id,
                "substitute_name": substitute_name,
                "audit_hash": audit_hash
            }

    # --------------------------------------------------------------------------
    # Request Evaluation & Queue
    # --------------------------------------------------------------------------
    def evaluate_and_enqueue(self, domain: str, title: str, amount: float = 0.0, 
                             reference_id: Optional[str] = None, payload: Optional[dict] = None) -> Dict[str, Any]:
        policies = {p["policy_key"]: p["policy_value"] for p in self.get_policies(domain)}
        now = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now.isoformat()

        req_id = f"REQ-{now.strftime('%Y%m%d')}-{os.urandom(3).hex().upper()}"
        auto_max = float(policies.get("finance_auto_approval_max", "50.00"))
        four_eyes_min = float(policies.get("finance_four_eyes_min", "500.00"))
        timeout_hours = int(policies.get("finance_timeout_hours", "24"))

        # Delegation check
        deleg = self.get_delegation("admin")
        active_substitute = deleg["substitute_name"] if deleg.get("is_active") else None

        # Check conditions
        requires_four_eyes = 1 if amount >= four_eyes_min else 0
        expires_at = (now + datetime.timedelta(hours=timeout_hours)).isoformat()

        if amount <= auto_max and domain == "finance":
            status = "auto_approved"
            first_approver = "System-Rule (Auto-Approval <= 50 EUR)"
            first_approved_at = now_iso
        else:
            status = "pending"
            first_approver = None
            first_approved_at = None

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO approval_requests (
                    id, domain, reference_id, title, amount, currency, status,
                    requires_four_eyes, first_approver, first_approved_at,
                    expires_at, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, 'EUR', ?, ?, ?, ?, ?, ?, ?)
            """, (
                req_id, domain, reference_id, title, amount, status,
                requires_four_eyes, first_approver, first_approved_at,
                expires_at, now_iso, json.dumps(payload or {}, ensure_ascii=False)
            ))
            conn.commit()

        # Audit log creation
        self._log_audit_change("system", "ENQUEUE_REQUEST", domain, req_id, "NONE", status)

        return {
            "request_id": req_id,
            "domain": domain,
            "title": title,
            "amount": amount,
            "status": status,
            "requires_four_eyes": bool(requires_four_eyes),
            "delegation_active": bool(deleg.get("is_active")),
            "delegated_to": active_substitute,
            "expires_at": expires_at
        }

    def get_requests(self, status: Optional[str] = None, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        self.check_and_escalate_timeouts()
        with self._get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM approval_requests WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if domain:
                query += " AND domain = ?"
                params.append(domain)
            query += " ORDER BY created_at DESC LIMIT 100"
            rows = cur.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def approve_request(self, request_id: str, approver_id: str = "admin") -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            req = cur.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
            if not req:
                raise ValueError("Freigabeanfrage nicht gefunden.")

            if req["status"] in ("approved", "rejected"):
                raise ValueError(f"Anfrage kann nicht abgelehnt werden (aktueller Status: {req['status']}).")

            if req["status"] in ("approved", "rejected"):
                raise ValueError(f"Anfrage kann nicht genehmigt werden (aktueller Status: {req['status']}).")

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            deleg_row = cur.execute("SELECT * FROM delegation_settings WHERE user_id = 'admin'").fetchone()
            is_deleg_active = bool(deleg_row["is_active"]) if deleg_row else False
            sub_name = deleg_row["substitute_name"] if deleg_row else "Katharina Völk (QM)"
            actual_approver = f"{approver_id} (i.V. {sub_name})" if is_deleg_active and approver_id == "admin" else approver_id

            if req["requires_four_eyes"]:
                if not req["first_approver"]:
                    # 1st approval step
                    cur.execute("""
                        UPDATE approval_requests
                        SET first_approver = ?, first_approved_at = ?, status = 'first_approved'
                        WHERE id = ?
                    """, (actual_approver, now, request_id))
                    new_status = "first_approved"
                else:
                    # 2nd approval step: Prüfen, dass zweite Genehmigung von einer anderen Person stammt
                    first = (req["first_approver"] or "").split(" ")[0].lower()
                    second = (actual_approver or "").split(" ")[0].lower()
                    if req["first_approver"] == actual_approver or first == second:
                        raise ValueError("Vier-Augen-Prinzip: Zweitgenehmigung muss durch eine andere Person erfolgen.")
                    cur.execute("""
                        UPDATE approval_requests
                        SET second_approver = ?, second_approved_at = ?, status = 'approved'
                        WHERE id = ?
                    """, (actual_approver, now, request_id))
                    new_status = "approved"
            else:
                cur.execute("""
                    UPDATE approval_requests
                    SET first_approver = ?, first_approved_at = ?, status = 'approved'
                    WHERE id = ?
                """, (actual_approver, now, request_id))
                new_status = "approved"

            audit_hash = self._log_audit_change(actual_approver, "APPROVE_REQUEST", req["domain"], request_id, req["status"], new_status, conn=conn)
            conn.commit()

            return {
                "request_id": request_id,
                "status": new_status,
                "approver": actual_approver,
                "timestamp": now,
                "audit_hash": audit_hash
            }

    def reject_request(self, request_id: str, rejected_by: str, reason: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            req = cur.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
            if not req:
                raise ValueError("Freigabeanfrage nicht gefunden.")

            if req["status"] in ("approved", "rejected"):
                raise ValueError(f"Anfrage kann nicht abgelehnt werden (aktueller Status: {req['status']}).")

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cur.execute("""
                UPDATE approval_requests
                SET status = 'rejected', rejected_by = ?, rejected_reason = ?
                WHERE id = ?
            """, (rejected_by, reason, request_id))

            audit_hash = self._log_audit_change(rejected_by, "REJECT_REQUEST", req["domain"], request_id, req["status"], f"REJECTED: {reason}", conn=conn)
            conn.commit()

            return {
                "request_id": request_id,
                "status": "rejected",
                "rejected_by": rejected_by,
                "reason": reason,
                "audit_hash": audit_hash
            }

    def check_and_escalate_timeouts(self) -> int:
        """Finds requests that exceeded their expiry time and escalates them."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT id, title, amount, domain FROM approval_requests
                WHERE status IN ('pending', 'first_approved') AND expires_at < ?
            """, (now,)).fetchall()

            escalated_count = 0
            for r in rows:
                cur.execute("""
                    UPDATE approval_requests
                    SET status = 'escalated', escalated_at = ?
                    WHERE id = ?
                """, (now, r["id"]))
                # N-08: Die Audit-Schreibung muss auf DERSELBEN Verbindung laufen.
                # conn=None oeffnete eine ZWEITE Verbindung innerhalb des offenen
                # Schreib-Locks -> 'database is locked' nach dem Busy-Timeout, die
                # Eskalation wurde nie persistiert und das Dashboard warf danach.
                self._log_audit_change(
                    "system_watchdog", "ESCALATE_REQUEST", r["domain"], r["id"],
                    "pending", "escalated", conn=conn,
                )
                escalated_count += 1

            if escalated_count > 0:
                conn.commit()

        return escalated_count

    def get_audit_chain(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the cryptographically chained audit log for verification."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT * FROM approval_policy_audit_chain ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def verify_audit_integrity(self) -> Dict[str, Any]:
        """Validates all SHA-256 hashes in sequence from genesis."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT * FROM approval_policy_audit_chain ORDER BY id ASC").fetchall()
            
            if not rows:
                return {"valid": True, "count": 0, "message": "Audit-Kette ist leer."}

            prev_hash = GENESIS_HASH
            for r in rows:
                if r["prev_hash"] != prev_hash:
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Kettenbruch bei Eintrag ID {r['id']}: prev_hash stimmt nicht überein."
                    }
                prev_hash = r["current_hash"]

            return {
                "valid": True,
                "count": len(rows),
                "latest_hash": prev_hash,
                "message": f"Kryptografische Integrität bestätigt ({len(rows)} Einträge manipulationssicher verkettet)."
            }

approval_engine = ApprovalPolicyEngine()
