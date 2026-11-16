"""
backend/db_backup_manager.py
Automatisches SQLite Online-Backup & WAL-Checkpointing (Pillar 4: Desaster-Recovery).
Führt periodisch PRAGMA wal_checkpoint(TRUNCATE) durch und sichert
die Datenbanken komprimiert im Ringpuffer (.hermes/backups/db/) mit konfigurierbarer Rotation.
"""

import os
import sys
import glob
import gzip
import sqlite3
import datetime
import shutil
import tempfile
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "backups", "db")


def _resolve_target(filename: str, legacy_subpath: str) -> str:
    try:
        from backend.db_paths import resolve_db
        return resolve_db(filename)
    except Exception:
        ws_path = os.path.join(WORKSPACE_DIR, "data", filename)
        return ws_path if os.path.exists(ws_path) else os.path.expanduser(legacy_subpath)


DB_TARGETS = [
    _resolve_target("agentic_memory.db", "~/.hermes/agentic_memory.db"),
    _resolve_target("kanban.db", "~/.hermes/kanban.db"),
    _resolve_target("state.db", "~/.hermes/state.db"),
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

        # Statische Kern-DBs + alle dynamischen Mandanten-DBs (ERP, Kanban, Contracts, Deals, CRM)
        tenant_dbs = sorted(glob.glob(os.path.join(WORKSPACE_DIR, "data", "tenants", "*", "*.db")))
        seen_paths = set()
        all_targets = []
        for candidate in list(DB_TARGETS) + tenant_dbs:
            norm = os.path.abspath(candidate)
            if norm not in seen_paths and os.path.exists(norm):
                seen_paths.add(norm)
                all_targets.append(norm)

        tenants_prefix = os.path.abspath(os.path.join(WORKSPACE_DIR, "data", "tenants")) + os.sep
        for db_path in all_targets:
            if db_path.startswith(tenants_prefix):
                rel = db_path[len(tenants_prefix):].replace(os.sep, "__")
                db_name = f"tenant_{rel}"
            else:
                db_name = os.path.basename(db_path)

            backup_file = os.path.join(self.backup_dir, f"{db_name}_{now_str}.db.gz")
            tmp_snapshot = None
            try:
                src_conn = sqlite3.connect(db_path, timeout=10.0)
                try:
                    try:
                        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    except Exception as e:
                        print(f"[DBBackupManager] Checkpoint notice for {db_name}: {e}", file=sys.stderr)
                    fd, tmp_snapshot = tempfile.mkstemp(prefix="archon_bkp_", suffix=".db", dir=self.backup_dir)
                    os.close(fd)
                    dst_conn = sqlite3.connect(tmp_snapshot)
                    try:
                        src_conn.backup(dst_conn)
                    finally:
                        dst_conn.close()
                finally:
                    src_conn.close()

                with open(tmp_snapshot, "rb") as f_in:
                    with gzip.open(backup_file, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                backed_up.append({
                    "db_name": db_name,
                    "backup_file": backup_file,
                    "size_bytes": os.path.getsize(backup_file)
                })
            except Exception as e:
                print(f"[DBBackupManager] Backup error for {db_name}: {e}", file=sys.stderr)
            finally:
                if tmp_snapshot and os.path.exists(tmp_snapshot):
                    try:
                        os.unlink(tmp_snapshot)
                    except OSError:
                        pass

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
