# -*- coding: utf-8 -*-
"""
backend/special_extensions.py
=============================
Meilenstein 88: Optionale Spezial-Erweiterungen
(flota / own-compute, kujo-hermes, riah-swipe, manners-meter).
"""

from __future__ import annotations

import re
import shlex
from typing import Any, Dict, List, Optional


# 1. flota / own-compute: SSH & Slurm Worker-Dispatch
def build_remote_worker_command(
    host: str,
    user: str,
    task_cmd: str,
    wol_mac: Optional[str] = None,
    slurm_partition: Optional[str] = None,
) -> Dict[str, Any]:
    safe_cmd = shlex.quote(task_cmd)
    if slurm_partition:
        cmd = f"srun --partition={shlex.quote(slurm_partition)} bash -lc {safe_cmd}"
        mode = "slurm"
    else:
        cmd = f"ssh -o BatchMode=yes {shlex.quote(f'{user}@{host}')} {safe_cmd}"
        mode = "ssh"
    return {
        "mode": mode,
        "command": cmd,
        "wol_mac": wol_mac or "",
        "requires_wol": bool(wol_mac),
    }


# 2. kujo-hermes: Approval-gated Kujo-Runtime-Bridge
def prepare_kujo_execution(
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    human_approved: bool = False,
) -> Dict[str, Any]:
    if not human_approved:
        return {
            "allowed": False,
            "requires_hitl": True,
            "tool": tool_name,
            "reason": "Kujo-Ausfuehrung erfordert explizite Human-Approval.",
        }
    return {
        "allowed": True,
        "requires_hitl": False,
        "tool": tool_name,
        "args": args or {},
        "status": "ready_for_kujo_runtime",
    }


# 3. riah-swipe: Medien-Swipe-Deck (Keep / Cut / Redo)
def create_swipe_deck(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    deck_items = [
        {
            "id": str(it.get("id") or f"item_{idx}"),
            "kind": str(it.get("kind") or "media"),
            "uri": str(it.get("uri") or ""),
            "decision": "pending",
            "note": "",
        }
        for idx, it in enumerate(items, start=1)
    ]
    return {"items": deck_items}


def record_swipe_action(
    deck: Dict[str, Any],
    item_id: str,
    action: str,
    note: str = "",
) -> Dict[str, Any]:
    act = (action or "").strip().lower()
    if act not in ("keep", "cut", "redo"):
        raise ValueError(f"Ungueltige Swipe-Aktion: {action}")
    for it in deck.get("items") or []:
        if it["id"] == item_id:
            it["decision"] = act
            it["note"] = note
            return it
    raise KeyError(f"Item '{item_id}' nicht im Swipe-Deck.")


# 4. manners-meter: Hoeflichkeits- & Token-Metrik (ohne Codebloecke)
_POLITE_RE = re.compile(r"\b(bitte|danke|vielen dank|please|thank you|thanks|merci|gracias)\b", re.I)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def analyze_manners_metrics(user_messages: List[str]) -> Dict[str, Any]:
    polite_hits = 0
    polite_tokens_est = 0
    for msg in user_messages:
        cleaned = _CODE_BLOCK_RE.sub(" ", msg or "")
        matches = _POLITE_RE.findall(cleaned)
        polite_hits += len(matches)
        polite_tokens_est += sum(max(1, len(m.split())) for m in matches)
    return {
        "messages_analyzed": len(user_messages),
        "polite_count": polite_hits,
        "estimated_polite_tokens": polite_tokens_est,
    }
