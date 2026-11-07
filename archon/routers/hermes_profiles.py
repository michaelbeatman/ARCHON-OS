"""Hermes-Profil-Verwaltung (lesen, anlegen, Status, Modell, Favorit, löschen)."""

import datetime
import json
import os
import re
import shutil
import sys
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from archon.core.runtime import (
    APP_ROOT, DATA_DIR, MEMORY_DIR, OBSIDIAN_VAULT_DIR, SETTINGS_FILE, WORKSPACE_DIR,
    add_ticker, logger,
)
from archon.core.permissions import (
    create_permission_gate as _create_permission_gate,
    load_permission_gates as _load_permission_gates,
)
from archon.core.profiles import (
    DEFAULT_HERMES_TOOLS, api_get_hermes_profiles, create_rolling_backup,
    get_hermes_profiles_base_dirs, get_primary_hermes_profiles_dir,
    invalidate_hermes_profiles_cache,
)

# --------------------------------------------------
# Dependency-Injektion statt Kopie
# --------------------------------------------------
# Die Funktionen save_all_agent_profiles, _sync_org_hierarchy_node,
# invalidate_paperclip_agents_cache leben in main.py und werden per
# configure() injiziert — kein main.py Import!
_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert die aus main.py injizierten Abhängigkeiten (einmalig beim Import)."""
    _DEPS.update(deps)
    _missing = {"save_all_agent_profiles", "_sync_org_hierarchy_node", "invalidate_paperclip_agents_cache"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] hermes_profiles: fehlende Dependencies {sorted(_missing)}")

router = APIRouter()


class SetProfileModelRequest(BaseModel):
    provider: str
    model: str
    reasoning_level: Optional[str] = None


class ProfileStatusUpdate(BaseModel):
    status: Optional[str] = "active"


class AgentProfileValidationSchema(BaseModel):
    id: str
    name: str
    person_name: str
    category: str
    model: str
    prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: List[str]

    def get_prompt_text(self) -> str:
        val = (self.prompt or self.system_prompt or "").strip()
        if not val:
            val = f"Du bist {self.person_name} ({self.name})."
        return val

@router.get("/api/hermes/profiles")
def api_get_hermes_profiles_route():
    """Duenne Huelle: Logik lebt in archon.core.profiles."""
    return api_get_hermes_profiles()


@router.get("/api/agents/profiles")
def api_get_agents_profiles():
    """Liefert die Agenten-Profile mit Runtime-Status (active/standby) aus agent_profiles.json."""
    profiles = list(api_get_hermes_profiles())  # liefert cached list
    enriched = []
    for p in profiles:
        p = dict(p)
        file_status = p.get("status", "active")
        p["runtime_status"] = file_status if file_status in ("active", "standby", "inactive") else "standby"
        # Frontend liest avatar_url — immer mitliefern, sonst springt das Bild zurueck
        if not p.get("avatar_url"):
            p["avatar_url"] = p.get("avatar") or ""
        enriched.append(p)
    return enriched


@router.post("/api/hermes/profiles")
def api_save_hermes_profile(profile_data: Dict = Body(...)):
    p_id = profile_data.get("id")
    if not p_id:
        p_id = re.sub(r'[^a-zA-Z0-9_]', '_', profile_data.get("name", "custom_agent").lower())
        profile_data["id"] = p_id

    person_name = profile_data.get("person_name") or profile_data.get("name", p_id)
    profile_data["person_name"] = person_name
    avatar_val = profile_data.get("avatar") or profile_data.get("avatar_url") or f"https://api.dicebear.com/7.x/notionists/svg?seed={p_id}&backgroundColor=3b82f6"
    profile_data["avatar"] = avatar_val
    # --- PERMISSION-GATE: NEUE TOOLS = Rechte-Erweiterung -> Owner per Telegram ---
    incoming_tools = profile_data.get("tools")
    _gate_ok = bool(profile_data.get("_approved_gate_id"))
    if isinstance(incoming_tools, list) and not _gate_ok:
        _alt_tools = []
        for p_base in get_hermes_profiles_base_dirs():
            yml = os.path.join(p_base, p_id, "profile.yaml")
            if os.path.exists(yml):
                try:
                    import yaml as _yaml
                    with open(yml, "r", encoding="utf-8") as _fy:
                        _alt_tools = (_yaml.safe_load(_fy) or {}).get("tools") or []
                    break
                except Exception:
                    pass
        _neue = [t for t in incoming_tools if t not in _alt_tools]
        if _neue:
            detail = (f"Profil '{p_id}' bekommt neue Tools: {', '.join(_neue[:8])}"
                      + (f" (+{len(_neue)-8} weitere)" if len(_neue) > 8 else ""))
            gate = _create_permission_gate(
                "tools_erweiterung", detail,
                f"agent:{profile_data.get('requested_by') or 'ui-owner'}",
                {k: v for k, v in profile_data.items() if k != "_approved_gate_id"})
            return {"status": "pending_owner_approval", "gate_id": gate["id"],
                    "message": "Rechte-Erweiterung erkannt: Warte auf deine Telegram-Bestätigung. "
                               f"Antworte dort: 'Erlauben {gate['id']}' oder 'Verbieten {gate['id']}'."}
    assigned_tools = profile_data.get("tools", DEFAULT_HERMES_TOOLS)
    profile_data["tools"] = assigned_tools
    assigned_skills = profile_data.get("skills", [])
    provider_val = profile_data.get("provider", "openrouter")
    model_val = profile_data.get("model", "deepseek/deepseek-v4-flash-0731")
    reasoning_val = str(profile_data.get("reasoning_level") or "high").strip().lower()
    if reasoning_val not in ("off", "minimal", "low", "medium", "high", "max"):
        reasoning_val = "high"
    profile_data["reasoning_level"] = reasoning_val
    status_val = profile_data.get("status", "active")
    is_fav = bool(profile_data.get("is_favorite", (p_id in ["default", "micha"])))

    # Prompt robust auflösen: Payload -> SOUL.md auf Disk -> Fallback
    prompt_val = (profile_data.get("prompt") or profile_data.get("system_prompt") or "").strip()
    if not prompt_val:
        for p_base in get_hermes_profiles_base_dirs():
            sf = os.path.join(p_base, p_id, "SOUL.md")
            if os.path.exists(sf):
                try:
                    with open(sf, "r", encoding="utf-8") as f_soul:
                        content = f_soul.read().strip()
                        if content:
                            prompt_val = content
                            break
                except Exception:
                    pass
        if not prompt_val:
            prompt_val = f"Du bist {person_name} ({profile_data.get('name', p_id)}). {profile_data.get('description', '')}".strip()

    profile_data["prompt"] = prompt_val
    profile_data["system_prompt"] = prompt_val
    profile_data["model"] = model_val

    # Pydantic-Schema-Validierung
    try:
        validated_profile = AgentProfileValidationSchema(
            id=str(p_id).strip(),
            name=str(profile_data.get("name", p_id)).strip(),
            person_name=str(person_name).strip(),
            category=str(profile_data.get("category", "1. Strategie, Führung & Lebensplanung")).strip(),
            model=str(model_val).strip(),
            prompt=profile_data.get("prompt"),
            system_prompt=profile_data.get("system_prompt"),
            tools=list(assigned_tools) if isinstance(assigned_tools, list) else []
        )
        prompt_text = validated_profile.get_prompt_text()
        if not validated_profile.name or not validated_profile.person_name or not validated_profile.category or not validated_profile.model:
            raise ValueError("All fields (id, name, person_name, category, model) are required and must be non-empty.")
    except Exception as val_err:
        logger.warning(f"[Profile Validation Failed] Rejecting profile save for '{p_id}': {val_err}")
        raise HTTPException(
            status_code=422,
            detail=f"Schema-Validierungsfehler für Profil: {str(val_err)}"
        )

    # In allen aktiven Profil-Ordnern anlegen/schreiben
    av_blob = None
    av_mime = "image/jpeg"
    clean_avatar = avatar_val

    if avatar_val and avatar_val.startswith("data:image"):
        try:
            import base64
            header, b64 = avatar_val.split(",", 1)
            av_mime = header.split(";")[0].replace("data:", "")
            ext = ".png" if "png" in av_mime else (".webp" if "webp" in av_mime else (".gif" if "gif" in av_mime else ".jpg"))
            av_blob = base64.b64decode(b64)
            
            _static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
            avatars_dir = os.path.join(_static_dir, "avatars")
            os.makedirs(avatars_dir, exist_ok=True)
            
            filename = f"custom_{p_id}{ext}"
            file_path = os.path.join(avatars_dir, filename)
            with open(file_path, "wb") as f_img:
                f_img.write(av_blob)
            
            clean_avatar = f"/static/avatars/{filename}"
            avatar_val = clean_avatar
            profile_data["avatar"] = clean_avatar
            profile_data["avatar_url"] = clean_avatar
            logger.info(f"[Profiles] Saved custom avatar for '{p_id}' to {file_path}")
        except Exception as e_av:
            logger.error(f"[Profiles] Error decoding/saving base64 avatar for {p_id}: {e_av}")
            clean_avatar = "/static/avatars/avatar_001.jpg"
    elif avatar_val and len(avatar_val) < 500:
        clean_avatar = avatar_val
    else:
        _static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        found_custom = False
        for test_ext in [".png", ".jpg", ".jpeg", ".webp"]:
            c_path = os.path.join(_static_dir, "avatars", f"custom_{p_id}{test_ext}")
            if os.path.exists(c_path):
                clean_avatar = f"/static/avatars/custom_{p_id}{test_ext}"
                found_custom = True
                break
        if not found_custom:
            clean_avatar = "/static/avatars/avatar_001.jpg"

    for p_base in get_hermes_profiles_base_dirs():
        try:
            target_pdir = os.path.join(p_base, p_id)
            os.makedirs(target_pdir, exist_ok=True)
            os.makedirs(os.path.join(target_pdir, "skills"), exist_ok=True)
            os.makedirs(os.path.join(target_pdir, "memories"), exist_ok=True)
            os.makedirs(os.path.join(target_pdir, "sessions"), exist_ok=True)

            soul_path = os.path.join(target_pdir, "SOUL.md")
            create_rolling_backup(soul_path, max_backups=3)
            with open(soul_path, "w", encoding="utf-8") as f:
                f.write(prompt_text + "\n")

            yaml_path = os.path.join(target_pdir, "profile.yaml")
            create_rolling_backup(yaml_path, max_backups=3)
            
            y_payload = {
                "name": profile_data.get("name", p_id),
                "person_name": person_name,
                "callsign": str(profile_data.get("callsign", "")).strip().lower(),
                "category": profile_data.get("category", "1. Strategie, Führung & Lebensplanung"),
                "description": profile_data.get("description", ""),
                "role_id": p_id,
                "avatar": clean_avatar,
                "avatar_url": clean_avatar,
                "tools": assigned_tools,
                "skills": assigned_skills,
                "status": status_val,
                "is_favorite": is_fav,
                "provider": provider_val,
                "model": model_val,
                "reasoning_level": reasoning_val,
                "llm": {
                    "provider": provider_val,
                    "model": model_val,
                    "reasoning_level": reasoning_val
                }
            }
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(y_payload, f, allow_unicode=True, sort_keys=False)

            # Hermes config.yaml anlegen ODER Modell/Provider aktualisieren
            config_path = os.path.join(target_pdir, "config.yaml")
            if not os.path.exists(config_path):
                default_cfg = {
                    "platforms": {"api_server": {"enabled": False}},
                    "model": {
                        "default": model_val,
                        "provider": provider_val,
                        "base_url": "http://omniroute:20128/v1",
                        "api_key": os.getenv("OMNIROUTE_API_KEY", "sk-archon-local-dev")
                    },
                    "providers": {
                        "omniroute": {
                            "name": "OmniRoute",
                            "base_url": "http://omniroute:20128/v1",
                            "api_key": os.getenv("OMNIROUTE_API_KEY", "sk-archon-local-dev"),
                            "key_env": "OMNIROUTE_API_KEY"
                        }
                    }
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(default_cfg, f, allow_unicode=True, sort_keys=False)
            else:
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        existing_cfg = yaml.safe_load(f) or {}
                    if not isinstance(existing_cfg.get("model"), dict):
                        existing_cfg["model"] = {}
                    existing_cfg["model"]["default"] = model_val
                    existing_cfg["model"]["provider"] = provider_val
                    with open(config_path, "w", encoding="utf-8") as f:
                        yaml.dump(existing_cfg, f, allow_unicode=True, sort_keys=False)
                except Exception as cfg_err:
                    logger.warning(f"[Profiles] Could not sync config.yaml for {p_id}: {cfg_err}")

            # Skills synchronisieren
            skills_sub = os.path.join(target_pdir, "skills")
            global_skills_dir = os.path.join(MEMORY_DIR, "hermes_skills")
            if not os.path.exists(global_skills_dir):
                global_skills_dir = os.path.expanduser("~/.hermes/skills")
            if os.path.exists(global_skills_dir):
                for sk_id in assigned_skills:
                    sk_src = os.path.join(global_skills_dir, sk_id)
                    sk_dst = os.path.join(skills_sub, sk_id)
                    if os.path.exists(sk_src) and not os.path.exists(sk_dst):
                        try:
                            if os.path.isdir(sk_src):
                                shutil.copytree(sk_src, sk_dst)
                            else:
                                shutil.copy2(sk_src, sk_dst)
                        except Exception as e:
                            logger.warning(f"Error copying skill {sk_id}: {e}")
        except Exception as e:
            logger.error(f"[Profiles] Error writing profile to {p_base}: {e}")

    # Synchronisiere agent_profiles.json für Operations-Kanban & Org-Chart
    try:
        ap_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
        if os.path.exists(ap_file):
            with open(ap_file, "r", encoding="utf-8") as f:
                ap_list = json.load(f)
            if isinstance(ap_list, list):
                updated_ap = False
                for item in ap_list:
                    if isinstance(item, dict) and item.get("id") == p_id:
                        item["name"] = profile_data.get("name", p_id)
                        item["person_name"] = person_name
                        item["category"] = profile_data.get("category", item.get("category", ""))
                        item["description"] = profile_data.get("description", item.get("description", ""))
                        item["avatar"] = clean_avatar
                        item["model"] = model_val
                        item["provider"] = provider_val
                        item["reasoning_level"] = reasoning_val
                        item["status"] = status_val
                        updated_ap = True
                        break
                if not updated_ap:
                    ap_list.append({
                        "id": p_id,
                        "name": profile_data.get("name", p_id),
                        "person_name": person_name,
                        "category": profile_data.get("category", ""),
                        "description": profile_data.get("description", ""),
                        "avatar": clean_avatar,
                        "model": model_val,
                        "provider": provider_val,
                        "status": status_val
                    })
                with open(ap_file, "w", encoding="utf-8") as f:
                    json.dump(ap_list, f, indent=2, ensure_ascii=False)
    except Exception as ap_err:
        logger.warning(f"[Profiles] Could not sync agent_profiles.json for {p_id}: {ap_err}")

    # Synchronisiere Avatar in avatars.db für Hermes WebUI
    try:
        import sqlite3, hashlib, time
        avatars_db_path = os.path.expanduser("~/.hermes/webui/avatars.db")
        if not os.path.exists(avatars_db_path):
            avatars_db_path = "/opt/data/webui/avatars.db"
        if os.path.exists(os.path.dirname(avatars_db_path)):
            with sqlite3.connect(avatars_db_path) as av_conn:
                if not av_blob and clean_avatar and clean_avatar.startswith("/static/avatars/"):
                    fname = os.path.basename(clean_avatar.split("?")[0])
                    _static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
                    loc_img = os.path.join(_static_dir, "avatars", fname)
                    if os.path.exists(loc_img):
                        with open(loc_img, "rb") as img_f:
                            av_blob = img_f.read()
                        av_mime = "image/png" if fname.endswith(".png") else "image/jpeg"
                if av_blob:
                    av_etag = '"' + hashlib.sha256(av_blob).hexdigest()[:32] + '"'
                    av_conn.execute(
                        "INSERT OR REPLACE INTO avatars (profile, mime, bytes, etag, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (p_id, av_mime, av_blob, av_etag, time.time())
                    )
                    av_conn.commit()
    except Exception as e:
        logger.warning(f"[Profiles] Error syncing avatar to avatars.db: {e}")

    _DEPS["_sync_org_hierarchy_node"](
        p_id,
        name=profile_data.get("name", p_id),
        person_name=person_name,
        avatar=clean_avatar,
        provider=provider_val,
        model=model_val,
        reasoning_level=reasoning_val
    )
    # Cache invalidieren und neu aufbauen
    invalidate_hermes_profiles_cache()
    api_get_hermes_profiles()
    add_ticker("Hermes Profiles", f"Profil '{person_name}' ({profile_data.get('name', p_id)}) gespeichert.")
    return {"status": "success", "profile": profile_data}


@router.post("/api/hermes/profiles/{profile_id}/avatar")
def api_upload_hermes_profile_avatar(profile_id: str, data: Dict = Body(...)):
    try:
        import base64, hashlib, time
        data_url = (data.get("image") or data.get("avatar") or "").strip()
        if not data_url.startswith("data:image"):
            raise HTTPException(status_code=400, detail="Ungültiges Bilddaten-Format (muss data:image/... sein).")
        
        header, b64 = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "")
        ext = ".png" if "png" in mime else (".webp" if "webp" in mime else (".gif" if "gif" in mime else ".jpg"))
        raw_bytes = base64.b64decode(b64)
        
        _static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        avatars_dir = os.path.join(_static_dir, "avatars")
        os.makedirs(avatars_dir, exist_ok=True)
        
        filename = f"custom_{profile_id}{ext}"
        file_path = os.path.join(avatars_dir, filename)
        with open(file_path, "wb") as f_img:
            f_img.write(raw_bytes)
        
        avatar_url = f"/static/avatars/{filename}"
        
        # In profile.yaml aller aktiven Profile-Verzeichnisse aktualisieren
        for p_base in get_hermes_profiles_base_dirs():
            py_path = os.path.join(p_base, profile_id, "profile.yaml")
            if os.path.exists(py_path):
                try:
                    with open(py_path, "r", encoding="utf-8") as f:
                        ydata = yaml.safe_load(f) or {}
                    ydata["avatar"] = avatar_url
                    ydata["avatar_url"] = avatar_url
                    with open(py_path, "w", encoding="utf-8") as f:
                        yaml.dump(ydata, f, allow_unicode=True, sort_keys=False)
                except Exception as py_err:
                    logger.warning(f"Could not update profile.yaml avatar for {profile_id}: {py_err}")
        
        # avatars.db aktualisieren
        try:
            import sqlite3
            avatars_db_path = os.path.expanduser("~/.hermes/webui/avatars.db")
            if not os.path.exists(avatars_db_path):
                avatars_db_path = "/opt/data/webui/avatars.db"
            if os.path.exists(os.path.dirname(avatars_db_path)):
                with sqlite3.connect(avatars_db_path) as av_conn:
                    av_etag = '"' + hashlib.sha256(raw_bytes).hexdigest()[:32] + '"'
                    av_conn.execute(
                        "INSERT OR REPLACE INTO avatars (profile, mime, bytes, etag, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (profile_id, mime, raw_bytes, av_etag, time.time())
                    )
                    av_conn.commit()
        except Exception as e_db:
            logger.warning(f"[upload_avatar] avatars.db sync warning: {e_db}")
            
        invalidate_hermes_profiles_cache()
        api_get_hermes_profiles()
        
        return {
            "status": "success",
            "profile_id": profile_id,
            "avatar_url": avatar_url,
            "revision": int(time.time())
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[upload_avatar] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/hermes/profiles/{profile_id}/status")
def api_update_hermes_profile_status(profile_id: str, body: Optional[ProfileStatusUpdate] = None):
    roles_list = api_get_hermes_profiles()
    prof = next((r for r in roles_list if r["id"] == profile_id), None)
    if not prof:
        return {"status": "error", "message": f"Profil '{profile_id}' nicht gefunden."}
    
    new_status = (body.status if body and body.status else "active").lower().strip()
    if new_status not in ("active", "inactive", "standby"):
        new_status = "active"
        
    prof["status"] = new_status
    prof["runtime_status"] = new_status
    _DEPS["save_all_agent_profiles"](roles_list)
    _DEPS["invalidate_paperclip_agents_cache"]()
    invalidate_hermes_profiles_cache()
    
    agent_label = prof.get('person_name', prof.get('name', profile_id)) if prof else profile_id
    action_text = "aktiviert" if new_status == "active" else "deaktiviert"
    add_ticker("Agenten-Kader", f"Agent '{agent_label}' {action_text}.")
    return {"status": "success", "profile_id": profile_id, "new_status": new_status}


@router.post("/api/hermes/profiles/{profile_id}/hire-paperclip")
def api_hire_hermes_profile_paperclip(profile_id: str):
    return api_update_hermes_profile_status(profile_id, ProfileStatusUpdate(status="active"))


@router.post("/api/hermes/profiles/{profile_id}/fire-paperclip")
def api_fire_hermes_profile_paperclip(profile_id: str):
    return api_update_hermes_profile_status(profile_id, ProfileStatusUpdate(status="inactive"))


@router.post("/api/hermes/profiles/{profile_id}/model")
def api_set_hermes_profile_model(profile_id: str, req: SetProfileModelRequest):
    try:
        import api_provider
        prov = req.provider.strip().lower()
        mod = req.model.strip()
        reas = (req.reasoning_level or "").strip().lower()
        res = api_provider.set_profile_model(profile_id, mod, provider=prov)
        for p_base in get_hermes_profiles_base_dirs():
            py_path = os.path.join(p_base, profile_id, "profile.yaml")
            if os.path.exists(py_path):
                try:
                    with open(py_path, "r", encoding="utf-8") as f:
                        p_data = yaml.safe_load(f) or {}
                    p_data["provider"] = prov
                    p_data["model"] = mod
                    if reas:
                        p_data["reasoning_level"] = reas
                    with open(py_path, "w", encoding="utf-8") as f:
                        yaml.dump(p_data, f, allow_unicode=True, sort_keys=False)
                except Exception as py_err:
                    logger.warning(f"Could not update profile.yaml for {profile_id}: {py_err}")
            cfg_path = os.path.join(p_base, profile_id, "config.yaml")
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        c_data = yaml.safe_load(f) or {}
                    if not isinstance(c_data.get("model"), dict):
                        c_data["model"] = {}
                    c_data["model"]["default"] = mod
                    c_data["model"]["provider"] = prov
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        yaml.dump(c_data, f, allow_unicode=True, sort_keys=False)
                except Exception as cfg_err:
                    logger.warning(f"Could not update config.yaml for {profile_id}: {cfg_err}")

        try:
            ap_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
            if os.path.exists(ap_file):
                with open(ap_file, "r", encoding="utf-8") as f:
                    ap_list = json.load(f)
                if isinstance(ap_list, list):
                    for item in ap_list:
                        if isinstance(item, dict) and item.get("id") == profile_id:
                            item["model"] = mod
                            item["provider"] = prov
                            if reas:
                                item["reasoning_level"] = reas
                            break
                    with open(ap_file, "w", encoding="utf-8") as f:
                        json.dump(ap_list, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        global _HERMES_PROFILES_CACHE
        _HERMES_PROFILES_CACHE = None

        return {"status": "ok", "provider": prov, "model": mod, "result": res}
    except Exception as e:
        logger.error(f"[set_profile_model] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.delete("/api/hermes/profiles/{profile_id}")
def api_delete_hermes_profile(profile_id: str, gate_approved_id: str = ""):
    if profile_id in ["default", "hermes_default", "micha"]:
        raise HTTPException(status_code=400, detail=f"System-Profil '{profile_id}' kann nicht gelöscht werden.")
    # --- PERMISSION-GATE: Loeschen = Rechte-Entzug -> Owner per Telegram ---
    if not gate_approved_id:
        _gates = _load_permission_gates().get("gates", [])
        _pend = [g for g in _gates if g.get("status") == "pending"
                 and g.get("kind") == "profil_loeschen"
                 and (g.get("payload") or {}).get("profile_id") == profile_id]
        if not _pend:
            gate = _create_permission_gate(
                "profil_loeschen", f"Profil '{profile_id}' soll Dauerhaft geloescht werden (Archiv)",
                "agent:ui-owner", {"profile_id": profile_id})
            return {"status": "pending_owner_approval", "gate_id": gate["id"],
                    "message": "Loeschen braucht deine Telegram-Bestätigung. "
                               f"Antworte: 'Erlauben {gate['id']}' oder 'Verbieten {gate['id']}'."}

    archived_locations = []
    for p_base in get_hermes_profiles_base_dirs():
        src_dir = os.path.join(p_base, profile_id)
        if os.path.exists(src_dir):
            archive_dir = os.path.join(p_base, ".archive")
            os.makedirs(archive_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dst_dir = os.path.join(archive_dir, f"{profile_id}_deleted_{ts}")
            try:
                shutil.move(src_dir, dst_dir)
                archived_locations.append(dst_dir)
            except Exception as e:
                logger.error(f"[Profiles] Error archiving {src_dir} to {dst_dir}: {e}")

    # Sofort aus agent_profiles.json entfernen
    _APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    for cand in [os.path.join(_APP_ROOT, "agent_profiles.json"), "agent_profiles.json"]:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    j_data = json.load(f)
                if isinstance(j_data, list):
                    filtered = [p for p in j_data if p.get("id") != profile_id]
                    create_rolling_backup(cand, max_backups=3)
                    with open(cand, "w", encoding="utf-8") as f:
                        json.dump(filtered, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"[Profiles] Error removing deleted profile from {cand}: {e}")

    invalidate_hermes_profiles_cache()
    # Aktualisierte Profil-Liste neu laden & spiegeln
    api_get_hermes_profiles()
    add_ticker("Hermes Profiles", f"Profil '{profile_id}' archiviert und entfernt.")
    return {"status": "success", "profile_id": profile_id, "archived_to": archived_locations}


@router.post("/api/hermes/profiles/{profile_id}/favorite")
def api_toggle_hermes_profile_favorite(profile_id: str, is_fav: Optional[bool] = None):
    new_fav_state = None
    for p_base in get_hermes_profiles_base_dirs():
        yaml_path = os.path.join(p_base, profile_id, "profile.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f) or {}
                if is_fav is not None:
                    ydata["is_favorite"] = is_fav
                else:
                    ydata["is_favorite"] = not ydata.get("is_favorite", False)
                new_fav_state = ydata["is_favorite"]
                with open(yaml_path, "w", encoding="utf-8") as f:
                    yaml.dump(ydata, f, allow_unicode=True, sort_keys=False)
            except Exception as e:
                logger.warning(f"[Profiles] Error updating favorite in {yaml_path}: {e}")

    invalidate_hermes_profiles_cache()
    api_get_hermes_profiles()
    return {"status": "success", "profile_id": profile_id, "is_favorite": new_fav_state if new_fav_state is not None else False}
