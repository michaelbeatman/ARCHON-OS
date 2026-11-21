# -*- coding: utf-8 -*-
"""
backend/db_consolidation.py
===========================
Phase 2.1 — Datenbank-Konsolidierung (28 verstreute SQLite-DBs -> 3 Domaenen-DBs):
- `ops.db`:      Kanban, Mission Control, Workflow-DAGs, Schedules, Checkpoints,
                 DLQ, Idempotency, Audit-Log, Warrants, Telemetry, Agent-State
- `business.db`: ERP, CRM, Contracts, Deals, Corporate, Treasury, Dunning,
                 Email-Drafts, Calendar, Content-Maschine
- `memory.db`:   Agentic Memory, Learnings, Conversations, Semantic Cache,
                 Core Working Memory, Offline Encrypted Compartment Vault

Eigenschaften:
- Zero-Ops, 100% SQLite WAL-Mode, Mandanten-faehig
- Konsistentes Online-Backup (sqlite3.backup) vor jeder Migration
- Idempotente Tabellen- & Daten-Migration (INSERT OR IGNORE, wiederholbar)
- Automatische Kollisionsvermeidung bei gleichnamigen Tabellen unterschiedlicher Herkunft
- Abwaertskompatible Aktivierung ueber Manifest `data/.db_consolidated.json`
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("archon.db_consolidation")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
CONSOLIDATED_DOMAINS = ("ops.db", "business.db", "memory.db")
MANIFEST_FILENAME = ".db_consolidated.json"

# Verbindliche Zuordnung aller Legacy-SQLite-Dateien auf die 3 Zieldomaenen
CONSOLIDATION_DOMAIN_MAP: Dict[str, str] = {
    # 1. OPS (Orchestrierung, Workflows, Governance, Telemetrie)
    "ops.db": "ops.db",
    "kanban.db": "ops.db",
    "state.db": "ops.db",
    "shared-state.db": "ops.db",
    "projects.db": "ops.db",
    "agent_os.db": "ops.db",
    "workflow_dags.db": "ops.db",
    "workflow_schedules.db": "ops.db",
    "checkpoints.db": "ops.db",
    "durable_checkpoints.db": "ops.db",
    "dead_letter_queue.db": "ops.db",
    "idempotency_guard.db": "ops.db",
    "audit_log.db": "ops.db",
    "chained_audit.db": "ops.db",
    "tool_warrants.db": "ops.db",
    "agent_scorecard.db": "ops.db",
    "telemetry.db": "ops.db",
    "precedent_log.db": "ops.db",
    "decision_receipts.db": "ops.db",
    "fleet_health.db": "ops.db",
    "data.db": "ops.db",
    # 2. BUSINESS (Virtuelles Unternehmen & Content-Maschine)
    "business.db": "business.db",
    "erp.db": "business.db",
    "crm.db": "business.db",
    "contracts.db": "business.db",
    "deals.db": "business.db",
    "corporate.db": "business.db",
    "treasury.db": "business.db",
    "dunning.db": "business.db",
    "email_drafts.db": "business.db",
    "calendar.db": "business.db",
    "operations_calendar.db": "business.db",
    "content_machine.db": "business.db",
    # 3. MEMORY (Langzeitgedaechtnis, Embeddings, Cache, Vault)
    "memory.db": "memory.db",
    "agentic_memory.db": "memory.db",
    "compartment_vault.db": "memory.db",
    "semantic_cache.db": "memory.db",
    "core_memory.db": "memory.db",
}


def resolve_consolidated_domain(legacy_filename: str) -> str:
    """Ordnet einen Legacy-DB-Dateinamen eindeutig einer der 3 Zieldomaenen zu."""
    base = os.path.basename(str(legacy_filename or "").strip()).lower()
    if base in CONSOLIDATION_DOMAIN_MAP:
        return CONSOLIDATION_DOMAIN_MAP[base]
    if any(k in base for k in ("mem", "cache", "vault", "learn", "embed")):
        return "memory.db"
    if any(k in base for k in ("erp", "crm", "contract", "deal", "treasury", "dunning", "content", "mail", "cal", "corp")):
        return "business.db"
    return "ops.db"


def get_manifest_path(target_dir: Optional[str] = None) -> str:
    base = os.path.abspath(target_dir or DEFAULT_DATA_DIR)
    return os.path.join(base, MANIFEST_FILENAME)


def is_consolidation_active(target_dir: Optional[str] = None) -> bool:
    """True, wenn die konsolidierte 3-DB-Architektur per Env oder Manifest aktiviert ist."""
    env_flag = os.environ.get("ARCHON_DB_CONSOLIDATED", "").strip().lower()
    if env_flag in ("1", "true", "yes"):
        return True
    if env_flag in ("0", "false", "no"):
        return False
    manifest = get_manifest_path(target_dir)
    if not os.path.isfile(manifest):
        return False
    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(isinstance(data, dict) and data.get("active"))
    except (OSError, ValueError) as exc:
        logger.warning(f"[DBConsolidation] Manifest nicht lesbar ({manifest}): {exc}")
        return False


def _sanitize_ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip()) or "tbl"


def _inspect_sqlite_file(db_path: str, *, fast_count: bool = False) -> Dict[str, Any]:
    """Liest Tabellen, Spalten, Zeilenanzahl und Indizes einer SQLite-Datei (read-only)."""
    info: Dict[str, Any] = {
        "path": os.path.abspath(db_path),
        "filename": os.path.basename(db_path),
        "size_bytes": os.path.getsize(db_path) if os.path.isfile(db_path) else 0,
        "target_domain": resolve_consolidated_domain(db_path),
        "tables": {},
        "total_rows": 0,
        "valid_sqlite": False,
        "error": None,
    }
    if not os.path.isfile(db_path) or info["size_bytes"] == 0:
        return info

    # Bei sehr grossen DBs (> 25 MB) im schnellen Plan-Modus teure Full-Table-Scans vermeiden
    skip_exact_count = fast_count and info["size_bytes"] > 25 * 1024 * 1024

    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.execute("PRAGMA busy_timeout=1500;")
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for tbl_name, create_sql in rows:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{tbl_name}")').fetchall()]
            if skip_exact_count:
                cnt = -1
            else:
                cnt_row = conn.execute(f'SELECT COUNT(*) FROM "{tbl_name}"').fetchone()
                cnt = int(cnt_row[0]) if cnt_row else 0
            info["tables"][tbl_name] = {
                "columns": cols,
                "row_count": cnt,
                "create_sql": create_sql or "",
            }
            if cnt > 0:
                info["total_rows"] += cnt
        info["valid_sqlite"] = True
    except sqlite3.Error as exc:
        info["error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()
    return info


def discover_legacy_databases(
    source_dirs: Optional[Sequence[str]] = None,
    include_consolidated: bool = False,
) -> List[str]:
    """Findet alle aktiven .db-Dateien (ohne Backups/Snapshots/Browser-NSS-DBs/fremde Hermes-state.db)."""
    dirs = list(source_dirs) if source_dirs is not None else [
        DEFAULT_DATA_DIR,
        os.path.join(WORKSPACE_DIR, "memory"),
        *(["/opt/data"] if os.path.isdir("/opt/data") else []),
    ]
    found: List[str] = []
    seen: set[str] = set()
    skip_names = {"cert9.db", "key4.db"}

    for sdir in dirs:
        if not sdir or not os.path.isdir(sdir):
            continue
        is_hermes_opt_dir = os.path.normpath(sdir) == os.path.normpath("/opt/data")
        for entry in sorted(os.listdir(sdir)):
            if not entry.endswith(".db"):
                continue
            low = entry.lower()
            if low in skip_names:
                continue
            # Fremde, aktiv vom Hermes-Container beschriebene state.db in /opt/data nicht blind kopieren
            if source_dirs is None and is_hermes_opt_dir and low == "state.db":
                continue
            if not include_consolidated and low in CONSOLIDATED_DOMAINS:
                continue
            full = os.path.abspath(os.path.join(sdir, entry))
            if os.path.isfile(full) and full not in seen:
                seen.add(full)
                found.append(full)
    return found


def plan_consolidation(
    source_dirs: Optional[Sequence[str]] = None,
    target_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Erstellt einen vollstaendigen Dry-Run-Plan inklusive Kollisionsanalyse."""
    tgt_dir = os.path.abspath(target_dir or DEFAULT_DATA_DIR)
    legacy_paths = discover_legacy_databases(source_dirs=source_dirs, include_consolidated=False)
    sources = [_inspect_sqlite_file(p, fast_count=True) for p in legacy_paths]

    domains: Dict[str, Dict[str, Any]] = {
        d: {
            "target_path": os.path.join(tgt_dir, d),
            "source_files": [],
            "table_mappings": [],
            "collisions_resolved": [],
            "total_rows": 0,
        }
        for d in CONSOLIDATED_DOMAINS
    }

    # Pro Zieldomaene pruefen, ob zwei Quell-DBs denselben Tabellennamen mit abweichenden Spalten liefern
    seen_tables_per_domain: Dict[str, Dict[str, Tuple[str, List[str]]]] = {d: {} for d in CONSOLIDATED_DOMAINS}

    for src in sources:
        if not src["valid_sqlite"] or not src["tables"]:
            continue
        dom = src["target_domain"]
        dom_entry = domains[dom]
        dom_entry["source_files"].append(src["filename"])
        dom_entry["total_rows"] += src["total_rows"]
        src_stem = _sanitize_ident(os.path.splitext(src["filename"])[0])

        for tbl_name, tinfo in src["tables"].items():
            prev = seen_tables_per_domain[dom].get(tbl_name)
            if prev is None:
                target_table = tbl_name
                seen_tables_per_domain[dom][tbl_name] = (src["filename"], tinfo["columns"])
            elif prev[1] == tinfo["columns"]:
                # Identisches Schema (z. B. duplizierte Tabelle in memory/ und data/): sauber mergen
                target_table = tbl_name
            else:
                # Abweichendes Schema bei gleichem Namen: sauber mit Quell-Praefix isolieren
                target_table = f"{src_stem}__{tbl_name}"
                dom_entry["collisions_resolved"].append({
                    "source_file": src["filename"],
                    "source_table": tbl_name,
                    "target_table": target_table,
                    "conflicts_with": prev[0],
                })
            dom_entry["table_mappings"].append({
                "source_path": src["path"],
                "source_file": src["filename"],
                "source_table": tbl_name,
                "target_table": target_table,
                "columns": tinfo["columns"],
                "row_count": tinfo["row_count"],
            })

    return {
        "consolidated_active": is_consolidation_active(tgt_dir),
        "target_dir": tgt_dir,
        "legacy_files_found": len(sources),
        "legacy_files_with_tables": sum(1 for s in sources if s["valid_sqlite"] and s["tables"]),
        "target_domains": list(CONSOLIDATED_DOMAINS),
        "domains": domains,
        "sources": sources,
    }


def _rewrite_create_table_sql(create_sql: str, src_table: str, dst_table: str) -> str:
    """Macht CREATE [VIRTUAL] TABLE idempotent (IF NOT EXISTS) und benennt bei Kollision um."""
    sql = (create_sql or "").strip()
    if not sql:
        return ""
    if re.match(r"^CREATE\s+VIRTUAL\s+TABLE\b", sql, flags=re.IGNORECASE):
        sql = re.sub(
            r"^CREATE\s+VIRTUAL\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)",
            "CREATE VIRTUAL TABLE IF NOT EXISTS ",
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if src_table != dst_table:
            sql = re.sub(
                rf'(CREATE\s+VIRTUAL\s+TABLE\s+IF\s+NOT\s+EXISTS\s+)(["`\[]?){re.escape(src_table)}(["`\]]?)',
                rf'\1"{dst_table}"',
                sql,
                count=1,
                flags=re.IGNORECASE,
            )
        return sql
    sql = re.sub(
        r"^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)",
        "CREATE TABLE IF NOT EXISTS ",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if src_table != dst_table:
        sql = re.sub(
            rf'(CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+)(["`\[]?){re.escape(src_table)}(["`\]]?)',
            rf'\1"{dst_table}"',
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
    return sql


def _online_backup_file(src_path: str, dst_path: str) -> None:
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=10.0)
    dst = sqlite3.connect(dst_path, timeout=10.0)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def run_consolidation(
    source_dirs: Optional[Sequence[str]] = None,
    target_dir: Optional[str] = None,
    *,
    dry_run: bool = False,
    create_backup: bool = True,
    activate: bool = False,
) -> Dict[str, Any]:
    """Fuehrt die Konsolidierung aller Legacy-DBs in ops.db, business.db und memory.db aus."""
    plan = plan_consolidation(source_dirs=source_dirs, target_dir=target_dir)
    if dry_run:
        return {"status": "dry_run", **plan}

    tgt_dir = plan["target_dir"]
    os.makedirs(tgt_dir, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir: Optional[str] = None

    if create_backup:
        backup_dir = os.path.join(tgt_dir, "backups", f"pre_consolidation_{ts}")
        os.makedirs(backup_dir, exist_ok=True)
        for src in plan["sources"]:
            if src["valid_sqlite"] and src["tables"]:
                parent_tag = _sanitize_ident(os.path.basename(os.path.dirname(src["path"])))
                b_dst = os.path.join(backup_dir, f"{parent_tag}__{src['filename']}")
                _online_backup_file(src["path"], b_dst)

    migration_report: Dict[str, Any] = {}

    for dom in CONSOLIDATED_DOMAINS:
        dom_plan = plan["domains"][dom]
        dom_path = dom_plan["target_path"]
        migrated_tables = 0
        migrated_rows = 0
        warnings: List[str] = []

        conn = sqlite3.connect(dom_path, timeout=15.0)
        try:
            if os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes"):
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=10000;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _archon_consolidation_meta (
                    source_file TEXT NOT NULL,
                    source_table TEXT NOT NULL,
                    target_table TEXT NOT NULL,
                    source_rows INTEGER NOT NULL,
                    migrated_at TEXT NOT NULL,
                    PRIMARY KEY (source_file, source_table)
                )
                """
            )

            # Indizes und Schemas pro Quell-DB uebertragen
            grouped_by_src: Dict[str, List[Dict[str, Any]]] = {}
            for m in dom_plan["table_mappings"]:
                grouped_by_src.setdefault(m["source_path"], []).append(m)

            for src_path, mappings in grouped_by_src.items():
                src_info = next((s for s in plan["sources"] if s["path"] == src_path), None)
                if not src_info:
                    continue
                conn.execute("ATTACH DATABASE ? AS legacy_src", (src_path,))
                try:
                    with conn:
                        for m in mappings:
                            src_tbl = m["source_table"]
                            dst_tbl = m["target_table"]
                            tmeta = src_info["tables"].get(src_tbl) or {}
                            raw_create = str(tmeta.get("create_sql") or "").strip()
                            # Interne FTS5-Schattentabellen (*_data, *_idx, *_docsize, *_config, *_content)
                            # werden automatisch durch die CREATE VIRTUAL TABLE erzeugt -> nicht manuell anlegen
                            if any(
                                src_tbl.endswith(suf)
                                and src_tbl[:-len(suf)] in src_info["tables"]
                                and "VIRTUAL TABLE" in str(src_info["tables"][src_tbl[:-len(suf)]].get("create_sql") or "").upper()
                                for suf in ("_data", "_idx", "_docsize", "_config", "_content")
                            ):
                                continue
                            create_sql = _rewrite_create_table_sql(raw_create, src_tbl, dst_tbl)
                            if not create_sql:
                                continue
                            try:
                                conn.execute(create_sql)
                            except sqlite3.Error as tbl_err:
                                warnings.append(f"Tabelle {src_tbl}->{dst_tbl} uebersprungen: {tbl_err}")
                                continue

                            # Gemeinsame Spalten ermitteln (sicher bei Schema-Evolution)
                            dst_cols = [c[1] for c in conn.execute(f'PRAGMA main.table_info("{dst_tbl}")').fetchall()]
                            src_cols = [c[1] for c in conn.execute(f'PRAGMA legacy_src.table_info("{src_tbl}")').fetchall()]
                            common_cols = [c for c in src_cols if c in dst_cols]
                            if common_cols:
                                cols_quoted = ", ".join(f'"{c}"' for c in common_cols)
                                try:
                                    conn.execute(
                                        f'INSERT OR IGNORE INTO main."{dst_tbl}" ({cols_quoted}) '
                                        f'SELECT {cols_quoted} FROM legacy_src."{src_tbl}"'
                                    )
                                except sqlite3.Error as ins_err:
                                    warnings.append(f"Datenkopie {src_tbl}->{dst_tbl} uebersprungen: {ins_err}")

                            # Indizes der Original-Tabelle mitnehmen (nur wenn nicht umbenannt)
                            if src_tbl == dst_tbl:
                                idx_rows = conn.execute(
                                    "SELECT sql FROM legacy_src.sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                                    (src_tbl,),
                                ).fetchall()
                                for (idx_sql,) in idx_rows:
                                    safe_idx = re.sub(
                                        r"^CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS\b)",
                                        r"CREATE \1INDEX IF NOT EXISTS ",
                                        idx_sql.strip(),
                                        count=1,
                                        flags=re.IGNORECASE,
                                    )
                                    try:
                                        conn.execute(safe_idx)
                                    except sqlite3.Error as idx_err:
                                        warnings.append(f"Index fuer {dst_tbl} uebersprungen: {idx_err}")

                            cnt_after = conn.execute(f'SELECT COUNT(*) FROM main."{dst_tbl}"').fetchone()[0]
                            migrated_tables += 1
                            migrated_rows += int(m["row_count"])
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO _archon_consolidation_meta
                                    (source_file, source_table, target_table, source_rows, migrated_at)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (m["source_file"], src_tbl, dst_tbl, int(m["row_count"]), datetime.datetime.now(datetime.timezone.utc).isoformat()),
                            )
                            if int(cnt_after) < int(m["row_count"]):
                                warnings.append(
                                    f"Zeilenzahl-Hinweis {dst_tbl}: target={cnt_after} < source={m['row_count']}"
                                )
                finally:
                    conn.execute("DETACH DATABASE legacy_src")

            integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        finally:
            conn.close()

        migration_report[dom] = {
            "path": dom_path,
            "migrated_tables": migrated_tables,
            "source_rows_processed": migrated_rows,
            "collisions_resolved": dom_plan["collisions_resolved"],
            "integrity_check": integrity,
            "warnings": warnings,
        }

    manifest_data = {
        "active": bool(activate),
        "version": 1,
        "migrated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "backup_dir": backup_dir,
        "domains": {d: migration_report[d]["path"] for d in CONSOLIDATED_DOMAINS},
        "domain_map": CONSOLIDATION_DOMAIN_MAP,
    }
    manifest_path = get_manifest_path(tgt_dir)
    tmp_manifest = f"{manifest_path}.tmp.{os.getpid()}"
    with open(tmp_manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest_data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp_manifest, manifest_path)

    # Cache in db_paths leeren, falls Konsolidierung aktiviert wurde
    if activate:
        try:
            from backend import db_paths
            db_paths._RESOLVED_DB_CACHE.clear()
        except Exception as exc:
            logger.debug(f"[DBConsolidation] db_paths Cache-Reset uebersprungen: {exc}")

    return {
        "status": "success",
        "activated": bool(activate),
        "backup_dir": backup_dir,
        "manifest_path": manifest_path,
        "report": migration_report,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Archon OS SQLite DB-Konsolidierung (28 -> 3)")
    parser.add_argument("--plan", action="store_true", help="Nur Dry-Run-Plan anzeigen")
    parser.add_argument("--migrate", action="store_true", help="Migration ausfuehren")
    parser.add_argument("--activate", action="store_true", help="Konsolidierte 3-DB-Aufloesung aktivieren")
    parser.add_argument("--target-dir", default=DEFAULT_DATA_DIR, help="Zielverzeichnis fuer ops/business/memory.db")
    args = parser.parse_args()

    if args.migrate:
        res = run_consolidation(target_dir=args.target_dir, dry_run=False, create_backup=True, activate=args.activate)
    else:
        res = plan_consolidation(target_dir=args.target_dir)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
