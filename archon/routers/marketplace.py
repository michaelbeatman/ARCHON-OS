from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""
Talent- & Skill-Marktplatz Router fuer Archon OS.
Verwaltet /api/marketplace/ Endpunkte (Sources, Templates, Skills, Recruiting).
Extrahiert aus main.py zur Modularisierung.
"""

import os
from typing import Dict, Any, List, Optional, cast
from fastapi import APIRouter, HTTPException, Query, Body, Request
from archon.routers._rbac import require_admin_or_503
from archon.core.runtime import add_ticker, logger
from archon.core.paths import HERMES_PROFILES_BASE, HERMES_PROFILES_DIR
from archon.core.profiles import (
    DEFAULT_HERMES_TOOLS,
    api_get_hermes_profiles,
    invalidate_hermes_profiles_cache,
)

_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert Dependencies (z.B. save_all_agent_profiles)."""
    _DEPS.update(deps)

from archon.routers._validated_body import PassthroughBody, as_payload
router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["marketplace"])

_MARKETPLACE_IMPORT_ERRORS: Dict[str, str] = {}

try:
    from utils.repo_sync import get_marketplace_sources, list_templates_for_source, get_template_detail
except Exception as _exc:
    # D01/MED: Importfehler nicht verschlucken und durch Fake-Quellen
    # ersetzen. Endpunkte melden explizit `not_configured` (HTTP 503).
    _MARKETPLACE_IMPORT_ERRORS["repo_sync"] = str(_exc)
    get_marketplace_sources = cast(Any, None)
    list_templates_for_source = cast(Any, None)
    get_template_detail = cast(Any, None)

try:
    from utils.skill_marketplace import get_skill_marketplace_sources, list_skills_for_source, get_skill_detail
except Exception as _exc:
    _MARKETPLACE_IMPORT_ERRORS["skill_marketplace"] = str(_exc)
    get_skill_marketplace_sources = cast(Any, None)
    list_skills_for_source = cast(Any, None)
    get_skill_detail = cast(Any, None)


def _require_marketplace_backend(name: str) -> None:
    if name in _MARKETPLACE_IMPORT_ERRORS:
        raise HTTPException(status_code=503, detail={
            "status": "not_configured",
            "code": "MARKETPLACE_BACKEND_UNAVAILABLE",
            "module": name,
            "message": _MARKETPLACE_IMPORT_ERRORS[name],
        })


@router.get("/api/marketplace/sources")
def api_get_marketplace_sources():
    _require_marketplace_backend("repo_sync")
    return get_marketplace_sources()


@router.get("/api/marketplace/templates")
def api_get_marketplace_templates(source: str = Query("fabric"), search: str = Query(None), category: str = Query(None)):
    _require_marketplace_backend("repo_sync")
    return list_templates_for_source(source, search=search, category=category)


@router.get("/api/marketplace/template")
def api_get_marketplace_template_detail(source: str = Query(...), id: str = Query(...)):
    _require_marketplace_backend("repo_sync")
    detail = get_template_detail(source, id)
    if not detail:
        raise HTTPException(status_code=404, detail="Template not found")
    return detail


@router.get("/api/marketplace/skills/sources")
def api_get_skill_sources():
    _require_marketplace_backend("skill_marketplace")
    return get_skill_marketplace_sources()


@router.get("/api/marketplace/skills")
def api_get_skills_list(source: str = Query("realestate"), search: str = Query(None), category: str = Query(None)):
    _require_marketplace_backend("skill_marketplace")
    return list_skills_for_source(source, search=search, category=category)


@router.get("/api/marketplace/skill")
def api_get_skill_detail(source: str = Query(...), id: str = Query(...)):
    _require_marketplace_backend("skill_marketplace")
    detail = get_skill_detail(source, id)
    if not detail:
        raise HTTPException(status_code=404, detail="Skill not found")
    return detail


@router.post("/api/marketplace/skills/assign")
def api_assign_skill_to_profile(request: Request, data: PassthroughBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    data_payload = as_payload(data)
    import re as _re
    profile_id = data_payload.get("profile_id")
    skill_name = data_payload.get("skill_name") or data_payload.get("skill_id")
    if not profile_id or not skill_name:
        raise HTTPException(status_code=400, detail="profile_id and skill_name are required")
    if (
        ".." in profile_id
        or ".." in skill_name
        or not _re.fullmatch(r"[A-Za-z0-9._\-]{1,128}", profile_id)
        or not _re.fullmatch(r"[A-Za-z0-9._\-]{1,128}", skill_name)
    ):
        raise HTTPException(status_code=400, detail="Ungueltige profile_id oder skill_name.")
        
    # Invalidate cache to fetch fresh state
    invalidate_hermes_profiles_cache()
    roles_list = api_get_hermes_profiles()
    
    target_prof = None
    for p in roles_list:
        if p.get("id") == profile_id:
            target_prof = p
            break
            
    if target_prof is not None:
        cur_skills = target_prof.get("skills", [])
        if skill_name not in cur_skills:
            cur_skills.append(skill_name)
            target_prof["skills"] = cur_skills
    else:
        roles_list.append({
            "id": profile_id,
            "name": profile_id,
            "person_name": profile_id,
            "category": "1. Strategie, Führung & Lebensplanung",
            "skills": [skill_name],
            "tools": DEFAULT_HERMES_TOOLS,
            "status": "active",
            "is_favorite": False
        })

    # 1. Update SSOT and mirror files
    save_fn = _DEPS.get("save_all_agent_profiles")
    if save_fn:
        save_fn(roles_list)
    invalidate_hermes_profiles_cache()

    # 2. Synchronize skill directory/tag in profile folders
    for p_base in [HERMES_PROFILES_DIR, HERMES_PROFILES_BASE, os.path.expanduser("~/.hermes/profiles")]:
        prof_skills_dir = os.path.join(p_base, profile_id, "skills")
        if os.path.exists(os.path.join(p_base, profile_id)):
            os.makedirs(prof_skills_dir, exist_ok=True)
            with open(os.path.join(prof_skills_dir, f"{skill_name}.md"), "w", encoding="utf-8") as f:
                f.write(f"# Assigned Skill: {skill_name}\n")

    return {"status": "success", "profile_id": profile_id, "assigned_skill": skill_name}


@router.post("/api/marketplace/recruit")
def api_marketplace_recruit(request: Request, data: PassthroughBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    data_payload = as_payload(data)
    source = data_payload.get("source", "fabric")
    template_id = str(data_payload.get("template_id") or data_payload.get("id") or "")
    custom_name = data_payload.get("name")

    _require_marketplace_backend("repo_sync")
    tpl = get_template_detail(source, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
        
    import re as _re
    profile_id = template_id.lower().replace("-", "_").replace(" ", "_")
    if ".." in profile_id or not _re.fullmatch(r"[A-Za-z0-9._\-]{1,128}", profile_id):
        raise HTTPException(status_code=400, detail="Ungueltige profile_id.")
    profile_name = custom_name or tpl.get("name") or profile_id.replace("_", " ").title()
    category = tpl.get("category", "1. Strategie, Führung & Lebensplanung")
    description = tpl.get("description") or f"Aus Marktplatz ({source}) rekrutiertes Profil."
    prompt = tpl.get("system_prompt", "")
    skills = tpl.get("skills", ["Research", "Tool Execution"])
    
    # Save as Hermes Profile
    prof_dir = os.path.join(HERMES_PROFILES_DIR, profile_id)
    os.makedirs(prof_dir, exist_ok=True)
    
    # Write SOUL.md
    with open(os.path.join(prof_dir, "SOUL.md"), "w", encoding="utf-8") as f:
        f.write(prompt + "\n")
        
    # Write profile.yaml
    with open(os.path.join(prof_dir, "profile.yaml"), "w", encoding="utf-8") as f:
        f.write(f'name: "{profile_name}"\ncategory: "{category}"\ndescription: "{description}"\nrole_id: "{profile_id}"\n')
        
    # Write skills
    skills_sub = os.path.join(prof_dir, "skills")
    os.makedirs(skills_sub, exist_ok=True)
    
    # Also write to host ~/.hermes/profiles
    host_profiles_dir = os.path.expanduser("~/.hermes/profiles")
    if os.path.exists(host_profiles_dir):
        host_prof_folder = os.path.join(host_profiles_dir, profile_id)
        os.makedirs(host_prof_folder, exist_ok=True)
        with open(os.path.join(host_prof_folder, "SOUL.md"), "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
        with open(os.path.join(host_prof_folder, "profile.yaml"), "w", encoding="utf-8") as f:
            f.write(f'name: "{profile_name}"\ncategory: "{category}"\ndescription: "{description}"\nrole_id: "{profile_id}"\n')
        os.makedirs(os.path.join(host_prof_folder, "skills"), exist_ok=True)

    # Invalidate and fetch current profiles
    invalidate_hermes_profiles_cache()
    roles_list = api_get_hermes_profiles()
    existing_r = False
    for r in roles_list:
        if r["id"] == profile_id:
            r["name"] = profile_name
            r["person_name"] = profile_name
            r["category"] = category
            r["description"] = description
            r["prompt"] = prompt
            r["skills"] = skills
            existing_r = True
            break
    if not existing_r:
        roles_list.append({
            "id": profile_id,
            "name": profile_name,
            "person_name": profile_name,
            "category": category,
            "description": description,
            "prompt": prompt,
            "skills": skills,
            "tools": DEFAULT_HERMES_TOOLS,
            "status": "active",
            "is_favorite": False
        })

    save_fn = _DEPS.get("save_all_agent_profiles")
    if save_fn:
        save_fn(roles_list)
    invalidate_hermes_profiles_cache()
    
    add_ticker("Talent-Marktplatz", f"Rolle '{profile_name}' ({profile_id}) aus {source} rekrutiert!")
    return {
        "status": "success",
        "profile": {
            "id": profile_id,
            "name": profile_name,
            "person_name": profile_name,
            "category": category,
            "description": description,
            "prompt": prompt,
            "skills": skills
        }
    }
