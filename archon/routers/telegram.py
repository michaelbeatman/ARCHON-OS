"""Router fuer Telegram-Relay, Voice-Relay und Benachrichtigungsversand."""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from archon.routers._rbac import require_admin_or_503

logger = logging.getLogger("archon.routers.telegram")

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_TELEGRAM_CHAT_ID_RE = re.compile(r"^-?[0-9]{1,20}$")


def _redact_telegram_secrets(text: object) -> str:
    """Entfernt Bot-Token und Bot-API-URLs aus Fehlertexten (Antwort/Log)."""
    out = str(text)
    out = re.sub(r"https?://api\.telegram\.org/\S*", "<telegram-api-url>", out)
    out = re.sub(r"bot[0-9]{3,}:[A-Za-z0-9_-]{10,}", "bot<redacted>", out)
    for env_key in ("TELEGRAM_BOT_TOKEN",):
        secret = (os.environ.get(env_key) or "").strip()
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


class TelegramSendPayload(BaseModel):
    text: str
    chat_id: Optional[str] = ""
    parse_mode: Optional[str] = "Markdown"


@router.post("/relay")
async def api_telegram_relay(
    ziel_agent: str = Form(""),
    text: str = Form(""),
    datei_name: str = Form(""),
    datei_b64: str = Form(""),
):
    """TELEGRAM-RELAY (12.10.2026, User-Vorgabe): Owner-Nachricht (Text +
    optionale Datei als base64) 1:1 an einen Agenten weiterleiten und die
    ANTWORT automatisch per Telegram zurueckschicken."""
    import main as app_main

    ziel = (ziel_agent or "").strip() or "executive_decision_architect"
    profiles = app_main.api_get_hermes_profiles()
    prof = next((p for p in profiles if p.get("id") == ziel), None)
    if not prof:
        raise HTTPException(
            status_code=400,
            detail=f"Ziel-Agent '{ziel}' existiert nicht im Kader.",
        )
    agent_name = prof.get("person_name") or prof.get("name") or ziel
    msg = (text or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="text darf nicht leer sein")

    anhang_hinweis = ""
    if datei_b64:
        try:
            import base64 as _b64

            safe_name = re.sub(
                r"[^a-zA-Z0-9._-]+", "_", (datei_name or "anhang.bin")
            )[-80:]
            rel_dir = os.path.join("static", "uploads", "telegram")
            os.makedirs(rel_dir, exist_ok=True)
            rel_path = os.path.join(
                rel_dir,
                f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}",
            )
            with open(rel_path, "wb") as f_bin:
                f_bin.write(_b64.b64decode(datei_b64))
            groesse = os.path.getsize(rel_path)
            anhang_hinweis = (
                f"\n\n📎 ANHANG des Owners ({safe_name}, {groesse} B): {rel_path}\n"
                f"Arbeite MIT dieser Datei (z.B. video_analyze/vision oder lesen)."
            )
            logger.info(f"[Relay] Anhang gespeichert: {rel_path} ({groesse} B)")
        except Exception as anh_err:
            logger.warning(
                f"[Relay] Anhang konnte nicht gespeichert werden: {anh_err}"
            )
            anhang_hinweis = f"\n\n(Anhang '{datei_name}' konnte nicht gespeichert werden: {anh_err})"

    relay_prompt = (
        f"LEITUNG VOM OWNER PER TELEGRAM (1:1, unveraendert):\n\n"
        f"{msg}{anhang_hinweis}\n\n"
        f"Antworte mit dem Ergebnis der Aufgabe (Deutsch, ohne Begruessung)."
    )

    system_prompt = (
        prof.get("system_prompt")
        or prof.get("prompt")
        or f"Du bist {agent_name}. Antworte praezise auf Deutsch."
    )
    model = (
        prof.get("model")
        if prof.get("model") not in ("", "free-forever")
        else ""
    ) or "deepseek/deepseek-v4-flash-0731"

    def _tg_send_relay(text_out):
        from telegram_notify import send_telegram_message

        return send_telegram_message(f"🤖 {agent_name}:\n\n{text_out[:3900]}")

    app_main.add_ticker(
        "Telegram-Relay",
        f"Nachricht an {agent_name} weitergeleitet ({len(msg)} Z)",
    )
    res = None
    try:
        res = await app_main.core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=ziel,
            agent_name=agent_name,
            prompt=relay_prompt,
            role=prof.get("category", "Relay-Ziel"),
            system_prompt=system_prompt,
            model=model,
        )
        antwort = (res.get("content") or "").strip()
    except Exception as rel_err:
        logger.error(f"[Relay] Dispatch an {ziel} fehlgeschlagen: {rel_err}")
        antwort = ""
        dispatch_error = str(rel_err)
    else:
        dispatch_error = None

    if not antwort:
        grund = dispatch_error or (
            res.get("error", "unbekannt")
            if isinstance(res, dict)
            else "dispatch-fehler"
        )
        antwort = (
            f"Der Relay an {agent_name} lieferte keine Antwort "
            f"(Grund: {grund})."
        )
    try:
        await asyncio.to_thread(_tg_send_relay, antwort)
    except Exception as tg3:
        logger.warning(f"[Relay] Telegram-Rueckantwort fehlgeschlagen: {tg3}")
    logger.info(
        f"[Relay] {ziel}: {len(msg)} Z rein, {len(antwort)} Z zurueck an Telegram"
    )
    return {"status": "ok", "ziel_agent": ziel, "antwort_kopf": antwort[:400]}


@router.post("/voice-relay")
async def api_telegram_voice_relay(
    request: Request,
    file: UploadFile = File(None),
    file_id: str = Form(""),
    chat_id: str = Form(""),
    ziel_agent: str = Form(""),
    reply_voice: bool = Form(True),
):
    """Empfaengt Sprachnachrichten aus Telegram (als Upload oder per Telegram file_id),
    transkribiert sie, routet sie an den Ziel-Agenten und sendet Text + Sprachantwort zurueck.
    """
    require_admin_or_503(request)
    clean_chat_id = (chat_id or "").strip()
    if clean_chat_id and not _TELEGRAM_CHAT_ID_RE.match(clean_chat_id):
        raise HTTPException(
            status_code=400,
            detail="chat_id ungueltig: erwartet numerische Telegram-ID "
            "(z. B. '123456789' oder '-1001234567890').",
        )

    from backend.voice_pipeline import (
        detect_target_agent,
        download_telegram_file,
        send_telegram_voice,
        synthesize_speech,
        transcribe_audio_bytes,
    )

    audio_bytes = b""
    fname = "voice.ogg"

    if file:
        audio_bytes = await file.read()
        fname = file.filename or "voice.ogg"
    elif file_id:
        try:
            audio_bytes, fname = await download_telegram_file(file_id)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Download von Telegram fehlgeschlagen: {_redact_telegram_secrets(e)}",
            )

    if not audio_bytes:
        raise HTTPException(
            status_code=400, detail="Keine Audio-Daten uebergeben."
        )

    # 1. Transkribieren
    transcript = await transcribe_audio_bytes(audio_bytes, filename=fname)

    # 2. Agenten-Routing
    detected_agent, clean_prompt = detect_target_agent(transcript)
    target = (ziel_agent or "").strip() or detected_agent

    # 3. An bestehenden Relay weiterleiten
    import main as app_main
    relay_res = await app_main.api_telegram_relay(ziel_agent=target, text=clean_prompt)
    answer_text = relay_res.get("antwort_kopf", "")

    # 4. Sprachantwort erzeugen & an Telegram senden
    voice_sent = False
    tgt_chat = clean_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if (
        reply_voice
        and tgt_chat
        and answer_text
        and not answer_text.startswith("[Sprachnachricht")
    ):
        try:
            speech_path = await synthesize_speech(answer_text)
            voice_sent = await send_telegram_voice(
                tgt_chat, speech_path, caption=f"Antwort von {target}"
            )
            if os.path.exists(speech_path):
                os.remove(speech_path)
        except Exception as v_err:
            logger.warning(
                f"[VoiceRelay] Sprachantwort-Versand fehlgeschlagen: "
                f"{_redact_telegram_secrets(v_err)}"
            )

    return {
        "status": "ok",
        "transcript": transcript,
        "ziel_agent": target,
        "clean_prompt": clean_prompt,
        "antwort": answer_text,
        "voice_sent": voice_sent,
    }


@router.post("/send")
async def api_telegram_send(payload: TelegramSendPayload):
    """Versendet eine Benachrichtigung, ein Briefing oder System-Statusnachricht
    direkt an Telegram (z. B. aufgerufen durch n8n Automatisierungs-Routinen)."""
    import telegram_notify

    if not payload.text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    if not telegram_notify.telegram_enabled():
        return {
            "status": "disabled",
            "result": False,
            "detail": "Telegram-Versand ist aus (settings.json -> telegram.enabled = false).",
        }
    try:
        res = telegram_notify.send_telegram_message(payload.text)
        return {"status": "success" if res else "failed", "result": res}
    except Exception as e:
        logger.warning(f"[TelegramSend] Fehler: {e}")
        return {"status": "error", "message": str(e)}
