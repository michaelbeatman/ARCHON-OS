"""F2: RBAC-/Identitaets-Guards fuer ``backend/**`` (D09/H-09-2).

``backend/**`` darf ``archon.routers`` nicht importieren. Die Original-Guards
bleiben bewusst in ``archon/routers/_rbac.py`` bzw. ``archon/routers/auth.py``:
dort patchen 13 Testdateien ``_checker`` / ``configure`` und ``main.py:3157``
verdrahtet den Rollenzaun. Ein Verschieben der SSOT wuerde diese
Patch-Punkte zu toten Attributen machen (Invariante: kein stilles Auflösen
bewaehrter Contracts).

Dieses Modul haelt daher NUR eine Registry mit den injizierten ORIGINAL-
Callables (A1-Muster, vgl. ``archon/core/permissions.py``) und stellt duenne
Wrapper mit den exakten Original-Signaturen bereit. ``main.py`` verdrahtet die
Registry einmal beim Import. Ohne Verdrahtung sperren die Guards fail-closed
(503) - identisch zum bisherigen Zustand bei ``_checker is None``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

__all__ = (
    "configure",
    "is_configured",
    "forbid_viewer_writes",
    "require_admin_or_503",
    "require_session_actor",
    "get_current_user_from_request",
)

_GUARDS: Dict[str, Optional[Callable[..., Any]]] = {
    "forbid_viewer_writes": None,
    "require_admin_or_503": None,
    "require_session_actor": None,
    "get_current_user_from_request": None,
}


def configure(**guards: Callable[..., Any]) -> None:
    """Injiziert die Original-Guards aus ``main.py`` (einmalig beim Import)."""
    unknown = set(guards) - set(_GUARDS)
    if unknown:
        raise ValueError(f"unbekannte Guards: {sorted(unknown)}")
    _GUARDS.update(guards)


def is_configured() -> bool:
    """True, wenn alle vier Guards verdrahtet sind (Diagnose, kein Gate)."""
    return all(fn is not None for fn in _GUARDS.values())


def _get(name: str) -> Callable[..., Any]:
    fn = _GUARDS.get(name)
    if fn is None:
        raise HTTPException(
            status_code=503,
            detail=f"RBAC-Guard '{name}' nicht verdrahtet; Aktion gesperrt.",
        )
    return fn


def forbid_viewer_writes(request: HTTPConnection) -> None:
    """Router-Dependency, Signatur 1:1 zu ``_rbac.forbid_viewer_writes``."""
    _get("forbid_viewer_writes")(request)


def require_admin_or_503(request: Request) -> None:
    """Signatur 1:1 zu ``_rbac.require_admin_or_503``."""
    _get("require_admin_or_503")(request)


def require_session_actor(request: Request) -> str:
    """Signatur 1:1 zu ``_rbac.require_session_actor``."""
    return _get("require_session_actor")(request)


def get_current_user_from_request(request: Request) -> dict:
    """Signatur 1:1 zu ``auth.get_current_user_from_request``.

    Fehlende Verdrahtung -> RuntimeError. ``operations_api._task_creator_actor``
    schluckt ihn weiterhin per ``except Exception: return ""`` (D14, fail-closed).
    """
    fn = _GUARDS.get("get_current_user_from_request")
    if fn is None:
        raise RuntimeError("Session-Identitaet nicht verdrahtet (F2-Injektion fehlt)")
    return fn(request)
