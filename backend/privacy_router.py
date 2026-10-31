"""
backend/privacy_router.py
Archon OS 2026 - Datenschutz-Routing & Lokales LLM HAL (t-c4489c)
Steuert das sensible Routing (Finanzen, Verträge, CRM) auf lokale On-Premise LLMs (Ollama / LM Studio)
sowie die EU-DSGVO-Konformitätsprüfung (Mistral AI) mit Live-Statusindikatoren.
"""

import os
import sys
import json
import time
import socket
import urllib.request
import urllib.error
from urllib.parse import urlparse
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("privacy_router")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVACY_CFG_FILE = os.path.join(WORKSPACE_DIR, "data", "privacy_routing.json")

DEFAULT_PRIVACY_CONFIG: Dict[str, Any] = {
    "sensitive_local_routing": False,
    "local_llm_url": "http://127.0.0.1:11434/v1",
    "local_llm_model": "llama3.2",
    "fallback_to_eu": True,
    "mistral_api_key": "",
    "mistral_model": "mistral-large-latest",
    "sensitive_categories": ["finance", "receipts", "contracts", "crm", "gdpr", "personalakte", "hr"]
}

_LOCAL_PING_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "available": False,
    "latency_ms": 0,
    "models": [],
    "error": None
}

def get_privacy_config() -> Dict[str, Any]:
    """Lädt die Datenschutz- und Routing-Konfiguration."""
    if os.path.exists(PRIVACY_CFG_FILE):
        try:
            with open(PRIVACY_CFG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = dict(DEFAULT_PRIVACY_CONFIG)
                merged.update(data)
                return merged
        except Exception as e:
            logger.warning(f"Konnte privacy_routing.json nicht lesen: {e}")
    return dict(DEFAULT_PRIVACY_CONFIG)

def save_privacy_config(cfg: Dict[str, Any], operator: str = "operator") -> Dict[str, Any]:
    """Speichert die Datenschutz-Konfiguration und protokolliert die Änderung im GoBD Audit-Log."""
    current = get_privacy_config()
    current.update(cfg)
    os.makedirs(os.path.dirname(PRIVACY_CFG_FILE), exist_ok=True)
    with open(PRIVACY_CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)

    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="config",
            action="privacy_routing_updated",
            agent_id=operator,
            payload={
                "sensitive_local_routing": current.get("sensitive_local_routing"),
                "local_llm_url": current.get("local_llm_url"),
                "local_llm_model": current.get("local_llm_model"),
                "fallback_to_eu": current.get("fallback_to_eu"),
                "mistral_configured": bool(current.get("mistral_api_key"))
            }
        )
    except Exception as e:
        logger.warning(f"Audit-Log Fehler bei privacy_routing: {e}")

    _LOCAL_PING_CACHE["ts"] = 0.0
    return current

def check_local_llm_status(force: bool = False) -> Dict[str, Any]:
    """
    Prüft die Erreichbarkeit und Latenz des lokalen LLM-Endpunkts (z. B. Ollama / LM Studio).
    Cached das Ergebnis für 10 Sekunden.
    """
    now = time.time()
    if not force and (now - _LOCAL_PING_CACHE.get("ts", 0.0) < 10.0):
        return _LOCAL_PING_CACHE

    cfg = get_privacy_config()
    target_url = cfg.get("local_llm_url", "http://127.0.0.1:11434/v1")
    
    try:
        parsed = urlparse(target_url)
        host = parsed.hostname or "127.0.0.1"
        if host.lower() == "localhost":
            host = "127.0.0.1"
        port = parsed.port or (11434 if "11434" in target_url else (80 if parsed.scheme == "http" else 443))

        start_t = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect((host, port))
        latency = int((time.time() - start_t) * 1000)
        s.close()

        # Versuche Modellliste abzurufen
        models = []
        try:
            raw_url = target_url.replace("localhost", "127.0.0.1").rstrip("/")
            models_url = f"{raw_url}/models" if "/v1" in raw_url else f"{raw_url}/v1/models"
            req = urllib.request.Request(models_url, headers={"User-Agent": "Archon-OS/2026"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    raw_data = resp.read().decode("utf-8", errors="ignore")
                    data = json.loads(raw_data)
                    models = [m.get("id") or m.get("name") for m in data.get("data", [])] if isinstance(data, dict) else []
        except Exception:
            pass

        _LOCAL_PING_CACHE.update({
            "ts": now,
            "available": True,
            "latency_ms": max(1, latency),
            "models": models[:10],
            "error": None
        })
    except Exception as e:
        _LOCAL_PING_CACHE.update({
            "ts": now,
            "available": False,
            "latency_ms": 0,
            "models": [],
            "error": str(e)
        })

    return _LOCAL_PING_CACHE

def test_endpoint_sync(provider: str, url: str, api_key: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """Testet synchron die Verbindung zu einem Provider (Local LLM oder Mistral)."""
    start_t = time.time()
    try:
        if provider == "local":
            parsed = urlparse(url)
            host = parsed.hostname or "127.0.0.1"
            if host.lower() == "localhost":
                host = "127.0.0.1"
            port = parsed.port or (11434 if "11434" in url else (80 if parsed.scheme == "http" else 443))

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((host, port))
            latency = int((time.time() - start_t) * 1000)
            s.close()

            models = []
            try:
                raw_url = url.replace("localhost", "127.0.0.1").rstrip("/")
                models_url = f"{raw_url}/models" if "/v1" in raw_url else f"{raw_url}/v1/models"
                req = urllib.request.Request(models_url, headers={"User-Agent": "Archon-OS/2026"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        raw_data = resp.read().decode("utf-8", errors="ignore")
                        data = json.loads(raw_data)
                        models = [m.get("id") or m.get("name") for m in data.get("data", [])] if isinstance(data, dict) else []
            except Exception:
                pass

            return {"available": True, "latency_ms": max(1, latency), "models": models[:10], "error": None}

        elif provider == "mistral":
            key = api_key or os.environ.get("MISTRAL_API_KEY", "")
            if not key:
                return {"available": False, "latency_ms": 0, "error": "Kein Mistral API-Key angegeben."}
            target_url = f"{url.rstrip('/')}/models" if "/v1" in url else f"{url.rstrip('/')}/v1/models"
            req = urllib.request.Request(
                target_url,
                headers={"Authorization": f"Bearer {key}", "User-Agent": "Archon-OS/2026"}
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                latency = int((time.time() - start_t) * 1000)
                if resp.status == 200:
                    raw_data = resp.read().decode("utf-8", errors="ignore")
                    data = json.loads(raw_data)
                    models = [m.get("id") for m in data.get("data", [])] if isinstance(data, dict) else []
                    return {"available": True, "latency_ms": latency, "models": models[:12], "error": None}
                return {"available": False, "latency_ms": latency, "error": f"HTTP {resp.status}"}
        else:
            return {"available": False, "latency_ms": 0, "error": f"Unbekannter Provider: {provider}"}
    except Exception as e:
        return {"available": False, "latency_ms": 0, "error": str(e)}

def get_overall_privacy_status() -> Dict[str, Any]:
    """
    Ermittelt den Gesamtstatus für die beiden Footer-Statusleuchten:
    1. Lokal-LLM Leuchte:
       - 'green': Lokales LLM vorhanden/erreichbar UND 'sensitive_local_routing' aktiviert! (User Rule: nur grün, wenn beides erfüllt ist)
       - 'amber': Lokales LLM erreichbar, aber sensibles Routing ist deaktiviert.
       - 'gray': Lokales LLM offline oder nicht konfiguriert.
    2. DSGVO Leuchte:
       - 'green': Aktiver Provider ist europäisch (Mistral AI) oder 100% On-Premise / Local.
       - 'yellow': US-Cloud aktiv, aber PII-Scrubber aktiv.
       - 'gray': Standard US-Cloud ohne Scrubber.
    """
    cfg = get_privacy_config()
    local_stat = check_local_llm_status()
    is_local_online = bool(local_stat.get("available"))
    is_routing_enabled = bool(cfg.get("sensitive_local_routing"))

    # 1. Lokal-LLM Indikator
    if is_local_online and is_routing_enabled:
        local_indicator = "green"
        local_tooltip = f"Lokal-LLM aktiv & gebunden ({local_stat.get('latency_ms', 0)}ms, Routing: Sensibel On-Premise)"
    elif is_local_online and not is_routing_enabled:
        local_indicator = "amber"
        local_tooltip = f"Lokal-LLM bereit ({local_stat.get('latency_ms', 0)}ms), aber sensibles Routing ist inaktiv"
    else:
        local_indicator = "gray"
        local_tooltip = "Lokal-LLM offline oder nicht konfiguriert"

    # 2. DSGVO Indikator
    active_provider = "groq"
    try:
        import api_provider
        ac = api_provider.read_active_config()
        active_provider = (ac.get("provider") or "groq").lower().strip()
    except Exception:
        pass

    mistral_configured = bool(cfg.get("mistral_api_key") or os.environ.get("MISTRAL_API_KEY"))

    if active_provider in ("local", "ollama", "lmstudio") or (is_local_online and is_routing_enabled):
        dsgvo_indicator = "green"
        dsgvo_label = "DSGVO (100% On-Premise)"
        dsgvo_tooltip = "EU-DSGVO-konform: Sensible Daten verbleiben vollständig auf der lokalen Hardware (Zero Egress)."
    elif active_provider == "mistral" or (mistral_configured and active_provider.startswith("mistral")):
        dsgvo_indicator = "green"
        dsgvo_label = "DSGVO (Mistral AI - Paris)"
        dsgvo_tooltip = "EU-DSGVO-konform: Verarbeitung auf europäischen Servern (Mistral AI, Frankreich)."
    else:
        pii_active = False
        try:
            from backend.autonomy_settings import get_module_config
            pii_cfg = get_module_config("pii_scrubber")
            pii_active = bool(pii_cfg.get("enabled", True))
        except Exception:
            pii_active = True

        if pii_active:
            dsgvo_indicator = "yellow"
            dsgvo_label = "DSGVO (PII-Scrubber)"
            dsgvo_tooltip = f"US-Cloud ({active_provider.upper()}) aktiv, aber personenbezogene Daten werden vor Egress anonymisiert."
        else:
            dsgvo_indicator = "gray"
            dsgvo_label = "Standard-Cloud"
            dsgvo_tooltip = f"US-Cloud ({active_provider.upper()}) ohne aktiven PII-Filter."

    return {
        "status": "ok",
        "config": cfg,
        "local_llm": {
            "indicator": local_indicator,
            "available": is_local_online,
            "latency_ms": local_stat.get("latency_ms", 0),
            "routing_enabled": is_routing_enabled,
            "url": cfg.get("local_llm_url"),
            "model": cfg.get("local_llm_model"),
            "tooltip": local_tooltip
        },
        "dsgvo": {
            "indicator": dsgvo_indicator,
            "label": dsgvo_label,
            "active_provider": active_provider,
            "mistral_configured": mistral_configured,
            "tooltip": dsgvo_tooltip
        }
    }

def route_sensitive_payload(category: str, messages: List[Dict], default_provider: str, default_model: str) -> Dict[str, Any]:
    """
    OmniRoute Sensitive Data Policy:
    Entscheidet, ob ein Prompt aufgrund sensibler Kategorien (Finanzen, Verträge, CRM)
    an das lokale LLM delegiert werden muss.
    """
    cfg = get_privacy_config()
    is_routing_enabled = bool(cfg.get("sensitive_local_routing"))
    sensitive_cats = [c.lower() for c in cfg.get("sensitive_categories", [])]

    is_sensitive = any(sc in category.lower() for sc in sensitive_cats)

    if not (is_routing_enabled and is_sensitive):
        return {
            "routed": False,
            "provider": default_provider,
            "model": default_model,
            "reason": "Standard-Routing (Nicht sensibel oder sensibles Routing deaktiviert)"
        }

    local_stat = check_local_llm_status()
    if local_stat.get("available"):
        logger.info(f"[PrivacyRouter] Sensibler Task ({category}) delegiert an Lokales LLM ({cfg.get('local_llm_model')}).")
        return {
            "routed": True,
            "provider": "local",
            "model": cfg.get("local_llm_model", "llama3.2"),
            "base_url": cfg.get("local_llm_url", "http://127.0.0.1:11434/v1"),
            "privacy_tier": "LOCAL_ZERO_EGRESS",
            "reason": f"Sensible Daten ({category}) On-Premise auf lokalem Modell verarbeitet."
        }

    if cfg.get("fallback_to_eu") and (cfg.get("mistral_api_key") or os.environ.get("MISTRAL_API_KEY")):
        logger.warning(f"[PrivacyRouter] Lokales LLM offline! Fallback für sensible Daten ({category}) auf Mistral AI (EU-DSGVO).")
        return {
            "routed": True,
            "provider": "mistral",
            "model": cfg.get("mistral_model", "mistral-large-latest"),
            "base_url": "https://api.mistral.ai/v1",
            "privacy_tier": "EU_DSGVO_FALLBACK",
            "reason": f"Lokales LLM offline: Sicheres Ausweichen auf EU-DSGVO-Provider Mistral AI."
        }

    logger.error(f"[PrivacyRouter] ACHTUNG: Lokales LLM offline und kein EU-Fallback hinterlegt für {category}!")
    return {
        "routed": False,
        "provider": default_provider,
        "model": default_model,
        "warning": "Lokal-LLM offline: Sensible Daten fließen über Standard-Cloud!",
        "reason": "Fallback auf Standard-Cloud wegen Nichterreichbarkeit des lokalen Endpunkts."
    }
