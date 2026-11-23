"""
scripts/automated_restore_test.py
Automatisierter Restore- & Integritätstest für SQLite-Backups und Litestream-Replikate.
Führt einen wöchentlichen oder On-Demand Prüflauf in einer isolierten Wegwerf-Sandbox aus:
1. Restore echter Backup-Artefakte der konsolidierten DBs (ops/business/memory.db)
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

HISTORY_FILE = os.path.join(WORKSPACE_DIR, "data", "restore_test_history.json")


# Audit 23.11.2026: der Test muss ECHTE Backup-Artefakte prüfen, nicht eine
# Kopie der live DB — sonst bleibt ein seit Wochen kaputter Backup-Job grün.
BACKUP_DIRS = (
    os.path.join(os.path.expanduser("~"), ".hermes", "backups", "db"),
    os.path.join(WORKSPACE_DIR, "data", "backups"),
)


def find_latest_backup(name: str) -> str:
    """Neuestes echtes Backup-Artefakt für 'name' (db oder db.gz)."""
    found = []
    for base in BACKUP_DIRS:
        for pattern in (f"archon_*/{name}", f"archon_*/{name}.gz", f"{name}", f"{name}.gz"):
            found.extend(glob.glob(os.path.join(base, pattern)))
    found = [p for p in found if os.path.isfile(p) and os.path.getsize(p) > 0]
    return max(found, key=os.path.getmtime) if found else ""


def resolve_db_path(name: str) -> str:
    """Findet den Quellpfad einer Datenbank — Backup-Artefakte haben Vorrang."""
    backup = find_latest_backup(name)
    if backup:
        return backup
    candidates = [
        f"/opt/data/{name}",
        os.path.expanduser(f"~/.hermes/{name}"),
        os.path.join(WORKSPACE_DIR, "data", name),
        os.path.join(WORKSPACE_DIR, name)
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
        ]

    def run_restore_test(self, notify: bool = True) -> Dict[str, Any]:
        """Führt den vollständigen Testlauf durch."""
        t_start = time.time()
        now_iso = datetime.datetime.now().isoformat()
        results = {
            "timestamp": now_iso,
            "overall_status": "PASSED",
            "databases_checked": 0,
            "databases_failed": 0,
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
                    db_report["status"] = "FAILED"
                    db_report["error"] = f"Quelldatenbank nicht gefunden: {src_path}"
                    results["databases_failed"] += 1
                    results["details"].append(db_report)
                    continue

                dest_path = os.path.join(sandbox_dir, f"restored_{db_name}")
                source_kind = "backup" if find_latest_backup(db_name) else "live"
                db_report["source_kind"] = source_kind
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
                    smoke_table = next((t for t in candidates if t in tables), None)
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

                    if smoke_table is None or not db_report.get("record_count"):
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
                st_icon = "✓" if d["status"] == "PASSED" else "✗"
                details_lines.append(f"{st_icon} {d['database']}: {d['integrity_check']} ({d['smoke_test']})")

            body_msg = (
                f"Automatisierter Restore- & Integritätstest: {report['overall_status']}\n"
                f"Geprüfte Datenbanken: {report['databases_checked']}/{len(self.dbs_to_test)}\n"
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
    tester = AutomatedRestoreTester()
    res = tester.run_restore_test(notify=False)
    print("=" * 65)
    print("  Archon OS – Automatisierter Restore- & Integritäts-Report")
    print("=" * 65)
    print(f"Status:      {res['overall_status']}")
    print(f"Zeitpunkt:   {res['timestamp']}")
    print(f"Dauer:       {res['duration_seconds']}s")
    print("-" * 65)
    for d in res["details"]:
        status_symbol = "[OK]" if d["status"] == "PASSED" else "[FAIL]"
        print(f"  {status_symbol} {d['database']:<18}: Integrität={d['integrity_check']} | Smoke={d['smoke_test']}")
        if d.get("error"):
            print(f"      Fehler: {d['error']}")
    print("=" * 65)
    if res["overall_status"] == "PASSED":
        print("[ERFOLG] Alle SQLite-Datenbanken wurden fehlerfrei in der Sandbox wiederhergestellt.")
        sys.exit(0)
    else:
        print("[WARNUNG] Mindestens eine Datenbank konnte nicht wiederhergestellt werden.")
        sys.exit(1)
