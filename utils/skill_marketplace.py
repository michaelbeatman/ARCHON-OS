"""
Fast Skill Marketplace Module for ARCHON OS
Loads from data/skills_marketplace_catalog.json
"""
import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in locals() else os.getcwd()
CATALOG_CANDIDATES = [
    os.path.join(BASE_DIR, 'data', 'skills_marketplace_catalog.json'),
    os.path.join(BASE_DIR, 'skills_marketplace_catalog.json'),
    '/app/data/skills_marketplace_catalog.json',
    '/app/skills_marketplace_catalog.json',
    'data/skills_marketplace_catalog.json',
    'skills_marketplace_catalog.json',
    '/opt/data/skills_marketplace_catalog.json'
]

SOURCE_ALIASES = {
    "realestate": "realestate_skills",
    "realestate_skills": "realestate_skills",
    "mcp": "mcp_tools",
    "mcp_tools": "mcp_tools",
    "hermes_native": "hermes_skills",
    "hermes_skills": "hermes_skills",
    "gemini": "gemini_skills",
    "gemini_skills": "gemini_skills",
    "science": "science_plugins",
    "science_plugins": "science_plugins",
    "german": "deutsch_fachskills",
    "deutsch": "deutsch_fachskills",
    "deutsch_fachskills": "deutsch_fachskills",
    "langchain": "gemini_skills",
    "toolhouse": "mcp_tools"
}

_CACHED_CATALOG = None

def _load_catalog():
    global _CACHED_CATALOG
    if _CACHED_CATALOG is not None:
        return _CACHED_CATALOG
        
    for cand in CATALOG_CANDIDATES:
        if os.path.exists(cand):
            try:
                with open(cand, 'r', encoding='utf-8') as f:
                    _CACHED_CATALOG = json.load(f)
                    return _CACHED_CATALOG
            except Exception as e:
                print(f"Error loading {cand}: {e}")
            
    return {}

def get_skill_marketplace_sources():
    catalog = _load_catalog()
    return [
        {"id": k, "name": f"{v['name']} ({len(v['skills'])} Skills)"} 
        for k, v in catalog.items()
    ]

def list_skills_for_source(source_id: str = "hermes_skills", search: str = None, category: str = None):
    catalog = _load_catalog()
    target_id = SOURCE_ALIASES.get(source_id, source_id)
    source_data = catalog.get(target_id)
    if not source_data:
        first_key = list(catalog.keys())[0] if catalog else None
        source_data = catalog.get(first_key, {"skills": []})
        
    skills = source_data.get("skills", [])
    
    if search:
        s_lower = search.lower().strip()
        skills = [
            s for s in skills 
            if s_lower in s["name"].lower() or s_lower in s["id"].lower() or s_lower in s.get("description", "").lower()
        ]
        
    if category and category != "all":
        skills = [s for s in skills if s.get("category") == category]
        
    return skills

def get_skill_detail(source_id: str, skill_id: str):
    catalog = _load_catalog()
    target_id = SOURCE_ALIASES.get(source_id, source_id)
    if target_id in catalog:
        for s in catalog[target_id].get("skills", []):
            if s["id"] == skill_id:
                return s
    for src in catalog.values():
        for s in src.get("skills", []):
            if s["id"] == skill_id:
                return s
    return None
