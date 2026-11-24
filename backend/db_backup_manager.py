"""
backend/db_backup_manager.py
Automatisches SQLite Online-Backup & WAL-Checkpointing (Pillar 4: Desaster-Recovery).
Führt periodisch PRAGMA wal_checkpoint(TRUNCATE) durch und sichert
die Datenbanken komprimiert im Ringpuffer (.hermes/backups/db/) mit konfigurierbarer Rotation.
"""

import os
import sys
import re
from contextlib import contextmanager
import glob
import gzip
import logging
import sqlite3
import datetime
import shutil
import tarfile
import tempfile
import threading
from typing import Dict, Any, List, Optional

logger = logging.getLogger("archon.db_backup_manager")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "backups", "db")
TENANTS_DIR = os.path.join(WORKSPACE_DIR, "data", "tenants")
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

        # Statische Kern-DBs (respektiert Test-Monkeypatches auf DB_TARGETS) + dynamische Mandanten-DBs
        base_targets = list(DB_TARGETS) if DB_TARGETS != _INITIAL_DB_TARGETS else _collect_db_targets()
        tenant_dbs = sorted(glob.glob(os.path.join(WORKSPACE_DIR, "data", "tenants", "*", "*.db")))
        seen_paths = set()
        all_targets = []
        for candidate in base_targets + tenant_dbs:
            norm = os.path.abspath(candidate)
            if norm not in seen_paths and os.path.exists(norm):
                seen_paths.add(norm)
                all_targets.append(norm)

        tenants_prefix = os.path.abspath(os.path.join(WORKSPACE_DIR, "data", "tenants")) + os.sep
        for db_path in all_targets:
            if db_path == POCKETBASE_DB_PATH:
                # Eindeutiger Backup-Name, sonst kollidiert er mit anderen data.db.
                db_name = "pb_data.db"
            elif db_path == POCKETBASE_AUX_DB_PATH:
                db_name = "pb_auxiliary.db"
            elif db_path.startswith(tenants_prefix):
                rel = db_path[len(tenants_prefix):].replace(os.sep, "__")
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

                with open(tmp_snapshot, "rb") as f_in:
                    with gzip.open(backup_file, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
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
                with open(src_path, "rb") as f_in:
                    with gzip.open(backup_file, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
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
        if not _within(target, WORKSPACE_DIR):
            raise ValueError(f"Restore-Ziel ausserhalb des Workspace: {target}")

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
        with tempfile.NamedTemporaryFile(dir=self.backup_dir, suffix=".restore.db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with gzip.open(src, "rb") as fin, open(tmp_path, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            # C (dieses Audits): VOR dem Austausch der Produktionsdatei
            # prüfen. Schlägt die Prüfung fehl, bleibt die Live-DB unberührt.
            conn = sqlite3.connect(tmp_path)
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
                quick = conn.execute("PRAGMA quick_check").fetchone()
                # F-015: FK-Check gehoert zwingend VOR den Austausch. Ein
                # FK-inkonsistentes Backup wurde bisher still in den Produktions-
                # pfad gespielt (genau die Korruption, die P1-24 bereinigte).
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                conn.close()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise RuntimeError(f"Integritätsprüfung fehlgeschlagen: {integrity}")
            if not quick or str(quick[0]).lower() != "ok":
                raise RuntimeError(f"Quick-Check des Backup-Snapshots fehlgeschlagen: {quick}")
            if fk_violations:
                raise RuntimeError(
                    f"Restore abgelehnt: {len(fk_violations)} FK-Verletzung(en) im Backup-Snapshot."
                )
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
            os.makedirs(os.path.dirname(target), exist_ok=True)
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
                    raise RuntimeError(
                        f"Restore abgelehnt: Zieldatenbank nicht verfügbar ({exc}). "
                        "Erst Hintergrund-Loops/Agenten in den Drain-Modus schicken."
                    ) from exc
                finally:
                    if guard is not None:
                        try:
                            guard.execute("ROLLBACK")
                        except Exception:
                            pass
                        guard.close()

                # Der Guard wird hier freigegeben, weil Windows einen
                # `os.replace()` auf eine noch offene Datei verweigert. Das
                # Cross-Prozess-Gate (_restore_gate) bleibt bis zum Ende der
                # Phase gehalten. Restrisiko: ein Writer, der genau in diesem
                # winzigen Fenster die alte Inode öffnet, schreibt danach in
                # die verworfene Datei. Deshalb im Anschluss verifizieren.
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = target + suffix
                    if os.path.exists(sidecar):
                        try:
                            os.remove(sidecar)
                        except OSError as exc:
                            logger.warning("[DBBackup] Sidecar %s nicht entfernbar: %s", sidecar, exc)
                os.replace(tmp_path, target)

                # Post-Condition: die restaurierte Datei muss lesbar und
                # integr sein. Schlägt sie fehl, wird die pre_restore-Kopie
                # unter dem noch gehaltenen Gate zurückgespielt. Damit bleibt
                # nie eine defekte DB am Produktionspfad liegen (Audit C).
                verify_error: Optional[BaseException] = None
                try:
                    verify = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
                    try:
                        check = verify.execute("PRAGMA quick_check").fetchone()
                    finally:
                        verify.close()
                    result["verified"] = bool(check and str(check[0]).lower() == "ok")
                    if not result["verified"]:
                        raise RuntimeError(f"Restore-Verifikation fehlgeschlagen: {check}")
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
        if not _within(target, WORKSPACE_DIR):
            raise ValueError(f"Secret-Restore-Ziel ausserhalb des Workspace: {target}")

        src = os.path.join(self.backup_dir, name)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"Secret-Backup '{name}' nicht gefunden.")

        result: Optional[Dict[str, Any]] = None
        with tempfile.NamedTemporaryFile(dir=self.backup_dir, suffix=".restore.secret", delete=False) as tmp:
            tmp_path = tmp.name
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
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                shutil.copy2(target, target + ".pre_restore")
            os.replace(tmp_path, target)
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
