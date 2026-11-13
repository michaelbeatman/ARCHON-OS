import os
import json
import re
import sys

base_dir = "/app/project_root" if os.path.exists("/app/project_root") else r"."
main_py_path = os.path.join(base_dir, "main.py")
index_html_path = os.path.join(base_dir, "static", "index.html")
core_dispatcher_path = os.path.join(base_dir, "core_dispatcher.py")

print(f"Applying profile sync on {base_dir}...")

# 1. Update main.py
with open(main_py_path, "r", encoding="utf-8") as f:
    main_content = f.read()

# Add get_all_hermes_profiles function and /api/profiles routes
profile_helper_code = '''
def get_all_hermes_profiles() -> List[Dict]:
    """
    Single Source of Truth for all Hermes agent profiles.
    Scans /opt/data/profiles/ (and fallbacks ~/.hermes/profiles, agent_profiles.json).
    """
    profiles_dict = {}
    
    # Candidate base directories
    candidate_dirs = [
        "/opt/data/profiles",
        os.path.expanduser("~/.hermes/profiles"),
        os.path.join(MEMORY_DIR, "hermes_profiles"),
        "C:\\\\Users\\\\micha\\\\.hermes\\\\profiles"
    ]
    
    for p_base in candidate_dirs:
        if not p_base or not os.path.exists(p_base):
            continue
        try:
            for handle in os.listdir(p_base):
                p_dir = os.path.join(p_base, handle)
                if not os.path.isdir(p_dir) or handle.startswith("."):
                    continue
                if handle in profiles_dict:
                    continue
                
                yaml_path = os.path.join(p_dir, "profile.yaml")
                soul_path = os.path.join(p_dir, "SOUL.md")
                
                meta = {}
                if os.path.exists(yaml_path):
                    try:
                        import yaml
                        with open(yaml_path, "r", encoding="utf-8", errors="ignore") as yf:
                            meta = yaml.safe_load(yf) or {}
                    except Exception:
                        pass
                
                soul_content = ""
                if os.path.exists(soul_path):
                    try:
                        with open(soul_path, "r", encoding="utf-8", errors="ignore") as sf:
                            soul_content = sf.read().strip()
                    except Exception:
                        pass
                
                display_name = meta.get("name") or meta.get("display_name") or handle.replace("_", " ").title()
                person_name = meta.get("person_name") or display_name
                category = meta.get("category") or "1. Strategie, Führung & Lebensplanung"
                description = meta.get("description") or ""
                desc_long = meta.get("description_long") or soul_content or description
                avatar = meta.get("avatar") or meta.get("avatar_url") or f"https://api.dicebear.com/7.x/notionists/svg?seed={handle}&backgroundColor=3b82f6"
                skills = meta.get("skills") or []
                tools = meta.get("tools") or DEFAULT_HERMES_TOOLS
                
                profiles_dict[handle] = {
                    "handle": handle,
                    "id": handle,
                    "display_name": display_name,
                    "name": display_name,
                    "person_name": person_name,
                    "category": category,
                    "description": description,
                    "description_long": desc_long,
                    "system_prompt": soul_content or desc_long,
                    "soul_markdown": soul_content,
                    "prompt": soul_content or desc_long,
                    "avatar": avatar,
                    "avatar_url": avatar,
                    "skills": skills,
                    "tools": tools,
                    "status": "active",
                    "is_favorite": meta.get("is_favorite", False)
                }
        except Exception as e:
            print(f"[HERMES PROFILE SCAN] Error reading {p_base}: {e}")
            
    # Fallback to agent_profiles.json / roles.json if directory scan was empty
    if not profiles_dict:
        for cand in [
            os.path.join(WORKSPACE_DIR, "agent_profiles.json"),
            os.path.join(MEMORY_DIR, "agent_profiles.json"),
            "agent_profiles.json",
            os.path.join(WORKSPACE_DIR, "roles.json")
        ]:
            if os.path.exists(cand):
                try:
                    with open(cand, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, list):
                        for r in raw:
                            hid = r.get("id") or r.get("handle") or r.get("role_id")
                            if hid and hid not in profiles_dict:
                                d_name = r.get("name") or r.get("display_name") or hid.replace("_", " ").title()
                                profiles_dict[hid] = {
                                    "handle": hid,
                                    "id": hid,
                                    "display_name": d_name,
                                    "name": d_name,
                                    "person_name": r.get("person_name") or d_name,
                                    "category": r.get("category") or "1. Strategie, Führung & Lebensplanung",
                                    "description": r.get("description", ""),
                                    "description_long": r.get("description_long") or r.get("prompt", ""),
                                    "system_prompt": r.get("system_prompt") or r.get("prompt", ""),
                                    "soul_markdown": r.get("soul_markdown") or r.get("prompt", ""),
                                    "prompt": r.get("prompt") or r.get("system_prompt", ""),
                                    "avatar": r.get("avatar") or r.get("avatar_url") or f"https://api.dicebear.com/7.x/notionists/svg?seed={hid}&backgroundColor=3b82f6",
                                    "skills": r.get("skills", []),
                                    "tools": r.get("tools", DEFAULT_HERMES_TOOLS),
                                    "status": r.get("status", "active")
                                }
                        break
                except Exception:
                    pass

    return list(profiles_dict.values())
'''

# Update load_roles in main.py to use get_all_hermes_profiles
old_load_roles = "def load_roles() -> List[Dict]: return _load_json(ROLES_FILE, DEFAULT_ROLES)"
new_load_roles = """def load_roles() -> List[Dict]:
    profs = get_all_hermes_profiles()
    return profs if profs else _load_json(ROLES_FILE, DEFAULT_ROLES)"""

if old_load_roles in main_content:
    main_content = main_content.replace(old_load_roles, old_load_roles + "\n" + profile_helper_code + "\n" + new_load_roles)
elif "def get_all_hermes_profiles()" not in main_content:
    main_content = profile_helper_code + "\n" + main_content

# Add /api/profiles endpoints
api_profiles_endpoints = '''
@app.get("/api/profiles")
def api_get_profiles():
    """Returns dynamic Hermes profiles from /opt/data/profiles/ as single source of truth."""
    return get_all_hermes_profiles()

@app.get("/api/profiles/{handle}")
def api_get_profile_by_handle(handle: str):
    for p in get_all_hermes_profiles():
        if p.get("handle") == handle or p.get("id") == handle:
            return p
    raise HTTPException(status_code=404, detail=f"Profile '{handle}' not found")

@app.post("/api/profiles/{handle}")
def api_update_profile_by_handle(handle: str, profile_data: Dict = Body(...)):
    profile_data["handle"] = handle
    profile_data["id"] = handle
    return api_save_hermes_profile(profile_data)

@app.post("/api/profiles")
def api_save_profiles_collection(profile_data: Any = Body(...)):
    if isinstance(profile_data, list):
        for p in profile_data:
            api_save_hermes_profile(p)
        return {"status": "success", "count": len(profile_data)}
    elif isinstance(profile_data, dict):
        return api_save_hermes_profile(profile_data)
    return {"status": "error", "detail": "Invalid payload"}
'''

if "@app.get(\"/api/profiles\")" not in main_content:
    main_content += "\n" + api_profiles_endpoints

with open(main_py_path, "w", encoding="utf-8") as f:
    f.write(main_content)

print(f"Updated {main_py_path} with /api/profiles endpoints and dynamic loader.")

# 2. Update static/index.html
with open(index_html_path, "r", encoding="utf-8") as f:
    html = f.read()

# Tab KI-ROLLEN -> HERMES-PROFILE
html = html.replace('🎭 KI-ROLLEN', '🎭 HERMES-PROFILE')
html = html.replace('Alle Kategorien (24 Spezial-Rollen)', 'Alle Kategorien (Hermes-Profile)')

# Remove RESET (24 BASE ROLES) button
html = re.sub(r'<button\s+onclick="resetRolesToDefault\(\)"[^>]*>.*?</button>', '', html)

# Update saveRoleSettingsChanges in JS to use POST /api/profiles/{handle}
js_save_role_old = r'async function saveRoleSettingsChanges\(\) \{.*?alert\("Rolle erfolgreich gespeichert!"\);.*?\} catch \(e\) \{.*?\}'
js_save_role_new = '''async function saveRoleSettingsChanges() {
      const name = document.getElementById("setting-role-name").value.trim();
      const prompt = document.getElementById("setting-role-prompt").value.trim();
      const category = document.getElementById("setting-role-category").value;
      if (!name || !prompt) {
        alert("Bitte fülle Rollenname und System Prompt aus!");
        return;
      }
      const role = roles.find(r => r.id === currentEditingRoleSettingsId || r.handle === currentEditingRoleSettingsId);
      if (role) {
        role.name = name;
        role.display_name = name;
        role.prompt = prompt;
        role.system_prompt = prompt;
        role.category = category;
      }
      
      const payload = {
        handle: currentEditingRoleSettingsId,
        id: currentEditingRoleSettingsId,
        name: name,
        display_name: name,
        category: category,
        system_prompt: prompt,
        soul_markdown: prompt,
        prompt: prompt
      };
      
      try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(currentEditingRoleSettingsId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          // Fallback to /api/hermes/profiles
          await fetch("/api/hermes/profiles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          });
        }
        alert("Hermes-Profil erfolgreich gespeichert!");
        await loadRolesFromServer();
        populateSettingsRoleDropdown();
        renderAgentsSidebar();
        populateBoardroomChairmanSelect();
      } catch (e) {
        alert("Fehler beim Speichern des Profils: " + e);
      }
    }'''

html = re.sub(js_save_role_old, js_save_role_new, html, flags=re.DOTALL)

# Update loadRolesFromServer to fetch /api/profiles first
js_load_roles_old = r'async function loadRolesFromServer\(\) \{.*?roles = await res\.json\(\);.*?\}'
js_load_roles_new = '''async function loadRolesFromServer() {
      try {
        let res = await fetch("/api/profiles");
        if (!res.ok) res = await fetch("/api/roles");
        if (res.ok) {
          roles = await res.json();
          hermesProfilesData = roles;
        }
      } catch (e) {
        console.error("Failed to load profiles from server:", e);
      }
    }'''

html = re.sub(js_load_roles_old, js_load_roles_new, html, flags=re.DOTALL)

with open(index_html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Updated {index_html_path} with Hermes-Profile tab, removed reset button, and /api/profiles integration.")

# 3. Update core_dispatcher.py fallback in run_boardroom_debate
with open(core_dispatcher_path, "r", encoding="utf-8") as f:
    cd_code = f.read()

# Enhance build_final_system_prompt or dispatch to read SOUL.md if base_system_prompt is empty
soul_fallback_code = '''
def _resolve_profile_base_prompt(profile_id: str, existing_prompt: str = "") -> str:
    if existing_prompt and len(existing_prompt.strip()) > 30:
        return existing_prompt.strip()
    candidate_paths = [
        f"/opt/data/profiles/{profile_id}/SOUL.md",
        os.path.expanduser(f"~/.hermes/profiles/{profile_id}/SOUL.md"),
        f"C:\\\\Users\\\\micha\\\\.hermes\\\\profiles\\\\{profile_id}\\\\SOUL.md"
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    if content:
                        return content
            except Exception:
                pass
    return existing_prompt or ""
'''

if "_resolve_profile_base_prompt" not in cd_code:
    # insert before build_final_system_prompt
    bf_idx = cd_code.find("def build_final_system_prompt(")
    if bf_idx != -1:
        cd_code = cd_code[:bf_idx] + soul_fallback_code + "\n" + cd_code[bf_idx:]
        
        # update build_final_system_prompt to use _resolve_profile_base_prompt
        cd_code = cd_code.replace(
            'if base_system_prompt and base_system_prompt.strip():\n        parts.append(f"[PROFILE_BASE_SOUL (FACHWISSEN & PERSONA)]\\n{base_system_prompt.strip()}")',
            'resolved_base = _resolve_profile_base_prompt(selected_framework_id if is_chairman else role_dimension, base_system_prompt)\n    if resolved_base:\n        parts.append(f"[PROFILE_BASE_SOUL (FACHWISSEN & PERSONA)]\\n{resolved_base}")'
        )

with open(core_dispatcher_path, "w", encoding="utf-8") as f:
    f.write(cd_code)

print(f"Updated {core_dispatcher_path} with SOUL.md resolution fallback.")
