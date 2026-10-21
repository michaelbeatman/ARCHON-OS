"""
apollo_voice_engine.py - Voice Agent & Conversational Audio Bridge für Archon OS
Bietet Sprachsynthese (TTS mit natürlichen Neural-Voices), Transkription und
Befehlsausführung für Desktop- und Browsersteuerung im Stil von Hermes Apollo.
"""

import os
import sys
import io
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
AUDIO_CACHE_DIR = BASE_DIR / "data" / "audio_cache"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VOICE_DE = "de-DE-KillianNeural"
DEFAULT_VOICE_EN = "en-US-AndrewNeural"

class ApolloVoiceEngine:
    def __init__(self, voice: str = DEFAULT_VOICE_DE):
        self.voice = voice

    async def synthesize_speech(self, text: str, voice: Optional[str] = None) -> bytes:
        """Wandelt Text asynchron in MP3-Audiodaten um."""
        import edge_tts
        target_voice = voice or self.voice
        clean_text = text.strip()
        if not clean_text:
            clean_text = "Kein Text angegeben."

        communicate = edge_tts.Communicate(clean_text, target_voice)
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])
        return audio_stream.getvalue()

    async def process_voice_command(self, transcript: str) -> Dict[str, Any]:
        """
        Nimmt transkribierten Text entgegen, ermittelt die Handlungsabsicht
        und liefert ein strukturiertes Ergebnis plus gesprochene Rückmeldung.
        """
        clean_prompt = transcript.strip()
        if not clean_prompt:
            return {
                "status": "error",
                "message": "Leere Spracheingabe erhalten.",
                "spoken_reply": "Ich habe keine Eingabe gehört."
            }

        # 1. Schnelle Intent-Erkennung
        lower = clean_prompt.lower()
        action = "chat_or_execute"
        spoken_reply = "Befehl wird verarbeitet."

        if any(w in lower for w in ["status", "container", "docker", "server"]):
            action = "inspect_system"
            spoken_reply = "Prüfe System- und Container-Status."
        elif any(w in lower for w in ["radar", "news", "trend", "oracle"]):
            action = "run_oracle"
            spoken_reply = "Starte Oracle News Radar."
        elif any(w in lower for w in ["e-mail", "email", "sync", "mail"]):
            action = "sync_emails"
            spoken_reply = "Synchronisiere E-Mails."
        elif any(w in lower for w in ["task", "aufgabe", "erstelle task"]):
            action = "create_task"
            spoken_reply = "Aufgabe wird im Kanban Board angelegt."

        # 2. Reale Ausführung bei bekannten System-Commands
        result_details = {}
        if action == "run_oracle":
            try:
                import oracle_news_radar
                radar = oracle_news_radar.OracleNewsRadar()
                cycle_res = radar.run_radar_cycle()
                spoken_reply = f"Oracle News Radar abgeschlossen. {cycle_res.get('new_signals_count', 0)} neue Signale erfasst."
                result_details = cycle_res
            except Exception as e:
                spoken_reply = f"Fehler beim Ausführen des Radars: {str(e)[:50]}"
        elif action == "inspect_system":
            try:
                from core_skills_engine import DockerControlSkill
                skill = DockerControlSkill()
                info = skill.inspect_system()
                c_count = len(info.get("containers", [])) if info.get("status") == "success" else 0
                spoken_reply = f"Systemprüfung abgeschlossen. {c_count} Container aktiv."
                result_details = info
            except Exception as e:
                spoken_reply = "Docker-Prüfung konnte nicht ausgeführt werden."

        # 3. Audio-Antwort generieren
        audio_bytes = await self.synthesize_speech(spoken_reply)
        cache_filename = f"reply_{int(time.time())}.mp3"
        cache_path = AUDIO_CACHE_DIR / cache_filename
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)

        return {
            "status": "success",
            "transcript": clean_prompt,
            "action": action,
            "spoken_reply": spoken_reply,
            "audio_url": f"/api/voice/audio/{cache_filename}",
            "details": result_details
        }

if __name__ == "__main__":
    engine = ApolloVoiceEngine()
    res = asyncio.run(engine.process_voice_command("Wie ist der Status der Container?"))
    print("Voice Engine Result:", res)
