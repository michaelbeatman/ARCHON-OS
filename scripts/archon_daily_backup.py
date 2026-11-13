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
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERMES = Path(os.environ.get("ARCHON_HERMES_DIR", os.path.expanduser("~/.hermes")))
DEST = ROOT / "backups"

DBS = [
    ROOT / "data" / "agentic_memory.db",
    ROOT / "data" / "deals.db",
    ROOT / "data" / "contracts.db",
    ROOT / "data" / "eu_ai_act_inventory.json",
    HERMES / "kanban.db",
    HERMES / "state.db",
    HERMES / "shared-state.db",
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
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30) as sconn:
        with sqlite3.connect(dst) as dconn:
            sconn.backup(dconn)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-days", type=int, default=14)
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    work = DEST / f".tmp_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    saved = 0

    for db in DBS:
        if not db.exists():
            continue
        target = work / db.name
        try:
            if db.suffix == ".db":
                sqlite_backup(db, target)
            else:
                shutil.copy2(db, target)
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
