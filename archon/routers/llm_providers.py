"""LLM-Provider-Verwaltung (Auswahl, Keys, Preise, Privacy-Routing)."""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request

from archon.routers._rbac import require_admin_or_503
from pydantic import BaseModel

from archon.core.runtime import logger  # noqa: F401

router = APIRouter()


class LLMProviderSaveKeyRequest(BaseModel):
    env_name: str
    key_value: str


class LLMProviderSelectRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None

@router.get("/api/llm-providers/models")
async def api_get_llm_provider_models(provider: str = Query("openrouter")):
    p = (provider or "openrouter").lower().strip()
    # 1. Vollständiger OpenRouter-Katalog aus Preiscache oder Live-API
    if p == "openrouter":
        try:
            p_res = get_llm_prices(refresh=0)
            if p_res.get("status") == "ok" and p_res.get("prices"):
                all_models = sorted(list(p_res["prices"].keys()))
                if len(all_models) > 10:
                    return {"status": "ok", "provider": p, "models": all_models}
        except Exception:
            pass
    # 2. Dynamische Modelle aus api_provider
    try:
        import api_provider
        dyn_models = api_provider.list_provider_models(p)
        if dyn_models and len(dyn_models) > 0:
            return {"status": "ok", "provider": p, "models": dyn_models}
    except Exception:
        pass
    catalog = {
        "openrouter": [
            "deepseek/deepseek-v4.1-flash",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-r1",
            "deepseek/deepseek-v4-flash-0731",
            "z-ai/glm-5.3",
            "anthropic/claude-3.7-sonnet",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
            "google/gemini-2.5-flash-image",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "openai/o3-mini",
            "meta-llama/llama-3.3-70b-instruct",
            "qwen/qwen-2.5-coder-32b-instruct"
        ],
        "omniroute": [
            "omniroute/free-forever",
            "auto/best-free",
            "auto/best-reasoning",
            "auto/best-coding",
            "auto/best-fast",
            "deepseek/deepseek-v4-flash-0731",
            "google/gemini-2.5-flash",
            "anthropic/claude-3.7-sonnet"
        ],
        "google": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-image",
            "gemini-2.0-flash"
        ],
        "anthropic": [
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest"
        ],
        "openai": [
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "o1"
        ],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "deepseek-r1-distill-llama-70b"
        ],
        "deepseek": [
            "deepseek-chat",
            "deepseek-reasoner"
        ],
        "ollama": [
            "llama3.2:latest",
            "qwen2.5-coder:14b",
            "deepseek-r1:14b",
            "hermes3:latest"
        ]
    }
    models = list(catalog.get(p, catalog["openrouter"]))
    global _openrouter_price_cache
    if p == "openrouter" and _openrouter_price_cache:
        for mid in _openrouter_price_cache.keys():
            if mid not in models:
                models.append(mid)
    return {"status": "success", "provider": p, "models": models}


@router.get("/api/llm-providers")
def get_llm_providers():
    try:
        import api_provider
        active_cfg = api_provider.read_active_config()
        keys = api_provider.collect_keys()
        all_catalog = api_provider.list_providers()
        
        provider_map = {p["id"]: p for p in all_catalog if isinstance(p, dict) and "id" in p}
        
        # Featured providers in intuitive order
        featured_ids = ["local", "mistral", "omniroute", "openrouter", "google", "groq", "openai", "nvidia", "anthropic", "deepseek"]

        if "local" not in provider_map:
            provider_map["local"] = {
                "id": "local",
                "name": "Lokales LLM (Ollama / LM Studio)",
                "env": ["LOCAL_LLM_URL", "OLLAMA_HOST"],
                "api": "http://127.0.0.1:11434/v1",
                "model_count": 8,
                "privacy_badge": "100% On-Premise"
            }
        if "mistral" not in provider_map:
            provider_map["mistral"] = {
                "id": "mistral",
                "name": "Mistral AI (EU / Paris - DSGVO-konform)",
                "env": ["MISTRAL_API_KEY"],
                "api": "https://api.mistral.ai/v1",
                "model_count": 12,
                "privacy_badge": "EU-DSGVO Zertifiziert"
            }
        
        if "omniroute" not in provider_map:
            provider_map["omniroute"] = {
                "id": "omniroute",
                "name": "OmniRoute Gateway (Lokal / Proxy)",
                "env": ["OMNIROUTE_API_KEY"],
                "api": "http://omniroute:20128/v1",
                "model_count": 50
            }
        
        result_providers = []
        for pid in featured_ids:
            p_data = provider_map.get(pid)
            if not p_data:
                continue
            
            envs = p_data.get("env", []) or []
            found_key_name = None
            found_val = None
            for e in envs:
                if keys.get(e):
                    found_key_name = e
                    found_val = keys.get(e)
                    break
            
            is_active = (active_cfg.get("provider") == pid) or (pid == "omniroute" and "omniroute" in (active_cfg.get("base_url") or ""))
            
            masked = ""
            if found_val:
                if len(found_val) > 8:
                    masked = found_val[:4] + "..." + found_val[-4:]
                else:
                    masked = "••••••••"
            
            result_providers.append({
                "id": pid,
                "name": p_data.get("name", pid),
                "is_active": is_active,
                "has_key": bool(found_val) or (pid == "omniroute"),
                "key_env": found_key_name or (envs[0] if envs else f"{pid.upper()}_API_KEY"),
                "key_masked": masked,
                "model_count": p_data.get("model_count", 0),
                "api": p_data.get("api"),
                "default_model": active_cfg.get("model") if is_active else api_provider.find_default_model_for_provider(pid)
            })
        
        return {
            "status": "ok",
            "active_config": active_cfg,
            "providers": result_providers
        }
    except Exception as e:
        logger.error(f"[llm-providers] get error: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "providers": []}


_openrouter_price_cache = None


_openrouter_price_timestamp = 0


@router.get('/api/llm-providers/prices')
def get_llm_prices(refresh: int = 0):
    global _openrouter_price_cache, _openrouter_price_timestamp
    try:
        now = time.time()
        if refresh or _openrouter_price_cache is None or (now - _openrouter_price_timestamp > 3600):
            import urllib.request
            import json
            req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data", [])
                formatted = {}
                for m in data:
                    pricing = m.get("pricing", {})
                    prompt_price = float(pricing.get("prompt", 0))
                    completion_price = float(pricing.get("completion", 0))
                    formatted[m["id"]] = {
                        "name": m.get("name") or m["id"],
                        "prompt_1m": prompt_price * 1000000,
                        "completion_1m": completion_price * 1000000,
                        "context_length": m.get("context_length", 0)
                    }
                _openrouter_price_cache = formatted
                _openrouter_price_timestamp = now
                return {"status": "ok", "prices": formatted}
        else:
            return {"status": "ok", "prices": _openrouter_price_cache}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": _openrouter_price_cache or {}}


def get_llm_provider_models(provider: str = ""):
    try:
        import api_provider
        pid = (provider or "").strip().lower()
        if not pid:
            return {"status": "ok", "provider": "", "models": []}
            
        models = api_provider.list_provider_models(pid)
        if not models and pid == "omniroute":
            models = ["auto/best-coding", "auto/best-reasoning", "auto/best-vision", "deepseek-ai/DeepSeek-V4-Pro", "qwen/Qwen3.6-27B"]
        return {"status": "ok", "provider": pid, "models": models}
    except Exception as e:
        return {"status": "error", "provider": provider, "models": [], "message": str(e)}


@router.post("/api/llm-providers/select")
def select_llm_provider(request: Request, req: LLMProviderSelectRequest):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        import api_provider
        pid = req.provider.strip().lower()
        model = req.model.strip() if req.model else None
        if model and "session-guard" in model:
            model = None
        
        if pid == "omniroute":
            base_url = req.base_url or "http://omniroute:20128/v1"
            chosen_model = model or "auto/best-coding"
            res = api_provider.set_provider_model(provider="omniroute", model=chosen_model)
            api_provider._set_model_block(chosen_model, "omniroute", base_url)
        else:
            res = api_provider.set_provider_model(provider=pid, model=model)
            # Remove base_url when switching away from omniroute
            api_provider._set_model_block(res.get("model") or model or "", pid, None)
            
        return {"status": "ok", "result": res, "active": api_provider.read_active_config()}
    except Exception as e:
        logger.error(f"[llm-providers] select error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/llm-providers/save-key")
def save_llm_provider_key(request: Request, req: LLMProviderSaveKeyRequest):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    env_key = req.env_name.strip()
    val = req.key_value.strip()
    # R-15: Validierung AUSSERHALB des try/except — das blanket-except verwandelte
    # das HTTPException(400) sonst in HTTP 200 mit {"status": "error"}.
    if not env_key or not val:
        raise HTTPException(status_code=400, detail="Missing key name or value")
    try:
        import api_provider
        os.environ[env_key] = val
        env_path = api_provider.ENV_PATH
        if env_path:
            api_provider.set_env_value(env_path, env_key, val)
            
        deploy_res = api_provider.deploy_keys(dry_run=False)
        # R-15 (2. Teil): "erfolgreich hinterlegt und verteilt" nur melden, wenn
        # deploy_keys wirklich ok ist — sonst wird ein Verteilungsfehler zur
        # Erfolgsmeldung.
        if deploy_res.get("status") != "ok":
            logger.warning(f"[llm-providers] save-key: Verteilung meldet '{deploy_res.get('status')}'")
            return {"status": "error", "message": f"{env_key} hinterlegt, aber Verteilung fehlgeschlagen ({deploy_res.get('status')}).", "deploy": deploy_res}
        return {"status": "ok", "message": f"{env_key} erfolgreich hinterlegt und verteilt", "deploy": deploy_res}
    except Exception as e:
        logger.error(f"[llm-providers] save-key error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/api/llm-providers/privacy-status")
def api_get_privacy_status():
    """Gibt den aktuellen Datenschutz- und Verbindungsstatus für Lokal-LLM und DSGVO zurück (t-c4489c)."""
    try:
        from backend.privacy_router import get_overall_privacy_status
        return get_overall_privacy_status()
    except Exception as e:
        logger.error(f"[privacy-status] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/llm-providers/privacy-routing")
def api_save_privacy_routing(request: Request, payload: Dict[str, Any] = Body(...)):
    """Aktualisiert die Richtlinien für sensibles On-Premise Routing und EU-Fallback (t-c4489c)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.privacy_router import save_privacy_config
        saved = save_privacy_config(payload, operator="operator")
        return {"status": "ok", "config": saved}
    except Exception as e:
        logger.error(f"[privacy-routing] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/llm-providers/test-connection")
def api_test_provider_connection(payload: Dict[str, Any] = Body(...)):
    """Testet die Live-Verbindung zu einem lokalen LLM oder Mistral AI (t-c4489c)."""
    try:
        from backend.privacy_router import test_endpoint_sync
        provider = payload.get("provider", "local")
        url = payload.get("url", "http://127.0.0.1:11434/v1")
        api_key = payload.get("api_key")
        model = payload.get("model")
        res = test_endpoint_sync(provider=provider, url=url, api_key=api_key, model=model)
        return {"status": "ok", "result": res}
    except Exception as e:
        logger.error(f"[test-connection] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
