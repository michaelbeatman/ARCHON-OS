# -*- coding: utf-8 -*-
"""
backend/tenant_db_registry.py
=============================
Zentrale Mandanten-DB-Registry fuer alle Archon-v2 SQLite-Datenbanken
inkl. DSGVO Art. 17 Loeschroutine ueber alle registrierten Tabellen.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

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
    """Loest einen DB-Namen physisch isoliert pro Mandant auf (data/tenants/<tid>/<db>)."""
    safe_db = os.path.basename(db_name)
    root = base_dir or DEFAULT_DATA_DIR
    tid = sanitize_tenant_id(tenant_id)
    if tid == "default":
        return os.path.join(root, safe_db)
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
    like_val = f"%{needle}%"

    for db_name in REGISTERED_V2_DBS:
        db_path = resolve_tenant_db_path(db_name, tenant_id=tenant_id, base_dir=base_dir)
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            tables = [
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            ]
            total_del = 0
            for tbl in tables:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall() if str(r[2]).upper().startswith("TEXT") or r[2] == ""]
                if not cols:
                    continue
                where_clause = " OR ".join(f"{c} LIKE ?" for c in cols)
                cur = conn.execute(f"DELETE FROM {tbl} WHERE {where_clause}", [like_val] * len(cols))
                total_del += cur.rowcount
            conn.commit()
            if total_del > 0:
                deleted_summary[db_name] = total_del
        finally:
            conn.close()

    return {
        "tenant_id": sanitize_tenant_id(tenant_id),
        "subject": needle,
        "deleted_by_db": deleted_summary,
        "total_deleted_rows": sum(deleted_summary.values()),
    }
