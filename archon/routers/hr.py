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


class SetSoulModeReq(BaseModel):
    mode: str = "compact"
    agent_id: Optional[str] = None


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


@router.get("/api/v1/hermes/soul-mode")
def api_get_soul_mode():
    """Liefert den aktuell aktiven SOUL-Modus ('full' vs 'compact')."""
    from scripts.sync_soul_modes import get_current_soul_mode_status
    return get_current_soul_mode_status()


@router.post("/api/v1/hermes/soul-mode")
def api_set_soul_mode(req: SetSoulModeReq):
    """Schaltet global oder pro Agent zwischen 'full' (Original/Voll-Experte) und 'compact' (Token-Spar) um."""
    from scripts.sync_soul_modes import apply_soul_mode
    from archon.core.profiles import invalidate_hermes_profiles_cache

    res = apply_soul_mode(mode=req.mode, target_agent_id=req.agent_id)
    invalidate_hermes_profiles_cache()
    if req.agent_id:
        soul_data = api_get_hermes_soul(req.agent_id)
        res["agent_markdown"] = soul_data.get("markdown", "")
        res["agent_id"] = req.agent_id
    return res


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
            "mode": "compact",
            "chars": 0,
        }

    try:
        with open(found_path, "r", encoding="utf-8") as f:
            content = f.read()
        pdir = os.path.dirname(found_path)
        full_len = len(content)
        pro_len = len(content)
        compact_len = len(content)
        if os.path.exists(os.path.join(pdir, "SOUL_FULL.md")):
            with open(os.path.join(pdir, "SOUL_FULL.md"), "r", encoding="utf-8", errors="ignore") as ff:
                full_len = len(ff.read())
        if os.path.exists(os.path.join(pdir, "SOUL_PRO.md")):
            with open(os.path.join(pdir, "SOUL_PRO.md"), "r", encoding="utf-8", errors="ignore") as fp:
                pro_len = len(fp.read())
        if os.path.exists(os.path.join(pdir, "SOUL_COMPACT.md")):
            with open(os.path.join(pdir, "SOUL_COMPACT.md"), "r", encoding="utf-8", errors="ignore") as fc:
                compact_len = len(fc.read())
        if len(content) > 10500 or "SOUL-DIREKTIVE (FULL-EXPERT)" in content:
            detected_mode = "full"
        elif len(content) > 4500 or "SOUL-DIREKTIVE (PRO-MODUS)" in content:
            detected_mode = "pro"
        else:
            detected_mode = "compact"
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": content,
            "file_path": found_path,
            "mode": detected_mode,
            "chars": len(content),
            "full_chars": full_len,
            "pro_chars": pro_len,
            "compact_chars": compact_len,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/hermes/soul/{agent_id}")
def api_save_hermes_soul(request: Request, agent_id: str, req: SaveSoulReq):
    """Speichert die SOUL.md Datei fuer ein Hermes-Profil und synchronisiert Cache + agent_profiles.json."""
    _require_admin(request)
    import main as app_main
    from archon.core.profiles import (
        invalidate_hermes_profiles_cache,
        load_all_agent_profiles,
        save_all_agent_profiles,
    )

    target_dir = app_main.profile_dir(agent_id)
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "SOUL.md")

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(req.markdown)
        for mirror_root in ("/opt/data/profiles", "/home/micha/.hermes/profiles", "/mnt/raid/AgenticOS-2026/data/hermes_profiles"):
            if os.path.exists(mirror_root):
                m_dir = os.path.join(mirror_root, agent_id)
                os.makedirs(m_dir, exist_ok=True)
                m_path = os.path.join(m_dir, "SOUL.md")
                if os.path.realpath(m_path) != os.path.realpath(target_path):
                    try:
                        with open(m_path, "w", encoding="utf-8") as fm:
                            fm.write(req.markdown)
                    except Exception:
                        pass

        # Synchronisiere prompt/system_prompt in agent_profiles.json und leere den 30s-Cache
        try:
            profiles = load_all_agent_profiles()
            changed = False
            for p in profiles:
                if isinstance(p, dict) and p.get("id") == agent_id:
                    p["prompt"] = req.markdown
                    p["system_prompt"] = req.markdown
                    changed = True
            if changed:
                save_all_agent_profiles(profiles)
        except Exception:
            pass
        invalidate_hermes_profiles_cache()

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
