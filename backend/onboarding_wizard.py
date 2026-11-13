"""
Milestone 30: Interactive First-Run Web Setup Wizard & Onboarding Backend.

Manages 4-step first-run onboarding state, SSRF-safe AI provider connectivity
probes, hardened .env secret persistence (0600), channel configuration
(IMAP/SMTP, Telegram, Obsidian Vault), and 8-domain / 70-specialist activation.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from archon.core.runtime import APP_ROOT, DATA_DIR, WORKSPACE_DIR, atomic_write_json
from utils.secret_files import write_secret_file

logger = logging.getLogger("archon.onboarding_wizard")

_ONBOARDING_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Configurable Paths (overridable via monkeypatch in unit tests)
# ---------------------------------------------------------------------------
ROOT_SETTINGS_FILE = os.path.join(APP_ROOT, "settings.json")
WORKSPACE_SETTINGS_FILE = (
    os.path.join(WORKSPACE_DIR, "settings.json")
    if os.path.isabs(WORKSPACE_DIR)
    else os.path.join(APP_ROOT, "agent_workspace", "settings.json")
)
_RESOLVED_DATA_DIR = (
    DATA_DIR
    if os.path.basename(os.path.abspath(DATA_DIR)) == "data"
    else os.path.join(APP_ROOT, "data")
)
TENANT_PROFILE_FILE = os.path.join(_RESOLVED_DATA_DIR, "tenants", "primary", "company_profile.json")
ENV_FILE = os.path.join(APP_ROOT, ".env")
PROFILES_FILE = os.path.join(APP_ROOT, "agent_profiles.json")


# ---------------------------------------------------------------------------
# Canonical 8 Specialist Domains (70 Specialists Total)
# ---------------------------------------------------------------------------
SPECIALIST_DOMAINS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "strategy_leadership",
        "index": 1,
        "category_de": "1. Strategie, Führung & Lebensplanung",
        "category_en": "1. Strategy, Leadership & Executive Planning",
        "description_en": "Boardroom synthesis, agile delivery, crisis command, negotiation, red-teaming & research.",
        "description_de": "Boardroom-Synthese, Projektsteuerung, Krisenstab, Verhandlung, Red-Teaming & Primäraufklärung.",
        "default_count": 12,
    },
    {
        "id": "commerce_procurement",
        "index": 2,
        "category_de": "2. Handel, Beschaffung & E-Commerce",
        "category_en": "2. Commerce, Procurement & Supply Chain",
        "description_en": "Sourcing, landed-cost arbitrage, inventory forecasting, 3PL logistics & vendor SLAs.",
        "description_de": "Strategischer Einkauf, Handelsarbitrage, Bestandsprognose, Zoll/Logistik & Lieferantenverträge.",
        "default_count": 7,
    },
    {
        "id": "legal_tax_compliance",
        "index": 3,
        "category_de": "3. Recht, Steuern & Compliance",
        "category_en": "3. Legal, Tax, Finance & Compliance",
        "description_en": "Contract redlining, corporate & holding tax, liquidity controlling, GDPR/AI-Act & IP protection.",
        "description_de": "Vertragsprüfung, Konzern-/Immobiliensteuerrecht, Liquiditätssteuerung, DSGVO/AI-Act & Markenrecht.",
        "default_count": 11,
    },
    {
        "id": "real_estate_construction",
        "index": 4,
        "category_de": "4. Immobilien & Objektentwicklung",
        "category_en": "4. Real Estate, Architecture & Construction",
        "description_en": "Property development, zoning/permits, construction controlling, ESG subsidies & facility ops.",
        "description_de": "Projektentwicklung, Baurecht/Genehmigungen, Bauleitung, ESG-/Fördermittel & Facility Management.",
        "default_count": 7,
    },
    {
        "id": "creative_media_content",
        "index": 5,
        "category_de": "5. Kreation, Medien & Content",
        "category_en": "5. Brand, Creative, Media & Content",
        "description_en": "Brand architecture, UI/UX direction, direct-response copy, PR communications & multi-channel media.",
        "description_de": "Markenarchitektur, UI/UX-Design, Conversion-Copywriting, PR-Kommunikation & Content-Produktion.",
        "default_count": 8,
    },
    {
        "id": "sales_crm_growth",
        "index": 6,
        "category_de": "6. Vertrieb, CRM & Growth",
        "category_en": "6. Sales, CRM, Marketing & Growth",
        "description_en": "B2B outreach, GTM launches, performance marketing, SEO intelligence, retention & partner channels.",
        "description_de": "B2B-Akquise, Go-to-Market, Performance-Marketing, SEO-Analyse, Kundenbindung & Partner-Vertrieb.",
        "default_count": 11,
    },
    {
        "id": "tech_software_data",
        "index": 7,
        "category_de": "7. Tech, Software & Data",
        "category_en": "7. Engineering, Cloud, Security & Data",
        "description_en": "Enterprise architecture, full-stack engineering, DevOps/SecOps, database tuning & BI analytics.",
        "description_de": "Systemarchitektur, Softwareentwicklung, Cloud/DevSecOps, Datenbank-Tuning & BI-Controlling.",
        "default_count": 8,
    },
    {
        "id": "science_medtech_engineering",
        "index": 8,
        "category_de": "8. Medizin, Chemie, Wissenschaft & Ingenieurwesen",
        "category_en": "8. Medicine, Biotech, Science & R&D",
        "description_en": "Clinical & medtech regulatory affairs, pharma/biotech R&D, materials chemistry & industrial engineering.",
        "description_de": "Medizintechnik-Regulatorik, Pharma/Biotech-Forschung, Materialchemie & Ingenieurwesen.",
        "default_count": 6,
    },
]

# ---------------------------------------------------------------------------
# Canonical 8 Supported AI Providers
# ---------------------------------------------------------------------------
SUPPORTED_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "url_env_key": None,
        "default_base_url": "https://openrouter.ai/api/v1",
        "probe_path": "/models",
        "allowed_hosts": {"openrouter.ai"},
        "is_local": False,
        "requires_key": True,
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "url_env_key": None,
        "default_base_url": "https://api.openai.com/v1",
        "probe_path": "/models",
        "allowed_hosts": {"api.openai.com"},
        "is_local": False,
        "requires_key": True,
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "url_env_key": None,
        "default_base_url": "https://api.anthropic.com/v1",
        "probe_path": "/models",
        "allowed_hosts": {"api.anthropic.com"},
        "is_local": False,
        "requires_key": True,
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "url_env_key": None,
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "probe_path": "/models",
        "allowed_hosts": {"generativelanguage.googleapis.com"},
        "is_local": False,
        "requires_key": True,
    },
    "groq": {
        "id": "groq",
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "url_env_key": None,
        "default_base_url": "https://api.groq.com/openai/v1",
        "probe_path": "/models",
        "allowed_hosts": {"api.groq.com"},
        "is_local": False,
        "requires_key": True,
    },
    "ollama": {
        "id": "ollama",
        "name": "Ollama (Local)",
        "env_key": None,
        "url_env_key": "OLLAMA_BASE_URL",
        "default_base_url": "http://localhost:11434",
        "probe_path": "/api/tags",
        "allowed_hosts": {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"},
        "is_local": True,
        "requires_key": False,
    },
    "lm_studio": {
        "id": "lm_studio",
        "name": "LM Studio (Local)",
        "env_key": None,
        "url_env_key": "LM_STUDIO_URL",
        "default_base_url": "http://localhost:1234/v1",
        "probe_path": "/models",
        "allowed_hosts": {"localhost", "127.0.0.1", "::1", "host.docker.internal"},
        "is_local": True,
        "requires_key": False,
    },
    "omniroute": {
        "id": "omniroute",
        "name": "OmniRoute Hub",
        "env_key": "OMNIROUTE_API_KEY",
        "url_env_key": "OMNIROUTE_URL",
        "default_base_url": "http://localhost:20128/v1",
        "probe_path": "/models",
        "allowed_hosts": {"localhost", "127.0.0.1", "::1", "host.docker.internal", "omniroute"},
        "is_local": True,
        "requires_key": False,
    },
}

_BLOCKED_PORTS = {22, 25, 2375, 2376, 3306, 5432, 6379}
_NEVER_ALLOWED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd00::/8"),
    ipaddress.ip_network("fe80::/10"),
)

_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{12,32}$")
_BIC_RE = re.compile(r"^[A-Z0-9]{8}([A-Z0-9]{3})?$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_TELEGRAM_TOKEN_RE = re.compile(r"^\d{5,20}:[A-Za-z0-9_-]{20,}$")


# ---------------------------------------------------------------------------
# Helpers: Demo Mode, Secret Parsing & Mask Detection
# ---------------------------------------------------------------------------
def is_demo_mode() -> bool:
    """Returns True when ARCHON_DEMO_MODE is active ('1', 'true', 'yes')."""
    return os.environ.get("ARCHON_DEMO_MODE", "").strip().lower() in ("1", "true", "yes")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_masked_secret(value: Optional[str]) -> bool:
    """Detects placeholder/masked values returned by UI forms so existing secrets are preserved."""
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return False
    if "\u2022" in v or "•" in v:
        return True
    if v in ("***", "********", "<redacted>", "<unchanged>", "UNCHANGED"):
        return True
    if set(v) == {"*"} and len(v) >= 4:
        return True
    return False


def parse_env_file(env_path: Optional[str] = None) -> Dict[str, str]:
    """Parses key=value pairs from .env without mutating os.environ."""
    target = env_path or ENV_FILE
    out: Dict[str, str] = {}
    if not target or not os.path.exists(target):
        return out
    try:
        with open(target, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                k, val = line.split("=", 1)
                key = k.strip()
                v = val.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                if key:
                    out[key] = v
    except Exception as exc:
        logger.warning("[Onboarding] Could not read .env at %s: %s", target, exc)
    return out


def _sanitize_env_value(val: str) -> str:
    """Prevents newline injection into .env files."""
    clean = str(val).replace("\r", "").replace("\n", "").strip()
    if any(ch in clean for ch in (" ", "#", '"', "'")) and not (clean.startswith('"') and clean.endswith('"')):
        escaped = clean.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return clean


def upsert_env_secrets(
    updates: Dict[str, Optional[str]],
    *,
    env_path: Optional[str] = None,
    secret_keys: Optional[Iterable[str]] = None,
) -> List[str]:
    """Atomically updates .env with 0600 permissions, preserving existing secrets if masked or empty."""
    target = env_path or ENV_FILE
    protected = set(secret_keys or ())

    with _ONBOARDING_LOCK:
        existing_lines: List[str] = []
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    existing_lines = f.read().splitlines()
            except Exception as exc:
                logger.warning("[Onboarding] Failed reading existing .env (%s): %s", target, exc)
                existing_lines = []

        existing_map = parse_env_file(target)
        effective_updates: Dict[str, str] = {}

        for key, raw_val in updates.items():
            if not key or raw_val is None:
                continue
            val_str = str(raw_val).strip()
            if is_masked_secret(val_str):
                continue
            if key in protected and val_str == "" and existing_map.get(key, ""):
                # Preserve previously saved secret when form field was left blank
                continue
            effective_updates[key] = _sanitize_env_value(val_str)

        if not effective_updates and os.path.exists(target):
            os.chmod(target, 0o600)
            return []

        written_keys: List[str] = []
        seen_in_file: set[str] = set()
        new_lines: List[str] = []

        for line in existing_lines:
            stripped = line.strip()
            matched_key = None
            if stripped and not stripped.startswith("#") and "=" in stripped:
                candidate = stripped[7:].strip() if stripped.startswith("export ") else stripped
                k_part = candidate.split("=", 1)[0].strip()
                if k_part in effective_updates:
                    matched_key = k_part

            if matched_key and matched_key not in seen_in_file:
                new_lines.append(f"{matched_key}={effective_updates[matched_key]}")
                seen_in_file.add(matched_key)
                written_keys.append(matched_key)
            else:
                new_lines.append(line)

        for key, safe_val in effective_updates.items():
            if key not in seen_in_file:
                new_lines.append(f"{key}={safe_val}")
                seen_in_file.add(key)
                written_keys.append(key)

        content = "\n".join(new_lines)
        if not content.endswith("\n"):
            content += "\n"

        if not write_secret_file(target, content):
            raise RuntimeError(f"Failed writing secret configuration to {target}")
        os.chmod(target, 0o600)
        return written_keys


# ---------------------------------------------------------------------------
# Settings Persistence Helpers (settings.json + agent_workspace/settings.json)
# ---------------------------------------------------------------------------
def _load_json_dict(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning("[Onboarding] Could not parse JSON %s: %s", path, exc)
    return {}


def _settings_targets() -> List[str]:
    targets: List[str] = []
    for p in (ROOT_SETTINGS_FILE, WORKSPACE_SETTINGS_FILE):
        if p:
            abs_p = os.path.abspath(p)
            if abs_p not in [os.path.abspath(x) for x in targets]:
                targets.append(p)
    return targets


def _load_merged_settings() -> Dict[str, Any]:
    """Loads settings giving precedence to workspace settings over root settings."""
    merged: Dict[str, Any] = {}
    if ROOT_SETTINGS_FILE:
        merged.update(_load_json_dict(ROOT_SETTINGS_FILE))
    if WORKSPACE_SETTINGS_FILE and os.path.abspath(WORKSPACE_SETTINGS_FILE) != os.path.abspath(ROOT_SETTINGS_FILE):
        ws = _load_json_dict(WORKSPACE_SETTINGS_FILE)
        for k, v in ws.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                sub = dict(merged[k])
                sub.update(v)
                merged[k] = sub
            else:
                merged[k] = v
    return merged


def _update_both_settings(mutator) -> Dict[str, Any]:
    """Atomically applies mutator(dict) to both settings.json and agent_workspace/settings.json."""
    with _ONBOARDING_LOCK:
        result_snapshot: Dict[str, Any] = {}
        for target in _settings_targets():
            current = _load_json_dict(target)
            mutator(current)
            atomic_write_json(target, current)
            result_snapshot = current
        return result_snapshot


# ---------------------------------------------------------------------------
# Step 1: Company & Tenant Profile Validation & Persistence
# ---------------------------------------------------------------------------
def validate_company_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and normalizes Step 1 Company & Tenant profile fields."""
    if not isinstance(raw, dict):
        raise ValueError("company_profile must be an object.")

    company_name = str(raw.get("company_name") or raw.get("name") or "").strip()
    if not company_name:
        raise ValueError("company_name is required.")
    if len(company_name) > 200:
        raise ValueError("company_name must not exceed 200 characters.")

    legal_form = str(raw.get("legal_form") or "").strip()[:80]

    raw_addr = raw.get("address", "")
    if isinstance(raw_addr, dict):
        address: Any = {
            "street": str(raw_addr.get("street") or "").strip()[:160],
            "postal_code": str(raw_addr.get("postal_code") or "").strip()[:32],
            "city": str(raw_addr.get("city") or "").strip()[:100],
            "country": str(raw_addr.get("country") or "").strip()[:100],
        }
    else:
        address = str(raw_addr or "").strip()[:400]

    tax_id = str(raw.get("tax_id") or "").strip()[:64]
    vat_id = str(raw.get("vat_id") or "").strip().upper().replace(" ", "")[:64]

    iban_raw = str(raw.get("iban") or "").strip().upper()
    iban_compact = iban_raw.replace(" ", "")
    if iban_compact and not _IBAN_RE.match(iban_compact):
        raise ValueError("Invalid IBAN format (expected 2-letter country code followed by 12-32 alphanumeric chars).")

    bic_clean = str(raw.get("bic") or "").strip().upper().replace(" ", "")
    if bic_clean and not _BIC_RE.match(bic_clean):
        raise ValueError("Invalid BIC/SWIFT format (expected 8 or 11 alphanumeric characters).")

    currency = str(raw.get("currency") or "EUR").strip().upper() or "EUR"
    if not _CURRENCY_RE.match(currency):
        raise ValueError("Invalid currency code (expected 3-letter ISO code such as EUR, USD, GBP, CHF).")

    language = str(raw.get("language") or "en").strip().lower()
    if language not in ("en", "de"):
        raise ValueError("Invalid language (must be 'en' or 'de').")

    return {
        "company_name": company_name,
        "legal_form": legal_form,
        "address": address,
        "tax_id": tax_id,
        "vat_id": vat_id,
        "iban": iban_raw,
        "bic": bic_clean,
        "currency": currency,
        "language": language,
    }


def save_company_profile(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and saves tenant profile to data/tenants/primary/company_profile.json and settings."""
    validated = validate_company_profile(profile_data)
    tenant_doc = {
        "tenant_id": "primary",
        **validated,
        "updated_at": _utc_now_iso(),
    }
    with _ONBOARDING_LOCK:
        atomic_write_json(TENANT_PROFILE_FILE, tenant_doc)

        def _mutate(s: Dict[str, Any]) -> None:
            s["company_profile"] = dict(validated)
            s["language"] = validated["language"]

        _update_both_settings(_mutate)
        upsert_env_secrets({"ARCHON_LANGUAGE": validated["language"]})

    return tenant_doc


# ---------------------------------------------------------------------------
# Step 2: SSRF-Safe Provider Validation & Live Connectivity Probe
# ---------------------------------------------------------------------------
def validate_provider_url(provider: str, base_url: Optional[str] = None) -> str:
    """Validates provider base_url against strict SSRF rules.

    - Cloud providers (openrouter, openai, anthropic, gemini, groq) MUST use https
      and match their canonical provider hostname.
    - Local/router providers (ollama, lm_studio, omniroute) may use http or https
      ONLY toward localhost / 127.0.0.1 / ::1 / host.docker.internal (or their
      dedicated compose service name).
    - Private RFC1918 IPs, link-local / cloud metadata IPs (169.254.169.254),
      embedded credentials, and blocked internal ports are strictly rejected.
    """
    prov_id = (provider or "").strip().lower()
    spec = SUPPORTED_PROVIDERS.get(prov_id)
    if not spec:
        raise ValueError(f"Unsupported provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS.keys())}")

    candidate = (base_url or "").strip() or spec["default_base_url"]
    parsed = urlparse(candidate)

    if parsed.username or parsed.password:
        raise ValueError("Credentials in provider URL are forbidden.")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("Provider URL is missing a valid hostname.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid port in URL: {exc}") from exc

    if port is not None and port in _BLOCKED_PORTS:
        raise ValueError(f"Port {port} is blocked by security policy.")

    # Evaluate IP literals explicitly before hostname allowlist checks
    literal_ip: Optional[ipaddress._BaseAddress] = None
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if spec["is_local"]:
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Local provider URL must use http or https scheme.")
        if literal_ip is not None:
            if not literal_ip.is_loopback or any(literal_ip in net for net in _NEVER_ALLOWED_NETWORKS):
                raise ValueError(f"IP literal '{literal_ip}' is not allowed; only loopback (127.0.0.1 / ::1) is permitted.")
        elif host not in spec["allowed_hosts"]:
            raise ValueError(
                f"Host '{host}' is not allowed for {prov_id}. Permitted hosts: {', '.join(sorted(spec['allowed_hosts']))}."
            )
    else:
        if parsed.scheme != "https":
            raise ValueError(f"Cloud provider '{prov_id}' requires https scheme (got '{parsed.scheme or 'none'}').")
        if literal_ip is not None:
            raise ValueError(f"IP literals are forbidden for cloud provider '{prov_id}'.")
        if host not in spec["allowed_hosts"]:
            raise ValueError(
                f"Host '{host}' is not permitted for '{prov_id}' (expected {', '.join(sorted(spec['allowed_hosts']))})."
            )

    return candidate.rstrip("/")


def _resolve_probe_endpoint_and_headers(
    prov_id: str,
    validated_base: str,
    effective_key: str,
) -> Tuple[str, Dict[str, str]]:
    headers: Dict[str, str] = {"Accept": "application/json"}

    if prov_id == "ollama":
        # Support both native Ollama base (http://localhost:11434 -> /api/tags)
        # and OpenAI-compatible path (http://localhost:11434/v1 -> /models)
        if validated_base.endswith("/v1"):
            probe_url = f"{validated_base}/models"
        elif validated_base.endswith("/api/tags"):
            probe_url = validated_base
        else:
            probe_url = f"{validated_base}/api/tags"
        return probe_url, headers

    if prov_id == "lm_studio":
        if validated_base.endswith("/models"):
            probe_url = validated_base
        elif validated_base.endswith("/v1"):
            probe_url = f"{validated_base}/models"
        else:
            probe_url = f"{validated_base}/v1/models"
        return probe_url, headers

    if prov_id == "omniroute":
        if validated_base.endswith("/models"):
            probe_url = validated_base
        elif validated_base.endswith("/v1"):
            probe_url = f"{validated_base}/models"
        else:
            probe_url = f"{validated_base}/v1/models"
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"
        return probe_url, headers

    if prov_id == "anthropic":
        probe_url = validated_base if validated_base.endswith("/models") else f"{validated_base}/models"
        headers["x-api-key"] = effective_key
        headers["anthropic-version"] = "2023-06-01"
        return probe_url, headers

    if prov_id == "gemini":
        probe_url = validated_base if validated_base.endswith("/models") else f"{validated_base}/models"
        headers["x-goog-api-key"] = effective_key
        return probe_url, headers

    # openrouter, openai, groq
    probe_url = validated_base if validated_base.endswith("/models") else f"{validated_base}/models"
    if effective_key:
        headers["Authorization"] = f"Bearer {effective_key}"
    return probe_url, headers


def _extract_models_count(payload: Any) -> int:
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            return len(payload["data"])
        if isinstance(payload.get("models"), list):
            return len(payload["models"])
    elif isinstance(payload, list):
        return len(payload)
    return 0


def _lookup_existing_secret(env_key: Optional[str]) -> str:
    if not env_key:
        return ""
    file_env = parse_env_file()
    if file_env.get(env_key):
        return file_env[env_key]
    return os.environ.get(env_key, "").strip()


def test_provider_connection(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Performs an SSRF-safe, 5s-timeout HTTP models/tags connectivity probe.

    Returns:
        dict with keys: ok, provider, latency_ms, models_detected, detail
    """
    prov_id = (provider or "").strip().lower()
    if prov_id not in SUPPORTED_PROVIDERS:
        return {
            "ok": False,
            "provider": prov_id,
            "latency_ms": 0,
            "models_detected": 0,
            "detail": f"Unsupported provider '{provider}'.",
        }

    spec = SUPPORTED_PROVIDERS[prov_id]

    try:
        validated_base = validate_provider_url(prov_id, base_url)
    except ValueError as exc:
        return {
            "ok": False,
            "provider": prov_id,
            "latency_ms": 0,
            "models_detected": 0,
            "detail": f"URL rejected by SSRF guard: {exc}",
        }

    supplied = (api_key or "").strip()
    if not supplied or is_masked_secret(supplied):
        effective_key = _lookup_existing_secret(spec["env_key"])
    else:
        effective_key = supplied

    if spec["requires_key"] and not effective_key:
        return {
            "ok": False,
            "provider": prov_id,
            "latency_ms": 0,
            "models_detected": 0,
            "detail": f"Missing API key ({spec['env_key']}).",
        }

    probe_url, headers = _resolve_probe_endpoint_and_headers(prov_id, validated_base, effective_key)

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            resp = client.get(probe_url, headers=headers)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    except httpx.TimeoutException:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "ok": False,
            "provider": prov_id,
            "latency_ms": latency_ms,
            "models_detected": 0,
            "detail": "Connection timed out after 5s.",
        }
    except httpx.RequestError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        # Ensure we never leak header values in exception string
        err_name = type(exc).__name__
        return {
            "ok": False,
            "provider": prov_id,
            "latency_ms": latency_ms,
            "models_detected": 0,
            "detail": f"Connection error ({err_name}): endpoint unreachable.",
        }

    if 200 <= resp.status_code < 300:
        try:
            body = resp.json()
        except Exception:
            body = {}
        count = _extract_models_count(body)
        return {
            "ok": True,
            "provider": prov_id,
            "latency_ms": latency_ms,
            "models_detected": count,
            "detail": f"Connected ({count} models detected).",
        }

    if resp.status_code in (401, 403):
        detail = f"Authentication failed (HTTP {resp.status_code}). Check API key."
    else:
        detail = f"Endpoint returned HTTP {resp.status_code}."

    return {
        "ok": False,
        "provider": prov_id,
        "latency_ms": latency_ms,
        "models_detected": 0,
        "detail": detail,
    }


def save_providers_and_privacy(
    providers_cfg: Dict[str, Any],
    *,
    zero_egress: bool = False,
) -> Dict[str, Any]:
    """Persists provider API keys & local URLs to .env (0600) and privacy.zero_egress to settings.json."""
    env_updates: Dict[str, Optional[str]] = {
        "PRIVACY_ZERO_EGRESS": "true" if zero_egress else "false",
    }
    secret_env_names: List[str] = []
    configured_providers: List[str] = []

    raw_keys = providers_cfg.get("api_keys") if isinstance(providers_cfg.get("api_keys"), dict) else providers_cfg
    raw_urls = providers_cfg.get("base_urls") if isinstance(providers_cfg.get("base_urls"), dict) else {}

    for prov_id, spec in SUPPORTED_PROVIDERS.items():
        entry = providers_cfg.get(prov_id) if isinstance(providers_cfg, dict) else None
        key_val: Optional[str] = None
        url_val: Optional[str] = None

        if isinstance(entry, dict):
            key_val = entry.get("api_key")
            url_val = entry.get("base_url")
        elif isinstance(entry, str) and spec["env_key"]:
            key_val = entry

        if key_val is None and isinstance(raw_keys, dict) and spec["env_key"]:
            if prov_id in raw_keys and isinstance(raw_keys[prov_id], str):
                key_val = raw_keys[prov_id]
            elif spec["env_key"] in raw_keys and isinstance(raw_keys[spec["env_key"]], str):
                key_val = raw_keys[spec["env_key"]]

        if url_val is None and isinstance(raw_urls, dict):
            if prov_id in raw_urls and isinstance(raw_urls[prov_id], str):
                url_val = raw_urls[prov_id]

        if spec["env_key"]:
            secret_env_names.append(spec["env_key"])
            if key_val is not None:
                env_updates[spec["env_key"]] = str(key_val)
                if str(key_val).strip() and not is_masked_secret(str(key_val)):
                    configured_providers.append(prov_id)

        if spec["url_env_key"] and url_val:
            validated_url = validate_provider_url(prov_id, str(url_val))
            env_updates[spec["url_env_key"]] = validated_url
            configured_providers.append(prov_id)

    updated_env_keys = upsert_env_secrets(env_updates, secret_keys=secret_env_names)

    def _mutate(s: Dict[str, Any]) -> None:
        priv = s.get("privacy") if isinstance(s.get("privacy"), dict) else {}
        priv = dict(priv)
        priv["zero_egress"] = bool(zero_egress)
        s["privacy"] = priv

    _update_both_settings(_mutate)
    return {
        "zero_egress": bool(zero_egress),
        "updated_env_keys": updated_env_keys,
        "configured_providers": sorted(set(configured_providers)),
    }


# ---------------------------------------------------------------------------
# Step 3: Channels (IMAP/SMTP, Telegram + optional getMe, Obsidian Vault)
# ---------------------------------------------------------------------------
def verify_telegram_bot(bot_token: str) -> Dict[str, Any]:
    """Optional lightweight Telegram Bot getMe connectivity check (5s timeout)."""
    tok = (bot_token or "").strip()
    if not tok or is_masked_secret(tok):
        tok = _lookup_existing_secret("TELEGRAM_BOT_TOKEN")
    if not tok:
        return {"ok": False, "detail": "No Telegram bot token provided."}
    if not _TELEGRAM_TOKEN_RE.match(tok):
        return {"ok": False, "detail": "Invalid Telegram bot token format."}

    url = f"https://api.telegram.org/bot{tok}/getMe"
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            resp = client.get(url)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok") and isinstance(data.get("result"), dict):
                uname = data["result"].get("username", "")
                return {
                    "ok": True,
                    "latency_ms": latency_ms,
                    "bot_username": uname,
                    "detail": f"Verified @{uname}" if uname else "Telegram bot verified.",
                }
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "detail": f"Telegram API returned HTTP {resp.status_code}.",
        }
    except httpx.RequestError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "detail": f"Telegram check failed ({type(exc).__name__}).",
        }


def save_channels_config(channels_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and saves IMAP/SMTP, Telegram, and Obsidian Vault settings safely."""
    if not isinstance(channels_cfg, dict):
        channels_cfg = {}

    imap_host = str(channels_cfg.get("imap_host") or "").strip()[:200]
    smtp_host = str(channels_cfg.get("smtp_host") or "").strip()[:200]
    email_user = str(channels_cfg.get("email_user") or "").strip()[:200]
    email_password = channels_cfg.get("email_password")

    try:
        imap_port = int(channels_cfg.get("imap_port") or 993)
    except (TypeError, ValueError) as exc:
        raise ValueError("imap_port must be a valid integer (1-65535).") from exc
    try:
        smtp_port = int(channels_cfg.get("smtp_port") or 587)
    except (TypeError, ValueError) as exc:
        raise ValueError("smtp_port must be a valid integer (1-65535).") from exc

    if not (1 <= imap_port <= 65535) or not (1 <= smtp_port <= 65535):
        raise ValueError("Email ports must be between 1 and 65535.")

    bot_token = channels_cfg.get("bot_token")
    if bot_token is None:
        bot_token = channels_cfg.get("telegram_bot_token")
    chat_id = str(channels_cfg.get("chat_id") or channels_cfg.get("telegram_chat_id") or "").strip()[:100]
    obsidian_vault_path = str(channels_cfg.get("obsidian_vault_path") or "").strip()[:500]
    if "\x00" in obsidian_vault_path:
        raise ValueError("Invalid null byte in obsidian_vault_path.")

    env_updates: Dict[str, Optional[str]] = {}
    if imap_host:
        env_updates["IMAP_HOST"] = imap_host
        env_updates["IMAP_PORT"] = str(imap_port)
    if smtp_host:
        env_updates["SMTP_HOST"] = smtp_host
        env_updates["SMTP_PORT"] = str(smtp_port)
    if email_user:
        env_updates["SMTP_USER"] = email_user
    if email_password is not None:
        env_updates["SMTP_PASSWORD"] = str(email_password)
    if bot_token is not None:
        env_updates["TELEGRAM_BOT_TOKEN"] = str(bot_token)
    if chat_id:
        env_updates["TELEGRAM_CHAT_ID"] = chat_id
    if obsidian_vault_path:
        env_updates["ARCHON_OBSIDIAN_DIR"] = obsidian_vault_path

    upsert_env_secrets(
        env_updates,
        secret_keys=("SMTP_PASSWORD", "TELEGRAM_BOT_TOKEN"),
    )

    current_env = parse_env_file()
    has_email_pw = bool(current_env.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASSWORD"))
    has_tg_token = bool(current_env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN"))

    telegram_probe: Optional[Dict[str, Any]] = None
    if channels_cfg.get("verify_telegram") and (bot_token or has_tg_token):
        telegram_probe = verify_telegram_bot(str(bot_token or ""))

    sanitized_channels = {
        "email": {
            "enabled": bool(smtp_host or imap_host),
            "imap_host": imap_host,
            "imap_port": imap_port,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "email_user": email_user,
            "password_configured": has_email_pw,
        },
        "telegram": {
            "enabled": bool(has_tg_token and chat_id),
            "chat_id": chat_id,
            "bot_token_configured": has_tg_token,
        },
        "obsidian_vault_path": obsidian_vault_path or "./obsidian_vault",
    }

    def _mutate(s: Dict[str, Any]) -> None:
        s["channels"] = sanitized_channels
        obs = s.get("obsidian") if isinstance(s.get("obsidian"), dict) else {}
        obs = dict(obs)
        obs["vault_path"] = sanitized_channels["obsidian_vault_path"]
        s["obsidian"] = obs

    _update_both_settings(_mutate)
    out: Dict[str, Any] = {"channels": sanitized_channels}
    if telegram_probe is not None:
        out["telegram_verification"] = telegram_probe
    return out


# ---------------------------------------------------------------------------
# Step 4: Specialist Domain Activation (8 Domains / 70 Specialists)
# ---------------------------------------------------------------------------
def _load_category_counts() -> Dict[str, int]:
    """Counts specialists per category from PROFILES_FILE, falling back to canonical 70 distribution."""
    counts: Dict[str, int] = {}
    if PROFILES_FILE and os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            if isinstance(profiles, list):
                for p in profiles:
                    if isinstance(p, dict) and p.get("category"):
                        cat = str(p["category"])
                        counts[cat] = counts.get(cat, 0) + 1
        except Exception as exc:
            logger.warning("[Onboarding] Could not read %s: %s", PROFILES_FILE, exc)
    return counts


def get_specialist_domains_summary(active_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Returns the 8 specialist domains with localized titles, counts (total 70), and active flags."""
    live_counts = _load_category_counts()
    active_set = set(active_ids) if active_ids is not None else {d["id"] for d in SPECIALIST_DOMAINS_CATALOG}
    summary: List[Dict[str, Any]] = []
    for dom in SPECIALIST_DOMAINS_CATALOG:
        cnt = live_counts.get(dom["category_de"], dom["default_count"])
        summary.append(
            {
                "id": dom["id"],
                "index": dom["index"],
                "category_de": dom["category_de"],
                "category_en": dom["category_en"],
                "description_de": dom["description_de"],
                "description_en": dom["description_en"],
                "specialist_count": cnt,
                "enabled": dom["id"] in active_set,
            }
        )
    return summary


def normalize_selected_domains(selected: Optional[Iterable[Any]]) -> List[str]:
    """Maps domain IDs, 1..8 indices, or localized category names to canonical domain IDs."""
    if selected is None:
        return [d["id"] for d in SPECIALIST_DOMAINS_CATALOG]

    lookup: Dict[str, str] = {}
    for d in SPECIALIST_DOMAINS_CATALOG:
        lookup[d["id"].lower()] = d["id"]
        lookup[str(d["index"])] = d["id"]
        lookup[d["category_de"].lower()] = d["id"]
        lookup[d["category_en"].lower()] = d["id"]

    resolved: List[str] = []
    for item in selected:
        key = str(item or "").strip().lower()
        if not key:
            continue
        if key not in lookup:
            raise ValueError(f"Unknown specialist domain '{item}'.")
        cid = lookup[key]
        if cid not in resolved:
            resolved.append(cid)

    if not resolved:
        raise ValueError("At least one specialist domain must be selected.")
    return resolved


def _trigger_soul_mode_sync(language: str = "en", mode: str = "compact") -> Dict[str, Any]:
    """Safely triggers sync_soul_modes.apply_soul_mode(mode='compact', lang=language) without blocking."""
    try:
        from scripts import sync_soul_modes

        # Guard: if PROFILES_FILE was redirected in tests to a path without agent_profiles.json
        # and apply_soul_mode is still the real unmocked function, do not mutate production repo files.
        apply_fn = getattr(sync_soul_modes, "apply_soul_mode", None)
        if apply_fn is None:
            return {"synced": False, "reason": "apply_soul_mode_unavailable"}

        is_real_fn = getattr(apply_fn, "__module__", "") == sync_soul_modes.__name__
        if is_real_fn and (
            not PROFILES_FILE
            or not os.path.exists(PROFILES_FILE)
            or os.path.abspath(PROFILES_FILE) != os.path.abspath(sync_soul_modes.PROFILES_JSON_PATH)
        ):
            return {"synced": False, "reason": "isolated_profiles_path"}

        res = apply_fn(mode=mode, lang=language)
        return {"synced": True, "mode": mode, "language": language, "detail": res}
    except Exception as exc:
        logger.warning("[Onboarding] Optional soul mode sync skipped/failed safely: %s", exc)
        return {"synced": False, "reason": str(exc)}


def activate_specialist_domains(
    selected_domains: Optional[Iterable[Any]],
    *,
    language: str = "en",
    sync_souls: bool = True,
) -> Dict[str, Any]:
    """Updates active specialist domain flags in settings and safely triggers compact SOUL sync."""
    active_ids = normalize_selected_domains(selected_domains)
    domains_summary = get_specialist_domains_summary(active_ids)
    active_specialists = sum(d["specialist_count"] for d in domains_summary if d["enabled"])

    domain_flags = {
        d["id"]: {
            "enabled": d["enabled"],
            "specialist_count": d["specialist_count"],
            "category_en": d["category_en"],
            "category_de": d["category_de"],
        }
        for d in domains_summary
    }

    def _mutate(s: Dict[str, Any]) -> None:
        s["active_domains"] = list(active_ids)
        s["specialist_domains"] = domain_flags

    _update_both_settings(_mutate)

    soul_sync = (
        _trigger_soul_mode_sync(language=language, mode="compact")
        if sync_souls
        else {"synced": False, "reason": "disabled"}
    )

    return {
        "active_domains": active_ids,
        "active_domain_count": len(active_ids),
        "total_domains": len(SPECIALIST_DOMAINS_CATALOG),
        "active_specialists": active_specialists,
        "total_specialists": sum(d["specialist_count"] for d in domains_summary),
        "soul_sync": soul_sync,
    }


# ---------------------------------------------------------------------------
# Status, Complete & Skip Orchestration
# ---------------------------------------------------------------------------
def get_detected_providers_booleans() -> Dict[str, bool]:
    """Returns boolean presence flags for each provider — NEVER exposes secret values."""
    file_env = parse_env_file()
    detected: Dict[str, bool] = {}
    for prov_id, spec in SUPPORTED_PROVIDERS.items():
        env_key = spec["env_key"]
        url_key = spec["url_env_key"]
        if env_key:
            val = (file_env.get(env_key) or os.environ.get(env_key) or "").strip()
            has_key = bool(val)
        else:
            has_key = False

        if url_key:
            uval = (file_env.get(url_key) or os.environ.get(url_key) or "").strip()
            has_url = bool(uval)
        else:
            has_url = False

        detected[prov_id] = bool(has_key or (spec["is_local"] and has_url))
    return detected


def get_onboarding_status() -> Dict[str, Any]:
    """Builds full sanitized onboarding status for GET /api/onboarding/status."""
    settings = _load_merged_settings()
    file_env = parse_env_file()
    demo = is_demo_mode()

    onb = settings.get("onboarding") if isinstance(settings.get("onboarding"), dict) else {}
    completed = bool(onb.get("completed") or settings.get("onboarding_completed"))
    dismissed = bool(onb.get("dismissed"))
    completed_at = onb.get("completed_at") or settings.get("completed_at")
    dismissed_at = onb.get("dismissed_at")

    auto_open = not (demo or completed or dismissed)

    lang = (
        str(settings.get("language") or file_env.get("ARCHON_LANGUAGE") or os.environ.get("ARCHON_LANGUAGE") or "en")
        .strip()
        .lower()
    )
    if lang not in ("en", "de"):
        lang = "en"

    priv = settings.get("privacy") if isinstance(settings.get("privacy"), dict) else {}
    env_ze = (file_env.get("PRIVACY_ZERO_EGRESS") or os.environ.get("PRIVACY_ZERO_EGRESS") or "").strip().lower()
    zero_egress = bool(priv.get("zero_egress")) or env_ze in ("1", "true", "yes")

    tenant_profile = _load_json_dict(TENANT_PROFILE_FILE)
    company_profile = (
        settings.get("company_profile")
        if isinstance(settings.get("company_profile"), dict) and settings.get("company_profile")
        else {k: v for k, v in tenant_profile.items() if k not in ("tenant_id", "updated_at")}
    )

    detected_providers = get_detected_providers_booleans()
    providers_catalog = [
        {
            "id": prov_id,
            "name": spec["name"],
            "env_key": spec["env_key"],
            "url_env_key": spec["url_env_key"],
            "default_base_url": (
                (file_env.get(spec["url_env_key"]) or os.environ.get(spec["url_env_key"]) or spec["default_base_url"])
                if spec["url_env_key"]
                else spec["default_base_url"]
            ),
            "is_local": spec["is_local"],
            "requires_key": spec["requires_key"],
            "configured": detected_providers[prov_id],
        }
        for prov_id, spec in SUPPORTED_PROVIDERS.items()
    ]

    saved_active_domains = settings.get("active_domains") if isinstance(settings.get("active_domains"), list) else None
    domains_summary = get_specialist_domains_summary(saved_active_domains)

    saved_channels = settings.get("channels") if isinstance(settings.get("channels"), dict) else {}
    email_ch = saved_channels.get("email") if isinstance(saved_channels.get("email"), dict) else {}
    tg_ch = saved_channels.get("telegram") if isinstance(saved_channels.get("telegram"), dict) else {}

    has_email_pw = bool(
        email_ch.get("password_configured")
        or file_env.get("SMTP_PASSWORD")
        or os.environ.get("SMTP_PASSWORD")
    )
    has_tg_tok = bool(
        tg_ch.get("bot_token_configured")
        or file_env.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
    )

    sanitized_channels = {
        "imap_host": str(email_ch.get("imap_host") or file_env.get("IMAP_HOST") or ""),
        "imap_port": int(email_ch.get("imap_port") or file_env.get("IMAP_PORT") or 993),
        "smtp_host": str(email_ch.get("smtp_host") or file_env.get("SMTP_HOST") or ""),
        "smtp_port": int(email_ch.get("smtp_port") or file_env.get("SMTP_PORT") or 587),
        "email_user": str(email_ch.get("email_user") or file_env.get("SMTP_USER") or ""),
        "email_password_configured": has_email_pw,
        "telegram_chat_id": str(tg_ch.get("chat_id") or file_env.get("TELEGRAM_CHAT_ID") or ""),
        "telegram_bot_configured": has_tg_tok,
        "obsidian_vault_path": str(
            saved_channels.get("obsidian_vault_path")
            or file_env.get("ARCHON_OBSIDIAN_DIR")
            or "./obsidian_vault"
        ),
    }

    return {
        "status": "ok",
        "auto_open": auto_open,
        "should_show_wizard": auto_open,
        "onboarding_completed": completed,
        "dismissed": dismissed,
        "completed_at": completed_at,
        "dismissed_at": dismissed_at,
        "demo_mode": demo,
        "language": lang,
        "zero_egress": zero_egress,
        "company_profile": company_profile or {},
        "detected_providers": detected_providers,
        "providers_catalog": providers_catalog,
        "channels": sanitized_channels,
        "active_domains": [d["id"] for d in domains_summary if d["enabled"]],
        "specialist_domains": domains_summary,
        "total_domains": len(domains_summary),
        "total_specialists": sum(d["specialist_count"] for d in domains_summary),
    }


def complete_onboarding(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validates all 4 onboarding steps up-front, then persists atomically and marks completed."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid onboarding payload.")

    maybe_company = payload.get("company_profile")
    raw_company: Dict[str, Any] = maybe_company if isinstance(maybe_company, dict) else payload
    maybe_providers = payload.get("providers")
    raw_providers: Dict[str, Any] = maybe_providers if isinstance(maybe_providers, dict) else {}
    maybe_channels = payload.get("channels")
    raw_channels: Dict[str, Any] = maybe_channels if isinstance(maybe_channels, dict) else {}
    selected_domains = payload.get("active_domains")
    sync_souls = bool(payload.get("sync_souls", True))
    zero_egress = bool(
        payload.get("zero_egress")
        if "zero_egress" in payload
        else raw_providers.get("zero_egress", False)
    )

    # Phase 1: Up-front validation across all 4 steps before mutating disk state
    validated_company = validate_company_profile(raw_company)
    maybe_urls = raw_providers.get("base_urls")
    raw_urls: Dict[str, Any] = maybe_urls if isinstance(maybe_urls, dict) else {}
    for prov_id, spec in SUPPORTED_PROVIDERS.items():
        entry = raw_providers.get(prov_id)
        candidate_url = entry.get("base_url") if isinstance(entry, dict) else raw_urls.get(prov_id)
        if spec["url_env_key"] and candidate_url:
            validate_provider_url(prov_id, str(candidate_url))

    try:
        imap_p = int(raw_channels.get("imap_port") or 993)
        smtp_p = int(raw_channels.get("smtp_port") or 587)
    except (TypeError, ValueError) as exc:
        raise ValueError("imap_port and smtp_port must be valid integers (1-65535).") from exc
    if not (1 <= imap_p <= 65535) or not (1 <= smtp_p <= 65535):
        raise ValueError("Email ports must be between 1 and 65535.")
    if "\x00" in str(raw_channels.get("obsidian_vault_path") or ""):
        raise ValueError("Invalid null byte in obsidian_vault_path.")

    normalize_selected_domains(selected_domains)

    # Phase 2: Atomic persistence across tenant profile, .env (0600), and settings files
    with _ONBOARDING_LOCK:
        saved_tenant = save_company_profile(validated_company)
        language = saved_tenant["language"]
        providers_summary = save_providers_and_privacy(raw_providers, zero_egress=zero_egress)
        channels_summary = save_channels_config(raw_channels)
        domains_result = activate_specialist_domains(
            selected_domains,
            language=language,
            sync_souls=sync_souls,
        )

        completed_at = _utc_now_iso()

        def _mark_done(s: Dict[str, Any]) -> None:
            s["onboarding_completed"] = True
            s["completed_at"] = completed_at
            onb = s.get("onboarding") if isinstance(s.get("onboarding"), dict) else {}
            onb = dict(onb)
            onb["completed"] = True
            onb["dismissed"] = False
            onb["completed_at"] = completed_at
            onb["version"] = "m30-v1"
            s["onboarding"] = onb

        _update_both_settings(_mark_done)

    return {
        "status": "ok",
        "onboarding_completed": True,
        "completed_at": completed_at,
        "company_profile": {k: v for k, v in saved_tenant.items() if k not in ("updated_at",)},
        "providers": {
            "zero_egress": providers_summary["zero_egress"],
            "detected_providers": get_detected_providers_booleans(),
        },
        "channels": channels_summary["channels"],
        "telegram_verification": channels_summary.get("telegram_verification"),
        "domains": domains_result,
    }


def skip_onboarding() -> Dict[str, Any]:
    """Marks onboarding.dismissed = True so power users are not nagged on future page loads."""
    dismissed_at = _utc_now_iso()

    def _mark_dismissed(s: Dict[str, Any]) -> None:
        onb = s.get("onboarding") if isinstance(s.get("onboarding"), dict) else {}
        onb = dict(onb)
        onb["dismissed"] = True
        onb["dismissed_at"] = dismissed_at
        s["onboarding"] = onb

    _update_both_settings(_mark_dismissed)
    return {
        "status": "ok",
        "dismissed": True,
        "dismissed_at": dismissed_at,
        "auto_open": False,
    }


__all__ = [
    "SPECIALIST_DOMAINS_CATALOG",
    "SUPPORTED_PROVIDERS",
    "is_demo_mode",
    "is_masked_secret",
    "parse_env_file",
    "upsert_env_secrets",
    "validate_company_profile",
    "save_company_profile",
    "validate_provider_url",
    "test_provider_connection",
    "save_providers_and_privacy",
    "verify_telegram_bot",
    "save_channels_config",
    "get_specialist_domains_summary",
    "normalize_selected_domains",
    "activate_specialist_domains",
    "get_detected_providers_booleans",
    "get_onboarding_status",
    "complete_onboarding",
    "skip_onboarding",
]
