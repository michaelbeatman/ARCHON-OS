"""
backend/tenant_context.py
=========================
M43 — Multi-Mandanten-Kontext & SQLite-DB-Isolation (Holding / Operative GmbH / SPV).

Stellt pro Mandant bereit:
1. Isolierte SQLite-Datenbankpfade unter `data/tenants/<company_id>/` für:
   - erp.db, kanban.db, crm.db, contracts.db, deals.db
2. Automatische Schema-Initialisierung (WAL-Modus) für alle 5 Mandanten-DBs
   sowie verlustfreie Erst-Migration bestehender Primärdaten.
3. Getrennte Nummernkreise (ANG, AB, RE, GS, VTR) mit atomarem Zähler je Mandant.
4. Mandanten-Metadaten (Gesellschaftsform: holding | operative_gmbh | spv,
   Steuernummer/USt-IdNr., Bankverbindung, Briefbogen) + GoBD-Audit-Logging.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from archon.core.runtime import WORKSPACE_DIR

ISOLATED_TENANT_DBS = ("erp.db", "kanban.db", "crm.db", "contracts.db", "deals.db")
PRIMARY_TENANT_IDS = frozenset({"archon-systems", "default"})

DEFAULT_NUMBER_PREFIXES = {
    "invoice": "RE",
    "offer": "ANG",
    "order": "AB",
    "credit_note": "GS",
    "contract": "VTR",
}


def sanitize_tenant_id(company_id: Optional[str]) -> str:
    raw = str(company_id or "default").strip()
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_")
    return cleaned or "default"


def _db_has_tables(db_path: str) -> bool:
    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return False
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
        try:
            row = con.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
            return row is not None
        finally:
            con.close()
    except Exception:
        return False


def _atomic_sqlite_backup(src_path: str, dst_path: str) -> bool:
    """Kopiert eine bestehende SQLite-DB konsistent per Online-Backup-API."""
    if not _db_has_tables(src_path):
        return False
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=10.0)
    dst = sqlite3.connect(dst_path, timeout=10.0)
    try:
        src.backup(dst)
        return True
    finally:
        dst.close()
        src.close()


def init_tenant_db_schema(db_filename: str, db_path: str) -> None:
    """Initialisiert das passende Tabellen-Schema für eine Mandanten-SQLite-Datei."""
    fname = os.path.basename(db_filename)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if fname == "erp.db":
        # ERPManager initialisiert das vollständige Schema inkl. Nummernkreise
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS erp_sequences (seq_key TEXT PRIMARY KEY, current_val INTEGER NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()
        return

    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        with conn:
            if fname == "deals.db":
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS deals (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        partner_name TEXT NOT NULL,
                        contact_email TEXT,
                        stage TEXT NOT NULL DEFAULT 'lead',
                        probability REAL DEFAULT 0.10,
                        deal_value REAL DEFAULT 0.0,
                        currency TEXT DEFAULT 'EUR',
                        expected_close_date TEXT,
                        actual_close_date TEXT,
                        assigned_agent TEXT DEFAULT 'Robert',
                        notes TEXT,
                        lost_reason TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_deals_partner ON deals(partner_name);")

            elif fname == "contracts.db":
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contracts (
                        id TEXT PRIMARY KEY,
                        contract_name TEXT NOT NULL,
                        partner_name TEXT NOT NULL,
                        category TEXT DEFAULT 'SaaS',
                        start_date TEXT,
                        end_date TEXT,
                        notice_period_days INTEGER DEFAULT 30,
                        notice_period_type TEXT DEFAULT 'days',
                        next_notice_deadline TEXT,
                        auto_renewal_months INTEGER DEFAULT 12,
                        payment_due_days INTEGER DEFAULT 14,
                        cost_amount REAL DEFAULT 0.0,
                        cost_currency TEXT DEFAULT 'EUR',
                        billing_cycle TEXT DEFAULT 'monatlich',
                        status TEXT DEFAULT 'active',
                        notes TEXT,
                        source_file TEXT,
                        alert_thresholds_json TEXT DEFAULT '[60, 30, 14, 7, 3, 1]',
                        last_alert_sent TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contract_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        contract_id TEXT NOT NULL,
                        alert_type TEXT NOT NULL,
                        days_remaining INTEGER NOT NULL,
                        message TEXT NOT NULL,
                        dispatched_via TEXT DEFAULT 'system',
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (contract_id) REFERENCES contracts (id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_contracts_deadline ON contracts(next_notice_deadline);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);")

            elif fname == "crm.db":
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kontakte (
                        "Vernetzt_seit" TEXT DEFAULT '' NOT NULL,
                        einladung_zurueckgezogen_am TEXT DEFAULT '' NOT NULL,
                        id TEXT PRIMARY KEY,
                        kommentar TEXT DEFAULT '' NOT NULL,
                        nachrichtenverlauf JSON DEFAULT NULL,
                        naechster_schritt TEXT DEFAULT '' NOT NULL,
                        name TEXT DEFAULT '' NOT NULL,
                        profilbild TEXT DEFAULT '' NOT NULL,
                        rating NUMERIC DEFAULT 0 NOT NULL,
                        region TEXT DEFAULT '' NOT NULL,
                        rolle TEXT DEFAULT '' NOT NULL,
                        status TEXT DEFAULT '' NOT NULL,
                        unternehmen TEXT DEFAULT '' NOT NULL,
                        updated TEXT DEFAULT '' NOT NULL,
                        vernetzt_am TEXT DEFAULT '' NOT NULL,
                        linkedin_url TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        telefon_1 TEXT DEFAULT '',
                        telefon_2 TEXT DEFAULT '',
                        tags JSON DEFAULT '[]',
                        "Webseite" TEXT DEFAULT '' NOT NULL,
                        "adresse" TEXT DEFAULT '' NOT NULL,
                        naechster_termin TEXT DEFAULT '',
                        created TEXT DEFAULT '',
                        "RollenVerteilungzuordnung" TEXT DEFAULT '' NOT NULL,
                        "LinkedInheader" TEXT DEFAULT '' NOT NULL,
                        "Linkedin_info" TEXT DEFAULT '' NOT NULL,
                        dsgvo_legal_basis TEXT DEFAULT 'art6_1_f',
                        dsgvo_opt_email INTEGER DEFAULT 1,
                        dsgvo_opt_phone INTEGER DEFAULT 1,
                        dsgvo_opt_postal INTEGER DEFAULT 0,
                        dsgvo_opt_source TEXT DEFAULT 'B2B Erstkontakt',
                        dsgvo_opt_out INTEGER DEFAULT 0,
                        dsgvo_opt_out_date TEXT DEFAULT '',
                        dsgvo_retention_category TEXT DEFAULT 'commercial_10y',
                        debitor_nr TEXT DEFAULT '',
                        kreditor_nr TEXT DEFAULT '',
                        zahlungsart TEXT DEFAULT '',
                        zahlungsziel_tage INTEGER DEFAULT 14,
                        skonto_prozent REAL DEFAULT 0.0,
                        skonto_tage INTEGER DEFAULT 0,
                        kreditlimit REAL DEFAULT 0.0,
                        preisgruppe TEXT DEFAULT '',
                        iban TEXT DEFAULT '',
                        bic TEXT DEFAULT '',
                        bank_name TEXT DEFAULT '',
                        ust_id TEXT DEFAULT '',
                        steuernummer TEXT DEFAULT '',
                        steuergebiet TEXT DEFAULT 'DE',
                        leitweg_id TEXT DEFAULT '',
                        ansprechpartner_json TEXT DEFAULT '[]',
                        dsgvo_status TEXT DEFAULT 'konform',
                        dsgvo_opt_in_datum TEXT DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS termine (
                        Ende TEXT DEFAULT '' NOT NULL,
                        Notiz TEXT DEFAULT '' NOT NULL,
                        Ort TEXT DEFAULT '' NOT NULL,
                        Start TEXT DEFAULT '' NOT NULL,
                        created TEXT DEFAULT '' NOT NULL,
                        id TEXT PRIMARY KEY,
                        kontakt TEXT DEFAULT '' NOT NULL,
                        titel TEXT DEFAULT '' NOT NULL,
                        updated TEXT DEFAULT '' NOT NULL
                    )
                    """
                )

            elif fname == "kanban.db":
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        body TEXT,
                        assignee TEXT,
                        status TEXT NOT NULL DEFAULT 'todo',
                        priority INTEGER DEFAULT 0,
                        created_by TEXT,
                        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                        started_at INTEGER,
                        completed_at INTEGER,
                        workspace_kind TEXT NOT NULL DEFAULT 'scratch',
                        workspace_path TEXT,
                        branch_name TEXT,
                        project_id TEXT,
                        claim_lock TEXT,
                        claim_expires INTEGER,
                        tenant TEXT,
                        result TEXT,
                        idempotency_key TEXT,
                        consecutive_failures INTEGER NOT NULL DEFAULT 0,
                        worker_pid INTEGER,
                        last_failure_error TEXT,
                        max_runtime_seconds INTEGER,
                        last_heartbeat_at INTEGER,
                        current_run_id INTEGER,
                        workflow_template_id TEXT,
                        current_step_key TEXT,
                        skills TEXT,
                        model_override TEXT,
                        max_retries INTEGER,
                        goal_mode INTEGER NOT NULL DEFAULT 0,
                        goal_max_turns INTEGER,
                        session_id TEXT,
                        block_kind TEXT,
                        block_recurrences INTEGER NOT NULL DEFAULT 0,
                        provider_override TEXT,
                        reasoning_effort TEXT,
                        completion_contract TEXT,
                        worker_started_at INTEGER
                    )
                    """
                )
    finally:
        conn.close()


class TenantContextManager:
    """Zentrale Verwaltung für Mandantenwechsel, DB-Isolation und Nummernkreise."""

    def __init__(
        self,
        workspace_dir: str = WORKSPACE_DIR,
        corporate_mgr: Any = None,
    ) -> None:
        self.workspace_dir = os.path.realpath(workspace_dir)
        self._is_default_workspace = self.workspace_dir == os.path.realpath(WORKSPACE_DIR)
        self.tenants_base_dir = os.path.join(self.workspace_dir, "data", "tenants")
        self._corporate_mgr = corporate_mgr
        self._lock = threading.RLock()
        self._initialized_schemas: set[tuple[str, str]] = set()

    def _get_corporate_manager(self):
        if self._corporate_mgr is not None:
            return self._corporate_mgr
        from backend.corporate_manager import corporate_manager
        return corporate_manager

    def get_active_company(self) -> Dict[str, Any]:
        mgr = self._get_corporate_manager()
        comp = mgr.get_company()
        if not comp:
            companies = mgr.list_companies()
            comp = (
                companies[0]
                if companies
                else {"id": "default", "name": "Standard-Mandant", "entity_type": "operative_gmbh"}
            )
        return comp

    def get_active_tenant_id(self) -> str:
        comp = self.get_active_company()
        return sanitize_tenant_id(comp.get("id"))

    def get_tenant_dir(self, company_id: Optional[str] = None) -> str:
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        target = os.path.realpath(os.path.join(self.tenants_base_dir, tid))
        base_real = os.path.realpath(self.tenants_base_dir)
        if not (target == base_real or target.startswith(base_real + os.sep)):
            raise ValueError(f"Ungültiger Mandantenpfad: {tid}")
        os.makedirs(target, exist_ok=True)
        return target

    def resolve_tenant_db(self, db_filename: str, company_id: Optional[str] = None) -> str:
        """Liefert den physisch isolierten SQLite-Pfad unter `data/tenants/<id>/<db>`."""
        fname = os.path.basename(db_filename)
        if fname not in ISOLATED_TENANT_DBS:
            raise ValueError(f"DB '{fname}' ist nicht für Mandanten-Isolation registriert.")
        tdir = self.get_tenant_dir(company_id)
        return os.path.join(tdir, fname)

    def resolve_active_db(self, db_filename: str, company_id: Optional[str] = None) -> str:
        """
        Löst den produktiven SQLite-Pfad für den aktiven (oder angegebenen) Mandanten auf:
        - Sekundäre Gesellschaften (Holding, SPV, weitere GmbHs) erhalten IMMER ihre
          physisch isolierte SQLite-Datei unter `data/tenants/<id>/<db_filename>` mit
          initialisiertem Schema.
        - Für den Primärmandanten (`archon-systems`) bleiben die Live-Engines für
          PocketBase-CRM (`pocketbase/pb_data/data.db`) und Hermes-Kanban (`kanban.db`)
          angebunden, während `deals.db` & `contracts.db` verlustfrei nach
          `data/tenants/archon-systems/` übernommen werden.
        """
        fname = os.path.basename(db_filename)
        if fname not in ISOLATED_TENANT_DBS:
            raise ValueError(f"DB '{fname}' ist nicht für Mandanten-Isolation registriert.")

        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        isolated_path = self.resolve_tenant_db(fname, tid)

        with self._lock:
            is_primary_prod = self._is_default_workspace and (tid in PRIMARY_TENANT_IDS)

            if is_primary_prod and fname == "crm.db":
                pb_db = os.path.join(self.workspace_dir, "pocketbase", "pb_data", "data.db")
                if os.path.isfile(pb_db):
                    return pb_db

            if is_primary_prod and fname == "kanban.db":
                for cand in (
                    "/opt/data/kanban.db",
                    os.path.join(self.workspace_dir, "data", "kanban.db"),
                    os.path.expanduser("~/.hermes/kanban.db"),
                ):
                    if os.path.isfile(cand):
                        return cand

            if is_primary_prod and fname in ("deals.db", "contracts.db") and not _db_has_tables(isolated_path):
                legacy_path = os.path.join(self.workspace_dir, "data", fname)
                if _db_has_tables(legacy_path):
                    _atomic_sqlite_backup(legacy_path, isolated_path)

            cache_key = (fname, isolated_path)
            if cache_key not in self._initialized_schemas or not os.path.isfile(isolated_path):
                init_tenant_db_schema(fname, isolated_path)
                self._initialized_schemas.add(cache_key)

            return isolated_path

    def ensure_tenant_databases(self, company_id: Optional[str] = None, init_schemas: bool = False) -> Dict[str, str]:
        """Stellt sicher, dass das Mandantenverzeichnis existiert und alle DB-Pfade auflösbar sind."""
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        paths = {}
        for db_name in ISOLATED_TENANT_DBS:
            p = self.resolve_tenant_db(db_name, tid)
            if init_schemas and not os.path.isfile(p):
                init_tenant_db_schema(db_name, p)
            paths[db_name] = p
        return paths

    def switch_tenant(self, company_id: str, actor: str = "admin") -> Dict[str, Any]:
        """Wechselt den aktiven Mandanten atomar, initialisiert dessen DBs und schreibt ein GoBD-Audit-Event."""
        mgr = self._get_corporate_manager()
        ok = mgr.set_active_company(company_id)
        if not ok:
            raise KeyError(f"Mandant '{company_id}' nicht gefunden.")
        comp = mgr.get_company(company_id) or {"id": company_id}
        tid = sanitize_tenant_id(company_id)
        is_secondary = not (self._is_default_workspace and tid in PRIMARY_TENANT_IDS)
        db_paths = self.ensure_tenant_databases(tid, init_schemas=is_secondary)
        # Nummernkreise ebenfalls sicherstellen
        ranges = self.get_number_ranges(tid)

        if self._is_default_workspace:
            try:
                from backend.audit_log import chained_audit_log
                chained_audit_log.record_event(
                    category="governance",
                    action="tenant_switched",
                    agent_id=actor,
                    payload={
                        "tenant_id": tid,
                        "company_name": comp.get("name", tid),
                        "entity_type": comp.get("entity_type", "operative_gmbh"),
                    },
                )
            except Exception:
                pass

        return {
            "status": "switched",
            "active_company": comp,
            "tenant_id": tid,
            "isolated_dbs": db_paths,
            "number_ranges": ranges,
        }

    # ------------------------------------------------------------------
    # Getrennte Nummernkreise je Mandant
    # ------------------------------------------------------------------

    def _ranges_file(self, company_id: Optional[str] = None) -> str:
        return os.path.join(self.get_tenant_dir(company_id), "number_ranges.json")

    def get_number_ranges(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        fpath = self._ranges_file(tid)
        with self._lock:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        return json.load(fh)
                except Exception:
                    pass
            year = datetime.datetime.now().year
            short_code = tid.upper()[:6]
            defaults = {
                doc_type: {
                    "prefix": f"{pfx}-{short_code}-{year}-",
                    "next_seq": 1,
                    "padding": 4,
                }
                for doc_type, pfx in DEFAULT_NUMBER_PREFIXES.items()
            }
            self._save_number_ranges(tid, defaults)
            return defaults

    def _save_number_ranges(self, company_id: str, data: Dict[str, Any]) -> None:
        fpath = self._ranges_file(company_id)
        tmp = f"{fpath}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, fpath)

    def next_document_number(self, doc_type: str, company_id: Optional[str] = None) -> str:
        """Vergibt atomar die nächste Belegnummer im Nummernkreis des Mandanten."""
        if doc_type not in DEFAULT_NUMBER_PREFIXES:
            raise ValueError(f"Unbekannter Belegtyp '{doc_type}'. Erlaubt: {list(DEFAULT_NUMBER_PREFIXES)}")
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        with self._lock:
            ranges = self.get_number_ranges(tid)
            entry = ranges.setdefault(
                doc_type,
                {
                    "prefix": f"{DEFAULT_NUMBER_PREFIXES[doc_type]}-{tid.upper()[:6]}-{datetime.datetime.now().year}-",
                    "next_seq": 1,
                    "padding": 4,
                },
            )
            seq = int(entry.get("next_seq", 1))
            pad = int(entry.get("padding", 4))
            formatted = f"{entry['prefix']}{str(seq).zfill(pad)}"
            entry["next_seq"] = seq + 1
            self._save_number_ranges(tid, ranges)
            return formatted

    def get_isolation_status(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        paths = self.ensure_tenant_databases(tid)
        db_status = {}
        for name, isolated_p in paths.items():
            active_p = self.resolve_active_db(name, tid)
            exists = os.path.isfile(isolated_p) or os.path.isfile(active_p)
            target_stat_path = isolated_p if os.path.isfile(isolated_p) else active_p
            size_bytes = os.path.getsize(target_stat_path) if os.path.isfile(target_stat_path) else 0
            db_status[name] = {
                "path": isolated_p,
                "active_path": active_p,
                "exists": exists,
                "size_bytes": size_bytes,
                "mode": "isolated" if os.path.realpath(active_p) == os.path.realpath(isolated_p) else "primary_engine",
            }
        return {"tenant_id": tid, "databases": db_status}


tenant_context = TenantContextManager()
