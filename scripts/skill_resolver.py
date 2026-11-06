# -*- coding: utf-8 -*-
"""
Skill Resolver & Dynamic Context Injector for Archon OS / Hermes.
Ensures specialized agents automatically load and use their assigned skills
from their profile manifest as well as session-activated and explicitly triggered skills.
"""

import os
import re
import sys
import json
import logging
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger("archon_skill_resolver")

DATA_DIR = "/app/data" if os.path.exists("/app/data") else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SESSION_SKILLS_JSON = os.path.join(DATA_DIR, "session_active_skills.json")

def _load_all_session_skills() -> dict:
    if os.path.exists(SESSION_SKILLS_JSON):
        try:
            with open(SESSION_SKILLS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_all_session_skills(data: dict):
    os.makedirs(os.path.dirname(SESSION_SKILLS_JSON), exist_ok=True)
    try:
        with open(SESSION_SKILLS_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[SkillResolver] Error writing session skills: {e}")

def get_session_active_skills(session_id: str) -> List[str]:
    data = _load_all_session_skills()
    return data.get(session_id, [])

def clear_session_active_skills(session_id: str):
    data = _load_all_session_skills()
    if session_id in data:
        del data[session_id]
        _save_all_session_skills(data)

def add_session_active_skill(session_id: str, skill_id: str):
    data = _load_all_session_skills()
    curr = data.get(session_id, [])
    if skill_id not in curr:
        curr.append(skill_id)
        data[session_id] = curr
        _save_all_session_skills(data)

def detect_skills_in_message(message: str, available_skills: dict) -> Tuple[List[str], Optional[str]]:
    """
    Scans a message for requested skills or management commands.
    Returns: (detected_skill_ids, action_command)
    action_command can be: None, 'clear', 'list'
    """
    msg_clean = message.strip()
    msg_lower = msg_clean.lower()
    
    # 0. Check for management commands
    if msg_lower in ("/skill clear", "/skills clear", "skills leeren", "skills reset"):
        return ([], "clear")
    if msg_lower in ("/skill list", "/skills list", "welche skills sind aktiv", "aktive skills"):
        return ([], "list")
        
    detected = set()
    msg_alphanum = re.sub(r'[^a-z0-9]', '', msg_lower)
    
    # 1. Slash commands: /skill <name>
    m_cmd = re.search(r'/(?:skill|load-skill)\s+([a-zA-Z0-9_\-]+)', msg_clean, re.IGNORECASE)
    if m_cmd:
        cand = m_cmd.group(1).lower().replace("skill-", "")
        for k in (cand, f"skill-{cand}"):
            if k in available_skills:
                detected.add(k.replace("skill-", ""))
            
    # 2. Natural language phrases: 'Skill <name>', 'Lade Skill <name>'
    m_phrase = re.findall(r'(?:skill|protokoll)[\s:"]+([a-zA-Z0-9_\-]+)', msg_clean, re.IGNORECASE)
    for cand in m_phrase:
        c_low = cand.lower().strip('"\'').replace("skill-", "")
        for k in (c_low, f"skill-{c_low}"):
            if k in available_skills:
                detected.add(k.replace("skill-", ""))
        c_hyphen = re.sub(r'([a-z])([A-Z])', r'\1-\2', cand).lower().replace("skill-", "")
        for k in (c_hyphen, f"skill-{c_hyphen}"):
            if k in available_skills:
                detected.add(k.replace("skill-", ""))

    # 3. Direct matching of specific known skills or normalized keys
    for skill_id in available_skills.keys():
        clean_id = skill_id.replace("skill-", "")
        if len(clean_id) < 5:
            continue
        skill_clean = re.sub(r'[^a-z0-9]', '', clean_id.lower())
        if skill_clean in msg_alphanum:
            if clean_id in ("bewerbungs-protokoll", "michael-keller-profile", "master-instruction", "karpathy-coder", "avoid-ai-writing") or "skill" in msg_lower or "protokoll" in msg_lower:
                detected.add(clean_id)
                
    return (sorted(list(detected)), None)

def load_skill_text(skill_id: str, find_skill_file_fn) -> Optional[Tuple[str, str]]:
    """
    Loads SKILL.md for a given skill_id, prioritizing local unnested paths.
    Returns (skill_title, file_content) or None.
    """
    clean_id = skill_id.replace("skill-", "")
    local_candidates = [
        f"/opt/data/skills/{skill_id}/SKILL.md",
        f"/opt/data/skills/{clean_id}/SKILL.md",
        f"/opt/data/skills/skill-{clean_id}/SKILL.md",
        os.path.expanduser(f"~/.hermes/skills/{skill_id}/SKILL.md"),
        os.path.expanduser(f"~/.hermes/skills/{clean_id}/SKILL.md"),
        os.path.join(os.path.dirname(DATA_DIR), ".agents", "skills", skill_id, "SKILL.md"),
        os.path.join(os.path.dirname(DATA_DIR), ".agents", "skills", clean_id, "SKILL.md")
    ]
    target_path = None
    for cand in local_candidates:
        if os.path.exists(cand):
            target_path = cand
            break
            
    if not target_path:
        target_path = find_skill_file_fn(skill_id) or find_skill_file_fn(clean_id)
        
    if not target_path or not os.path.exists(target_path):
        return None
        
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return (clean_id, content)
    except Exception as e:
        logger.error(f"[SkillResolver] Error reading skill file {target_path}: {e}")
        return None

def resolve_and_prepare_skill_context(
    session_id: str, 
    user_msg: str, 
    find_skill_file_fn, 
    skills_index: dict,
    agent_prof: Optional[dict] = None
) -> Tuple[Optional[str], List[str], Optional[str]]:
    """
    1. Scans user_msg for explicit/natural skill triggers.
    2. Inspects agent_prof for profile-assigned skills from the Kader.
    3. Auto-activates relevant assigned skills based on prompt keywords.
    4. Auto-loads companion skills (e.g. michael-keller-profile for bewerbungs-protokoll).
    5. Injects structured skills context into the agent's system prompt.
    """
    detected_new, action_cmd = detect_skills_in_message(user_msg, skills_index)
    freshly_loaded = []
    direct_notice = None
    
    if action_cmd == "clear":
        clear_session_active_skills(session_id)
        direct_notice = "🧹 *[System: Alle aktiven Skills für diese Sitzung wurden zurückgesetzt.]*\n\n"
        return (None, [], direct_notice)
        
    if action_cmd == "list":
        active = get_session_active_skills(session_id)
        assigned = (agent_prof.get("skills", []) if agent_prof else [])
        msg = f"📋 **[System: Skill-Status für {agent_prof.get('person_name', 'Agent') if agent_prof else 'Agent'}]**\n\n"
        msg += f"• **Im Profil zugewiesene Skills ({len(assigned)}):** " + (", ".join([f"`{s}`" for s in assigned]) if assigned else "_Keine_") + "\n"
        msg += f"• **In dieser Session aktiv im Volltext geladen ({len(active)}):** " + (", ".join([f"`{s}`" for s in active]) if active else "_Keine_") + "\n\n"
        return (None, [], msg)
    
    COMPANIONS = {
        "bewerbungs-protokoll": ["michael-keller-profile"]
    }
    
    # Check profile-assigned skills: Does the user message match any assigned skill?
    assigned_skills = []
    if agent_prof and isinstance(agent_prof.get("skills"), list):
        assigned_skills = agent_prof["skills"]
        
    msg_clean_lower = user_msg.lower()
    msg_alphanum = re.sub(r'[^a-z0-9]', '', msg_clean_lower)
    
    for a_sk in assigned_skills:
        clean_ask = a_sk.replace("skill-", "")
        ask_alphanum = re.sub(r'[^a-z0-9]', '', clean_ask.lower())
        # Check if skill name or parts of it appear in user message
        tokens = [t for t in re.split(r'[-_]', clean_ask.lower()) if len(t) > 3]
        matches = False
        if ask_alphanum and ask_alphanum in msg_alphanum:
            matches = True
        elif tokens and any(tok in msg_clean_lower for tok in tokens):
            # If 2 or more tokens match, or 1 strong token
            matched_toks = [tok for tok in tokens if tok in msg_clean_lower]
            if len(matched_toks) >= 1 and (len(tokens) == 1 or len(matched_toks) >= 2):
                matches = True
                
        if matches and clean_ask not in detected_new:
            detected_new.append(clean_ask)
            
    # If the agent has assigned bewerbungs-protokoll directly in its profile, always ensure it is active
    for a_sk in assigned_skills:
        if "bewerbung" in a_sk.lower() and "bewerbungs-protokoll" not in detected_new:
            detected_new.append("bewerbungs-protokoll")

    # Add detected skills to session
    for s_id in detected_new:
        clean_s = s_id.replace("skill-", "")
        add_session_active_skill(session_id, clean_s)
        if clean_s not in freshly_loaded:
            freshly_loaded.append(clean_s)
        for comp in COMPANIONS.get(clean_s, []):
            add_session_active_skill(session_id, comp)
            if comp not in freshly_loaded:
                freshly_loaded.append(comp)
                
    all_active = get_session_active_skills(session_id)
    
    # Build prompt blocks
    blocks = []
    
    # 1. Assigned skills manifest (shows the agent its official toolkit from the Kader)
    if assigned_skills:
        manifest_lines = [f"- `{s}`" for s in assigned_skills]
        blocks.append(
            "### DEIN ZUGEWIESENES FACH-SKILLSET (OFFIZIELLE KADER-FÄHIGKEITEN) ###\n"
            f"Du wurdest im Agenten-Kader mit {len(assigned_skills)} spezialisierten Fach-Fähigkeiten ausgestattet:\n"
            + "\n".join(manifest_lines) + "\n"
            "Agiere stets gemäß den Best Practices und Standards dieser Fach-Skills!"
        )
        
    # 2. Fully loaded active skills (full text of SKILL.md)
    loaded_skills_content = []
    for s_id in all_active:
        res = load_skill_text(s_id, find_skill_file_fn)
        if res:
            name, content = res
            loaded_skills_content.append(f"### SKILL-VOLLTEXT: {name} ###\n{content.strip()}\n")
            
    if loaded_skills_content:
        blocks.append(
            "================================================================================\n"
            "⚡ AKTIV IM ARBEITSSPEICHER GELADENE SKILLS (SINGLE SOURCE OF TRUTH)\n"
            "================================================================================\n"
            + "\n--------------------------------------------------------------------------------\n".join(loaded_skills_content)
            + "\n================================================================================\n"
        )
    # 3. Obsidian Bewerbungs-Datenbank (Direkt-Kontext bei Bewerbungs-Aufgaben)
    if any("bewerbung" in str(s).lower() for s in all_active) or "bewerbung" in user_msg.lower():
        obsidian_docs = []
        doc_paths = [
            "/opt/data/obsidian/Bewerbung/Vorlagen/Bewerbungsprotokoll.md",
            "/mnt/raid/Mein Obsidian/Bewerbung\\Vorlagen\\Bewerbungsprotokoll.md",
            "/opt/data/obsidian/Bewerbung/Vorlagen/Operator-One-Pager-Final.md",
            "/mnt/raid/Mein Obsidian/Bewerbung\\Vorlagen\\Operator-One-Pager-Final.md"
        ]
        for dp in doc_paths:
            if os.path.exists(dp) and os.path.isfile(dp):
                try:
                    with open(dp, "r", encoding="utf-8", errors="ignore") as f_dp:
                        bname = os.path.basename(dp)
                        # Begrenzen auf die wichtigsten Kerninhalte
                        txt = f_dp.read(15000).strip()
                        if txt and not any(bname in d for d in obsidian_docs):
                            obsidian_docs.append(f"#### OBSIDIAN DOKUMENT: {bname} ####\n{txt}\n")
                except Exception:
                    pass
        if obsidian_docs:
            blocks.append(
                "================================================================================\n"
                "📂 OBSIDIAN VAULT: BEWERBUNGS-UNTERLAGEN & HISTORIE (Michael Keller)\n"
                "================================================================================\n"
                + "\n--------------------------------------------------------------------------------\n".join(obsidian_docs)
                + "\n================================================================================\n"
            )

    if not blocks:
        return (None, freshly_loaded, None)
        
    final_prompt_block = "\n\n".join(blocks)
    return (final_prompt_block, freshly_loaded, None)
