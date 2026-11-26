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
- Aktivierung ueber VERSIONIERTES Manifest `config/db_consolidated.json`
  (oder ENV `ARCHON_DB_CONSOLIDATED=1`), niemals mehr ueber das gitignored
  `data/.db_consolidated.json` (D03/HIGH: frischer Clone war inaktiv).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import shutil
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.db_paths import (  # F-013/F015: SSOT busy_timeout
    APP_DATA_DIR,
    DB_BUSY_TIMEOUT_MS,
    DB_BUSY_TIMEOUT_S,
)

logger = logging.getLogger("archon.db_consolidation")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
CONSOLIDATED_DOMAINS = ("ops.db", "business.db", "memory.db")
MANIFEST_FILENAME = "db_consolidated.json"
# Versioniertes Artefakt ausserhalb des gitignored data/-Verzeichnisses.
VERSIONED_MANIFEST_PATH = os.path.join(WORKSPACE_DIR, "config", MANIFEST_FILENAME)
LEGACY_MANIFEST_FILENAME = ".db_consolidated.json"

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
    "taint_guard.db": "ops.db",
    "passkey_hitl.db": "ops.db",
    "workflow_templates.db": "ops.db",
    "flightlog.db": "ops.db",
    "lcm_sessions.db": "ops.db",
    "watchdog_v2.db": "ops.db",
    "agent_scorecard.db": "ops.db",
    "telemetry.db": "ops.db",
    "precedent_log.db": "ops.db",
    "precedents.db": "ops.db",
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
    "time_tracking.db": "business.db",
    "client_portal.db": "business.db",
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


def get_schema_versions(target_dir: Optional[str] = None) -> Dict[str, int]:
    """P2: user_version aller (auch nicht konsolidierten) DBs auslesen.

    Damit ist die Schema-Version zentral inspizierbar, statt dass ~155
    ad-hoc CREATE/ALTER-Statements ohne Versionsmarke nebeneinander stehen.
    """
    base = os.path.abspath(target_dir or DEFAULT_DATA_DIR)
    versions: Dict[str, int] = {}
    names = list(CONSOLIDATION_DOMAIN_MAP.keys()) + list(CONSOLIDATED_DOMAINS)
    seen = set()
    for name in names:
        path = os.path.join(base, name)
        if path in seen or not os.path.isfile(path) or os.path.getsize(path) == 0:
            continue
        seen.add(path)
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=DB_BUSY_TIMEOUT_S)
            try:
                versions[name] = int(conn.execute("PRAGMA user_version").fetchone()[0])
            finally:
                conn.close()
        except Exception:
            continue
    return versions


def get_manifest_path(target_dir: Optional[str] = None) -> str:
    """D03/HIGH: versioniertes Manifest unter config/, nicht im gitignored data/.

    Explizite target_dirs (Tests/Container-Isolation) behalten ihr lokales
    Manifest; der Produktionsdefault zeigt auf ``config/db_consolidated.json``.
    """
    if target_dir is None or os.path.abspath(target_dir) == os.path.abspath(DEFAULT_DATA_DIR):
        return VERSIONED_MANIFEST_PATH
    return os.path.join(os.path.abspath(target_dir), MANIFEST_FILENAME)


def _manifest_active(path: str) -> Optional[bool]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(isinstance(data, dict) and data.get("active"))
    except (OSError, ValueError) as exc:
        logger.warning(f"[DBConsolidation] Manifest nicht lesbar ({path}): {exc}")
        return None


def is_consolidation_active(target_dir: Optional[str] = None) -> bool:
    """True, wenn die 3-DB-Architektur per Env oder VERSIONIERTEM Manifest aktiv ist."""
    env_flag = os.environ.get("ARCHON_DB_CONSOLIDATED", "").strip().lower()
    if env_flag in ("1", "true", "yes"):
        return True
    if env_flag in ("0", "false", "no"):
        return False
    active = _manifest_active(get_manifest_path(target_dir))
    if active is not None:
        return active
    # Rueckwaertskompatibilitaet: das alte, gitignored Manifest darf gelesen
    # werden, ist aber NIE mehr Schreibziel (sonst erneut nicht reproduzierbar).
    if target_dir is None or os.path.abspath(target_dir) == os.path.abspath(DEFAULT_DATA_DIR):
        legacy = os.path.join(DEFAULT_DATA_DIR, LEGACY_MANIFEST_FILENAME)
        legacy_active = _manifest_active(legacy)
        if legacy_active:
            logger.warning(
                "[DBConsolidation] Altes Manifest %s ist aktiv — bitte nach config/ migrieren.",
                legacy,
            )
            return True
    return False


def _sanitize_ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip()) or "tbl"


def _full_schema_signature(tinfo: Dict[str, Any]) -> Tuple:
    """P2: vollstaendige Signatur statt nur Spaltennamen.

    Vorher verglich plan_consolidation nur `tinfo["columns"]` (eine Liste
    von Namen). Zwei Tabellen mit gleichen Namen, aber unterschiedlichen
    Typen/PK/NOT NULL wurden zusammengefuehrt; CREATE TABLE IF NOT EXISTS
    liess die erste gewinnen und INSERT OR IGNORE verwarf Zeilen still.
    Die CREATE-SQL enthaelt Typen, PK, Constraints und Defaultwerte.
    """
    sql = str(tinfo.get("create_sql") or "")
    # Nur Whitespaces/Case normalisieren — semantisch relevante Unterschiede
    # (Typen, NOT NULL, PK) bleiben erhalten.
    normalized = re.sub(r"\s+", " ", sql).strip().lower().rstrip(";")
    return (tuple(tinfo.get("columns") or []), normalized)


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
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=DB_BUSY_TIMEOUT_S)
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
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
        # D03/HIGH: ARCHON_DATA_DIR ist bei Test-/Container-Isolation die
        # kanonische Quelle — vorher wurden 0 Quellen gefunden und "success"
        # gemeldet. APP_DATA_DIR zuerst, DEFAULT_DATA_DIR als Legacy-Ziel.
        APP_DATA_DIR,
        DEFAULT_DATA_DIR,
        os.path.join(WORKSPACE_DIR, "memory"),
        *(["/opt/data"] if os.path.isdir("/opt/data") else []),
    ]
    found: List[str] = []
    seen: set[str] = set()
    skip_names = {"cert9.db", "key4.db"}

    # Die echte Hermes-Kanban-DB liegt in ~/.hermes, NICHT in data/. Ohne
    # diese explizite Quelle wurde die 41-Spalten-Tasks-Tabelle nie nach
    # ops.db migriert (statt dessen landete die 8-Spalten-Agent-Tabelle aus
    # agentic_memory.db dort) —的经典 Split-Brain.
    if source_dirs is None:
        hermes_kanban = os.path.expanduser("~/.hermes/kanban.db")
        if os.path.isfile(hermes_kanban) and os.path.getsize(hermes_kanban) > 0:
            found.append(os.path.abspath(hermes_kanban))
            seen.add(os.path.abspath(hermes_kanban))

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
    seen_tables_per_domain: Dict[str, Dict[str, Tuple[str, Tuple]]] = {d: {} for d in CONSOLIDATED_DOMAINS}

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
            signature = _full_schema_signature(tinfo)
            if prev is None:
                target_table = tbl_name
                seen_tables_per_domain[dom][tbl_name] = (src["filename"], signature)
            elif prev[1] == signature:
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


def _missing_source_rows(
    conn: sqlite3.Connection,
    src_table: str,
    dst_table: str,
    columns: List[str],
    alias: str = "legacy_src",
) -> int:
    """Anzahl Quellzeilen, die im Ziel wirklich fehlen.

    `INSERT OR IGNORE` meldet bei einem idempotenten Zweitlauf rowcount=0,
    obwohl alle Daten da sind. Nur dieser Abgleich unterscheidet "../already
    present" von echtem DATENVERLUST.
    """
    if not columns:
        return 0
    # d03 / #20: IMMER alle gemeinsamen Spalten vergleichen, NICHT nur pk_cols!
    # Vorher gab ein PK-Only-Check bei PK-Kollision mit abweichendem Inhalt
    # (Quelle A: id=1,'Alice'; Quelle B: id=1,'Bob') faelschlich 0 zurueck,
    # obwohl INSERT OR IGNORE 'Bob' still verworfen hatte.
    # Bei einem idempotenten Zweitlauf sind alle Spalten identisch -> 0;
    # bei divergierender PK-Kollision -> > 0 -> harter Abbruch (DATENVERLUST).
    cond = " AND ".join(f'd."{c}" IS s."{c}"' for c in columns)
    sql = (
        f'SELECT COUNT(*) FROM "{alias}"."{src_table}" s '
        f'WHERE NOT EXISTS (SELECT 1 FROM main."{dst_table}" d WHERE {cond})'
    )
    try:
        return int(conn.execute(sql).fetchone()[0])
    except sqlite3.Error as exc:
        # KRITISCH (Audit 23.11.2026): "0" ist hier KEIN konservativer Wert,
        # sondern behauptet "kein Verlust", obwohl die Prüfung fehlgeschlagen
        # ist. Fail-closed: Migration hart abbrechen.
        raise RuntimeError(
            f"Verifikation der migrierten Zeilen fehlgeschlagen "
            f"({src_table}->{dst_table}): {exc}"
        ) from exc


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
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=DB_BUSY_TIMEOUT_S)
    dst = sqlite3.connect(dst_path, timeout=DB_BUSY_TIMEOUT_S)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _snapshot_target_for_rollback(dom_path: str, rollback_dir: str, tag: str) -> Dict[str, Any]:
    """Sichert eine bereits existierende Ziel-DB vor der Konsolidierung.

    D03/MED: ohne diesen Snapshot koennen die Ziel-DBs bei einem spaeteren
    DATENVERLUST-Abbruch teil-migriert zurueckbleiben.
    """
    os.makedirs(rollback_dir, exist_ok=True)
    snap: Dict[str, Any] = {
        "path": os.path.abspath(dom_path),
        "existed_before": os.path.exists(dom_path),
        "backup_path": os.path.join(rollback_dir, f"{tag}__{os.path.basename(dom_path)}"),
    }
    if snap["existed_before"]:
        _online_backup_file(snap["path"], snap["backup_path"])
    return snap


def _rollback_targets_from_snapshots(snapshots: List[Dict[str, Any]]) -> List[str]:
    """Stellt die Ziel-DBs bei DATENVERLUST wieder her (kein Teilstand)."""
    restored: List[str] = []
    for snap in snapshots:
        path = snap.get("path")
        if not path:
            continue
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = path + suffix
            try:
                if os.path.exists(sidecar):
                    os.unlink(sidecar)
            except OSError:
                pass
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
        if snap.get("existed_before") and os.path.isfile(snap.get("backup_path") or ""):
            _online_backup_file(snap["backup_path"], path)
            restored.append(path)
    return restored


def run_consolidation(
    source_dirs: Optional[Sequence[str]] = None,
    target_dir: Optional[str] = None,
    *,
    dry_run: bool = False,
    create_backup: bool = True,
    activate: bool = False,
    deactivate: bool = False,
    confirm_deactivate: bool = False,
) -> Dict[str, Any]:
    """Fuehrt die Konsolidierung aller Legacy-DBs in ops.db, business.db und memory.db aus.

    D03-H3: Das Manifest ist ein *Zustand*, kein Migrations-Log. Ein normaler
    ``--migrate`` (``activate=False, deactivate=False``) aendert ihn nicht —
    ein bestehendes ``active=true`` bleibt byte-identisch erhalten. Nur die
    expliziten Flags ``--activate``/``--deactivate`` schreiben das Manifest;
    ``--deactivate`` zusaetzlich nur mit Bestaetigung, Audit und Backup des
    alten Manifests.
    """
    # Validierung VOR jeder migration (kein Teilstand bei abgelehntem Flag).
    if activate and deactivate:
        raise ValueError("--activate und --deactivate schliessen sich aus.")
    if deactivate and not confirm_deactivate:
        raise ValueError(
            "--deactivate erfordert explizite Bestaetigung "
            "(confirm_deactivate=True)."
        )

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

    # D03/MED: Rollback-Snapshots der Ziel-DBs. Bei DATENVERLUST werden die
    # committeten Teilmigrationen damit vor dem Abbruch zurueckgespielt, statt
    # teil-migrierte Ziel-DBs ohne Manifest zurueckzulassen.
    rollback_dir = os.path.join(tgt_dir, "backups", f"rollback_{ts}")
    target_snapshots: List[Dict[str, Any]] = []
    for _dom, _dom_plan in plan["domains"].items():
        target_snapshots.append(
            _snapshot_target_for_rollback(
                _dom_plan["target_path"], rollback_dir, _sanitize_ident(_dom)
            )
        )

    migration_report: Dict[str, Any] = {}

    for dom in CONSOLIDATED_DOMAINS:
        dom_plan = plan["domains"][dom]
        dom_path = dom_plan["target_path"]
        migrated_tables = 0
        migrated_rows = 0
        warnings: List[str] = []

        conn = sqlite3.connect(dom_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0)
        integrity = "not_run"
        try:
            wal_enabled = os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes")
            if wal_enabled:
                conn.execute("PRAGMA journal_mode=WAL;")
            # synchronous ist verbindungsbezogen (D03/MED) — IMMER setzen.
            if wal_enabled:
                conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            # D03/HIGH: deklarierte FK (ON DELETE CASCADE) muessen auch beim
            # Migrieren wirksam sein, sonst entstehen verwaiste Zeilen.
            conn.execute("PRAGMA foreign_keys=ON;")
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

            # Indizes und Schemas pro Quell-DB uebertragen.
            grouped_by_src: Dict[str, List[Dict[str, Any]]] = {}
            for m in dom_plan["table_mappings"]:
                grouped_by_src.setdefault(m["source_path"], []).append(m)

            # D03/HIGH: EINE Transaktion pro Domaene ueber ALLE Quellen.
            # ATTACH ist innerhalb einer Transaktion in SQLite verboten —
            # deshalb werden alle Quellen VOR BEGIN IMMEDIATE angehaengt.
            aliases: Dict[str, str] = {}
            for idx, src_path in enumerate(grouped_by_src):
                alias = f"legacy_src_{idx}"
                aliases[src_path] = alias
                conn.execute(f"ATTACH DATABASE ? AS {alias}", (src_path,))

            try:
                conn.execute("BEGIN IMMEDIATE")
                for src_path, mappings in grouped_by_src.items():
                    alias = aliases[src_path]
                    src_info = next((s for s in plan["sources"] if s["path"] == src_path), None)
                    if not src_info:
                        continue
                    for m in mappings:
                        src_tbl = m["source_table"]
                        dst_tbl = m["target_table"]
                        # Plan-Zahl kann -1 sein (fast_count bei DBs > 25 MB).
                        # Nach dem ATTACH wird sie durch eine exakte Zaehlung
                        # ersetzt — nie als gueltige Zahl verwenden.
                        src_count = int(m["row_count"])
                        tmeta = src_info["tables"].get(src_tbl) or {}
                        raw_create = str(tmeta.get("create_sql") or "").strip()
                        # Interne FTS5-Schattentabellen werden automatisch
                        # durch die CREATE VIRTUAL TABLE erzeugt.
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
                            # D03/HIGH: kein "uebersprungen" mehr — jede
                            # Ausnahme ist DATENVERLUST und bricht ab.
                            raise RuntimeError(
                                f"DATENVERLUST {src_tbl}->{dst_tbl}: CREATE fehlgeschlagen: {tbl_err}"
                            ) from tbl_err

                        # Gemeinsame Spalten ermitteln (sicher bei Schema-Evolution)
                        dst_cols = [c[1] for c in conn.execute(f'PRAGMA main.table_info("{dst_tbl}")').fetchall()]
                        src_cols = [c[1] for c in conn.execute(f'PRAGMA {alias}.table_info("{src_tbl}")').fetchall()]
                        common_cols = [c for c in src_cols if c in dst_cols]
                        # D03/HIGH: nur in der Quelle vorhandene Spalten wurden
                        # frueher still verworfen — explizit diagnostizieren.
                        source_only = [c for c in src_cols if c not in dst_cols]
                        if source_only:
                            warnings.append(
                                f"DATENVERLUST {src_tbl}->{dst_tbl}: Quellspalten ohne Ziel: "
                                + ", ".join(source_only)
                            )
                        if common_cols:
                            cols_quoted = ", ".join(f'"{c}"' for c in common_cols)
                            try:
                                cur = conn.execute(
                                    f'INSERT OR IGNORE INTO main."{dst_tbl}" ({cols_quoted}) '
                                    f'SELECT {cols_quoted} FROM "{alias}"."{src_tbl}"'
                                )
                                inserted = int(cur.rowcount or 0)
                                exact = conn.execute(
                                    f'SELECT COUNT(*) FROM "{alias}"."{src_tbl}"'
                                ).fetchone()[0]
                                src_count = int(exact)
                                if inserted < src_count:
                                    missing = _missing_source_rows(
                                        conn, src_tbl, dst_tbl, common_cols, alias=alias
                                    )
                                    if missing > 0:
                                        warnings.append(
                                            f"DATENVERLUST {src_tbl}->{dst_tbl}: "
                                            f"{missing}/{src_count} Zeilen fehlen im Ziel "
                                            "(PK/UNIQUE/NOT NULL-Konflikt)"
                                        )
                            except sqlite3.Error as ins_err:
                                raise RuntimeError(
                                    f"DATENVERLUST {src_tbl}->{dst_tbl}: Datenkopie fehlgeschlagen: {ins_err}"
                                ) from ins_err

                        # Indizes der Original-Tabelle mitnehmen (nur wenn nicht umbenannt)
                        if src_tbl == dst_tbl:
                            idx_rows = conn.execute(
                                f"SELECT sql FROM {alias}.sqlite_master "
                                "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
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
                                    warnings.append(
                                        f"DATENVERLUST Index {dst_tbl} nicht migriert: {idx_err}"
                                    )

                        migrated_tables += 1
                        migrated_rows += src_count
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO _archon_consolidation_meta
                                (source_file, source_table, target_table, source_rows, migrated_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (m["source_file"], src_tbl, dst_tbl, src_count, datetime.datetime.now(datetime.timezone.utc).isoformat()),
                        )

                # D03/HIGH: relationale Konsistenz der Zieldomäne fail-closed pruefen.
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_violations:
                    warnings.append(
                        f"DATENVERLUST {dom}: {len(fk_violations)} FK-Verletzung(en) nach Migration"
                    )
                integrity = str(conn.execute("PRAGMA integrity_check;").fetchone()[0])
                if integrity.lower() != "ok":
                    warnings.append(f"DATENVERLUST {dom}: integrity_check={integrity}")
                if not warnings:
                    # P2: Schema-Versionierung nur bei sauberer Migration.
                    conn.execute("PRAGMA user_version = 1;")
                conn.commit()
            except BaseException as exc:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                warnings.append(f"DATENVERLUST {dom}: Migration abgebrochen: {exc}")
            finally:
                for alias in aliases.values():
                    try:
                        conn.execute(f"DETACH DATABASE {alias}")
                    except sqlite3.Error:
                        pass
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

    # DATENVERLUST ist kein Hinweis, sondern ein Abbruchgrund: INSERT OR IGNORE
    # hat Zeilen still verworfen. Kein Manifest, keine Aktivierung, kein
    # "success" — sonst waere die Konsolidierung ein Datenverlust-Versprechen.
    # D03/HIGH: JEDER Warning ist DATENVERLUST (CREATE-/INSERT-/Indexfehler,
    # Quellspalten ohne Ziel, FK-/Integritätsverletzung). Kein Filtern nach
    # Schluesselwort mehr — ein "uebersprungen" durfte frueher durchgewinkt
    # werden. Manifest wird NUR bei leerer warnings + integrity ok geschrieben.
    data_loss = [
        f"{dom}: {w}"
        for dom, report in migration_report.items()
        for w in report.get("warnings", [])
    ]
    integrity_failures = [
        f"{dom}: integrity_check={report.get('integrity_check')}"
        for dom, report in migration_report.items()
        if str(report.get("integrity_check", "")).lower() != "ok"
    ]
    # Integritaetsfehler sind ebenfalls DATENVERLUST und laufen ueber denselben
    # Abbruchpfad (eine Branch, ein Rollback).
    data_loss.extend(integrity_failures)
    if data_loss:
        # D03/MED: zuerst alle Ziel-DBs aus den Snapshots zuruecks-spielen,
        # DANN abbrechen. Es bleibt kein committeter Teilstand zurueck.
        restored = _rollback_targets_from_snapshots(target_snapshots)
        shutil.rmtree(rollback_dir, ignore_errors=True)
        raise RuntimeError(
            "Konsolidierung abgebrochen — DATENVERLUST erkannt "
            f"({len(restored)} Ziel-DB(s) zurueckgerollt): " + "; ".join(data_loss)
        )

    shutil.rmtree(rollback_dir, ignore_errors=True)

    # D03-H3: Manifest NUR bei expliziter, tatsaechlicher Zustandsaenderung
    # schreiben. `--migrate` ohne Flags laesst ein bestehendes active=true
    # unberuehrt (byte-identisch) — frueher wurde es still auf false gesetzt
    # und die 28->3-Konsolidierung damit deaktiviert.
    manifest_path = get_manifest_path(tgt_dir)
    existing_active = _manifest_active(manifest_path)
    requested_active = True if activate else (False if deactivate else None)
    manifest_state_changed = (
        requested_active is not None and requested_active != existing_active
    )
    manifest_written = False
    manifest_backup_path: Optional[str] = None
    audit_event_id: Optional[str] = None

    if manifest_state_changed:
        # D03-H3: Backup des ALTEN Manifests vor jeder Deaktivierung. Der
        # fruehere Zustand muss wiederherstellbar bleiben (GoBD/Revisionssicherheit).
        if deactivate and os.path.isfile(manifest_path):
            manifest_backup_path = f"{manifest_path}.pre_deactivate.{ts}.bak"
            with open(manifest_path, "rb") as old_fh:
                old_bytes = old_fh.read()
            tmp_backup = f"{manifest_backup_path}.tmp.{os.getpid()}"
            with open(tmp_backup, "wb") as bak_fh:
                bak_fh.write(old_bytes)
                bak_fh.flush()
                os.fsync(bak_fh.fileno())
            os.replace(tmp_backup, manifest_backup_path)

        audit_payload = {
            "manifest_path": os.path.abspath(manifest_path),
            "previous_active": existing_active,
            "requested_active": requested_active,
            "action": "activate" if activate else "deactivate",
            "manifest_backup": manifest_backup_path,
            "migrated_domains": list(CONSOLIDATED_DOMAINS),
        }
        try:
            from backend.audit_log import chained_audit_log

            audit_event = chained_audit_log.record_event(
                category="db_consolidation",
                action=(
                    "consolidation_activated" if activate
                    else "consolidation_deactivated"
                ),
                agent_id="system",
                payload=audit_payload,
            )
            audit_event_id = audit_event.get("event_id")
        except Exception as exc:
            logger.error(
                "[DBConsolidation][ALARM] Audit der Manifest-Zustaenderung "
                "fehlgeschlagen: %s", exc,
            )
            # Deaktivierung ist destruktiv: ohne Auditnachweis KEIN Schreiben.
            if deactivate:
                raise RuntimeError(
                    "Deaktivierung der Konsolidierung verweigert: "
                    f"Auditnachweis fehlt ({exc})."
                ) from exc

        manifest_data = {
            "active": bool(requested_active),
            "version": 1,
            "migrated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "backup_dir": backup_dir,
            "domains": {d: migration_report[d]["path"] for d in CONSOLIDATED_DOMAINS},
            "domain_map": CONSOLIDATION_DOMAIN_MAP,
        }
        tmp_manifest = f"{manifest_path}.tmp.{os.getpid()}"
        with open(tmp_manifest, "w", encoding="utf-8") as fh:
            json.dump(manifest_data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_manifest, manifest_path)
        manifest_written = True

    # Cache in db_paths leeren, sobald sich der konsolidierte Zustand geaendert hat.
    if manifest_state_changed:
        try:
            from backend import db_paths
            db_paths._RESOLVED_DB_CACHE.clear()
        except Exception as exc:
            logger.debug(f"[DBConsolidation] db_paths Cache-Reset uebersprungen: {exc}")

    return {
        "status": "success",
        "activated": bool(activate),
        "deactivated": bool(deactivate),
        "manifest_written": manifest_written,
        "manifest_state_changed": manifest_state_changed,
        "manifest_active": bool(requested_active) if manifest_written else existing_active,
        "manifest_backup_path": manifest_backup_path,
        "audit_event_id": audit_event_id,
        "backup_dir": backup_dir,
        "manifest_path": manifest_path,
        "report": migration_report,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Archon OS SQLite DB-Konsolidierung (28 -> 3)")
    parser.add_argument("--plan", action="store_true", help="Nur Dry-Run-Plan anzeigen")
    parser.add_argument("--migrate", action="store_true", help="Migration ausfuehren (Manifest-Zustand bleibt unberuehrt)")
    parser.add_argument("--activate", action="store_true", help="Konsolidierte 3-DB-Aufloesung aktivieren")
    parser.add_argument(
        "--deactivate", action="store_true",
        help="Konsolidierung deaktivieren (nur mit --confirm-deactivate; Audit + Manifest-Backup)",
    )
    parser.add_argument(
        "--confirm-deactivate", action="store_true",
        help="Bestaetigung fuer --deactivate",
    )
    parser.add_argument("--target-dir", default=DEFAULT_DATA_DIR, help="Zielverzeichnis fuer ops/business/memory.db")
    args = parser.parse_args()

    if args.migrate or args.activate or args.deactivate:
        res = run_consolidation(
            target_dir=args.target_dir,
            dry_run=False,
            create_backup=True,
            activate=args.activate,
            deactivate=args.deactivate,
            confirm_deactivate=args.confirm_deactivate,
        )
    else:
        res = plan_consolidation(target_dir=args.target_dir)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
