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

import os
import sys
import glob
import gzip
import json
import time
import sqlite3
import shutil
import tempfile
import datetime
from typing import Dict, Any, List

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

BACKUP_DIRS = (
    BACKUP_DIR,
    os.path.join(WORKSPACE_DIR, "data", "backups"),  # nur Legacy-Ziel, niemals Live-Quelle
)


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
    """Physisch isolierte Mandanten-DBs (FULL_TENANT_ISOLATION defaultet '1')."""
    return sorted(glob.glob(os.path.join(WORKSPACE_DIR, "data", "tenants", "*", "*.db")))


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
            self.dbs_to_test.append({
                "name": f"tenant:{_tid}/{os.path.basename(_path)}",
                "source": _path,
                "required_table": (),  # kein festes Schema — erste Tabelle als Smoke
                "optional": True,
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
                db_name = item["name"]
                src_path = item["source"]
                req_table = item["required_table"]

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
                    if item.get("optional"):
                        db_report["status"] = "SKIPPED"
                        db_report["skip_reason"] = (
                            "PocketBase nicht lokal verfügbar — ARCHON_POCKETBASE_DB setzen "
                            "oder Backup-Artefakt pb_data.db bereitstellen."
                        )
                        results["databases_skipped"] += 1
                    else:
                        db_report["status"] = "FAILED"
                        db_report["error"] = f"Quelldatenbank nicht gefunden: {src_path}"
                        results["databases_failed"] += 1
                    results["details"].append(db_report)
                    continue

                safe_dest_name = db_name.replace(":", "_").replace("/", "_").replace("\\", "_")
                dest_path = os.path.join(sandbox_dir, f"restored_{safe_dest_name}")
                if db_name.startswith("tenant:"):
                    source_kind = "tenant_live"
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
                        results["databases_failed"] += 1
                        results["details"].append(db_report)
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
                        src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=10.0)
                    except Exception:
                        src_conn = sqlite3.connect(src_path, timeout=10.0)

                    dest_conn = sqlite3.connect(dest_path)
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
                        results["databases_failed"] += 1
                    elif smoke_table is None or not db_report.get("record_count"):
                        db_report["status"] = "FAILED"
                        db_report["error"] = (
                            f"Smoke-Test fehlgeschlagen: keine Pflichttabelle {candidates} "
                            "vorhanden oder leer."
                        )
                        results["databases_failed"] += 1
                    elif int_res.lower() != "ok":
                        db_report["status"] = "FAILED"
                        db_report["error"] = f"Integritätsprüfung fehlgeschlagen: {int_res}"
                        results["databases_failed"] += 1
                    else:
                        results["databases_checked"] += 1

                except Exception as e:
                    db_report["status"] = "FAILED"
                    db_report["error"] = str(e)
                    results["databases_failed"] += 1

                results["details"].append(db_report)

        # Audit D / v0.5-Härtung: Tenant-DBs liegen bei FULL_TENANT_ISOLATION=1
        # unter data/tenants/<tid>/*.db. `_litestream_covers_tenants()` akzeptiert
        # explizite Pfade ODER einen `dir:`-Eintrag (Directory Replication).
        # Nur wenn beides fehlt, ist das ein harter FAIL — kein SKIPPED, kein
        # stilles Grün. Bei vorhandener Abdeckung wird das jetzt explizit als
        # OK ausgewiesen. Die Versionsnummer der Image-Konfiguration ist hier
        # irrelevant: geprüft wird ausschliesslich die Config-Datei.
        tenant_dbs = _tenant_dbs_present()
        if tenant_dbs:
            tenant_covered = _litestream_covers_tenants()
            results["details"].append({
                "database": "TENANT_REPLICATION",
                "source_path": os.path.join(WORKSPACE_DIR, "data", "tenants"),
                "source_exists": True,
                "source_size_bytes": 0,
                "integrity_check": "N/A",
                "foreign_key_check": "N/A",
                "smoke_test": (
                    f"OK ({len(tenant_dbs)} Tenant-DBs via Litestream abgedeckt)"
                    if tenant_covered else
                    f"FEHLER ({len(tenant_dbs)} Tenant-DBs ohne Litestream-Abdeckung)"
                ),
                "source_kind": "configured" if tenant_covered else "unreplicated",
                "status": "PASSED" if tenant_covered else "FAILED",
                "error": None if tenant_covered else (
                    f"{len(tenant_dbs)} Tenant-DBs vorhanden, aber config/litestream.yml "
                    "enthält weder einen expliziten Tenant-`path:` noch einen `dir:`-Eintrag "
                    "für /app/data/tenants. Bitte Directory Replication konfigurieren "
                    "(dir: /app/data/tenants, pattern: \"*.db\", recursive: true) oder "
                    "die Tenant-DBs einzeln unter dbs: aufführen."
                ),
            })
            if not tenant_covered:
                results["databases_failed"] += 1

        results["duration_seconds"] = round(time.time() - t_start, 2)
        if results["databases_failed"] > 0:
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
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception:
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
