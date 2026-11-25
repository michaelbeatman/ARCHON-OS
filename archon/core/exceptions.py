"""
API Exception Handler für lokalisierte Fehlerantworten.
Ersetzt detail-Strings durch code+params, Client übersetzt via archon_i18n.t()
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Optional
import logging

logger = logging.getLogger("archon.exceptions")


def get_client_language(request: Request) -> str:
    """Ermittelt Client-Sprache aus Accept-Language Header oder Cookie."""
    # 1. Cookie (explizite User-Wahl)
    lang = request.cookies.get("archon_language")
    if lang and lang in SUPPORTED_LANGUAGES:
        return lang
    
    # 2. Accept-Language Header
    accept_lang = request.headers.get("accept-language", "")
    for lang_code in accept_lang.split(","):
        lang_code = lang_code.split(";")[0].strip().lower()
        if lang_code in SUPPORTED_LANGUAGES:
            return lang_code
        # Fallback: nur Sprachcode (de-DE -> de)
        base = lang_code.split("-")[0]
        if base in SUPPORTED_LANGUAGES:
            return base
    
    # 3. Default
    return "de"


SUPPORTED_LANGUAGES = {"de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"}


def _trace_context() -> str:
    """D16/MED: trace_id aus dem aktiven W3C-Kontext (fail-safe leer)."""
    try:
        from backend.trace_context import current_trace_id
        return str(current_trace_id() or "")
    except Exception:
        return ""


def _trace_headers(trace_id: str, base: Optional[dict] = None) -> dict:
    """Antwort-Header ueber den zentralen Helper (X-Trace-Id + traceparent/tracestate).

    Vorhandene Header (z. B. WWW-Authenticate) bleiben erhalten.
    """
    from backend.trace_context import response_trace_headers
    return response_trace_headers(base or {})


# Mapping: HTTP status_code -> Standard-Code falls nicht angegeben
DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthorized", 
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Wandelt HTTPException in code+params Format um."""
    # Wenn detail bereits ein dict mit code/params ist -> durchreichen
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = exc.detail["code"]
        params = exc.detail.get("params", {})
        status_code = exc.status_code
        # Für curl/logs: error aus params als Fallback, falls vorhanden
        legacy_detail = params.get("error", "") if isinstance(params.get("error"), str) else ""
    else:
        # Legacy: detail ist String -> Code ableiten
        code = exc.detail if isinstance(exc.detail, str) and "_" in exc.detail else DEFAULT_CODES.get(exc.status_code, "error")
        params = {"detail": str(exc.detail)} if exc.detail else {}
        status_code = exc.status_code
        legacy_detail = str(exc.detail) if exc.detail else ""
    
    # Sprache für Server-seitiges Logging (optional)
    lang = get_client_language(request)
    trace_id = _trace_context()
    content = {
        "error": True,
        "code": code,
        "params": params,
        "status_code": status_code,
        # Optional: lokalisierter Text für Clients ohne i18n (curl, logs)
        "detail": f"[{code}] " + legacy_detail,
    }
    if trace_id:
        content["trace_id"] = trace_id
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=_trace_headers(trace_id, getattr(exc, "headers", None)),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Validation Errors mit code+params."""
    lang = get_client_language(request)
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(x) for x in err["loc"])
        errors.append(f"{loc}: {err['msg']}")
    trace_id = _trace_context()
    content = {
        "error": True,
        "code": "validation_error",
        "params": {"errors": errors},
        "status_code": 422,
        "detail": "Validierungsfehler: " + "; ".join(errors),
    }
    if trace_id:
        content["trace_id"] = trace_id
    return JSONResponse(
        status_code=422,
        content=content,
        headers=_trace_headers(trace_id),
    )


async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette HTTPException (z.B. 404 vom Router)."""
    code = DEFAULT_CODES.get(exc.status_code, "error")
    trace_id = _trace_context()
    content = {
        "error": True,
        "code": code,
        "params": {"detail": exc.detail} if exc.detail else {},
        "status_code": exc.status_code,
        "detail": exc.detail,
    }
    if trace_id:
        content["trace_id"] = trace_id
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=_trace_headers(trace_id, getattr(exc, "headers", None)),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Audit D07: letzte Verteidigungslinie für unerwartete Fehler.

    Kein Stacktrace an den Client (Info-Disclosure), aber trace_id aus dem
    aktiven W3C-Kontext, damit Log/Audit/HTTP-Antwort korrelierbar bleiben.
    """
    from backend.trace_context import current_trace_id as _current_trace_id

    trace_id = _current_trace_id()
    logger.exception(
        "[Unhandled] %s %s -> 500 (trace_id=%s)",
        request.method, request.url.path, trace_id or "-",
    )
    payload = {
        "error": True,
        "code": "internal_error",
        "detail": "Interner Fehler. Bitte trace_id an die Administration melden.",
        "status_code": 500,
    }
    if trace_id:
        payload["trace_id"] = trace_id
    return JSONResponse(
        status_code=500,
        content=payload,
        headers=_trace_headers(trace_id),
    )


def register_exception_handlers(app):
    """Registriert alle Exception-Handler in der FastAPI App."""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    logger.info("[i18n] Exception-Handler registriert (code+params Format, inkl. 500-Catch-All)")
