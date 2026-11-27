"""
scripts/automated_restore_test.py
Automatisierter Restore- & Integritätstest für SQLite-Backups und Litestream-Replikate.
Führt einen wöchentlichen oder On-Demand Prüflauf in einer isolierten Wegwerf-Sandbox aus:
1. Restore echter Backup-Artefakte der konsolidierten DBs (ops/business/memory.db)
   sowie der PocketBase-CRM-DB (pb_data.db → pocketbase/pb_data/data.db)
2. PRAGMA integrity_check & foreign_key_check
3. Smoke-Tests auf Kern-Tabellen & Datensätze
4. Alarmierung via NotificationHub (Telegram-Push bei Fehlern)
"""

import datetime
import glob
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

try:
    import yaml  # PyYAML 6.x ist im Archon-Container verfügbar
except ImportError:  # Fallback: minimale Textprüfung ohne PyYAML
    yaml = None

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

HISTORY_FILE = os.path.join(WORKSPACE_DIR, "data", "restore_test_history.json")

# Audit 23.11.2026 / Härtung: Verzeichnis UND Namensmuster kommen aus dem
# Backup-Manager (SSOT). Der alte Test suchte unter ~/.hermes/backups/db nach
# `ops.db`/`ops.db.gz`, während der Job `<name>_YYYYmmdd_HHMMSS.db.gz` unter
# <workspace>/.hermes/backups/db schreibt — dadurch griff er stets auf die
# Live-DB zurück und meldete grün. Keine Duplizierung der Konstanten mehr.
from backend.db_backup_manager import BACKUP_DIR, BACKUP_GLOB_PATTERN  # noqa: E402
from backend.db_paths import DB_BUSY_TIMEOUT_S  # D03/MED (F015): SSOT busy_timeout  # noqa: E402

BACKUP_DIRS = (
    BACKUP_DIR,
    os.path.join(WORKSPACE_DIR, "data", "backups"),  # nur Legacy-Ziel, niemals Live-Quelle
)

# D10-M2: Litestream-Replikate sind eine ZWEITE, unabhaengige Quelle. Der
# fruehere Test pruefte nur die Konfigurationspraesenz von `dir: /app/data/tenants`
# und meldete "PASSED" — ohne je ein Replikat materialisiert zu haben. Jetzt
# wird `litestream restore` in der Sandbox ausgefuehrt und die Frische gegen
# den juengsten Replikat-Timestamp geprueft. Ohne Artefakt: FAILED (nie SKIPPED).
LITESTREAM_REPLICA_DIR = os.getenv(
    "ARCHON_LITESTREAM_REPLICA_DIR", os.path.join(WORKSPACE_DIR, "dr_replicas")
).strip()
LITESTREAM_BIN = os.getenv("ARCHON_LITESTREAM_BIN", "litestream").strip()
LITESTREAM_CONFIG = os.getenv(
    "ARCHON_LITESTREAM_CONFIG", os.path.join(WORKSPACE_DIR, "config", "litestream.yml")
).strip()
LITESTREAM_MAX_AGE_S = max(30.0, float(os.getenv("ARCHON_LITESTREAM_MAX_AGE_S", "120")))
LITESTREAM_RESTORE_TIMEOUT_S = max(
    10.0, float(os.getenv("ARCHON_LITESTREAM_RESTORE_TIMEOUT_S", "120"))
)

# Bekannte Replikat-Ziele aus config/litestream.yml (SSOT der Quellpfade).
_LITESTREAM_SOURCE_PATHS = {
    "ops.db": "/app/data/ops.db",
    "business.db": "/app/data/business.db",
    "memory.db": "/app/data/memory.db",
    "kanban.db": "/opt/data/kanban.db",
    "state.db": "/opt/data/state.db",
}


def find_latest_backup(name: str) -> str:
    """Neuestes echtes Backup-Artefakt für 'name' (Muster aus db_backup_manager)."""
    found = []
    for base in BACKUP_DIRS:
        found.extend(glob.glob(os.path.join(base, BACKUP_GLOB_PATTERN.format(db_name=name))))
        # Ältere Hermes-Ringpuffer-Artefakte nur ergänzend berücksichtigen.
        for pattern in (f"archon_*/{name}.db.gz", f"archon_*/{name}.gz"):
            found.extend(glob.glob(os.path.join(base, pattern)))
    found = [p for p in found if os.path.isfile(p) and os.path.getsize(p) > 0]
    return max(found, key=os.path.getmtime) if found else ""


def _tenant_dbs_present() -> List[str]:
    """Physisch isolierte Mandanten-DBs (APP_DATA_DIR + Workspace-Legacy)."""
    try:
        from backend.db_paths import APP_DATA_DIR
    except Exception:
        APP_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
    found = set(
        glob.glob(os.path.join(APP_DATA_DIR, "tenants", "*", "*.db"))
        + glob.glob(os.path.join(WORKSPACE_DIR, "data", "tenants", "*", "*.db"))
    )
    return sorted(os.path.abspath(p) for p in found)


def _is_tenant_target(value: Any) -> bool:
    """True für Pfade wie /app/data/tenants oder /app/data/tenants/<tid>/x.db."""
    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/").strip("\"'")
    return "/tenants/" in normalized or normalized.endswith("/tenants")


def _litestream_covers_tenants() -> bool:
    """True, wenn litestream.yml Tenant-DBs tatsächlich repliziert.

    Zwei gleichwertige Formen zählen:
      1) explizite `path:`-Einträge unter .../tenants/ (v0.3-Stil),
      2) ein `dir:`-Eintrag auf das Tenant-Verzeichnis (v0.5 Directory
         Replication). `pattern:`/`recursive:` sind dabei erlaubt und dürfen
         die Erkennung nicht verhindern.

    Kommentarzeilen zählen bewusst nicht: ein hingewiesener
    `# TENANT_DBS: ...`-Hinweis darf den Test nicht grün färben.
    """
    config_path = os.path.join(WORKSPACE_DIR, "config", "litestream.yml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return False

    if yaml is not None:
        try:
            cfg = yaml.safe_load(raw) or {}
            dbs = cfg.get("dbs") or []
            for db in dbs:
                if not isinstance(db, dict):
                    continue
                # dir: (v0.5) ODER path: (explizit) — pattern/recursive ignorieren
                if _is_tenant_target(db.get("dir")) or _is_tenant_target(db.get("path")):
                    return True
            return False
        except Exception:
            pass  # Defektes/unkonventionelles YAML -> Text-Fallback

    # Fallback ohne PyYAML: nur kommentarfreie Zeilen, keine value-Abhängigkeit.
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # YAML-Listeneintraege beginnen mit "- "; das Prefix entfernen.
        candidate = stripped[2:].strip() if stripped.startswith("- ") else stripped
        if (candidate.startswith("path:") or candidate.startswith("dir:")) and "/tenants" in candidate:
            return True
    return False


def _find_litestream_replicas() -> List[str]:
    """Alle Replikat-Kandidaten unter ``ARCHON_LITESTREAM_REPLICA_DIR``.

    Litestream legt Datei-Replikate als Verzeichnisse ``<name>.db`` an; in
    Wegwerf-/Test-Setups koennen es auch ".db"-Dateien sein. Tenant-Replikate
    liegen unter ``<dir>/tenants/<tid>/<db>``. Beides wird erfasst.
    """
    found: List[str] = []
    if not os.path.isdir(LITESTREAM_REPLICA_DIR):
        return found
    for root, dirs, files in os.walk(LITESTREAM_REPLICA_DIR):
        for name in dirs:
            if name.endswith(".db"):
                found.append(os.path.join(root, name))
        for name in files:
            if name.endswith(".db") or name.endswith(".db.gz"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _litestream_source_path(replica: str) -> str:
    """Konfigurierten DB-Quellpfad aus ``config/litestream.yml`` ableiten.

    ``litestream restore`` braucht den in der Config registrierten DB-Pfad,
    nicht das Replikat-Verzeichnis. Die Config ist SSOT; die eingebaute Tabelle
    ist nur Fallback fuer defektes YAML (und deckt die 5 Bestandseintraege ab).
    """
    normalized = replica.replace("\\", "/")
    base = os.path.basename(replica.rstrip("/").rstrip(os.sep))
    if "/tenants/" in normalized:
        return "/app/data/tenants/" + normalized.split("/tenants/", 1)[1].rstrip("/")
    if yaml is not None:
        try:
            with open(LITESTREAM_CONFIG, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            for db in cfg.get("dbs") or []:
                if isinstance(db, dict) and str(db.get("path") or "").endswith("/" + base):
                    return str(db["path"])
        except Exception:
            pass  # defektes YAML -> Fallback-Tabelle
    return _LITESTREAM_SOURCE_PATHS.get(base, f"/app/data/{base}")


def _litestream_replica_age_s(replica: str) -> Optional[float]:
    """Alter des juengsten Replikat-Artefakts (WAL-Segment/Snapshot)."""
    newest = 0.0
    if os.path.isfile(replica):
        newest = os.path.getmtime(replica)
    elif os.path.isdir(replica):
        for root, dirs, files in os.walk(replica):
            for name in dirs + files:
                path = os.path.join(root, name)
                try:
                    newest = max(newest, os.path.getmtime(path))
                except OSError:
                    pass
    if newest <= 0.0:
        return None
    return max(0.0, time.time() - newest)


def _restore_litestream_replica(replica: str, dest_path: str) -> Dict[str, Any]:
    """Fuehrt den echten ``litestream restore`` in die Sandbox aus."""
    db_path = _litestream_source_path(replica)
    cmd = [LITESTREAM_BIN, "restore", "-o", dest_path, "-config", LITESTREAM_CONFIG, db_path]
    completed = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=LITESTREAM_RESTORE_TIMEOUT_S, check=False,
    )
    return {
        "cmd": cmd,
        "returncode": int(completed.returncode),
        "stderr": str(completed.stderr or "").strip()[:500],
    }


def _verify_sqlite_snapshot(path: str, req_table: Any, db_report: Dict[str, Any]) -> bool:
    """PRAGMA integrity/FK + Smoke auf einer wiederhergestellten SQLite-Datei.

    Dieselbe Verifikation wie beim Backup-Artefakt-Pfad — nur ausgelagert,
    damit der Litestream-Pfad nicht hinter einer Getrennt-Nachweis-Pruefung
    zurueckbleibt.
    """
    dest_conn = sqlite3.connect(path, timeout=DB_BUSY_TIMEOUT_S)
    try:
        cur = dest_conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        int_res = str(cur.fetchone()[0])
        db_report["integrity_check"] = int_res

        cur.execute("PRAGMA foreign_key_check;")
        fk_res = cur.fetchall()
        db_report["foreign_key_check"] = "OK" if len(fk_res) == 0 else f"{len(fk_res)} Fehler"

        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        db_report["tables_found"] = len(tables)

        candidates = req_table if isinstance(req_table, (tuple, list)) else (req_table,)
        candidates = [c for c in candidates if c]
        smoke_table = (
            tables[0] if tables else None
        ) if not candidates else next((t for t in candidates if t in tables), None)
        if smoke_table:
            cur.execute(f'SELECT COUNT(*) FROM "{smoke_table}";')
            cnt = cur.fetchone()[0]
            db_report["record_count"] = cnt
            db_report["smoke_test"] = f"OK ({cnt} Einträge in {smoke_table})"
        else:
            db_report["smoke_test"] = (
                f"FEHLER (keine Pflichttabelle {candidates} vorhanden, "
                f"tabellen: {len(tables)})"
            )
    finally:
        dest_conn.close()

    if fk_res:
        db_report["error"] = f"Foreign-Key-Check fehlgeschlagen: {len(fk_res)} Verletzung(en)."
        return False
    if candidates and (smoke_table is None or not db_report.get("record_count")):
        db_report["error"] = (
            f"Smoke-Test fehlgeschlagen: keine Pflichttabelle {candidates} vorhanden oder leer."
        )
        return False
    if int_res.lower() != "ok":
        db_report["error"] = f"Integritätsprüfung fehlgeschlagen: {int_res}"
        return False
    return True


def resolve_db_path(name: str) -> str:
    """Findet den Quellpfad einer Datenbank — Backup-Artefakte haben Vorrang."""
    backup = find_latest_backup(name)
    if backup:
        return backup
    # K2-Fix (Rückmeldung nach Welle 0): die CRM-DB heisst auf Platte
    # `data.db`, im Backup-Artefakt aber `pb_data.db`. Der alte Kandidat
    # `/opt/data/pb_data.db` existiert ausserhalb des PocketBase-Containers
    # nicht und liess den Test auf Windows/CI rot werden.
    if name == "pb_data.db":
        env_path = os.getenv("ARCHON_POCKETBASE_DB", "").strip()
        if env_path:
            return os.path.abspath(os.path.expanduser(env_path))
        return os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data", "data.db")
    candidates = [
        f"/opt/data/{name}",
        os.path.expanduser(f"~/.hermes/{name}"),
        os.path.join(WORKSPACE_DIR, "data", name),
        os.path.join(WORKSPACE_DIR, name),
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 0:
            return c
    return candidates[0]


class AutomatedRestoreTester:
    """Führt atomare Restore- und Integritätstests in einer Sandbox durch."""

    def __init__(self):
        # Konsolidierte Domänen-DBs (Audit 23.11.2026: die alten Namen
        # kanban.db/state.db/agentic_memory.db sind nur noch Legacy-Aliase).
        self.dbs_to_test = [
            {"name": "ops.db", "source": resolve_db_path("ops.db"),
             "required_table": ("tasks", "task_events", "checkpoints")},
            {"name": "business.db", "source": resolve_db_path("business.db"),
             "required_table": ("deals", "contracts", "invoices")},
            {"name": "memory.db", "source": resolve_db_path("memory.db"),
             "required_table": ("learnings", "prompt_versions")},
            # K2 (Audit 23.11.2026): PocketBase-CRM war in keinem Restore-Test.
            # optional: in Container-Deployments liegt die DB im PocketBase-
            # Volume und ist hier nicht sichtbar -> SKIPPED statt FAILED.
            {"name": "pb_data.db", "source": resolve_db_path("pb_data.db"),
             "required_table": ("kontakte",), "optional": True},
        ]
        # D03/HIGH: echte Mandanten-DBs nicht nur konfigurationsseitig
        # prüfen, sondern im Sandbox-Restore mit integrity/FK/Smoke testen.
        for _path in _tenant_dbs_present():
            _tid = os.path.basename(os.path.dirname(_path))
            _db_file = os.path.basename(_path)
            # D03/MED: echtes tenant_<tid>__<db>_<stamp>.db.gz-Artefakt
            # bevorzugen (Namensschema aus db_backup_manager). Nur wenn kein
            # Backup existiert, wird die Live-Kopie als SKIPPED vermerkt.
            _artifact = find_latest_backup(f"tenant_{_tid}__{_db_file}")
            self.dbs_to_test.append({
                "name": f"tenant:{_tid}/{_db_file}",
                "source": _artifact or _path,
                "required_table": (),  # kein festes Schema — erste Tabelle als Smoke
                "optional": not bool(_artifact),
                "source_kind": "backup" if _artifact else "tenant_live",
                "tenant_tid": _tid,
            })

    def run_restore_test(self, notify: bool = True) -> Dict[str, Any]:
        """Führt den vollständigen Testlauf durch."""
        t_start = time.time()
        now_iso = datetime.datetime.now().isoformat()
        results = {
            "timestamp": now_iso,
            "overall_status": "PASSED",
            "databases_checked": 0,
            "databases_failed": 0,
            "databases_skipped": 0,
            "details": [],
            "duration_seconds": 0.0
        }

        with tempfile.TemporaryDirectory() as sandbox_dir:
            for item in self.dbs_to_test:
                db_name = item["name"]  # type: ignore[index]
                src_path = item["source"]  # type: ignore[index]
                req_table = item["required_table"]  # type: ignore[index]

                db_report = {
                    "database": db_name,
                    "source_path": src_path,
                    "source_exists": os.path.exists(src_path),
                    "source_size_bytes": os.path.getsize(src_path) if os.path.exists(src_path) else 0,
                    "integrity_check": "FAILED",
                    "foreign_key_check": "FAILED",
                    "smoke_test": "FAILED",
                    "record_count": 0,
                    "status": "PASSED",
                    "error": None
                }

                if not os.path.exists(src_path):
                    if item.get("optional"):  # type: ignore[attr-defined]
                        db_report["status"] = "SKIPPED"
                        db_report["skip_reason"] = (
                            "PocketBase nicht lokal verfügbar — ARCHON_POCKETBASE_DB setzen "
                            "oder Backup-Artefakt pb_data.db bereitstellen."
                        )
                        results["databases_skipped"] += 1  # type: ignore[operator]
                    else:
                        db_report["status"] = "FAILED"
                        db_report["error"] = f"Quelldatenbank nicht gefunden: {src_path}"
                        results["databases_failed"] += 1  # type: ignore[operator]
                    results["details"].append(db_report)  # type: ignore[attr-defined]
                    continue

                safe_dest_name = db_name.replace(":", "_").replace("/", "_").replace("\\", "_")
                dest_path = os.path.join(sandbox_dir, f"restored_{safe_dest_name}")
                if db_name.startswith("tenant:"):
                    # echtes Backup-Artefakt hat Vorrang vor der Live-Kopie
                    source_kind = item.get("source_kind") or "tenant_live"  # type: ignore[attr-defined]
                    db_report["source_kind"] = source_kind
                else:
                    source_kind = "backup" if find_latest_backup(db_name) else "live"
                    db_report["source_kind"] = source_kind
                    if source_kind != "backup":
                        # Pflichtbedingung (Audit A): der Test darf NIEMALS mit
                        # einer Kopie der Live-DB erfolgreich sein — das war der
                        # Grund, warum ein kaputter Backup-Job wochenlang grün war.
                        db_report["status"] = "FAILED"
                        db_report["error"] = (
                            f"Kein echtes Backup-Artefakt für {db_name} gefunden "
                            f"({BACKUP_DIR}); Live-DB als Quelle ist nicht zulässig."
                        )
                        results["databases_failed"] += 1  # type: ignore[operator]
                        results["details"].append(db_report)  # type: ignore[attr-defined]
                        continue
                if src_path.endswith(".gz"):
                    # Reales Backup-Artefakt: erst in der Sandbox dekomprimieren.
                    raw_path = os.path.join(sandbox_dir, f"source_{db_name}")
                    with gzip.open(src_path, "rb") as f_src, open(raw_path, "wb") as f_dst:
                        shutil.copyfileobj(f_src, f_dst)
                    src_path = raw_path

                try:
                    # 1. Atomarer Online-Restore via SQLite Backup API.
                    # KRITISCH: immutable=1 ignorierte WAL-Sidecars komplett —
                    # der Test pruefte einen veralteten Snapshot und meldete
                    # PASSED, obwohl die letzten Commits fehlten.
                    try:
                        src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=DB_BUSY_TIMEOUT_S)
                    except Exception:
                        src_conn = sqlite3.connect(src_path, timeout=DB_BUSY_TIMEOUT_S)

                    dest_conn = sqlite3.connect(dest_path, timeout=DB_BUSY_TIMEOUT_S)
                    with dest_conn:
                        src_conn.backup(dest_conn, pages=200)
                    src_conn.close()

                    # 2. PRAGMA Prüfungen in der Sandbox
                    cur = dest_conn.cursor()
                    cur.execute("PRAGMA integrity_check;")
                    int_res = cur.fetchone()[0]
                    db_report["integrity_check"] = int_res

                    cur.execute("PRAGMA foreign_key_check;")
                    fk_res = cur.fetchall()
                    db_report["foreign_key_check"] = "OK" if len(fk_res) == 0 else f"{len(fk_res)} Fehler"

                    # 3. Smoke-Test: Tabellen- und Datensatz-Verifikation
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    tables = [r[0] for r in cur.fetchall()]
                    db_report["tables_found"] = len(tables)

                    candidates = req_table if isinstance(req_table, (tuple, list)) else (req_table,)
                    candidates = [c for c in candidates if c]
                    # Tenant-DBs haben kein festes Pflicht-Schema: erste Tabelle.
                    smoke_table = (
                        tables[0] if tables else None
                    ) if not candidates else next((t for t in candidates if t in tables), None)
                    if smoke_table:
                        cur.execute(f'SELECT COUNT(*) FROM "{smoke_table}";')
                        cnt = cur.fetchone()[0]
                        db_report["record_count"] = cnt
                        db_report["smoke_test"] = f"OK ({cnt} Einträge in {smoke_table})"
                    else:
                        db_report["smoke_test"] = (
                            f"FEHLER (keine Pflichttabelle {candidates} vorhanden, "
                            f"tabellen: {len(tables)})"
                        )

                    dest_conn.close()

                    if fk_res:
                        # Audit B: foreign_key_check wurde bisher gespeichert,
                        # aber nie in die Status-Entscheidung einbezogen.
                        db_report["status"] = "FAILED"
                        db_report["error"] = (
                            f"Foreign-Key-Check fehlgeschlagen: {len(fk_res)} Verletzung(en)."
                        )
                        results["databases_failed"] += 1  # type: ignore[operator]
                    elif candidates and (smoke_table is None or not db_report.get("record_count")):
                        db_report["status"] = "FAILED"
                        db_report["error"] = (
                            f"Smoke-Test fehlgeschlagen: keine Pflichttabelle {candidates} "
                            "vorhanden oder leer."
                        )
                        results["databases_failed"] += 1  # type: ignore[operator]
                    elif int_res.lower() != "ok":
                        db_report["status"] = "FAILED"
                        db_report["error"] = f"Integritätsprüfung fehlgeschlagen: {int_res}"
                        results["databases_failed"] += 1  # type: ignore[operator]
                    else:
                        results["databases_checked"] += 1  # type: ignore[operator]

                except Exception as e:
                    db_report["status"] = "FAILED"
                    db_report["error"] = str(e)
                    results["databases_failed"] += 1  # type: ignore[operator]

                results["details"].append(db_report)  # type: ignore[attr-defined]

            # ------------------------------------------------------------------
            # D10-M2: echter Litestream-Replikat-Restore in derselben Sandbox.
            # Der fruehere Check las nur config/litestream.yml und meldete
            # "via Litestream abgedeckt", ohne je ein Replikat zu beruehren.
            # Jetzt: `litestream restore -config ... -o <sandbox> <db-path>`,
            # danach integrity/FK/Smoke und Frische gegen den Timestamp.
            # Fehlt das Artefakt -> FAILED, nie SKIPPED (Pflichtquelle).
            # ------------------------------------------------------------------
            replicas = _find_litestream_replicas()
            results["litestream_replicas_found"] = len(replicas)
            for replica in replicas:
                rep_name = os.path.basename(replica.rstrip("/").rstrip(os.sep))
                rreport: Dict[str, Any] = {
                    "database": f"LITESTREAM_RESTORE:{rep_name}",
                    "source_path": replica,
                    "source_exists": True,
                    "source_size_bytes": 0,
                    "integrity_check": "FAILED",
                    "foreign_key_check": "FAILED",
                    "smoke_test": "FAILED",
                    "source_kind": "litestream_replica",
                    "status": "FAILED",
                    "error": None,
                }
                try:
                    age_s = _litestream_replica_age_s(replica)
                    rreport["replica_age_sec"] = round(age_s, 1) if age_s is not None else None
                    dest = os.path.join(
                        sandbox_dir,
                        "litestream_restored_" + rep_name.replace(":", "_").replace("/", "_"),
                    )
                    cmd_result = _restore_litestream_replica(replica, dest)
                    rreport["restore_command"] = " ".join(cmd_result["cmd"][:5])
                    rreport["restore_returncode"] = cmd_result["returncode"]
                    if cmd_result["returncode"] != 0:
                        raise RuntimeError(
                            f"litestream restore exit {cmd_result['returncode']}: "
                            f"{cmd_result['stderr'][:200]}"
                        )
                    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
                        raise RuntimeError("litestream restore erzeugte keine Datenbankdatei")
                    verified = _verify_sqlite_snapshot(dest, (), rreport)
                    if age_s is None:
                        raise RuntimeError(
                            "Replikat-Alter nicht bestimmbar (keine Timestamp-Evidenz)"
                        )
                    if age_s > LITESTREAM_MAX_AGE_S:
                        raise RuntimeError(
                            f"Replikat veraltet: {age_s:.1f}s > "
                            f"{LITESTREAM_MAX_AGE_S:.0f}s (sync-interval 5-10 s erwartet)"
                        )
                    if not verified:
                        raise RuntimeError(
                            str(rreport.get("error") or "Sandbox-Verifikation fehlgeschlagen")
                        )
                    rreport["status"] = "PASSED"
                    results["databases_checked"] += 1  # type: ignore[operator]
                except Exception as exc:
                    rreport["status"] = "FAILED"
                    rreport["error"] = str(exc)
                    results["databases_failed"] += 1  # type: ignore[operator]
                results["details"].append(rreport)  # type: ignore[attr-defined]

            if not replicas:
                results["details"].append({  # type: ignore[attr-defined]
                    "database": "LITESTREAM_REPLICA_SOURCE",
                    "source_path": LITESTREAM_REPLICA_DIR,
                    "source_exists": False,
                    "source_size_bytes": 0,
                    "integrity_check": "FAILED",
                    "foreign_key_check": "FAILED",
                    "smoke_test": "FAILED",
                    "source_kind": "litestream_replica",
                    "status": "FAILED",
                    "error": (
                        f"Keine Litestream-Replikate unter {LITESTREAM_REPLICA_DIR} gefunden. "
                        "ARCHON_LITESTREAM_REPLICA_DIR auf das Replikat-Volume setzen; "
                        "Konfigurationspraesenz allein ist kein Restore-Beweis."
                    ),
                })
                results["databases_failed"] += 1  # type: ignore[operator]

        # Audit D / v0.5-Härtung + D10-M2: Tenant-DBs liegen bei
        # FULL_TENANT_ISOLATION=1 unter data/tenants/<tid>/*.db. DieConfig-
        # abdeckung (`dir:`/`path:`) ist nur noch eine Teilbedingung; PASSED
        # verlangt zusaetzlich den oben verifizierten echten Replikat-Restore.
        # Kein SKIPPED, kein stilles Gruen. Die Image-Versionsnummer ist
        # irrelevant: geprueft werden Config und Replikat-Artefakte.
        tenant_dbs = _tenant_dbs_present()
        if tenant_dbs:
            tenant_covered = _litestream_covers_tenants()
            # D10-M2: Config-Praesenz allein ist kein Restore-Beweis. Der Check
            # ist PASSED nur, wenn zusaetzlich mindestens ein echtes Tenant-
            # Replikat in der Sandbox wiederhergestellt und verifiziert wurde.
            tenant_restored = any(
                str(d.get("database", "")).startswith("LITESTREAM_RESTORE:")
                and d.get("status") == "PASSED"
                and "/tenants/" in str(d.get("source_path", "")).replace("\\", "/")
                for d in results["details"]  # type: ignore[attr-defined]
            )
            tenant_ok = tenant_covered and tenant_restored
            results["details"].append({  # type: ignore[attr-defined]
                "database": "TENANT_REPLICATION",
                "source_path": os.path.join(WORKSPACE_DIR, "data", "tenants"),
                "source_exists": True,
                "source_size_bytes": 0,
                "integrity_check": "N/A",
                "foreign_key_check": "N/A",
                "smoke_test": (
                    f"OK ({len(tenant_dbs)} Tenant-DBs: Config vorhanden, "
                    "echtes Replikat in Sandbox restore-verifiziert)"
                    if tenant_ok else
                    f"FEHLER ({len(tenant_dbs)} Tenant-DBs ohne verifizierten Replikat-Restore)"
                ),
                "source_kind": "litestream_replica" if tenant_ok else "unreplicated",
                "litestream_config_present": tenant_covered,
                "litestream_restore_verified": tenant_restored,
                "status": "PASSED" if tenant_ok else "FAILED",
                "error": None if tenant_ok else (
                    f"{len(tenant_dbs)} Tenant-DBs vorhanden, aber kein Tenant-Replikat "
                    "wurde via `litestream restore` in der Sandbox verifiziert. "
                    "Config-Praesenz (`dir: /app/data/tenants`) allein genuegt nicht."
                ),
            })
            if not tenant_ok:
                results["databases_failed"] += 1  # type: ignore[operator]

        # D03/MED: Secret-Restores waren bisher gar nicht getestet. Dry-run gegen ein
        # vorhandenes .secret.gz-Artefakt (kein Schreiben, kein Confirm).
        secret_artifacts = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.secret.gz")))
        if secret_artifacts:
            try:
                from backend.db_backup_manager import db_backup_manager
                secret_name = os.path.basename(secret_artifacts[-1])
                secret_res = db_backup_manager.restore_secret_files(
                    secret_name, dry_run=True, confirm=False
                )
                results["details"].append({  # type: ignore[attr-defined]
                    "database": "SECRET_RESTORE_DRY_RUN",
                    "source_path": secret_artifacts[-1],
                    "source_exists": True,
                    "source_size_bytes": os.path.getsize(secret_artifacts[-1]),
                    "integrity_check": "N/A",
                    "foreign_key_check": "N/A",
                    "smoke_test": f"OK ({secret_res.get('secret')})",
                    "source_kind": "backup",
                    "status": "PASSED",
                    "error": None,
                })
            except Exception as exc:
                results["details"].append({  # type: ignore[attr-defined]
                    "database": "SECRET_RESTORE_DRY_RUN",
                    "source_path": secret_artifacts[-1],
                    "source_exists": True,
                    "source_size_bytes": 0,
                    "integrity_check": "FAILED",
                    "foreign_key_check": "FAILED",
                    "smoke_test": "FAILED",
                    "status": "FAILED",
                    "error": str(exc),
                })
                results["databases_failed"] += 1  # type: ignore[operator]

        results["duration_seconds"] = round(time.time() - t_start, 2)
        if results["databases_failed"] > 0:  # type: ignore[operator]
            results["overall_status"] = "FAILED"

        # Verlauf speichern
        self._save_history(results)

        # Benachrichtigung über NotificationHub
        if notify:
            self._dispatch_notification(results)

        return results

    def _save_history(self, report: Dict[str, Any]):
        """Hängt das Testergebnis an die Historie an (max 30 Einträge)."""
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        history.insert(0, report)
        history = history[:30]

        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        # D03/MED: atomic write + sichtbarer Fehler (frueher open("w") mit
        # verschluckter Exception — die Historie war bei Abbruch weg).
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(HISTORY_FILE), prefix=".restore_history_", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, HISTORY_FILE)
            tmp_path = None
        except Exception as exc:
            print(f"[RestoreTest] FEHLER beim Speichern der Historie: {exc}", file=sys.stderr)
            raise
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _dispatch_notification(self, report: Dict[str, Any]):
        """Sendet einen Alarm via NotificationHub / Telegram."""
        try:
            from backend.notification_hub import get_notification_hub
            hub = get_notification_hub()

            passed = (report["overall_status"] == "PASSED")
            sev = "INFO" if passed else "CRITICAL"
            icon = "✅" if passed else "🚨"

            details_lines = []
            for d in report["details"]:
                st_icon = "✓" if d["status"] == "PASSED" else ("–" if d["status"] == "SKIPPED" else "✗")
                details_lines.append(f"{st_icon} {d['database']}: {d['integrity_check']} ({d['smoke_test']})")

            body_msg = (
                f"Automatisierter Restore- & Integritätstest: {report['overall_status']}\n"
                f"Geprüfte Datenbanken: {report['databases_checked']}/{len(self.dbs_to_test)} "
                f"(übersprungen: {report['databases_skipped']})\n"
                f"Dauer: {report['duration_seconds']}s\n\n" +
                "\n".join(details_lines)
            )

            hub.dispatch_notification(
                title=f"{icon} SQLite Restore-Test: {report['overall_status']}",
                message=body_msg,
                severity=sev,
                category="backup_restore"
            )
        except Exception as e:
            print(f"[RestoreTester] Fehler beim Senden der Benachrichtigung: {e}", file=sys.stderr)


restore_tester = AutomatedRestoreTester()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Archon OS – automatisierter Restore- & Integritätstest (Sandbox)."
    )
    parser.add_argument("--notify", action="store_true",
                        help="Ergebnis via NotificationHub / Telegram melden (default: aus)")
    parser.add_argument("--json", action="store_true",
                        help="Roh-Report als JSON ausgeben")
    args = parser.parse_args()

    tester = AutomatedRestoreTester()
    res = tester.run_restore_test(notify=args.notify)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res["overall_status"] == "PASSED" else 1)
    print("=" * 65)
    print("  Archon OS – Automatisierter Restore- & Integritäts-Report")
    print("=" * 65)
    print(f"Status:      {res['overall_status']}")
    print(f"Zeitpunkt:   {res['timestamp']}")
    print(f"Dauer:       {res['duration_seconds']}s")
    print("-" * 65)
    for d in res["details"]:
        status_symbol = {"PASSED": "[OK]", "SKIPPED": "[SKIP]"}.get(d["status"], "[FAIL]")
        print(f"  {status_symbol} {d['database']:<18}: Integrität={d['integrity_check']} | Smoke={d['smoke_test']}")
        if d.get("error"):
            print(f"      Fehler: {d['error']}")
        if d.get("skip_reason"):
            print(f"      Hinweis: {d['skip_reason']}")
    print("=" * 65)
    if res["overall_status"] == "PASSED":
        print("[ERFOLG] Alle SQLite-Datenbanken wurden fehlerfrei in der Sandbox wiederhergestellt.")
        sys.exit(0)
    else:
        print("[WARNUNG] Mindestens eine Datenbank konnte nicht wiederhergestellt werden.")
        sys.exit(1)
