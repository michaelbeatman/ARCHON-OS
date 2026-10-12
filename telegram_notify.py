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
import json
import logging
import httpx

logger = logging.getLogger("archon_os")

_TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_TELEGRAM_TIMEOUT = 10.0
# Telegram-Bot-API: sendDocument akzeptiert bis 50 MB; wir bleiben mit Puffer darunter.
_TELEGRAM_DOC_MAX_BYTES = 45 * 1024 * 1024


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
            # 12.10.2026: Markdown-Entities-400 (z.B. Unterstrich in Tool-Namen
            # 'x_search_probe' -> unvollstaendige Kursiv-Entity) -> EINMAL retry
            # OHNE parse_mode, NOCH INNERHALB des with-Blocks (sonst:
            # "client has been closed"). So kommt jede Nachricht an,
            # Markdown bleibt fuer alle anderen Nachrichten aktiv.
            if resp.status_code == 400 and "parse" in str(data.get("description", "")):
                clean = {k: v for k, v in payload.items() if k != "parse_mode"}
                try:
                    resp2 = client.post(_api_url("sendMessage"), json=clean)
                    data2 = resp2.json()
                    if resp2.status_code == 200 and data2.get("ok"):
                        logger.info("[Telegram] Nachricht ohne Markdown-Rendern zugestellt (Parse-Fallback).")
                        return True
                    logger.warning(f"[Telegram] Retry fehlgeschlagen: HTTP {resp2.status_code} — {data2.get('description', '')}")
                    return False
                except Exception as e_retry:
                    logger.warning(f"[Telegram] Retry-Fehler: {e_retry}")
                    return False
            logger.warning(f"[Telegram] sendMessage fehlgeschlagen: HTTP {resp.status_code} — {data.get('description', 'unbekannt')}")
            return False
    except Exception as e:
        logger.warning(f"[Telegram] sendMessage Fehler (Netzwerk): {e}")
        return False


def send_telegram_document(file_path: str, caption: str = "", filename: str = None,
                           mime: str = "text/html", reply_markup: dict = None) -> bool:
    """Sendet eine Datei (z.B. das HTML-Dossier eines Zwischenberichts) als
    Telegram-Dokument an den Owner-Chat. Gibt True bei Erfolg zurueck.

    12.10.2026 (User-Wunsch "2a"): Berichte sollen MIT der Freigabe-Anfrage
    kommen, damit der Owner sieht, was er freigibt. Bewusst OHNE parse_mode im
    caption - der Markdown-Entities-400 soll hier gar nicht erst entstehen.
    """
    if not telegram_enabled():
        logger.warning("[Telegram] Dokument-Ping übersprungen: Token/Chat-ID nicht konfiguriert.")
        return False
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"[Telegram] Dokument nicht gefunden: {file_path}")
        return False
    try:
        size = os.path.getsize(file_path)
    except OSError:
        size = 0
    if size <= 0:
        logger.warning(f"[Telegram] Dokument leer - nicht gesendet: {file_path}")
        return False
    if size > _TELEGRAM_DOC_MAX_BYTES:
        logger.warning(f"[Telegram] Dokument zu groß ({size} B > {_TELEGRAM_DOC_MAX_BYTES} B) - nicht gesendet.")
        return False
    name = filename or os.path.basename(file_path)
    try:
        with open(file_path, "rb") as fh:
            files = {"document": (name, fh, mime)}
            data = {"chat_id": _TELEGRAM_CHAT_ID}
            if caption:
                data["caption"] = caption[:1000]
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(_api_url("sendDocument"), data=data, files=files)
                j = resp.json()
                if resp.status_code == 200 and j.get("ok"):
                    logger.info(f"[Telegram] Dokument zugestellt: {name} ({size} B)")
                    return True
                logger.warning(f"[Telegram] sendDocument fehlgeschlagen: HTTP {resp.status_code} — {j.get('description', 'unbekannt')}")
                return False
    except Exception as e:
        logger.warning(f"[Telegram] sendDocument Fehler: {e}")
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


def notify_task_status(task_id: str, status: str, title: str, result: str = "",
                       obsidian_rel: str = None, dossier_dir: str = None) -> bool:
    """Delegations-Ping: done / blocked / review aus _bg_watch_task.

    12.10.2026 (User-Wunsch "2a"): Bei review/blocked wird der VOLLE Bericht als
    HTML-Dossier ANGEHAENGT (statt nur einem Zeiger auf den Obsidian-Pfad), damit
    der Owner sieht, was er freigibt. Ohne dossier_dir/Inhalt bleibt es beim
    Text-Ping - fehlertolerant, aber sichtbar geloggt.
    """
    head_map = {
        "done": "✅ *AUFGABE ERLEDIGT*",
        "blocked": "⛔ *AUFGABE BLOCKIERT*",
        "review": "🔐 *ENTSCHEIDUNG NÖTIG*",
    }
    plain_head_map = {
        "done": "✅ AUFGABE ERLEDIGT",
        "blocked": "⛔ AUFGABE BLOCKIERT",
        "review": "🔐 ENTSCHEIDUNG NÖTIG",
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
        # 2a: vollen Bericht als Dossier ANHAENGEN (captions sind auf 1024 Zeichen begrenzt,
        # darum bewusst OHNE parse_mode und ohne den langen Text-Auszug)
        if dossier_dir and (result or "").strip():
            try:
                from dossier_builder import build_dossier_from_report
                dpath = build_dossier_from_report(
                    f"{'Review' if status == 'review' else 'Blockiert'}: {title}",
                    result,
                    dossier_dir,
                    f"{task_id}_{status}",
                    ref_id=task_id,
                    quelle="Archon-Delegation",
                )
                if dpath:
                    caption = (
                        f"{plain_head_map.get(status, 'STATUS')} — {title}\n"
                        f"Task: {task_id}\n\n"
                        f"Der vollständige Bericht liegt als Anhang bei.\n"
                        f"Entscheidung: „Erlauben {task_id}“ / „Verbieten {task_id}“"
                    )
                    if send_telegram_document(dpath, caption=caption):
                        return True
                    logger.warning("[Telegram] Dossier-Anhang fehlgeschlagen — Fallback auf Text-Ping.")
                else:
                    logger.warning("[Telegram] Dossier konnte nicht erzeugt werden — Text-Ping stattdessen.")
            except Exception as d_err:
                logger.warning(f"[Telegram] Dossier-Anhang nicht möglich: {d_err}")
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
