#!/usr/bin/env python3
"""
Trigger AI Boardroom Debate Tool for Archon OS / Hermes Agents.
Enables agents (Robert, Micha, Default, etc.) to trigger and orchestrate
multi-agent debates programmatically with dynamic framework and model selection.
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error

FRAMEWORK_DEFAULTS = {
    "Steffi Kieffer Boardroom": [
        {"role_name": "Skeptiker & Risikoprüfer", "profile_id": "liability_risk_analyst"},
        {"role_name": "Innovator & Stratege", "profile_id": "executive_decision_architect"},
        {"role_name": "Pragmatiker & Implementierer", "profile_id": "enterprise_solutions_architect"}
    ],
    "CLEAR-Model": [
        {"role_name": "Collaborative Alignment (Team)", "profile_id": "agile_scrum_master"},
        {"role_name": "Limited & Emotional Scope", "profile_id": "personal_life_strategist"},
        {"role_name": "Appreciable Milestones", "profile_id": "product_requirements_engineer"},
        {"role_name": "Refinable Delivery (Tech)", "profile_id": "senior_fullstack_engineer"}
    ],
    "Six Thinking Hats": [
        {"role_name": "Weißer Hut (Fakten & Daten)", "profile_id": "market_research_analyst"},
        {"role_name": "Roter Hut (Emotion & Intuition)", "profile_id": "personal_life_strategist"},
        {"role_name": "Schwarzer Hut (Kritik & Risiko)", "profile_id": "liability_risk_analyst"},
        {"role_name": "Gelber Hut (Optimismus & Chancen)", "profile_id": "executive_decision_architect"},
        {"role_name": "Grüner Hut (Kreativität)", "profile_id": "gtm_launch_strategist"},
        {"role_name": "Blauer Hut (Prozess & Synthese)", "profile_id": "enterprise_solutions_architect"}
    ],
    "Red-Teaming": [
        {"role_name": "Red Team Leader (Angreifer)", "profile_id": "liability_risk_analyst"},
        {"role_name": "Blue Team (Verteidiger)", "profile_id": "system_architect_orchestrator"},
        {"role_name": "White Team (Schiedsrichter)", "profile_id": "executive_decision_architect"}
    ]
}

MODEL_PRESETS = {
    "free": {
        "provider": "omniroute",
        "model": "auto/best-free",
        "chairman_model": "auto/best-free",
        "chairman_provider": "omniroute"
    },
    "cheap": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "chairman_model": "deepseek/deepseek-chat",
        "chairman_provider": "openrouter"
    },
    "balanced": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "chairman_model": "deepseek/deepseek-r1",
        "chairman_provider": "openrouter"
    },
    "premium": {
        "provider": "openrouter",
        "model": "anthropic/claude-3.7-sonnet",
        "chairman_model": "anthropic/claude-3.7-sonnet",
        "chairman_provider": "openrouter"
    }
}

def auto_detect_framework(task_text: str) -> str:
    t = task_text.lower()
    if any(k in t for k in ["sicherheit", "security", "gefahr", "risiko", "angriff", "pentest", "red team", "schwachstelle"]):
        return "Red-Teaming"
    if any(k in t for k in ["kreativ", "ideen", "brainstorm", "hüte", "perspektiven", "neue produkte"]):
        return "Six Thinking Hats"
    if any(k in t for k in ["sprint", "milestones", "team", "agil", "scope", "delivery"]):
        return "CLEAR-Model"
    return "Steffi Kieffer Boardroom"

def run_debate(task: str, framework: str = None, budget: str = "balanced", rounds: int = 2, chairman_id: str = "orchestrator", host: str = "http://127.0.0.1:8501"):
    if not framework:
        framework = auto_detect_framework(task)
    
    preset = MODEL_PRESETS.get(budget.lower(), MODEL_PRESETS["balanced"])
    
    # Pick slots based on framework
    chosen_slots_def = None
    for fw_key, slots in FRAMEWORK_DEFAULTS.items():
        if fw_key.lower() in framework.lower() or framework.lower() in fw_key.lower():
            chosen_slots_def = slots
            break
    if not chosen_slots_def:
        chosen_slots_def = FRAMEWORK_DEFAULTS["Steffi Kieffer Boardroom"]
    
    slots_payload = []
    for s in chosen_slots_def:
        slots_payload.append({
            "role_name": s["role_name"],
            "profile_id": s.get("profile_id") or s.get("default_profile") or "senior_coder",
            "provider": preset["provider"],
            "model_id": preset["model"]
        })
    
    payload = {
        "task": task,
        "rounds": rounds,
        "chairman_id": chairman_id,
        "chairman_provider": preset["chairman_provider"],
        "chairman_model": preset["chairman_model"],
        "framework": framework,
        "slots": slots_payload
    }
    
    url = f"{host}/api/boardroom/run"
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            res_text = resp.read().decode("utf-8")
            return json.loads(res_text)
    except urllib.error.URLError as e:
        # Fallback to local python dispatcher if web server not reached on localhost
        print(f"[Warning] HTTP call failed ({e}). Falling back to internal dispatcher...", file=sys.stderr)
        try:
            import asyncio
            from core.agent_core import core_dispatcher
            from main import _prepare_boardroom_agents, BoardroomRequest
            breq = BoardroomRequest(**payload)
            chair, all_agents = _prepare_boardroom_agents(breq)
            res = asyncio.run(core_dispatcher.run_boardroom_debate(
                task=task,
                max_rounds=rounds,
                chairman_id=chair["id"],
                active_agents=all_agents,
                framework=framework
            ))
            return res
        except Exception as inner_e:
            return {"status": "error", "message": f"Connection and fallback failed: {inner_e}"}

def main():
    parser = argparse.ArgumentParser(description="Trigger an autonomous AI Boardroom debate in Archon OS")
    parser.add_argument("--task", "-t", required=True, help="The debate question, goal, or strategic issue to discuss")
    parser.add_argument("--framework", "-f", default=None, help="Framework name (e.g. 'Steffi Kieffer Boardroom', 'Six Thinking Hats', 'CLEAR-Model', 'Red-Teaming')")
    parser.add_argument("--budget", "-b", choices=["free", "cheap", "balanced", "premium"], default="balanced", help="Budget tier for LLM model assignment")
    parser.add_argument("--rounds", "-r", type=int, default=2, help="Number of debate rounds (default: 2)")
    parser.add_argument("--chairman", "-c", default="orchestrator", help="Profile ID of chairman / moderator")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    
    args = parser.parse_args()
    
    result = run_debate(
        task=args.task,
        framework=args.framework,
        budget=args.budget,
        rounds=args.rounds,
        chairman_id=args.chairman
    )
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    
    if result.get("status") == "error":
        print(f"❌ Fehler bei der Boardroom-Debatte: {result.get('message')}")
        sys.exit(1)
        
    print("=" * 60)
    print("🏛️ AI BOARDROOM DEBATTE ABGESCHLOSSEN")
    print("=" * 60)
    print(f"📌 Fragestellung : {args.task}")
    print(f"⚙️ Framework    : {result.get('framework', args.framework)}")
    print(f"👑 Moderator     : {result.get('chairman', {}).get('name', args.chairman)}")
    print(f"🔄 Runden        : {args.rounds}")
    print("-" * 60)
    print("📝 SYNTHESE & BESCHLUSSEMPFEHLUNG:")
    print("-" * 60)
    print(result.get("synthesis", "Keine Synthese verfügbar."))
    print("=" * 60)
    if "vault_file" in result:
        print(f"💾 Protokoll im Vault: {result['vault_file']}")
    if "history_id" in result:
        print(f"🆔 Historie ID       : {result['history_id']}")

if __name__ == "__main__":
    main()
