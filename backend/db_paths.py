"""Zentrale, deterministische Datenbank-Auflösung für Archon OS.

Problem vorher: Jedes Modul hatte eine eigene `_resolve_db()`, die den *ersten
existierenden* Pfad nahm. Lag irgendwo eine leere Datei gleichen Namens (z. B.
`/opt/data/agentic_memory.db`), band sich das Modul still an eine DB ohne
Tabellen — jede Query endete in `no such table: ...`, ohne dass die Ursache
sichtbar wurde.

Regeln hier:
1. Pro Dateiname gibt es ein verbindliches Heimatverzeichnis (DB_HOME).
2. Ein Kandidat wird nur akzeptiert, wenn er tatsächlich Tabellen enthält.
3. Existiert kein brauchbarer Kandidat, wird der Heimatpfad zurückgegeben,
   damit das Modul sein Schema dort anlegen kann — nie ein fremder Leerling.
4. Jede Verworfene Datei wird geloggt, damit Split-Brain auffällt.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger("archon.db_paths")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")

# Hermes-Heimat (Agenten-State, Sessions, Kanban) — bleibt getrennt vom App-Data-Ordner.
HERMES_DATA_DIR = "/opt/data" if os.path.isdir("/opt/data") else os.path.expanduser("~/.hermes")

# Die 3 konsolidierten Ziel-Datenbanken (Phase 2.1)
CONSOLIDATED_DB_FILENAMES = ("ops.db", "business.db", "memory.db")

# Verbindliche Zuordnung: Datei -> Heimatverzeichnis.
DB_HOME = {
    "ops.db": APP_DATA_DIR,
    "business.db": APP_DATA_DIR,
    "memory.db": APP_DATA_DIR,
    "agentic_memory.db": APP_DATA_DIR,
    "contracts.db": APP_DATA_DIR,
    "deals.db": APP_DATA_DIR,
    "corporate.db": APP_DATA_DIR,
    "content_machine.db": APP_DATA_DIR,
    "kanban.db": HERMES_DATA_DIR,
    "state.db": HERMES_DATA_DIR,
    "shared-state.db": HERMES_DATA_DIR,
    "projects.db": HERMES_DATA_DIR,
}


def resolve_tenant_db(filename: str, company_id: Optional[str] = None) -> str:
    """Löst mandantenspezifische DBs über tenant_context auf, sonst fallback auf resolve_db."""
    try:
        from backend.tenant_context import tenant_context
        return tenant_context.resolve_active_db(os.path.basename(filename), company_id)
    except Exception:
        return resolve_db(os.path.basename(filename))


def _has_tables(path: str) -> bool:
    """True, wenn die Datei existiert und mindestens eine Tabelle enthält (read-only)."""
    if not os.path.isfile(path):
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
        try:
            rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return len(rows) > 0
        finally:
            con.close()
    except Exception:
        return False


def db_candidates(filename: str) -> list[str]:
    home = DB_HOME.get(filename, APP_DATA_DIR)
    other = HERMES_DATA_DIR if home == APP_DATA_DIR else APP_DATA_DIR
    raw = [
        os.path.join(home, filename),
        os.path.join(other, filename),
        os.path.join(HERMES_DATA_DIR, ".hermes", filename),
        os.path.expanduser(f"~/.hermes/{filename}"),
    ]
    seen, ordered = set(), []
    for c in raw:
        c = os.path.abspath(c)
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


_RESOLVED_DB_CACHE: dict[str, str] = {}
_DB_PRAGMA_INITIALIZED: set[str] = set()


def resolve_db(filename: str) -> str:
    """Liefert den Pfad zur richtigen DB-Datei. Erzeugt keine Datei.

    Ist die Phase-2-Konsolidierung (`ARCHON_DB_CONSOLIDATED=1` oder Manifest)
    aktiviert, werden Legacy-Dateinamen transparent auf `ops.db`, `business.db`
    oder `memory.db` umgeleitet, sobald die konsolidierte Zieldatei existiert.
    """
    base = os.path.basename(str(filename or "").strip())
    try:
        from backend.db_consolidation import is_consolidation_active, resolve_consolidated_domain
        if base not in CONSOLIDATED_DB_FILENAMES and is_consolidation_active(APP_DATA_DIR):
            domain_db = resolve_consolidated_domain(base)
            consolidated_path = os.path.abspath(os.path.join(APP_DATA_DIR, domain_db))
            if _has_tables(consolidated_path):
                return consolidated_path
    except Exception as exc:
        logger.debug(f"[db_paths] Konsolidierungs-Check fuer {base} uebersprungen: {exc}")

    cached = _RESOLVED_DB_CACHE.get(filename)
    if cached and os.path.isfile(cached):
        return cached

    candidates = db_candidates(filename)
    preferred = candidates[0]

    for candidate in candidates:
        if _has_tables(candidate):
            if candidate != preferred:
                logger.warning(
                    "[db_paths] %s wird aus %s geladen (Heimat wäre %s). "
                    "Bitte Datei prüfen/migrieren, um Split-Brain zu vermeiden.",
                    filename, candidate, preferred,
                )
            _RESOLVED_DB_CACHE[filename] = candidate
            return candidate

    for candidate in candidates:
        if candidate != preferred and os.path.isfile(candidate):
            size = os.path.getsize(candidate)
            logger.error(
                "[db_paths] Verworfener Kandidat für %s: %s (%d Bytes, 0 Tabellen). "
                "Nutze stattdessen %s.",
                filename, candidate, size, preferred,
            )

    logger.info("[db_paths] %s wird unter %s neu initialisiert.", filename, preferred)
    return preferred


class ClosingConnection(sqlite3.Connection):
    """Verbindung, die sich am Ende eines with-Blocks deterministisch schliesst."""
    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def get_db_connection(db_name_or_path: str, timeout: float = 15.0) -> sqlite3.Connection:
    """Erzeugt eine gehärtete ClosingConnection mit busy_timeout und WAL-Modus."""
    if os.path.isabs(db_name_or_path) or "/" in db_name_or_path or "\\" in db_name_or_path:
        db_path = os.path.abspath(db_name_or_path)
    else:
        db_path = os.path.abspath(resolve_db(db_name_or_path))

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=timeout, factory=ClosingConnection)
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)};")
    conn.execute("PRAGMA cache_size = -32000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    if db_path not in _DB_PRAGMA_INITIALIZED:
        try:
            if os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes"):
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
            _DB_PRAGMA_INITIALIZED.add(db_path)
        except sqlite3.Error as exc:
            logger.warning(f"[db_paths] WAL-PRAGMA fuer {db_path} fehlgeschlagen: {exc}")
    return conn
