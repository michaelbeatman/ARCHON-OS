"""Gemeinsamer Rollenzaun fuer die ausgelagerten Router (RBAC-Paket 2).

Ein Modul, ein Injektionspunkt: `main.py` registriert seine Prueffunktion einmal
per ``configure(require_admin=require_admin)``; jede Router-Funktion ruft danach
``require_admin_or_503(request)`` als **erste** Anweisung auf.

Warum die Umleitung ueber dieses Modul und nicht ein Import aus ``main``:
``main`` importiert die Router — ein Rueckimport waere ein Zyklus. Warum nicht in
jedem Router eine eigene Kopie: neun Kopien derselben fuenfzehn Zeilen driften
auseinander und die Injektion muesste neunmal gepflegt werden.

Fail-closed: ist die Prueffunktion nicht injiziert, sperrt die Route (503) statt
durchzulassen. Ein Rollenzaun, der bei falscher Verdrahtung oeffnet, ist keiner.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request

logger = logging.getLogger("archon.rbac")

_checker: Optional[Callable[[Request], Any]] = None


def configure(require_admin: Optional[Callable[[Request], Any]] = None) -> None:
    """Registriert die Rollenpruefung aus ``main.py`` (einmalig beim Import)."""
    global _checker
    if require_admin is None:
        logger.warning(
            "[RBAC] configure() ohne require_admin — alle geschuetzten Router-Routen sperren."
        )
        return
    _checker = require_admin


def is_configured() -> bool:
    return _checker is not None


def require_admin_or_503(request: Request) -> None:
    """Rollenzaun; ohne Injektion bewusst laut sperren statt still durchlassen."""
    checker = _checker
    if checker is None:
        logger.error("[RBAC] require_admin nicht injiziert — Route sperrt.")
        raise HTTPException(
            status_code=503,
            detail="Rollenzaun nicht verdrahtet (require_admin fehlt); Aktion gesperrt.",
        )
    checker(request)


def forbid_viewer_writes(request: Request) -> None:
    """Router-Dependency: blockiert POST/PUT/DELETE/PATCH fuer Rolle 'viewer'."""
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return
    if request.url.path in ("/api/auth/login", "/api/auth/logout"):
        return
    try:
        from archon.routers.auth import get_current_user_from_request
        user = get_current_user_from_request(request)
    except Exception as exc:
        logger.error("[RBAC] Session-Pruefung in forbid_viewer_writes fehlgeschlagen: %s", exc)
        raise HTTPException(status_code=503, detail="RBAC-Pruefung nicht verfuegbar.")
    role = str(user.get("role") or "").lower()
    if role in ("viewer", "anonymous"):
        raise HTTPException(
            status_code=403,
            detail=f"Nur Administratoren oder Operatoren duerfen schreibende Aktionen ausfuehren (erkannte Rolle: {role}).",
        )
