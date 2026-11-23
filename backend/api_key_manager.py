"""
Archon OS - API Key Manager mit Scopes, Rate-Limits und GoBD/ISO 27001 Auditierung (t-6fad7a)
Verwaltung sicherer API-Tokens fuer n8n, Telegram und MCP-Clients mit Einmalanzeige,
gehashter Speicherung (SHA-256) und Sliding-Window Drosselung.
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
import json
import time
import datetime
import threading
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    from backend.db_paths import resolve_db
    DB_FILE = resolve_db("agentic_memory.db")
except Exception:
    DB_FILE = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
KEY_SALT = os.environ.get("ARCHON_API_KEY_PEPPER") or "ARCHON_OS_API_KEY_SALT_2026_SECURE"
LEGACY_KEY_SALT = "ARCHON_OS_API_KEY_SALT_2026_SECURE"
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

_PEPPER_FALLBACK_WARNED = False


def _warn_missing_pepper_once() -> None:
    global _PEPPER_FALLBACK_WARNED
    if _PEPPER_FALLBACK_WARNED:
        return
    _PEPPER_FALLBACK_WARNED = True
    import logging
    logging.getLogger(__name__).warning(
        "ARCHON_API_KEY_PEPPER ist nicht gesetzt; verwende Legacy-Salt-SHA256-Fallback. "
        "Fuer Produktivbetrieb ARCHON_API_KEY_PEPPER (oder Docker-Secret) konfigurieren."
    )

# Erlaubte Standard-Scopes
VALID_SCOPES = {
    "read_only": "Nur lesender Zugriff (Status, Logs, Telemetrie, Profile)",
    "kanban_rw": "Kanban Lese- und Schreibzugriff (Aufgaben anlegen, verschieben, schließen)",
    "agent_execute": "Agenten-Ausführung & Autonomie-Trigger (Remote-Befehle, Chat)",
    "admin_full": "Vollzugriff auf alle System-APIs & Konfigurationen"
}

class ApiKeyManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        # In-Memory Rate-Limiter Tracking: key_id -> [timestamps]
        self._request_history: Dict[str, List[float]] = {}
        self._history_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        # ClosingConnection: `with conn` schliesst die Verbindung
        # deterministisch. Ohne das bleiben bei jedem Aufruf offene
        # Dateideskriptoren zurueck (unter Windows blockiert das den
        # Temp-Verzeichnis-Teardown).
        class _ClosingConn(sqlite3.Connection):
            def __enter__(self):
                super().__enter__()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                try:
                    super().__exit__(exc_type, exc_val, exc_tb)
                finally:
                    self.close()

        conn = sqlite3.connect(self.db_path, timeout=15.0, factory=_ClosingConn)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    scopes TEXT NOT NULL,
                    rate_limit_rpm INTEGER DEFAULT 60,
                    rate_limit_rpd INTEGER DEFAULT 5000,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    last_used_at TEXT,
                    is_active INTEGER DEFAULT 1,
                    revoked_at TEXT,
                    revoked_by TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_key_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    prev_hash TEXT NOT NULL,
                    block_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );
            """)
            # H3 (Audit 23.11.2026): Append-only wie die Zentralkette.
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS api_key_audit_no_update
                BEFORE UPDATE ON api_key_audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'api_key_audit_log is append-only');
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS api_key_audit_no_delete
                BEFORE DELETE ON api_key_audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'api_key_audit_log is append-only');
                END
            """)
            conn.commit()

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        """Erzeugt einen keyed HMAC-SHA256 Hash mit Pepper (oder Legacy-Salt-Fallback)."""
        pepper = os.environ.get("ARCHON_API_KEY_PEPPER")
        if pepper:
            return hmac.new(pepper.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()
        _warn_missing_pepper_once()
        salted = f"{KEY_SALT}:{raw_token}".encode("utf-8")
        return hashlib.sha256(salted).hexdigest()

    @staticmethod
    def _legacy_hash_token(raw_token: str) -> str:
        salted = f"{LEGACY_KEY_SALT}:{raw_token}".encode("utf-8")
        return hashlib.sha256(salted).hexdigest()

    def _log_audit(self, key_id: str, action: str, details: Dict[str, Any], created_by: str = "admin", conn: Optional[sqlite3.Connection] = None, emit_global: bool = True):
        """Fuegt einen Eintrag in die SHA-256 Hash-Kette fuer API-Keys ein."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        details_json = json.dumps(details, sort_keys=True, ensure_ascii=False)

        def _do_log(active_conn: sqlite3.Connection):
            row = active_conn.execute("SELECT block_hash FROM api_key_audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row["block_hash"] if row else GENESIS_HASH
            raw_chain_string = f"{prev_hash}|{key_id}|{action}|{details_json}|{created_by}|{now_iso}"
            # H3: HMAC mit dem zentralen Chain-Secret statt nacktem SHA-256,
            # sonst kann die Kette mit DB-Schreibzugriff ab Block 1 neu
            # signiert werden.
            from backend.audit_log import _chain_hash
            block_hash = _chain_hash(raw_chain_string)

            active_conn.execute("""
                INSERT INTO api_key_audit_log (key_id, action, details, prev_hash, block_hash, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key_id, action, details_json, prev_hash, block_hash, now_iso, created_by))

        if conn is not None:
            _do_log(conn)
        else:
            with self._get_conn() as local_conn:
                _do_log(local_conn)
                local_conn.commit()
        if emit_global and conn is None:
            try:
                from backend.audit_log import chained_audit_log
                chained_audit_log.record_event(
                    category="api_keys",
                    action=f"api_{action.lower()}",
                    agent_id=created_by,
                    payload={"key_id": key_id, **details}
                )
            except Exception as exc:
                logger.debug("API-Key-Manager: Audit-Log-Eintrag fehlgeschlagen: %s", exc)

    def verify_integrity(self) -> Dict[str, Any]:
        """Lauf-5 H-02: kryptografische Pruefung der API-Key-Audit-Kette.

        Die Kette hatte Append-only-Trigger und HMAC-Signatur, aber keine
        Verifikationsfunktion — Manipulationen waren nur bei manueller
        Pruefung erkennbar.
        """
        from backend.audit_log import HMAC_PREFIX, _hmac_epochs, _verify_hash
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM api_key_audit_log ORDER BY id ASC"
            ).fetchall()
            if not rows:
                return {"valid": True, "count": 0, "message": "API-Key-Kette ist leer."}
            prev_hash = GENESIS_HASH
            hmac_blocks = 0
            for r in rows:
                if r["prev_hash"] != prev_hash:
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Kettenbruch bei API-Key-Audit ID {r['id']}.",
                    }
                if str(r["block_hash"] or "").startswith(HMAC_PREFIX):
                    hmac_blocks += 1
                payload = (
                    f"{r['prev_hash']}|{r['key_id']}|{r['action']}|"
                    f"{r['details']}|{r['created_by']}|{r['created_at']}"
                )
                if not _verify_hash(payload, str(r["block_hash"] or ""), r["id"]):
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Payload-Manipulation bei API-Key-Audit ID {r['id']}.",
                    }
                prev_hash = r["block_hash"]
            key_active = bool(_hmac_epochs())
            if hmac_blocks and not key_active:
                return {
                    "valid": False, "count": len(rows), "hmac_active": False,
                    "message": "HMAC-Bloecke ohne passenden ARCHON_AUDIT_HMAC_KEY.",
                }
            return {
                "valid": True, "count": len(rows), "hmac_active": key_active,
                "hmac_blocks": hmac_blocks, "latest_hash": prev_hash,
            }

    @staticmethod
    def _emit_global_audit(key_id: str, action: str, details: Dict[str, Any], created_by: str) -> None:
        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="api_keys",
                action=f"api_{action.lower()}",
                agent_id=created_by,
                payload={"key_id": key_id, **details},
            )
        except Exception as exc:
            logger.debug("API-Key-Manager: Globaler Audit-Log-Eintrag fehlgeschlagen: %s", exc)

    def create_key(
        self,
        name: str,
        scopes: List[str],
        rate_limit_rpm: int = 60,
        rate_limit_rpd: int = 5000,
        created_by: str = "admin"
    ) -> Dict[str, Any]:
        """
        Erstellt einen neuen kryptografischen API-Key.
        Gibt den Klartext-Token EXAKT EINMALIG zurueck.
        In der Datenbank wird ausschliesslich der Hash gespeichert.
        """
        if not name or not name.strip():
            raise ValueError("Name/Zweck des API-Keys darf nicht leer sein.")

        # Scopes normalisieren und validieren
        cleaned_scopes = [s.strip().lower() for s in scopes if s.strip().lower() in VALID_SCOPES]
        if not cleaned_scopes:
            cleaned_scopes = ["read_only"]

        # Kryptografisch sicheres Token (archon_live_...)
        random_hex = secrets.token_hex(24)
        raw_token = f"archon_live_{random_hex}"
        key_prefix = raw_token[:18] + "..."
        key_hash = self._hash_token(raw_token)
        key_id = f"key_{secrets.token_hex(8)}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO api_keys (
                    key_id, name, key_prefix, key_hash, scopes,
                    rate_limit_rpm, rate_limit_rpd, created_at, created_by, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                key_id,
                name.strip(),
                key_prefix,
                key_hash,
                json.dumps(cleaned_scopes),
                int(rate_limit_rpm),
                int(rate_limit_rpd),
                now_iso,
                created_by
            ))

            audit_details = {
                "name": name.strip(),
                "key_prefix": key_prefix,
                "scopes": cleaned_scopes,
                "rate_limit_rpm": rate_limit_rpm,
                "rate_limit_rpd": rate_limit_rpd
            }
            self._log_audit(key_id, "KEY_CREATED", audit_details, created_by=created_by, conn=conn, emit_global=False)
            conn.commit()
        self._emit_global_audit(key_id, "KEY_CREATED", audit_details, created_by)

        return {
            "key_id": key_id,
            "name": name.strip(),
            "raw_token": raw_token,
            "key_prefix": key_prefix,
            "scopes": cleaned_scopes,
            "rate_limit_rpm": rate_limit_rpm,
            "rate_limit_rpd": rate_limit_rpd,
            "created_at": now_iso,
            "created_by": created_by
        }

    def list_keys(self) -> List[Dict[str, Any]]:
        """Gibt alle API-Keys zurueck (ohne Hash oder Klartext-Token)."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT key_id, name, key_prefix, scopes, rate_limit_rpm, rate_limit_rpd,
                       created_at, created_by, last_used_at, is_active, revoked_at, revoked_by
                FROM api_keys
                ORDER BY created_at DESC
            """).fetchall()

            result = []
            for r in rows:
                scopes_list = []
                try:
                    scopes_list = json.loads(r["scopes"])
                except Exception as exc:
                    logger.debug("API-Key-Manager: Scopes-JSON unlesbar: %s", exc)

                result.append({
                    "key_id": r["key_id"],
                    "name": r["name"],
                    "key_prefix": r["key_prefix"],
                    "scopes": scopes_list,
                    "rate_limit_rpm": r["rate_limit_rpm"],
                    "rate_limit_rpd": r["rate_limit_rpd"],
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                    "last_used_at": r["last_used_at"],
                    "is_active": bool(r["is_active"]),
                    "revoked_at": r["revoked_at"],
                    "revoked_by": r["revoked_by"]
                })
            return result

    def revoke_key(self, key_id: str, revoked_by: str = "admin") -> bool:
        """Deaktiviert einen API-Key dauerhaft und revisionssicher."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute("""
                UPDATE api_keys
                SET is_active = 0, revoked_at = ?, revoked_by = ?
                WHERE key_id = ? AND is_active = 1
            """, (now_iso, revoked_by, key_id))

            if cur.rowcount == 0:
                return False

            rev_details = {"revoked_at": now_iso, "revoked_by": revoked_by}
            self._log_audit(key_id, "KEY_REVOKED", rev_details, created_by=revoked_by, conn=conn, emit_global=False)
            conn.commit()
        self._emit_global_audit(key_id, "KEY_REVOKED", rev_details, revoked_by)
        return True

    def delete_key(self, key_id: str, deleted_by: str = "admin") -> bool:
        """Loescht einen Key vollstaendig aus der aktiven Tabelle (Audit-Log bleibt unveraendert erhalten)."""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM api_keys WHERE key_id = ?", (key_id,))
            if cur.rowcount == 0:
                return False

            del_details = {"deleted_by": deleted_by}
            self._log_audit(key_id, "KEY_DELETED", del_details, created_by=deleted_by, conn=conn, emit_global=False)
            conn.commit()
        self._emit_global_audit(key_id, "KEY_DELETED", del_details, deleted_by)
        return True

    def validate_and_consume(self, raw_token: str, required_scope: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Validiert einen einkommenden API-Key gegen Hash, Scopes und Sliding-Window Rate-Limits.
        Rueckgabe: (is_valid: bool, key_info: dict, error_msg: str)
        """
        if not raw_token or not raw_token.startswith("archon_live_"):
            return False, None, "Ungültiges Token-Format (erwartet: archon_live_...)"

        key_hash = self._hash_token(raw_token)
        legacy_hash = self._legacy_hash_token(raw_token)
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT key_id, name, scopes, rate_limit_rpm, rate_limit_rpd, is_active
                FROM api_keys
                WHERE key_hash = ? OR key_hash = ?
            """, (key_hash, legacy_hash)).fetchone()

            if not row:
                return False, None, "API-Key nicht gefunden oder ungültig."

            if not row["is_active"]:
                return False, None, "API-Key wurde widerrufen (inaktiv)."

            key_id = row["key_id"]
            rpm = row["rate_limit_rpm"] or 0
            rpd = row["rate_limit_rpd"] or 0

            # Scopes pruefen
            try:
                scopes = json.loads(row["scopes"])
            except Exception:
                scopes = []

            if required_scope:
                if "admin_full" not in scopes and required_scope not in scopes:
                    return False, None, f"Fehlende Berechtigung. Erforderlicher Scope: '{required_scope}'"

            # Rate-Limiter (Sliding Window, thread-safe)
            with self._history_lock:
                now = time.time()
                hist = self._request_history.get(key_id, [])
                cutoff_day = now - 86400.0
                hist = [t for t in hist if t >= cutoff_day]

                # 1. RPM Check (letzte 60 Sekunden)
                if rpm > 0:
                    cutoff_min = now - 60.0
                    rpm_count = sum(1 for t in hist if t >= cutoff_min)
                    if rpm_count >= rpm:
                        self._request_history[key_id] = hist
                        return False, None, f"Rate-Limit überschritten: Maximal {rpm} Anfragen pro Minute erlaubt."

                # 2. RPD Check (letzte 24 Stunden)
                if rpd > 0 and len(hist) >= rpd:
                    self._request_history[key_id] = hist
                    return False, None, f"Tageslimit überschritten: Maximal {rpd} Anfragen pro Tag erlaubt."

                hist.append(now)
                self._request_history[key_id] = hist

            # Letzte Nutzung aktualisieren
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE key_id = ?", (now_iso, key_id))
            conn.commit()

            return True, {
                "key_id": key_id,
                "name": row["name"],
                "scopes": scopes,
                "rate_limit_rpm": rpm,
                "rate_limit_rpd": rpd
            }, "OK"

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Liefert die kryptografische Hash-Kette der Key-Verwaltung zurueck."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, key_id, action, details, prev_hash, block_hash, created_at, created_by
                FROM api_key_audit_log
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()

            return [dict(r) for r in rows]

# Globale Instanz
api_key_manager = ApiKeyManager()
