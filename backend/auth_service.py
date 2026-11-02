"""
backend/auth_service.py
Meilenstein 4: Multi-User-Architektur & Rollenbasierte Zugriffskontrolle (RBAC).
Verwaltet Benutzer, Rollen (admin, operator, viewer), PBKDF2-verschlüsselte Kennwörter
und sichere Session-Tokens mit Zero-Disruption für lokale Entwicklungs-Workflows.
"""

import os
import sys
import uuid
import hmac
import hashlib
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_password(password: str, salt: str = None) -> tuple:
    if not salt:
        salt = uuid.uuid4().hex
    # 100.000 Runden PBKDF2-HMAC-SHA256 (NIST / BSI konform)
    pwd_bytes = password.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    pwd_hash = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, 100000).hex()
    return pwd_hash, salt


class AuthService:
    def __init__(self):
        self._init_tables()
        self._seed_default_admin()

    @staticmethod
    def is_auth_enabled() -> bool:
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
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        s = json.load(f)
                        if isinstance(s, dict) and "auth" in s:
                            return bool(s.get("auth", {}).get("enabled", False))
                except Exception:
                    pass
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
                    ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def _seed_default_admin(self):
        """Erstellt den initialen Haupt-Administrator (Michael Keller), falls noch kein Admin existiert."""
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as count FROM users WHERE role = 'admin'")
            row = cur.fetchone()
            if row and row["count"] == 0:
                pwd_hash, salt = _hash_password("archon2026")
                admin_id = f"usr_{uuid.uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO users (id, username, display_name, email, password_hash, salt, role, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, 'admin', 1)
                """, (admin_id, "admin", "Michael Keller", "michael@archon.local", pwd_hash, salt))
                conn.commit()

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
        if len(password or "") < 6:
            raise ValueError("Das Passwort muss mindestens 6 Zeichen lang sein.")

        role = role.lower().strip()
        if role not in ("admin", "operator", "viewer"):
            role = "operator"

        display_name = (display_name or "").strip() or username.capitalize()
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
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, username, display_name, email, password_hash, salt, role, is_active 
                FROM users WHERE username = ?
            """, (username,))
            user = cur.fetchone()

            if not user:
                return None
            if not user["is_active"]:
                raise PermissionError("Dieses Benutzerkonto ist deaktiviert.")

            check_hash, _ = _hash_password(password, user["salt"])
            if not hmac.compare_digest(check_hash, user["password_hash"]):
                return None

            # Login-Zeitstempel aktualisieren
            now = datetime.datetime.now(datetime.timezone.utc)
            cur.execute("UPDATE users SET last_login = ? WHERE id = ?", (now.isoformat(), user["id"]))

            # Session anlegen (30 Tage Gültigkeit)
            token = f"tok_{uuid.uuid4().hex}_{uuid.uuid4().hex[:12]}"
            expires_at = now + datetime.timedelta(days=30)
            cur.execute("""
                INSERT INTO user_sessions (token, user_id, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            """, (token, user["id"], expires_at.isoformat(), ip_address, user_agent))
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
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT u.id, u.username, u.display_name, u.email, u.role, u.is_active, s.expires_at
                FROM user_sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.token = ? AND s.expires_at > ?
            """, (token, now))
            row = cur.fetchone()
            if not row or not row["is_active"]:
                return None

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
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_sessions WHERE token = ?", (token.strip(),))
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

    def change_password(self, user_id: str, new_password: str) -> bool:
        if len(new_password or "") < 6:
            raise ValueError("Das neue Passwort muss mindestens 6 Zeichen lang sein.")
        pwd_hash, salt = _hash_password(new_password)
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (pwd_hash, salt, user_id))
            # Alle bestehenden Sessions dieses Nutzers invalidieren
            cur.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

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
