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
from typing import Any, Dict, Optional

from backend.delegation_isolation import mark_session_tainted_on_tool_read

logger = logging.getLogger("archon.tool_runtime")


def _emit_tool_event(kind: str, payload: Dict[str, Any]) -> bool:
    """Gibt True zurueck, wenn eine erforderliche GoBD-Audit-Schreibung klappte.

    B1: frueher wurden Audit-Fehler verschluckt und der Tool-Call lief trotzdem
    (oder der Block wurde nicht nachweisbar protokolliert).
    """
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("tool_runtime", {"event": kind, **payload})
    except Exception as exc:
        logger.warning("[ToolRuntime] Event-Broadcast fehlgeschlagen: %s", exc)
    if kind != "tool.blocked":
        return True
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="tool_runtime",
            action="tool_blocked",
            agent_id=str(payload.get("agent_id") or "system"),
            payload=payload,
        )
        return True
    except Exception as exc:
        logger.error("[ToolRuntime] GoBD-Audit-Schreibung fuer tool.blocked fehlgeschlagen: %s", exc)
        return False


def enforce_tool_execution(
    *,
    agent_id: str = "",
    session_id: str = "default_session",
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    warrant: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prueft M75 Isolation, M89 Taint-Guard und optional M90 Tool-Warrant."""
    clean_tool = str(tool_name or "").strip()
    clean_agent = str(agent_id or "").strip()
    clean_session = str(session_id or "default_session").strip()

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
    )
    if not gate.get("allowed"):
        audit_ok = _emit_tool_event("tool.blocked", {
            "agent_id": clean_agent,
            "session_id": clean_session,
            "tool_name": clean_tool,
            "reason": gate.get("reason", "gate_denied"),
            "gate": gate.get("gate"),
        })
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

    _emit_tool_event("tool.allowed", {
        "agent_id": clean_agent,
        "session_id": clean_session,
        "tool_name": clean_tool,
    })
    return {
        "allowed": True,
        "tool": clean_tool,
        "agent_id": clean_agent,
        "session_id": clean_session,
        "privileged": bool(gate.get("privileged")),
        "obligations": gate.get("obligations") or [],
    }


_GUARDED_TEXT_FIELDS = ("content", "result", "output", "text", "error", "message", "stdout", "stderr")


def _guard_text(tool_name: str, text: Any) -> Any:
    try:
        from backend.tool_output_firewall import guard_tool_output
        guarded = guard_tool_output(tool_name, text)
        return guarded.get("output", text)
    except Exception as exc:
        # Fail-closed: bei Ausfall des Guards darf kein ungefilterter Output in
        # den LLM-Kontext (Secrets/Prompt-Injection).
        logger.error("[ToolRuntime] Output-Guard fehlgeschlagen: %s", exc)
        return "[OUTPUT_GUARD_UNAVAILABLE — Inhalt aus Sicherheitsgruenden verworfen]"


def guard_result(tool_name: str, result: Any) -> Any:
    """F10: oeffentlicher Pflicht-Chokepoint fuer alle Tool-Resultate.

    Maskiert Secrets/PII, scannt auf Injection und packt externe Outputs in
    Untrusted-Delimiter. Bei Dict-Results bleiben Struktur und Status erhalten;
    nur die Textfelder werden gehaertet (DAG-/API-Kompatibilitaet).
    """
    if isinstance(result, dict):
        guarded = dict(result)
        # FRUEHER: nur eine Whitelist von 8 Feldern — MCP/Plugin-Results mit
        # data/body/response/structuredContent/html blieben ungefiltert.
        # Jetzt: alle String-Blätter (mit Tiefe-/Anzahl-Limit) rekursiv haerten.
        seen = 0
        def _walk(v: Any, depth: int = 0) -> Any:
            nonlocal seen
            if depth > 6 or seen > 200:
                # D12/HIGH: Fail-Open beseitigt. Strings gehen weiterhin durch
                # die Firewall, alle anderen Strukturen werden durch einen
                # Platzhalter ersetzt — nie ungefiltert in den LLM-Kontext.
                if isinstance(v, str):
                    return _guard_text(tool_name, v)
                return "[OUTPUT_OMITTED_LIMIT]"
            if isinstance(v, str):
                if v:
                    seen += 1
                    return _guard_text(tool_name, v)
                return v
            if isinstance(v, dict):
                return {k: _walk(val, depth + 1) for k, val in v.items()}
            if isinstance(v, (list, tuple)):
                return [_walk(x, depth + 1) for x in v]
            return v
        return _walk(guarded)
    return _guard_text(tool_name, result)


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
) -> None:
    """D12/BLOCKER: Produzent fuer `flight_events` im echten Tool-Chokepoint.

    R-B4 (Re-Audit D13): Der Gruppierungsschluessel muss der sein, mit dem
    `detect_silent_failures()` abfragt. Frueher wurde die HTTP-Trace-ID
    verwendet (`current_trace_id()`), die pro Request wechselt und mit der
    `rid`/`tid` der Detektoren nichts zu tun hat. Explizite ID > session_id >
    Trace-ID als Fallback.
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
            tool_ok=str(status).lower() == "success",
            tokens_used=_result_token_estimate(result),
        )
    except Exception as exc:
        # Kein stilles Scheitern: der Detektor darf nicht erneut blind werden.
        logger.error("[ToolRuntime] Flight-Event-Schreibung fehlgeschlagen: %s", exc)


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
) -> Dict[str, Any]:
    """Einheitlicher Ausfuehrungspfad fuer Agent- und DAG-Node-Tool-Calls."""
    gate = enforce_tool_execution(
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
    )
    def _finalize(status: str, payload: Dict[str, Any], result: Any) -> Dict[str, Any]:
        _record_tool_flight_event(
            tool_name=tool_name,
            args=args,
            agent_id=agent_id,
            session_id=session_id,
            status=status,
            result=result,
            flightlog_run_id=flightlog_run_id,
        )
        return payload

    if not gate.get("allowed"):
        call_args = args if isinstance(args, dict) else {}
        return _finalize("blocked", {"status": "blocked", "error": gate.get("reason", "Tool blockiert"), "gate": gate}, gate)

    call_args = args if isinstance(args, dict) else {}

    # 1. Zuerst PluginManager pruefen
    try:
        from backend.plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        exported = {t.get("name") for t in (pm.get_all_exported_tools() or []) if isinstance(t, dict)}
        if tool_name in exported:
            res = await pm.execute_plugin_tool(tool_name, call_args)
            record_tool_read_side_effect(session_id, tool_name)
            guarded = _guard_tool_result(tool_name, res)
            return _finalize("success", {"status": "success", "source": "plugin", "result": guarded}, guarded)
    except Exception as exc:
        return _finalize("error", {"status": "error", "source": "plugin", "error": str(exc)}, str(exc))

    # 2. Danach ArchonMcpServer
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        res = ArchonMcpServer().execute_tool(tool_name, call_args)
        if isinstance(res, dict) and str(res.get("status") or "").lower() in ("error", "failed", "blocked"):
            return _finalize("error", {
                "status": "error",
                "source": "mcp",
                "error": str(res.get("message") or res.get("error") or "MCP-Tool-Fehler"),
                "result": res,
            }, res)
        record_tool_read_side_effect(session_id, tool_name)
        guarded = _guard_tool_result(tool_name, res)
        return _finalize("success", {"status": "success", "source": "mcp", "result": guarded}, guarded)
    except Exception as exc:
        return _finalize("error", {"status": "error", "source": "mcp", "error": str(exc)}, str(exc))
