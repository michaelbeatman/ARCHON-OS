#!/usr/bin/env python3
"""Tägliches Backup der Archon-Datenbanken und Kernkonfigurationen.

Sichert konsistent über die SQLite-Backup-API (auch bei laufender Anwendung),
legt ein tar.gz je Lauf ab und rotiert nach KEEP_DAYS.

    python3 scripts/archon_daily_backup.py [--keep-days 14]

Exit-Code 1, wenn eine Datenbank nicht gesichert werden konnte.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERMES = Path(os.environ.get("ARCHON_HERMES_DIR", os.path.expanduser("~/.hermes")))
DEST = ROOT / "backups"

# D03/MED (F015): die produktiven DBs werden zur Laufzeit aus APP_DATA_DIR,
# dem Konsolidierungsmanifest und den Tenant-Verzeichnissen ermittelt. Die
# fruehere statische Liste sicherte nur veraltete/leere Legacy-Dateien und
# meldete trotzdem Erfolg. Die JSON-Datei bleibt als Config-Eintrag erhalten.
DBS = [
    ROOT / "data" / "eu_ai_act_inventory.json",
]
CONFIGS = [
    ROOT / "settings.json",
    ROOT / "agent_workspace" / "settings.json",
    ROOT / "agent_profiles.json",
    ROOT / "data" / "model_routing.json",
    ROOT / "data" / "guarantor_limits.json",
    ROOT / "scripts" / "n8n_routine_workflows.json",
]


def sqlite_backup(src: Path, dst: Path) -> None:
    """Konsistente Kopie über die SQLite-API (WAL-sicher)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.db_paths import DB_BUSY_TIMEOUT_S
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=DB_BUSY_TIMEOUT_S) as sconn:
        with sqlite3.connect(dst, timeout=DB_BUSY_TIMEOUT_S) as dconn:
            sconn.backup(dconn)


def runtime_db_targets() -> list[tuple[str, Path]]:
    """Produktive DB-Ziele zur Laufzeit (APP_DATA_DIR + Konsolidierung + Tenants)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.db_paths import APP_DATA_DIR, CONSOLIDATED_DB_FILENAMES

    app = Path(APP_DATA_DIR)
    targets: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(arcname: str, path: Path) -> None:
        key = os.path.abspath(str(path))
        if key in seen or not path.is_file():
            return
        seen.add(key)
        targets.append((arcname, path))

    # 1. Die 3 konsolidierten Domänen-DBs (SSOT aus db_paths).
    for name in CONSOLIDATED_DB_FILENAMES:
        add(name, app / name)
    # 2. Noch physisch vorhandene Legacy-DBs (ältere Deployments/Migration).
    for name in ("agentic_memory.db", "contracts.db", "deals.db",
                 "corporate.db", "content_machine.db"):
        add(name, app / name)
    # 3. Physisch isolierte Mandanten-DBs (APP_DATA_DIR + Workspace-Legacy).
    for base in (app / "tenants", ROOT / "data" / "tenants"):
        for path in sorted(base.glob("*/*.db")):
            add(f"tenant_{path.parent.name}__{path.name}", path)
    # 4. Hermes-DBs bleiben ergänzend erhalten.
    for name in ("kanban.db", "state.db", "shared-state.db"):
        add(name, HERMES / name)
    return targets


def required_db_targets(targets: list[tuple[str, Path]]) -> list[str]:
    """Konsolidierte + Tenant-DBs — ohne diese darf kein Erfolg gemeldet werden."""
    return [
        arc for arc, _ in targets
        if arc in ("ops.db", "business.db", "memory.db") or arc.startswith("tenant_")
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-days", type=int, default=14)
    args = ap.parse_args()

    try:
        db_targets = runtime_db_targets()
    except Exception as exc:  # noqa: BLE001
        print(f"[FEHLER] DB-Zielauflösung fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    required = required_db_targets(db_targets)
    # D03/MED:Guard — leere/veraltete Archive mit Exit 0 sind der Befund.
    if not required:
        print(
            "[FEHLER] Keine konsolidierten (ops/business/memory.db) oder "
            "Tenant-DBs gefunden — Backup abgebrochen (Exit 1). "
            "APP_DATA_DIR/ARCHON_DATA_DIR pruefen.",
            file=sys.stderr,
        )
        return 1

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    work = DEST / f".tmp_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    saved = 0

    for arcname, db in db_targets:
        target = work / arcname
        try:
            if db.suffix == ".db":
                sqlite_backup(db, target)
            else:
                shutil.copy2(db, target)
            saved += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{arcname}: {exc}")

    for db in DBS:
        if not db.exists():
            continue
        try:
            shutil.copy2(db, work / db.name)
            saved += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{db.name}: {exc}")

    for cfg in CONFIGS:
        if cfg.exists():
            try:
                shutil.copy2(cfg, work / cfg.name)
                saved += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{cfg.name}: {exc}")

    manifest = {
        "created": stamp,
        "files": sorted(p.name for p in work.iterdir()),
        "required_db_targets": required,
        "errors": errors,
    }
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    archive = DEST / f"archon_backup_{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(work, arcname=f"archon_backup_{stamp}")
    shutil.rmtree(work, ignore_errors=True)

    # Rotation
    cutoff = datetime.datetime.now() - datetime.timedelta(days=args.keep_days)
    removed = 0
    for old in DEST.glob("archon_backup_*.tar.gz"):
        try:
            ts = datetime.datetime.strptime(old.stem.replace("archon_backup_", ""), "%Y-%m-%d_%H%M")
        except ValueError:
            continue
        if ts < cutoff:
            old.unlink(missing_ok=True)
            removed += 1

    size_mb = archive.stat().st_size / 1024 / 1024 if archive.exists() else 0
    print(f"[{stamp}] {saved} Dateien gesichert -> {archive.name} ({size_mb:.1f} MB), "
          f"{removed} alte entfernt, {len(errors)} Fehler")
    for err in errors:
        print("  FEHLER:", err)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
