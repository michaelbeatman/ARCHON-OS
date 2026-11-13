"""
archon/routers/demo.py
Milestone 47 — Public Read-Only Live-Demo Status & Showcase Router.

Endpoints:
- GET /api/demo/status   -> demo_mode flag, tenant summary, locked features, GitHub repo URL
- GET /api/demo/showcase -> full bilingual ('en' | 'de') showcase bundle for Mittelstand Muster GmbH
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request

from backend.demo_mode import (
    DEMO_REPO_URL,
    get_demo_showcase,
    get_demo_status,
    normalize_demo_lang,
)

router = APIRouter(tags=["demo"])


def _resolve_request_lang(request: Request, lang: Optional[str]) -> str:
    if lang and lang.strip():
        return normalize_demo_lang(lang)
    state_lang = getattr(getattr(request, "state", None), "lang", None)
    if isinstance(state_lang, str) and state_lang.strip():
        return normalize_demo_lang(state_lang)
    accept_lang = request.headers.get("accept-language", "").strip().lower()
    if accept_lang.startswith("de") or ",de" in accept_lang:
        return "de"
    if accept_lang.startswith("en"):
        return "en"
    return normalize_demo_lang(None)


@router.get("/api/demo/status")
def api_demo_status(
    request: Request,
    lang: Optional[str] = Query(default=None, description="Language code ('en' or 'de')"),
) -> Dict[str, Any]:
    """Return Live-Demo mode status, tenant info, locked features, and repository URL."""
    resolved_lang = _resolve_request_lang(request, lang)
    status = get_demo_status(lang=resolved_lang)
    status["repo_url"] = DEMO_REPO_URL
    return status


@router.get("/api/demo/showcase")
def api_demo_showcase(
    request: Request,
    lang: Optional[str] = Query(default="en", description="Showcase language ('en' or 'de')"),
) -> Dict[str, Any]:
    """Return the complete bilingual enterprise showcase dataset ('en' | 'de')."""
    resolved_lang = _resolve_request_lang(request, lang)
    return get_demo_showcase(lang=resolved_lang)
