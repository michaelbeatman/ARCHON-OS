"""
backend/notification_hub.py
Zentraler Multi-Channel Notification Hub für Archon OS (Pillar 3 & 6).
Routet Systemereignisse nach Schweregrad und Ruhezeit-Richtlinien:
- INFO: Nur UI-Toast / Dashboard-Feed
- WARNING: Dashboard-Feed + Audit-Log (+ Telegram tagsüber)
- CRITICAL: Sofortiger Telegram-Push an den Benutzer (durchbricht auch Ruhezeiten)
- RUHEZEITEN: Nachts (z. B. 22:00–07:00 Uhr) werden nicht-kritische Telegram-Pings stummgeschaltet
  und für das Morgen-Standup gepuffert.
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class NotificationHub:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        except Exception:
            pass
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'INFO',
                    category TEXT NOT NULL DEFAULT 'system',
                    channels_dispatched TEXT,
                    suppressed_by_quiet_hours INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Sichere Spalten-Migration falls Tabelle bereits existiert
            try:
                conn.execute("ALTER TABLE system_notifications ADD COLUMN suppressed_by_quiet_hours INTEGER DEFAULT 0")
            except Exception:
                pass
            conn.commit()

    def _get_policy(self) -> Dict[str, Any]:
        """Liest die Benachrichtigungs- und Ruhezeit-Einstellungen aus settings.json."""
        default_policy = {
            "enabled": True,
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
            "allow_critical_during_quiet_hours": True,
            "telegram_enabled": True,
            "telegram_min_severity": "WARNING"
        }
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("notification_policy")
            if cfg and isinstance(cfg, dict):
                default_policy.update(cfg)
        except Exception:
            pass
        return default_policy

    def get_policy(self) -> Dict[str, Any]:
        """Gibt die aktuellen Richtlinien zurück."""
        return self._get_policy()

    def update_policy(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Aktualisiert die Benachrichtigungs- und Ruhezeit-Einstellungen persistent."""
        try:
            from backend.autonomy_settings import save_autonomy_settings
            save_autonomy_settings({"notification_policy": updates})
        except Exception as e:
            print(f"[NotificationHub] Fehler beim Speichern der Policy: {e}", file=sys.stderr)
        return self._get_policy()

    def is_in_quiet_hours(self, now: Optional[datetime.datetime] = None) -> bool:
        """Prüft, ob die aktuelle Zeit im konfigurierten Ruhezeit-Intervall liegt."""
        policy = self._get_policy()
        if not policy.get("enabled", True) or not policy.get("quiet_hours_enabled", True):
            return False

        if now is None:
            now = datetime.datetime.now()

        current_time = now.time()
        try:
            s_hour, s_min = map(int, policy.get("quiet_hours_start", "22:00").split(":"))
            e_hour, e_min = map(int, policy.get("quiet_hours_end", "07:00").split(":"))
            start = datetime.time(s_hour, s_min)
            end = datetime.time(e_hour, e_min)
        except Exception:
            start = datetime.time(22, 0)
            end = datetime.time(7, 0)

        if start <= end:
            return start <= current_time <= end
        else:
            # Nachtübergreifend (z. B. 22:00 bis 07:00)
            return current_time >= start or current_time <= end

    def dispatch_notification(
        self,
        title: str,
        message: str,
        severity: str = "INFO",
        category: str = "system",
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Verteilt eine Benachrichtigung basierend auf Dringlichkeit und Ruhezeiten."""
        sev = severity.upper().strip()
        policy = self._get_policy()
        in_quiet = self.is_in_quiet_hours()
        dispatched_channels = ["ui_feed"]
        was_suppressed = False

        # Maskiere sensible Daten in der Nachricht
        try:
            from backend.secret_masker import mask_sensitive_text
            clean_msg, _ = mask_sensitive_text(message)
        except Exception:
            clean_msg = message

        # Telegram-Entscheidung
        tg_allowed = policy.get("telegram_enabled", True)
        if tg_allowed:
            # Relevanz prüfen
            is_critical = (sev == "CRITICAL")
            is_warning = (sev == "WARNING")
            is_budget_warn = (is_warning and "budget" in category.lower())
            
            should_push = is_critical or is_budget_warn or (is_warning and policy.get("telegram_min_severity") == "WARNING")

            if should_push:
                if in_quiet and not (is_critical and policy.get("allow_critical_during_quiet_hours", True)):
                    # Stummgeschaltet wegen Ruhezeit
                    was_suppressed = True
                    dispatched_channels.append("telegram_quiet_suppressed")
                else:
                    try:
                        import telegram_notify
                        icon = "🚨" if is_critical else "⚠️"
                        tg_text = (
                            f"{icon} *[{sev}] {title}*\n\n"
                            f"{clean_msg}\n\n"
                            f"⏰ *Zeitpunkt:* {datetime.datetime.now().strftime('%H:%M:%S')}\n"
                            f"📂 *Kategorie:* {category}"
                        )
                        telegram_notify.send_telegram_message(tg_text)
                        dispatched_channels.append("telegram")
                    except Exception as e:
                        print(f"[NotificationHub] Telegram push error: {e}", file=sys.stderr)

        # In SQLite protokollieren
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_notifications (
                    title, message, severity, category, channels_dispatched, 
                    suppressed_by_quiet_hours, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (title, clean_msg, sev, category, json.dumps(dispatched_channels), 1 if was_suppressed else 0))
            conn.commit()
            notif_id = cur.lastrowid

        return {
            "status": "success",
            "notification_id": notif_id,
            "severity": sev,
            "channels": dispatched_channels,
            "in_quiet_hours": in_quiet,
            "suppressed_by_quiet_hours": was_suppressed,
            "title": title
        }

    def get_suppressed_digest(self, since_hours: int = 12) -> List[Dict[str, Any]]:
        """Liefert während der Ruhezeiten gepufferte Benachrichtigungen (z. B. für das 08:00 Standup)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM system_notifications 
                WHERE suppressed_by_quiet_hours = 1 
                  AND created_at >= datetime('now', ?)
                ORDER BY id ASC
            """, (f"-{since_hours} hours",))
            return [dict(r) for r in cur.fetchall()]

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM system_notifications ORDER BY id DESC LIMIT ?", (limit,))
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["channels_dispatched"] = json.loads(d["channels_dispatched"])
                except Exception:
                    d["channels_dispatched"] = []
                rows.append(d)
            return rows

# Globales Singleton
notification_hub = NotificationHub()

def get_notification_hub() -> NotificationHub:
    return notification_hub

