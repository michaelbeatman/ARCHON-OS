"""
backend/llm_egress_guard.py
===========================
Zentrales Zero-Egress-Durchsetzungs-Gate & SHA-256-Dispatch-Auditor für alle LLM-Aufrufe.

Aufgaben:
1. Kategorisiert jeden LLM-Call (Finanzen, Verträge, CRM, HR, DSGVO, Allgemein).
2. Erzwingt vor dem ersten Netzwerk-Byte:
   - `zero_egress_strict`: Kein einziger Call an Cloud-Hosts (`EXTERNAL_CLOUD`) oder Cloud-Modelle über `omniroute`.
   - `sensitive_local_routing`: Sensible Kategorien gehen zwingend an das lokale On-Premise-Modell;
     ist dieses offline, greift sofort der **harte Fail-Closed Block (`ZeroEgressBlockedError`)**!
3. Schreibt für **jeden einzelnen Call** (sowohl durchgeführte Calls als auch geblockte Versuche)
   einen kryptografisch verketteten SHA-256-Block (`category="llm_dispatch"`) mit:
   `provider`, `model`, `target_endpoint`, `target_host`, `egress_zone` und `http_status` in `audit_log.py`.
4. Prüft live die Docker-Worker-Netzwerk-Isolation (`archon-worker-zero-egress_net`, `Internal: true`, keine Internet-Route).
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from backend.audit_log import chained_audit_log, sanitize_llm_endpoint
from backend.privacy_router import (
    check_local_llm_status,
    get_privacy_config,
    is_sensitive_category,
    route_sensitive_payload,
    verify_zero_egress_config,
)

ZERO_EGRESS_WORKER_NET = "archon-worker-zero-egress_net"

# Zuordnung von Spezialisten-IDs und Rollenbezeichnungen zu sensiblen Datenkategorien
_SENSITIVE_AGENT_CATEGORY_MAP = {
    "finance": (
        "finance", "finanzen", "buchhaltung", "accounting", "bi_controller",
        "tax_holding_advisor", "dunning", "mahnwesen", "receipt", "beleg",
        "realestate_dcf_calculator", "pricing", "invoice", "rechnung", "erp",
    ),
    "contracts": (
        "commercial_jurist_contracts", "contract", "vertrag", "verträge",
        "legal", "rechtsanwalt", "jurist", "nda", "baugb", "ip_licensing",
    ),
    "crm": (
        "crm", "sales_closer", "customer_success", "b2b_outreach",
        "lead", "kunde", "debitoren", "kontakt",
    ),
    "hr": (
        "hr_recruiter", "labor_law_hr_governance", "personalakte",
        "recruiting", "bewerber", "chro", "mitarbeiter",
    ),
    "gdpr": (
        "compliance_gdpr_auditor", "gdpr", "dsgvo", "datenschutz",
    ),
}

_CLOUD_PROVIDERS = frozenset({
    "openrouter",
    "openai",
    "groq",
    "anthropic",
    "google",
    "gemini",
    "mistral",
    "nvidia",
})


class ZeroEgressBlockedError(RuntimeError):
    """Wird geworfen, wenn der Privacy-Router oder Zero-Egress einen ausgehenden LLM-Call hart blockiert."""

    def __init__(self, message: str, *, audit_event: Optional[Dict[str, Any]] = None, error_code: str = "ZERO_EGRESS_BLOCKED"):
        super().__init__(message)
        self.error_code = error_code
        self.audit_event = audit_event or {}


def infer_data_category(
    agent_id: str = "",
    role: str = "",
    explicit_category: str = "",
) -> str:
    if explicit_category and explicit_category.strip():
        return explicit_category.strip().lower()
    haystack = f"{agent_id} {role}".lower()
    for cat, markers in _SENSITIVE_AGENT_CATEGORY_MAP.items():
        if any(m in haystack for m in markers):
            return cat
    return "general"


def _is_local_model_name(model: str) -> bool:
    m = (model or "").lower().strip()
    if m.startswith(("ollama/", "local/", "vllm/", "lmstudio/")):
        return True
    # Cloud-Präfixe ausschließen
    if any(m.startswith(pfx) for pfx in ("openai/", "anthropic/", "google/", "deepseek/", "openrouter/", "mistralai/", "meta-llama/", "auto/", "strict-free-tier")):
        return False
    return m in ("llama3.2", "llama3.1", "llama3", "qwen2.5", "qwen3", "mistral", "phi3", "gemma2")


def evaluate_and_gate_llm_dispatch(
    *,
    agent_id: str,
    provider: str,
    model: str,
    messages: Optional[List[Dict[str, Any]]] = None,
    role: str = "",
    explicit_category: str = "",
    intended_url: str = "",
    audit_logger: Any = None,
) -> Dict[str, Any]:
    """
    Zentrales Pre-Flight-Gate vor jedem LLM-Aufruf:
    - Gibt bei Freigabe bzw. lokalem Rerouting zurück:
      `{"allowed": True, "routed_to_local": bool, "provider": str, "model": str, "target_url": str, "data_category": str, "zero_egress_active": bool}`
    - Wirft bei Verstoß oder Offline-Lokalmodell sofort `ZeroEgressBlockedError` und schreibt
      den Block-Beweis unveränderbar in die SHA-256-Hashkette!
    """
    alog = audit_logger or chained_audit_log
    cfg = get_privacy_config()
    zero_strict = bool(cfg.get("zero_egress_strict", False))
    sens_routing = bool(cfg.get("sensitive_local_routing", False))
    category = infer_data_category(agent_id=agent_id, role=role, explicit_category=explicit_category)
    sens = is_sensitive_category(category, cfg)
    zero_active = zero_strict or (sens_routing and sens)

    route_decision = route_sensitive_payload(
        category=category,
        messages=messages or [],
        default_provider=provider,
        default_model=model,
    )

    if route_decision.get("blocked"):
        blocked_ep = intended_url or str(cfg.get("local_llm_url", "http://127.0.0.1:11434/v1")) + "/chat/completions"
        ev = alog.record_llm_dispatch(
            agent_id=agent_id or "system",
            provider=provider or "local",
            model=model or str(cfg.get("local_llm_model", "llama3.2")),
            target_endpoint=blocked_ep,
            action="llm_dispatch_blocked_local_offline",
            data_category=category,
            http_status=0,
            zero_egress_active=True,
            extra={
                "error_code": route_decision.get("error_code", "LOCAL_LLM_OFFLINE_HARD_BLOCK"),
                "reason": route_decision.get("reason", ""),
            },
        )
        raise ZeroEgressBlockedError(
            route_decision.get("reason") or "Zero-Egress Hard-Block: Lokales Modell ist offline.",
            audit_event=ev,
            error_code=route_decision.get("error_code", "LOCAL_LLM_OFFLINE_HARD_BLOCK"),
        )

    if route_decision.get("routed"):
        base_url = str(route_decision.get("base_url") or cfg.get("local_llm_url", "http://127.0.0.1:11434/v1")).rstrip("/")
        local_ep = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        _, _, zone = sanitize_llm_endpoint(local_ep)
        if zero_strict and zone != "LOCAL_ON_PREM":
            ev = alog.record_llm_dispatch(
                agent_id=agent_id or "system",
                provider=str(route_decision.get("provider") or provider),
                model=str(route_decision.get("model") or model),
                target_endpoint=local_ep,
                action="llm_dispatch_blocked_egress_zone",
                data_category=category,
                http_status=0,
                zero_egress_active=True,
                extra={"reason": "Strict Zero-Egress verbietet jeden Nicht-On-Premise-Endpunkt."},
            )
            raise ZeroEgressBlockedError(
                f"Strict Zero-Egress: Ziel '{local_ep}' liegt außerhalb von LOCAL_ON_PREM ({zone}).",
                audit_event=ev,
                error_code="STRICT_ZERO_EGRESS_EXTERNAL_FORBIDDEN",
            )
        return {
            "allowed": True,
            "routed_to_local": route_decision.get("provider") == "local",
            "provider": str(route_decision.get("provider") or "local"),
            "model": str(route_decision.get("model") or model),
            "target_url": local_ep,
            "data_category": category,
            "zero_egress_active": True,
        }

    # Sicherheitsnetz: Falls intended_url explizit übergeben wurde und Zero-Egress aktiv ist,
    # darf niemals ein EXTERNAL_CLOUD-Endpunkt oder Cloud-Provider passieren.
    if zero_active and intended_url:
        clean_ep, _, zone = sanitize_llm_endpoint(intended_url)
        prov_low = (provider or "").strip().lower()
        if zone == "EXTERNAL_CLOUD" or prov_low in _CLOUD_PROVIDERS or (zone == "INTERNAL_GATEWAY" and not _is_local_model_name(model)):
            ev = alog.record_llm_dispatch(
                agent_id=agent_id or "system",
                provider=provider or "unknown",
                model=model or "unknown",
                target_endpoint=clean_ep,
                action="llm_dispatch_blocked_egress_policy",
                data_category=category,
                http_status=0,
                zero_egress_active=True,
                extra={"reason": "Direkter Cloud-Aufruf durch Zero-Egress-Policy unterbunden."},
            )
            raise ZeroEgressBlockedError(
                f"Zero-Egress Policy blockiert externen Aufruf an '{clean_ep}' (Provider: {provider}, Modell: {model}).",
                audit_event=ev,
                error_code="ZERO_EGRESS_CLOUD_ENDPOINT_BLOCKED",
            )

    return {
        "allowed": True,
        "routed_to_local": False,
        "provider": provider,
        "model": model,
        "target_url": intended_url,
        "data_category": category,
        "zero_egress_active": zero_active,
    }


def log_completed_llm_dispatch(
    *,
    agent_id: str,
    provider: str,
    model: str,
    target_endpoint: str,
    http_status: int = 200,
    data_category: str = "general",
    zero_egress_active: bool = False,
    task_id: str = "",
    audit_logger: Any = None,
) -> Dict[str, Any]:
    """Schreibt den Nachweis eines real ausgeführten LLM-Calls in die SHA-256-Hashkette."""
    alog = audit_logger or chained_audit_log
    extra: Dict[str, Any] = {}
    if task_id:
        extra["task_id"] = task_id
    return alog.record_llm_dispatch(
        agent_id=agent_id or "system",
        provider=provider or "unknown",
        model=model or "unknown",
        target_endpoint=target_endpoint,
        action="llm_call_dispatched" if 200 <= int(http_status) < 400 else "llm_call_http_error",
        data_category=data_category,
        http_status=int(http_status),
        zero_egress_active=zero_egress_active,
        extra=extra,
    )


def inspect_worker_network_isolation(network_name: str = ZERO_EGRESS_WORKER_NET) -> Dict[str, Any]:
    """
    Prüft über die Docker-Engine, ob das Worker-Netzwerk mit `Internal: true`
    (keine Internet-Route / kein NAT-Masquerading) existiert und aktiv erzwungen wird.
    """
    try:
        from utils.docker_client import docker_cli_host_args
        cmd = ["docker", *docker_cli_host_args(), "network", "inspect", network_name]
    except Exception:
        cmd = ["docker", "network", "inspect", network_name]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            return {
                "network_name": network_name,
                "exists": False,
                "internal_no_internet_route": False,
                "driver": None,
                "error": (proc.stderr or "Netzwerk nicht gefunden").strip(),
            }
        info_list = json.loads(proc.stdout)
        info = info_list[0] if info_list else {}
        is_internal = bool(info.get("Internal", False))
        opts = info.get("Options") or {}
        containers = list((info.get("Containers") or {}).keys())
        return {
            "network_name": info.get("Name", network_name),
            "network_id": str(info.get("Id", ""))[:12],
            "exists": True,
            "internal_no_internet_route": is_internal,
            "driver": info.get("Driver", "bridge"),
            "attached_containers_count": len(containers),
            "options": opts,
        }
    except Exception as exc:
        return {
            "network_name": network_name,
            "exists": False,
            "internal_no_internet_route": False,
            "driver": None,
            "error": str(exc),
        }


def ensure_worker_zero_egress_network(network_name: str = ZERO_EGRESS_WORKER_NET) -> Dict[str, Any]:
    """Legt das isolierte Worker-Docker-Netzwerk (`--internal`, ohne Internet-Route) idempotent an."""
    status = inspect_worker_network_isolation(network_name)
    if status.get("exists"):
        return status
    try:
        from utils.docker_client import docker_cli_host_args
        cmd = ["docker", *docker_cli_host_args(), "network", "create", "--internal", network_name]
    except Exception:
        cmd = ["docker", "network", "create", "--internal", network_name]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception:
        pass
    return inspect_worker_network_isolation(network_name)


def audit_zero_egress_posture(audit_logger: Any = None) -> Dict[str, Any]:
    """
    Gesamt-Prüfbericht der Zero-Egress-Konfiguration (für Governance-API, UI & Prüfer):
    1. Privacy-Router-Konfiguration (`zero_egress_strict`, `sensitive_local_routing`, `hard_block_on_local_offline`, `fallback_to_eu=False`)
    2. Lokales On-Premise-Modell Status
    3. Docker-Worker-Netzwerk-Isolation (`Internal: true` = keine Internet-Route)
    4. SHA-256-Hashketten-Beweis über alle bisherigen `llm_dispatch`-Einträge
    """
    alog = audit_logger or chained_audit_log
    cfg = get_privacy_config()
    local_llm = check_local_llm_status(force=False)
    worker_net = inspect_worker_network_isolation(cfg.get("worker_isolation_network", ZERO_EGRESS_WORKER_NET))
    sandbox_net = inspect_worker_network_isolation("archon-sandbox_net")
    chain = alog.verify_integrity()
    recent_dispatches = alog.list_llm_dispatches(limit=20)

    zone_counts = {"LOCAL_ON_PREM": 0, "INTERNAL_GATEWAY": 0, "EXTERNAL_CLOUD": 0, "BLOCKED": 0}
    for d in recent_dispatches:
        act = str(d.get("action") or "")
        z = str(d.get("egress_zone") or "")
        if "blocked" in act:
            zone_counts["BLOCKED"] += 1
        elif z in zone_counts:
            zone_counts[z] += 1

    no_cloud_leak_ready = (
        bool(cfg.get("hard_block_on_local_offline", True))
        and not bool(cfg.get("fallback_to_eu", False))
        and bool(chain.get("valid", False))
    )
    cfg_check = verify_zero_egress_config(cfg)

    return {
        "zero_egress_strict": bool(cfg.get("zero_egress_strict", False)),
        "sensitive_local_routing": bool(cfg.get("sensitive_local_routing", False)),
        "hard_block_on_local_offline": bool(cfg.get("hard_block_on_local_offline", True)),
        "fallback_to_eu": bool(cfg.get("fallback_to_eu", False)),
        "sensitive_categories": cfg.get("sensitive_categories", []),
        "config_verification": cfg_check,
        "local_llm_status": local_llm,
        "docker_worker_network": worker_net,
        "docker_sandbox_network": sandbox_net,
        "audit_chain": {
            "valid": chain.get("valid", False),
            "total_records": chain.get("total_records", 0),
            "llm_dispatch_records": chain.get("llm_dispatch_records", 0),
            "latest_hash": chain.get("latest_hash", ""),
        },
        "recent_dispatch_zone_summary": zone_counts,
        "recent_dispatches": recent_dispatches[:10],
        "fail_closed_verified": no_cloud_leak_ready and bool(cfg_check.get("zero_egress_verified", False)),
    }
