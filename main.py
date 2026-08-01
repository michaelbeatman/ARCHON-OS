import os
import sys
import time
import json
import csv
import datetime
import asyncio
import socket
import re
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import core_dispatcher
import httpx

app = FastAPI(title="Agent OS Control Panel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKSPACE_DIR = "/app/agent_workspace" if os.path.exists("/app/agent_workspace") or os.path.exists("/.dockerenv") else "./agent_workspace"
MEMORY_DIR = "/app/data" if os.path.exists("/app/data") else "."
os.makedirs(os.path.join(WORKSPACE_DIR, "obsidian_vault"), exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_DIR, "sandbox"), exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

try:
    from core_skills_engine import CoreSkillsEngine
    skills_engine = CoreSkillsEngine(
        vault_dir=os.path.join(WORKSPACE_DIR, "obsidian_vault"),
        rag_db_dir=os.path.join(WORKSPACE_DIR, "chroma_db")
    )
except Exception as e:
    print(f"Failed to import core_skills_engine: {e}", file=sys.stderr)
    skills_engine = None

MEMORY_FILE = os.path.join(MEMORY_DIR, "agent_memory.json")
AGENTS_FILE = os.path.join(MEMORY_DIR, "agents.json")
ROLES_FILE = os.path.join(MEMORY_DIR, "roles.json")
KANBAN_FILE = os.path.join(WORKSPACE_DIR, "kanban_data.json")
SERVICES_FILE = os.path.join(MEMORY_DIR, "services.json")
THEME_FILE = os.path.join(MEMORY_DIR, "theme_custom.json")

# In-Memory Ticker
ticker_entries = []

def add_ticker(agent_name: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    ticker_entries.append(f"[{ts}] {agent_name}: {message}")
    if len(ticker_entries) > 20:
        ticker_entries.pop(0)

# =====================================================================
# PERSISTENZ-HELFER (Basic UI Configuration State)
# =====================================================================

DEFAULT_AGENTS = [
    {
        "id": "A-01",
        "name": "Deep Researcher",
        "model": "free-forever",
        "role": "Researcher",
        "prompt": "Du bist ein Deep-Research-Agent. Recherchiere Fakten und strukturiere sie.",
        "active": True
    }
]

# DEFAULT_ROLES: definiert weiter unten mit allen 24 Spezialrollen (Zeile ~525)

DEFAULT_SERVICES = [
    {
        "id": "omniroute",
        "name": "OmniRoute Gateway",
        "description": "Multi-LLM & Gateway Proxy Router",
        "active": True,
        "model": "free-forever",
        "role": "Orchestrator",
        "port": 20128
    },
    {
        "id": "hermes",
        "name": "Hermes Agent",
        "description": "Orchestration & Coordination Daemon",
        "active": True,
        "model": "claude-3-5-sonnet",
        "role": "Orchestrator",
        "port": 9119
    },
    {
        "id": "openclaw",
        "name": "OpenClaw Coder",
        "description": "Autonomous Codebase Engineering Agent",
        "active": False,
        "model": "gpt-4o",
        "role": "Coder",
        "port": 8080
    },
    {
        "id": "odysseus",
        "name": "Odysseus System",
        "description": "Under-the-Hood Agent System Driver",
        "active": False,
        "model": "gpt-4o-mini",
        "role": "System Operator",
        "port": 7000
    },
    {
        "id": "audio-processor",
        "name": "Audio Processor",
        "description": "Voice & Audio Intelligence Service",
        "active": False,
        "model": "free-forever",
        "role": "Researcher",
        "port": 8080
    },
    {
        "id": "minara-cli",
        "name": "Minara CLI Agent",
        "description": "Command Line Autonomous Agent",
        "active": False,
        "model": "free-forever",
        "role": "Coder",
        "port": 8080
    },
    {
        "id": "sillytavern",
        "name": "SillyTavern Frontend",
        "description": "LLM Character & Interface Server",
        "active": False,
        "model": "free-forever",
        "role": "Custom",
        "port": 8000
    }
]

def _load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def _save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

def load_agents() -> List[Dict]: return _load_json(AGENTS_FILE, DEFAULT_AGENTS)
def save_agents(agents: List[Dict]): _save_json(AGENTS_FILE, agents)

def load_roles() -> List[Dict]: return _load_json(ROLES_FILE, DEFAULT_ROLES)
def save_roles(roles: List[Dict]): _save_json(ROLES_FILE, roles)

COUPLED_AGENTS_FILE = os.path.join(WORKSPACE_DIR, "config", "coupled_agents.json")

def load_services() -> List[Dict]:
    if os.path.exists(COUPLED_AGENTS_FILE):
        return _load_json(COUPLED_AGENTS_FILE, DEFAULT_SERVICES)
    return _load_json(SERVICES_FILE, DEFAULT_SERVICES)

def save_services(services: List[Dict]):
    _save_json(SERVICES_FILE, services)
    os.makedirs(os.path.join(WORKSPACE_DIR, "config"), exist_ok=True)
    _save_json(COUPLED_AGENTS_FILE, services)

def load_memory() -> List[Dict]: return _load_json(MEMORY_FILE, [])
def save_memory(memory_data: List[Dict]): _save_json(MEMORY_FILE, memory_data)

# =====================================================================
# REST ENDPOINTS
# =====================================================================

@app.get("/api/settings")
def get_settings():
    s = _load_json(SETTINGS_FILE, {})
    gw_url = s.get("gateway_url") if isinstance(s, dict) else None
    if not gw_url:
        gw_url = "http://localhost:20128/v1"
    return {
        "gateway_url": gw_url,
        "workspace_dir": WORKSPACE_DIR
    }

@app.get("/api/ticker")
def get_ticker():
    return {"entries": ticker_entries}

@app.post("/api/ticker/clear")
def clear_ticker():
    global ticker_entries
    ticker_entries = []
    return {"status": "cleared"}

@app.get("/api/agents")
def api_get_agents(): return load_agents()

@app.post("/api/agents")
def api_save_agents(agents: List[Dict]):
    save_agents(agents)
    return {"status": "success"}

@app.get("/api/roles")
def api_get_roles(): return load_roles()

@app.post("/api/roles")
def api_save_roles(roles: List[Dict]):
    save_roles(roles)
    return {"status": "success"}

def get_docker_containers_from_socket() -> List[Dict]:
    """
    Liest ALLE echten Docker-Container direkt vom Docker-Daemon über /var/run/docker.sock aus.
    """
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect('/var/run/docker.sock')
        s.sendall(b'GET /containers/json?all=true HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
        
        response = b''
        while True:
            try:
                chunk = s.recv(16384)
                if not chunk: break
                response += chunk
            except socket.timeout:
                break
        s.close()
        
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) < 2:
            return load_services()
        
        body_raw = parts[1]
        json_start = body_raw.find(b'[')
        json_end = body_raw.rfind(b']')
        
        if json_start != -1 and json_end != -1:
            raw_json_slice = body_raw[json_start:json_end+1]
            clean_bytes = re.sub(rb'\r\n[0-9a-fA-F]+\r\n', b'', raw_json_slice)
            containers_data = json.loads(clean_bytes.decode('utf-8', errors='ignore'))
        else:
            return load_services()
        
        containers_list = []
        SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"]
        
        saved_configs = {}
        if os.path.exists(COUPLED_AGENTS_FILE):
            raw_saved = _load_json(COUPLED_AGENTS_FILE, [])
            if isinstance(raw_saved, list):
                for sc in raw_saved:
                    saved_configs[sc.get("id") or sc.get("container_name")] = sc
            elif isinstance(raw_saved, dict):
                saved_configs = raw_saved

        for c in containers_data:
            if not isinstance(c, dict): continue
            raw_names = c.get('Names') or []
            c_name = raw_names[0].lstrip('/') if (raw_names and len(raw_names) > 0) else c.get('Id', '')[:12]
            c_id = c_name
            
            if c_name.lower() in SYSTEM_INTERNAL_IDS:
                continue
                
            status_str = c.get('Status', '') or ''
            is_active = "Up" in status_str
            image_str = c.get('Image', '') or ''
            
            saved_cfg = saved_configs.get(c_name) or saved_configs.get(c_id) or {}
            if "active" in saved_cfg:
                is_active = bool(saved_cfg["active"])
            elif "coupled" in saved_cfg:
                is_active = bool(saved_cfg["coupled"])
            
            ports_list = c.get('Ports') or []
            port_num = 8080
            for p in ports_list:
                if isinstance(p, dict):
                    if 'PublicPort' in p:
                        port_num = p['PublicPort']
                        break
                    elif 'PrivatePort' in p:
                        port_num = p['PrivatePort']
                    
            display_name = c_name.replace('-', ' ').replace('_', ' ').title()
            
            default_role = saved_cfg.get("role") or ("Orchestrator & System-Architekt" if "hermes" in c_name.lower() else "Senior Coder / Software Engineer")
            default_model = saved_cfg.get("model") or "free-forever"
            
            containers_list.append({
                "id": c_id,
                "name": display_name,
                "container_name": c_name,
                "image": image_str,
                "description": f"Docker Container '{c_name}' | Image: {image_str.split(':')[0]} | Port: {port_num}",
                "status": status_str,
                "active": is_active,
                "coupled": is_active,
                "port": port_num,
                "model": default_model,
                "role": default_role
            })
            
        return containers_list if len(containers_list) > 0 else load_services()
    except Exception as e:
        print(f"Error querying docker socket: {e}")
        return load_services()

def post_docker_container_action(container_name: str, action: str = "start") -> dict:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect('/var/run/docker.sock')
        req = f'POST /containers/{container_name}/{action} HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n'.encode('utf-8')
        s.sendall(req)
        resp = s.recv(4096)
        s.close()
        return {"status": "success", "message": f"Container {container_name} {action}ed."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/services")
@app.get("/api/services")
def api_get_services(): 
    return get_docker_containers_from_socket()

@app.post("/api/docker/start")
def api_docker_start(payload: Dict):
    c_name = payload.get("container_name") or payload.get("id")
    if not c_name: return {"status": "error", "message": "Missing container_name"}
    return post_docker_container_action(c_name, "start")

@app.post("/api/docker/stop")
def api_docker_stop(payload: Dict):
    c_name = payload.get("container_name") or payload.get("id")
    if not c_name: return {"status": "error", "message": "Missing container_name"}
    return post_docker_container_action(c_name, "stop")

@app.post("/api/v1/services")
def api_save_services(services: List[Dict]):
    save_services(services)
    return {"status": "success"}

@app.get("/api/models")
async def api_get_models():
    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "hermes-3", "gemini-1.5-pro"]

# --- Run / Dispatcher ---
class RunRequest(BaseModel):
    prompt: str

async def fetch_agent_response_api(agent: Dict, user_prompt: str) -> Dict:
    agent_name = agent["name"]
    model_combo = agent.get("model", "free-forever")
    agent_id = agent["id"]
    agent_role = agent.get("role", "Custom")
    agent_prompt = agent.get("prompt", "")
    
    start_time = time.time()
    
    add_ticker(agent_name, f"Leite Anfrage an physischen Container '{agent_id}' weiter (Dispatcher)...")
    
    prompt_text = user_prompt
    if isinstance(user_prompt, list):
        prompt_text = "\n".join([f"{m.get('role', '')}: {m.get('content', '')}" for m in user_prompt])
        
    try:
        # Dispatch to container or OmniRoute Gateway
        res = await core_dispatcher.dispatch_to_external_agent(
            agent_id=agent_id, 
            agent_name=agent_name, 
            prompt=prompt_text,
            role=agent_role,
            system_prompt=agent_prompt,
            model=model_combo,
            timeout=30
        )
    except Exception as e:
        res = {"status": "error", "content": f"Dispatcher Fehler: {str(e)}"}
    
    duration = time.time() - start_time
    
    if res["status"] == "success":
        add_ticker(agent_name, f"Antwort erfolgreich erhalten in {duration:.2f}s")
        try:
            if skills_engine:
                note_title = f"run_{agent_id}_{int(start_time)}"
                note_content = (
                    f"# Agent Run Log - {agent_name}\n\n"
                    f"- **Agent ID**: {agent_id}\n"
                    f"- **Model**: {model_combo}\n"
                    f"- **Role**: {agent_role}\n"
                    f"- **Timestamp**: {datetime.datetime.now().isoformat()}\n"
                    f"- **Duration**: {duration:.2f}s\n\n"
                    f"## Prompt\n\n```\n{prompt_text}\n```\n\n"
                    f"## Response\n\n```\n{res.get('content', '')}\n```\n"
                )
                skills_engine.obsidian.write_obsidian_note(note_title, note_content, ["run", agent_id, agent_role])
        except Exception as obs_err:
            print(f"Failed to write note to Obsidian: {obs_err}", file=sys.stderr)
    else:
        add_ticker(agent_name, f"Fehler: {res['content']}")
        
    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": res["status"],
        "content": res["content"],
        "duration": f"{duration:.2f}s",
        "model": model_combo
    }

FRAMEWORKS_FILE = os.path.join(WORKSPACE_DIR, "frameworks.json")

def load_boardroom_frameworks():
    fw = _load_json(FRAMEWORKS_FILE, None)
    if fw:
        core_dispatcher.CATEGORIZED_FRAMEWORKS = fw
    else:
        _save_json(FRAMEWORKS_FILE, core_dispatcher.CATEGORIZED_FRAMEWORKS)
    return core_dispatcher.CATEGORIZED_FRAMEWORKS

@app.get("/api/boardroom/frameworks")
def api_get_boardroom_frameworks():
    return load_boardroom_frameworks()

@app.post("/api/boardroom/frameworks")
def api_save_boardroom_frameworks(frameworks: Dict = Body(...)):
    core_dispatcher.CATEGORIZED_FRAMEWORKS = frameworks
    _save_json(FRAMEWORKS_FILE, frameworks)
    return {"status": "success"}

@app.post("/api/boardroom/frameworks/reset")
def api_reset_boardroom_frameworks():
    if os.path.exists(FRAMEWORKS_FILE):
        try:
            os.remove(FRAMEWORKS_FILE)
        except Exception:
            pass
    core_dispatcher.CATEGORIZED_FRAMEWORKS = copy.deepcopy(core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS)
    _save_json(FRAMEWORKS_FILE, core_dispatcher.CATEGORIZED_FRAMEWORKS)
    return {"status": "success"}

class BoardroomRequest(BaseModel):
    task: str
    rounds: int = 3
    chairman_id: Optional[str] = None
    framework: str = "Steffi Kieffer Boardroom"

@app.post("/api/boardroom/run")
async def api_run_boardroom(req: BoardroomRequest):
    agents = load_agents()
    active_agents = [a for a in agents if a.get("active")]
    if not active_agents:
        raise HTTPException(status_code=400, detail="Keine aktiven Agenten für den AI Boardroom konfiguriert.")
    
    chairman_id = req.chairman_id or active_agents[0]["id"]
    add_ticker("AI Boardroom", f"Debatte gestartet: '{req.task[:40]}...' ({req.framework})")
    
    res = await core_dispatcher.run_boardroom_debate(
        task=req.task,
        max_rounds=req.rounds,
        chairman_id=chairman_id,
        active_agents=active_agents,
        framework=req.framework
    )
    
    # Speichere finales Protokoll im Obsidian Vault
    try:
        vault_dir = os.path.join(WORKSPACE_DIR, "obsidian_vault")
        os.makedirs(vault_dir, exist_ok=True)
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        vault_file = os.path.join(vault_dir, f"boardroom_debatte_{ts_str}.md")
        
        md_content = f"# AI Boardroom Debatte: {req.task}\n\n"
        md_content += f"**Datum:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        md_content += f"**Methodik-Framework:** {req.framework}\n"
        md_content += f"**Chairman:** {res.get('chairman', {}).get('name', 'Unbekannt')}\n"
        md_content += f"**Max Runden:** {req.rounds}\n\n"
        md_content += f"## Diskussionsprotokoll\n\n{res.get('transcript', '')}\n\n"
        md_content += f"## Finale Synthese\n\n{res.get('synthesis', '')}\n"
        
        with open(vault_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: boardroom_debatte_{ts_str}.md")
    except Exception as e:
        print(f"Error saving obsidian vault note: {e}")
        
    return res

@app.post("/api/run")
async def api_run_parallel(req: RunRequest):
    agents = load_agents()
    active_agents = [a for a in agents if a.get("active")]
    if not active_agents:
        raise HTTPException(status_code=400, detail="Keine aktiven Agenten konfiguriert.")
    
    add_ticker("System", f"Run gestartet für Befehl: '{req.prompt[:40]}'")
    tasks = [fetch_agent_response_api(agent, req.prompt) for agent in active_agents]
    results = await asyncio.gather(*tasks)
    
    memory = load_memory()
    memory.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": req.prompt,
        "responses": {
            res["agent_name"]: {
                "model": res["model"],
                "content": res["content"],
                "duration": res["duration"],
                "status": res["status"]
            }
            for res in results
        }
    })
    save_memory(memory)
    return results

@app.get("/api/theme")
def api_get_theme(): return _load_json(THEME_FILE, {})

@app.post("/api/theme")
def api_save_theme(theme_data: Dict = Body(...)):
    _save_json(THEME_FILE, theme_data)
    return {"status": "success"}

ROLES_FILE = os.path.join(WORKSPACE_DIR, "roles.json")
SERVICES_FILE = os.path.join(WORKSPACE_DIR, "services.json")

DEFAULT_ROLES = [
    # CATEGORY I: MANAGEMENT & ARCHITEKTUR (DIE STRATEGEN)
    {
        "id": "orchestrator",
        "category": "1. Management & Architektur",
        "name": "Orchestrator & System-Architekt",
        "prompt": "Du bist ein erfahrener Orchestrator & System-Architekt. Deine Aufgabe ist es, meisterhaft komplexe Problemstellungen zu analysieren, Aufgaben strukturiert auf Spezial-Agenten zu verteilen, Abhängigkeiten zu managen und Teilergebnisse zu einer schlüssigen Gesamtlösung zu synthetisieren."
    },
    {
        "id": "product_manager",
        "category": "1. Management & Architektur",
        "name": "Product Manager / Requirements Engineer",
        "prompt": "Du bist ein strikter Product Manager & Requirements Engineer. Du übersetzt vage Nutzerideen in glasklare, präzise technische User Stories, Akzeptanzkriterien und funktionale Spezifikationen (PRDs). Du verhinderst Scope Creep und forderst Messbarkeit in allen Anforderungen."
    },
    {
        "id": "scrum_master",
        "category": "1. Management & Architektur",
        "name": "Agile Scrum Master / Task Triage Manager",
        "prompt": "Du bist ein proaktiver Agile Scrum Master & Task Triage Manager. Du strukturierst Workflows in überschaubare Sprint-Tasks, identifizierst Blockaden, priorisierst das Backlog in der Kanban-Pipeline und verteilst Arbeitspakete effizient an ausführende Worker-Agenten."
    },
    {
        "id": "enterprise_architect",
        "category": "1. Management & Architektur",
        "name": "Enterprise Architect",
        "prompt": "Du bist ein pragmatischer Enterprise Architect. Du bewertest Systemarchitekturen auf langfristige Skalierbarkeit, Modulkopplung, Microservice-Muster und Technologie-Stacks. Du verhinderst technologische Sackgassen und achtest auf Zukunftsfähigkeit."
    },
    {
        "id": "technical_writer",
        "category": "1. Management & Architektur",
        "name": "Technical Writer & Documentation Specialist",
        "prompt": "Du bist ein präziser Technical Writer & Dokumentations-Spezialist. Du wandelst komplexen Code und Architekturentscheidungen in saubere, übersichtliche Markdown-Dokumentationen, API-Guides, READMEs und strukturierte Obsidian-Vault-Notizen um."
    },
    {
        "id": "prompt_engineer",
        "category": "1. Management & Architektur",
        "name": "Prompt & AI Systems Engineer",
        "prompt": "Du bist ein Prompt & AI Systems Engineer. Du analysierst und optimierst System-Prompts, Instruction Tuning, Context-Window-Nutzung und Output-Parsing (z.B. JSON/XML-Garantien) für maximale Genauigkeit der ausführenden LLM-Agenten."
    },

    # CATEGORY II: SOFTWARE DEVELOPMENT & ENGINEERING (DIE BUILDER)
    {
        "id": "senior_coder",
        "category": "2. Software Development & Engineering",
        "name": "Senior Coder / Software Engineer",
        "prompt": "Du bist ein extrem kompetenter Senior Software Engineer. Du schreibst sauberen, modularen, objektorientierten und produktionsreifen Code (Python, TypeScript, Go). Du folgst strikt Best Practices (DRY, SOLID) und lieferst fehlerfreie Implementierungen."
    },
    {
        "id": "frontend_architect",
        "category": "2. Software Development & Engineering",
        "name": "Frontend & UI/UX Architect",
        "prompt": "Du bist ein visuell denkender Frontend & UI/UX Architect. Du entwirfst moderne, performante und ergonomische Benutzeroberflächen (Streamlit, React, CSS3, Tailwind). Du achtest penibel auf visuelle Hierarchien, responsive Grids und reibungslose User-Flows."
    },
    {
        "id": "backend_db_designer",
        "category": "2. Software Development & Engineering",
        "name": "Backend & Database Designer",
        "prompt": "Du bist ein hochspezialisierter Backend & Database Designer. Du entwickelst robuste API-Schnittstellen (REST, GraphQL, gRPC), optimierst SQL/NoSQL-Datenbankschemas, indizierst Tabellen und verhinderst Bottlenecks bei Abfragen."
    },
    {
        "id": "clean_code_expert",
        "category": "2. Software Development & Engineering",
        "name": "Refactoring & Clean Code Expert",
        "prompt": "Du bist ein kompromissloser Refactoring & Clean Code Expert. Du durchleuchtest bestehenden Code auf Code Smells, Redundanzen, hohe zyklomatische Komplexität und schlechte Benennungen, um die Wartbarkeit drastisch zu erhöhen."
    },
    {
        "id": "devops_container",
        "category": "2. Software Development & Engineering",
        "name": "DevOps & Container Specialist",
        "prompt": "Du bist ein erfahrener DevOps & Container Specialist. Du erstellst gehärtete Dockerfiles, Docker-Compose-Setups, Netzwerkkonfigurationen und CI/CD-Pipelines für eine nahtlose, isolierte und ausfallsichere Container-Laufzeitumgebung."
    },
    {
        "id": "qa_test_engineer",
        "category": "2. Software Development & Engineering",
        "name": "QA & Automated Testing Engineer",
        "prompt": "Du bist ein penibler QA & Automated Testing Engineer. Du entwirfst umfassende Unit-Tests, Integrationstests und E2E-Testsuites (PyTest, Jest). Du suchst gezielt nach Edge Cases, um Fehler vor dem Deployment abzufangen."
    },

    # CATEGORY III: SECURITY, DATA & AUDIT (DIE KONTROLLEURE)
    {
        "id": "security_auditor",
        "category": "3. Security, Data & Audit",
        "name": "Security Auditor / DevSecOps",
        "prompt": "Du bist ein akribischer Security Auditor & DevSecOps. Du analysierst Code und Systeme auf Sicherheitslücken (OWASP Top 10, Injection Risks, Secret Leaks, Insecure Deserialization) und verlangst harte Schutzmaßnahmen und Sanitization."
    },
    {
        "id": "gdpr_compliance",
        "category": "3. Security, Data & Audit",
        "name": "Data Protection & Compliance Officer (DSGVO)",
        "prompt": "Du bist ein Data Protection & Compliance Officer. Du stellst sicher, dass Systeme, Logs und Speichermethoden vollumfänglich DSGVO-konform sind, keine personenbezogenen Daten (PII) unverschlüsselt verarbeiten und Datenschutzprinzipien wahren."
    },
    {
        "id": "performance_auditor",
        "category": "3. Security, Data & Audit",
        "name": "Performance & Benchmarking Auditor",
        "prompt": "Du bist ein analytischer Performance & Benchmarking Auditor. Du misst Ausführungszeiten, Token-Effizienz, Memory Leaks und CPU-Last. Du identifizierst Ineffizienzen und machst konkrete Vorschläge zur Ressourcenminimierung."
    },
    {
        "id": "fact_checker",
        "category": "3. Security, Data & Audit",
        "name": "Fact-Checker & Logic Validator",
        "prompt": "Du bist ein unbestechlicher Fact-Checker & Logic Validator. Du prüfst Generierungen und Behauptungen anderer Agenten auf Halluzinationen, mathematische Fehler, logische Fehlschlüsse und verifizierst Quellen auf absolute Richtigkeit."
    },
    {
        "id": "dependency_auditor",
        "category": "3. Security, Data & Audit",
        "name": "Dependency & Supply Chain Auditor",
        "prompt": "Du bist ein wachsamer Dependency & Supply Chain Auditor. Du prüfst externe Bibliotheken (pip, npm), Lizenzen (MIT, GPL, Apache) und Paketabhängigkeiten auf Sicherheitsrisiken, veraltete Versionen und Deprecations."
    },
    {
        "id": "devils_advocate",
        "category": "3. Security, Data & Audit",
        "name": "Skeptic / Devil's Advocate",
        "prompt": "Du bist der kritische Skeptic & Devil's Advocate im Boardroom. Deine Aufgabe ist es, getroffene Entscheidungen, Pläne und Code-Entwürfe konstruktiv, aber schonungslos zu hinterfragen, um verdeckte Risiken und Denkfehler aufzudecken."
    },

    # CATEGORY IV: BUSINESS, RESEARCH & MARKETING (DIE ANALYSTEN)
    {
        "id": "researcher",
        "category": "4. Business, Research & Marketing",
        "name": "Researcher & Data Analyst",
        "prompt": "Du bist ein tiefgründiger Researcher & Data Analyst. Du durchsuchst das Web, Datenbanken und Fachliteratur, filterst Rauschen von Signalen und erstellst fundierte, evidenzbasierte Analysen und Zusammenfassungen."
    },
    {
        "id": "market_intelligence",
        "category": "4. Business, Research & Marketing",
        "name": "Market & Competitor Intelligence Analyst",
        "prompt": "Du bist ein strategischer Market & Competitor Intelligence Analyst. Du analysierst Marktsegmente, Mitbewerber-Tools, Preismodelle und Feature-Gaps, um Wettbewerbsvorteile und Differenzierungsmerkmale herauszuarbeiten."
    },
    {
        "id": "seo_content",
        "category": "4. Business, Research & Marketing",
        "name": "SEO & Content Pipeline Specialist",
        "prompt": "Du bist ein datengetriebener SEO & Content Pipeline Specialist. Du recherchierst High-Intent-Keywords, erstellst strukturierte Content-Pipelines und entwirfst suchmaschinenoptimierte Artikel und Veröffentlichungsstrategien."
    },
    {
        "id": "outreach_automator",
        "category": "4. Business, Research & Marketing",
        "name": "Outreach & Lead Gen Automator",
        "prompt": "Du bist ein fokussierter Outreach & Lead Gen Automator. Du konzipierst automatisierte B2B-Ansprachen, LinkedIn-Sequenzen und E-Mail-Kampagnen, inklusive Lead-Validierung und Triage für den Vertrieb."
    },
    {
        "id": "financial_optimizer",
        "category": "4. Business, Research & Marketing",
        "name": "Financial & Cost Optimizer",
        "prompt": "Du bist ein kostenbewusster Financial & Cost Optimizer. Du überwachst Token-Verbräuche, verglichst API-Kosten vs. Open-Source-Modelle und optimierst die Betriebskosten der gesamten Agenten-Infrastruktur."
    },
    {
        "id": "growth_strategist",
        "category": "4. Business, Research & Marketing",
        "name": "Growth & UX Conversion Strategist",
        "prompt": "Du bist ein ergebnisorientierter Growth & UX Conversion Strategist. Du analysierst Funnels, Onboarding-Abläufe und A/B-Test-Szenarien, um Reibungspunkte abzubauen und die Nutzeraktivierung zu maximieren."
    }
]

SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

@app.post("/api/settings")
def api_save_settings(settings: Dict = Body(...)):
    _save_json(SETTINGS_FILE, settings)
    return {"status": "success"}

@app.get("/api/v1/models")
def api_get_models_v1():
    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-r1", "hermes-3", "llama-3.3-70b"]

@app.get("/api/vault/files")
def api_get_vault_files():
    vault_dir = os.path.join(WORKSPACE_DIR, "obsidian_vault")
    if not os.path.exists(vault_dir):
        return []
    files = []
    for f in os.listdir(vault_dir):
        if f.endswith(".md"):
            files.append({"name": f, "path": os.path.join(vault_dir, f)})
    return files

@app.get("/api/v1/telemetry/dashboard")
def api_telemetry_dashboard():
    return {
        "active_agents": len(load_agents()),
        "tasks_running": 0,
        "network_ops": 42,
        "avg_uptime": "99.9%"
    }

# Helper to read/write persistent agent settings in main.py
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "obsidian_vault", "agent_configs.json")

def load_agent_configs():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_agent_config(container_name, config):
    configs = load_agent_configs()
    configs[container_name] = config
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")

def decode_chunked(data: bytes) -> bytes:
    result = b''
    offset = 0
    while offset < len(data):
        line_end = data.find(b'\r\n', offset)
        if line_end == -1:
            break
        chunk_size_str = data[offset:line_end].strip()
        if not chunk_size_str:
            offset = line_end + 2
            continue
        try:
            chunk_size = int(chunk_size_str, 16)
        except ValueError:
            result += data[offset:]
            break
        if chunk_size == 0:
            break
        offset = line_end + 2
        result += data[offset:offset+chunk_size]
        offset += chunk_size + 2
    return result

def docker_socket_request(method: str, path: str, payload: dict = None) -> bytes:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect('/var/run/docker.sock')
        
        body = ""
        if payload is not None:
            body = json.dumps(payload)
            
        req = f'{method} {path} HTTP/1.1\r\nHost: localhost\r\n'
        if body:
            req += f'Content-Type: application/json\r\nContent-Length: {len(body.encode("utf-8"))}\r\n'
        req += 'Connection: close\r\n\r\n'
        
        if body:
            req += body
            
        s.sendall(req.encode('utf-8'))
        
        response = b''
        while True:
            try:
                chunk = s.recv(65536)
                if not chunk: break
                response += chunk
            except socket.timeout:
                break
        s.close()
        
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) < 2:
            return b''
            
        headers, body_raw = parts[0], parts[1]
        is_chunked = b'Transfer-Encoding: chunked' in headers or b'transfer-encoding: chunked' in headers
        if is_chunked:
            return decode_chunked(body_raw)
        return body_raw
    except Exception as e:
        print(f"Docker Socket Request Error: {e}")
        return b''

def parse_docker_stream(data: bytes) -> str:
    result = ""
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            result += data[offset:].decode('utf-8', errors='ignore')
            break
        import struct
        try:
            size = struct.unpack('>I', data[offset+4:offset+8])[0]
        except Exception:
            result += data[offset:].decode('utf-8', errors='ignore')
            break
        offset += 8
        payload = data[offset:offset+size]
        result += payload.decode('utf-8', errors='ignore')
        offset += size
    return result

def parse_docker_stream_bytes(data: bytes) -> bytes:
    result = b''
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            result += data[offset:]
            break
        import struct
        try:
            size = struct.unpack('>I', data[offset+4:offset+8])[0]
        except Exception:
            result += data[offset:]
            break
        offset += 8
        payload = data[offset:offset+size]
        result += payload
        offset += size
    return result

@app.get("/api/v1/container/settings")
def get_container_settings(container_name: str):
    configs = load_agent_configs()
    return configs.get(container_name, {})

@app.post("/api/v1/container/settings")
def save_container_settings(container_name: str, config: Dict = Body(...)):
    save_agent_config(container_name, config)
    return {"status": "success"}

@app.get("/api/v1/container/logs")
def get_container_logs_api(container_name: str, tail: int = 150):
    logs_raw = docker_socket_request("GET", f"/containers/{container_name}/logs?tail={tail}&stdout=true&stderr=true")
    if not logs_raw:
        return {"logs": ""}
    logs = parse_docker_stream(logs_raw)
    return {"logs": logs}

@app.get("/api/v1/container/metrics")
def get_container_metrics_api(container_name: str):
    stats_raw = docker_socket_request("GET", f"/containers/{container_name}/stats?stream=false")
    if not stats_raw:
        return {"status": "Stopped", "cpu": 0.0, "memory_mb": 0.0, "memory_pct": 0.0}
        
    try:
        stats = json.loads(stats_raw.decode('utf-8'))
        
        # Memory metrics
        mem_stats = stats.get("memory_stats", {})
        mem_usage = mem_stats.get("usage", 0)
        mem_limit = mem_stats.get("limit", 1)
        mem_mb = mem_usage / (1024 * 1024)
        mem_pct = (mem_usage / mem_limit) * 100.0 if mem_limit else 0.0
        
        # CPU metrics
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        
        cpu_usage = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        precpu_usage = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        
        system_cpu = cpu_stats.get("system_cpu_usage", 0)
        system_precpu = precpu_stats.get("system_cpu_usage", 0)
        
        online_cpus = cpu_stats.get("online_cpus", 1)
        
        cpu_percent = 0.0
        cpu_delta = cpu_usage - precpu_usage
        system_delta = system_cpu - system_precpu
        
        if system_delta > 0 and cpu_delta > 0:
            cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
            
        return {
            "status": "Running",
            "cpu": min(100.0 * online_cpus, cpu_percent),
            "memory_mb": mem_mb,
            "memory_pct": mem_pct
        }
    except Exception:
        return {"status": "Running", "cpu": 0.0, "memory_mb": 0.0, "memory_pct": 0.0}

@app.get("/api/v1/container/files")
def get_container_files_api(container_name: str):
    inspect_raw = docker_socket_request("GET", f"/containers/{container_name}/json")
    if not inspect_raw:
        return {"files": []}
    
    try:
        inspect_data = json.loads(inspect_raw.decode('utf-8'))
        working_dir = inspect_data.get("Config", {}).get("WorkingDir", "") or "/app"
    except Exception:
        working_dir = "/app"
        
    exec_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["find", ".", "-maxdepth", "3", "-type", "f"],
        "WorkingDir": working_dir
    }
    create_raw = docker_socket_request("POST", f"/containers/{container_name}/exec", exec_payload)
    if not create_raw:
        return {"files": []}
        
    try:
        exec_id = json.loads(create_raw.decode('utf-8'))["Id"]
    except Exception:
        return {"files": []}
        
    start_payload = {"Detach": False, "Tty": False}
    start_raw = docker_socket_request("POST", f"/exec/{exec_id}/start", start_payload)
    
    output = parse_docker_stream(start_raw)
    
    files = []
    lines = output.strip().split('\n')
    exclude_patterns = [".git/", "__pycache__/", ".venv/", "node_modules/", ".pytest_cache/"]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("./"):
            line = line[2:]
        if any(pat in line for pat in exclude_patterns):
            continue
        files.append(line)
        
    return {"files": sorted(files)}

@app.get("/api/v1/container/file/content")
def get_container_file_content(container_name: str, filepath: str):
    inspect_raw = docker_socket_request("GET", f"/containers/{container_name}/json")
    if not inspect_raw:
        raise HTTPException(status_code=404, detail="Container not found")
    
    try:
        inspect_data = json.loads(inspect_raw.decode('utf-8'))
        working_dir = inspect_data.get("Config", {}).get("WorkingDir", "") or "/app"
    except Exception:
        working_dir = "/app"
        
    exec_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["cat", filepath],
        "WorkingDir": working_dir
    }
    create_raw = docker_socket_request("POST", f"/containers/{container_name}/exec", exec_payload)
    if not create_raw:
        raise HTTPException(status_code=500, detail="Failed to create exec instance")
        
    try:
        exec_id = json.loads(create_raw.decode('utf-8'))["Id"]
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse exec ID")
        
    start_payload = {"Detach": False, "Tty": False}
    start_raw = docker_socket_request("POST", f"/exec/{exec_id}/start", start_payload)
    
    file_bytes = parse_docker_stream_bytes(start_raw)
    
    ext = os.path.splitext(filepath)[1].lower()
    is_binary = ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".zip", ".tar", ".gz"]
    
    if is_binary:
        import base64
        encoded = base64.b64encode(file_bytes).decode('utf-8')
        return {"content": encoded, "binary": True}
    else:
        return {"content": file_bytes.decode('utf-8', errors='ignore'), "binary": False}

class ContainerExecRequest(BaseModel):
    container_name: str
    command: str

@app.post("/api/v1/container/exec")
def exec_container_command_api(req: ContainerExecRequest):
    inspect_raw = docker_socket_request("GET", f"/containers/{req.container_name}/json")
    if not inspect_raw:
        raise HTTPException(status_code=404, detail="Container not found")
    
    try:
        inspect_data = json.loads(inspect_raw.decode('utf-8'))
        working_dir = inspect_data.get("Config", {}).get("WorkingDir", "") or "/app"
    except Exception:
        working_dir = "/app"
        
    exec_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["sh", "-c", req.command],
        "WorkingDir": working_dir
    }
    create_raw = docker_socket_request("POST", f"/containers/{req.container_name}/exec", exec_payload)
    if not create_raw:
        raise HTTPException(status_code=500, detail="Failed to create exec instance")
        
    try:
        exec_id = json.loads(create_raw.decode('utf-8'))["Id"]
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse exec ID")
        
    start_payload = {"Detach": False, "Tty": False}
    start_raw = docker_socket_request("POST", f"/exec/{exec_id}/start", start_payload)
    
    output = parse_docker_stream(start_raw)
    return {
        "exit_code": 0,
        "stdout": output,
        "stderr": ""
    }

class ContainerActionRequest(BaseModel):
    container_name: str
    action: str

@app.post("/api/v1/container/action")
def run_container_action(req: ContainerActionRequest):
    if req.action not in ["start", "stop", "restart"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    res = post_docker_container_action(req.container_name, req.action)
    if res.get("status") == "success":
        add_ticker("SYSTEM", f"Container {req.container_name} {req.action}ed via dashboard.")
    return res

@app.post("/api/v1/container/inject_config")
async def inject_container_config(container_name: str, config: Dict = Body(...)):
    ports_map = {
        "odysseus": 7000,
        "hermes": 8787,
        "captain": 7001,
        "openhands": 3000
    }
    try:
        saved_configs = load_agent_configs()
        saved_cfg = saved_configs.get(container_name, {})
        custom_url = saved_cfg.get("web_ui_url", "")
        if custom_url:
            url = custom_url
        else:
            port = ports_map.get(container_name, 7000)
            url = f"http://{container_name}:{port}"
    except Exception:
        port = ports_map.get(container_name, 7000)
        url = f"http://{container_name}:{port}"

    if not url.startswith("http"):
        url = "http://" + url
        
    config_url = url.rstrip("/") + "/config"
    
    payload = {
        "config": {
            "api_base": "http://host.docker.internal:20128/v1",
            "api_key": "omniroute-local-key",
            "model": config.get("model", "free-forever"),
            "system_prompt": config.get("system_prompt", "")
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(config_url, json=payload)
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = resp.text
            return {
                "status": "success",
                "target_url": config_url,
                "response": resp_data
            }
    except Exception as e:
        return {
            "status": "error",
            "target_url": config_url,
            "message": f"Could not inject config to {config_url}: {e}"
        }

@app.get("/api/v1/skills/docker/inspect")
def api_skills_docker_inspect():
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.docker.inspect_system()

@app.get("/api/v1/skills/docker/logs")
def api_skills_docker_logs(container_name: str, tail: int = 100):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.docker.read_container_logs(container_name, tail)

@app.post("/api/v1/skills/docker/restart")
def api_skills_docker_restart(container_name: str = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.docker.restart_service(container_name)

@app.post("/api/v1/skills/obsidian/write")
def api_skills_obsidian_write(title: str = Body(...), content: str = Body(...), tags: List[str] = Body(None)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.obsidian.write_obsidian_note(title, content, tags)

@app.get("/api/v1/skills/obsidian/search")
def api_skills_obsidian_search(query: str):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.obsidian.search_obsidian_notes(query)

@app.post("/api/v1/skills/obsidian/changelog")
def api_skills_obsidian_changelog(version: str = Body(...), changes: List[str] = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.obsidian.update_changelog(version, changes)

@app.get("/api/v1/skills/rag/query")
def api_skills_rag_query(prompt: str):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.rag.query_knowledge_base(prompt)

@app.post("/api/v1/skills/rag/store")
def api_skills_rag_store(event_data: Dict = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.rag.store_system_metric(event_data)

@app.post("/api/v1/skills/git/pytest")
def api_skills_git_pytest(test_path: str = Body("tests/")):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.testing.run_pytest(test_path)

@app.post("/api/v1/skills/git/commit")
def api_skills_git_commit(message: str = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.testing.git_safe_commit(message)

@app.post("/api/v1/skills/mcp/connect")
def api_skills_mcp_connect(server_script_or_url: str = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.mcp.connect_mcp_server(server_script_or_url)

@app.post("/api/v1/skills/mcp/execute")
def api_skills_mcp_execute(tool_name: str = Body(...), arguments: Dict = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return skills_engine.mcp.execute_mcp_tool(tool_name, arguments)



@app.get("/")
def get_index():
    return FileResponse(os.path.join("static", "index.html"))

app.mount("/static", StaticFiles(directory="static"), name="static")
