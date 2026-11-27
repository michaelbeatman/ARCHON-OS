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

import contextlib
import json
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("archon_os")


@contextlib.contextmanager
def _telegram_trace_headers():
    """D16: Telegram-Notify ist eine Systemgrenze — Child-Span + W3C-Header."""
    try:
        from backend.trace_context import child_span, inject_headers
    except Exception as exc:
        logger.warning("[Telegram] Trace-Kontext nicht verfügbar: %s", exc)
        yield {}
        return
    with child_span():
        yield inject_headers()

_TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_TELEGRAM_TIMEOUT = 10.0
# Telegram-Bot-API: sendDocument akzeptiert bis 50 MB; wir bleiben mit Puffer darunter.
_TELEGRAM_DOC_MAX_BYTES = 45 * 1024 * 1024


_ENABLED_CACHE = {"ts": 0.0, "value": False}
_WARNED_ONCE = {"done": False}


def telegram_enabled() -> bool:
    """Liest settings.json -> telegram.enabled (Standard: aus).

    Früher hart auf False; jetzt konfigurierbar, damit n8n-Routinen und
    Alarme wieder senden können, sobald der Eigentümer es einschaltet.
    """
    import json as _json
    import time as _time

    now = _time.time()
    if now - _ENABLED_CACHE["ts"] < 30:
        return bool(_ENABLED_CACHE["value"])

    enabled = False
    for path in ("/app/settings.json", "/app/agent_workspace/settings.json"):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
            tg = data.get("telegram")
            if isinstance(tg, dict) and "enabled" in tg:
                enabled = bool(tg.get("enabled"))
                break
        except Exception:
            continue

    _ENABLED_CACHE.update({"ts": now, "value": enabled})
    return enabled


# --- 2d (12.10.2026, User-Entscheidung): HTML statt Markdown ---------------
# Markdown zerbrach an jedem '_' (Tool-/Profilnamen) mit HTTP 400. Im HTML-Modus
# muessen NUR <, > und & escaped werden -> robust. Aufrufer-Regel: eigene
# Nutzdaten mit tg_escape() entschaerfen, fertige Tags selbst setzen.
_TG_TYP_LABEL = {
    "synthesis_freigabe": "Synthese freigeben",
    "delegation_review": "Delegation prüfen",
    "mission_freigabe": "Mission freigeben",
    "permission_gate": "Rechte freigeben",
}


def tg_escape(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def decision_message(*, typ, titel="", projekt="", von="", ref="", kurzfassung="",
                     zahlen=None, anhang=None, fallback_ref="", zeit=None) -> str:
    """Nachrichtenformat 'Kontext zuerst' (Variante B): beschrifteter Kopf als
    Monospace-Block (ausgerichtet), Kurzfassung, Zahlen, Anhang, dezenter
    Text-Fallback. Gibt HTML zurueck (passend zu parse_mode=HTML)."""
    e = tg_escape
    kopf = "🔐 <b>ENTSCHEIDUNG NÖTIG</b>" + (f"     <i>{e(zeit)}</i>" if zeit else "")
    kontext = [("Was", _TG_TYP_LABEL.get(typ, typ or "Entscheidung"))]
    if titel:
        kontext.append(("Titel", titel))
    if projekt:
        kontext.append(("Projekt", projekt))
    if von:
        kontext.append(("Von", von))
    if ref:
        kontext.append(("Referenz", ref))
    breite = max(len(lbl) for lbl, _ in kontext)
    block = "\n".join(f"{lbl.ljust(breite)}  {v}" for lbl, v in kontext)
    teile = [kopf, f"<pre>{e(block)}</pre>"]
    if kurzfassung:
        teile.append("<b>Worum es geht</b>")
        teile.append(e(kurzfassung))
    if zahlen:
        teile.append(e("\n".join(zahlen)))
    if anhang:
        teile.append(f"📎 {e(anhang)}")
    if fallback_ref:
        teile.append(f"Kein Knopf zur Hand? <code>Erlauben {e(fallback_ref)}</code>")
    return "\n\n".join(teile)


def _api_url(method: str, bot_token: Optional[str] = None) -> str:
    token = (bot_token or "").strip() or _TELEGRAM_BOT_TOKEN
    return _TELEGRAM_API_BASE.format(token=token, method=method)


def send_telegram_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    *,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> bool:
    """Sendet eine Textnachricht an den angegebenen User-Chat (Fallback: Owner-Chat).

    Fehlschläge werden als WARNING geloggt (nie still) und geben False zurück.
    """
    if not telegram_enabled():
        if not _WARNED_ONCE["done"]:
            logger.info("[Telegram] Versand deaktiviert (settings.json -> telegram.enabled = false).")
            _WARNED_ONCE["done"] = True
        return False
    target_chat = str(chat_id or "").strip() or _TELEGRAM_CHAT_ID
    if not target_chat:
        logger.warning("[Telegram] sendMessage übersprungen: keine Ziel-chat_id konfiguriert.")
        return False
    payload = {
        "chat_id": target_chat,
        "text": text[:4000],  # Telegram-Limit: 4096 Zeichen
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        with httpx.Client(timeout=_TELEGRAM_TIMEOUT) as client, _telegram_trace_headers() as trace_headers:
            resp = client.post(_api_url("sendMessage", bot_token=bot_token), json=payload, headers=trace_headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return True
            if resp.status_code == 400 and "parse" in str(data.get("description", "")):
                clean = {k: v for k, v in payload.items() if k != "parse_mode"}
                try:
                    resp2 = client.post(_api_url("sendMessage", bot_token=bot_token), json=clean, headers=trace_headers)
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


def send_telegram_document(file_path: str, caption: str = "", filename: Optional[str] = None,
                           mime: Optional[str] = None, reply_markup: Optional[Dict[str, Any]] = None,
                           parse_mode: Optional[str] = None) -> bool:
    """Sendet eine Datei (z.B. PDF oder HTML) als Dokument an den Owner-Chat."""
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

    # Automatische Erkennung des korrekten MIME-Typs
    if not mime:
        lower_name = name.lower()
        if lower_name.endswith(".pdf"):
            mime = "application/pdf"
        elif lower_name.endswith(".html") or lower_name.endswith(".htm"):
            mime = "text/html"
        else:
            mime = "application/octet-stream"
    try:
        with open(file_path, "rb") as fh:
            files = {"document": (name, fh, mime)}
            data = {"chat_id": _TELEGRAM_CHAT_ID}
            if caption:
                data["caption"] = caption[:1000]
                if parse_mode:
                    data["parse_mode"] = parse_mode
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            with httpx.Client(timeout=45.0) as client, _telegram_trace_headers() as trace_headers:
                resp = client.post(_api_url("sendDocument"), data=data, files=files, headers=trace_headers)
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
        return "(kein Ergebnis-Text im Task hinterlegt — Details im Kanban/Showroom)."
    if len(text) <= limit:
        return text
    return text[:limit] + " […]"


def notify_task_status(task_id: str, status: str, title: str, result: str = "",
                       obsidian_rel: Optional[str] = None, dossier_dir: Optional[str] = None) -> bool:
    """Delegations-Ping: done / blocked / review aus _bg_watch_task.

    12.10.2026 (User-Wunsch "2a"): Bei review/blocked wird der VOLLE Bericht als
    HTML-Dossier ANGEHAENGT (statt nur einem Zeiger auf den Obsidian-Pfad), damit
    der Owner sieht, was er freigibt. Ohne dossier_dir/Inhalt bleibt es beim
    Text-Ping - fehlertolerant, aber sichtbar geloggt.
    """
    head_map = {
        "done": "✅ <b>AUFGABE ERLEDIGT</b>",
        "blocked": "⛔ <b>AUFGABE BLOCKIERT</b>",
        "review": "🔐 <b>ENTSCHEIDUNG NÖTIG</b>",
    }
    plain_head_map = {
        "done": "✅ AUFGABE ERLEDIGT",
        "blocked": "⛔ AUFGABE BLOCKIERT",
        "review": "🔐 ENTSCHEIDUNG NÖTIG",
    }
    e = tg_escape
    emoji_head = head_map.get(status, "ℹ️ <b>AUFGABEN-STATUS</b>")
    title = (title or task_id).strip()
    lines = [
        emoji_head,
        f"<b>Task:</b> <code>{e(task_id)}</code> — {e(title)}",
        "",
        e(_excerpt(result)),
    ]
    if obsidian_rel:
        lines.append("")
        lines.append(f"📁 Obsidian: <code>{e('01_PROJEKTE/' + str(obsidian_rel))}</code>")
    # Freigabe-Buttons nur, wenn eine Entscheidung des Owners nötig ist
    if status in ("review", "blocked"):
        lines.append("")
        lines.append("<i>Bitte Entscheidung treffen:</i>")
        lines.append(f"<code>Details {e(task_id)}</code> · <code>Erlauben {e(task_id)}</code> · <code>Verbieten {e(task_id)}</code>")
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
    e = tg_escape
    lines = [
        "🔐 <b>FREIGABE ERFORDERLICH</b>",
        f"<b>Mission:</b> <code>{e(task_id)}</code> — {e(title)}",
        f"<b>Agent:</b> {e(agent_name)}",
        "",
        "<i>Bitte Entscheidung treffen — oder als Text antworten:</i>",
        f"<code>Details {e(task_id)}</code> · <code>Erlauben {e(task_id)}</code> · <code>Verbieten {e(task_id)}</code>",
    ]
    return send_telegram_message("\n".join(lines), reply_markup=_hitl_keyboard(task_id))
