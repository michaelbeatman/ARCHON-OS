"""Tenant-Context- und Auth-Gate-Middlewares (M3 aus main.py).

Reine Extraktion nach dem S3-Muster (Call-Time-Dependency-Injection):
* Kein Rueckimport auf ``main``.
* ``_get_service_token`` und ``_request_has_service_token`` bleiben physisch in
  ``main.py`` (D2 §295) und werden zur Aufrufzeit ueber ``AuthGateDeps`` gereicht.
* Die ``@app.middleware("http")``-Registrierungen bleiben an exakt ihrer alten
  Position in ``main.py`` (vor CORS, Rate-Limit und TraceContext).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, NamedTuple, Set, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger("archon_os")


class AuthGateDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Auth-/Policy-Abhaengigkeiten aus main.py."""

    request_has_service_token: Callable[[Request], bool]
    auth_unavailable_response: Callable[[], JSONResponse]
    auth_public_exact: Set[str]
    auth_public_prefixes: Tuple[str, ...]
    auth_api_prefixes: Tuple[str, ...]
    auth_protected_prefixes: Tuple[str, ...]


async def run_tenant_context_middleware(
    request: Request,
    call_next: Callable[[Request], Any],
    deps: AuthGateDeps,
) -> Any:
    """Bindet optionalen Mandanten-Header (X-Tenant-Id / X-Company-Id) request-lokal via ContextVar."""
    response = None
    hdr_tid = (request.headers.get("X-Tenant-Id") or request.headers.get("X-Company-Id") or "").strip()
    if not hdr_tid:
        from backend.tenant_context import reset_request_tenant, set_request_tenant
        from backend.tenant_context import tenant_context as _tc

        _tok = set_request_tenant(_tc.get_active_tenant_id())
        try:
            response = await call_next(request)
        finally:
            reset_request_tenant(_tok)
    else:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", hdr_tid):
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_tenant_id", "detail": "X-Tenant-Id ist ungueltig."},
            )
        _user = getattr(request.state, "user", None) or {}
        _role = str(_user.get("role", "")).strip().lower()
        _is_service = deps.request_has_service_token(request)
        if not _is_service and _role != "admin":
            return JSONResponse(
                status_code=403,
                content={
                    "error": "tenant_forbidden",
                    "detail": "Mandantenwechsel per Header ist nur Admins und Service-Tokens erlaubt.",
                },
            )
        try:
            from backend.tenant_context import (
                reset_request_tenant,
                set_request_tenant,
                tenant_context,
            )

            known = False
            try:
                mgr = tenant_context._get_corporate_manager()
                companies = mgr.list_companies() or []
                known = any(
                    str(c.get("id") or "").strip().lower() == hdr_tid.lower()
                    for c in companies
                    if isinstance(c, dict)
                )
            except Exception:
                known = False
            if not known and hdr_tid.lower() != "default":
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "tenant_not_found",
                        "detail": "X-Tenant-Id referenziert keinen bekannten Mandanten.",
                    },
                )
            tok = set_request_tenant(hdr_tid)
            try:
                response = await call_next(request)
            finally:
                reset_request_tenant(tok)
        except Exception as err:
            logger.error(f"[Tenant] Kontext konnte nicht gesetzt werden: {err}")
            return deps.auth_unavailable_response()
    if response is None:
        response = await call_next(request)
    if request.url.path == "/static/sw_calendar.js":
        response.headers["Service-Worker-Allowed"] = "/"
    return response


async def run_auth_gate_middleware(
    request: Request,
    call_next: Callable[[Request], Any],
    deps: AuthGateDeps,
) -> Any:
    """Blockt API-Aufrufe ohne gueltige Session, sobald Multi-User aktiv ist (fail-closed)."""
    try:
        from backend.auth_service import auth_service as _auth

        auth_enabled = _auth.is_auth_enabled()
    except Exception as err:
        logger.error(f"[Auth] Gate kann die Konfiguration nicht lesen: {err}")
        return deps.auth_unavailable_response()

    if not auth_enabled:
        return await call_next(request)

    path = request.url.path
    is_forced_api = path.startswith(deps.auth_api_prefixes)
    if path == "/mcp" or (path.startswith("/mcp/") and path != "/mcp/info"):
        return await call_next(request)
    if not is_forced_api and (path in deps.auth_public_exact or path.startswith(deps.auth_public_prefixes)):
        return await call_next(request)

    if deps.request_has_service_token(request):
        return await call_next(request)

    token = ""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "x-archon-session" in request.headers:
        token = request.headers.get("x-archon-session", "").strip()
    elif "archon_session" in request.cookies:
        token = request.cookies.get("archon_session", "").strip()

    try:
        session_user = _auth.verify_session(token) if token else None
        if session_user:
            session_user["auth_enabled"] = True
            request.state.user = session_user
            user_role = str(session_user.get("role", "")).strip().lower()
            if (
                request.method in ("POST", "PUT", "DELETE", "PATCH")
                and user_role in ("viewer", "anonymous", "")
                and not path.startswith("/api/auth/")
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "forbidden",
                        "detail": f"Nur Administratoren oder Operatoren duerfen schreibende Aktionen ausfuehren (erkannte Rolle: {user_role or 'anonymous'}).",
                    },
                )
            return await call_next(request)
    except Exception as err:
        logger.error(f"[Auth] Session-Prüfung fehlgeschlagen: {err}")
        return deps.auth_unavailable_response()

    if path.startswith("/api/") or is_forced_api:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Login erforderlich", "login_url": "/login"},
        )
    if path.startswith(deps.auth_protected_prefixes):
        return RedirectResponse(url=f"/login?next={path}", status_code=307)
    return RedirectResponse(url=f"/login?next={path}", status_code=307)
