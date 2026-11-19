# -*- coding: utf-8 -*-
"""
backend/hybrid_sop_runner.py
============================
Meilenstein 80: Hybrid-SOP-Runner — Script + Agenten-Urteil (opensop-Pattern).

Trennt deterministische Script-Schritte (100 % Sicherheit, z. B. Validierung,
Buchung, Export) von Agenten-Schritten mit Ermessensspielraum.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

ScriptHandler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
AgentHandler = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


async def run_hybrid_sop(
    sop_def: Dict[str, Any],
    script_handlers: Dict[str, ScriptHandler],
    agent_handler: AgentHandler,
    initial_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Fuehrt eine hybride SOP aus:
    `steps`: [{"id": "...", "kind": "script"|"agent", "handler": "...", "prompt": "..."}]
    """
    ctx: Dict[str, Any] = dict(initial_context or {})
    trace: List[Dict[str, Any]] = []

    for step in sop_def.get("steps") or []:
        sid = str(step.get("id") or f"step_{len(trace)+1}")
        kind = str(step.get("kind") or "agent").lower()

        if kind == "script":
            h_name = str(step.get("handler") or "")
            fn = script_handlers.get(h_name)
            if not fn:
                trace.append({"id": sid, "kind": "script", "status": "failed", "error": f"Unknown script handler: {h_name}"})
                return {"status": "failed", "failed_step": sid, "context": ctx, "trace": trace}
            out = fn(step, ctx)
            if not isinstance(out, dict) or out.get("ok", True) is False:
                trace.append({"id": sid, "kind": "script", "status": "failed", "output": out})
                return {"status": "failed", "failed_step": sid, "context": ctx, "trace": trace}
            ctx[sid] = out
            trace.append({"id": sid, "kind": "script", "status": "completed", "output": out})
        else:
            out = await agent_handler(step, ctx)
            if isinstance(out, dict) and out.get("status") == "error":
                trace.append({"id": sid, "kind": "agent", "status": "failed", "output": out})
                return {"status": "failed", "failed_step": sid, "context": ctx, "trace": trace}
            ctx[sid] = out
            trace.append({"id": sid, "kind": "agent", "status": "completed", "output": out})

    return {"status": "completed", "sop_id": sop_def.get("id", "sop"), "context": ctx, "trace": trace}
