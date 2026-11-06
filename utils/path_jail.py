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

__all__ = ["PathJailError", "safe_path", "allowed_roots", "is_allowed"]


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