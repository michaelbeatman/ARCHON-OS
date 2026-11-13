"""
FastAPI Router for Milestone 30: Interactive First-Run Web Setup Wizard & Onboarding.

Endpoints:
  - GET  /api/onboarding/status        : Sanitized onboarding status, provider flags & 8 domains
  - POST /api/onboarding/test-provider : SSRF-safe live connectivity & latency probe
  - POST /api/onboarding/complete      : Atomic 4-step configuration persistence
  - POST /api/onboarding/skip          : Dismiss auto-open prompt for power users
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from archon.routers._rbac import forbid_viewer_writes, is_configured, require_admin_or_503
from backend import onboarding_wizard

logger = logging.getLogger("archon.routers.onboarding")

router = APIRouter(dependencies=[Depends(forbid_viewer_writes)], tags=["onboarding"])


def _require_admin(request: Request) -> None:
    """Enforces admin role when multi-user auth is enabled or via wired _rbac checker."""
    if is_configured():
        require_admin_or_503(request)
        return
    from archon.routers.auth import require_admin

    require_admin(request)


def _forbid_demo_writes() -> None:
    if onboarding_wizard.is_demo_mode():
        raise HTTPException(
            status_code=403,
            detail="Onboarding mutations are disabled while ARCHON_DEMO_MODE is active.",
        )


def _to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)


class ProviderTestRequest(BaseModel):
    provider: str = Field(..., description="Provider identifier (e.g. openrouter, openai, ollama)")
    api_key: Optional[str] = Field(default="", description="Optional API key to test")
    base_url: Optional[str] = Field(default=None, description="Optional custom endpoint URL")


class CompanyProfileInput(BaseModel):
    company_name: str
    legal_form: Optional[str] = ""
    address: Optional[Union[str, Dict[str, Any]]] = ""
    tax_id: Optional[str] = ""
    vat_id: Optional[str] = ""
    iban: Optional[str] = ""
    bic: Optional[str] = ""
    currency: Optional[str] = "EUR"
    language: Optional[str] = "en"


class ChannelsInput(BaseModel):
    imap_host: Optional[str] = ""
    imap_port: Optional[int] = 993
    smtp_host: Optional[str] = ""
    smtp_port: Optional[int] = 587
    email_user: Optional[str] = ""
    email_password: Optional[str] = None
    bot_token: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    chat_id: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    verify_telegram: Optional[bool] = False
    obsidian_vault_path: Optional[str] = "./obsidian_vault"


class OnboardingCompleteRequest(BaseModel):
    company_profile: Optional[CompanyProfileInput] = None
    company_name: Optional[str] = None
    legal_form: Optional[str] = ""
    address: Optional[Union[str, Dict[str, Any]]] = ""
    tax_id: Optional[str] = ""
    vat_id: Optional[str] = ""
    iban: Optional[str] = ""
    bic: Optional[str] = ""
    currency: Optional[str] = "EUR"
    language: Optional[str] = "en"
    providers: Optional[Dict[str, Any]] = None
    zero_egress: Optional[bool] = False
    channels: Optional[ChannelsInput] = None
    active_domains: Optional[List[Union[str, int]]] = None
    sync_souls: Optional[bool] = True


@router.get("/api/onboarding/status")
def api_onboarding_status() -> Dict[str, Any]:
    """Returns first-run wizard status, boolean provider detection, and 8 specialist domains."""
    return onboarding_wizard.get_onboarding_status()


@router.post("/api/onboarding/test-provider")
def api_onboarding_test_provider(request: Request, payload: ProviderTestRequest) -> Dict[str, Any]:
    """Tests AI provider connectivity with SSRF protection and 5s timeout."""
    _require_admin(request)
    _forbid_demo_writes()

    prov = (payload.provider or "").strip().lower()
    if prov not in onboarding_wizard.SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{payload.provider}'. Supported: {', '.join(onboarding_wizard.SUPPORTED_PROVIDERS.keys())}",
        )

    return onboarding_wizard.test_provider_connection(
        provider=prov,
        api_key=payload.api_key,
        base_url=payload.base_url,
    )


@router.post("/api/onboarding/complete")
def api_onboarding_complete(
    request: Request,
    payload: OnboardingCompleteRequest = Body(...),
) -> Dict[str, Any]:
    """Atomically saves all 4 onboarding wizard steps and marks onboarding.completed = True."""
    _require_admin(request)
    _forbid_demo_writes()

    raw_data = _to_dict(payload)
    try:
        return onboarding_wizard.complete_onboarding(raw_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[Onboarding] Complete failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to persist onboarding configuration.") from exc


@router.post("/api/onboarding/skip")
def api_onboarding_skip(request: Request) -> Dict[str, Any]:
    """Marks onboarding.dismissed = True so power users are not nagged on future loads."""
    _require_admin(request)
    _forbid_demo_writes()
    return onboarding_wizard.skip_onboarding()
