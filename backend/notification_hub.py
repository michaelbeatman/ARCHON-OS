"""
backend/notification_hub.py
Zentraler Multi-Channel Notification Hub für Archon OS (Pillar 3 & 6).
Routet Systemereignisse nach Schweregrad:
- INFO: Nur UI-Toast / Dashboard-Feed
- WARNING: Dashboard-Feed + Audit-Log
- CRITICAL: Sofortiger Telegram-Push an den Benutzer mit Aktionshinweis
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class NotificationHub:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def dispatch_notification(
        self,
        title: str,
        message: str,
        severity: str = "INFO",
        category: str = "system",
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Verteilt eine Benachrichtigung basierend auf ihrer Dringlichkeit."""
        sev = severity.upper().strip()
        dispatched_channels = ["ui_feed"]

        # Maskiere sensible Daten in der Nachricht
        try:
            from backend.secret_masker import mask_sensitive_text
            clean_msg, _ = mask_sensitive_text(message)
        except Exception:
            clean_msg = message

        # Bei CRITICAL oder schwerem WARNING -> Telegram Push
        if sev == "CRITICAL" or (sev == "WARNING" and "budget" in category.lower()):
            try:
                import telegram_notify
                tg_text = (
                    f"🚨 *[{sev}] {title}*\n\n"
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
                INSERT INTO system_notifications (title, message, severity, category, channels_dispatched, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (title, clean_msg, sev, category, json.dumps(dispatched_channels)))
            conn.commit()
            notif_id = cur.lastrowid

        return {
            "status": "success",
            "notification_id": notif_id,
            "severity": sev,
            "channels": dispatched_channels,
            "title": title
        }

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM system_notifications ORDER BY id DESC LIMIT ?", (limit,))
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["channels"] = json.loads(d["channels_dispatched"])
                except Exception:
                    d["channels"] = []
                rows.append(d)
            return rows

notification_hub = NotificationHub()
