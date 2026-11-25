"""Cluster 2 — Node-Plugins („VST-Schnittstelle") des DAG-Executors.

Reine Extraktion aus ``backend/workflow_dag_runner.default_agent_node_executor``
(frueher Zeilen ~1250-1279). KEINE Logikaenderung: Reihenfolge, Kanban-Events,
Fehlertext und Return-Zusammensetzung sind 1:1 uebernommen.

Dependency-Injection (S3): ``kanban_update`` wird von der Facade zur Aufrufzeit
uebergeben, damit ``patch("backend.workflow_dag_runner._update_kanban_task_status")``
weiterhin greift und kein Rueckimport-Zyklus entsteht.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["execute_plugin_node"]


async def execute_plugin_node(
    node: Dict[str, Any],
    upstream: Dict[str, Any],
    node_type: str,
    kanban_task_id: Optional[str],
    kanban_update: Callable[..., None],
) -> Dict[str, Any]:
    """Fuehrt einen standardisierten Node-Plugin-Knoten aus und synct Kanban.

    Rueckgabe ist das **komplette** Ergebnis-Dict (Early-Return der Facade):
    ``pres`` wird um ``node_id``, ``agent_id`` und ``kanban_task_id`` angereichert.
    """
    await asyncio.to_thread(
        kanban_update,
        kanban_task_id,
        "in_progress",
        event_kind="workflow_node_started",
        event_payload={"node_id": node.get("id"), "type": node_type},
    )
    try:
        from backend.workflow_node_plugins import execute_workflow_node_plugin

        pres = await execute_workflow_node_plugin(node_type, node, upstream)
    except Exception as pexc:
        logger.error(
            "[WorkflowDAG] Node-Plugin '%s' abgestuerzt: %s",
            node_type, pexc, exc_info=pexc,
        )
        pres = {"status": "error", "error": f"Plugin-Ausfuehrungsfehler: {pexc}", "content": ""}
    p_err = str(pres.get("status") or "success").lower() in ("error", "failed", "blocked")
    await asyncio.to_thread(
        kanban_update,
        kanban_task_id,
        "blocked" if p_err else "done",
        result=str(pres.get("content") or pres.get("error") or ""),
        block_kind="workflow_error" if p_err else None,
        event_kind="workflow_node_failed" if p_err else "workflow_node_completed",
        event_payload={"node_id": node.get("id"), "type": node_type, "status": pres.get("status", "success")},
    )
    return {
        **pres,
        "node_id": node.get("id"),
        "agent_id": str(node.get("agent_id") or node_type),
        "kanban_task_id": kanban_task_id,
    }
