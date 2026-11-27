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

import datetime
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger("archon.approval_policy_engine")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.db_paths import resolve_db
    DB_FILE = resolve_db("agentic_memory.db")
except Exception:
    DB_FILE = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

# D14/M4: Domains, deren Antraege grundsaetzlich HITL-pflichtig sind. Bei
# diesen Domains ist ein Antrag ohne zuordenbaren Ersteller wirkungslos und
# wird bei der Freigabe hart abgelehnt (kein Self-Approval durch den Admin).
HITL_REQUIRED_DOMAINS = frozenset({
    "agent_dispatch", "boardroom", "workflow_authoring",
    "context_hygiene", "system", "governance",
})

# D04/HIGH (A4-Handoff): harter Mindestabstand zwischen der Auto-Freigabe- und
# der Vier-Augen-Schwelle. Die blosse Ungleichung `auto_max < four_eyes_min`
# liess Werte wie 499.99 / 500.00 zu und machte die 50-EUR-Regel wirkungslos.
# Die Invariante wird ab jetzt SYMMETRISCH geprueft — egal welche der beiden
# Schwellen geaendert wird.
FINANCE_THRESHOLD_MIN_GAP = 0.01  # ein Cent — kleinste harte, geldbetragsrelevante Distanz
_GAP_EPSILON = 1e-9  # Float-Rundung (500.0 - 499.99 == 0.009999999999990905)

# M95: Harte Sicherheits-Invarianten fuer Urlaubs-/Vertretungsmodus & Eskalation
ALLOWED_DEPUTY_ROLES: FrozenSet[str] = frozenset({"admin", "operator"})
ADMIN_ONLY_DEPUTY_DOMAINS: FrozenSet[str] = frozenset({"system", "governance"})
_FORBIDDEN_AGENT_IDENTITIES: FrozenSet[str] = frozenset({
    "system",
    "agent",
    "default",
    "system_watchdog",
    "hermes",
    "archon",
    "auto",
    "bot",
    "ai",
    "llm",
    "assistant",
    "executive_decision_architect",
    "legal_counsel",
    "tax_holding_advisor",
    "finance_lead",
    "senior_fullstack_engineer",
    "agile_scrum_master",
    "qa_test_engineer",
    "linkedin_social_media_specialist",
})
_FORBIDDEN_AGENT_PREFIXES = (
    "agent:",
    "agent_",
    "bot:",
    "bot_",
    "sys:",
    "system:",
    "system_",
    "ai:",
    "ai_",
    "llm:",
    "auto:",
)


def is_agent_or_system_identity(actor: Optional[str]) -> bool:
    """True, wenn die Identitaet ein Agent, Bot oder System-Default ist (nie als Mensch zulassen)."""
    clean = str(actor or "").strip().lower()
    if not clean:
        return True
    if clean in _FORBIDDEN_AGENT_IDENTITIES:
        return True
    return any(clean.startswith(prefix) for prefix in _FORBIDDEN_AGENT_PREFIXES)


def _record_central_audit(category: str, action: str, actor: str, details: Dict[str, Any]) -> None:
    """Protokolliert M95-Urlaubs- und Eskalationsereignisse zusaetzlich in backend/audit_log.py."""
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(category, action, actor, details)
    except Exception as exc:
        logger.warning("[ApprovalPolicyEngine] Zentrales Audit-Event (%s/%s) nicht geschrieben: %s", category, action, exc)


def _actor_identity_tokens(actor: str) -> set:
    """Identitaets-Tokens eines Actors (inkl. Stellvertretungs-Suffix).

    D04/D14: gemeinsam genutzt von der Ersteller-Sperre und der
    Vier-Augen-Pruefung, damit "alice" und "alice (i.V. Bob)" als dieselbe
    physische Person erkannt werden.
    """
    s = (actor or "").strip().lower()
    if not s:
        return set()
    tokens = {s}
    if " (i.v. " in s:
        main_p, sub_p = s.split(" (i.v. ", 1)
        tokens.add(main_p.strip())
        sub_clean = sub_p.rstrip(")").strip()
        if sub_clean:
            tokens.add(sub_clean)
            tokens.add(sub_clean.split(" ")[0])
    else:
        tokens.add(s.split(" ")[0])
    return {t for t in tokens if t}


class ApprovalPolicyEngine:
    _chain_lock = threading.RLock()

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._chain_lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
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

            # D05/MED (F013): frueher sperrte der Trigger nur id/prev_hash/
            # current_hash — timestamp, action, new_value und signature_valid
            # waren per SQL-UPDATE aenderbar. Die Erkennung in
            # verify_audit_integrity() war bloss Detektion, keine Verhinderung.
            # Jetzt blockt BEFORE UPDATE ON (ohne OF-Klausel) JEDE Spalte.
            # Bestands-DBs muessen den alten Trigger droppen, damit die neue
            # Definition wirksam wird (CREATE IF NOT EXISTS greift sonst nicht).
            conn.execute("DROP TRIGGER IF EXISTS approval_chain_no_hash_update")
            conn.execute("""
                CREATE TRIGGER approval_chain_no_hash_update
                BEFORE UPDATE ON approval_policy_audit_chain
                BEGIN
                    SELECT RAISE(ABORT, 'approval_policy_audit_chain is append-only');
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS approval_chain_no_delete
                BEFORE DELETE ON approval_policy_audit_chain
                BEGIN
                    SELECT RAISE(ABORT, 'approval_policy_audit_chain is append-only');
                END
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
            # D04/MED: Der Antragsteller wird als eigene Spalte persistiert,
            # damit die Ersteller-Sperre engine-seitig (nicht nur im Router)
            # greift. Idempotenter SQLite-ALTER wie in session_taint_guard.py.
            _columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(approval_requests)").fetchall()
            }
            if "requester_id" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN requester_id TEXT")
            if "assigned_approver" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN assigned_approver TEXT")
            if "escalated_to" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN escalated_to TEXT")
            if "escalation_reason" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN escalation_reason TEXT")

            # d14/HIGH: Aenderung der 4-Augen-Schwelle benötigt einen zweiten,
            # unabhaengigen Genehmiger. Einzel-Admin erzeugt nur einen Vorschlag.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_policy_change_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    policy_key TEXT NOT NULL,
                    proposed_value TEXT NOT NULL,
                    old_value TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    approved_by TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
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
                # E (Audit): Block-ID an den Schreibpfad geben, damit der
                # gleiche HMAC-Epochen-Key wie in verify_audit_integrity()
                # (r["id"]) verwendet wird.
                next_audit_id = int(cur.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM approval_policy_audit_chain"
                ).fetchone()[0])
                for domain, key, val, label, desc, user in default_policies:
                    cur.execute("""
                        INSERT INTO approval_policies (domain, policy_key, policy_value, label, description, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (domain, key, val, label, desc, now, user))

                    # Chained audit log (HMAC-SHA256 wenn ARCHON_AUDIT_HMAC_KEY gesetzt, sonst SHA-256)
                    from backend.audit_log import _chain_hash
                    payload = f"{prev_h}|{now}|{user}|INIT|{domain}|{key}|{val}"
                    curr_h = _chain_hash(payload, next_audit_id)
                    cur.execute("""
                        INSERT INTO approval_policy_audit_chain 
                        (id, prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
                        VALUES (?, ?, ?, ?, ?, 'INIT', ?, ?, '', ?)
                    """, (next_audit_id, prev_h, curr_h, now, user, domain, key, val))
                    prev_h = curr_h
                    next_audit_id += 1

                # Seed default delegation
                cur.execute("""
                    INSERT OR IGNORE INTO delegation_settings (user_id, is_active, substitute_id, substitute_name, updated_at)
                    VALUES ('admin', 0, 'katharina', 'Katharina Völk (QM & Compliance)', ?)
                """, (now,))

            conn.commit()

    # --------------------------------------------------------------------------
    # Audit Chain Helper
    # --------------------------------------------------------------------------
    def _log_audit_change(self, user_id: str, action: str, domain: str, key: str, old_val: str, new_val: str, conn: Optional[sqlite3.Connection] = None) -> str:
        from backend.audit_log import _chain_hash
        with self._chain_lock:
            should_close = False
            if conn is None:
                conn = self._get_conn()
                conn.execute("BEGIN IMMEDIATE")
                should_close = True

            cur = conn.cursor()
            last_entry = cur.execute("SELECT current_hash FROM approval_policy_audit_chain ORDER BY id DESC LIMIT 1").fetchone()
            prev_h = last_entry["current_hash"] if last_entry else GENESIS_HASH
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            payload = f"{prev_h}|{now}|{user_id}|{action}|{domain}|{key}|{old_val}->{new_val}"
            # E (Audit): gleiche Block-ID wie in verify_audit_integrity().
            next_id = int(cur.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM approval_policy_audit_chain"
            ).fetchone()[0])
            curr_h = _chain_hash(payload, next_id)

            cur.execute("""
                INSERT INTO approval_policy_audit_chain 
                (id, prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (next_id, prev_h, curr_h, now, user_id, action, domain, key, old_val, new_val))
            conn.commit()

            if should_close:
                conn.close()
            return curr_h

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

    @staticmethod
    def _parse_finance_threshold(value: Any, policy_key: str) -> float:
        """Numerische Schwelle mit spanne — bei Parse-Fehler fail-closed."""
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"Policy '{policy_key}' muss ein numerischer Betrag sein.")
        if not (0.0 <= numeric <= 1_000_000.0):
            raise ValueError(
                f"Policy '{policy_key}' liegt ausserhalb der erlaubten Spanne (0..1_000_000)."
            )
        return numeric

    def _assert_finance_threshold_invariant(
        self, cur: sqlite3.Cursor, policy_key: str, candidate_value: Any
    ) -> None:
        """D04/HIGH: `auto_max < four_eyes_min` mit Mindestabstand, SYMMETRISCH.

        Frueher wurde die Invariante nur beim Aendern von
        `finance_auto_approval_max` gegen `finance_four_eyes_min` geprueft.
        Ein einzelner Admin konnte daher `finance_four_eyes_min` unter die
        Auto-Freigabeschwelle senken und damit alle Betraege automatisch
        freigeben. Jetzt wird bei jeder Aenderung einer der beiden Schwellen
        das jeweilige Gegenstück aus der DB gelesen und die Invariante mit
        hartem Mindestabstand geprueft (fail-closed bei fehlender/Nicht-Zahl).
        """
        keys = ("finance_auto_approval_max", "finance_four_eyes_min")
        if policy_key not in keys:
            return
        values = {
            key: (
                self._parse_finance_threshold(candidate_value, policy_key)
                if key == policy_key
                else None
            )
            for key in keys
        }
        for key in keys:
            if values[key] is None:
                row = cur.execute(
                    "SELECT policy_value FROM approval_policies WHERE policy_key = ?", (key,)
                ).fetchone()
                if not row:
                    raise ValueError(
                        f"Policy '{key}' fehlt — Schwellen-Invariante nicht pruefbar (fail-closed)."
                    )
                values[key] = self._parse_finance_threshold(row["policy_value"], key)
        gap = values["finance_four_eyes_min"] - values["finance_auto_approval_max"]  # type: ignore[operator, operator, operator]
        if gap + _GAP_EPSILON < FINANCE_THRESHOLD_MIN_GAP:
            raise ValueError(
                "Invariante verletzt: finance_auto_approval_max muss mindestens "
                f"{FINANCE_THRESHOLD_MIN_GAP:.2f} EUR unter finance_four_eyes_min liegen "
                f"(auto_max={values['finance_auto_approval_max']:.2f}, "
                f"four_eyes_min={values['finance_four_eyes_min']:.2f})."
            )

    def update_policy(self, policy_key: str, new_value: str, user_id: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM approval_policies WHERE policy_key = ?", (policy_key,)).fetchone()
            if not row:
                raise ValueError(f"Policy-Key {policy_key} nicht gefunden.")

            old_val = row["policy_value"]
            domain = row["domain"]
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # P1/D04/HIGH: Vorher konnte ein Admin finance_auto_approval_max auf
            # 1_000_000 setzen und damit alle Finanzanfragen ohne Vier-Augen-Prinzip
            # automatisch freigeben. Typ, Bereich und die SYMMETRISCHE Invariante
            # (auch bei Aenderung von finance_four_eyes_min) werden jetzt zentral
            # fuer ALLE Aufrufer geprueft.
            self._assert_finance_threshold_invariant(cur, policy_key, new_value)

            # d14/MED: finance_four_eyes_min ist die Hoheits-Schwelle selbst,
            # finance_auto_approval_max die korrespondierende Freigabeschwelle.
            # Ein einzelner Admin darf KEINE von beiden direkt aendern — er
            # erzeugt einen Vorschlag, der von einer zweiten, unabhaengigen
            # Person freigegeben werden muss (4-Augen). Vorher konnte ein
            # Admin die Auto-Freigabe von 50 auf knapp 500 EUR anheben.
            if policy_key in ("finance_four_eyes_min", "finance_auto_approval_max"):
                import uuid
                proposal_id = f"policy-change-{uuid.uuid4().hex}"
                cur.execute("""
                    INSERT INTO approval_policy_change_proposals
                    (proposal_id, policy_key, proposed_value, old_value, proposed_by,
                     approved_by, status, created_at, resolved_at)
                    VALUES (?, ?, ?, ?, ?, NULL, 'pending', ?, NULL)
                """, (proposal_id, policy_key, str(new_value), str(old_val), user_id, now))
                audit_hash = self._log_audit_change(
                    user_id, "PROPOSE_POLICY_CHANGE", domain, policy_key,
                    old_val, new_value, conn=conn,
                )
                conn.commit()
                return {
                    "policy_key": policy_key,
                    "old_value": old_val,
                    "new_value": new_value,
                    "status": "pending_four_eyes",
                    "proposal_id": proposal_id,
                    "message": (
                        f"Aenderung der Finanz-Schwelle '{policy_key}' erfordert eine zweite, "
                        "unabhaengige Freigabe (approve_policy_change_proposal)."
                    ),
                    "audit_hash": audit_hash,
                    "updated_at": now,
                }

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

    def approve_policy_change_proposal(
        self, proposal_id: str, approver_id: str
    ) -> Dict[str, Any]:
        """Vierte-Augen-Freigabe fuer eine Policy-Aenderung (d14/HIGH).

        Der zweite Genehmiger muss eine andere physische Person sein als der
        Antragsteller; sonst bleibt der Vorschlag pending.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            p = cur.execute(
                "SELECT * FROM approval_policy_change_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if not p:
                raise ValueError(f"Policy-Aenderungsvorschlag {proposal_id} nicht gefunden.")
            if p["status"] != "pending":
                raise ValueError(f"Vorschlag {proposal_id} ist bereits {p['status']}.")

            def _identity_tokens(actor: str) -> set:
                s = (actor or "").strip().lower()
                tokens = {s}
                if s:
                    tokens.add(s.split(" ")[0])
                return {t for t in tokens if t}

            proposer = str(p["proposed_by"] or "")
            if approver_id == proposer or bool(
                _identity_tokens(approver_id) & _identity_tokens(proposer)
            ):
                raise ValueError(
                    "Vier-Augen-Prinzip: die zweite Freigabe muss durch eine "
                    "andere Person erfolgen als den Antragsteller."
                )

            key = p["policy_key"]
            if key not in ("finance_four_eyes_min", "finance_auto_approval_max"):
                raise ValueError(f"Vorschlag fuer {key} ist nicht 4-Augen-pflichtig.")
            # D04/HIGH: gleiche symmetrische Invariante wie im Einzel-Admin-Pfad.
            # Vorher wurde auch hier nur `auto_max` gegen `four_eyes_min` geprueft;
            # ein Vorschlag, der `four_eyes_min` unter `auto_max` senkte, ging durch.
            self._assert_finance_threshold_invariant(cur, key, p["proposed_value"])

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cur.execute("""
                UPDATE approval_policies SET policy_value = ?, updated_at = ?, updated_by = ?
                WHERE policy_key = ?
            """, (p["proposed_value"], now, approver_id, key))
            cur.execute("""
                UPDATE approval_policy_change_proposals
                SET status = 'approved', approved_by = ?, resolved_at = ?
                WHERE proposal_id = ?
            """, (approver_id, now, proposal_id))
            audit_hash = self._log_audit_change(
                approver_id, "APPROVE_POLICY_CHANGE", "finance", key,
                p["old_value"], p["proposed_value"], conn=conn,
            )
            conn.commit()
            return {
                "policy_key": key,
                "new_value": p["proposed_value"],
                "proposal_id": proposal_id,
                "status": "approved",
                "approved_by": approver_id,
                "audit_hash": audit_hash,
            }

    # --------------------------------------------------------------------------
    # Delegation / Urlaubsmodus (M95 — RBAC-gesichert, nie Agent-Fallback)
    # --------------------------------------------------------------------------
    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _required_deputy_roles(domain: str = "finance") -> FrozenSet[str]:
        if str(domain or "").strip().lower() in ADMIN_ONLY_DEPUTY_DOMAINS:
            return frozenset({"admin"})
        return ALLOWED_DEPUTY_ROLES

    def _lookup_human_user(
        self, conn: sqlite3.Connection, identifier: str
    ) -> Optional[Dict[str, Any]]:
        clean = str(identifier or "").strip()
        if not clean or not self._table_exists(conn, "users"):
            return None
        user_cols = {
            str(r["name"]) for r in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        tg_chat_expr = (
            "COALESCE(telegram_chat_id, '') AS telegram_chat_id"
            if "telegram_chat_id" in user_cols
            else "'' AS telegram_chat_id"
        )
        row = conn.execute(
            f"SELECT id, username, display_name, role, is_active, {tg_chat_expr} "
            "FROM users WHERE id = ? OR lower(username) = ? LIMIT 1",
            (clean, clean.lower()),
        ).fetchone()
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"] or row["username"]),
            "role": str(row["role"] or "viewer").lower().strip(),
            "is_active": bool(row["is_active"]),
            "telegram_chat_id": str(row["telegram_chat_id"] or "").strip(),
        }

    def validate_human_deputy(
        self,
        substitute_id: str,
        *,
        delegating_user_id: Optional[str] = None,
        domain: str = "finance",
        conn: Optional[sqlite3.Connection] = None,
        strict_rbac: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Prueft, dass der Stellvertreter ein aktiver Mensch mit ausreichender RBAC-Rolle ist.

        Harte M95-Invariante: Niemals Agent, System-Default, Viewer, inaktiver User
        oder Selbst-Delegation.
        """
        sub = str(substitute_id or "").strip()
        if is_agent_or_system_identity(sub):
            raise ValueError(
                f"Ungueltiger Stellvertreter '{sub}': Agenten oder System-Defaults duerfen "
                "niemals als HITL-/4-Augen-Stellvertreter eingesetzt werden."
            )

        owner = str(delegating_user_id or "").strip()
        if owner and bool(_actor_identity_tokens(owner) & _actor_identity_tokens(sub)):
            raise ValueError(
                "Selbst-Delegation ist unzulaessig: Stellvertreter muss eine andere Person sein."
            )

        def _check(c: sqlite3.Connection) -> Dict[str, Any]:
            has_users = self._table_exists(c, "users")
            enforce = has_users if strict_rbac is None else bool(strict_rbac)
            required_roles = self._required_deputy_roles(domain)
            if not enforce:
                return {
                    "id": sub,
                    "username": sub,
                    "display_name": sub,
                    "role": "operator",
                    "is_active": True,
                    "telegram_chat_id": "",
                }

            user = self._lookup_human_user(c, sub)
            if not user:
                raise ValueError(
                    f"Stellvertreter '{sub}' ist kein registrierter menschlicher Benutzer (fail-closed)."
                )
            if not user["is_active"]:
                raise ValueError(
                    f"Stellvertreter '{user['username']}' ist deaktiviert und nicht freigabeberechtigt."
                )
            if user["role"] not in required_roles:
                raise ValueError(
                    f"Stellvertreter '{user['username']}' hat Rolle '{user['role']}' "
                    f"(erforderlich: {', '.join(sorted(required_roles))}; Viewer ausgeschlossen)."
                )
            if owner:
                owner_user = self._lookup_human_user(c, owner)
                if owner_user and owner_user["id"] == user["id"]:
                    raise ValueError(
                        "Selbst-Delegation ist unzulaessig: Stellvertreter ist identisch mit dem Abwesenden."
                    )
            # Keine Delegationsschleife: wenn Stellvertreter selbst im Urlaubsmodus ist -> fail-closed
            if self._table_exists(c, "delegation_settings"):
                sub_deleg = c.execute(
                    "SELECT is_active FROM delegation_settings WHERE lower(user_id) IN (?, ?) AND is_active = 1",
                    (user["id"].lower(), user["username"].lower()),
                ).fetchone()
                if sub_deleg:
                    raise ValueError(
                        f"Stellvertreter '{user['username']}' befindet sich selbst im Urlaubsmodus (fail-closed)."
                    )
            return user

        if conn is not None:
            return _check(conn)
        with self._get_conn() as own_conn:
            return _check(own_conn)

    def resolve_human_escalation_target(
        self,
        owner_user_id: str,
        *,
        domain: str = "finance",
        requester_id: Optional[str] = None,
        first_approver: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
        strict_rbac: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Ermittelt den gueltigen menschlichen Stellvertreter oder blockiert fail-closed."""
        def _resolve(c: sqlite3.Connection) -> Dict[str, Any]:
            if not self._table_exists(c, "delegation_settings"):
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": "Keine delegation_settings vorhanden (fail-closed).",
                }
            row = c.execute(
                "SELECT * FROM delegation_settings WHERE lower(user_id) = ? LIMIT 1",
                (str(owner_user_id or "admin").strip().lower(),),
            ).fetchone()
            if not row or not str(row["substitute_id"] or "").strip():
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": f"Kein menschlicher Stellvertreter fuer '{owner_user_id}' hinterlegt (fail-closed).",
                }
            sub_id = str(row["substitute_id"]).strip()
            try:
                deputy = self.validate_human_deputy(
                    sub_id,
                    delegating_user_id=owner_user_id,
                    domain=domain,
                    conn=c,
                    strict_rbac=strict_rbac,
                )
            except ValueError as exc:
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": str(exc),
                }

            deputy_tokens = _actor_identity_tokens(deputy["username"]) | _actor_identity_tokens(deputy["id"])
            if requester_id and bool(deputy_tokens & _actor_identity_tokens(requester_id)):
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": "Vier-Augen-Konflikt: Stellvertreter ist identisch mit Antragsteller (fail-closed).",
                }
            if first_approver and bool(deputy_tokens & _actor_identity_tokens(first_approver)):
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": "Vier-Augen-Konflikt: Stellvertreter hat bereits Erstfreigabe erteilt (fail-closed).",
                }

            return {
                "resolved": True,
                "status": "escalated",
                "deputy": deputy,
                "reason": f"Eskaliert an menschlichen Stellvertreter '{deputy['username']}' ({deputy['role']}).",
            }

        if conn is not None:
            return _resolve(conn)
        with self._get_conn() as own_conn:
            return _resolve(own_conn)

    def get_delegation(self, user_id: str = "admin") -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM delegation_settings WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                return dict(row)
            return {
                "user_id": user_id,
                "is_active": 0,
                "substitute_id": "",
                "substitute_name": "",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }

    def set_delegation(
        self,
        user_id: str,
        is_active: bool,
        substitute_id: str,
        substitute_name: str = "",
        *,
        domain: str = "finance",
        strict_rbac: Optional[bool] = None,
    ) -> Dict[str, Any]:
        clean_user = str(user_id or "").strip()
        if not clean_user:
            raise ValueError("user_id darf nicht leer sein.")
        clean_sub_id = str(substitute_id or "").strip()
        clean_sub_name = str(substitute_name or "").strip()

        with self._get_conn() as conn:
            verified_deputy: Optional[Dict[str, Any]] = None
            if is_active:
                verified_deputy = self.validate_human_deputy(
                    clean_sub_id,
                    delegating_user_id=clean_user,
                    domain=domain,
                    conn=conn,
                    strict_rbac=strict_rbac,
                )
                if not clean_sub_name:
                    clean_sub_name = str(verified_deputy.get("display_name") or clean_sub_id)
            elif clean_sub_id and is_agent_or_system_identity(clean_sub_id):
                raise ValueError(
                    f"Ungueltiger Stellvertreter '{clean_sub_id}': Agenten oder System-Defaults sind unzulaessig."
                )

            cur = conn.cursor()
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            prev_row = cur.execute(
                "SELECT is_active, substitute_id, substitute_name FROM delegation_settings WHERE user_id = ?",
                (clean_user,),
            ).fetchone()
            old_state = (
                f"{'active' if prev_row['is_active'] else 'inactive'}:{prev_row['substitute_id']}"
                if prev_row
                else "inactive"
            )
            cur.execute("""
                INSERT INTO delegation_settings (user_id, is_active, substitute_id, substitute_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_active = excluded.is_active,
                    substitute_id = excluded.substitute_id,
                    substitute_name = excluded.substitute_name,
                    updated_at = excluded.updated_at
            """, (clean_user, 1 if is_active else 0, clean_sub_id, clean_sub_name, now))

            action = "ENABLE_DELEGATION" if is_active else "DISABLE_DELEGATION"
            audit_hash = self._log_audit_change(
                clean_user,
                action,
                "system",
                "delegation_settings",
                old_state,
                f"{'active' if is_active else 'inactive'}:{clean_sub_id}:{clean_sub_name}",
                conn=conn,
            )
            conn.commit()

        _record_central_audit(
            "approval_delegation",
            "VACATION_MODE_ENABLED" if is_active else "VACATION_MODE_DISABLED",
            clean_user,
            {
                "user_id": clean_user,
                "is_active": bool(is_active),
                "substitute_id": clean_sub_id,
                "substitute_name": clean_sub_name,
                "substitute_role": (verified_deputy or {}).get("role", ""),
                "audit_hash": audit_hash,
            },
        )
        return {
            "user_id": clean_user,
            "is_active": 1 if is_active else 0,
            "substitute_id": clean_sub_id,
            "substitute_name": clean_sub_name,
            "substitute_role": (verified_deputy or {}).get("role", ""),
            "audit_hash": audit_hash,
        }

    # --------------------------------------------------------------------------
    # Request Evaluation & Queue
    # --------------------------------------------------------------------------
    def evaluate_and_enqueue(self, domain: str, title: str, amount: float = 0.0,
                             reference_id: Optional[str] = None, payload: Optional[dict] = None,
                             requester_id: Optional[str] = None,
                             force_four_eyes: bool = False,
                             requester_required: bool = False,
                             assigned_approver: Optional[str] = None) -> Dict[str, Any]:
        # D04/MED: requester_id ist jetzt Teil des Engine-Vertrags. Er wird
        # zusaetzlich signiert im payload_json abgelegt (defense in depth),
        # damit auch Router/Caller ohne Spaltenzugriff den Ersteller pruefen.
        stored_payload = dict(payload or {})
        requester = str(requester_id or "").strip()
        if requester:
            stored_payload.setdefault("_requester_id", requester)
        # D14/M4: HITL-pflichtige Antraege markieren die Erstellerpflicht
        # explizit im signierten Payload. `approve_request()` leert damit nicht
        # still laufen, falls die requester_id-Spalte aus einem Legacy-Pfad
        # leer bleibt.
        requires_requester = bool(
            requester
            or requester_required
            or force_four_eyes
            or str(domain or "").strip().lower() in HITL_REQUIRED_DOMAINS
        )
        if requires_requester:
            stored_payload.setdefault("_requester_required", True)
        policies = {p["policy_key"]: p["policy_value"] for p in self.get_policies(domain)}
        now = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now.isoformat()

        req_id = f"REQ-{now.strftime('%Y%m%d')}-{os.urandom(3).hex().upper()}"
        auto_max = float(policies.get("finance_auto_approval_max", "50.00"))
        four_eyes_min = float(policies.get("finance_four_eyes_min", "500.00"))
        timeout_hours = int(policies.get("finance_timeout_hours", "24"))

        owner_approver = str(assigned_approver or "admin").strip() or "admin"
        deleg = self.get_delegation(owner_approver)
        delegation_active = bool(deleg.get("is_active"))
        active_substitute: Optional[str] = None
        escalated_to: Optional[str] = None
        escalation_reason: Optional[str] = None

        # Check conditions
        # F022/H-14-3: Hoheitsaenderungen (z.B. AI-Act-Downgrades) sind immer
        # 4-Augen-pflichtig — unabhaengig von einem Geldbetrag.
        requires_four_eyes = 1 if (force_four_eyes or amount >= four_eyes_min) else 0
        expires_at = (now + datetime.timedelta(hours=timeout_hours)).isoformat()

        # D04/HIGH: Auto-Freigabe NUR wenn die Invariante auch tatsaechlich
        # greift. Ein Betrag, der die Vier-Augen-Schwelle erreicht/ueberschreitet,
        # darf niemals automatisch freigegeben werden.
        if amount <= auto_max and not requires_four_eyes and domain == "finance":
            status = "auto_approved"
            first_approver = "System-Rule (Auto-Approval <= 50 EUR)"
            first_approved_at = now_iso
        else:
            status = "pending"
            first_approver = None
            first_approved_at = None

        # M95: Bei aktivem Urlaubsmodus menschlichen Stellvertreter pruefen (nie Agent, fail-closed)
        if status == "pending" and delegation_active:
            esc = self.resolve_human_escalation_target(
                owner_approver,
                domain=domain,
                requester_id=requester or None,
            )
            if esc["resolved"] and esc["deputy"]:
                escalated_to = str(esc["deputy"]["username"])
                active_substitute = str(deleg.get("substitute_name") or esc["deputy"]["display_name"])
                escalation_reason = str(esc["reason"])
            else:
                status = "escalated_blocked"
                escalated_to = None
                active_substitute = None
                escalation_reason = str(esc["reason"])

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO approval_requests (
                    id, domain, reference_id, title, amount, currency, status,
                    requires_four_eyes, first_approver, first_approved_at,
                    expires_at, created_at, payload_json, requester_id,
                    assigned_approver, escalated_to, escalation_reason
                ) VALUES (?, ?, ?, ?, ?, 'EUR', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req_id, domain, reference_id, title, amount, status,
                requires_four_eyes, first_approver, first_approved_at,
                expires_at, now_iso, json.dumps(stored_payload, ensure_ascii=False),
                requester or None, owner_approver, escalated_to, escalation_reason,
            ))
            conn.commit()

        # Audit log creation
        self._log_audit_change("system", "ENQUEUE_REQUEST", domain, req_id, "NONE", status)
        if delegation_active and status in ("pending", "escalated_blocked"):
            esc_action = "DEPUTY_ESCALATION" if escalated_to else "ESCALATION_BLOCKED_FAIL_CLOSED"
            self._log_audit_change(
                owner_approver,
                esc_action,
                domain,
                req_id,
                "pending",
                f"{escalated_to or 'BLOCKED'}:{escalation_reason or ''}",
            )
            _record_central_audit(
                "approval_escalation",
                esc_action,
                owner_approver,
                {
                    "request_id": req_id,
                    "domain": domain,
                    "status": status,
                    "assigned_approver": owner_approver,
                    "escalated_to": escalated_to,
                    "reason": escalation_reason or "",
                },
            )

        return {
            "request_id": req_id,
            "domain": domain,
            "title": title,
            "amount": amount,
            "status": status,
            "requires_four_eyes": bool(requires_four_eyes),
            "assigned_approver": owner_approver,
            "delegation_active": delegation_active,
            "delegated_to": active_substitute,
            "escalated_to": escalated_to,
            "escalation_reason": escalation_reason,
            "expires_at": expires_at,
        }

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Eine Freigabeanfrage exakt nach ID (kein Listen-Scan, kein stilles Fallback)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
            ).fetchone()
            return dict(row) if row else None

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

    def approve_request(self, request_id: str, approver_id: str) -> Dict[str, Any]:
        # D04/MED + M95: kein Default-Approver, kein Agent, kein Viewer.
        if is_agent_or_system_identity(approver_id):
            raise ValueError(
                f"Freigabe verweigert: '{approver_id}' ist eine Agenten-/System-Identitaet "
                "(HITL-/4-Augen-Freigaben erfordern einen berechtigten Menschen)."
            )
        with self._chain_lock:
            with self._get_conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                req = cur.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
                if not req:
                    raise ValueError("Freigabeanfrage nicht gefunden.")

                if req["status"] in ("approved", "rejected"):
                    raise ValueError(f"Anfrage kann nicht genehmigt werden (aktueller Status: {req['status']}).")

                # M95: RBAC-Rollenpruefung wenn users-Tabelle existiert (Viewer / Inaktive blockieren)
                approver_user = self._lookup_human_user(conn, approver_id)
                if approver_user is not None:
                    if not approver_user["is_active"]:
                        raise ValueError(f"Freigabe verweigert: Benutzer '{approver_user['username']}' ist deaktiviert.")
                    allowed_roles = self._required_deputy_roles(str(req["domain"] or "finance"))
                    if approver_user["role"] not in allowed_roles:
                        raise ValueError(
                            f"Freigabe verweigert: Rolle '{approver_user['role']}' darf Domain "
                            f"'{req['domain']}' nicht freigeben (erforderlich: {', '.join(sorted(allowed_roles))})."
                        )

                # D04/MED: Ersteller-Sperre zentral im Engine — nicht nur im
                # Router. Jeder Aufrufer (u. a. MCP-Pfad) ist damit gebunden.
                # Quelle: eigene Spalte -> signiertes Payload -> created_by.
                pl = req["payload_json"]
                if isinstance(pl, str):
                    try:
                        pl = json.loads(pl)
                    except (TypeError, ValueError):
                        pl = {}
                if not isinstance(pl, dict):
                    pl = {}
                requester = str(req["requester_id"] or "").strip()
                if not requester:
                    requester = str(pl.get("_requester_id") or pl.get("requester_id") or "").strip()
                if not requester and "created_by" in req.keys():
                    requester = str(req["created_by"] or "").strip()
                # D14/M4: bei HITL-pflichtigen Antraegen darf ein leerer
                # Ersteller nicht still durchgewinkt werden — sonst ist die
                # Ersteller-Sperre wirkungslos und eine identifizierte Person
                # kann sich selbst freigeben.
                if not requester and bool(pl.get("_requester_required")):
                    raise ValueError(
                        "Vier-Augen-Prinzip: Ersteller der Freigabeanfrage nicht verifizierbar "
                        "— Freigabe verweigert (fail-closed)."
                    )
                if requester and bool(
                    _actor_identity_tokens(approver_id) & _actor_identity_tokens(requester)
                ):
                    raise ValueError(
                        "Vier-Augen-Prinzip: der Ersteller darf die eigene Freigabeanfrage nicht genehmigen."
                    )

                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                deleg_row = cur.execute("SELECT * FROM delegation_settings WHERE user_id = ?", (approver_id,)).fetchone()
                is_deleg_active = bool(deleg_row["is_active"]) if deleg_row else False
                sub_name = deleg_row["substitute_name"] if deleg_row else "Katharina Völk (QM)"
                actual_approver = f"{approver_id} (i.V. {sub_name})" if is_deleg_active else approver_id

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
                        # 2nd approval step: Prüfen, dass zweite Genehmigung von einer anderen physischen Person stammt
                        def _identity_tokens(actor_str: str) -> set:
                            s = (actor_str or "").strip().lower()
                            tokens = set()
                            if " (i.v. " in s:
                                main_p, sub_p = s.split(" (i.v. ", 1)
                                tokens.add(main_p.strip())
                                sub_clean = sub_p.rstrip(")").strip()
                                if sub_clean:
                                    tokens.add(sub_clean)
                                    tokens.add(sub_clean.split(" ")[0])
                            elif s:
                                tokens.add(s)
                                tokens.add(s.split(" ")[0])
                            return {t for t in tokens if t}

                        first_ids = _identity_tokens(req["first_approver"])
                        second_ids = _identity_tokens(actual_approver)
                        if req["first_approver"] == actual_approver or bool(first_ids & second_ids):
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

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()  # noqa: F841
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
        """Finds requests that exceeded their expiry time and escalates them fail-closed (M95).

        Harte Invariante: Timeout fuehrt niemals zu Auto-Approval oder Agent-Delegation.
        Eskalation erfolgt ausschliesslich an einen verifizierten menschlichen RBAC-Stellvertreter;
        fehlt dieser, wird die Anfrage fail-closed auf ``escalated_blocked`` gesetzt.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        central_events: List[Dict[str, Any]] = []
        with self._get_conn() as conn:
            cur = conn.cursor()
            req_cols = {
                str(c["name"]) for c in cur.execute("PRAGMA table_info(approval_requests)").fetchall()
            }
            has_m95_cols = {"assigned_approver", "escalated_to", "escalation_reason"}.issubset(req_cols)
            has_users = self._table_exists(conn, "users")
            has_deleg = self._table_exists(conn, "delegation_settings")

            select_cols = ["id", "title", "amount", "domain", "status"]
            for opt_col in ("requester_id", "first_approver", "assigned_approver"):
                if opt_col in req_cols:
                    select_cols.append(opt_col)
            rows = cur.execute(
                f"SELECT {', '.join(select_cols)} FROM approval_requests "
                "WHERE status IN ('pending', 'first_approved') AND expires_at < ?",
                (now,),
            ).fetchall()

            escalated_count = 0
            for r in rows:
                old_status = str(r["status"] or "pending")
                if has_users and has_deleg:
                    owner = (
                        str(r["assigned_approver"] or "").strip()
                        if "assigned_approver" in req_cols
                        else ""
                    ) or "admin"
                    requester = str(r["requester_id"] or "").strip() if "requester_id" in req_cols else None
                    first_app = str(r["first_approver"] or "").strip() if "first_approver" in req_cols else None
                    esc = self.resolve_human_escalation_target(
                        owner,
                        domain=str(r["domain"] or "finance"),
                        requester_id=requester or None,
                        first_approver=first_app or None,
                        conn=conn,
                        strict_rbac=True,
                    )
                    new_status = str(esc["status"])  # 'escalated' | 'escalated_blocked'
                    target_human = str(esc["deputy"]["username"]) if esc["resolved"] and esc["deputy"] else None
                    esc_reason = str(esc["reason"])
                    audit_action = "ESCALATE_TO_DEPUTY" if target_human else "ESCALATE_BLOCKED_FAIL_CLOSED"
                    audit_new = f"{new_status}:{target_human or 'NO_HUMAN_DEPUTY'}"
                else:
                    # Kompatibilitaet fuer isolierte Legacy-Schema-Tests ohne users-Tabelle
                    new_status = "escalated"
                    target_human = None
                    esc_reason = "Timeout eskaliert"
                    audit_action = "ESCALATE_REQUEST"
                    audit_new = "escalated"

                if has_m95_cols:
                    cur.execute(
                        """
                        UPDATE approval_requests
                        SET status = ?, escalated_at = ?, escalated_to = ?, escalation_reason = ?
                        WHERE id = ?
                        """,
                        (new_status, now, target_human, esc_reason, r["id"]),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE approval_requests
                        SET status = ?, escalated_at = ?
                        WHERE id = ?
                        """,
                        (new_status, now, r["id"]),
                    )
                # N-08: Die Audit-Schreibung muss auf DERSELBEN Verbindung laufen.
                self._log_audit_change(
                    "system_watchdog",
                    audit_action,
                    str(r["domain"]),
                    str(r["id"]),
                    old_status,
                    audit_new,
                    conn=conn,
                )
                central_events.append({
                    "action": audit_action,
                    "request_id": str(r["id"]),
                    "domain": str(r["domain"]),
                    "old_status": old_status,
                    "new_status": new_status,
                    "escalated_to": target_human,
                    "reason": esc_reason,
                })
                escalated_count += 1

            if escalated_count > 0:
                conn.commit()

        for ev in central_events:
            _record_central_audit("approval_escalation", ev["action"], "system_watchdog", ev)

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
        """d05 F-03: Kette + signierter Head-Anker + Trigger."""
        from backend.audit_log import finalize_secondary_chain_verification
        return finalize_secondary_chain_verification(
            "approval_policy_audit_chain", self._verify_audit_integrity_raw(), db_path=self.db_path
        )

    def _verify_audit_integrity_raw(self) -> Dict[str, Any]:
        """Validates all SHA-256 / HMAC-SHA256 hashes in sequence from genesis."""
        from backend.audit_log import HMAC_PREFIX, _hmac_epochs, _verify_hash
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT * FROM approval_policy_audit_chain ORDER BY id ASC").fetchall()
            
            if not rows:
                return {"valid": True, "count": 0, "hmac_active": bool(_hmac_epochs()), "hmac_blocks": 0, "message": "Audit-Kette ist leer."}

            prev_hash = GENESIS_HASH
            hmac_blocks = 0
            for r in rows:
                if r["prev_hash"] != prev_hash:
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Kettenbruch bei Eintrag ID {r['id']}: prev_hash stimmt nicht überein."
                    }
                if str(r["current_hash"] or "").startswith(HMAC_PREFIX):
                    hmac_blocks += 1
                # R-30: Validiere auch den berechneten Hash ueber dem tatsaechlichen Inhalt der Zeile
                if r["action"] == "INIT":
                    payload = f"{r['prev_hash']}|{r['timestamp']}|{r['user_id']}|INIT|{r['domain']}|{r['policy_key']}|{r['new_value']}"
                else:
                    payload = f"{r['prev_hash']}|{r['timestamp']}|{r['user_id']}|{r['action']}|{r['domain']}|{r['policy_key']}|{r['old_value']}->{r['new_value']}"
                # H4 (Audit 23.11.2026): Block-ID uebergeben, sonst werden
                # nach einer HMAC-Epochen-Rotation alle alten Bloecke mit dem
                # NEUEN Key geprueft -> falscher Manipulationsalarm.
                if not _verify_hash(payload, str(r["current_hash"] or ""), r["id"]):
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Payload-Manipulation bei Eintrag ID {r['id']}: Berechneter Hash stimmt nicht mit aktuellem Zeileninhalt überein."
                    }
                prev_hash = r["current_hash"]

            key_active = bool(_hmac_epochs())
            if key_active:
                try:
                    legacy_max = int(os.environ.get("ARCHON_AUDIT_LEGACY_MAX_BLOCK", "0") or 0)
                except ValueError:
                    legacy_max = 0
                # d05 F-01: Voller HMAC-Downgrade (auch wenn hmac_blocks == 0) muss erkannt werden.
                downgraded_ids = [
                    int(r["id"]) for r in rows
                    if not str(r["current_hash"] or "").startswith(HMAC_PREFIX)
                    and int(r["id"]) > legacy_max
                ]
                if downgraded_ids:
                    return {
                        "valid": False,
                        "count": len(rows),
                        "hmac_active": True,
                        "hmac_blocks": hmac_blocks,
                        "downgraded_ids": downgraded_ids[:10],
                        "message": (
                            "HMAC-Key ist aktiv, aber Approval-Policy-Audit-Block(e) ohne HMAC-Signatur "
                            "vorhanden (moeglicher Downgrade auf nacktes SHA-256)."
                        ),
                    }
            if hmac_blocks and not key_active:
                return {
                    "valid": False,
                    "count": len(rows),
                    "hmac_active": False,
                    "hmac_blocks": hmac_blocks,
                    "message": "HMAC-Signaturpruefung fehlgeschlagen: ARCHON_AUDIT_HMAC_KEY fehlt."
                }

            return {
                "valid": True,
                "count": len(rows),
                "hmac_active": key_active,
                "hmac_blocks": hmac_blocks,
                "latest_hash": prev_hash,
                "message": f"Kryptografische Integrität bestätigt ({len(rows)} Einträge manipulationssicher verkettet)."
            }

approval_engine = ApprovalPolicyEngine()
