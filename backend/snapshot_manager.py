"""
backend/snapshot_manager.py
Atomares Datei-Snapshotting mit 1-Klick-Rollback (Pillar 4 & 6).
Vor jedem Schreib- oder Patch-Vorgang wird ein Backup der Originaldatei
in einem lokalen Ringpuffer (.hermes/snapshots/) hinterlegt.
Ermöglicht sofortiges Undo bei fehlerhaften Änderungen.
"""
import logging
_archon_exc_logger = logging.getLogger("snapshot_manager")

import os
import sys
import gzip
import json
import sqlite3
import datetime
import shutil
import tempfile
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "snapshots")
_ClosingConnection: type[sqlite3.Connection] = sqlite3.Connection
try:
    from backend.db_paths import (
        resolve_db as _resolve_db,
        ClosingConnection as _ClosingConnectionFromPaths,
        DB_BUSY_TIMEOUT_MS,
    )
    _ClosingConnection = _ClosingConnectionFromPaths
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_BUSY_TIMEOUT_MS = 5000
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _audit_snapshot_restore(result: Dict[str, Any]) -> Dict[str, Any]:
    """D5/F-08: Snapshot-Restore signiert in die Zentralkette (append-only).

    Fail-closed: der Rollback ist zum Zeitpunkt des Aufrufs bereits entschieden.
    Ein Audit-Fehler darf keine Exception in die laufende DB-Transaktion werfen;
    er wird geloggt und im Result sichtbar gemacht. Protokolliert werden nur
    IDs/Status/Metadaten — kein Dateiinhalt, kein vollstaendiger Pfad.
    """
    restored_file = str(result.get("restored_file") or "")
    payload = {
        "status": str(result.get("status") or ""),
        "snapshot_id": str(result.get("snapshot_id") or ""),
        "file_name": os.path.basename(restored_file) if restored_file else "",
        "bytes_restored": int(result.get("bytes_restored") or 0),
    }
    try:
        from backend.audit_log import chained_audit_log

        event = chained_audit_log.record_event(
            category="snapshot",
            action="snapshot_restored",
            agent_id="system",
            payload=payload,
        )
        result["audit_status"] = "recorded"
        result["audit_event_id"] = event.get("event_id")
    except Exception as exc:
        _archon_exc_logger.error(
            "[snapshot_manager] Audit-Eintrag snapshot_restored fehlgeschlagen: %s", exc
        )
        result["audit_status"] = "error"
        result["audit_error"] = type(exc).__name__
    return result


def _atomic_write_bytes(path: str, data: bytes) -> None:
    """F-017: Temp + fsync + Verify + os.replace + Directory-fsync.

    Bei jedem Fehler bleibt `path` unberührt; die Temp-Datei wird entfernt.
    """
    tdir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tdir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tdir, prefix=".snapshot_restore_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f_out:
            f_out.write(data)
            f_out.flush()
            os.fsync(f_out.fileno())
        # Verifikation VOR dem Austausch: nie eine truncierte Datei einbauen.
        with open(tmp, "rb") as f_chk:
            if f_chk.read() != data:
                raise IOError("snapshot_restore_verify_failed")
        os.replace(tmp, path)
        tmp = ""
        try:
            dir_fd = os.open(tdir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


class SnapshotManager:
    def __init__(self, snapshots_dir: str = SNAPSHOTS_DIR, db_path: str = DB_PATH):
        self.snapshots_dir = snapshots_dir
        self.db_path = db_path
        os.makedirs(self.snapshots_dir, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        # W2: Connection.__exit__ committet, schliesst aber NICHT — mit der
        # ClosingConnection-Factory wird bei jedem Snapshot kein FD mehr
        # geleakt (bei häufigen Snapshots sonst FD-Erschöpfung).
        conn = sqlite3.connect(self.db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, factory=_ClosingConnection)
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
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
        except Exception as _exc:
            _archon_exc_logger.debug("[snapshot_manager] Ignorierte Ausnahme (Z.60): %s", _exc)

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
                    except Exception as _exc:
                        _archon_exc_logger.debug("[snapshot_manager] Ignorierte Ausnahme (Z.89): %s", _exc)
                    conn.execute("DELETE FROM file_snapshots WHERE id = ?", (r["id"],))
                conn.commit()
            return snap_id
        except Exception as e:
            print(f"[SnapshotManager] Fehler beim Erstellen des Snapshots: {e}", file=sys.stderr)
            return None

    def restore_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """Stellt den Zustand der Datei vor der Änderung exakt wieder her (Rollback).

        F-017: Zielpfad-Jail, atomarer Write (Temp+fsync+os.replace),
        pre_restore-Sicherung und Rollback. Ein Fehler vor dem Replace lässt
        das Ziel unberührt; ein Fehler danach wird über die Kopie zurückgerollt.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM file_snapshots WHERE id = ?", (snapshot_id,))
            row = cur.fetchone()
            if not row:
                return _audit_snapshot_restore({
                    "status": "error", "snapshot_id": snapshot_id,
                    "reason": "snapshot_not_found",
                })

            item = dict(row)
            comp_file = item["compressed_path"]
            raw_target = item["file_path"]

            # F-017: file_path kommt ungefiltert aus der DB — Pfad-Jail gegen
            # Workspace (allow_write=True, allow_dirs=False).
            try:
                from utils.path_jail import safe_path_within
                target_path = safe_path_within(
                    raw_target, [WORKSPACE_DIR], allow_write=True, allow_dirs=False
                )
            except Exception as e:
                return _audit_snapshot_restore({
                    "status": "error", "snapshot_id": snapshot_id,
                    "reason": f"path_jail_rejected:{type(e).__name__}",
                    "message": f"Restore-Ziel ausserhalb des Workspace abgelehnt: {raw_target}",
                })

            if not os.path.exists(comp_file):
                return _audit_snapshot_restore({
                    "status": "error", "snapshot_id": snapshot_id,
                    "reason": "archive_missing",
                })

            pre_restore = ""
            target_existed = os.path.exists(target_path)
            replaced = False
            try:
                tdir = os.path.dirname(target_path) or "."
                os.makedirs(tdir, exist_ok=True)

                # Dekomprimieren: ein Lesefehler trifft nur den Puffer, nie das Ziel.
                with gzip.open(comp_file, "rb") as f_in:
                    data = f_in.read()

                # pre_restore-Kopie anlegen (atomar), damit ein Fehler nach dem
                # Replace zurückgerollt werden kann.
                if target_existed:
                    with open(target_path, "rb") as f_cur:
                        original = f_cur.read()
                    pre_fd, pre_restore = tempfile.mkstemp(
                        dir=tdir, prefix=".pre_restore_", suffix=".bak"
                    )
                    os.close(pre_fd)
                    _atomic_write_bytes(pre_restore, original)

                # Atomarer Restore — erst nach erfolgreichem Verify ersetzen.
                _atomic_write_bytes(target_path, data)
                replaced = True

                conn.execute(
                    "UPDATE file_snapshots SET restored_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (snapshot_id,),
                )
                conn.commit()

                return _audit_snapshot_restore({
                    "status": "success",
                    "snapshot_id": snapshot_id,
                    "restored_file": target_path,
                    "bytes_restored": len(data),
                    "message": f"Datei {os.path.basename(target_path)} erfolgreich auf Stand vor der Agenten-Änderung zurückgesetzt."
                })
            except Exception as e:
                # Rollback NUR, wenn der Replace bereits stattgefunden hat.
                if replaced:
                    try:
                        if pre_restore and os.path.exists(pre_restore):
                            with open(pre_restore, "rb") as f_back:
                                _atomic_write_bytes(target_path, f_back.read())
                        elif not target_existed and os.path.exists(target_path):
                            os.unlink(target_path)
                    except Exception as rb_exc:
                        _archon_exc_logger.error(
                            "[snapshot_manager] Rollback nach fehlgeschlagenem Restore nicht moeglich: %s",
                            rb_exc,
                        )
                return _audit_snapshot_restore({
                    "status": "error", "snapshot_id": snapshot_id,
                    "reason": f"rollback_failed:{type(e).__name__}",
                    "message": f"Rollback fehlgeschlagen: {e}",
                })
            finally:
                if pre_restore:
                    try:
                        os.unlink(pre_restore)
                    except OSError:
                        pass

    def list_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM file_snapshots ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

snapshot_manager = SnapshotManager()
