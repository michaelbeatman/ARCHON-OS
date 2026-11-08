"""Router fuer Quickchat-Sessions (Archon OS)."""
from __future__ import annotations

import datetime
import logging
import os
import re
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("archon.routers.quickchat")

router = APIRouter(tags=["quickchat"])


def _quickchat_session_path(profile_id: str) -> str:
    import main as app_main

    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", profile_id)
    return os.path.join(app_main.QUICKCHAT_SESSIONS_DIR, f"{safe_id}.json")


def _load_quickchat_session(profile_id: str) -> Dict:
    import main as app_main

    path = _quickchat_session_path(profile_id)
    if os.path.exists(path):
        data = app_main._load_json(path, {})
        if isinstance(data, dict):
            return data
    return {
        "profile_id": profile_id,
        "messages": [],
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
    }


def _save_quickchat_session(session: Dict):
    import main as app_main

    session["updated_at"] = datetime.datetime.now().isoformat()
    app_main._save_json(_quickchat_session_path(session["profile_id"]), session)


def _load_db_messages(sid: str) -> List[Dict]:
    """Hilfsfunktion fuer Datenbankzugriff ausserhalb des AST-Routers."""
    import main as app_main

    msgs = []
    try:
        with app_main._get_state_db() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id = ? AND active = 1 "
                "ORDER BY timestamp ASC LIMIT 200",
                (sid,),
            ).fetchall()
        for role, content, ts in rows:
            msgs.append(
                {
                    "role": "user" if role == "user" else "agent",
                    "text": content,
                    "ts": datetime.datetime.fromtimestamp(float(ts or 0)).isoformat() if ts else None,
                }
            )
    except Exception as e:
        logger.warning(f"[QuickChat] Verlauf laden fehlgeschlagen: {e}")
    return msgs


@router.get("/api/v1/quickchat/session/{profile_id}")
def api_get_quickchat_session(profile_id: str):
    """Verlauf aus state.db (identisch mit Master-/Agentenchat)."""
    import main as app_main

    sid = app_main._quickchat_state_session_id(profile_id)
    msgs = _load_db_messages(sid)
    return {"profile_id": profile_id, "session_id": sid, "messages": msgs}


class QuickchatSendRequest(BaseModel):
    profile_id: str
    message: str
    attachment_content: Optional[str] = None
    attachment_name: Optional[str] = None


@router.post("/api/v1/quickchat/send")
async def api_quickchat_send(req: QuickchatSendRequest):
    import main as app_main

    state_sid = app_main._quickchat_state_session_id(req.profile_id)
    app_main._ensure_state_session(
        state_sid, source="quickchat", profile_name=req.profile_id, title=req.message
    )
    session = _load_quickchat_session(req.profile_id)

    # Update last_used for idle-stop tracking
    cfg = app_main._load_gateway_config()
    cfg["last_used"][req.profile_id] = datetime.datetime.now().isoformat()
    app_main._save_gateway_config(cfg)

    # Load profile for system prompt
    profiles = app_main.load_profiles_list()
    prof = next((p for p in profiles if p.get("id") == req.profile_id), None)
    if not prof:
        prof = {
            "id": req.profile_id,
            "name": req.profile_id,
            "model": "gpt-4o-mini",
            "provider": "openrouter",
        }

    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or req.profile_id
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Antworte präzise, kompetent und direkt. Halte den Kontext der bisherigen Konversation."
    )
    model = prof.get("model") or "gpt-4o-mini"
    provider = prof.get("provider") or "openrouter"

    user_msg = req.message
    if req.attachment_content:
        user_msg = (
            f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n"
            f"```\n{req.attachment_content[:6000]}\n```\n\n{req.message}"
        )

    start_t = time.time()
    try:
        res = await app_main.core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=agent_name,
            prompt=user_msg,
            role=role_title,
            system_prompt=system_prompt,
            model=model,
            provider=provider,
        )
        reply_text = res.get("content", "Keine Antwort erhalten.")
    except Exception as e:
        reply_text = f"⚠ Fehler: {str(e)}"

    duration = round(time.time() - start_t, 2)

    try:
        app_main._save_message_to_db(state_sid, "user", req.message)
        if reply_text:
            app_main._save_message_to_db(state_sid, "assistant", str(reply_text))
    except Exception as _pc_err:
        logger.warning(f"[QuickChat] Speichern im gemeinsamen Verlauf fehlgeschlagen: {_pc_err}")

    session["messages"].append(
        {"role": "user", "text": req.message, "ts": datetime.datetime.now().isoformat()}
    )
    session["messages"].append(
        {"role": "agent", "text": str(reply_text), "ts": datetime.datetime.now().isoformat()}
    )
    if len(session["messages"]) > 200:
        session["messages"] = session["messages"][-200:]
    _save_quickchat_session(session)

    app_main.add_ticker("Quickchat", f"{agent_name}: {req.message[:40]}… ({duration}s)")

    return {
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
    }


@router.delete("/api/v1/quickchat/session/{profile_id}")
def api_delete_quickchat_session(profile_id: str):
    path = _quickchat_session_path(profile_id)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True, "profile_id": profile_id}
