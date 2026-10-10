# -*- coding: utf-8 -*-
"""
telegram_notify.py — Telegram-Push-Kanal der Delegations-Engine (ARCHON-OS)

Zweck: Sendet Status-Pings (done / blocked / review / approval) aus der
Delegations-Engine und dem Mission-Modus an den Kommunikations-Bot
(@Beatman_bot, Profil telegram_bot) — der Owner bekommt sie aufs Handy.

WICHTIG — Architektur (User-Vorgabe):
  - Dieser Bot-Token wird hier NUR für sendMessage (senden) genutzt.
  - Der telegram_bot-Gateway im hermes-Container bleibt der einzige POLLER
    (getUpdates); Senden und Polling parallel sind Telegram-konform.
  - Fehlertolerant: Ein fehlgeschlagener Ping darf NIEMALS den Delegations-
    Fluss blockieren — er wird aber sichtbar geloggt (kein stilles pass).

HITL-Freigabe (User-Wunsch): Nachrichten mit Status 'review'/'approval'
bekommen ein Inline-Keyboard mit 3 Buttons:
  [ 📋 Details ] [ ✅ Erlauben ] [ ❌ Verbieten ]
Callback-Daten (vom telegram_bot-Gateway verarbeitet, siehe Skill
'archon-remote-control' im Profil telegram_bot):
  app:details:<task_id>   -> volle Task-Details als Telegram-Bericht
  app:approve:<task_id>   -> Freigabe (Kanban: review->todo | Mission: in_progress)
  app:reject:<task_id>    -> Verbieten (Kanban: review->backlog | Mission: dismissed)
"""

import os
import logging
import httpx

logger = logging.getLogger("archon_os")

_TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_TELEGRAM_TIMEOUT = 10.0


def telegram_enabled() -> bool:
    """True, wenn Token + Chat-ID konfiguriert sind."""
    return bool(_TELEGRAM_BOT_TOKEN and _TELEGRAM_CHAT_ID)


def _api_url(method: str) -> str:
    return _TELEGRAM_API_BASE.format(token=_TELEGRAM_BOT_TOKEN, method=method)


def send_telegram_message(text: str, reply_markup: dict = None) -> bool:
    """Sendet eine Textnachricht an den Owner-Chat. Gibt True bei Erfolg zurück.

    Fehlschläge werden als WARNING geloggt (nie still) und geben False zurück.
    """
    if not telegram_enabled():
        logger.warning("[Telegram] Ping übersprungen: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nicht konfiguriert.")
        return False
    payload = {
        "chat_id": _TELEGRAM_CHAT_ID,
        "text": text[:4000],  # Telegram-Limit: 4096 Zeichen
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        with httpx.Client(timeout=_TELEGRAM_TIMEOUT) as client:
            resp = client.post(_api_url("sendMessage"), json=payload)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return True
        logger.warning(f"[Telegram] sendMessage fehlgeschlagen: HTTP {resp.status_code} — {data.get('description', 'unbekannt')}")
        return False
    except Exception as e:
        logger.warning(f"[Telegram] sendMessage Fehler (Netzwerk): {e}")
        return False


def _hitl_keyboard(task_id: str) -> dict:
    """Inline-Keyboard mit den 3 HITL-Buttons (Details / Erlauben / Verbieten)."""
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Details", "callback_data": f"app:details:{task_id}"},
            ],
            [
                {"text": "✅ Erlauben", "callback_data": f"app:approve:{task_id}"},
                {"text": "❌ Verbieten", "callback_data": f"app:reject:{task_id}"},
            ],
        ]
    }


def _excerpt(text: str, limit: int = 350) -> str:
    text = (text or "").strip()
    if not text:
        return "_(keine Ergebnis-Text im Task hinterlegt — Details im Kanban/Showroom)_."
    if len(text) <= limit:
        return text
    return text[:limit] + " […]"


def notify_task_status(task_id: str, status: str, title: str, result: str = "", obsidian_rel: str = None) -> bool:
    """Delegations-Ping: done / blocked / review aus _bg_watch_task."""
    head_map = {
        "done": "✅ *AUFGABE ERLEDIGT*",
        "blocked": "⛔ *AUFGABE BLOCKIERT*",
        "review": "🔐 *ENTSCHEIDUNG NÖTIG*",
    }
    emoji_head = head_map.get(status, "ℹ️ *AUFGABEN-STATUS*")
    title = (title or task_id).strip()
    lines = [
        emoji_head,
        f"*Task:* `{task_id}` — {title}",
        "",
        _excerpt(result),
    ]
    if obsidian_rel:
        lines.append("")
        lines.append(f"📁 Obsidian: `01_PROJEKTE/{obsidian_rel}`")
    # Freigabe-Buttons nur, wenn eine Entscheidung des Owners nötig ist
    if status in ("review", "blocked"):
        lines.append("")
        lines.append("_Bitte Entscheidung treffen — oder als Text antworten:_")
        lines.append(f"`Details {task_id}` · `Erlauben {task_id}` · `Verbieten {task_id}`")
        return send_telegram_message("\n".join(lines), reply_markup=_hitl_keyboard(task_id))
    return send_telegram_message("\n".join(lines))


def notify_mission_approval(task_id: str, title: str, agent_name: str) -> bool:
    """Mission-Modus-Ping: Task liegt im HITL-Approval-Gate (status=approval)."""
    lines = [
        "🔐 *FREIGABE ERFORDERLICH*",
        f"*Mission:* `{task_id}` — {title}",
        f"*Agent:* {agent_name}",
        "",
        "_Bitte Entscheidung treffen — oder als Text antworten:_",
        f"`Details {task_id}` · `Erlauben {task_id}` · `Verbieten {task_id}`",
    ]
    return send_telegram_message("\n".join(lines), reply_markup=_hitl_keyboard(task_id))
