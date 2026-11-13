"""
backend/snapshot_manager.py
Atomares Datei-Snapshotting mit 1-Klick-Rollback (Pillar 4 & 6).
Vor jedem Schreib- oder Patch-Vorgang wird ein Backup der Originaldatei
in einem lokalen Ringpuffer (.hermes/snapshots/) hinterlegt.
Ermöglicht sofortiges Undo bei fehlerhaften Änderungen.
"""

import os
import sys
import gzip
import json
import sqlite3
import datetime
import shutil
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "snapshots")
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class SnapshotManager:
    def __init__(self, snapshots_dir: str = SNAPSHOTS_DIR, db_path: str = DB_PATH):
        self.snapshots_dir = snapshots_dir
        self.db_path = db_path
        os.makedirs(self.snapshots_dir, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_snapshots (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    compressed_path TEXT NOT NULL,
                    file_size INTEGER,
                    reason TEXT,
                    agent_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    restored_at TIMESTAMP
                )
            """)
            conn.commit()

    def create_snapshot(self, target_file_path: str, reason: str = "pre_write", agent_id: str = "hermes-coder") -> Optional[str]:
        """Sichert eine bestehende Datei komprimiert im Ringpuffer ab."""
        max_snapshots = 50
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("time_travel_snapshots")
            if not cfg.get("auto_pre_write_snapshots", True):
                return None
            max_snapshots = int(cfg.get("max_snapshots", 50))
        except Exception:
            pass

        abs_path = os.path.abspath(target_file_path)
        if not os.path.exists(abs_path):
            return None

        snap_id = f"snap-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        comp_file = os.path.join(self.snapshots_dir, f"{snap_id}.gz")

        try:
            with open(abs_path, "rb") as f_in:
                data = f_in.read()
            with gzip.open(comp_file, "wb") as f_out:
                f_out.write(data)

            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO file_snapshots (id, file_path, compressed_path, file_size, reason, agent_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (snap_id, abs_path, comp_file, len(data), reason, agent_id))
                # Ringpuffer-Bereinigung nach max_snapshots
                cur = conn.cursor()
                cur.execute("SELECT id, compressed_path FROM file_snapshots ORDER BY created_at DESC LIMIT -1 OFFSET ?", (max_snapshots,))
                old_rows = cur.fetchall()
                for r in old_rows:
                    try:
                        if os.path.exists(r["compressed_path"]):
                            os.remove(r["compressed_path"])
                    except Exception:
                        pass
                    conn.execute("DELETE FROM file_snapshots WHERE id = ?", (r["id"],))
                conn.commit()
            return snap_id
        except Exception as e:
            print(f"[SnapshotManager] Fehler beim Erstellen des Snapshots: {e}", file=sys.stderr)
            return None

    def restore_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """Stellt den Zustand der Datei vor der Änderung exakt wieder her (Rollback)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM file_snapshots WHERE id = ?", (snapshot_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": f"Snapshot {snapshot_id} nicht gefunden."}

            item = dict(row)
            comp_file = item["compressed_path"]
            target_path = item["file_path"]

            if not os.path.exists(comp_file):
                return {"status": "error", "message": f"Archivdatei {comp_file} existiert nicht."}

            try:
                with gzip.open(comp_file, "rb") as f_in:
                    data = f_in.read()
                
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "wb") as f_out:
                    f_out.write(data)

                conn.execute("UPDATE file_snapshots SET restored_at = CURRENT_TIMESTAMP WHERE id = ?", (snapshot_id,))
                conn.commit()

                return {
                    "status": "success",
                    "snapshot_id": snapshot_id,
                    "restored_file": target_path,
                    "bytes_restored": len(data),
                    "message": f"Datei {os.path.basename(target_path)} erfolgreich auf Stand vor der Agenten-Änderung zurückgesetzt."
                }
            except Exception as e:
                return {"status": "error", "message": f"Rollback fehlgeschlagen: {e}"}

    def list_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM file_snapshots ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

snapshot_manager = SnapshotManager()
