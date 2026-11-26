"""Router fuer HR-Personalakten und Hermes-SOUL-Direktiven."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import datetime
import logging
import os
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("archon.routers.hr")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["hr"])


def _require_admin(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


class SavePersonalakteReq(BaseModel):
    markdown: str


class SaveSoulReq(BaseModel):
    markdown: str


class SetSoulModeReq(BaseModel):
    mode: str = "compact"
    agent_id: Optional[str] = None
    refresh_soul_pin: bool = False
    guardrail_review_note: str = ""


class LogActivityReq(BaseModel):
    task_title: str
    task_id: Optional[str] = "heartbeat"
    status: Optional[str] = "Erledigt"
    summary: str
    artifacts: Optional[str] = "Keine Artefakte"


def _validate_agent_id(agent_id: str) -> str:
    import re as _re
    if not agent_id or ".." in agent_id or not _re.fullmatch(r"[A-Za-z0-9._\-]{1,128}", agent_id):
        raise HTTPException(status_code=400, detail="Ungueltige agent_id (Pfad-Traversal unzulaessig).")
    return agent_id


@router.get("/api/v1/hr/personalakte/{agent_id}")
def api_get_personalakte(agent_id: str):
    _validate_agent_id(agent_id)
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

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
def api_save_personalakte(request: Request, agent_id: str, req: SavePersonalakteReq):
    _require_admin(request)
    _validate_agent_id(agent_id)
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

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
        except OSError as exc:
            logger.warning(f"[HR] Spiegel-Speichern nach {fp} fehlgeschlagen: {exc}")

    return {"status": "success", "agent_id": agent_id, "file_paths": saved_paths}


@router.get("/api/v1/hermes/soul-mode")
def api_get_soul_mode():
    """Liefert den aktuell aktiven SOUL-Modus ('full' vs 'compact')."""
    from scripts.sync_soul_modes import get_current_soul_mode_status
    return get_current_soul_mode_status()


@router.post("/api/v1/hermes/soul-mode")
def api_set_soul_mode(request: Request, req: SetSoulModeReq):
    """Schaltet global oder pro Agent zwischen 'full', 'pro' und 'compact' um.

    F23 (D15): Ein Tier-Wechsel fuer HIGH_RISK-Agenten (oder global) aendert
    den SOUL-SHA-256-Hash und erfordert zwingend ``refresh_soul_pin=True`` nach
    fachlichem Guardrail-Review — sonst fail-closed HTTP 403.
    """
    _require_admin(request)
    from archon.core.profiles import invalidate_hermes_profiles_cache
    from backend.eu_ai_act_inventory import HIGH_RISK_AGENT_IDS
    from scripts.sync_soul_modes import apply_soul_mode

    is_high_risk_scope = (req.agent_id is None) or (str(req.agent_id).strip() in HIGH_RISK_AGENT_IDS)
    if is_high_risk_scope and not req.refresh_soul_pin:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "agent_not_compliant",
                "code": "SOUL_PIN_REFRESH_REQUIRED",
                "agent_id": req.agent_id or "*",
                "detail": (
                    "SOUL-Tier-Wechsel fuer HIGH_RISK-Agenten erfordert zwingend "
                    "refresh_soul_pin=True nach fachlichem Guardrail-Review."
                ),
            },
        )

    res = apply_soul_mode(
        mode=req.mode,
        target_agent_id=req.agent_id,
        refresh_pin=bool(req.refresh_soul_pin),
    )
    invalidate_hermes_profiles_cache()
    if req.agent_id:
        soul_data = api_get_hermes_soul(req.agent_id)
        res["agent_markdown"] = soul_data.get("markdown", "")
        res["agent_id"] = req.agent_id
    return res


@router.get("/api/v1/hermes/soul/{agent_id}")
def api_get_hermes_soul(agent_id: str):
    """Liest die echte SOUL.md Direktive des Hermes-Profils aus."""
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")
    from utils.path_jail import safe_identifier, PathJailError

    try:
        clean_id = safe_identifier(agent_id, "agent_id")
    except PathJailError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    candidates = [
        app_main.soul_path(clean_id),
        f"/root/.hermes/profiles/{clean_id}/SOUL.md",
        f"/home/streamlituser/.hermes/profiles/{clean_id}/SOUL.md",
    ]
    found_path = None
    for p in candidates:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        return {
            "status": "not_found",
            "agent_id": clean_id,
            "markdown": "",
            "file_path": candidates[0],
            "mode": "compact",
            "chars": 0,
        }

    try:
        with open(found_path, "r", encoding="utf-8") as f:
            content = f.read()
        pdir = os.path.dirname(found_path)
        full_content = pro_content = compact_content = None
        full_len = pro_len = compact_len = len(content)
        if os.path.exists(os.path.join(pdir, "SOUL_FULL.md")):
            with open(os.path.join(pdir, "SOUL_FULL.md"), "r", encoding="utf-8", errors="ignore") as ff:
                full_content = ff.read()
                full_len = len(full_content)
        if os.path.exists(os.path.join(pdir, "SOUL_PRO.md")):
            with open(os.path.join(pdir, "SOUL_PRO.md"), "r", encoding="utf-8", errors="ignore") as fp:
                pro_content = fp.read()
                pro_len = len(pro_content)
        if os.path.exists(os.path.join(pdir, "SOUL_COMPACT.md")):
            with open(os.path.join(pdir, "SOUL_COMPACT.md"), "r", encoding="utf-8", errors="ignore") as fc:
                compact_content = fc.read()
                compact_len = len(compact_content)

        if compact_content is not None and content == compact_content:
            detected_mode = "compact"
        elif pro_content is not None and content == pro_content:
            detected_mode = "pro"
        elif full_content is not None and content == full_content:
            detected_mode = "full"
        elif "SOUL-DIREKTIVE (FULL-EXPERT)" in content:
            detected_mode = "full"
        elif "SOUL-DIREKTIVE (PRO-MODUS)" in content:
            detected_mode = "pro"
        elif "SOUL-DIREKTIVE (KOMPAKT)" in content:
            detected_mode = "compact"
        else:
            clen = len(content)
            candidates_dist = [("compact", abs(clen - compact_len)), ("pro", abs(clen - pro_len)), ("full", abs(clen - full_len))]
            detected_mode = min(candidates_dist, key=lambda x: x[1])[0]
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
    _validate_agent_id(agent_id)
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")
    from archon.core.profiles import (
        api_get_hermes_profiles,
        invalidate_hermes_profiles_cache,
        save_all_agent_profiles,
    )

    target_dir = app_main.profile_dir(agent_id)
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "SOUL.md")

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(req.markdown)
        from archon.core.profiles import get_hermes_profiles_base_dirs
        for mirror_root in get_hermes_profiles_base_dirs():
            if os.path.exists(mirror_root):
                m_dir = os.path.join(mirror_root, agent_id)
                os.makedirs(m_dir, exist_ok=True)
                m_path = os.path.join(m_dir, "SOUL.md")
                if os.path.realpath(m_path) != os.path.realpath(target_path):
                    try:
                        with open(m_path, "w", encoding="utf-8") as fm:
                            fm.write(req.markdown)
                    except OSError as exc:
                        logger.warning(f"[HR] HR-Spiegeldatei {m_path} konnte nicht geschrieben werden: {exc}")

        # Synchronisiere prompt/system_prompt in agent_profiles.json und leere den 30s-Cache
        try:
            profiles = api_get_hermes_profiles()
            changed = False
            for p in profiles:
                if isinstance(p, dict) and p.get("id") == agent_id:
                    p["prompt"] = req.markdown
                    p["system_prompt"] = req.markdown
                    changed = True
            if changed:
                save_all_agent_profiles(profiles)
        except Exception as sync_err:
            logger.warning(f"[HR SOUL] Cache/Profile Sync fehlgeschlagen: {sync_err}")
        invalidate_hermes_profiles_cache()

        return {"status": "success", "agent_id": agent_id, "file_path": target_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/hr/personalakte/{agent_id}/log_activity")
def api_log_personalakte_activity(request: Request, agent_id: str, req: LogActivityReq):
    _require_admin(request)
    _validate_agent_id(agent_id)
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

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
