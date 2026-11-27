# -*- coding: utf-8 -*-
"""
backend/telegram_gateway_v2.py
==============================
Meilenstein 32 + M95: Telegram-Kommunikation, Gateway-Haertung &
benutzerspezifische Telegram-Kanaele fuer HITL-/Vertretungs-Freigaben.

- Konfliktfreies Session-Keying pro Chat + Ziel-Agent
- Deterministisches Slash-Command-Routing (/robert, /anwalt, ...)
- Inline-HITL-Keyboard-Builder & Callback-Parser
- Edit-in-Place Live-Status-Formatter fuer Langlaeufer-Tasks
- M95: Benutzerspezifisches Telegram-Routing & strenge Chat-ID-Autorisierung
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("archon.telegram_gateway_v2")

_TELEGRAM_CHAT_ID_RE = re.compile(r"^-?[0-9]{1,20}$")

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


def is_valid_telegram_chat_id(chat_id: Any) -> bool:
    return bool(_TELEGRAM_CHAT_ID_RE.match(str(chat_id or "").strip()))


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


def parse_hitl_callback(callback_data: str) -> Optional[Dict[str, Any]]:
    parts = (callback_data or "").strip().split(":", 2)
    if len(parts) != 3 or parts[0] not in ("hitl", "app"):
        return None
    action = parts[1].strip().lower()
    if action not in ("approve", "reject", "deny"):
        return None
    approval_id = parts[2].strip()
    if not approval_id:
        return None
    normalized = "reject" if action == "deny" else action
    return {
        "action": normalized,
        "approval_id": approval_id,
        "approved": normalized == "approve",
    }


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


def _audit_telegram_auth(action: str, actor: str, details: Dict[str, Any]) -> None:
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event("telegram_hitl", action, actor, details)
    except Exception as exc:
        logger.warning("[TelegramGateway] Audit-Event (%s) nicht schreibbar: %s", action, exc)


def resolve_user_telegram_channel(
    user_identifier: Optional[str] = None,
    *,
    fallback_chat_id: str = "",
    fallback_bot_token: str = "",
    allow_single_user_fallback: bool = True,
) -> Dict[str, Any]:
    """Loest den Telegram-Kanal fuer einen Archon-User auf (mit Single-User-Fallback)."""
    clean_user = str(user_identifier or "").strip()
    if clean_user:
        try:
            from backend.auth_service import auth_service

            ch = auth_service.get_user_telegram_channel(clean_user)
            if ch and ch.get("is_active") and is_valid_telegram_chat_id(ch.get("chat_id")):
                return {
                    "resolved": True,
                    "source": "user",
                    "user_id": ch["user_id"],
                    "username": ch["username"],
                    "role": ch["role"],
                    "chat_id": ch["chat_id"],
                    "bot_token": ch.get("bot_token") or fallback_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
                }
        except Exception as exc:
            logger.warning("[TelegramGateway] User-Kanal-Lookup fehlgeschlagen (%s): %s", clean_user, exc)

    if allow_single_user_fallback:
        fb_chat = (fallback_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
        fb_tok = (fallback_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        if is_valid_telegram_chat_id(fb_chat):
            return {
                "resolved": True,
                "source": "single_user_fallback",
                "user_id": clean_user or "owner",
                "username": clean_user or "owner",
                "role": "admin",
                "chat_id": fb_chat,
                "bot_token": fb_tok,
            }

    return {
        "resolved": False,
        "source": "none",
        "user_id": clean_user,
        "username": clean_user,
        "role": "",
        "chat_id": "",
        "bot_token": "",
    }


def route_approval_telegram_notification(
    request_record: Dict[str, Any],
    *,
    event_type: str = "approval_request",
    target_user_id: Optional[str] = None,
    sender: Optional[Callable[..., bool]] = None,
    allow_single_user_fallback: bool = True,
) -> Dict[str, Any]:
    """Leitet Freigaben, Timeouts & Vertretungen an den Telegram-Kanal des zustaendigen Menschen."""
    req_id = str(request_record.get("request_id") or request_record.get("id") or "").strip()
    title = str(request_record.get("title") or "Freigabeanfrage")
    domain = str(request_record.get("domain") or "finance")
    status = str(request_record.get("status") or "pending")
    escalated_to = str(request_record.get("escalated_to") or "").strip()
    assigned = str(request_record.get("assigned_approver") or "").strip()

    recipient = str(target_user_id or "").strip() or escalated_to or assigned or "admin"
    channel = resolve_user_telegram_channel(
        recipient,
        allow_single_user_fallback=allow_single_user_fallback,
    )
    if not channel["resolved"]:
        return {
            "sent": False,
            "reason": f"Kein Telegram-Kanal fuer '{recipient}' konfiguriert.",
            "recipient": recipient,
            "chat_id": "",
            "source": channel["source"],
        }

    is_blocked = status == "escalated_blocked" or event_type == "escalated_blocked"
    header = (
        "⛔ <b>ESKALATION BLOCKIERT (FAIL-CLOSED)</b>"
        if is_blocked
        else (
            "⏰ <b>FREIGABE-ESKALATION / VERTRETUNG</b>"
            if escalated_to or event_type in ("timeout", "deputy_escalation")
            else "🔐 <b>HITL-FREIGABE ERFORDERLICH</b>"
        )
    )
    lines = [
        header,
        f"ID: <code>{req_id}</code>",
        f"Domain: {domain} | Status: {status}",
        f"Titel: {title}",
    ]
    if request_record.get("amount"):
        lines.append(f"Betrag: {request_record.get('amount')} {request_record.get('currency', 'EUR')}")
    if escalated_to:
        lines.append(f"Stellvertreter: {escalated_to}")
    if request_record.get("escalation_reason"):
        lines.append(f"Hinweis: {request_record.get('escalation_reason')}")
    text = "\n".join(lines)

    keyboard = None if is_blocked or not req_id else build_hitl_inline_keyboard(req_id)

    send_fn = sender
    if send_fn is None:
        from telegram_notify import send_telegram_message

        send_fn = send_telegram_message

    sent = bool(
        send_fn(
            text,
            reply_markup=keyboard,
            chat_id=channel["chat_id"],
            bot_token=channel["bot_token"] or None,
        )
    )
    return {
        "sent": sent,
        "recipient": recipient,
        "chat_id": channel["chat_id"],
        "source": channel["source"],
        "event_type": event_type,
        "request_id": req_id,
    }


def authorize_hitl_callback(
    callback_data: str,
    chat_id: int | str,
    *,
    expected_user_id: Optional[str] = None,
    approval_record: Optional[Dict[str, Any]] = None,
    fallback_owner_chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Prueft streng, ob die sendende chat_id zur Freigabe/Ablehnung berechtigt ist (M95).

    Verhindert Fremd-Freigaben ueber nicht autorisierte Chats, Viewer-Accounts oder
    den eigenen Antragsteller (Vier-Augen-Prinzip).
    """
    parsed = parse_hitl_callback(callback_data)
    if not parsed:
        return {"authorized": False, "reason": "invalid_callback_data", "parsed": None}

    clean_chat = str(chat_id or "").strip()
    if not is_valid_telegram_chat_id(clean_chat):
        _audit_telegram_auth("callback_denied", "unknown", {"reason": "invalid_chat_id", "chat_id": clean_chat})
        return {"authorized": False, "reason": "invalid_chat_id", "parsed": parsed}

    from backend.approval_policy_engine import (
        ADMIN_ONLY_DEPUTY_DOMAINS,
        ALLOWED_DEPUTY_ROLES,
        _actor_identity_tokens,
    )
    from backend.auth_service import auth_service

    rec = approval_record or {}
    domain = str(rec.get("domain") or "finance").strip().lower()
    required_roles = frozenset({"admin"}) if domain in ADMIN_ONLY_DEPUTY_DOMAINS else ALLOWED_DEPUTY_ROLES
    expected = (
        str(expected_user_id or "").strip()
        or str(rec.get("escalated_to") or "").strip()
        or str(rec.get("assigned_approver") or "").strip()
    )
    requester = str(rec.get("requester_id") or "").strip()

    chat_user = auth_service.get_user_by_telegram_chat_id(clean_chat)
    if chat_user is not None:
        if not chat_user.get("is_active"):
            _audit_telegram_auth(
                "callback_denied",
                chat_user["username"],
                {"reason": "inactive_user", "chat_id": clean_chat, "approval_id": parsed["approval_id"]},
            )
            return {"authorized": False, "reason": "inactive_user", "parsed": parsed}

        if str(chat_user.get("role") or "").lower() not in required_roles:
            _audit_telegram_auth(
                "callback_denied",
                chat_user["username"],
                {
                    "reason": "insufficient_role",
                    "role": chat_user.get("role"),
                    "chat_id": clean_chat,
                    "approval_id": parsed["approval_id"],
                },
            )
            return {"authorized": False, "reason": "insufficient_role", "parsed": parsed}

        user_tokens = _actor_identity_tokens(chat_user["username"]) | _actor_identity_tokens(chat_user["id"])
        if requester and bool(user_tokens & _actor_identity_tokens(requester)):
            _audit_telegram_auth(
                "callback_denied",
                chat_user["username"],
                {"reason": "four_eyes_requester_conflict", "chat_id": clean_chat, "approval_id": parsed["approval_id"]},
            )
            return {"authorized": False, "reason": "four_eyes_requester_conflict", "parsed": parsed}

        if expected:
            exp_user = auth_service.get_user_by_identifier(expected)
            exp_tokens = _actor_identity_tokens(expected)
            if exp_user:
                exp_tokens |= _actor_identity_tokens(exp_user["username"]) | _actor_identity_tokens(exp_user["id"])
            if not (user_tokens & exp_tokens):
                _audit_telegram_auth(
                    "callback_denied",
                    chat_user["username"],
                    {
                        "reason": "unauthorized_chat_for_target_user",
                        "expected": expected,
                        "chat_id": clean_chat,
                        "approval_id": parsed["approval_id"],
                    },
                )
                return {
                    "authorized": False,
                    "reason": "unauthorized_chat_for_target_user",
                    "parsed": parsed,
                }

        _audit_telegram_auth(
            "callback_authorized",
            chat_user["username"],
            {"chat_id": clean_chat, "action": parsed["action"], "approval_id": parsed["approval_id"]},
        )
        return {
            "authorized": True,
            "reason": "ok",
            "actor": chat_user["username"],
            "user_id": chat_user["id"],
            "role": chat_user["role"],
            "chat_id": clean_chat,
            "parsed": parsed,
        }

    # Kein User mit dieser chat_id verknuepft: Single-User-Fallback NUR erlaubt,
    # wenn der erwartete User keinen eigenen Telegram-Kanal hat UND chat_id exakt
    # der konfigurierten Owner-Fallback-Chat-ID entspricht.
    expected_has_own_chat = False
    if expected:
        exp_ch = auth_service.get_user_telegram_channel(expected)
        if exp_ch and is_valid_telegram_chat_id(exp_ch.get("chat_id")):
            expected_has_own_chat = True

    owner_fb = str(
        fallback_owner_chat_id
        if fallback_owner_chat_id is not None
        else os.environ.get("TELEGRAM_CHAT_ID", "")
    ).strip()

    if not expected_has_own_chat and owner_fb and clean_chat == owner_fb:
        actor_name = expected or "admin"
        _audit_telegram_auth(
            "callback_authorized_fallback",
            actor_name,
            {"chat_id": clean_chat, "action": parsed["action"], "approval_id": parsed["approval_id"]},
        )
        return {
            "authorized": True,
            "reason": "single_user_fallback",
            "actor": actor_name,
            "user_id": actor_name,
            "role": "admin",
            "chat_id": clean_chat,
            "parsed": parsed,
        }

    _audit_telegram_auth(
        "callback_denied",
        "unknown",
        {
            "reason": "unauthorized_chat_id",
            "chat_id": clean_chat,
            "expected": expected,
            "approval_id": parsed["approval_id"],
        },
    )
    return {"authorized": False, "reason": "unauthorized_chat_id", "parsed": parsed}
