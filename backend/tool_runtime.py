# -*- coding: utf-8 -*-
"""
backend/tool_runtime.py
=======================
Zentraler ToolRuntime-Chokepoint fuer Archon OS (Stufe 2 Konsolidierung).

Vereint:
1. M75 Rollen- & Tool-Isolation (`delegation_isolation.enforce_runtime_tool_gate`)
2. M89 Session-Taint-Guard (`session_taint_guard`)
3. M90 Kryptografische Tool-Warrants (`tool_warrants.verify_warrant_for_call`)
4. Einheitliches Event-Bus- & Audit-Logging fuer alle Tool-Ausfuehrungen
   (Plugins, MCP Gateway, SysOps MCP-REST, DAG-Multi-Turn-Agents).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from backend.delegation_isolation import mark_session_tainted_on_tool_read

logger = logging.getLogger("archon.tool_runtime")


def _record_tool_span(
    tool_name: str,
    *,
    status: str = "OK",
    agent_id: str = "",
    attributes: Optional[Dict[str, Any]] = None,
) -> None:
    """D16/MED: Tool-Calls als eigene Spans im OTel-Baum sichtbar machen.

    Ohne aktiven Trace wird bewusst kein Span erfunden. Fehler beim
    Schreiben werden ueber die zentrale trace_context-Fehlerzaehlung
    sichtbar, nie still verschluckt.
    """
    try:
        from backend.trace_context import current_span_id, current_trace_id

        tid = str(current_trace_id() or "")
        if not tid:
            return
        sid = str(current_span_id() or "")
        from backend.otel_tracer import tracer

        tracer.record_span(
            trace_id=tid,
            name=f"tool.{tool_name}",
            span_type="tool",
            parent_span_id=sid or None,
            agent_id=str(agent_id) or None,
            status=status,
            attributes={"tool.name": str(tool_name), **(attributes or {})},
        )
    except Exception as exc:
        try:
            from backend.trace_context import note_local_trace_error

            note_local_trace_error("tool-span", exc)
        except Exception:
            logger.warning("[ToolRuntime] Tool-Span nicht geschrieben: %s", exc)


def _emit_tool_event(kind: str, payload: Dict[str, Any]) -> bool:
    """Gibt True zurueck, wenn eine erforderliche GoBD-Audit-Schreibung klappte.

    B1/F14: Sowohl `tool.blocked` als auch `tool.allowed` muessen kryptografisch
    in die Audit-Kette signiert werden; ein Schreibfehler darf nie still
    durchgereicht werden.
    """
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("tool_runtime", {"event": kind, **payload})
    except Exception as exc:
        logger.warning("[ToolRuntime] Event-Broadcast fehlgeschlagen: %s", exc)
    action_map = {
        "tool.blocked": "tool_blocked",
        "tool.allowed": "tool_allowed",
    }
    action = action_map.get(kind)
    if not action:
        return True
    try:
        from backend.audit_log import _require_audit_event
        _require_audit_event(
            category="tool_runtime",
            action=action,
            agent_id=str(payload.get("agent_id") or "system"),
            payload=payload,
        )
        return True
    except Exception as exc:
        logger.error("[ToolRuntime] GoBD-Audit-Schreibung fuer %s fehlgeschlagen: %s", kind, exc)
        return False


def enforce_tool_execution(
    *,
    agent_id: str = "",
    session_id: str = "default_session",
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    warrant: Optional[Dict[str, Any]] = None,
    requested_by: str = "",
) -> Dict[str, Any]:
    """Prueft M75 Isolation, M89 Taint-Guard und optional M90 Tool-Warrant."""
    clean_tool = str(tool_name or "").strip()
    clean_agent = str(agent_id or "").strip()
    clean_session = str(session_id or "default_session").strip()
    clean_requester = str(requested_by or "").strip()

    # Zentrale PolicyEngine: M75 + M89 + M90 + RBAC an EINER Stelle.
    # Dieser Chokepoint enthält keine eigene Policy-Logik mehr.
    from backend.delegation_isolation import policy_engine

    gate = policy_engine.decide(
        agent_id=clean_agent,
        session_id=clean_session,
        tool_name=clean_tool,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
        requested_by=clean_requester,
    )
    if not gate.get("allowed"):
        audit_ok = _emit_tool_event("tool.blocked", {
            "agent_id": clean_agent,
            "session_id": clean_session,
            "tool_name": clean_tool,
            "reason": gate.get("reason", "gate_denied"),
            "gate": gate.get("gate"),
        })
        _record_tool_span(
            clean_tool,
            status="ERROR",
            agent_id=clean_agent,
            attributes={
                "tool.gate": str(gate.get("gate") or ""),
                "tool.block_reason": str(gate.get("reason") or "gate_denied"),
                "tool.audit_ok": bool(audit_ok),
            },
        )
        if not audit_ok:
            # B1: ohne GoBD-Auditnachweis darf kein (auch kein blockierter)
            # Tool-Call unbemerkt durchgereicht werden.
            return {
                **gate,
                "allowed": False,
                "blocked": True,
                "gate": "audit_write_failed",
                "reason": "audit_write_failed",
            }
        return gate

    audit_ok = _emit_tool_event("tool.allowed", {
        "agent_id": clean_agent,
        "session_id": clean_session,
        "tool_name": clean_tool,
        "privileged": bool(gate.get("privileged")),
        "requested_by": clean_requester,
    })
    if not audit_ok:
        return {
            "allowed": False,
            "blocked": True,
            "gate": "audit_write_failed",
            "reason": "audit_write_failed",
            "tool": clean_tool,
            "agent_id": clean_agent,
            "session_id": clean_session,
        }
    return {
        "allowed": True,
        "tool": clean_tool,
        "agent_id": clean_agent,
        "session_id": clean_session,
        "privileged": bool(gate.get("privileged")),
        "obligations": gate.get("obligations") or [],
    }


_GUARDED_TEXT_FIELDS = ("content", "result", "output", "text", "error", "message", "stdout", "stderr")

_ERROR_STATUSES = ("error", "failed", "blocked")

# D12/H1: `is_empty_tool_result()` gilt auch fuer verschachtelte Werte — aber
# nur fuer die primaeren Ergebnistraeger. Leere Listen ("keine Treffer"),
# Zaehler (`count=0`), leere Metadaten und leere Felder innerhalb von
# Datensätzen (z. B. `tasks[0].body`) sind legitime Daten und keine Silent
# Failures. Ein `"status": "success", "result": ""` bleibt dagegen ein Fehler.
_EMPTY_PRIMARY_FIELDS = frozenset({
    "result", "content", "output", "text", "structuredContent",
    "stdout", "stderr", "data", "payload", "body", "response", "value",
})


def _is_empty_relevant_leaf(path: str) -> bool:
    """Prueft, ob ein leeres Blatt der eigentliche Tool-Output ist."""
    parts = path.split(".")
    # Listen-Elemente sind Datensätze, keine Ergebnistraeger.
    if any("[" in part for part in parts):
        return False
    # `result.<feld>` und `result.<feld>.<feld>` sind zulaessig; tiefere
    # Verschachtelungen gehoeren bereits zum Nutzdatenmodell.
    if len(parts) > 3:
        return False
    return parts[-1] in _EMPTY_PRIMARY_FIELDS


def _firewall_text(tool_name: str, value: Any) -> tuple[str, Optional[str]]:
    """Einziger Pfad vom Firewall-Urteil zum LLM-Kontext.

    Liefert ``(text, error_code)``. Bei ``status="error"`` enthält der Text
    einen *sichtbaren* Marker (D12/H-12-2) statt ``""``. Der Rohtext der
    Firewall wird nie durchgereicht, wenn die Klassifikation scheiterte
    (D12/H-12-3, fail-closed in ``tool_output_firewall``).
    """
    try:
        from backend.tool_output_firewall import guard_tool_output
        guarded = guard_tool_output(tool_name, value)
        if str(guarded.get("status") or "").lower() == "error":
            code = str(
                guarded.get("error_code") or guarded.get("error") or "TOOL_ERROR"
            )
            marker = (
                f"[TOOL-FEHLER {tool_name}: {code} "
                "— kein Ergebnis; nicht als Fakt verwenden]"
            )
            # firewall-output ist bei Fehlern entweder leer oder ein harmloser
            # Platzhalter — nie ungepruefter Rohtext.
            fallback = str(guarded.get("output") or "")
            return (marker + (" " + fallback if fallback else "")), code
        return str(guarded.get("output", "")), None
    except Exception as exc:
        # Fail-closed: bei Ausfall des Guards darf kein ungefilterter Output in
        # den LLM-Kontext (Secrets/Prompt-Injection).
        logger.error("[ToolRuntime] Output-Guard fehlgeschlagen: %s", exc)
        return (
            "[OUTPUT_GUARD_UNAVAILABLE — Inhalt aus Sicherheitsgruenden verworfen]",
            "OUTPUT_GUARD_UNAVAILABLE",
        )


def _guard_text(tool_name: str, text: Any) -> Any:
    """Rueckwaerts-kompatibel: nur der Text (mit sichtbarem Fehlermarker)."""
    return _firewall_text(tool_name, text)[0]


def _guard_result_verdict(tool_name: str, result: Any) -> Dict[str, Any]:
    """D12/H-12-1: vollstaendiges Firewall-Urteil fuer den Tool-Chokepoint.

    Rueckgabe: ``status`` (``ok``/``error``), ``error``/``error_code``,
    ``result`` (der gehaertete Payload fuer den LLM-Kontext), ``output``
    (nur bei Text-Results), ``security`` und ``empty_fields``. Die Konsumenten
    pruefen ``status`` und eskalieren — statt ihn zu verwerfen.
    """
    from backend.tool_output_firewall import is_empty_tool_result

    # Leere Gesamtergebnisse (None/{}/[]/0) gehen unveraendert durch die
    # Firewall und werden zum sichtbaren Fehler — nie zu einer leeren Luecke.
    if is_empty_tool_result(result):
        text, code = _firewall_text(tool_name, result)
        return {
            "status": "error", "error": code, "error_code": code,
            "result": text, "output": text, "security": {},
            "empty_fields": ["<root>"],
        }

    if isinstance(result, dict):
        guarded = dict(result)
        seen = 0
        guard_errors: List[str] = []
        empty_fields: List[str] = []

        # FRUEHER: nur eine Whitelist von 8 Feldern — MCP/Plugin-Results mit
        # data/body/response/structuredContent/html blieben ungefiltert.
        # Jetzt: alle String-Blätter (mit Tiefe-/Anzahl-Limit) rekursiv haerten.
        # D12/H1: `is_empty_tool_result()` wird auf verschachtelte Werte
        # angewendet — begrenzt auf die primaeren Ergebnisfelder, damit
        # "keine Treffer" und leere Datensatz-Felder nicht zu Fake-Fehlern
        # werden (siehe `_is_empty_relevant_leaf`).
        def _walk(v: Any, depth: int = 0, path: str = "result") -> Any:
            nonlocal seen
            if depth > 6 or seen > 200:
                # D12/HIGH: Strings gehen weiterhin durch die Firewall, alle
                # anderen Strukturen werden ersetzt — nie ungefiltert in den
                # LLM-Kontext.
                if isinstance(v, str) and v:
                    text, code = _firewall_text(tool_name, v)
                    if code:
                        guard_errors.append(code)
                    return text
                return "[OUTPUT_OMITTED_LIMIT]"

            if isinstance(v, str):
                if not v.strip():
                    if _is_empty_relevant_leaf(path):
                        empty_fields.append(path)
                        guard_errors.append("EMPTY_TOOL_RESULT_FIELD")
                    return v
                seen += 1
                text, code = _firewall_text(tool_name, v)
                if code:
                    guard_errors.append(code)
                return text
            if isinstance(v, dict):
                if is_empty_tool_result(v) and _is_empty_relevant_leaf(path):
                    empty_fields.append(path)
                    guard_errors.append("EMPTY_TOOL_RESULT_FIELD")
                return {k: _walk(val, depth + 1, f"{path}.{k}") for k, val in v.items()}
            if isinstance(v, (list, tuple)):
                # Eine leere Liste heisst "keine Treffer" und ist kein
                # leeres Tool-Ergebnis (der Ingest-Pfad meldet Ausfaelle selbst).
                return [_walk(x, depth + 1, f"{path}[{i}]") for i, x in enumerate(v)]
            # Zahlen (inkl. 0) und Booleans sind nur als Gesamtergebnis leer
            # (siehe `is_empty_tool_result(result)` am Funktionsanfang).
            return v

        walked = _walk(guarded)
        # Ein bereits vom Tool gemeldeter Fehler darf nicht durch die Firewall
        # zu "ok" umgewertet werden (der Plugin-Pfad hatte keinen Pre-Check).
        tool_status = str(result.get("status") or "").lower()
        real_codes = [c for c in guard_errors if c != "EMPTY_TOOL_RESULT_FIELD"]
        # Ein leeres Ergebnis-Blatt ist der naechste Grund fuer den Fehler —
        # er darf nicht hinter einem Klassifikatorfehler verschwinden.
        code = (
            "EMPTY_TOOL_RESULT" if empty_fields
            else (real_codes[0] if real_codes else None)
        )
        if not code and tool_status in _ERROR_STATUSES:
            code = "TOOL_REPORTED_ERROR"
        return {
            "status": "error" if code else "ok",
            "error": code, "error_code": code,
            "result": walked, "output": None, "security": {},
            "empty_fields": empty_fields,
        }

    text, code = _firewall_text(tool_name, result)
    return {
        "status": "error" if code else "ok",
        "error": code, "error_code": code,
        "result": text, "output": text, "security": {},
        "empty_fields": [],
    }


def guard_result(tool_name: str, result: Any, *, with_status: bool = True) -> Any:
    """F10: oeffentlicher Pflicht-Chokepoint fuer alle Tool-Resultate.

    Maskiert Secrets/PII, scannt auf Injection und packt externe Outputs in
    Untrusted-Delimiter. Bei Dict-Results bleiben Struktur und Status erhalten;
    nur die Textfelder werden gehaertet (DAG-/API-Kompatibilitaet).

    D12/H-12-1: das vollstaendige Firewall-Urteil (``status``/``error_code``/
    ``result``/``empty_fields``) ist jetzt der **Default-Vertrag**. Ein Aufruf
    ohne ``with_status`` verwirft das Urteil nicht mehr. ``with_status=False``
    bleibt nur als expliziter, veralteter Opt-out fuer Legacy-Konsumenten
    erhalten und darf in neuen Pfaden nicht verwendet werden.
    """
    verdict = _guard_result_verdict(tool_name, result)
    # D16/MED: Finalize des Tool-Calls. Das Firewall-Urteil (inkl. sichtbarem
    # Fehlermarker) ist die Gate-Entscheid, die im Span landet — nie der
    # Roh-Output (PII/Secrets gehoeren nicht in den Trace).
    _record_tool_span(
        tool_name,
        status="OK" if verdict.get("status") == "ok" else "ERROR",
        attributes={
            "tool.result_status": str(verdict.get("status") or "error"),
            "tool.error_code": str(verdict.get("error_code") or ""),
            "tool.with_status": bool(with_status),
        },
    )
    return verdict if with_status else verdict["result"]


def guard_result_payload(verdict: Any) -> Any:
    """Gibt den gehaerteten Payload aus einem Firewall-Urteil zurueck.

    Der Default von ``guard_result()`` ist das Urteil. Konsumenten, die den
    Payload an Clients/Caches weiterreichen, entpacken ihn ueber diese SSOT.
    Ein injizierter Legacy-/Mock-Guard ohne ``status`` liefert direkt den
    Payload und bleibt unveraendert durchgereicht.
    """
    if isinstance(verdict, dict) and "status" in verdict and "result" in verdict:
        return verdict.get("result")
    return verdict


# Rueckwaerts kompatibel zum bisherigen internen Namen.
_guard_tool_result = guard_result


def _result_token_estimate(result: Any) -> int:
    """Echte, nachvollziehbare Token-Naherung aus dem Tool-Output."""
    if isinstance(result, dict):
        for key in ("tokens_used", "completion_tokens", "total_tokens"):
            value = result.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                return int(value)
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        text = str(result)
    return max(1, len(text) // 4)


def _record_tool_flight_event(
    *,
    tool_name: str,
    args: Optional[Dict[str, Any]],
    agent_id: str,
    session_id: str,
    status: str,
    result: Any,
    flightlog_run_id: Optional[str] = None,
    error_code: str = "",
    tool_ok: Optional[bool] = None,
) -> bool:
    """D12/BLOCKER: Produzent fuer `flight_events` im echten Tool-Chokepoint.

    R-B4 (Re-Audit D13): Der Gruppierungsschluessel muss der sein, mit dem
    `detect_silent_failures()` abfragt. Frueher wurde die HTTP-Trace-ID
    verwendet (`current_trace_id()`), die pro Request wechselt und mit der
    `rid`/`tid` der Detektoren nichts zu tun hat. Explizite ID > session_id >
    Trace-ID als Fallback.

    D12/MED: Gibt ``False`` zurueck, wenn die Audit-Schreibung scheitert. Der
    Aufrufer muss daraus einen Fehlerzustand machen — ein nur geloggter
    Schreibfehler macht den Silent-Failure-Detektor blind.
    """
    try:
        from backend.flightlog_backtester import record_flight_event
        from backend.trace_context import current_trace_id

        run_id = (
            str(flightlog_run_id or "").strip()
            or str(session_id or "").strip()
            or str(current_trace_id() or "").strip()
            or "no-trace"
        )
        record_flight_event(
            run_id=run_id,
            agent_id=str(agent_id or "unknown"),
            tool_name=str(tool_name or "unknown"),
            args=args if isinstance(args, dict) else {},
            # D12/H-12-1: tool_ok kommt aus dem Firewall-Status, nicht aus dem
            # hart codierten _finalize-Parameter.
            tool_ok=(str(status).lower() == "success" if tool_ok is None else bool(tool_ok)),
            tokens_used=_result_token_estimate(result),
            error_code=str(error_code or ""),
        )
        return True
    except Exception as exc:
        # Kein stilles Scheitern: der Detektor darf nicht erneut blind werden.
        logger.error("[ToolRuntime] Flight-Event-Schreibung fehlgeschlagen: %s", exc)
        return False


def record_tool_read_side_effect(session_id: str, tool_name: str) -> None:
    """Markiert eine Session als tainted, sobald externe/untrusted Tool-Outputs gelesen wurden."""
    try:
        mark_session_tainted_on_tool_read(str(session_id or "default_session").strip(), str(tool_name or "").strip())
    except Exception as exc:
        logger.debug(f"[ToolRuntime] Taint-Read-Marker fehlgeschlagen: {exc}")


async def execute_agent_tool(
    *,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    agent_id: str = "",
    session_id: str = "default_session",
    approval_id: Optional[str] = None,
    warrant: Optional[Dict[str, Any]] = None,
    flightlog_run_id: Optional[str] = None,
    requested_by: str = "",
) -> Dict[str, Any]:
    """Einheitlicher Ausfuehrungspfad fuer Agent- und DAG-Node-Tool-Calls."""
    gate = enforce_tool_execution(
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
        requested_by=requested_by,
    )
    def _finalize(
        status: str,
        payload: Dict[str, Any],
        result: Any,
        *,
        error_code: str = "",
        tool_ok: Optional[bool] = None,
    ) -> Dict[str, Any]:
        written = _record_tool_flight_event(
            tool_name=tool_name,
            args=args,
            agent_id=agent_id,
            session_id=session_id,
            status=status,
            result=result,
            flightlog_run_id=flightlog_run_id,
            error_code=error_code,
            tool_ok=tool_ok,
        )
        if not written:
            # D12/MED: Audit-Schreibfehler nie verschlucken. Ohne Flight-Event
            # sieht detect_silent_failures() 0 Events und meldet "kein Fehler".
            return {
                **payload,
                "status": "error",
                "error_code": "FLIGHTLOG_WRITE_FAILED",
                "error": "Flight-Event konnte nicht geschrieben werden — "
                         "Ergebnis nicht verifiziert",
                "original_status": status,
            }
        return payload

    if not gate.get("allowed"):
        reason = str(gate.get("reason") or "Tool blockiert")
        return _finalize(
            "blocked",
            {"status": "blocked", "error": reason, "gate": gate},
            gate,
            error_code=str(gate.get("reason") or "TOOL_BLOCKED"),
            tool_ok=False,
        )

    call_args = args if isinstance(args, dict) else {}

    # 1. Zuerst PluginManager pruefen
    try:
        from backend.plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        exported = {t.get("name") for t in (pm.get_all_exported_tools() or []) if isinstance(t, dict)}
        if tool_name in exported:
            res = await pm.execute_plugin_tool(tool_name, call_args)
            record_tool_read_side_effect(session_id, tool_name)
            # F24a (D01): echten Plugin-Abschluss-Hook (inkl. on_task_completed / CostGuard)
            # am ToolRuntime-Chokepoint ausfuehren, bevor guard_result filtert.
            if callable(getattr(pm, "apply_after_tool_execute", None)):
                res = await pm.apply_after_tool_execute(
                    tool_name,
                    res,
                    {"agent_id": agent_id, "session_id": session_id, "source": "plugin"},
                )
            # D12/H-12-1: Firewall-Urteil unveraendert durchreichen und pruefen.
            verdict = guard_result(tool_name, res, with_status=True)
            guarded = verdict.get("result")
            if str(verdict.get("status") or "").lower() == "error":
                code = str(verdict.get("error_code") or "TOOL_OUTPUT_SANITIZATION_ERROR")
                return _finalize("error", {
                    "status": "error", "source": "plugin",
                    "error": code, "error_code": code, "result": guarded,
                }, guarded, error_code=code, tool_ok=False)
            return _finalize(
                "success",
                {"status": "success", "source": "plugin", "result": guarded},
                guarded,
                tool_ok=(str(verdict.get("status") or "").lower() == "ok"),
            )
    except Exception as exc:
        return _finalize("error", {
            "status": "error", "source": "plugin",
            "error": str(exc), "error_code": "TOOL_EXECUTION_ERROR",
        }, str(exc), error_code="TOOL_EXECUTION_ERROR", tool_ok=False)

    # 2. Danach ArchonMcpServer
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        res = ArchonMcpServer().execute_tool(tool_name, call_args)
        if isinstance(res, dict) and str(res.get("status") or "").lower() in _ERROR_STATUSES:
            return _finalize("error", {
                "status": "error",
                "source": "mcp",
                "error": str(res.get("message") or res.get("error") or "MCP-Tool-Fehler"),
                "error_code": "TOOL_REPORTED_ERROR",
                "result": res,
            }, res, error_code="TOOL_REPORTED_ERROR", tool_ok=False)
        record_tool_read_side_effect(session_id, tool_name)
        # F24a (D01): auch im MCP-/DAG-Pfad apply_after_tool_execute (on_task_completed / CostGuard)
        # ausfuehren, damit CostGuard im DAG-Pfad nicht blind bleibt.
        try:
            from backend.plugin_manager import get_plugin_manager
            pm_mcp = get_plugin_manager()
            res = await pm_mcp.apply_after_tool_execute(
                tool_name,
                res,
                {"agent_id": agent_id, "session_id": session_id, "source": "mcp"},
            )
        except Exception as hook_exc:
            logger.warning("[ToolRuntime] apply_after_tool_execute (mcp) fehlgeschlagen: %s", hook_exc)
        # D12/H-12-1: auch im MCP-Pfad das Firewall-Urteil pruefen.
        verdict = guard_result(tool_name, res, with_status=True)
        guarded = verdict.get("result")
        if str(verdict.get("status") or "").lower() == "error":
            code = str(verdict.get("error_code") or "TOOL_OUTPUT_SANITIZATION_ERROR")
            return _finalize("error", {
                "status": "error", "source": "mcp",
                "error": code, "error_code": code, "result": guarded,
            }, guarded, error_code=code, tool_ok=False)
        return _finalize(
            "success",
            {"status": "success", "source": "mcp", "result": guarded},
            guarded,
            tool_ok=(str(verdict.get("status") or "").lower() == "ok"),
        )
    except Exception as exc:
        return _finalize("error", {
            "status": "error", "source": "mcp",
            "error": str(exc), "error_code": "TOOL_EXECUTION_ERROR",
        }, str(exc), error_code="TOOL_EXECUTION_ERROR", tool_ok=False)
