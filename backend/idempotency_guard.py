"""
backend/idempotency_guard.py
Paket 3 (Feature 13): Idempotency-Keys & Tool-Call-Deduplizierung.
Verhindert, dass bei Retries, Netzwerk-Timeouts oder Agenten-Schleifen kritische Seiteneffekte
(E-Mail-Versand, Webhook-Call, Datenbank-Buchung) doppelt ausgeführt werden.
"""

import os
import json
import hashlib
import sqlite3
import logging

logger = logging.getLogger("archon_os.idempotency_guard")

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    _LEGACY_DB_PATH = _resolve_db("memory.db")
except Exception:
    _LEGACY_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "memory.db")

# F014 / H-06-1: DB_PATH bleibt der historische, monkeypatchbare Default
# (bestehende Tests und Deployment-Overrides setzen ihn explizit). Im
# Produktivpfad wird der Pfad PRO AUFRUF ueber die SSOT mandantenisoliert
# aufgeloest; ein explizit abweichender Wert hat Vorrang.
DB_PATH = _LEGACY_DB_PATH

_LEGACY_SHARED_ENV = "ARCHON_LEDGER_LEGACY_SHARED_DB"

# Modul-Import initiiert das Schema des Modul-Singletons, manchmal noch bevor
# die Request-/Mandanten-Infrastruktur voll verfuegbar ist. Dieser Flag erlaubt
# ausschliesslich waehrend des Imports einen best-effort Fallback; zur Laufzeit
# ist der Resolver fail-closed (F014). Kein Runtime-Legacy-Pfad.
_IMPORT_BOOTSTRAP = True


def _legacy_shared_allowed() -> bool:
    """Expliziter, dokumentierter Legacy-Modus fuer eine geteilte Ledger-DB.

    Default ist fail-closed: ohne Opt-in darf der Resolver nicht auf eine
    mandantenuebergreifende Datei zurueckfallen (FULL_TENANT_ISOLATION).
    """
    return os.environ.get(_LEGACY_SHARED_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _db_path() -> str:
    """F014: mandantenisolierter Pfad ueber `db_paths.resolve_tenant_db`."""
    if DB_PATH != _LEGACY_DB_PATH:
        return DB_PATH  # expliziter Override (Tests / bewusste Konfiguration)
    try:
        from backend.db_paths import resolve_tenant_db
        return resolve_tenant_db("memory.db")
    except Exception as exc:
        if _legacy_shared_allowed() or _IMPORT_BOOTSTRAP:
            logger.warning(
                "[F014] Tenant-Resolver unavailable (%s); best-effort legacy path: %s",
                "explicit legacy mode" if _legacy_shared_allowed() else "import bootstrap",
                exc,
            )
            return _LEGACY_DB_PATH
        raise RuntimeError(
            f"[F014] Tenant-DB resolution failed for idempotency ledger: {exc}. "
            f"Set {_LEGACY_SHARED_ENV}=1 only for an explicitly accepted legacy deployment."
        ) from exc


def _current_tenant_id() -> str:
    """Aktiver Mandant (Request-Kontext vor Corporate-Default)."""
    try:
        from backend.tenant_context import _REQUEST_TENANT_VAR, sanitize_tenant_id
        tid = _REQUEST_TENANT_VAR.get()
        if tid:
            return sanitize_tenant_id(tid)
    except Exception:
        pass
    try:
        from backend.tenant_context import tenant_context
        return tenant_context.get_active_tenant_id()
    except Exception:
        return "default"


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("idempotency_guard")
    except Exception:
        return {
            "enabled": True,
            "ttl_hours": 24,
            "block_duplicate_side_effects": True
        }


_INITIALIZED_PATHS: set[str] = set()


def _ensure_db() -> str:
    """Stellt Schema fuer den *jeweiligen* Mandanten-Pfad sicher (einmal pro Pfad)."""
    path = _db_path()
    if path not in _INITIALIZED_PATHS:
        _init_db(path)
        _INITIALIZED_PATHS.add(path)
    return path


def _init_db(db_path: Optional[str] = None) -> str:
    db_path = db_path or _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                tool_name TEXT,
                payload_hash TEXT,
                result_json TEXT,
                duplicate_blocks_count INTEGER DEFAULT 0,
                created_at TEXT,
                expires_at TEXT,
                status TEXT DEFAULT 'pending',
                executed_at TEXT
            )
        """)
        # N-04: Migration fuer Bestands-Datenbanken (Spalte status/executed_at).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(idempotency_ledger)").fetchall()}
        if cols and "status" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN status TEXT DEFAULT 'pending'")
        if cols and "executed_at" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN executed_at TEXT")
        # Tenant-/Lease-Scope: der alte Key enthielt weder Mandant noch
        # Ausfuehrungs-ID -> Mandant B bekam das Ergebnis von A bzw. zwei
        # Worker fuehrten denselben Seiteneffekt parallel aus.
        if cols and "scope_key" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN scope_key TEXT DEFAULT ''")
        if cols and "owner_id" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN owner_id TEXT DEFAULT ''")
        if cols and "lease_expires" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN lease_expires TEXT DEFAULT ''")
        # F014/H-06-1: tenant_id als eigene Spalte (bestandskompatibel via ALTER).
        # Der scope_key war bereits tenant-präfigiert; die Spalte macht den
        # Mandanten abfragbar und ermoeglicht explizite Cross-Tenant-Guards.
        if cols and "tenant_id" not in cols:
            conn.execute("ALTER TABLE idempotency_ledger ADD COLUMN tenant_id TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency_ledger(expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_scope ON idempotency_ledger(scope_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_tenant ON idempotency_ledger(tenant_id)")
        conn.commit()
    return db_path


def _current_scope() -> str:
    """F014: der Scope ist immer der aktive Mandant (SSOT tenant_context)."""
    return _current_tenant_id()


class IdempotencyGuard:
    def __init__(self):
        _INITIALIZED_PATHS.add(_init_db())

    def check_or_register(
        self,
        tool_name: str,
        params: Dict[str, Any],
        explicit_key: Optional[str] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        scope_key: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        block_dups = bool(cfg.get("block_duplicate_side_effects", True))
        ttl_hours = int(cfg.get("ttl_hours", 24))

        tenant_id = _current_tenant_id()
        # Ein expliziter scope_key darf den Mandanten NIE ersetzen — sonst
        # koennen zwei Mandanten mit gleichem Scope denselben Key treffen (H-06-1).
        scope = f"{tenant_id}::{scope_key}" if scope_key else tenant_id
        canonical_params = json.dumps(params, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(
            f"{scope}::{tool_name}::{canonical_params}".encode("utf-8")
        ).hexdigest()
        # KRITISCH: explizite Keys (mct-{task_id}, workflow-{id}, ...) waren
        # nicht tenant-gescoped — Mandant B bekam bei gleicher ID das
        # gecachte Ergebnis von A oder wurde am eigenen Seiteneffekt gehindert.
        idem_key = f"{scope}::{explicit_key}" if explicit_key else f"idem-{payload_hash[:20]}"
        owner = str(owner_id or "")

        if not enabled:
            return {
                "allowed": True,
                "duplicate_detected": False,
                "bypassed": True,
                "idempotency_key": idem_key
            }

        now = datetime.now()
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_iso = (now + timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")
        # Lease fuer laufende Ausfuehrungen: 10 min. Danach darf ein anderer
        # Worker uebernehmen (z. B. nach Crash ohne invalidate_key).
        lease_iso = (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(_ensure_db(), timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("DELETE FROM idempotency_ledger WHERE expires_at < ?", (now_iso,))

            # N-04 (Race-Fix): INSERT OR IGNORE + Ruecklesen statt SELECT->INSERT.
            # Zwei gleichzeitige Aufrufe mit gleichem Key liefen vorher beide in
            # den zweiten INSERT -> IntegrityError -> 500 statt Duplikat-Block.
            cur = conn.execute("""
                INSERT OR IGNORE INTO idempotency_ledger
                (idempotency_key, tool_name, payload_hash, result_json, duplicate_blocks_count, created_at, expires_at, status, scope_key, owner_id, lease_expires, tenant_id)
                VALUES (?, ?, ?, NULL, 0, ?, ?, 'pending', ?, ?, ?, ?)
            """, (idem_key, tool_name, payload_hash, now_iso, exp_iso, scope, owner, lease_iso, tenant_id))
            if cur.rowcount > 0:
                # Erster Anruf: mit echtem Resultat sofort als executed registrieren.
                if execution_result:
                    conn.execute("""
                        UPDATE idempotency_ledger
                        SET status = 'executed', result_json = ?, executed_at = ?
                        WHERE idempotency_key = ?
                    """, (json.dumps(execution_result, ensure_ascii=False), now_iso, idem_key))
                conn.commit()
                return {
                    "allowed": True,
                    "duplicate_detected": False,
                    "blocked": False,
                    "idempotency_key": idem_key,
                    "tool_name": tool_name,
                    "status": "executed" if execution_result else "pending_registered",
                    "expires_at": exp_iso
                }

            existing = conn.execute(
                "SELECT * FROM idempotency_ledger WHERE idempotency_key = ?",
                (idem_key,)
            ).fetchone()

            if existing["status"] == "executed":
                conn.execute(
                    "UPDATE idempotency_ledger SET duplicate_blocks_count = duplicate_blocks_count + 1 WHERE idempotency_key = ?",
                    (idem_key,)
                )
                conn.commit()
                return {
                    "allowed": not block_dups,
                    "duplicate_detected": True,
                    "blocked": block_dups,
                    "idempotency_key": idem_key,
                    "tool_name": tool_name,
                    "original_executed_at": existing["created_at"],
                    "duplicate_blocks_count": existing["duplicate_blocks_count"] + 1,
                    "cached_result": json.loads(existing["result_json"] or "{}")
                }

            # KRITISCH: PENDING durfte frueher immer ausgefuehrt werden. Damit
            # fuehrten zwei Worker bei Lease-Ablauf denselben Seiteneffekt
            # doppelt aus. Jetzt gilt: eine noch aktive Lease blockiert; erst
            # nach Ablauf (Crash) oder nach invalidate_key darf uebernommen
            # werden.
            lease = str(existing["lease_expires"] or "")
            if lease and lease > now_iso:
                conn.commit()
                return {
                    "allowed": False,
                    "blocked": True,
                    "duplicate_detected": True,
                    "previous_attempt_pending": True,
                    "idempotency_key": idem_key,
                    "tool_name": tool_name,
                    "reason": "another_execution_in_progress",
                    "lease_expires": lease,
                }
            # KRITISCH (Audit 23.11.2026): CAS gegen den gelesenen Lease-Wert.
            # Sonst können zwei Worker nach Ablauf denselben Key gleichzeitig
            # übernehmen und den Seiteneffekt doppelt ausführen.
            cur = conn.execute(
                "UPDATE idempotency_ledger SET created_at = ?, expires_at = ?, owner_id = ?, lease_expires = ? "
                "WHERE idempotency_key = ? AND COALESCE(lease_expires, '') = ?",
                (now_iso, exp_iso, owner, lease_iso, idem_key, lease)
            )
            if int(cur.rowcount or 0) != 1:
                conn.commit()
                return {
                    "allowed": False,
                    "blocked": True,
                    "duplicate_detected": True,
                    "previous_attempt_pending": True,
                    "idempotency_key": idem_key,
                    "tool_name": tool_name,
                    "reason": "concurrent_claim",
                }
            if execution_result:
                conn.execute("""
                    UPDATE idempotency_ledger
                    SET status = 'executed', result_json = ?, executed_at = ?
                    WHERE idempotency_key = ?
                """, (json.dumps(execution_result, ensure_ascii=False), now_iso, idem_key))
            conn.commit()
            return {
                "allowed": True,
                "duplicate_detected": False,
                "blocked": False,
                "previous_attempt_pending": True,
                "idempotency_key": idem_key,
                "tool_name": tool_name,
                "status": "executed" if execution_result else "pending_registered",
                "expires_at": exp_iso
            }

    def record_execution_result(self, key: str, result: Dict[str, Any]) -> bool:
        """Verbucht ein reales Ausfuehrungsergebnis (Phase 2, N-04).

        Erst ab hier gilt der Key als ausgefuehrt — Retries vorher sind
        Versuche, kein erfundener Erfolg.
        """
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(_ensure_db(), timeout=15.0, factory=_ArchonClosingConn) as conn:
            cur = conn.execute("""
                UPDATE idempotency_ledger
                SET status = 'executed', result_json = ?, executed_at = ?
                WHERE idempotency_key = ? AND status != 'executed'
            """, (json.dumps(result, ensure_ascii=False), now_iso, key))
            conn.commit()
        return cur.rowcount > 0

    def invalidate_key(self, key: str) -> bool:
        """Loescht einen Key nach FEHLGESCHLAGENER Ausfuehrung (Phase 2b, N-04),
        damit ein Retry frisch registrieren kann.
        """
        with sqlite3.connect(_ensure_db(), timeout=15.0, factory=_ArchonClosingConn) as conn:
            cur = conn.execute(
                "DELETE FROM idempotency_ledger WHERE idempotency_key = ?", (key,)
            )
            conn.commit()
        return cur.rowcount > 0


idempotency_guard = IdempotencyGuard()

# F014: ab hier gilt fail-closed — kein stiller Fallback auf die globale DB.
_IMPORT_BOOTSTRAP = False
