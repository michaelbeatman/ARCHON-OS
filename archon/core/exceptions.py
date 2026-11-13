"""
API Exception Handler für lokalisierte Fehlerantworten.
Ersetzt detail-Strings durch code+params, Client übersetzt via archon_i18n.t()
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
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
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": True,
            "code": code,
            "params": params,
            "status_code": status_code,
            # Optional: lokalisierter Text für Clients ohne i18n (curl, logs)
            "detail": f"[{code}] " + legacy_detail
        },
        headers=exc.headers if hasattr(exc, "headers") else None
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Validation Errors mit code+params."""
    lang = get_client_language(request)
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(x) for x in err["loc"])
        errors.append(f"{loc}: {err['msg']}")
    
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "code": "validation_error",
            "params": {"errors": errors},
            "status_code": 422,
            "detail": "Validierungsfehler: " + "; ".join(errors)
        }
    )


async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette HTTPException (z.B. 404 vom Router)."""
    code = DEFAULT_CODES.get(exc.status_code, "error")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "code": code,
            "params": {"detail": exc.detail} if exc.detail else {},
            "status_code": exc.status_code,
            "detail": exc.detail
        }
    )


def register_exception_handlers(app):
    """Registriert alle Exception-Handler in der FastAPI App."""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_http_exception_handler)
    logger.info("[i18n] Exception-Handler registriert (code+params Format)")
