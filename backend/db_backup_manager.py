"""
backend/db_backup_manager.py
Automatisches SQLite Online-Backup & WAL-Checkpointing (Pillar 4: Desaster-Recovery).
Führt periodisch PRAGMA wal_checkpoint(TRUNCATE) durch und sichert
die Datenbanken komprimiert im Ringpuffer (.hermes/backups/db/) mit konfigurierbarer Rotation.
"""

import os
import sys
import gzip
import sqlite3
import datetime
import shutil
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "backups", "db")
DB_TARGETS = [
    os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db"),
    os.path.join(WORKSPACE_DIR, "data", "kanban.db") if os.path.exists(os.path.join(WORKSPACE_DIR, "data", "kanban.db")) else os.path.expanduser("~/.hermes/kanban.db"),
    os.path.join(WORKSPACE_DIR, "data", "state.db") if os.path.exists(os.path.join(WORKSPACE_DIR, "data", "state.db")) else os.path.expanduser("~/.hermes/state.db")
]

class DBBackupManager:
    def __init__(self, backup_dir: str = BACKUP_DIR):
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    def checkpoint_and_backup(self, keep_days: Optional[int] = None) -> Dict[str, Any]:
        """Führt WAL-Truncate durch und sichert jede existierende SQLite-Datenbank komprimiert ab."""
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("fleet_and_hygiene")
            if keep_days is None:
                keep_days = int(cfg.get("db_backup_keep_days", 7))
        except Exception:
            if keep_days is None:
                keep_days = 7

        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backed_up = []

        for db_path in DB_TARGETS:
            if not os.path.exists(db_path):
                continue

            db_name = os.path.basename(db_path)
            try:
                conn = sqlite3.connect(db_path, timeout=10.0)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                conn.close()
            except Exception as e:
                print(f"[DBBackupManager] Checkpoint notice for {db_name}: {e}", file=sys.stderr)

            backup_file = os.path.join(self.backup_dir, f"{db_name}_{now_str}.db.gz")
            try:
                with open(db_path, "rb") as f_in:
                    with gzip.open(backup_file, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                backed_up.append({
                    "db_name": db_name,
                    "backup_file": backup_file,
                    "size_bytes": os.path.getsize(backup_file)
                })
            except Exception as e:
                print(f"[DBBackupManager] Backup error for {db_name}: {e}", file=sys.stderr)

        self._rotate_backups(keep_days=keep_days)

        return {
            "status": "success",
            "timestamp": now_str,
            "keep_days": keep_days,
            "backup_dir": self.backup_dir,
            "backed_up_count": len(backed_up),
            "backups": backed_up
        }

    def _rotate_backups(self, keep_days: int = 7):
        cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
        try:
            for f in os.listdir(self.backup_dir):
                if f.endswith(".gz"):
                    f_path = os.path.join(self.backup_dir, f)
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f_path))
                    if mtime < cutoff:
                        os.remove(f_path)
        except Exception:
            pass

    def list_backups(self) -> List[Dict[str, Any]]:
        res = []
        try:
            for f in sorted(os.listdir(self.backup_dir), reverse=True):
                if f.endswith(".gz"):
                    f_path = os.path.join(self.backup_dir, f)
                    res.append({
                        "file_name": f,
                        "size_bytes": os.path.getsize(f_path),
                        "created_at": datetime.datetime.fromtimestamp(os.path.getmtime(f_path)).isoformat()
                    })
        except Exception:
            pass
        return res

db_backup_manager = DBBackupManager()
