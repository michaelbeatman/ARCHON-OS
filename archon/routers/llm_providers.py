"""LLM-Provider-Verwaltung (Auswahl, Keys, Preise, Privacy-Routing)."""

import datetime
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi import Depends as _ArchonDepends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from archon.core.runtime import logger  # noqa: F401
from archon.routers._rbac import (
    forbid_viewer_writes as _forbid_viewer_writes,
)
from archon.routers._rbac import (
    require_admin_or_503,
    require_session_actor,
)
from backend.credential_masking import mask_secret
from backend.llm_prices import (
    _get_llm_prices_impl,
    get_llm_prices,
    get_price_cache,
)

# F1a: Preis-SSOT liegt in backend/ (backend/** darf archon.routers nicht
# importieren). Re-Export haelt main.py:1093 / chat.py:50 unveraendert.
router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])

# M98: verwaltete ausgehende Provider-Keys. Der Katalog ist Source of Truth
# fuer die Env-Namen; die Fallback-Tabelle greift nur, wenn der Hermes-Katalog
# (models_dev_cache.json) fehlt (z. B. in isolierten Tests).
_MANAGED_PROVIDER_KEYS: tuple[tuple[str, str], ...] = (
    ("openrouter", "OpenRouter"),
    ("google", "Google Gemini"),
    ("omniroute", "OmniRoute Gateway"),
    ("groq", "Groq"),
    ("openai", "OpenAI"),
)
_FALLBACK_PROVIDER_ENVS: Dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "omniroute": ("OMNIROUTE_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
}
# OmniRoute-Scopes sind Routing-Profile und werden auf erlaubte Modell-Aliase
# abgebildet. Nicht identisch mit den scopes eingehender Archon-Tokens.
_OMNIROUTE_SCOPE_MODELS: Dict[str, str] = {
    "free": "omniroute/free-forever",
    "best_free": "auto/best-free",
    "best_reasoning": "auto/best-reasoning",
    "best_coding": "auto/best-coding",
    "best_fast": "auto/best-fast",
}
_OMNIROUTE_SCOPE_ENV = "OMNIROUTE_SCOPE"
_DEFAULT_OMNIROUTE_BASE_URL = "http://omniroute:20128/v1"
_DISALLOWED_ENV_KEYS = frozenset(
    {"PATH", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "HOME", "SHELL", "USER"}
)


def _is_allowed_provider_env_key(env_key: str) -> bool:
    """Einzige Allowlist fuer Provider-Env-Namen (save-key und M98-Endpunkte)."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*_(?:API_KEY|TOKEN|KEY)", env_key):
        return False
    return env_key not in _DISALLOWED_ENV_KEYS


def _provider_env_names(provider: str) -> List[str]:
    """Loest Env-Namen aus dem Provider-Katalog, nie aus dem Provider-Parameter."""
    import api_provider

    catalog = api_provider.load_provider_catalog()
    entry = catalog.get(provider)
    names: List[str] = []
    if isinstance(entry, dict):
        names = [str(e).strip() for e in (entry.get("env") or []) if str(e).strip()]
    allowed = [n for n in dict.fromkeys(names) if _is_allowed_provider_env_key(n)]
    if not allowed:
        allowed = [
            n for n in _FALLBACK_PROVIDER_ENVS.get(provider, ())
            if _is_allowed_provider_env_key(n)
        ]
    return allowed


def _env_file_updated_at() -> Optional[str]:
    """Aenderungszeitpunkt der aktiven Env-Datei (keine Secret-Werte)."""
    import api_provider

    path = api_provider.ENV_PATH
    try:
        if path and os.path.exists(path):
            return datetime.datetime.fromtimestamp(
                os.path.getmtime(path), datetime.timezone.utc
            ).isoformat()
    except OSError:
        return None
    return None


def _key_source(env_name: Optional[str], has_key: bool) -> str:
    if not has_key or not env_name:
        return "none"
    return "process_env" if os.environ.get(env_name) else "env_file"


def _omniroute_scope() -> str:
    import api_provider

    scope = str(os.environ.get(_OMNIROUTE_SCOPE_ENV) or "").strip()
    if not scope:
        scope = str(
            api_provider.read_env_value(api_provider.ENV_PATH, _OMNIROUTE_SCOPE_ENV) or ""
        ).strip()
    return scope if scope in _OMNIROUTE_SCOPE_MODELS else "best_coding"


def _provider_key_targets() -> List[str]:
    """Alle Env-Dateien, in denen ein Provider-Key stehen kann (Revoke-Pfad)."""
    import api_provider

    paths = [
        str(api_provider.ENV_PATH),
        os.path.join(api_provider.HERMES_DATA, ".env"),
        os.path.join(api_provider.HOME, ".env"),
    ]
    if os.path.isdir(api_provider.PROFILES_DIR):
        for name in sorted(os.listdir(api_provider.PROFILES_DIR)):
            paths.append(os.path.join(api_provider.PROFILES_DIR, name, ".env"))
    return list(dict.fromkeys(p for p in paths if p))


class ProviderKeySetRequest(BaseModel):
    """Klartext kommt nur im Request-Body an und verlaesst die Antwort nie."""

    model_config = ConfigDict(extra="ignore")
    key_value: str = Field(min_length=1, max_length=4096)


class OmniRouteScopeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scope: str = Field(min_length=1, max_length=40)
    model: Optional[str] = Field(default=None, max_length=160)
    base_url: Optional[str] = Field(default=None, max_length=500)


class LLMProviderSaveKeyRequest(BaseModel):
    env_name: str
    key_value: str


class LLMProviderSelectRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None


class PrivacyRoutingRequest(BaseModel):
    """Typisierte Felder; weitere Legacy-Keys bleiben erlaubt (extra='allow')."""
    model_config = ConfigDict(extra="allow")
    zero_egress_strict: Optional[bool] = None
    sensitive_local_routing: Optional[bool] = None
    hard_block_on_local_offline: Optional[bool] = None
    fallback_to_eu: Optional[bool] = None
    local_llm_url: Optional[str] = None


class ProviderConnectionTestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider: str = Field(default="local", min_length=1, max_length=60)
    url: str = Field(default="http://127.0.0.1:11434/v1", min_length=5, max_length=500)
    api_key: Optional[str] = None
    model: Optional[str] = None

@router.get("/api/llm-providers/models")
def api_get_llm_provider_models(provider: str = Query("openrouter")):
    p = (provider or "openrouter").lower().strip()
    # 1. Vollständiger OpenRouter-Katalog aus Preiscache oder Live-API
    if p == "openrouter":
        try:
            p_res = get_llm_prices(refresh=0)
            if p_res.get("status") == "ok" and p_res.get("prices"):
                all_models = sorted(list(p_res["prices"].keys()))
                if len(all_models) > 10:
                    return {"status": "ok", "provider": p, "models": all_models}
        except Exception as exc:
            logger.debug(f"Preis-Modelliste fuer Provider {p} konnte nicht geladen werden: {exc}")
    # 2. Dynamische Modelle aus api_provider
    try:
        import api_provider
        dyn_models = api_provider.list_provider_models(p)
        if dyn_models and len(dyn_models) > 0:
            provenance = api_provider.model_list_provenance(dyn_models)
            if provenance.get("source") == "static_fallback":
                # D06/MED (A7): die harte OmniRoute-Fallbackliste darf nicht
                # als "ok" beim Client ankommen. Kennzeichnung durchreichen.
                return JSONResponse(status_code=502, content={
                    "status": "degraded",
                    "provider": p,
                    "models": dyn_models,
                    "provenance": provenance,
                    "message": "Modellliste nicht live verifiziert (static_fallback).",
                })
            return {
                "status": "ok",
                "provider": p,
                "models": dyn_models,
                "provenance": provenance,
            }
    except Exception as exc:
        logger.debug(f"Dynamische Modelliste fuer Provider {p} konnte nicht abgerufen werden: {exc}")
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
    price_cache = get_price_cache()
    if p == "openrouter" and price_cache:
        for mid in price_cache.keys():
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
        # Echter HTTP-Fehlerstatus, alter Body-Shape bleibt kompatibel.
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "providers": []})


# F1a: Cache, Single-Flight-Lock und Preisabfrage liegen jetzt in
# backend/llm_prices.py (SSOT). get_llm_prices / _get_llm_prices_impl werden
# oben aus backend.llm_prices re-exportiert, damit main.py:1093 und
# archon/routers/chat.py:50 unveraendert bleiben.


@router.get('/api/llm-providers/prices')
def api_get_llm_prices_route(refresh: int = 0):
    """HTTP-Fassade: Fehlerstatus wird zum echten HTTP-Fehler, Body bleibt gleich."""
    result = _get_llm_prices_impl(refresh=refresh)
    if isinstance(result, dict) and result.get("status") == "error":
        return JSONResponse(status_code=502, content=result)
    return result


def _get_llm_provider_models_impl(provider: str = "") -> Dict[str, Any]:
    """Kernlogik der Modelllisten-Abfrage; liefert immer ein Dict."""
    try:
        import api_provider
        pid = (provider or "").strip().lower()
        if not pid:
            return {"status": "ok", "provider": "", "models": []}
            
        models = api_provider.list_provider_models(pid)
        provenance = api_provider.model_list_provenance(models)
        if not models and pid == "omniroute":
            # Harte Liste ohne Live-Beleg: nie als "live"/"ok" kennzeichnen.
            models = ["auto/best-coding", "auto/best-reasoning", "auto/best-vision", "deepseek-ai/DeepSeek-V4-Pro", "qwen/Qwen3.6-27B"]
            provenance = {
                "source": "static_fallback",
                "verified_at": None,
                "status": "degraded",
            }
        return {
            "status": "degraded" if provenance.get("source") == "static_fallback" else "ok",
            "provider": pid,
            "models": models,
            "provenance": provenance,
        }
    except Exception as e:
        return {"status": "error", "provider": provider, "models": [], "message": str(e)}


def get_llm_provider_models(provider: str = "") -> Dict[str, Any]:
    """Interner Helfer: immer ein Dict (kein JSONResponse)."""
    return _get_llm_provider_models_impl(provider=provider)


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
            if not api_provider._validate_base_url(base_url):
                raise ValueError("Ungueltige base_url: nur http(s)-URLs ohne Steuerzeichen/Credentials erlaubt.")
            chosen_model = model or "auto/best-coding"
            res = api_provider.set_provider_model(provider="omniroute", model=chosen_model)
            if not api_provider._set_model_block(chosen_model, "omniroute", base_url):
                raise RuntimeError("Hermes-Model-Block konnte nicht geschrieben werden.")
        else:
            res = api_provider.set_provider_model(provider=pid, model=model)
            # Remove base_url when switching away from omniroute
            if not api_provider._set_model_block(res.get("model") or model or "", pid, None):
                raise RuntimeError("Hermes-Model-Block konnte nicht geschrieben werden.")
            
        return {"status": "ok", "result": res, "active": api_provider.read_active_config()}
    except Exception as e:
        logger.error(f"[llm-providers] select error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/api/llm-providers/save-key")
def save_llm_provider_key(request: Request, req: LLMProviderSaveKeyRequest):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    env_key = req.env_name.strip()
    val = req.key_value.strip()
    # R-15: Validierung AUSSERHALB des try/except — das blanket-except verwandelte
    # das HTTPException(400) sonst in HTTP 200 mit {"status": "error"}.
    if not env_key or not val:
        raise HTTPException(status_code=400, detail="Missing key name or value")
    if not _is_allowed_provider_env_key(env_key):
        raise HTTPException(status_code=400, detail=f"Invalid or disallowed provider env key: {env_key}")
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
            return JSONResponse(status_code=502, content={"status": "error", "message": f"{env_key} hinterlegt, aber Verteilung fehlgeschlagen ({deploy_res.get('status')}).", "deploy": deploy_res})
        return {"status": "ok", "message": f"{env_key} erfolgreich hinterlegt und verteilt", "deploy": deploy_res}
    except Exception as e:
        logger.error(f"[llm-providers] save-key error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/api/provider-keys")
def api_list_provider_keys(request: Request):
    """Maskierte Uebersicht ausgehender Provider-Keys (nie Klartext oder Hashes)."""
    require_admin_or_503(request)  # RBAC: Key-Bestand ist Admin-Wissen
    require_session_actor(request)
    try:
        import api_provider

        keys = api_provider.collect_keys()
        active_cfg = api_provider.read_active_config()
        updated_at = _env_file_updated_at()
        providers: List[Dict[str, Any]] = []
        for pid, display_name in _MANAGED_PROVIDER_KEYS:
            found_name: Optional[str] = None
            found_value = ""
            for env_name in _provider_env_names(pid):
                if keys.get(env_name):
                    found_name = env_name
                    found_value = str(keys[env_name])
                    break
            entry: Dict[str, Any] = {
                "provider": pid,
                "name": display_name,
                "has_key": bool(found_value),
                "key_env": found_name,
                "key_masked": mask_secret(found_value) if found_value else "",
                "source": _key_source(found_name, bool(found_value)),
                "updated_at": updated_at if found_value else None,
                "scopes": [],
                "is_active": (
                    active_cfg.get("provider") == pid
                    or (
                        pid == "omniroute"
                        and "omniroute" in str(active_cfg.get("base_url") or "")
                    )
                ),
            }
            if pid == "omniroute":
                # Nur die URL, niemals der Gateway-Key.
                entry["base_url"] = active_cfg.get("base_url") or _DEFAULT_OMNIROUTE_BASE_URL
                entry["scope"] = _omniroute_scope()
                entry["available_scopes"] = sorted(_OMNIROUTE_SCOPE_MODELS)
                entry["model"] = active_cfg.get("model")
            providers.append(entry)
        return {"status": "success", "provider_keys": providers}
    except Exception:
        logger.error("[provider-keys] Uebersicht fehlgeschlagen", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Provider-Key-Uebersicht nicht verfuegbar."
        )


@router.post("/api/provider-keys/{provider}")
def api_set_provider_key(request: Request, provider: str, req: ProviderKeySetRequest):
    """Setzt oder rotiert einen Provider-Key; die Antwort enthaelt nur eine Maske."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    actor = require_session_actor(request)
    pid = (provider or "").strip().lower()
    if pid not in _FALLBACK_PROVIDER_ENVS:
        raise HTTPException(status_code=400, detail="Unbekannter Provider.")
    env_names = _provider_env_names(pid)
    if not env_names:
        raise HTTPException(status_code=400, detail="Kein erlaubter Env-Name fuer Provider gefunden.")
    env_key = env_names[0]  # Katalog-Reihenfolge ist verbindlich
    val = req.key_value.strip()
    if not val:
        raise HTTPException(status_code=400, detail="Key-Wert darf nicht leer sein.")
    try:
        import api_provider

        previous = os.environ.get(env_key)
        os.environ[env_key] = val
        if not api_provider.set_env_value(api_provider.ENV_PATH, env_key, val):
            # Kein halb gesetzter Zustand zuruecklassen.
            if previous is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = previous
            raise RuntimeError("Env-Datei konnte nicht geschrieben werden.")
        # Sonst liefert collect_keys() bis zu 30 s den alten Wert (TTL-Cache).
        api_provider.invalidate_key_cache()
        try:
            import core_dispatcher

            core_dispatcher.refresh_cached_provider_keys()
        except Exception:
            pass
        deploy_res = api_provider.deploy_keys(dry_run=False)
        if deploy_res.get("status") != "ok":
            raise HTTPException(
                status_code=502, detail="Key hinterlegt, aber Verteilung fehlgeschlagen."
            )
        logger.info("[provider-keys] %s fuer %s durch %s gesetzt", env_key, pid, actor)
        return {
            "status": "success",
            "provider": pid,
            "key_env": env_key,
            "has_key": True,
            "key_masked": mask_secret(val),
            "source": "process_env",
            "updated_at": _env_file_updated_at(),
        }
    except HTTPException:
        raise
    except Exception:
        logger.error("[provider-keys] Setzen fehlgeschlagen", exc_info=True)
        raise HTTPException(status_code=500, detail="Provider-Key konnte nicht gesetzt werden.")


@router.delete("/api/provider-keys/{provider}")
def api_revoke_provider_key(request: Request, provider: str):
    """Entfernt einen Provider-Key aus Prozess-Env und allen Env-Dateien."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    actor = require_session_actor(request)
    pid = (provider or "").strip().lower()
    if pid not in _FALLBACK_PROVIDER_ENVS:
        raise HTTPException(status_code=400, detail="Unbekannter Provider.")
    env_names = _provider_env_names(pid)
    if not env_names:
        raise HTTPException(status_code=400, detail="Kein erlaubter Env-Name fuer Provider gefunden.")
    try:
        import api_provider

        for env_key in env_names:
            os.environ.pop(env_key, None)
            # Ein leerer Wert entfernt die Variable (api_provider.set_env_value).
            for path in _provider_key_targets():
                api_provider.set_env_value(path, env_key, "")
        api_provider.invalidate_key_cache()
        try:
            import core_dispatcher

            core_dispatcher.refresh_cached_provider_keys()
        except Exception:
            pass
        logger.info("[provider-keys] %s durch %s widerrufen", pid, actor)
        return {
            "status": "success",
            "provider": pid,
            "has_key": False,
            "key_masked": "",
            "revoked_envs": env_names,
            "updated_at": _env_file_updated_at(),
        }
    except Exception:
        logger.error("[provider-keys] Widerruf fehlgeschlagen", exc_info=True)
        raise HTTPException(status_code=500, detail="Provider-Key konnte nicht widerrufen werden.")


@router.post("/api/provider-keys/omniroute/scope")
def api_set_omniroute_scope(request: Request, req: OmniRouteScopeRequest):
    """Steuert OmniRoute-Scope, Modell und Base-URL (ohne Key-Material)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    actor = require_session_actor(request)
    scope = (req.scope or "").strip().lower()
    if scope not in _OMNIROUTE_SCOPE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannter OmniRoute-Scope. Erlaubt: {', '.join(sorted(_OMNIROUTE_SCOPE_MODELS))}",
        )
    default_model = _OMNIROUTE_SCOPE_MODELS[scope]
    model = (req.model or default_model).strip()
    if "session-guard" in model:
        model = default_model
    base_url = (req.base_url or _DEFAULT_OMNIROUTE_BASE_URL).strip()
    try:
        import api_provider

        if not api_provider._validate_base_url(base_url):
            raise ValueError(
                "Ungueltige base_url: nur http(s)-URLs ohne Steuerzeichen/Credentials erlaubt."
            )
        if not api_provider.set_env_value(api_provider.ENV_PATH, _OMNIROUTE_SCOPE_ENV, scope):
            raise RuntimeError("OmniRoute-Scope konnte nicht gespeichert werden.")
        os.environ[_OMNIROUTE_SCOPE_ENV] = scope
        result = api_provider.set_provider_model(provider="omniroute", model=model)
        if not api_provider._set_model_block(model, "omniroute", base_url):
            raise RuntimeError("Hermes-Model-Block konnte nicht geschrieben werden.")
        logger.info("[provider-keys] OmniRoute-Scope %s durch %s gesetzt", scope, actor)
        return {
            "status": "success",
            "scope": scope,
            "model": model,
            "base_url": base_url,
            "available_scopes": sorted(_OMNIROUTE_SCOPE_MODELS),
            "result": result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.error("[provider-keys] OmniRoute-Scope fehlgeschlagen", exc_info=True)
        raise HTTPException(
            status_code=500, detail="OmniRoute-Scope konnte nicht gespeichert werden."
        )


@router.get("/api/llm-providers/privacy-status")
def api_get_privacy_status():
    """Gibt den aktuellen Datenschutz- und Verbindungsstatus für Lokal-LLM und DSGVO zurück (t-c4489c)."""
    try:
        from backend.privacy_router import get_overall_privacy_status
        return get_overall_privacy_status()
    except Exception as e:
        logger.error(f"[privacy-status] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/api/llm-providers/privacy-routing")
def api_save_privacy_routing(request: Request, payload: PrivacyRoutingRequest):
    """Aktualisiert die Richtlinien für sensibles On-Premise Routing und EU-Fallback (t-c4489c)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.privacy_router import save_privacy_config
        saved = save_privacy_config(payload.model_dump(exclude_none=True), operator="operator")
        return {"status": "ok", "config": saved}
    except Exception as e:
        logger.error(f"[privacy-routing] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/api/llm-providers/test-connection")
def api_test_provider_connection(request: Request, payload: ProviderConnectionTestRequest):
    """Testet die Live-Verbindung zu einem lokalen LLM oder Mistral AI (t-c4489c)."""
    require_admin_or_503(request)  # D-14: Rollenzaun wie select/save-key/privacy-routing
    if isinstance(payload, dict):
        # Direkte Python-Aufrufer/interne Automaten senden ein Dict; Pydantic
        # v2 validiert es hier nach (kein AttributeError/500 mehr).
        payload = ProviderConnectionTestRequest(**payload)
    try:
        from backend.privacy_router import test_endpoint_sync
        res = test_endpoint_sync(
            provider=payload.provider, url=payload.url,
            api_key=payload.api_key, model=payload.model,
        )
        return {"status": "ok", "result": res}
    except Exception as e:
        logger.error(f"[test-connection] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
