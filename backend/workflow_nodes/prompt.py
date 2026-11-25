"""Cluster 4 — Profil-Aufloesung, Markenstimme und Prompt-Bau des DAG-Executors.

Reine Extraktion aus ``default_agent_node_executor`` (frueher ~:1274-1345).
KEINE Logikaenderung: Reihenfolge der ``sections``, ``{{item}}``-Substitution,
``config/voice.md``-Injektion, Upstream-Trunkierung ``[:4000]`` und alle
Defaults sind 1:1 uebernommen.

Das ``PromptContext`` traegt bewusst auch die Werte, die spaetere Cluster
(C6 Tool-Loop, C7 Schema, C8 Anti-Slop, C9 Deliverable, C10 Return) brauchen.
Die Facade behaelt damit saemtliche Locals und wird zur reinen Orchestrierung.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

__all__ = ["PromptContext", "build_agent_prompt"]


@dataclass(frozen=True)
class PromptContext:
    """Alle aus Profil + Node abgeleiteten Werte fuer einen Agenten-Schritt."""

    agent_name: str
    role: str
    system_prompt: str
    model: str
    escalation_model: str
    reasoning_level: str
    channel_hint: str
    is_content_node: bool
    node_title: str
    full_prompt: str
    eff_system_prompt: str


def build_agent_prompt(
    node: Dict[str, Any],
    upstream: Dict[str, Any],
    prof: Dict[str, Any],
    agent_id: str,
) -> PromptContext:
    """Baut System-Prompt, Prompt-Sektionen und Content-/Voice-Flags auf.

    Synchron und frei von DAG-Effekten (kein Kanban, kein Dispatcher). Die
    Lazy-Imports ``archon.core.runtime.APP_ROOT`` / ``archon.core.paths``
    bleiben zur Laufzeit aufgeloest, damit bestehende Patches greifen.
    """
    agent_name = str(prof.get("person_name") or prof.get("name") or agent_id)
    role = str(prof.get("role") or prof.get("category") or "Fach-Spezialist")
    system_prompt = str(
        prof.get("system_prompt")
        or prof.get("prompt")
        or f"Du bist {agent_name} in Archon OS. Bearbeite deinen Workflow-Schritt praezise und strukturiert."
    )
    model = str(node.get("model") or prof.get("model") or "deepseek/deepseek-chat").strip()
    # Punkt 3.2.6: Cheap-First -> Frontier-Escalation pro Node
    escalation_model = str(node.get("escalation_model") or "").strip()
    reasoning_level = str(node.get("reasoning_effort") or "medium").strip()

    # Optionale Markenstimme (config/voice.md) automatisch fuer Content-/Marketing-Schritte injizieren
    voice_block = ""
    channel_hint = str(node.get("channel") or "").strip().lower()
    is_content_node = bool(
        channel_hint
        or node.get("quality_gate")
        or any(
            kw in f"{agent_id} {role} {node.get('title', '')}".lower()
            for kw in ("writer", "content", "linkedin", "youtube", "tiktok", "shorts", "social", "storyteller", "newsletter", "blog")
        )
    )
    if is_content_node:
        try:
            from archon.core.runtime import APP_ROOT

            voice_path = os.path.join(APP_ROOT, "config", "voice.md")
            if os.path.isfile(voice_path):
                with open(voice_path, "r", encoding="utf-8", errors="ignore") as voice_file:
                    voice_txt = voice_file.read(3000).strip()
                if voice_txt:
                    voice_block = f"\n\n[BRAND VOICE & STIL-VORGABEN (config/voice.md)]\n{voice_txt}"
        except OSError as voice_exc:
            logger.debug("[WorkflowDAG] config/voice.md nicht lesbar: %s", voice_exc)

    # Prompt inkl. Upstream-Kontext & Guardrails aufbauen
    sections: List[str] = []
    node_title = str(node.get("title") or node.get("id") or "Workflow-Schritt")
    sections.append(f"WORKFLOW-SCHRITT: {node_title}")
    if node.get("prompt"):
        sections.append(str(node["prompt"]))
    if node.get("expected_output"):
        sections.append(f"[ERWARTETES ERGEBNIS]\n{node['expected_output']}")
    if node.get("allowed_tools"):
        allowed_list = [str(t) for t in node["allowed_tools"] if str(t).strip()]
        sections.append(
            f"[ERLAUBTE TOOLS]\n{', '.join(allowed_list)}\n"
            "Wenn du ein Tool ausfuehren musst, antworte exakt mit einem JSON-Objekt: "
            '{"tool_call": {"name": "<tool_name>", "args": {...}}}'
        )
    if node.get("forbidden_actions"):
        sections.append("[VERBOTEN / GUARDRAILS]\n- " + "\n- ".join(str(f) for f in node["forbidden_actions"]))
    if node.get("map_item") is not None:
        item_val = node["map_item"]
        item_str = json.dumps(item_val, ensure_ascii=False) if isinstance(item_val, (dict, list)) else str(item_val)
        sections.append(f"[AKTUELLER MAP-EINTRAG ({int(node.get('map_index', 0)) + 1}/{int(node.get('map_total', 1))})]\n{item_str}")
        if node.get("prompt") and "{{item}}" in str(node.get("prompt")):
            for p_idx, p_sec in enumerate(sections):
                if "{{item}}" in p_sec:
                    sections[p_idx] = p_sec.replace("{{item}}", item_str)
    if upstream:
        up_blocks = []
        for dep_id, dep_val in upstream.items():
            if isinstance(dep_val, dict):
                txt = dep_val.get("content") or dep_val.get("summary") or dep_val.get("result") or json.dumps(dep_val, ensure_ascii=False)
            else:
                txt = str(dep_val)
            up_blocks.append(f"### Vorlauf-Schritt `{dep_id}`:\n{str(txt)[:4000]}")
        sections.append("[UPSTREAM-ERGEBNISSE AUS VORHERIGEN SCHRITTEN]\n" + "\n\n".join(up_blocks))

    full_prompt = "\n\n".join(sections)
    eff_system_prompt = system_prompt + voice_block
    return PromptContext(
        agent_name=agent_name,
        role=role,
        system_prompt=system_prompt,
        model=model,
        escalation_model=escalation_model,
        reasoning_level=reasoning_level,
        channel_hint=channel_hint,
        is_content_node=is_content_node,
        node_title=node_title,
        full_prompt=full_prompt,
        eff_system_prompt=eff_system_prompt,
    )
