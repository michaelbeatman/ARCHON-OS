"""2c — reine Auth-/RAG-Policy, aus main.py gehoben (F4-Muster).

Reine Extraktion, keine Logikaenderung. ``main.py`` re-exportiert alle Namen
per ``X as X``, damit Attributzugriffe, Patch-Punkte und die Registrierung in
``_STARTUP_HOOKS`` unveraendert bleiben (u. a. tests/test_rag_key_env.py).

BEWUSST NICHT hierher verschoben (INVARIANTS §3 — keine stillen Aenderungen):
* ``_SERVICE_TOKEN_CACHE`` / ``_get_service_token`` — nutzt ``__file__`` fuer
  den Repo-Root (main.py:940); ein Modulwechsel wuerde den Token-Pfad aendern.
* ``_request_has_service_token`` — stabiler Contract (D2 §295), haengt an
  ``_get_service_token`` und wird zur Laufzeit injiziert.

Der Logger-Name bleibt ``archon_os`` (kein stiller Kanal-Wechsel, vgl. B9).
"""

from __future__ import annotations

import logging
import os
from typing import Set

from fastapi.responses import JSONResponse

logger = logging.getLogger("archon_os")

__all__ = [
    "_AUTH_PUBLIC_EXACT",
    "RAG_API_KEY_ENV",
    "MissingRagApiKeyError",
    "_get_rag_api_key",
    "_check_rag_api_key_config",
    "_auth_unavailable_response",
]

_AUTH_PUBLIC_EXACT: Set[str] = {
    "/", "/health", "/livez", "/readyz", "/metrics", "/favicon.ico", "/openapi.json",
    "/login", "/docs", "/redoc",
    # Randluecken: exakt /static (ohne Slash) wurde vom Prefix "/static/"
    # nicht erfasst und lief in einen Login-Redirect. /mcp/info ist
    # bewusst oeffentlich, wird aber vom Protected-Prefix "/m" erfasst.
    "/static", "/static_v2", "/mcp/info",
    # Kalender-Push (Google/Graph) kommt ohne Session-Token. Absicherung
    # AUSSCHLIESSLICH ueber clientState/watch_id per hmac.compare_digest in
    # backend/operations_calendar.py — bewusst NUR dieser exakte Pfad, kein
    # Prefix, damit kein weiterer /api/-Pfad geoeffnet wird.
    "/api/v1/calendar/webhooks/push",
}

# --- RAG-Sync-Zugang: Env statt Klartext, fail-fast ------------------------
# Der Vault->RAG-Sync braucht einen AnythingLLM-API-Key. Bis 07.11.2026 stand
# er als Literal im Code (hier und in mehreren tools/-Skripten); jetzt kommt er
# ausschliesslich aus der Umgebung. Variablenname bewusst identisch mit
# backend/rag_bridge.py — ein Secret, ein Name, kein zweites Schema.
RAG_API_KEY_ENV = "ANYTHINGLLM_API_KEY"


class MissingRagApiKeyError(RuntimeError):
    """Der RAG-Sync hat keinen API-Key — es wird kein Request abgesetzt."""


def _get_rag_api_key() -> str:
    """Liefert den RAG-API-Key aus der Umgebung.

    Kein stiller Fallback auf einen Default: ein leerer Key endet downstream
    als Auth-Fehler oder als Sync, der nichts tut. Deshalb Exception am
    Nutzungspunkt, damit kein subprocess mit leerem Key startet.
    """
    key = (os.environ.get(RAG_API_KEY_ENV) or "").strip()
    if not key:
        raise MissingRagApiKeyError(
            f"{RAG_API_KEY_ENV} fehlt in der Umgebung. Der Vault->RAG-Sync "
            "startet nicht (kein Fallback-Key, kein Request mit leerem Key)."
        )
    return key


def _check_rag_api_key_config() -> bool:
    """Startcheck: fehlender RAG-Key ist als ERROR sichtbar, kippt den Start nicht.

    Der Key wird nur im Hintergrund-Trigger nach einem Library-Upload mit
    auto_ingest gebraucht. Ein harter Startabbruch wuerde einen Dienst
    verweigern, der ohne die RAG-Funktion voll funktionsfaehig ist — deshalb
    fail-fast am Nutzungspunkt (Exception + ERROR dort) plus diese Zeile.
    """
    try:
        _get_rag_api_key()
    except MissingRagApiKeyError as err:
        logger.error(f"[RAG-Sync] {err}")
        return False
    logger.info(f"[RAG-Sync] API-Key aus {RAG_API_KEY_ENV} geladen.")
    return True


def _auth_unavailable_response() -> JSONResponse:
    """Einheitliche 503-Antwort des Gates, wenn die Pruefung selbst ausfaellt.

    Fail-closed: lieber eine ehrliche 503 als ein stilles Durchlassen.
    """
    return JSONResponse(
        status_code=503,
        content={"error": "auth_unavailable", "detail": "Auth unavailable"},
    )
