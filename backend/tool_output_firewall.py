# -*- coding: utf-8 -*-
"""
backend/tool_output_firewall.py
===============================
Meilenstein 93: Code-as-Orchestration & Tool-Output-Firewall
(codemode & toolaria-Pattern).

1. Tool-Output-Firewall (toolaria): Faengt uebergrosse MCP- und Web-Outputs
   ab, bevor sie das Kontextfenster sprengen.
2. Batch-Orchestrator (codemode): Fuehrt gebuendelte Tool-Call-Listen in
   einem einzigen Turn aus statt vieler teurer LLM-Roundtrips.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List


def guard_tool_output(
    tool_name: str,
    raw_output: Any,
    max_chars: int = 8000,
    head_chars: int = 4500,
    tail_chars: int = 2500,
) -> Dict[str, Any]:
    text = raw_output if isinstance(raw_output, str) else str(raw_output)
    orig_len = len(text)
    if orig_len <= max_chars:
        return {"tool": tool_name, "truncated": False, "original_chars": orig_len, "output": text}

    omitted = orig_len - (head_chars + tail_chars)
    compacted = (
        f"{text[:head_chars]}\n\n"
        f"[TRUNCATED BY TOOL-OUTPUT-FIREWALL ({tool_name}): {omitted} Zeichen ausgelassen, Gesamt: {orig_len}]\n\n"
        f"{text[-tail_chars:]}"
    )
    return {"tool": tool_name, "truncated": True, "original_chars": orig_len, "output": compacted}


async def run_batch_tool_calls(
    calls: List[Dict[str, Any]],
    tool_executor: Callable[[str, Dict[str, Any]], Awaitable[Any]],
    max_chars_per_result: int = 8000,
) -> List[Dict[str, Any]]:
    """Fuehrt mehrere Tool-Calls parallel in einem Turn aus und filtert uebergrosse Outputs."""
    async def _one(c: Dict[str, Any]) -> Dict[str, Any]:
        tname = str(c.get("tool") or "")
        args = c.get("args") or {}
        try:
            res = await tool_executor(tname, args)
            guarded = guard_tool_output(tname, res, max_chars=max_chars_per_result)
            return {"tool": tname, "status": "ok", **guarded}
        except Exception as exc:
            return {"tool": tname, "status": "error", "error": str(exc), "output": ""}

    return list(await asyncio.gather(*(_one(c) for c in calls)))
