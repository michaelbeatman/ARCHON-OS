"""Cluster 6 — Multi-Turn Tool-Calling Loop des DAG-Executors.

Reine Extraktion aus ``default_agent_node_executor`` (frueher ~:1324-1439).
KEINE Logikaenderung: Tool-Call-Parsing, ``reserve_hop``-Guard,
``allowed_tools``-Pruefung, ToolRuntime-Chokepoint, Flightlog-Mirror,
Checkpoint-DB, ``turn_prompt`` und der Folge-Dispatch sind 1:1 uebernommen.

Rueckgabe-Tupel statt geteiltem State-Objekt: die Facade behaelt saemtliche
Locals. ``res`` wird (wie vorher) in place mutiert und zusaetzlich zurueckgegeben.

Dependency-Injection (S3): ``dispatch_with_budget`` und ``connect`` werden zur
Aufrufzeit als Callables uebergeben. Alle uebrigen Abhaengigkeiten bleiben
Lazy-Imports, damit bestehende ``patch(...)``-Punkte weiter greifen.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["run_tool_loop"]

ToolTrace = List[Dict[str, Any]]


async def run_tool_loop(
    *,
    node: Dict[str, Any],
    res: Dict[str, Any],
    content: str,
    is_error: bool,
    model: str,
    agent_id: str,
    agent_name: str,
    eff_system_prompt: str,
    role: str,
    reasoning_level: str,
    kanban_task_id: Optional[str],
    full_prompt: str,
    dispatch_with_budget: Callable[..., Awaitable[Tuple[Any, bool]]],
    connect: Callable[..., Any],
) -> Tuple[str, Dict[str, Any], bool, ToolTrace]:
    """Fuehrt den Multi-Turn-Tool-Loop aus und liefert die mutierten Locals."""
    tool_trace: ToolTrace = []
    allowed_tool_set = {str(t).strip() for t in (node.get("allowed_tools") or []) if str(t).strip()}
    if not is_error and content and allowed_tool_set:
        max_turns = max(1, min(6, int(node.get("max_turns") or 3)))
        turn_prompt = full_prompt
        for _turn in range(max_turns):
            _tc = None
            try:
                _stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
                if _stripped.startswith("{") and '"tool_call"' in _stripped:
                    _parsed_tc = json.loads(_stripped)
                    if isinstance(_parsed_tc, dict) and isinstance(_parsed_tc.get("tool_call"), dict):
                        _tc = _parsed_tc["tool_call"]
            except Exception:
                _tc = None
            if not _tc:
                break
            _tname = str(_tc.get("name") or "").strip()
            _targs = _tc.get("args") if isinstance(_tc.get("args"), dict) else {}
            _tid_node = str(node.get("_trajectory_id") or "")
            _hop_ok = True
            if _tid_node.startswith("traj-"):
                try:
                    from backend.trajectory_budget import reserve_hop

                    _hop = await asyncio.to_thread(
                        reserve_hop, _tid_node, str(node.get("agent_id") or agent_id),
                        f"tool:{_tname}",
                    )
                    _hop_ok = bool(_hop.get("allowed", False))
                except Exception:
                    _hop_ok = False
            if not _hop_ok:
                _tres = {"status": "blocked", "error": "TRAJECTORY_HOP_CAP (tool call)"}
            elif _tname not in allowed_tool_set:
                _tres = {"status": "blocked", "error": f"Tool '{_tname}' ist in diesem DAG-Node nicht unter allowed_tools freigegeben."}
            else:
                from backend.tool_runtime import execute_agent_tool

                _tres = await execute_agent_tool(
                    tool_name=_tname,
                    args=_targs,
                    agent_id=agent_id,
                    session_id=str(kanban_task_id or node.get("id") or "dag_session"),
                    # R-B4: identischer Schluessel wie detect_silent_failures() am
                    # Run-Abschluss (dort `rid`, hier ueber den Node mitgefuehrt).
                    flightlog_run_id=str(node.get("_dag_run_id") or ""),
                )
                # D13/HIGH: der Chokepoint schreibt nur unter flightlog_run_id;
                # der Dispatcher-Konsument liest current_trace_id(). Spiegeln
                # ohne Event-Replay — der Primaereintrag bleibt unberuehrt.
                try:
                    from backend.flightlog_backtester import mirror_flight_event_to_trace
                    from backend.tool_runtime import _result_token_estimate

                    mirror_flight_event_to_trace(
                        run_id=str(node.get("_dag_run_id") or ""),
                        agent_id=agent_id, tool_name=_tname, args=_targs,
                        tool_ok=str(_tres.get("status") or "").lower() == "success",
                        tokens_used=_result_token_estimate(_tres),
                        session_id=str(kanban_task_id or node.get("id") or "dag_session"),
                    )
                except Exception as _mirror_exc:
                    logger.debug("[WorkflowDAG] Flightlog-Trace-Mirror fehlgeschlagen: %s", _mirror_exc)
            tool_trace.append({"turn": _turn + 1, "tool": _tname, "args": _targs, "result": _tres})
            _ckpt_rid = str(node.get("_dag_run_id") or "")
            _ckpt_db = node.get("_dag_db_path")
            if _ckpt_rid and node.get("id"):
                try:
                    with connect(_ckpt_db) as conn:
                        conn.execute(
                            """
                            INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                            VALUES (?, ?, ?, 'running', ?, ?)
                            ON CONFLICT(run_id, node_id) DO UPDATE SET
                                status='running', output_json=excluded.output_json, updated_at=excluded.updated_at
                            """,
                            (
                                _ckpt_rid,
                                str(node["id"]),
                                "running_checkpoint",
                                json.dumps({"partial_tool_trace": tool_trace, "turn": _turn + 1}, ensure_ascii=False),
                                time.time(),
                            ),
                        )
                        conn.commit()
                except Exception as _cexc:
                    logger.debug("[WorkflowDAG] Tool-Checkpoint fehlgeschlagen: %s", _cexc)
            turn_prompt = (
                f"{turn_prompt}\n\n[TOOL-AUFRUF #{_turn + 1}: {_tname}]\n"
                f"Ergebnis:\n{json.dumps(_tres, ensure_ascii=False)[:3500]}\n\n"
                "Nutze dieses Ergebnis. Wenn kein weiterer Tool-Aufruf noetig ist, liefere jetzt deine finale Antwort ohne tool_call-Wrapper."
            )
            _next_res, _next_blocked = await dispatch_with_budget(
                node, res, model,
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=turn_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=model,
                reasoning_level=reasoning_level,
                task_id=str(kanban_task_id or node.get("id") or ""),
                _phase="tool_loop_followup",
            )
            if _next_blocked:
                is_error = True
                res["error"] = str(_next_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
                break
            res["input_tokens"] = int(res.get("input_tokens") or 0) + int(_next_res.get("input_tokens") or 0)
            res["output_tokens"] = int(res.get("output_tokens") or 0) + int(_next_res.get("output_tokens") or 0)
            _next_status = str(_next_res.get("status") or "success").lower()
            _next_content = str(_next_res.get("content") or "").strip()
            if _next_status in ("error", "failed", "blocked") or not _next_content:
                is_error = True
                res["error"] = _next_res.get("error") or "Tool-Loop Folgeschritt fehlgeschlagen"
                break
            content = _next_content

    return content, res, is_error, tool_trace
