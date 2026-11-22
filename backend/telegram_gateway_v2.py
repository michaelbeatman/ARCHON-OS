# -*- coding: utf-8 -*-
"""
backend/telegram_gateway_v2.py
==============================
Meilenstein 32: Telegram-Kommunikation & Gateway-Haertung.

- Konfliktfreies Session-Keying pro Chat + Ziel-Agent
- Deterministisches Slash-Command-Routing (/robert, /anwalt, ...)
- Inline-HITL-Keyboard-Builder & Callback-Parser
- Edit-in-Place Live-Status-Formatter fuer Langlaeufer-Tasks
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

AGENT_COMMAND_ALIASES: Dict[str, str] = {
    "robert": "executive_decision_architect",
    "ceo": "executive_decision_architect",
    "anwalt": "legal_counsel",
    "legal": "legal_counsel",
    "steuer": "tax_holding_advisor",
    "tax": "tax_holding_advisor",
    "finance": "finance_lead",
    "coder": "senior_fullstack_engineer",
    "dev": "senior_fullstack_engineer",
    "scrum": "agile_scrum_master",
    "qa": "qa_test_engineer",
    "linkedin": "linkedin_social_media_specialist",
    "social": "linkedin_social_media_specialist",
    "default": "default",
}


def resolve_telegram_session_key(chat_id: int | str, agent_id: str = "default") -> str:
    clean_agent = (agent_id or "default").strip().lower()
    return f"tg_{chat_id}_{clean_agent}"


def parse_telegram_agent_route(text: str) -> Tuple[str, str]:
    raw = (text or "").strip()
    if raw.startswith("/"):
        parts = raw.split(None, 1)
        cmd = parts[0][1:].split("@")[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if cmd in AGENT_COMMAND_ALIASES:
            return AGENT_COMMAND_ALIASES[cmd], rest
    return "default", raw


def build_hitl_inline_keyboard(
    approval_id: str,
    approve_label: str = "Freigeben",
    reject_label: str = "Ablehnen",
) -> Dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": approve_label, "callback_data": f"hitl:approve:{approval_id}"},
            {"text": reject_label, "callback_data": f"hitl:reject:{approval_id}"},
        ]]
    }


def parse_hitl_callback(callback_data: str) -> Optional[Dict[str, str]]:
    parts = (callback_data or "").strip().split(":", 2)
    if len(parts) != 3 or parts[0] != "hitl" or parts[1] not in ("approve", "reject"):
        return None
    return {"action": parts[1], "approval_id": parts[2], "approved": parts[1] == "approve"}


def format_live_task_status(
    task_id: str,
    title: str,
    elapsed_seconds: float,
    step_text: str,
    status: str = "running",
) -> str:
    mins, secs = divmod(max(0, int(elapsed_seconds)), 60)
    return (
        f"[{status.upper()}] {title} (`{task_id}`)\n"
        f"Laufzeit: {mins:02d}:{secs:02d} | Schritt: {step_text}"
    )
