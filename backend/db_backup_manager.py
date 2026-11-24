"""
backend/db_backup_manager.py
Automatisches SQLite Online-Backup & WAL-Checkpointing (Pillar 4: Desaster-Recovery).
Führt periodisch PRAGMA wal_checkpoint(TRUNCATE) durch und sichert
die Datenbanken komprimiert im Ringpuffer (.hermes/backups/db/) mit konfigurierbarer Rotation.
"""

import datetime
import glob
import gzip
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

logger = logging.getLogger("archon.db_backup_manager")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import APP_DATA_DIR as _APP_DATA_DIR
except Exception:
    _APP_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
# D03/MED: der Sidecar-Scan bleibt auf produktive Datenverzeichnisse begrenzt.
# D03/HIGH: pb_data/.wal|.shm verwaister Snapshots (data_corrupted/data_temp)
# liegen ausserhalb von APP_DATA_DIR und muessen ebenfalls erfasst werden.
_CLEANUP_ROOTS = (
    _APP_DATA_DIR,
    os.path.join(WORKSPACE_DIR, ".hermes", "backups"),
    os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data"),
)
BACKUP_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "backups", "db")
# D03/HIGH: Tenant-DBs liegen unter APP_DATA_DIR (ARCHON_DATA_DIR), nicht
# zwingend im Workspace — sonst sichert/restore't der Manager ins Leere.
TENANTS_DIR = os.path.join(_APP_DATA_DIR, "tenants")


def _tenant_roots() -> list:
    """D03: APP_DATA_DIR ist kanonisch, WORKSPACE_DIR/data/tenants bleiben
    Legacy-Standorte (Tests/älter Deployments) — beide werden gesichert."""
    roots = [TENANTS_DIR]
    legacy = os.path.join(WORKSPACE_DIR, "data", "tenants")
    if os.path.abspath(legacy) != os.path.abspath(TENANTS_DIR):
        roots.append(legacy)
    return roots
# K2 (Audit 23.11.2026): PocketBase-CRM war in keinem wiederkehrenden Backup.
# Fester Pfad statt resolve_db("data.db") — letzteres würde eine leere DB
# neu anlegen, weil "data.db" nicht in der db_paths-Registry steht.
POCKETBASE_DATA_DIR = os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data")
POCKETBASE_DB_PATH = os.path.join(POCKETBASE_DATA_DIR, "data.db")
# K (dieses Audits): PocketBase legt zusätzliche Daten ab — auxiliary.db und
# storage/**. Ohne diese Artefakte ist ein pb_data-Restore unvollständig.
POCKETBASE_AUX_DB_PATH = os.path.join(POCKETBASE_DATA_DIR, "auxiliary.db")

# SSOT für das Artefakt-Namensmuster. Früher hatte der Restore-Test sein eigenes
# (falsches) Muster und suchte dadurch nie echte Backups. Beide Seiten nutzen
# jetzt diese Konstanten.
BACKUP_FILENAME_TEMPLATE = "{db_name}_{now_str}.db.gz"
BACKUP_GLOB_PATTERN = "{db_name}_*.db.gz"

# Sensible Konfigurationsdateien, die ohne DB-Backup nicht wiederhergestellt
# werden koennten (Settings, HITL-Passkeys, HMAC-Keys, Service-Token).
SECRET_FILES: Dict[str, str] = {
    "settings": os.path.join(WORKSPACE_DIR, "settings.json"),
    "compartment_key": os.path.join(WORKSPACE_DIR, "data", "compartment.key"),
    "warrant_hmac_key": os.path.join(WORKSPACE_DIR, "data", "warrant_hmac.key"),
    "passkey_hitl": os.path.join(WORKSPACE_DIR, "config", "passkey_hitl.json"),
    "archon_service_token": os.path.join(WORKSPACE_DIR, "data", ".archon_service_token"),
    "initial_admin_password": os.path.join(WORKSPACE_DIR, ".archon_initial_admin_password"),
}
_SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.secret\.gz$")

# K1 (Audit 23.11.2026): parallele Restores müssen serialisiert werden.
_RESTORE_LOCK = threading.RLock()
# D03/MED: auch die Sidecar-Bereinigung ist serialisiert (exists()+unlink()).
_SIDECAR_CLEANUP_LOCK = threading.RLock()


def _release_db_guard(conn: Optional[sqlite3.Connection]) -> None:
    """Gibt einen EXCLUSIVE-Guard auf der Ziel-DB idempotent frei (D03/MED)."""
    if conn is None:
        return
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass


def _verify_snapshot(conn: sqlite3.Connection, label: str) -> None:
    """Fail-closed Integritäts-Gate: integrity + quick + foreign_key (D03).

    Wirft bei jeder Abweichung; der Aufrufer lässt die Live-DB unberührt.
    """
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    quick = conn.execute("PRAGMA quick_check").fetchone()
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if not integrity or str(integrity[0]).lower() != "ok":
        raise RuntimeError(f"{label}: Integritätsprüfung fehlgeschlagen: {integrity}")
    if not quick or str(quick[0]).lower() != "ok":
        raise RuntimeError(f"{label}: Quick-Check fehlgeschlagen: {quick}")
    if fk_violations:
        raise RuntimeError(
            f"{label}: {len(fk_violations)} FK-Verletzung(en) — Restore abgelehnt."
        )


def cleanup_orphaned_pocketbase_dbs() -> Dict[str, Any]:
    """D03/HIGH: Forensik-basierte Bereinigung verwaister PocketBase-DBs.

    Nur namentlich bekannte, nachweislich MALFORMED Kopien (``data_corrupted``,
    ``data_temp``) werden entfernt — die produktiven ``data.db``/``auxiliary.db``
    werden nie angefasst, und eine gueltige DB wird nie geloescht (kein stiller
    Datenverlust). Vor dem Entfernen werden Hash und Groesse protokolliert.
    """
    removed: list[str] = []
    kept: list[str] = []
    pb_dir = POCKETBASE_DATA_DIR
    for name in ("data_corrupted.db", "data_temp.db"):
        path = os.path.join(pb_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            probe = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
            try:
                integrity = str(probe.execute("PRAGMA integrity_check").fetchone()[0]).lower()
            finally:
                probe.close()
        except Exception as exc:
            integrity, digest = f"error:{exc}", "unknown"
        if integrity != "ok":
            for victim in [path] + [path + s for s in ("-wal", "-shm", "-journal")]:
                if os.path.isfile(victim):
                    try:
                        os.unlink(victim)
                        removed.append(os.path.basename(victim))
                    except OSError:
                        pass
            logger.info("[DBBackup] Verwaiste PB-Kopie %s entfernt (sha256=%s, integrity=%s)",
                        name, digest[:16], integrity)
        else:
            kept.append(name)
    return {"removed": removed, "kept_valid": kept}


def _gzip_atomic(src_path: str, dst_path: str) -> None:
    """D03/MED: gzip in eine Temp-Datei im Zielverzeichnis, fsync, os.replace.

    Ein Abbruch mitten im Komprimieren hinterliess frueher eine unvollstaendige
    `<name>.db.gz`, die der Restore-Test als gueltiges Backup-Artefakt sah.
    """
    dst_dir = os.path.dirname(dst_path) or "."
    os.makedirs(dst_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".gzip_", suffix=".tmp", dir=dst_dir)
    os.close(fd)
    try:
        with open(tmp_path, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb") as f_out:
                with open(src_path, "rb") as f_in:
                    shutil.copyfileobj(f_in, f_out)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp_path, dst_path)
        try:
            dir_fd = os.open(dst_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def cleanup_orphaned_sidecars(root_dir: Optional[str] = None) -> Dict[str, Any]:
    """Entfernt WAL/SHM/Journal-Sidecars ohne existierende Basis-DB (D03/MED).

    Nur eindeutig verwäiste Artefakte werden gelöscht (Basis fehlt). Sidecars
    aktiver Datenbanken werden nie angefasst. Historische Restore-Artefakte
    wie `.memory.db.restore.<stamp>.tmp-wal` werden damit erfasst.
    """
    roots = [os.path.abspath(root_dir)] if root_dir else [os.path.abspath(r) for r in _CLEANUP_ROOTS]
    removed: list[str] = []
    errors: list[str] = []
    skipped = False
    suffixes = ("-wal", "-shm", "-journal")
    # D03/MED: OS-verwalteter Lock ueber die gesamte Bereinigung. Bei
    # Kontention wird NICHT geloescht (fail-safe) statt in ein fremdes
    # Restore/Writer-Fenster hineinzugreifen.
    os_lock = None
    try:
        from backend.process_lock import try_acquire_loop_lock
        os_lock = try_acquire_loop_lock("sidecar_cleanup", timeout=1.0)
    except Exception as exc:
        errors.append(f"os_lock: {exc}")
    if os_lock is None:
        skipped = True
        logger.warning("[DBBackup] Sidecar-Cleanup uebersprungen: OS-Lock nicht verfuegbar.")
    try:
        if not skipped:
            for root in roots:
                # Rekursiv: Mandanten-DBs liegen unter data/tenants/<tid>/,
                # historische Restore-Artefakte direkt unter data/.
                for dirpath, dirnames, _filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if d not in ("node_modules", "__pycache__")]
                    try:
                        entries = os.listdir(dirpath)
                    except OSError:
                        continue
                    for name in entries:
                        matched = next((s for s in suffixes if name.endswith(s)), None)
                        if not matched:
                            continue
                        base = name[: -len(matched)]
                        if not base:
                            continue
                        victim = os.path.join(dirpath, name)
                        with _SIDECAR_CLEANUP_LOCK:
                            # D03/MED: erneuter Existenz-Check UNMITTELBAR vor
                            # unlink() — sonst kann zwischen exists() und
                            # unlink() eine aktive DB inkl. WAL entstehen.
                            if os.path.exists(os.path.join(dirpath, base)):
                                continue
                            try:
                                os.unlink(victim)
                                removed.append(os.path.relpath(victim, root))
                            except OSError as exc:
                                errors.append(f"{victim}: {exc}")
    finally:
        if os_lock is not None:
            try:
                os_lock.release()
            except Exception:
                pass
    # Lock-DB-Journals haben eine existierende Basis und brauchen einen
    # EXCLUSIVE-Probe (eigener Helper in process_lock).
    try:
        from backend.process_lock import cleanup_stale_lock_journals
        for j in cleanup_stale_lock_journals():
            removed.append(os.path.basename(j))
    except Exception as exc:
        errors.append(f"lock_journals: {exc}")
    return {"removed": removed, "errors": errors, "count": len(removed), "skipped": skipped}


def _audit_backup_restore(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """D5/F-08: Restore signiert in die Zentralkette (append-only).

    Fail-closed: der Restore ist zum Zeitpunkt dieses Aufrufs bereits
    abgeschlossen (oder fehlgeschlagen). Ein Audit-Schreibfehler darf keine
    Exception in die Restore-Transaktion werfen; er wird geloggt und im
    Result-Feld sichtbar gemacht. Nur IDs/Status/Metadaten, keine Inhalte.
    """
    try:
        from backend.audit_log import chained_audit_log

        event = chained_audit_log.record_event(
            category="backup",
            action="backup_restored",
            agent_id=str(metadata.get("agent_id") or "system"),
            payload=metadata,
        )
        return {"audit_status": "recorded", "audit_event_id": event.get("event_id")}
    except Exception as exc:
        logger.error("[DBBackup] Audit-Eintrag backup_restored fehlgeschlagen: %s", exc)
        return {"audit_status": "error", "audit_error": type(exc).__name__}


@contextmanager
def _restore_gate(target: str):
    """C07/Option B: Cross-Prozess-Gate über die gesamte Restore-Phase.

    Der eigentliche SQLite-EXCLUSIVE-Guard darf unter Windows nicht über den
    Dateiaustausch hinweg offen bleiben (Sharing-Violation). Das Gate auf einer
    separaten Lock-DB verhindert zumindest parallele Restores über Prozess-
    grenzen hinweg und wird vom OS bei Prozessende automatisch freigegeben.
    """
    from backend.process_lock import acquire_restore_lock
    lock = acquire_restore_lock(target)
    try:
        yield
    finally:
        lock.release()


def _tenant_secret_files() -> Dict[str, str]:
    """Vault-Keys liegen pro Mandant unter data/tenants/<tid>/compartment.key.

    Vorher wurde nur der globale Key gesichert — ein Restore der Tenant-Vault-
    DB ohne ihren Key machte die AES-GCM-Daten dauerhaft unlesbar.
    """
    out: Dict[str, str] = {}
    try:
        import glob as _glob
        for key_path in _glob.glob(os.path.join(TENANTS_DIR, "*", "compartment.key")):
            tid = os.path.basename(os.path.dirname(key_path))
            out[f"tenant_{tid}_compartment_key"] = key_path
    except Exception:
        pass
    return out


def _within(path: str, root: str) -> bool:
    """Jail-Pruefung: path muss unter root liegen (symlink-aufgeloest)."""
    try:
        real_path = os.path.realpath(path)
        real_root = os.path.realpath(root)
        return os.path.commonpath([real_path, real_root]) == real_root
    except (ValueError, OSError):
        return False


def _tenant_restore_target(db_name: str) -> Optional[str]:
    """`tenant_<tid>__<db>` -> `data/tenants/<tid>/<db>` (mit Jail-Pruefung)."""
    m = re.fullmatch(r"tenant_([A-Za-z0-9_.\-]+)__([A-Za-z0-9_.\-]+)", str(db_name or ""))
    if not m:
        return None
    tid, db_file = m.group(1), m.group(2)
    if tid in (".", "..") or db_file in (".", ".."):
        return None
    target = os.path.abspath(os.path.join(TENANTS_DIR, tid, db_file))
    if not _within(target, TENANTS_DIR):
        return None
    return target


def _resolve_target(filename: str, legacy_subpath: str) -> str:
    try:
        from backend.db_paths import resolve_db
        return resolve_db(filename)
    except Exception:
        ws_path = os.path.join(WORKSPACE_DIR, "data", filename)
        return ws_path if os.path.exists(ws_path) else os.path.expanduser(legacy_subpath)


def _collect_db_targets() -> List[str]:
    targets = [
        _resolve_target("ops.db", "~/.hermes/ops.db"),
        _resolve_target("business.db", "~/.hermes/business.db"),
        _resolve_target("memory.db", "~/.hermes/memory.db"),
        _resolve_target("agentic_memory.db", "~/.hermes/agentic_memory.db"),
        _resolve_target("kanban.db", "~/.hermes/kanban.db"),
        _resolve_target("state.db", "~/.hermes/state.db"),
        _resolve_target("contracts.db", "~/.hermes/contracts.db"),
        _resolve_target("deals.db", "~/.hermes/deals.db"),
        _resolve_target("corporate.db", "~/.hermes/corporate.db"),
    ]
    if os.path.isfile(POCKETBASE_DB_PATH):
        targets.append(POCKETBASE_DB_PATH)
    # PocketBase-owned Zusatz-DB (Auth/Records-Metadaten) gehoert zum
    # Wiederherstellungsumfang. Read-only gesichert (siehe checkpoint_and_backup).
    if os.path.isfile(POCKETBASE_AUX_DB_PATH):
        targets.append(POCKETBASE_AUX_DB_PATH)
    return targets


_INITIAL_DB_TARGETS = _collect_db_targets()
DB_TARGETS = list(_INITIAL_DB_TARGETS)

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

        # D03/HIGH: verwaiste, nachweislich defekte PocketBase-Kopien entfernen.
        pb_cleanup = cleanup_orphaned_pocketbase_dbs()
        if pb_cleanup["removed"]:
            logger.info("[DBBackup] PB-Orphans entfernt: %s", pb_cleanup["removed"])
        # D03/MED: verwaisste Restore-/Lock-Sidecars vor jedem Backup-Sweep
        # aufräumen (auch aus anderen Schreibpfaden stammende Artefakte).
        sweep = cleanup_orphaned_sidecars()
        if sweep["count"]:
            logger.info("[DBBackup] %d verwaisste Sidecars entfernt: %s",
                        sweep["count"], sweep["removed"])

        # Statische Kern-DBs (respektiert Test-Monkeypatches auf DB_TARGETS) + dynamische Mandanten-DBs
        base_targets = list(DB_TARGETS) if DB_TARGETS != _INITIAL_DB_TARGETS else _collect_db_targets()
        tenant_dbs = sorted(
            path for root in _tenant_roots()
            for path in glob.glob(os.path.join(root, "*", "*.db"))
        )
        seen_paths = set()
        all_targets = []
        for candidate in base_targets + tenant_dbs:
            norm = os.path.abspath(candidate)
            if norm not in seen_paths and os.path.exists(norm):
                seen_paths.add(norm)
                all_targets.append(norm)

        tenant_prefixes = [os.path.abspath(root) + os.sep for root in _tenant_roots()]
        for db_path in all_targets:
            if db_path == POCKETBASE_DB_PATH:
                # Eindeutiger Backup-Name, sonst kollidiert er mit anderen data.db.
                db_name = "pb_data.db"
            elif db_path == POCKETBASE_AUX_DB_PATH:
                db_name = "pb_auxiliary.db"
            elif any(db_path.startswith(pref) for pref in tenant_prefixes):
                _pref = next(pref for pref in tenant_prefixes if db_path.startswith(pref))
                rel = db_path[len(_pref):].replace(os.sep, "__")
                db_name = f"tenant_{rel}"
            else:
                db_name = os.path.basename(db_path)

            backup_file = os.path.join(
                self.backup_dir,
                BACKUP_FILENAME_TEMPLATE.format(db_name=db_name, now_str=now_str),
            )
            tmp_snapshot = None
            try:
                if db_path in (POCKETBASE_DB_PATH, POCKETBASE_AUX_DB_PATH):
                    # PocketBase owns schema and WAL of these DBs. Never issue a
                    # write PRAGMA against the live file (D3-H7). A read-only
                    # connection + backup API still sees a consistent snapshot.
                    src_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
                else:
                    src_conn = sqlite3.connect(db_path, timeout=10.0)
                try:
                    # W2: kein wal_checkpoint(TRUNCATE) mehr auf der Live-DB.
                    # Die SQLite-Backup-API unten erzeugt einen konsistenten
                    # Snapshot inkl. WAL; der TRUNCATE war ein schreibender
                    # Eingriff mit SQLITE_BUSY-Risiko für andere Connections.
                    fd, tmp_snapshot = tempfile.mkstemp(prefix="archon_bkp_", suffix=".db", dir=self.backup_dir)
                    os.close(fd)
                    dst_conn = sqlite3.connect(tmp_snapshot)
                    try:
                        src_conn.backup(dst_conn)
                        chk_row = dst_conn.execute("PRAGMA integrity_check(1);").fetchone()
                        if not chk_row or str(chk_row[0]).lower() != "ok":
                            raise RuntimeError(f"Backup-Integritaetspruefung fehlgeschlagen: {chk_row}")
                    finally:
                        dst_conn.close()
                finally:
                    src_conn.close()

                _gzip_atomic(tmp_snapshot, backup_file)
                backed_up.append({
                    "db_name": db_name,
                    "backup_file": backup_file,
                    "size_bytes": os.path.getsize(backup_file),
                    "integrity": "ok",
                })
            except Exception as e:
                print(f"[DBBackupManager] Backup error for {db_name}: {e}", file=sys.stderr)
            finally:
                if tmp_snapshot and os.path.exists(tmp_snapshot):
                    try:
                        os.unlink(tmp_snapshot)
                    except OSError as rm_exc:
                        logger.debug(f"[DBBackupManager] Temp-Snapshot {tmp_snapshot} nicht entfernt: {rm_exc}")

        # PocketBase storage/** (PDF-/Bild-Anhaenge) liegt ausserhalb der DBs
        # und war bisher gar nicht im Backup. Eigenes, eindeutiges Artefakt.
        backed_up.extend(self._backup_pocketbase_storage(now_str))

        # Secret-Dateien gehoeren zum Wiederherstellungs-Umfang: ohne sie
        # hilft das beste DB-Backup nichts (settings/HITL/Token weg).
        backed_up.extend(self._backup_secret_files(now_str))

        self._rotate_backups(keep_days=keep_days)

        return {
            "status": "success",
            "timestamp": now_str,
            "keep_days": keep_days,
            "backup_dir": self.backup_dir,
            "backed_up_count": len(backed_up),
            "backups": backed_up
        }

    def _backup_pocketbase_storage(self, now_str: str) -> List[Dict[str, Any]]:
        """Sichert pocketbase/pb_data/storage/** als eigenes tar.gz-Artefakt.

        Der Name `pb_storage_<stamp>.tar.gz` greift nicht in die bestehenden
        `<db_name>_<stamp>.db.gz`-Namen ein. Fehlt das Verzeichnis (z.B. in
        Tests), wird nichts angelegt.
        """
        secured: List[Dict[str, Any]] = []
        # Pfad zur Laufzeit aus WORKSPACE_DIR ableiten (Tests monkeypatchen
        # diese Konstante auf ein tmp_path).
        storage_dir = os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data", "storage")
        if not os.path.isdir(storage_dir):
            return secured
        backup_file = os.path.join(self.backup_dir, f"pb_storage_{now_str}.tar.gz")
        tmp_archive = None
        try:
            fd, tmp_archive = tempfile.mkstemp(
                prefix="archon_pb_storage_", suffix=".tar.gz", dir=self.backup_dir
            )
            os.close(fd)
            with tarfile.open(tmp_archive, "w:gz") as tar:
                tar.add(storage_dir, arcname="storage")
            os.replace(tmp_archive, backup_file)
            secured.append({
                "db_name": "pb_storage",
                "kind": "pocketbase_storage",
                "source_path": storage_dir,
                "backup_file": backup_file,
                "size_bytes": os.path.getsize(backup_file),
                "integrity": "ok",
            })
        except Exception as exc:
            print(f"[DBBackupManager] PocketBase-Storage-Backup fehlgeschlagen: {exc}", file=sys.stderr)
            for stale in (tmp_archive, backup_file):
                if stale and os.path.exists(stale):
                    try:
                        os.unlink(stale)
                    except OSError:
                        pass
        return secured

    def _backup_secret_files(self, now_str: str) -> List[Dict[str, Any]]:
        """Sichert settings.json, compartment.key, warrant_hmac.key,
        passkey_hitl.json und .archon_service_token komprimiert im Ringpuffer.
        """
        secured: List[Dict[str, Any]] = []
        all_secrets = {**SECRET_FILES, **_tenant_secret_files()}
        for logical_name, src_path in all_secrets.items():
            if not os.path.isfile(src_path):
                continue
            backup_file = os.path.join(self.backup_dir, f"{logical_name}_{now_str}.secret.gz")
            try:
                _gzip_atomic(src_path, backup_file)
                secured.append({
                    "db_name": logical_name,
                    "kind": "secret",
                    "source_path": src_path,
                    "backup_file": backup_file,
                    "size_bytes": os.path.getsize(backup_file),
                    "integrity": "ok",
                })
            except Exception as exc:
                print(f"[DBBackupManager] Secret-Backup {logical_name} fehlgeschlagen: {exc}", file=sys.stderr)
                try:
                    if os.path.exists(backup_file):
                        os.unlink(backup_file)
                except OSError:
                    pass
        return secured

    def _rotate_backups(self, keep_days: int = 7):
        cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
        try:
            for f in os.listdir(self.backup_dir):
                if f.endswith(".gz"):
                    f_path = os.path.join(self.backup_dir, f)
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f_path))
                    if mtime < cutoff:
                        os.remove(f_path)
        except OSError as exc:
            logger.warning(f"[DBBackupManager] Backup-Rotation fehlgeschlagen: {exc}")

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
        except OSError as exc:
            logger.warning(f"[DBBackupManager] Backup-Liste nicht lesbar: {exc}")
        return res

    def restore_backup(
        self,
        file_name: str,
        target_path: Optional[str] = None,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Stellt ein komprimiertes Backup wieder her (openssl-artig sicher).

        Vorher gab es nur Backups, aber KEINE Restore-Funktion — ein Backup
        war damit ein Versprechen, keine Sicherheit. Ablauf:
        Datei-Jail -> Dekompression -> PRAGMA integrity_check -> atomic replace.
        """
        name = os.path.basename(str(file_name or ""))
        if not name.endswith(".db.gz") or not re.fullmatch(r"[A-Za-z0-9_.\-]+\.db\.gz", name):
            raise ValueError("Ungueltiger Backup-Dateiname.")
        src = os.path.join(self.backup_dir, name)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"Backup '{name}' nicht gefunden.")

        if target_path is None:
            # Format: <db_name>_YYYYmmdd_HHMMSS.db.gz
            stem = name[:-len(".db.gz")]
            db_name = re.sub(r"_\d{8}_\d{6}$", "", stem)
            # Tenant-Backups: tenant_<tid>__<db> -> data/tenants/<tid>/<db>.
            # Vorher wurde daraus falsch data/tenant_<tid>__<db>.
            tenant_target = _tenant_restore_target(db_name)
            if tenant_target is not None:
                target_path = tenant_target
            elif db_name == "pb_data.db":
                target_path = POCKETBASE_DB_PATH
            elif db_name == "pb_auxiliary.db":
                target_path = POCKETBASE_AUX_DB_PATH
            else:
                candidates = {os.path.abspath(p): p for p in DB_TARGETS}
                target_path = next((p for candidate, p in candidates.items()
                                    if os.path.basename(candidate) == db_name), None)
                if target_path is None:
                    target_path = os.path.join(WORKSPACE_DIR, "data", db_name)
        target = os.path.abspath(target_path)
        # D03/MED: bei ARCHON_DATA_DIR ausserhalb des Workspace liegen die
        # korrekten Tenant-Ziele unter APP_DATA_DIR — vorher fail-closed, aber
        # funktional gebrochen. Jail = APP_DATA_DIR ∪ WORKSPACE_DIR.
        if not (_within(target, WORKSPACE_DIR) or _within(target, _APP_DATA_DIR)):
            raise ValueError(
                f"Restore-Ziel weder unter APP_DATA_DIR noch im Workspace: {target}"
            )

        # D5/F-08: genau ein signiertes Event pro Restore-Versuch. `result`
        # bleibt None, wenn vor der Integritätsprüfung abgebrochen wurde.
        result: Optional[Dict[str, Any]] = None
        audit_status = "failed"
        audit_meta: Dict[str, Any] = {
            "source_kind": "db_backup",
            "backup": name,
            "target": target,
            "integrity": "unknown",
            "restored": False,
            "dry_run": bool(dry_run),
            "rollback_ok": None,
        }
        # D03/MED: auch im Restore-Pfad verwaisste Sidecars einsammeln.
        sweep = cleanup_orphaned_sidecars()
        if sweep["count"]:
            logger.info("[DBBackup] %d verwaisste Sidecars entfernt: %s",
                        sweep["count"], sweep["removed"])

        target_dir = os.path.dirname(target)
        if not dry_run:
            os.makedirs(target_dir, exist_ok=True)
        # D03/MED: `os.replace()` ist nur innerhalb desselben Dateisystems
        # atomar. Für echte Restores liegt das Tempfile deshalb NEBEN dem Ziel
        # und nicht im (eventuell anders gemounteten) Backup-Verzeichnis.
        tmp_dir = target_dir if not dry_run else self.backup_dir
        with tempfile.NamedTemporaryFile(
            dir=tmp_dir, prefix=".restore_", suffix=".tmp.db", delete=False
        ) as tmp:
            tmp_path = tmp.name
        try:
            with gzip.open(src, "rb") as fin, open(tmp_path, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            # C / F-015: Fail-closed VOR dem Austausch der Produktionsdatei.
            # integrity_check + quick_check + foreign_key_check (eine SSOT).
            conn = sqlite3.connect(tmp_path)
            try:
                _verify_snapshot(conn, "Backup-Snapshot")
            finally:
                conn.close()
            result = {
                "restored": not dry_run,
                "backup": name,
                "target": target,
                "integrity": "ok",
                "rollback_ok": None,  # None = kein Rollback noetig
            }
            if dry_run:
                audit_status = "dry_run"
                return result
            with _RESTORE_LOCK, _restore_gate(target):
                # K1: Fail-Closed statt Split-Brain. Ein EXCLUSIVE-Lock bricht
                # ab, wenn gerade andere Schreiber auf der Zieldatenbank aktiv
                # sind — dann wird der Restore abgelehnt (Stattdessen vorher
                # in den Drain-Modus gehen). Ein stilles Weiterspielen auf der
                # ausgetauschten Datei erzeugte früher zwei konkurrierende Inodes.
                guard = None
                pre_path: Optional[str] = None
                try:
                    if os.path.exists(target):
                        # 1) Konsistente pre_restore-Kopie über die Backup-API,
                        #    noch OHNE Schreib-Lock. shutil.copy2 verlor bei
                        #    WAL-DBs die letzten Commits. Read-first vermeidet
                        #    einen Lock-Konflikt bei DBs ohne WAL-Modus.
                        _stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        pre_path = target + f".pre_restore.{_stamp}"
                        src_ro = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=2.0)
                        try:
                            with sqlite3.connect(pre_path, timeout=10.0) as pre_conn:
                                src_ro.backup(pre_conn)
                        finally:
                            src_ro.close()
                        result["pre_restore"] = pre_path
                        # 2) Erst danach weitere Schreiber blockieren.
                        guard = sqlite3.connect(target, timeout=2.0, isolation_level=None)
                        guard.execute("BEGIN EXCLUSIVE")
                except sqlite3.Error as exc:
                    _release_db_guard(guard)
                    guard = None
                    raise RuntimeError(
                        f"Restore abgelehnt: Zieldatenbank nicht verfügbar ({exc}). "
                        "Erst Hintergrund-Loops/Agenten in den Drain-Modus schicken."
                    ) from exc

                try:
                    # Letzte, fail-closed Kontrolle des Snapshots unmittelbar
                    # vor dem Austausch (D03): kein FK-inkonsistentes oder
                    # beschädigtes Backup darf den Produktionspfad erreichen.
                    recheck = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True, timeout=5.0)
                    try:
                        _verify_snapshot(recheck, "Restore-Snapshot (pre-replace)")
                    finally:
                        recheck.close()

                    for suffix in ("-wal", "-shm", "-journal"):
                        sidecar = target + suffix
                        if os.path.exists(sidecar):
                            try:
                                os.remove(sidecar)
                            except OSError as exc:
                                logger.warning("[DBBackup] Sidecar %s nicht entfernbar: %s", sidecar, exc)

                    # D03/MED: Auf POSIX (Linux) bleibt der EXCLUSIVE-Guard bis
                    # NACH os.replace() offen. Damit kann kein Writer im
                    # frueheren Fenster zwischen Guard-Release und Replace die
                    # alte Inode oeffnen und danach in die verworfene Datei
                    # schreiben. Windows verweigert os.replace() auf eine noch
                    # geoeffnete Datei (Sharing-Violation); dort wird der Guard
                    # vorher freigegeben und das Restrisiko ueber das
                    # Cross-Prozess-Gate + Cache-Invalidierung (siehe unten)
                    # abgedeckt und im Result ehrlich ausgewiesen.
                    if os.name == "nt":
                        result["guard_held_through_replace"] = False
                        logger.warning(
                            "[DBBackup] Windows: EXCLUSIVE-Guard vor os.replace() "
                            "freigegeben (Sharing-Violation). Schutz: Cross-Prozess-Gate "
                            "+ Cache-Invalidierung; minimales Restfenster bleibt."
                        )
                        _release_db_guard(guard)
                        guard = None
                    else:
                        result["guard_held_through_replace"] = True
                    os.replace(tmp_path, target)
                    _release_db_guard(guard)
                    guard = None
                finally:
                    _release_db_guard(guard)

                # Post-Condition: die restaurierte Datei muss lesbar und
                # integr sein. Schlägt sie fehl, wird die pre_restore-Kopie
                # unter dem noch gehaltenen Gate zurückgespielt. Damit bleibt
                # nie eine defekte DB am Produktionspfad liegen (Audit C).
                verify_error: Optional[BaseException] = None
                try:
                    verify = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
                    try:
                        # D03: die Post-Condition umfasst ausdrücklich den
                        # FK-Check — quick_check allein erkennt relationale
                        # Korruption nicht.
                        _verify_snapshot(verify, "Restore-Ziel (post-replace)")
                    finally:
                        verify.close()
                    result["verified"] = True
                except (sqlite3.Error, RuntimeError) as exc:
                    verify_error = exc
                    result["verified"] = False

                if verify_error is not None:
                    result["rollback_ok"] = False
                    if pre_path and os.path.isfile(pre_path):
                        try:
                            for suffix in ("-wal", "-shm", "-journal"):
                                sidecar = target + suffix
                                if os.path.exists(sidecar):
                                    try:
                                        os.remove(sidecar)
                                    except OSError as sc_exc:
                                        logger.warning("[DBBackup] Rollback-Sidecar %s nicht entfernbar: %s", sidecar, sc_exc)
                            os.replace(pre_path, target)
                            result["rollback_ok"] = True
                        except OSError as rb_exc:
                            logger.error("[DBBackup] Rollback von %s fehlgeschlagen: %s", pre_path, rb_exc)
                    raise RuntimeError(
                        f"Restore-Verifikation fehlgeschlagen: {verify_error}. "
                        f"Rollback {'erfolgreich' if result['rollback_ok'] else 'FEHLGESCHLAGEN'}."
                    ) from verify_error

                # Directory-fsync: ohne ihn kann der Rename nach Stromausfall
                # im Dateisystem-Journal verloren gehen.
                try:
                    dir_fd = os.open(os.path.dirname(target), os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except OSError as exc:
                    logger.debug("[DBBackup] Directory-fsync nicht verfügbar: %s", exc)

                # Der gecachte Pragma-Status gehört zur alten Datei. Ohne Reset
                # läuft die restaurierte DB ohne WAL weiter.
                try:
                    from backend.db_paths import _DB_PRAGMA_INITIALIZED
                    _DB_PRAGMA_INITIALIZED.discard(target)
                except Exception:
                    pass

                # I (dieses Audits): archon.core.state_db merkt sich pro
                # Prozesslebensdauer, bei welchen Dateien journal_mode=WAL
                # bereits gesetzt wurde. Nach einem Restore zeigt der Cache
                # auf die alte Inode. Vorsichtiger Inside-Import mit
                # hasattr-Guard, damit dieser Manager nicht hart von state_db
                # abhaengig wird (auch für Profile-DBs).
                try:
                    from archon.core import state_db as _state_db
                    wal_init = getattr(_state_db, "_STATE_WAL_INIT", None)
                    if wal_init is not None and hasattr(wal_init, "discard"):
                        wal_init.discard(os.path.abspath(target))
                        # state_db.STATE_DB_PATH kann von target abweichen;
                        # zusätzlich den konfigurierten Pfad invalidieren.
                        cfg_path = getattr(_state_db, "STATE_DB_PATH", "")
                        if cfg_path:
                            wal_init.discard(os.path.abspath(cfg_path))
                except Exception:
                    pass
                # D03/MED: Mission Control haelt zwei SQLite-Caches pro Datei
                # (_MC_TABLES_INITIALIZED, _KANBAN_PRAGMA_INITIALIZED). Ohne
                # Invalidierung folgt "no such table" bis zum Prozessneustart.
                try:
                    from archon.core.mission_control import invalidate_caches_after_restore
                    invalidate_caches_after_restore(target)
                except Exception:
                    pass
            audit_status = "success"
            return result
        finally:
            # D5/F-08: Auch Dry-Runs und fehlgeschlagene Restores werden
            # protokolliert. Der Helper verschluckt Audit-Fehler absichtlich
            # (siehe _audit_backup_restore), damit die Restore-Transaktion
            # nicht durch einen Audit-Ausfall zerstoert wird.
            _meta = dict(audit_meta)
            _meta["status"] = audit_status
            if result is not None:
                _meta.update({
                    "integrity": result.get("integrity", "unknown"),
                    "restored": bool(result.get("restored")),
                    "rollback_ok": result.get("rollback_ok"),
                    "verified": result.get("verified"),
                })
            if result is not None:
                result.update(_audit_backup_restore(_meta))
            else:
                _audit_backup_restore(_meta)
            # F-016: SQLite legt beim Öffnen des Tempfiles WAL/SHM-Sidecars an.
            # Ohne Cleanup bleiben verwaiste Artefakte zurück (real beobachtet:
            # .memory.db.restore.*.tmp-shm/-wal in data/).
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = tmp_path + suffix
                if os.path.exists(sidecar):
                    try:
                        os.unlink(sidecar)
                    except OSError as exc:
                        logger.warning("[DBBackup] Temp-Sidecar %s nicht entfernbar: %s", sidecar, exc)
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def restore_secret_files(
        self,
        backup_file: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        """Stellt eine mit `_backup_secret_files()` gesicherte Datei wieder her.

        Secrets sind explizit geschuetzt: ohne ``confirm=True`` passiert nichts
        (separat bestaetigter Restore-Pfad). Ziel ist ausschliesslich der in
        ``SECRET_FILES`` hinterlegte, workspace-jailed Pfad.
        """
        name = os.path.basename(str(backup_file or ""))
        if not _SECRET_NAME_RE.fullmatch(name):
            raise ValueError("Ungueltiger Secret-Backup-Dateiname.")
        stem = name[:-len(".secret.gz")]
        logical = re.sub(r"_\d{8}_\d{6}$", "", stem)
        target_checked = {**SECRET_FILES, **_tenant_secret_files()}.get(logical)
        if not target_checked:
            raise ValueError(f"Unbekannte Secret-Datei: {logical}")
        target = os.path.abspath(target_checked)
        if not (_within(target, WORKSPACE_DIR) or _within(target, _APP_DATA_DIR)):
            raise ValueError(
                f"Secret-Restore-Ziel weder unter APP_DATA_DIR noch im Workspace: {target}"
            )

        src = os.path.join(self.backup_dir, name)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"Secret-Backup '{name}' nicht gefunden.")

        result: Optional[Dict[str, Any]] = None
        # D03/MED: Tempfile NEBEN das Ziel — das Backup-Verzeichnis kann auf
        # einem anderen Volume liegen (EXDEV bei os.replace).
        target_dir = os.path.dirname(target)
        os.makedirs(target_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target_dir, suffix=".restore.secret", delete=False) as tmp:
            tmp_path = tmp.name
        pre_path: Optional[str] = None
        try:
            with gzip.open(src, "rb") as fin, open(tmp_path, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            result = {
                "restored": not dry_run and confirm,
                "dry_run": bool(dry_run),
                "confirmed": bool(confirm),
                "backup": name,
                "secret": logical,
                "target": target,
            }
            if dry_run or not confirm:
                return result
            if os.path.exists(target):
                pre_path = target + ".pre_restore"
                shutil.copy2(target, pre_path)
            try:
                os.replace(tmp_path, target)
            except OSError as exc:
                # Rollback bei Replace-Fehler: alte Datei wiederherstellen.
                if pre_path and os.path.isfile(pre_path):
                    try:
                        os.replace(pre_path, target)
                    except OSError:
                        pass
                raise RuntimeError(f"Secret-Restore fehlgeschlagen: {exc}") from exc
            try:
                dir_fd = os.open(target_dir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
            return result
        finally:
            # D5/F-08: auch abgelehnte (unbestaetigte) Secret-Restores sind
            # revisionsrelevant. Kein Secret-Inhalt, nur Name/Status/Ziel.
            _meta = {
                "source_kind": "secret_backup",
                "backup": name,
                "secret": logical,
                "target": target,
                "integrity": "not_applicable",
                "restored": bool(result and result.get("restored")),
                "dry_run": bool(dry_run),
                "confirmed": bool(confirm),
                "rollback_ok": None,
                "status": "success" if result and result.get("restored") else (
                    "dry_run" if dry_run or not confirm else "failed"
                ),
            }
            if result is not None:
                result.update(_audit_backup_restore(_meta))
            else:
                _audit_backup_restore(_meta)
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


db_backup_manager = DBBackupManager()
