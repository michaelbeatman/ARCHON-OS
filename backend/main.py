import os
import json
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Archon OS Backend Engine",
    description="FastAPI Backend serving Agents, Teams & AutoGen Studio JSON Schema",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
AGENTS_PATH = os.path.join(CONFIG_DIR, "agents.json")
ROOT_AGENTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.json")
TEAMS_PATH = os.path.join(CONFIG_DIR, "teams.json")

class TeamCreateSchema(BaseModel):
    id: Optional[str] = None
    name: str
    mode: Optional[str] = "Round-Robin"
    mission: Optional[str] = ""
    leader: Optional[str] = "hermes"
    members: List[str] = []
    selected_model: Optional[str] = "OmniRoute Free"
    tools: Optional[List[str]] = ["FileSystem_MCP", "Calculator"]

def load_agents_data() -> List[Dict[str, Any]]:
    for path in [AGENTS_PATH, ROOT_AGENTS_PATH, "config/coupled_agents.json"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        res = []
                        for k, v in data.items():
                            if isinstance(v, dict):
                                res.append({
                                    "id": k,
                                    "name": k.replace("-", " ").title(),
                                    "role": v.get("role", "Spezialist"),
                                    "model": v.get("model", "free-forever")
                                })
                        if res:
                            return res
            except Exception as e:
                print(f"Error loading agents from {path}: {e}")
    return [
        {"id": "hermes", "name": "Hermes Orchestrator", "role": "Orchestrator & System-Architekt", "model": "free-forever"},
        {"id": "openhands", "name": "OpenHands Coder", "role": "Autonomer Software-Ingenieur", "model": "free-forever"},
        {"id": "gpt-researcher", "name": "GPT Researcher", "role": "Autonomer Tiefen-Rechercheur", "model": "free-forever"},
        {"id": "openclaw", "name": "OpenClaw", "role": "Messenger & E-Mail Bridge Agent", "model": "free-forever"}
    ]

def load_teams_data() -> List[Dict[str, Any]]:
    if os.path.exists(TEAMS_PATH):
        try:
            with open(TEAMS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get("teams", [])
        except Exception as e:
            print(f"Error loading teams: {e}")
    return [
        {
            "id": "roundrobin-team-alpha",
            "name": "RoundRobin Team Alpha",
            "mode": "Round-Robin",
            "mission": "Autonome Entwicklung & Recherche",
            "leader": "Hermes Orchestrator",
            "members": ["Hermes Orchestrator", "OpenHands Coder", "GPT Researcher"],
            "selected_model": "OmniRoute Free",
            "tools": ["FileSystem_MCP", "Calculator"]
        }
    ]

def save_teams_data(teams: List[Dict[str, Any]]):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TEAMS_PATH, "w", encoding="utf-8") as f:
        json.dump({"teams": teams}, f, indent=2, ensure_ascii=False)

# F-14: Die Kollisionen GET / und GET /api/agents sind entfernt — beide werden
# von der Haupt-App (main.py, Routen / und /api/agents) bedient. Dieser
# Standalone-Backend-Runner bedient nur noch /api/teams*, damit keine
# Pfad+Methode-Dublette mehr existiert (AST-Scan: "doppelte Pfad+Methode").
@app.get("/api/teams")
def get_teams():
    teams = load_teams_data()
    return {"status": "success", "count": len(teams), "teams": teams}

@app.post("/api/teams")
def create_team(team_in: TeamCreateSchema):
    teams = load_teams_data()
    team_id = team_in.id or team_in.name.lower().replace(" ", "-")
    
    new_team = {
        "id": team_id,
        "name": team_in.name,
        "mode": team_in.mode,
        "mission": team_in.mission,
        "leader": team_in.leader,
        "members": team_in.members,
        "selected_model": team_in.selected_model,
        "tools": team_in.tools
    }
    
    # Replace existing or append
    existing_idx = next((i for i, t in enumerate(teams) if t.get("id") == team_id), None)
    if existing_idx is not None:
        teams[existing_idx] = new_team
    else:
        teams.append(new_team)
        
    save_teams_data(teams)
    return {"status": "success", "team": new_team}

@app.get("/api/teams/{team_id}/json")
def get_team_autogen_json(team_id: str):
    teams = load_teams_data()
    team = next((t for t in teams if t.get("id") == team_id or t.get("name").lower() == team_id.lower()), None)
    
    if not team:
        # Fallback to alpha if not found
        team = teams[0] if teams else {
            "id": team_id,
            "name": "RoundRobin Team",
            "members": ["Hermes Orchestrator", "OpenHands Coder"],
            "selected_model": "omniroute-free",
            "tools": ["FileSystem_MCP", "Calculator"]
        }

    members = team.get("members", ["Hermes Orchestrator", "OpenHands Coder"])
    model_name = team.get("selected_model", "omniroute-free")
    tools = team.get("tools", ["FileSystem_MCP", "Calculator"])

    schema = {
        "provider": "autogen_agentchat.teams.RoundRobinGroupChat",
        "component_type": "team",
        "version": 1,
        "label": team.get("name", "RoundRobin Team"),
        "config": {
            "participants": [
                {
                    "provider": "autogen_agentchat.agents.AssistantAgent",
                    "label": member_name if isinstance(member_name, str) else member_name.get("name"),
                    "config": {
                        "name": (member_name if isinstance(member_name, str) else member_name.get("id", "agent")).lower().replace(" ", "-"),
                        "role": "Assistant Agent",
                        "model_client": {
                            "provider": "autogen_ext.models.openai.OpenAIChatCompletionClient",
                            "config": {
                                "model": model_name,
                                "base_url": "http://localhost:20128/v1"
                            }
                        },
                        "tools": tools
                    }
                } for member_name in members
            ],
            "termination_condition": {
                "provider": "autogen_agentchat.conditions.OrTerminationCondition",
                "conditions": [
                    {"type": "MaxMessageTermination", "max_messages": 10},
                    {"type": "TextMentionTermination", "text": "TERMINATE"}
                ]
            }
        }
    }
    
    return schema
