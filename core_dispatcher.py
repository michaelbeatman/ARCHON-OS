import asyncio
import contextvars
import datetime
import functools
import hashlib
import json
import logging
import os
import random
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


def _record_failed_cancel(task_name: str, detail: str) -> Dict[str, Any]:
    """Persistiert einen gescheiterten cancel() inkl. signiertem Audit-Event.

    D05/HIGH (H-05-4): der frühere Aufruf ohne Pflicht-`agent_id` löste
    garantiert TypeError aus und wurde als WARNING verschluckt — ein toter
    Audit-Pfad. Jetzt: agent_id="system", ERROR-Eskalation und sichtbares
    Result-Feld. Bei ARCHON_AUDIT_STRICT=1 bleibt der Vorfall ausdrücklich
    nicht quittiert (audit_status="error"), /readyz spiegelt _FAILED_CANCELS.
    """
    entry: Dict[str, Any] = {
        "task": str(task_name),
        "detail": str(detail)[:500],
        "ts": time.time(),
        "audit_status": "ok",
    }
    _FAILED_CANCELS.append(entry)
    logger.error("[Dispatcher] Cancel fehlgeschlagen: %s — %s", task_name, entry["detail"])
    try:
        with _AUDIT_WRITE_LOCK:
            from backend.audit_log import chained_audit_log
            ev = chained_audit_log.record_event(
                category="recovery",
                action="cancel_failed",
                agent_id="system",
                payload={k: v for k, v in entry.items() if k != "audit_status"},
            )
        entry["audit_status"] = "ok"
        entry["audit_event_id"] = ev.get("event_id")
    except Exception as audit_exc:
        # Audit-Schreibfehler nie verschlucken (§0 / §2.5).
        entry["audit_status"] = "error"
        entry["audit_error"] = f"{type(audit_exc).__name__}: {audit_exc}"
        logger.error("[Dispatcher] Cancel-Fehler nicht auditierbar: %s", audit_exc)
    return entry


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


_POLICY_VETO_ERROR_PREFIXES = (
    "ZERO_EGRESS",
    "EGRESS_",
    "PROMPT_INJECTION",
    "POLICY_",
    "COMPLIANCE_",
    "GOVERNANCE_",
    "SILENT_FAILURE",
    "HITL_",
    "BUDGET_GATE",
    "CONCURRENCY_GATE",
    "AGENT_NOT_COMPLIANT",
    "SOUL_SHA256_MISMATCH",
    "SOUL_PIN_REFRESH_REQUIRED",
    "AUDIT_WRITE_FAILED",
)


def _attach_guardrail_result(res: dict) -> dict:
    """F21 (D14): Kanonischer Produzent fuer ``res['guardrail_result']`` am Dispatch-Chokepoint.

    Stellt sicher, dass jeder Return aus ``dispatch_to_omniroute_or_container``
    einen strukturierten Policy-Veto-Kanal traegt (nie aus Freitext, nicht nur
    bei ``status == 'blocked'``).
    """
    if not isinstance(res, dict):
        return res
    raw_gr = res.get("guardrail_result")
    existing: Dict[str, Any] = raw_gr if isinstance(raw_gr, dict) else {}
    policy_v = bool(existing.get("policy_violation") or res.get("policy_violation"))
    guardrail_v = bool(existing.get("guardrail_violation") or res.get("guardrail_violation"))
    severity = existing.get("severity") or res.get("severity") or None

    status_l = str(res.get("status") or "").strip().lower()
    err_code = str(res.get("error_code") or "").strip().upper()
    has_policy_err = bool(err_code and any(err_code.startswith(p) for p in _POLICY_VETO_ERROR_PREFIXES))
    has_silent_flags = bool(res.get("silent_failure_flags"))

    if status_l == "blocked" or has_policy_err or (status_l == "needs_human" and has_silent_flags):
        policy_v = True
        guardrail_v = True
        severity = str(severity or "high")

    trace_id = existing.get("source_trace_id") or res.get("source_trace_id") or res.get("trace_id")
    if not trace_id:
        try:
            from backend.trace_context import current_trace_id
            trace_id = str(current_trace_id() or "") or None
        except Exception:
            trace_id = None

    res["guardrail_result"] = {
        "policy_violation": policy_v,
        "guardrail_violation": guardrail_v,
        "severity": str(severity) if severity else None,
        "source_trace_id": str(trace_id) if trace_id else None,
        "error_code": err_code or None,
    }
    return res


def _with_prompt_info(res: dict, info: Optional[Dict[str, Any]] = None) -> dict:
    """Hängt effective_prompt_info/prompt_version_info und guardrail_result an JEDEN Return."""
    if not isinstance(res, dict):
        return res
    _attach_guardrail_result(res)
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
            # F10c / D12 §2.5: GoBD-relevanter Audit-Schreibfehler darf nie nur
            # geloggt und geschluckt werden — fail-closed abbrechen.
            logger.error("[Dispatcher] Silent-Failure-Audit fehlgeschlagen: %s", audit_exc)
            raise RuntimeError("audit_write_failed") from audit_exc

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


from archon.core.dispatch_budget_cache import (  # noqa: E402, I001 - INVARIANTS §3: bewusster später Re-Export/Patch-Punkt
    _DispClosingConn as _DispClosingConn,
    _audit_dispatch_failure_with_lock as _audit_dispatch_failure_with_lock,
    _cache_policy_context as _cache_policy_context,
    _dispatch_cache_scope as _dispatch_cache_scope,
    _log_dispatcher_usage_sync_impl as _log_dispatcher_usage_sync_impl,
    _reserve_trajectory_budget_sync as _reserve_trajectory_budget_sync,
    _validate_cache_hit_gate as _validate_cache_hit_gate,
)

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

    W4-B/D06: Outbox-first ueber ``event_mesh.emit_outbound_event_async``.
    Der HTTP-Hop bleibt injizierbar (httpx), damit Retry/DLQ und Ack-Pruefung
    in der Outbox liegen und ein Timeout nicht zum dauerhaften Verlust fuehrt.
    """
    import datetime
    url = f"{N8N_URL}/webhook/archon-execution"
    executed_at = datetime.datetime.now().isoformat()
    action = target_action or "none"
    payload = {
        "parent_project_id": parent_project_id,
        "title": title,
        "final_report_path": final_report_path,
        "content": content,
        "action": action,
        "executed_at": executed_at,
    }
    # Deterministischer Idempotency-Key aus (parent_project_id, action, executed_at).
    key_source = json.dumps(
        {"parent_project_id": str(parent_project_id or ""), "action": action,
         "executed_at": executed_at},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    idem = hashlib.sha256(key_source.encode("utf-8")).hexdigest()
    payload["idempotency_key"] = idem

    async def _httpx_transport(target, method, headers, body, request_timeout):
        """Echter HTTP-Hop; Idempotency-Key und Trace stammen aus der Outbox.

        Die Outbox injiziert den traceparent bereits mit der exakt zum Payload
        passenden Span-ID (``new_child=False``). Der Transport darf ihn daher
        NICHT erneut forken — sonst zeigen Header und Payload auf zwei
        verschiedene Kanten. Nur wenn die Outbox ausnahmsweise keinen Kontext
        beigesteuert hat, wird hier ein Child-Span erzeugt und injiziert.
        """
        send_headers = dict(headers)
        try:
            has_traceparent = any(
                str(k).lower() == "traceparent" and bool(v)
                for k, v in (headers or {}).items()
            )
            if not has_traceparent:
                from backend.trace_context import child_span, inject_headers

                with child_span():
                    send_headers = inject_headers(send_headers)
        except Exception as tr_exc:
            logger.warning(
                "[Dispatcher] Trace-Injektion im n8n-Transport fehlgeschlagen: %s", tr_exc
            )
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            resp = await client.post(target, content=body, headers=send_headers)
            return (
                int(resp.status_code),
                {
                    str(k).lower(): str(v)
                    for k, v in (getattr(resp, "headers", None) or {}).items()
                },
                getattr(resp, "content", None) or b"",
            )

    try:
        from backend.event_mesh import event_mesh

        res = await event_mesh.emit_outbound_event_async(
            url,
            "archon.execution",
            payload,
            timeout=float(timeout),
            ack_required=True,
            transport=_httpx_transport,
        )
    except Exception as e:
        logger.error("[Dispatcher] n8n-Outbox nicht erreichbar: %s", e)
        return {
            "status": "blocked",
            "blocked": True,
            "error_code": "N8N_OUTBOX_UNAVAILABLE",
            "idempotency_key": idem,
            "message": f"n8n outbox unavailable: {str(e)[:300]}",
        }

    outbox_id = res.get("outbox_id")
    outbox_status = str(res.get("status") or "")
    http_status = int(res.get("http_status") or 0)
    if outbox_status == "delivered" and res.get("ack_confirmed"):
        ack = {}
        try:
            ack = json.loads(str(res.get("response") or "") or "{}")
        except (ValueError, TypeError):
            ack = {}
        if not isinstance(ack, dict):
            ack = {}
        execution_id = str(ack.get("executionId") or ack.get("execution_id") or "").strip()
        return {
            "status": "success",
            "code": http_status or 200,
            "execution_id": execution_id,
            "idempotency_key": idem,
            "outbox_id": outbox_id,
            "message": "n8n execution acknowledged via outbox",
        }
    # HTTP 200 ohne executionId/status ist kein Erfolg. pending,
    # delivery_failed und dead bleiben in der Outbox und werden vom 30-s-
    # Drainer mit demselben Key erneut zugestellt (CAS + Backoff + DLQ).
    unconfirmed = http_status == 200 and not res.get("ack_confirmed")
    logger.warning(
        "[Dispatcher] n8n-Ausfuehrung nicht bestaetigt (action=%s, outbox=%s, status=%s).",
        action, outbox_id, outbox_status,
    )
    return {
        "status": "unconfirmed" if unconfirmed else "blocked",
        "blocked": True,
        "code": http_status,
        "error_code": "N8N_DELIVERY_UNCONFIRMED" if unconfirmed else "N8N_OUTBOX_PENDING",
        "idempotency_key": idem,
        "outbox_id": outbox_id,
        "outbox_status": outbox_status,
        "message": (
            "n8n HTTP 200 ohne executionId — Ausfuehrung nicht bestaetigt (Outbox "
            f"id={outbox_id}, status={outbox_status})."
        ),
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
        # D04/H-04-1: fehlender Key darf NIE "Cloud erlaubt" bedeuten.
        if DataClassifier.classify(prompt or "").get("cloud_llm_allowed", False) is not True:
            explicit_cat = "confidential"
    except Exception as exc:
        # D04/H-04-1: Klassifikationsfehler = fail-closed confidential +
        # signierter Block-Proof + ZeroEgressBlockedError (analog Z.308-310 /
        # agent_router.py:834-836). Nie still mit leerer Kategorie weiterlaufen.
        logger.error("[Dispatcher] DataClassifier fehlgeschlagen (fail-closed, Zero-Egress): %s", exc)
        explicit_cat = "confidential"
        ev = {}
        try:
            from backend.audit_log import chained_audit_log
            from backend.llm_egress_guard import _record_blocked_proof
            ev = _record_blocked_proof(
                alog=chained_audit_log,
                agent_id=aid or "system",
                provider=provider or "omniroute",
                model=model or "",
                target_endpoint=url or "egress-firewall://proof.local",
                action="llm_dispatch_blocked_classifier_unavailable",
                error_code="DATA_CLASSIFIER_UNAVAILABLE",
                reason=f"DataClassifier nicht verfuegbar — fail-closed: {exc}",
                data_category="confidential",
            )
        except Exception as proof_exc:
            # Auch ein fehlgeschlagener Proof darf den Block nicht aufheben.
            logger.error("[Dispatcher] Classifier-Block-Proof nicht schreibbar (fail-closed): %s", proof_exc)
        raise ZeroEgressBlockedError(
            f"DataClassifier nicht verfuegbar — Zero-Egress fail-closed: {exc}",
            audit_event=ev,
            error_code="DATA_CLASSIFIER_UNAVAILABLE",
        ) from exc

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

from archon.core.dispatch_parsing import (  # noqa: E402, I001 - INVARIANTS §3: bewusster später Re-Export/Patch-Punkt
    _OMNIROUTE_OPENROUTER_FALLBACK_MAP as _OMNIROUTE_OPENROUTER_FALLBACK_MAP,
    _extract_tokens_usage as _extract_tokens_usage,
    _resolve_openrouter_fallback_model as _resolve_openrouter_fallback_model,
    clean_think_tags as clean_think_tags,
    parse_omniroute_response as parse_omniroute_response,
)

# Globaler Concurrency Throttle (Pillar 2 / Prozessmodell)
# Drosselt gleichzeitige rechenintensive LLM-Tasks zum Schutz vor 99% CPU-Spitzen / Buffer Overflows
MAX_CONCURRENT_AGENT_TASKS = int(os.getenv("MAX_CONCURRENT_AGENT_TASKS", "5"))
# WeakKeyDictionary statt id(loop): id() wird nach GC eines Loops wiederverwendet
# und lieferte dann einen geschlossenen Client/Semaphore an einen neuen Loop.
# Ausserdem verhindert die Weak-Referenz, dass tote Loops Pools halten.
_TASK_SEMAPHORES: Any = weakref.WeakKeyDictionary()
_DISPATCHER_HTTP_CLIENTS: Any = weakref.WeakKeyDictionary()


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


async def close_dispatcher_clients() -> Dict[str, Any]:
    """Shutdown-Hook: alle gepoolten Clients kontrolliert schliessen.

    D08/MED (H-08/Client-Close): ein fehlgeschlagenes ``aclose()`` wurde frueher
    verschluckt UND der Client danach aus dem Registry geloescht — der Shutdown
    meldete Erfolg, waehrend Transport/FD offen blieben. Fehlgeschlagene Clients
    bleiben jetzt im Dict (aufrufbarer Retry), werden auf ERROR geloggt und als
    ``failed_closes`` zurueckgegeben.
    """
    closed = 0
    failed: List[str] = []
    for loop, client in list(_DISPATCHER_HTTP_CLIENTS.items()):
        if client.is_closed:
            continue
        try:
            await client.aclose()
            closed += 1
        except Exception as exc:
            # Kein stilles Verlieren der Referenz: der Client bleibt im Registry,
            # damit ein spaeterer Shutdown-Versuch ihn erneut schliessen kann.
            failed.append(str(exc))
            logger.error(
                "[Dispatcher] HTTP-Client-Close fehlgeschlagen (FD-Leak-Risiko): %s",
                exc, exc_info=exc,
            )
    return {
        "closed": closed,
        "failed_closes": len(failed),
        "failed_clients": failed,
        "remaining_clients": len(_DISPATCHER_HTTP_CLIENTS),
    }


def _audit_dispatch_failure(action: str, detail: str, **extra: Any) -> None:
    """Call-Time-Wrapper: nutzt das Singleton _AUDIT_WRITE_LOCK auf core_dispatcher."""
    _audit_dispatch_failure_with_lock(_AUDIT_WRITE_LOCK, action, detail, **extra)


async def _log_dispatcher_usage(agent_id: str, model: str, in_tok: int, out_tok: int, task_id: str = "") -> None:
    """Audit-/Budget-Logging nie direkt im Event-Loop."""
    try:
        await asyncio.to_thread(
            _log_dispatcher_usage_sync, agent_id, model, in_tok, out_tok, task_id
        )
    except Exception as exc:
        _audit_dispatch_failure("usage_log_failed", str(exc), stage="async_usage_log")


def _log_dispatcher_usage_sync(agent_id: str, model: str, in_tok: int, out_tok: int, task_id: str = "") -> None:
    _log_dispatcher_usage_sync_impl(
        agent_id,
        model,
        in_tok,
        out_tok,
        task_id,
        audit_failure_fn=_audit_dispatch_failure,
    )

# _extract_tokens_usage wird oben via `X as X` aus archon.core.dispatch_parsing re-exportiert.

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
    trajectory_reason: str = "",
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

                # D13/H-13-1: die Trajectory-Invariante (Hop/Zyklus/Token-Cap)
                # wurde bisher NUR im DAG-/Agent-Router-Pfad geprueft. Der
                # zentrale LLM-Chokepoint war Produzent ohne Konsument. Harte
                # Blockade VOR dem Provider-Call; die Budget-Reservierung wird
                # im `finally` wieder freigegeben.
                try:
                    _traj = await asyncio.to_thread(
                        _reserve_trajectory_budget_sync,
                        str(task_id or ""),
                        str(agent_id or ""),
                        est_in_tokens + est_out_tokens,
                        str(trajectory_reason or ""),
                    )
                except Exception as traj_exc:
                    logger.error(
                        "[Dispatcher] Trajectory-Gate nicht verfuegbar - Dispatch blockiert: %s",
                        traj_exc,
                    )
                    return _with_prompt_info({
                        "status": "blocked",
                        "error": f"trajectory_gate_unavailable: {traj_exc}",
                        "error_code": "TRAJECTORY_GATE_UNAVAILABLE",
                        "content": "🛑 [TRAJECTORY-GATE]: Budget-Invariante nicht pruefbar — Dispatch blockiert (fail-closed).",
                    })
                if not _traj.get("allowed", False):
                    _traj_reason = str(_traj.get("reason") or "TRAJECTORY_CAP_BLOCKED")
                    logger.error(
                        "[Dispatcher] Trajectory-Cap blockiert task=%s agent=%s stage=%s reason=%s",
                        task_id, agent_id, _traj.get("stage"), _traj_reason,
                    )
                    return _with_prompt_info({
                        "status": "blocked",
                        "error": _traj_reason,
                        "error_code": "TRAJECTORY_CAP_BLOCKED",
                        "content": f"🛑 [TRAJECTORY-CAP]: {_traj_reason}",
                        "trajectory_id": _traj.get("trajectory_id"),
                        "trajectory_stage": _traj.get("stage"),
                    })
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
                    # D08/MED: SQLite-Feedback (2 Connections, timeout=15) nach
                    # JEDEM Dispatch gehoert in den Threadpool, nicht in den Loop.
                    await asyncio.to_thread(
                        bandit_model_router.record_outcome,
                        model_id=used_model,
                        success=is_ok,
                        latency_ms=duration_ms,
                    )
                except Exception as bn_exc:
                    logger.warning("[Dispatcher] Bandit-Feedback fehlgeschlagen: %s", bn_exc)

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

from backend.llm_kernel import AUTO_MODEL_MAP, estimate_model_cost_usd as estimate_model_cost_usd  # noqa: E402, I001 - INVARIANTS §3: Re-Export
# _OMNIROUTE_OPENROUTER_FALLBACK_MAP & _resolve_openrouter_fallback_model werden oben via `X as X` re-exportiert.


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


def _build_dispatch_context_sync(
    prompt: str,
    agent_id: str,
    task_id: str,
    system_prompt: str,
    model: str,
) -> Dict[str, Any]:
    """D08/H-08-1: alle blockierenden Kontextquellen in EINEM Worker-Thread.

    Vorher liefen Prefetcher (bis zu 3x sqlite3.connect), Prompt-Registry
    (SQLite + open/json.load), Core-Memory (SQLite, timeout=15) und Bandit-
    Auswahl (SQLite) direkt im Event-Loop. Bei 5 parallelen Dispatch-Slots
    blockierten diese Lesen /livez, /health und den SSE-Stream. Jedes Quelle
    bleibt einzeln fehlertolerant (wie zuvor), aber der Aufruf passiert nur
    noch einmal via ``asyncio.to_thread``.
    """
    result: Dict[str, Any] = {
        "prefetch_addon": "",
        "effective_prompt_info": None,
        "prompt_version_info": None,
        "core_mem_addon": "",
        "system_prompt": system_prompt,
        "model": model,
    }

    # 1. Spekulatives Vorladen (CRM/ERP/Learnings) — SQLite + os.path.exists.
    try:
        from backend.speculative_prefetcher import get_speculative_prefetcher
        p_res = get_speculative_prefetcher().prefetch_for_task(prompt, agent_id=agent_id)
        p_items = p_res.get("cached_items", {}) if isinstance(p_res, dict) else {}
        p_lines = []
        if "crm_contact" in p_items:
            c = p_items["crm_contact"]
            p_lines.append(
                f"- CRM-Kontakt: {c.get('first_name', '')} {c.get('last_name', '')} "
                f"({c.get('email', '')}) [Firma: {c.get('company', 'Unbekannt')}]"
            )
        if "erp_doc" in p_items:
            d = p_items["erp_doc"]
            p_lines.append(
                f"- ERP-Dokument: {d.get('doc_number', '')} ({d.get('type', '')}) "
                f"[Status: {d.get('status', '')}]"
            )
        if p_lines:
            result["prefetch_addon"] = (
                "\n\n### [SPEKULATIV VORGELADENE KONTEXT-DATEN]:\n" + "\n".join(p_lines)
            )
    except Exception as pf_err:
        logger.debug("[Dispatcher] Spekulatives Prefetching uebersprungen: %s", pf_err)

    # 2. Prompt-Registry & Canary-Routing.
    try:
        from backend.prompt_registry import prompt_registry
        eff = prompt_registry.get_effective_prompt(agent_id, task_id)
        if eff and eff.get("prompt"):
            # Die Registry ist die BASIS; vom DAG injizierte Bloecke bleiben
            # erhalten (nicht ersetzen, sondern voranstellen).
            registry_prompt = eff["prompt"]
            if registry_prompt not in result["system_prompt"]:
                result["system_prompt"] = f"{registry_prompt}\n\n{result['system_prompt']}"
            result["effective_prompt_info"] = eff
            result["prompt_version_info"] = {
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
            if eff.get("model") and not result["model"]:
                result["model"] = eff["model"]
    except Exception as pr_err:
        logger.debug("[Dispatcher] Prompt-Registry Lookup uebersprungen: %s", pr_err)

    # 3. Core Working Memory (gepinnte Bloecke).
    try:
        from backend.core_memory_manager import core_memory_manager
        cm_xml = core_memory_manager.compile_system_prompt_injection(agent_id=agent_id)
        if cm_xml:
            result["core_mem_addon"] = f"\n\n{cm_xml}"
    except Exception as cm_err:
        logger.debug("[Dispatcher] Core-Memory-Injection uebersprungen: %s", cm_err)

    # 4. Bandit Model Router (opt-in ueber auto/bandit).
    if result["model"] in ("auto/bandit", "auto/best-bandit"):
        try:
            from backend.bandit_model_router import bandit_model_router
            b_res = bandit_model_router.select_best_model()
            if b_res.get("enabled") and b_res.get("selected_model"):
                result["model"] = b_res["selected_model"]
        except Exception as bn_err:
            logger.debug("[Dispatcher] Bandit-Router Auswahl uebersprungen: %s", bn_err)

    return result


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

    # D08/H-08-1: EIN Worker-Thread fuer alle vier blockierenden Kontextquellen
    # (Prefetcher, Prompt-Registry, Core-Memory, Bandit-Auswahl).
    _ctx = await asyncio.to_thread(
        _build_dispatch_context_sync, prompt, agent_id, task_id, system_prompt, model,
    )
    system_prompt = _ctx["system_prompt"]
    model = _ctx["model"]
    prefetch_addon = _ctx["prefetch_addon"]
    effective_prompt_info = _ctx["effective_prompt_info"]
    prompt_version_info = _ctx["prompt_version_info"]
    core_mem_addon = _ctx["core_mem_addon"]

    # Task-lokaler Ref fuer den aeusseren Dispatcher (D11: jeder Return).
    # ContextVars muessen im Event-Loop-Task gesetzt werden (nicht im Worker).
    _PROMPT_VERSION_CTX.set(prompt_version_info)

    static_system_prompt = f"Du bist {agent_name} (Rolle: {role}). {system_prompt}".strip()
    dynamic_system_addon = f"{core_mem_addon}{memory_context_addon}{prefetch_addon}".strip()
    full_system_prompt = (
        f"{static_system_prompt}\n\n{dynamic_system_addon}".strip()
        if dynamic_system_addon
        else static_system_prompt
    )

    chat_history_turns: List[Dict[str, str]] = []
    if history:
        # F030/W3-A: stumme Kuerzung auf die letzten 8 Turns durch den
        # kanonischen Helper ersetzen — der dropped-Marker bleibt sichtbar (kein
        # erfundenes Ergebnis, Verweis auf den Session-Store).
        try:
            from archon.routers.chat import history_with_dropped_marker
            kept_history = history_with_dropped_marker(
                history, 8, artifact=f"dispatch.history/{task_id or agent_id}"
            )
        except Exception as hist_exc:
            logger.debug("[Dispatcher] History-Dropped-Marker nicht verfuegbar: %s", hist_exc)
            kept_history = list(history)[-8:]
        for h in kept_history:
            if isinstance(h, dict):
                r = str(h.get("role", "")).strip().lower()
                c = str(h.get("content", "") or "").strip()
                if r == "system" and "GEKÜRZT" in c:
                    # Ausschliesslich der explizite Kuerzungs-Marker darf als
                    # System-Turn in die History (kein Prompt-Injection-Vektor).
                    chat_history_turns.append({"role": "system", "content": c})
                elif r in ("user", "assistant") and c:
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
        # D04/H-04-1: fehlender Key darf NIE "Cloud erlaubt" bedeuten.
        cls_res = DataClassifier.classify(prompt or "")
        if cls_res.get("cloud_llm_allowed", False) is not True:
            classified_cat = "confidential"
    except Exception as cls_err:
        # D04/H-04-1: Klassifikationsfehler -> confidential + signierter Proof +
        # ZeroEgressBlockedError (fail-closed, analog _gate_container_dispatch).
        logger.error("[Dispatcher] DataClassifier fehlgeschlagen (fail-closed, Zero-Egress): %s", cls_err)
        classified_cat = "confidential"
        ev = {}
        try:
            from backend.audit_log import chained_audit_log
            from backend.llm_egress_guard import _record_blocked_proof
            ev = _record_blocked_proof(
                alog=chained_audit_log,
                agent_id=agent_id or "system",
                provider=prov_lower or "omniroute",
                model=selected_model or "",
                # F821-Fix 25.11.2026: `url` existiert nur als Parameter des
                # spaeter definierten `_audited_post`, nicht in diesem Scope.
                # Der Proof-Pfad läuft vor der Provider-Auswahl — hier ist der
                # explizite Platzhalter korrekt und verhindert den NameError.
                target_endpoint="egress-firewall://proof.local",
                action="llm_dispatch_blocked_classifier_unavailable",
                error_code="DATA_CLASSIFIER_UNAVAILABLE",
                reason=f"DataClassifier nicht verfuegbar — fail-closed: {cls_err}",
                data_category="confidential",
            )
        except Exception as proof_exc:
            logger.error("[Dispatcher] Classifier-Block-Proof nicht schreibbar (fail-closed): %s", proof_exc)
        raise ZeroEgressBlockedError(
            f"DataClassifier nicht verfuegbar — Zero-Egress fail-closed: {cls_err}",
            audit_event=ev,
            error_code="DATA_CLASSIFIER_UNAVAILABLE",
        ) from cls_err

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
                ev = await _audit_log_async(  # type: ignore[assignment]
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

import copy  # noqa: E402, I001 - INVARIANTS §3: bewusster später Re-Export/Patch-Punkt

from archon.core.dispatcher_frameworks import (  # noqa: E402 - INVARIANTS §3: Re-Export
    DEFAULT_CATEGORIZED_FRAMEWORKS as DEFAULT_CATEGORIZED_FRAMEWORKS,
    DEFAULT_CATEGORIZED_FRAMEWORKS_EN as DEFAULT_CATEGORIZED_FRAMEWORKS_EN,
    UNIVERSAL_METHODOLOGY_HEADER as UNIVERSAL_METHODOLOGY_HEADER,
    UNIVERSAL_METHODOLOGY_HEADER_EN as UNIVERSAL_METHODOLOGY_HEADER_EN,
    build_final_system_prompt_text as _build_final_system_prompt_text,
    build_flat_framework_map as _build_flat_framework_map,
    is_english_framework as _is_english_framework_impl,
    resolve_framework_info as _resolve_framework_info,
)

# INVARIANTS §3: Mutable Globals bleiben auf core_dispatcher (Laufzeit-Rebind
# durch main.py:1281 und archon/routers/boardroom.py:242,255,256).
CATEGORIZED_FRAMEWORKS = copy.deepcopy(DEFAULT_CATEGORIZED_FRAMEWORKS)
CATEGORIZED_FRAMEWORKS_EN = copy.deepcopy(DEFAULT_CATEGORIZED_FRAMEWORKS_EN)


def get_flat_framework_map(lang: str = "de") -> dict:
    return _build_flat_framework_map(CATEGORIZED_FRAMEWORKS, CATEGORIZED_FRAMEWORKS_EN, lang=lang)


def _is_english_framework(name: str) -> bool:
    return _is_english_framework_impl(name, CATEGORIZED_FRAMEWORKS, CATEGORIZED_FRAMEWORKS_EN)


def get_framework_info(name: str, lang: str = "") -> dict:
    return _resolve_framework_info(name, CATEGORIZED_FRAMEWORKS, CATEGORIZED_FRAMEWORKS_EN, lang=lang)


def build_final_system_prompt(selected_framework_id: str, base_system_prompt: str = "", lang: str = "") -> str:
    """Compiles the final Boardroom system prompt (Call-Time-Injection fuer Patch-Punkte)."""
    return _build_final_system_prompt_text(
        selected_framework_id,
        CATEGORIZED_FRAMEWORKS,
        CATEGORIZED_FRAMEWORKS_EN,
        base_system_prompt=base_system_prompt,
        lang=lang,
        framework_info_fn=lambda fw_id, target_lang: get_framework_info(fw_id, lang=target_lang),
    )

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
    moa_reference_models: list = None,  # type: ignore[assignment]
    moa_aggregator: dict = None,  # type: ignore[assignment]
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
            cancel_token.register_task(asyncio.current_task())  # type: ignore[union-attr]
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
            clear_scope(cancel_token.scope)  # type: ignore[union-attr]


@_boardroom_cancellation_guard
async def _stream_boardroom_debate_inner(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30,
    use_moa: bool = False,
    moa_reference_models: list = None,  # type: ignore[assignment]
    moa_aggregator: dict = None,  # type: ignore[assignment]
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

    token.check()  # type: ignore[union-attr]  # Abbruch vor dem ersten Dispatch beachten
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
        token.check()  # type: ignore[union-attr]
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
                token.check()  # type: ignore[union-attr]  # Abbruch vor jedem Agent-Dispatch beachten
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

                token.check()  # type: ignore[union-attr]  # Abbruch vor jedem Agent-Dispatch beachten
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
    token.check()  # type: ignore[union-attr]
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
            token.check()  # type: ignore[union-attr]  # Abbruch vor jedem Agent-Dispatch beachten
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

        token.check()  # type: ignore[union-attr]  # Abbruch vor dem Aggregator-Dispatch beachten
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
    
        token.check()  # type: ignore[union-attr]  # Abbruch vor dem Synthese-Dispatch beachten
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
    moa_reference_models: list = None,  # type: ignore[assignment]
    moa_aggregator: dict = None  # type: ignore[assignment]
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
    model: str = "deepseek/deepseek-chat",
    task_id: str = "",
) -> dict:
    """
    Pillar 2 / Self-Correction & Reflection Loop:
    Führt Tool-Aufrufe oder Skripte aus. Bei Fehlern (Exit-Code != 0, Exception)
    wird der Fehlertext an den Agenten zurückgespeist, damit dieser die Parameter/den Code
    analysiert, korrigiert und bis zu 3-mal selbstständig neu versucht.
    """
    attempt = 1
    current_args = dict(initial_args)
    correction_history: list[Any] = []
    
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
                model=model,
                # D13/H-13-1: der Reflexions-Call muss dasselbe Ticket-Cap
                # belasten wie der Haupt-Dispatch, sonst entstehen bis zu 3
                # weitere, nicht zugeordnete kostenpflichtige Calls. `retry:`
                # kennzeichnet die zaehlerbegrenzte Wiederholung desselben
                # Agenten (kein A→B→A-Zyklus, aber ein budgetierter Hop).
                task_id=task_id,
                trajectory_reason=f"retry:{attempt}",
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
