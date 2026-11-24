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

import contextvars
import datetime
import json
import logging
import os
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional

# Autoritative Basis ist der Repo-Root (identisch mit backend.db_paths).
# Vorher kam WORKSPACE_DIR aus archon.core.runtime ("./agent_workspace") und
# erzeugte ein zweites, leeres data/tenants-Verzeichnis -> Split-Brain.
from backend.db_paths import WORKSPACE_DIR, APP_DATA_DIR, DB_BUSY_TIMEOUT_MS  # F-013: SSOT

logger = logging.getLogger("archon.tenant_context")

# B2: GoBD-Auditfehler beim Mandantenwechsel duerfen nie still verschwinden.
_AUDIT_ERROR_COUNTS: Dict[str, int] = {}


def _record_audit_error(action: str, exc: BaseException) -> None:
    _AUDIT_ERROR_COUNTS[action] = _AUDIT_ERROR_COUNTS.get(action, 0) + 1
    logger.error(
        "[GoBD-Audit] '%s' fehlgeschlagen (count=%d): %s",
        action, _AUDIT_ERROR_COUNTS[action], exc,
    )


_REQUEST_TENANT_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "archon_request_tenant", default=None
)


def set_request_tenant(company_id: Optional[str]) -> contextvars.Token:
    """Bindet eine Request-spezifische Mandanten-ID an den aktuellen Async/Thread-Kontext."""
    val = sanitize_tenant_id(company_id) if company_id else None
    return _REQUEST_TENANT_VAR.set(val)


def reset_request_tenant(token: contextvars.Token) -> None:
    """Setzt den Request-Mandantenkontext nach Abschluss des Requests zurueck."""
    _REQUEST_TENANT_VAR.reset(token)

ISOLATED_TENANT_DBS = ("erp.db", "kanban.db", "crm.db", "contracts.db", "deals.db")
CONSOLIDATED_TENANT_DBS = ("ops.db", "business.db", "memory.db")
PRIMARY_TENANT_IDS = frozenset({"archon-systems", "default"})

# Benutzerentscheidung 22.11.2026: JEDE Mandant bekommt eine eigene,
# physisch isolierte Datenbank — auch 'default' und 'archon-systems'.
# Damit ist DSGVO Art. 17 eindeutig auf eine Datei anwendbar und die
# 28→3-Konsolidierung bleibt pro Mandant erhalten (3 Domänen-DBs je Tenant).
FULL_TENANT_ISOLATION = (
    os.environ.get("ARCHON_TENANT_FULL_ISOLATION", "1").strip().lower()
    not in ("0", "false", "no", "off")
)

DEFAULT_NUMBER_PREFIXES = {
    "invoice": "RE",
    "offer": "ANG",
    "order": "AB",
    "credit_note": "GS",
    "contract": "VTR",
}

# F-018: einzige Schema-Definition der Nummernkreis-Authority. Wird sowohl
# von tenant_context als auch von der ERP-Legacy-Migration verwendet.
DOCUMENT_NUMBER_SEQUENCES_DDL = """
    CREATE TABLE IF NOT EXISTS document_number_sequences (
        tenant_id TEXT NOT NULL,
        doc_type  TEXT NOT NULL,
        year      INTEGER NOT NULL,
        prefix    TEXT NOT NULL,
        next_seq  INTEGER NOT NULL,
        padding   INTEGER NOT NULL DEFAULT 4,
        PRIMARY KEY (tenant_id, doc_type, year)
    )
"""


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
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
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
                        dsgvo_opt_email INTEGER DEFAULT 0,
                        dsgvo_opt_phone INTEGER DEFAULT 0,
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
        # W6: bei ARCHON_DATA_DIR (Test-Isolation) liegt auch der Tenant-Store
        # im getrennten Datenverzeichnis, nicht unter WORKSPACE_DIR/data.
        # Explizit übergebene workspace_dir (Tests mit tmp_path) bleibt unberührt.
        self._data_root = (
            APP_DATA_DIR if self._is_default_workspace
            else os.path.join(self.workspace_dir, "data")
        )
        self.tenants_base_dir = os.path.join(self._data_root, "tenants")
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
        ctx_tid = _REQUEST_TENANT_VAR.get()
        if ctx_tid:
            return sanitize_tenant_id(ctx_tid)
        comp = self.get_active_company()
        return sanitize_tenant_id(comp.get("id"))

    def get_tenant_dir(self, company_id: Optional[str] = None, create: bool = True) -> str:
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        target = os.path.realpath(os.path.join(self.tenants_base_dir, tid))
        base_real = os.path.realpath(self.tenants_base_dir)
        if not (target == base_real or target.startswith(base_real + os.sep)):
            raise ValueError(f"Ungültiger Mandantenpfad: {tid}")
        if create:
            os.makedirs(target, exist_ok=True)
        return target

    def resolve_tenant_db(self, db_filename: str, company_id: Optional[str] = None, create_dirs: bool = True) -> str:
        """Liefert den physisch isolierten SQLite-Pfad unter `data/tenants/<id>/<db>`."""
        fname = os.path.basename(db_filename)
        if fname not in ISOLATED_TENANT_DBS and fname not in CONSOLIDATED_TENANT_DBS:
            raise ValueError(f"DB '{fname}' ist nicht für Mandanten-Isolation registriert.")
        tdir = self.get_tenant_dir(company_id, create=create_dirs)
        return os.path.join(tdir, fname)

    def resolve_active_db(self, db_filename: str, company_id: Optional[str] = None) -> str:
        """
        Löst den produktiven SQLite-Pfad für den aktiven (oder angegebenen) Mandanten auf:
        - Sekundäre Gesellschaften (Holding, SPV, weitere GmbHs) erhalten IMMER ihre
          physisch isolierte SQLite-Datei unter `data/tenants/<id>/<db_filename>` mit
          initialisiertem Schema.
        - Ist die Phase-2-Konsolidierung (`ops.db`/`business.db`/`memory.db`) aktiv und
          die Ziel-Domänen-DB existiert, wird für den Primärmandanten transparent auf
          `data/{ops,business,memory}.db` geroutet; für Sekundärmandanten auf deren
          eigene konsolidierte `data/tenants/<id>/{ops,business,memory}.db` (falls vorhanden).
        """
        fname = os.path.basename(db_filename)
        if fname not in ISOLATED_TENANT_DBS and fname not in CONSOLIDATED_TENANT_DBS:
            raise ValueError(f"DB '{fname}' ist nicht für Mandanten-Isolation registriert.")

        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        isolated_path = self.resolve_tenant_db(fname, tid)

        with self._lock:
            # VOLLSTAENDIGE MANDANTEN-ISOLATION (Benutzerentscheidung):
            # Auch Primärmandanten arbeiten ausschliesslich unter
            # data/tenants/<tid>/. Bisher gemeinsam genutzte DBs werden einmalig
            # konsistent in das Mandantenverzeichnis kopiert. Danach gibt es
            # keine geteilten Daten mehr und Art.-17 kann sauber löschen.
            if FULL_TENANT_ISOLATION:
                # d03: Auch bei FULL_TENANT_ISOLATION bleibt die 28->3-Konsolidierung
                # erreichbar — pro Mandant unter data/tenants/<tid>/{ops,business,memory}.db,
                # damit Voll-Isolation und 3-DB-Konsolidierung keinen Split-Brain bilden.
                try:
                    from backend.db_consolidation import is_consolidation_active, resolve_consolidated_domain
                    if is_consolidation_active(self._data_root):
                        dom_name = fname if fname in CONSOLIDATED_TENANT_DBS else resolve_consolidated_domain(fname)
                        cons_tenant = os.path.join(self.get_tenant_dir(tid), dom_name)
                        if _db_has_tables(cons_tenant):
                            return cons_tenant
                except Exception as cons_exc:
                    logger.debug(f"[TenantContext] Konsolidierungs-Aufloesung (full-isolation) uebersprungen: {cons_exc}")
                # F-014: Die Legacy-Kopie darf NUR fuer Primärmandanten laufen.
                # Ohne diesen Guard erbt jeder neu angelegte Sekundärmandant die
                # Business-/CRM-Daten des Primärmandanten (reale Cross-Tenant-
                # Vermischung, im Bestand nachgewiesen). Sekundärmandanten erhalten
                # ausschliesslich ein leeres, inicialisiertes Schema.
                if (not os.path.isfile(isolated_path)) and (tid in PRIMARY_TENANT_IDS):
                    legacy_candidates = [
                        os.path.join(self._data_root, fname),
                        os.path.join(os.path.expanduser("~"), ".hermes", fname),
                    ]
                    if fname in ("crm.db",):
                        legacy_candidates.append(
                            os.path.join(self._data_root, "business.db")
                        )
                    env_override = os.environ.get("ARCHON_LEGACY_DB_DIR", "").strip()
                    if env_override:
                        legacy_candidates.insert(0, os.path.join(env_override, fname))
                    for legacy in legacy_candidates:
                        if _atomic_sqlite_backup(legacy, isolated_path):
                            logger.warning(
                                "[TenantContext] Legacy-DB '%s' nach '%s' migriert.",
                                legacy, isolated_path,
                            )
                            break
                cache_key = (fname, isolated_path)
                if cache_key not in self._initialized_schemas or not os.path.isfile(isolated_path):
                    init_tenant_db_schema(fname, isolated_path)
                    self._initialized_schemas.add(cache_key)
                return isolated_path

            is_primary_prod = self._is_default_workspace and (tid in PRIMARY_TENANT_IDS)

            try:
                from backend.db_consolidation import is_consolidation_active, resolve_consolidated_domain
                data_dir = self._data_root
                if is_consolidation_active(data_dir):
                    dom_name = fname if fname in CONSOLIDATED_TENANT_DBS else resolve_consolidated_domain(fname)
                    if tid in PRIMARY_TENANT_IDS:
                        cons_primary = os.path.join(data_dir, dom_name)
                        if _db_has_tables(cons_primary):
                            return cons_primary
                    else:
                        cons_tenant = os.path.join(self.get_tenant_dir(tid), dom_name)
                        if _db_has_tables(cons_tenant):
                            return cons_tenant
            except Exception as cons_exc:
                logger.debug(f"[TenantContext] Konsolidierungs-Aufloesung uebersprungen: {cons_exc}")

            if fname in CONSOLIDATED_TENANT_DBS:
                return os.path.join(self._data_root, fname) if (tid in PRIMARY_TENANT_IDS) else isolated_path

            if is_primary_prod and fname == "crm.db":
                # Archon OS CRM nutzt die interne business.db (saubere Trennung von externem PocketBase-LinkedIn-CRM)
                biz_db = os.path.join(self._data_root, "business.db")
                cache_key = ("crm.db", biz_db)
                if cache_key not in self._initialized_schemas or not os.path.isfile(biz_db):
                    init_tenant_db_schema("crm.db", biz_db)
                    self._initialized_schemas.add(cache_key)
                return biz_db

            if is_primary_prod and fname == "kanban.db":
                try:
                    from backend.db_paths import resolve_db as _resolve_db
                    cand = _resolve_db("kanban.db")
                except Exception:
                    cand = os.path.join(self._data_root, "kanban.db")
                if cand and os.path.isfile(cand):
                    return cand

            if is_primary_prod and fname in ("deals.db", "contracts.db") and not _db_has_tables(isolated_path):
                legacy_path = os.path.join(self._data_root, fname)
                if _db_has_tables(legacy_path):
                    _atomic_sqlite_backup(legacy_path, isolated_path)

            cache_key = (fname, isolated_path)
            if cache_key not in self._initialized_schemas or not os.path.isfile(isolated_path):
                init_tenant_db_schema(fname, isolated_path)
                self._initialized_schemas.add(cache_key)

            return isolated_path

    def ensure_tenant_databases(self, company_id: Optional[str] = None, init_schemas: bool = False, create_dirs: bool = True) -> Dict[str, str]:
        """Stellt sicher, dass das Mandantenverzeichnis existiert und alle DB-Pfade auflösbar sind.
        create_dirs=False macht den Aufruf read-only (GET-Endpoints dürfen keine Ordner anlegen)."""
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        paths = {}
        for db_name in ISOLATED_TENANT_DBS:
            p = self.resolve_tenant_db(db_name, tid, create_dirs=create_dirs)
            if init_schemas and not os.path.isfile(p):
                init_tenant_db_schema(db_name, p)
            paths[db_name] = p
        return paths

    def switch_tenant(self, company_id: str, actor: str = "admin") -> Dict[str, Any]:
        """Wechselt den aktiven Mandanten atomar, initialisiert dessen DBs und schreibt ein GoBD-Audit-Event."""
        mgr = self._get_corporate_manager()
        # B2: alten Mandanten fuer den Abbruch bei Auditfehlern merken.
        prev_company = mgr.get_company()
        previous_id = str((prev_company or {}).get("id") or "default")
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
            except Exception as exc:
                # B2: kein Mandantenwechsel ohne GoBD-Auditnachweis.
                _record_audit_error("tenant_switched", exc)
                try:
                    mgr.set_active_company(previous_id)
                except Exception as rollback_exc:
                    _record_audit_error("tenant_switch_rollback", rollback_exc)
                raise RuntimeError(
                    f"Mandantenwechsel abgebrochen: GoBD-Audit-Log fehlgeschlagen: {exc}"
                ) from exc

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

    # ------------------------------------------------------------------
    # Nummernkreise: SQLite als Authorität (prozessübergreifend, GoBD)
    # ------------------------------------------------------------------

    def _ranges_file(self, company_id: Optional[str] = None) -> str:
        """Legacy-Datei (nur noch fuer die einmalige Migration)."""
        return os.path.join(self.get_tenant_dir(company_id), "number_ranges.json")

    def _numbers_db_path(self, company_id: str) -> str:
        """Isolierte DB des Mandanten, in der die Sequenzen liegen."""
        path = self.resolve_tenant_db("erp.db", company_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def migrate_legacy_erp_sequences(self, conn: sqlite3.Connection, company_id: str) -> None:
        """F-018: erp_sequences (alter, nicht jahresbezogener Zaehler) nach
        document_number_sequences migrieren — einmalig und verlustfrei.

        `erp_sequences.current_val` enthaelt die *zuletzt vergebene* Nummer
        (`_next_sequence` erhoeht vor dem Lesen). Der neue Zaehler speichert
        die *naechste* Nummer, daher `next_seq = current_val + 1`.
        `INSERT OR IGNORE` schuetzt bereits vorhandene, hoehere Staende.
        """
        conn.execute(DOCUMENT_NUMBER_SEQUENCES_DDL)
        year = datetime.datetime.now().year
        legacy_map = {
            "offer": ("offer", f"ANG-{year}-"),
            "order": ("order", f"AB-{year}-"),
            "invoice": ("invoice", f"RE-{year}-"),
            "credit_note": ("credit_note", f"GS-{year}-"),
        }
        tid = sanitize_tenant_id(company_id)
        for seq_key, (doc_type, prefix) in legacy_map.items():
            try:
                row = conn.execute(
                    "SELECT current_val FROM erp_sequences WHERE seq_key = ?", (seq_key,)
                ).fetchone()
            except sqlite3.Error:
                return  # Tabelle existiert nicht (frische DB) — nichts zu migrieren.
            if not row:
                continue
            next_seq = max(1, int(row[0]) + 1)
            conn.execute(
                """INSERT OR IGNORE INTO document_number_sequences
                   (tenant_id, doc_type, year, prefix, next_seq, padding)
                   VALUES (?, ?, ?, ?, ?, 4)""",
                (tid, doc_type, year, prefix, next_seq),
            )

    def _ensure_number_sequences_table(self, company_id: str) -> str:
        path = self._numbers_db_path(company_id)
        with sqlite3.connect(path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            conn.execute(DOCUMENT_NUMBER_SEQUENCES_DDL)
            # F-018: Legacy-Zaehler aus der ERP-Tabelle erp_sequences in die
            # eine Authority ueberfuehren (Zaehlerstaende erhalten).
            self.migrate_legacy_erp_sequences(conn, company_id)
            # Einmalige Migration aus number_ranges.json (Zaehlerstand muss
            # erhalten bleiben — sonst drohen doppelte Rechnungsnummern).
            legacy = self._ranges_file(company_id)
            legacy_migrated = False
            ranges: Dict[str, Any] = {}
            if os.path.exists(legacy):
                try:
                    with open(legacy, "r", encoding="utf-8") as fh:
                        ranges = json.load(fh)
                    if isinstance(ranges, dict):
                        for doc_type, entry in ranges.items():
                            if not isinstance(entry, dict):
                                continue
                            prefix = str(entry.get("prefix") or "")
                            year_match = re.search(r"(20\d{2})", prefix)
                            year = int(year_match.group(1)) if year_match else datetime.datetime.now().year
                            conn.execute(
                                """INSERT OR IGNORE INTO document_number_sequences
                                   (tenant_id, doc_type, year, prefix, next_seq, padding)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (company_id, doc_type, year, prefix,
                                 int(entry.get("next_seq") or 1),
                                 int(entry.get("padding") or 4)),
                            )
                    legacy_migrated = True
                except Exception as exc:
                    logger.warning("[TenantContext] Nummernkreis-Migration %s: %s", legacy, exc)
            conn.commit()
            # Zaehlerstand ZUERST verifizieren: nichts darf still auf 1 zurueckfallen.
            expected = sum(
                1 for v in (ranges.values() if isinstance(ranges, dict) else [])
                if isinstance(v, dict)
            )
            actual = conn.execute(
                "SELECT COUNT(*) FROM document_number_sequences WHERE tenant_id = ?",
                (company_id,),
            ).fetchone()[0]
            if expected and actual < expected:
                raise RuntimeError(
                    f"[TenantContext] Nummernkreis-Migration unvollstaendig: {actual}/{expected} Zaehler "
                    f"fuer Mandant '{company_id}' — Zaehlerdatei bewusst NICHT archiviert."
                )
            # KRITISCH (Audit 23.11.2026): die Legacy-Datei darf ERST nach
            # Commit UND erfolgreicher Verifikation umbenannt werden. Vorher
            # war sie bei einem unvollstaendigen Lauf bereits weg → doppelte
            # Belegnummern (GoBD).
            if legacy_migrated and os.path.exists(legacy):
                os.replace(legacy, legacy + ".migrated")
        return path

    def get_number_ranges(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        path = self._ensure_number_sequences_table(tid)
        year = datetime.datetime.now().year
        result: Dict[str, Any] = {}
        with sqlite3.connect(path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0) as conn:
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            rows = conn.execute(
                "SELECT doc_type, prefix, next_seq, padding FROM document_number_sequences "
                "WHERE tenant_id = ? AND year = ?",
                (tid, year),
            ).fetchall()
        for doc_type, prefix, next_seq, padding in rows:
            result[doc_type] = {
                "prefix": prefix,
                "next_seq": int(next_seq),
                "padding": int(padding),
            }
        # Fehlende Typen mit Defaults ergaenzen (nur lesend, kein Schreiben
        # im Read-Pfad — die Tabelle wird bei next_document_number gefuellt).
        short_code = tid.upper()[:6]
        for doc_type, pfx in DEFAULT_NUMBER_PREFIXES.items():
            result.setdefault(doc_type, {
                "prefix": f"{pfx}-{short_code}-{year}-",
                "next_seq": 1,
                "padding": 4,
            })
        return result

    def _save_number_ranges(self, company_id: str, data: Dict[str, Any]) -> None:
        """Kompatibilitätswrapper: schreibt in SQLite statt in eine JSON-Datei."""
        path = self._ensure_number_sequences_table(company_id)
        year = datetime.datetime.now().year
        with sqlite3.connect(path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0) as conn:
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            conn.execute("BEGIN IMMEDIATE")
            for doc_type, entry in (data or {}).items():
                if not isinstance(entry, dict):
                    continue
                conn.execute("""
                    INSERT INTO document_number_sequences
                        (tenant_id, doc_type, year, prefix, next_seq, padding)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, doc_type, year) DO UPDATE SET
                        prefix = excluded.prefix,
                        next_seq = excluded.next_seq,
                        padding = excluded.padding
                """, (company_id, doc_type, year, str(entry.get("prefix") or ""),
                      int(entry.get("next_seq") or 1), int(entry.get("padding") or 4)))
            conn.commit()

    def next_document_number(
        self,
        doc_type: str,
        company_id: Optional[str] = None,
        *,
        conn: Optional[sqlite3.Connection] = None,
        prefix: Optional[str] = None,
    ) -> str:
        """F-018: einzige Authority für Belegnummern (jahresbezogen, atomar).

        Der Zähler liegt in `document_number_sequences` mit
        `PRIMARY KEY (tenant_id, doc_type, year)` — dadurch startet jedes Jahr
        wieder bei 0001. Ohne `conn` wird `BEGIN IMMEDIATE` auf einer eigenen
        Verbindung ausgeführt (Tenant-Endpoint). Wird `conn` übergeben
        (ERP-Belegpfad), läuft die Zähler-Transaktion innerhalb der bereits
        offenen Transaktion desselben Connects — sonst Deadlock am DB-Lock.

        `prefix` erlaubt dem ERP das DATEV-/GoBD-Format `RE-YYYY-0001`, ohne
        einen zweiten Zähler einzuführen. Ohne Override bleibt das historische
        `RE-{MANDANT}-{YYYY}-0001`-Format (kompatibel mit tests/test_m43_*).
        """
        if doc_type not in DEFAULT_NUMBER_PREFIXES:
            raise ValueError(f"Unbekannter Belegtyp '{doc_type}'. Erlaubt: {list(DEFAULT_NUMBER_PREFIXES)}")
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        year = datetime.datetime.now().year
        short_code = tid.upper()[:6]
        default_prefix = f"{DEFAULT_NUMBER_PREFIXES[doc_type]}-{short_code}-{year}-"
        override_prefix = str(prefix) if prefix is not None else None

        own_conn: Optional[sqlite3.Connection] = None
        target: sqlite3.Connection
        if conn is not None:
            target = conn
            target.execute(DOCUMENT_NUMBER_SEQUENCES_DDL)
        else:
            path = self._ensure_number_sequences_table(tid)
            own_conn = sqlite3.connect(path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0)
            own_conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            own_conn.execute("BEGIN IMMEDIATE")
            target = own_conn

        try:
            row = target.execute(
                "SELECT prefix, next_seq, padding FROM document_number_sequences "
                "WHERE tenant_id = ? AND doc_type = ? AND year = ?",
                (tid, doc_type, year),
            ).fetchone()
            store_prefix = override_prefix if override_prefix is not None else default_prefix
            if row is None:
                seq, pad = 1, 4
                target.execute(
                    "INSERT INTO document_number_sequences "
                    "(tenant_id, doc_type, year, prefix, next_seq, padding) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, doc_type, year, store_prefix, seq + 1, pad),
                )
                out_prefix = store_prefix
            else:
                seq, pad = int(row[1]), int(row[2] or 4)
                target.execute(
                    "UPDATE document_number_sequences SET next_seq = ? "
                    "WHERE tenant_id = ? AND doc_type = ? AND year = ?",
                    (seq + 1, tid, doc_type, year),
                )
                out_prefix = override_prefix if override_prefix is not None else str(row[0])
            if own_conn is not None:
                own_conn.commit()
            return f"{out_prefix}{str(seq).zfill(pad)}"
        finally:
            if own_conn is not None:
                own_conn.close()

    def get_isolation_status(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        tid = sanitize_tenant_id(company_id) if company_id else self.get_active_tenant_id()
        paths = self.ensure_tenant_databases(tid, create_dirs=False)
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
