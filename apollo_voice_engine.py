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
        elif action == "sync_emails":
            try:
                from backend.email_polling_daemon import EmailPollingDaemon
                daemon = EmailPollingDaemon()
                sync_res = await asyncio.to_thread(daemon.poll_once)
                fetched = sync_res.get("new_emails", 0) if isinstance(sync_res, dict) else 0
                spoken_reply = f"E-Mail-Abgleich abgeschlossen. {fetched} neue Nachrichten verarbeitet."
                result_details = sync_res if isinstance(sync_res, dict) else {"result": sync_res}
            except Exception as e:
                spoken_reply = f"E-Mail-Sync nicht verfügbar: {str(e)[:60]}"
        elif action == "create_task":
            try:
                from archon.core.mission_control import save_mission_control_data, load_mission_control_data
                import uuid as _uuid
                task_id = f"voice_{_uuid.uuid4().hex[:8]}"
                title = clean_prompt[:120]
                data = load_mission_control_data()
                tasks = data.setdefault("tasks", [])
                tasks.insert(0, {
                    "id": task_id,
                    "title": title,
                    "body": clean_prompt,
                    "status": "todo",
                    "assignee": "executive_decision_architect",
                    "created_via": "voice",
                })
                save_mission_control_data(data)
                spoken_reply = f"Aufgabe '{title[:50]}' wurde im Mission Control angelegt."
                result_details = {"task_id": task_id, "title": title}
            except Exception as e:
                spoken_reply = f"Aufgabe konnte nicht gespeichert werden: {str(e)[:60]}"
        else:
            try:
                import core_dispatcher
                d_res = await core_dispatcher.dispatch_to_omniroute_or_container(
                    agent_id="executive_decision_architect",
                    agent_name="Apollo Assistant",
                    prompt=clean_prompt,
                    role="Voice Assistant",
                    timeout=15,
                )
                reply_txt = str(d_res.get("content") or "").strip()
                if reply_txt and d_res.get("status") == "success":
                    spoken_reply = reply_txt[:400]
                result_details = d_res
            except Exception as e:
                result_details = {"error": str(e)}

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
