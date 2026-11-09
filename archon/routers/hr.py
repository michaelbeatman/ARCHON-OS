"""Router fuer HR-Personalakten und Hermes-SOUL-Direktiven."""
from __future__ import annotations

import datetime
import logging
import os
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("archon.routers.hr")

router = APIRouter(tags=["hr"])


def _require_admin(request: Request):
    import main as app_main
    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


class SavePersonalakteReq(BaseModel):
    markdown: str


class SaveSoulReq(BaseModel):
    markdown: str


class LogActivityReq(BaseModel):
    task_title: str
    task_id: Optional[str] = "heartbeat"
    status: Optional[str] = "Erledigt"
    summary: str
    artifacts: Optional[str] = "Keine Artefakte"


@router.get("/api/v1/hr/personalakte/{agent_id}")
def api_get_personalakte(agent_id: str):
    import main as app_main

    vault_dir = app_main.OBSIDIAN_VAULT_DIR
    candidates = [
        os.path.join(vault_dir, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
        os.path.join(app_main.PERSONALAKTEN_DIR, f"{agent_id}.md"),
        os.path.join(app_main.OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
    ]
    file_path = None
    for c in candidates:
        if os.path.exists(c) and os.path.isfile(c):
            file_path = c
            break

    if not file_path:
        return {
            "status": "not_found",
            "agent_id": agent_id,
            "markdown": f"# Personalakte für {agent_id}\n\nNoch keine Akte vorhanden.",
            "file_path": candidates[0],
        }

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_md = f.read()
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": raw_md,
            "file_path": file_path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/hr/personalakte/{agent_id}")
def api_save_personalakte(agent_id: str, req: SavePersonalakteReq):
    import main as app_main

    vault_dir = app_main.OBSIDIAN_VAULT_DIR
    target_dirs = [
        os.path.join(vault_dir, "00_HR_Agenten", "Personalakten"),
        app_main.PERSONALAKTEN_DIR,
    ]
    if sys.platform == "win32" or os.path.exists(app_main.OBSIDIAN_VAULT):
        target_dirs.append(app_main.PERSONALAKTEN_DIR)

    saved_paths = []
    for p_dir in target_dirs:
        try:
            if os.path.exists(os.path.dirname(p_dir)):
                os.makedirs(p_dir, exist_ok=True)
                fp = os.path.join(p_dir, f"{agent_id}.md")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(req.markdown)
                saved_paths.append(fp)
        except Exception:
            pass

    return {"status": "success", "agent_id": agent_id, "file_paths": saved_paths}


@router.get("/api/v1/hermes/soul/{agent_id}")
def api_get_hermes_soul(agent_id: str):
    """Liest die echte SOUL.md Direktive des Hermes-Profils aus."""
    import main as app_main

    candidates = [
        app_main.soul_path(agent_id),
        f"/root/.hermes/profiles/{agent_id}/SOUL.md",
        f"/home/streamlituser/.hermes/profiles/{agent_id}/SOUL.md",
    ]
    found_path = None
    for p in candidates:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        return {
            "status": "not_found",
            "agent_id": agent_id,
            "markdown": "",
            "file_path": candidates[0],
        }

    try:
        with open(found_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": content,
            "file_path": found_path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/hermes/soul/{agent_id}")
def api_save_hermes_soul(request: Request, agent_id: str, req: SaveSoulReq):
    """Speichert die SOUL.md Datei fuer ein Hermes-Profil."""
    _require_admin(request)
    import main as app_main

    target_dir = app_main.profile_dir(agent_id)
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "SOUL.md")

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(req.markdown)
        host_dir = app_main.profile_dir(agent_id)
        if os.path.exists(os.path.dirname(host_dir)):
            try:
                os.makedirs(host_dir, exist_ok=True)
                with open(os.path.join(host_dir, "SOUL.md"), "w", encoding="utf-8") as f2:
                    f2.write(req.markdown)
            except Exception:
                pass
        return {"status": "success", "agent_id": agent_id, "file_path": target_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/hr/personalakte/{agent_id}/log_activity")
def api_log_personalakte_activity(agent_id: str, req: LogActivityReq):
    import main as app_main

    vault_dir = app_main.OBSIDIAN_VAULT_DIR
    personalakten_dir = os.path.join(vault_dir, "00_HR_Agenten", "Personalakten")
    os.makedirs(personalakten_dir, exist_ok=True)
    file_path = os.path.join(personalakten_dir, f"{agent_id}.md")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n\n### [{now_str}] Heartbeat / Task: {req.task_title} (ID: `{req.task_id}`)\n- **Status:** `{req.status}`\n- **Zusammenfassung:** {req.summary}\n- **Erzeugte Artefakte & Notizen:** {req.artifacts}\n"

    content = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = f"# Personalakte für {agent_id}\n\n"
    else:
        content = f"# Personalakte für {agent_id}\n\n"

    content += entry

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        if os.path.exists(app_main.OBSIDIAN_VAULT):
            c_dir = os.path.join(app_main.OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten")
            os.makedirs(c_dir, exist_ok=True)
            with open(os.path.join(c_dir, f"{agent_id}.md"), "w", encoding="utf-8") as f2:
                f2.write(content)

        return {"status": "success", "agent_id": agent_id, "logged_at": now_str, "file_path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
