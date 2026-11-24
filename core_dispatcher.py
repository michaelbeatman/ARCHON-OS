# mypy: ignore-errors
import asyncio
import contextvars
import datetime
import functools
import hashlib
import json
import logging
import os
import random
import sqlite3
import sys
import threading
import time
import weakref
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("archon.core_dispatcher")

# D11: Die im Prompt-Registry geloeste Version muss in JEDEM Dispatch-Return
# landen. Der ContextVar ist task-lokal und damit parallelITAetsicher; der
# outright-Aufrufer setzt ihn vor jedem Dispatch zurueck (kein Stale-Wert).
_PROMPT_VERSION_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "archon_dispatch_prompt_version", default=None
)
# D15/HIGH (A8): task-lokales Pflichtfeld-Schema fuer den Structured-Output-
# Chokepoint. Ohne Schema bleibt der Enforcer inaktiv (kein "schema_required"-
# Fehler fuer normale Freitext-Dispatcher).
_STRUCTURED_OUTPUT_SCHEMA_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "archon_structured_output_schema", default=None
)


def set_structured_output_schema(schema: Optional[Dict[str, Any]]) -> None:
    """Setzt das Pflichtfeld-Schema fuer den naechsten Dispatch (task-lokal)."""
    _STRUCTURED_OUTPUT_SCHEMA_CTX.set(dict(schema) if isinstance(schema, dict) else None)


# Audit-Schreibpfade sind sync SQLite. Serialisiert ueber einen Thread-Lock und
# aus dem Event-Loop via asyncio.to_thread ausgelagert (kein Event-Loop-Block).
_AUDIT_WRITE_LOCK = threading.Lock()

# D07/MED (A9): fehlgeschlagene Task-Abbrueche sind keine Erfolge und duerfen
# nicht still verschwinden. Prozess-lokal, kein Event-Replay (G-01/G-02).
_FAILED_CANCELS: list = []


def _record_failed_cancel(task_name: str, detail: str) -> None:
    """Persistiert einen gescheiterten cancel() inkl. Audit (best effort)."""
    entry = {"task": str(task_name), "detail": str(detail)[:500], "ts": time.time()}
    _FAILED_CANCELS.append(entry)
    logger.error("[Dispatcher] Cancel fehlgeschlagen: %s — %s", task_name, entry["detail"])
    try:
        with _AUDIT_WRITE_LOCK:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="recovery",
                action="cancel_failed",
                payload=entry,
            )
    except Exception as audit_exc:
        logger.warning("[Dispatcher] Cancel-Fehler nicht auditierbar: %s", audit_exc)


# D11: explizite Kürzungs-Marker statt stiller Slices in OTel-Spans.
from backend.handoff_desk import mark_truncated as _mark_truncated  # noqa: E402

# D15/HIGH (A8): zentrale Structured-Output-Pflicht am Antwort-Chokepoint.
from backend.structured_output_enforcer import structured_output_enforcer  # noqa: E402


def _prompt_version_fallback(agent_id: str, model: str = "") -> Dict[str, Any]:
    """Minimaler, ehrlicher Ref fuer Pfade vor der Registry-Aufloesung."""
    return {
        "agent_id": agent_id,
        "version": "",
        "canary": False,
        "prompt_chars": 0,
        "model": model or "",
        "resolved": False,
    }


def _with_prompt_info(res: dict, info: Optional[Dict[str, Any]] = None) -> dict:
    """Hängt effective_prompt_info/prompt_version_info an JEDEN Return."""
    if not isinstance(res, dict):
        return res
    if info is not None:
        ref = dict(info)
        res["effective_prompt_info"] = ref
        res["prompt_version_info"] = ref
        return res
    ref = dict(_PROMPT_VERSION_CTX.get() or {})
    if not ref:
        ref = _prompt_version_fallback(str(res.get("agent_id") or ""))
    res.setdefault("effective_prompt_info", ref)
    res.setdefault("prompt_version_info", ref)
    return res


def _resolve_prompt_ref(agent_id: str, task_id: str = "", model: str = "") -> Dict[str, Any]:
    """Prompt-Ref aus der Registry fuer Pfade ohne Provider-Impl (Container)."""
    try:
        from backend.prompt_registry import prompt_registry
        eff = prompt_registry.get_effective_prompt(agent_id, task_id or None)
        if eff and eff.get("prompt"):
            return {
                "agent_id": agent_id,
                "version": str(eff.get("version_num") or eff.get("version") or eff.get("prompt_version") or ""),
                "canary": bool(eff.get("is_canary") or eff.get("canary") or False),
                "canary_percentage": eff.get("canary_percentage"),
                "prompt_hash": hashlib.sha256(str(eff.get("prompt") or "").encode("utf-8")).hexdigest(),
                "prompt_chars": len(str(eff.get("prompt") or "")),
                "model": eff.get("model") or model or "",
                "resolved": True,
            }
    except Exception as pr_exc:
        logger.debug("[Dispatcher] Prompt-Ref (Container-Pfad) nicht verfuegbar: %s", pr_exc)
    return _prompt_version_fallback(agent_id, model)


async def _audit_log_async(**kwargs: Any) -> Optional[dict]:
    """Audit-Nachweis aus dem Event-Loop auslagern (D11/D05: kein Sync-SQLite)."""
    def _write() -> Optional[dict]:
        from backend.llm_egress_guard import log_completed_llm_dispatch
        with _AUDIT_WRITE_LOCK:
            return log_completed_llm_dispatch(**kwargs)

    try:
        return await asyncio.to_thread(_write)
    except Exception as exc:
        # R-B/D05 (Re-Audit): kein erfolgreicher Dispatch ohne signierten
        # Proof. Vorher wurde der Fehler nur gewarnt und None zurueckgegeben.
        logger.error("[Dispatcher] Audit-Schreibpfad fehlgeschlagen (fail-closed): %s", exc)
        raise RuntimeError(f"audit_write_failed: {exc}") from exc


_SILENT_FAILURE_FLAG_PREFIXES = ("tool_loop", "token_spike", "effort_collapse")


async def _guard_silent_failures(res: dict, agent_id: str, task_id: str) -> dict:
    """D12: 'success' trotz versteckter Tool-/Token-Anomalien ist kein Erfolg.

    Der Flightlog-Produzent (tool_runtime.execute_agent_tool) schreibt Events
    unter ``flightlog_run_id`` (Trajectory-/Task-ID; A5 spiegelt zusaetzlich
    unter der Trace-ID). Der Dispatcher prueft Trajectory-ID **und** Trace-ID.
    Bei Flags wird der Status auf ``needs_human``/``blocked`` gesetzt
    und ein signiertes Audit-Event geschrieben.
    """
    if not isinstance(res, dict) or res.get("status") != "success":
        return res
    # D13/HIGH: Produzent schreibt unter flightlog_run_id (Trajectory/Task-ID),
    # nicht unter current_trace_id(). Beide Namensraeume abfragen.
    run_ids: list[str] = []
    try:
        from backend.trajectory_budget import normalize_trajectory_id
        if str(task_id or "").strip():
            run_ids.append(normalize_trajectory_id(
                task_id if str(task_id).startswith("traj-") else None,
                root_ticket_id=str(task_id),
            ))
    except Exception as exc:
        logger.debug("[Dispatcher] Trajectory-ID nicht verfuegbar: %s", exc)
    try:
        from backend.trace_context import current_trace_id
        trace = str(current_trace_id() or "").strip()
        if trace and trace not in run_ids:
            run_ids.append(trace)          # Fallback: gespiegelter Namensraum (A5)
    except Exception as exc:
        logger.debug("[Dispatcher] Trace-ID nicht verfuegbar: %s", exc)
    if not run_ids:
        return res

    try:
        from backend.flightlog_backtester import detect_silent_failures
    except Exception as flight_exc:
        logger.debug("[Dispatcher] Silent-Failure-Detektor nicht verfuegbar: %s", flight_exc)
        return res

    finding: dict = {}
    run_id = run_ids[0]
    for rid in run_ids:
        try:
            candidate = await asyncio.to_thread(
                detect_silent_failures, rid,
                res.get("status", "success"), str(res.get("content") or ""),
            )
        except Exception as flight_exc:
            logger.debug("[Dispatcher] Silent-Failure-Detektor fuer %s nicht verfuegbar: %s", rid, flight_exc)
            continue
        if not finding or candidate.get("flags"):
            finding = candidate
            run_id = rid
        if candidate.get("flags"):
            break
    if not finding:
        return res

    flags = [str(f) for f in (finding.get("flags") or [])]
    hits = [f for f in flags if any(f.startswith(p) for p in _SILENT_FAILURE_FLAG_PREFIXES)]
    if not hits and not finding.get("silent_failure"):
        return res

    status = "needs_human" if any(f.startswith("effort_collapse") or f.startswith("hidden_tool_errors") for f in flags) else "blocked"
    logger.error(
        "[Dispatcher] Silent-Failure-Guard: run=%s agent=%s flags=%s -> %s",
        run_id, agent_id, flags, status,
    )
    res["status"] = status
    res["error_code"] = "SILENT_FAILURE_DETECTED"
    res["silent_failure_flags"] = flags
    res["silent_failure_run_id"] = run_id
    res["content"] = (
        f"🛑 [SILENT-FAILURE-BLOCK]: {', '.join(flags)} — "
        "Erfolgsmeldung unterdrueckt, HITL-Pruefung erforderlich."
    )

    def _write_audit() -> None:
        try:
            from backend.audit_log import chained_audit_log
            with _AUDIT_WRITE_LOCK:
                chained_audit_log.record_event(
                    category="silent_failure",
                    action="dispatch_blocked_by_silent_failure",
                    agent_id=agent_id or "system",
                    payload={
                        "run_id": run_id,
                        "task_id": task_id,
                        "flags": flags,
                        "status": status,
                        "event_count": finding.get("event_count"),
                        "total_tokens": finding.get("total_tokens"),
                    },
                )
        except Exception as audit_exc:
            # D05/S-5.4: GoBD-relevanter Audit-Schreibfehler darf nie nur als
            # WARNING verschwinden, während der Dispatch als Erfolg gilt.
            logger.error("[Dispatcher] Silent-Failure-Audit fehlgeschlagen: %s", audit_exc)

    await asyncio.to_thread(_write_audit)
    return res


async def _provider_backoff(response=None, *, provider: str = "") -> None:
    """H1: jittered Backoff nach 429/5xx bzw. fehlgeschlagenem Provider-Hop.

    Verhindert, dass die Fallback-Kette einen rate-limitierten Provider im
    selben Millisekundenfenster erneut haemmert (Thundering Herd). `Retry-After`
    wird respektiert, aber auf 3 s gedeckelt.
    """
    delay = 0.2
    if response is not None:
        try:
            if getattr(response, "status_code", 0) == 429:
                delay = max(delay, float(getattr(response, "headers", {}).get("Retry-After", "0")))
        except (TypeError, ValueError):
            pass
    delay = min(3.0, delay)
    await asyncio.sleep(delay * (0.75 + random.random() * 0.5))


def _dispatch_cache_scope(
    agent_id: str = "",
    *,
    data_category: str = "",
    canary: bool = False,
    zero_egress_active: bool = False,
) -> str:
    """Tenant-/Policy-Scope fuer den semantischen Cache (kein Cross-Tenant-Leak).

    D02/HIGH: der Scope umfasst jetzt auch die wirksame Datenkategorie, die
    Prompt-Canary-Variante und den tatsaechlich aktiven Zero-Egress-Zustand.
    Eine zwischenzeitlich geaenderte Policy darf keine alte gecachte Antwort
    als "success" ausgeben.
    """
    tenant = ""
    try:
        from backend import tenant_context as _tc
        tenant = str(_tc._REQUEST_TENANT_VAR.get() or "")
    except Exception as tc_exc:
        logger.debug("[Dispatcher] Tenant-Var nicht verfuegbar: %s", tc_exc)
    if not tenant:
        try:
            from backend.tenant_context import tenant_context
            tenant = str(tenant_context.get_active_tenant_id() or "")
        except Exception as tc_exc:
            logger.debug("[Dispatcher] Tenant-Context nicht verfuegbar: %s", tc_exc)
    # D02: Policy-/Egress-Kontext in den Scope aufnehmen — eine zwischenzeitlich
    # geänderte Policy darf keine alte gecachte Antwort als "success" ausgeben.
    policy_version = str(os.environ.get("ARCHON_POLICY_VERSION") or "")
    zero_egress = str(os.environ.get("ARCHON_ZERO_EGRESS_STRICT") or "").strip().lower()
    return (
        f"{tenant or 'default'}:{agent_id or 'default'}:{policy_version}:{zero_egress}"
        f":{data_category or 'general'}:{'canary' if canary else 'stable'}"
        f":{'zero_active' if zero_egress_active else 'egress_allowed'}"
    )


def _cache_policy_context(agent_id: str, role: str = "", prompt: str = "") -> tuple[str, bool]:
    """Wirksame Datenkategorie / Zero-Egress fuer den Cache-Key (ohne Audit-Write)."""
    explicit_cat = ""
    try:
        from backend.data_classifier import DataClassifier
        if not DataClassifier.classify(prompt or "").get("cloud_llm_allowed", True):
            explicit_cat = "confidential"
    except Exception as exc:
        logger.warning("[Dispatcher] Cache-DataClassifier fehlgeschlagen (fail-closed): %s", exc)
        explicit_cat = "confidential"
    try:
        from backend.llm_egress_guard import infer_data_category
        from backend.privacy_router import get_privacy_config, is_sensitive_category
        cfg = get_privacy_config() or {}
        category = infer_data_category(agent_id=agent_id, role=role, explicit_category=explicit_cat)
        zero_active = bool(cfg.get("zero_egress_strict", False)) or (
            bool(cfg.get("sensitive_local_routing", False))
            and is_sensitive_category(category, cfg)
        )
        return category, bool(zero_active)
    except Exception as exc:
        # scope-seitig fail-closed: anderer Scope => Cache-Miss => echter Gate-Pfad.
        logger.error("[Dispatcher] Cache-Policy-Kontext nicht verfuegbar (fail-closed): %s", exc)
        return "confidential", True


def _validate_cache_hit_gate(
    agent_id: str,
    provider: str,
    model: str,
    prompt: str,
    role: str = "",
    system_prompt: str = "",
) -> dict:
    """D02/HIGH: Governance-Gate bei JEDEM Cache-Hit erneut auswerten.

    Compliance-/Activation-Check, DataClassifier und
    ``evaluate_and_gate_llm_dispatch()`` sind die Produzenten des
    ``blocked``-Verdikts; hier gibt es endlich einen Konsumenten. Fehler
    eskalieren als ZeroEgressBlockedError (fail-closed), nie als Cache-Erfolg.
    """
    from backend.llm_egress_guard import (
        ZeroEgressBlockedError,
        evaluate_and_gate_llm_dispatch,
    )

    try:
        from backend.compliance_engine import compliance_engine
        chk = compliance_engine.check_activation_allowed(
            agent_id, system_prompt=system_prompt or prompt or ""
        )
        if not chk.get("allowed", True):
            raise ZeroEgressBlockedError(
                chk.get("reason") or f"Compliance Guardrail blockiert '{agent_id}'.",
                error_code=chk.get("error_code") or "COMPLIANCE_BLOCKED",
            )
    except ZeroEgressBlockedError:
        raise
    except Exception as exc:
        logger.error("[Dispatcher] Cache-Hit Compliance-Gate nicht verfuegbar — blockiert: %s", exc)
        raise ZeroEgressBlockedError(
            f"Compliance-Gate nicht verfuegbar: {exc}",
            error_code="COMPLIANCE_GATE_UNAVAILABLE",
        ) from exc

    explicit_cat = ""
    try:
        from backend.data_classifier import DataClassifier
        if not DataClassifier.classify(prompt or "").get("cloud_llm_allowed", True):
            explicit_cat = "confidential"
    except Exception as exc:
        logger.error("[Dispatcher] Cache-Hit DataClassifier fehlgeschlagen (fail-closed): %s", exc)
        explicit_cat = "confidential"

    gate = evaluate_and_gate_llm_dispatch(
        agent_id=agent_id,
        provider=provider or "omniroute",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        role=role,
        explicit_category=explicit_cat,
    )
    if not gate.get("allowed", True):
        raise ZeroEgressBlockedError(
            "Dispatch-Gate verweigert den Cache-Hit (fail-closed).",
            error_code="LLM_DISPATCH_GATE_BLOCKED",
        )
    return gate

# --- External Agent URLs ---
# Defaulting to docker network hostnames, but can be overridden by env vars
HERMES_URL = os.getenv("HERMES_URL", "http://hermes-dashboard:9119")
ODYSSEUS_URL = os.getenv("ODYSSEUS_URL", "http://odysseus:7000")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:8080")
OMNIROUTE_URL = os.getenv("OMNIROUTE_URL", "http://omniroute:20128/v1")
# W4: der konfigurierte Key wurde im Haupt-Dispatcher nie in die Requests
# injiziert (nur in agent_router.py) — OmniRoute lieferte dann 401 und die
# Kette fiel auf OpenRouter/Ollama zurück, ohne dass der Router je erreicht
# wurde.
OMNIROUTE_API_KEY = os.getenv("OMNIROUTE_API_KEY", "").strip()
N8N_URL = os.getenv("N8N_URL", "http://n8n:5678")

def detect_target_action(text: str, frontmatter: str = "") -> str:
    """
    Erkennt operative Folgeaktionen aus Prompt-Payload oder Frontmatter.
    Beispiele:
    - ACTION: POST_LINKEDIN -> publish_linkedin
    - ACTION: WEBHOOK_CRM -> webhook_crm
    - ACTION: NONE / keine Angabe -> none
    """
    try:
        import jev_router
        if jev_router.is_jev_enabled():
            c = jev_router.classify_prompt(text)
            if c.get("action") == "direct_command":
                return c.get("intent", "none")
    except Exception as exc:
        logger.debug(f"[Dispatcher] JEV-Router-Klassifikation uebersprungen: {exc}")

    combined = f"{frontmatter}\n{text}".upper()
    import re
    m = re.search(r'ACTION:\s*([A-Z0-9_\-]+)', combined)
    if m:
        action_val = m.group(1).strip().lower()
        if "linkedin" in action_val:
            return "publish_linkedin"
        elif "crm" in action_val:
            return "webhook_crm"
        elif "none" in action_val:
            return "none"
        return action_val
    if "POST_LINKEDIN" in combined or "PUBLISH_LINKEDIN" in combined:
        return "publish_linkedin"
    if "WEBHOOK_CRM" in combined:
        return "webhook_crm"
    return "none"

async def trigger_n8n_execution(
    parent_project_id: str,
    title: str,
    final_report_path: str,
    content: str,
    target_action: str = "none",
    timeout: int = 10
) -> dict:
    """
    Sendet einen asynchronen Outbound-Webhook an n8n (Port 5678).
    URL: http://n8n:5678/webhook/archon-execution
    """
    import datetime
    url = f"{N8N_URL}/webhook/archon-execution"
    payload = {
        "parent_project_id": parent_project_id,
        "title": title,
        "final_report_path": final_report_path,
        "content": content,
        "action": target_action or "none",
        "executed_at": datetime.datetime.now().isoformat()
    }
    try:
        from backend.trace_context import child_span, inject_headers, inject_payload
    except Exception as exc:
        logger.warning("[Dispatcher] Trace-Kontext am n8n-Hop nicht verfuegbar: %s", exc)
        child_span = None
        inject_headers = None
        inject_payload = None
    try:
        from utils.safe_http import webhook_signature_headers
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(webhook_signature_headers(body))
        if child_span is not None and inject_headers is not None:
            # D16/H2: genau EIN Child-Span fuer diesen Hop. inject_headers()/
            # inject_payload() MUESSEN im Block laufen, damit die NEUE Span-ID
            # in traceparent und Payload steht (sonst Self-Parenting ohne
            # Kausalkante). child_span() forkt den aktiven Kontext; ohne
            # Kontext entsteht genau ein Root, und beim Verlassen wird der
            # umgebende Kontext wiederhergestellt.
            with child_span():
                if inject_payload is not None:
                    payload = inject_payload(payload)
                    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    headers.update(webhook_signature_headers(body))
                headers = inject_headers(headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, content=body, headers=headers)
            if resp.status_code == 200:
                # D12/MED: HTTP 200 allein ist KEIN Nachweis einer Ausfuehrung.
                # Ohne executionId/status bleibt der Versand unbestaeigt.
                ack = {}
                try:
                    ack = resp.json() if resp.content else {}
                except Exception as ack_exc:
                    logger.debug("[Dispatcher] n8n-Ack nicht parsbar: %s", ack_exc)
                if not isinstance(ack, dict):
                    ack = {}
                execution_id = str(ack.get("executionId") or ack.get("execution_id") or "").strip()
                confirmed = bool(execution_id) or str(ack.get("status") or "").strip().lower() in ("success", "ok", "running", "queued")
                if confirmed:
                    return {
                        "status": "success",
                        "code": 200,
                        "execution_id": execution_id,
                        "message": "n8n execution acknowledged",
                    }
                logger.warning("[Dispatcher] n8n HTTP 200 ohne Execution-Nachweis (action=%s).", target_action)
                return {
                    "status": "unconfirmed",
                    "code": 200,
                    "error_code": "N8N_DELIVERY_UNCONFIRMED",
                    "message": "n8n HTTP 200 ohne executionId — Ausfuehrung nicht bestaetigt.",
                }
            logger.warning("[Dispatcher] n8n HTTP %s (action=%s).", resp.status_code, target_action)
            return {
                "status": "error",
                "code": resp.status_code,
                "error_code": "N8N_DELIVERY_UNCONFIRMED",
                "message": f"n8n returned HTTP {resp.status_code} — Ausfuehrung nicht bestaetigt.",
            }
    except Exception as e:
        logger.error("[Dispatcher] n8n-Webhook nicht erreichbar: %s", e)
        return {
            "status": "error",
            "error_code": "N8N_DELIVERY_UNCONFIRMED",
            "message": f"n8n unreachable: {str(e)}",
        }

def _clean_dispatch_output(text: Any, session_id: Optional[str] = None, is_local: bool = False) -> str:
    from backend.llm_kernel import finalize_llm_output
    return finalize_llm_output(text, session_id=session_id, is_local=is_local)


def _gate_container_dispatch(agent_name: str, provider: str, model: str, prompt: str, url: str, *, system_prompt: str = "") -> dict:
    """Einheitliches Pre-Flight-Gate für Container-Dispatches (Compliance + DataClassifier + Zero-Egress)."""
    from backend.llm_egress_guard import (
        ZeroEgressBlockedError,
        enforce_egress_firewall_for_url,
        evaluate_and_gate_llm_dispatch,
    )
    aid = agent_name or provider
    try:
        from backend.compliance_engine import compliance_engine
        # D04: der SOUL-/System-Prompt MUSS mitgegeben werden, sonst wird der
        # HIGH_RISK-Hashabgleich in check_activation_allowed() übersprungen.
        chk = compliance_engine.check_activation_allowed(
            aid, system_prompt=system_prompt or prompt or ""
        )
        if not chk.get("allowed", True):
            raise ZeroEgressBlockedError(
                chk.get("reason") or f"Compliance Guardrail blockiert '{aid}'.",
                error_code=chk.get("error_code") or "COMPLIANCE_BLOCKED",
            )
    except ZeroEgressBlockedError:
        raise
    except Exception as exc:
        # F-041: kein Dispatch ohne auswertbares Compliance-Gate.
        logger.error(f"[Dispatcher] Compliance-Check fehlgeschlagen — blockiert: {exc}")
        raise ZeroEgressBlockedError(
            f"Compliance-Gate nicht verfuegbar: {exc}",
            error_code="COMPLIANCE_GATE_UNAVAILABLE",
        ) from exc

    explicit_cat = ""
    try:
        from backend.data_classifier import DataClassifier
        if not DataClassifier.classify(prompt or "").get("cloud_llm_allowed", True):
            explicit_cat = "confidential"
    except Exception as exc:
        logger.warning(f"[Dispatcher] DataClassifier fehlgeschlagen: {exc}")

    gate = evaluate_and_gate_llm_dispatch(
        agent_id=aid,
        provider=provider,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        explicit_category=explicit_cat,
        intended_url=url,
    )
    enforce_egress_firewall_for_url(url, agent_id=aid)
    return gate


async def _dispatch_to_container_endpoint(
    *,
    agent_name: str,
    provider: str,
    model: str,
    url: str,
    headers: dict,
    payload: dict,
    prompt: str,
    extract_fn,
    timeout: int = 30,
    system_prompt: str = "",
    task_id: str = "",
) -> dict:
    from backend.llm_egress_guard import ZeroEgressBlockedError
    aid = agent_name or provider
    try:
        gate = _gate_container_dispatch(agent_name, provider, model, prompt, url, system_prompt=system_prompt)
    except ZeroEgressBlockedError as ze:
        return _with_prompt_info({
            "status": "blocked", "error_code": ze.error_code,
            "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze}",
        })

    try:
        # D16/H3: Trace-Kontext ueber die Grenze Dispatcher -> Provider/n8n.
        # Alle drei Wrapper (Hermes :9119, Odysseus :7000, OpenClaw) rufen
        # diese Funktion; ein Child-Span hier deckt alle drei Hops ab.
        try:
            from backend.trace_context import child_span, inject_headers
            with child_span():
                headers = inject_headers(headers)
        except Exception as tr_exc:
            logger.warning("[Dispatcher] Trace-Injektion am Container-Hop (%s) fehlgeschlagen: %s", provider, tr_exc)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            await _audit_log_async(
                agent_id=aid,
                provider=provider,
                model=model,
                target_endpoint=url,
                http_status=resp.status_code,
                data_category=gate["data_category"],
                zero_egress_active=gate["zero_egress_active"],
                task_id=task_id,
                extra={"effective_prompt_info": _PROMPT_VERSION_CTX.get()} if _PROMPT_VERSION_CTX.get() else None,
            )
            if resp.status_code == 200:
                data = resp.json()
                # D12: HTTP 200 ohne Nutzlast darf NIE als Erfolg durchgereicht
                # werden. extract_fn liefert nur noch echte Inhaltsfelder.
                if not isinstance(data, dict):
                    raise RuntimeError("EMPTY_RESPONSE: Container-Antwort ist kein JSON-Objekt")
                raw = extract_fn(data)
                content = _clean_dispatch_output(raw) if raw else ""
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("EMPTY_RESPONSE: Container lieferte HTTP 200 ohne Nutzlast")

                p_toks = max(1, len(prompt or "") // 4)
                c_toks = max(1, len(content) // 4)
                cost_unverified = False
                try:
                    from backend.llm_kernel import estimate_model_cost_usd
                    est_cost = float(estimate_model_cost_usd(model, p_toks, c_toks))
                except Exception as cost_exc:
                    logger.debug("[Dispatcher] Kosten-Schaetzung nicht verfuegbar: %s", cost_exc)
                    est_cost = round((p_toks * 0.00000015) + (c_toks * 0.00000030), 6)
                    cost_unverified = True
                try:
                    from backend.execution_receipt_ledger import execution_receipt_ledger
                    await asyncio.to_thread(
                        execution_receipt_ledger.issue_receipt,
                        task_id=f"{provider}-{int(time.time())}",
                        agent_role=aid,
                        model_used=model,
                        prompt_tokens=p_toks,
                        completion_tokens=c_toks,
                        cost_usd=est_cost,
                        tools_invoked=[f"core_dispatcher.dispatch_to_{provider}"],
                    )
                except Exception as log_exc:
                    # D05/S-5.4: Quittungsfehler nie verschlucken. Der Erfolg
                    # wird explizit als ohne signierten Beweis markiert.
                    logger.error("[Dispatcher] Receipt fehlgeschlagen (%s): %s", provider, log_exc)
                    receipt_unverified = True
                else:
                    receipt_unverified = False
                return _with_prompt_info({
                    "status": "success", "content": content,
                    "cost_usd": est_cost, "cost_unverified": cost_unverified,
                    "receipt_unverified": receipt_unverified,
                })
            return _with_prompt_info({
                "status": "error", "error_code": "CONTAINER_HTTP_ERROR",
                "content": f"{provider.capitalize()} Error (HTTP {resp.status_code}): {resp.text}",
            })
    except RuntimeError as re_exc:
        logger.error("[Dispatcher] %s: %s", provider, re_exc)
        return _with_prompt_info({
            "status": "error", "error_code": "EMPTY_RESPONSE",
            "error": str(re_exc), "content": "",
        })
    except Exception as e:
        logger.error("[Dispatcher] Connection to %s failed: %s", provider, e)
        return _with_prompt_info({
            "status": "error", "error_code": "CONTAINER_CONNECTION_FAILED",
            "content": f"Connection to {provider.capitalize()} failed: {str(e)}",
        })


async def dispatch_to_hermes(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """Routet Anfragen physisch an den Hermes Agent (Port 9119)."""
    return await _dispatch_to_container_endpoint(
        agent_name=agent_name,
        provider="hermes",
        model="hermes-gateway",
        url=f"{HERMES_URL}/api/chat",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('HERMES_API_TOKEN', '')}",
        },
        payload={"messages": [{"role": "user", "content": prompt}]},
        prompt=prompt,
        extract_fn=lambda d: (d.get("choices") or [{}])[0].get("message", {}).get("content", ""),
        timeout=timeout,
    )


async def dispatch_to_odysseus(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """Routet Anfragen physisch an den Odysseus Agent (Port 7000)."""
    return await _dispatch_to_container_endpoint(
        agent_name=agent_name,
        provider="odysseus",
        model="odysseus-agent",
        url=f"{ODYSSEUS_URL}/api/run",
        headers={"Content-Type": "application/json"},
        payload={"prompt": prompt},
        prompt=prompt,
        extract_fn=lambda d: d.get("result") or d.get("response") or "",
        timeout=timeout,
    )


async def dispatch_to_openclaw(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """Routet Anfragen physisch an OpenClaw."""
    return await _dispatch_to_container_endpoint(
        agent_name=agent_name,
        provider="openclaw",
        model="openclaw-agent",
        url=f"{OPENCLAW_URL}/api/execute",
        headers={"Content-Type": "application/json"},
        payload={"task": prompt},
        prompt=prompt,
        extract_fn=lambda d: d.get("output", ""),
        timeout=timeout,
    )

def clean_think_tags(text: str) -> str:
    """
    Entfernt sauber alle <think>...</think> Abschnitte (sowohl geschlossene als auch offene/abgeschnittene).
    """
    if not text:
        return ""
    import re
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<think>[\s\S]*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()

def parse_omniroute_response(resp_text: str) -> str:
    """
    Parst Antworten von OpenAI-kompatiblen APIs (Groq, OmniRoute).

    D12: Eine leere/ungueltige Antwort ist ein FEHLER, keine leere Erfolgs-
    antwort. Der Parser wirft ``RuntimeError``; die Provider-Hops muessen das
    mit ``error_code=EMPTY_OR_INVALID_RESPONSE`` eskalieren.
    """
    if not resp_text:
        raise RuntimeError("EMPTY_OR_INVALID_RESPONSE: leere Provider-Antwort")
    try:
        data = json.loads(resp_text) if isinstance(resp_text, str) else resp_text
        if isinstance(data, dict):
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                msg = choice.get("message", {})
                content = msg.get("content") or choice.get("text") or ""
                if content:
                    return clean_think_tags(str(content))
            if "content" in data and data["content"]:
                return clean_think_tags(str(data["content"]))
    except Exception as exc:
        logger.debug(f"[Dispatcher] JSON-Antwort-Extraktion fehlgeschlagen: {exc}")

    # Server-Sent Events Parsing (data: {...})
    collected_content = []
    for line in resp_text.splitlines():
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            json_str = line[6:].strip()
            try:
                chunk = json.loads(json_str)
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content_piece = delta.get("content", "")
                    if content_piece:
                        collected_content.append(content_piece)
            except Exception as sse_exc:
                logger.debug("[Dispatcher] SSE-Chunk nicht parsbar: %s", sse_exc)
                continue

    if collected_content:
        return clean_think_tags("".join(collected_content))

    raise RuntimeError("EMPTY_OR_INVALID_RESPONSE: keine Nutzlast in Provider-Antwort")

# Globaler Concurrency Throttle (Pillar 2 / Prozessmodell)
# Drosselt gleichzeitige rechenintensive LLM-Tasks zum Schutz vor 99% CPU-Spitzen / Buffer Overflows
MAX_CONCURRENT_AGENT_TASKS = int(os.getenv("MAX_CONCURRENT_AGENT_TASKS", "5"))
# WeakKeyDictionary statt id(loop): id() wird nach GC eines Loops wiederverwendet
# und lieferte dann einen geschlossenen Client/Semaphore an einen neuen Loop.
# Ausserdem verhindert die Weak-Referenz, dass tote Loops Pools halten.
_TASK_SEMAPHORES = weakref.WeakKeyDictionary()
_DISPATCHER_HTTP_CLIENTS = weakref.WeakKeyDictionary()


def _get_task_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _TASK_SEMAPHORES.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(MAX_CONCURRENT_AGENT_TASKS)
        _TASK_SEMAPHORES[loop] = sem
    return sem


def _get_dispatcher_http_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    c = _DISPATCHER_HTTP_CLIENTS.get(loop)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(
            timeout=90.0,
            limits=httpx.Limits(max_keepalive_connections=25, max_connections=100)
        )
        _DISPATCHER_HTTP_CLIENTS[loop] = c
    return c


async def close_dispatcher_clients() -> int:
    """Shutdown-Hook: alle gepoolten Clients kontrolliert schliessen."""
    closed = 0
    for client in list(_DISPATCHER_HTTP_CLIENTS.values()):
        if not client.is_closed:
            try:
                await client.aclose()
                closed += 1
            except Exception:
                pass
    _DISPATCHER_HTTP_CLIENTS.clear()
    return closed

class _DispClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

async def _log_dispatcher_usage(agent_id: str, model: str, in_tok: int, out_tok: int, task_id: str = "") -> None:
    """Audit-/Budget-Logging nie direkt im Event-Loop: mehrere SQLite-
    Transaktionen pro Call serialisierten sonst alle parallelen Dispatches."""
    try:
        await asyncio.to_thread(
            _log_dispatcher_usage_sync, agent_id, model, in_tok, out_tok, task_id
        )
    except Exception as exc:
        logger.debug(f"[Dispatcher] Async Usage-Log fehlgeschlagen: {exc}")


def _log_dispatcher_usage_sync(agent_id: str, model: str, in_tok: int, out_tok: int, task_id: str = ""):
    try:
        import os
        import sqlite3
        import sys
        import time
        try:
            from backend.db_paths import resolve_db as _resolve_db
            db_path = _resolve_db("state.db")
        except Exception:
            db_path = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            
        # D03/H6 (A3-Delegation): busy_timeout + Connect-Timeout aus der SSOT,
        # keine hartcodierten 15000/15.0 mehr (Drift/Lock-Contention).
        from backend.db_paths import DB_BUSY_TIMEOUT_MS
        with sqlite3.connect(db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, factory=_DispClosingConn) as conn:
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            now = time.time()
            eff_task = task_id or f"agent_{agent_id}"
            s_id = f"task_{eff_task}" if not str(eff_task).startswith("task_") else str(eff_task)
            t_key = str(eff_task)
            # P0-8: Ein Einheitstarif fuer alle Modelle war falsch (Claude-Opus
            # wurde ~100x unterberechnet). Echte Preis-Tabelle mit Fallback.
            try:
                from backend.llm_kernel import estimate_model_cost_usd
                cost_usd = estimate_model_cost_usd(model, in_tok, out_tok)
            except Exception:
                cost_usd = round((in_tok * 0.00000015) + (out_tok * 0.00000030), 6)
            
            cur = conn.cursor()
            cur.execute("SELECT id FROM sessions WHERE id = ?", (s_id,))
            inserted_session = False
            if not cur.fetchone():
                unique_title = f"Task {eff_task[:25]} [{time.time_ns() % 1000000000}]"
                try:
                    cur.execute("""
                        INSERT OR IGNORE INTO sessions (
                            id, source, display_name, title, model, profile_name, started_at, message_count,
                            input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                        ) VALUES (?, 'agent_task', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """, (s_id, unique_title, unique_title, model, agent_id, now, in_tok, out_tok, cost_usd, cost_usd))
                    inserted_session = cur.rowcount > 0
                except sqlite3.Error as db_exc:
                    logger.debug(f"[Dispatcher] Session-Insert fuer Usage-Logging uebersprungen: {db_exc}")
            
            conn.execute("""
                INSERT INTO session_model_usage (
                    session_id, model, billing_provider, billing_base_url, billing_mode, task,
                    api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    reasoning_tokens, estimated_cost_usd, actual_cost_usd, first_seen, last_seen
                ) VALUES (?, ?, 'omniroute', 'http://omniroute:20128/v1', 'proxy', ?, 1, ?, ?, 0, 0, 0, ?, ?, ?, ?)
                ON CONFLICT(session_id, model, billing_provider, billing_base_url, billing_mode, task) DO UPDATE SET
                    api_call_count = api_call_count + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    last_seen = excluded.last_seen
            """, (s_id, model, t_key, in_tok, out_tok, cost_usd, cost_usd, now, now))
            
            if not inserted_session:
                conn.execute("""
                    UPDATE sessions 
                    SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                        estimated_cost_usd = estimated_cost_usd + ?
                    WHERE id = ?
                """, (in_tok, out_tok, cost_usd, s_id))
            
        if "main" in sys.modules:
            m = sys.modules["main"]
            if hasattr(m, "_LIVE_TELEMETRY_CACHE"):
                m._LIVE_TELEMETRY_CACHE["data"] = None
            if hasattr(m, "_MC_STATE_CACHE"):
                m._MC_STATE_CACHE["data"] = None
        try:
            from backend.execution_receipt_ledger import execution_receipt_ledger
            execution_receipt_ledger.issue_receipt(
                task_id=str(eff_task),
                agent_role=str(agent_id or "dispatcher"),
                model_used=str(model or "unknown"),
                prompt_tokens=int(in_tok),
                completion_tokens=int(out_tok),
                cost_usd=float(cost_usd),
                tools_invoked=["core_dispatcher"],
            )
        except Exception as log_exc:
            # D05/S-5.4: Usage-/Receipt-Schreibfehler sind GoBD-relevant —
            # nicht auf DEBUG verschlucken, sondern sichtbar eskalieren.
            logger.error(f"[Dispatcher] Usage-Audit-Log fehlgeschlagen: {log_exc}")
    except Exception as e:
        print(f"[DISPATCHER] Token telemetry write error: {e}", file=sys.stderr)

def _extract_tokens_usage(resp_text: str, prompt_str: str, reply_str: str):
    inp, out = max(50, len(prompt_str.split()) * 2), max(20, len(reply_str.split()) * 2)
    try:
        import json
        d = json.loads(resp_text) if isinstance(resp_text, str) else resp_text
        if isinstance(d, dict):
            u = d.get("usage", {})
            if isinstance(u, dict):
                inp = u.get("prompt_tokens") or u.get("input_tokens") or inp
                out = u.get("completion_tokens") or u.get("output_tokens") or out
    except (ValueError, TypeError, AttributeError) as exc:
        logger.debug(f"[Dispatcher] Token-Usage-Parsing fehlgeschlagen, nutze Schaetzung: {exc}")
    return int(inp), int(out)

async def dispatch_to_omniroute_or_container(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "deepseek/deepseek-chat",
    provider: str = "",
    timeout: int = 15,
    reasoning_level: str = "medium",
    task_id: str = "",
    history: Optional[list] = None,
    available_tools: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """
    Zentraler Dispatcher: Nutzt dynamisch den im Profil konfigurierten Provider & das Sprachmodell.
    Ermittelt API-Keys live aus api_provider.collect_keys(), Profil-.env oder System-Environment.
    Geregelt über globalen Concurrency Throttle Semaphore (Pillar 2).
    Instrumentiert mit OpenTelemetry- / Langfuse-Spans.
    """
    t_start = time.time()
    slot_id = task_id or f"{agent_id}-{t_start}"
    has_throttle_slot = False
    budget_reservation_id: str | None = None
    # Kein Stale-Prompt-Ref aus einer vorherigen Dispatch-Generation.
    _PROMPT_VERSION_CTX.set(None)
    try:
        from backend.concurrency_throttle import concurrency_throttle
        acquired = await concurrency_throttle.acquire_slot(agent_id, slot_id, priority=2)
        if not acquired:
            return _with_prompt_info({
                "status": "blocked",
                "error": "concurrency_throttle_timeout",
                "content": "🛑 [CONCURRENCY-THROTTLE]: Maximalzahl gleichzeitiger Agenten-Tasks erreicht (Timeout).",
            })
        has_throttle_slot = True
    except Exception as th_exc:
        # Fail-CLOSED: wenn das Concurrency-Gate nicht auswertbar ist, darf
        # kein unbegrenzter Dispatch starten (Audit: fail-open war kritisch).
        logger.error(f"[Dispatcher] Concurrency-Gate nicht verfuegbar - Dispatch blockiert: {th_exc}")
        return _with_prompt_info({
            "status": "blocked",
            "error": "concurrency_gate_unavailable",
            "error_code": "CONCURRENCY_GATE_UNAVAILABLE",
            "content": "🛑 [CONCURRENCY-GATE]: Gate nicht verfügbar — Dispatch blockiert (fail-closed).",
        })

    # d07: try/finally MUSS unmittelbar nach acquire_slot beginnen, damit ein
    # Abbruch (CancelledError) waehrend des Cache-Lookups den Slot niemals leakt.
    try:
        # Semantischer Cache VOR dem LLM-Call: ein Treffer erspart Budget-Reservierung
        # und Provider-Aufruf. D02/HIGH: Scope umfasst jetzt Tenant/Agent plus die
        # wirksame Policy (data_category, canary, zero_egress_active).
        cache_category, cache_zero_active = _cache_policy_context(agent_id, role=role, prompt=prompt)
        cache_canary = False
        try:
            cache_canary = bool(
                (await asyncio.to_thread(_resolve_prompt_ref, agent_id, task_id, model)).get("canary")
            )
        except Exception as cache_ref_exc:
            logger.debug("[Dispatcher] Cache-Prompt-Ref nicht verfuegbar: %s", cache_ref_exc)
        cache_scope = _dispatch_cache_scope(
            agent_id,
            data_category=cache_category,
            canary=cache_canary,
            zero_egress_active=cache_zero_active,
        )
        cache_hit = None
        try:
            from backend.semantic_cache import semantic_cache_manager
            # H11: lookup ist reine Sync-SQLite + JSON-Parse + Cosine über bis zu
            # 500 Vektoren. Direkt im Event-Loop serialisiert das bei parallelen
            # Agenten den Dispatch (und erzeugt Write-Locks durch den DELETE).
            cache_hit = await asyncio.to_thread(
                semantic_cache_manager.lookup, prompt, model=model, scope_key=cache_scope
            )
        except Exception as cache_exc:
            logger.debug(f"[Dispatcher] Semantischer Cache-Lookup nicht verfuegbar: {cache_exc}")
        if cache_hit and cache_hit.get("hit"):
            # D02/HIGH: bei JEDEM Hit das Governance-Gate erneut validieren.
            # Der Cache darf weder einen Compliance-/HITL-Block noch eine
            # DataClassifier- oder Zero-Egress-Entscheidung umgehen, und es
            # gibt keinen Cloud-Fallback auf einen blockierten Treffer.
            try:
                _validate_cache_hit_gate(
                    agent_id, provider, model, prompt,
                    role=role, system_prompt=system_prompt,
                )
            except Exception as gate_exc:
                logger.error("[Dispatcher] Cache-Hit durch Governance-Gate blockiert: %s", gate_exc)
                return _with_prompt_info({
                    "status": "blocked",
                    "error": str(gate_exc),
                    "error_code": getattr(gate_exc, "error_code", None) or "LLM_DISPATCH_GATE_BLOCKED",
                    "content": f"🛑 [GOVERNANCE-GATE]: {gate_exc}",
                    "audit_event": getattr(gate_exc, "audit_event", None),
                })
        if cache_hit and cache_hit.get("hit"):
            cached_content = str(cache_hit.get("response") or "")
            cache_clean_ok = True
            try:
                cached_content = _clean_dispatch_output(
                    cached_content,
                    session_id=task_id or agent_id,
                    is_local=False,
                )
            except Exception as cache_clean_exc:
                # D07/S-7.6: kein "success" mit ungeprüftem Cache-Inhalt. Den
                # Treffer verwerfen und darunter regulär zum Provider laufen.
                logger.error("[Dispatcher] Cache-Content-Cleanup fehlgeschlagen: %s", cache_clean_exc)
                cache_clean_ok = False
            if cache_clean_ok:
                return _with_prompt_info({
                    "status": "success",
                    "content": cached_content,
                    "model": cache_hit.get("cached_model") or model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    # Kein echter Call: 0 ist korrekt, aber explizit als ungeprüft markieren.
                    "cost_usd": 0.0,
                    "cost_unverified": True,
                    "cached": True,
                    "cache_match_type": cache_hit.get("match_type"),
                    "cache_similarity": cache_hit.get("similarity"),
                })

        async with _get_task_semaphore():
            # Atomare Budget-Reservierung statt Check-then-Use: parallele
            # DAG-Nodes können das harte Cap nicht mehr überschreiten.
            try:
                from backend.role_budget_engine import budget_bank
                est_in_tokens = max(100, len(str(prompt or "")) // 4)
                # P0-8: Output-Tokens und EUR-Vorabschaetzung fehlten. Ohne
                # est_eur greift der harte EUR-Cap erst NACH dem Geldausgeben.
                est_out_tokens = max(256, est_in_tokens // 2)
                try:
                    from backend.llm_kernel import estimate_model_cost_usd
                    from backend.role_budget_engine import USD_TO_EUR_RATE
                    est_cost_eur = round(
                        estimate_model_cost_usd(model, est_in_tokens, est_out_tokens, provider=provider)
                        * USD_TO_EUR_RATE,
                        6,
                    )
                except Exception:
                    est_cost_eur = 0.0
                # Sync SQLite (BEGIN IMMEDIATE + threading.Lock) — im
                # Event-Loop auslagern, sonst blockiert jeder Dispatch alle
                # parallelen DAG-Nodes (Audit 23.11.2026).
                bg_chk = await asyncio.to_thread(
                    budget_bank.reserve,
                    agent_id=agent_id,
                    task_id=task_id or None,
                    estimated_tokens=est_in_tokens + est_out_tokens,
                    estimated_cost_eur=est_cost_eur,
                    node_id=slot_id,
                )
                if not bg_chk.get("allowed", False):
                    return _with_prompt_info({
                        "status": "blocked",
                        "error": bg_chk.get("error_code", "ROLE_BUDGET_EXCEEDED"),
                        "error_code": bg_chk.get("error_code", "ROLE_BUDGET_EXCEEDED"),
                        "content": f"🛑 [BUDGET-CAP BLOCK]: {bg_chk.get('reason')}",
                    })
                budget_reservation_id = bg_chk.get("reservation_id")
            except Exception as bg_exc:
                # Fail-closed: ein nicht auswertbares Budget-Gate darf niemals
                # einen unbegrenzten Dispatch freigeben (Audit v3 Welle 6).
                logger.error(f"[Dispatcher] Pre-Flight Budget-Check fehlgeschlagen - Dispatch blockiert: {bg_exc}")
                return _with_prompt_info({
                    "status": "blocked",
                    "error": "budget_gate_unavailable",
                    "error_code": "BUDGET_GATE_UNAVAILABLE",
                    "content": "🛑 [BUDGET-GATE]: Budget-Prüfung nicht verfügbar — Dispatch blockiert (fail-closed).",
                })

            tr_id = None
            parent_sp_id = None
            try:
                from backend.trace_context import current_span_id, current_trace_id, ensure_trace
                if not current_trace_id():
                    ensure_trace()
                parent_sp_id = current_span_id() or None
            except Exception:
                parent_sp_id = None
            try:
                from backend.otel_tracer import tracer
                tr_id = tracer.start_trace(f"exec.{agent_id}", task_id=task_id or None, agent_id=agent_id)
            except Exception:
                tr_id = None

            res = await _dispatch_to_omniroute_or_container_exec(
                agent_id, agent_name, prompt, role, system_prompt, model, provider, timeout, reasoning_level, task_id,
                history=history, available_tools=available_tools,
            )
            # D12 (Agent E): Flightlog-Silent-Failure-Guard vor jeder
            # Erfolgsverbuchung (Cache, Budget-Settle, OTel-OK).
            res = await _guard_silent_failures(res, agent_id, task_id)

            # D15/HIGH (A8): Structured-Output-Pflicht am zentralen
            # Antwort-Chokepoint (nach parse_omniroute_response /
            # _clean_dispatch_output im Exec-Pfad, VOR Cache-Store und
            # Budget-Settle). Ohne Schema bleibt der Pfad inaktiv.
            if isinstance(res, dict) and res.get("status") == "success":
                _schema: Optional[Dict[str, Any]] = _STRUCTURED_OUTPUT_SCHEMA_CTX.get()
                if not isinstance(_schema, dict) or not _schema:
                    for _schema_key in ("output_schema", "response_schema", "schema"):
                        _candidate = res.get(_schema_key)
                        if isinstance(_candidate, dict) and _candidate:
                            _schema = _candidate
                            break
                if isinstance(_schema, dict) and _schema:
                    # Das DAG-Format {"required": [...]} auf das Enforcer-
                    # Format {feld: typ} abbilden (sonst "required" als
                    # Pflichtfeld fehlinterpretiert).
                    _schema_to_use = _schema
                    if isinstance(_schema.get("required"), (list, tuple)):
                        _schema_to_use = {str(_f): "str" for _f in _schema["required"]}
                        for _k, _v in _schema.items():
                            if _k != "required":
                                _schema_to_use[_k] = _v
                    try:
                        _soe_res = structured_output_enforcer.validate_and_enforce(
                            raw_output=str(res.get("content") or ""),
                            schema=_schema_to_use,
                        )
                        if _soe_res.get("valid") is False:
                            logger.error(
                                "[Dispatcher] Structured-Output ungueltig: %s",
                                _soe_res.get("error"),
                            )
                            res["status"] = "error"
                            res["error_code"] = "STRUCTURED_OUTPUT_INVALID"
                            res["error"] = str(_soe_res.get("error") or "structured_output_invalid")
                            res["structured_output_validation"] = _soe_res
                    except Exception as _soe_exc:
                        # Fail-closed: kein Erfolg ohne auswertbare Validierung.
                        logger.error(
                            "[Dispatcher] Structured-Output-Enforcer fehlgeschlagen (fail-closed): %s",
                            _soe_exc,
                        )
                        res["status"] = "error"
                        res["error_code"] = "STRUCTURED_OUTPUT_INVALID"
                        res["error"] = f"structured_output_enforcement_failed: {_soe_exc}"

            duration_ms = (time.time() - t_start) * 1000.0
            in_tok = int(res.get("input_tokens", 0) or 0)
            out_tok = int(res.get("output_tokens", 0) or 0)
            used_model = res.get("model") or model
            # D12/S-12.3: die Provider-Hops liefern meist keinen cost_usd.
            # Nicht still eine hartcodierte Konstante als echten Preis ausgeben,
            # sondern echt schätzen und das Ergebnis als ungeprüft markieren.
            if res.get("cost_usd") is not None:
                est_cost = float(res["cost_usd"])
                est_cost_unverified = bool(res.get("cost_unverified", False))
            else:
                est_cost_unverified = True
                try:
                    est_cost = float(estimate_model_cost_usd(
                        used_model, in_tok, out_tok,
                        provider=str(res.get("provider") or provider or ""),
                    ))
                except Exception as cost_est_exc:
                    logger.error("[Dispatcher] Kosten-Schaetzung fehlgeschlagen: %s", cost_est_exc)
                    est_cost = round((in_tok * 0.00000015) + (out_tok * 0.00000030), 6)
                res["cost_usd"] = est_cost
            res["cost_unverified"] = est_cost_unverified
            is_ok = res.get("status") == "success"

            # Erfolgreiche Antwort im tenant-scoped Cache speichern (nur echte Calls).
            if is_ok and res.get("content"):
                try:
                    from backend.semantic_cache import semantic_cache_manager
                    await asyncio.to_thread(
                        semantic_cache_manager.store,
                        prompt, str(res["content"]), model=used_model, scope_key=cache_scope,
                    )
                except Exception as cache_store_exc:
                    logger.debug(f"[Dispatcher] Semantic-Cache Store nicht verfuegbar: {cache_store_exc}")

            if budget_reservation_id:
                try:
                    from backend.role_budget_engine import budget_bank
                    if is_ok:
                        await asyncio.to_thread(
                            budget_bank.settle,
                            budget_reservation_id,
                            actual_tokens=in_tok + out_tok,
                            actual_cost_usd=est_cost,
                        )
                    else:
                        await asyncio.to_thread(
                            budget_bank.release,
                            budget_reservation_id,
                            reason=f"dispatch status={res.get('status')}",
                        )
                    budget_reservation_id = None
                except Exception as rec_exc:
                    # Kein stilles Verlieren von Verbrauch: sonst faellt sich das
                    # Budget nie und harte Caps wirken nur bis zum ersten DB-Fehler.
                    logger.error(f"[Dispatcher] Budget-Settlement fehlgeschlagen: {rec_exc}")

            if tr_id:
                try:
                    from backend.otel_tracer import tracer
                    tracer.record_span(
                        trace_id=tr_id,
                        name=f"llm.{agent_id}",
                        span_type="llm",
                        parent_span_id=parent_sp_id,
                        agent_id=agent_id,
                        model=used_model,
                        # D11: Kürzungen in OTel-Spans explizit markieren.
                        input_data=_mark_truncated(prompt, 500, artifact="dispatch prompt"),
                        output_data=_mark_truncated(res.get("content") or "", 500, artifact="dispatch response"),
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        cost_usd=est_cost,
                        duration_ms=duration_ms,
                        # D12: Ungeprüfte Kostenschätzung auch im Span sichtbar.
                        attributes={"cost_unverified": est_cost_unverified},
                        status="OK" if is_ok else "ERROR"
                    )
                    tracer.end_trace(tr_id, status="OK" if is_ok else "ERROR")
                except Exception as tr_exc:
                    # D16/H5: Export-/Abschlussfehler duerfen nicht auf DEBUG
                    # verschluckt werden — sichtbar loggen und zentral zaehlen.
                    logger.warning("[Dispatcher] Trace-Abschluss fehlgeschlagen: %s", tr_exc)
                    try:
                        from backend.trace_context import note_local_trace_error
                        note_local_trace_error("dispatch-trace-close", tr_exc)
                    except Exception as count_exc:  # pragma: no cover - nur bei Import-/Zaehlfehler
                        logger.warning("[Dispatcher] Trace-Fehlerzaehlung nicht verfuegbar: %s", count_exc)

            if res.get("status") in ("success", "error") and used_model:
                try:
                    from backend.bandit_model_router import bandit_model_router
                    bandit_model_router.record_outcome(
                        model_id=used_model,
                        success=is_ok,
                        latency_ms=duration_ms,
                    )
                except Exception as bn_exc:
                    logger.debug(f"[Dispatcher] Bandit-Feedback fehlgeschlagen: {bn_exc}")

            if isinstance(res, dict) and res.get("status") == "success" and res.get("content"):
                res["content"] = _clean_dispatch_output(
                    res["content"],
                    session_id=task_id or agent_id,
                    is_local=(str(res.get("provider") or "").lower() == "local"),
                )

            # D11: der im Provider-Pfad geloeste Prompt-Ref gehoert in JEDEN Return.
            return _with_prompt_info(res)
    finally:
        if budget_reservation_id:
            # Reservierung darf nie hängen bleiben (früher Return, Exception,
            # Zero-Egress-Block) — sonst wird Budget dauerhaft blockiert.
            try:
                from backend.role_budget_engine import budget_bank
                await asyncio.to_thread(
                    budget_bank.release,
                    budget_reservation_id,
                    reason="dispatch_finished_without_settle",
                )
            except Exception as rel_exc:
                logger.warning(f"[Dispatcher] Budget-Release im finally fehlgeschlagen: {rel_exc}")
        if has_throttle_slot:
            try:
                from backend.concurrency_throttle import concurrency_throttle
                await concurrency_throttle.release_slot(slot_id)
            except Exception as th_exc:
                logger.warning(f"[Dispatcher] Throttle-Slot {slot_id} konnte nicht freigegeben werden: {th_exc}")

from backend.llm_kernel import AUTO_MODEL_MAP, estimate_model_cost_usd

_OMNIROUTE_OPENROUTER_FALLBACK_MAP = {
    **AUTO_MODEL_MAP,
    "omniroute/best-coding": "deepseek/deepseek-chat",
    "omniroute/best-reasoning": "deepseek/deepseek-r1",
    "omniroute/best-vision": "google/gemini-2.5-flash",
    "omniroute/best-fast": "openai/gpt-4o-mini",
    "omniroute/best-free": "google/gemini-2.5-flash",
    "omniroute/free-forever": "google/gemini-2.5-flash",
    "omniroute/deepseek-coder": "deepseek/deepseek-chat",
}


def _resolve_openrouter_fallback_model(model: str) -> str:
    """Normalizes OmniRoute/auto model aliases to direct OpenRouter model IDs."""
    raw = (model or "").strip()
    low = raw.lower()
    if low in _OMNIROUTE_OPENROUTER_FALLBACK_MAP:
        return _OMNIROUTE_OPENROUTER_FALLBACK_MAP[low]
    if low.startswith("omniroute/"):
        stripped = raw.split("/", 1)[1].strip()
        if f"auto/{stripped}" in _OMNIROUTE_OPENROUTER_FALLBACK_MAP:
            return _OMNIROUTE_OPENROUTER_FALLBACK_MAP[f"auto/{stripped}"]
        if "/" in stripped:
            return stripped
        return "deepseek/deepseek-chat"
    if low.startswith("auto/") or raw in ("", "free-forever"):
        return "deepseek/deepseek-chat"
    return raw


async def _dispatch_to_omniroute_or_container_exec(
    agent_id: str,
    agent_name: str,
    prompt: str,
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "deepseek/deepseek-chat",
    provider: str = "",
    timeout: int = 15,
    reasoning_level: str = "medium",
    task_id: str = "",
    history: Optional[list] = None,
    available_tools: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """Wrapper mit harter Gesamt-Deadline fuer die Provider-Fallback-Kette.

    Vorher konnten 4 Groq-Modelle + 2 OmniRoute-URLs + OpenRouter + Ollama +
    3 Container nacheinander probiert werden — bis zu ~308 s bei gehaltenem
    Concurrency-Slot und gebundener Budget-Reservierung. Ein schlechter
    Provider legte damit das gesamte System lahm.
    """
    budget = float(os.environ.get("ARCHON_DISPATCH_FALLBACK_BUDGET_SEC", "90") or 90)
    try:
        async with asyncio.timeout(max(5.0, budget)):
            return await _dispatch_to_omniroute_or_container_impl(
                agent_id=agent_id, agent_name=agent_name, prompt=prompt,
                role=role, system_prompt=system_prompt, model=model,
                provider=provider, timeout=timeout, reasoning_level=reasoning_level,
                task_id=task_id, history=history, available_tools=available_tools,
            )
    except TimeoutError:
        logger.error(
            "[Dispatcher] Fallback-Budget von %ss ueberschritten (task=%s, agent=%s).",
            budget, task_id, agent_id,
        )
        return {
            "status": "error",
            "error": "dispatch_fallback_budget_exceeded",
            "detail": f"Keine Provider-Antwort binnen {budget}s.",
            "task_id": task_id,
        }


async def _dispatch_to_omniroute_or_container_impl(
    agent_id: str,
    agent_name: str,
    prompt: str,
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "deepseek/deepseek-chat",
    provider: str = "",
    timeout: int = 15,
    reasoning_level: str = "medium",
    task_id: str = "",
    history: Optional[list] = None,
    available_tools: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    # D07/MED (A7): dieselbe Kettendeadline wie im Wrapper auch hier sichtbar,
    # damit nach einer fehlgeschlagenen Exception kein weiterer Hop gestartet
    # wird, wenn die Restzeit bereits aufgebraucht ist.
    _fallback_budget = max(5.0, float(os.environ.get("ARCHON_DISPATCH_FALLBACK_BUDGET_SEC", "90") or 90))
    chain_deadline = time.monotonic() + _fallback_budget
    # JEV Tool-Pruning im echten Dispatch-Pfad: nur die zum Prompt passenden
    # Werkzeuge gehen in den LLM-Request (statt aller MCP-Tools).
    pruned_tools: List[Dict[str, Any]] = []
    if available_tools:
        try:
            import jev_router
            pruned_tools = jev_router.prune_tools(prompt or "", list(available_tools))
        except Exception as jev_exc:
            logger.debug(f"[Dispatcher] JEV-Tool-Pruning nicht verfuegbar: {jev_exc}")
            pruned_tools = list(available_tools)

    # Pillar 4 & Punkt 4: Aktive Memory-Injection (Erkenntnisse aus agentic_memory.db)
    memory_context_addon = ""
    try:
        from local_memory_bridge import memory_bridge as bridge
        # Hole die wichtigsten und relevantesten Erkenntnisse für diesen Agenten
        # Audit v3 2.1.5 / Punkt 3.2.5: STREKT nach agent_id isoliert — ohne Agenten-Kontext
        # keine Memory-Injection (Cross-Agent-Leakage).
        if agent_id:
            query_hint = prompt[:100] if prompt else ""
            # Audit 23.11.2026: tenant_id mitgeben (sonst landen Learnings
            # eines anderen Mandanten im System-Prompt) und die sync FTS5-
            # Suche aus dem Event-Loop auslagern.
            try:
                from backend.tenant_context import tenant_context as _tc
                _tenant_id = _tc.get_active_tenant_id()
            except Exception:
                _tenant_id = ""
            learnings = await asyncio.to_thread(
                bridge.search_learnings, query_hint, limit=4,
                agent_id=str(agent_id), tenant_id=_tenant_id,
            )
        else:
            learnings = []
        if learnings:
            lines = [f"- [{l.get('category', 'Allgemein')}] {l.get('summary')}" for l in learnings if l.get('summary')]
            if lines:
                memory_context_addon = "\n\n### [RELEVANTE ERKENNTNISSE AUS DEINEM LANGZEITGEDÄCHTNIS]:\n" + "\n".join(lines)
    except Exception as mem_err:
        logger.debug(f"[Dispatcher] Memory-Injection uebersprungen: {mem_err}")

    # Spekulatives Vorladen von Entitaeten (CRM, ERP, relevante Notizen)
    prefetch_addon = ""
    try:
        from backend.speculative_prefetcher import get_speculative_prefetcher
        prefetcher = get_speculative_prefetcher()
        p_res = prefetcher.prefetch_for_task(prompt, agent_id=agent_id)
        p_items = p_res.get("cached_items", {}) if isinstance(p_res, dict) else {}
        p_lines = []
        if "crm_contact" in p_items:
            c = p_items["crm_contact"]
            p_lines.append(f"- CRM-Kontakt: {c.get('first_name', '')} {c.get('last_name', '')} ({c.get('email', '')}) [Firma: {c.get('company', 'Unbekannt')}]")
        if "erp_doc" in p_items:
            d = p_items["erp_doc"]
            p_lines.append(f"- ERP-Dokument: {d.get('doc_number', '')} ({d.get('type', '')}) [Status: {d.get('status', '')}]")
        if p_lines:
            prefetch_addon = "\n\n### [SPEKULATIV VORGELADENE KONTEXT-DATEN]:\n" + "\n".join(p_lines)
    except Exception as pf_err:
        logger.debug(f"[Dispatcher] Spekulatives Prefetching uebersprungen: {pf_err}")

    # Prompt-Registry & Canary-Routing
    effective_prompt_info = None
    prompt_version_info = None
    try:
        from backend.prompt_registry import prompt_registry
        eff = prompt_registry.get_effective_prompt(agent_id, task_id)
        if eff and eff.get("prompt"):
            # WICHTIG: die Registry ersetzt den System-Prompt nicht einfach —
            # sonst gehen die vom DAG injizierten Brand-Voice-/Memory-Bloecke
            # verloren. Die Registry ist die BASIS, Addons werden angehaengt.
            registry_prompt = eff["prompt"]
            if registry_prompt not in system_prompt:
                system_prompt = f"{registry_prompt}\n\n{system_prompt}"
            effective_prompt_info = eff
            # Audit D11: Canary-/Prompt-Version muss im Handoff nachvollziehbar
            # bleiben. Nur Metadaten signieren, nie den kompletten Prompt-Text.
            # D11: die Registry liefert `version_num`/`is_canary` — nicht
            # `version`/`canary`. Ohne diese Kette war der signierte Versions-
            # String dauerhaft leer.
            prompt_version_info = {
                "agent_id": agent_id,
                "version": str(
                    eff.get("version_num") or eff.get("version") or eff.get("prompt_version") or ""
                ),
                "canary": bool(eff.get("is_canary") or eff.get("canary") or False),
                "canary_percentage": eff.get("canary_percentage"),
                "prompt_hash": hashlib.sha256(
                    str(eff.get("prompt") or "").encode("utf-8")
                ).hexdigest(),
                "prompt_chars": len(str(eff.get("prompt") or "")),
                "model": eff.get("model") or "",
                "resolved": True,
            }
            if eff.get("model") and not model:
                model = eff["model"]
    except Exception as pr_err:
        logger.debug(f"[Dispatcher] Prompt-Registry Lookup uebersprungen: {pr_err}")

    # Task-lokaler Ref fuer den aeusseren Dispatcher (D11: jeder Return).
    _PROMPT_VERSION_CTX.set(prompt_version_info)

    # Core Working Memory Blocks (letzte 2-3 gepinnte Blöcke)
    core_mem_addon = ""
    try:
        from backend.core_memory_manager import core_memory_manager
        cm_xml = core_memory_manager.compile_system_prompt_injection(agent_id=agent_id)
        if cm_xml:
            core_mem_addon = f"\n\n{cm_xml}"
    except Exception as cm_err:
        logger.debug(f"[Dispatcher] Core-Memory-Injection uebersprungen: {cm_err}")

    # Bandit Model Router (opt-in über auto/bandit)
    if model in ("auto/bandit", "auto/best-bandit"):
        try:
            from backend.bandit_model_router import bandit_model_router
            b_res = bandit_model_router.select_best_model()
            if b_res.get("enabled") and b_res.get("selected_model"):
                model = b_res["selected_model"]
        except Exception as bn_err:
            logger.debug(f"[Dispatcher] Bandit-Router Auswahl uebersprungen: {bn_err}")

    static_system_prompt = f"Du bist {agent_name} (Rolle: {role}). {system_prompt}".strip()
    dynamic_system_addon = f"{core_mem_addon}{memory_context_addon}{prefetch_addon}".strip()
    full_system_prompt = (
        f"{static_system_prompt}\n\n{dynamic_system_addon}".strip()
        if dynamic_system_addon
        else static_system_prompt
    )

    chat_history_turns = []
    if history:
        for h in history[-8:]:
            if isinstance(h, dict):
                r = str(h.get("role", "")).strip().lower()
                c = str(h.get("content", "") or "").strip()
                if r in ("user", "assistant") and c:
                    chat_history_turns.append({"role": r, "content": c})

    messages = [{"role": "system", "content": full_system_prompt}] + chat_history_turns + [
        {"role": "user", "content": prompt}
    ]

    # Keys dynamisch aus api_provider und Environment ermitteln
    collected_keys = {}
    try:
        import api_provider
        # D08/S-8.1: der Profil-.env-Scan liest ~70 Dateien synchron. Nicht im
        # Event-Loop blockieren — der TTL-Cache begrenzt nur die Frequenz.
        collected_keys = await asyncio.to_thread(api_provider.collect_keys)
    except Exception as key_err:
        logger.warning(f"[Dispatcher] API-Keys aus api_provider konnten nicht geladen werden: {key_err}")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY") or collected_keys.get("OPENROUTER_API_KEY") or ""
    groq_api_key = os.getenv("GROQ_API_KEY") or collected_keys.get("GROQ_API_KEY") or ""
    openai_api_key = os.getenv("OPENAI_API_KEY") or collected_keys.get("OPENAI_API_KEY") or ""
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or collected_keys.get("ANTHROPIC_API_KEY") or ""
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or collected_keys.get("GEMINI_API_KEY") or ""

    if isinstance(provider, (int, float)):
        timeout = int(provider)
        provider = ""
    prov_lower = (str(provider) if provider else "").strip().lower()
    if model in AUTO_MODEL_MAP:
        selected_model = AUTO_MODEL_MAP[model]
    elif model and model.startswith("auto/"):
        selected_model = AUTO_MODEL_MAP.get(model, "deepseek/deepseek-chat")
    elif model and model.lower().startswith("omniroute/"):
        # Audit 23.11.2026: Alias VOR der Kette auflösen, damit Budget,
        # Telemetrie und OpenRouter-Schritt das echte Modell sehen. Die
        # Groq/OpenAI/Anthropic-Schritte wählen weiterhin ihre eigenen Modelle.
        selected_model = _resolve_openrouter_fallback_model(model)
    else:
        selected_model = model.strip() if (model and model not in ("free-forever", "default")) else "deepseek/deepseek-chat"

    # Zero-Egress & Privacy-Router Pre-Flight Gate + EU AI Act + DataClassifier
    from backend.llm_egress_guard import (
        ZeroEgressBlockedError,
        evaluate_and_gate_llm_dispatch,
        log_completed_llm_dispatch,
    )
    from backend.privacy_router import get_privacy_config

    try:
        from backend.compliance_engine import compliance_engine
        chk = compliance_engine.check_activation_allowed(agent_id, system_prompt=system_prompt or "")
        if not chk.get("allowed", True):
            return {
                "status": "blocked",
                "error": chk.get("reason") or "EU AI Act Guardrail verweigert Aktivierung.",
                "error_code": chk.get("error_code") or "COMPLIANCE_BLOCKED",
                "content": f"🛑 [COMPLIANCE GUARDRAIL BLOCK]: {chk.get('reason')}",
            }
    except Exception as cmp_err:
        # F-041: fail-closed statt Warnung + Weiterlauf des LLM-Dispatchs.
        logger.error(f"[Dispatcher] Compliance-Engine Pruefung fuer '{agent_id}' fehlgeschlagen — blockiert: {cmp_err}")
        return {
            "status": "blocked",
            "error": f"Compliance-Gate nicht verfuegbar: {cmp_err}",
            "error_code": "COMPLIANCE_GATE_UNAVAILABLE",
            "content": "🛑 [COMPLIANCE GUARDRAIL UNAVAILABLE]",
        }

    try:
        from backend.execution_routing_guard import classify_execution_layer
        _erg = classify_execution_layer((prompt or "")[:160], prompt or "")
        if _erg.get("layer") in ("deterministic_n8n", "deterministic_script"):
            # F-009: Klassifikation ist KEIN Hinweis mehr, sondern ein echter
            # 0-Token-Effekt. Deterministische Arbeit darf niemals durch ein
            # Sprachmodell halluziniert werden.
            _action = str(_erg.get("webhook_action") or "none")
            logger.info(
                "[ExecutionRoutingGuard] '%s' -> %s (%s, 0 Tokens)",
                agent_id, _erg.get("layer"), _action,
            )
            if _erg.get("requires_hitl"):
                return {
                    "status": "blocked",
                    "error_code": "DETERMINISTIC_HITL_REQUIRED",
                    "error": "Deterministische Ausfuehrung mit Aussenwirkung erfordert Freigabe.",
                    "content": "🛑 [HITL] Freigabe erforderlich — kein LLM-Dispatch.",
                    "engine": _erg.get("recommended_engine"),
                    "tokens": 0,
                }
            if _erg.get("layer") == "deterministic_n8n":
                _n8n = await trigger_n8n_execution(
                    parent_project_id=task_id or f"det-{agent_id}",
                    title=(prompt or "")[:120],
                    final_report_path="",
                    content=(prompt or "")[:2000],
                    target_action=_action,
                )
                # D12: nur bestaetigte Ausfuehrung ist Erfolg. `warning`/
                # `unconfirmed` darf nie als success mit Fake-Content enden.
                n8n_ok = _n8n.get("status") == "success"
                return {
                    "status": "success" if n8n_ok else "blocked",
                    "engine": "n8n",
                    "webhook_action": _action,
                    "tokens": 0,
                    "n8n_result": _n8n,
                    "error_code": None if n8n_ok else _n8n.get("error_code", "N8N_DELIVERY_UNCONFIRMED"),
                    "content": (
                        f"Deterministisch an n8n ausgefuehrt ({_action}, executionId={_n8n.get('execution_id', '')})."
                        if n8n_ok else f"n8n-Ausfuehrung nicht bestaetigt ({_action}) — HITL/Outbox erforderlich."
                    ),
                }
            return {
                "status": "blocked",
                "error_code": "DETERMINISTIC_SCRIPT_SCHEDULER_ONLY",
                "error": "Skriptläufe sind nur über den Scheduler/n8n zulässig — kein LLM-Dispatch.",
                "engine": _erg.get("recommended_engine"),
                "tokens": 0,
            }
    except Exception as exc:
        # F-049: keine stillen Swallower im Dispatch-Pfad.
        logger.debug("[Dispatcher] ExecutionRoutingGuard nicht verfuegbar: %s", exc)

    classified_cat = ""
    try:
        from backend.data_classifier import DataClassifier
        cls_res = DataClassifier.classify(prompt or "")
        if not cls_res.get("cloud_llm_allowed", True):
            classified_cat = "confidential"
    except Exception as cls_err:
        logger.warning(f"[Dispatcher] DataClassifier fehlgeschlagen: {cls_err}")

    try:
        preflight_gate = evaluate_and_gate_llm_dispatch(
            agent_id=agent_id,
            provider=prov_lower or "omniroute",
            model=selected_model,
            messages=messages,
            role=role,
            explicit_category=classified_cat,
        )
    except ZeroEgressBlockedError as ze_err:
        return {
            "status": "blocked",
            "error": str(ze_err),
            "error_code": ze_err.error_code,
            "content": f"🛑 [ZERO-EGRESS / PRIVACY-ROUTER HARD-BLOCK]: {ze_err}",
            "audit_event": ze_err.audit_event,
        }

    # Schutz gegen Datenleck: ALLE Kontext-Injektionen (spekulatives CRM/ERP,
    # Langzeitgedaechtnis, Core-Memory) duerfen nicht an externe Cloud-Modelle,
    # sobald sensibles lokales Routing aktiv ist. Vorher wurde nur prefetch_addon
    # entfernt — core_mem_addon und memory_context_addon blieben im Prompt.
    if (prefetch_addon or core_mem_addon or memory_context_addon) and not preflight_gate.get("routed_to_local"):
        try:
            p_cfg_chk = get_privacy_config()
            if bool(p_cfg_chk.get("block_crm_erp_prefetch_on_cloud", True)) and bool(p_cfg_chk.get("sensitive_local_routing", True)):
                full_system_prompt = f"Du bist {agent_name} (Rolle: {role}). {system_prompt}".strip()
                messages = [{"role": "system", "content": full_system_prompt}] + chat_history_turns + [
                    {"role": "user", "content": prompt},
                ]
        except Exception as priv_err:
            logger.error(f"[Dispatcher] Privacy-Config Pruefung fuer Kontext-Stripping fehlgeschlagen: {priv_err}")
            return {
                "status": "blocked",
                "error": "context_strip_unavailable",
                "error_code": "PRIVACY_CONTEXT_STRIP_FAILED",
                "content": "🛑 [PRIVACY]: Kontext konnte nicht vor Cloud-Hop bereinigt werden — Dispatch blockiert.",
            }

    async def _audited_post(http_client: httpx.AsyncClient, url: str, *, provider_id: str, model_id: str, headers: dict | None = None, json_body: dict | None = None, timeout: float | None = None):
        from backend.llm_egress_guard import (
            enforce_egress_firewall_for_url,
            sanitize_llm_endpoint,
            sanitize_outbound_llm_payload,
        )
        hop_gate = evaluate_and_gate_llm_dispatch(
            agent_id=agent_id,
            provider=provider_id,
            model=model_id,
            messages=messages,
            role=role,
            intended_url=url,
            explicit_category=classified_cat,
        )
        enforce_egress_firewall_for_url(url, agent_id=agent_id)
        _, _, ep_zone = sanitize_llm_endpoint(url)
        is_local_hop = (
            bool(hop_gate.get("routed_to_local"))
            or ep_zone == "LOCAL_ON_PREM"
            or (provider_id or "").strip().lower() in ("local", "ollama", "lmstudio", "vllm")
        )
        safe_body = sanitize_outbound_llm_payload(
            json_body,
            agent_id=agent_id,
            session_id=task_id or agent_id,
            is_local=is_local_hop,
        )
        active_trace_id = ""
        try:
            from backend.trace_context import child_span, current_trace_id, inject_headers
            with child_span():
                # D16/H2: NEUE Span-ID im traceparent, keine Self-Parent-Kante.
                headers = inject_headers(headers)
                active_trace_id = current_trace_id()
        except Exception as tr_exc:
            logger.warning("[Dispatcher] Trace-Injektion am LLM-Hop (%s) fehlgeschlagen: %s", provider_id, tr_exc)
        post_kwargs: dict[str, Any] = {"headers": headers, "json": safe_body}
        if timeout is not None:
            post_kwargs["timeout"] = timeout
        # W3: Fail-Fast für ausgefallene Provider statt Thundering Herd.
        from backend.provider_circuit_breaker import provider_breaker

        async def _audit_dispatch_blocked(status: int) -> None:
            # SECURITY.md: "Every executed and blocked LLM call is atomically recorded".
            # Circuit-Open und Netzwerkfehler blieben bisher ohne Audit-Block.
            await _audit_log_async(
                agent_id=agent_id,
                provider=provider_id,
                model=model_id,
                target_endpoint=url,
                http_status=status,
                data_category=hop_gate["data_category"],
                zero_egress_active=hop_gate["zero_egress_active"],
                task_id=task_id,
                trace_id=active_trace_id,
                extra={"effective_prompt_info": prompt_version_info} if prompt_version_info else None,
            )

        if not provider_breaker.allow(provider_id):
            await _audit_dispatch_blocked(0)
            raise RuntimeError(f"Provider '{provider_id}' ist circuit-open (Fail-Fast).")
        try:
            r = await http_client.post(url, **post_kwargs)
        except Exception:
            provider_breaker.record_failure(provider_id)
            await _audit_dispatch_blocked(0)
            await _provider_backoff(provider=provider_id)
            raise
        if r.status_code >= 500 or r.status_code == 429:
            provider_breaker.record_failure(provider_id)
            await _provider_backoff(r, provider=provider_id)
        else:
            provider_breaker.record_success(provider_id)
        await _audit_log_async(
            agent_id=agent_id,
            provider=provider_id,
            model=model_id,
            target_endpoint=url,
            http_status=r.status_code,
            data_category=hop_gate["data_category"],
            zero_egress_active=hop_gate["zero_egress_active"],
            task_id=task_id,
            trace_id=active_trace_id,
            extra={"effective_prompt_info": prompt_version_info} if prompt_version_info else None,
        )
        return r

    # 0. On-Premise Lokales LLM (erzwungen durch Privacy-Router / Zero-Egress oder explizit prov_lower == 'local')
    _local_requested = bool(preflight_gate.get("routed_to_local")) or prov_lower in ("local", "ollama", "lmstudio", "vllm")
    if _local_requested:
        p_cfg = get_privacy_config()
        base_local = str(preflight_gate.get("target_url") or p_cfg.get("local_llm_url", "http://127.0.0.1:11434/v1")).rstrip("/")
        local_ep = base_local if base_local.endswith("/chat/completions") else f"{base_local}/chat/completions"
        local_model = str(preflight_gate.get("model") or p_cfg.get("local_llm_model", "llama3.2"))
        try:
            client = _get_dispatcher_http_client()
            resp = await _audited_post(
                client,
                local_ep,
                provider_id="local",
                model_id=local_model,
                headers={"Content-Type": "application/json"},
                json_body={"model": local_model, "messages": messages, "max_tokens": 2048, "temperature": 0.3},
            )
            if resp.status_code == 200:
                content = parse_omniroute_response(resp.text)
                if content:
                    i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                    await _log_dispatcher_usage(agent_id, local_model, i_tok, o_tok, task_id)
                    return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": local_model, "provider": "local"}
            if preflight_gate.get("zero_egress_active") or _local_requested:
                return {
                    "status": "blocked",
                    "error_code": "LOCAL_LLM_HTTP_ERROR_HARD_BLOCK",
                    "error": f"Lokales Modell lieferte HTTP {resp.status_code}",
                    "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: Lokales Modell ({local_ep}) antwortete mit HTTP {resp.status_code} — kein Cloud-Fallback erlaubt.",
                }
        except ZeroEgressBlockedError as ze_err:
            return {
                "status": "blocked",
                "error": str(ze_err),
                "error_code": ze_err.error_code,
                "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}",
                "audit_event": ze_err.audit_event,
            }
        except Exception as loc_err:
            if preflight_gate.get("zero_egress_active") or _local_requested:
                ev = await _audit_log_async(
                    agent_id=agent_id,
                    provider="local",
                    model=local_model,
                    target_endpoint=local_ep,
                    http_status=0,
                    data_category=preflight_gate["data_category"],
                    zero_egress_active=True,
                    task_id=task_id,
                    extra={"effective_prompt_info": prompt_version_info} if prompt_version_info else None,
                )
                return _with_prompt_info({
                    "status": "blocked",
                    "error_code": "LOCAL_LLM_OFFLINE_HARD_BLOCK",
                    "error": str(loc_err),
                    "content": f"🛑 [PRIVACY-ROUTER HARD-BLOCK]: Lokales On-Premise-Modell ({local_ep}) ist nicht erreichbar ({loc_err}) — keine Daten verlassen das Haus.",
                    "audit_event": ev,
                })

    # Ein explizit lokales Routing darf NIEMALS still in die Cloud-Kette fallen
    # (Groq/OpenRouter/OmniRoute). Vorher war der Fallback nur bei
    # zero_egress_active gesperrt — bei reinem Privacy-Routing ging das durch.
    if _local_requested:
        ev = await _audit_log_async(
            agent_id=agent_id,
            provider="local",
            model=local_model if _local_requested else (model or ""),
            target_endpoint=local_ep if _local_requested else "",
            http_status=0,
            data_category=preflight_gate.get("data_category", classified_cat),
            zero_egress_active=True,
            task_id=task_id,
            extra={"effective_prompt_info": prompt_version_info} if prompt_version_info else None,
        )
        return _with_prompt_info({
            "status": "blocked",
            "error": "local_route_cloud_fallback_denied",
            "error_code": "LOCAL_ROUTE_CLOUD_FALLBACK_BLOCKED",
            "content": "🛑 [PRIVACY-ROUTER]: Lokal gerouteter Task darf nicht in die Cloud-Fallback-Kette fallen (fail-closed).",
            "audit_event": ev,
        })

    # 1. Spezifischer Provider: GROQ
    if prov_lower == "groq" and groq_api_key:
        try:
            g_model = selected_model if ("llama" in selected_model or "gemma" in selected_model or "mixtral" in selected_model) else "llama-3.3-70b-versatile"
            client = _get_dispatcher_http_client()
            if True:
                resp = await _audited_post(
                    client,
                    "https://api.groq.com/openai/v1/chat/completions",
                    provider_id="groq",
                    model_id=g_model,
                    headers={"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"},
                    json_body={"model": g_model, "messages": messages, "max_tokens": 1500, "temperature": 0.4},
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        await _log_dispatcher_usage(agent_id, g_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": g_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as e:
            logger.warning("[Dispatcher] Groq direct call failed: %s", e)

    # 2. Spezifischer Provider: OPENAI
    if prov_lower == "openai" and openai_api_key:
        try:
            o_model = selected_model if "gpt" in selected_model else "gpt-4o-mini"
            client = _get_dispatcher_http_client()
            if True:
                resp = await _audited_post(
                    client,
                    "https://api.openai.com/v1/chat/completions",
                    provider_id="openai",
                    model_id=o_model,
                    headers={"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"},
                    json_body={"model": o_model, "messages": messages, "max_tokens": 1500, "temperature": 0.4},
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        await _log_dispatcher_usage(agent_id, o_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": o_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as e:
            logger.warning("[Dispatcher] OpenAI direct call failed: %s", e)

    # 3. Spezifischer Provider: ANTHROPIC (mit Prompt-Caching für bis zu 90% Kostenreduktion)
    if prov_lower == "anthropic" and anthropic_api_key:
        try:
            a_model = selected_model if "claude" in selected_model else "claude-3-5-sonnet-20241022"
            client = _get_dispatcher_http_client()
            if True:
                resp = await _audited_post(
                    client,
                    "https://api.anthropic.com/v1/messages",
                    provider_id="anthropic",
                    model_id=a_model,
                    headers={
                        "x-api-key": anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "anthropic-beta": "prompt-caching-2024-07-31",
                        "Content-Type": "application/json"
                    },
                    json_body={
                        "model": a_model,
                        "system": [
                            {
                                "type": "text",
                                "text": static_system_prompt,
                                "cache_control": {"type": "ephemeral"}
                            },
                            *(
                                [{"type": "text", "text": dynamic_system_addon}]
                                if dynamic_system_addon
                                else []
                            ),
                        ],
                        "messages": chat_history_turns + [{"role": "user", "content": prompt}],
                        "max_tokens": 1500
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = "".join(
                        c.get("text", "")
                        for c in data.get("content", [])
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                    if content:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        await _log_dispatcher_usage(agent_id, a_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": a_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as e:
            logger.warning("[Dispatcher] Anthropic direct call failed: %s", e)

    # 4. OpenRouter Gateway (Universal für DeepSeek, Claude, Llama, Qwen, Gemini etc.)
    if openrouter_api_key and prov_lower != "omniroute":
        try:
            or_payload = {
                "model": selected_model,
                "messages": messages,
                "max_tokens": 4096,
                "temperature": 0.4
            }
            if pruned_tools:
                or_payload["tools"] = pruned_tools
            r_lvl = (reasoning_level or "medium").strip().lower()
            effort_map = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "max": "high"}
            if r_lvl == "off":
                or_payload["reasoning"] = {"exclude": True}
            elif r_lvl in effort_map:
                or_payload["reasoning"] = {"effort": effort_map[r_lvl]}

            client = _get_dispatcher_http_client()
            if True:
                resp = await _audited_post(
                    client,
                    "https://openrouter.ai/api/v1/chat/completions",
                    provider_id="openrouter",
                    model_id=selected_model,
                    headers={
                        "Authorization": f"Bearer {openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "ArchonOS"
                    },
                    json_body=or_payload,
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        await _log_dispatcher_usage(agent_id, selected_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": selected_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as e:
            logger.warning("[Dispatcher] OpenRouter call failed with model %s: %s", selected_model, e)

    # 5. Fallback: Groq Ultra-Fast API
    if groq_api_key:
        groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"]
        client = _get_dispatcher_http_client()
        for g_model in groq_models:
            if time.monotonic() >= chain_deadline:
                logger.error("[Dispatcher] Fallback-Kettendeadline erreicht — kein weiterer Groq-Hop.")
                break
            try:
                resp = await _audited_post(
                    client,
                    "https://api.groq.com/openai/v1/chat/completions",
                    provider_id="groq",
                    model_id=g_model,
                    headers={
                        "Authorization": f"Bearer {groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json_body={
                        "model": g_model,
                        "messages": messages,
                        "max_tokens": 1200,
                        "temperature": 0.5
                    },
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        await _log_dispatcher_usage(agent_id, g_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": g_model}
            except ZeroEgressBlockedError as ze_err:
                return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
            except Exception as e:
                # D07/MED (A7): kein stilles continue — Hop sichtbar quittieren,
                # Backoff und Kettendeadline pruefen (HopResult-Modell: DELEGATED).
                logger.warning("[Dispatcher] Groq-Hop %s fehlgeschlagen: %s", g_model, e)
                await _provider_backoff(response=getattr(e, "response", None), provider="groq")
                if time.monotonic() >= chain_deadline:
                    logger.error("[Dispatcher] Fallback-Kettendeadline nach Groq-Hop erreicht.")
                    break
                continue

    # 3. Tertiär: OmniRoute Gateway (Port 20128)
    omni_urls = [
        "http://omniroute:20128/v1/chat/completions",
        f"{OMNIROUTE_URL}/chat/completions"
    ]
    omni_model = model if (model and model != "free-forever") else "auto/best-coding"
    omni_payload = {
        "model": omni_model,
        "messages": messages
    }
    if pruned_tools:
        omni_payload["tools"] = pruned_tools

    client = _get_dispatcher_http_client()
    for omni_url in omni_urls:
        if time.monotonic() >= chain_deadline:
            logger.error("[Dispatcher] Fallback-Kettendeadline erreicht — kein weiterer OmniRoute-Hop.")
            break
        try:
            resp = await _audited_post(
                client,
                omni_url,
                provider_id="omniroute",
                model_id=omni_model,
                headers=(
                    {"Authorization": f"Bearer {OMNIROUTE_API_KEY}", "Content-Type": "application/json"}
                    if OMNIROUTE_API_KEY else {"Content-Type": "application/json"}
                ),
                json_body=omni_payload,
                timeout=timeout,
            )
            if resp.status_code == 200:
                content = parse_omniroute_response(resp.text)
                if content:
                    i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                    await _log_dispatcher_usage(agent_id, omni_model, i_tok, o_tok, task_id)
                    return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": omni_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as e:
            # D07/MED (A7): kein stilles continue — Hop sichtbar quittieren,
            # Backoff und Kettendeadline pruefen (HopResult-Modell: DELEGATED).
            logger.warning("[Dispatcher] OmniRoute-Hop %s fehlgeschlagen: %s", omni_url, e)
            await _provider_backoff(response=getattr(e, "response", None), provider="omniroute")
            if time.monotonic() >= chain_deadline:
                logger.error("[Dispatcher] Fallback-Kettendeadline nach OmniRoute-Hop erreicht.")
                break
            continue

    # 3b. Direkter OpenRouter-Fallback bei OmniRoute-Ausfall / Rate-Limit
    or_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        try:
            or_model = _resolve_openrouter_fallback_model(model)
            resp = await _audited_post(
                client,
                "https://openrouter.ai/api/v1/chat/completions",
                provider_id="openrouter",
                model_id=or_model,
                headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json"},
                json_body={"model": or_model, "messages": messages, "max_tokens": 4096},
                timeout=timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                if content:
                    i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                    await _log_dispatcher_usage(agent_id, or_model, i_tok, o_tok, task_id)
                    return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": or_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as or_err:
            logger.warning(f"[Dispatcher] OpenRouter-Dispatch fehlgeschlagen ({or_model}): {or_err}")

    # 3c. Lokaler Ollama-Fallback (falls OmniRoute offline & kein OpenRouter-Key konfiguriert)
    if not (preflight_gate.get("routed_to_local") or prov_lower in ("local", "ollama", "lmstudio", "vllm")):
        try:
            p_cfg_fb = get_privacy_config()
            fb_base = str(p_cfg_fb.get("local_llm_url") or "http://127.0.0.1:11434/v1").rstrip("/")
            fb_ep = fb_base if fb_base.endswith("/chat/completions") else f"{fb_base}/chat/completions"
            fb_model = str(p_cfg_fb.get("local_llm_model") or "llama3.2")
            fb_resp = await _audited_post(
                client,
                fb_ep,
                provider_id="ollama",
                model_id=fb_model,
                headers={"Content-Type": "application/json"},
                json_body={"model": fb_model, "messages": messages, "max_tokens": 2048, "temperature": 0.3},
                timeout=min(float(timeout or 15), 8.0),
            )
            if fb_resp.status_code == 200:
                fb_content = parse_omniroute_response(fb_resp.text)
                if fb_content:
                    i_tok, o_tok = _extract_tokens_usage(fb_resp.text, prompt, fb_content)
                    await _log_dispatcher_usage(agent_id, fb_model, i_tok, o_tok, task_id)
                    return {"status": "success", "content": fb_content, "input_tokens": i_tok, "output_tokens": o_tok, "model": fb_model, "provider": "ollama"}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as fb_err:
            logger.warning(f"[Dispatcher] Ollama-Fallback fehlgeschlagen ({fb_model}): {fb_err}")

    # 4. Direkte Container-Endpunkte
    direct_urls = [
        f"http://{agent_id}:8080/api/chat",
        f"http://{agent_id}:8000/api/run",
        f"http://{agent_id}:8080/v1/chat/completions"
    ]
    for url in direct_urls:
        if time.monotonic() >= chain_deadline:
            logger.error("[Dispatcher] Fallback-Kettendeadline erreicht — kein weiterer Container-Hop.")
            break
        try:
            resp = await _audited_post(
                client,
                url,
                provider_id="container",
                model_id=selected_model,
                json_body={"prompt": prompt, "messages": messages},
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                # H6: keine ungepruefte Container-Antwort als Agenten-Output
                # uebernehmen. Nur bekannte Inhaltsfelder, bereinigt wie im
                # anderen Container-Pfad (Z. 202).
                if not isinstance(data, dict):
                    data = {"content": data}
                raw_content = data.get("content") or data.get("output") or data.get("result")
                if not raw_content:
                    logger.warning("[Dispatcher] Container-Antwort ohne Inhalt: %s", str(data)[:200])
                    continue
                content = _clean_dispatch_output(raw_content)
                i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, str(content))
                await _log_dispatcher_usage(agent_id, selected_model, i_tok, o_tok, task_id)
                return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": selected_model}
        except ZeroEgressBlockedError as ze_err:
            return {"status": "blocked", "error": str(ze_err), "error_code": ze_err.error_code, "content": f"🛑 [ZERO-EGRESS HARD-BLOCK]: {ze_err}", "audit_event": ze_err.audit_event}
        except Exception as container_exc:
            # D07/MED (A7): kein stilles continue — Hop sichtbar quittieren,
            # Backoff und Kettendeadline pruefen (HopResult-Modell: DELEGATED).
            logger.warning("[Dispatcher] Container-Hop %s fehlgeschlagen: %s", url, container_exc)
            await _provider_backoff(response=getattr(container_exc, "response", None), provider="container")
            if time.monotonic() >= chain_deadline:
                logger.error("[Dispatcher] Fallback-Kettendeadline nach Container-Hop erreicht.")
                break
            continue

    # 5. Robuste Fehlerbehandlung (Keine Dummy-Bereitschaftsmeldung vortaeuschen)
    err_msg = f"[FEHLER: Kein Sprachmodell-Provider erreichbar fuer @{agent_id} ({agent_name}) mit Modell '{selected_model}']"
    logger.error("[DISPATCHER-ERROR] %s", err_msg)
    return _with_prompt_info({
        "status": "error",
        "content": err_msg,
        "error": "No LLM provider available",
        "error_code": "NO_LLM_PROVIDER_AVAILABLE",
    })

async def dispatch_to_external_agent(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "free-forever",
    timeout: int = 30,
    provider: str = "",
    reasoning_level: str = "medium",
    task_id: str = "",
) -> dict:
    """
    Haupt-Dispatcher: Routet Anfragen primär an den Container und fällt nahtlos auf OmniRoute (Port 20128) zurück.

    P0-1: ``task_id`` war in den Zeilen 1258/1269/1280 referenziert, aber nicht
    definiert — der Erfolgsfall der Container-Dispatches (hermes/odysseus/openclaw)
    endete deshalb in einem NameError.
    """
    if agent_id == "hermes":
        res = await dispatch_to_hermes(agent_name, prompt, timeout)
        if res.get("status") in ("success", "blocked"):
            if isinstance(res, dict) and res.get("status") == "success" and res.get("content"):
                res["content"] = _clean_dispatch_output(
                    res["content"],
                    session_id=task_id or agent_id,
                    is_local=(str(res.get("provider") or "").lower() == "local"),
                )
            return _with_prompt_info(res, _resolve_prompt_ref(agent_id, task_id, model))
    elif agent_id == "odysseus":
        res = await dispatch_to_odysseus(agent_name, prompt, timeout)
        if res.get("status") in ("success", "blocked"):
            if isinstance(res, dict) and res.get("status") == "success" and res.get("content"):
                res["content"] = _clean_dispatch_output(
                    res["content"],
                    session_id=task_id or agent_id,
                    is_local=(str(res.get("provider") or "").lower() == "local"),
                )
            return _with_prompt_info(res, _resolve_prompt_ref(agent_id, task_id, model))
    elif agent_id == "openclaw" or agent_id == "openclaw-docker":
        res = await dispatch_to_openclaw(agent_name, prompt, timeout)
        if res.get("status") in ("success", "blocked"):
            if isinstance(res, dict) and res.get("status") == "success" and res.get("content"):
                res["content"] = _clean_dispatch_output(
                    res["content"],
                    session_id=task_id or agent_id,
                    is_local=(str(res.get("provider") or "").lower() == "local"),
                )
            return _with_prompt_info(res, _resolve_prompt_ref(agent_id, task_id, model))
            
    # Falls der spezifische Container-Endpoint fehlschlägt oder ein anderer Agent gewählt wurde, OmniRoute Gateway nutzen!
    return await dispatch_to_omniroute_or_container(
        agent_id=agent_id,
        agent_name=agent_name,
        prompt=prompt,
        role=role,
        system_prompt=system_prompt,
        model=model,
        provider=provider,
        timeout=timeout,
        reasoning_level=reasoning_level,
        task_id=task_id,
    )

CATEGORIZED_FRAMEWORKS = {
    "1. Bisherige, Agile & Innovation": {
        "CLEAR-Model": "[METHODIK-FRAMEWORK: CLEAR-MODELL]\nDu wendest auf jede Fragestellung strikt das CLEAR-Analysemodell an. Strukturiere deine Denkweise und deine Ausgabe ausnahmslos in folgenden 5 Phasen:\n\n1. CONCISE (Prägnanz):\n- Reduziere die Problemstellung auf maximal 2-3 Kernsätze. Eliminiere Ablenkungen und Nebenschauplätze.\n\n2. LOGICAL (Logische Kausalität):\n- Baue eine lückenlose Argumentationskette auf (Wenn X, dann Y, weil Z). Decke Fehlschlüsse oder unbewiesene Annahmen auf.\n\n3. EXPLICIT (Eindeutigkeit):\n- Vermeide vage Begriffe. Benenne konkrete Zahlen, Methoden, Werkzeuge, Verantwortlichkeiten und eindeutige Handlungsoptionen.\n\n4. ADAPTIVE (Anpassungsfähigkeit):\n- Teste die Lösung gegen veränderte Rahmenbedingungen und Edge Cases. Zeige mindestens eine funktionale Alternative auf.\n\n5. REFLECTIVE (Selbstkritik):\n- Unterziehe dein eigenes Ergebnis einem Stresstest: Wo liegen Schwachstellen, Risiken oder blinde Flecken?\n\nAUSGABE-FORMAT:\nAntworte zwingend mit den Abschnitten:\n[C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective",
        "CREATE-Framework": "[METHODIK-FRAMEWORK: CREATE-FRAMEWORK]\nDu analysierst und löst die Aufgabe entlang der 6 Stufen der verhaltensökonomischen CREATE-Action-Funktion:\n\n1. C - Cue (Auslöser): Welches Signal oder Ereignis stößt das Problem/Verhalten an?\n2. R - Reaction (Intuitive Reaktion): Welche unmittelbare, kognitive Reaktion erfolgt (System 1)?\n3. E - Evaluation (Bewertung): Welche Vor- und Nachteile werden abgewogen (System 2)?\n4. A - Ability (Fähigkeit/Hürden): Ist die Umsetzung einfach genug? Wo liegen Reibungsverluste/Komplexität?\n5. T - Timing (Dringlichkeit): Warum muss die Handlung JETZT erfolgen?\n6. E - Execute (Ausführung): Wie sieht die konkrete finale Umsetzungsschleife aus?\n\nAUSGABE-FORMAT:\nGliedere deine Lösung sauber in die Abschnitte [C], [R], [E], [A], [T] und [E].",
        "Design Sprint (GV / Jake Knapp)": "[METHODIK-FRAMEWORK: 5-TAGE DESIGN SPRINT]\nSimuliere und durchlaufe den Design-Sprint-Prozess in 5 klaren Schritten:\n\n1. MAP (Verstehen & Kartieren): Definiere das langfristige Ziel, zeichne die Map des Problems und wähle den Fokusbereich.\n2. SKETCH (Lösungen skizzieren): Generiere verschiedene, konkurrierende Lösungsansätze im Detail.\n3. DECIDE (Entscheiden): Bewerte die Ansätze kritisch und wähle die stärkste Hypothese aus.\n4. PROTOTYPE (Fokussierter Prototyp): Erstelle eine konkrete, detaillierte Spezifikation/Skizze des kleinstmöglichen Testobjekts.\n5. TEST (Validierung): Definiere 3-5 konkrete Testfragen und Metriken zur Überprüfung der Lösung.\n\nAUSGABE-FORMAT:\nNutze die Abschnitte: ### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test",
        "Double Diamond (Design Council)": "[METHODIK-FRAMEWORK: DOUBLE DIAMOND]\nLöse das Problem durch den Wechsel von divergentem (öffnendem) und konvergentem (schließendem) Denken:\n\nDIAMOND 1: DAS RICHTIGE PROBLEM FINDEN\n1. Discover (Entdecken - Divergent): Exploriere das Problemfeld breit. Welche versteckten Aspekte und Perspektiven gibt es?\n2. Define (Definieren - Konvergent): Verdichte die Erkenntnisse auf die eine, entscheidende Problemstellung (Problem-Definition).\n\nDIAMOND 2: DIE RICHTIGE LÖSUNG ENTWERFEN\n3. Develop (Entwickeln - Divergent): Generiere vielfältige Lösungsmöglichkeiten ohne unmittelbare Bewertung.\n4. Deliver (Liefern - Konvergent): Wähle die beste Lösung, verfeinere sie und mache sie sofort einsatzbereit.\n\nAUSGABE-FORMAT:\nNutze die Abschnitte: [1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]",
        "Lean Startup (Eric Ries)": "[METHODIK-FRAMEWORK: LEAN STARTUP (BUILD-MEASURE-LEARN)]\nWende den empirischen Feedbackzyklus zur schnellen Hypothesenprüfung an:\n\n1. HYPOTHESE (Glaubenssatz): Welche unbewiesene Grundannahme muss wahr sein, damit das Vorhaben funktioniert?\n2. BUILD (MVP): Entwirf das Minimum Viable Product mit der geringsten Komplexität, um die Hypothese zu testen.\n3. MEASURE (Messen): Definiere konkrete, nicht-manipulierbare Kennzahlen (Actionable Metrics statt Vanity Metrics).\n4. LEARN (Lernen & Pivot/Persevere): Analysiere das Ergebnis: Soll das Konzept beibehalten (Persevere) oder angepasst (Pivot) werden?\n\nAUSGABE-FORMAT:\nStrukturiere deine Antwort in: 1. Hypothese | 2. Build (MVP) | 3. Measure (Metriken) | 4. Learn (Pivot/Persevere)",
        "OKRs (Objectives and Key Results)": "[METHODIK-FRAMEWORK: OBJECTIVES AND KEY RESULTS]\nÜbersetze die Aufgabenstellung in ein operationalisierbares OKR-Set:\n\n1. OBJECTIVE (Qualitatives Ziel):\n- Formuliere 1-2 ambitionierte, inspirierende und einprägsame Ziele (Wo wollen wir hin?).\n\n2. KEY RESULTS (Quantitative Messergebnisse):\n- Definiere pro Objective 3 konkrete, messbare Key Results (Wie messen wir den Erfolg?).\n- Format: \"Steigerung/Reduzierung von X auf Y bis Z\".\n\n3. INITIATIVES (Konkrete Maßnahmen):\n- Liste die spezifischen Aufgaben und Projekte auf, die notwendig sind, um die Key Results zu erreichen.\n\nAUSGABE-FORMAT:\nVerwende die Struktur: ### Objective | ### Key Results (1-3) | ### Initiativen & Action Items",
        "STEEPLE / PESTEL": "[METHODIK-FRAMEWORK: STEEPLE / PESTEL ANALYSE]\nAnalysiere das externe Umfeld der Problemstellung systematisch nach folgenden 7 Makro-Faktoren:\n\n1. Social (Soziokulturell): Demografie, Verhalten, Werte.\n2. Technological (Technologisch): Innovationen, Automatisierung, Tech-Hürden.\n3. Economic (Ökonomisch): Kosten, Inflation, Marktstrukturen.\n4. Environmental (Ökologisch): Nachhaltigkeit, Ressourcen, Umweltauflagen.\n5. Political (Politisch): Regulierungen, Stabilität, Vorgaben.\n6. Legal (Rechtlich): DSGVO, Haftung, Gesetze.\n7. Ethical (Ethisch): Fairness, Transparenz, KI-Ethik.\n\nAUSGABE-FORMAT:\nFühre für jeden Buchstaben [S], [T], [E], [E], [P], [L], [E] eine kurze, prägnante Risiko- und Chancenbewertung durch.",
        "Steffi Kieffer Boardroom": "[METHODIK-FRAMEWORK: AI BOARDROOM DEBATE]\nFühre eine mehrperspektivische Boardroom-Debatte durch, in der unterschiedliche Spezialisten-Perspektiven aufeinandertreffen:\n\n1. CHARMING MODERATOR (Einleitung): Rahmenbedingung setzen und Problem präzise formulieren.\n2. SKEPTIKER / RISIKOANALYSATOR: Hinterfragt Annahmen, deckt Sicherheits- und Umsetzungsrisiken auf.\n3. STRATEGISCHER OPTIMIST / INNOVATOR: Fokus auf Chancen, Effizienzsteigerung und Zukunftsfähigkeit.\n4. PRAGMATISCHER IMPLEMENTIERER: Fokus auf technische Machbarkeit, Ressourcen und unmittelbaren Code/Schritte.\n5. CHAIRMAN SYNTHESIS (Fazit): Wiegt die Argumente gegeneinander ab und liefert eine klare, unmissverständliche Entscheidung.\n\nAUSGABE-FORMAT:\nZeige den Dialog der Rollen gefolgt von der hervorgehobenen [CHAIRMAN SYNTHESIS].",
        "Jobs-to-be-Done (JTBD / Clayton Christensen)": "[METHODIK-FRAMEWORK: JOBS-TO-BE-DONE (JTBD)]\nAnalysiere die Aufgabenstellung nicht über Produktfeatures oder Demografie, sondern über den konkreten Fortschritt (\"Job\"), den der Nutzer in einer bestimmten Situation erreichen will:\n\n1. KONTEXT & AUSLÖSER (Struggling Moment): In welcher konkreten Situation stößt der bisherige Ansatz an seine Grenzen?\n2. FUNKTIONALER, EMOTIONALER & SOZIALER JOB:\n   - Funktional: Welche messbare Kernaufgabe muss erledigt werden?\n   - Emotional/Sozial: Welche Unsicherheit, Reibung oder welches Risiko soll eliminiert werden?\n3. VIER KRÄFTE DES WECHSELS (Forces of Progress):\n   - Push (Schmerz des Status Quo) & Pull (Anziehung der neuen Lösung) vs. Anxiety (Angst vorm Neuen) & Habit (Trägheit/Gewohnheit).\n4. OUTCOME-DRIVEN LÖSUNG: Entwirf die Lösung so, dass der Job schneller, verlässlicher und mit minimaler Reibung erledigt wird.\n\nAUSGABE-FORMAT:\n[1. Struggling Moment] | [2. Job-Dimensionen] | [3. Kräfte-Bilanz (Push/Pull vs. Anxiety/Habit)] | [4. Zielgenaue Lösung]",
        "Blue Ocean Strategy (ERRC-Grid)": "[METHODIK-FRAMEWORK: BLUE OCEAN STRATEGY & ERRC-GRID]\nÜberwinde ruinösen Preis- und Feature-Wettbewerb (Red Ocean) und schaffe unbestrittenen neuen Marktraum (Blue Ocean) über Value Innovation:\n\n1. RED OCEAN IST-ANALYSE: Auf welchen überfüllten Faktoren konkurriert die Branche heute zu hohen Kosten?\n2. ERRC-VIER-AKTIONEN-FORMAT:\n   - ELIMINATE (Eliminieren): Welche branchenüblichen Faktoren stiften keinen echten Nutzen mehr und werden komplett gestrichen?\n   - REDUCE (Reduzieren): Welche Standards sind überdimensioniert und werden deutlich unter Branchenniveau gesenkt?\n   - RAISE (Steigern): Welche entscheidenden Werttreiber werden weit über den Branchenstandard gehoben?\n   - CREATE (Kreieren): Welche völlig neuen Nutzenfaktoren werden erstmals geschaffen?\n3. NEUE WERTKURVE: Zeige, wie gleichzeitig Kostensenkung UND Nutzensteigerung erreicht werden.\n\nAUSGABE-FORMAT:\n### Red-Ocean-Status | ### ERRC-Matrix (Eliminate / Reduce / Raise / Create) | ### Neue Wertkurve & Differenzierung",
    },
    "2. Ursachenanalyse, Logik & Problem-Solving": {
        "5-Why-Methode": "[METHODIK-FRAMEWORK: 5-WHY URSACHENANALYSE]\nDringe durch kaskadierendes Hinterfragen zur tatsächlichen Wurzel des Problems (Root Cause) vor:\n\n- Problem-Statement: [Symptom präzise beschreiben]\n- Warum 1: Warum tritt dieses Symptom auf? -> Antwort 1\n- Warum 2: Warum passiert Antwort 1? -> Antwort 2\n- Warum 3: Warum passiert Antwort 2? -> Antwort 3\n- Warum 4: Warum passiert Antwort 3? -> Antwort 4\n- Warum 5: Warum passiert Antwort 4? -> WURZELURSACHE (Root Cause)\n\nKORREKTURMAßNAHME:\nDefiniere eine dauerhafte Lösung, die exakt an der Wurzelursache ansetzt (nicht am Symptom!).\n\nAUSGABE-FORMAT:\nListe die 5 Why-Schritte untereinander auf und schließe mit: ### Wurzelursache & ### Gegenmaßnahme.",
        "Cynefin-Framework (Dave Snowden)": "[METHODIK-FRAMEWORK: CYNEFIN DOMÄNEN-ANALYSE]\nOrdnest die Problemstellung zuerst der richtigen System-Domäne zu und wendest das dazugehörige Handlungsmuster an:\n\n1. DOMÄNEN-DIAGNOSE: In welcher Domäne befindet sich das Problem?\n   - Offensichtlich (Simple): Ursache-Wirkung klar -> Erkennen - Kategorisieren - Reagieren.\n   - Kompliziert (Complicated): Expertenwissen nötig -> Erkennen - Analysieren - Reagieren.\n   - Komplex (Complex): Keine klare Ursache-Wirkung -> Probieren - Erkennen - Reagieren.\n   - Chaotisch (Chaotic): Mitten im Brand -> Handeln - Erkennen - Reagieren.\n\n2. HANDLUNGSSTRATEGIE: Leite die exakten Schritte basierend auf der diagnostizierten Domäne ab.\n\nAUSGABE-FORMAT:\n### Domänen-Zuordnung | ### Begründung | ### Handlungsstrategie",
        "First Principles Thinking": "[METHODIK-FRAMEWORK: FIRST PRINCIPLES THINKING]\nZerlege das Problem in seine fundamentalsten Wahrheitselemente und baue von Grund auf eine neue Lösung:\n\n1. DEKONSTRUKTION (Annahmen streichen):\n   - Welche Analogien, Gewohnheiten und Branchen-Mythen verdecken das Problem? Lösche alle \"Das haben wir schon immer so gemacht\"-Annahmen.\n\n2. FUNDAMENTALE WAHRHEITEN (Physik/Fakten):\n   - Was sind die unumstößlichen, mathematischen, technischen oder logischen Fakten des Problems?\n\n3. REKONSTRUKTION (Neuaufbau):\n   - Baue aus diesen Grundbausteinen eine völlig neue, optimierte Lösung auf, ohne bestehende Denkmuster zu kopieren.\n\nAUSGABE-FORMAT:\nStrukturiere in: [1. Bekannte Annahmen verwerfen] | [2. Fundamentale Fakten] | [3. Neuaufbau aus Grundprinzipien]",
        "Ishikawa-Diagramm (6M)": "[METHODIK-FRAMEWORK: ISHIKAWA (URSACHEN-WIRKUNGS-DIAGRAMM)]\nUntersuche die Fehlerursachen systematisch anhand der 6M-Kategorien:\n\n1. Mensch: Unwissenheit, Überlastung, Schnittstellenfehler.\n2. Maschine/Tooling: Hardware, Server, Bug in der KI/Software.\n3. Methode: Mangelhafte Prozesse, falsche Logik, fehlende Vorgaben.\n4. Material/Daten: Mangelhafte Datenqualität, fehlerhafte Prompts/Input.\n5. Milieu/Umfeld: Systemumgebung, Zeitdruck, Netzwerklatenzen.\n6. Messung: Falsche Metriken, fehlendes Monitoring, ungenaue Logs.\n\nHAUPTURSACHE & LÖSUNG:\nIdentifiziere die wahrscheinlichste Hauptursache über alle 6 Achsen hinweg.\n\nAUSGABE-FORMAT:\nGliedere die Analyse in die 6M-Blöcke und schließe mit: ### Hauptfehlerquelle.",
        "Porter's Five Forces": "[METHODIK-FRAMEWORK: PORTER'S 5 FORCES BRANCHENANALYSE]\nBewerte die Wettbewerbsintensität und Attraktivität der Problemstellung/des Marktes:\n\n1. Rivalität unter bestehenden Wettbewerbern (Hoch/Mittel/Gering)\n2. Bedrohung durch neue Anbieter (Eintrittsbarrieren)\n3. Verhandlungsmacht der Lieferanten (Tech-Provider, APIs, Datenquellen)\n4. Verhandlungsmacht der Abnehmer (Kunden, Nutzer)\n5. Bedrohung durch Ersatzprodukte (Substitutionsrisiko durch andere Tech)\n\nSTRATEGISCHE EMPFEHLUNG: Wie kann das System/Produkt eine uneinnehmbare Festung (Moat) aufbauen?\n\nAUSGABE-FORMAT:\nAnalysiere die 5 Kräfte einzeln und schließe mit: ### Strategische Positionierung & Moat.",
        "SWOT-Analyse": "[METHODIK-FRAMEWORK: STRATEGISCHE SWOT-ANALYSE]\nFühre eine strukturierte Matrix-Analyse der internen und externen Faktoren durch:\n\nINTERNE FAKTOREN:\n- Strengths (Stärken): Was sind die Alleinstellungsmerkmale und Kernkompetenzen?\n- Weaknesses (Schwachstellen): Wo liegen Engpässe, Wissenslücken oder Ineffizienzen?\n\nEXTERNE FAKTOREN:\n- Opportunities (Chancen): Welche Markttrends, Automatisierungen oder Lücken lassen sich nutzen?\n- Threats (Risiken): Welche externen Gefahren (Regulierung, Konkurrenz, Tech-Shifts) drohen?\n\nSTRATEGISCHE KRUZUNG (TOWS):\nLeite mindestens 2 konkrete SO-Strategien (Stärken nutzen um Chancen zu ergreifen) und ST-Strategien (Stärken nutzen um Risiken abzuwehren) ab.\n\nAUSGABE-FORMAT:\nVerwende die Abschnitte: [Stärken] | [Schwächen] | [Chancen] | [Risiken] | [TOWS-Strategieableitung]",
        "MECE & Minto-Pyramide (Barbara Minto)": "[METHODIK-FRAMEWORK: MECE & MINTO-PYRAMIDEN-PRINZIP]\nStrukturiere Problemanalyse und Entscheidungskommunikation nach höchster Management-Beratungslogik (McKinsey / Barbara Minto):\n\n1. GOVERNING THOUGHT (Answer First): Beginne sofort mit der präzisen Kernaussage / Handlungsempfehlung in 1–2 Sätzen.\n2. MECE-ZERLEGUNG (Mutually Exclusive, Collectively Exhaustive):\n   - Zerlege das Problem in überschneidungsfreie (keine Redundanz) und erschöpfende (keine Lücken) Hauptstränge.\n3. SCQA-RAHMEN (Situation – Complication – Question – Answer): Verankere die Logik im geschäftlichen Engpass.\n4. BEWEISKETTE & DATENBELEGE: Untermauere jeden Hauptstrang mit verifizierbaren Zahlen, Fakten und Kausalbelegen.\n\nAUSGABE-FORMAT:\n### Executive Answer First | ### SCQA-Kontext | ### MECE-Analysebaum (Strang 1–3) | ### Zahlen- & Maßnahmenfazit",
        "Kepner-Tregoe Problem Analysis (KT)": "[METHODIK-FRAMEWORK: KEPNER-TREGOE PROBLEMANALYSE (IST / IST-NICHT)]\nIsoliere komplexe technische oder operative Störungsursachen durch scharfe Kontrastierung von IST und IST-NICHT:\n\n1. PROBLEMDEFINITION: Präzise Abweichung zwischen Soll-Standard und tatsächlicher Ist-Leistung.\n2. VIER-ACHSEN-SPEZIFIKATION (IST vs. IST-NICHT):\n   - WAS ist betroffen vs. WAS könnte betroffen sein, ist es aber NICHT?\n   - WO tritt es auf vs. WO tritt es NICHT auf?\n   - WANN trat es erstmals/wiederkehrend auf vs. WANN NICHT?\n   - WELCHES AUSMAß / welcher Trend zeigt sich?\n3. UNTERSCHIEDE & VERÄNDERUNGEN: Was unterscheidet das IST vom IST-NICHT und welche Änderung ging voraus?\n4. HYPOTHESENTEST: Prüfe mögliche Ursachen streng gegen alle IST- und IST-NICHT-Fakten bis zur einzig widerspruchsfreien Ursache.\n\nAUSGABE-FORMAT:\n[1. Abweichungs-Statement] | [2. IST / IST-NICHT Matrix] | [3. Kritische Änderungen] | [4. Verifizierte Ursache & Fix]",
        "Fault Tree Analysis (FTA / Fehlerbaumanalyse)": "[METHODIK-FRAMEWORK: FAULT TREE ANALYSIS (FTA / IEC 61025)]\nUntersuche kritische Systemausfälle deduktiv Top-Down über boolesche Logikgatter (UND / ODER):\n\n1. TOP-EVENT: Definiere das unerwünschte kritische Ausfallereignis an der Spitze des Fehlerbaums.\n2. LOGISCHE GATTER-ZERLEGUNG:\n   - ODER-Gatter (Single Point of Failure): Bereits EIN Teilfehler löst den Gesamtausfall aus.\n   - UND-Gatter (Redundanzbarriere): Mehrere unabhängige Fehler müssen gleichzeitig eintreten.\n3. MINIMAL CUT SETS (Minimale Schnittmengen): Identifiziere die kürzesten Fehlerpfade, die direkt zum Top-Event führen.\n4. ARCHITEKTUR-HÄRTUNG: Ersetze kritische ODER-Pfade gezielt durch unabhängige UND-Barrieren (Redundanz, Failover, Validierung).\n\nAUSGABE-FORMAT:\n### Top-Event | ### Fehlerbaum (UND/ODER-Pfade) | ### Single Points of Failure (Minimal Cut Sets) | ### Redundanz-Maßnahmen",
    },
    "3. Operations, Lean & Qualität": {
        "DMAIC (Six Sigma)": "[METHODIK-FRAMEWORK: DMAIC (SIX SIGMA PROZESSOPTIMIERUNG)]\nSichere die Qualität und eliminiere Prozessabweichungen strikt in 5 Phasen:\n\n1. DEFINE (Definieren): Was ist das Problem? Wer ist der Kunde? Was ist der Qualitätsanspruch (CTQ)?\n2. MEASURE (Messen): Wie sieht der aktuelle Ist-Zustand aus? Welche Daten/Metriken liegen vor?\n3. ANALYZE (Analysieren): Was sind die Kernursachen für Streuung und Fehler im Prozess?\n4. IMPROVE (Verbessern): Welche Maßnahmen beseitigen die Fehlerursachen vollständig?\n5. CONTROL (Steuern): Wie wird der neue Standard dauerhaft überwacht (KPIs, Alerts)?\n\nAUSGABE-FORMAT:\nStrukturiere deine Antwort in die 5 Abschnitte: [Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control].",
        "PDCA-Zyklus (Demingkreis)": "[METHODIK-FRAMEWORK: PDCA CONTINUOUS IMPROVEMENT]\nDurchlaufe den kontinuierlichen Verbesserungsprozess:\n\n1. PLAN (Planen): Analysiere die Ist-Situation, definiere das Ziel und erstelle einen konkreten Umsetzungsplan.\n2. DO (Umsetzen): Führe den Plan testweise oder im kleinen Rahmen aus (Prototyping/Pilotierung).\n3. CHECK (Überprüfen): Vergleiche die Ergebnisse der Umsetzung direkt mit den ursprünglichen Zielen. Wo gab es Abweichungen?\n4. ACT (Agieren): Standardisiere die erfolgreiche Lösung oder passe den Plan an und starte den Zyklus neu.\n\nAUSGABE-FORMAT:\nVerwende die Abschnitte: ### Plan | ### Do | ### Check | ### Act",
        "Theory of Constraints (TOC)": "[METHODIK-FRAMEWORK: THEORY OF CONSTRAINTS (ENGPASS-THEORIE)]\nMaximiere den Durchsatz des gesamten Systems durch Fokussierung auf den schwächsten Punkt (Bottleneck):\n\n1. IDENTIFIZIEREN: Welches ist der eine, primäre Engpass, der den Gesamtdurchsatz limitiert?\n2. AUSNUTZEN: Wie kann dieser Engpass ohne große Investitionen maximal effizient ausgelastet werden?\n3. UNTERORDNEN: Richte alle anderen Prozesse und Schritte im System strikt nach dem Takt des Engpasses aus.\n4. BESEITIGEN: Investiere Ressourcen, um die Kapazität des Engpasses drastisch zu erweitern.\n5. NIEMALS AUFHÖREN: Sobald der Engpass gehoben ist, suche sofort den NÄCHSTEN Engpass (Vermeidung von Trägheit).\n\nAUSGABE-FORMAT:\nGliedere in: [1. Primärer Engpass] | [2. Ausnutzung] | [3. Unterordnung] | [4. Behebung]",
        "Value Stream Mapping (VSM / Wertstromanalyse)": "[METHODIK-FRAMEWORK: VALUE STREAM MAPPING (WERTSTROMANALYSE)]\nDurchleuchte den End-to-End-Fluss von Materialien, Daten oder Aufgaben vom Auslöser bis zum Kundenergebnis und eliminiere Verschwendung (7 Muda):\n\n1. IST-WERTSTROM: Kartiere alle Prozessschritte inkl. Bearbeitungszeit (Value-Add Time), Liege-/Wartezeit (Lead Time) und Fehlerrate (% Complete & Accurate).\n2. PROCESS CYCLE EFFICIENCY (PCE): Berechne das Verhältnis aus echter Wertschöpfungszeit zur Gesamtdurchlaufzeit.\n3. VERSCHWENDUNGS-DIAGNOSE (TIMWOODS): Decke Wartezeiten, Überproduktion, Medienbrüche, Nacharbeit und unnötige Übergaben auf.\n4. SOLL-WERTSTROM (Future State): Entwirf den verschlankten Zielprozess mit Pull-Steuerung, Automatisierung und messbarer Durchlaufzeitverkürzung.\n\nAUSGABE-FORMAT:\n[1. Ist-Wertstrom & Durchlaufzeit] | [2. Identifizierte Verschwendung (Muda)] | [3. Soll-Wertstrom] | [4. Effizienzgewinn]",
        "A3 Problem-Solving (Toyota Production System)": "[METHODIK-FRAMEWORK: TOYOTA A3 PROBLEM-SOLVING REPORT]\nVerdichte Problemlösung, Ursachenanalyse und Umsetzungssteuerung auf ein diszipliniertes Toyota-A3-Entscheidungsblatt:\n\n1. HINTERGRUND & BUSINESS-RELEVANZ: Warum ist dieses Thema jetzt geschäftskritisch?\n2. IST-ZUSTAND (Gemba-Fakten): Quantifizierte Ist-Kennzahlen ohne Vermutungen.\n3. ZIELZUSTAND (Smart Target): Messbarer Soll-Wert bis zu einem klaren Stichtag.\n4. WURZELURSACHEN-ANALYSE: Kausaler Nachweis der Kernursache hinter der Lücke.\n5. GEGENMAßNAHMEN & UMSETZUNGSPLAN: Konkrete Maßnahmen mit Verantwortlichen, Terminen und erwartetem Effekt.\n6. ERFOLGSKONTROLLE & STANDARDISIERUNG: Prüfmetrik und Verankerung im Standardbetrieb (SOP).\n\nAUSGABE-FORMAT:\n### 1. Hintergrund | ### 2. Ist-Daten | ### 3. Zielwert | ### 4. Wurzelursache | ### 5. Maßnahmenplan | ### 6. Erfolgsprüfung & SOP",
        "SIPOC & RACI Prozess-Governance": "[METHODIK-FRAMEWORK: SIPOC & RACI PROZESS-ARCHITEKTUR]\nSchaffe lückenlose Schnittstellen- und Verantwortungsklarheit für komplexe Betriebs- und Projektprozesse:\n\n1. SIPOC-ABGRENZUNG:\n   - Suppliers (Zulieferer/Quellen) -> Inputs (Eingangsdaten/-güter mit Qualitätskriterien) -> Process (5–7 Kernschritte) -> Outputs (Artefakte) -> Customers (Abnehmer & SLA-Anforderungen).\n2. RACI-VERANTWORTUNGSMATRIX:\n   - Responsible (Durchführungsverantwortlich), Accountable (Genau EINE Person mit Endverantwortung/Freigabe!), Consulted (Fachexpertise vorab), Informed (Information über Ergebnis).\n3. SCHNITTSTELLEN-GUARDRAILS: Eliminiere geteilte Accountabilities und unklare Übergabepunkte.\n\nAUSGABE-FORMAT:\n### SIPOC-Übersicht | ### RACI-Matrix (Tabellarisch) | ### Übergabe- & SLA-Regeln",
    },
    "4. Strategie, Priorisierung & Change": {
        "Eisenhower-Matrix": "[METHODIK-FRAMEWORK: EISENHOWER PRIORISIERUNGS-MATRIX]\nKategorisiere alle anstehenden Teilaufgaben strikt nach Wichtigkeit und Dringlichkeit:\n\n1. DO FIRST (Wichtig & Dringend): Sofort selbst erledigen. Exakte Ausführungsschritte festlegen.\n2. SCHEDULE (Wichtig & Nicht Dringend): Terminieren und strategisch durchdenken (Hauptfokus für Langzeiterfolg).\n3. DELEGATE (Nicht Wichtig & Dringend): An spezialisierte Sub-Agenten oder automatisierte Skripte auslagern.\n4. ELIMINATE (Nicht Wichtig & Nicht Dringend): Komplett streichen und als Ablenkung identifizieren.\n\nAUSGABE-FORMAT:\nPräsentiere die Aufgaben aufgeteilt in die 4 Quadranten: [Quadrant I: Do] | [Quadrant II: Schedule] | [Quadrant III: Delegate] | [Quadrant IV: Eliminate]",
        "Kano-Modell": "[METHODIK-FRAMEWORK: KANO MERKMAL-ANALYSE]\nKlassifiziere die Systemfunktionen/Features nach ihrer Auswirkung auf die Nutzerzufriedenheit:\n\n1. BASIS-MERKMALE (Must-Haves): Selbstverständliche Funktionen. Fehlen sie, herrscht große Unzufriedenheit.\n2. LEISTUNGS-MERKMALE (Linear): Je mehr/schneller vorhanden, desto höher die Zufriedenheit (z.B. Geschwindigkeit, Token-Preis).\n3. BEGEISTERUNGS-MERKMALE (Delighters): Unerwartete Features, die einen Aha-Effekt auslösen und echte Alleinstellung schaffen.\n4. UNERWÜNSCHTE/INERHEBLICHE MERKMALE: Features, die keinen Mehrwert stiften oder den Nutzer verwirren.\n\nAUSGABE-FORMAT:\nKategorisiere die Lösungselemente in: [Must-Haves] | [Performance-Features] | [Begeisterungs-Features]",
        "Kotter 8-Stufen-Modell": "[METHODIK-FRAMEWORK: KOTTER CHANGE MANAGEMENT]\nStrukturiere die Transformation / Systemumstellung entlang der 8 Stufen des Change Managements:\n\n1. Dringlichkeit erzeugen (Urgency)\n2. Führungskoalition aufbauen (Guiding Coalition)\n3. Vision und Strategie entwickeln (Vision)\n4. Die Vision kommunizieren (Communication)\n5. Hindernisse beseitigen (Empowerment)\n6. Schnelle Erfolge erzielen (Short-Term Wins)\n7. Erfolge konsolidieren und weitere Veränderungen anstoßen (Consolidation)\n8. Neue Ansätze in der Kultur verankern (Institutionalization)\n\nAUSGABE-FORMAT:\nLiefere für jede der 8 Stufen eine konkrete Handlungsanweisung für das System/Team.",
        "McKinsey 7S": "[METHODIK-FRAMEWORK: MCKINSEY 7S ORGANISATIONSANALYSE]\nAnalysiere die ganzheitliche Abstimmung des Systems über 7 Dimensionen:\n\nHARD S (Harte Faktoren):\n1. Strategy (Strategie): Ausrichtung und Wettbewerbsvorteil.\n2. Structure (Struktur): Systemarchitektur und Modulaufbau.\n3. Systems (Systeme): Prozesse, Pipelines und Workflows.\n\nSOFT S (Weiche Faktoren):\n4. Shared Values (Unternehmenskultur/Leitbild): Grundwerte der Lösung.\n5. Style (Führungsstil/Modell-Verhalten): Wie agiert das System?\n6. Staff (Personal/Agenten-Ressourcen): Fähigkeiten der eingesetzten LLMs.\n7. Skills (Fähigkeiten/Tools): Verfügbare APIs und operationaler Funktionsumfang.\n\nAUSGABE-FORMAT:\nGliedere in [Hard S] und [Soft S] und zeige Diskrepanzen zwischen den Dimensionen auf.",
        "NABC-Methode": "[METHODIK-FRAMEWORK: NABC PITCH & VALUE PROPOSITION]\nFormuliere die Lösung als prägnanten, überzeugenden Wertantrag (Pitch):\n\n1. NEED (Bedürfnis): Welches konkrete, schmerzhafte Problem des Nutzers/Systems wird adressiert?\n2. APPROACH (Ansatz): Wie sieht die spezifische, innovative Lösung aus?\n3. BENEFIT (Nutzen): Welchen quantifizierbaren Mehrwert/Ersparnis bringt der Ansatz?\n4. COMPETITION (Wettbewerb/Alternativen): Warum ist dieser Ansatz besser als bestehende Alternativen?\n\nAUSGABE-FORMAT:\nGliedere die Antwort präzise in: [Need] | [Approach] | [Benefit] | [Competition].",
        "RICE-Priorisierung": "[METHODIK-FRAMEWORK: RICE PRIORISIERUNGS-SCORE]\nBewerte und ranke Backlog-Items, Features oder Handlungsoptionen quantitativ nach der RICE-Formel:\nRICE Score = (Reach x Impact x Confidence) / Effort\n\n1. REACH (Reichweite): Wie viele Nutzer/Prozesse/Kunden sind pro Quartal betroffen? (Konkrete absolute Zahl).\n2. IMPACT (Auswirkung): Welchen Effekt hat das Item auf den Nutzer/das Ziel?\n   - 3 = Massiv, 2 = Hoch, 1 = Mittel, 0.5 = Gering, 0.25 = Minimal.\n3. CONFIDENCE (Zuversicht): Wie verlässlich sind unsere Daten/Annahmen?\n   - 100% = Hohe Evidenz / Datenbasis, 80% = Mittlere Datenlage, 50% = Schätzung / Bauchgefühl.\n4. EFFORT (Aufwand): Wie viele Personenmonate oder Entwicklungszeitfenster werden benötigt? (1 = 1 Monat / 1 Sprint).\n\nSCORE-BERECHNUNG:\nBerechne für jede Option den numerischen RICE-Score und erstelle eine absteigende Prioritätenliste mit klarer Umsetzungsbegründung.\n\nAUSGABE-FORMAT:\nTabellarische Matrix: Option | Reach | Impact | Confidence | Effort | RICE Score | Empfehlung",
        "Make-or-Buy / TCO-Scoring": "[METHODIK-FRAMEWORK: MAKE-OR-BUY & TCO-ANALYSE]\nFühre eine strukturierte Bewertung für Build vs. Buy vs. Partner durch, insbesondere für KI-, Software- und Infrastruktur-Entscheidungen:\n\n1. KERNKOMPETENZ & DIFFERENZIERUNG:\n- Gehört das Modul zur Kern-IP und strategischen Differenzierung (Build) oder ist es Standard-Commodity (Buy)?\n\n2. TOTAL COST OF OWNERSHIP (TCO) ÜBER 36 MONATE:\n- Build: Initiale Entwicklungskosten + laufende Wartung, Security-Patches, Hosting/Hardware, Opportunitätskosten des Dev-Teams.\n- Buy: SaaS-/API-Lizenzkosten, Vendor-Lock-in-Risiko, Integrationsaufwand, Token-Preiserhöhungsrisiko.\n- Partner: Integrations- und Betreuungskosten, Abhängigkeit von Drittdienstleistern.\n\n3. ZEITHORIZONT & TIME-TO-MARKET:\n- Wie viele Wochen/Monate Vorsprung verschafft die Buy-Option gegenüber einer Eigenentwicklung?\n\n4. DATENSCHUTZ, SOUVERÄNITÄT & RUNTIME-KONTROLLE:\n- Verbleiben sensible Kundendaten auf eigener Hardware (On-Prem / Selbst-Hosting) oder fließen Daten an externe US-Cloud-Hyperscaler?\n\nDECISION MATRIX & VERDIKT:\nFälle ein unmissverständliches Verdikt: Build, Buy oder Partner mit Meilensteinplan für die nächsten 90 Tage.\n\nAUSGABE-FORMAT:\n### Differenzierung & IP | ### TCO-3-Jahres-Vergleich | ### Risiko & Souveränität | ### Klares Verdikt & Roadmap",
        "Ansoff-Matrix & Wachstumsvektoren": "[METHODIK-FRAMEWORK: ANSOFF WACHSTUMS- & RISIKOMATRIX]\nBewerte strategische Wachstumsoptionen systematisch entlang von Produkt- und Marktdimension inklusive Risikoprofil:\n\n1. MARKTDURCHDRINGUNG (Bestehendes Produkt / Bestehender Markt — geringstes Risiko): Marktanteilsgewinn, Frequenz, Retention, Preispunkt.\n2. MARKTENTWICKLUNG (Bestehendes Produkt / Neuer Markt): Geografische Expansion, neue Kundensegmente oder Vertriebskanäle.\n3. PRODUKTENTWICKLUNG (Neues Produkt / Bestehender Markt): Upsell-Module, nächste Produktgeneration für bestehende Kundenbasis.\n4. DIVERSIFIKATION (Neues Produkt / Neuer Markt — höchstes Risiko): Horizontale, vertikale oder laterale Expansion.\n5. KAPITALALLOKATION: Empfiehl die optimale Sequenzierung nach Kapitalrendite und Umsetzungsrisiko.\n\nAUSGABE-FORMAT:\n[1. Marktdurchdringung] | [2. Marktentwicklung] | [3. Produktentwicklung] | [4. Diversifikation] | [Priorisierte Wachstumssequenz]",
        "BCG Growth-Share Portfolio-Matrix": "[METHODIK-FRAMEWORK: BCG PORTFOLIO- & KAPITALALLOKATIONS-MATRIX]\nSteuere Produktlinien, Projekte oder Geschäftseinheiten nach Marktwachstum, relativem Marktanteil und Cashflow-Beitrag:\n\n1. CASH COWS (Hoher Anteil / Reifer Markt): Cashflow-Generatoren — Effizienz sichern, Überschüsse abschöpfen, Überinvestition vermeiden.\n2. STARS (Hoher Anteil / Hohes Wachstum): Zukunftsträger — gezielt skalieren, um Marktführerschaft zu verteidigen.\n3. QUESTION MARKS (Niedriger Anteil / Hohes Wachstum): Selektive Wette (Double-Down bis zum Star) oder konsequenter Ausstieg.\n4. POOR DOGS (Niedriger Anteil / Niedriges Wachstum): Gebundenes Kapital und Management-Aufmerksamkeit freisetzen (Restrukturieren / Abstoßen).\n\nAUSGABE-FORMAT:\n### Portfolio-Einordnung (Cows / Stars / Question Marks / Dogs) | ### Cashflow-Umverteilung | ### Konkrete Stop/Invest-Entscheidung",
        "VRIO-Framework (Barney / Competitive Moat)": "[METHODIK-FRAMEWORK: VRIO WETTBEWERBSVORTEILS-PRÜFUNG]\nPrüfe Ressourcen, Technologie, Daten und Fähigkeiten schonungslos auf echte, dauerhafte Verteidigbarkeit (Moat):\n\n1. VALUABLE (Wertstiftend): Erhöht die Ressource nachweislich Zahlungsbereitschaft oder senkt sie strukturell die Stückkosten?\n2. RARE (Selten): Besitzen nur wenige Wettbewerber Zugang zu dieser Fähigkeit oder Datenbasis?\n3. INIMITABLE (Schwer imitierbar): Ist das Nachbauen durch Netzwerkeffekte, Wechselkosten, Patente, Regulierung oder Historie teuer/langwierig?\n4. ORGANIZED (Organisatorisch verankert): Ist das Unternehmen operativ aufgestellt, diesen Wert voll abzuschöpfen?\n\nKLASSIFIZIERUNG: Wettbewerbsnachteil -> Parität -> Temporärer Vorteil -> Nachhaltiger Burggraben (Sustained Moat).\n\nAUSGABE-FORMAT:\nTabellarisches VRIO-Audit je Kernressource + ### Moat-Ausbaustrategie",
    },
    "5. Kognitive Entzerrung & Kritisches Denken": {
        "Ladder of Inference (Chris Argyris)": "[METHODIK-FRAMEWORK: LADDER OF INFERENCE]\nLege deine kognitive Schlussfolgerungskette von den Rohdaten bis zur Handlung transparent offen, um Fehlschlüsse zu vermeiden:\n\n1. ROHDATEN: Welche beobachtbaren Fakten/Codezeilen wurden ausgewählt?\n2. GEFILTERTE DATEN: Welche Daten wurden ignoriert oder hervorgehoben?\n3. BEDEUTUNG (Sinngebung): Welche Bedeutung wird den Daten zugeschrieben?\n4. ANNAHMEN: Welche unbewiesenen Vorannahmen fließen ein?\n5. SCHLUSSFOLGERUNG: Welche logische Konsequenz wird gezogen?\n6. HANDLUNG: Welche konkrete Aktion folgt daraus?\n\nAUSGABE-FORMAT:\nZeige die Leiter von unten nach oben: [Sprosse 1: Daten] -> [Sprosse 2: Selektion] -> [Sprosse 3: Annahmen] -> [Sprosse 4: Aktion]",
        "Pre-Mortem Analyse (Gary Klein)": "[METHODIK-FRAMEWORK: PRE-MORTEM ANALYSE]\nSetze voraus, dass das geplante Projekt/der Code in 12 Monaten krisenhaft und vollständig gescheitert ist. Nimm diesen Misserfolg als mathematische Tatsache hin und arbeite rückwärts:\n\n1. GESCHICHTE DES SCHEITERNS:\n- Beschreibe das genaue Szenario des Totalschadens. Was ist schiefgegangen?\n\n2. URSACHEN-BRAINSTORMING:\n- Liste alle verdeckten Risiken, schlechten Annahmen, Zeitfresser und technischen Schwachstellen auf, die zu diesem Scheitern geführt haben.\n\n3. PRE-EMPTIVE MAßNAHMEN:\n- Leite sofortige, präventive Korrekturmaßnahmen ab, um jeden einzelnen identifizierten Scheiter-Grund HEUTE noch zu verhindern.\n\nAUSGABE-FORMAT:\nStrukturiere in: [1. Das Scheiter-Szenario] | [2. Identifizierte Todesursachen] | [3. Präventive Schutzmaßnahmen]",
        "Red Teaming / Adversarial Analysis": "[METHODIK-FRAMEWORK: RED TEAMING / ADVERSARIAL ATTACK]\nNimm die Rolle eines aggressiven, externen Angreifers / Gegners ein und zerlege das vorgelegte Konzept:\n\n1. ATTACK VECTORS (Angriffsflächen):\n- Wo liegen Schwachstellen in der Logik, Sicherheit, Performance oder Usability?\n\n2. EXPLOITATION (Ausnutzung):\n- Wie könnte ein Gegner, Edge Case oder Systemfehler diese Lücke maximal ausnutzen?\n\n3. DEFENSIVE HARDENING (Härtung):\n- Wie muss das Konzept/der Code sofort umgebaut werden, um diesen Angriff vollkommen unmöglich zu machen?\n\nAUSGABE-FORMAT:\n### Angriffsvektoren | ### Ausnutzungs-Szenario | ### Härtungs-Maßnahmen (Blue Team)",
        "Six Thinking Hats (Edward de Bono)": "[METHODIK-FRAMEWORK: SIX THINKING HATS]\nAnalysiere die Aufgabenstellung konsequent aus 6 klar getrennten Denkperspektiven:\n\n1. WEIßER HUT (Fakten): Welche reinen Daten, Fakten und Informationen liegen vor? Was fehlt?\n2. ROTER HUT (Emotionen): Welche intuitiven Bedenken, Ängste oder Bauchgefühle gibt es?\n3. SCHWARZER HUT (Kritik): Wo liegen die Gefahren, Risiken, Schwachstellen und Hürden?\n4. GELBER HUT (Optimismus): Was sind die Best-Case-Chancen, Vorteile und der Nutzen?\n5. GRÜNER HUT (Kreativität): Welche unkonventionellen, alternativen Wege gibt es noch?\n6. BLAUER HUT (Prozess): Wie sieht die finale Synthese und der nächste Prozessschritt aus?\n\nAUSGABE-FORMAT:\nAntworte zwingend geordnet nach den 6 Hüten: ⚪ Weiß | 🔴 Rot | 🖤 Schwarz | 🟡 Gelb | 🟢 Grün | 🔵 Blau",
        "Game-Theoretic Mechanism Design": "[METHODIK-FRAMEWORK: SPIELTHEORIE & MECHANISM DESIGN]\nAnalysiere die Situation als spieltheoretisches System aus strategischen Akteuren, Anreizen und Informationsasymmetrien:\n\n1. SPIELER & ZIELE (Akteure):\n- Wer sind die handelnden Parteien (z.B. Käufer, Verkäufer, Wettbewerber, Nutzer, Agenten)? Welche Nutzenfunktionen maximieren sie?\n\n2. ANREIZSTRUKTUREN & FEHLANREIZE (Incentive Alignment):\n- Wo existieren Moral Hazard, Principal-Agent-Konflikte oder adverse Selektion? Welche Handlungen werden belohnt, welche bestraft?\n\n3. GLEICHGEWICHTSANALYSE (Nash-Gleichgewicht):\n- In welchem stabilen Zustand endet das System, wenn jeder Akteur eigennützig und rational seine beste Antwort wählt?\n\n4. MECHANISM DESIGN & AUKTIONSTHEORIE:\n- Wie müssen Regeln, Auszahlungsmatrizen, Verträge oder Bietverfahren (z.B. Vickrey-Auktion, Stufenrabatte, Earn-Outs) gestaltet werden, damit ehrliches Verhalten und Kooperation die dominante Strategie werden?\n\nAUSGABE-FORMAT:\n### Akteure & Nutzenfunktionen | ### Fehlanreize & Asymmetrien | ### Nash-Gleichgewicht | ### Designter Mechanismus (Dominante Strategie)",
        "Bayesian Updating & Superforecasting (Tetlock)": "[METHODIK-FRAMEWORK: BAYESIAN UPDATING & SUPERFORECASTING]\nErsetze Bauchgefühl und binäres Schwarz-Weiß-Denken durch kalibrierte Wahrscheinlichkeiten nach Bayes und Philip Tetlock:\n\n1. OUTSIDE VIEW (Basisrate / Prior $P(H)$): Wie oft gelingen vergleichbare Vorhaben statistisch in der Referenzklasse wirklich (ohne Insider-Optimismus)?\n2. INSIDE VIEW & EVIDENZGEWICHTUNG (Likelihood Ratio): Welche spezifischen positiven und negativen Signale verschieben die Basisrate nach oben oder unten?\n3. POSTERIOR-WAHRSCHEINLICHKEIT ($P(H|E)$): Beziffere die aktualisierte Erfolgswahrscheinlichkeit als explizites Prozent-Intervall.\n4. FALSIFIKATIONS-MEILENSTEINE: Welche konkreten Messdaten in 30/90 Tagen würden deine Wahrscheinlichkeit um $\\ge 20$ Prozentpunkte senken oder erhöhen?\n\nAUSGABE-FORMAT:\n[1. Referenzklasse & Prior %] | [2. Evidenz-Signale (+/-)] | [3. Kalibrierter Posterior %] | [4. Update-Trigger]",
        "Inversion Thinking (Charlie Munger / Jacobi)": "[METHODIK-FRAMEWORK: INVERSION THINKING (\"INVERT, ALWAYS INVERT\")]\nLöse komplexe Probleme vorwärts UND rückwärts nach Charlie Munger und Carl Gustav Jacobi: Statt nur zu fragen \"Wie erreichen wir Brillanz?\", frage zuerst \"Wie garantieren wir katastrophales Scheitern?\" und eliminiere diese Pfade:\n\n1. VORWÄRTS-ZIEL: Was ist das angestrebte positive Ergebnis?\n2. ANTI-ZIEL (Garantierter Misserfolg): Welche 5–7 Handlungen, Architekturentscheidungen oder Unterlassungen führen mit Sicherheit in das Desaster?\n3. SYSTEMATISCHE VERMEIDUNGS-BARRIEREN: Baue harte technische, vertragliche oder prozessuale Sperren gegen jeden einzelnen Misserfolgs-Pfad ein.\n4. ASYMMETRISCHER RESTPFAD: Formuliere die robuste Strategie, die übrig bleibt, wenn alle Dummheiten ausgeschlossen sind.\n\nAUSGABE-FORMAT:\n### 1. Vorwärts-Ziel | ### 2. Rezept für garantiertes Scheitern | ### 3. Harte Schutz-Barrieren | ### 4. Robuste Gewinnstrategie",
        "Steelmanning & Hegelian Dialectic (Thesis-Antithesis-Synthesis)": "[METHODIK-FRAMEWORK: STEELMANNING & HEGELSCHE DIALEKTIK]\nÜberwinde oberflächliche Kompromisse und Strohmann-Argumente, indem du widerstreitende Positionen in ihrer jeweils stärkstmöglichen Form gegeneinanderstellst:\n\n1. THESE (Stärkstes Argument für Option A): Formuliere Position A mit den besten Daten, Prämissen und ökonomischen Hebeln.\n2. ANTITHESE ALS STEELMAN (Stärkstes Gegenargument / Option B): Baue die Gegenposition NICHT als schwachen Strohmann auf, sondern mache sie so intelligent, faktenstark und unwiderlegbar wie möglich.\n3. KERNKONFLIKT DER PRÄMISSEN: An exakt welcher Annahme oder Zielgewichtung scheiden sich These und Antithese?\n4. DIALEKTISCHE SYNTHESE: Konstruiere eine Lösung höherer Ordnung, die die berechtigten Stärken beider Seiten bewahrt und den Widerspruch auflöst.\n\nAUSGABE-FORMAT:\n[1. These (Maximalform)] | [2. Steelman-Antithese] | [3. Prämissen-Bruchlinie] | [4. Überlegene Synthese]",
    },
    "6. Systemdenken & Komplexität": {
        "Causal Loop Diagrams (System Dynamics)": "[METHODIK-FRAMEWORK: CAUSAL LOOP DIAGRAMS]\nAnalysiere die Dynamik des Systems über Rückkopplungsschleifen:\n\n1. SYSTEM-ELEMENTE: Identifiziere die Schlüsselvariablen des Problems.\n2. VERSTÄRKENDE SCHLEIFEN (Reinforcing Loops - R):\n- Welche Teufelskreise oder Positiv-Spiralen verstärken sich selbst? (Wenn A steigt, steigt B, was A weiter erhöht).\n3. AUSGLEICHENDE SCHLEIFEN (Balancing Loops - B):\n- Welche Dämpfer oder natürlichen Grenzen begrenzen das Wachstum/die Leistung?\n4. ZEITVERZÖGERUNGEN (Delays): Wo treten verzögerte Wirkungen auf, die zu Fehlanpassungen führen?\n\nAUSGABE-FORMAT:\nStrukturiere in: [Variablen] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Zeitverzögerungen]",
        "Iceberg Model (Systems Thinking)": "[METHODIK-FRAMEWORK: DAS EISBERG-MODELL]\nDringe unter die Oberfläche des sichtbaren Problems vor:\n\n1. EREIGNISSE (Sichtbare Spitze): Was ist gerade passiert? (Das unmittelbare Symptom).\n2. MUSTER & TRENDS (Unter der Wasserlinie): Was passiert immer wieder? Welche Historie zeigt sich?\n3. SYSTEMSTRUKTUREN: Wie sind die Prozesse, Werkzeuge und Regeln aufgebaut, die dieses Muster erzeugen?\n4. MENTALE MODELLE (Fundament): Welche Grundhaltungen, Überzeugungen oder Design-Philosophien halten die Struktur aufrecht?\n\nAUSGABE-FORMAT:\nAnalysiere von oben nach unten: [1. Ereignis] -> [2. Muster] -> [3. Struktur] -> [4. Mentales Modell]",
        "Second-Order Thinking (Howard Marks)": "[METHODIK-FRAMEWORK: SECOND-ORDER THINKING]\nDenke über die unmittelbaren Konsequenzen einer Entscheidung hinaus:\n\n1. EFFEKTE 1. ORDNUNG (Unmittelbar & Offensichtlich):\n- Was ist die direkte Folge der Handlung/des Codes? (Fast immer positiv gedacht).\n\n2. EFFEKTE 2. ORDNUNG (Mittelbar & Nebenwirkungen):\n- Was passiert in 3-6 Monaten als direkte Konsequenz der Effekte 1. Ordnung? Welche unbeabsichtigten Nebenwirkungen entstehen?\n\n3. EFFEKTE 3. ORDNUNG (Langfristige System-Shifts):\n- Wie verändert diese Entscheidung das Gesamtsystem, die Kosten oder das Nutzerverhalten langfristig?\n\nAUSGABE-FORMAT:\nGliedere in: [1st Order: Direkt] | [2nd Order: Nebenwirkungen] | [3rd Order: Systemwirkung]",
        "Wardley Mapping": "[METHODIK-FRAMEWORK: WARDLEY MAPPING]\nKartiere die Komponenten des Systems entlang der Wertschöpfungskette und ihrer Evolution:\n\n1. NORTSTERN / USER NEED: Was braucht der Nutzer an oberster Stelle?\n2. WERTSCHÖPFUNGSKETTE: Welches Modul baut auf welchem auf? (Sichtbar -> Unsichtbar).\n3. EVOLUTIONSSTUFEN DER KOMPONENTEN:\n   - Genesis (Unbekannt, Experimentell)\n   - Custom-Built (Maßgeschneidert, Eigenbau)\n   - Product/Rental (Standard-Produkt/SaaS)\n   - Commodity/Utility (Infrastruktur, Standard-Strom)\n\nSTRATEGISCHER ZUG: Welche Eigenbauten sollten durch Commodities ersetzt werden, um Ressourcen freizusetzen?\n\nAUSGABE-FORMAT:\n### Wertschöpfungskette | ### Evolutions-Mapping | ### Strategischer Hebel",
        "Donella Meadows 12 Leverage Points": "[METHODIK-FRAMEWORK: DONELLA MEADOWS LEVERAGE POINTS (SYSTEMHEBEL)]\nVerschwende keine Ressourcen an schwachen Parameter-Korrekturen, sondern identifiziere die tiefsten Eingriffspunkte im System (von schwach nach hochwirksam):\n\n1. PARAMETER & PUFFER (Schwacher Hebel): Bloßes Drehen an Zahlen, Budgets, Fristen oder Kapazitätsgrenzen.\n2. INFORMATIONSFLÜSSE & FEEDBACK-GESCHWINDIGKEIT (Mittlerer Hebel): Wer sieht welche Konsequenzen in Echtzeit? Wo fehlen direkte Rückkopplungen?\n3. SYSTEMREGELN & ANREIZE (Starker Hebel): Wer hat Entscheidungsbefugnis, wie werden Gewinne/Strafen verteilt, welche Constraints gelten?\n4. SYSTEMZIEL & PARADIGMA (Höchster Hebel): Auf welche oberste Zielgröße ist das Gesamtsystem ausgerichtet?\n\nAUSGABE-FORMAT:\n### Diagnose schwacher Parameter-Eingriffe | ### Informations- & Regel-Hebel | ### Höchster Systemhebel & Umbauplan",
        "Viable System Model (VSM / Stafford Beer)": "[METHODIK-FRAMEWORK: VIABLE SYSTEM MODEL (KYBERNETISCHE ORGANISATION)]\nDiagnostiziere und gestalte komplexe Organisationen oder Multi-Agenten-Systeme anhand der 5 lebensnotwendigen Subsysteme nach Stafford Beer:\n\n1. SYSTEM 1 (Operative Einheiten): Wertschöpfende Facheinheiten mit notwendiger lokaler Autonomie.\n2. SYSTEM 2 (Koordination & Anti-Oszillation): Gemeinsame Standards, Protokolle und Konfliktdämpfung zwischen den Einheiten.\n3. SYSTEM 3 & 3* (Operative Steuerung & Sporadisches Audit): Ressourcenallokation, Synergien und direkter Stichproben-Durchgriff.\n4. SYSTEM 4 (Strategische Umweltaufklärung / Zukunft): Radar für Marktveränderungen, Technologiebrüche und externe Risiken.\n5. SYSTEM 5 (Normative Identität & oberste Balance): Ausgleich zwischen heutiger Effizienz (System 3) und Zukunftsfähigkeit (System 4).\n\nAUSGABE-FORMAT:\n[System 1: Betrieb] | [System 2: Koordination] | [System 3/3*: Steuerung & Audit] | [System 4: Zukunft] | [System 5: Governance-Verdikt]",
    },
    "7. Zukunftsforschung, Risiko & Resilienz": {
        "Antifragilitäts-Analyse (Nassim Taleb)": "[METHODIK-FRAMEWORK: TALEB ANTIFRAGILITÄT]\nKlassifiziere und optimiere das System nach seiner Reaktion auf Stress, Fehler und Volatilität:\n\n1. FRAGIL (Bricht bei Stress): Wo führen Fehler zu fatalen Kettenreaktionen oder Abstürzen?\n2. ROBUST (Hält Stress stand): Wo bleibt das System unverändert stabil, lernt aber nicht dazu?\n3. ANTIFRAGIL (Gewinnt durch Stress): Wie kann das System so gebaut werden, dass es aus Fehlern, Ausnahmen und Stress Dazulernt und BESSER wird?\n\nREFACTORING: Wandle fragile Systemkomponenten in antifragile Schleifen um (z. B. automatisches Reinforcement-Learning aus Error-Logs).\n\nAUSGABE-FORMAT:\n### Fragile Schwachstellen | ### Robuste Kernzonen | ### Antifragile Optimierungen",
        "FMEA (Failure Mode and Effects Analysis)": "[METHODIK-FRAMEWORK: FMEA RISIKO-QUANTIFIZIERUNG]\nBewerte Systemfehler quantitativ nach der Risikoprioritätszahl (RPN = A x B x E):\n\n1. FEHLERMÖGLICHKEIT: Was kann an Komponente X schiefgehen?\n2. AUFTRETENSWAHRSCHEINLICHKEIT (A: 1-10): Wie oft kommt der Fehler vor?\n3. BEDEUTUNG / SCHWERE (B: 1-10): Wie gravierend ist der Schaden für den Nutzer?\n4. ENTDECKUNGSSICHERHEIT (E: 1-10): Wie schwer ist der Fehler vor dem Deployment zu erkennen? (10 = unbemerkt).\n5. RPN-SCORE (A x B x E): Werte über 100 erfordern zwingend eine Überarbeitung.\n\nKORREKTUR-ACTION: Behebe vorrangig Fehler mit den höchsten RPN-Scores.\n\nAUSGABE-FORMAT:\nTabellarische Liste: Component | Failure Mode | A | B | E | RPN | Massnahme",
        "OODA-Loop (John Boyd)": "[METHODIK-FRAMEWORK: OODA-LOOP ECHTZEIT-STEUERUNG]\nDurchlaufe den schnellen Orientierungs- und Entscheidungszirkel:\n\n1. OBSERVE (Beobachten): Erfasse alle verfügbaren Systemzustände, Logs, API-Feedbacks und Inputs.\n2. ORIENT (Orientieren): Filtere die Daten durch aktuelle Kontextfenster, KI-Rollen und Erfahrungen. Zerschlage falsche Wahrnehmungen.\n3. DECIDE (Entscheiden): Wähle schnell die effektivste Handlungsoption aus (Vermeide Analysis Paralysis).\n4. ACT (Handeln): Führe den Code/die Aktion sofort aus und speise das Ergebnis direkt zurück in Schritt 1.\n\nAUSGABE-FORMAT:\n[Observe] -> [Orient] -> [Decide] -> [Act]",
        "Scenario Planning (Shell-Methode)": "[METHODIK-FRAMEWORK: SZENARIO-PLANUNG]\nEntwickle 3 plausible, voneinander unabhängige Zukunftsszenarien für das Vorhaben:\n\n1. SZENARIO A: \"BEST CASE / GROWTH\" (Optimale Bedingungen)\n- Wie sieht die Lösung aus und wie skaliert sie unter idealen Voraussetzungen?\n\n2. SZENARIO B: \"STAGFLATION / ADVERSARIAL\" (Ressourcenknappheit / Hohe Fehlerquote)\n- Wie schlägt sich das System bei extrem hohen Kosten, Ausfällen oder Latenzen?\n\n3. SZENARIO C: \"BLACK SWAN / DISRUPTION\" (Unerwarteter Systemwechsel)\n- Was passiert, wenn sich die Grundannahmen schlagartig ändern?\n\nSTRATEGIE: Leite Maßnahmen ab, die in ALLEN 3 Szenarien funktionieren (No-Regret-Moves).\n\nAUSGABE-FORMAT:\n[Szenario A] | [Szenario B] | [Szenario C] | [No-Regret-Maßnahmen]",
        "Monte-Carlo & Expected Value Entscheidungsbaum": "[METHODIK-FRAMEWORK: MONTE-CARLO & EXPECTED-VALUE ENTSCHEIDUNGSANALYSE]\nBewerte Entscheidungen unter Unsicherheit nicht mit trügerischen Punktschätzungen, sondern über Wahrscheinlichkeitsverteilungen und Erwartungswerte:\n\n1. UNSICHERHEITSTREIBER & SPANNBREITEN: Definiere für die 3–5 kritischen Variablen P10 (Pessimistisch), P50 (Median) und P90 (Optimistisch).\n2. ENTSCHEIDUNGSBAUM & EXPECTED VALUE (EV):\n   - Berechne $EV = \\sum p_i \\cdot \\text{Payoff}_i$ für jede Handlungsalternative.\n3. TAIL-RISK & RUIN-SCHUTZ (Value at Risk): Prüfe das untere 5-%-Perzentil — führt der Worst Case zu existenziellem Schaden / Liquiditätsbruch (Kelly-Kriterium)?\n4. REALOPTIONEN & STUFEN-COMMITMENT: Wie lässt sich die Investition in kleine Meilensteine schneiden, um Informationen zu kaufen, bevor das volle Kapital gebunden wird?\n\nAUSGABE-FORMAT:\n### Variablen-Spannen (P10/P50/P90) | ### Expected-Value-Vergleich | ### Downside-/Ruin-Check | ### Gestufte Options-Entscheidung",
        "Swiss Cheese Model (James Reason / Defense-in-Depth)": "[METHODIK-FRAMEWORK: SWISS CHEESE MODEL & DEFENSE-IN-DEPTH]\nEntwirf mehrschichtige Sicherheits- und Qualitätsbarrieren, damit einzelne menschliche oder technische Fehler niemals bis zum Gesamtschaden durchschlagen:\n\n1. GEFAHRENQUELLE & SCHADENSEREIGNIS: Welcher kritische Fehler (Security Breach, Fehlüberweisung, Produktionsausfall, Rechtsverstoß) muss verhindert werden?\n2. UNABHÄNGIGE ABWEHRSCHICHTEN (Cheese Slices):\n   - Schicht 1: Prävention durch Design / Architektur (Fehler unmöglich machen, Poka-Yoke).\n   - Schicht 2: Automatisierte Validierung / Guardrails / Berechtigungszäune.\n   - Schicht 3: Echtzeit-Detektion, Anomalie-Monitoring & Circuit-Breaker.\n   - Schicht 4: Eindämmung (Blast-Radius-Isolation, Rollback, Backup).\n3. LATENTE LÖCHER VERSCHIEBEN: Stelle sicher, dass keine zwei Schichten dieselbe gemeinsame Fehlerursache (Common-Mode Failure) teilen.\n\nAUSGABE-FORMAT:\n### Bedrohungsvektor | ### Abwehrschichten 1–4 & ihre aktuellen Löcher | ### Entkoppelte Härtungs-Architektur",
    },
}

CATEGORIZED_FRAMEWORKS_EN = {
    "1. Agile, Design & Innovation": {
        "CLEAR Model": "[METHODOLOGY FRAMEWORK: CLEAR MODEL]\nApply the CLEAR analytical model strictly to the problem statement. Structure your reasoning and output across all 5 phases without exception:\n\n1. CONCISE:\n- Distill the core problem down to 2–3 razor-sharp sentences. Strip away distractions and secondary noise.\n\n2. LOGICAL:\n- Build an unbroken causal argument chain (If X, then Y, because Z). Expose logical fallacies and unverified assumptions.\n\n3. EXPLICIT:\n- Ban vague abstractions. Specify exact metrics, methods, tools, owners, timelines, and unambiguous decision options.\n\n4. ADAPTIVE:\n- Stress-test the proposed solution against shifting boundary conditions and edge cases. Provide at least one viable fallback alternative.\n\n5. REFLECTIVE:\n- Subject your own conclusion to adversarial self-critique: Where do residual vulnerabilities, risks, or blind spots remain?\n\nOUTPUT FORMAT:\nStructure your response strictly with:\n[C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective",
        "CREATE Behavioral Framework": "[METHODOLOGY FRAMEWORK: CREATE ACTION FUNNEL]\nAnalyze and solve the challenge across the 6 behavioral-economics stages of the CREATE Action Funnel:\n\n1. C - Cue (Trigger): What external or internal signal initiates the behavior or workflow?\n2. R - Reaction (Intuitive System-1 Response): What immediate emotional or cognitive gut reaction occurs?\n3. E - Evaluation (Conscious System-2 Cost-Benefit): How are benefits weighed against costs and risks?\n4. A - Ability (Friction & Capability): Does the actor have the tools and low-friction path to act immediately?\n5. T - Timing (Urgency): Why must action happen NOW rather than later?\n6. E - Execute (Action & Feedback Loop): How is execution completed and reinforced?\n\nOUTPUT FORMAT:\nOrganize your deliverable cleanly into [C], [R], [E], [A], [T], and [E].",
        "Design Sprint (GV / Jake Knapp)": "[METHODOLOGY FRAMEWORK: 5-PHASE DESIGN SPRINT]\nExecute the Google Ventures Design Sprint methodology across 5 structured phases:\n\n1. MAP: Define the long-term target outcome, map the end-to-end actor journey, and isolate the critical sprint focus.\n2. SKETCH: Generate competing, concrete solution architectures in high resolution.\n3. DECIDE: Evaluate competing sketches against impact/feasibility criteria and commit to the strongest testable hypothesis.\n4. PROTOTYPE: Specify the minimum realistic artifact needed to validate the core assumption rapidly.\n5. TEST: Define 3–5 falsifiable validation questions and pass/fail metrics with real users or stakeholders.\n\nOUTPUT FORMAT:\n### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test",
        "Double Diamond (Design Council)": "[METHODOLOGY FRAMEWORK: DOUBLE DIAMOND]\nSolve the challenge by alternating systematically between divergent exploration and convergent synthesis:\n\nDIAMOND 1: SOLVING THE RIGHT PROBLEM\n1. Discover (Divergent): Explore the problem space broadly—uncover hidden stakeholder needs, system constraints, and edge cases.\n2. Define (Convergent): Synthesize findings into a single, razor-sharp problem definition and root bottleneck.\n\nDIAMOND 2: DESIGNING THE RIGHT SOLUTION\n3. Develop (Divergent): Architect distinct, competing solution pathways without premature filtering.\n4. Deliver (Convergent): Select the highest-leverage architecture, refine implementation details, and prepare immediate rollout.\n\nOUTPUT FORMAT:\n[1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]",
        "Lean Startup (Build-Measure-Learn)": "[METHODOLOGY FRAMEWORK: LEAN STARTUP (ERIC RIES)]\nApply empirical hypothesis testing to minimize wasted capital and engineering cycles:\n\n1. LEAP-OF-FAITH HYPOTHESIS: Identify the riskiest unproven value and growth assumptions that must hold true.\n2. BUILD (Minimum Viable Experiment): Design the leanest MVP or concierge test capable of validating or refuting the hypothesis.\n3. MEASURE (Actionable Metrics): Define non-gameable cohort/conversion metrics rather than vanity metrics.\n4. LEARN (Persevere or Pivot): Establish explicit numeric thresholds triggering either scaling (Persevere) or strategic redirection (Pivot).\n\nOUTPUT FORMAT:\n1. Core Hypothesis | 2. MVP Specification | 3. Actionable Metrics | 4. Pivot / Persevere Thresholds",
        "OKRs (Objectives and Key Results)": "[METHODOLOGY FRAMEWORK: OBJECTIVES AND KEY RESULTS (OKRs)]\nTranslate the strategic challenge into an execution-ready OKR cascade:\n\n1. OBJECTIVE (Qualitative North Star):\n- Formulate 1–2 ambitious, unambiguous, directional objectives (Where must we win?).\n\n2. KEY RESULTS (Quantitative Outcomes, Not Tasks):\n- Define 3 measurable Key Results per Objective (\"Move metric X from baseline A to target B by date T\").\n\n3. STRATEGIC INITIATIVES (Execution Plan):\n- List the concrete workstreams, owners, and milestones required to drive the Key Results.\n\nOUTPUT FORMAT:\n### Objective | ### Key Results (1–3) | ### High-Leverage Initiatives",
        "STEEPLE / PESTEL Macro Analysis": "[METHODOLOGY FRAMEWORK: STEEPLE / PESTEL MACRO-ENVIRONMENT AUDIT]\nAudit external macro-environmental forces systematically across all 7 dimensions:\n\n1. Social: Demographics, buyer behavior, workforce shifts, cultural norms.\n2. Technological: AI/automation shifts, infrastructure maturity, obsolescence risk.\n3. Economic: Interest rates, inflation, unit-cost dynamics, capital availability.\n4. Environmental: Carbon/ESG mandates, physical climate risk, resource constraints.\n5. Political: Trade/tariff policy, subsidies, geopolitical stability, public procurement.\n6. Legal: Regulatory compliance (GDPR/CCPA, antitrust, liability, sector statutes).\n7. Ethical: Trust, algorithmic fairness, transparency, reputational risk.\n\nOUTPUT FORMAT:\nDeliver a quantified Opportunity & Threat rating for [S], [T], [E], [E], [P], [L], and [E], followed by ### Top 3 Strategic Implications.",
        "Steffi Kieffer Boardroom": "[METHODOLOGY FRAMEWORK: EXECUTIVE AI BOARDROOM DEBATE]\nConduct a multi-perspective executive boardroom deliberation pitting distinct specialist lenses against one another:\n\n1. CHAIRMAN FRAMING: Set decision boundaries, constraints, and evaluation criteria clearly.\n2. RISK & COMPLIANCE CHALLENGER: Expose downside risks, regulatory traps, security flaws, and fragile assumptions.\n3. STRATEGIC INNOVATOR: Champion asymmetric upside, market differentiation, and long-term compounding leverage.\n4. PRAGMATIC OPERATOR: Ground the debate in execution feasibility, budget, timeline, and immediate implementation steps.\n5. CHAIRMAN RESOLUTION: Weigh competing trade-offs transparently and issue an unmistakable executive decision.\n\nOUTPUT FORMAT:\nPresent the structured specialist positions followed by a decisive [CHAIRMAN SYNTHESIS & RESOLUTION].",
        "Jobs-to-be-Done (JTBD / Clayton Christensen)": "[METHODOLOGY FRAMEWORK: JOBS-TO-BE-DONE (JTBD)]\nAnalyze demand and product strategy through the concrete progress (\"Job\") the customer is hiring a solution to achieve in a specific context:\n\n1. STRUGGLING MOMENT & CONTEXT: Under what exact operational trigger does the current workaround break down?\n2. FUNCTIONAL, EMOTIONAL & SOCIAL DIMENSIONS:\n   - Functional: What measurable core outcome must be completed?\n   - Emotional / Social: What risk, anxiety, or stakeholder friction must be eliminated?\n3. FOUR FORCES OF PROGRESS:\n   - Push of the status quo + Pull of the new solution vs. Anxiety of switching + Habit of the incumbent workflow.\n4. OUTCOME-DRIVEN SOLUTION: Engineer the offering to complete the entire job faster, cheaper, and with zero switching friction.\n\nOUTPUT FORMAT:\n[1. Struggling Moment] | [2. Job Dimensions] | [3. Four Forces Balance] | [4. Outcome-Driven Solution]",
        "Blue Ocean Strategy (ERRC Grid)": "[METHODOLOGY FRAMEWORK: BLUE OCEAN STRATEGY & ERRC GRID]\nBreak out of zero-sum Red Ocean competition and unlock uncontested market space through Value Innovation (simultaneous differentiation and lower cost):\n\n1. RED OCEAN BASELINE: Identify the commoditized industry factors where rivals over-compete at shrinking margins.\n2. ERRC FOUR-ACTIONS MATRIX:\n   - ELIMINATE: Which taken-for-granted industry factors deliver zero real buyer value and should be cut completely?\n   - REDUCE: Which over-engineered specs should be dialed well below industry norms?\n   - RAISE: Which high-impact value drivers must be elevated dramatically above industry standards?\n   - CREATE: Which entirely new sources of buyer value should be introduced for the first time?\n3. DIVERGENT VALUE CURVE: Demonstrate how cost structure drops while buyer utility surges.\n\nOUTPUT FORMAT:\n### Red Ocean Baseline | ### ERRC Grid (Eliminate / Reduce / Raise / Create) | ### New Value Curve & Tagline",
    },
    "2. Root-Cause Analysis, Logic & Problem Solving": {
        "5-Whys Root-Cause Analysis": "[METHODOLOGY FRAMEWORK: 5-WHYS ROOT-CAUSE DRILLDOWN]\nPierce past superficial symptoms to isolate the structural root cause via cascading causal interrogation:\n\n- Problem Statement: [Define observable failure or performance gap precisely]\n- Why 1: Why does this symptom occur? -> Causal Fact 1\n- Why 2: Why does Causal Fact 1 occur? -> Causal Fact 2\n- Why 3: Why does Causal Fact 2 occur? -> Causal Fact 3\n- Why 4: Why does Causal Fact 3 occur? -> Causal Fact 4\n- Why 5: Why does Causal Fact 4 occur? -> SYSTEMIC ROOT CAUSE\n\nPERMANENT COUNTERMEASURE:\nDesign a structural fix eliminating the systemic root cause rather than patching the surface symptom.\n\nOUTPUT FORMAT:\nList all 5 causal steps explicitly and conclude with ### Systemic Root Cause & ### Permanent Countermeasure.",
        "Cynefin Sense-Making Framework (Dave Snowden)": "[METHODOLOGY FRAMEWORK: CYNEFIN DOMAIN CLASSIFICATION]\nClassify the operational regime accurately before selecting a management or engineering response:\n\n1. DOMAIN DIAGNOSIS:\n   - Clear (Simple): Tight cause-and-effect -> Sense – Categorize – Respond (apply best practice / automate).\n   - Complicated: Discoverable cause-and-effect requiring expertise -> Sense – Analyze – Respond (apply good practice).\n   - Complex: Emergent causality understood only in retrospect -> Probe – Sense – Respond (run safe-to-fail experiments).\n   - Chaotic: Acute crisis with no visible constraints -> Act – Sense – Respond (stabilize bleeding immediately).\n2. REGIME-MATCHED ACTION PLAN: Derive concrete execution steps matching the diagnosed Cynefin domain without misapplying rigid rules to complex problems.\n\nOUTPUT FORMAT:\n### Cynefin Domain Diagnosis | ### Diagnostic Evidence | ### Regime-Specific Action Plan",
        "First Principles Thinking": "[METHODOLOGY FRAMEWORK: FIRST PRINCIPLES DECONSTRUCTION]\nStrip away reasoning-by-analogy and rebuild the optimal solution from bedrock physical, mathematical, and economic truths:\n\n1. ASSUMPTION STRIPPING:\n   - Expose inherited industry conventions, legacy cost structures, and \"that's how it's always done\" dogmas.\n2. BEDROCK AXIOMS (Fundamental Truths):\n   - Isolate the non-negotiable physical, technical, statutory, and unit-economic constraints that cannot be violated.\n3. GROUND-UP RECONSTRUCTION:\n   - Synthesize a step-change architecture directly from those fundamental truths without copying legacy blueprints.\n\nOUTPUT FORMAT:\n[1. Discarded Legacy Assumptions] | [2. Bedrock Fundamental Truths] | [3. Ground-Up Reconstructed Solution]",
        "Ishikawa Fishbone Diagram (6Ms)": "[METHODOLOGY FRAMEWORK: ISHIKAWA 6M CAUSE-AND-EFFECT AUDIT]\nInvestigate failure contributors systematically across all 6 operational branches:\n\n1. Man / People: Skill gaps, cognitive overload, handoff ambiguity, incentive misalignment.\n2. Machine / Infrastructure: Compute/hardware limits, software bugs, model/API instability.\n3. Method / Process: Flawed workflows, missing SOPs, broken approval or validation logic.\n4. Material / Data: Corrupted inputs, schema drift, stale upstream data, prompt defects.\n5. Milieu / Environment: Network latency, regulatory shifts, load spikes, external dependencies.\n6. Measurement / Telemetry: Blind monitoring, misleading KPIs, missing alerts, noisy logs.\n\nOUTPUT FORMAT:\nAudit each of the 6Ms systematically and conclude with ### Primary Causal Driver & Remediation.",
        "Porter's Five Forces": "[METHODOLOGY FRAMEWORK: PORTER'S FIVE FORCES INDUSTRY STRUCTURE]\nQuantify structural industry attractiveness and profit pool defensibility across 5 competitive forces:\n\n1. Competitive Rivalry Among Incumbents (High / Moderate / Low + margin impact)\n2. Threat of New Entrants (Capital, regulatory, network, and data barriers to entry)\n3. Bargaining Power of Suppliers (Compute, APIs, talent, raw materials, concentration risk)\n4. Bargaining Power of Buyers (Switching costs, price sensitivity, buyer concentration)\n5. Threat of Substitutes (Alternative workflows, open-source disruption, paradigm shifts)\n\nOUTPUT FORMAT:\nRate and evidence each of the 5 forces, concluding with ### Structural Moat & Positioning Strategy.",
        "SWOT & TOWS Strategic Matrix": "[METHODOLOGY FRAMEWORK: SWOT & ACTIONABLE TOWS CROSS-MATRIX]\nMove beyond passive SWOT lists into executable TOWS strategic pairings:\n\nINTERNAL CAPABILITIES:\n- Strengths (S): Verified proprietary advantages, assets, and cost/tech edges.\n- Weaknesses (W): Internal bottlenecks, capability gaps, and structural vulnerabilities.\n\nEXTERNAL ENVIRONMENT:\n- Opportunities (O): Asymmetric market openings, regulatory tailwinds, underserved demand.\n- Threats (T): Competitive, technological, macroeconomic, or regulatory hazards.\n\nACTIONABLE TOWS PAIRINGS:\nDerive concrete **SO** (Maxi-Maxi), **WO** (Mini-Maxi), **ST** (Maxi-Mini), and **WT** (Mini-Mini) strategic moves.\n\nOUTPUT FORMAT:\n[Strengths] | [Weaknesses] | [Opportunities] | [Threats] | [TOWS Execution Moves]",
        "MECE & Minto Pyramid Principle (Barbara Minto)": "[METHODOLOGY FRAMEWORK: MECE & MINTO PYRAMID PRINCIPLE]\nStructure analytical problem-solving and executive communication with top-tier strategy consulting rigor:\n\n1. GOVERNING THOUGHT (Answer First): Lead immediately with the decisive, action-oriented recommendation in 1–2 sentences.\n2. SCQA FRAMING: Anchor context cleanly via *Situation – Complication – Key Question – Answer*.\n3. MECE DISAGGREGATION (*Mutually Exclusive, Collectively Exhaustive*):\n   - Decompose the argument or problem tree into non-overlapping, zero-gap analytical pillars.\n4. QUANTIFIED EVIDENCE BASE: Back each pillar with verifiable metrics, calculations, and empirical proof.\n\nOUTPUT FORMAT:\n### Governing Thought (Answer First) | ### SCQA Context | ### MECE Pillar Breakdown (1–3) | ### Implementation Metrics",
        "Kepner-Tregoe Problem Analysis (IS / IS NOT)": "[METHODOLOGY FRAMEWORK: KEPNER-TREGOE (KT) IS / IS-NOT DIAGNOSTIC]\nIsolate elusive technical or operational root causes by contrasting exact boundary conditions:\n\n1. DEVIATION STATEMENT: State the exact gap between expected standard performance and observed behavior.\n2. FOUR-DIMENSION SPECIFICATION MATRIX (IS vs. IS NOT):\n   - WHAT object/defect IS observed vs. closely related objects/defects that ARE NOT affected?\n   - WHERE is it observed geographically/architecturally vs. WHERE IS IT NOT?\n   - WHEN did it first occur / recur in lifecycle timing vs. WHEN DID IT NOT?\n   - EXTENT: How many units/requests are impacted and is the trend growing, stable, or decaying?\n3. DISTINCTIONS & CHANGES: Identify what is unique to the IS column and what changed near that boundary.\n4. CAUSE TESTING: Test candidate causes against every IS and IS-NOT fact until one explains all observations without contradiction.\n\nOUTPUT FORMAT:\n[1. Deviation Statement] | [2. IS / IS-NOT Table] | [3. Distinctions & Changes] | [4. Verified Root Cause & Fix]",
        "Fault Tree Analysis (FTA / IEC 61025)": "[METHODOLOGY FRAMEWORK: DEDUCTIVE FAULT TREE ANALYSIS (FTA)]\nMap critical system failure pathways top-down using Boolean gate logic (AND / OR):\n\n1. TOP UNDESIRED EVENT: Define the exact catastrophic failure state at the apex of the tree.\n2. BOOLEAN GATE DECOMPOSITION:\n   - OR Gates (Single Points of Failure): Any single child fault triggers the parent failure immediately.\n   - AND Gates (Redundancy Barriers): All child faults must fail simultaneously for the fault to propagate.\n3. MINIMAL CUT SETS: Extract the shortest fault combinations capable of causing the Top Event.\n4. ARCHITECTURAL REMEDIATION: Convert high-probability OR gates into independent AND gates via failover, validation, and isolation.\n\nOUTPUT FORMAT:\n### Top Event | ### Boolean Fault Tree (AND/OR Paths) | ### Minimal Cut Sets (SPOFs) | ### Redundancy Hardening",
    },
    "3. Operations, Lean & Quality Excellence": {
        "DMAIC (Six Sigma)": "[METHODOLOGY FRAMEWORK: SIX SIGMA DMAIC PROCESS EXCELLENCE]\nEliminate process defects, variance, and quality drift systematically across all 5 DMAIC phases:\n\n1. DEFINE: Specify the problem, customer Critical-to-Quality (CTQ) requirements, and project scope.\n2. MEASURE: Establish baseline process capability, defect rates, and data collection validity.\n3. ANALYZE: Isolate statistically and causally verified root drivers of variation.\n4. IMPROVE: Engineer, pilot, and verify targeted process changes eliminating the root drivers.\n5. CONTROL: Lock in gains with Statistical Process Control (SPC), automated alerts, and standard operating procedures.\n\nOUTPUT FORMAT:\n[Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control]",
        "PDCA Cycle (Deming Wheel)": "[METHODOLOGY FRAMEWORK: DEMING PDCA CONTINUOUS IMPROVEMENT]\nDrive disciplined iterative improvement across the 4-stage Plan-Do-Check-Act loop:\n\n1. PLAN: Diagnose the current baseline, quantify the target improvement, and formulate a falsifiable action plan.\n2. DO: Execute a controlled, small-blast-radius pilot or prototype implementation.\n3. CHECK: Measure pilot results rigorously against predicted targets and analyze deviations.\n4. ACT: Standardize validated improvements system-wide or refine hypotheses for the next cycle.\n\nOUTPUT FORMAT:\n### Plan | ### Do | ### Check | ### Act",
        "Theory of Constraints (TOC / Eliyahu Goldratt)": "[METHODOLOGY FRAMEWORK: THEORY OF CONSTRAINTS (5 FOCUSING STEPS)]\nMaximize end-to-end system throughput by concentrating exclusively on the single governing bottleneck:\n\n1. IDENTIFY THE CONSTRAINT: Pinpoint the single resource, policy, or stage limiting total system throughput.\n2. EXPLOIT THE CONSTRAINT: Squeeze 100% productive utilization out of the bottleneck using existing resources (zero idle/waste at the constraint).\n3. SUBORDINATE EVERYTHING ELSE: Pace all upstream and downstream non-constraints strictly to serve the bottleneck (Drum-Buffer-Rope).\n4. ELEVATE THE CONSTRAINT: Invest targeted capital, automation, or capacity to break the bottleneck only after full exploitation.\n5. PREVENT INERTIA: Once broken, immediately identify the new system constraint.\n\nOUTPUT FORMAT:\n[1. Governing Bottleneck] | [2. Exploitation Plan] | [3. System Subordination] | [4. Capacity Elevation]",
        "Value Stream Mapping (VSM / Lean Flow)": "[METHODOLOGY FRAMEWORK: END-TO-END VALUE STREAM MAPPING (VSM)]\nExpose and eliminate non-value-adding waste across the entire delivery pipeline from trigger to customer outcome:\n\n1. CURRENT-STATE MAP: Quantify Process Time (Value-Add), Wait/Queue Time, Total Lead Time, and First-Pass Yield (% Complete & Accurate) per step.\n2. PROCESS CYCLE EFFICIENCY (PCE): Compute $\\text{PCE} = \\text{Value-Add Time} / \\text{Total Lead Time}$.\n3. 8-WASTES AUDIT (DOWNTIME): Pinpoint Defects, Overproduction, Waiting, Non-utilized talent, Transportation, Inventory/WIP queues, Motion, and Extra-processing.\n4. FUTURE-STATE ARCHITECTURE: Design continuous flow,WIP pull limits, and automation with quantified Lead-Time reduction.\n\nOUTPUT FORMAT:\n[1. Current-State Metrics & PCE] | [2. Waste Hotspots (DOWNTIME)] | [3. Future-State Design] | [4. Throughput Gain]",
        "A3 Problem-Solving (Toyota Production System)": "[METHODOLOGY FRAMEWORK: TOYOTA A3 EXECUTIVE PROBLEM-SOLVING]\nSynthesize diagnosis, root-cause proof, and execution governance onto a crisp single-sheet Toyota A3 structure:\n\n1. BACKGROUND & STRATEGIC CONTEXT: Why does solving this gap matter right now?\n2. CURRENT CONDITION (Gemba Facts): Verified baseline metrics and observed workflow breakdown.\n3. TARGET CONDITION: Specific measurable target metric and deadline.\n4. ROOT-CAUSE ANALYSIS: Direct causal chain explaining the gap between Current and Target.\n5. COUNTERMEASURES & EXECUTION PLAN: Concrete interventions with Owner, Due Date, and Expected Impact.\n6. CONFIRMATION OF EFFECT & FOLLOW-UP: Verification telemetry and permanent SOP standardization.\n\nOUTPUT FORMAT:\n### 1. Background | ### 2. Current Baseline | ### 3. Target State | ### 4. Root Cause | ### 5. Countermeasures | ### 6. Verification & SOP",
        "SIPOC & RACI Process Governance": "[METHODOLOGY FRAMEWORK: SIPOC BOUNDARIES & RACI ACCOUNTABILITY]\nEliminate handoff ambiguity and diffused ownership across cross-functional workflows:\n\n1. SIPOC ARCHITECTURE:\n   - Suppliers -> Inputs (with strict entry acceptance criteria) -> Process (5–7 high-level stages) -> Outputs (artifacts) -> Customers (SLA expectations).\n2. RACI GOVERNANCE MATRIX:\n   - **R**esponsible (executes work), **A**ccountable (strictly ONE single owner per deliverable holding final sign-off!), **C**onsulted (two-way input before action), **I**nformed (one-way notification after action).\n3. HANDOFF & SLA GUARDRAILS: Resolve any step with zero or multiple Accountable owners.\n\nOUTPUT FORMAT:\n### SIPOC Specification | ### RACI Matrix Table | ### Handoff & Escalation SLAs",
    },
    "4. Corporate Strategy, Prioritization & Change": {
        "Eisenhower Priority Matrix": "[METHODOLOGY FRAMEWORK: EISENHOWER URGENCY-IMPORTANCE MATRIX]\nTriage competing initiatives and tasks ruthlessly across Importance and Urgency:\n\n1. QUADRANT I — DO IMMEDIATELY (Important & Urgent): Execute first with a concrete crisis/delivery checklist.\n2. QUADRANT II — SCHEDULE & PROTECT (Important & Not Urgent): Compounding strategic work—allocate dedicated deep-work blocks.\n3. QUADRANT III — DELEGATE OR AUTOMATE (Not Important & Urgent): Route to sub-agents, scripts, or standardized SOPs.\n4. QUADRANT IV — ELIMINATE (Not Important & Not Urgent): Drop completely to protect cognitive and system bandwidth.\n\nOUTPUT FORMAT:\n[Quadrant I: Do Now] | [Quadrant II: Schedule] | [Quadrant III: Delegate/Automate] | [Quadrant IV: Eliminate]",
        "Kano Customer Value Model": "[METHODOLOGY FRAMEWORK: KANO FEATURE & SATISFACTION CLASSIFICATION]\nClassify product or service attributes by their non-linear impact on customer satisfaction and retention:\n\n1. THRESHOLD / MUST-BE ATTRIBUTES: Table-stakes expectations—absence causes immediate churn, presence merely prevents dissatisfaction.\n2. PERFORMANCE / LINEAR ATTRIBUTES: More is directly better (e.g., speed, accuracy, unit cost)—primary battleground of competitive comparison.\n3. EXCITEMENT / DELIGHTERS: Unexpected high-leverage capabilities creating disproportionate differentiation and pricing power.\n4. INDIFFERENT / REVERSE ATTRIBUTES: Bloated features nobody values (cut to save engineering cost) or features that actively annoy users.\n\nOUTPUT FORMAT:\n[Must-Be Table Stakes] | [Linear Performance Drivers] | [Asymmetric Delighters] | [Cut / Avoid List]",
        "Kotter 8-Step Change Model": "[METHODOLOGY FRAMEWORK: KOTTER 8-STEP ORGANIZATIONAL TRANSFORMATION]\nArchitect complex organizational or technical migrations across all 8 transformation stages:\n\n1. Create Genuine Urgency (Quantify cost of status-quo stagnation)\n2. Build a Guiding Coalition (Assemble cross-functional authority and champions)\n3. Form a Strategic Vision & Initiatives (Clear target state)\n4. Enlist & Communicate the Vision (Relentless, unambiguous Rollout messaging)\n5. Enable Action by Removing Barriers (Eliminate legacy blockers, permissions, and friction)\n6. Generate Short-Term Wins (Deliver visible 30-day proof points)\n7. Sustain Acceleration (Compound wins without declaring premature victory)\n8. Institute Change in Systems & Culture (Embed into SOPs, incentives, and defaults)\n\nOUTPUT FORMAT:\nProvide concrete operational actions for all 8 stages tailored to the mission.",
        "McKinsey 7S Alignment Model": "[METHODOLOGY FRAMEWORK: MCKINSEY 7S ORGANIZATIONAL ALIGNMENT]\nAudit systemic coherence and surface misalignments across Hard and Soft organizational dimensions:\n\nHARD S ELEMENTS:\n1. Strategy: Competitive thesis and resource allocation.\n2. Structure: Organizational / modular topology and reporting lines.\n3. Systems: Operational workflows, tech stack, telemetry, and incentives.\n\nSOFT S ELEMENTS:\n4. Shared Values: Core non-negotiable operating principles.\n5. Style: Leadership posture and decision-making culture.\n6. Staff: Human and AI-agent roster composition.\n7. Skills: Distinct institutional capabilities and toolchains.\n\nOUTPUT FORMAT:\n### Hard-S Audit | ### Soft-S Audit | ### Cross-Dimensional Friction & Realignment Plan",
        "NABC Value Proposition Pitch (SRI International)": "[METHODOLOGY FRAMEWORK: SRI NABC VALUE PROPOSITION]\nDistill the initiative into an investor- and board-grade NABC value thesis:\n\n1. NEED: What acute, quantified market or operational pain exists, and who owns the budget for it?\n2. APPROACH: What is the specific, defensible mechanism or architecture that solves the need?\n3. BENEFITS PER COSTS: What is the quantified ROI, payback period, or unit-cost improvement relative to total investment?\n4. COMPETITION & ALTERNATIVES: Why does this approach beat both direct competitors and \"do-nothing / internal spreadsheet\" workarounds?\n\nOUTPUT FORMAT:\n[Need] | [Approach] | [Quantified Benefits / Cost] | [Competitive Superiority]",
        "RICE Quantitative Prioritization": "[METHODOLOGY FRAMEWORK: RICE QUANTITATIVE SCORING]\nRank competing roadmap items or strategic initiatives objectively using the RICE formula:\n$$\\text{RICE Score} = \\frac{\\text{Reach} \\times \\text{Impact} \\times \\text{Confidence}}{\\text{Effort}}$$\n\n1. REACH: Concrete number of users, transactions, or accounts impacted per quarter.\n2. IMPACT: Effect per user/account (3 = Massive, 2 = High, 1 = Medium, 0.5 = Low, 0.25 = Minimal).\n3. CONFIDENCE: Evidence quality (100% = Hard empirical data, 80% = Solid benchmark, 50% = Informed estimate).\n4. EFFORT: Total person-months / engineering sprints required.\n\nOUTPUT FORMAT:\nMarkdown Table: `Initiative | Reach | Impact | Confidence | Effort | RICE Score | Verdict` followed by sequencing rationale.",
        "Make-or-Buy & 36-Month TCO Scoring": "[METHODOLOGY FRAMEWORK: BUILD vs. BUY vs. PARTNER & 36-MONTH TCO]\nEvaluate technology, AI, and operational capability decisions across IP moat and full lifecycle economics:\n\n1. STRATEGIC DIFFERENTIATION: Core proprietary IP & competitive moat (Build) vs. non-differentiating commodity utility (Buy).\n2. 36-MONTH TOTAL COST OF OWNERSHIP (TCO):\n   - Build: Engineering build cost + ongoing maintenance, security patching, infra/GPU hosting, and opportunity cost.\n   - Buy: SaaS/API licensing, usage/token escalation risk, integration cost, and vendor lock-in switching cost.\n   - Partner: Revenue share / retainer, SLA dependency, and knowledge transfer.\n3. TIME-TO-VALUE: Speed advantage in weeks/months across options.\n4. DATA SOVEREIGNTY, SECURITY & COMPLIANCE: On-prem / VPC control vs. third-party data egress exposure.\n\nOUTPUT FORMAT:\n### Core IP Assessment | ### 36-Month TCO Comparison Table | ### Sovereignty & Lock-In Risk | ### Binding Verdict & 90-Day Plan",
        "Ansoff Growth Matrix": "[METHODOLOGY FRAMEWORK: ANSOFF PRODUCT-MARKET GROWTH MATRIX]\nEvaluate expansion vectors systematically across market familiarity, product novelty, and execution risk:\n\n1. MARKET PENETRATION (Existing Product / Existing Market — Lowest Risk): Capture share, increase usage frequency, reduce churn, optimize pricing.\n2. MARKET DEVELOPMENT (Existing Product / New Market): Expand into new geographies, enterprise/SMB tiers, or distribution channels.\n3. PRODUCT DEVELOPMENT (New Product / Existing Market): Launch adjacent modules or next-gen offerings to the existing customer base.\n4. DIVERSIFICATION (New Product / New Market — Highest Risk): Related (concentric) vs. unrelated expansion requiring new capabilities.\n5. SEQUENCED CAPITAL ALLOCATION: Recommend exact phasing by risk-adjusted ROI.\n\nOUTPUT FORMAT:\n[1. Market Penetration] | [2. Market Development] | [3. Product Development] | [4. Diversification] | [Capital Allocation Sequence]",
        "BCG Growth-Share Portfolio Matrix": "[METHODOLOGY FRAMEWORK: BCG PORTFOLIO & CAPITAL ALLOCATION MATRIX]\nAllocate capital and executive bandwidth across business units, products, or initiatives by Market Growth and Relative Market Share:\n\n1. CASH COWS (High Share / Mature Growth): Harvest free cashflow, automate operations, and avoid over-reinvestment.\n2. STARS (High Share / High Growth): Invest aggressively to lock in compounding category leadership.\n3. QUESTION MARKS (Low Share / High Growth): Make a binary call—fund decisively to reach Star velocity or exit cleanly.\n4. PETS / DOGS (Low Share / Low Growth): Divest, sunset, or put on zero-overhead maintenance to free trapped capital.\n\nOUTPUT FORMAT:\n### Portfolio Classification | ### Cashflow Reallocation Loop | ### Explicit Invest / Harvest / Sunset Decisions",
        "VRIO Competitive Advantage Framework": "[METHODOLOGY FRAMEWORK: BARNEY VRIO MOAT AUDIT]\nStress-test core assets, proprietary data, technology, and distribution for durable competitive advantage:\n\n1. VALUABLE: Does the capability directly expand willingness-to-pay or structurally lower unit costs?\n2. RARE: How few competitors possess or can access an equivalent asset?\n3. INIMITABLE: Do network effects, switching costs, proprietary data flywheels, patents, or regulatory licenses make replication prohibitively costly or slow?\n4. ORGANIZED: Are governance, incentives, and GTM execution wired to capture the full economic value?\n\nVERDICT SCALE: Competitive Disadvantage -> Competitive Parity -> Temporary Advantage -> Sustained Moat.\n\nOUTPUT FORMAT:\nMarkdown VRIO Audit Table per Asset + ### Moat Deepening Roadmap",
    },
    "5. Cognitive Debiasing & Critical Thinking": {
        "Ladder of Inference (Chris Argyris)": "[METHODOLOGY FRAMEWORK: ARGYRIS LADDER OF INFERENCE]\nAudit reasoning step-by-step from raw observable facts up to executive action to eliminate premature leaps and confirmation bias:\n\n1. OBSERVABLE RAW DATA: What verifiable logs, numbers, text, or events actually exist?\n2. SELECTED DATA: Which subset of facts is being focused on—and what disconfirming data was filtered out?\n3. INTERPRETED MEANING: What cultural or contextual meaning is being attached to the selected facts?\n4. ASSUMPTIONS: What unstated premises are being applied?\n5. CONCLUSIONS: What causal or strategic deduction follows—and is it logically valid?\n6. ACTION: What concrete decision is justified once the lower rungs are verified?\n\nOUTPUT FORMAT:\nWalk up the rungs explicitly: [Rung 1: Raw Facts] -> [Rung 2: Filtered Signals] -> [Rung 3: Assumptions] -> [Rung 4: Verified Action]",
        "Pre-Mortem Analysis (Gary Klein)": "[METHODOLOGY FRAMEWORK: PROSPECTIVE HINDSIGHT PRE-MORTEM]\nAssume as an established historical fact that 12 months from today this initiative has suffered a catastrophic failure. Work backward relentlessly:\n\n1. THE AUTOPSY HEADLINE: Describe the exact nature, magnitude, and trigger of the total failure.\n2. LETHAL FAILURE DRIVERS: Surface the hidden architectural flaws, wishful unit-economic assumptions, regulatory traps, key-person bottlenecks, and market shifts that killed it.\n3. PRE-EMPTIVE IMMUNIZATION: Re-architect the plan TODAY with concrete structural safeguards neutralizing each top failure mode before launch.\n\nOUTPUT FORMAT:\n[1. The Failure Autopsy] | [2. Ranked Causes of Death] | [3. Pre-Launch Structural Safeguards]",
        "Red Teaming & Adversarial Analysis": "[METHODOLOGY FRAMEWORK: ADVERSARIAL RED TEAMING]\nAdopt the mindset of a sophisticated competitor, hostile attacker, or skeptical regulator determined to break the proposed plan or system:\n\n1. ATTACK SURFACE & VULNERABILITIES: Pinpoint the weakest assumptions across security, legal exposure, unit economics, UX, and operational dependencies.\n2. EXPLOITATION SCENARIOS: Detail exactly how an adversary, market shock, or pathological edge case exploits those weaknesses for maximum damage.\n3. BLUE-TEAM ARCHITECTURAL HARDENING: Specify immediate structural changes that close each exploit vector permanently.\n\nOUTPUT FORMAT:\n### Attack Vectors | ### Adversarial Exploit Scenarios | ### Blue-Team Hardening Directives",
        "Six Thinking Hats (Edward de Bono)": "[METHODOLOGY FRAMEWORK: DE BONO SIX THINKING HATS]\nExamine the decision sequentially through 6 strictly separated cognitive lenses without muddling modes:\n\n1. WHITE HAT (Pure Facts & Missing Data): Verified metrics, hard facts, and explicit information gaps.\n2. RED HAT (Intuition & Stakeholder Sentiment): Gut friction, buyer/team trust reactions, reputational optics.\n3. BLACK HAT (Rigorous Caution): Downside risks, legal/financial exposure, failure modes, and constraints.\n4. YELLOW HAT (Constructive Upside): Best-case value creation, synergies, and asymmetric upside.\n5. GREEN HAT (Lateral Alternatives): Non-obvious creative workarounds and structural reframings.\n6. BLUE HAT (Executive Synthesis): Final decision rule, sequencing, and immediate next actions.\n\nOUTPUT FORMAT:\n⚪ White Hat | 🔴 Red Hat | 🖤 Black Hat | 🟡 Yellow Hat | 🟢 Green Hat | 🔵 Blue Hat Synthesis",
        "Game-Theoretic Mechanism Design": "[METHODOLOGY FRAMEWORK: GAME THEORY & INCENTIVE MECHANISM DESIGN]\nModel the problem as a multi-agent strategic game governed by payoffs, private information, and equilibrium incentives:\n\n1. PLAYERS & PAYOFF FUNCTIONS: Map every rational actor (buyers, vendors, competitors, regulators, employees/agents) and what each actually optimizes for.\n2. ASYMMETRIES & PERVERSE INCENTIVES: Diagnose Principal-Agent divergence, Moral Hazard, Adverse Selection, and Free-Rider traps.\n3. NASH EQUILIBRIUM PREDICTION: Predict the stable outcome if every actor plays their self-interested best response under current rules.\n4. INCENTIVE-COMPATIBLE MECHANISM: Redesign contracts, pricing tiers, SLAs, escrow/clawbacks, or auction rules so truth-telling and value alignment become the dominant strategy.\n\nOUTPUT FORMAT:\n### Players & Payoffs | ### Moral Hazard & Asymmetries | ### Baseline Nash Equilibrium | ### Incentive-Compatible Mechanism",
        "Bayesian Updating & Superforecasting (Tetlock)": "[METHODOLOGY FRAMEWORK: BAYESIAN PROBABILITY UPDATING & SUPERFORECASTING]\nReplace vague verbal words (\"likely\", \"promising\") with calibrated probabilities grounded in base rates and diagnostic evidence:\n\n1. OUTSIDE VIEW (Reference-Class Prior $P(H)$): What is the historical statistical base rate of success across comparable real-world initiatives?\n2. INSIDE VIEW (Diagnostic Likelihood Ratios): List specific positive and negative case-specific signals and how strongly each shifts the odds.\n3. CALIBRATED POSTERIOR ($P(H|E)$): State the updated probability explicitly with a 90% confidence interval.\n4. SIGNPOSTS & FALSIFICATION TRIGGERS: Define concrete 30/90-day observable milestones that would shift your posterior by $\\ge 20$ percentage points.\n\nOUTPUT FORMAT:\n[1. Base-Rate Prior %] | [2. Diagnostic Evidence (+/-)] | [3. Calibrated Posterior %] | [4. Signpost Triggers]",
        "Inversion Thinking (Charlie Munger / Jacobi)": "[METHODOLOGY FRAMEWORK: INVERSION THINKING (\"INVERT, ALWAYS INVERT\")]\nSolve hard problems both forward and backward: instead of asking only how to succeed brilliantly, first identify everything guaranteed to cause ruin and systematically remove it:\n\n1. FORWARD OBJECTIVE: Define the desired strategic outcome clearly.\n2. INVERTED ANTI-GOAL (Guaranteed Failure Blueprint): List the 5–7 decisions, habits, or architectural flaws that would guarantee catastrophic failure.\n3. HARD PREVENTION CONSTRAINTS: Engineer non-bypassable technical, contractual, or financial guardrails blocking every failure trigger.\n4. RESIDUAL ANTI-STUPIDITY STRATEGY: Articulate the durable, high-probability strategy that remains once unforced errors are eliminated.\n\nOUTPUT FORMAT:\n### 1. Forward Objective | ### 2. Blueprint for Guaranteed Ruin | ### 3. Hard Prevention Guardrails | ### 4. Durable Winning Strategy",
        "Steelmanning & Hegelian Dialectic": "[METHODOLOGY FRAMEWORK: STEELMANNING & DIALECTICAL SYNTHESIS]\nEliminate weak strawman debates and watered-down compromises by colliding opposing theses at maximum intellectual strength:\n\n1. THESIS (Strongest Case for Option A): Articulate Option A with its sharpest logic, best empirical evidence, and highest upside.\n2. STEELMAN ANTITHESIS (Strongest Possible Case for Option B): Construct the opposing argument NOT as a caricature, but in its most rigorous, persuasive, data-backed form.\n3. CRUX OF DISAGREEMENT: Pinpoint the exact empirical assumption, time horizon, or risk weight where Thesis and Antithesis diverge.\n4. HIGHER-ORDER SYNTHESIS: Architect a third structural design that resolves the crux while preserving the core strengths of both sides.\n\nOUTPUT FORMAT:\n[1. Thesis] | [2. Steelman Antithesis] | [3. Empirical Crux] | [4. Higher-Order Synthesis]",
    },
    "6. Systems Thinking & Complexity": {
        "Causal Loop Diagrams (System Dynamics)": "[METHODOLOGY FRAMEWORK: SYSTEM DYNAMICS & CAUSAL LOOP DIAGRAMS]\nMap endogenous feedback loops, stocks, flows, and time delays governing long-term system behavior:\n\n1. CORE STOCKS & VARIABLES: Define the accumulating stocks (capital, customers, tech debt, trust) and flow rates.\n2. REINFORCING LOOPS (R — Compounding Engines or Vicious Spirals): Trace self-amplifying feedback cycles (+/+ or -/-).\n3. BALANCING LOOPS (B — Stabilizers & Ceilings): Identify natural saturation limits, capacity ceilings, and corrective dampeners.\n4. SYSTEM DELAYS: Pinpoint latency between action and observable effect that triggers oscillation or overshoot.\n\nOUTPUT FORMAT:\n[Stocks & Variables] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Time Delays & Damping Plan]",
        "Iceberg Model (Systems Thinking)": "[METHODOLOGY FRAMEWORK: SYSTEMS THINKING ICEBERG MODEL]\nMove intervention depth from reactive firefighting at the surface down to structural root architecture:\n\n1. EVENTS (Visible Tip — Reactive): What acute incident or metric spike just occurred?\n2. PATTERNS & TRENDS (Historical Trajectory — Adaptive): What recurring trend or cycle appears over weeks/quarters?\n3. UNDERLYING STRUCTURES (Rules & Architecture — Generative): What incentives, schemas, bottlenecks, and SOPs physically produce that pattern?\n4. MENTAL MODELS (Bedrock Beliefs — Transformative): What unspoken assumptions or governance beliefs keep the flawed structure in place?\n\nOUTPUT FORMAT:\n[1. Surface Event] -> [2. Recurring Pattern] -> [3. Generating Structure] -> [4. Bedrock Mental Model Shift]",
        "Second-Order Thinking (Howard Marks)": "[METHODOLOGY FRAMEWORK: SECOND- & THIRD-ORDER CONSEQUENCE ANALYSIS]\nTrace cascading consequences beyond the obvious immediate effect (\"And then what?\"):\n\n1. FIRST-ORDER EFFECTS (Immediate & Obvious — 0 to 30 Days):\n- What is the direct, intended outcome everyone sees immediately?\n\n2. SECOND-ORDER EFFECTS (Behavioral & Systemic Ripples — 1 to 6 Months):\n- How do competitors, customers, regulators, or internal teams adapt in response to the first-order change? What unintended side effects emerge?\n\n3. THIRD-ORDER EQUILIBRIUM (Long-Term Structural Shift — 6 to 36 Months):\n- What is the net long-run impact on margins, defensibility, and system complexity?\n\nOUTPUT FORMAT:\n[1st-Order Direct Effect] | [2nd-Order Adaptive Ripples] | [3rd-Order Long-Term Equilibrium & Decision]",
        "Wardley Mapping (Simon Wardley)": "[METHODOLOGY FRAMEWORK: WARDLEY VALUE-CHAIN & EVOLUTION MAPPING]\nMap system components along User Visibility (Y-axis) and Commodity Evolution (X-axis) to guide strategic resource allocation:\n\n1. ANCHOR USER NEED: Define the sovereign user/customer and their top-level need at the top of the value chain.\n2. DEPENDENCY VALUE CHAIN: Trace component dependencies from visible user experience down to invisible infrastructure.\n3. EVOLUTION STAGE PER COMPONENT:\n   - I. Genesis (Novel, uncertain, experimental)\n   - II. Custom-Built (Bespoke competitive differentiation)\n   - III. Product / Rental (Standardized commercial/open-source software)\n   - IV. Commodity / Utility (Standardized API, cloud/power utility)\n4. STRATEGIC DOCTRINE MOVES: Stop custom-building Stage-III/IV commodities; focus bespoke engineering exclusively on Stage-I/II differentiators.\n\nOUTPUT FORMAT:\n### User Anchor & Value Chain | ### Component Evolution Map (I–IV) | ### Strategic Build/Consume Moves",
        "Donella Meadows 12 Leverage Points": "[METHODOLOGY FRAMEWORK: DONELLA MEADOWS SYSTEM LEVERAGE HIERARCHY]\nAvoid burning resources on low-leverage parameter tweaks by targeting high-leverage structural intervention points:\n\n1. LOW LEVERAGE (Parameters, Subsidies & Buffers): Merely tuning numbers, budgets, headcount, or queue sizes within a broken loop.\n2. MEDIUM LEVERAGE (Information Flows & Feedback Delays): Exposing real-time consequences directly to decision-makers and tightening feedback loops.\n3. HIGH LEVERAGE (Rules, Incentives & Self-Organization): Changing system constraints, permissions, ownership rules, and reward functions.\n4. MAXIMUM LEVERAGE (Overarching System Goal & Paradigm): Redefining the objective function the entire system optimizes for.\n\nOUTPUT FORMAT:\n### Low-Leverage Traps to Avoid | ### Information & Feedback Fixes | ### Rule & Incentive Redesign | ### Top-Level System Goal",
        "Viable System Model (VSM / Stafford Beer)": "[METHODOLOGY FRAMEWORK: STAFFORD BEER CYBERNETIC VIABLE SYSTEM MODEL (VSM)]\nDiagnose organizational or multi-agent architecture across the 5 cybernetic subsystems required for autonomous viability:\n\n1. SYSTEM 1 (Autonomous Operations): Value-producing operational units and their required local autonomy.\n2. SYSTEM 2 (Anti-Oscillation Coordination): Shared schemas, scheduling protocols, and conflict damping across units.\n3. SYSTEM 3 & 3* (Operational Delivery & Sporadic Audit): Resource bargaining, internal synergy, and direct ground-truth spot audits.\n4. SYSTEM 4 (Strategic Intelligence & Outside/Future Radar): Environmental scanning, R&D, and adaptation to external shifts.\n5. SYSTEM 5 (Policy, Identity & Homeostasis): Executive arbitration balancing present exploitation (S3) against future exploration (S4).\n\nOUTPUT FORMAT:\n[System 1: Operations] | [System 2: Coordination] | [System 3/3*: Control & Audit] | [System 4: Foresight] | [System 5: Governance Balance]",
    },
    "7. Foresight, Risk & Resilience": {
        "Antifragility Analysis (Nassim Nicholas Taleb)": "[METHODOLOGY FRAMEWORK: TALEB FRAGILE–ROBUST–ANTIFRAGILE TRIAD]\nAudit and re-architect exposure to volatility, shocks, tail events, and randomness:\n\n1. FRAGILE EXPOSURES (Concave Payoffs — Harmed by Volatility): Identify hidden leverage, tight coupling, single points of failure, and uncapped downside.\n2. ROBUST BASELINE (Insensitive to Shocks): Establish cash/capacity buffers, redundancy, and strict fault isolation.\n3. ANTIFRAGILE DESIGN (Convex Payoffs — Gains from Disorder): Apply a **Barbell Strategy** (90% ultra-safe downside floor + 10% capped-loss, uncapped-upside optionality) and automated post-error learning loops.\n\nOUTPUT FORMAT:\n### Fragile Tail Exposures | ### Robustness Buffers | ### Antifragile Barbell & Optionality Design",
        "FMEA (Failure Mode and Effects Analysis)": "[METHODOLOGY FRAMEWORK: QUANTITATIVE FMEA RISK SCORING]\nQuantify and prioritize technical, legal, or operational failure modes using Risk Priority Numbers ($\\text{RPN} = S \\times O \\times D$):\n\n1. FAILURE MODE & EFFECT: Exact way each component/process step can fail and its downstream impact.\n2. SEVERITY ($S$: 1–10): Magnitude of customer, financial, safety, or regulatory harm (10 = catastrophic).\n3. OCCURRENCE ($O$: 1–10): Likelihood/frequency of the failure occurring under real load.\n4. DETECTION ($D$: 1–10): Inability of current controls to catch the fault before impact (10 = silent/undetected!).\n5. RPN MITIGATION: Every item with $\\text{RPN} > 100$ or $S \\ge 9$ mandates an immediate engineering control with re-scored target RPN.\n\nOUTPUT FORMAT:\nMarkdown Table: `Component | Failure Mode | S | O | D | RPN | Mandatory Control | Post-Fix RPN`",
        "OODA Loop (John Boyd)": "[METHODOLOGY FRAMEWORK: BOYD HIGH-TEMPO OODA LOOP]\nOutpace rapidly evolving operational or competitive environments by cycling faster and more accurately through Observe–Orient–Decide–Act:\n\n1. OBSERVE: Ingest raw real-time telemetry, market signals, logs, and adversary moves without filter lag.\n2. ORIENT (The Decisive Center): Synthesize signals against mental models, strip away outdated priors, and isolate the true mismatch.\n3. DECIDE: Commit rapidly to a clear, testable hypothesis—avoiding analysis paralysis.\n4. ACT: Execute decisively and wire immediate outcome telemetry straight back into Observation.\n\nOUTPUT FORMAT:\n[Observe: Live Signals] -> [Orient: Reframed Reality] -> [Decide: Chosen Hypothesis] -> [Act: Immediate Execution & Telemetry]",
        "Scenario Planning (Shell Matrix Method)": "[METHODOLOGY FRAMEWORK: SCENARIO PLANNING & NO-REGRET STRATEGY]\nStress-test long-term strategy across divergent, plausible future worlds driven by the 2 highest-impact, highest-uncertainty macro axes:\n\n1. SCENARIO A — ACCELERATED TAILWIND (High Growth / Favorable Regulation & Tech)\n2. SCENARIO B — STAGFLATION & FRICTION (Capital Scarcity / Cost Compression / Tightening Constraints)\n3. SCENARIO C — STRUCTURAL DISRUPTION (Paradigm Shift / Regulatory or Technological Regime Change)\n4. ROBUST PORTFOLIO: Separate **No-Regret Moves** (winning across ALL 3 scenarios) from **Contingent Options** triggered by early-warning signposts.\n\nOUTPUT FORMAT:\n[Scenario A] | [Scenario B] | [Scenario C] | [No-Regret Core Moves & Early-Warning Signposts]",
        "Monte Carlo & Expected Value Decision Tree": "[METHODOLOGY FRAMEWORK: MONTE CARLO RANGES & EXPECTED-VALUE DECISION TREE]\nEliminate point-estimate illusions by evaluating uncertain commitments across probability distributions, expected value, and ruin thresholds:\n\n1. UNCERTAINTY DISTRIBUTIONS: Define P10 (Bear), P50 (Base), and P90 (Bull) ranges for the 3–5 primary value drivers.\n2. DECISION TREE & EXPECTED VALUE ($EV$):\n   - Calculate $EV = \\sum p_i \\cdot \\text{Net Payoff}_i$ across each strategic branch including option value of staged abandonment.\n3. TAIL-RISK & RUIN CHECK (Ergo-Safety / Kelly Discipline): Verify the bottom 5% tail outcome—never accept positive EV if the left tail breaches solvency or irreversible compliance limits.\n4. STAGED TRANCHING: Structure milestone gates buying maximum information at minimum upfront capital commitment.\n\nOUTPUT FORMAT:\n### Driver Distributions (P10/P50/P90) | ### Expected-Value Tree | ### Left-Tail Solvency Check | ### Tranched Commitment Plan",
        "Swiss Cheese Model (James Reason / Defense-in-Depth)": "[METHODOLOGY FRAMEWORK: REASON SWISS CHEESE & DEFENSE-IN-DEPTH]\nArchitect independent, orthogonal defensive layers so no single human error, model hallucination, or component fault can propagate to catastrophic loss:\n\n1. HAZARD & UNACCEPTABLE LOSS: Specify the exact high-severity incident to block (security breach, erroneous wire/trade, production outage, compliance breach).\n2. FOUR ORTHOGONAL DEFENSE LAYERS (Slices):\n   - Layer 1 (Intrinsic Prevention / Poka-Yoke): Schema/type constraints making invalid states unrepresentable.\n   - Layer 2 (Automated Gatekeeping): RBAC permissions, pre-flight validation, dual-control HITL approvals.\n   - Layer 3 (Runtime Detection & Circuit Breakers): Anomaly telemetry, rate limits, automated halt thresholds.\n   - Layer 4 (Blast-Radius Containment & Recovery): Sandboxing, atomic rollbacks, immutable offline backups.\n3. COMMON-MODE ELIMINATION: Audit and eliminate shared dependencies that could align holes across multiple layers simultaneously.\n\nOUTPUT FORMAT:\n### Target Hazard | ### Layers 1–4 & Latent Holes | ### Common-Mode Decoupling & Hardening Plan",
    },
}

import copy

DEFAULT_CATEGORIZED_FRAMEWORKS = copy.deepcopy(CATEGORIZED_FRAMEWORKS)
DEFAULT_CATEGORIZED_FRAMEWORKS_EN = copy.deepcopy(CATEGORIZED_FRAMEWORKS_EN)

def get_flat_framework_map(lang: str = "de") -> dict:
    flat = {}
    sources = (
        [CATEGORIZED_FRAMEWORKS, CATEGORIZED_FRAMEWORKS_EN]
        if not str(lang or "").lower().startswith("en")
        else [CATEGORIZED_FRAMEWORKS_EN, CATEGORIZED_FRAMEWORKS]
    )
    # Load secondary first, primary second so primary wins on identical keys
    for src in reversed(sources):
        for cat, frameworks in src.items():
            for fw_name, fw_val in frameworks.items():
                if isinstance(fw_val, dict):
                    flat[fw_name] = {
                        "summary": fw_val.get("summary", fw_name),
                        "system_instruction": fw_val.get("system_instruction", fw_val.get("summary", ""))
                    }
                else:
                    flat[fw_name] = {
                        "summary": fw_val,
                        "system_instruction": fw_val
                    }
    return flat

UNIVERSAL_METHODOLOGY_HEADER = """[UNIVERSAL METHODOLOGY ENGINE HEADER]
Du bist ein kompromissloser Experten-Analyst im AgentOS. 
Deine Aufgabe ist es, die Problemstellung ausschließlich durch die Linse des zugewiesenen Frameworks zu zerlegen.

STRIKTE REGELN:
1. Keine Einleitungen, kein Höflichkeits-Fluff, kein "Gerne helfe ich dir dabei".
2. Denke Schritt für Schritt (Chain-of-Thought), bevor du antwortest.
3. Überspringe KEINE Phase des Frameworks. Jeder Abschnitt muss fundiert ausgearbeitet sein.
4. Sei konkret: Nenne Zahlen, Code-Schnipsel, Werkzeuge, spezifische Risiken und eindeutige Befehle statt vager Ratschläge.
5. Halte dich exakt an das vorgegebene AUSGABE-FORMAT.
========================================"""

UNIVERSAL_METHODOLOGY_HEADER_EN = """[UNIVERSAL METHODOLOGY ENGINE HEADER]
You are an uncompromising principal analyst within Archon OS.
Your mandate is to dissect the problem statement strictly through the lens of the assigned methodology framework.

STRICT RULES:
1. Zero introductions, zero pleasantries, zero "Here is the analysis".
2. Reason step-by-step before formulating conclusions.
3. Skip NO phase of the framework. Every section must be rigorously substantiated.
4. Be concrete: provide numbers, formulas, code snippets, specific risks, and unambiguous decisions rather than vague advice.
5. Adhere strictly to the specified OUTPUT FORMAT.
========================================"""

def _is_english_framework(name: str) -> bool:
    for fws in CATEGORIZED_FRAMEWORKS_EN.values():
        if name in fws:
            # Check if it's uniquely in EN or contains METHODOLOGY FRAMEWORK
            val = fws[name]
            if isinstance(val, str) and "[METHODOLOGY FRAMEWORK:" in val:
                for de_fws in CATEGORIZED_FRAMEWORKS.values():
                    if name in de_fws:
                        return False
                return True
    return False

def get_framework_info(name: str, lang: str = "") -> dict:
    eff_lang = (lang or os.environ.get("ARCHON_LANGUAGE") or "").strip().lower()
    flat = get_flat_framework_map(lang="en" if eff_lang.startswith("en") else "de")
    if name in flat:
        return flat[name]
    if eff_lang.startswith("en"):
        return {
            "summary": "Conduct a structured, multi-perspective executive debate grounded in verifiable evidence, explicit trade-offs, and actionable synthesis.",
            "system_instruction": "Conduct a structured, multi-perspective executive debate grounded in verifiable evidence, explicit trade-offs, and actionable synthesis.",
        }
    return flat.get("Steffi Kieffer Boardroom", {
        "summary": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion.",
        "system_instruction": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion."
    })

def build_final_system_prompt(selected_framework_id: str, base_system_prompt: str = "", lang: str = "") -> str:
    """
    Compiles the final Boardroom system prompt from:
    1. UNIVERSAL_METHODOLOGY_HEADER (DE or EN)
    2. Selected framework methodology instruction
    3. Optional specialist base system prompt
    """
    eff_lang = (lang or os.environ.get("ARCHON_LANGUAGE") or "").strip().lower()
    use_en = eff_lang.startswith("en") or _is_english_framework(selected_framework_id)
    fw_info = get_framework_info(selected_framework_id, lang="en" if use_en else "de")
    fw_instruction = fw_info.get("system_instruction", "") if fw_info else ""

    header = UNIVERSAL_METHODOLOGY_HEADER_EN if use_en else UNIVERSAL_METHODOLOGY_HEADER
    parts = [header.strip()]
    if base_system_prompt and base_system_prompt.strip():
        parts.append(base_system_prompt.strip())
    if fw_instruction and fw_instruction.strip():
        parts.append(f"[SELECTED METHODOLOGY: {selected_framework_id}]\n{fw_instruction.strip()}")

    return "\n\n".join(parts)


def _boardroom_tier(agent: dict) -> str:
    """Tier aus der verifizierten Slot-SSOT (D14/MED: Produzent fehlt sonst)."""
    from backend.consensus_gate import _infer_tier

    return str(agent.get("tier") or _infer_tier(str(agent.get("id") or "")))


def _boardroom_guardrail_result(res: dict) -> Dict[str, Any]:
    """D14/HIGH: strukturiertes Guardrail-Result aus dem Dispatch-Ergebnis.

    Die Felder wandern als bool/str in das ``agent_response``-Event und werden
    von ``resolve_debate_consensus()`` als hartes Veto ausgewertet — kein
    Freitext-Marker, keine Mehrheitsabstimmung ueber einen Policy-Verstoß.
    """
    out: Dict[str, Any] = {
        "policy_violation": False,
        "guardrail_violation": False,
        "severity": None,
        "source_trace_id": None,
    }
    if not isinstance(res, dict):
        return out
    gr = res.get("guardrail_result")
    if isinstance(gr, dict):
        out["policy_violation"] = bool(gr.get("policy_violation"))
        out["guardrail_violation"] = bool(gr.get("guardrail_violation"))
        out["severity"] = gr.get("severity")
        out["source_trace_id"] = gr.get("source_trace_id")
    for key in ("policy_violation", "guardrail_violation"):
        if bool(res.get(key)):
            out[key] = True
    out["severity"] = str(out["severity"] or res.get("severity") or "") or None
    _trace = out["source_trace_id"] or res.get("source_trace_id") or res.get("trace_id")
    out["source_trace_id"] = str(_trace) if _trace else None
    if not out["source_trace_id"]:
        try:
            from backend.trace_context import current_trace_id
            out["source_trace_id"] = str(current_trace_id() or "") or None
        except Exception:
            pass
    # Ein vom Governance-Gate blockierter Dispatch ist immer ein Veto, nie
    # eine zaehlbare Ja-Stimme.
    if str(res.get("status") or "").strip().lower() == "blocked":
        out["guardrail_violation"] = True
        out["policy_violation"] = True
        out["severity"] = out["severity"] or "high"
    return out


def _boardroom_cancellation_guard(fn):
    """
    Wrappt den kompletten Debatten-Generator:
    Eine asyncio.CancelledError (z. B. aus ``token.check()``) wird in EIN
    finales ``cancelled``-Event uebersetzt und der Generator kehrt sauber
    zurueck. Der Abbruch wird damit nicht still geschluckt, sondern dem
    SSE-Consumer explizit gemeldet.
    """
    @functools.wraps(fn)
    async def _wrapped(*args, **kwargs):
        last_round = 0
        try:
            async for ev in fn(*args, **kwargs):
                if isinstance(ev, dict) and isinstance(ev.get("round"), int):
                    last_round = ev["round"]
                yield ev
        except asyncio.CancelledError:
            yield {
                "type": "cancelled",
                "round": last_round,
                "content": "Debatte abgebrochen",
            }
            return
    return _wrapped


async def stream_boardroom_debate(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30,
    use_moa: bool = False,
    moa_reference_models: list = None,
    moa_aggregator: dict = None,
    cancel_token: Optional[Any] = None,
    task_id: Optional[str] = None,
):
    """Oeffentlicher Entry-Point: BEIDE Boardroom-Pfade hängen am Killswitch.

    Vorher erzeugte der Pfad ohne expliziten Token ein ROOT-Token, das
    cancel_scope('boardroom') nie erreichte und nie aufgeräumt wurde
    (Audit 23.11.2026).
    """
    from backend.cancellation import clear_scope, get_child_token
    own_token = cancel_token is None
    if own_token:
        cancel_token = get_child_token("boardroom", f"boardroom:{time.time_ns()}")
    # H6 (Audit 23.11.2026): der Kill-Switch setzte nur ein Flag, aber der
    # laufende HTTP-LLM-Call blieb am Leben. Task registrieren wie in
    # archon/core/orchestration.py — cancel() bricht ihn jetzt aktiv ab.
    # C10: frueher wurde ein Registrierungsfehler mit `pass` verschluckt und
    # die Debatte lief ohne wirksamen Abbruch weiter (fail-open). Jetzt
    # fail-closed — inkl. Scope-Cleanup im selben try/finally.
    try:
        try:
            cancel_token.register_task(asyncio.current_task())
        except Exception as exc:
            logger.error("[Boardroom] Kill-Switch-Registrierung fehlgeschlagen: %s", exc)
            raise RuntimeError("Kill-Switch konnte nicht registriert werden") from exc
        async for ev in _stream_boardroom_debate_inner(
            task=task,
            max_rounds=max_rounds,
            chairman_id=chairman_id,
            active_agents=active_agents,
            framework=framework,
            timeout=timeout,
            use_moa=use_moa,
            moa_reference_models=moa_reference_models,
            moa_aggregator=moa_aggregator,
            cancel_token=cancel_token,
            task_id=task_id,
        ):
            yield ev
    finally:
        if own_token:
            clear_scope(cancel_token.scope)


@_boardroom_cancellation_guard
async def _stream_boardroom_debate_inner(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30,
    use_moa: bool = False,
    moa_reference_models: list = None,
    moa_aggregator: dict = None,
    cancel_token: Optional[Any] = None,
    task_id: Optional[str] = None
):
    """
    Asynchroner Generator für Live-Streaming der 'AI Boardroom' Multi-Agenten Debatte:
    Streamt Events schrittweise (start, chairman_init, round_start, agent_response,
    consensus_reached, final_synthesis, done). Bei Abbruchueber das cancel_token
    folgt ein abschliessendes 'cancelled'-Event (siehe _boardroom_cancellation_guard).
    """
    if cancel_token is None:
        # Import hier, um Import-Zyklen zwischen Dispatcher und Backend zu vermeiden.
        from backend.cancellation import get_token
        cancel_token = get_token(f"boardroom:{task_id or chairman_id}")
    token = cancel_token

    if not active_agents:
        yield {"type": "error", "content": "Keine aktiven Agenten für den Boardroom vorhanden."}
        return
    
    framework_info = get_framework_info(framework)
    framework_instruction = framework_info["system_instruction"]

    # Chairman ist das erste Element, alle weiteren Elemente sind die Experten-Slots
    chairman = active_agents[0]
    expert_agents = active_agents[1:] if len(active_agents) > 1 else [chairman]

    yield {
        "type": "start",
        "task": task,
        "framework": framework,
        "chairman": chairman,
        "max_rounds": max_rounds
    }
    
    # 1. CHAIRMAN INITIALIZATION
    chairman_init_prompt = (
        f"Du bist der Moderator / Chairman des AI Boardrooms.\n"
        f"Strategische Aufgabe: '{task}'\n"
        f"METHODIK-FRAMEWORK: {framework}\n"
        f"Wende das Framework '{framework}' an (vollstaendige Instruktion im System-Prompt).\n\n"
        f"Aufgabe: Rahmen das Problem kurz ein, definiere Bewertungskriterien im Sinne des Frameworks '{framework}' "
        f"und weise den Experten-Agenten ({', '.join([a['name'] for a in expert_agents])}) "
        f"erste Fokusbereiche für die Debatte zu."
    )
    
    chairman_sys_prompt = build_final_system_prompt(framework, chairman.get("prompt", ""))

    token.check()  # Abbruch vor dem ersten Dispatch beachten
    res_init = await dispatch_to_external_agent(
        agent_id=chairman["id"],
        agent_name=chairman["name"],
        prompt=chairman_init_prompt,
        role=chairman.get("role", "Orchestrator"),
        system_prompt=chairman_sys_prompt,
        model=chairman.get("model", "deepseek/deepseek-chat"),
        timeout=timeout,
        provider=chairman.get("provider", ""),
        reasoning_level=chairman.get("reasoning_level", "medium")
    )
    
    init_text = res_init.get("content", f"Problemeinrahmung für '{task}' gestartet.")
    yield {
        "type": "chairman_init",
        "round": 0,
        "agent_id": chairman["id"],
        "agent_name": chairman["name"],
        "role": chairman.get("role", "Orchestrator"),
        "model": chairman.get("model") or "deepseek/deepseek-chat",
        "content": init_text
    }

    # 2. ROUND-BASED DEBATE
    def _prompt_transcript(full: str, limit: int = 24000) -> str:
        """W5 / Zielkonflikt Z5: das VOLLE Protokoll bleibt in Historie und
        Audit-Kette (Nachvollziehbarkeit), aber in die LLM-Prompts geht nur
        ein gekürztes Fenster. Sonst wachsen Eingabe-Tokens mit O(R²·A)."""
        if len(full) <= limit:
            return full
        head = full[:limit // 3]
        tail = full[-(limit - limit // 3):]
        return (
            head
            + "\n\n... [gekürzt — vollständiges Protokoll in der Audit-Historie] ...\n\n"
            + tail
        )

    running_transcript = f"--- MODERATOR INITIALISIERUNG ---\n{init_text}\n\n"
    # Alle Agent-Aussagen dieser Debatte fuer die offline Konsensauswertung sammeln.
    debate_statements: List[Any] = []
    # D02/D14: Konsens wird in JEDER Runde — auch der letzten — geprueft.
    consensus: Dict[str, Any] = {
        "consensus_reached": False,
        "verdict": "NO_CONSENSUS",
        "veto_by": None,
        "evidence": [],
        "tie_break_rule": "executive>lead>specialist>no_consensus",
        "authority_weights": {"executive": 3, "lead": 2, "specialist": 1},
    }
    critique_text = ""
    
    for round_num in range(1, max_rounds + 1):
        yield {
            "type": "round_start",
            "round": round_num,
            "max_rounds": max_rounds
        }
        # Abbruch zu Beginn jeder Runde pruefen (nach round_start, damit das
        # cancelled-Event die korrekte Rundennummer trägt).
        token.check()
        # H5 (Audit 23.11.2026): der Circuit-Breaker existierte nur im
        # Master-Chat-Pfad. Ping-Pong/Endlosschleifen in Boardroom- und
        # Subagenten-Ketten wurden nicht erkannt. Wir übergeben nur ein
        # Fenster der letzten Aussagen, damit die globale max_steps-Grenze
        # (15) nicht fälschlich bei 10 Agenten × 2 Runden auslöst.
        try:
            from backend.agent_router import router_instance
            # D13/S-13.4: feste 8er-Fenster konnte die max_steps-Grenze (15)
            # nie erreichen. Die Policy-Fenstergröße aus trajectory_budget
            # verwenden (>= max_steps+1).
            _window = max(8, int(router_instance.guard_window_size()))
            _recent = debate_statements[-_window:]
            _cb_messages = [
                {"role": "agent", "content": str(s.get("content", ""))}
                for s in _recent if isinstance(s, dict)
            ]
            _cb = router_instance.check_loop_or_circuit_breaker(_cb_messages)
            if _cb.get("tripped"):
                yield {
                    "type": "cancelled",
                    "round": round_num,
                    "reason": _cb.get("reason", "circuit_breaker"),
                    "content": "Debatte durch Circuit-Breaker beendet (Endlosschleife erkannt).",
                }
                return
        except Exception as _cb_exc:
            # D13: Guard-Ausfall darf die Debatte nicht unkontrolliert
            # weiterlaufen lassen (fail-open) — hart abbrechen.
            logger.error("[Boardroom] Circuit-Breaker-Prüfung fehlgeschlagen (fail-closed): %s", _cb_exc)
            yield {
                "type": "cancelled",
                "round": round_num,
                "reason": "circuit_breaker_unavailable",
                "content": "Debatte abgebrochen: Loop-Guard nicht verfügbar.",
            }
            return

        if round_num == 1 and len(expert_agents) > 1:
            async def _dispatch_agent(ag):
                prompt = (
                    f"--- AI BOARDROOM DEBATTE - RUNDE {round_num} VON {max_rounds} ---\n"
                    f"Ursprüngliche Aufgabe: {task}\n"
                    f"METHODIK-FRAMEWORK: {framework}\n"
                    f"Wende das Framework '{framework}' an (vollstaendige Instruktion im System-Prompt).\n\n"
                    f"Bisheriger Diskussionsverlauf:\n{_prompt_transcript(running_transcript)}\n\n"
                    f"Instruktion: Reagiere auf die Initialisierung des Moderators. "
                    f"Behalte strikt deine Rolle ({ag.get('role', 'Expert')}) bei und wende das Framework '{framework}' an. "
                    f"Formuliere deine klare Fachperspektive. "
                    f"Beende deine Aussage mit EINER eigenen Zeile, die genau einen der "
                    f"Marker enthält: `KONSENS_ERREICHT` (du stimmst zu) oder `KEIN KONSENS` "
                    f"(du widersprichst oder hast Vorbehalte). Ohne Marker zählt deine "
                    f"Aussage nicht als Konsens. Wenn du einen Regel-/Policy-Verstoß "
                    f"feststellst, schreibe zusätzlich eine eigene Zeile `POLICY_VIOLATION` "
                    f"— dieses Veto ist stärker als jede Mehrheit."
                )
                sys_prompt = build_final_system_prompt(framework, ag.get("prompt", ""))
                token.check()  # Abbruch vor jedem Agent-Dispatch beachten
                res = await dispatch_to_external_agent(
                    agent_id=ag["id"],
                    agent_name=ag["name"],
                    prompt=prompt,
                    role=ag.get("role", "Expert"),
                    system_prompt=sys_prompt,
                    model=ag.get("model", "deepseek/deepseek-chat"),
                    timeout=timeout,
                    provider=ag.get("provider", ""),
                    reasoning_level=ag.get("reasoning_level", "medium")
                )
                return {
                    "type": "agent_response",
                    "round": round_num,
                    "agent_id": ag["id"],
                    "agent_name": ag["name"],
                    "role": ag.get("role", "Expert"),
                    "model": ag.get("model") or "deepseek/deepseek-chat",
                    # D14: Tier aus verifizierter Slot-SSOT + strukturiertes
                    # Guardrail-Result (kein Freitext-Marker) am Event-Grenze.
                    "tier": _boardroom_tier(ag),
                    **_boardroom_guardrail_result(res),
                    "content": res.get("content", "Keine Antwort.")
                }

            from archon.core.task_registry import spawn as _tracked_spawn
            tasks = [_tracked_spawn(_dispatch_agent(a), name=f"boardroom_agent_{a.get('id')}") for a in expert_agents]
            try:
              for coro in asyncio.as_completed(tasks):
                res_event = await coro
                debate_statements.append(res_event)
                running_transcript += f"[{res_event['agent_name']} ({res_event['role']}) - Runde {round_num}]:\n{res_event['content']}\n\n"
                # Replicate live into task_events for #boardroom and #all-stream in Operations
                try:
                    def _persist_boardroom_turn() -> None:
                        from backend.operations_api import _get_kanban_connection
                        _k_conn = _get_kanban_connection()
                        try:
                            _k_now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                            _k_payload = json.dumps({
                                "author": res_event["agent_id"],
                                "message": f"[BOARDROOM RUNDE {round_num}] {res_event['content']}",
                                "target": "boardroom",
                                "broadcast": True,
                                "framework": framework
                            }, ensure_ascii=False)
                            _k_conn.execute("""
                                INSERT INTO task_events (task_id, kind, payload, created_at)
                                VALUES (?, 'boardroom_turn', ?, ?)
                            """, (f"boardroom_{int(time.time())}", _k_payload, _k_now))
                            _k_conn.commit()
                        finally:
                            _k_conn.close()
                    # Sync SQLite pro Agent-Antwort blockiert den Event-Loop
                    # (Audit 23.11.2026) — in den Threadpool auslagern.
                    await asyncio.to_thread(_persist_boardroom_turn)
                except Exception as _e_rep:
                    logger.debug(f"[Dispatcher] Boardroom-Turn Kanban-Protokollierung fehlgeschlagen: {_e_rep}")

                yield res_event
            finally:
                # Bei Client-Disconnect/Cancel duerfen keine verwaisten
                # LLM-Calls weiterlaufen und Kanban-Events schreiben.
                for t in tasks:
                    if not t.done():
                        t.cancel()
                # D07/MED (A9): Result-Liste auswerten statt verwerfen.
                # CancelledError ist der erwartete Normalfall; jede andere
                # BaseException ist ein fehlgeschlagener Abbruch -> Audit.
                try:
                    cancel_results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    # Bei Timeout werden nicht beendete Tasks NICHT aus der
                    # Registry geloescht, sondern als failed_cancels quittiert.
                    cancel_results = []
                    for t in tasks:
                        if not t.done():
                            _record_failed_cancel(
                                t.get_name() or "boardroom_agent",
                                "cancel_timeout: Task nicht innerhalb von 10s beendet",
                            )
                for t, cres in zip(tasks, cancel_results):
                    if isinstance(cres, asyncio.CancelledError):
                        continue
                    if isinstance(cres, BaseException):
                        _record_failed_cancel(
                            t.get_name() or "boardroom_agent",
                            f"{type(cres).__name__}: {cres}",
                        )
        else:
            for agent in expert_agents:
                agent_prompt = (
                    f"--- AI BOARDROOM DEBATTE - RUNDE {round_num} VON {max_rounds} ---\n"
                    f"Ursprüngliche Aufgabe: {task}\n"
                    f"METHODIK-FRAMEWORK: {framework}\n"
                    f"Wende das Framework '{framework}' an (vollstaendige Instruktion im System-Prompt).\n\n"
                    f"Bisheriger Diskussionsverlauf:\n{_prompt_transcript(running_transcript)}\n\n"
                    f"Instruktion: Reagiere auf die Aussagen der anderen Agenten. "
                    f"Behalte strikt deine Rolle ({agent.get('role', 'Expert')}) bei und wende das Framework '{framework}' an. "
                    f"Hinterfrage, validiere oder erweitere die Argumente deiner Vorredner explizit. "
                    f"Beende deine Aussage mit EINER eigenen Zeile, die genau einen der "
                    f"Marker enthält: `KONSENS_ERREICHT` (du stimmst zu) oder `KEIN KONSENS` "
                    f"(du widersprichst oder hast Vorbehalte). Ohne Marker zählt deine "
                    f"Aussage nicht als Konsens. Wenn du einen Regel-/Policy-Verstoß "
                    f"feststellst, schreibe zusätzlich eine eigene Zeile `POLICY_VIOLATION` "
                    f"— dieses Veto ist stärker als jede Mehrheit."
                )
                
                agent_sys_prompt = build_final_system_prompt(framework, agent.get("prompt", ""))

                token.check()  # Abbruch vor jedem Agent-Dispatch beachten
                res = await dispatch_to_external_agent(
                    agent_id=agent["id"],
                    agent_name=agent["name"],
                    prompt=agent_prompt,
                    role=agent.get("role", "Expert"),
                    system_prompt=agent_sys_prompt,
                    model=agent.get("model", "deepseek/deepseek-chat"),
                    timeout=timeout,
                    provider=agent.get("provider", ""),
                    reasoning_level=agent.get("reasoning_level", "medium")
                )
                
                resp_content = res.get("content", "Keine Antwort.")
                ev_agent = {
                    "type": "agent_response",
                    "round": round_num,
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "role": agent.get("role", "Expert"),
                    "model": agent.get("model") or "deepseek/deepseek-chat",
                    "tier": _boardroom_tier(agent),
                    **_boardroom_guardrail_result(res),
                    "content": resp_content
                }
                debate_statements.append(ev_agent)
                running_transcript += f"[{agent['name']} ({agent.get('role', 'Expert')}) - Runde {round_num}]:\n{resp_content}\n\n"
                yield ev_agent
        
        # 3. CONSENSUS CHECK & WATCHDOG (deterministisch, OFFLINE, kein LLM)
        # M-1: Explizite Negation schlaegt positive Marker; unklar = kein Konsens.
        # D02/D14/BLOCKER: AUCH in der letzten Runde ausfuehren. Der verdict
        # wird konsumiert und bestimmt, ob ueberhaupt synthetisiert wird.
        from backend.consensus_gate import resolve_debate_consensus
        consensus = resolve_debate_consensus(
            debate_statements,
            authority={
                str(s.get("agent_id") or ""): str(s.get("tier") or "")
                for s in debate_statements if isinstance(s, dict) and s.get("tier")
            } or None,
        )
        if consensus.get("consensus_reached"):
            yield {
                "type": "consensus_reached",
                "round": round_num,
                "content": f"Konsens in Runde {round_num} erzielt.",
                "yes_votes": consensus["yes_votes"],
                "total_votes": consensus["total_votes"],
                "required_votes": consensus["required_votes"],
                "verdict": consensus["verdict"],
                "evidence": consensus["evidence"],
            }
            break
        if round_num == max_rounds:
            yield {
                "type": "no_consensus",
                "round": round_num,
                "verdict": consensus["verdict"],
                "veto_by": consensus.get("veto_by"),
                "content": "Kein Konsens nach der letzten Debattenrunde — Eskalation an HITL.",
            }

    # 3a. DEDIZIERTER CRITIQUE-DISPATCH (D14/HIGH) — VOR der finalen
    # Konsensauswertung. Der Critique ist ein echter Veto-Produzent, keine
    # Prompt-Floskel nach der bereits gefassten Entscheidung.
    token.check()
    critique_text = ""
    critique_error = False
    try:
        critique_prompt = (
            f"Du bist der unabhaengige Boardroom-Critic (Adversarial Review).\n"
            f"Aufgabe: '{task}' | Framework: '{framework}'\n\n"
            f"Debattenprotokoll:\n{_prompt_transcript(running_transcript)}\n\n"
            f"Pruefe schonungslos: logische Brueche, unbelegte Behauptungen, "
            f"Regel-/Policy-Verstoesse, blinde Flecken und ungeloeste Konflikte. "
            f"Benenne mindestens ein konkretes Risiko. Formuliere deine Befunde knapp.\n"
            f"Wenn du einen Regel-/Policy-Verstoß findest, schreibe zusaetzlich eine "
            f"eigene Zeile `POLICY_VIOLATION` — dieses Veto ist staerker als jede Mehrheit."
        )
        res_critique = await dispatch_to_external_agent(
            agent_id="boardroom-critic",
            agent_name="Boardroom Critic",
            prompt=critique_prompt,
            role="Adversarial Reviewer",
            system_prompt=(
                "Du bist ein extrem kritischer, unabhaengiger Revisor. "
                "Du stimmst keiner Position zu, bevor du sie nicht widerlegt hast. "
                "Antworte nur mit praezisen Befunden."
            ),
            model=chairman.get("model", "deepseek/deepseek-chat"),
            timeout=timeout,
        )
        critique_text = str(res_critique.get("content") or "").strip()
        critique_ev = {
            "type": "critique",
            "agent_id": "boardroom-critic",
            "agent_name": "Boardroom Critic",
            "role": "Adversarial Reviewer",
            "tier": "specialist",
            **_boardroom_guardrail_result(res_critique),
            "content": critique_text,
        }
        debate_statements.append(critique_ev)
        running_transcript += f"\n--- CRITIQUE (Adversarial Review) ---\n{critique_text}\n\n"
        yield critique_ev
    except Exception as critique_exc:
        critique_error = True
        logger.error("[Boardroom] Critique-Dispatch fehlgeschlagen (fail-closed): %s", critique_exc)
        yield {"type": "critique_error", "content": str(critique_exc)}

    # 4. FINALE KONSENSAUSWERTUNG NACH DER KRITIK (D14/HIGH).
    # Der Critique kann einen vorherigen CONSENSUS_REACHED noch kippen.
    from backend.consensus_gate import resolve_debate_consensus
    consensus = resolve_debate_consensus(
        debate_statements,
        authority={
            str(s.get("agent_id") or ""): str(s.get("tier") or "")
            for s in debate_statements if isinstance(s, dict) and s.get("tier")
        } or None,
    )
    if critique_error:
        # Fail-closed: ohne abgeschlossene Kritik kein Finalbeschluss (HITL).
        consensus = dict(consensus)
        consensus["consensus_reached"] = False
        consensus["verdict"] = "NO_CONSENSUS"
        consensus["veto_by"] = "boardroom-critic"
        consensus["critique_error"] = True
        yield {
            "type": "no_consensus",
            "verdict": "NO_CONSENSUS",
            "veto_by": "boardroom-critic",
            "critique_error": True,
            "content": "Critique nicht verfuegbar — kein Finalbeschluss, HITL erforderlich.",
        }
    final_verdict = str(consensus.get("verdict") or "NO_CONSENSUS").upper()
    has_final_decision = final_verdict.startswith("CONSENSUS_REACHED")

    # 4b. FINAL SYNTHESIS (STANDARD ODER MIXTURE OF AGENTS - MoA)
    # D02/BLOCKER: Bei NO_CONSENSUS garantiert KEINE finale Entscheidung.
    no_consensus_mode = not has_final_decision
    synthesis_directive = (
        "Erstelle NUR eine Konfliktanalyse im Markdown-Format:\n"
        "### Konflikte / offene Punkte\n"
        "### Policy-/Guardrail-Befunde und Eskalationsbedarf\n"
        "SCHREIBE KEINE finale Entscheidung und KEINEN Aktionsplan."
        if no_consensus_mode else
        "Erstelle eine finale, strukturierte Synthese im Markdown-Format mit folgenden 3 Abschnitten:\n"
        "### 1. Key Consensus Points (Haupt-Konsenspunkte)\n"
        "### 2. Unresolved Risks / Counterarguments (Offene Risiken & Gegenargumente)\n"
        "### 3. Final Actionable Decision (Finale Entscheidung & konkreter Aktionsplan)"
    )
    if critique_text:
        synthesis_directive += f"\n\nADVERSARIAL CRITIQUE (zwingend zu beruecksichtigen):\n{critique_text[:2000]}"
    synthesis_text = ""
    if use_moa:
        # Default Referenz-Modelle falls keine übergeben wurden
        ref_models = moa_reference_models or [
            {"model": "deepseek/deepseek-chat", "provider": "openrouter", "name": "DeepSeek V3 (MoA Ref)"},
            {"model": "anthropic/claude-3.5-sonnet", "provider": "openrouter", "name": "Claude 3.5 Sonnet (MoA Ref)"},
            {"model": "meta-llama/llama-3.3-70b-instruct", "provider": "openrouter", "name": "Llama 3.3 70B (MoA Ref)"}
        ]
        agg_model = moa_aggregator or {
            "model": chairman.get("model", "deepseek/deepseek-chat"),
            "provider": chairman.get("provider", "openrouter"),
            "name": f"{chairman['name']} (MoA Aggregator)"
        }

        yield {
            "type": "moa_start",
            "reference_models": ref_models,
            "aggregator": agg_model,
            "message": f"MoA aktiviert: Starte parallele Layer-1 Synthese über {len(ref_models)} Sprachmodelle..."
        }

        moa_prompt = (
            f"Du bist ein unabhängiges Referenz-Modell im Mixture-of-Agents (MoA) Verbund.\n"
            f"Debatten-Aufgabe: '{task}'\n"
            f"Framework: '{framework}'\n\n"
            f"Diskussionsprotokoll:\n{_prompt_transcript(running_transcript)}\n\n"
            f"Erstelle eine präzise, eigenständige Entscheidungsvorlage mit Konsenspunkten, offenen Risiken und Empfehlungen."
        )

        async def _run_moa_ref(m_item):
            m_id = m_item.get("model", "deepseek/deepseek-chat")
            m_prov = m_item.get("provider", "openrouter")
            m_name = m_item.get("name", m_id)
            token.check()  # Abbruch vor jedem Agent-Dispatch beachten
            try:
                res = await dispatch_to_external_agent(
                    agent_id=f"moa_ref_{m_name}",
                    agent_name=m_name,
                    prompt=moa_prompt,
                    role="MoA Reference Model",
                    system_prompt=f"Du bist {m_name}. Liefere eine objektive, strukturierte Entscheidungsvorlage.",
                    model=m_id,
                    provider=m_prov,
                    timeout=timeout
                )
                return {"model": m_id, "provider": m_prov, "name": m_name, "content": res.get("content", ""), "status": "ok"}
            except Exception as e:
                return {"model": m_id, "provider": m_prov, "name": m_name, "content": f"Fehler bei {m_name}: {e}", "status": "error"}

        moa_tasks = [asyncio.create_task(_run_moa_ref(m)) for m in ref_models]
        moa_results = await asyncio.gather(*moa_tasks)

        running_transcript += "\n--- MIXTURE OF AGENTS (MoA) LAYER-1 REFERENZEN ---\n"
        for r in moa_results:
            running_transcript += f"[{r['name']}]:\n{r['content']}\n\n"
            yield {
                "type": "moa_ref_done",
                "model": r["model"],
                "name": r["name"],
                "status": r["status"],
                "content": r["content"]
            }

        # Jetzt der Aggregator
        agg_prompt = (
            f"Du bist der MoA-Aggregator (Mixture of Agents) für den AI Boardroom.\n"
            f"Aufgabe: '{task}' | Framework: '{framework}'\n\n"
            f"Vorheriger Diskussionsverlauf:\n{_prompt_transcript(running_transcript)}\n\n"
            f"Die folgenden Referenzmodelle haben unabhängig voneinander Analysen geliefert:\n"
        )
        for idx, r in enumerate(moa_results):
            agg_prompt += f"=== MODELL {idx+1}: {r['name']} ({r['model']}) ===\n{r['content']}\n\n"
        
        agg_prompt += (
            f"Synthetisiere als Aggregator alle Perspektiven:\n"
            f"1. Extrahiere die stärksten Konsenspunkte aller Modelle\n"
            f"2. Hebe Kontroversen, blinde Flecken oder Risiken hervor\n"
            f"3. {synthesis_directive}"
        )

        yield {
            "type": "moa_aggregating",
            "aggregator": agg_model,
            "message": f"Aggregator {agg_model.get('name', 'Chair')} synthetisiert alle Layer-1 Ergebnisse..."
        }

        token.check()  # Abbruch vor dem Aggregator-Dispatch beachten
        res_agg = await dispatch_to_external_agent(
            agent_id=chairman["id"],
            agent_name=agg_model.get("name", chairman["name"]),
            prompt=agg_prompt,
            role="MoA Aggregator",
            system_prompt=chairman_sys_prompt,
            model=agg_model.get("model", chairman.get("model", "deepseek/deepseek-chat")),
            provider=agg_model.get("provider", chairman.get("provider", "openrouter")),
            timeout=timeout
        )
        synthesis_text = res_agg.get("content", "MoA Aggregator konnte keine Synthese erstellen.")
    else:
        synthesis_prompt = (
            f"Du bist der Chairman ({chairman['name']}).\n"
            f"Die Debatte zu '{task}' unter Anwendung des Frameworks '{framework}' ist beendet.\n"
            f"Konsens-Status: {final_verdict}\n"
            f"Wende das Framework '{framework}' an (vollstaendige Instruktion im System-Prompt).\n\n"
            f"Gesamter Diskussionsverlauf:\n{_prompt_transcript(running_transcript)}\n\n"
            f"{synthesis_directive}"
        )
    
        token.check()  # Abbruch vor dem Synthese-Dispatch beachten
        res_synth = await dispatch_to_external_agent(
            agent_id=chairman["id"],
            agent_name=chairman["name"],
            prompt=synthesis_prompt,
            role=chairman.get("role", "Orchestrator"),
            system_prompt=chairman_sys_prompt,
            model=chairman.get("model", "deepseek/deepseek-chat"),
            timeout=timeout,
            provider=chairman.get("provider", ""),
            reasoning_level=chairman.get("reasoning_level", "medium")
        )

        synthesis_text = res_synth.get("content", "Synthese konnte nicht erstellt werden.")
    
    yield {
        "type": "final_synthesis",
        "agent_id": chairman["id"],
        "agent_name": chairman["name"],
        "role": chairman.get("role", "Orchestrator"),
        "model": chairman.get("model") or "deepseek/deepseek-chat",
        "content": synthesis_text,
        "consensus_status": final_verdict,
        "is_final_decision": has_final_decision,
    }

    yield {
        "type": "done",
        "transcript": running_transcript,
        "synthesis": synthesis_text,
        "consensus_status": final_verdict,
        "consensus_verdict": final_verdict,
        "consensus_reached": bool(consensus.get("consensus_reached")),
        "veto_by": consensus.get("veto_by"),
        "veto_marker": "POLICY_VIOLATION" if final_verdict == "NO_CONSENSUS_POLICY_VIOLATION" else None,
        "critique": critique_text,
        "critique_error": critique_error,
        "is_final_decision": has_final_decision,
        "evidence": consensus.get("evidence", []),
    }


async def run_boardroom_debate(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30,
    use_moa: bool = False,
    moa_reference_models: list = None,
    moa_aggregator: dict = None
) -> dict:
    events = []
    # D01/S-1.7: solange kein done-Event mit Synthese eingegangen ist, darf
    # das Ergebnis NICHT "success" sein (sonst wird eine leere Debatte als
    # erfolgreiche Entscheidung archiviert).
    done_seen = False
    task_res = {
        "status": "incomplete",
        "task": task,
        "framework": framework,
        "chairman": active_agents[0] if active_agents else {},
        "max_rounds": max_rounds,
        "events": [],
        "transcript": "",
        "synthesis": "",
        # D02/D14:默认值 fail-closed — nur ein explizites CONSENSUS_REACHED
        # darf später als finale Entscheidung archiviert werden.
        "consensus_status": "NO_CONSENSUS",
        "consensus_verdict": "NO_CONSENSUS",
        "consensus_reached": False,
        "veto_by": None,
        "critique": "",
        "critique_error": False,
        "is_final_decision": False,
    }

    async for ev in stream_boardroom_debate(task, max_rounds, chairman_id, active_agents, framework, timeout, use_moa=use_moa, moa_reference_models=moa_reference_models, moa_aggregator=moa_aggregator):
        ev_type = ev.get("type")
        if ev_type == "start":
            task_res["chairman"] = ev.get("chairman", task_res["chairman"])
        elif ev_type == "done":
            done_seen = True
            task_res["transcript"] = ev.get("transcript", "")
            task_res["synthesis"] = ev.get("synthesis", "")
            verdict = str(ev.get("consensus_verdict") or ev.get("consensus_status") or "NO_CONSENSUS").upper()
            task_res["consensus_status"] = verdict
            task_res["consensus_verdict"] = verdict
            task_res["consensus_reached"] = bool(ev.get("consensus_reached"))
            task_res["veto_by"] = ev.get("veto_by")
            task_res["critique"] = ev.get("critique", "")
            task_res["critique_error"] = bool(ev.get("critique_error"))
            task_res["evidence"] = ev.get("evidence", [])
            # Nur echter Konsens ist eine finale Entscheidung.
            task_res["is_final_decision"] = verdict.startswith("CONSENSUS_REACHED")
            if not task_res["is_final_decision"]:
                task_res["status"] = "no_consensus"
            elif str(task_res.get("synthesis") or "").strip():
                task_res["status"] = "success"
        elif ev_type == "error":
            return {"status": "error", "content": ev.get("content", "")}
        elif ev_type == "cancelled":
            # Ein Abbruch darf nie als erfolgreiche Entscheidung archiviert
            # werden (Decision-Engine/Telegram hingen am status=Feld).
            task_res["status"] = "cancelled"
            task_res["cancel_reason"] = ev.get("reason", "")
            task_res["cancel_scope"] = ev.get("cancel_scope") or "boardroom"
            break
        elif ev_type == "round_start":
            continue
        else:
            events.append(ev)

    task_res["events"] = events
    # D02/HIGH: ein Abbruch ist ein eigener Terminalstatus. Er darf nicht
    # durch den allgemeinen Unvollständigkeits-Check zu "incomplete" werden,
    # sonst ist ein Cancel im Result/Archiv nicht mehr von einer leeren
    # Debatte zu unterscheiden.
    if str(task_res.get("status") or "").lower() == "cancelled":
        return task_res
    # D01/S-1.7: Stream ohne done-Event oder ohne Synthese ist keine
    # erfolgreiche Entscheidung — nie als "success" an Client/Archiv geben.
    if not done_seen or not str(task_res.get("synthesis") or "").strip():
        task_res["status"] = "incomplete"
        task_res["incomplete_reason"] = "no_done_event" if not done_seen else "empty_synthesis"
    return task_res

async def execute_with_self_correction(
    agent_id: str,
    agent_name: str,
    task_description: str,
    execution_fn,
    initial_args: dict,
    max_retries: int = 3,
    role: str = "Developer",
    model: str = "deepseek/deepseek-chat"
) -> dict:
    """
    Pillar 2 / Self-Correction & Reflection Loop:
    Führt Tool-Aufrufe oder Skripte aus. Bei Fehlern (Exit-Code != 0, Exception)
    wird der Fehlertext an den Agenten zurückgespeist, damit dieser die Parameter/den Code
    analysiert, korrigiert und bis zu 3-mal selbstständig neu versucht.
    """
    attempt = 1
    current_args = dict(initial_args)
    correction_history = []
    
    while attempt <= max_retries:
        try:
            if asyncio.iscoroutinefunction(execution_fn):
                res = await execution_fn(current_args)
            else:
                res = await asyncio.to_thread(execution_fn, current_args)
            
            is_error = False
            err_msg = ""
            if isinstance(res, dict):
                if res.get("status") in ("error", "failed") or (res.get("code") is not None and res.get("code") != 0):
                    is_error = True
                    err_msg = str(res.get("stderr") or res.get("message") or res.get("content") or "Unbekannter Fehler")
            
            if not is_error:
                return {
                    "status": "success",
                    "attempts": attempt,
                    "result": res,
                    "corrections": correction_history
                }
            
            if attempt == max_retries:
                return {
                    "status": "error",
                    "attempts": attempt,
                    "message": f"Selbstkorrektur nach {max_retries} Versuchen fehlgeschlagen: {err_msg}",
                    "corrections": correction_history,
                    "last_result": res
                }
                
            reflection_prompt = (
                f"[SELBSTKORREKTUR-REFLEXION - VERSUCH {attempt}/{max_retries}]\n"
                f"Aufgabe: {task_description}\n"
                f"Bisherige Parameter/Code:\n{json.dumps(current_args, ensure_ascii=False, indent=2)}\n\n"
                f"FEHLER-AUSGABE:\n{err_msg[:1200]}\n\n"
                f"Instruktion: Analysiere den Fehler präzise. Liefere als Antwort ein valides JSON-Objekt "
                f"mit den korrigierten Parametern/Feldern, um diesen Fehler zu beheben."
            )
            
            llm_res = await dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=reflection_prompt,
                role=role,
                system_prompt="Du bist ein Experte für Fehleranalyse und autonome Selbstkorrektur. Antworte ausschließlich mit JSON.",
                model=model
            )
            
            content = llm_res.get("content", "")
            if llm_res.get("status") in ("blocked", "error"):
                # Audit 23.11.2026: ein blockierter Call (Budget/Concurrency/
                # Egress) darf nicht 3× mit identischen Parametern wiederholt
                # werden — das erzeugt nur weitere blockierte Calls.
                return {
                    "status": llm_res.get("status"),
                    "error_code": llm_res.get("error_code", "SELF_CORRECTION_BLOCKED"),
                    "message": str(llm_res.get("error") or "Selbstkorrektur blockiert"),
                    "attempts": attempt,
                    "corrections": correction_history,
                }
            try:
                clean_json = content
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                parsed = json.loads(clean_json)
                if isinstance(parsed, dict):
                    correction_history.append({"attempt": attempt, "error": err_msg, "correction": parsed})
                    current_args.update(parsed)
            except Exception:
                correction_history.append({"attempt": attempt, "error": err_msg, "raw_response": content[:300]})
                
        except Exception as exc:
            if attempt == max_retries:
                return {
                    "status": "error",
                    "attempts": attempt,
                    "message": f"Unerwarteter Ausführungsfehler: {str(exc)}",
                    "corrections": correction_history
                }
            correction_history.append({"attempt": attempt, "exception": str(exc)})
            
        attempt += 1

    return {"status": "error", "attempts": attempt, "corrections": correction_history}
