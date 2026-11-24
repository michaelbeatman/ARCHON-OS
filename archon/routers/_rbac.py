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
from starlette.requests import HTTPConnection

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


def get_session_actor(request: Optional[Request], fallback: str = "admin") -> str:
    """Liest den verifizierten Benutzername aus der Session (nie ungeprüft aus JSON-Bodies)."""
    if request is None:
        return fallback
    try:
        from archon.routers.auth import get_current_user_from_request
        user = get_current_user_from_request(request)
        if isinstance(user, dict) and user.get("username"):
            return str(user["username"]).strip()
    except Exception as exc:
        logger.debug(f"[RBAC] Session-Actor konnte nicht ermittelt werden, nutze Fallback '{fallback}': {exc}")
    return fallback


def require_session_actor(request: Request) -> str:
    """P0-3: Strikt verifizierter Actor fuer Freigaben und Audit-Eintraege.

    Kein Fallback auf ``request.state.user`` (beliebig setzbar), kein
    Body-Wert, kein stilles ``"admin"``. Sonst koennen zwei Aufrufe mit
    ``{"approver_id": "alice"}`` / ``{"approver_id": "bob"}`` ein
    Vier-Augen-Prinzip simulieren, ohne dass diese Personen existieren.

    Im lokalen Single-User-Modus (auth aus) bleibt der Fallback-Admin
    zulaessig — aber weiterhin NUR aus der Session-Hilfe, nie aus dem Body.
    """
    from archon.routers.auth import get_current_user_from_request

    try:
        user = get_current_user_from_request(request)
    except Exception as exc:
        logger.error("[RBAC] Actor-Pruefung fehlgeschlagen (fail-closed): %s", exc)
        raise HTTPException(status_code=503, detail="Actor-Pruefung nicht verfuegbar.")

    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Keine verifizierte Identitaet.")
    if user.get("is_service"):
        raise HTTPException(status_code=403, detail="Service-Token duerfen keine Freigaben erteilen.")
    role = str(user.get("role") or "").strip().lower()
    if bool(user.get("auth_enabled")) and role in ("anonymous", "", "viewer"):
        raise HTTPException(status_code=401, detail="Freigaben erfordern eine verifizierte Session.")

    for key in ("username", "user_id", "sub", "email"):
        val = user.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    raise HTTPException(status_code=401, detail="Keine verifizierte Identitaet.")


def _audit_rbac_denial(
    request: Any, *, required_role: str, reason: str, actor: Optional[str] = None
) -> None:
    """D5/F-08: RBAC-Denial signiert in die Zentralkette (append-only).

    Fail-closed: der Zugriff ist hier bereits verweigert. Ein Audit-Fehler darf
    diese Entscheidung NIE in einen Allow kippen — deshalb nur loggen, keine
    Exception werfen. Es werden ausschliesslich Route/Rolle/Grund protokolliert,
    niemals Request-Bodies oder Session-Daten.
    """
    try:
        from backend.audit_log import chained_audit_log

        chain_actor = str(actor or get_session_actor(request, fallback="unknown"))
        chained_audit_log.record_event(
            category="rbac",
            action="rbac_denied",
            agent_id=chain_actor,
            payload={
                "route": str(getattr(getattr(request, "url", None), "path", "") or ""),
                "method": str(getattr(request, "method", "") or ""),
                "required_role": str(required_role),
                "reason": str(reason),
            },
        )
    except Exception as exc:
        logger.error(
            "[RBAC] Audit-Eintrag rbac_denied fehlgeschlagen (Denial bleibt bestehen): %s",
            exc,
        )


def require_admin_or_503(request: Request) -> None:
    """Rollenzaun; ohne Injektion bewusst laut sperren statt still durchlassen."""
    checker = _checker
    if checker is None:
        logger.error("[RBAC] require_admin nicht injiziert — Route sperrt.")
        _audit_rbac_denial(
            request, required_role="admin", reason="require_admin_not_injected"
        )
        raise HTTPException(
            status_code=503,
            detail="Rollenzaun nicht verdrahtet (require_admin fehlt); Aktion gesperrt.",
        )
    try:
        checker(request)
    except HTTPException as exc:
        _audit_rbac_denial(
            request, required_role="admin", reason=f"checker_rejected:{exc.status_code}"
        )
        raise


def forbid_viewer_writes(request: HTTPConnection) -> None:
    """Router-Dependency: blockiert POST/PUT/DELETE/PATCH fuer Rolle 'viewer'."""
    if not isinstance(request, Request):
        return
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return
    if request.url.path in ("/api/auth/login", "/api/auth/logout"):
        return
    try:
        from archon.routers.auth import get_current_user_from_request
        user = get_current_user_from_request(request)
    except Exception as exc:
        logger.error("[RBAC] Session-Pruefung in forbid_viewer_writes fehlgeschlagen: %s", exc)
        _audit_rbac_denial(
            request,
            required_role="admin_or_operator",
            reason="session_check_unavailable",
        )
        raise HTTPException(status_code=503, detail="RBAC-Pruefung nicht verfuegbar.")
    role = str(user.get("role") or "").lower()
    if role in ("viewer", "anonymous"):
        _audit_rbac_denial(
            request,
            required_role="admin_or_operator",
            reason=f"write_forbidden_for_role:{role}",
        )
        raise HTTPException(
            status_code=403,
            detail=f"Nur Administratoren oder Operatoren duerfen schreibende Aktionen ausfuehren (erkannte Rolle: {role}).",
        )
