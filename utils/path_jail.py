"""
Pfad-Jail für Archon OS.

Zweck: Jeder dateibasierte Endpunkt darf ausschliesslich innerhalb
definierter Wurzelverzeichnisse lesen/schreiben. Damit sind Path-Traversal
(../..), absolute Systempfade (/etc/passwd) und Symlink-Escapes blockiert.

Benutzung:
    from utils.path_jail import safe_path, PathJailError

    p = safe_path(user_input, must_exist=True)          # Lesen
    p = safe_path(user_input, allow_write=True)          # Schreiben
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

__all__ = ["PathJailError", "safe_path", "safe_path_within", "allowed_roots", "is_allowed"]


class PathJailError(PermissionError):
    """Pfad liegt ausserhalb der erlaubten Wurzeln."""


def _env_roots() -> list[str]:
    raw = os.environ.get("ARCHON_FILE_ROOTS", "")
    return [r.strip() for r in raw.split(os.pathsep) if r.strip()]


def _default_roots() -> list[str]:
    roots: list[str] = []
    # Daten- und Workspace-Bereiche (Hauptarbeitsflaeche des Systems)
    roots += [
        "/opt/data",
        "/app/data",
        "/app/agent_workspace",
        "./agent_workspace",
        "./data",
        "data",
    ]
    # Obsidian-Vaults (Host-Mounts)
    roots += [
        "/opt/data/obsidian",
        "/mnt/c/Mein Obsidian",
        os.path.expanduser("~/Documents/Mein Obsidian"),
    ]
    # Hermes-Profile
    roots += [
        os.path.expanduser("~/.hermes"),
        "/root/.hermes",
    ]
    return roots


def allowed_roots(extra: Optional[Iterable[str]] = None) -> list[str]:
    """Liefert die Liste der realpfad-normalisierten Wurzeln."""
    seen: list[str] = []
    for r in [*_env_roots(), *(_default_roots()), *(extra or [])]:
        try:
            real = os.path.realpath(os.path.abspath(os.path.expanduser(str(r))))
        except Exception:
            continue
        if real and real not in seen:
            seen.append(real)
    return seen


def is_allowed(candidate: str, extra_roots: Optional[Iterable[str]] = None) -> bool:
    real = os.path.realpath(os.path.abspath(os.path.expanduser(candidate)))
    for root in allowed_roots(extra_roots):
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def is_within(candidate: str, roots: Iterable[str]) -> bool:
    """Prueft ausschliesslich gegen ``roots`` — die Default-Wurzeln gelten nicht.

    ``safe_path(..., extra_roots=[x])`` *erweitert* das Jail; es verengt es
    nicht. Endpunkte, deren Reichweite ein einziges Verzeichnis ist, brauchen
    deshalb diese Variante (sonst bleibt z. B. ``/opt/data/.env`` erreichbar).
    """
    real = os.path.realpath(os.path.abspath(os.path.expanduser(str(candidate))))
    for root in roots:
        try:
            root_real = os.path.realpath(os.path.abspath(os.path.expanduser(str(root))))
        except Exception:
            continue
        if root_real and (real == root_real or real.startswith(root_real + os.sep)):
            return True
    return False


def safe_filename(name: str) -> str:
    """Reduziert einen (ggf. feindlichen) Dateinamen auf seinen Basisnamen.

    Backslash wird wie ein Separator behandelt (Windows-Semantik), damit
    ``..\\..\\x`` nicht als harmloser Literalname durchgeht. Leere Namen sowie
    ``.``/``..`` werden abgewiesen.
    """
    raw = str(name or "").replace("\x00", "").replace("\\", "/").strip()
    base = os.path.basename(raw).strip()
    if base in ("", ".", ".."):
        raise PathJailError(f"Ungueltiger Dateiname: {name!r}")
    return base


def safe_path_within(
    candidate: str,
    roots: Iterable[str],
    *,
    must_exist: bool = False,
    allow_write: bool = False,
    allow_dirs: bool = True,
) -> str:
    """Wie :func:`safe_path`, aber ausschliesslich innerhalb von ``roots``.

    Gedacht fuer Endpunkte mit fachlich engem Zielverzeichnis (Vault,
    ``raw_docs``, Inbox): die Default-Wurzeln (``/opt/data``, ``/app``,
    ``~/.hermes``) sind hier bewusst **nicht** erlaubt.
    """
    if not candidate or not str(candidate).strip():
        raise PathJailError("Leerer Pfad.")

    root_list = [r for r in (roots or []) if str(r).strip()]
    if not root_list:
        raise PathJailError("Keine erlaubte Wurzel angegeben.")

    raw = str(candidate).strip().strip("\x00")
    if "\x00" in raw:
        raise PathJailError("Ungueltiges Zeichen im Pfad.")

    real = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))

    if not is_within(real, root_list):
        raise PathJailError(f"Pfad ausserhalb der erlaubten Wurzel: {raw}")

    if must_exist and not os.path.exists(real):
        raise PathJailError(f"Pfad existiert nicht: {raw}")

    if not allow_dirs and os.path.isdir(real):
        raise PathJailError(f"Verzeichnis nicht erlaubt: {raw}")

    if allow_write:
        parent = os.path.dirname(real) or "."
        if not is_within(parent, root_list):
            raise PathJailError(f"Zielverzeichnis ausserhalb der Wurzel: {parent}")

    return real


def safe_path(
    candidate: str,
    *,
    must_exist: bool = False,
    allow_write: bool = False,
    extra_roots: Optional[Iterable[str]] = None,
    allow_dirs: bool = True,
) -> str:
    """
    Prueft `candidate` gegen das Jail und gibt den realen Pfad zurueck.

    :param must_exist: Datei/Pfad muss existieren (bei Lesen sinnvoll).
    :param allow_write: auch fuer Schreiboperationen erlaubt (Schreibpfade
                        muessen nicht existieren, aber im Jail liegen).
    :param extra_roots: zusaetzliche erlaubte Wurzeln.
    :param allow_dirs:  Verzeichnisse als Ziel zulassen.
    :raises PathJailError: bei Jail-Verletzung oder fehlender Datei.
    """
    if not candidate or not str(candidate).strip():
        raise PathJailError("Leerer Pfad.")

    raw = str(candidate).strip().strip("\x00")

    # Offensichtliche Traversal-Marker frueh abweisen (Defense in Depth)
    if "\x00" in raw:
        raise PathJailError("Ungueltiges Zeichen im Pfad.")

    real = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))

    if not is_allowed(real, extra_roots):
        raise PathJailError(
            f"Pfad ausserhalb der erlaubten Bereiche: {raw}"
        )

    if must_exist and not os.path.exists(real):
        raise PathJailError(f"Pfad existiert nicht: {raw}")

    if not allow_dirs and os.path.isdir(real):
        raise PathJailError(f"Verzeichnis nicht erlaubt: {raw}")

    if allow_write:
        parent = os.path.dirname(real) or "."
        # Elternverzeichnis muss im Jail liegen (auch wenn es erst entsteht)
        if not is_allowed(parent, extra_roots):
            raise PathJailError(f"Zielverzeichnis ausserhalb des Jails: {parent}")

    return real