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
import re
from typing import Iterable, Optional

from archon.core.config import config
from archon.core.paths import OBSIDIAN_VAULT, OPT_DATA_DIR

__all__ = [
    "PathJailError",
    "safe_path",
    "safe_path_within",
    "safe_filename",
    "safe_identifier",
    "allowed_roots",
    "is_allowed",
]

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_identifier(value: str, label: str = "ID") -> str:
    """Validiert technische IDs (agent_id, skill_id, task_id) gegen Pfad-Traversal."""
    raw = str(value or "").strip()
    if not raw or ".." in raw or "/" in raw or "\\" in raw or "\x00" in raw or not _SAFE_IDENT_RE.fullmatch(raw):
        raise PathJailError(f"Ungueltige {label}: {value!r}")
    return raw


class PathJailError(PermissionError):
    """Pfad liegt ausserhalb der erlaubten Wurzeln."""


def _env_roots() -> list[str]:
    return config.file_roots


def _default_roots() -> list[str]:
    roots: list[str] = []
    # Daten- und Workspace-Bereiche (Hauptarbeitsflaeche des Systems)
    roots += [
        "/opt/data",
        OPT_DATA_DIR,
        "/app/data",
        "/app/agent_workspace",
        "./agent_workspace",
        "./data",
        "data",
    ]
    # Obsidian-Vaults (Host-Mounts)
    roots += [
        OBSIDIAN_VAULT,
        os.path.expanduser("~/Documents/Obsidian Vault"),
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


def _norm_cmp(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(str(p)))))


def is_allowed(candidate: str, extra_roots: Optional[Iterable[str]] = None) -> bool:
    real = _norm_cmp(candidate)
    for root in allowed_roots(extra_roots):
        root_cmp = _norm_cmp(root)
        if real == root_cmp or real.startswith(root_cmp + os.sep):
            return True
    return False


def is_within(candidate: str, roots: Iterable[str]) -> bool:
    """Prueft ausschliesslich gegen ``roots`` — die Default-Wurzeln gelten nicht.

    ``safe_path(..., extra_roots=[x])`` *erweitert* das Jail; es verengt es
    nicht. Endpunkte, deren Reichweite ein einziges Verzeichnis ist, brauchen
    deshalb diese Variante (sonst bleibt z. B. ``/opt/data/.env`` erreichbar).
    """
    if isinstance(roots, (str, bytes, os.PathLike)):
        raise TypeError("roots muss ein Iterable von Pfaden sein, kein einzelner String/Pfad.")
    real = _norm_cmp(candidate)
    for root in roots:
        try:
            root_real = _norm_cmp(str(root))
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
    if isinstance(roots, (str, bytes, os.PathLike)):
        raise TypeError("roots muss ein Iterable von Pfaden sein, kein einzelner String/Pfad.")

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