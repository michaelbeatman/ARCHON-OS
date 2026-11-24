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

# F-013 / D03: einzige autoritative busy_timeout für ALLE SQLite-Verbindungen
# (S-3.1). Früher standen 15000/10000/1500/5000 verstreut in den Modulen —
# Drift und Lock-Contention waren die Folge. Alle Module importieren diese
# Konstante; `audit_busy_timeout_ssot()` macht die SSOT-Behauptung prüfbar.
DB_BUSY_TIMEOUT_MS = 5000
DB_BUSY_TIMEOUT_S = DB_BUSY_TIMEOUT_MS / 1000.0

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# W6: Test-DB-Isolation. Wenn pytest und der laufende Container gleichzeitig
# auf dasselbe Bind-Mount ./data/*.db schreiben, entsteht WAL-Korruption
# (am 23.11. passiert). Mit ARCHON_DATA_DIR zeigt ALLE DB-Auflösung auf ein
# getrenntes Verzeichnis. Muss VOR dem Import der App-Module gesetzt sein.
APP_DATA_DIR = os.path.abspath(
    os.getenv("ARCHON_DATA_DIR", "").strip() or os.path.join(WORKSPACE_DIR, "data")
)

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
    # EIN Resolver: bei aktiver Voll-Isolation (Benutzerentscheidung 22.11.)
    # ist tenant_context.resolve_active_db die einzige Autoritaet fuer alle
    # mandantenfaehigen DBs. System-DBs ausserhalb ISOLATED/CONSOLIDATED
    # laufen deterministisch ueber den Konsolidierungs-/Heimat-Resolver
    # (kein stilles ValueError-Catch-and-Fallthrough mehr, d03).
    # D03/HIGH: bei FULL_TENANT_ISOLATION darf ein Resolverfehler NIE auf
    # einen nicht-Mandanten-Pfad zurückfallen (still Vermischung).
    _full_isolation = os.environ.get("ARCHON_TENANT_FULL_ISOLATION", "1").strip().lower() not in ("0", "false", "no", "off")
    try:
        from backend.tenant_context import (
            CONSOLIDATED_TENANT_DBS,
            FULL_TENANT_ISOLATION,
            ISOLATED_TENANT_DBS,
            tenant_context,
        )
        if FULL_TENANT_ISOLATION and (base in ISOLATED_TENANT_DBS or base in CONSOLIDATED_TENANT_DBS):
            return tenant_context.resolve_active_db(base)
    except Exception as exc:
        if _full_isolation:
            raise RuntimeError(
                f"[db_paths] Tenant-Resolver fehlgeschlagen bei FULL_TENANT_ISOLATION "
                f"für {filename}: {exc}"
            ) from exc
        logger.debug(f"[db_paths] Tenant-Resolver nicht verfuegbar: {exc}")
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


def get_db_connection(db_name_or_path: str, timeout: Optional[float] = None) -> sqlite3.Connection:
    """Erzeugt eine gehärtete ClosingConnection mit busy_timeout und WAL-Modus.

    D03: `timeout` wird nur noch aus Kompatibilitätsgründen akzeptiert und
    ignoriert. Sowohl der sqlite3.connect()-Parameter als auch der PRAGMA
    kommen ausschließlich aus der SSOT `DB_BUSY_TIMEOUT_MS` (5000 ms). Ein
    abweichender Aufruferwert wird protokolliert, aber nie wirksam.
    """
    if timeout is not None and float(timeout) != DB_BUSY_TIMEOUT_S:
        logger.debug(
            "[db_paths] Ignoriere abweichenden timeout=%ss; SSOT=%s ms.",
            timeout, DB_BUSY_TIMEOUT_MS,
        )
    if os.path.isabs(db_name_or_path) or "/" in db_name_or_path or "\\" in db_name_or_path:
        db_path = os.path.abspath(db_name_or_path)
    else:
        db_path = os.path.abspath(resolve_db(db_name_or_path))

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=DB_BUSY_TIMEOUT_S, factory=ClosingConnection)
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS};")
    # W2: SQLite schaltet foreign_keys standardmässig AUS. Ohne dieses
    # PRAGMA wirkten deklarierte Relations und ON DELETE CASCADE nirgends
    # (verwaiste Zeilen in tasks/task_links, sessions/messages, ...).
    conn.execute("PRAGMA foreign_keys = ON;")
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


def audit_busy_timeout_ssot(root_dir: Optional[str] = None) -> list[tuple[str, int, str]]:
    """Read-only AST-Scan: findet vom SSOT abweichende busy_timeout-Setzer.

    D03: Die SSOT-Behauptung soll nicht nur im Kommentar stehen. Diese
    Funktion liefert ``[(relative_datei, zeile, literal), ...]``; eine leere
    Liste bedeutet, dass außerhalb dieser Datei kein *abweichender* Wert
    gesetzt wird. Literale mit 5000 ms sind zulässig (SSOT-konform), alle
    anderen (z.B. 10000/15000) sind Drift. Aufgerufen aus der Verifikation /
    als CI-Gate von außen.
    """
    import re as _re

    root = os.path.abspath(root_dir or WORKSPACE_DIR)
    offenders: list[tuple[str, int, str]] = []
    # Nur Code-Verzeichnisse; Archive/Vaults/Backups/venvs sind irrelevant
    # und würden den Scan auf Windows minutenlang blockieren.
    code_dirs = ("backend", "archon", "scripts", "tests", "utils", "tools",
                 "views", "plugins", "config")
    files: list[str] = []
    for d in code_dirs:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x != "__pycache__"]
            files.extend(os.path.join(dirpath, f) for f in filenames if f.endswith(".py"))
    files.extend(
        os.path.join(root, f) for f in os.listdir(root)
        if f.endswith(".py") and os.path.isfile(os.path.join(root, f))
    )
    pattern = _re.compile(r"busy_timeout\s*=\s*(\d+)", _re.I)
    for full in files:
        rel = os.path.relpath(full, root).replace("\\", "/")
        if rel == "backend/db_paths.py":
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                for lineno, line in enumerate(fh, 1):
                    match = pattern.search(line)
                    if match and int(match.group(1)) != DB_BUSY_TIMEOUT_MS:
                        offenders.append((rel, lineno, match.group(1)))
        except OSError:
            continue
    return sorted(offenders)
