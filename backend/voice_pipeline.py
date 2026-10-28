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


async def transcribe_audio_bytes(data: bytes, filename: str = "audio.ogg", language: str = "de") -> str:
    """
    Transkribiert rohe Audio-Bytes.
    """
    # 1. Groq Whisper (extrem schnell & präzise)
    if GROQ_API_KEY:
        try:
            import httpx
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            files = {"file": (filename, data, "audio/ogg")}
            data_fields = {"model": "whisper-large-v3", "language": language}
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                         headers=headers, files=files, data=data_fields)
                if resp.status_code == 200:
                    result = resp.json()
                    txt = result.get("text", "").strip()
                    if txt:
                        logger.info(f"[Voice] Transkription via Groq Whisper erfolgreich: {len(txt)} Zeichen")
                        return txt
        except Exception as e:
            logger.warning(f"[Voice] Groq Whisper fehlgeschlagen: {e}")

    # 2. OpenAI Whisper
    if OPENAI_API_KEY:
        try:
            import httpx
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            files = {"file": (filename, data, "audio/ogg")}
            data_fields = {"model": "whisper-1", "language": language}
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post("https://api.openai.com/v1/audio/transcriptions",
                                         headers=headers, files=files, data=data_fields)
                if resp.status_code == 200:
                    result = resp.json()
                    txt = result.get("text", "").strip()
                    if txt:
                        logger.info(f"[Voice] Transkription via OpenAI Whisper erfolgreich: {len(txt)} Zeichen")
                        return txt
        except Exception as e:
            logger.warning(f"[Voice] OpenAI Whisper fehlgeschlagen: {e}")

    # 3. Google Gemini Audio-Inferenz (wenn GOOGLE_API_KEY vorhanden)
    if GOOGLE_API_KEY:
        try:
            import httpx
            b64_audio = base64.b64encode(data).decode("utf-8")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": "Transkribiere diese deutsche Audiospur präzise und wortgetreu. Gib ausschließlich den transkribierten Text ohne Erklärung aus."},
                        {"inline_data": {"mime_type": "audio/ogg", "data": b64_audio}}
                    ]
                }]
            }
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    res_json = resp.json()
                    txt = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    logger.info(f"[Voice] Transkription via Gemini Flash erfolgreich: {len(txt)} Zeichen")
                    return txt
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

    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, voice=voice)
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
