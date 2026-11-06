"""Router /api/voice — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

router = APIRouter()


class VoiceSynthesizePayload(BaseModel):
    text: str
    voice: Optional[str] = "de-DE-ConradNeural"

@router.post("/api/voice/speak")
async def api_voice_speak(payload: Dict[str, Any] = Body(...)):
    text = payload.get("text", "")
    voice = payload.get("voice")
    if not text:
        raise HTTPException(status_code=400, detail="Text ist erforderlich")
    try:
        from apollo_voice_engine import ApolloVoiceEngine
        engine = ApolloVoiceEngine()
        audio_bytes = await engine.synthesize_speech(text, voice)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/voice/command")
async def api_voice_command(payload: Dict[str, Any] = Body(...)):
    transcript = payload.get("transcript", "")
    if not transcript:
        raise HTTPException(status_code=400, detail="Transkript ist erforderlich")
    try:
        from apollo_voice_engine import ApolloVoiceEngine
        engine = ApolloVoiceEngine()
        return await engine.process_voice_command(transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/voice/audio/{filename}")
def api_get_voice_audio(filename: str):
    audio_file = os.path.join("data", "audio_cache", filename)
    if os.path.exists(audio_file):
        return FileResponse(audio_file, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio-Datei nicht gefunden")


@router.post("/api/voice/synthesize")
async def api_voice_synthesize(payload: VoiceSynthesizePayload):
    """Generiert eine Audiodatei aus Text via edge-tts."""
    from backend.voice_pipeline import synthesize_speech
    try:
        mp3_path = await synthesize_speech(payload.text, voice=payload.voice or "de-DE-ConradNeural")
        return FileResponse(mp3_path, media_type="audio/mpeg", filename="voice_output.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
