"""
Locale Middleware: setzt request.state.lang aus Accept-Language Header.
Wird von Exception-Handler und Routern für server-seitige Lokalisierung genutzt.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SUPPORTED_LANGUAGES = {"de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"}


class LocaleMiddleware(BaseHTTPMiddleware):
    """Extrahiert Sprache aus Request und setzt request.state.lang."""
    
    async def dispatch(self, request: Request, call_next):
        # Sprache ermitteln (Priorität: Cookie > Accept-Language > Default)
        lang = request.cookies.get("archon_language", "")
        if lang not in SUPPORTED_LANGUAGES:
            accept_lang = request.headers.get("accept-language", "")
            for lang_code in accept_lang.split(","):
                lang_code = lang_code.split(";")[0].strip().lower()
                if lang_code in SUPPORTED_LANGUAGES:
                    lang = lang_code
                    break
                base = lang_code.split("-")[0]
                if base in SUPPORTED_LANGUAGES:
                    lang = base
                    break
        
        if lang not in SUPPORTED_LANGUAGES:
            lang = "de"
        
        request.state.lang = lang
        
        response = await call_next(request)
        
        # Vary Header für korrektes Caching
        response.headers["Vary"] = "Accept-Language, Cookie"
        
        return response
