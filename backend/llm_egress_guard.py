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
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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
    haystack = f"{agent_id} {role}".lower()
    inferred = "general"
    for cat, markers in _SENSITIVE_AGENT_CATEGORY_MAP.items():
        if any(m in haystack for m in markers):
            inferred = cat
            break
    want = str(explicit_category or "").strip().lower()
    if not want:
        return inferred
    # KRITISCH (Audit 23.11.2026): explicit_category darf die serverseitige
    # Klassifikation NIE abschwächen. Eine sensibel klassifizierte Rolle bleibt
    # sensibel, egal was der Client behauptet.
    if want in _SENSITIVE_AGENT_CATEGORY_MAP or want == "confidential":
        return want
    if inferred in _SENSITIVE_AGENT_CATEGORY_MAP:
        return inferred
    return want


def _is_local_model_name(model: str) -> bool:
    m = (model or "").lower().strip()
    if m.startswith(("ollama/", "local/", "vllm/", "lmstudio/")):
        return True
    # Cloud-Präfixe ausschließen
    if any(m.startswith(pfx) for pfx in ("openai/", "anthropic/", "google/", "deepseek/", "openrouter/", "mistralai/", "meta-llama/", "auto/", "strict-free-tier")):
        return False
    return m in ("llama3.2", "llama3.1", "llama3", "qwen2.5", "qwen3", "phi3", "gemma2")


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

    # Sicherheitsnetz: Falls Zero-Egress aktiv ist, darf niemals ein EXTERNAL_CLOUD-Endpunkt
    # oder Cloud-Provider passieren — auch nicht bei LEEREM intended_url (Fail-Closed).
    if zero_active:
        prov_low = (provider or "").strip().lower()
        # FRUEHER: unbekannte Provider (custom/azure/bedrock/"") ohne
        # intended_url passierten ungeprüft — sensibler Inhalt konnte die
        # Umgebung verlassen. Jetzt Default-Deny: alles blocken, was nicht
        # explizit als lokales Modell ERKANNT wurde.
        if not intended_url:
            if prov_low in _CLOUD_PROVIDERS or not _is_local_model_name(model):
                alog = audit_logger or chained_audit_log
                ev = alog.record_llm_dispatch(
                    agent_id=agent_id or "system",
                    provider=provider or "unknown",
                    model=model or "unknown",
                    target_endpoint="(keine Ziel-URL)",
                    action="llm_dispatch_blocked_egress_policy",
                    data_category=category,
                    http_status=0,
                    zero_egress_active=True,
                    extra={"reason": "Cloud-Provider ohne Ziel-URL durch Zero-Egress-Policy unterbunden (Fail-Closed)."},
                )
                raise ZeroEgressBlockedError(
                    f"Zero-Egress Policy blockiert Cloud-Provider '{provider}' ohne Ziel-URL (Modell: {model}).",
                    audit_event=ev,
                    error_code="ZERO_EGRESS_CLOUD_ENDPOINT_BLOCKED",
                )
        else:
            clean_ep, _, zone = sanitize_llm_endpoint(intended_url)
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
    trace_id: str = "",
    audit_logger: Any = None,
) -> Dict[str, Any]:
    """Schreibt den Nachweis eines real ausgeführten LLM-Calls in die SHA-256-Hashkette."""
    alog = audit_logger or chained_audit_log
    resolved_tid = (trace_id or "").strip()
    if not resolved_tid:
        try:
            from backend.trace_context import current_trace_id
            resolved_tid = current_trace_id()
        except Exception:
            resolved_tid = ""
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
        trace_id=resolved_tid,
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
    except Exception as _exc:
        logger.debug("[llm_egress_guard] Ignorierte Ausnahme (Z.316): %s", _exc)
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

    # P1: Eine "gueltige" Kette ohne HMAC-Key darf nicht als verifiziert gelten.
    no_cloud_leak_ready = (
        bool(cfg.get("hard_block_on_local_offline", True))
        and not bool(cfg.get("fallback_to_eu", False))
        and bool(chain.get("valid", False))
        and bool(chain.get("hmac_active", False))
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
            "hmac_active": chain.get("hmac_active", False),
            "hmac_blocks": chain.get("hmac_blocks", 0),
            "total_records": chain.get("total_records", 0),
            "llm_dispatch_records": chain.get("llm_dispatch_records", 0),
            "latest_hash": chain.get("latest_hash", ""),
        },
        "recent_dispatch_zone_summary": zone_counts,
        "recent_dispatches": recent_dispatches[:10],
        "fail_closed_verified": no_cloud_leak_ready and bool(cfg_check.get("zero_egress_verified", False)),
    }


_INTERNAL_EGRESS_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "[::1]",
    "omniroute", "ollama", "hermes", "hermes-agent", "hermes-dashboard",
    "odysseus", "openclaw", "host.docker.internal", "vllm", "lmstudio",
})


def enforce_egress_firewall_for_url(
    url: str,
    *,
    agent_id: str = "agent-worker",
    audit_logger: Any = None,
) -> Dict[str, Any]:
    """
    Prüft ausgehende LLM-Endpunkte gegen `egress_firewall.check_url(...)`.
    Interne Docker-Service-Namen und LOCAL_ON_PREM-Hosts bleiben zulässig;
    unautorisierte externe Cloud-Hosts lösen `ZeroEgressBlockedError` aus.
    """
    if not url or not str(url).strip():
        alog = audit_logger or chained_audit_log
        ev = alog.record_llm_dispatch(
            agent_id=agent_id or "system",
            provider="unknown",
            model="egress-firewall",
            target_endpoint="unknown://empty",
            action="llm_dispatch_blocked_empty_url",
            data_category="egress_firewall",
            http_status=0,
            zero_egress_active=True,
            extra={"reason": "Leere Ziel-URL durch Fail-Closed Egress-Guard blockiert."},
        )
        raise ZeroEgressBlockedError(
            "Leere Ziel-URL für ausgehenden LLM-Aufruf blockiert (Fail-Closed).",
            audit_event=ev,
            error_code="EGRESS_EMPTY_URL_BLOCKED",
        )

    clean_ep, host, zone = sanitize_llm_endpoint(url)
    host_low = (host or "").strip().lower()
    # IPv6-sicher extrahieren: [fe80::254]:8080, bare fe80::254 und IPv4:port
    if host_low.startswith("["):
        host_ip_raw = host_low[1:].split("]")[0]
    elif host_low.count(":") >= 2:
        host_ip_raw = host_low
    else:
        host_ip_raw = host_low.split(":")[0]
    import ipaddress as _ipaddr
    import socket as _socket
    _ip_obj = None
    try:
        _ip_obj = _ipaddr.ip_address(host_ip_raw)
    except ValueError:
        try:
            # Hex/Oktal/Integer-IPv4 wie 0xa9fea9fe oder 2852039166 abfangen
            _packed = _socket.inet_aton(host_ip_raw)
            _ip_obj = _ipaddr.ip_address(_socket.inet_ntoa(_packed))
        except OSError:
            _ip_obj = None
    if _ip_obj is not None:
        # IPv4-mapped IPv6 (::ffff:169.254.169.254) auf die gemappte IPv4 pruefen
        _check_obj = _ip_obj
        try:
            _mapped = getattr(_ip_obj, "ipv4_mapped", None)
            if _mapped is not None:
                _check_obj = _mapped
        except Exception:
            _check_obj = _ip_obj
        if _check_obj.is_link_local or _check_obj.is_multicast or _check_obj.is_unspecified or str(_check_obj) == "169.254.169.254" or str(_ip_obj) == "fd00:ec2::254":
            alog = audit_logger or chained_audit_log
            ev = alog.record_llm_dispatch(
                agent_id=agent_id or "system",
                provider=host_low or "external",
                model="egress-firewall",
                target_endpoint=clean_ep,
                action="llm_dispatch_blocked_metadata_ip",
                data_category="egress_firewall",
                http_status=0,
                zero_egress_active=True,
                extra={"reason": f"Link-Local / Cloud-Metadata IP blockiert: {_ip_obj}", "url": clean_ep},
            )
            raise ZeroEgressBlockedError(
                f"Link-Local / Cloud-Metadata-Adresse blockiert: '{clean_ep}'",
                audit_event=ev,
                error_code="EGRESS_METADATA_BLOCKED",
            )
    if zone == "LOCAL_ON_PREM" or host_low in _INTERNAL_EGRESS_HOSTS or (zone == "INTERNAL_GATEWAY" and "." not in host_low and not host_low.endswith(".local")):
        # KRITISCH: die Zonenklassifikation allein darf nie freigeben. Ein
        # interner Service-Name kann per DNS-Search/Rebinding auf eine
        # oeffentliche IP zeigen. Vor der Freigabe JEDES aufgeloeste Ziel
        # gegen private/link-locale Adressen pruefen (auch IPv6).
        import ipaddress
        import socket
        resolved_ok = True
        try:
            infos = socket.getaddrinfo(host_low, None)
            for info in infos:
                addr = str(info[4][0])
                try:
                    ip = ipaddress.ip_address(addr.split("%")[0])
                except ValueError:
                    resolved_ok = False
                    break
                mapped = getattr(ip, "ipv4_mapped", None)
                if mapped is not None:
                    ip = mapped
                if not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast):
                    resolved_ok = False
                    break
        except (OSError, ValueError):
            resolved_ok = False  # DNS nicht aufloesbar -> fail-closed
        if not resolved_ok:
            # F-030: auch der DNS-/Rebinding-Fail-Closed-Block braucht einen
            # signierten Dispatch-Proof — alle anderen Blockpfade dieser
            # Funktion schreiben ebenfalls einen (S-5.2 „auch geblockte").
            alog = audit_logger or chained_audit_log
            reason = (
                f"Zero-Egress: '{host_low}' ({zone}) liefert keine rein lokale/private "
                "Adresse — blockiert."
            )
            ev = alog.record_llm_dispatch(
                agent_id=agent_id or "system",
                provider=host_low or "external",
                model="egress-firewall",
                target_endpoint=clean_ep,
                action="llm_dispatch_blocked_dns_not_local",
                data_category="egress_firewall",
                http_status=0,
                zero_egress_active=True,
                extra={"reason": reason, "egress_zone": zone, "error_code": "EGRESS_DNS_NOT_LOCAL"},
            )
            raise ZeroEgressBlockedError(
                reason,
                audit_event=ev,
                error_code="EGRESS_DNS_NOT_LOCAL",
            )
        return {"allowed": True, "blocked": False, "zone": zone, "reason": "local_or_internal_gateway"}

    try:
        from backend.egress_firewall import egress_firewall
        fw_res = egress_firewall.check_url(url, agent_id=agent_id or "agent-worker")
    except Exception as exc:
        logger.warning("[EgressGuard] Firewall-Check fehlgeschlagen (%s): %s", clean_ep, exc)
        raise ZeroEgressBlockedError(
            f"Egress-Firewall-Prüfung fehlgeschlagen (Fail-Closed) für '{clean_ep}': {exc}",
            error_code="EGRESS_FIREWALL_ERROR",
        )

    if fw_res.get("blocked") or not fw_res.get("allowed", True):
        reason = str(fw_res.get("reason") or f"Egress-Firewall blockiert '{clean_ep}'")
        alog = audit_logger or chained_audit_log
        ev = alog.record_llm_dispatch(
            agent_id=agent_id or "system",
            provider=host_low or "external",
            model="egress-firewall",
            target_endpoint=clean_ep,
            action="llm_dispatch_blocked_egress_firewall",
            data_category="egress_firewall",
            http_status=0,
            zero_egress_active=True,
            extra={"reason": reason, "url": clean_ep},
        )
        raise ZeroEgressBlockedError(
            reason,
            audit_event=ev,
            error_code="EGRESS_FIREWALL_BLOCKED",
        )

    return {"allowed": True, "blocked": False, "zone": zone, "reason": str(fw_res.get("reason", "allowed"))}


def _sanitize_text_for_egress(text: str, session_id: str = "") -> Tuple[str, bool]:
    """Wendet Secret-Masking und PII-Scrubbing nacheinander auf einen Textblock an (Fail-Closed)."""
    if not isinstance(text, str) or not text:
        return text, False
    current = text
    changed = False
    try:
        from backend.secret_masker import mask_sensitive_text
        masked, count = mask_sensitive_text(current)
        if count:
            current = masked
            changed = True
    except Exception as exc:
        logger.error("[EgressGuard] Secret-Masking fehlgeschlagen (Fail-Closed): %s", exc)
        raise ZeroEgressBlockedError(
            f"Secret-Masking für ausgehenden Cloud-Call fehlgeschlagen (Fail-Closed): {exc}",
            error_code="EGRESS_SANITIZATION_ERROR",
        )
    try:
        from backend.pii_scrubber import pii_scrubber
        scrub_res = pii_scrubber.scrub_text(current, session_id=session_id or "")
        if isinstance(scrub_res, dict):
            scrubbed = scrub_res.get("scrubbed_text") or scrub_res.get("text")
            if scrubbed and (scrub_res.get("scrubbed") or scrub_res.get("redactions_count", 0) > 0 or scrubbed != current):
                current = scrubbed
                changed = True
    except Exception as exc:
        logger.error("[EgressGuard] PII-Scrubbing fehlgeschlagen (Fail-Closed): %s", exc)
        raise ZeroEgressBlockedError(
            f"PII-Scrubbing für ausgehenden Cloud-Call fehlgeschlagen (Fail-Closed): {exc}",
            error_code="EGRESS_SANITIZATION_ERROR",
        )
    return current, changed


def sanitize_outbound_llm_payload(
    payload: Optional[Dict[str, Any]],
    *,
    agent_id: str = "agent-worker",
    session_id: str = "",
    is_local: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Bereinigt ausgehende Cloud-LLM-Payloads (Secrets + PII) ohne Mutation der Eingabe-Dicts.
    Für lokale On-Premise-Modelle (`is_local=True`) bleiben die Payloads unverändert.
    """
    if not isinstance(payload, dict) or is_local:
        return payload

    sid = session_id or f"{agent_id or 'agent'}-{int(time.time() // 3600)}"
    out = dict(payload)

    for key in ("system", "prompt", "input"):
        if isinstance(out.get(key), str):
            sanitized, _ = _sanitize_text_for_egress(out[key], session_id=sid)
            out[key] = sanitized

    if isinstance(out.get("messages"), list):
        clean_msgs: List[Any] = []
        for msg in out["messages"]:
            if not isinstance(msg, dict):
                clean_msgs.append(msg)
                continue
            m_copy = dict(msg)
            content = m_copy.get("content")
            if isinstance(content, str):
                sanitized, _ = _sanitize_text_for_egress(content, session_id=sid)
                m_copy["content"] = sanitized
            elif isinstance(content, list):
                clean_blocks: List[Any] = []
                for blk in content:
                    if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                        b_copy = dict(blk)
                        sanitized, _ = _sanitize_text_for_egress(b_copy["text"], session_id=sid)
                        b_copy["text"] = sanitized
                        clean_blocks.append(b_copy)
                    else:
                        clean_blocks.append(blk)
                m_copy["content"] = clean_blocks
            if isinstance(m_copy.get("tool_calls"), list):
                clean_tcs: List[Any] = []
                for tc in m_copy["tool_calls"]:
                    if isinstance(tc, dict) and isinstance(tc.get("function"), dict):
                        tc_copy = dict(tc)
                        fn_copy = dict(tc_copy["function"])
                        if isinstance(fn_copy.get("arguments"), str):
                            sanitized_args, _ = _sanitize_text_for_egress(fn_copy["arguments"], session_id=sid)
                            fn_copy["arguments"] = sanitized_args
                        tc_copy["function"] = fn_copy
                        clean_tcs.append(tc_copy)
                    else:
                        clean_tcs.append(tc)
                m_copy["tool_calls"] = clean_tcs
            clean_msgs.append(m_copy)
        out["messages"] = clean_msgs

    if isinstance(out.get("contents"), list):
        clean_contents: List[Any] = []
        for item in out["contents"]:
            if not isinstance(item, dict) or not isinstance(item.get("parts"), list):
                clean_contents.append(item)
                continue
            item_copy = dict(item)
            clean_parts: List[Any] = []
            for part in item_copy["parts"]:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    p_copy = dict(part)
                    sanitized, _ = _sanitize_text_for_egress(p_copy["text"], session_id=sid)
                    p_copy["text"] = sanitized
                    clean_parts.append(p_copy)
                else:
                    clean_parts.append(part)
            item_copy["parts"] = clean_parts
            clean_contents.append(item_copy)
        out["contents"] = clean_contents

    return out

