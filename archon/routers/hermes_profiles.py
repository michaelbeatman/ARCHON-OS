import sqlite3

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Hermes-Profil-Verwaltung (lesen, anlegen, Status, Modell, Favorit, löschen).

Die Fachlogik fuer Anlegen und Loeschen liegt in
``archon.services.profiles_service`` — dieser Router ist nur die HTTP-Fassade
(Rollenzaun + Uebersetzung der Domaenenfehler in HTTP-Antworten).
"""

import json
import os
import sys
from typing import Any, Dict, Optional

import yaml
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile, Request

from archon.routers._rbac import require_admin_or_503
from archon.services import profiles_service
from archon.services.profiles_service import (
    GateNotApproved, ProfileProtectedError, ProfileValidationError,
)
from utils.path_jail import safe_filename, PathJailError
from pydantic import BaseModel

from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import add_ticker, logger
from archon.core.profiles import (
    api_get_hermes_profiles,
    get_hermes_profiles_base_dirs, invalidate_hermes_profiles_cache,
    materialize_data_uri_avatar,
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

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class SetProfileModelRequest(BaseModel):
    provider: str
    model: str
    reasoning_level: Optional[str] = None


class ProfileStatusUpdate(BaseModel):
    status: Optional[str] = "active"


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
def api_save_hermes_profile(request: Request, profile_data: Dict = Body(...)):
    """Legt ein Profil an bzw. schreibt es fort.

    Duenne Fassade: der Rollenzaun steht hier, die Fachlogik liegt in
    ``archon.services.profiles_service`` (ohne HTTP-Abhaengigkeit, damit der
    Gate-Pfad in ``main.py`` sie direkt aufrufen kann).
    """
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        return profiles_service.save_profile(profile_data)
    except ProfileValidationError as val_err:
        raise HTTPException(
            status_code=422,
            detail={"code": "profiles_schema_validation_failed", "params": {"error": str(val_err)}}
        )
    except GateNotApproved as gate_err:
        raise HTTPException(status_code=403, detail=str(gate_err))


@router.post("/api/hermes/profiles/{profile_id}/avatar")
def api_upload_hermes_profile_avatar(request: Request, profile_id: str, data: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache (fail-closed, vor jedem Schreibpfad)
    if ".." in profile_id or "/" in profile_id or "\\" in profile_id:
        raise HTTPException(status_code=400, detail="Ungueltige profile_id (Pfad-Traversal unzulaessig).")
    try:
        profile_id = safe_filename(profile_id)
    except (PathJailError, ValueError) as e:
        raise HTTPException(status_code=400, detail={"code": "profiles_invalid_profile_id", "params": {"error": str(e)}})
    try:
        import base64, hashlib, time
        data_url = (data.get("image") or data.get("avatar") or "").strip()
        if not data_url.startswith("data:image"):
            raise HTTPException(status_code=400, detail="Ungültiges Bilddaten-Format (muss data:image/... sein).")

        # Ein Schreibpfad fuer alle: der atomare Helfer (tmp + os.replace) legt die
        # Datei im Laufzeitverzeichnis ab (avatars_dir) und liefert die /static-URL.
        # Frueher stand hier eine eigene Kopie dieser Logik ohne tmp+replace.
        avatar_url = materialize_data_uri_avatar(profile_id, data_url)
        if not avatar_url:
            raise HTTPException(status_code=400, detail="Bild konnte nicht gespeichert werden (Format/Inhalt ungueltig).")

        _, b64 = data_url.split(",", 1)
        mime = data_url.split(";")[0].replace("data:", "")
        raw_bytes = base64.b64decode(b64)

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
                avatars_db_path = os.path.join(OPT_DATA_DIR, "webui", "avatars.db")
            if os.path.exists(os.path.dirname(avatars_db_path)):
                with sqlite3.connect(avatars_db_path, factory=_ArchonClosingConn) as av_conn:
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
def api_update_hermes_profile_status(request: Request, profile_id: str, body: Optional[ProfileStatusUpdate] = None):
    require_admin_or_503(request)  # RBAC: Admin-Sache
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
def api_hire_hermes_profile_paperclip(request: Request, profile_id: str):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    return api_update_hermes_profile_status(request, profile_id, ProfileStatusUpdate(status="active"))


@router.post("/api/hermes/profiles/{profile_id}/fire-paperclip")
def api_fire_hermes_profile_paperclip(request: Request, profile_id: str):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    return api_update_hermes_profile_status(request, profile_id, ProfileStatusUpdate(status="inactive"))


@router.post("/api/hermes/profiles/{profile_id}/model")
def api_set_hermes_profile_model(request: Request, profile_id: str, req: SetProfileModelRequest):
    require_admin_or_503(request)  # RBAC: Admin-Sache
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
            from archon.core.runtime import APP_ROOT, atomic_write_json
            ap_file = os.path.join(APP_ROOT, "agent_profiles.json")
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
                    atomic_write_json(ap_file, ap_list)
        except Exception as _ap_err:
            logger.warning(f"[set_profile_model] Error updating SSOT agent_profiles.json: {_ap_err}")

        invalidate_hermes_profiles_cache()

        return {"status": "ok", "provider": prov, "model": mod, "result": res}
    except Exception as e:
        logger.error(f"[set_profile_model] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.delete("/api/hermes/profiles/{profile_id}")
def api_delete_hermes_profile(request: Request, profile_id: str, gate_approved_id: str = ""):
    """Archiviert ein Profil (Loeschen braucht ein Owner-Gate).

    Duenne Fassade: Rollenzaun hier, Fachlogik in
    ``archon.services.profiles_service``.
    """
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        return profiles_service.delete_profile(profile_id, approved_gate_id=gate_approved_id)
    except ProfileProtectedError as prot_err:
        raise HTTPException(status_code=400, detail=str(prot_err))
    except GateNotApproved as gate_err:
        raise HTTPException(status_code=403, detail=str(gate_err))


@router.post("/api/hermes/profiles/{profile_id}/favorite")
def api_toggle_hermes_profile_favorite(profile_id: str, is_fav: Optional[bool] = None, request: Request = None):
    if request is not None and isinstance(request, Request):
        require_admin_or_503(request)  # RBAC: Admin-Sache
    if ".." in profile_id or "/" in profile_id or "\\" in profile_id:
        raise HTTPException(status_code=400, detail="Ungueltige profile_id (Pfad-Traversal unzulaessig).")
    try:
        profile_id = safe_filename(profile_id)
    except (PathJailError, ValueError) as e:
        raise HTTPException(status_code=400, detail={"code": "profiles_invalid_profile_id_2", "params": {"error": str(e)}})
    # F-11: keine Erfolgsmeldung ohne Schreibbeleg. Vorher meldete der Endpoint
    # {"status": "success", "is_favorite": False}, wenn kein profile.yaml gefunden
    # oder der Write fehlschlug.
    updated_path = None
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
                # F-11: Temp + os.replace statt direktem Write (kein Halbstand).
                tmp_path = yaml_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    yaml.dump(ydata, f, allow_unicode=True, sort_keys=False)
                os.replace(tmp_path, yaml_path)
                updated_path = yaml_path
                break
            except Exception as e:
                logger.warning(f"[Profiles] Error updating favorite in {yaml_path}: {e}")

    if updated_path is None:
        # F-11: weder geschrieben noch gefunden -> ehrlicher Fehler (404), damit
        # das UI eine falsche Profil-ID nicht als Erfolg zeigt.
        raise HTTPException(status_code=404, detail={"code": "profiles_not_found_or_writable", "params": {"profile_id": profile_id}})

    invalidate_hermes_profiles_cache()
    api_get_hermes_profiles()
    return {"status": "success", "profile_id": profile_id, "is_favorite": new_fav_state, "path": updated_path}
