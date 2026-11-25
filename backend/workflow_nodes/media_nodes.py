"""Cluster 3 — nativer Media-Render / Clip-Matrix-Knoten des DAG-Executors.

Reine Extraktion aus ``default_agent_node_executor`` (frueher ~:1281-1344).
KEINE Logikaenderung: Upstream-Text-Merge, ``media_config``-Defaults,
Kanban-Events, Erfolgs- und Exception-Return sind 1:1 uebernommen.

Dependency-Injection (S3): ``kanban_update`` wird zur Aufrufzeit uebergeben.
``generate_video_clip_matrix`` bleibt ein Lazy-Import, damit
``patch("backend.content_machine.generate_video_clip_matrix")`` greift.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["execute_media_node"]


async def execute_media_node(
    node: Dict[str, Any],
    upstream: Dict[str, Any],
    node_type: str,
    kanban_task_id: Optional[str],
    kanban_update: Callable[..., None],
) -> Dict[str, Any]:
    """Rendert eine Clip-Matrix und liefert das komplette Early-Return-Dict."""
    await asyncio.to_thread(
        kanban_update,
        kanban_task_id,
        "in_progress",
        event_kind="workflow_node_started",
        event_payload={"node_id": node.get("id"), "type": node_type},
    )
    try:
        from backend.content_machine import generate_video_clip_matrix

        mcfg = dict(node.get("media_config") or {})
        up_texts: List[str] = []
        for _dv in (upstream or {}).values():
            if isinstance(_dv, dict):
                up_texts.append(str(_dv.get("content") or _dv.get("summary") or ""))
            elif _dv:
                up_texts.append(str(_dv))
        script_text = str(
            mcfg.get("script")
            or "\n\n".join(t for t in up_texts if t)
            or node.get("prompt")
            or node.get("title")
            or ""
        )
        campaign_id = str(mcfg.get("campaign_id") or node.get("workflow_id") or "wf_media")
        target_channels = mcfg.get("target_channels")
        if not isinstance(target_channels, list) or not target_channels:
            target_channels = [
                str(mcfg.get("target_platform") or node.get("channel") or "youtube_shorts")
            ]
        matrix = await generate_video_clip_matrix(
            campaign_id=campaign_id,
            script_text=script_text,
            clip_count=int(mcfg.get("clip_count") or 3),
            target_channels=target_channels,
            dry_run=bool(mcfg.get("dry_run", False)),
        )
        rendered_md = json.dumps(matrix, ensure_ascii=False, indent=2)
        await asyncio.to_thread(
            kanban_update,
            kanban_task_id,
            "done",
            result=rendered_md,
            event_kind="workflow_node_completed",
            event_payload={"node_id": node.get("id"), "type": node_type, "status": "success"},
        )
        return {
            "status": "success",
            "node_id": node.get("id"),
            "agent_id": str(node.get("agent_id") or "media_engine"),
            "content": rendered_md,
            "media_matrix": matrix,
            "kanban_task_id": kanban_task_id,
        }
    except Exception as mexc:
        await asyncio.to_thread(
            kanban_update,
            kanban_task_id,
            "blocked",
            result=str(mexc),
            block_kind="workflow_error",
            event_kind="workflow_node_failed",
            event_payload={"node_id": node.get("id"), "type": node_type, "error": str(mexc)},
        )
        return {
            "status": "error",
            "node_id": node.get("id"),
            "error": str(mexc),
            "content": "",
            "kanban_task_id": kanban_task_id,
        }
