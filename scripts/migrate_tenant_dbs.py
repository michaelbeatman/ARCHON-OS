#!/usr/bin/env python3
"""Einmalige Migration: gemeinsam genutzte DBs -> pro Mandant eigene DBs.

Benutzerentscheidung 22.11.2026:
- jeder Mandant (auch 'default') bekommt data/tenants/<tid>/*.db
- verwaiste DB-Dateien im Repository-Root werden nach data/_legacy_root_dbs/
  verschoben (nicht gelöscht — revertierbar, aber aus dem aktiven Pfad weg).

Standardsicher: Default ist dry-run. Erst mit --execute wird geschrieben.
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sqlite3
import sys

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
TENANTS_DIR = os.path.join(DATA_DIR, "tenants")
DEFAULT_TENANT_DIR = os.path.join(TENANTS_DIR, "default")


def _has_tables(path: str) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
        try:
            return con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
            ).fetchone() is not None
        finally:
            con.close()
    except Exception:
        return False


def _copy_db(src: str, dst: str) -> bool:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return False
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=15.0)
    d = sqlite3.connect(dst, timeout=15.0)
    try:
        s.backup(d)
        return True
    finally:
        d.close()
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true", help="Änderungen tatsächlich schreiben")
    ap.add_argument("--tenant", default="default", help="Ziel-Mandant (default: default)")
    ap.add_argument("--skip-root", action="store_true", help="Root-DBs nicht archivieren")
    args = ap.parse_args()

    tenant = "".join(c for c in args.tenant if c.isalnum() or c in "-_") or "default"
    tenant_dir = os.path.join(TENANTS_DIR, tenant)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join(DATA_DIR, f"_legacy_root_dbs_{stamp}")

    actions: list[str] = []
    # 1) Geteilte DBs aus data/ in Mandantenverzeichnis kopieren
    if os.path.isdir(DATA_DIR):
        for name in sorted(os.listdir(DATA_DIR)):
            if not name.endswith(".db"):
                continue
            src = os.path.join(DATA_DIR, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(tenant_dir, name)
            if os.path.exists(dst):
                continue
            if _has_tables(src):
                actions.append(f"COPY data/{name} -> data/tenants/{tenant}/{name}")
                if args.execute:
                    _copy_db(src, dst)

    # 1b) Alten Workspace-Tenant-Pfad (agent_workspace/data/tenants) konsolidieren.
    # archon.core.runtime lieferte frueher "./agent_workspace" als WORKSPACE_DIR,
    # wodurch ein zweites tenants-Verzeichnis entstand. Jetzt zeigt alles auf
    # data/tenants (identisch mit backend.db_paths).
    legacy_tenants = os.path.join(WORKSPACE_DIR, "agent_workspace", "data", "tenants")
    if os.path.isdir(legacy_tenants):
        for tid in sorted(os.listdir(legacy_tenants)):
            src_dir = os.path.join(legacy_tenants, tid)
            if not os.path.isdir(src_dir):
                continue
            for name in sorted(os.listdir(src_dir)):
                if not name.endswith(".db"):
                    continue
                src = os.path.join(src_dir, name)
                dst = os.path.join(TENANTS_DIR, tid, name)
                if os.path.exists(dst) or not _has_tables(src):
                    continue
                actions.append(f"COPY agent_workspace/data/tenants/{tid}/{name} -> data/tenants/{tid}/{name}")
                if args.execute:
                    _copy_db(src, dst)
            actions.append(f"ARCHIVE agent_workspace/data/tenants/{tid} -> data/{os.path.basename(archive_dir)}/workspace_tenant_{tid}")
            if args.execute:
                os.makedirs(archive_dir, exist_ok=True)
                shutil.move(src_dir, os.path.join(archive_dir, f"workspace_tenant_{tid}"))

    # 2) Verwaiste Root-DBs archivieren (aus dem aktiven Pfad entfernen)
    if not args.skip_root:
        for name in sorted(os.listdir(WORKSPACE_DIR)):
            if not name.endswith(".db"):
                continue
            src = os.path.join(WORKSPACE_DIR, name)
            if not os.path.isfile(src):
                continue
            dst_tenant = os.path.join(tenant_dir, name)
            if _has_tables(src) and not os.path.exists(dst_tenant):
                actions.append(f"COPY {name} -> data/tenants/{tenant}/{name}")
                if args.execute:
                    _copy_db(src, dst_tenant)
            actions.append(f"ARCHIVE ./{name} -> data/{os.path.basename(archive_dir)}/{name}")
            if args.execute:
                os.makedirs(archive_dir, exist_ok=True)
                shutil.move(src, os.path.join(archive_dir, name))

    print(f"{'EXECUTE' if args.execute else 'DRY-RUN'}: {len(actions)} Aktion(en)")
    for a in actions:
        print("  " + a)
    if not args.execute and actions:
        print("\nZum Ausführen: python scripts/migrate_tenant_dbs.py --execute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
