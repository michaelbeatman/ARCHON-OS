# -*- coding: utf-8 -*-
"""
backend/voice_pipeline.py — Archon OS Voice & Audio Pipeline

Ermöglicht Sprachverarbeitung für mobile Nutzung via Telegram und Dashboard:
1. Audio-Transkription (Voice-to-Text via Groq, OpenAI, Gemini oder OmniRoute)
2. Sprachausgabe (Text-to-Speech via edge-tts mit de-DE-ConradNeural)
3. Telegram Voice Relay: Eingehende Sprachmemos (.ogg/Opus) empfangen, transkribieren,
   an den Ziel-Agenten übergeben und optional als Sprachnachricht zurücksenden.
"""

import os
import sys
import json
import base64
import logging
import asyncio
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("archon_os.voice")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "").strip()

DEFAULT_VOICE = "de-DE-ConradNeural"


async def transcribe_audio_file(file_path: str, language: str = "de") -> str:
    """
    Transkribiert eine Audiodatei (.ogg, .mp3, .wav, .m4a) zu Text.
    Nutzt prioritär Groq Whisper, OpenAI Whisper oder Google Gemini API.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Audiodatei nicht gefunden: {file_path}")

    audio_bytes = p.read_bytes()
    return await transcribe_audio_bytes(audio_bytes, filename=p.name, language=language)


def _gate_cloud_voice_dispatch(url: str, *, provider: str, model: str,
                               metadata: dict, data_category: str = "general") -> dict:
    """F-022: ein gemeinsames Egress+DLP-Gate fuer ALLE Cloud-Audio-Zweige.

    Vorher hatte nur der Groq-Zweig die URL-Firewall; OpenAI, Gemini und TTS
    schickten Audio/PII ohne Pre-Flight-Gate und ohne Maskierung nach draussen.
    """
    from backend.llm_egress_guard import (
        ZeroEgressBlockedError,
        enforce_egress_firewall_for_url,
        evaluate_and_gate_llm_dispatch,
        sanitize_outbound_llm_payload,
    )
    enforce_egress_firewall_for_url(url, agent_id="voice_pipeline")
    gate = evaluate_and_gate_llm_dispatch(
        agent_id="voice_pipeline",
        provider=provider,
        model=model,
        messages=[{"role": "user", "content": "audio transcription metadata"}],
        explicit_category=data_category,
        intended_url=url,
    )
    if not gate.get("allowed", True):
        raise ZeroEgressBlockedError(
            "Voice-Dispatch durch Egress-Gate blockiert.",
            error_code=gate.get("error_code") or "VOICE_EGRESS_BLOCKED",
        )
    return sanitize_outbound_llm_payload(
        metadata, agent_id="voice_pipeline", is_local=bool(gate.get("routed_to_local"))
    ) or {}


async def transcribe_audio_bytes(data: bytes, filename: str = "audio.ogg", language: str = "de") -> str:
    """
    Transkribiert rohe Audio-Bytes (Zero-Egress-geschuetzt).
    """
    # P0-4: is_zero_egress_active existiert nicht in llm_egress_guard →
    # ImportError; der TypeError mit data_category= liess den Guard nie laufen.
    from backend.llm_egress_guard import ZeroEgressBlockedError, enforce_egress_firewall_for_url
    from backend.privacy_router import get_privacy_config

    if bool(get_privacy_config().get("zero_egress_strict")):
        logger.warning("[Voice] Zero-Egress aktiv — Cloud-Transkription (Groq/OpenAI/Gemini) blockiert.")
        return "[Zero-Egress aktiv: Cloud-Audio-Transkription blockiert]"

    # 1. Groq Whisper (extrem schnell & präzise)
    if GROQ_API_KEY:
        try:
            import httpx
            groq_url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            files = {"file": (filename, data, "audio/ogg")}
            data_fields = _gate_cloud_voice_dispatch(
                groq_url, provider="groq", model="whisper-large-v3",
                metadata={"model": "whisper-large-v3", "language": language},
            )
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(groq_url, headers=headers, files=files, data=data_fields)
                if resp.status_code == 200:
                    result = resp.json()
                    txt = result.get("text", "").strip()
                    if txt:
                        logger.info(f"[Voice] Transkription via Groq Whisper erfolgreich: {len(txt)} Zeichen")
                        return txt
        except ZeroEgressBlockedError:
            # D04/MED: der Block-Proof wurde bereits im Gate signiert
            # (chained_audit_log.record_llm_dispatch). Ein blockierter Dispatch
            # darf NIEMALS zum nächsten Cloud-Provider fallen.
            logger.error("[Voice] Groq-Dispatch durch Egress-Gate blockiert — kein Fallback.")
            raise
        except Exception as e:
            logger.warning(f"[Voice] Groq Whisper fehlgeschlagen: {e}")

    # 2. OpenAI Whisper
    if OPENAI_API_KEY:
        try:
            import httpx
            openai_url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            files = {"file": (filename, data, "audio/ogg")}
            data_fields = _gate_cloud_voice_dispatch(
                openai_url, provider="openai", model="whisper-1",
                metadata={"model": "whisper-1", "language": language},
            )
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(openai_url, headers=headers, files=files, data=data_fields)
                if resp.status_code == 200:
                    result = resp.json()
                    txt = result.get("text", "").strip()
                    if txt:
                        logger.info(f"[Voice] Transkription via OpenAI Whisper erfolgreich: {len(txt)} Zeichen")
                        return txt
        except ZeroEgressBlockedError:
            logger.error("[Voice] OpenAI-Dispatch durch Egress-Gate blockiert — kein Fallback.")
            raise
        except Exception as e:
            logger.warning(f"[Voice] OpenAI Whisper fehlgeschlagen: {e}")

    # 3. Google Gemini Audio-Inferenz — nur wenn ausdrücklich freigeschaltet.
    # Standard aus, weil jeder Aufruf das Google-Kontingent des Eigentümers belastet.
    def _google_voice_allowed() -> bool:
        return os.environ.get("ARCHON_GOOGLE_VOICE_ENABLED", "").strip().lower() in ("1", "true", "yes")

    if GOOGLE_API_KEY and _google_voice_allowed():
        try:
            import httpx
            b64_audio = base64.b64encode(data).decode("utf-8")
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": "Transkribiere diese deutsche Audiospur präzise und wortgetreu. Gib ausschließlich den transkribierten Text ohne Erklärung aus."},
                        {"inline_data": {"mime_type": "audio/ogg", "data": b64_audio}}
                    ]
                }]
            }
            # F-022: API-Key in den Header (nicht in die URL, damit er nicht
            # signiert/geloggt wird) und gemeinsames Egress+DLP-Gate.
            headers = {"x-goog-api-key": GOOGLE_API_KEY}
            _gate_cloud_voice_dispatch(
                url, provider="gemini", model="gemini-1.5-flash",
                metadata={"prompt": "audio transcription", "mime_type": "audio/ogg"},
            )
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    res_json = resp.json()
                    txt = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    logger.info(f"[Voice] Transkription via Gemini Flash erfolgreich: {len(txt)} Zeichen")
                    return txt
        except ZeroEgressBlockedError:
            logger.error("[Voice] Gemini-Dispatch durch Egress-Gate blockiert — kein Fallback.")
            raise
        except Exception as e:
            logger.warning(f"[Voice] Gemini Transkription fehlgeschlagen: {e}")

    # 4. Fallback-Meldung, wenn kein Transkriptionsdienst konfiguriert ist
    logger.info("[Voice] Kein API-Schlüssel für Whisper/Gemini hinterlegt.")
    return "[Sprachnachricht empfangen, aber kein Whisper- oder Gemini-API-Key konfiguriert]"


async def synthesize_speech(text: str, output_path: Optional[str] = None, voice: str = DEFAULT_VOICE) -> str:
    """
    Erzeugt aus Text eine natürliche deutsche Sprachausgabe (.mp3) via edge-tts.
    """
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Kein Text für Sprachsynthese übergeben.")

    # Bereinige Markdown-Tags für sauberes Vorlesen
    import re
    clean_text = re.sub(r"```.*?```", "[Codeblock übersprungen]", clean_text, flags=re.DOTALL)
    clean_text = re.sub(r"[`*#_~]", "", clean_text)
    clean_text = clean_text[:2000] # Maximale Leselänge für Sprachnotizen

    if not output_path:
        fd, output_path = tempfile.mkstemp(prefix="archon_voice_", suffix=".mp3")
        os.close(fd)

    # D04/MED: auch die Sprachsynthese ist ein externer Dispatch und läuft
    # deshalb über dasselbe Egress+DLP-Gate wie die Transkription. Vorher
    # wurde nur ein Boolean geprüft und Freitext unmaskiert an edge-tts
    # geschickt. Ist der Endpunkt nicht allowlistet, blockiert das Gate
    # fail-closed (kein stiller Cloud-Dispatch).
    tts_endpoint = os.environ.get(
        "ARCHON_VOICE_TTS_ENDPOINT",
        "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1",
    )
    safe = _gate_cloud_voice_dispatch(
        tts_endpoint, provider="edge-tts", model=voice,
        metadata={"prompt": clean_text}, data_category="voice_tts",
    )
    safe_text = str(safe.get("prompt") or "") if isinstance(safe, dict) else ""
    if not safe_text:
        raise RuntimeError("TTS-Payload wurde vom DLP-Gate verworfen — kein Dispatch.")

    try:
        import edge_tts
        communicate = edge_tts.Communicate(safe_text, voice=voice)
        await communicate.save(output_path)
        logger.info(f"[Voice] Sprachsynthese erfolgreich gespeichert: {output_path} ({os.path.getsize(output_path)} Bytes)")
        return output_path
    except Exception as e:
        logger.error(f"[Voice] Fehler bei edge-tts Sprachsynthese: {e}")
        raise


async def download_telegram_file(file_id: str, bot_token: Optional[str] = None) -> Tuple[bytes, str]:
    """
    Lädt eine Datei (z. B. Sprachnachricht) über die Telegram Bot API herunter.
    Gibt (file_bytes, filename) zurück.
    """
    token = bot_token or TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("Kein TELEGRAM_BOT_TOKEN konfiguriert.")

    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. getFile
        r1 = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
        d1 = r1.json()
        if not d1.get("ok"):
            raise RuntimeError(f"Telegram getFile Fehler: {d1.get('description')}")
        file_path = d1["result"]["file_path"]

        # 2. Download
        r2 = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        return r2.content, os.path.basename(file_path)


async def send_telegram_voice(chat_id: str, audio_path: str, caption: Optional[str] = None, bot_token: Optional[str] = None) -> bool:
    """
    Sendet eine Sprachnachricht (.mp3/.ogg) an einen Telegram-Chat via sendVoice.
    """
    token = bot_token or TELEGRAM_BOT_TOKEN
    if not token or not chat_id:
        logger.warning("[Voice] Senden abgebrochen: Fehlender Bot-Token oder Chat-ID.")
        return False

    p = Path(audio_path)
    if not p.exists():
        return False

    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(audio_path, "rb") as af:
                files = {"voice": (p.name, af, "audio/mpeg")}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption[:1024]
                resp = await client.post(f"https://api.telegram.org/bot{token}/sendVoice", data=data, files=files)
                ok = resp.json().get("ok", False)
                if ok:
                    logger.info(f"[Voice] Sprachnachricht erfolgreich an Telegram {chat_id} übermittelt.")
                else:
                    logger.warning(f"[Voice] Telegram sendVoice abgewiesen: {resp.text}")
                return ok
    except Exception as ex:
        logger.error(f"[Voice] Fehler beim Senden an Telegram: {ex}")
        return False


def detect_target_agent(transcript: str) -> Tuple[str, str]:
    """
    Ermittelt aus dem Transkript den Ziel-Agenten anhand von Präfixen oder Rufnamen.
    Gibt (agent_id, bereinigter_text) zurück.
    """
    clean = transcript.strip()
    lower = clean.lower()

    agent_triggers = {
        "/robert": "robert",
        "robert": "robert",
        "/anwalt": "anwalt",
        "anwalt": "anwalt",
        "/steuerberater": "steuerberater",
        "steuerberater": "steuerberater",
        "/katharina": "katharina",
        "katharina": "katharina",
        "/hermes": "hermes-researcher",
        "recherche": "hermes-researcher"
    }

    for trigger, aid in agent_triggers.items():
        if lower.startswith(trigger):
            remainder = clean[len(trigger):].strip(" ,;:-")
            return aid, remainder or clean

    return "robert", clean
