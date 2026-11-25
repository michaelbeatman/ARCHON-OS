# mypy: ignore-errors
"""
backend/auth_service.py
Meilenstein 4: Multi-User-Architektur & Rollenbasierte Zugriffskontrolle (RBAC).
Verwaltet Benutzer, Rollen (admin, operator, viewer), PBKDF2-verschlüsselte Kennwörter
und sichere Session-Tokens mit Zero-Disruption für lokale Entwicklungs-Workflows.
"""

import datetime
import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import DB_BUSY_TIMEOUT_MS, DB_BUSY_TIMEOUT_S, resolve_db
    DB_PATH = resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
    DB_BUSY_TIMEOUT_MS = 5000  # Fallback: SSOT (backend.db_paths) nicht importierbar
    DB_BUSY_TIMEOUT_S = DB_BUSY_TIMEOUT_MS / 1000.0

_PBKDF2_ITERATIONS = 600000
_LEGACY_PBKDF2_ITERATIONS = 100000
_MAX_FAILED_LOGINS = 5
_LOCKOUT_WINDOW_SEC = 900
# C) Harte Obergrenze: ohne Cap waechst _FAILED_LOGINS mit jedem neuen
# Username/IP-Key unbegrenzt (nur erfolgreiche Logins entfernten Keys).
_MAX_FAILED_LOGIN_KEYS = 10_000
_AUTH_LOCK = threading.RLock()
_FAILED_LOGINS: Dict[str, List[float]] = {}


def _audit_auth_event(
    action: str,
    username: str,
    reason: str,
    *,
    ip_address: str = "",
    user_agent: str = "",
    user_id: str = "",
    role: str = "",
) -> None:
    """H-05-3: signiertes Auth-Event — keine Klartext-Passwörter/Tokens/IPs.

    Unter ARCHON_AUDIT_STRICT=1 (Default) ist ein Schreibfehler ein harter
    Abbruch (RuntimeError 'audit_write_failed'); otherwise wird er auf ERROR
    eskaliert, aber die Aktion nicht blockiert.
    """
    from backend.audit_log import (
        _require_audit_event,
        audit_actor_context,
        is_audit_strict,
    )

    payload = {
        "reason": str(reason)[:200],
        "user_id": str(user_id or ""),
        "role": str(role or ""),
        **audit_actor_context(ip_address=ip_address, user_agent=user_agent),
    }
    actor = str(username or "unknown")
    if is_audit_strict():
        _require_audit_event("auth", action, actor, payload)
        return
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event("auth", action, actor, payload)
    except Exception as exc:
        logger.error("[Auth] Audit-Event %s nicht schreibbar: %s", action, exc)


def _record_failed_login(
    fail_key: str,
    now_mono: float,
    *,
    username: str = "",
    ip_address: str = "",
    user_agent: str = "",
    reason: str = "credentials_invalid",
) -> None:
    """Zeichnet einen Fehlversuch auf und begrenzt die Key-Anzahl hart.

    C) Wechselnde Username/IP-Kombinationen konnten _FAILED_LOGINS sonst
    unbegrenzt wachsen lassen. Die Dict-Reihenfolge ist die Insertion-Order,
    daher werden bei Ueberlauf die aeltesten Keys zuerst entfernt.
    H-05-3: zusätzlich dauerhaft signiertes login_failed-Event (das Dict
    ging bei jedem Neustart verloren).
    """
    with _AUTH_LOCK:
        attempts = _FAILED_LOGINS.get(fail_key)
        if attempts is None:
            attempts = []
            _FAILED_LOGINS[fail_key] = attempts
        attempts.append(now_mono)
        overflow = len(_FAILED_LOGINS) - _MAX_FAILED_LOGIN_KEYS
        if overflow > 0:
            for _ in range(overflow):
                _FAILED_LOGINS.pop(next(iter(_FAILED_LOGINS)), None)
    _audit_auth_event(
        "login_failed", username or fail_key.split("|", 1)[0], reason,
        ip_address=ip_address, user_agent=user_agent,
    )


logger = logging.getLogger("archon.auth")


class _ClosingAuthConn(sqlite3.Connection):
    """Auto-closes SQLite connections cleanly at end of `with _get_db() as conn:` blocks."""
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # A3-Delegation: connect-timeout aus der SSOT (5000 ms), kein harter
    # 10-s-Wert mehr, der von DB_BUSY_TIMEOUT_MS abweicht.
    conn = sqlite3.connect(DB_PATH, timeout=DB_BUSY_TIMEOUT_S, factory=_ClosingAuthConn)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
    except Exception as exc:
        logger.warning(f"SQLite-PRAGMA-Init fehlgeschlagen, Standard-Verhalten bleibt aktiv: {exc}")
    return conn


def _hash_password(password: str, salt: str = None, iterations: int = _PBKDF2_ITERATIONS) -> tuple:
    if not salt:
        salt = uuid.uuid4().hex
    pwd_bytes = password.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, int(iterations)).hex()
    return f"pbkdf2_sha256${int(iterations)}${digest}", salt


def _verify_password_hash(password: str, stored_hash: str, salt: str) -> tuple[bool, bool]:
    """Prüft moderne pbkdf2_sha256$600000$... sowie Legacy-100k-Hex-Hashes."""
    if not stored_hash or not salt:
        return False, False
    if stored_hash.startswith("pbkdf2_sha256$"):
        parts = stored_hash.split("$", 2)
        if len(parts) != 3:
            return False, False
        try:
            iters = int(parts[1])
        except ValueError:
            return False, False
        expected = parts[2]
        cand = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iters).hex()
        ok = hmac.compare_digest(cand, expected)
        return ok, (ok and iters < _PBKDF2_ITERATIONS)

    legacy = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _LEGACY_PBKDF2_ITERATIONS).hex()
    ok = hmac.compare_digest(legacy, stored_hash)
    return ok, ok


def _hash_session_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self):
        self._init_tables()
        self._seed_default_admin()

    @staticmethod
    def is_auth_enabled() -> bool:
        """True = Login-Pflicht aktiv.

        P0-2b: Reine Localhost-Entwicklung (127.0.0.1, kein production)
        bleibt bewusst offen, damit Dev-/UI-Tests nicht ausgesperrt werden.
        Sobald der Server auf einer nicht-lokalen Adresse gebunden wird oder
        ``ENVIRONMENT``/``ARCHON_ENV`` = production, wird Auth ERZWUNGEN —
        ein Produktiv-Server steht niemals offen, auch wenn settings.json
        ``auth.enabled=false`` sagt.
        """
        configured = AuthService._read_auth_enabled()
        if not configured and AuthService._must_force_auth():
            logger.warning(
                "[Auth] Nicht-lokale Bindung oder ENVIRONMENT=production erkannt — "
                "Auth wird ungeachtet settings.json erzwungen."
            )
            return True
        return configured

    @staticmethod
    def _must_force_auth() -> bool:
        # K2/C01: expliziter Operator-Schalter fuer Mesh-/Prod-Deployments.
        # Production wird unten bereits erzwungen; dieser Flag deckt den Fall
        # ab, dass der Container zwar `ENVIRONMENT=development` hat, aber
        # ueber `agentic_mesh`/`archon-admin_net` fuer andere Dienste
        # erreichbar ist. Erst nach Provisionierung des Service-Tokens setzen.
        forced = str(os.environ.get("ARCHON_REQUIRE_AUTH") or "").strip().lower()
        if forced in ("1", "true", "yes", "on"):
            return True
        env_name = str(
            os.environ.get("ENVIRONMENT") or os.environ.get("ARCHON_ENV") or ""
        ).strip().lower()
        if env_name in ("production", "prod", "live"):
            return True
        bind = str(os.environ.get("ARCHON_BIND_IP") or "").strip()
        local_binds = {"127.0.0.1", "localhost", "::1", "[::1]"}
        # 0.0.0.0 und jede LAN-/oeffentliche IP sind kein Localhost.
        if bind and bind not in local_binds:
            return True
        # KRITISCH: Docker/Demo-Compose starten uvicorn mit --host 0.0.0.0,
        # setzen aber oft kein ARCHON_BIND_IP. Beim Host-Port-Mapping auf
        # 0.0.0.0 darf Auth niemals aus bleiben (Fallback-Admin fuer alle).
        host = str(
            os.environ.get("UVICORN_HOST") or os.environ.get("HOST") or ""
        ).strip()
        if host and host not in local_binds:
            return True
        return False

    @staticmethod
    def _read_auth_enabled() -> bool:
        """True = Login-Pflicht aktiv.

        Fail-closed (R-08): eine vorhandene, aber unlesbare oder strukturell
        defekte ``settings.json`` ist ein Fehlerfall und schaltet die
        Authentifizierung **nicht** ab — sonst genügt eine abgeschnittene Datei
        für anonymen Zugriff auf die gesamte API. Fehlt jede Konfigurationsdatei,
        bleibt der Entwicklungsdefault (Auth aus).
        """
        possible_paths = [
            os.path.join(WORKSPACE_DIR, "agent_workspace", "settings.json"),
            "/app/agent_workspace/settings.json",
            os.path.join(WORKSPACE_DIR, "settings.json"),
            "/app/settings.json",
            os.path.join(os.getcwd(), "agent_workspace", "settings.json"),
            os.path.join(os.getcwd(), "settings.json")
        ]
        import json
        for p in possible_paths:
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    s = json.load(f)
            except Exception as err:  # noqa: BLE001 - Fail-closed ist die Absicht
                logger.error(f"[Auth] {p} nicht lesbar ({err}) — Auth bleibt aktiv.")
                return True
            if not isinstance(s, dict):
                logger.error(f"[Auth] {p} hat kein Objekt als Wurzel — Auth bleibt aktiv.")
                return True
            if "auth" not in s:
                # Lesbare Datei ohne auth-Block: kein Fehler, naechster Kandidat.
                continue
            auth_cfg = s.get("auth")
            if not isinstance(auth_cfg, dict):
                logger.error(f"[Auth] {p}: 'auth' ist kein Objekt — Auth bleibt aktiv.")
                return True
            return bool(auth_cfg.get("enabled", False))
        return False

    def _init_tables(self):
        with _get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    email TEXT DEFAULT '',
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operator', -- 'admin', 'operator', 'viewer'
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    last_seen_at TEXT DEFAULT '',
                    ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            try:
                conn.execute("ALTER TABLE user_sessions ADD COLUMN last_seen_at TEXT DEFAULT ''")
            except sqlite3.OperationalError as exc:
                logger.warning(f"Migration last_seen_at uebersprungen (vermutlich bereits vorhanden): {exc}")
            conn.commit()

    def _seed_default_admin(self):
        """Erstellt den initialen Haupt-Administrator, falls noch kein Admin existiert."""
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as count FROM users WHERE role = 'admin'")
            row = cur.fetchone()
            if row and row["count"] == 0:
                initial_pwd = (os.environ.get("ARCHON_INITIAL_ADMIN_PASSWORD") or "").strip()
                generated = not initial_pwd
                if generated:
                    # P0-2: kein hartcodiertes Default-Passwort im Quellcode.
                    initial_pwd = secrets.token_urlsafe(18)
                pwd_hash, salt = _hash_password(initial_pwd)
                admin_id = f"usr_{uuid.uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO users (id, username, display_name, email, password_hash, salt, role, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, 'admin', 1)
                """, (admin_id, "admin", "Archon Administrator", "admin@archon.local", pwd_hash, salt))
                conn.commit()
                if generated:
                    # Einmalige Ausgabe an den Operator — danach nur noch Hash
                    # in der DB. Datei liegt im Runtime-State (nicht im Repo).
                    try:
                        # Neben der DB: bei temporaeren Test-DBs landet das
                        # Passwort ebenfalls im Testverzeichnis, nicht im
                        # Produktions-/data-Ordner.
                        pwd_file = os.path.join(
                            os.path.dirname(DB_PATH) or WORKSPACE_DIR,
                            ".archon_initial_admin_password",
                        )
                        os.makedirs(os.path.dirname(pwd_file), exist_ok=True)
                        with open(pwd_file, "w", encoding="utf-8") as fh:
                            fh.write(initial_pwd + "\n")
                        try:
                            os.chmod(pwd_file, 0o600)
                        except OSError:
                            pass
                        logger.warning(
                            "[Auth] Initiales Admin-Passwort generiert und einmalig nach %s geschrieben. "
                            "Nach dem ersten Login aendern und die Datei loeschen.",
                            pwd_file,
                        )
                    except Exception as exc:
                        logger.error(
                            "[Auth] Generiertes Admin-Passwort konnte nicht ausgegeben werden (%s). "
                            "Setze ARCHON_INITIAL_ADMIN_PASSWORD und starte mit leerer users-Tabelle neu.",
                            exc,
                        )

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "operator",
        display_name: str = "",
        email: str = ""
    ) -> Dict[str, Any]:
        username = (username or "").strip().lower()
        if not username:
            raise ValueError("Benutzername darf nicht leer sein.")
        if not re.match(r"^[a-zA-Z0-9._-]+$", username):
            raise ValueError("Ungueltiger Benutzername. Nur Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich erlaubt.")
        if len(password or "") < 8:
            raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")

        role = role.lower().strip()
        if role not in ("admin", "operator", "viewer"):
            role = "operator"

        raw_display = (display_name or "").strip() or username.capitalize()
        display_name = html.escape(raw_display)
        email = (email or "").strip().lower()

        pwd_hash, salt = _hash_password(password)
        user_id = f"usr_{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO users (id, username, display_name, email, password_hash, salt, role, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (user_id, username, display_name, email, pwd_hash, salt, role))
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Der Benutzername '{username}' ist bereits vergeben.")

        return {
            "id": user_id,
            "username": username,
            "display_name": display_name,
            "email": email,
            "role": role,
            "is_active": True
        }

    def authenticate(
        self,
        username: str,
        password: str,
        ip_address: str = "",
        user_agent: str = ""
    ) -> Optional[Dict[str, Any]]:
        username = (username or "").strip().lower()
        fail_key = f"{username}|{ip_address or ''}"
        now_mono = time.monotonic()
        with _AUTH_LOCK:
            recent = [t for t in _FAILED_LOGINS.get(fail_key, []) if now_mono - t < _LOCKOUT_WINDOW_SEC]
            if recent:
                _FAILED_LOGINS[fail_key] = recent
            else:
                _FAILED_LOGINS.pop(fail_key, None)
            if len(recent) >= _MAX_FAILED_LOGINS:
                _audit_auth_event(
                    "login_failed", username, "account_locked",
                    ip_address=ip_address, user_agent=user_agent,
                )
                raise PermissionError("Konto temporär gesperrt: zu viele fehlgeschlagene Anmeldeversuche. Bitte 15 Minuten warten.")

        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, username, display_name, email, password_hash, salt, role, is_active 
                FROM users WHERE username = ?
            """, (username,))
            user = cur.fetchone()

            if not user:
                _record_failed_login(
                    fail_key, now_mono, username=username,
                    ip_address=ip_address, user_agent=user_agent,
                    reason="unknown_user",
                )
                return None
            if not user["is_active"]:
                _audit_auth_event(
                    "login_failed", username, "account_inactive",
                    ip_address=ip_address, user_agent=user_agent,
                    user_id=str(user["id"]), role=str(user["role"]),
                )
                raise PermissionError("Dieses Benutzerkonto ist deaktiviert.")

            ok_pw, needs_upgrade = _verify_password_hash(password, user["password_hash"], user["salt"])
            if not ok_pw:
                _record_failed_login(
                    fail_key, now_mono, username=username,
                    ip_address=ip_address, user_agent=user_agent,
                    reason="wrong_password",
                )
                return None

            with _AUTH_LOCK:
                _FAILED_LOGINS.pop(fail_key, None)

            now = datetime.datetime.now(datetime.timezone.utc)
            now_iso = now.isoformat()
            if needs_upgrade:
                up_hash, up_salt = _hash_password(password)
                cur.execute(
                    "UPDATE users SET password_hash = ?, salt = ?, last_login = ? WHERE id = ?",
                    (up_hash, up_salt, now_iso, user["id"]),
                )
            else:
                cur.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso, user["id"]))

            # Session anlegen: Klartext-Token nur einmalig zurückgeben, in DB nur SHA-256-Hash speichern
            token = f"tok_{uuid.uuid4().hex}_{uuid.uuid4().hex[:12]}"
            token_hash = _hash_session_token(token)
            max_days = max(1, int(os.environ.get("ARCHON_SESSION_MAX_DAYS", "30") or "30"))
            expires_at = now + datetime.timedelta(days=max_days)
            cur.execute("""
                INSERT INTO user_sessions (token, user_id, expires_at, last_seen_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (token_hash, user["id"], expires_at.isoformat(), now_iso, ip_address, user_agent))
            conn.commit()

            return {
                "token": token,
                "expires_at": expires_at.isoformat(),
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "email": user["email"],
                    "role": user["role"]
                }
            }

    def verify_session(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        token = token.strip()
        tok_hash = _hash_session_token(token)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now = now_dt.isoformat()

        with _get_db() as conn:
            cur = conn.cursor()
            # KRITISCH: frueher wurde auch der Klartext-Token akzeptiert
            # (`WHERE s.token IN (hash, raw)`). Wer die DB schreiben kann,
            # konnte einen Admin-Session-Eintrag mit bekanntem Klartext-Token
            # einfügen. Nur noch den Hash akzeptieren.
            cur.execute("""
                SELECT s.token AS stored_token, s.last_seen_at, u.id, u.username, u.display_name, u.email, u.role, u.is_active, s.expires_at
                FROM user_sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.token = ? AND s.expires_at > ?
            """, (tok_hash, now))
            row = cur.fetchone()
            if not row or not row["is_active"]:
                return None

            idle_hours = int(os.environ.get("ARCHON_SESSION_IDLE_HOURS", "72") or "0")
            if idle_hours > 0 and row["last_seen_at"]:
                try:
                    last_dt = datetime.datetime.fromisoformat(str(row["last_seen_at"]))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                    if (now_dt - last_dt).total_seconds() > idle_hours * 3600:
                        cur.execute("DELETE FROM user_sessions WHERE token = ?", (row["stored_token"],))
                        conn.commit()
                        return None
                except ValueError as exc:
                    logger.error(f"verify_session: ungueltiges last_seen_at-Format, Session bleibt aktiv: {exc}")

            try:
                cur.execute("UPDATE user_sessions SET last_seen_at = ? WHERE token = ?", (now, row["stored_token"]))
                conn.commit()
            except Exception as exc:
                logger.error(f"verify_session: last_seen_at-Update fehlgeschlagen (Session-Verlauf wird nicht verlaengert): {exc}")

            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "email": row["email"],
                "role": row["role"],
                "permissions": self.get_permissions_for_role(row["role"])
            }

    def get_fallback_admin(self) -> Dict[str, Any]:
        """Liefert das Standard-Adminprofil für lokale Desktop-Sitzungen (Zero-Disruption)."""
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, username, display_name, email, role FROM users WHERE role = 'admin' LIMIT 1")
            row = cur.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "email": row["email"],
                    "role": "admin",
                    "permissions": self.get_permissions_for_role("admin"),
                    "is_fallback": True
                }
        return {
            "id": "usr_admin_default",
            "username": "admin",
            "display_name": "Michael Keller",
            "email": "michael@archon.local",
            "role": "admin",
            "permissions": self.get_permissions_for_role("admin"),
            "is_fallback": True
        }

    def logout(self, token: str) -> bool:
        if not token:
            return False
        tok = token.strip()
        tok_hash = _hash_session_token(tok)
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_sessions WHERE token IN (?, ?)", (tok_hash, tok))
            conn.commit()
            return cur.rowcount > 0

    def list_users(self) -> List[Dict[str, Any]]:
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, username, display_name, email, role, is_active, created_at, last_login 
                FROM users ORDER BY created_at ASC
            """)
            return [
                {
                    "id": r["id"],
                    "username": r["username"],
                    "display_name": r["display_name"],
                    "email": r["email"],
                    "role": r["role"],
                    "is_active": bool(r["is_active"]),
                    "created_at": r["created_at"],
                    "last_login": r["last_login"]
                }
                for r in cur.fetchall()
            ]

    def update_user(
        self,
        user_id: str,
        role: Optional[str] = None,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Dict[str, Any]:
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, role, is_active FROM users WHERE id = ?", (user_id,))
            target = cur.fetchone()
            if not target:
                raise ValueError("Benutzer nicht gefunden.")

            # Schutz: Letzten Admin nicht degradieren oder deaktivieren
            if target["role"] == "admin":
                if (role and role != "admin") or (is_active is False):
                    cur.execute("SELECT count(*) as count FROM users WHERE role = 'admin' AND is_active = 1")
                    admin_count = cur.fetchone()["count"]
                    if admin_count <= 1:
                        raise ValueError("Der letzte verbleibende Administrator kann weder deaktiviert noch herabgestuft werden.")

            updates = []
            params = []
            if role and role in ("admin", "operator", "viewer"):
                updates.append("role = ?")
                params.append(role)
            if display_name is not None:
                updates.append("display_name = ?")
                params.append(display_name.strip())
            if email is not None:
                updates.append("email = ?")
                params.append(email.strip().lower())
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)

            if updates:
                params.append(user_id)
                cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
                conn.commit()

        return self.get_user_by_id(user_id)

    def verify_password(self, username: str, password: str) -> bool:
        """Prüft ein Passwort, ohne eine Session anzulegen."""
        username = (username or "").strip().lower()
        if not username or not password:
            return False
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, password_hash, salt, is_active FROM users WHERE username = ?", (username,))
            user = cur.fetchone()
            if not user or not user["is_active"]:
                return False
            ok, needs_upgrade = _verify_password_hash(password, user["password_hash"], user["salt"])
            if ok and needs_upgrade:
                up_hash, up_salt = _hash_password(password)
                cur.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (up_hash, up_salt, user["id"]))
                conn.commit()
            return ok

    def change_password(self, user_id: str, new_password: str) -> bool:
        if len(new_password or "") < 8:
            raise ValueError("Das neue Passwort muss mindestens 8 Zeichen lang sein.")
        pwd_hash, salt = _hash_password(new_password)
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (pwd_hash, salt, user_id))
            updated = cur.rowcount
            # Alle bestehenden Sessions dieses Nutzers invalidieren
            cur.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
            return updated > 0

    def delete_user(self, user_id: str) -> bool:
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT role FROM users WHERE id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Benutzer nicht gefunden.")
            if row["role"] == "admin":
                cur.execute("SELECT count(*) as count FROM users WHERE role = 'admin'")
                if cur.fetchone()["count"] <= 1:
                    raise ValueError("Der letzte Administrator kann nicht gelöscht werden.")

            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, username, display_name, email, role, is_active, created_at, last_login 
                FROM users WHERE id = ?
            """, (user_id,))
            r = cur.fetchone()
            if not r:
                return None
            return {
                "id": r["id"],
                "username": r["username"],
                "display_name": r["display_name"],
                "email": r["email"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
                "last_login": r["last_login"],
                "permissions": self.get_permissions_for_role(r["role"])
            }

    @staticmethod
    def get_permissions_for_role(role: str) -> Dict[str, bool]:
        role = (role or "viewer").lower().strip()
        if role == "admin":
            return {
                "can_view": True,
                "can_edit_tasks": True,
                "can_execute_agents": True,
                "can_manage_crm": True,
                "can_manage_finance": True,
                "can_manage_settings": True,
                "can_manage_users": True,
                "can_manage_plugins": True,
                "can_view_audit_logs": True
            }
        elif role == "operator":
            return {
                "can_view": True,
                "can_edit_tasks": True,
                "can_execute_agents": True,
                "can_manage_crm": True,
                "can_manage_finance": True,
                "can_manage_settings": False,
                "can_manage_users": False,
                "can_manage_plugins": False,
                "can_view_audit_logs": True
            }
        else:  # viewer
            return {
                "can_view": True,
                "can_edit_tasks": False,
                "can_execute_agents": False,
                "can_manage_crm": False,
                "can_manage_finance": False,
                "can_manage_settings": False,
                "can_manage_users": False,
                "can_manage_plugins": False,
                "can_view_audit_logs": True
            }


# Globaler Singleton
auth_service = AuthService()
