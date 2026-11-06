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

logger = logging.getLogger("archon.db_paths")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")

# Hermes-Heimat (Agenten-State, Sessions, Kanban) — bleibt getrennt vom App-Data-Ordner.
HERMES_DATA_DIR = "/opt/data" if os.path.isdir("/opt/data") else os.path.expanduser("~/.hermes")

# Verbindliche Zuordnung: Datei -> Heimatverzeichnis.
DB_HOME = {
    "agentic_memory.db": APP_DATA_DIR,
    "contracts.db": APP_DATA_DIR,
    "deals.db": APP_DATA_DIR,
    "corporate.db": APP_DATA_DIR,
    "kanban.db": HERMES_DATA_DIR,
    "state.db": HERMES_DATA_DIR,
    "shared-state.db": HERMES_DATA_DIR,
    "projects.db": HERMES_DATA_DIR,
}


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


def resolve_db(filename: str) -> str:
    """Liefert den Pfad zur richtigen DB-Datei. Erzeugt keine Datei."""
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
