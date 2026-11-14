"""
backend/privacy_router.py
Archon OS 2026 - Zero-Egress Datenschutz-Routing & Lokales LLM HAL (t-c4489c)
Steuert:
1. Zero-Egress-Konfiguration (`zero_egress_strict`, konsolidiert über `privacy_routing.json`,
   `settings.json -> privacy.zero_egress` und `PRIVACY_ZERO_EGRESS`).
2. Sensibles On-Premise Routing (Finanzen, Verträge, CRM, HR, DSGVO) mit **hartem Fail-Closed Block**
   (`hard_block_on_local_offline = True`), sobald das lokale Modell offline ist — kein stiller Cloud-Abfluss!
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

from backend.audit_log import sanitize_llm_endpoint

logger = logging.getLogger("privacy_router")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVACY_CFG_FILE = os.path.join(WORKSPACE_DIR, "data", "privacy_routing.json")
ROOT_SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

DEFAULT_PRIVACY_CONFIG: Dict[str, Any] = {
    "zero_egress_strict": False,
    "sensitive_local_routing": True,
    "hard_block_on_local_offline": True,
    "block_crm_erp_prefetch_on_cloud": True,
    "local_llm_url": "http://127.0.0.1:11434/v1",
    "local_llm_model": "llama3.2",
    "fallback_to_eu": False,
    "mistral_api_key": "",
    "mistral_model": "mistral-large-latest",
    "worker_isolation_network": "archon-worker-zero-egress_net",
    "sensitive_categories": [
        "finance", "finanzen", "receipts", "buchhaltung", "erp", "invoices",
        "contracts", "verträge", "vertraege", "legal",
        "crm", "kunden", "contacts",
        "gdpr", "dsgvo", "personalakte", "hr",
    ],
}

_CANONICAL_SENSITIVE_ALIASES = frozenset({
    "finance", "finanzen", "buchhaltung", "receipt", "receipts", "beleg", "belege",
    "rechnung", "rechnungen", "invoice", "invoices", "erp", "tax", "steuern",
    "contract", "contracts", "vertrag", "verträge", "vertraege", "legal", "nda",
    "crm", "kunde", "kunden", "contact", "contacts", "lead", "leads",
    "gdpr", "dsgvo", "datenschutz", "personalakte", "hr", "personal",
})

_LOCAL_PING_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "available": False,
    "latency_ms": 0,
    "models": [],
    "error": None,
}


def is_sensitive_category(category: str, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Prüft deterministisch, ob eine Kategorie unter sensible Daten (Finanzen, Verträge, CRM, HR, DSGVO) fällt."""
    cat_low = (category or "").strip().lower()
    if not cat_low or cat_low in ("general", "allgemein", "public", "none"):
        return False
    effective_cfg = cfg if isinstance(cfg, dict) else get_privacy_config()
    configured = [str(c).strip().lower() for c in (effective_cfg.get("sensitive_categories") or []) if str(c).strip()]
    if any(sc in cat_low or cat_low in sc for sc in configured):
        return True
    return any(alias == cat_low or alias in cat_low.split("_") for alias in _CANONICAL_SENSITIVE_ALIASES)


def get_privacy_config() -> Dict[str, Any]:
    """
    Lädt und konsolidiert die Zero-Egress- und Datenschutz-Konfiguration aus:
    1. `DEFAULT_PRIVACY_CONFIG`
    2. `settings.json -> privacy.zero_egress`
    3. `data/privacy_routing.json`
    4. Umgebungsvariable `PRIVACY_ZERO_EGRESS`
    """
    merged = dict(DEFAULT_PRIVACY_CONFIG)
    merged["sensitive_categories"] = list(DEFAULT_PRIVACY_CONFIG["sensitive_categories"])

    if os.path.exists(ROOT_SETTINGS_FILE):
        try:
            with open(ROOT_SETTINGS_FILE, "r", encoding="utf-8") as sf:
                sdata = json.load(sf)
            priv_block = sdata.get("privacy") if isinstance(sdata, dict) else None
            if isinstance(priv_block, dict) and "zero_egress" in priv_block:
                merged["zero_egress_strict"] = bool(priv_block.get("zero_egress"))
        except Exception:
            pass

    if os.path.exists(PRIVACY_CFG_FILE):
        try:
            with open(PRIVACY_CFG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    merged.update(data)
        except Exception as e:
            logger.warning(f"Konnte privacy_routing.json nicht lesen: {e}")

    env_ze = (os.environ.get("PRIVACY_ZERO_EGRESS") or "").strip().lower()
    if env_ze in ("1", "true", "yes", "on"):
        merged["zero_egress_strict"] = True

    # Invariante: Im strikten Zero-Egress-Modus darf kein einziger Call das Haus verlassen
    if bool(merged.get("zero_egress_strict")):
        merged["sensitive_local_routing"] = True
        merged["hard_block_on_local_offline"] = True
        merged["fallback_to_eu"] = False

    return merged


def verify_zero_egress_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Überprüft die Zero-Egress-Konfiguration auf Datenabfluss-Risiken (insb. Cloud-Modelle,
    extern fehlkonfigurierte Lokal-URLs oder EU-Cloud-Fallbacks).
    """
    c = cfg if isinstance(cfg, dict) else get_privacy_config()
    issues: List[str] = []

    local_url = str(c.get("local_llm_url") or "http://127.0.0.1:11434/v1")
    clean_ep, target_host, egress_zone = sanitize_llm_endpoint(local_url)
    if egress_zone != "LOCAL_ON_PREM":
        issues.append(
            f"Kritisch: local_llm_url ('{clean_ep}') zeigt auf '{egress_zone}' statt 'LOCAL_ON_PREM' — Daten würden das Haus verlassen."
        )

    if not bool(c.get("hard_block_on_local_offline", True)):
        issues.append(
            "hard_block_on_local_offline ist deaktiviert — bei Ausfall des lokalen Modells droht Cloud-Fallback."
        )

    if bool(c.get("fallback_to_eu", False)) and not bool(c.get("hard_block_on_local_offline", True)):
        issues.append(
            "fallback_to_eu ist aktiv ohne Hard-Block — Daten würden bei Offline-Lokalmodell an externe Cloud (Mistral) abfließen."
        )

    for required_cat in ("finance", "contracts", "crm"):
        if not is_sensitive_category(required_cat, c):
            issues.append(f"Pflichtkategorie '{required_cat}' fehlt in sensitive_categories.")

    return {
        "zero_egress_verified": len(issues) == 0,
        "zero_egress_strict": bool(c.get("zero_egress_strict", False)),
        "sensitive_local_routing": bool(c.get("sensitive_local_routing", True)),
        "hard_block_on_local_offline": bool(c.get("hard_block_on_local_offline", True)),
        "fallback_to_eu": bool(c.get("fallback_to_eu", False)),
        "local_endpoint_sanitized": clean_ep,
        "local_target_host": target_host,
        "local_egress_zone": egress_zone,
        "issues": issues,
    }


def save_privacy_config(cfg: Dict[str, Any], operator: str = "operator") -> Dict[str, Any]:
    """Speichert die Datenschutz-Konfiguration und protokolliert die Änderung im GoBD SHA-256 Audit-Log."""
    current = get_privacy_config()
    current.update(cfg)

    # Zero-Egress-Invariante beim Speichern durchsetzen
    if bool(current.get("zero_egress_strict")):
        current["sensitive_local_routing"] = True
        current["hard_block_on_local_offline"] = True
        current["fallback_to_eu"] = False

    os.makedirs(os.path.dirname(PRIVACY_CFG_FILE), exist_ok=True)
    with open(PRIVACY_CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)

    # Synchronisiere settings.json -> privacy.zero_egress, falls Datei existiert
    if "zero_egress_strict" in cfg and os.path.exists(ROOT_SETTINGS_FILE):
        try:
            with open(ROOT_SETTINGS_FILE, "r", encoding="utf-8") as sf:
                sdata = json.load(sf)
            if isinstance(sdata, dict):
                priv = sdata.get("privacy") if isinstance(sdata.get("privacy"), dict) else {}
                priv["zero_egress"] = bool(current["zero_egress_strict"])
                sdata["privacy"] = priv
                with open(ROOT_SETTINGS_FILE, "w", encoding="utf-8") as sf:
                    json.dump(sdata, sf, indent=2, ensure_ascii=False)
        except Exception as sync_err:
            logger.warning(f"settings.json privacy sync warning: {sync_err}")

    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="config",
            action="privacy_routing_updated",
            agent_id=operator,
            payload={
                "zero_egress_strict": bool(current.get("zero_egress_strict", False)),
                "sensitive_local_routing": bool(current.get("sensitive_local_routing", True)),
                "hard_block_on_local_offline": bool(current.get("hard_block_on_local_offline", True)),
                "local_llm_url": current.get("local_llm_url"),
                "local_llm_model": current.get("local_llm_model"),
                "fallback_to_eu": bool(current.get("fallback_to_eu", False)),
                "mistral_configured": bool(current.get("mistral_api_key")),
            },
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
            "error": None,
        })
    except Exception as e:
        _LOCAL_PING_CACHE.update({
            "ts": now,
            "available": False,
            "latency_ms": 0,
            "models": [],
            "error": str(e),
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
                headers={"Authorization": f"Bearer {key}", "User-Agent": "Archon-OS/2026"},
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
    Ermittelt den Gesamtstatus für die beiden Footer-Statusleuchten sowie Zero-Egress-Audit.
    """
    cfg = get_privacy_config()
    local_stat = check_local_llm_status()
    ze_check = verify_zero_egress_config(cfg)
    is_local_online = bool(local_stat.get("available"))
    is_routing_enabled = bool(cfg.get("sensitive_local_routing"))
    zero_strict = bool(cfg.get("zero_egress_strict", False))
    hard_block = bool(cfg.get("hard_block_on_local_offline", True))

    # 1. Lokal-LLM Indikator
    if is_local_online and is_routing_enabled:
        local_indicator = "green"
        local_tooltip = f"Lokal-LLM aktiv & gebunden ({local_stat.get('latency_ms', 0)}ms, Zero-Egress Hard-Block: {'EIN' if hard_block else 'AUS'})"
    elif is_local_online and not is_routing_enabled:
        local_indicator = "amber"
        local_tooltip = f"Lokal-LLM bereit ({local_stat.get('latency_ms', 0)}ms), aber sensibles Routing ist inaktiv"
    else:
        local_indicator = "gray"
        if is_routing_enabled and hard_block:
            local_tooltip = "Lokal-LLM offline — Harter Fail-Closed Block aktiv für Finanzen, Verträge & CRM (Zero Egress)"
        else:
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

    if zero_strict or active_provider in ("local", "ollama", "lmstudio") or (is_local_online and is_routing_enabled):
        dsgvo_indicator = "green"
        dsgvo_label = "DSGVO (100% Zero-Egress)" if zero_strict else "DSGVO (100% On-Premise)"
        dsgvo_tooltip = "Zero-Egress erzwungen: Keine Daten verlassen das lokale Hausnetz."
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
            dsgvo_label = "DSGVO (PII-Scrubber + Hard-Block)" if (is_routing_enabled and hard_block) else "DSGVO (PII-Scrubber)"
            dsgvo_tooltip = (
                f"Cloud ({active_provider.upper()}) für Allgemein-Tasks; Finanzen/Verträge/CRM durch Hard-Block vor Egress geschützt."
                if (is_routing_enabled and hard_block)
                else f"US-Cloud ({active_provider.upper()}) aktiv, aber personenbezogene Daten werden vor Egress anonymisiert."
            )
        else:
            dsgvo_indicator = "gray"
            dsgvo_label = "Standard-Cloud"
            dsgvo_tooltip = f"US-Cloud ({active_provider.upper()}) ohne aktiven PII-Filter."

    return {
        "status": "ok",
        "config": cfg,
        "zero_egress_verification": ze_check,
        "local_llm": {
            "indicator": local_indicator,
            "available": is_local_online,
            "latency_ms": local_stat.get("latency_ms", 0),
            "routing_enabled": is_routing_enabled,
            "hard_block_on_local_offline": hard_block,
            "zero_egress_strict": zero_strict,
            "url": cfg.get("local_llm_url"),
            "model": cfg.get("local_llm_model"),
            "tooltip": local_tooltip,
        },
        "dsgvo": {
            "indicator": dsgvo_indicator,
            "label": dsgvo_label,
            "active_provider": active_provider,
            "mistral_configured": mistral_configured,
            "tooltip": dsgvo_tooltip,
        },
    }


def route_sensitive_payload(
    category: str,
    messages: List[Dict],
    default_provider: str,
    default_model: str,
) -> Dict[str, Any]:
    """
    Privacy-Router & Zero-Egress Policy:
    1. Im Modus `zero_egress_strict=True` gilt Zero-Egress für **alle** Kategorien (auch Cloud-Modelle werden lokal umgeleitet bzw. hart geblockt).
    2. Für sensible Kategorien (Finanzen, Verträge, CRM, HR, DSGVO) gilt:
       - Ist das lokale On-Premise-Modell erreichbar -> zwingendes Routing auf `local` (`LOCAL_ON_PREM`).
       - Ist das lokale Modell offline -> **harter Fail-Closed Block (`blocked: True`, `LOCAL_LLM_OFFLINE_HARD_BLOCK`)**!
         (Kein Ausweichen auf US-Cloud, OmniRoute-Cloud oder EU-Cloud, solange `hard_block_on_local_offline=True` aktiv ist.)
    """
    cfg = get_privacy_config()
    zero_strict = bool(cfg.get("zero_egress_strict", False))
    is_routing_enabled = bool(cfg.get("sensitive_local_routing", False)) or zero_strict
    hard_block_offline = bool(cfg.get("hard_block_on_local_offline", True)) or zero_strict
    is_sensitive = is_sensitive_category(category, cfg)

    if not zero_strict and not (is_routing_enabled and is_sensitive):
        return {
            "routed": False,
            "blocked": False,
            "provider": default_provider,
            "model": default_model,
            "reason": "Standard-Routing (Nicht sensibel oder sensibles Routing deaktiviert)",
        }

    local_url = str(cfg.get("local_llm_url", "http://127.0.0.1:11434/v1")).strip()
    clean_ep, _, egress_zone = sanitize_llm_endpoint(local_url)
    if egress_zone != "LOCAL_ON_PREM":
        logger.error(
            f"[PrivacyRouter] HARD-BLOCK: Konfigurierte local_llm_url ('{clean_ep}') liegt in Zone '{egress_zone}' statt LOCAL_ON_PREM!"
        )
        return {
            "routed": False,
            "blocked": True,
            "error_code": "LOCAL_LLM_URL_NOT_ON_PREM",
            "provider": None,
            "model": None,
            "reason": f"Zero-Egress Hard-Block: Konfigurierter Lokal-Endpunkt '{clean_ep}' ist kein lokaler On-Premise-Host ({egress_zone}).",
        }

    local_stat = check_local_llm_status()
    if local_stat.get("available"):
        logger.info(
            f"[PrivacyRouter] Task ({category}) On-Premise delegiert an Lokales LLM ({cfg.get('local_llm_model')})."
        )
        return {
            "routed": True,
            "blocked": False,
            "provider": "local",
            "model": cfg.get("local_llm_model", "llama3.2"),
            "base_url": local_url,
            "privacy_tier": "LOCAL_ZERO_EGRESS",
            "reason": f"Daten ({category}) On-Premise auf lokalem Modell verarbeitet (Zero Egress).",
        }

    # Harter Block bei sensiblen Kategorien (Finanzen, Verträge, CRM) oder striktem Zero-Egress,
    # sobald das lokale Modell offline ist!
    if hard_block_offline:
        logger.error(
            f"[PrivacyRouter] HARD-BLOCK (LOCAL_LLM_OFFLINE): Lokales Modell offline — Kategorie '{category}' hart blockiert!"
        )
        return {
            "routed": False,
            "blocked": True,
            "error_code": "LOCAL_LLM_OFFLINE_HARD_BLOCK",
            "provider": None,
            "model": None,
            "reason": (
                f"Privacy-Router Hard-Block: Lokales On-Premise-Modell ({local_url}) ist offline. "
                f"Anfrage der Kategorie '{category}' wurde hart blockiert — keine Daten verlassen das Haus."
            ),
        }

    # Optionaler EU-Fallback NUR falls Operator hard_block_on_local_offline explizit abgeschaltet hat
    if not zero_strict and cfg.get("fallback_to_eu") and (cfg.get("mistral_api_key") or os.environ.get("MISTRAL_API_KEY")):
        logger.warning(
            f"[PrivacyRouter] Lokales LLM offline! Explizit freigegebener Fallback für ({category}) auf Mistral AI (EU-DSGVO)."
        )
        return {
            "routed": True,
            "blocked": False,
            "provider": "mistral",
            "model": cfg.get("mistral_model", "mistral-large-latest"),
            "base_url": "https://api.mistral.ai/v1",
            "privacy_tier": "EU_DSGVO_FALLBACK",
            "reason": "Lokales LLM offline: Ausweichen auf EU-DSGVO-Provider Mistral AI.",
        }

    logger.error(
        f"[PrivacyRouter] BLOCKIERT: Lokales LLM offline und kein zulässiger Fallback für '{category}'!"
    )
    return {
        "routed": False,
        "blocked": True,
        "error_code": "LOCAL_LLM_OFFLINE_HARD_BLOCK",
        "provider": None,
        "model": None,
        "reason": "Sensibles Routing aktiv, aber lokales LLM offline und kein EU-Fallback hinterlegt — Anfrage blockiert (DSGVO-Fail-Closed).",
    }
