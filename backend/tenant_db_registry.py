# -*- coding: utf-8 -*-
"""
backend/tenant_db_registry.py
=============================
Zentrale Mandanten-DB-Registry fuer alle Archon-v2 SQLite-Datenbanken
inkl. DSGVO Art. 17 Loeschroutine ueber alle registrierten Tabellen.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("archon_os.tenant_db_registry")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")

REGISTERED_V2_DBS: List[str] = [
    "taint_guard.db",
    "precedents.db",
    "workflow_dags.db",
    "flightlog.db",
    "compartment_vault.db",
    "frozen_workflows.db",
    "lcm_sessions.db",
    "eval_arena.db",
    "time_tracking.db",
    "watchdog_v2.db",
    "client_portal.db",
]


def sanitize_tenant_id(tenant_id: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", (tenant_id or "default").strip()).strip("_")
    return clean or "default"


def resolve_tenant_db_path(db_name: str, tenant_id: str = "default", base_dir: Optional[str] = None) -> str:
    """Loest einen DB-Namen physisch isoliert pro Mandant auf (data/tenants/<tid>/<db>).

    Benutzerentscheidung 22.11.2026: auch 'default' bekommt ein eigenes
    Mandantenverzeichnis. Vorher wurde 'default' auf data/*.db geroutet,
    wodurch DSGVO Art. 17 fuer den Primaermandanten wirkungslos war.
    """
    safe_db = os.path.basename(db_name)
    root = base_dir or DEFAULT_DATA_DIR
    tid = sanitize_tenant_id(tenant_id)
    t_dir = os.path.join(root, "tenants", tid)
    os.makedirs(t_dir, exist_ok=True)
    return os.path.join(t_dir, safe_db)


def gdpr_erase_subject_data(
    subject_identifier: str,
    tenant_id: str = "default",
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    DSGVO Art. 17 Loeschroutine: entfernt Zeilen mit `subject_identifier`
    (z. B. E-Mail oder Kundenname) aus allen vorhandenen registrierten v2-DBs
    des angegebenen Mandanten.
    """
    needle = (subject_identifier or "").strip()
    if len(needle) < 3:
        raise ValueError("subject_identifier muss mindestens 3 Zeichen enthalten.")

    deleted_summary: Dict[str, int] = {}
    # Audit v3 1.3.6: LIKE-Wildcards im Suchbegriff escapen — '%___%' darf nicht zum
    # Tabellenvolltreffer werden. ESCAPE-Konvention: Backslash.
    escaped_needle = (
        (subject_identifier or "").strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    like_val = f"%{escaped_needle}%"
    # GoBD/Compliance-Ausschluss (Audit v3 1.3.6): Diese Tabellen werden NIE per
    # Art.-17-Skript geloescht (Hashketten-/Belegpersistenz).
    protected_tables = {
        "audit_log", "erp_documents", "erp_document_lines",
        "treasury_transactions", "gdpr_audit_log", "receipts", "invoices", "learnings",
    }

    # D03/HIGH: alle 11 REGISTERED_V2_DBS ueber den physischen
    # Mandanten-Resolver erreichen. `tenant_context.resolve_active_db()` lehnt
    # diese Namen ab (nur ISOLATED/CONSOLIDATED) — ein stilles `continue` liess
    # Art.17 bisher genau dort ins Leere laufen.
    # Resolve-Fehler werden gesammelt und am Ende als HARTER Fehler geworfen:
    # eine Art.17-Quittung darf niemals vorgetaeuscht werden (HTTP 500).
    from backend.db_paths import APP_DATA_DIR, get_db_connection

    v2_dbs = list(REGISTERED_V2_DBS)
    core_dbs = [
        "business.db", "ops.db", "memory.db", "crm.db", "erp.db",
        "contracts.db", "deals.db", "agentic_memory.db",
    ]
    scan_dbs = list(dict.fromkeys(v2_dbs + core_dbs))
    resolver_errors: List[str] = []

    for db_name in scan_dbs:
        try:
            if db_name in v2_dbs:
                db_path = resolve_tenant_db_path(db_name, tenant_id, base_dir=APP_DATA_DIR)
            else:
                # Kern-/konsolidierte DBs: autoritativer Resolver (mit
                # Legacy-Migrationslogik). Kein Fallback auf eine falsche Datei.
                resolved_name = db_name
                try:
                    from backend.db_consolidation import is_consolidation_active
                    if db_name == "agentic_memory.db" and is_consolidation_active(APP_DATA_DIR):
                        resolved_name = "memory.db"
                except Exception as exc:
                    logger.error(
                        "[TenantDB] Konsolidierungscheck für %s fehlgeschlagen: %s",
                        db_name, exc,
                    )
                    resolver_errors.append(f"{db_name}: Konsolidierungscheck: {exc}")
                    # Weitere DBs pruefen, um ALLE Fehler zu sammeln — am Ende
                    # folgt der HARTE Abbruch (keine success-Quittung).
                    continue
                from backend.tenant_context import tenant_context
                db_path = tenant_context.resolve_active_db(resolved_name, tenant_id)
        except Exception as exc:
            logger.error("[TenantDB] Art.17-Resolver %s fehlgeschlagen: %s", db_name, exc)
            resolver_errors.append(f"{db_name}: {exc}")
            continue
        if not os.path.exists(db_path):
            continue
        # D03/HIGH: zentrale Verbindung — setzt busy_timeout=5000 (SSOT) und
        # PRAGMA foreign_keys=ON (kein stiller Bruch von ON DELETE CASCADE).
        conn = get_db_connection(db_path)
        try:
            tables = [
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            ]
            total_del = 0
            for tbl in tables:
                safe_tbl = str(tbl).replace('"', '""')
                if str(tbl).lower() in protected_tables:
                    continue  # audit_log / erp_documents: GoBD-schutzwuerdig
                # KRITISCH: vorher nur TEXT/leer — VARCHAR, CHAR, CLOB, JSON
                # und NUMERIC-Spalten mit personenbezogenen Daten (IBAN,
                # Telefon, contact_email, nachrichtenverlauf JSON) wurden
                # uebersehen → Art.-17-Loeschung unvollstaendig.
                _text_types = ("TEXT", "VARCHAR", "CHAR", "CLOB", "JSON", "STRING", "NVARCHAR", "NCHAR", "")
                cols = [
                    r[1] for r in conn.execute(f'PRAGMA table_info("{safe_tbl}")').fetchall()
                    if any(str(r[2] or "").upper().startswith(t) for t in _text_types)
                ]
                if not cols:
                    continue
                # Art. 17: NUR die tatsächlich betroffenen TEXT-Spalten
                # anonymisieren. Ein DELETE ganzer Zeilen würde z. B.
                # erp_document_lines löschen, während erp_documents die
                # Beträge behält — GoBD-Bruch und Buchhaltungskorruptur.
                safe_cols = [str(c).replace('"', '""') for c in cols]
                esc = " ESCAPE '\\'"
                set_clause = ", ".join(
                    f'"{c}" = CASE WHEN "{c}" LIKE ?{esc} THEN ? ELSE "{c}" END'
                    for c in safe_cols
                )
                where_clause = " OR ".join(f'"{c}" LIKE ?{esc}' for c in safe_cols)
                anonymized = "[ANONYMISIERT_DSGVO_ART17]"
                params: list = []
                for _c in safe_cols:
                    params.extend([like_val, anonymized])
                params.extend([like_val] * len(safe_cols))
                cur = conn.execute(
                    f'UPDATE "{safe_tbl}" SET {set_clause} WHERE {where_clause}',
                    params,
                )
                total_del += cur.rowcount
            conn.commit()
            if total_del > 0:
                deleted_summary[db_name] = total_del
        finally:
            conn.close()

    if resolver_errors:
        raise RuntimeError(
            "DSGVO Art.17 unvollständig — Resolverfehler: " + "; ".join(resolver_errors)
        )

    return {
        "tenant_id": sanitize_tenant_id(tenant_id),
        "subject": needle,
        "deleted_by_db": deleted_summary,
        "total_deleted_rows": sum(deleted_summary.values()),
    }
