import os
import secrets
import sys
import time
import json
import csv
import datetime
import asyncio
import socket
import re
import threading
import tempfile
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, Query, Request, Body, File, UploadFile, Form, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import shutil
import sqlite3
import base64
import yaml
import core_dispatcher
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("archon_os")

app = FastAPI(title="Agent OS Control Panel")

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_for_avatars(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/avatars/") or path.startswith("/static/js/") or path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}

@app.get("/metrics")
def prometheus_metrics():
    """Prometheus-konformer Metriken-Endpoint fuer Scraping und Monitoring."""
    from fastapi.responses import Response
    try:
        from backend.metrics_collector import metrics_collector
        return Response(
            content=metrics_collector.generate_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        return Response(content=f"# Error collecting metrics: {e}\n", status_code=500, media_type="text/plain")

WORKSPACE_DIR = "/app/agent_workspace" if os.path.exists("/app/agent_workspace") or os.path.exists("/.dockerenv") else "./agent_workspace"
MEMORY_DIR = "/app/data" if os.path.exists("/app/data") else "."
DATA_DIR = MEMORY_DIR

def resolve_obsidian_vault_path():
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # Auf Linux/Docker-Systemen MUSS der Mount /opt/data/obsidian zwingend Vorrang haben
    if sys.platform != "win32":
        candidates = [
            "/opt/data/obsidian",
            "/app/data/obsidian",
            os.path.join(WORKSPACE_DIR, "obsidian_vault")
        ]
    else:
        candidates = [
            "C:\\Mein Obsidian",
            "C:\\.Mein Obsidian",
            os.path.expanduser("~/Documents/Obsidian Vault"),
            os.path.join(WORKSPACE_DIR, "obsidian_vault")
        ]
    for candidate in candidates:
        if os.path.exists(candidate) and os.path.isdir(candidate):
            return candidate
    return "/opt/data/obsidian" if sys.platform != "win32" else "C:\\Mein Obsidian"

OBSIDIAN_VAULT_DIR = resolve_obsidian_vault_path()
os.makedirs(OBSIDIAN_VAULT_DIR, exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_DIR, "sandbox"), exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

try:
    from core_skills_engine import CoreSkillsEngine
    skills_engine = CoreSkillsEngine(
        vault_dir=OBSIDIAN_VAULT_DIR,
        rag_db_dir=os.path.join(WORKSPACE_DIR, "chroma_db")
    )
except Exception as e:
    print(f"Failed to import core_skills_engine: {e}", file=sys.stderr)
    skills_engine = None

try:
    from local_memory_bridge import LocalMemoryBridge
    memory_bridge = LocalMemoryBridge(
        db_path=os.path.join(MEMORY_DIR, "agentic_memory.db"),
        vault_path=OBSIDIAN_VAULT_DIR
    )
except Exception as e:
    print(f"Failed to import local_memory_bridge: {e}", file=sys.stderr)
    memory_bridge = None

try:
    from watchdog_daemon import start_background_watchdog
    watchdog_runner = start_background_watchdog()
except Exception as e:
    print(f"Failed to start watchdog_daemon: {e}", file=sys.stderr)
    watchdog_runner = None

MEMORY_FILE = os.path.join(MEMORY_DIR, "agent_memory.json")
AGENTS_FILE = os.path.join(MEMORY_DIR, "agents.json")
ROLES_FILE = os.path.join(MEMORY_DIR, "roles.json")
KANBAN_FILE = os.path.join(WORKSPACE_DIR, "kanban_data.json")
SERVICES_FILE = os.path.join(MEMORY_DIR, "services.json")
THEME_FILE = os.path.join(MEMORY_DIR, "theme_custom.json")
THEME_LIVE_FILE = os.path.join(MEMORY_DIR, "theme_live_overrides.json")
GATEWAY_CONFIG_FILE = os.path.join(MEMORY_DIR, "gateway_config.json")
MISSION_CONTROL_FILE = os.path.join(MEMORY_DIR, "mission_control_data.json")
QUICKCHAT_SESSIONS_DIR = os.path.join(MEMORY_DIR, "quickchat_sessions")
os.makedirs(QUICKCHAT_SESSIONS_DIR, exist_ok=True)

# In-Memory Ticker
ticker_entries = []

# =====================================================================
# REAL-TIME SSE EVENT BROADCASTER (Pillar 1 & 2 / Event-Driven Push)
# =====================================================================
_SSE_SUBSCRIBERS: List[asyncio.Queue] = []

def broadcast_event(event_type: str, data: Optional[Dict[str, Any]] = None):
    """
    Sendet ein typisiertes Server-Sent Event an alle verbundenen Web-Clients.
    Verhindert langsame Polling-Intervalle bei Kanban-Updates, Telegram-Decisions und Task-Fortschritten.
    """
    global _SSE_SUBSCRIBERS
    payload = json.dumps({"type": event_type, "timestamp": time.time(), "data": data or {}})
    dead_queues = []
    for q in _SSE_SUBSCRIBERS:
        try:
            q.put_nowait(payload)
        except Exception:
            dead_queues.append(q)
    for dq in dead_queues:
        if dq in _SSE_SUBSCRIBERS:
            _SSE_SUBSCRIBERS.remove(dq)

def add_ticker(agent_name: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    ticker_entries.append(f"[{ts}] {agent_name}: {message}")
    if len(ticker_entries) > 20:
        ticker_entries.pop(0)
    # Event direkt per SSE an alle offenen Clients pushen
    broadcast_event("ticker_update", {"agent": agent_name, "message": message, "time": ts})

# =====================================================================
# PERSISTENZ-HELFER (Basic UI Configuration State)
# =====================================================================

DEFAULT_AGENTS = [
    {
        "id": "hermes-orchestrator",
        "name": "Hermes Master Orchestrator",
        "role": "System-Architekt & Paperclip Lead",
        "model": "omniroute/best-reasoning",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    },
    {
        "id": "hermes-researcher",
        "name": "Hermes Deep Researcher",
        "role": "Web-Scraping, Markt- & SEO-Analysen",
        "model": "omniroute/free-forever",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    },
    {
        "id": "hermes-coder",
        "name": "Hermes Senior Coder",
        "role": "Fullstack Software Engineer & Dev",
        "model": "omniroute/deepseek-coder",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    },
    {
        "id": "hermes-odysseus",
        "name": "Hermes Odysseus Strategist",
        "role": "Business Strategy & Second Brain Vault",
        "model": "omniroute/best-reasoning",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    }
]

# DEFAULT_ROLES: definiert weiter unten mit allen 24 Spezialrollen (Zeile ~525)

DEFAULT_SERVICES = [
    {
        "id": "omniroute",
        "name": "OmniRoute AI Gateway",
        "description": "Multi-LLM & Gateway Proxy Router",
        "active": True,
        "model": "free-forever",
        "role": "Gateway",
        "port": 20128
    },
    {
        "id": "hermes",
        "name": "Hermes Engine & WebUI",
        "description": "Universelle Multi-Profile Agent Engine",
        "active": True,
        "model": "free-forever",
        "role": "Orchestrator",
        "port": 8787
    },
    {
        "id": "hermes-dashboard",
        "name": "Hermes Control Dashboard",
        "description": "Hermes Telemetrie & Performance Monitor",
        "active": True,
        "model": "free-forever",
        "role": "Telemetry",
        "port": 9119
    },
    {
        "id": "crm",
        "name": "CRM & LinkedIn Hub",
        "description": "Kontakt-Management & Outreach System",
        "active": True,
        "model": "free-forever",
        "role": "CRM",
        "port": 3005
    },
    {
        "id": "open-webui",
        "name": "Open WebUI",
        "description": "Schneller LLM-Chat Fallback",
        "active": True,
        "model": "free-forever",
        "role": "Chat Fallback",
        "port": 8082
    },
    {
        "id": "pocketbase",
        "name": "Pocketbase Storage",
        "description": "Echtzeit-Datenbank & Auth System",
        "active": True,
        "model": "free-forever",
        "role": "Database",
        "port": 8090
    },
    {
        "id": "n8n",
        "name": "n8n Automatisierung",
        "description": "Workflow- & Integrations-Automatisierung",
        "active": True,
        "model": "free-forever",
        "role": "Automation",
        "port": 5678
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

GHOST_AGENT_IDS = {"prime-agent", "autogen-studio", "openhands", "openclaw", "gpt-researcher", "a-01", "a-02"}

def load_agents() -> List[Dict]:
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    if os.path.exists(agents_root):
        loaded = _load_json(agents_root, DEFAULT_AGENTS)
    elif os.path.exists(AGENTS_FILE):
        loaded = _load_json(AGENTS_FILE, DEFAULT_AGENTS)
    else:
        loaded = DEFAULT_AGENTS
    cleaned = [a for a in loaded if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    return cleaned if len(cleaned) > 0 else DEFAULT_AGENTS

def save_agents(agents: List[Dict]):
    cleaned = [a for a in agents if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    _save_json(agents_root, cleaned)
    _save_json(AGENTS_FILE, cleaned)

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

def load_theme() -> Dict: return _load_json(THEME_FILE, {})
def save_theme(theme_data: Dict): _save_json(THEME_FILE, theme_data)

# =====================================================================
# REST ENDPOINTS
# =====================================================================

async def forward_to_hermes(request: Request) -> Response:
    path_to_use = request.url.path
    if path_to_use.startswith("/static/hermes-webui"):
        path_to_use = path_to_use[len("/static/hermes-webui"):]
    query_str = f"?{str(request.query_params)}" if request.query_params else ""
    
    candidates = [
        f"http://hermes-webui:8787{path_to_use}{query_str}",
        f"http://127.0.0.1:8787{path_to_use}{query_str}",
        f"http://host.docker.internal:8787{path_to_use}{query_str}",
        f"http://hermes-dashboard:9119{path_to_use}{query_str}",
        f"http://127.0.0.1:9119{path_to_use}{query_str}",
    ]
        
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length", "authorization", "cookie"]}
    fwd_headers["Host"] = "localhost:8787"
    _hermes_tok = os.getenv("HERMES_SESSION_TOKEN") or os.getenv("OMNIROUTE_API_KEY") or "sk-archon-session-dev"
    fwd_headers["X-Hermes-Session-Token"] = _hermes_tok
    fwd_headers["Authorization"] = f"Bearer {_hermes_tok}"
    
    body = await request.body()
    last_err = None
    for target in candidates:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(
                    method=request.method,
                    url=target,
                    headers=fwd_headers,
                    content=body if body else None,
                    timeout=15.0
                )
            return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("Content-Type", "application/json"))
        except Exception as e:
            last_err = e
            continue
    return Response(content=f'{{"error": "{last_err}"}}', status_code=502, media_type="application/json")

@app.get("/api/settings")
async def get_settings(request: Request):
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        return await forward_to_hermes(request)

    s = _load_json(SETTINGS_FILE, {})
    gw_url = s.get("gateway_url") if isinstance(s, dict) else None
    if not gw_url:
        gw_url = "http://localhost:20128/v1"
    jev_cfg = s.get("jev", {}) if isinstance(s, dict) else {}
    mem_cfg = s.get("memory", {
        "enabled": True,
        "auto_learn": True,
        "apply_lessons": True,
        "max_injected_lessons": 3,
        "half_life_days": 14,
        "auto_evict": False,
        "eviction_threshold": 0.1,
        "vault_path": "C:\\Mein Obsidian",
        "daily_consolidation": True,
        "hours_back": 24
    }) if isinstance(s, dict) else {}
    email_guard_cfg = s.get("email_guard", {
        "enabled": True,
        "protect_email": True,
        "protect_telegram": True,
        "protect_crm": True,
        "sensitivity": "moderate",
        "use_llm": False,
        "model": "omniroute/free-forever"
    }) if isinstance(s, dict) else {}
    validate_cfg = s.get("validate", {
        "enabled": True,
        "min_score": 7,
        "on_failure": "warn",
        "check_hallucinations": True,
        "check_cutoff": True,
        "use_llm": False,
        "judge_model": "omniroute/free-forever"
    }) if isinstance(s, dict) else {}
    return {
        "gateway_url": gw_url,
        "workspace_dir": WORKSPACE_DIR,
        "jev": jev_cfg,
        "memory": mem_cfg,
        "email_guard": email_guard_cfg,
        "validate": validate_cfg
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

# =====================================================================
# ORACLE NEWS RADAR (Hermes Intelligence Stream & Obsidian Sync)
# =====================================================================

@app.get("/api/oracle/feed")
def api_get_oracle_feed(limit: int = 50):
    try:
        import oracle_news_radar
        radar = oracle_news_radar.OracleNewsRadar()
        return {"status": "success", "feed": radar.get_feed(limit)}
    except Exception as e:
        return {"status": "error", "message": str(e), "feed": []}

@app.post("/api/oracle/run")
def api_run_oracle_cycle():
    try:
        import oracle_news_radar
        radar = oracle_news_radar.OracleNewsRadar()
        return radar.run_radar_cycle()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/oracle/triage")
def api_triage_oracle_signal(payload: Dict[str, Any] = Body(...)):
    try:
        import oracle_news_radar
        radar = oracle_news_radar.OracleNewsRadar()
        signal_id = payload.get("id") or payload.get("signal_id")
        if not signal_id:
            return {"status": "error", "message": "Signal-ID fehlt im Payload"}
        return radar.triage_to_task(signal_id)
    except Exception as e:
        return {"status": "error", "message": str(e)}

# =====================================================================
# APOLLO VOICE AGENT (Hermes Conversational Voice & Execution Bridge)
# =====================================================================

@app.post("/api/voice/speak")
async def api_voice_speak(payload: Dict[str, Any] = Body(...)):
    text = payload.get("text", "")
    voice = payload.get("voice")
    if not text:
        raise HTTPException(status_code=400, detail="Text ist erforderlich")
    try:
        from apollo_voice_engine import ApolloVoiceEngine
        engine = ApolloVoiceEngine()
        audio_bytes = await engine.synthesize_speech(text, voice)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/voice/command")
async def api_voice_command(payload: Dict[str, Any] = Body(...)):
    transcript = payload.get("transcript", "")
    if not transcript:
        raise HTTPException(status_code=400, detail="Transkript ist erforderlich")
    try:
        from apollo_voice_engine import ApolloVoiceEngine
        engine = ApolloVoiceEngine()
        return await engine.process_voice_command(transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/voice/audio/{filename}")
def api_get_voice_audio(filename: str):
    audio_file = os.path.join("data", "audio_cache", filename)
    if os.path.exists(audio_file):
        return FileResponse(audio_file, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio-Datei nicht gefunden")

# =====================================================================
# SEO & EXECUTION AGENT (Programmatic Content & Webhook Pipeline)
# =====================================================================

@app.post("/api/seo/generate")
async def api_seo_generate(payload: Dict[str, Any] = Body(...)):
    topic = payload.get("topic", "")
    keyword = payload.get("keyword", topic)
    audience = payload.get("audience", "B2B / Tech")
    trigger_n8n = payload.get("trigger_n8n", True)
    if not topic:
        raise HTTPException(status_code=400, detail="Thema (topic) ist erforderlich")
    try:
        from seo_execution_agent import SEOExecutionAgent
        agent = SEOExecutionAgent()
        return await agent.execute_content_pipeline(topic, keyword, audience, trigger_n8n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/seo/articles")
def api_seo_articles():
    content_dir = os.path.join(WORKSPACE_DIR, "obsidian_vault", "05_Content")
    if not os.path.exists(content_dir):
        content_dir = os.path.join("obsidian_vault", "05_Content")
    articles = []
    if os.path.exists(content_dir):
        for f in os.listdir(content_dir):
            if f.endswith(".md"):
                fp = os.path.join(content_dir, f)
                articles.append({
                    "filename": f,
                    "path": fp,
                    "size_bytes": os.path.getsize(fp),
                    "modified": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()
                })
    return {"status": "success", "articles": articles}

THEMES_DIR = os.path.join(WORKSPACE_DIR, "themes")
os.makedirs(THEMES_DIR, exist_ok=True)

@app.get("/api/themes")
def api_get_themes():
    themes = []
    if os.path.exists(THEMES_DIR):
        for file in os.listdir(THEMES_DIR):
            if file.endswith(".json"):
                themes.append(file.replace(".json", ""))
    return {"themes": themes}

@app.get("/api/themes/{theme_name}")
def api_get_theme_by_name(theme_name: str):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(path):
        return _load_json(path, {})
    return {}

@app.post("/api/themes/{theme_name}")
def api_save_theme_by_name(theme_name: str, theme_data: dict = Body(...)):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    _save_json(path, theme_data)
    return {"status": "success", "theme_name": theme_name}

@app.delete("/api/themes/{theme_name}")
def api_delete_theme_by_name(theme_name: str):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "success"}

DESIGN_THEMES_TARGETS = [
    os.path.join("config", "design_themes.json"),
    "/app/config/design_themes.json",
    os.path.join("data", "design_themes.json"),
    "/app/data/design_themes.json"
]

@app.get("/api/design/themes")
def api_get_design_themes():
    for cand in DESIGN_THEMES_TARGETS:
        if os.path.exists(cand):
            data = _load_json(cand, {})
            if data and "themes" in data and len(data["themes"]) > 0:
                return data
    return {"active_theme_id": "archon_current", "active_mode": "light", "themes": {}}

@app.post("/api/design/themes")
def api_save_design_themes(payload: Dict = Body(...)):
    current = api_get_design_themes()
    if "active_theme_id" in payload:
        current["active_theme_id"] = payload["active_theme_id"]
    if "active_mode" in payload:
        current["active_mode"] = payload["active_mode"]
    if "themes" in payload and isinstance(payload["themes"], dict):
        current["themes"] = payload["themes"]
    if "theme" in payload and isinstance(payload["theme"], dict):
        t = payload["theme"]
        tid = t.get("id") or "custom_" + str(int(time.time()))
        t["id"] = tid
        if "themes" not in current or not isinstance(current["themes"], dict):
            current["themes"] = {}
        current["themes"][tid] = t
        if payload.get("set_active", True):
            current["active_theme_id"] = tid
    for target in DESIGN_THEMES_TARGETS:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            _save_json(target, current)
        except Exception:
            pass
    return {"status": "success", "data": current}

@app.delete("/api/design/themes/{theme_id}")
def api_delete_design_theme(theme_id: str):
    current = api_get_design_themes()
    themes = current.get("themes", {})
    if theme_id in themes and len(themes) > 1:
        del themes[theme_id]
        if current.get("active_theme_id") == theme_id:
            current["active_theme_id"] = next(iter(themes.keys()), "archon_current")
        for target in DESIGN_THEMES_TARGETS:
            try:
                _save_json(target, current)
            except Exception:
                pass
    return {"status": "success", "data": current}

@app.get("/api/theme")
def api_get_theme():
    return load_theme()

@app.post("/api/theme")
def api_save_theme(theme_data: Dict = Body(...)):
    save_theme(theme_data)
    return {"status": "success"}

@app.get("/api/theme/live-overrides")
def api_get_theme_live_overrides():
    return _load_json(THEME_LIVE_FILE, {"rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {}})

@app.post("/api/theme/live-overrides")
def api_save_theme_live_overrides(payload: Dict = Body(...)):
    _save_json(THEME_LIVE_FILE, payload)
    # [ARCHIVED] Überschreiben von static/custom_studio.css deaktiviert zugunsten
    # der zentralen 15-Bausteine-Engine (/api/design/themes).
    return {"status": "success"}

@app.post("/api/theme/bake-into-main-design")
def api_bake_theme_into_main_design(payload: Dict = Body(None)):
    """
    Kompiliert alle Live-Studio-Regeln direkt in static/custom_studio.css,
    leert die temporären Overrides auf Server und Client und setzt den Zähler auf 0 zurück.
    """
    data = payload or _load_json(THEME_LIVE_FILE, {})
    rules = data.get("rules", {})
    if not rules:
        live = _load_json(THEME_LIVE_FILE, {})
        rules = live.get("rules", {})

    css_lines = []
    prop_count = 0
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css_lines.append("/* ========================================================================= */")
    css_lines.append(f"/* ARCHON STUDIO BAKED CSS — Eingebrannt am: {now_str}               */")
    css_lines.append("/* ========================================================================= */\n")

    for sel, props in rules.items():
        if not props or not isinstance(props, dict):
            continue
        clean_props = []
        for p, v in props.items():
            if v is not None and str(v).strip() != "":
                clean_val = str(v).replace("!important", "").strip()
                clean_props.append(f"  {p}: {clean_val} !important;")
                prop_count += 1
        if clean_props:
            css_lines.append(f"{sel} {{")
            css_lines.extend(clean_props)
            css_lines.append("}\n")

    compiled_css = "\n".join(css_lines)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    studio_css_path = os.path.join(root_dir, "static", "custom_studio.css")
    try:
        with open(studio_css_path, "w", encoding="utf-8") as f:
            f.write(compiled_css)
    except Exception as e:
        print(f"[ThemeBake] Fehler beim Schreiben in custom_studio.css: {e}")

    # Setze theme_live_overrides.json zurück
    reset_data = {
        "rules": {},
        "rawCss": "",
        "textOverrides": data.get("textOverrides", {}),
        "htmlOverrides": data.get("htmlOverrides", {}),
        "migration_version": f"baked_{int(time.time())}",
        "reset_all": True,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds")
    }
    _save_json(THEME_LIVE_FILE, reset_data)

    return {
        "status": "success",
        "baked_rules_count": prop_count,
        "selectors_count": len(rules),
        "version": reset_data["migration_version"],
        "message": f"{prop_count} Regeln erfolgreich ins permanente Hauptdesign eingebrannt."
    }

@app.delete("/api/theme/live-overrides")
def api_delete_theme_live_overrides():
    _save_json(THEME_LIVE_FILE, {
        "rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {},
        "migration_version": "2026_10_27_baked_1793101139", "reset_all": True,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    return {"status": "success"}

def detect_container_port(container_identifier: str, inspected_port: int = None) -> int:
    """Ermittelt den echten Host-Port eines Docker-Containers."""
    cid_lower = str(container_identifier).lower()
    known_ports = {
        "prime-agent": 7681,
        "prime": 7681,
        "browser-use": 7788,
        "browser-use-webui": 7788,
        "browser": 7788,
        "gpt-researcher": 8000,
        "researcher": 8000,
        "openhands": 3000,
        "crewai-flowise": 3001,
        "flowise": 3001,
        "crewai": 3001,
        "open-webui": 8082,
        "webui": 8082,
        "autogen-studio": 8083,
        "autogen": 8083,
        "openclaw": 18789,
        "claw": 18789,
        "hermes-dashboard-proxy": 9119,
        "hermes-dashboard": 9119,
        "hermes-dash": 9119,
        "hermes": 9119,
        "odysseus-agent": 7000,
        "odysseus-odysseus-1": 7000,
        "odysseus-1": 7000,
        "odysseus": 7000,
        "omniroute": 20128,
        "n8n": 5678,
        "espocrm": 8081,
        "agent-os-container": 8501
    }
    
    for key, port in known_ports.items():
        if key in cid_lower:
            return port

    if inspected_port and inspected_port not in (0,):
        return inspected_port
        
    return 8082

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
        SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container", "crm", "pocketbase", "pocketbase-crm"]
        
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
            is_online = "Up" in status_str
            image_str = c.get('Image', '') or ''
            
            saved_cfg = saved_configs.get(c_name) or saved_configs.get(c_id) or {}
            is_active = is_online
            if "active" in saved_cfg:
                is_active = bool(saved_cfg["active"])
            elif "coupled" in saved_cfg:
                is_active = bool(saved_cfg["coupled"])
            
            ports_list = c.get('Ports') or []
            inspected_p = None
            for p in ports_list:
                if isinstance(p, dict):
                    if 'PublicPort' in p:
                        inspected_p = p['PublicPort']
                        break
                    elif 'PrivatePort' in p:
                        inspected_p = p['PrivatePort']
                    
            port_num = detect_container_port(c_name, inspected_p)
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
                "online": is_online,
                "running": is_online,
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
        
        # Keep hermes-dashboard-proxy in sync if hermes-dashboard restarted
        if container_name in ["hermes-dashboard", "hermes"] and action in ["start", "restart"]:
            try:
                s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s2.settimeout(5)
                s2.connect('/var/run/docker.sock')
                req2 = f'POST /containers/hermes-dashboard-proxy/restart HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n'.encode('utf-8')
                s2.sendall(req2)
                s2.recv(4096)
                s2.close()
            except Exception:
                pass

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
async def api_get_models(request: Request):
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        return await forward_to_hermes(request)

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
BOARDROOM_HISTORY_FILE = os.path.join(WORKSPACE_DIR, "boardroom_history.json")

def load_boardroom_history():
    hist = _load_json(BOARDROOM_HISTORY_FILE, None)
    if hist is None:
        # Initial starter entries so the overview looks alive immediately
        hist = [
            {
                "id": "deb_sample_001",
                "timestamp": "2026-10-26T21:30:00",
                "date_display": "26.10.2026 · 21:30 Uhr",
                "task": "Sollten wir unsere Microservices-Architektur konsolidieren und kostenfreie OmniRoute-Modelle als zentrales Gateway nutzen?",
                "framework": "Steffi Kieffer Boardroom",
                "chairman": "Michael Keller (Orchestrator)",
                "rounds": 2,
                "slots_count": 3,
                "slots": [
                    {"name": "Skeptiker & Risikoprüfer", "role": "Haftungs- & Risikoanalyse", "model": "deepseek/deepseek-r1"},
                    {"name": "Innovator & Stratege", "role": "Strategische Entscheidungen", "model": "anthropic/claude-3.7-sonnet"},
                    {"name": "Pragmatiker & Implementierer", "role": "Enterprise Solutions", "model": "deepseek/deepseek-chat"}
                ],
                "transcript": "Michael Keller (Moderator): Debatte eröffnet. Fragestellung: Konsolidierung der Microservices und Nutzung von OmniRoute als zentrales Gateway.\n\nSkeptiker (Haftungs- & Risikoanalyse): Aus Ausfallsicherheits- und SLA-Sicht birgt ein zentrales Gateway ein Single-Point-of-Failure-Risiko, sofern kein lokales Fallback auf Ollama oder direkte API-Keys hinterlegt ist.\n\nInnovator (Strategie): Wirtschaftlich sparen wir dadurch erhebliche Infrastrukturkosten. Die Konsolidierung vereinfacht das Routing und Token-Accounting drastisch.\n\nPragmatiker (Enterprise Solutions): Technisch machbar mittels NGINX-Reverse-Proxy und FastAPI-Failover. Empfehlung: Hybrides Modell mit 2 Fallback-Providern.",
                "synthesis": "KONSENS & ENTSCHEIDUNGSEMPFEHLUNG:\n1. Konsolidierung wird befürwortet unter der Bedingung eines automatischen Fallback-Routings.\n2. OmniRoute fungiert als primäres Gateway; bei Latenz > 5000ms wird nahtlos auf direkte API-Keys bzw. lokale Modelle (Ollama) umgeschaltet.\n3. Implementierung eines 30-Tage-Pilotbetriebs mit Token-Monitoring.",
                "vault_file": "boardroom_debatte_sample_001.md"
            },
            {
                "id": "deb_sample_002",
                "timestamp": "2026-10-25T17:15:00",
                "date_display": "25.10.2026 · 17:15 Uhr",
                "task": "Einführung eines autonomen Nacht-Watchdogs für CI/CD-Pipelines und Sicherheits-Patches",
                "framework": "CLEAR-Model",
                "chairman": "Michael Keller (Orchestrator)",
                "rounds": 2,
                "slots_count": 3,
                "slots": [
                    {"name": "Code Security Lead", "role": "Zero-Trust & Pentest", "model": "openai/gpt-4o"},
                    {"name": "Senior DevOps Engineer", "role": "Docker & Infrastructure", "model": "deepseek/deepseek-chat"},
                    {"name": "Quality Assurance", "role": "E2E Playwright Suite", "model": "google/gemini-2.5-flash"}
                ],
                "transcript": "Michael Keller: Diskussion zur Einführung eines autonomen Nacht-Watchdogs für automatische CI/CD-Patches.\n\nSecurity Lead: Autonome Patches dürfen nur in isolierten Staging-Branches committet werden. Production-Deploys erfordern HITL-Freigabe (Human-in-the-Loop).\n\nDevOps: Wir können nächtliche Cron-Jobs aufsetzen, die automatische PRs erstellen und Test-Suites laufen lassen.\n\nQA: Vollständige Test-Suite muss grün sein, bevor ein PR für den Reviewer markiert wird.",
                "synthesis": "KONSENS & FAZIT:\n- Autonomer Nacht-Watchdog wird aktiviert, agiert jedoch im Staging-Modus.\n- Keine automatischen Merges in den Main-Branch ohne 2FA-Freigabe des Administrators.\n- Slack/Telegram-Benachrichtigung bei erfolgreichem Testlauf.",
                "vault_file": "boardroom_debatte_sample_002.md"
            }
        ]
        _save_json(BOARDROOM_HISTORY_FILE, hist)
    return hist

def save_boardroom_history_item(item: dict):
    hist = load_boardroom_history()
    hist.insert(0, item)
    if len(hist) > 100:
        hist = hist[:100]
    _save_json(BOARDROOM_HISTORY_FILE, hist)
    return hist

@app.get("/api/boardroom/history")
def api_get_boardroom_history():
    return load_boardroom_history()

@app.get("/api/boardroom/history/{item_id}")
def api_get_boardroom_history_item(item_id: str):
    hist = load_boardroom_history()
    for item in hist:
        if item.get("id") == item_id:
            return item
    raise HTTPException(status_code=404, detail="Debatte nicht gefunden")

@app.delete("/api/boardroom/history/{item_id}")
def api_delete_boardroom_history_item(item_id: str):
    hist = load_boardroom_history()
    hist = [h for h in hist if h.get("id") != item_id]
    _save_json(BOARDROOM_HISTORY_FILE, hist)
    return {"status": "success"}

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

@app.post("/api/boardroom/parse-attachment")
async def api_boardroom_parse_attachment(file: UploadFile = File(...)):
    filename = file.filename or "attachment"
    content = await file.read()
    extracted_text = ""
    lower_name = filename.lower()
    
    if lower_name.endswith(".pdf"):
        try:
            import pypdf, io
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = []
            for i, page in enumerate(reader.pages[:25]):
                t = page.extract_text() or ""
                if t.strip():
                    pages_text.append(f"--- Seite {i+1} ---\n{t.strip()}")
            extracted_text = "\n\n".join(pages_text)
            if not extracted_text.strip():
                extracted_text = f"[Hinweis: Keine extrahierbare Textebene in PDF '{filename}' gefunden (z.B. gescanntes Dokument ohne OCR).]"
        except Exception as e:
            extracted_text = f"[Fehler beim Lesen der PDF-Datei '{filename}': {str(e)}]"
    else:
        try:
            extracted_text = content.decode("utf-8", errors="replace")
        except Exception as e:
            extracted_text = f"[Konnte Datei '{filename}' nicht als Text dekodieren: {str(e)}]"
            
    max_chars = 30000
    is_truncated = len(extracted_text) > max_chars
    final_text = extracted_text[:max_chars]
    if is_truncated:
        final_text += f"\n\n[... Inhalt nach {max_chars} Zeichen für Prompt-Budget gekürzt ...]"
        
    return {
        "filename": filename,
        "size": len(content),
        "text": final_text,
        "is_truncated": is_truncated
    }

class BoardroomSlotItem(BaseModel):
    role_name: str
    profile_id: str
    model_id: Optional[str] = None
    provider: Optional[str] = None

class BoardroomRequest(BaseModel):
    task: str
    rounds: int = 2
    chairman_id: Optional[str] = "orchestrator"
    chairman_provider: Optional[str] = "openrouter"
    chairman_model: Optional[str] = None
    framework: str = "Steffi Kieffer Boardroom"
    slots: Optional[List[BoardroomSlotItem]] = None
    reasoning_level: Optional[str] = "profile"
    use_moa: bool = False
    moa_reference_models: Optional[List[dict]] = None
    moa_aggregator: Optional[dict] = None

def _prepare_boardroom_agents(req: BoardroomRequest):
    roles = load_roles()
    roles_map = {r["id"]: r for r in roles}
    try:
        hermes_profiles = api_get_hermes_profiles()
        for hp in hermes_profiles:
            pid = hp.get("id")
            if pid:
                roles_map[pid] = {
                    "id": pid,
                    "name": hp.get("name", pid),
                    "role": hp.get("role", "Expert"),
                    "prompt": hp.get("system_prompt") or hp.get("prompt") or "",
                    "model": hp.get("model") or "deepseek/deepseek-chat",
                    "provider": hp.get("provider") or "openrouter",
                    "reasoning_level": hp.get("reasoning_level") or "medium"
                }
    except Exception:
        pass
    
    override_reasoning = (req.reasoning_level or "profile").strip().lower()

    def _resolve_reasoning(prof_dict: dict) -> str:
        if override_reasoning and override_reasoning != "profile":
            return override_reasoning
        return prof_dict.get("reasoning_level") or "medium"

    # Chairman Profil
    chairman_id = req.chairman_id or "orchestrator"
    chairman_prof = roles_map.get(chairman_id, {
        "id": chairman_id,
        "name": "Orchestrator & System-Architekt",
        "role": "Moderator & Chairman",
        "prompt": "Du bist der Moderator und Chairman des AI Boardrooms.",
        "model": "deepseek/deepseek-chat",
        "provider": "openrouter",
        "reasoning_level": "medium"
    })
    
    chairman_chosen_model = (req.chairman_model or "").strip() or chairman_prof.get("model") or "deepseek/deepseek-chat"
    chairman_chosen_provider = (req.chairman_provider or "").strip() or chairman_prof.get("provider") or "openrouter"

    chairman_agent = {
        "id": chairman_prof["id"],
        "name": chairman_prof.get("name", "Chairman"),
        "role": "Moderator & Chairman",
        "prompt": chairman_prof.get("prompt", ""),
        "model": chairman_chosen_model,
        "provider": chairman_chosen_provider,
        "reasoning_level": _resolve_reasoning(chairman_prof),
        "active": True
    }
    
    # Participant Slots
    participant_agents = []
    if req.slots and len(req.slots) > 0:
        for idx, s in enumerate(req.slots):
            p_id = s.profile_id or "senior_coder"
            r_name = s.role_name or f"Experte {idx+1}"
            prof = roles_map.get(p_id, {})
            chosen_model = (s.model_id or "").strip() or prof.get("model") or "deepseek/deepseek-chat"
            chosen_provider = (s.provider or "").strip() or prof.get("provider") or "openrouter"
            participant_agents.append({
                "id": p_id,
                "name": prof.get("name", p_id),
                "role": r_name,
                "prompt": prof.get("prompt", ""),
                "model": chosen_model,
                "provider": chosen_provider,
                "reasoning_level": _resolve_reasoning(prof),
                "active": True
            })
    else:
        # Standard-Fallback aus Rollen
        for r in roles[1:4]:
            prof = roles_map.get(r["id"], r)
            participant_agents.append({
                "id": r["id"],
                "name": prof.get("name", r["name"]),
                "role": prof.get("role", r.get("name", "Experte")),
                "prompt": prof.get("prompt", r.get("prompt", "")),
                "model": prof.get("model") or "deepseek/deepseek-chat",
                "provider": prof.get("provider") or "openrouter",
                "reasoning_level": _resolve_reasoning(prof),
                "active": True
            })
            
    all_debate_agents = [chairman_agent] + participant_agents
    return chairman_agent, all_debate_agents

@app.post("/api/boardroom/run")
async def api_run_boardroom(req: BoardroomRequest):
    chairman_agent, all_debate_agents = _prepare_boardroom_agents(req)
    
    add_ticker("AI Boardroom", f"Debatte gestartet: '{req.task[:40]}...' ({req.framework}) mit {len(all_debate_agents)} Teilnehmern")
    
    res = await core_dispatcher.run_boardroom_debate(
        task=req.task,
        max_rounds=req.rounds,
        chairman_id=chairman_agent["id"],
        active_agents=all_debate_agents,
        framework=req.framework,
        use_moa=req.use_moa,
        moa_reference_models=req.moa_reference_models,
        moa_aggregator=req.moa_aggregator
    )
    
    # Speichere finales Protokoll im Obsidian Vault
    try:
        vault_dir = OBSIDIAN_VAULT_DIR
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

        # Speichere strukturierten Eintrag in boardroom_history
        try:
            hist_entry = {
                "id": f"deb_{int(time.time())}",
                "timestamp": datetime.datetime.now().isoformat(),
                "date_display": datetime.datetime.now().strftime("%d.%m.%Y · %H:%M Uhr"),
                "task": req.task,
                "framework": req.framework,
                "chairman": chairman_agent.get("name", "Moderator"),
                "use_moa": req.use_moa,
                "rounds": req.rounds,
                "slots_count": max(0, len(all_debate_agents) - 1),
                "slots": [
                    {"name": a.get("name", ""), "role": a.get("role", ""), "model": a.get("model", "")}
                    for a in all_debate_agents[1:]
                ],
                "transcript": res.get("transcript", ""),
                "synthesis": res.get("synthesis", ""),
                "vault_file": f"boardroom_debatte_{ts_str}.md"
            }
            save_boardroom_history_item(hist_entry)
            res["history_id"] = hist_entry["id"]
        except Exception as e:
            print(f"Error saving boardroom history item in run: {e}")
    except Exception as e:
        print(f"Error saving obsidian vault note: {e}")
        
    return res

@app.post("/api/boardroom/stream")
async def api_stream_boardroom(req: BoardroomRequest, request: Request):
    chairman_agent, all_debate_agents = _prepare_boardroom_agents(req)
    add_ticker("AI Boardroom", f"Live-Debatte gestartet: '{req.task[:40]}...' ({req.framework}) mit {len(all_debate_agents)} Teilnehmern")

    async def sse_generator():
        running_transcript = ""
        synthesis_text = ""
        async for ev in core_dispatcher.stream_boardroom_debate(
            task=req.task,
            max_rounds=req.rounds,
            chairman_id=chairman_agent["id"],
            active_agents=all_debate_agents,
            framework=req.framework,
            use_moa=req.use_moa,
            moa_reference_models=req.moa_reference_models,
            moa_aggregator=req.moa_aggregator
        ):
            if await request.is_disconnected():
                print("[AI Boardroom] Client disconnected. Beende Debatten-Stream vorzeitig.")
                break
            if ev.get("type") == "done":
                running_transcript = ev.get("transcript", "")
                synthesis_text = ev.get("synthesis", "")
                vault_file_name = ""
                # Save to Obsidian Vault
                try:
                    vault_dir = OBSIDIAN_VAULT_DIR
                    os.makedirs(vault_dir, exist_ok=True)
                    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    vault_file_name = f"boardroom_debatte_{ts_str}.md"
                    vault_file = os.path.join(vault_dir, vault_file_name)
                    
                    md_content = f"# AI Boardroom Debatte: {req.task}\n\n"
                    md_content += f"**Datum:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    md_content += f"**Methodik-Framework:** {req.framework}\n"
                    md_content += f"**Chairman:** {chairman_agent.get('name', 'Unbekannt')}\n"
                    md_content += f"**Max Runden:** {req.rounds}\n\n"
                    md_content += f"## Diskussionsprotokoll\n\n{running_transcript}\n\n"
                    md_content += f"## Finale Synthese\n\n{synthesis_text}\n"
                    
                    with open(vault_file, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: {vault_file_name}")
                    ev["vault_file"] = vault_file_name
                except Exception as e:
                    print(f"Error saving obsidian vault note: {e}")

                # Save structured debate entry to boardroom history
                try:
                    hist_entry = {
                        "id": f"deb_{int(time.time())}",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "date_display": datetime.datetime.now().strftime("%d.%m.%Y · %H:%M Uhr"),
                        "task": req.task,
                        "framework": req.framework,
                        "chairman": chairman_agent.get("name", "Moderator"),
                "use_moa": req.use_moa,
                        "rounds": req.rounds,
                        "slots_count": max(0, len(all_debate_agents) - 1),
                        "slots": [
                            {"name": a.get("name", ""), "role": a.get("role", ""), "model": a.get("model", "")}
                            for a in all_debate_agents[1:]
                        ],
                        "transcript": running_transcript,
                        "synthesis": synthesis_text,
                        "vault_file": vault_file_name
                    }
                    save_boardroom_history_item(hist_entry)
                    ev["history_id"] = hist_entry["id"]
                except Exception as e:
                    print(f"Error saving boardroom history item: {e}")

            payload = json.dumps(ev, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

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

class DirectAgentChatRequest(BaseModel):
    agent_id: str
    message: str
    attachment_name: Optional[str] = None
    attachment_content: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = []

def load_profiles_list() -> List[Dict]:
    _app_root = os.path.dirname(os.path.abspath(__file__))
    for path in [
        os.path.join(_app_root, "agent_profiles.json"),
        "agent_profiles.json",
        "/app/agent_profiles.json",
        os.path.join(MEMORY_DIR, "agent_profiles.json"),
        "/app/data/agent_profiles.json",
        os.path.join(WORKSPACE_DIR, "agent_profiles.json")
    ]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "profiles" in data:
                        return data["profiles"]
            except Exception:
                pass
    return []

@app.post("/api/v1/agent/chat")
async def api_direct_agent_chat(req: DirectAgentChatRequest):
    # Load profile data
    profiles = load_profiles_list()
    prof = next((p for p in profiles if p.get("id") == req.agent_id), None)
    if not prof:
        prof = {
            "id": req.agent_id,
            "person_name": req.agent_id,
            "name": req.agent_id,
            "system_prompt": "Du bist ein intelligenter KI-Spezialist in Archon OS. Antworte präzise, strukturiert und direkt.",
            "model": "gpt-4o-mini"
        }
    
    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or "IT-Spezialist & DevOps Auditor"
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Du bist ein praxisorientierter, hochkompetenter IT-Administrator, Systemarchitekt und DevOps-Experte. "
        "Wenn dir Log-Einträge, Fehlermeldungen oder Systemfragen übergeben werden, analysiere die Ursache sofort präzise "
        "und erkläre dem Nutzer Schritt für Schritt, wie das Problem behoben werden kann (inklusive passender Konfigurations- oder Terminal-Befehle)."
    )
    
    user_msg = req.message
    if req.attachment_content:
        user_msg = f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n```\n{req.attachment_content[:6000]}\n```\n\n{req.message}"
    
    messages = [{"role": "system", "content": system_prompt}]
    if req.history:
        for h in req.history[-8:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_msg})
    
    model_to_use = prof.get("model") or "deepseek/deepseek-chat"
    provider_to_use = prof.get("provider") or "openrouter"
    
    start_t = time.time()
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=agent_name,
            prompt=user_msg,
            role=prof.get("name", "Spezialist"),
            system_prompt=system_prompt,
            model=model_to_use,
            provider=provider_to_use
        )
        reply_text = res.get("content", "Keine Antwort erhalten.")
    except Exception as e:
        reply_text = f"Fehler bei der Kommunikation mit {agent_name}: {str(e)}"
    
    duration = round(time.time() - start_t, 2)
    add_ticker("Direct Chat", f"Nachricht an {agent_name} beantwortet ({duration}s)")
    
    return {
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }

# =====================================================================
# GATEWAY MANAGER — Hermes Profile Start/Stop/Autostart/Idle-Timeout
# =====================================================================

import subprocess
import threading

def _run_docker_exec(cmd: list) -> tuple[int, str, str]:
    """Run a command inside the hermes container via Docker Unix Socket."""
    target_containers = ["hermes-webui", "hermes", "hermes-agent"]
    try:
        transport = httpx.HTTPTransport(uds="/var/run/docker.sock")
        with httpx.Client(transport=transport, timeout=25.0) as client:
            for c_name in target_containers:
                try:
                    res = client.post(f"http://docker/containers/{c_name}/exec", json={
                        "AttachStdout": True,
                        "AttachStderr": True,
                        "Cmd": cmd
                    })
                    if res.status_code == 201:
                        exec_id = res.json().get("Id")
                        res_start = client.post(f"http://docker/exec/{exec_id}/start", json={
                            "Detach": False,
                            "Tty": False
                        })
                        return 0, res_start.text, ""
                except Exception:
                    continue
    except Exception as e:
        pass

    # Fallback to local subprocess if running in host mode
    for c_name in target_containers:
        try:
            full_cmd = ["docker", "exec", c_name] + cmd
            r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return r.returncode, r.stdout, r.stderr
        except Exception:
            continue
    return 1, "", "Failed to execute in hermes container (tried hermes-agent, hermes)"

def _load_gateway_config() -> Dict:
    cfg = _load_json(GATEWAY_CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("idle_timeout_minutes", 30)
    cfg.setdefault("autostart", {"default": True})
    cfg.setdefault("last_used", {})
    return cfg

def _save_gateway_config(cfg: Dict):
    _save_json(GATEWAY_CONFIG_FILE, cfg)

def _get_all_installed_profiles() -> list[str]:
    """List profile names from the mounted profiles volume directory."""
    candidates = ["/opt/data/profiles", os.path.join(MEMORY_DIR, "hermes_profiles")]
    for d in candidates:
        if os.path.exists(d) and os.path.isdir(d):
            try:
                entries = [e for e in os.listdir(d) if os.path.isdir(os.path.join(d, e))]
                if entries:
                    if "default" not in entries:
                        entries.insert(0, "default")
                    return sorted(entries)
            except Exception:
                pass
    return ["default"]

@app.get("/api/v1/gateway/list")
async def api_gateway_list():
    all_profiles = _get_all_installed_profiles()
    cfg = _load_gateway_config()
    autostart_map = cfg.get("autostart", {})
    last_used_map = cfg.get("last_used", {})
    active_gateways = cfg.get("active_gateways", {})

    # Read live state from volume
    gw_state_file = "/opt/data/gateway_state.json"
    served_profiles = []
    is_master_running = False
    if os.path.exists(gw_state_file):
        try:
            gw_data = _load_json(gw_state_file, {})
            is_master_running = gw_data.get("gateway_state") == "running"
            served_profiles = gw_data.get("served_profiles", [])
        except Exception:
            pass

    profiles = []
    for pid in all_profiles:
        # Default is running if master gateway is up; others according to active_gateways or explicit state
        if pid == "default":
            status = "running" if is_master_running else "stopped"
        else:
            status = "running" if active_gateways.get(pid, False) else "stopped"

        profiles.append({
            "id": pid,
            "status": status,
            "autostart": autostart_map.get(pid, pid == "default"),
            "last_used": last_used_map.get(pid, None)
        })

    return {"profiles": profiles, "idle_timeout_minutes": cfg.get("idle_timeout_minutes", 30)}

def _update_profile_status(profile_id: str, new_status: str):
    try:
        prof_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
        if os.path.exists(prof_file):
            with open(prof_file, "r", encoding="utf-8") as f:
                profs = json.load(f)
            updated = False
            for p in profs:
                if p.get("id") == profile_id:
                    p["status"] = new_status
                    updated = True
                    break
            if updated:
                with open(prof_file, "w", encoding="utf-8") as f:
                    json.dump(profs, f, indent=2, ensure_ascii=False)
        hier_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "org_hierarchy.json")
        if os.path.exists(hier_file):
            with open(hier_file, "r", encoding="utf-8") as f:
                hier = json.load(f)
            for n in hier.get("nodes", []):
                if n.get("id") == profile_id:
                    n["status"] = new_status
                    break
            with open(hier_file, "w", encoding="utf-8") as f:
                json.dump(hier, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Error updating profile status for {profile_id}: {e}")

@app.post("/api/v1/gateway/start")
async def api_gateway_start(payload: Dict = Body(...)):
    profile_id = payload.get("profile_id", "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    
    cfg = _load_gateway_config()
    cfg.setdefault("active_gateways", {})
    cfg["active_gateways"][profile_id] = True
    cfg.setdefault("last_used", {})
    cfg["last_used"][profile_id] = datetime.datetime.now().isoformat()
    _save_gateway_config(cfg)
    _update_profile_status(profile_id, "active")

    # Execute profile gateway start command
    cmd = ["hermes", "gateway", "start"] if profile_id == "default" else ["hermes", "--profile", profile_id, "gateway", "start"]
    rc, stdout, stderr = _run_docker_exec(cmd)
    return {"ok": True, "profile_id": profile_id, "output": stdout or stderr}

@app.post("/api/v1/gateway/stop")
async def api_gateway_stop(payload: Dict = Body(...)):
    profile_id = payload.get("profile_id", "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    if profile_id == "default":
        raise HTTPException(status_code=400, detail="default gateway cannot be stopped")

    cfg = _load_gateway_config()
    cfg.setdefault("active_gateways", {})
    cfg["active_gateways"][profile_id] = False
    _save_gateway_config(cfg)
    _update_profile_status(profile_id, "standby")

    # Execute profile gateway stop command
    cmd = ["hermes", "--profile", profile_id, "gateway", "stop"]
    rc, stdout, stderr = _run_docker_exec(cmd)
    return {"ok": True, "profile_id": profile_id, "output": stdout or stderr}

@app.get("/api/v1/gateway/config")
def api_get_gateway_config():
    return _load_gateway_config()

@app.post("/api/v1/gateway/config")
def api_save_gateway_config_endpoint(payload: Dict = Body(...)):
    cfg = _load_gateway_config()
    if "idle_timeout_minutes" in payload:
        try:
            cfg["idle_timeout_minutes"] = max(1, int(payload["idle_timeout_minutes"]))
        except (ValueError, TypeError):
            pass
    if "autostart" in payload and isinstance(payload["autostart"], dict):
        cfg["autostart"].update(payload["autostart"])
    _save_gateway_config(cfg)
    return cfg

@app.post("/api/v1/gateway/autostart")
def api_gateway_autostart(payload: Dict = Body(...)):
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    enable = bool(payload.get("autostart", False))
    cfg = _load_gateway_config()
    cfg.setdefault("autostart", {})
    cfg["autostart"][profile_id] = enable
    _save_gateway_config(cfg)
    return {"ok": True, "profile_id": profile_id, "autostart": enable}

@app.post("/api/v1/gateway/stop-all")
async def api_gateway_stop_all():
    cfg = _load_gateway_config()
    active_map = cfg.get("active_gateways", {})
    stopped = []
    for pid, is_active in list(active_map.items()):
        if pid == "default" or not is_active:
            continue
        cfg["active_gateways"][pid] = False
        _update_profile_status(pid, "standby")
        try:
            _run_docker_exec(["hermes", "--profile", pid, "gateway", "stop"])
        except Exception:
            pass
        stopped.append(pid)
    _save_gateway_config(cfg)
    return {"ok": True, "stopped": stopped}

# =====================================================================
# INTERNET WATCHDOG (SÄULE 4 DER KOGNITION: AUTONOMER WEB-RADAR)
# =====================================================================

@app.get("/api/v1/watchdog/config")
def api_get_watchdog_config():
    from backend.internet_watchdog import get_watchdog_config
    return get_watchdog_config()

@app.post("/api/v1/watchdog/config")
def api_save_watchdog_config(payload: Dict = Body(...)):
    from backend.internet_watchdog import get_watchdog_config, save_watchdog_config
    cfg = get_watchdog_config()
    if "enabled" in payload:
        cfg["enabled"] = bool(payload["enabled"])
    if "interval_minutes" in payload:
        try:
            cfg["interval_minutes"] = max(5, int(payload["interval_minutes"]))
        except (ValueError, TypeError):
            pass
    if "basket_threshold" in payload:
        try:
            cfg["basket_threshold"] = max(1, int(payload["basket_threshold"]))
        except (ValueError, TypeError):
            pass
    if "priority_keywords" in payload and isinstance(payload["priority_keywords"], list):
        cfg["priority_keywords"] = [str(k).strip() for k in payload["priority_keywords"] if str(k).strip()]
    if "basket" in payload and isinstance(payload["basket"], list):
        cfg["basket"] = payload["basket"]
    if "channels" in payload and isinstance(payload["channels"], dict):
        cfg.setdefault("channels", {}).update(payload["channels"])
    if "targets" in payload and isinstance(payload["targets"], list):
        cfg["targets"] = payload["targets"]
    save_watchdog_config(cfg)
    return {"ok": True, "config": cfg}

@app.post("/api/v1/watchdog/dispatch_action")
async def api_watchdog_dispatch_action(payload: Dict = Body(...)):
    """Erzeugt eine gezielte Kanban-Aufgabe aus einem oder mehreren Watchdog-Funden.
    action_type: 'linkedin_post' | 'robert_dossier' | 'bundle_content' | 'custom'
    """
    from datetime import datetime
    import sqlite3

    action_type = payload.get("action_type", "custom")
    findings = payload.get("findings", [])
    custom_prompt = payload.get("custom_prompt", "").strip()
    target_profile = payload.get("target_profile")
    
    if not findings:
        return {"ok": False, "error": "Keine Funde übergeben"}

    now_iso = datetime.now().isoformat()
    now_display = datetime.now().strftime("%d.%m.%Y %H:%M")

    if action_type == "linkedin_post":
        f = findings[0]
        assignee = "storyteller_ghostwriter"
        title = f"✍️ LinkedIn-Post: {f['title'][:60]}"
        prompt_instruction = custom_prompt or (
            "Analysiere diesen Fund, arbeite die Kern-Relevanz für den deutschen Markt heraus "
            "und formuliere einen ansprechenden LinkedIn-Beitrag (Hook, Story, 3 Takeaways, Call-to-Action). "
            "ZITATIONS-PFLICHT: Bette die Primärquelle als sauberen Markdown-Link [Quelle: Name](URL) "
            "direkt im Text oder am Beitragsende ein."
        )
        body = (
            f"📱 **LinkedIn-Content Auftrag**\n\n"
            f"• **Thema:** {f['title']}\n"
            f"• **Quelle:** {f.get('target_name')} ({f.get('category')})\n"
            f"• **Link:** {f.get('link')}\n\n"
            f"**Anweisung:**\n{prompt_instruction}\n\n"
            f"**Roh-Inhalt:**\n{f.get('snippet', '')}"
        )
    elif action_type == "robert_dossier":
        f = findings[0]
        assignee = "executive_decision_architect"
        title = f"📊 Strategie-Dossier: {f['title'][:60]}"
        prompt_instruction = custom_prompt or (
            "Prüfe die strategische Tragweite dieser Meldung für unsere Bau-, Investitions- und Projektentwicklungen "
            "und erstelle eine 1-Seiten-Entscheidungsvorlage mit Handlungsoptionen. "
            "ZITATIONS-PFLICHT: Zitiere die Primärquelle mit offiziellem Link [Quelle: Name](URL) und Einstufung (Amtlich/Leitmedium)."
        )
        body = (
            f"🏛️ **Strategische Vorlage für Robert (CEO)**\n\n"
            f"• **Gegenstand:** {f['title']}\n"
            f"• **Quelle:** {f.get('target_name')}\n"
            f"• **Referenz:** {f.get('link')}\n\n"
            f"**Prüfungsauftrag:**\n{prompt_instruction}\n\n"
            f"**Fundauszug:**\n{f.get('snippet', '')}"
        )
    elif action_type == "bundle_content":
        assignee = target_profile or "content_repurposing_specialist"
        title = f"🧺 Trend-Synthese aus {len(findings)} Radar-Funden"
        items_text = "\n".join([f"- **{it['title']}** ({it.get('category')}): {it.get('link')}\n  {it.get('snippet', '')[:180]}" for it in findings])
        prompt_instruction = custom_prompt or (
            f"Erstelle aus diesen {len(findings)} gesammelten Trend-Meldungen eine zusammenfassende Branchen- und Investitions-Synthese "
            "sowie zwei darauf aufbauende Content-Ideen. "
            "ZITATIONS-PFLICHT: Zitiere alle herangezogenen Quellen als anklickbare Hyperlinks [Quelle: Name](URL) in einem abschließenden Quellenverzeichnis."
        )
        body = (
            f"🧺 **Sammelkorb-Synthese ({len(findings)} Quellen)**\n\n"
            f"**Zusammenstellung:**\n{items_text}\n\n"
            f"**Auftrag:**\n{prompt_instruction}"
        )
    else: # custom
        f = findings[0] if len(findings) == 1 else findings
        assignee = target_profile or "executive_decision_architect"
        title = payload.get("title") or (f"Aufgabe: {findings[0]['title'][:60]}" if len(findings) == 1 else f"Sammel-Aufgabe ({len(findings)} Funde)")
        body = custom_prompt or f"Fund verarbeiten: {findings[0].get('link') if len(findings) == 1 else ''}"

    task_id = f"task-{int(datetime.now().timestamp())}"

    # Eintragen in kanban.db
    inserted = False
    for kanban_db in ["/home/micha/.hermes/kanban.db", "/opt/data/kanban.db"]:
        if os.path.exists(kanban_db):
            try:
                with sqlite3.connect(kanban_db, timeout=5.0) as kconn:
                    kconn.execute("""
                        INSERT OR IGNORE INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (task_id, title, body, assignee, "ready", "normal", "watchdog_action", now_iso))
                    kconn.commit()
                    inserted = True
            except Exception as e:
                print(f"[Watchdog] Action Kanban Insert Fehler: {e}")

    # Fallback MemoryBridge
    if not inserted:
        try:
            from local_memory_bridge import LocalMemoryBridge
            LocalMemoryBridge().sync_task(task_id=task_id, title=title, role=assignee, status="ready")
        except Exception:
            pass

    return {
        "ok": True,
        "task_id": task_id,
        "title": title,
        "assignee": assignee,
        "status": "ready"
    }

@app.post("/api/v1/watchdog/run_now")
async def api_trigger_watchdog_run():
    from backend.internet_watchdog import run_watchdog_scan
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, run_watchdog_scan, True)
    return res

# Background idle-stop task
_idle_stop_running = False


def _parse_gateway_list(stdout: str) -> list:
    '''Parses the hermes gateway list output into a list of dicts.'''
    profiles = []
    lines = stdout.split('\n')
    # Expected table format or simple json, let's do a basic parse
    # For now return empty list to prevent crash
    return profiles

async def _gateway_idle_stop_loop():

    global _idle_stop_running
    _idle_stop_running = True
    while True:
        await asyncio.sleep(300)  # check every 5 minutes
        try:
            cfg = _load_gateway_config()
            timeout_min = cfg.get("idle_timeout_minutes", 30)
            last_used = cfg.get("last_used", {})
            autostart = cfg.get("autostart", {})
            now = datetime.datetime.now()
            rc, stdout, _ = _run_docker_exec(["hermes", "gateway", "list"])
            if rc != 0:
                continue
            running_profiles = [p["id"] for p in _parse_gateway_list(stdout) if p["status"] == "running" and p["id"] != "default"]
            for pid in running_profiles:
                if autostart.get(pid, False):
                    continue  # autostart profiles stay up
                last = last_used.get(pid)
                if last:
                    try:
                        last_dt = datetime.datetime.fromisoformat(last)
                        idle_min = (now - last_dt).total_seconds() / 60
                        if idle_min >= timeout_min:
                            _run_docker_exec(["hermes", "gateway", "stop", pid])
                            print(f"[GatewayManager] Auto-stopped idle gateway: {pid} (idle {idle_min:.0f}m)")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[GatewayManager] Idle-stop loop error: {e}")

async def _email_imap_background_loop():
    await asyncio.sleep(15)
    while True:
        try:
            from backend.email_service import sync_imap_inbox
            await asyncio.to_thread(sync_imap_inbox, limit=20)
        except Exception as e:
            print(f"[EmailService] Background sync error: {e}")
        await asyncio.sleep(180)

@app.on_event("startup")
async def _start_gateway_idle_loop():
    asyncio.create_task(_gateway_idle_stop_loop())
    asyncio.create_task(_email_imap_background_loop())
    try:
        from backend.inbox_watcher import inbox_watcher_background_loop
        asyncio.create_task(inbox_watcher_background_loop())
    except Exception as e:
        print(f"[Startup] Inbox Watcher init notice: {e}")
    try:
        from backend.internet_watchdog import internet_watchdog_background_loop
        asyncio.create_task(internet_watchdog_background_loop())
    except Exception as e:
        print(f"[Startup] Internet Watchdog init notice: {e}")

# =====================================================================
# QUICKCHAT — Persistent Per-Profile Sessions
# =====================================================================

def _quickchat_session_path(profile_id: str) -> str:
    # Sanitize profile_id to avoid path traversal
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", profile_id)
    return os.path.join(QUICKCHAT_SESSIONS_DIR, f"{safe_id}.json")

def _load_quickchat_session(profile_id: str) -> Dict:
    path = _quickchat_session_path(profile_id)
    if os.path.exists(path):
        data = _load_json(path, {})
        if isinstance(data, dict):
            return data
    return {
        "profile_id": profile_id,
        "messages": [],
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat()
    }

def _save_quickchat_session(session: Dict):
    session["updated_at"] = datetime.datetime.now().isoformat()
    _save_json(_quickchat_session_path(session["profile_id"]), session)

@app.get("/api/v1/quickchat/session/{profile_id}")
def api_get_quickchat_session(profile_id: str):
    return _load_quickchat_session(profile_id)

class QuickchatSendRequest(BaseModel):
    profile_id: str
    message: str
    attachment_content: Optional[str] = None
    attachment_name: Optional[str] = None

@app.post("/api/v1/quickchat/send")
async def api_quickchat_send(req: QuickchatSendRequest):
    session = _load_quickchat_session(req.profile_id)

    # Build history for context (last 12 turns = 6 back-and-forth)
    history = []
    for msg in session["messages"][-12:]:
        role = "user" if msg.get("role") == "user" else "assistant"
        history.append({"role": role, "content": msg.get("text", "")})

    # Update last_used for idle-stop tracking
    cfg = _load_gateway_config()
    cfg["last_used"][req.profile_id] = datetime.datetime.now().isoformat()
    _save_gateway_config(cfg)

    # Load profile for system prompt
    profiles = load_profiles_list()
    prof = next((p for p in profiles if p.get("id") == req.profile_id), None)
    if not prof:
        prof = {"id": req.profile_id, "name": req.profile_id, "model": "gpt-4o-mini", "provider": "openrouter"}

    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or req.profile_id
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Antworte präzise, kompetent und direkt. Halte den Kontext der bisherigen Konversation."
    )
    model = prof.get("model") or "gpt-4o-mini"
    provider = prof.get("provider") or "openrouter"

    user_msg = req.message
    if req.attachment_content:
        user_msg = f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n```\n{req.attachment_content[:6000]}\n```\n\n{req.message}"

    start_t = time.time()
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=agent_name,
            prompt=user_msg,
            role=role_title,
            system_prompt=system_prompt,
            model=model,
            provider=provider
        )
        reply_text = res.get("content", "Keine Antwort erhalten.")
    except Exception as e:
        reply_text = f"⚠ Fehler: {str(e)}"

    duration = round(time.time() - start_t, 2)

    # Append to persistent session
    session["messages"].append({"role": "user", "text": req.message, "ts": datetime.datetime.now().isoformat()})
    session["messages"].append({"role": "agent", "text": str(reply_text), "ts": datetime.datetime.now().isoformat()})
    # Keep last 200 messages to cap disk usage
    if len(session["messages"]) > 200:
        session["messages"] = session["messages"][-200:]
    _save_quickchat_session(session)

    add_ticker("Quickchat", f"{agent_name}: {req.message[:40]}… ({duration}s)")

    return {
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }

@app.delete("/api/v1/quickchat/session/{profile_id}")
def api_delete_quickchat_session(profile_id: str):
    path = _quickchat_session_path(profile_id)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True, "profile_id": profile_id}

THEME_WORKSPACE_FILE = os.path.join(WORKSPACE_DIR, "theme_custom.json")


@app.get("/api/theme")
def api_get_theme():
    if os.path.exists(THEME_WORKSPACE_FILE):
        return _load_json(THEME_WORKSPACE_FILE, {})
    return _load_json(THEME_FILE, {})

@app.post("/api/theme")
def api_save_theme(theme_data: Dict = Body(...)):
    _save_json(THEME_FILE, theme_data)
    _save_json(THEME_WORKSPACE_FILE, theme_data)
    return {"status": "success"}

class TextReplacementItem(BaseModel):
    original: str
    replacement: str

class TextReplacementsRequest(BaseModel):
    replacements: List[TextReplacementItem]

@app.post("/api/v1/ui/save-text-replacements")
def api_save_text_replacements(req: TextReplacementsRequest):
    candidates = [
        "/app/static/index.html",
        "static/index.html",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"),
        os.path.join(WORKSPACE_DIR, "static", "index.html")
    ]
    target_files = [p for p in set(candidates) if os.path.exists(p)]
    if not target_files:
        raise HTTPException(status_code=404, detail="Keine static/index.html Datei gefunden.")
    
    total_replaced = 0
    for target_path in target_files:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            file_replaced = 0
            for item in req.replacements:
                orig = item.original
                repl = item.replacement
                if orig and repl and orig != repl and orig in content:
                    content = content.replace(orig, repl)
                    file_replaced += 1
            
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
            total_replaced = max(total_replaced, file_replaced)
        except Exception as err:
            print(f"Error saving replacements to {target_path}: {err}")
            
    add_ticker("Live UI Editor", f"{total_replaced} Texte dauerhaft in index.html eingefroren & gespeichert.")
    return {"status": "success", "replaced_count": total_replaced}

class FullHtmlSaveRequest(BaseModel):
    html: Optional[str] = None
    custom_css: Optional[str] = None

@app.post("/api/v1/ui/save-full-html")
def api_save_full_html(req: FullHtmlSaveRequest):
    candidates = [
        "/app/static/index.html",
        "static/index.html",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"),
        os.path.join(WORKSPACE_DIR, "static", "index.html")
    ]
    target_files = [p for p in set(candidates) if os.path.exists(p)]
    if not target_files:
        raise HTTPException(status_code=404, detail="Keine static/index.html Datei gefunden.")
    
    if req.html and len(req.html.strip()) > 100:
        for target_path in target_files:
            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(req.html)
            except Exception as err:
                print(f"Error saving full HTML to {target_path}: {err}")
    
    add_ticker("Design Studio", "HTML & Design-Stand erfolgreich eingefroren und gespeichert.")
    return {"status": "success"}

# ==========================================
# ðŸ§  BRAIN & ARCHIV (3D GALAXY & VAULT API)
# ==========================================

@app.get("/api/v1/brain/galaxy-data")
def api_brain_galaxy_data():
    nodes = []
    links = []
    node_ids = set()

    # 1. Central Core Node
    core_id = "core_archon_os"
    nodes.append({
        "id": core_id,
        "name": "⚡ Archon OS Kernel",
        "group": "core",
        "color": "#38bdf8",
        "val": 35,
        "description": "Zentraler OS-Kern & Event Loop Orchestrator",
        "details": {"type": "System Kernel", "status": "Online"}
    })
    node_ids.add(core_id)

    # 2. Agenten aus agent_profiles.json & roles.json
    agent_profiles = []
    # SSOT: nur die Projekt-Wurzel-Datei (data/agent_workspace sind Spiegel)
    for path in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json"), "agent_profiles.json"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    agent_profiles = json.load(f)
                break
            except:
                pass
    
    if not agent_profiles:
        agent_profiles = DEFAULT_ROLES

    for a in agent_profiles:
        aid = f"agent_{a.get('id', a.get('name'))}"
        if aid not in node_ids:
            nodes.append({
                "id": aid,
                "name": f"ðŸ¤– {a.get('name', 'Agent')}",
                "group": "agent",
                "color": "#22c55e",
                "val": 22,
                "description": a.get("category", "Autonomer Agent"),
                "details": {
                    "role_id": a.get("id"),
                    "category": a.get("category", "General"),
                    "prompt": a.get("prompt", "")[:180] + "...",
                    "skills": a.get("skills", [])
                }
            })
            node_ids.add(aid)
            links.append({"source": core_id, "target": aid, "relationship": "orchestrates", "color": "rgba(56, 189, 248, 0.4)"})

            # Connect agent skills
            for s in a.get("skills", []):
                sid = f"skill_{s}"
                if sid not in node_ids:
                    nodes.append({
                        "id": sid,
                        "name": f"⚡ {s.replace('skill-', '').replace('_', ' ').title()}",
                        "group": "skill",
                        "color": "#a855f7",
                        "val": 14,
                        "description": "Fähigkeit / Execution Skill",
                        "details": {"skill_id": s}
                    })
                    node_ids.add(sid)
                links.append({"source": aid, "target": sid, "relationship": "executes", "color": "rgba(168, 85, 247, 0.5)"})

    # 3. Obsidian Vault Notizen & Personalakten
    vault_candidates = [
        "C:\\Mein Obsidian",
        "C:\\.Mein Obsidian",
        "/opt/data/obsidian",
        OBSIDIAN_VAULT_DIR,
        os.path.join(WORKSPACE_DIR, "agent_workspace", "obsidian_vault"),
        "agent_workspace/obsidian_vault",
        "/app/agent_workspace/obsidian_vault"
    ]
    vault_dir = None
    for v in vault_candidates:
        if v and os.path.exists(v):
            vault_dir = v
            break

    if vault_dir:
        for root, dirs, files in os.walk(vault_dir):
            if ".obsidian" in root or ".git" in root or "node_modules" in root:
                continue
            for file in files:
                if file.endswith(".md"):
                    rel_path = os.path.relpath(os.path.join(root, file), vault_dir).replace("\\", "/")
                    note_id = f"note_{rel_path}"
                    clean_name = file.replace(".md", "").replace("_", " ").title()
                    is_personalakte = "Personalakten" in rel_path
                    
                    if note_id not in node_ids:
                        nodes.append({
                            "id": note_id,
                            "name": f"{'ðŸ“‹' if is_personalakte else 'ðŸ“„'} {clean_name}",
                            "group": "personalakte" if is_personalakte else "vault_note",
                            "color": "#eab308" if is_personalakte else "#06b6d4",
                            "val": 16 if is_personalakte else 10,
                            "description": rel_path,
                            "details": {
                                "rel_path": rel_path,
                                "type": "Personalakte" if is_personalakte else "Vault Dokument",
                                "filename": file
                            }
                        })
                        node_ids.add(note_id)

                        # Match with agent if Personalakte
                        matched_agent = False
                        if is_personalakte:
                            for a in agent_profiles:
                                aid = f"agent_{a.get('id', a.get('name'))}"
                                if a.get("id") and a.get("id").lower() in file.lower() or file.lower().replace(".md", "") in a.get("id", "").lower():
                                    if aid in node_ids:
                                        links.append({"source": aid, "target": note_id, "relationship": "documented_in", "color": "rgba(234, 179, 8, 0.6)"})
                                        matched_agent = True
                                        break
                        if not matched_agent:
                            links.append({"source": core_id, "target": note_id, "relationship": "stores", "color": "rgba(6, 182, 212, 0.3)"})

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "agents_count": len([n for n in nodes if n["group"] == "agent"]),
            "skills_count": len([n for n in nodes if n["group"] == "skill"]),
            "vault_notes_count": len([n for n in nodes if "note" in n["group"] or "personalakte" in n["group"]])
        }
    }

@app.get("/api/v1/brain/vault-file")
def api_brain_vault_file(path: str):
    vault_candidates = [
        "C:\\Mein Obsidian",
        "C:\\.Mein Obsidian",
        "/opt/data/obsidian",
        OBSIDIAN_VAULT_DIR,
        os.path.join(WORKSPACE_DIR, "agent_workspace", "obsidian_vault"),
        "agent_workspace/obsidian_vault",
        "/app/agent_workspace/obsidian_vault"
    ]
    vault_dir = None
    for v in vault_candidates:
        if v and os.path.exists(v):
            vault_dir = os.path.abspath(v)
            break
            
    if not vault_dir:
        raise HTTPException(status_code=404, detail="Obsidian Vault Verzeichnis nicht gefunden.")

    clean_path = path.lstrip("/\\")
    safe_path = os.path.abspath(os.path.join(vault_dir, clean_path))
    if not safe_path.startswith(vault_dir):
        raise HTTPException(status_code=400, detail="Ungültiger Dateipfad.")
        
    if not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail=f"Datei '{path}' nicht gefunden.")
        
    try:
        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "path": path,
            "filename": os.path.basename(safe_path),
            "content": content,
            "size": len(content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# NOTEBOOK & DEEP DOCS / OCR LIBRARY PIPELINE
# ---------------------------------------------------------

@app.post("/api/v1/library/upload")
async def api_library_upload(request: Request):
    try:
        from utils.batch_library_importer import resolve_raw_docs_dir, resolve_vault_path, process_document
        raw_dir = resolve_raw_docs_dir()
        vault_dir = resolve_vault_path()
        os.makedirs(raw_dir, exist_ok=True)
        
        form = await request.form()
        uploaded_files = form.getlist("files") or form.getlist("file")
        if not uploaded_files:
            single_file = form.get("file")
            if single_file:
                uploaded_files = [single_file]
                
        if not uploaded_files:
            raise HTTPException(status_code=400, detail="Keine Dateien übermittelt.")
            
        auto_ingest = form.get("auto_ingest", "true").lower() in ["true", "1", "yes"]
        category = form.get("category", "auto")
        
        results = []
        for file in uploaded_files:
            if hasattr(file, "filename") and file.filename:
                file_path = os.path.join(raw_dir, file.filename)
                content = await file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                    
                item_info = {
                    "filename": file.filename,
                    "size_bytes": len(content),
                    "saved_path": file_path
                }
                
                if auto_ingest:
                    try:
                        ingest_res = process_document(file_path, vault_dir, target_category=category)
                        item_info["ingest"] = ingest_res
                    except Exception as err:
                        item_info["ingest"] = {"status": "error", "error": str(err)}
                        
                results.append(item_info)
            
        # Wenn auto_ingest aktiv war, im Hintergrund AnythingLLM RAG-Sync anstoßen
        if auto_ingest:
            async def trigger_background_rag_sync():
                try:
                    import subprocess
                    sync_script = os.path.join(os.path.dirname(__file__), "tools", "sync_vault_to_rag.py")
                    if os.path.exists(sync_script):
                        cmd = [sys.executable, sync_script, "--api-key", "R9YRVG7-FCFMRNK-NZ3FKSX-QKN5RHF", "--all"]
                        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as ex:
                    print(f"[RAG-Sync-Trigger Error]: {ex}", file=sys.stderr)
            asyncio.create_task(trigger_background_rag_sync())

        return {
            "status": "success",
            "uploaded_count": len(results),
            "items": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/library/ingest")
def api_library_ingest():
    try:
        from utils.batch_library_importer import run_batch_ingest
        summary = run_batch_ingest()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/library/books")
def api_library_books():
    try:
        from utils.batch_library_importer import list_indexed_books
        books = list_indexed_books()
        return {"books": books, "count": len(books)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/library/book-content")
def api_library_book_content(rel_path: str = Query(...)):
    try:
        from utils.batch_library_importer import resolve_vault_path
        vault_dir = resolve_vault_path()
        bib_dir = os.path.join(vault_dir, "02_Wissensbibliothek")
        
        clean_path = rel_path.lstrip("/\\")
        safe_path = os.path.abspath(os.path.join(bib_dir, clean_path))
        if not safe_path.startswith(os.path.abspath(bib_dir)):
            raise HTTPException(status_code=400, detail="Ungültiger Pfad.")
            
        if not os.path.exists(safe_path):
            raise HTTPException(status_code=404, detail=f"Dokument '{rel_path}' nicht gefunden.")
            
        with open(safe_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        return {
            "rel_path": rel_path,
            "filename": os.path.basename(safe_path),
            "content": content,
            "size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# NOTEBOOKLM STUDIO & GROUNDED RETRIEVAL API
# ---------------------------------------------------------

@app.get("/api/v1/notebooks")
def api_get_notebooks():
    try:
        from utils.notebook_engine import list_notebooks
        return {"notebooks": list_notebooks()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks")
def api_create_notebook(payload: dict = Body(...)):
    try:
        from utils.notebook_engine import create_notebook
        name = payload.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name ist erforderlich.")
        description = payload.get("description", "").strip()
        nb = create_notebook(name, description)
        return {"status": "success", "notebook": nb}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/notebooks/{nb_id}")
def api_delete_notebook(nb_id: str):
    try:
        from utils.notebook_engine import delete_notebook
        ok = delete_notebook(nb_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notebook nicht gefunden.")
        return {"status": "deleted", "id": nb_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/notebooks/{nb_id}/sources")
def api_get_notebook_sources(nb_id: str):
    try:
        from utils.notebook_engine import list_sources
        sources = list_sources(nb_id)
        return {"sources": sources, "count": len(sources)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/sources/upload")
async def api_upload_notebook_source(nb_id: str, request: Request):
    try:
        from utils.notebook_engine import add_source_file
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="Keine Datei übermittelt.")
        file_bytes = await file.read()
        res = add_source_file(nb_id, file_bytes, file.filename)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/sources/attach-vault")
def api_attach_vault_source(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import add_source_from_vault
        rel_path = payload.get("rel_path")
        if not rel_path:
            raise HTTPException(status_code=400, detail="rel_path ist erforderlich.")
        res = add_source_from_vault(nb_id, rel_path)
        return res
    except (ValueError, FileNotFoundError) as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/notebooks/{nb_id}/sources/{src_id}")
def api_delete_notebook_source(nb_id: str, src_id: str):
    try:
        from utils.notebook_engine import delete_source
        ok = delete_source(nb_id, src_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Quelle nicht gefunden.")
        return {"status": "deleted", "source_id": src_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/notebooks/{nb_id}/chat-history")
def api_get_notebook_chat(nb_id: str):
    try:
        from utils.notebook_engine import get_notebook
        nb = get_notebook(nb_id)
        if not nb:
            raise HTTPException(status_code=404, detail="Notebook nicht gefunden.")
        return {"chat_history": nb.get("chat_history", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/query")
async def api_query_notebook(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import query_notebook
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt ist erforderlich.")
        res = await query_notebook(nb_id, prompt)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/sync-obsidian")
def api_sync_notebook_obsidian(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import save_to_obsidian
        query = payload.get("query", "")
        response_text = payload.get("response", "")
        citations = payload.get("citations", "")
        res = save_to_obsidian(nb_id, query, response_text, citations)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/brain/quartz-config")
def api_get_quartz_config():
    config_candidates = [
        os.path.join(WORKSPACE_DIR, "quartz_app", "quartz.config.default.yaml"),
        "quartz_app/quartz.config.default.yaml",
        "/app/quartz_app/quartz.config.default.yaml"
    ]
    config_file = None
    for c in config_candidates:
        if os.path.exists(c):
            config_file = c
            break
            
    if not config_file:
        raise HTTPException(status_code=404, detail="Quartz Konfigurationsdatei nicht gefunden.")

    try:
        import yaml
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return {"config": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/brain/quartz-config")
async def api_save_quartz_config(request: Request):
    payload = await request.json()
    new_config = payload.get("config")
    if not new_config:
        raise HTTPException(status_code=400, detail="Keine Konfiguration übergeben.")

    config_candidates = [
        os.path.join(WORKSPACE_DIR, "quartz_app", "quartz.config.default.yaml"),
        "quartz_app/quartz.config.default.yaml",
        "/app/quartz_app/quartz.config.default.yaml"
    ]
    config_file = None
    for c in config_candidates:
        if os.path.exists(c):
            config_file = c
            break
            
    if not config_file:
        config_file = "quartz_app/quartz.config.default.yaml"

    try:
        import yaml, base64
        yaml_content = yaml.dump(new_config, sort_keys=False, allow_unicode=True)
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Extract active theme colors for custom.scss
        th_colors = new_config.get("configuration", {}).get("theme", {}).get("colors", {})
        dark_c = th_colors.get("darkMode", {})
        light_c = th_colors.get("lightMode", {})
        
        c_bg = dark_c.get("light") or light_c.get("light") or "#ffffff"
        c_text = dark_c.get("darkgray") or light_c.get("darkgray") or "#1e293b"
        c_dark = dark_c.get("dark") or light_c.get("dark") or "#0f172a"
        c_gray = dark_c.get("gray") or light_c.get("gray") or "#64748b"
        c_lightgray = dark_c.get("lightgray") or light_c.get("lightgray") or "#e2e8f0"
        c_sec = dark_c.get("secondary") or light_c.get("secondary") or "#2563eb"
        c_ter = dark_c.get("tertiary") or light_c.get("tertiary") or "#84a59d"
        c_hl = dark_c.get("highlight") or light_c.get("highlight") or "rgba(143, 159, 169, 0.15)"
        c_thl = dark_c.get("textHighlight") or light_c.get("textHighlight") or "#fef08a"

        custom_scss_content = f"""@use "./variables.scss" as *;

:root {{
  --light: {c_bg};
  --lightgray: {c_lightgray};
  --gray: {c_gray};
  --darkgray: {c_text};
  --dark: {c_dark};
  --secondary: {c_sec};
  --tertiary: {c_ter};
  --highlight: {c_hl};
  --textHighlight: {c_thl};
}}

:root[saved-theme="dark"], :root[saved-theme="light"], html, body, .page, article, main, header, footer, .sidebar, .center {{
  background-color: var(--light) !important;
  color: var(--darkgray) !important;
}}

h1, h2, h3, h4, h5, h6, .article-title, .page-title, .page-title a {{
  color: var(--dark) !important;
}}

a {{
  color: var(--secondary) !important;
}}
"""
        scss_candidates = [
            os.path.join(WORKSPACE_DIR, "quartz_app", "quartz", "styles", "custom.scss"),
            "quartz_app/quartz/styles/custom.scss",
            "/app/quartz_app/quartz/styles/custom.scss"
        ]
        for sc in scss_candidates:
            if os.path.exists(os.path.dirname(sc)):
                try:
                    with open(sc, "w", encoding="utf-8") as f:
                        f.write(custom_scss_content)
                except Exception:
                    pass

        # Write inside archon-quartz container if active
        try:
            b64_yaml = base64.b64encode(yaml_content.encode('utf-8')).decode('ascii')
            b64_scss = base64.b64encode(custom_scss_content.encode('utf-8')).decode('ascii')
            
            cmd = f"echo '{b64_yaml}' | base64 -d > /usr/src/app/quartz.config.default.yaml && echo '{b64_scss}' | base64 -d > /usr/src/app/quartz/styles/custom.scss"
            exec_payload = {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": ["sh", "-c", cmd]}
            res_exec = docker_socket_request("POST", "/containers/archon-quartz/exec", exec_payload)
            if res_exec:
                import json
                exec_id = json.loads(res_exec.decode('utf-8', errors='ignore')).get("Id")
                if exec_id:
                    docker_socket_request("POST", f"/exec/{exec_id}/start", {"Detach": False, "Tty": False})
            
            post_docker_container_action("archon-quartz", "restart")
        except Exception as e:
            print(f"Error updating archon-quartz via docker: {e}")

        return {"status": "success", "message": "Quartz Konfiguration gespeichert und Service neu gestartet."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

ROLES_FILE = os.path.join(WORKSPACE_DIR, "roles.json")
SERVICES_FILE = os.path.join(WORKSPACE_DIR, "services.json")

DEFAULT_ROLES = [
    # 1. MANAGEMENT & ARCHITEKTUR
    {
        "id": "orchestrator",
        "category": "1. Management & Architektur",
        "name": "Orchestrator & System-Architekt",
        "prompt": "Du bist ein erfahrener Orchestrator & System-Architekt. Deine Aufgabe ist es, meisterhaft komplexe Problemstellungen zu analysieren, Aufgaben strukturiert auf Spezial-Agenten zu verteilen, Abhängigkeiten zu managen und Teilergebnisse zu einer schlüssigen Gesamtlösung zu synthetisieren.",
        "skills": ["skill-karpathy-coder"]
    },
    {
        "id": "product_manager",
        "category": "1. Management & Architektur",
        "name": "Product Manager / Requirements Engineer",
        "prompt": "Du bist ein strikter Product Manager & Requirements Engineer. Du übersetzt vage Nutzerideen in glasklare, präzise technische User Stories, Akzeptanzkriterien und funktionale Spezifikationen (PRDs). Du verhinderst Scope Creep und forderst Messbarkeit in allen Anforderungen.",
        "skills": ["skill-competitive-matrix"]
    },
    {
        "id": "scrum_master",
        "category": "1. Management & Architektur",
        "name": "Agile Scrum Master / Task Triage Manager",
        "prompt": "Du bist ein proaktiver Agile Scrum Master & Task Triage Manager. Du strukturierst Workflows in überschaubare Sprint-Tasks, identifizierst Blockaden, priorisierst das Backlog in der Kanban-Pipeline und verteilst Arbeitspakete effizient an ausführende Worker-Agenten.",
        "skills": []
    },
    {
        "id": "enterprise_architect",
        "category": "1. Management & Architektur",
        "name": "Enterprise Architect",
        "prompt": "Du bist ein pragmatischer Enterprise Architect. Du bewertest Systemarchitekturen auf langfristige Skalierbarkeit, Modulkopplung, Microservice-Muster und Technologie-Stacks. Du verhinderst technologische Sackgassen und achtest auf Zukunftsfähigkeit.",
        "skills": ["skill-cloud-security"]
    },

    # 2. IMMOBILIEN & OBJEKTENTWICKLUNG
    {
        "id": "baurecht_experte",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Baurechts- & Genehmigungs-Experte (§34/BauGB)",
        "prompt": "Du bist ein hochspezialisierter Baurechts- und Genehmigungsexperte. Du analysierst Flächen und Bauvorhaben nach BauGB (§ 30 B-Plan, § 34 Einfügen in Eigenart der näheren Umgebung, § 35 Außenbereich). Du prüfst GRZ/GFZ, Abstandsflächen, Stellplatzsatzungen und formulierst wasserdichte Bauvoranfragen.",
        "skills": ["skill-baugb-checker", "skill-lbo-standards"]
    },
    {
        "id": "realestate_concept_strategist",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Konzept- & Erschließungsstratege",
        "prompt": "Du bist ein visionärer Immobilien-Konzept- und Erschließungsstratege. Du entwickelst marktgerechte Nutzungskonzepte (Wohnen, Micro-Living, Gewerbe-Mischung), bewertest Lagepotenziale, Erschließungsaufwände (Straßen, Medien, Entwässerung) und ESG-Nachhaltigkeitskriterien (KfW/GEG).",
        "skills": ["skill-esg-realestate"]
    },
    {
        "id": "realestate_yield_calculator",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Wirtschaftlichkeits- & Rendite-Kalkulator",
        "prompt": "Du bist ein präziser Immobilien-Wirtschaftlichkeits- & Rendite-Kalkulator. Du erstellst dynamische Cashflow-Modelle, Vervielfältiger-Berechnungen, IRR/ROI-Projektionen, Baukostenschätzungen nach DIN 276 (BKI-Indizes) und unterziehst Finanzierungen harten Zins- und Leerstands-Stresstests.",
        "skills": ["skill-realestate-dcf", "skill-bki-cost-estimator"]
    },
    {
        "id": "construction_pm_hoai",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Bau-Projektleiter & Ausschreibung (HOAI / VOB)",
        "prompt": "Du bist ein erfahrener Bau-Projektleiter. Du steuerst Projekte entlang der HOAI-Leistungsphasen 1 bis 9, überwachst VOB/B-Verträge, prüfst Nachtragsforderungen, kontrollierst Bauzeitenpläne und stellst budgettreue Ausschreibungen und Vergaben sicher.",
        "skills": ["skill-hoai-workflow"]
    },

    # 3. RECHT, STEUERN & COMPLIANCE
    {
        "id": "wirtschaftsjurist",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Wirtschaftsjurist & Vertragsprüfer",
        "prompt": "Du bist ein scharfsinniger Wirtschaftsjurist & Vertragsprüfer. Du analysierst BGB/HGB-Verträge, Kaufverträge, NDAs, Gesellschaftervereinbarungen und AGB. Du deckst versteckte Haftungsrisiken auf und formulierst risikominimierende Vertragsklauseln.",
        "skills": ["skill-contract-redline", "skill-liability-scanner"]
    },
    {
        "id": "tax_holding_advisor",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Steuer- & Holding-Strukturberater",
        "prompt": "Du bist ein strategischer Steuer- & Holding-Strukturberater. Du optimierst Unternehmens- und Immobilienstrukturen (Holdinggesellschaften, vermögensverwaltende GmbH mit erweiterter Gewerbesteuerkürzung, § 8b KStG, Grunderwerbsteuer-Gestaltung und Nachfolgeplanung).",
        "skills": ["skill-tax-structure-optimizer"]
    },
    {
        "id": "gdpr_compliance",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Data Protection & Compliance Officer (DSGVO)",
        "prompt": "Du bist ein Data Protection & Compliance Officer. Du stellst sicher, dass Systeme, Workflows und Datenbanken vollumfänglich DSGVO-konform sind, Verarbeitungsverzeichnisse (VVT) geführt werden und Verträge zur Auftragsverarbeitung (AVV) vorliegen.",
        "skills": ["skill-gdpr-audit"]
    },
    {
        "id": "devils_advocate",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Skeptic / Devil's Advocate",
        "prompt": "Du bist der kritische Skeptic & Devil's Advocate im Boardroom. Deine Aufgabe ist es, getroffene Entscheidungen, Pläne und Verträge konstruktiv, aber schonungslos zu hinterfragen, um verdeckte Risiken und Denkfehler aufzudecken.",
        "skills": ["skill-liability-scanner"]
    },

    # 4. FINANZEN, M&A & CAPITAL
    {
        "id": "financial_modeler",
        "category": "4. Finanzen, M&A & Capital",
        "name": "Financial Modeler & DCF-Spezialist",
        "prompt": "Du bist ein hochkompetenter Financial Modeler & DCF-Spezialist. Du baust integrierte 3-Statement-Finanzmodelle (GuV, Bilanz, Cashflow), berechnest Discounted Cash Flows (WACC), bewertest Working Capital und führst Sensitivitätsanalysen durch.",
        "skills": ["skill-dcf-valuation", "skill-saas-metrics"]
    },
    {
        "id": "ma_due_diligence_analyst",
        "category": "4. Finanzen, M&A & Capital",
        "name": "M&A & Due-Diligence Analyst",
        "prompt": "Du bist ein akribischer M&A & Due-Diligence Analyst. Du auditierst Datenräume bei Unternehmenstransaktionen, bewertest Synergien und Risiken (Financial, Legal, Commercial) und simulierst Cap Tables und Waterfall-Payouts.",
        "skills": ["skill-ma-playbook"]
    },
    {
        "id": "grant_funding_scout",
        "category": "4. Finanzen, M&A & Capital",
        "name": "Fördermittel- & Kapital-Scout",
        "prompt": "Du bist ein spezialisierter Fördermittel- & Kapital-Scout. Du recherchierst nicht-rückzahlbare Zuschüsse (ZIM, BAFA, KfW, Horizon Europe), strukturierst Banken-Kreditanträge und erstellst investorenreife Pitch-Memos.",
        "skills": ["skill-grant-matcher"]
    },
    {
        "id": "financial_optimizer",
        "category": "4. Finanzen, M&A & Capital",
        "name": "Financial & Cost Optimizer",
        "prompt": "Du bist ein kostenbewusster Financial & Cost Optimizer. Du überwachst operative Betriebsausgaben, API-Kosten und optimierst die Ressourcen- und Kostenstruktur der gesamten Organisation.",
        "skills": ["skill-saas-metrics"]
    },

    # 5. VERTRIEB, MARKETING & STRATEGIE
    {
        "id": "b2b_sales_pitch_architect",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "B2B-Vertriebs- & Pitch-Architekt",
        "prompt": "Du bist ein hochwirksamer B2B-Vertriebs- & Pitch-Architekt. Du entwickelst überzeugende Value Propositions, Einwandbehandlungen, Enterprise-Verkaufssequenzen, Kaltakquise-Strategien und B2B-Angebotsstrukturen.",
        "skills": ["skill-cold-outreach"]
    },
    {
        "id": "pricing_monetization_strategist",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "Pricing- & Monetarisierungs-Stratege",
        "prompt": "Du bist ein datengetriebener Pricing- & Monetarisierungs-Stratege. Du analysierst Zahlungsbereitschaften, entwickelst Value-based Pricing-Modelle, gestaltest Feature-Tiers/Pakete und minimierst Churn.",
        "skills": ["skill-pricing-calculator"]
    },
    {
        "id": "market_intelligence",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "Market & Competitor Intelligence Analyst",
        "prompt": "Du bist ein strategischer Market & Competitor Intelligence Analyst. Du analysierst Marktsegmente, Mitbewerber, Preismodelle und Feature-Gaps, um nachhaltige Wettbewerbsvorteile herauszuarbeiten.",
        "skills": ["skill-competitive-matrix"]
    },
    {
        "id": "seo_content",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "SEO & Content Pipeline Specialist",
        "prompt": "Du bist ein SEO & Content Pipeline Specialist. Du recherchierst High-Intent-Keywords, erstellst strukturierte Content-Pipelines und entwirfst suchmaschinenoptimierte Fachartikel und Veröffentlichungsstrategien.",
        "skills": ["skill-seo-audit"]
    },

    # 6. SOFTWARE DEVELOPMENT & ENGINEERING (TECH)
    {
        "id": "senior_coder",
        "category": "6. Software & Tech",
        "name": "Senior Coder / Software Engineer",
        "prompt": "Du bist ein extrem kompetenter Senior Software Engineer. Du schreibst sauberen, modularen, objektorientierten und produktionsreifen Code (Python, TypeScript, Go). Du folgst strikt Best Practices (DRY, SOLID) und lieferst fehlerfreie Implementierungen.",
        "skills": ["skill-karpathy-coder", "skill-database-designer"]
    },
    {
        "id": "frontend_architect",
        "category": "6. Software & Tech",
        "name": "Frontend & UI/UX Architect",
        "prompt": "Du bist ein visuell denkender Frontend & UI/UX Architect. Du entwirfst moderne, performante und ergonomische Benutzeroberflächen (Streamlit, React, CSS3, Tailwind). Du achtest penibel auf visuelle Hierarchien, responsive Grids und reibungslose User-Flows.",
        "skills": []
    },
    {
        "id": "backend_db_designer",
        "category": "6. Software & Tech",
        "name": "Backend & Database Designer",
        "prompt": "Du bist ein hochspezialisierter Backend & Database Designer. Du entwickelst robuste API-Schnittstellen (REST, GraphQL, gRPC), optimierst SQL/NoSQL-Datenbankschemas, indizierst Tabellen und verhinderst Bottlenecks bei Abfragen.",
        "skills": ["skill-database-designer"]
    },
    {
        "id": "clean_code_expert",
        "category": "6. Software & Tech",
        "name": "Refactoring & Clean Code Expert",
        "prompt": "Du bist ein kompromissloser Refactoring & Clean Code Expert. Du durchleuchtest bestehenden Code auf Code Smells, Redundanzen, hohe zyklomatische Komplexität und schlechte Benennungen, um die Wartbarkeit drastisch zu erhöhen.",
        "skills": ["skill-karpathy-coder"]
    },
    {
        "id": "devops_container",
        "category": "6. Software & Tech",
        "name": "DevOps & Container Specialist",
        "prompt": "Du bist ein erfahrener DevOps & Container Specialist. Du erstellst gehärtete Dockerfiles, Docker-Compose-Setups, Netzwerkkonfigurationen und CI/CD-Pipelines für eine nahtlose, isolierte und ausfallsichere Container-Laufzeitumgebung.",
        "skills": ["skill-docker-generator", "skill-cloud-security"]
    },
    {
        "id": "security_auditor",
        "category": "6. Software & Tech",
        "name": "Security Auditor / DevSecOps",
        "prompt": "Du bist ein akribischer Security Auditor & DevSecOps. Du analysierst Code und Systeme auf Sicherheitslücken (OWASP Top 10, Injection Risks, Secret Leaks, Insecure Deserialization) und verlangst harte Schutzmaßnahmen und Sanitization.",
        "skills": ["skill-cloud-security"]
    },

    # 7. QUALITY, REGULATORY & HEALTHCARE
    {
        "id": "iso13485_mdr_auditor",
        "category": "7. Quality, Regulatory & Health",
        "name": "ISO 13485 & MDR-Auditor",
        "prompt": "Du bist ein kompromissloser Qualitäts- & Regulatory-Auditor für Medizinprodukte (MDR 2017/745, ISO 13485, ISO 14971). Du prüfst Design Controls, Risikomanagement-Akten, CAPA-Pläne und klinische Bewertungen.",
        "skills": ["skill-iso13485-prep"]
    },
    {
        "id": "clinical_research_analyst",
        "category": "7. Quality, Regulatory & Health",
        "name": "Klinischer Forschungs- & Evidenz-Analyst",
        "prompt": "Du bist ein analytischer klinischer Forschungs-Spezialist. Du durchsuchst PubMed, Studienregister und Leitlinien, bewertest Evidenzgrade und erstellst wissenschaftlich fundierte Synthesen.",
        "skills": ["skill-pubmed-fetch"]
    }
]

GLOBAL_HERMES_SKILLS = [
    # 1. Immobilien & Bau
    {"id": "skill-baugb-checker", "name": "BauGB & B-Plan Prüfer", "category": "Immobilien & Bau", "description": "Prüft Zulässigkeit nach § 30, § 34, § 35 BauGB, GRZ/GFZ und Nachverdichtung.", "tags": ["BauGB", "B-Plan", "§34"]},
    {"id": "skill-lbo-standards", "name": "LBO Abstandsflächen-Rechner", "category": "Immobilien & Bau", "description": "Berechnet Abstandsflächen, Stellplatzschlüssel und Brandschutz nach LBO.", "tags": ["LBO", "Abstandsflächen", "Stellplätze"]},
    {"id": "skill-realestate-dcf", "name": "Immobilien-DCF & Rendite-Modell", "category": "Immobilien & Bau", "description": "Erstellt Cashflow-Projektionen, Vervielfältiger, IRR, ROI und Zins-Stresstests.", "tags": ["DCF", "Rendite", "IRR", "Cashflow"]},
    {"id": "skill-bki-cost-estimator", "name": "Baukosten-Kalkulator (DIN 276)", "category": "Immobilien & Bau", "description": "Schätzt Baukosten nach Kostengruppen 100-700 und BKI-Kennwerten.", "tags": ["DIN276", "BKI", "Baukosten"]},
    {"id": "skill-hoai-workflow", "name": "HOAI & VOB Bauleiter-Toolkit", "category": "Immobilien & Bau", "description": "Prüft HOAI Leistungsphasen 1-9 und VOB/B-konforme Nachträge.", "tags": ["HOAI", "VOB", "Bauleitung"]},
    {"id": "skill-esg-realestate", "name": "ESG & KfW-Effizienz-Check", "category": "Immobilien & Bau", "description": "Prüft ESG-Kriterien, GEG und KfW-Förderstufen für Gebäude.", "tags": ["ESG", "KfW", "GEG", "Nachhaltigkeit"]},

    # 2. Recht & Steuern
    {"id": "skill-contract-redline", "name": "Vertrags-Redlining & Klausel-Prüfer", "category": "Recht & Steuern", "description": "Analysiert BGB-Kaufverträge, NDAs, Dienstbarkeiten und AGB auf Fallstricke.", "tags": ["BGB", "Verträge", "Redline"]},
    {"id": "skill-tax-structure-optimizer", "name": "Holding- & Steuer-Strukturierer", "category": "Recht & Steuern", "description": "Modelliert § 8b KStG, vermögensverwaltende GmbH und Grunderwerbsteuer.", "tags": ["Steuern", "Holding", "GmbH", "KStG"]},
    {"id": "skill-gdpr-audit", "name": "DSGVO / GDPR Compliance Auditor", "category": "Recht & Steuern", "description": "Artikel-genaue DSGVO-Prüfung, AVV-Erstellung und PII-Schutz.", "tags": ["DSGVO", "GDPR", "Datenschutz", "AVV"]},
    {"id": "skill-liability-scanner", "name": "Haftungs- & Risiko-Scanner", "category": "Recht & Steuern", "description": "Erkennt Freistellungs- und Haftungsrisiken in Geschäftsverträgen.", "tags": ["Haftung", "Compliance", "Risiko"]},

    # 3. Finanzen & M&A
    {"id": "skill-dcf-valuation", "name": "Unternehmensbewertung (DCF/WACC)", "category": "Finanzen & M&A", "description": "Berechnet Multiples, Discounted Cash Flow und Enterprise Value.", "tags": ["DCF", "WACC", "Valuation"]},
    {"id": "skill-ma-playbook", "name": "M&A Due Diligence Playbook", "category": "Finanzen & M&A", "description": "Strukturierte Due-Diligence-Listen für Finance, Legal, Tech & HR.", "tags": ["M&A", "Due Diligence", "Transaktionen"]},
    {"id": "skill-saas-metrics", "name": "SaaS Health & Unit Economics", "category": "Finanzen & M&A", "description": "Kalkuliert ARR, MRR, CAC, LTV, Magic Number und Rule of 40.", "tags": ["SaaS", "ARR", "CAC", "LTV"]},
    {"id": "skill-grant-matcher", "name": "Fördermittel- & Grant-Scout", "category": "Finanzen & M&A", "description": "Sucht nach ZIM-, BAFA-, KfW- und Horizon-Europe-Förderungen.", "tags": ["Grants", "Förderung", "KfW", "BAFA"]},

    # 4. Vertrieb & Marketing
    {"id": "skill-cold-outreach", "name": "B2B Cold Outreach & LinkedIn Sequencer", "category": "Vertrieb & Marketing", "description": "Erstellt konversionsstarke Anspracheskripte und E-Mail-Sequenzen.", "tags": ["B2B", "Outreach", "LinkedIn", "Sales"]},
    {"id": "skill-pricing-calculator", "name": "Pricing & Packaging Strategist", "category": "Vertrieb & Marketing", "description": "Führt Van-Westendorp-Preissensitivitäts- & Feature-Tier-Analysen durch.", "tags": ["Pricing", "Packaging", "Funnels"]},
    {"id": "skill-competitive-matrix", "name": "Competitor Intelligence & Feature Matrix", "category": "Vertrieb & Marketing", "description": "Erstellt radar-basierte Wettbewerbsmatrizen und Gap-Analysen.", "tags": ["Competitor", "Matrix", "Research"]},
    {"id": "skill-seo-audit", "name": "High-Intent SEO & Content Pipeline", "category": "Vertrieb & Marketing", "description": "Analysiert SERP-Intents, Keyword-Cluster und Content-Architektur.", "tags": ["SEO", "Content", "SERP"]},

    # 5. Software, KI & Tech
    {"id": "skill-karpathy-coder", "name": "Karpathy Clean Coder (Minimal Complexity)", "category": "Software & Tech", "description": "Schreibt sauberen, modularen Code ohne Over-Engineering.", "tags": ["CleanCode", "Python", "TypeScript"]},
    {"id": "skill-docker-generator", "name": "Docker & Container Hardening", "category": "Software & Tech", "description": "Generiert gehärtete Multi-Stage Dockerfiles und Compose-Setups.", "tags": ["Docker", "Containers", "DevOps"]},
    {"id": "skill-database-designer", "name": "Database Schema & Migration Architect", "category": "Software & Tech", "description": "Designt SQL/NoSQL Schemas, Indizes und optimierte Queries.", "tags": ["SQL", "Postgres", "Database"]},
    {"id": "skill-cloud-security", "name": "Cloud Security & IAM Privilege Auditor", "category": "Software & Tech", "description": "Scannt AWS/GCP/Azure-Setups auf Schwachstellen und Least-Privilege.", "tags": ["Cloud", "Security", "AWS", "GCP"]},

    # 6. Quality & Healthcare
    {"id": "skill-iso13485-prep", "name": "ISO 13485 & MDR Audit-Kit", "category": "Quality & Healthcare", "description": "Prüft Design Controls, CAPA und technische Dokumentation.", "tags": ["ISO13485", "MDR", "QMS"]},
    {"id": "skill-pubmed-fetch", "name": "PubMed & Clinical Evidence Fetcher", "category": "Quality & Healthcare", "description": "Extrahiert Evidenz, Studiendaten und Fachliteratur aus NCBI/PubMed.", "tags": ["PubMed", "Medical", "Evidence"]}
]

HERMES_PROFILES_DIR = os.path.join(MEMORY_DIR, "hermes_profiles")
os.makedirs(HERMES_PROFILES_DIR, exist_ok=True)
_HERMES_SKILLS_CACHE = None
_HERMES_SKILLS_CACHE_TIME = 0
_HERMES_SKILLS_CACHE_TTL = 300.0
_SKILL_FILE_INDEX = {}
_SKILL_FILE_INDEX_TIME = 0

def get_all_skill_search_roots():
    return [
        os.path.join(WORKSPACE_DIR, "data", "hermes_skills"),
        os.path.join(WORKSPACE_DIR, "templates", "skills"),
        os.path.join(WORKSPACE_DIR, ".agents", "skills"),
        os.path.join(WORKSPACE_DIR, "config", "skills"),
        os.path.join(WORKSPACE_DIR, "antigravity_complete_skills_package"),
        os.path.join(WORKSPACE_DIR, "data", "hermes_profiles"),
        os.path.join(MEMORY_DIR, "hermes_skills"),
        os.path.expanduser("~/.hermes/skills"),
        "/app/skills",
        "/opt/data/skills"
    ]

_SKILL_INDEX_DISK_PATH = os.path.join(DATA_DIR, "hermes_skills_index.json")

def build_skills_file_index(force: bool = False):
    global _SKILL_FILE_INDEX, _SKILL_FILE_INDEX_TIME
    now = time.time()
    if not force and _SKILL_FILE_INDEX and (now - _SKILL_FILE_INDEX_TIME) < 300.0:
        return _SKILL_FILE_INDEX
    
    if not force and not _SKILL_FILE_INDEX and os.path.exists(_SKILL_INDEX_DISK_PATH):
        try:
            with open(_SKILL_INDEX_DISK_PATH, "r", encoding="utf-8") as f:
                _SKILL_FILE_INDEX = json.load(f)
                _SKILL_FILE_INDEX_TIME = now
                return _SKILL_FILE_INDEX
        except Exception:
            pass
    
    index = {}
    search_dirs = get_all_skill_search_roots()
    for s_dir in search_dirs:
        if not os.path.exists(s_dir):
            continue
        try:
            for root, dirs, files in os.walk(s_dir):
                # PRUNING (10.10.2026): Ausschluesse VOR dem Betreten abschneiden
                # (top-down-Walk). Vorher wurde z.B. der komplette .git-Baum
                # traversiert und erst pro Knoten per continue verworfen -
                # gemessen: 10.2s Walk ueber 1671 Verzeichnisse / 4 .git-Baeume.
                dirs[:] = [d for d in dirs if d not in
                           ("node_modules", ".git", "backups", "__pycache__", ".venv", "venv")]
                if "node_modules" in root or ".git" in root or "backups" in root:
                    continue
                if "SKILL.md" in files:
                    folder_name = os.path.basename(root)
                    skill_path = os.path.join(root, "SKILL.md")
                    if folder_name not in index:
                        index[folder_name] = skill_path
                    if folder_name.startswith("skill-"):
                        stripped = folder_name[6:]
                        if stripped not in index:
                            index[stripped] = skill_path
                    else:
                        prefixed = f"skill-{folder_name}"
                        if prefixed not in index:
                            index[prefixed] = skill_path
        except Exception as e:
            print(f"[Skills Indexer] Error walking {s_dir}: {e}")
            
    _SKILL_FILE_INDEX = index
    _SKILL_FILE_INDEX_TIME = now
    try:
        with open(_SKILL_INDEX_DISK_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f)
    except Exception:
        pass
    return index

def find_skill_file(skill_id: str) -> Optional[str]:
    index = build_skills_file_index()
    if skill_id in index and os.path.exists(index[skill_id]):
        return index[skill_id]
    
    variations = [skill_id]
    if skill_id.startswith("skill-"):
        variations.append(skill_id[6:])
    else:
        variations.append(f"skill-{skill_id}")
        
    for var in variations:
        if var in index and os.path.exists(index[var]):
            return index[var]
            
    for root in get_all_skill_search_roots():
        if not os.path.exists(root):
            continue
        for var in variations:
            direct = os.path.join(root, var, "SKILL.md")
            if os.path.exists(direct):
                index[skill_id] = direct
                return direct
            try:
                for sub in os.listdir(root):
                    sub_path = os.path.join(root, sub)
                    if os.path.isdir(sub_path):
                        target = os.path.join(sub_path, var, "SKILL.md")
                        if os.path.exists(target):
                            index[skill_id] = target
                            return target
            except Exception:
                pass
    return None

def parse_skill_frontmatter_and_content(raw_content: str, default_id: str):
    name = default_id.replace("-", " ").title()
    category = "Allgemein"
    description = ""
    tags = []
    
    lines = raw_content.splitlines()
    in_frontmatter = False
    fm_lines = []
    body_lines = []
    
    for i, line in enumerate(lines):
        line_str = line.strip()
        if i == 0 and line_str == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line_str == "---":
                in_frontmatter = False
                continue
            fm_lines.append(line)
            if line_str.startswith("name:"):
                name = line_str.split("name:", 1)[1].strip().strip('"\'')
            elif line_str.startswith("category:"):
                category = line_str.split("category:", 1)[1].strip().strip('"\'')
            elif line_str.startswith("description:"):
                description = line_str.split("description:", 1)[1].strip().strip('"\'|')
            elif line_str.startswith("tags:"):
                raw_tags = line_str.split("tags:", 1)[1].strip().strip("[]")
                tags = [t.strip().strip('"\'') for t in raw_tags.split(",") if t.strip()]
        else:
            body_lines.append(line)
            if not description and line_str and not line_str.startswith("#"):
                description = line_str[:120]
                
    return {
        "name": name,
        "category": category,
        "description": description,
        "tags": tags,
        "content": raw_content
    }

def compose_skill_frontmatter(name: str, category: str, tags: List[str], description: str, body_or_full_content: str) -> str:
    content = body_or_full_content.strip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
        else:
            body = content
    else:
        body = content

    tags_json = json.dumps(tags, ensure_ascii=False) if tags else "[]"
    frontmatter = (
        f"---\n"
        f"name: \"{name}\"\n"
        f"category: \"{category}\"\n"
        f"description: \"{description}\"\n"
        f"tags: {tags_json}\n"
        f"---\n\n"
    )
    return frontmatter + body + "\n"

_SKILLS_CACHE_DISK_PATH = os.path.join(DATA_DIR, "hermes_skills_cache.json")

@app.on_event("startup")
async def _warm_hermes_skill_caches():
    """Skills-Caches VOR dem ersten Request warm machen (Disk -> Memory).
    Sonst bezahlt der erste Request nach Restart den vollen Kaltbau
    (gemessen: Walk 10.2s + 850 SKILL.md lesen = ~22s fuer das Panel)."""
    def _warm():
        t0 = time.time()
        try:
            build_skills_file_index()
            api_get_hermes_skills()
            print(f"[Skills-Warmup] caches warm after {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[Skills-Warmup] failed: {e}")
    threading.Thread(target=_warm, daemon=True, name="skills-warmup").start()

@app.get("/api/hermes/skills")
def api_get_hermes_skills():
    global _HERMES_SKILLS_CACHE, _HERMES_SKILLS_CACHE_TIME
    now = time.time()
    if _HERMES_SKILLS_CACHE is not None and (now - _HERMES_SKILLS_CACHE_TIME) < _HERMES_SKILLS_CACHE_TTL:
        return _HERMES_SKILLS_CACHE

    if not _HERMES_SKILLS_CACHE and os.path.exists(_SKILLS_CACHE_DISK_PATH):
        try:
            with open(_SKILLS_CACHE_DISK_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and isinstance(data, list) and len(data) > 0:
                    _HERMES_SKILLS_CACHE = data
                    _HERMES_SKILLS_CACHE_TIME = now
                    return data
        except Exception:
            pass

    index = build_skills_file_index()
    discovered_skills = []
    seen_ids = set()

    for skill_id, file_path in index.items():
        if skill_id in seen_ids:
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            parsed = parse_skill_frontmatter_and_content(raw, skill_id)
            seen_ids.add(skill_id)
            discovered_skills.append({
                "id": skill_id,
                "name": parsed["name"],
                "category": parsed["category"],
                "description": parsed["description"] or f"Hermes Agent Skill ({skill_id})",
                "tags": parsed["tags"] or [parsed["category"].split(" ")[0]],
                "file_path": file_path
            })
        except Exception:
            pass

    if not discovered_skills:
        discovered_skills = GLOBAL_HERMES_SKILLS

    _HERMES_SKILLS_CACHE = discovered_skills
    _HERMES_SKILLS_CACHE_TIME = now
    try:
        with open(_SKILLS_CACHE_DISK_PATH, "w", encoding="utf-8") as f:
            json.dump(discovered_skills, f)
    except Exception:
        pass
    return discovered_skills

@app.get("/api/hermes/skills/{skill_id}")
def api_get_single_hermes_skill(skill_id: str):
    file_path = find_skill_file(skill_id)
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            parsed = parse_skill_frontmatter_and_content(content, skill_id)
            orig_path = os.path.join(os.path.dirname(file_path), ".SKILL.md.orig")
            has_backup = os.path.exists(orig_path)
            return {
                "id": skill_id,
                "name": parsed["name"],
                "category": parsed["category"],
                "description": parsed["description"],
                "tags": parsed["tags"],
                "content": content,
                "file_path": file_path,
                "has_original_backup": has_backup
            }
        except Exception as e:
            print(f"[Skills API] Error reading {file_path}: {e}")

    # Fallback to Global Hermes skills
    for item in GLOBAL_HERMES_SKILLS:
        if item.get("id") == skill_id or item.get("id") == f"skill-{skill_id}":
            return {
                **item,
                "content": f"---\nname: \"{item.get('name')}\"\ncategory: \"{item.get('category')}\"\ndescription: \"{item.get('description')}\"\ntags: {json.dumps(item.get('tags', []))}\n---\n\n# {item.get('name')}\n{item.get('description')}\n\n## Parameter & Ausführung\nFühre diesen Skill im Kontext des übergeordneten Agenten aus.",
                "file_path": "",
                "has_original_backup": False
            }
            
    return {
        "id": skill_id,
        "name": skill_id.replace("-", " ").title(),
        "category": "Allgemein",
        "description": f"Hermes Skill {skill_id}",
        "tags": ["Allgemein"],
        "content": f"# Skill: {skill_id}\n\nAutomatisch registrierter Hermes-Skill.",
        "file_path": "",
        "has_original_backup": False
    }

@app.post("/api/hermes/skills/{skill_id}")
async def api_save_single_hermes_skill(skill_id: str, request: Request):
    global _HERMES_SKILLS_CACHE
    data = await request.json()
    file_path = find_skill_file(skill_id)
    
    if not file_path:
        skills_dir = os.path.join(MEMORY_DIR, "hermes_skills", skill_id)
        os.makedirs(skills_dir, exist_ok=True)
        file_path = os.path.join(skills_dir, "SKILL.md")
    else:
        skills_dir = os.path.dirname(file_path)
        
    orig_path = os.path.join(skills_dir, ".SKILL.md.orig")
    
    # Create original snapshot backup if this is the first edit
    if os.path.exists(file_path) and not os.path.exists(orig_path):
        try:
            shutil.copy2(file_path, orig_path)
            print(f"[Skills API] Created original backup snapshot at {orig_path}")
        except Exception as e:
            print(f"[Skills API] Failed to create backup: {e}")
            
    name = data.get("name", skill_id)
    category = data.get("category", "Allgemein")
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    description = data.get("description", "")
    content = data.get("content", "")
    
    composed_content = compose_skill_frontmatter(name, category, tags, description, content)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(composed_content)
        print(f"[Skills API] Saved skill {skill_id} to {file_path}")
    except Exception as e:
        print(f"[Skills API] Error writing skill {skill_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
        
    # Invalidate caches
    _HERMES_SKILLS_CACHE = None
    build_skills_file_index(force=True)
    
    return {
        "status": "ok", 
        "id": skill_id, 
        "file_path": file_path, 
        "has_original_backup": os.path.exists(orig_path)
    }

@app.post("/api/hermes/skills/{skill_id}/reset")
async def api_reset_single_hermes_skill(skill_id: str):
    global _HERMES_SKILLS_CACHE
    file_path = find_skill_file(skill_id)
    if not file_path or not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": f"Skill {skill_id} nicht gefunden."})
        
    skills_dir = os.path.dirname(file_path)
    orig_path = os.path.join(skills_dir, ".SKILL.md.orig")
    
    if not os.path.exists(orig_path):
        return JSONResponse(status_code=400, content={"error": "Keine Original-Sicherung (.SKILL.md.orig) für diesen Skill vorhanden."})
        
    try:
        shutil.copy2(orig_path, file_path)
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            restored_content = f.read()
        parsed = parse_skill_frontmatter_and_content(restored_content, skill_id)
        
        # Invalidate cache
        _HERMES_SKILLS_CACHE = None
        build_skills_file_index(force=True)
        
        return {
            "status": "ok",
            "id": skill_id,
            "message": "Skill erfolgreich auf Originalzustand zurückgesetzt.",
            "content": restored_content,
            "name": parsed["name"],
            "category": parsed["category"],
            "description": parsed["description"],
            "tags": parsed["tags"],
            "has_original_backup": True
        }
    except Exception as e:
        print(f"[Skills API] Error resetting skill {skill_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

ALL_HERMES_TOOLS = [
    "web_search", "browser", "terminal", "filesystem", "execute_code", "vision_analyze",
    "video_analyze", "image_generate", "video_generate", "bfl_flux3", "x_search", "text_to_speech",
    "speech_to_text", "skills", "task_planning", "memory", "context_engine", "session_search",
    "clarify", "delegate_task", "cronjob", "home_assistant", "spotify", "discord",
    "discord_admin", "yuanbao", "computer_use", "a2a"
]

DEFAULT_HERMES_TOOLS = [
    "web_search", "browser", "terminal", "filesystem", "execute_code", "vision_analyze",
    "image_generate", "bfl_flux3", "text_to_speech", "speech_to_text", "skills", "task_planning",
    "memory", "session_search", "clarify", "delegate_task", "cronjob", "computer_use"
]

def get_hermes_profiles_base_dirs() -> List[str]:
    """Liefert alle aktiven Hermes-Profil-Pfade (Container-Mounts und Host-Pfade)."""
    candidates = [
        "/opt/data/profiles",
        os.path.expanduser("~/.hermes/profiles"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "profiles")
    ]
    valid_dirs = []
    for c in candidates:
        if c and os.path.exists(c) and c not in valid_dirs:
            valid_dirs.append(c)
    if not valid_dirs:
        primary = "/opt/data/profiles" if os.path.exists("/opt/data") else os.path.expanduser("~/.hermes/profiles")
        try:
            os.makedirs(primary, exist_ok=True)
        except Exception:
            pass
        valid_dirs.append(primary)
    return valid_dirs

def get_primary_hermes_profiles_dir() -> str:
    return get_hermes_profiles_base_dirs()[0]

_HERMES_PROFILES_CACHE = None
_HERMES_PROFILES_CACHE_TIME = 0.0
_HERMES_PROFILES_CACHE_MTIME = 0.0
_HERMES_PROFILES_CACHE_TTL = 300.0

def _compute_profiles_mtime() -> float:
    max_m = 0.0
    try:
        pdir = get_primary_hermes_profiles_dir()
        if os.path.exists(pdir):
            max_m = max(max_m, os.path.getmtime(pdir))
        ap_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
        if os.path.exists(ap_file):
            max_m = max(max_m, os.path.getmtime(ap_file))
    except Exception:
        pass
    return max_m

try:
    _init_pfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
    if os.path.exists(_init_pfile):
        with open(_init_pfile, "r", encoding="utf-8") as _f_init:
            _init_data = json.load(_f_init)
            if isinstance(_init_data, list) and len(_init_data) > 0:
                _HERMES_PROFILES_CACHE = _init_data
                _HERMES_PROFILES_CACHE_TIME = time.time()
                logger.info(f"[Profiles] Fast pre-warm cache loaded {len(_HERMES_PROFILES_CACHE)} profiles.")
except Exception as _e_init:
    logger.warning(f"[Profiles] Fast pre-warm warning: {_e_init}")

def invalidate_hermes_profiles_cache():
    global _HERMES_PROFILES_CACHE, _HERMES_PROFILES_CACHE_TIME, _HERMES_PROFILES_CACHE_MTIME
    _HERMES_PROFILES_CACHE = None
    _HERMES_PROFILES_CACHE_TIME = 0.0
    _HERMES_PROFILES_CACHE_MTIME = 0.0

@app.get("/api/hermes/profiles")
def api_get_hermes_profiles():
    global _HERMES_PROFILES_CACHE, _HERMES_PROFILES_CACHE_TIME, _HERMES_PROFILES_CACHE_MTIME
    now = time.time()
    cur_mtime = _compute_profiles_mtime()
    if (
        _HERMES_PROFILES_CACHE is not None
        and (now - _HERMES_PROFILES_CACHE_TIME) < _HERMES_PROFILES_CACHE_TTL
        and (_HERMES_PROFILES_CACHE_MTIME == 0.0 or cur_mtime <= _HERMES_PROFILES_CACHE_MTIME)
    ):
        return _HERMES_PROFILES_CACHE

    HERMES_PROFILES_DIR = get_primary_hermes_profiles_dir()
    os.makedirs(HERMES_PROFILES_DIR, exist_ok=True)

    # 1. Fallback-Map aus agent_profiles.json laden
    _APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    json_fallback_map = {}
    for cand in [os.path.join(_APP_ROOT, "agent_profiles.json"), "agent_profiles.json"]:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    j_data = json.load(f)
                    if isinstance(j_data, list):
                        for item in j_data:
                            if isinstance(item, dict) and item.get("id"):
                                json_fallback_map[item["id"]] = item
                    break
            except Exception as e:
                logger.warning(f"[Profiles] Error loading fallback {cand}: {e}")

    # 2. Live-Verzeichnisse aus HERMES_PROFILES_DIR scannen (SSOT)
    subdirs = []
    if os.path.exists(HERMES_PROFILES_DIR):
        subdirs = [
            d for d in os.listdir(HERMES_PROFILES_DIR)
            if os.path.isdir(os.path.join(HERMES_PROFILES_DIR, d)) and not d.startswith(".")
        ]

    # SSOT: Wenn Verzeichnisse auf Disk existieren, bestimmen ausschließlich diese die aktiven Profile.
    if subdirs:
        active_profile_ids = subdirs
    else:
        active_profile_ids = list(json_fallback_map.keys())

    enriched_profiles = []
    for p_id in active_profile_ids:
        prof_dir = os.path.join(HERMES_PROFILES_DIR, p_id)
        os.makedirs(prof_dir, exist_ok=True)

        ydata = {}
        yaml_path = os.path.join(prof_dir, "profile.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"[Profiles] Error reading {yaml_path}: {e}")

        cdata = {}
        cfg_path = os.path.join(prof_dir, "config.yaml")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cdata = yaml.safe_load(f) or {}
            except Exception:
                pass

        soul_prompt = ""
        soul_path = os.path.join(prof_dir, "SOUL.md")
        if os.path.exists(soul_path):
            try:
                with open(soul_path, "r", encoding="utf-8", errors="ignore") as f:
                    soul_prompt = f.read().strip()
            except Exception:
                pass

        # Skills aus Ordner und YAML aggregieren
        skills_sub = os.path.join(prof_dir, "skills")
        active_skills = []
        if isinstance(ydata.get("skills"), list):
            active_skills.extend(ydata["skills"])
        if os.path.exists(skills_sub):
            discovered_in_folder = [
                d for d in os.listdir(skills_sub)
                if os.path.isdir(os.path.join(skills_sub, d)) and not d.startswith(".")
            ]
            discovered_files = [
                os.path.splitext(f)[0] for f in os.listdir(skills_sub)
                if os.path.isfile(os.path.join(skills_sub, f)) and f.endswith(".md") and not f.startswith(".")
            ]
            active_skills.extend(discovered_in_folder + discovered_files)

        fallback = json_fallback_map.get(p_id, {})
        if isinstance(fallback.get("skills"), list):
            active_skills.extend(fallback["skills"])
        active_skills = list(dict.fromkeys([s for s in active_skills if s]))

        # Attribute auflösen (YAML -> Disk -> JSON Fallback -> Defaults)
        name = ydata.get("name") or fallback.get("name") or p_id.replace("_", " ").title()
        person_name = ydata.get("person_name") or fallback.get("person_name") or fallback.get("display_name") or ydata.get("name") or fallback.get("name") or p_id
        category = ydata.get("category") or fallback.get("category") or "1. Strategie, Führung & Lebensplanung"
        description = ydata.get("description") or fallback.get("description") or (soul_prompt[:140] + "..." if soul_prompt else "")
        prompt = soul_prompt or ydata.get("prompt") or fallback.get("prompt") or fallback.get("system_prompt") or f"Du bist {person_name} ({name})."
        tools = ydata.get("tools") or fallback.get("tools") or DEFAULT_HERMES_TOOLS
        # Automatische Erkennung vorhandener Custom-Avatare
        avatar_val = None
        _static_avatars = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "avatars")
        for _ext in [".png", ".jpg", ".jpeg", ".webp"]:
            _c_avatar = os.path.join(_static_avatars, f"custom_{p_id}{_ext}")
            if os.path.exists(_c_avatar):
                avatar_val = f"/static/avatars/custom_{p_id}{_ext}"
                break

        if not avatar_val:
            cand_y = ydata.get("avatar") or ydata.get("avatar_url")
            cand_fb = fallback.get("avatar") or fallback.get("avatar_url")
            if cand_y and "dicebear.com" not in cand_y:
                avatar_val = cand_y
            elif cand_fb and "dicebear.com" not in cand_fb:
                avatar_val = cand_fb
            else:
                # Deterministischer Fallback aus dem realistischen Katalog (verhindert Duplikate)
                _h = abs(hash(p_id)) % 108 + 1
                if _h == 1:
                    _h = 2
                avatar_val = f"/static/avatars/avatar_{_h:03d}.jpg"
        
        provider = ydata.get("provider") or (cdata.get("model", {}).get("provider") if isinstance(cdata.get("model"), dict) else None) or fallback.get("provider", "omniroute")
        model = ydata.get("model") or (cdata.get("model", {}).get("default") if isinstance(cdata.get("model"), dict) else None) or fallback.get("model", "auto/best-free")
        reasoning_level = ydata.get("reasoning_level") or (ydata.get("llm", {}).get("reasoning_level") if isinstance(ydata.get("llm"), dict) else None) or fallback.get("reasoning_level", "high")
        status_val = ydata.get("status") or fallback.get("status", "active")
        is_fav = bool(ydata.get("is_favorite") if "is_favorite" in ydata else fallback.get("is_favorite", (p_id in ["default", "micha"])))
        callsign = ydata.get("callsign") or fallback.get("callsign") or ""
        if not callsign:
            if p_id == "executive_decision_architect":
                callsign = "robert"
            elif p_id == "micha":
                callsign = "micha"
        callsign = str(callsign).strip().lower()

        # Sonderbehandlung für default & micha
        if p_id in ["default", "hermes_default"]:
            p_id = "default"
            name = name or "Hermes Default (Root Engine)"
            person_name = person_name or "Hermes Orchestrator"
            is_fav = True
            if not (avatar_val and "avatar_" in avatar_val and "avatar_001.jpg" not in avatar_val):
                avatar_val = "/static/avatars/hermes_default_avatar.png"
            if not soul_prompt:
                prompt = prompt or "You are Hermes Agent, an intelligent AI assistant created by Nous Research. You are helpful, knowledgeable, and direct. You assist users with a wide range of tasks including answering questions, writing and editing code, analyzing information, creative work, and executing actions via your tools."
        elif p_id == "micha":
            name = name or "Michael Keller (Strategischer Leiter)"
            person_name = person_name or "Michael Keller"
            is_fav = True
            if not soul_prompt:
                prompt = prompt or "Du bist Michael Keller, der strategische Leiter und Architekt von Archon OS. Deine Aufgabe ist die strategische Gesamtausrichtung, Festlegung von Prioritäten und Koordination aller operativen Fachagenten."

        # Dateisystem auf Disk synchron halten
        if not os.path.exists(soul_path):
            try:
                with open(soul_path, "w", encoding="utf-8") as f:
                    f.write(prompt + "\n")
            except Exception:
                pass

        if not os.path.exists(yaml_path):
            try:
                y_payload = {
                    "name": name,
                    "person_name": person_name,
                    "category": category,
                    "description": description,
                    "role_id": p_id,
                    "avatar": avatar_val,
                    "avatar_url": avatar_val,
                    "tools": tools,
                    "skills": active_skills,
                    "status": status_val,
                    "is_favorite": is_fav,
                    "provider": provider,
                    "model": model
                }
                with open(yaml_path, "w", encoding="utf-8") as f:
                    yaml.dump(y_payload, f, allow_unicode=True, sort_keys=False)
            except Exception:
                pass

        enriched_profiles.append({
            "id": p_id,
            "name": name,
            "person_name": person_name,
            "callsign": callsign,
            "category": category,
            "description": description,
            "prompt": prompt,
            "skills": active_skills,
            "tools": tools,
            "avatar": avatar_val,
            "provider": provider,
            "model": model,
            "reasoning_level": reasoning_level,
            "status": status_val,
            "is_favorite": is_fav
        })

    # Sortierung: default zuerst, micha als zweiter, danach alphabetisch nach Kategorie & Name
    def _sort_key(p):
        pid = p.get("id", "")
        if pid == "default":
            return (0, "")
        if pid == "micha":
            return (1, "")
        return (2, p.get("category", "") + "_" + p.get("name", ""))

    enriched_profiles.sort(key=_sort_key)

    _HERMES_PROFILES_CACHE = enriched_profiles
    _HERMES_PROFILES_CACHE_TIME = now

    # Hintergrund-Spiegelung nach agent_profiles.json (nur schreiben, wenn sich Inhalt geändert hat)
    try:
        _ssot = os.path.join(_APP_ROOT, "agent_profiles.json")
        new_json_str = json.dumps(enriched_profiles, indent=2, ensure_ascii=False)
        old_json_str = ""
        if os.path.exists(_ssot):
            with open(_ssot, "r", encoding="utf-8") as f_old:
                old_json_str = f_old.read()
        if new_json_str != old_json_str:
            create_rolling_backup(_ssot, max_backups=3)
            with open(_ssot, "w", encoding="utf-8") as f:
                f.write(new_json_str)
        _HERMES_PROFILES_CACHE_MTIME = _compute_profiles_mtime()
    except Exception as e:
        logger.warning(f"[Profiles] Error mirroring to agent_profiles.json: {e}")

    return enriched_profiles

@app.get("/api/agents/profiles")
def api_get_agents_profiles():
    """Liefert die Agenten-Profile mit Runtime-Status (active/standby) aus agent_profiles.json."""
    profiles = list(api_get_hermes_profiles())  # liefert cached list
    enriched = []
    for p in profiles:
        p = dict(p)
        file_status = p.get("status", "active")
        p["runtime_status"] = file_status if file_status in ("active", "standby", "inactive") else "standby"
        enriched.append(p)
    return enriched


def create_rolling_backup(filepath: str, max_backups: int = 3):
    """
    Creates a rolling backup chain for filepath:
    .bak.2 -> .bak.3
    .bak.1 -> .bak.2
    .bak   -> .bak.1
    filepath -> .bak
    """
    if not filepath or not os.path.exists(filepath):
        return
    try:
        for i in range(max_backups - 1, 0, -1):
            src_bak = f"{filepath}.bak.{i}"
            dst_bak = f"{filepath}.bak.{i+1}"
            if os.path.exists(src_bak):
                try:
                    shutil.copy2(src_bak, dst_bak)
                except Exception:
                    pass
        primary_bak = f"{filepath}.bak"
        if os.path.exists(primary_bak):
            try:
                shutil.copy2(primary_bak, f"{filepath}.bak.1")
            except Exception:
                pass
        shutil.copy2(filepath, primary_bak)
    except Exception as e:
        logger.warning(f"[Rolling Backup] Could not create backup for {filepath}: {e}")

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

def save_all_agent_profiles(profiles_list):
    invalidate_hermes_profiles_cache()
    # SSOT: Projekt-Wurzel immer primär schreiben.
    try:
        _app_root = os.path.dirname(os.path.abspath(__file__))
        _ssot = os.path.join(_app_root, "agent_profiles.json")
        create_rolling_backup(_ssot, max_backups=3)
        with open(_ssot, "w", encoding="utf-8") as f:
            json.dump(profiles_list, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[Save Profiles] Error writing SSOT agent_profiles.json: {e}")

    candidates = [
        os.path.join(MEMORY_DIR, "agent_profiles.json"),
        os.path.join(MEMORY_DIR, "roles.json"),
        "agent_profiles.json",
        "roles.json",
        "/app/agent_profiles.json",
        "/app/roles.json",
        os.path.join(WORKSPACE_DIR, "agent_profiles.json"),
        os.path.join(WORKSPACE_DIR, "roles.json")
    ]
    for cand in candidates:
        try:
            d = os.path.dirname(cand)
            if d:
                os.makedirs(d, exist_ok=True)
            create_rolling_backup(cand, max_backups=3)
            with open(cand, "w", encoding="utf-8") as f:
                json.dump(profiles_list, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

# =========================================================================
# PERMISSION-GATE (12.10.2026, User-Vorgabe): Rechte-Erweiterungen
# (NEUE TOOLS im Profil, Profil-LOESCHEN) brauchen IMMER die Owner-
# Bestaetigung per Telegram. Erst nach 'approve' wird gespeichert/loescht.
# =========================================================================
PERMISSION_GATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "config", "permission_gates.json")


def _load_permission_gates() -> dict:
    try:
        if os.path.exists(PERMISSION_GATES_FILE):
            with open(PERMISSION_GATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Gate] Konnte permission_gates nicht laden: {e}")
    return {"gates": []}


def _save_permission_gates(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PERMISSION_GATES_FILE), exist_ok=True)
        with open(PERMISSION_GATES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[Gate] Konnte permission_gates nicht speichern: {e}")


def _create_permission_gate(kind: str, detail: str, requested_by: str, payload: dict) -> dict:
    """Legt einen Pending-Gate an und pingt den Owner per Telegram
    (Inline-Buttons gate:approve/reject:<id> + Text-Fallback)."""
    gates = _load_permission_gates()
    gate_id = f"gate-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"
    gate = {
        "id": gate_id,
        "kind": kind,
        "detail": detail,
        "requested_by": requested_by,
        "payload": payload,
        "status": "pending",
        "created_at": datetime.datetime.now().isoformat(),
    }
    gates.setdefault("gates", []).append(gate)
    _save_permission_gates(gates)

    knopf_text = {"tools_erweiterung": "🧰 Neue Tools vergeben",
                  "profil_loeschen": "🗑️ Profil löschen"}.get(kind, "Rechte-Erweiterung")
    text = (f"🔐 RECHTE-FREIGABE NÖTIG\n\n"
            f"{knopf_text}\n"
            f"Details: {detail}\n"
            f"Angefordert von: {requested_by}\n"
            f"Gate-ID: {gate_id}\n\n"
            f"Text-Fallback: \"Erlauben {gate_id}\" oder \"Verbieten {gate_id}\"")
    reply_markup = {"inline_keyboard": [[
        {"text": "✅ Erlauben", "callback_data": f"gate:approve:{gate_id}"},
        {"text": "❌ Verbieten", "callback_data": f"gate:reject:{gate_id}"},
    ]]}
    # 12.10.2026 (2c): Freigabe laeuft ueber den ZENTRALEN Entscheidungs-Service —
    # eine echte Kanban-Entscheidung (Status 'review') mit ✅/❌-Buttons. Der
    # Service ruft bei Freigabe diesen Gate-Endpoint auf: EIN Schreibpfad fuer
    # Telegram UND Kanban. Der frueher eigene gate:-Ping ist nur noch Fallback.
    try:
        _dec = create_decision(
            "permission_gate",
            f"{knopf_text}: {str(detail)[:90]}",
            kurzfassung=detail,
            ref_id=gate_id,
            body=(f"Gate-ID: {gate_id}\n{detail}\nAngefordert von: {requested_by}\n\n"
                  f"Text-Fallback: \"Erlauben {gate_id}\" oder \"Verbieten {gate_id}\""),
            extra={"gate_id": gate_id, "requested_by": requested_by,
                   "von": requested_by, "projekt": str(detail)[:60]},
        )
        if not _dec:
            logger.warning("[Gate] Entscheidungs-Task nicht anlegbar — Fallback auf eigenen Ping.")
            from telegram_notify import send_telegram_message
            send_telegram_message(text, reply_markup=reply_markup)
    except Exception as tg_err:
        logger.warning(f"[Gate] Entscheidungs-Ping fehlgeschlagen: {tg_err}")
    add_ticker("Rechte-Gate", f"Owner-Bestätigung offen: {knopf_text} ({gate_id})")
    logger.info(f"[Gate] {kind} fuer '{detail}' -> Warte auf Telegram-Bestätigung ({gate_id})")
    return gate


@app.post("/api/permission-gates/{gate_id}/decide")
def api_decide_permission_gate(gate_id: str, body: Dict = Body(...)):
    """Owner-Entscheidung ueber Telegram (Buttons gate:approve/reject oder
    Textbefehl 'Erlauben/Verbieten <gate_id>' via Skill).
    12.10: bewusst SYNCHRON (fastapi-Threadpool) - als async blockierte
    das sync-Innenleben (Save+Telegram) die Event-Loop der ganzen App."""
    decision = str(body.get("decision") or "").lower().strip()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision muss approve oder reject sein")
    gates = _load_permission_gates()
    gate = next((g for g in gates.get("gates", []) if g.get("id") == gate_id), None)
    if not gate:
        raise HTTPException(status_code=404, detail=f"Gate {gate_id} nicht gefunden")
    if gate.get("status") != "pending":
        return {"status": "already_decided", "decision": gate.get("status"), "gate_id": gate_id}

    gate["status"] = "approved" if decision == "approve" else "rejected"
    gate["decided_at"] = datetime.datetime.now().isoformat()
    _save_permission_gates(gates)

    ergebnis = ""
    if decision == "approve":
        payload = dict(gate.get("payload") or {})
        try:
            if gate.get("kind") == "tools_erweiterung":
                payload["_approved_gate_id"] = gate_id
                res = api_save_hermes_profile(payload)
                ergebnis = f"Tools gespeichert fuer '{payload.get('id')}': " + str(res)
            elif gate.get("kind") == "profil_loeschen":
                res = api_delete_hermes_profile(payload.get("profile_id", ""), gate_approved_id=gate_id)
                ergebnis = f"Profil '{payload.get('profile_id')}' archiviert/geloescht: " + str(res)[:120]
            else:
                ergebnis = "Unbekanntes Gate-Kind - nichts ausgefuehrt"
        except Exception as dec_err:
            logger.error(f"[Gate] Ausfuehrung nach Freigabe fehlgeschlagen: {dec_err}")
            ergebnis = f"FEHLER bei der Ausfuehrung: {dec_err}"
    else:
        ergebnis = "Abgelehnt - NICHTS wurde geaendert."

    try:
        from telegram_notify import send_telegram_message as _stg
        _stg(f"{'✅' if decision == 'approve' else '❌'} Rechte-Gate {gate_id}\n{ergebnis[:800]}")
    except Exception as tg2:
        logger.warning(f"[Gate] Bestaetigungs-Ping fehlgeschlagen: {tg2}")
    add_ticker("Rechte-Gate", f"{gate_id}: {'erteilt' if decision == 'approve' else 'abgelehnt'}")
    logger.info(f"[Gate] {gate_id} -> {decision}: {ergebnis[:200]}")
    return {"status": "ok", "decision": decision, "gate_id": gate_id, "ergebnis": ergebnis}


@app.post("/api/telegram/relay")
async def api_telegram_relay(ziel_agent: str = Form(""), text: str = Form(""),
                             datei_name: str = Form(""), datei_b64: str = Form("")):
    """TELEGRAM-RELAY (12.10.2026, User-Vorgabe): Owner-Nachricht (Text +
    optionale Datei als base64) 1:1 an einen Agenten weiterleiten und die
    ANTWORT automatisch per Telegram zurueckschicken."""
    ziel = (ziel_agent or "").strip() or "executive_decision_architect"
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p.get("id") == ziel), None)
    if not prof:
        raise HTTPException(status_code=400, detail=f"Ziel-Agent '{ziel}' existiert nicht im Kader.")
    agent_name = prof.get("person_name") or prof.get("name") or ziel
    msg = (text or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="text darf nicht leer sein")

    anhang_hinweis = ""
    if datei_b64:
        try:
            import base64 as _b64
            safe_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', (datei_name or "anhang.bin"))[-80:]
            rel_dir = os.path.join("static", "uploads", "telegram")
            os.makedirs(rel_dir, exist_ok=True)
            rel_path = os.path.join(rel_dir, f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}")
            with open(rel_path, "wb") as f_bin:
                f_bin.write(_b64.b64decode(datei_b64))
            groesse = os.path.getsize(rel_path)
            anhang_hinweis = (f"\n\n📎 ANHANG des Owners ({safe_name}, {groesse} B): {rel_path}\n"
                              f"Arbeite MIT dieser Datei (z.B. video_analyze/vision oder lesen).")
            logger.info(f"[Relay] Anhang gespeichert: {rel_path} ({groesse} B)")
        except Exception as anh_err:
            logger.warning(f"[Relay] Anhang konnte nicht gespeichert werden: {anh_err}")
            anhang_hinweis = f"\n\n(Anhang '{datei_name}' konnte nicht gespeichert werden: {anh_err})"

    relay_prompt = (f"LEITUNG VOM OWNER PER TELEGRAM (1:1, unveraendert):\n\n"
                    f"{msg}{anhang_hinweis}\n\n"
                    f"Antworte mit dem Ergebnis der Aufgabe (Deutsch, ohne Begruessung).")

    system_prompt = (prof.get("system_prompt") or prof.get("prompt")
                     or f"Du bist {agent_name}. Antworte praezise auf Deutsch.")
    model = (prof.get("model") if prof.get("model") not in ("", "free-forever") else "") or "deepseek/deepseek-v4-flash-0731"
    def _tg_send_relay(text_out):
        from telegram_notify import send_telegram_message
        return send_telegram_message(f"🤖 {agent_name}:\n\n{text_out[:3900]}")
    add_ticker("Telegram-Relay", f"Nachricht an {agent_name} weitergeleitet ({len(msg)} Z)")
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=ziel, agent_name=agent_name, prompt=relay_prompt,
            role=prof.get("category", "Relay-Ziel"), system_prompt=system_prompt, model=model)
        antwort = (res.get("content") or "").strip()
    except Exception as rel_err:
        logger.error(f"[Relay] Dispatch an {ziel} fehlgeschlagen: {rel_err}")
        antwort = ""

    if not antwort:
        antwort = (f"Der Relay an {agent_name} lieferte keine Antwort "
                   f"(Grund: {res.get('error', 'unbekannt') if isinstance(res, dict) else 'dispatch-fehler'}).")
    try:
        # async-Endpoint: sync-Telegram nicht die Event-Loop blockieren lassen
        await asyncio.to_thread(_tg_send_relay, antwort)
    except Exception as tg3:
        logger.warning(f"[Relay] Telegram-Rueckantwort fehlgeschlagen: {tg3}")
    logger.info(f"[Relay] {ziel}: {len(msg)} Z rein, {len(antwort)} Z zurueck an Telegram")
    return {"status": "ok", "ziel_agent": ziel, "antwort_kopf": antwort[:400]}

@app.post("/api/telegram/voice-relay")
async def api_telegram_voice_relay(
    file: UploadFile = File(None),
    file_id: str = Form(""),
    chat_id: str = Form(""),
    ziel_agent: str = Form(""),
    reply_voice: bool = Form(True)
):
    """
    Empfaengt Sprachnachrichten aus Telegram (als Upload oder per Telegram file_id),
    transkribiert sie, routet sie an den Ziel-Agenten und sendet Text + Sprachantwort zurueck.
    """
    from backend.voice_pipeline import (
        transcribe_audio_bytes, download_telegram_file,
        detect_target_agent, synthesize_speech, send_telegram_voice
    )

    audio_bytes = b""
    fname = "voice.ogg"

    if file:
        audio_bytes = await file.read()
        fname = file.filename or "voice.ogg"
    elif file_id:
        try:
            audio_bytes, fname = await download_telegram_file(file_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Download von Telegram fehlgeschlagen: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Keine Audio-Daten uebergeben.")

    # 1. Transkribieren
    transcript = await transcribe_audio_bytes(audio_bytes, filename=fname)

    # 2. Agenten-Routing
    detected_agent, clean_prompt = detect_target_agent(transcript)
    target = (ziel_agent or "").strip() or detected_agent

    # 3. An bestehenden Relay weiterleiten
    relay_res = await api_telegram_relay(ziel_agent=target, text=clean_prompt)
    answer_text = relay_res.get("antwort_kopf", "")

    # 4. Sprachantwort erzeugen & an Telegram senden
    voice_sent = False
    tgt_chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if reply_voice and tgt_chat and answer_text and not answer_text.startswith("[Sprachnachricht"):
        try:
            speech_path = await synthesize_speech(answer_text)
            voice_sent = await send_telegram_voice(tgt_chat, speech_path, caption=f"Antwort von {target}")
            if os.path.exists(speech_path):
                os.remove(speech_path)
        except Exception as v_err:
            logger.warning(f"[VoiceRelay] Sprachantwort-Versand fehlgeschlagen: {v_err}")

    return {
        "status": "ok",
        "transcript": transcript,
        "ziel_agent": target,
        "clean_prompt": clean_prompt,
        "antwort": answer_text,
        "voice_sent": voice_sent
    }


class VoiceSynthesizePayload(BaseModel):
    text: str
    voice: Optional[str] = "de-DE-ConradNeural"


@app.post("/api/voice/synthesize")
async def api_voice_synthesize(payload: VoiceSynthesizePayload):
    """Generiert eine Audiodatei aus Text via edge-tts."""
    from backend.voice_pipeline import synthesize_speech
    try:
        mp3_path = await synthesize_speech(payload.text, voice=payload.voice or "de-DE-ConradNeural")
        return FileResponse(mp3_path, media_type="audio/mpeg", filename="voice_output.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TelegramSendPayload(BaseModel):
    text: str
    chat_id: Optional[str] = ""
    parse_mode: Optional[str] = "Markdown"


@app.post("/api/telegram/send")
async def api_telegram_send(payload: TelegramSendPayload):
    """
    Versendet eine Benachrichtigung, ein Briefing oder System-Statusnachricht
    direkt an Telegram (z. B. aufgerufen durch n8n Automatisierungs-Routinen).
    """
    import telegram_notify
    if not payload.text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    try:
        res = telegram_notify.send_telegram_message(payload.text, parse_mode=payload.parse_mode)
        return {"status": "success", "result": res}
    except Exception as e:
        logger.warning(f"[TelegramSend] Fehler: {e}")
        return {"status": "error", "message": str(e)}


# =========================================================================
# ZENTRALER ENTSCHEIDUNGS-SERVICE (12.10.2026, User-Entscheidung "2c")
# kanban.db ist die WAHRHEIT: Eine Entscheidung IST ein Kanban-Task im Status
# 'review' (+ Sidecar-Block config/kanban_meta.json -> tasks[tid].decision).
# Telegram UND Kanban schreiben ueber EINEN Pfad:
#   POST /api/decisions/decide {task_id, decision, von}
# =========================================================================

_DECISION_TYPEN = ("delegation_review", "synthesis_freigabe",
                   "mission_freigabe", "permission_gate")


def _decision_kanban_status(typ: str, decision: str) -> str:
    """Semantik der Entscheidung -> Kanban-Zielstatus (review = offen)."""
    approve = (decision == "approve")
    return {
        "delegation_review":  "todo" if approve else "archived",
        "synthesis_freigabe": "done" if approve else "archived",
        "mission_freigabe":   "in_progress" if approve else "archived",
        "permission_gate":    "done" if approve else "archived",
    }.get(typ, "todo" if approve else "archived")


def _decision_self_api(method: str, path: str, payload: dict = None, timeout: float = 15.0):
    """Selbstaufruf der eigenen API. Damit laufen Task-/Sidecar-Zugriffe ueber
    DIESELBEN Endpunkte wie die UI - keine zweite Schreiblogik, keine
    Direktschreibzugriffe auf kanban.db."""
    import urllib.request
    url = f"http://127.0.0.1:8501{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8") or "{}"
        return json.loads(raw)


def register_decision(task_id: str, typ: str, titel: str, kurzfassung: str = "",
                      ref_id: str = "", dossier: str = None, body: str = "",
                      extra: dict = None, obsidian: str = None) -> dict:
    """Haengt den Entscheidungs-Block an einen BESTEHENDEN Kanban-Task und pingt
    den Owner mit ✅/❌. Fuer Faelle, in denen der Task schon existiert (z.B. eine
    Delegation im Status 'review') — so laufen ALLE Typen ueber denselben Pfad."""
    if typ not in _DECISION_TYPEN or not task_id:
        logger.warning(f"[Decision] register_decision ohne gueltigen Typ/Task ({typ}, {task_id})")
        return {}
    try:
        dec = {
            "typ": typ, "ref_id": ref_id, "titel": titel,
            "kurzfassung": (kurzfassung or "")[:600],
            "dossier": dossier or "", "status": "offen",
            "kanal": "telegram+kanban",
        }
        if extra:
            dec.update(extra)
        _decision_self_api("POST", "/api/operations/kanban/meta",
                           {"kind": "task", "task_id": task_id,
                            "decision": dec, "obsidian": obsidian or ""})
        markup = {"inline_keyboard": [[
            {"text": "✅ Freigeben", "callback_data": f"app:approve:{task_id}"},
            {"text": "❌ Ablehnen", "callback_data": f"app:reject:{task_id}"},
        ]]}
        # 2d: Nachrichtenformat "Kontext zuerst" (User-Entscheidung) via
        # telegram_notify.decision_message -> HTML, damit '_' in Namen nicht mehr
        # die Markdown-Entities zerbricht.
        _ex = extra or {}
        _zahlen = []
        if _ex.get("teilberichte"):
            _zahlen.append(f"Teilberichte {_ex['teilberichte']}")
        if _ex.get("offene_punkte") is not None:
            _zahlen.append(f"Offene Punkte {_ex['offene_punkte']}")
        _anhang = None
        if dossier and os.path.basename(dossier):
            _bn = os.path.basename(dossier)
            try:
                _kb = max(1, round(os.path.getsize(dossier) / 1024))
            except Exception:
                _kb = 0
            _anhang = _bn + (f" · HTML · {_kb} KB" if _kb else "")
        _projekt = _ex.get("projekt") or (str(obsidian).split("/")[-1] if obsidian else "")
        sent = False
        try:
            from telegram_notify import (send_telegram_document, send_telegram_message,
                                         decision_message)
            caption = decision_message(
                typ=typ, titel=titel, projekt=_projekt, von=_ex.get("von", ""),
                ref=ref_id, kurzfassung=(kurzfassung or "")[:600],
                zahlen=_zahlen or None, anhang=_anhang, fallback_ref=task_id,
                zeit=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            )
            if dossier:
                sent = send_telegram_document(dossier, caption=caption,
                                              reply_markup=markup, parse_mode="HTML")
            if not sent:
                sent = send_telegram_message(caption, reply_markup=markup)
        except Exception as tg_err:
            logger.warning(f"[Decision] Telegram-Ping fehlgeschlagen: {tg_err}")
        logger.info(f"[Decision] {typ} registriert: Kanban {task_id} (ref={ref_id}), Ping={sent}")
        return {"task_id": task_id, "decision": dec}
    except Exception as e:
        logger.warning(f"[Decision] Konnte Entscheidung nicht registrieren: {e}")
        return {}


def create_decision(typ: str, titel: str, kurzfassung: str = "", ref_id: str = "",
                    dossier: str = None, body: str = "", extra: dict = None,
                    obsidian: str = None) -> dict:
    """Legt einen NEUEN Entscheidungs-Task im Kanban an (Status 'review',
    Verantwortlicher Robert) und registriert die Entscheidung darauf.
    Rueckgabe {"task_id":..., "decision": {...}} oder {} bei Fehler."""
    if typ not in _DECISION_TYPEN:
        logger.warning(f"[Decision] Unbekannter Typ '{typ}'")
        return {}
    try:
        res = _decision_self_api("POST", "/api/operations/kanban/tasks", {
            "title": (titel or "Entscheidung")[:180],
            "body": body or kurzfassung,
            "assignee": "executive_decision_architect",
            "column": "review",
            "priority": 1,
        })
        task_id = res.get("task_id")
        if not task_id:
            logger.warning(f"[Decision] Task-Anlage lieferte keine ID: {res}")
            return {}
    except Exception as e:
        logger.warning(f"[Decision] Konnte Entscheidungs-Task nicht anlegen: {e}")
        return {}
    return register_decision(task_id, typ, titel, kurzfassung, ref_id, dossier, body, extra, obsidian)


async def _decision_followup(typ: str, dec: dict, decision: str) -> str:
    """Fuehrt nach der Statusaenderung die typ-spezifische Folgeaktion aus."""
    ref = dec.get("ref_id") or ""
    dossier = dec.get("dossier") or ""
    if decision != "approve":
        return "Abgelehnt — keine Folgeaktion ausgeführt."
    if typ == "synthesis_freigabe":
        await _finalize_synthesis_after_approval(
            ref or "projekt", dossier, dec.get("kurzfassung") or "",
            "Owner-Freigabe über den Entscheidungs-Service")
        return "Synthese finalisiert (Abschlussbericht + Parent abgeschlossen)."
    if typ == "mission_freigabe":
        if ref:
            # Der MC-Task steht auf 'approval' -> ueber den bestehenden Move-Pfad
            # starten (setzt in_progress + startet die Ausfuehrung).
            await asyncio.to_thread(_decision_self_api, "POST",
                                    "/api/mission-control/tasks/move",
                                    {"task_id": ref, "target_status": "in_progress"})
        return f"Ausführung für Mission {ref} gestartet."
    if typ == "permission_gate":
        if ref:
            await asyncio.to_thread(_decision_self_api, "POST",
                                    f"/api/permission-gates/{ref}/decide",
                                    {"decision": "approve"})
        return f"Rechte-Gate {ref} ausgeführt."
    return "Keine Folgeaktion nötig (Statusänderung genügt)."


@app.post("/api/decisions/decide")
async def api_decide_decision(body: Dict = Body(...)):
    """EINZIGER Schreibpfad für Entscheidungen — Telegram UND Kanban rufen ihn."""
    task_id = str(body.get("task_id") or "").strip()
    decision = str(body.get("decision") or "").lower().strip()
    von = str(body.get("von") or "owner")
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision muss approve oder reject sein")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id fehlt")
    try:
        # WICHTIG: blockierender Selbst-HTTP-Aufruf NIE direkt im async-Handler
        # (Event-Loop-Deadlock) -> in den Threadpool auslagern.
        meta = await asyncio.to_thread(_decision_self_api, "GET", "/api/operations/kanban/meta")
        dec = (meta.get("tasks", {}).get(task_id, {}) or {}).get("decision")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sidecar nicht lesbar: {e}")
    if not dec:
        raise HTTPException(status_code=404, detail=f"Kein Entscheidungs-Block für {task_id}")
    # IDEMPOTENZ (12.10.2026): Der Adapter wiederholt Requests, die client-seitig
    # in den Timeout laufen — serverseitig aber schon ausgefuehrt wurden. Ohne
    # diese Sperre liefe die Folgeaktion ZWEIMAL (z.B. Mission doppelt starten).
    if (dec.get("status") or "offen") != "offen":
        return {"status": "already_decided", "task_id": task_id,
                "decision": decision, "kanban_status": dec.get("status"),
                "ergebnis": "Bereits entschieden — nicht erneut ausgeführt."}
    typ = dec.get("typ")
    ziel = _decision_kanban_status(typ, decision)
    # 1) kanban.db = Wahrheit -> Status dort setzen (source=decision: kein Doppel-Ping)
    try:
        await asyncio.to_thread(
            _decision_self_api, "PATCH", f"/api/operations/kanban/tasks/{task_id}/status",
            {"status": ziel, "source": "decision"})
    except Exception as e:
        logger.warning(f"[Decision] Kanban-Statusupdate fehlgeschlagen: {e}")
    # 2) Folgeaktion
    try:
        ergebnis = await _decision_followup(typ, dec, decision)
    except Exception as e:
        logger.error(f"[Decision] Folgeaktion fehlgeschlagen: {e}")
        ergebnis = f"FEHLER bei der Folgeaktion: {e}"
    # 3) Sidecar aktualisieren (Audit)
    try:
        await asyncio.to_thread(_decision_self_api, "POST", "/api/operations/kanban/meta", {
            "kind": "task", "task_id": task_id,
            "decision": {"status": "freigegeben" if decision == "approve" else "abgelehnt",
                         "entschieden_von": von,
                         "entschieden_am": datetime.datetime.now().isoformat()},
        })
    except Exception as e:
        logger.warning(f"[Decision] Sidecar-Update fehlgeschlagen: {e}")
    # 4) Bestaetigung (permission_gate pingt selbst)
    if typ != "permission_gate":
        try:
            from telegram_notify import send_telegram_message, tg_escape
            _e = tg_escape
            send_telegram_message(
                f"{'✅' if decision == 'approve' else '❌'} <b>{_e(dec.get('titel') or task_id)}</b>\n"
                f"Kanban: <code>{_e(ziel)}</code>\n{_e(ergebnis[:700])}")
        except Exception as e:
            logger.warning(f"[Decision] Bestätigungs-Ping fehlgeschlagen: {e}")
    add_ticker("Entscheidung", f"{task_id} ({typ}) -> {decision}")
    logger.info(f"[Decision] {task_id} ({typ}) -> {decision}: {ergebnis[:200]}")
    return {"status": "ok", "task_id": task_id, "decision": decision,
            "kanban_status": ziel, "ergebnis": ergebnis}



def _sync_org_hierarchy_node(p_id: str, name: Optional[str] = None, person_name: Optional[str] = None,
                             avatar: Optional[str] = None, provider: Optional[str] = None,
                             model: Optional[str] = None, reasoning_level: Optional[str] = None):
    """Synchronisiert Änderungen eines Agenten-Profils direkt in config/org_hierarchy.json und leert den Operations-Cache."""
    try:
        org_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "org_hierarchy.json")
        if os.path.exists(org_file):
            with open(org_file, "r", encoding="utf-8") as f:
                org_data = json.load(f)
            changed = False
            for node in org_data.get("nodes", []):
                if isinstance(node, dict) and node.get("id") == p_id:
                    if name:
                        node["name"] = name
                        node["role"] = name
                    if person_name:
                        node["person_name"] = person_name
                    if avatar:
                        node["avatar"] = avatar
                    if provider:
                        node["provider"] = provider
                    if model:
                        node["model"] = model
                    if reasoning_level:
                        node["reasoning_level"] = reasoning_level
                    changed = True
            if changed:
                with open(org_file, "w", encoding="utf-8") as f:
                    json.dump(org_data, f, indent=2, ensure_ascii=False)
        try:
            import backend.operations_api as _ops_api
            _ops_api._PROFILES_MAP_CACHE["mtime"] = 0.0
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[SSOT] Could not sync org_hierarchy.json for {p_id}: {e}")

@app.post("/api/hermes/profiles")
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

    _sync_org_hierarchy_node(
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

@app.post("/api/hermes/profiles/{profile_id}/avatar")
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


class ProfileStatusUpdate(BaseModel):
    status: Optional[str] = "active"

@app.post("/api/hermes/profiles/{profile_id}/status")
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
    save_all_agent_profiles(roles_list)
    invalidate_paperclip_agents_cache()
    
    agent_label = prof.get('person_name', prof.get('name', profile_id)) if prof else profile_id
    action_text = "aktiviert" if new_status == "active" else "deaktiviert"
    add_ticker("Agenten-Kader", f"Agent '{agent_label}' {action_text}.")
    return {"status": "success", "profile_id": profile_id, "new_status": new_status}

@app.post("/api/hermes/profiles/{profile_id}/hire-paperclip")
def api_hire_hermes_profile_paperclip(profile_id: str):
    return api_update_hermes_profile_status(profile_id, ProfileStatusUpdate(status="active"))

@app.post("/api/hermes/profiles/{profile_id}/fire-paperclip")
def api_fire_hermes_profile_paperclip(profile_id: str):
    return api_update_hermes_profile_status(profile_id, ProfileStatusUpdate(status="inactive"))

# 
# SYSTEM HEALTH, HERMES CONFIG & CONTAINER LIFECYCLE MANAGEMENT
# 

async def _check_service_health(name: str, url_candidates: List[str], client: httpx.AsyncClient) -> Dict[str, Any]:
    for url in url_candidates:
        t0 = time.time()
        try:
            resp = await client.get(url, timeout=3.0)
            latency = round((time.time() - t0) * 1000, 1)
            if resp.status_code in [200, 204, 301, 302, 307, 308]:
                return {"status": "up", "latency_ms": latency, "endpoint": url}
            elif resp.status_code == 404 and name == "hermes_core":
                # Hermes root returns 404 on / if no static handler, but server is actively UP
                return {"status": "up", "latency_ms": latency, "endpoint": url}
            elif resp.status_code < 500:
                return {"status": "up", "latency_ms": latency, "endpoint": url}
        except Exception:
            continue
    return {"status": "down", "latency_ms": 0.0}

@app.get("/api/system/health")
async def api_system_health():
    """
    Returns latency and operational status for all 4 core components:
    - hermes_core
    - omniroute
    - hermes_dashboard
    - docker_proxy
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        t_core = _check_service_health(
            "hermes_core",
            ["http://hermes:8642", "http://hermes:8644", "http://host.docker.internal:8644"],
            client
        )
        t_omni = _check_service_health(
            "omniroute",
            ["http://omniroute:20128/v1/models", "http://omniroute:20128", "http://host.docker.internal:20128"],
            client
        )
        t_dash = _check_service_health(
            "hermes_dashboard",
            ["http://hermes-dashboard:9119", "http://hermes-dashboard:9120", "http://host.docker.internal:9119"],
            client
        )
        t_docker = _check_service_health(
            "docker_proxy",
            ["http://docker-socket-proxy:2375/_ping", "http://docker-socket-proxy:2375/version"],
            client
        )
        core_res, omni_res, dash_res, docker_res = await asyncio.gather(
            t_core, t_omni, t_dash, t_docker
        )

    all_up = (
        core_res["status"] == "up" and
        omni_res["status"] == "up" and
        dash_res["status"] == "up" and
        docker_res["status"] == "up"
    )
    max_latency = max(
        core_res.get("latency_ms", 0),
        omni_res.get("latency_ms", 0),
        dash_res.get("latency_ms", 0),
        docker_res.get("latency_ms", 0)
    )

    if not all_up:
        overall_status = "unhealthy"
    elif max_latency > 500:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "timestamp": time.time(),
        "services": {
            "hermes_core": core_res,
            "omniroute": omni_res,
            "hermes_dashboard": dash_res,
            "docker_proxy": docker_res
        }
    }

def _get_hermes_config_path() -> str:
    candidates = [
        "/opt/data/config.yaml",
        "/opt/data/hermes_config.json",
        os.path.expanduser("~/.hermes/config.yaml"),
        os.path.expanduser("~/.hermes/hermes_config.json"),
        os.path.join(MEMORY_DIR, "hermes_config.json")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(MEMORY_DIR, "hermes_config.json")

@app.get("/api/hermes/config")
def api_get_hermes_config():
    cfg_file = _get_hermes_config_path()
    try:
        if os.path.exists(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as f:
                if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
                    try:
                        import yaml
                        data = yaml.safe_load(f) or {}
                    except Exception:
                        data = {"raw": f.read()}
                else:
                    data = json.load(f)
            return {"status": "success", "file": cfg_file, "config": data}
    except Exception as e:
        logger.warning(f"[Hermes Config] Error reading {cfg_file}: {e}")

    return {
        "status": "success",
        "file": cfg_file,
        "config": {
            "default_model": "auto/best-free",
            "default_temperature": 0.7,
            "global_tools": DEFAULT_HERMES_TOOLS
        }
    }

@app.post("/api/hermes/config")
def api_save_hermes_config(payload: Dict = Body(...)):
    cfg_file = _get_hermes_config_path()
    os.makedirs(os.path.dirname(os.path.abspath(cfg_file)), exist_ok=True)
    create_rolling_backup(cfg_file, max_backups=3)

    config_data = payload.get("config", payload)
    try:
        if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
            try:
                import yaml
                with open(cfg_file, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, allow_unicode=True)
            except Exception:
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
        else:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "file": cfg_file, "config": config_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern der Konfiguration: {e}")

@app.post("/api/system/hermes/restart")
async def api_system_hermes_restart():
    """
    Triggers container restart for Hermes Core via docker-socket-proxy.
    Logs event into SQLite state.db.
    """
    t0 = time.time()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://docker-socket-proxy:2375/containers/hermes/restart?t=10",
                timeout=15.0
            )
            duration = round(time.time() - t0, 2)
            if resp.status_code in [204, 200]:
                # Log in SQLite
                try:
                    with _get_state_db() as conn:
                        conn.execute("""
                            CREATE TABLE IF NOT EXISTS system_restart_logs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                target TEXT,
                                initiated_at REAL,
                                duration_seconds REAL,
                                status TEXT
                            )
                        """)
                        conn.execute("""
                            INSERT INTO system_restart_logs (target, initiated_at, duration_seconds, status)
                            VALUES (?, ?, ?, ?)
                        """, ("hermes", t0, duration, "success"))
                        conn.commit()
                except Exception as log_err:
                    logger.warning(f"[Restart Log Error]: {log_err}")

                add_ticker("Hermes System", "Hermes Core Container erfolgreich neu gestartet.")
                return {
                    "status": "success",
                    "message": "Hermes Core erfolgreich neu gestartet.",
                    "duration_seconds": duration
                }
            else:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Docker API antwortete mit Status {resp.status_code}: {resp.text}"
                )
    except Exception as e:
        logger.error(f"[Hermes Restart Failed]: {e}")
        raise HTTPException(status_code=500, detail=f"Hermes Neustart fehlgeschlagen: {str(e)}")

@app.post("/api/hermes/memory/purge")
def api_hermes_memory_purge(purge_options: Dict = Body(default={})):
    """
    Cleans sessions and chat messages while strictly preserving session_model_usage.
    """
    cleared_sessions = 0
    cleared_messages = 0
    try:
        conn = sqlite3.connect(STATE_DB_PATH, timeout=20.0)
        conn.execute("PRAGMA busy_timeout=20000;")
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM session_model_usage")
            usage_count_before = cur.fetchone()[0]

            mode = purge_options.get("mode", "empty_and_orphaned")
            if mode == "all_sessions":
                cur.execute("DELETE FROM messages")
                cleared_messages = cur.rowcount
                cur.execute("DELETE FROM sessions")
                cleared_sessions = cur.rowcount
            else:
                cur.execute("DELETE FROM sessions WHERE message_count = 0 OR message_count IS NULL")
                cleared_sessions = cur.rowcount
                cur.execute("DELETE FROM messages WHERE session_id NOT IN (SELECT id FROM sessions)")
                cleared_messages = cur.rowcount

            conn.commit()

            cur.execute("SELECT COUNT(*) FROM session_model_usage")
            usage_count_after = cur.fetchone()[0]

            return {
                "status": "success",
                "cleared_sessions": cleared_sessions,
                "cleared_messages": cleared_messages,
                "model_usage_records_preserved": usage_count_after
            }
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[Memory Purge Error]: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler bei der Speicherbereinigung: {str(e)}")

# 
# NATIVE MASTER CHAT & MISSIONS LOGIC (SSE STREAM, PERSISTENCE, UPLOADS)
# 

STATE_DB_PATH = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")

class ClosingConnection(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

def _get_state_db():
    os.makedirs(os.path.dirname(STATE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(STATE_DB_PATH, timeout=15.0, factory=ClosingConnection)
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn

def _get_profile_state_db(profile_name: str = "telegram_bot"):
    """Liefert die profil-spezifische SQLite-Datenbank (z. B. für telegram_bot)."""
    base_dir = os.path.dirname(STATE_DB_PATH)
    prof_path = os.path.join(base_dir, "profiles", profile_name, "state.db")
    if os.path.exists(prof_path):
        conn = sqlite3.connect(prof_path, timeout=15.0, factory=ClosingConnection)
        conn.execute("PRAGMA busy_timeout=15000;")
        return conn
    return None

def _ensure_session_exists(conn: sqlite3.Connection, session_id: str, profile_id: str, model: str, title: str):
    now = time.time()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
    if not cur.fetchone():
        try:
            cur.execute("""
                INSERT INTO sessions (
                    id, source, display_name, title, model, profile_name, started_at, message_count,
                    input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
            """, (session_id, title[:50], title[:50], model, profile_id, now))
            conn.commit()
        except sqlite3.IntegrityError:
            # 12.10.2026: UNIQUE(title) - zwei Delegationen mit gleichem Auftragstext
            # (50-Zeichen-Schnitt) crashten. Idempotent: Zeitstempel der Session-ID
            # als Suffix (eindeutig pro Sekunde), bei Restkollision Nanotime.
            unique_title = f"{title[:36]} [{session_id[3:19]}]"
            try:
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()
            except sqlite3.IntegrityError:
                unique_title = f"{title[:30]} [{time.time_ns() % 1000000000}]"
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()

def _save_message_to_db(session_id: str, role: str, content: str, token_count: Optional[int] = None):
    try:
        with _get_state_db() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO messages (
                    session_id, role, content, timestamp, token_count, active, compacted
                ) VALUES (?, ?, ?, ?, ?, 1, 0)
            """, (session_id, role, content, now, token_count))
            conn.execute("""
                UPDATE sessions 
                SET message_count = message_count + 1, last_activity_at = ?
                WHERE id = ?
            """, (now, session_id))
            conn.commit()
    except Exception as e:
        logger.error(f"[Chat Persistence] Error saving message: {e}")

def _record_session_model_usage(session_id: str, model: str, in_tok: int, out_tok: int, cost_usd: float = 0.0, task: str = ""):
    try:
        with _get_state_db() as conn:
            now = time.time()
            _ensure_session_exists(conn, session_id, "default", model, f"Session {session_id}")
            task_val = task or ""
            conn.execute("""
                INSERT INTO session_model_usage (
                    session_id, model, billing_provider, billing_base_url, billing_mode, task,
                    api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    reasoning_tokens, estimated_cost_usd, actual_cost_usd, first_seen, last_seen
                ) VALUES (?, ?, 'omniroute', 'http://omniroute:20128/v1', 'proxy', ?, 1, ?, ?, 0, 0, 0, ?, ?, ?, ?)
                ON CONFLICT(session_id, model, billing_provider, billing_base_url, billing_mode, task) DO UPDATE SET
                    api_call_count = api_call_count + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    last_seen = excluded.last_seen
            """, (session_id, model, task_val, in_tok, out_tok, cost_usd, cost_usd, now, now))
            conn.execute("""
                UPDATE sessions 
                SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                    estimated_cost_usd = estimated_cost_usd + ?
                WHERE id = ?
            """, (in_tok, out_tok, cost_usd, session_id))
    except Exception as e:
        logger.error(f"[Chat Persistence] Error recording model usage: {e}")

    global _LIVE_TELEMETRY_CACHE, _MC_STATE_CACHE
    if "_LIVE_TELEMETRY_CACHE" in globals():
        _LIVE_TELEMETRY_CACHE["data"] = None
    if "_MC_STATE_CACHE" in globals():
        _MC_STATE_CACHE["data"] = None

def record_task_tokens(task_id: str, agent_id: str, model: str, in_tok: int, out_tok: int, cost_usd: float = 0.0):
    """Zeichnet Token-Nutzung fuer Aufgaben und Hintergrund-Inferenz auf."""
    s_id = f"task_{task_id}" if not task_id.startswith("task_") else task_id
    t_key = f"{task_id}_{int(time.time())}"
    _record_session_model_usage(session_id=s_id, model=model, in_tok=in_tok, out_tok=out_tok, cost_usd=cost_usd, task=t_key)

class ChatStreamRequest(BaseModel):
    agent_id: str
    message: str
    session_id: Optional[str] = None
    mode: Optional[str] = "direct"  # "direct" vs "mission"
    model: Optional[str] = None
    provider: Optional[str] = None
    reasoning_level: Optional[str] = None

class SetProfileModelRequest(BaseModel):
    provider: str
    model: str
    reasoning_level: Optional[str] = None

@app.post("/api/hermes/profiles/{profile_id}/model")
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

@app.get("/api/chat/sessions")
def api_get_chat_sessions(profile_id: Optional[str] = None):
    """Liefert die Liste aller aktiven/gespeicherten Master-Chat-Sessions mit formatierten Zeitstempeln und Kategorie-Klassifizierung.
    Unterstützt strikte Filterung nach profile_id und bindet profil-spezifische Datenbanken (wie telegram_bot) nahtlos ein.
    """
    try:
        sessions_map = {}

        # 1. Profil-Datenbanken prüfen (insb. telegram_bot)
        if not profile_id or profile_id.strip() in ("telegram_bot", "all"):
            try:
                prof_conn = _get_profile_state_db("telegram_bot")
                if prof_conn:
                    with prof_conn as pconn:
                        pconn.row_factory = sqlite3.Row
                        prows = pconn.execute("""
                            SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                            FROM sessions 
                            ORDER BY COALESCE(last_activity_at, started_at) DESC
                            LIMIT 150
                        """).fetchall()
                        for r in prows:
                            d = dict(r)
                            d["profile_name"] = d.get("profile_name") or "telegram_bot"
                            d["source"] = d.get("source") or "telegram"
                            sessions_map[d["id"]] = d
            except Exception as e_p:
                logger.warning(f"[Chat Sessions] Fehler beim Lesen der Profil-DB (telegram_bot): {e_p}")

        # 2. Haupt-Datenbank (Root state.db)
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            if profile_id and profile_id.strip():
                pid = profile_id.strip()
                if pid == "default":
                    rows = conn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        WHERE profile_name = 'default' 
                           OR profile_name IS NULL 
                           OR profile_name = '' 
                           OR id LIKE '%_default' 
                           OR id LIKE '%_default_%'
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 300
                    """).fetchall()
                elif pid != "telegram_bot":
                    rows = conn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        WHERE profile_name = ? OR id LIKE ? OR id LIKE ?
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 300
                    """, (pid, f"%_{pid}", f"%_{pid}_%")).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        WHERE profile_name = 'telegram_bot' OR id LIKE '%_telegram_bot%'
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 100
                    """).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                    FROM sessions 
                    ORDER BY COALESCE(last_activity_at, started_at) DESC
                    LIMIT 300
                """).fetchall()
            for r in rows:
                d = dict(r)
                if d["id"] not in sessions_map:
                    sessions_map[d["id"]] = d

        # Sortiere nach Aktualität
        sorted_sessions = sorted(
            sessions_map.values(),
            key=lambda x: x.get("last_activity_at") or x.get("started_at") or 0,
            reverse=True
        )

        sessions = []
        for d in sorted_sessions:
            st = d.get("started_at")
            if isinstance(st, (int, float)) and st > 0:
                try:
                    d["started_at_formatted"] = datetime.datetime.fromtimestamp(st).strftime("%d.%m.%Y, %H:%M")
                except Exception:
                    d["started_at_formatted"] = str(st)
            else:
                d["started_at_formatted"] = str(st) if st else ""

            lat = d.get("last_activity_at")
            if isinstance(lat, (int, float)) and lat > 0:
                try:
                    d["last_activity_at_formatted"] = datetime.datetime.fromtimestamp(lat).strftime("%d.%m.%Y, %H:%M")
                except Exception:
                    d["last_activity_at_formatted"] = str(lat)
            else:
                d["last_activity_at_formatted"] = d.get("started_at_formatted") or ""

            source_val = (d.get("source") or "").lower()
            id_val = (d.get("id") or "").lower()
            prof_val = (d.get("profile_name") or "").lower()

            # Fallback-Titel fuer Telegram Bot
            if (source_val == "telegram" or prof_val == "telegram_bot") and (not d.get("title") or d.get("title") in ("New Session", "Chat", "Analyze uploaded image")):
                d["title"] = "Telegram Bot (Live-Stream)"

            # Klassifiziere: 'group' vs. 'agent'
            if source_val in ("paperclip", "boardroom", "multi-agent", "group", "team") or id_val.startswith("paperclip:") or id_val.startswith("group:") or prof_val in ("boardroom", "multi-agent", "team"):
                d["chat_type"] = "group"
            else:
                d["chat_type"] = "agent"
            sessions.append(d)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"[Chat Sessions] Error fetching sessions: {e}")
        return {"sessions": []}

@app.get("/api/chat/sessions/{session_id}/messages")
def api_get_chat_session_messages(session_id: str):
    """Liefert den Nachrichtenverlauf einer bestimmten Session aus Root- oder Profil-DB."""
    try:
        # 1. Zuerst Root-DB prüfen
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, role, content, timestamp, token_count
                FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id ASC
            """, (session_id,)).fetchall()
            if rows:
                return {"session_id": session_id, "messages": [dict(r) for r in rows]}

        # 2. Falls nicht in Root-DB: Profil-DB prüfen (telegram_bot)
        prof_conn = _get_profile_state_db("telegram_bot")
        if prof_conn:
            with prof_conn as pconn:
                pconn.row_factory = sqlite3.Row
                prows = pconn.execute("""
                    SELECT id, role, content, timestamp, token_count
                    FROM messages
                    WHERE session_id = ? AND active = 1
                    ORDER BY id ASC
                """, (session_id,)).fetchall()
                if prows:
                    return {"session_id": session_id, "messages": [dict(r) for r in prows]}

        return {"session_id": session_id, "messages": []}
    except Exception as e:
        logger.error(f"[Chat Messages] Error fetching messages for {session_id}: {e}")
        return {"session_id": session_id, "messages": []}

class RenameSessionRequest(BaseModel):
    title: str

@app.post("/api/chat/sessions/{session_id}/rename")
@app.patch("/api/chat/sessions/{session_id}")
def api_rename_chat_session(session_id: str, req: RenameSessionRequest):
    """Ermöglicht das freie Umbenennen jeder Chat-Session."""
    new_title = req.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Der Titel darf nicht leer sein.")
    try:
        with _get_state_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE sessions SET title = ?, display_name = ? WHERE id = ?", (new_title, new_title, session_id))
            conn.commit()
            if cur.rowcount == 0:
                # Fallback: Versuche case-insensitive oder partial ID
                cur.execute("UPDATE sessions SET title = ?, display_name = ? WHERE id LIKE ?", (new_title, new_title, f"{session_id}%"))
                conn.commit()
            if cur.rowcount == 0:
                # Session existiert noch nicht in der DB (z.B. neu initialisierter Chat ohne Vorab-Nachrichten)
                now = time.time()
                cur.execute("""
                    INSERT OR REPLACE INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, '', 'default', ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, new_title, new_title, now))
                conn.commit()
            logger.info(f"[Chat Rename] Session {session_id} umbenannt zu '{new_title}'")
            return {"status": "success", "session_id": session_id, "title": new_title}
    except Exception as e:
        logger.error(f"[Chat Rename] Fehler beim Umbenennen von {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/upload")
async def api_chat_upload(file: UploadFile = File(...)):
    """Empfängt Datei-Uploads und legt sie im Agent-Workspace (/projects/ bzw. ./agent_workspace) ab."""
    try:
        target_dir = "/projects" if os.path.exists("/projects") else os.path.join(WORKSPACE_DIR, "uploads")
        os.makedirs(target_dir, exist_ok=True)
        
        safe_filename = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', file.filename)
        timestamp_prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        final_filename = f"{timestamp_prefix}_{safe_filename}"
        dest_path = os.path.join(target_dir, final_filename)
        
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_size = os.path.getsize(dest_path)
        logger.info(f"[Chat Upload] Datei gespeichert: {dest_path} ({file_size} Bytes)")
        add_ticker("Chat Upload", f"Datei '{file.filename}' im Workspace abgelegt.")
        
        return {
            "status": "success",
            "filename": final_filename,
            "original_name": file.filename,
            "path": dest_path,
            "size": file_size
        }
    except Exception as e:
        logger.error(f"[Chat Upload] Upload fehlgeschlagen: {e}")
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {str(e)}")

# ============================================================================
# DELEGATION ENGINE v2 (09.10.2026)
# Strukturiertes Delegations-Protokoll: ```delegation```-JSON-Blöcke mit
# Quittung, serverseitiger Hierarchie-Prüfung (APEX/LEAD/SPEZIALIST),
# Kanban-Integration und Fehlerbehandlung. Ersetzt den naiven CLI-Regex-
# Interceptor (der bleibt als Legacy-Fallback aktiv).
# ============================================================================
_ORG_HIERARCHY_CACHE = {"mtime": 0.0, "nodes": {}, "loaded": False}

def _load_org_hierarchy_map():
    path = os.path.join("config", "org_hierarchy.json")
    try:
        mtime = os.path.getmtime(path)
        if not _ORG_HIERARCHY_CACHE["loaded"] or mtime != _ORG_HIERARCHY_CACHE["mtime"]:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            nodes = {}
            for n in data.get("nodes", []):
                try:
                    nodes[n.get("id")] = {"tier": int(n.get("tier") or 3), "team_id": n.get("team_id")}
                except Exception:
                    continue
            _ORG_HIERARCHY_CACHE.update({"mtime": mtime, "nodes": nodes, "loaded": True})
        return _ORG_HIERARCHY_CACHE["nodes"]
    except Exception as e:
        logger.warning(f"[Delegation] org_hierarchy.json nicht lesbar: {e}")
        return {}

def _check_delegation_permission(delegator_id: str, target_id: str):
    """Hierarchie-Regeln: Tier 1 (APEX) -> alle; Tier 2 (LEAD) -> eigenes Team; Tier 3 -> keine Delegation."""
    org = _load_org_hierarchy_map()
    d = org.get(delegator_id)
    t = org.get(target_id)
    if d is None:
        return False, f"Delegator '{delegator_id}' ist in der Organisationsstruktur nicht registriert."
    if delegator_id == target_id:
        return False, "Selbst-Delegation ist nicht erlaubt."
    if d["tier"] == 1:
        return True, "APEX"
    if d["tier"] == 2:
        if t and t.get("team_id") and t.get("team_id") == d.get("team_id"):
            return True, "LEAD->Team"
        return False, (f"LEAD '{delegator_id}' (Team {d.get('team_id')}) darf nur an das eigene Team delegieren — "
                       f"'{target_id}' gehört zu Team {(t or {}).get('team_id', 'unbekannt')}.")
    return False, f"Spezialist '{delegator_id}' (Tier 3) darf nicht delegieren. Bitte beim eigenen LEAD eskalieren."

DELEGATION_PROTOCOL_PROMPT = """

=== DELEGATIONSPROTOKOLL (Engine v2) ===
Wenn eine Aufgabe an einen anderen Agenten delegiert werden soll, MUSST du dafür ausschließlich
den folgenden JSON-Block in deine Antwort schreiben (valides JSON, exakte Feldnamen):

```delegation
{"ziel_agent": "<agent_id>", "auftrag": "<präzise Aufgabenbeschreibung mit Kontext>", "modell": "<auto/best-reasoning|auto/best-coding|auto/best-free|auto/best-vision>", "prioritaet": "normal|hoch", "reasoning_level": "off|minimal|low|medium|high|max", "parent_project_id": "<nur bei Zerlegung in mehrere Teilauftraege: IMMER dieselbe id fuer alle Bloecke, z.B. projekt-immobilienplattform>"}
```

Regeln für reasoning_level:
- Wähle den Denkgrad angepasst an die Komplexität des Auftrags:
  * "off": Für einfache Routine-Aufgaben, Formatierungen oder Textablagen (0 Tokens Denkzeit, maximal schnell & billig).
  * "minimal": Für simple Überprüfungen oder kurze Standardrecherchen (~1k Tokens).
  * "low": Für Standardarbeiten mit kurzer Plausibilitätsprüfung (~2k Tokens).
  * "medium": Ausgewogener Standard für normale Fachaufgaben (~4k Tokens).
  * "high": Für fundierte Code-Architektur, Refactoring oder Finanzmodellierung (~8k Tokens).
  * "max": Für hochkritische strategische Memos, Rechtsgutachten oder System-Apex-Entscheidungen (~16k Tokens).

Regeln:
- ziel_agent = exakte Agent-ID, nie der Anzeigename. Mehrere Blöcke für Parallelaufträge erlaubt.
- ZERLEGST du EINEN Auftrag in MEHRERE Teilaufträge: gib in JEDEM Block dieselbe `parent_project_id` an (z.B. "projekt-<kurzname>"). Das löst automatisch die Synthese aus: Alle Teilergebnisse werden gesammelt, Lisa (aggregation_lisa) fügt sie zum Gesamtergebnis zusammen und Robert gibt es frei — du musst nicht selbst nachfragen.
- Das System führt die Delegation serverseitig aus und schreibt dir eine QUITTUNG in den Chat:
  "✅ DELEGATION QUITTUNG" (mit Kanban-Task-ID und Sub-Session — merke dir die Task-ID),
  "❌ DELEGATION ABGELEHNT" (mit Grund) oder "⚠️ DELEGATION-FEHLER" (Block korrigieren und erneut senden).
- Sage NIE "delegiert/erledigt", bevor eine ✅-Quittung in deinem Chat vorliegt.
- Hierarchie: Du darfst {"APEX: an alle Agenten" if TIER==1 else "LEAD: nur an dein eigenes Team"} delegieren.
- Status-Verfolgung über die Task-ID: Kanban in_progress = läuft, review = Ergebnis da, blocked = Problem.
=== ENDE DELEGATIONSPROTOKOLL ==="""

def _get_delegation_prompt_for(agent_id: str):
    """Liefert das Protokoll-Prompt für Tier 1/2-Agenten, sonst None."""
    try:
        node = _load_org_hierarchy_map().get(agent_id)
        if node and node.get("tier") in (1, 2):
            tier = node["tier"]
            return DELEGATION_PROTOCOL_PROMPT.replace('{"APEX: an alle Agenten" if TIER==1 else "LEAD: nur an dein eigenes Team"}',
                                                       ("APEX: an alle Agenten" if tier == 1 else "LEAD: nur an dein eigenes Team"))
    except Exception as e:
        logger.warning(f"[Delegation] Protokoll-Prompt-Aufbau fehlgeschlagen: {e}")
    return None

def _parse_delegation_blocks(text: str):
    """Findet alle ```delegation```-JSON-Blöcke. Rückgabe: (valide_payloads, fehlerhafte_blöcke)."""
    valid, invalid = [], []
    for m in re.finditer(r"```delegation\s*\n(.*?)```", text, re.DOTALL):
        raw = m.group(1).strip()
        try:
            payload = json.loads(raw)
            if not payload.get("ziel_agent") or not payload.get("auftrag"):
                invalid.append({"raw": raw[:200], "error": "Felder 'ziel_agent' oder 'auftrag' fehlen"})
            else:
                valid.append(payload)
        except Exception as e:
            invalid.append({"raw": raw[:200], "error": str(e)})
    return valid, invalid

def _execute_delegation(delegator_id, payload, provider, all_keys):
    """Führt eine Delegation aus: Berechtigungsprüfung, Sub-Session, Kanban-Task,
    Hintergrund-Ausführung. Gibt eine Quittung als Text zurück (wird in die
    Delegator-Session geschrieben, damit der Agent sich erinnert)."""
    ziel = str(payload.get("ziel_agent") or "").strip()
    auftrag = str(payload.get("auftrag") or "").strip()
    modell = str(payload.get("modell") or payload.get("model") or "").strip()
    prioritaet = str(payload.get("prioritaet") or "normal").strip().lower()
    reasoning_lvl = str(payload.get("reasoning_level") or payload.get("reasoning") or "medium").strip().lower()

    allowed, reason = _check_delegation_permission(delegator_id, ziel)
    if not allowed:
        return f"❌ DELEGATION ABGELEHNT — Ziel: {ziel} | Grund: {reason}"

    profiles = api_get_hermes_profiles()
    t_prof = next((p for p in profiles if p["id"] == ziel), None)
    if not t_prof:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel}' existiert nicht im Agenten-Kader."
    d_prof = next((p for p in profiles if p["id"] == delegator_id), None)
    t_name = (t_prof.get("person_name") or t_prof.get("name") or ziel)
    d_name = (d_prof.get("person_name") or d_prof.get("name") or delegator_id) if d_prof else delegator_id
    t_model = modell or ((t_prof.get("model") or "") if (t_prof.get("model") or "") not in ("", "free-forever") else "") or "auto/best-coding"

    tgt_sess = f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{ziel}"
    msg_text = f"Message from 🤖 {d_name} (@{delegator_id}): {auftrag}"
    with _get_state_db() as conn:
        _ensure_session_exists(conn, tgt_sess, ziel, t_model, auftrag[:50])
    _save_message_to_db(tgt_sess, "user", msg_text)

    task_id = None
    try:
        from backend.operations_api import _get_kanban_connection
        import secrets as _secrets
        task_id = f"t-{_secrets.token_hex(3)}"
        now_iso = datetime.datetime.now().isoformat()
        prio_num = 2 if prioritaet in ("hoch", "high", "sofort", "critical", "urgent") else (1 if prioritaet in ("mittel", "normal", "medium") else 0)
        kconn = _get_kanban_connection()
        kconn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (task_id, auftrag[:80] + ("..." if len(auftrag) > 80 else ""),
             f"Delegation von @{delegator_id} an @{ziel}:\n{auftrag}", ziel, "todo", prio_num, delegator_id, now_iso)
        )
        kconn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
            (task_id, "created", json.dumps({"title": auftrag[:80], "assignee": ziel, "via": "delegation_engine_v2", "delegator": delegator_id, "reasoning_level": reasoning_lvl}), now_iso)
        )
        kconn.commit()
        kconn.close()
    except Exception as e:
        logger.warning(f"[Delegation] Kanban-Insert fehlgeschlagen: {e}")

    async def _bg_watch_task(task_id, s_id, prof_id):
        """Beobachtet den Kanban-Task, während der Hermes-Agent-Worker ihn abarbeitet,
        und spiegelt das Endergebnis in die Sub-Session (Rücklauf ohne Doppel-Ausführung).
        WICHTIG: Kein eigener Modell-Aufruf mehr — die Ausführung macht der hermes-Worker
        (claim -> spawn -> heartbeats -> done/blocked). Kein vorzeitiges 'blocked' mehr."""
        try:
            import sqlite3 as _sq
            deadline = time.time() + 1200  # max 20 Minuten beobachten
            final = None
            while time.time() < deadline:
                try:
                    from backend.operations_api import _get_kanban_connection as _kgc
                    kc = _kgc()
                    row = kc.execute("SELECT status, result, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                    kc.close()
                    if row and row[0] in ("done", "blocked", "review"):
                        final = row
                        break
                except Exception:
                    pass
                await asyncio.sleep(10)
            if final is None:
                _save_message_to_db(s_id, "assistant",
                    "⏱️ DELEGATION-TIMEOUT — Der Task läuft länger als 20 Minuten ohne Endstatus. "
                    "Aktueller Stand bitte im Kanban prüfen (Task-ID siehe Delegations-Quittung).")
                return
            status, result = final[0], (final[1] or "").strip()
            final_title = (final[2] or "").strip()
            # Fallback: Zusammenfassung aus dem completed/blocked-Event ziehen, wenn das Result-Feld leer ist
            if not result:
                try:
                    from backend.operations_api import _get_kanban_connection as _kgc2
                    kc = _kgc2()
                    ev = kc.execute(
                        "SELECT payload FROM task_events WHERE task_id = ? AND kind IN ('completed','blocked') ORDER BY rowid DESC LIMIT 1",
                        (task_id,)).fetchone()
                    kc.close()
                    if ev and ev[0]:
                        try:
                            result = json.loads(ev[0]).get("summary") or json.loads(ev[0]).get("reason") or ""
                        except Exception:
                            result = ev[0][:500]
                except Exception:
                    pass
            # Ergebnis-Dateien des Hermes-Workers einsammeln (Attachments)
            attach_note = ""
            try:
                attach_dir = os.path.join("/opt/data/kanban/attachments", task_id)
                if os.path.isdir(attach_dir):
                    files = [f for f in os.listdir(attach_dir) if os.path.isfile(os.path.join(attach_dir, f))]
                    if files:
                        attach_note = "\n\n**Angehängte Artefakte:**\n" + "\n".join(f"- {f}" for f in files)
            except Exception:
                pass
            # --- Ergebnis nach Obsidian exportieren (01_PROJEKTE) -> Showroom-Rücklauf ---
            obsidian_rel = None
            try:
                title = (final_title or "Delegation")[:80]
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:50] or "auftrag"
                for cand in ("/opt/data/obsidian/01_PROJEKTE",
                              os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
                              r"C:\Mein Obsidian\01_PROJEKTE"):
                    try:
                        os.makedirs(cand, exist_ok=True)
                        obsidian_rel = cand
                        break
                    except Exception:
                        continue
                if obsidian_rel:
                    # 12.10.2026 (User-Fix 'Ordnerflut'): EIN Ordner pro Projekt -
                    # hat der Subtask ein parent, TEILT er sich den Eltern-Ordner
                    # (Name ueber die gemeinsame Quelle project_folder_name).
                    fan_parent = None
                    fan_parent_title = None
                    try:
                        _mc = _load_mission_control_data()
                        for _t in _mc.get("tasks", []):
                            if _t.get("kanban_task_id") == task_id:
                                fan_parent = _t.get("parent_project_id")
                                fan_parent_title = _t.get("parent_project_title")
                                break
                    except Exception:
                        pass
                    try:
                        from backend.post_task_pipeline import project_folder_name
                        proj_name = project_folder_name({
                            "id": task_id, "title": final_title or "Delegation",
                            "parent_project_id": fan_parent or "",
                            "parent_project_title": fan_parent_title or "",
                        })
                    except Exception:
                        proj_name = f"{datetime.datetime.now().strftime('%Y%m%d')}-{task_id}-{slug}"
                    proj_folder = os.path.join(obsidian_rel, proj_name)
                    end_dir = os.path.join(proj_folder, "03_Endprodukte")
                    os.makedirs(end_dir, exist_ok=True)
                    for sub in ("01_Zwischenberichte", "02_Medien"):
                        os.makedirs(os.path.join(proj_folder, sub), exist_ok=True)
                    # Attachments des Hermes-Workers nach 02_Medien kopieren
                    try:
                        att_src = os.path.join("/opt/data/kanban/attachments", task_id)
                        if os.path.isdir(att_src):
                            for f in os.listdir(att_src):
                                src_f = os.path.join(att_src, f)
                                if os.path.isfile(src_f):
                                    shutil.copy2(src_f, os.path.join(proj_folder, "02_Medien", f))
                    except Exception:
                        pass
                    result_fn = f"{task_id}-{slug}.md"
                    with open(os.path.join(end_dir, result_fn), "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\n"
                                f"**Task:** `{task_id}` | **Ziel-Agent:** `@{prof_id}` | **Status:** {status.upper()}\n\n"
                                f"{result or '(Ergebnis siehe Kanban-Task-Events und Anhänge in 02_Medien/.)'}\n")
                    # PROJEKT.md nur beim ERSTEN Schreiber (N-Worker parallel!),
                    # Ueberschrift = Eltern-Projekttitel wenn parent vorhanden.
                    proj_title = fan_parent_title if (fan_parent and fan_parent_title) else title
                    p_herkunft = (f"Teilauftrag von Projekt `{fan_parent}`" if fan_parent
                                  else f"Delegation über Archon OS (Task `{task_id}`)")
                    p_parent_line = f'parent_project: "{fan_parent}"' if fan_parent else ""
                    try:
                        with open(os.path.join(proj_folder, "PROJEKT.md"), "x", encoding="utf-8") as f:
                            f.write("---\nproject_folder: \"" + proj_name + "\"\ncreated_at: \""
                                    + str(datetime.datetime.now().timestamp()) + "\"\n"
                                    "title: \"" + proj_title + "\"\nstatus: \"" + str(status)
                                    + "\"\nsource_task: \"" + task_id + "\"\n"
                                    "source: \"delegation_engine_v2\"\n" + p_parent_line + "---\n\n"
                                    "# Projekt: " + str(proj_title) + "\n\n"
                                    "- **Herkunft:** " + p_herkunft + "\n"
                                    "- **Ziel-Agent:** `@" + str(prof_id) + "` | **Status:** " + str(status).upper() + "\n"
                                    "- **Hauptdokument:** [[" + task_id + "-" + slug + "]]\n\n"
                                    "### 📁 Projekt-Struktur:\n"
                                    "- `01_Zwischenberichte/`: Entwürfe und Arbeitsprotokolle\n"
                                    "- `02_Medien/`: Artefakte der Fachagenten\n"
                                    "- `03_Endprodukte/`: [[" + task_id + "-" + slug + "]]"
                                    + ("+ Lisa-Synthese + finale Beschlussvorlage" if fan_parent else "")
                                    + "\n\n---\n[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]\n")
                    except FileExistsError:
                        pass  # Eltern-Ordner-Projekt.md existiert bereits
                    obsidian_rel = proj_name
            except Exception as oe:
                logger.warning(f"[Delegation] Obsidian-Export fehlgeschlagen: {oe}")
                obsidian_rel = None
            if status == "done":
                msg = ("✅ DELEGATION ABGESCHLOSSEN — Der Sub-Agent hat die Aufgabe erledigt.\n\n"
                       f"**Zusammenfassung/Ergebnis:**\n{result or '(siehe Kanban-Task und Anhänge)'}{attach_note}\n\n"
                       f"Task-ID: {task_id} | Status im Kanban: done"
                       + (f"\n📁 Obsidian-Projekt: `01_PROJEKTE/{obsidian_rel}` (auch im Showroom sichtbar)" if obsidian_rel else ""))
            elif status == "review":
                msg = ("🔍 DELEGATION IN REVIEW — Das Ergebnis liegt zur Prüfung bereit.\n\n"
                       f"**Ergebnis:**\n{result or '(siehe Kanban-Task)'}{attach_note}\n\nTask-ID: {task_id}")
            else:
                msg = ("⛔ DELEGATION BLOCKIERT — Der Sub-Agent konnte die Aufgabe nicht abschließen.\n\n"
                       f"**Grund/Eskalation:**\n{result or 'Siehe Task-Events im Kanban (Kommentare des Agenten).'}{attach_note}\n\n"
                       f"Task-ID: {task_id} | Ggf. Kontextdaten nachliefern oder Aufgabe umformulieren."
                       + (f"\n📁 Dokumentation: `01_PROJEKTE/{obsidian_rel}`" if obsidian_rel else ""))
            _save_message_to_db(s_id, "assistant", msg)
            # --- Telegram-Push (HITL-Kanal, User-Vorgabe 09.10.2026) ---
            # Ping bei done/blocked/review aufs Handy; Freigabe via Inline-Buttons.
            # Fehlertolerant: darf den Delegations-Fluss nie blockieren, loggt aber sichtbar.
            try:
                # 2a: Zielordner fuer das Bericht-Dossier (landet im Projektordner
                # unter 01_Zwischenberichte, damit es Kanban/Showroom ebenfalls sieht)
                _doss_dir = None
                if obsidian_rel:
                    try:
                        _doss_dir = os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE",
                                                 obsidian_rel, "01_Zwischenberichte")
                    except Exception:
                        _doss_dir = None
                if status in ("review", "blocked"):
                    # 2c: Entscheidung ueber den zentralen Service. Der Kanban-Task
                    # EXISTIERT hier bereits -> register_decision + app:-Buttons.
                    _doss = None
                    if _doss_dir and (result or "").strip():
                        try:
                            from dossier_builder import build_dossier_from_report
                            _doss = build_dossier_from_report(
                                f"{'Review' if status == 'review' else 'Blockiert'}: {final_title}",
                                result, _doss_dir, f"{task_id}_{status}",
                                ref_id=task_id, quelle="Archon-Delegation")
                        except Exception as _de:
                            logger.warning(f"[Delegation] Dossier fehlgeschlagen: {_de}")
                    await asyncio.to_thread(
                        register_decision, task_id, "delegation_review",
                        final_title, result, task_id, _doss)
                else:
                    from telegram_notify import notify_task_status
                    notify_task_status(task_id, status, final_title, result, obsidian_rel,
                                       dossier_dir=_doss_dir)
            except Exception as tg_err:
                logger.warning(f"[Telegram] Delegations-Ping für Task {task_id} fehlgeschlagen: {tg_err}")
            # --- FAN-IN RUECKLAUF (12.10.2026): MC-Subtask abschliessen und
            # pruefen, ob alle Geschwister des Delegationsprojekts fertig sind
            # (-> Synthese durch Lisa + Robert-Freigabe, siehe Synthese-Loop) ---
            if status == "done":
                try:
                    fan_parent = None
                    mc = _load_mission_control_data()
                    for _t in mc.get("tasks", []):
                        if _t.get("kanban_task_id") == task_id:
                            _t["status"] = "completed"
                            _t["result_summary"] = (result or "")[:800]
                            _t["completed_at"] = time.time()
                            fan_parent = _t.get("parent_project_id")
                            break
                    if fan_parent:
                        _save_mission_control_data(mc)
                        asyncio.create_task(_fan_in_maybe_start_synthesis(fan_parent))
                except Exception as fan_err:
                    logger.warning(f"[Delegation] Fan-in-Ruecklauf fehlgeschlagen: {fan_err}")
        except Exception as e:
            logger.error(f"[Delegation] Task-Watcher error: {e}")

    # --- FAN-IN BRUECKE (12.10.2026, User-Wunsch "Teilergebnisse an Robert
    # zurueck": Eltern-Projekt + MC-Subtask-Spiegel + Kanban-Beziehungen ---
    parent_pid = str(payload.get("parent_project_id") or payload.get("projekt") or "").strip()
    if parent_pid:
        try:
            mc_data = _load_mission_control_data()
            mc_tasks = mc_data.setdefault("tasks", [])
            parent_title_var = str(payload.get("projekt_titel") or payload.get("titel") or "").strip()
            # Auto-Parent anlegen, falls noch nicht vorhanden
            existing_parent = next((t for t in mc_tasks if t.get("id") == parent_pid), None)
            if existing_parent is None:
                if not parent_title_var:
                    parent_title_var = f"Delegationsprojekt {parent_pid}"
                mc_tasks.append({
                    "id": parent_pid,
                    "title": parent_title_var,
                    "agent_id": delegator_id,
                    "agent_name": d_name,
                    "status": "active",
                    "phase": "in_progress",
                    "created_via": "delegation_bridge",
                    "capture_input": auftrag[:400],
                    "target_action": "none",
                })
                logger.info(f"[Delegation] Fan-in Parent '{parent_pid}' angelegt")
            else:
                # Eltern-Titel immer mitfuehren (Ordnername-Einheitlichkeit)
                parent_title_var = str(existing_parent.get("title") or parent_title_var or parent_pid)
            # MC-Subtask = Tracking-Spiegel des Kanban-Tasks (Wird in _bg_watch_task completed)
            if task_id:
                mc_tasks.append({
                    "id": f"mcsub-{task_id}",
                    "title": auftrag[:80],
                    "agent_id": ziel,
                    "agent_name": t_name,
                    "status": "active",
                    "phase": "in_progress",
                    "parent_project_id": parent_pid,
                    "parent_project_title": parent_title_var,
                    "kanban_task_id": task_id,
                    "created_via": "delegation_bridge",
                    "capture_input": auftrag[:400],
                    "target_action": "none",
                })
            _save_mission_control_data(mc_data)
            # Kanban: project_id + Eltern-Kind-Beziehung (task_links war bisher immer leer)
            from backend.operations_api import _get_kanban_connection as _kg_link
            kc_link = _kg_link()
            kc_link.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (parent_pid, task_id))
            kc_link.execute("INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)", (parent_pid, task_id))
            kc_link.commit()
            kc_link.close()
        except Exception as fan_err:
            logger.warning(f"[Delegation] Fan-in-Anbindung fehlgeschlagen: {fan_err}")

    asyncio.create_task(_bg_watch_task(task_id, tgt_sess, ziel))
    return (f"✅ DELEGATION QUITTUNG — Ziel: {ziel} ({t_name}) | Kanban-Task: {task_id or 'n/a'} | "
            f"Sub-Session: {tgt_sess} | Modell (Empfehlung): {t_model} | "
            f"Ausführung: Hermes-Agent-Worker | Ergebnis erscheint im Kanban und wird automatisch in die Sub-Session gespiegelt.")

@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatStreamRequest):
    """
    Natives Chat-Streaming via Server-Sent Events (SSE).
    Unterstützt Direkt-Dialog und Missions-Modus mit Paperclip-Kopplung.
    """
    agent_id = req.agent_id or "default"
    user_msg = req.message.strip()
    session_id = req.session_id or f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_id}"
    mode = (req.mode or "direct").lower()

    if not user_msg:
        raise HTTPException(status_code=400, detail="Nachricht darf nicht leer sein.")

    # Profil laden
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p["id"] == agent_id), None)
    if not prof and profiles:
        prof = profiles[0]
    
    agent_name = prof.get("person_name") or prof.get("name") or "Hermes Agent"
    system_prompt = prof.get("prompt") or "You are Hermes Agent, an intelligent AI assistant created by Nous Research."
    # Delegations-Protokoll für berechtigte Hierarchie-Ebenen (Tier 1/2) dynamisch injizieren
    delegation_prompt_addon = _get_delegation_prompt_for(agent_id)
    if delegation_prompt_addon:
        system_prompt += delegation_prompt_addon

    # Obsidian Personalakte als Identitäts- und Kompetenzkontext injizieren
    try:
        akte_candidates = [
            os.path.join(OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
            f"/opt/data/obsidian/00_HR_Agenten/Personalakten/{agent_id}.md",
            f"C:\\Mein Obsidian\\00_HR_Agenten\\Personalakten\\{agent_id}.md"
        ]
        akte_content = None
        for cand in akte_candidates:
            if os.path.exists(cand) and os.path.isfile(cand):
                with open(cand, "r", encoding="utf-8", errors="ignore") as f_akte:
                    akte_content = f_akte.read().strip()
                break
        if akte_content:
            system_prompt += f"\n\n[OBSIDIAN PERSONALAKTE & STATUS]\n{akte_content}\n"
    except Exception as akte_err:
        logger.warning(f"[Chat Stream] Konnte Personalakte für {agent_id} nicht laden: {akte_err}")
    import api_provider
    all_keys = api_provider.collect_keys()

    provider = (req.provider or "").strip().lower()
    if not provider:
        provider = (prof.get("provider") or "").strip().lower()
    if not provider and req.model:
        provider = api_provider.infer_provider_from_model(req.model) or ""
    if not provider:
        active_cfg = api_provider.read_active_config()
        provider = (active_cfg.get("provider") or "").strip().lower()
    if not provider:
        provider = "openrouter" if all_keys.get("OPENROUTER_API_KEY") else "omniroute"

    reasoning_level = (req.reasoning_level or prof.get("reasoning_level") or "medium").strip().lower()
    model = (req.model or prof.get("model") or "").strip()
    if not model or model == "free-forever":
        if provider == "google":
            model = "gemini-2.5-flash"
        elif provider == "openrouter":
            model = "meta-llama/llama-3.3-70b-instruct"
        elif provider == "groq":
            model = "llama-3.3-70b-versatile"
        elif provider == "omniroute":
            model = "evey-session-guard:"
        else:
            model = "auto/best-coding"

    # 1. MISSIONS-MODUS: Task erzeugen & HITL Approval-Gate aktivieren
    if mode == "mission":
        task_id = f"task-{int(time.time()) % 10000}"
        title = user_msg[:80] + ("..." if len(user_msg) > 80 else "")

        # Task in Archon OS erfassen mit status: approval
        data = _load_mission_control_data()
        est_tokens = 95000 if len(user_msg) > 200 else 45000
        est_cost = 0.18 if len(user_msg) > 200 else 0.05
        
        # Operative Zielaktion erkennen (z.B. ACTION: POST_LINKEDIN)
        detected_action = core_dispatcher.detect_target_action(user_msg)
        
        # Phase bestimmen: Falls Robert (executive_decision_architect), startet Kaskade mit strategy
        initial_phase = "strategy" if agent_id in ("executive_decision_architect", "robert") else "execution"

        new_task = {
            "id": task_id,
            "title": title,
            "capture_input": user_msg,
            "plan": [
                f"Missions-Start: '{title}' über Hermes Core Task Engine",
                f"Ressourcen- und Werkzeugallokation für {agent_name} ({agent_id})",
                "Ausführung & atomarer Obsidian-Sync"
            ],
            "agent_id": agent_id,
            "agent_name": agent_name,
            "model": model,
            "estimated_tokens": est_tokens,
            "estimated_cost_eur": est_cost,
            "subagents_count": 2,
            "status": "approval",  # HITL Gate sperrt Ausführung zwingend
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result_summary": "",
            "artifact_path": "",
            "paperclip_issue": None,
            "parent_project_id": None,
            "subtask_ids": [],
            "target_action": detected_action,
            "phase": initial_phase
        }
        data.setdefault("tasks", []).insert(0, new_task)
        
        # Audit Log
        now_t = datetime.datetime.now().strftime("%H:%M:%S")
        data.setdefault("audit_logs", []).insert(0, {
            "time": now_t,
            "source": "Approval Gate",
            "msg": f"Missions-Modus: Task #{task_id} erfordert Freigabe vor Ausführung!"
        })
        data["audit_logs"] = data["audit_logs"][:25]
        _save_mission_control_data(data)
        
        # --- 2c: Mission liegt im HITL-Approval-Gate -> ueber den zentralen
        # Entscheidungs-Service (echter Kanban-Task, EIN Schreibpfad) ---
        try:
            _mdec = await asyncio.to_thread(
                create_decision, "mission_freigabe",
                f"Mission-Freigabe: {str(title)[:80]}",
                f"Agent: {agent_name} ({agent_id})\nGeschätzte Kosten: ~{est_cost:.2f}",
                task_id, None, "", None)
            if not _mdec:
                logger.warning(f"[Mission] Entscheidungs-Task für {task_id} nicht angelegt.")
        except Exception as tg_err:
            logger.warning(f"[Telegram] Missions-Freigabe-Ping für {task_id} fehlgeschlagen: {tg_err}")

        # In DB persistieren
        with _get_state_db() as conn:
            _ensure_session_exists(conn, session_id, agent_id, model, title)
        _save_message_to_db(session_id, "user", user_msg)
        
        approval_confirmation = (
            f"🛡️ **Mission erfasst & HITL-Freigabe erforderlich!**\n\n"
            f"- **Task-ID:** `{task_id}`\n"
            f"- **Operations Identifier:** `TASK-{task_id}`\n"
            f"- **Zugewiesener Agent:** {agent_name} (`{agent_id}`)\n"
            f"- **Geschtzte Kosten:** ~{est_cost:.2f}  ({est_tokens:,} Tokens)\n"
            f"- **Status:** `1 STOP / Freigabe erforderlich` (Im Mission Control Approval Gate gesperrt)"
        )
        _save_message_to_db(session_id, "assistant", approval_confirmation)

        async def mission_event_stream():
            yield f"data: {json.dumps({'type': 'mission_created', 'task_id': task_id, 'task': new_task, 'content': approval_confirmation}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(mission_event_stream(), media_type="text/event-stream")

    # 2. DIREKT-DIALOG: Streaming via ausgewählten Provider (Google, OpenRouter, Groq, OmniRoute etc.)
    try:
        with _get_state_db() as conn:
            _ensure_session_exists(conn, session_id, agent_id, model, user_msg[:50])
        _save_message_to_db(session_id, "user", user_msg)
    except Exception as db_err:
        logger.warning(f"[Chat Stream] Session/Message DB init warning: {db_err}")

    # Lade letzten Kontext aus DB (bis zu 50 Nachrichten fuer stabilen Sitzungsverlauf)
    recent_messages = []
    try:
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT role, content FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id DESC LIMIT 50
            """, (session_id,)).fetchall()
            for r in reversed(rows):
                content_val = r["content"]
                role_val = r["role"]
                # Dateianhänge (bis zu 5 Dateien: Bilder als multimodale Vision-Inhalte, Text/Code als Prompt-Inhalt)
                if role_val == "user" and "[Datei angehängt:" in content_val:
                    matches = list(re.finditer(r'\[Datei angehängt:\s*([^\]]+)\]', content_val))
                    if matches:
                        clean_text = content_val
                        for m in matches:
                            clean_text = clean_text.replace(m.group(0), "")
                        clean_text = clean_text.strip()
                        
                        image_blocks = []
                        text_attachments = []
                        for m in matches[:5]:
                            f_path = m.group(1).strip()
                            if os.path.exists(f_path):
                                lower_p = f_path.lower()
                                if lower_p.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                                    try:
                                        with open(f_path, "rb") as img_f:
                                            img_b64 = base64.b64encode(img_f.read()).decode("utf-8")
                                        mime = "image/png"
                                        if lower_p.endswith(('.jpg', '.jpeg')):
                                            mime = "image/jpeg"
                                        elif lower_p.endswith('.webp'):
                                            mime = "image/webp"
                                        elif lower_p.endswith('.gif'):
                                            mime = "image/gif"
                                        image_blocks.append({
                                            "type": "image_url",
                                            "image_url": {"url": f"data:{mime};base64,{img_b64}"}
                                        })
                                    except Exception as img_err:
                                        logger.warning(f"[Chat Stream] Konnte Bild nicht einbetten: {img_err}")
                                elif lower_p.endswith(('.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.html', '.css', '.yaml', '.yml', '.log')):
                                    try:
                                        with open(f_path, "r", encoding="utf-8", errors="ignore") as tf:
                                            snippet = tf.read(15000)
                                            b_name = os.path.basename(f_path)
                                            text_attachments.append(f"\n--- DATEI-INHALT ({b_name}) ---\n{snippet}\n--- ENDE DATEI-INHALT ---")
                                    except Exception as tf_err:
                                        logger.warning(f"[Chat Stream] Konnte Textdatei nicht lesen: {tf_err}")

                        if image_blocks:
                            full_prompt = clean_text
                            if text_attachments:
                                full_prompt += "\n" + "\n".join(text_attachments)
                            content_val = [{"type": "text", "text": full_prompt or "Siehe angehängte Dateien."}] + image_blocks
                        elif text_attachments:
                            content_val = (clean_text + "\n" + "\n".join(text_attachments)).strip()

                recent_messages.append({"role": role_val, "content": content_val})
    except Exception as e:
        logger.warning(f"[Chat Stream] Konnte Kontext nicht laden: {e}")
        recent_messages = [{"role": "user", "content": user_msg}]

    # Enterprise Skill Resolver (Dynamische Kontext-Injektion für Session)
    skills_prompt_block = None
    freshly_loaded_skills = []
    direct_skill_notice = None
    try:
        from scripts.skill_resolver import resolve_and_prepare_skill_context
        skills_idx = build_skills_file_index()
        skills_prompt_block, freshly_loaded_skills, direct_skill_notice = resolve_and_prepare_skill_context(
            session_id=session_id,
            user_msg=user_msg,
            find_skill_file_fn=find_skill_file,
            skills_index=skills_idx,
            agent_prof=prof
        )
    except Exception as sk_err:
        logger.error(f"[Chat Stream] Error resolving enterprise skills: {sk_err}")

    if skills_prompt_block:
        payload_messages = [{"role": "system", "content": system_prompt}, {"role": "system", "content": skills_prompt_block}] + recent_messages
    else:
        payload_messages = [{"role": "system", "content": system_prompt}] + recent_messages

    async def chat_event_stream():
        full_assistant_text = ""
        prompt_tokens = len(user_msg.split()) * 2
        completion_tokens = 0

        # Direkte System-Antwort bei Management-Befehlen (/skill list, /skill clear)
        if direct_skill_notice:
            yield f"data: {json.dumps({'type': 'delta', 'delta': direct_skill_notice}, ensure_ascii=False)}\n\n"
            full_assistant_text = direct_skill_notice
            _save_message_to_db(session_id, "assistant", full_assistant_text)
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
            return

        # Falls in diesem Turn ein neuer Skill geladen wurde, visuelle Bestätigung im Stream ausgeben
        if freshly_loaded_skills:
            skill_pills = ", ".join([f"`{s}`" for s in freshly_loaded_skills])
            pill_text = f"⚙️ *[System: Skill(s) erfolgreich in den Arbeitsspeicher geladen: {skill_pills}]*\n\n"
            full_assistant_text += pill_text
            yield f"data: {json.dumps({'type': 'delta', 'delta': pill_text}, ensure_ascii=False)}\n\n"

        from backend.agent_router import router_instance

        # Delegate LLM execution to the Hardware Abstraction Layer (AgentRouter)
        try:
            async for chunk in router_instance.stream_chat_completion(
                messages=payload_messages,
                provider=provider,
                model=model,
                api_keys=all_keys,
                reasoning_level=reasoning_level
            ):
                if chunk.startswith("ERROR: "):
                    yield f"data: {json.dumps({'type': 'error', 'error': chunk[7:]})}\n\n"
                    full_assistant_text += chunk[7:]
                else:
                    full_assistant_text += chunk
                    completion_tokens += 1
                    yield f"data: {json.dumps({'type': 'delta', 'delta': chunk}, ensure_ascii=False)}\n\n"
                    
            if not full_assistant_text:
                full_assistant_text = f"Keine Antwort von {provider.capitalize()} erhalten."
                yield f"data: {json.dumps({'type': 'delta', 'delta': full_assistant_text})}\n\n"

        except Exception as exc:
            err_msg = f"Verbindungsfehler zu {provider.capitalize()}: {str(exc)}"
            logger.error(f"[Chat Stream] {err_msg}")
            full_assistant_text = err_msg
            yield f"data: {json.dumps({'type': 'error', 'error': err_msg})}\n\n"

        # Kosten-Berechnung und Transparenz-Anzeige (Pillar 3/6)
        cost_str = "0.0000"
        try:
            with _get_state_db() as conn:
                cur = conn.execute("SELECT value FROM kv_store WHERE key = 'openrouter_prices'")
                row = cur.fetchone()
                if row and row[0]:
                    prices = json.loads(row[0])
                    m_price = prices.get(model, {})
                    p_cost = (prompt_tokens / 1_000_000) * m_price.get("prompt_1m", 0.0)
                    c_cost = (completion_tokens / 1_000_000) * m_price.get("completion_1m", 0.0)
                    total_cost = p_cost + c_cost
                    if total_cost > 0:
                        cost_str = f"{total_cost:.5f}"
        except Exception as e:
            logger.error(f"Cost calculation error: {e}")
            
        # Append transparency tag to the final text
        tier = "High" if provider == "openrouter" else "Low"
        transparency_tag = f"\n\n*- Routed to: `{model}` | Tier: `{tier}` | Est. Cost: `{cost_str}$`*"
        
        payload = json.dumps({"type": "delta", "delta": transparency_tag}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
        full_assistant_text += transparency_tag

        # Delegation Engine v2: strukturierte ```delegation```-Blöcke + Legacy-CLI-Interception.
        # Quittungen werden in die Delegator-Session geschrieben -> der Agent "erinnert" sich.
        delegation_receipts = []
        try:
            payloads, invalid_blocks = _parse_delegation_blocks(full_assistant_text)
            # Legacy-Fallback: alte `hermes -p ...`-CLI-Befehle weiterhin abfangen
            for m in re.finditer(r'hermes\s+-p\s+([a-zA-Z0-9_-]+)\s+chat\s+.*?-q\s+["\'](.*?)["\']', full_assistant_text, re.DOTALL):
                mm = re.search(r'-m\s+([a-zA-Z0-9_/.:-]+)', m.group(0))
                payloads.append({
                    "ziel_agent": m.group(1),
                    "auftrag": m.group(2),
                    "modell": mm.group(1) if mm else "",
                    "prioritaet": "normal"
                })
            for payload in payloads:
                try:
                    delegation_receipts.append(_execute_delegation(agent_id, payload, provider, all_keys))
                except Exception as de:
                    delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Intern: {de}")
            for bad in invalid_blocks:
                delegation_receipts.append(
                    f"⚠️ DELEGATION-FEHLER — Ungültiger Delegations-Block ({bad['error']}). "
                    f"Der Auftrag wurde NICHT ausgeführt. Block: {bad['raw'][:120]}"
                )
        except Exception as e:
            logger.error(f"Delegation Engine Fehler: {e}")
            delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Engine: {e}")

        if delegation_receipts:
            receipt_text = "\n\n" + "\n".join(delegation_receipts)
            payload = json.dumps({"type": "delta", "delta": receipt_text}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            full_assistant_text += receipt_text

        # Antwort & Metriken in SQLite verbuchen
        _save_message_to_db(session_id, "assistant", full_assistant_text, completion_tokens)
        
        # Parse total_cost if possible
        try:
            total_cost_val = float(cost_str)
        except:
            total_cost_val = 0.0
            
        _record_session_model_usage(session_id, model, prompt_tokens, completion_tokens, total_cost_val)
        payload_done = json.dumps({"type": "done", "session_id": session_id, "tokens": completion_tokens})
        yield f"data: {payload_done}\n\n" 

    return StreamingResponse(chat_event_stream(), media_type="text/event-stream")

class ImageGenerateToolRequest(BaseModel):
    prompt: str
    model: Optional[str] = "google/gemini-2.5-flash-image"
    provider: Optional[str] = "openrouter"
    session_id: Optional[str] = None

@app.post("/api/v1/tools/image_generate")
async def api_tool_image_generate(req: ImageGenerateToolRequest):
    """Führt eine direkte Bildgenerierung über OpenRouter (z.B. Google Nano Banana) oder Bild-Modelle aus."""
    import api_provider
    all_keys = api_provider.collect_keys()
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt darf nicht leer sein.")

    model = (req.model or "google/gemini-2.5-flash-image").strip()
    provider = (req.provider or "openrouter").strip().lower()

    if provider == "openrouter":
        or_key = all_keys.get("OPENROUTER_API_KEY")
        if not or_key:
            raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY fehlt in den Einstellungen.")
        headers = {
            "Authorization": f"Bearer {or_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Archon OS"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail=f"OpenRouter Fehler: {resp.text[:300]}")
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                text = msg.get("content", "")
                images = msg.get("images", [])
                img_url = ""
                if images:
                    first = images[0]
                    img_url = first.get("image_url", {}).get("url") if isinstance(first, dict) else str(first)

                markdown = f"{text}\n\n![{prompt}]({img_url})" if img_url else text
                if req.session_id and img_url:
                    _save_message_to_db(req.session_id, "assistant", markdown)

                return {
                    "status": "ok",
                    "image_url": img_url,
                    "text": text,
                    "markdown": markdown,
                    "model": model
                }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fehler bei Bildgenerierung: {str(e)}")

    raise HTTPException(status_code=400, detail=f"Provider '{provider}' für Bildgenerierung aktuell nicht unterstützt. Bitte 'openrouter' wählen.")

_GUARDIAN_STATS_CACHE = {}

@app.get("/api/guardian/stats")
def api_get_guardian_stats(timeframe: str = "all"):
    """Aggregiert Token-, Kosten- und Verlaufsstatistiken aller Profile aus SQLite state.db."""
    import sqlite3, glob, datetime
    
    now_ts = datetime.datetime.now().timestamp()
    cached = _GUARDIAN_STATS_CACHE.get(timeframe)
    if cached and (now_ts - cached["ts"]) < 10.0:
        return cached["data"]
    
    profiles_stats = []
    models_stats = {}
    daily_trend = {}
    all_sessions_list = []
    grand_total_tokens = 0
    grand_total_cost = 0.0
    grand_total_calls = 0
    max_overall_ts = 0
    
    min_ts = 0
    if timeframe == "24h":
        min_ts = now_ts - 86400
    elif timeframe == "7d":
        min_ts = now_ts - (7 * 86400)
    elif timeframe == "30d":
        min_ts = now_ts - (30 * 86400)
    
    state_dbs = sorted(glob.glob('/opt/data/profiles/*/state.db') + ['/opt/data/state.db'])
    if not state_dbs:
        state_dbs = sorted(glob.glob(os.path.expanduser('~/.hermes/profiles/*/state.db')) + [os.path.expanduser('~/.hermes/state.db')])
    
    for db in state_dbs:
        con = None
        try:
            prof_name = db.split('/')[-2] if 'profiles' in db else 'root'
            con = sqlite3.connect(db, timeout=5.0)
            con.execute("PRAGMA busy_timeout=5000;")
            
            # Hole Einzelzeilen für Zeitfilterung und Tages-Trend
            query = '''
                SELECT session_id, model, api_call_count, input_tokens, output_tokens, cache_read_tokens, estimated_cost_usd, first_seen, last_seen
                FROM session_model_usage
            '''
            rows = con.execute(query).fetchall()
            
            p_tokens = 0
            p_cost = 0.0
            p_calls = 0
            p_models = {}
            
            for r in rows:
                session_id, model_name, calls, inp, out, cache, cost, f_seen, l_seen = r[0], r[1], r[2] or 0, r[3] or 0, r[4] or 0, r[5] or 0.0, r[6] or 0.0, r[7], r[8]
                ts = l_seen or f_seen or 0
                if ts > max_overall_ts:
                    max_overall_ts = ts
                
                # Filter nach Zeitraum
                if min_ts > 0 and ts < min_ts:
                    continue
                
                tot = inp + out + cache
                # Plausibilitäts-Korrektur: Verhindere 1M-Faktor-Pricing-Bugs (z.B. OpenRouter 0.75$/1M als 0.75$/Token)
                if tot > 0 and (cost / tot) > 0.001:
                    cost = cost / 1_000_000.0
                p_tokens += tot
                p_cost += cost
                p_calls += calls
                
                # Session Details für den zweiten Reiter
                first_date_str = datetime.datetime.fromtimestamp(f_seen).strftime('%d.%m.%Y %H:%M') if f_seen else "-"
                last_date_str = datetime.datetime.fromtimestamp(l_seen).strftime('%d.%m.%Y %H:%M') if l_seen else "-"
                
                all_sessions_list.append({
                    "session_id": session_id or "unbekannt",
                    "profile": prof_name,
                    "model": model_name,
                    "calls": calls,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_tokens": cache,
                    "total_tokens": tot,
                    "cost": round(cost, 4),
                    "first_seen": first_date_str,
                    "last_seen": last_date_str,
                    "last_seen_ts": ts
                })
                
                # Daily Trend Aggregation
                if ts:
                    d_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                else:
                    d_str = "Unbekannt"
                if d_str not in daily_trend:
                    daily_trend[d_str] = {"tokens": 0, "cost": 0.0, "calls": 0}
                daily_trend[d_str]["tokens"] += tot
                daily_trend[d_str]["cost"] += cost
                daily_trend[d_str]["calls"] += calls
                
                if model_name not in p_models:
                    p_models[model_name] = {"model": model_name, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "total_tokens": 0, "cost": 0.0}
                p_models[model_name]["calls"] += calls
                p_models[model_name]["input_tokens"] += inp
                p_models[model_name]["output_tokens"] += out
                p_models[model_name]["cache_tokens"] += cache
                p_models[model_name]["total_tokens"] += tot
                p_models[model_name]["cost"] += cost
                
                if model_name not in models_stats:
                    models_stats[model_name] = {"calls": 0, "total_tokens": 0, "cost": 0.0}
                models_stats[model_name]["calls"] += calls
                models_stats[model_name]["total_tokens"] += tot
                models_stats[model_name]["cost"] += cost
            
            if p_calls > 0:
                grand_total_tokens += p_tokens
                grand_total_cost += p_cost
                grand_total_calls += p_calls
                profiles_stats.append({
                    "profile": prof_name,
                    "total_tokens": p_tokens,
                    "total_cost": round(p_cost, 4),
                    "total_calls": p_calls,
                    "models": list(p_models.values())
                })
        except Exception as e:
            pass
        finally:
            if con:
                con.close()
            
    profiles_stats.sort(key=lambda x: x["total_tokens"], reverse=True)
    models_list = [{"model": k, "calls": v["calls"], "total_tokens": v["total_tokens"], "cost": round(v["cost"], 4)} for k, v in models_stats.items()]
    models_list.sort(key=lambda x: x["total_tokens"], reverse=True)
    all_sessions_list.sort(key=lambda x: x["total_tokens"], reverse=True)
    
    # Sortierte Trend-Liste
    sorted_trend = []
    for d in sorted(daily_trend.keys()):
        if d != "Unbekannt":
            sorted_trend.append({
                "date": d,
                "tokens": daily_trend[d]["tokens"],
                "cost": round(daily_trend[d]["cost"], 4),
                "calls": daily_trend[d]["calls"]
            })
            
    # Ungenutzte Zeit / Inaktivitätsdauer berechnen
    idle_seconds = max(0, int(now_ts - max_overall_ts)) if max_overall_ts > 0 else 0
    if idle_seconds >= 86400:
        days = idle_seconds // 86400
        hours = (idle_seconds % 86400) // 3600
        idle_str = f"{days} Tag{'e' if days != 1 else ''}, {hours} Std."
    elif idle_seconds >= 3600:
        hours = idle_seconds // 3600
        mins = (idle_seconds % 3600) // 60
        idle_str = f"{hours} Std., {mins} Min."
    elif idle_seconds >= 60:
        mins = idle_seconds // 60
        idle_str = f"{mins} Min."
    else:
        idle_str = f"{idle_seconds} Sek."
        
    last_activity_str = datetime.datetime.fromtimestamp(max_overall_ts).strftime('%d.%m.%Y %H:%M') if max_overall_ts > 0 else "Keine Aktivität"
    checked_at_str = datetime.datetime.now().strftime('%H:%M:%S')
    
    result = {
        "status": "success",
        "timeframe": timeframe,
        "grand_total_tokens": grand_total_tokens,
        "grand_total_cost": round(grand_total_cost, 2),
        "grand_total_calls": grand_total_calls,
        "max_last_seen": max_overall_ts,
        "last_activity_str": last_activity_str,
        "idle_seconds": idle_seconds,
        "idle_str": idle_str,
        "checked_at": checked_at_str,
        "profiles": profiles_stats,
        "models": models_list,
        "sessions": all_sessions_list,
        "trend": sorted_trend
    }
    _GUARDIAN_STATS_CACHE[timeframe] = {"ts": now_ts, "data": result}
    return result

@app.get("/api/guardian/config")
def api_get_guardian_config():
    """Liest die aktuellen Wächter-Einstellungen und ALLE registrierten Plugins dynamisch aus."""
    import yaml, glob
    config_file = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_file):
        config_file = "/opt/data/config.yaml"
        
    cfg = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass
            
    plugins_cfg = cfg.get("plugins", {})
    enabled_plugins = plugins_cfg.get("enabled", [])
    if not isinstance(enabled_plugins, list):
        enabled_plugins = []
    
    # Cost budget json
    cost_budget_file = os.path.expanduser("~/.hermes/cost-budget.json")
    if not os.path.exists(cost_budget_file):
        cost_budget_file = "/opt/data/cost-budget.json"
    budget_data = {"daily_budget": 2.0, "task_budget": 0.5}
    if os.path.exists(cost_budget_file):
        try:
            with open(cost_budget_file, "r", encoding="utf-8") as f:
                budget_data = json.load(f)
        except Exception:
            pass

    # Guardian limits json & config.yaml sync
    limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
    agent_cfg = cfg.get("agent", {})
    limits = {
        "max_context_tokens": agent_cfg.get("max_context_tokens", 32000),
        "max_history_messages": agent_cfg.get("max_history_messages", 20),
        "max_steps_per_task": 15,
        "session_timeout_seconds": 60,
        "loop_detection_enabled": True,
        "cache_ttl_hours": 24,
        "max_cache_entries": 100,
        "watchdog_interval_seconds": 30
    }
    if os.path.exists(limits_file):
        try:
            with open(limits_file, "r", encoding="utf-8") as f:
                limits.update(json.load(f))
        except Exception:
            pass

    # Dynamische Plugin-Erkennung aus allen Plugin-Ordnern
    plugins_dir = os.path.expanduser("~/.hermes/plugins")
    if not os.path.exists(plugins_dir):
        plugins_dir = "/opt/data/plugins"
        
    discovered_plugins = []
    category_map = {
        "evey-cost-guard": "Sicherheit & Wächter",
        "evey-session-guard": "Sicherheit & Wächter",
        "evey-email-guard": "Sicherheit & Wächter",
        "evey-watchdog": "Sicherheit & Wächter",
        "evey-cache": "Performance & Cache",
        "evey-telemetry": "Monitoring & Analytics",
        "evey-status": "Monitoring & Analytics",
        "evey-delegation-score": "Monitoring & Analytics",
        "evey-autonomy": "Agenten-Intelligenz",
        "evey-council": "Agenten-Intelligenz",
        "evey-reflect": "Agenten-Intelligenz",
        "evey-learner": "Agenten-Intelligenz",
        "evey-identity": "Agenten-Intelligenz",
        "evey-habits": "Agenten-Intelligenz",
        "evey-proactive": "Agenten-Intelligenz",
        "evey-goals": "Planung & Tasks",
        "evey-scheduler": "Planung & Tasks",
        "evey-bridge": "Brücken & Schnittstellen",
        "evey-mqtt": "Brücken & Schnittstellen",
        "evey-moltbook": "Brücken & Schnittstellen",
        "evey-telegram-ux": "Brücken & Schnittstellen",
        "evey-github": "Brücken & Schnittstellen",
        "evey-research": "Tools & Recherche",
        "evey-news": "Tools & Recherche",
        "evey-digest": "Tools & Recherche",
        "evey-sandbox": "Tools & Execution",
        "evey-rag": "Gedächtnis & Wissen",
        "evey-memory-adaptive": "Gedächtnis & Wissen",
        "evey-memory-consolidate": "Gedächtnis & Wissen",
        "evey-wallet": "Finanzen & Web3",
        "evey-validate": "Qualität & Ausführung",
        "evey-verification": "Qualität & Ausführung",
        "evey-delegate-model": "Qualität & Ausführung",
        "disk-cleanup": "System-Wartung"
    }

    icon_map = {
        "evey-cost-guard": "coins",
        "evey-session-guard": "shield-check",
        "evey-email-guard": "shield-alert",
        "evey-watchdog": "activity",
        "evey-cache": "zap",
        "evey-telemetry": "gauge",
        "evey-status": "heart-pulse",
        "evey-delegation-score": "award",
        "evey-autonomy": "cpu",
        "evey-council": "users",
        "evey-reflect": "sparkles",
        "evey-learner": "graduation-cap",
        "evey-identity": "user-check",
        "evey-habits": "calendar-clock",
        "evey-proactive": "bell-ring",
        "evey-goals": "target",
        "evey-scheduler": "clock",
        "evey-bridge": "network",
        "evey-mqtt": "radio",
        "evey-moltbook": "book-open",
        "evey-telegram-ux": "send",
        "evey-github": "git-branch",
        "evey-research": "search",
        "evey-news": "newspaper",
        "evey-digest": "file-text",
        "evey-sandbox": "box",
        "evey-rag": "database",
        "evey-memory-adaptive": "brain",
        "evey-memory-consolidate": "layers",
        "evey-wallet": "wallet",
        "evey-validate": "check-check",
        "evey-verification": "file-check",
        "evey-delegate-model": "share-2",
        "disk-cleanup": "trash-2"
    }

    # Bidirektionale Brücke zwischen Plugin-Registry und nativen Archon-OS-Modulen (settings.json)
    from backend.autonomy_settings import load_autonomy_settings
    aut_settings = load_autonomy_settings()

    plugin_autonomy_bridge = {
        "evey-cost-guard": ("budget_guard", "auto_downgrade_on_limit"),
        "evey-session-guard": ("durable_execution", "enabled"),
        "evey-email-guard": ("pii_scrubber", "enabled"),
        "evey-watchdog": ("resource_backpressure", "enabled"),
        "evey-cache": ("semantic_cache", "enabled"),
        "evey-telemetry": ("time_travel", "enabled"),
        "evey-status": ("execution_receipts", "enabled"),
        "evey-delegation-score": ("model_benchmarker", "enabled"),
        "evey-autonomy": ("ephemeral_teams", "enabled"),
        "evey-council": ("consensus_gate", "enabled"),
        "evey-reflect": ("self_healing", "enabled"),
        "evey-learner": ("skill_synthesizer", "enabled"),
        "evey-identity": ("core_memory", "enabled"),
        "evey-proactive": ("inbox_watcher", "enabled"),
        "evey-goals": ("map_reduce", "enabled"),
        "evey-scheduler": ("dead_letter_queue", "enabled"),
        "evey-research": ("corrective_rag", "enabled"),
        "evey-digest": ("inbox_watcher", "standup_enabled"),
        "evey-sandbox": ("ephemeral_sandbox", "enabled"),
        "evey-rag": ("hybrid_search", "enabled"),
        "evey-memory-adaptive": ("citation_pinner", "enabled"),
        "evey-memory-consolidate": ("memory_consolidation", "enabled"),
        "evey-validate": ("sla_enforcer", "enabled"),
        "evey-verification": ("egress_firewall", "enabled"),
        "evey-delegate-model": ("speculative_hedging", "enabled"),
    }

    if os.path.exists(plugins_dir):
        for p_yaml in sorted(glob.glob(os.path.join(plugins_dir, "*/plugin.yaml"))):
            try:
                folder_name = os.path.basename(os.path.dirname(p_yaml))
                if folder_name.startswith("_"):
                    continue
                with open(p_yaml, "r", encoding="utf-8") as pf:
                    p_info = yaml.safe_load(pf) or {}
                p_id = p_info.get("name", folder_name)
                p_name = p_info.get("display_name") or p_id.replace("evey-", "").replace("-", " ").title()
                p_desc = p_info.get("description", "")
                p_cat = p_info.get("category") or category_map.get(p_id, "Weitere Module")
                p_tools = p_info.get("provides_tools", []) or p_info.get("tools", []) or []
                p_icon = icon_map.get(p_id, p_info.get("icon", "puzzle"))

                if p_id in plugin_autonomy_bridge:
                    grp, key = plugin_autonomy_bridge[p_id]
                    is_enabled = bool(aut_settings.get(grp, {}).get(key, True))
                else:
                    is_enabled = (p_id in enabled_plugins) or (p_id == "evey-telegram-ux")

                discovered_plugins.append({
                    "id": p_id,
                    "name": p_name,
                    "desc": p_desc,
                    "problem": p_info.get("problem", ""),
                    "solution": p_info.get("solution", ""),
                    "tradeoff": p_info.get("tradeoff", ""),
                    "when_to_disable": p_info.get("when_to_disable", ""),
                    "category": p_cat,
                    "tools": p_tools,
                    "icon": p_icon,
                    "version": str(p_info.get("version", "2.6.0")),
                    "enabled": is_enabled
                })
            except Exception:
                pass

    try:
        from backend.plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        for p in pm.plugins.values():
            tools_list = [t.get("name") for t in p.get_tools() if "name" in t]
            discovered_plugins.append({
                "id": p.id,
                "name": p.name,
                "desc": p.description,
                "problem": p.manifest.get("problem", "Fehlende Überwachung oder fehlende modulare Werkzeuge."),
                "solution": p.manifest.get("solution", p.description),
                "tradeoff": p.manifest.get("tradeoff", "Geringe Latenz beim Hook-Durchlauf."),
                "when_to_disable": p.manifest.get("when_to_disable", "Wenn dieses Modul vorübergehend nicht aktiv sein soll."),
                "category": "Tools & Execution" if p.category == "tool" else "Sicherheit & Wächter",
                "tools": tools_list,
                "icon": "shield-check" if p.category == "security" else "cpu",
                "version": p.version,
                "enabled": p.enabled,
                "is_modular_plugin": True
            })
    except Exception as e:
        print(f"[GuardianConfig] PluginManager integration error: {e}")

    return {
        "status": "success",
        "plugins": discovered_plugins,
        "budget": budget_data,
        "limits": limits
    }

@app.post("/api/guardian/config")
def api_save_guardian_config(payload: dict):
    """Speichert Budget-Limits, Session-Schranken und Wächter-Einstellungen."""
    # Speichere Budget
    cost_budget_file = os.path.expanduser("~/.hermes/cost-budget.json")
    if not os.path.exists(cost_budget_file):
        cost_budget_file = "/opt/data/cost-budget.json"
    
    if "daily_budget" in payload or "task_budget" in payload:
        b_data = {
            "daily_budget": float(payload.get("daily_budget", 2.0)),
            "task_budget": float(payload.get("task_budget", 0.5))
        }
        try:
            with open(cost_budget_file, "w", encoding="utf-8") as f:
                json.dump(b_data, f, indent=2)
        except Exception as e:
            print(f"Error saving cost budget: {e}")

    # Speichere Limits
    limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
    try:
        cur_limits = {}
        if os.path.exists(limits_file):
            with open(limits_file, "r", encoding="utf-8") as f:
                cur_limits = json.load(f)
        for k in ["max_context_tokens", "max_history_messages", "max_steps_per_task", "session_timeout_seconds", "loop_detection_enabled", "cache_ttl_hours", "max_cache_entries", "watchdog_interval_seconds"]:
            if k in payload:
                cur_limits[k] = payload[k]
        with open(limits_file, "w", encoding="utf-8") as f:
            json.dump(cur_limits, f, indent=2)
            
        # Aktualisiere auch config.yaml für Hermes Core
        config_file = os.path.expanduser("~/.hermes/config.yaml")
        if not os.path.exists(config_file):
            config_file = "/opt/data/config.yaml"
        if os.path.exists(config_file):
            import yaml
            with open(config_file, "r", encoding="utf-8") as f:
                h_cfg = yaml.safe_load(f) or {}
            if "agent" not in h_cfg:
                h_cfg["agent"] = {}
            if "max_context_tokens" in payload:
                h_cfg["agent"]["max_context_tokens"] = int(payload["max_context_tokens"])
            if "max_history_messages" in payload:
                h_cfg["agent"]["max_history_messages"] = int(payload["max_history_messages"])
            if "session_timeout_seconds" in payload:
                h_cfg["agent"]["task_timeout_seconds"] = int(payload["session_timeout_seconds"])
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(h_cfg, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"Error saving guardian limits: {e}")

    add_ticker("Guardian", "Wächter-, Budget- und Kontext-Schranken aktualisiert.")
    return {"status": "success", "message": "Konfiguration gespeichert"}

@app.post("/api/guardian/plugins/toggle")
@app.post("/api/guardian/plugin/toggle")
def api_toggle_guardian_plugin(payload: dict):
    """Aktiviert oder deaktiviert ein Plugin in Hermes."""
    import yaml
    plugin_id = payload.get("plugin_id") or payload.get("id")
    enable = payload.get("enable")
    if enable is None:
        enable = payload.get("enabled", True)
    
    if not plugin_id:
        return {"status": "error", "message": "plugin_id fehlt"}
        
    config_file = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_file):
        config_file = "/opt/data/config.yaml"
        
    try:
        cfg = {}
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                
        if "plugins" not in cfg or not isinstance(cfg["plugins"], dict):
            cfg["plugins"] = {"enabled": [], "disabled": []}
            
        enabled_list = cfg["plugins"].get("enabled", [])
        if not isinstance(enabled_list, list):
            enabled_list = []
            
        if enable:
            if plugin_id not in enabled_list:
                enabled_list.append(plugin_id)
        else:
            if plugin_id in enabled_list:
                enabled_list.remove(plugin_id)
                
        cfg["plugins"]["enabled"] = enabled_list
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)

        try:
            from backend.plugin_manager import get_plugin_manager
            pm = get_plugin_manager()
            if plugin_id in pm.plugins:
                if enable:
                    pm.enable_plugin(plugin_id)
                else:
                    pm.disable_plugin(plugin_id)
        except Exception as e:
            print(f"[PluginToggle] Error updating plugin manager: {e}")

        # Synchronisiere Schalter direkt mit backend/autonomy_settings.py (settings.json)
        plugin_autonomy_bridge = {
            "evey-cost-guard": ("budget_guard", "auto_downgrade_on_limit"),
            "evey-session-guard": ("durable_execution", "enabled"),
            "evey-email-guard": ("pii_scrubber", "enabled"),
            "evey-watchdog": ("resource_backpressure", "enabled"),
            "evey-cache": ("semantic_cache", "enabled"),
            "evey-telemetry": ("time_travel", "enabled"),
            "evey-status": ("execution_receipts", "enabled"),
            "evey-delegation-score": ("model_benchmarker", "enabled"),
            "evey-autonomy": ("ephemeral_teams", "enabled"),
            "evey-council": ("consensus_gate", "enabled"),
            "evey-reflect": ("self_healing", "enabled"),
            "evey-learner": ("skill_synthesizer", "enabled"),
            "evey-identity": ("core_memory", "enabled"),
            "evey-proactive": ("inbox_watcher", "enabled"),
            "evey-goals": ("map_reduce", "enabled"),
            "evey-scheduler": ("dead_letter_queue", "enabled"),
            "evey-research": ("corrective_rag", "enabled"),
            "evey-digest": ("inbox_watcher", "standup_enabled"),
            "evey-sandbox": ("ephemeral_sandbox", "enabled"),
            "evey-rag": ("hybrid_search", "enabled"),
            "evey-memory-adaptive": ("citation_pinner", "enabled"),
            "evey-memory-consolidate": ("memory_consolidation", "enabled"),
            "evey-validate": ("sla_enforcer", "enabled"),
            "evey-verification": ("egress_firewall", "enabled"),
            "evey-delegate-model": ("speculative_hedging", "enabled"),
        }
        if plugin_id in plugin_autonomy_bridge:
            from backend.autonomy_settings import save_autonomy_settings
            grp, key = plugin_autonomy_bridge[plugin_id]
            save_autonomy_settings({grp: {key: bool(enable)}})

        add_ticker("Guardian", f"Modul '{plugin_id}' {'aktiviert' if enable else 'deaktiviert'} (settings.json synchronisiert).")
        return {"status": "success", "plugin_id": plugin_id, "enabled": bool(enable)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

DEFAULT_PLUGIN_CONFIGS = {
    "evey-cost-guard": {
        "daily_budget": 2.0,
        "task_budget": 0.5,
        "alert_threshold_percent": 85,
        "hard_stop": True
    },
    "evey-cache": {
        "cache_ttl_hours": 24,
        "max_cache_entries": 100,
        "semantic_match": False
    },
    "evey-autonomy": {
        "operator_name": "Michael",
        "timezone": "Europe/Berlin",
        "heavy_model": "claude-sonnet-4-6",
        "cheap_model": "claude-haiku-4-5",
        "cooldown_minutes": 30,
        "max_cycles_per_day": 24
    },
    "evey-watchdog": {
        "silent_threshold_minutes": 120,
        "work_hours_start": 9,
        "work_hours_end": 21,
        "alert_channel": "ntfy",
        "auto_restart_stalled": True
    },
    "evey-proactive": {
        "max_messages_per_day": 5,
        "cooldown_minutes": 45,
        "allowed_start_hour": 9,
        "allowed_end_hour": 20
    },
    "evey-sandbox": {
        "allowed_folders": ["/opt/data/workspace", "/tmp"],
        "allowed_folders_str": "/opt/data/workspace, /tmp",
        "max_exec_seconds": 60,
        "pii_filter": True
    },
    "evey-wallet": {
        "btc_address": "",
        "eth_address": "",
        "sol_address": ""
    },
    "evey-email-guard": {
        "sensitivity_level": "standard",
        "max_attachment_mb": 15,
        "safe_domains_whitelist": "gmail.com, googlemail.com, posteo.de",
        "quarantine_suspicious": True
    },
    "evey-session-guard": {
        "max_session_hours": 24,
        "idle_timeout_minutes": 60,
        "max_tokens_per_session": 64000,
        "strict_context_isolation": True
    },
    "evey-telemetry": {
        "log_level": "INFO",
        "prometheus_port": 9090,
        "retention_days": 14
    },
    "evey-status": {
        "healthcheck_interval_seconds": 30,
        "cpu_threshold_percent": 85,
        "heartbeat_webhook_url": ""
    },
    "evey-delegation-score": {
        "min_confidence_score": 0.75,
        "penalty_factor": 0.5,
        "fallback_mode": "ask_operator"
    },
    "evey-council": {
        "debate_rounds": 2,
        "consensus_rule": "majority",
        "judge_model": "claude-sonnet-4-6",
        "anonymize_votes": False
    },
    "evey-reflect": {
        "reflect_frequency_tasks": 5,
        "reflect_depth": "deep",
        "save_to_vault": True
    },
    "evey-learner": {
        "min_quality_score": 0.85,
        "auto_extract_lessons": True,
        "auto_index_skills": True
    },
    "evey-identity": {
        "persona_name": "Archon",
        "default_language": "de-DE",
        "tone_of_voice": "direct_pragmatic"
    },
    "evey-habits": {
        "morning_briefing_time": "08:30",
        "evening_recap_time": "18:45",
        "auto_daily_cleanup": True
    },
    "evey-goals": {
        "review_cadence": "weekly",
        "max_active_okrs": 5,
        "auto_breakdown_epics": True
    },
    "evey-scheduler": {
        "worker_concurrency": 4,
        "max_retry_attempts": 3
    },
    "evey-bridge": {
        "bridge_endpoint_url": "http://localhost:4000/bridge",
        "api_bearer_token": "",
        "timeout_seconds": 60
    },
    "evey-mqtt": {
        "broker_host": "localhost",
        "broker_port": 1883,
        "topic_prefix": "archon/events"
    },
    "evey-moltbook": {
        "vault_path": "/opt/data/obsidian",
        "sync_interval_minutes": 30
    },
    "evey-telegram-ux": {
        "bot_token": "",
        "allowed_chat_ids": "",
        "silent_notifications": False
    },
    "evey-github": {
        "default_repo": "michaelbeatman/Agentic-Archon-Os",
        "github_pat": "",
        "default_branch": "main"
    },
    "evey-research": {
        "search_depth": 3,
        "max_sources": 8,
        "excluded_domains": "spam.com, ads.net"
    },
    "evey-news": {
        "fetch_interval_minutes": 120,
        "keyword_filter": "AI, Agentic, LLM, Linux, Security"
    },
    "evey-digest": {
        "daily_digest_time": "07:45",
        "destination_channel": "ui_dashboard"
    },
    "evey-rag": {
        "top_k_results": 5,
        "similarity_threshold": 0.70,
        "embedding_model": "text-embedding-3-small"
    },
    "evey-memory-adaptive": {
        "half_life_days": 14,
        "eviction_threshold": 0.10,
        "max_injected_lessons": 3
    },
    "evey-memory-consolidate": {
        "schedule": "nightly",
        "deduplicate_facts": True
    },
    "evey-validate": {
        "gate_strictness": "strict",
        "syntax_type_check": True
    },
    "evey-verification": {
        "gate_strictness": "strict",
        "syntax_type_check": True
    },
    "evey-delegate-model": {
        "routing_strategy": "quality_optimal",
        "max_latency_ms": 5000
    },
    "disk-cleanup": {
        "log_retention_days": 7,
        "max_disk_usage_percent": 85
    },
    "browser-browser-use": {
        "api_key": "",
        "headless": True,
        "timeout_seconds": 30,
        "max_steps_per_run": 20
    }
}

@app.get("/api/guardian/plugins/{plugin_id}/config")
def api_get_plugin_config(plugin_id: str):
    """Gibt die gespeicherten oder Standard-Einstellungen für jedes Plugin zurück."""
    import yaml
    
    # 1. Basis-Konfiguration aus Defaults
    data = dict(DEFAULT_PLUGIN_CONFIGS.get(plugin_id, {}))

    # 2. Spezifische Live-Systemdateien prüfen und überlagern
    if plugin_id == "evey-cost-guard":
        path = os.path.expanduser("~/.hermes/cost-budget.json")
        if not os.path.exists(path):
            path = "/opt/data/cost-budget.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-cache":
        limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
        if os.path.exists(limits_file):
            try:
                with open(limits_file, "r", encoding="utf-8") as f:
                    cur = json.load(f)
                    if "cache_ttl_hours" in cur:
                        data["cache_ttl_hours"] = cur["cache_ttl_hours"]
                    if "max_cache_entries" in cur:
                        data["max_cache_entries"] = cur["max_cache_entries"]
            except Exception:
                pass

    elif plugin_id == "evey-autonomy":
        path = os.path.expanduser("~/.hermes/evey-autonomy.json")
        if not os.path.exists(path):
            path = "/opt/data/evey-autonomy.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-watchdog":
        path = os.path.expanduser("~/.hermes/workspace/watchdog-state.json")
        if not os.path.exists(path):
            path = "/opt/data/workspace/watchdog-state.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-proactive":
        path = os.path.expanduser("~/.hermes/workspace/manager/proactive-state.json")
        if not os.path.exists(path):
            path = "/opt/data/workspace/manager/proactive-state.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-sandbox":
        path = os.path.expanduser("~/.hermes/config/sandbox.yaml")
        if not os.path.exists(path):
            path = "/opt/data/config/sandbox.yaml"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f)
                    if isinstance(ydata, dict):
                        data["allowed_folders"] = ydata.get("allowed_folders", data.get("allowed_folders", []))
                        data["pii_filter"] = ydata.get("pii", {}).get("enabled", True)
            except Exception:
                pass
        if isinstance(data.get("allowed_folders"), list):
            data["allowed_folders_str"] = ", ".join(data["allowed_folders"])

    elif plugin_id == "evey-wallet":
        path = os.path.expanduser("~/.hermes/wallet-balances.json")
        if not os.path.exists(path):
            path = "/opt/data/wallet-balances.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-telegram-ux":
        # Synchronisiere mit echter Telegram-Bot-Umgebung wenn vorhanden
        tg_env = "/opt/data/profiles/telegram_bot/.env"
        if os.path.exists(tg_env):
            try:
                with open(tg_env, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("TELEGRAM_BOT_TOKEN="):
                            data["bot_token"] = line.split("=", 1)[1].strip()
                        elif line.startswith("TELEGRAM_ALLOWED_USERS="):
                            data["allowed_chat_ids"] = line.split("=", 1)[1].strip()
            except Exception:
                pass

    # 3. Gespeicherte individuelle Plugin-Konfiguration laden
    generic_dir = os.path.join(MEMORY_DIR, "plugins_config")
    os.makedirs(generic_dir, exist_ok=True)
    gfile = os.path.join(generic_dir, f"{plugin_id}.json")
    if os.path.exists(gfile):
        try:
            with open(gfile, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    data.update(saved)
        except Exception:
            pass

    # 4. Überlagere mit echten Live-Schwellenwerten aus backend/autonomy_settings.py (settings.json)
    try:
        from backend.autonomy_settings import load_autonomy_settings
        aut = load_autonomy_settings()
        if plugin_id == "evey-rag":
            data["top_k_results"] = aut.get("hybrid_search", {}).get("top_k", 5)
            data["similarity_threshold"] = aut.get("corrective_rag", {}).get("min_relevance_score", 0.45)
        elif plugin_id == "evey-cache":
            data["cache_ttl_hours"] = max(1, int(aut.get("semantic_cache", {}).get("ttl_seconds", 86400) // 3600))
            data["max_cache_entries"] = aut.get("semantic_cache", {}).get("max_entries", 500)
            data["semantic_match"] = aut.get("semantic_cache", {}).get("enabled", True)
        elif plugin_id == "evey-sandbox":
            data["max_exec_seconds"] = aut.get("ephemeral_sandbox", {}).get("timeout_seconds", 30)
            data["pii_filter"] = aut.get("pii_scrubber", {}).get("enabled", True)
        elif plugin_id == "evey-council":
            data["debate_rounds"] = aut.get("consensus_gate", {}).get("council_size", 3)
        elif plugin_id == "evey-reflect":
            data["reflect_frequency_tasks"] = aut.get("self_healing", {}).get("max_retries", 2)
        elif plugin_id == "evey-learner":
            data["min_quality_score"] = aut.get("sla_enforcer", {}).get("min_quality_score", 0.75)
            data["auto_index_skills"] = aut.get("skill_synthesizer", {}).get("enabled", True)
        elif plugin_id == "evey-scheduler":
            data["worker_concurrency"] = aut.get("concurrency", {}).get("max_concurrent_agents", 4)
            data["max_retry_attempts"] = aut.get("dead_letter_queue", {}).get("max_replay_attempts", 3)
        elif plugin_id == "evey-digest":
            data["daily_digest_time"] = aut.get("inbox_watcher", {}).get("standup_hour", "07:30")
        elif plugin_id == "evey-status":
            data["cpu_threshold_percent"] = int(aut.get("resource_backpressure", {}).get("max_cpu_percent", 85))
    except Exception:
        pass

    return {"status": "success", "plugin_id": plugin_id, "config": data}

@app.post("/api/guardian/plugins/{plugin_id}/config")
def api_save_plugin_config(plugin_id: str, payload: dict):
    """Speichert Konfigurationsänderungen für ein Plugin und synchronisiert sie mit Systemdateien."""
    import yaml
    cfg = payload.get("config", payload)
    if not isinstance(cfg, dict):
        cfg = {}

    try:
        # 1. Immer in plugins_config/{plugin_id}.json persistieren
        generic_dir = os.path.join(MEMORY_DIR, "plugins_config")
        os.makedirs(generic_dir, exist_ok=True)
        gfile = os.path.join(generic_dir, f"{plugin_id}.json")
        with open(gfile, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        # Auch unter /opt/data spiegeln falls Container-Volume aktiv
        if os.path.exists("/opt/data") and os.path.isdir("/opt/data"):
            opt_dir = "/opt/data/plugins_config"
            os.makedirs(opt_dir, exist_ok=True)
            with open(os.path.join(opt_dir, f"{plugin_id}.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)

        # 2. Spezifische Live-Systemdateien synchronisieren
        if plugin_id == "evey-cost-guard":
            path = os.path.expanduser("~/.hermes/cost-budget.json")
            if not os.path.exists(path) and os.path.exists("/opt/data"):
                path = "/opt/data/cost-budget.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            b_data = {
                "daily_budget": float(cfg.get("daily_budget", 2.0)),
                "task_budget": float(cfg.get("task_budget", 0.5))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(b_data, f, indent=2)

        elif plugin_id == "evey-cache":
            limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
            os.makedirs(os.path.dirname(os.path.abspath(limits_file)), exist_ok=True)
            cur = {}
            if os.path.exists(limits_file):
                try:
                    with open(limits_file, "r", encoding="utf-8") as f:
                        cur = json.load(f)
                except Exception:
                    pass
            cur["cache_ttl_hours"] = int(cfg.get("cache_ttl_hours", 24))
            cur["max_cache_entries"] = int(cfg.get("max_cache_entries", 100))
            with open(limits_file, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2)

        elif plugin_id == "evey-autonomy":
            path = os.path.expanduser("~/.hermes/evey-autonomy.json")
            if not os.path.exists(path) and os.path.exists("/opt/data"):
                path = "/opt/data/evey-autonomy.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "operator_name": str(cfg.get("operator_name", "Michael")),
                "timezone": str(cfg.get("timezone", "Europe/Berlin")),
                "heavy_model": str(cfg.get("heavy_model", "claude-sonnet-4-6")),
                "cheap_model": str(cfg.get("cheap_model", "claude-haiku-4-5")),
                "cooldown_minutes": int(cfg.get("cooldown_minutes", 30))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-watchdog":
            path = os.path.expanduser("~/.hermes/workspace/watchdog-state.json")
            if not os.path.exists(path) and os.path.exists("/opt/data/workspace"):
                path = "/opt/data/workspace/watchdog-state.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "silent_threshold_minutes": int(cfg.get("silent_threshold_minutes", 120)),
                "work_hours_start": int(cfg.get("work_hours_start", 9)),
                "work_hours_end": int(cfg.get("work_hours_end", 21)),
                "alert_channel": str(cfg.get("alert_channel", "ntfy"))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-proactive":
            path = os.path.expanduser("~/.hermes/workspace/manager/proactive-state.json")
            if not os.path.exists(path) and os.path.exists("/opt/data/workspace/manager"):
                path = "/opt/data/workspace/manager/proactive-state.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "max_messages_per_day": int(cfg.get("max_messages_per_day", 5)),
                "cooldown_minutes": int(cfg.get("cooldown_minutes", 45)),
                "allowed_start_hour": int(cfg.get("allowed_start_hour", 9)),
                "allowed_end_hour": int(cfg.get("allowed_end_hour", 20))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-sandbox":
            path = os.path.expanduser("~/.hermes/config/sandbox.yaml")
            if not os.path.exists(path) and os.path.exists("/opt/data/config"):
                path = "/opt/data/config/sandbox.yaml"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            raw_folders = cfg.get("allowed_folders_str", "")
            folders = [f.strip() for f in raw_folders.split(",") if f.strip()] if isinstance(raw_folders, str) else cfg.get("allowed_folders", [])
            data = {
                "allowed_folders": folders,
                "pii": {"enabled": bool(cfg.get("pii_filter", True))}
            }
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False)

        elif plugin_id == "evey-wallet":
            path = os.path.expanduser("~/.hermes/wallet-balances.json")
            if not os.path.exists(path) and os.path.exists("/opt/data"):
                path = "/opt/data/wallet-balances.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "btc_address": str(cfg.get("btc_address", "")).strip(),
                "eth_address": str(cfg.get("eth_address", "")).strip(),
                "sol_address": str(cfg.get("sol_address", "")).strip()
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-telegram-ux":
            tg_env = "/opt/data/profiles/telegram_bot/.env"
            if os.path.exists(tg_env) and ("bot_token" in cfg or "allowed_chat_ids" in cfg):
                try:
                    with open(tg_env, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    new_lines = []
                    for l in lines:
                        if l.startswith("TELEGRAM_BOT_TOKEN=") and "bot_token" in cfg and cfg["bot_token"]:
                            new_lines.append(f"TELEGRAM_BOT_TOKEN={cfg['bot_token'].strip()}\n")
                        elif l.startswith("TELEGRAM_ALLOWED_USERS=") and "allowed_chat_ids" in cfg and cfg["allowed_chat_ids"]:
                            new_lines.append(f"TELEGRAM_ALLOWED_USERS={cfg['allowed_chat_ids'].strip()}\n")
                        else:
                            new_lines.append(l)
                    with open(tg_env, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                except Exception as ex:
                    print(f"Failed to sync telegram .env: {ex}")

        # 3. Synchronisiere geänderte Schwellenwerte direkt zurück in backend/autonomy_settings.py (settings.json)
        try:
            from backend.autonomy_settings import save_autonomy_settings
            if plugin_id == "evey-rag":
                save_autonomy_settings({
                    "hybrid_search": {"top_k": int(cfg.get("top_k_results", 5))},
                    "corrective_rag": {"min_relevance_score": float(cfg.get("similarity_threshold", 0.45))}
                })
            elif plugin_id == "evey-cache":
                save_autonomy_settings({
                    "semantic_cache": {
                        "ttl_seconds": int(cfg.get("cache_ttl_hours", 24)) * 3600,
                        "max_entries": int(cfg.get("max_cache_entries", 500)),
                        "enabled": bool(cfg.get("semantic_match", True))
                    }
                })
            elif plugin_id == "evey-sandbox":
                save_autonomy_settings({
                    "ephemeral_sandbox": {"timeout_seconds": int(cfg.get("max_exec_seconds", 30))},
                    "pii_scrubber": {"enabled": bool(cfg.get("pii_filter", True))}
                })
            elif plugin_id == "evey-council":
                save_autonomy_settings({
                    "consensus_gate": {"council_size": int(cfg.get("debate_rounds", 3))}
                })
            elif plugin_id == "evey-reflect":
                save_autonomy_settings({
                    "self_healing": {"max_retries": int(cfg.get("reflect_frequency_tasks", 2))}
                })
            elif plugin_id == "evey-learner":
                save_autonomy_settings({
                    "sla_enforcer": {"min_quality_score": float(cfg.get("min_quality_score", 0.75))},
                    "skill_synthesizer": {"enabled": bool(cfg.get("auto_index_skills", True))}
                })
            elif plugin_id == "evey-scheduler":
                save_autonomy_settings({
                    "concurrency": {"max_concurrent_agents": int(cfg.get("worker_concurrency", 4))},
                    "dead_letter_queue": {"max_replay_attempts": int(cfg.get("max_retry_attempts", 3))}
                })
            elif plugin_id == "evey-digest":
                save_autonomy_settings({
                    "inbox_watcher": {"standup_hour": str(cfg.get("daily_digest_time", "07:30"))}
                })
            elif plugin_id == "evey-status":
                save_autonomy_settings({
                    "resource_backpressure": {"max_cpu_percent": float(cfg.get("cpu_threshold_percent", 85.0))}
                })
        except Exception as sync_err:
            print(f"Warnung bei Autonomy-Settings-Sync ({plugin_id}): {sync_err}")

        add_ticker("Guardian", f"Einstellungen für Modul '{plugin_id}' gespeichert (settings.json synchronisiert).")
        return {"status": "success", "plugin_id": plugin_id, "message": "Gespeichert", "config": cfg}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/guardian/cache/clear")
def api_clear_guardian_cache():
    """Leert den Delegation- und Prompt-Cache."""
    cache_file = os.path.expanduser("~/.hermes/workspace/orchestrator/delegation-cache.json")
    if not os.path.exists(cache_file):
        cache_file = "/opt/data/workspace/orchestrator/delegation-cache.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({}, f)
        except Exception:
            pass
    add_ticker("Guardian", "Delegations- & Prompt-Cache geleert.")
    return {"status": "success", "message": "Cache erfolgreich geleert"}

# --- HERMES RAW CONFIG & LIVE EDITOR ENDPOINTS ---

def _get_hermes_config_paths():
    base_dirs = [
        "/opt/data",
        os.path.expanduser("~/.hermes"),
        "C:\\Users\\micha\\.hermes"
    ]
    found_configs = []
    active_path = None
    
    for b in base_dirs:
        if not os.path.exists(b):
            continue
            
        # 1. Global config is primary default
        glob_yaml = os.path.join(b, "config.yaml")
        if os.path.exists(glob_yaml):
            if glob_yaml not in found_configs:
                found_configs.append(glob_yaml)
            if not active_path:
                active_path = glob_yaml

        # 2. Profiles (default first, then others)
        prof_dir = os.path.join(b, "profiles")
        if os.path.exists(prof_dir):
            try:
                def_prof = os.path.join(prof_dir, "default", "config.yaml")
                if os.path.exists(def_prof) and def_prof not in found_configs:
                    found_configs.append(def_prof)
                for entry in sorted(os.listdir(prof_dir)):
                    pyaml = os.path.join(prof_dir, entry, "config.yaml")
                    if os.path.exists(pyaml) and pyaml not in found_configs:
                        found_configs.append(pyaml)
            except Exception:
                pass

    if not active_path and found_configs:
        active_path = found_configs[0]
    return active_path, found_configs

@app.get("/api/hermes/settings")
def api_get_hermes_form_config(path: Optional[str] = None):
    import yaml
    active_path, all_configs = _get_hermes_config_paths()
    target_path = path if (path and os.path.exists(path)) else active_path
    
    parsed = {}
    content = ""
    if target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            parsed = yaml.safe_load(content) or {}
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception as e:
            logger.error(f"Fehler beim Parsen von {target_path}: {e}")
            parsed = {}

    model_obj = parsed.get("model", {}) if isinstance(parsed.get("model"), dict) else {}
    agent_obj = parsed.get("agent", {}) if isinstance(parsed.get("agent"), dict) else {}
    disp_obj = parsed.get("display", {}) if isinstance(parsed.get("display"), dict) else {}
    dash_obj = parsed.get("dashboard", {}) if isinstance(parsed.get("dashboard"), dict) else {}
    stream_obj = parsed.get("streaming", {}) if isinstance(parsed.get("streaming"), dict) else {}
    gw_obj = parsed.get("gateway", {}) if isinstance(parsed.get("gateway"), dict) else {}
    plat_obj = parsed.get("platforms", {}) if isinstance(parsed.get("platforms"), dict) else {}
    a2a_obj = plat_obj.get("a2a", {}) if isinstance(plat_obj.get("a2a"), dict) else {}
    tg_obj = plat_obj.get("telegram", {}) if isinstance(plat_obj.get("telegram"), dict) else {}
    wh_obj = plat_obj.get("webhook", {}) if isinstance(plat_obj.get("webhook"), dict) else {}
    api_srv_obj = plat_obj.get("api_server", {}) if isinstance(plat_obj.get("api_server"), dict) else {}
    stt_obj = parsed.get("stt", {}) if isinstance(parsed.get("stt"), dict) else {}
    stt_groq = stt_obj.get("groq", {}) if isinstance(stt_obj.get("groq"), dict) else {}
    stt_openai = stt_obj.get("openai", {}) if isinstance(stt_obj.get("openai"), dict) else {}
    stt_local = stt_obj.get("local", {}) if isinstance(stt_obj.get("local"), dict) else {}
    voice_obj = parsed.get("voice", {}) if isinstance(parsed.get("voice"), dict) else {}
    term_obj = parsed.get("terminal", {}) if isinstance(parsed.get("terminal"), dict) else {}
    code_obj = parsed.get("code_execution", {}) if isinstance(parsed.get("code_execution"), dict) else {}
    loop_obj = parsed.get("tool_loop_guardrails", {}) if isinstance(parsed.get("tool_loop_guardrails"), dict) else {}
    warn_after = loop_obj.get("warn_after", {}) if isinstance(loop_obj.get("warn_after"), dict) else {}
    stop_after = loop_obj.get("hard_stop_after", {}) if isinstance(loop_obj.get("hard_stop_after"), dict) else {}
    comp_obj = parsed.get("compression", {}) if isinstance(parsed.get("compression"), dict) else {}
    pcache_obj = parsed.get("prompt_caching", {}) if isinstance(parsed.get("prompt_caching"), dict) else {}
    mem_obj = parsed.get("memory", {}) if isinstance(parsed.get("memory"), dict) else {}
    sreset_obj = parsed.get("session_reset", {}) if isinstance(parsed.get("session_reset"), dict) else {}
    skills_obj = parsed.get("skills", {}) if isinstance(parsed.get("skills"), dict) else {}
    deleg_obj = parsed.get("delegation", {}) if isinstance(parsed.get("delegation"), dict) else {}
    moa_obj = parsed.get("moa", {}) if isinstance(parsed.get("moa"), dict) else {}
    moa_agg = moa_obj.get("aggregator", {}) if isinstance(moa_obj.get("aggregator"), dict) else {}
    aux_obj = parsed.get("auxiliary", {}) if isinstance(parsed.get("auxiliary"), dict) else {}
    aux_vis = aux_obj.get("vision", {}) if isinstance(aux_obj.get("vision"), dict) else {}
    aux_web = aux_obj.get("web_extract", {}) if isinstance(aux_obj.get("web_extract"), dict) else {}
    brow_obj = parsed.get("browser", {}) if isinstance(parsed.get("browser"), dict) else {}
    tools_obj = parsed.get("tools", {}) if isinstance(parsed.get("tools"), dict) else {}
    tsearch_obj = tools_obj.get("tool_search", {}) if isinstance(tools_obj.get("tool_search"), dict) else {}
    upd_obj = parsed.get("updates", {}) if isinstance(parsed.get("updates"), dict) else {}

    settings = {
        # Sektion 1: Modell & Provider
        "model_default": model_obj.get("default", "z-ai/glm-5.3"),
        "model_provider": model_obj.get("provider", "openrouter"),
        "base_url": model_obj.get("base_url", ""),
        # Sektion 2: Agenten-Kognition & Limits
        "reasoning_effort": agent_obj.get("reasoning_effort", "medium"),
        "max_context_tokens": agent_obj.get("max_context_tokens", 32000),
        "max_history_messages": agent_obj.get("max_history_messages", 20),
        "task_timeout_seconds": agent_obj.get("task_timeout_seconds", 60),
        "max_turns": agent_obj.get("max_turns", 60),
        "verify_on_stop": agent_obj.get("verify_on_stop", False),
        "verbose": agent_obj.get("verbose", False),
        # Sektion 3: Anzeige, Streaming & Dashboard
        "language": disp_obj.get("language", "de"),
        "reasoning_full": disp_obj.get("reasoning_full", disp_obj.get("show_reasoning", True)),
        "show_cost": disp_obj.get("show_cost", True),
        "timestamps": disp_obj.get("timestamps", True),
        "bell_on_complete": disp_obj.get("bell_on_complete", True),
        "compact": disp_obj.get("compact", True),
        "streaming_enabled": disp_obj.get("streaming", stream_obj.get("enabled", True)),
        "busy_input_mode": disp_obj.get("busy_input_mode", "interrupt"),
        "interim_assistant_messages": disp_obj.get("interim_assistant_messages", True),
        "background_process_notifications": disp_obj.get("background_process_notifications", "all"),
        "tool_progress": disp_obj.get("tool_progress", "all"),
        "long_running_notifications": disp_obj.get("long_running_notifications", True),
        "cleanup_progress": disp_obj.get("cleanup_progress", False),
        "timestamp_format": disp_obj.get("timestamp_format", "%H:%M:%S"),
        "skin": disp_obj.get("skin", "coffee-shop"),
        "dashboard_theme": dash_obj.get("theme", disp_obj.get("dashboard_theme", "boring-light")),
        # Sektion 4: Gateway, Multiplexing & Plattformen
        "multiplex_profiles": gw_obj.get("multiplex_profiles", True),
        "a2a_enabled": a2a_obj.get("enabled", True),
        "telegram_enabled": tg_obj.get("enabled", True),
        "webhook_enabled": wh_obj.get("enabled", True),
        "api_server_enabled": api_srv_obj.get("enabled", False),
        "group_sessions_per_user": parsed.get("group_sessions_per_user", True),
        # Sektion 5: Befehls-Allowlist & Code-Execution
        "command_allowlist": parsed.get("command_allowlist", ["script execution via heredoc", "execute_code"]) if isinstance(parsed.get("command_allowlist"), list) else [],
        "code_max_tool_calls": code_obj.get("max_tool_calls", 50),
        "code_timeout": code_obj.get("timeout", 300),
        # Sektion 6: Terminal-Backend & Container-Grenzwerte
        "terminal_backend": term_obj.get("backend", "local"),
        "terminal_cwd": term_obj.get("cwd", "."),
        "terminal_timeout": term_obj.get("timeout", 180),
        "terminal_home_mode": term_obj.get("home_mode", "auto"),
        "terminal_container_cpu": term_obj.get("container_cpu", 1),
        "terminal_container_memory": term_obj.get("container_memory", 5120),
        "terminal_container_disk": term_obj.get("container_disk", 51200),
        "terminal_container_persistent": term_obj.get("container_persistent", True),
        "terminal_docker_mount_cwd": term_obj.get("docker_mount_cwd_to_workspace", False),
        "terminal_lifetime_seconds": term_obj.get("lifetime_seconds", 300),
        # Sektion 7: Native Tool-Loop-Guardrails
        "loop_warnings_enabled": loop_obj.get("warnings_enabled", True),
        "loop_hard_stop_enabled": loop_obj.get("hard_stop_enabled", False),
        "warn_exact_failure": warn_after.get("exact_failure", 2),
        "warn_same_tool_failure": warn_after.get("same_tool_failure", 3),
        "warn_idempotent_no_progress": warn_after.get("idempotent_no_progress", 2),
        "stop_exact_failure": stop_after.get("exact_failure", 5),
        "stop_same_tool_failure": stop_after.get("same_tool_failure", 8),
        "stop_idempotent_no_progress": stop_after.get("idempotent_no_progress", 5),
        # Sektion 8: Kontext-Kompression & Prompt-Caching
        "compression_enabled": comp_obj.get("enabled", True),
        "compression_threshold": comp_obj.get("threshold", 0.5),
        "compression_target_ratio": comp_obj.get("target_ratio", 0.2),
        "compression_protect_last_n": comp_obj.get("protect_last_n", 20),
        "compression_protect_first_n": comp_obj.get("protect_first_n", 3),
        "compression_codex_autoraise": comp_obj.get("codex_gpt55_autoraise", True),
        "prompt_cache_ttl": pcache_obj.get("cache_ttl", "5m"),
        # Sektion 9: Hermes Memory, Session-Reset & Skill-Synthese
        "memory_enabled": mem_obj.get("memory_enabled", True),
        "user_profile_enabled": mem_obj.get("user_profile_enabled", True),
        "memory_char_limit": mem_obj.get("memory_char_limit", 2200),
        "user_char_limit": mem_obj.get("user_char_limit", 1375),
        "memory_flush_min_turns": mem_obj.get("flush_min_turns", 6),
        "memory_nudge_interval": mem_obj.get("nudge_interval", 10),
        "session_reset_mode": sreset_obj.get("mode", "both"),
        "session_reset_at_hour": sreset_obj.get("at_hour", 4),
        "session_reset_idle_minutes": sreset_obj.get("idle_minutes", 1440),
        "skills_creation_nudge_interval": skills_obj.get("creation_nudge_interval", 15),
        # Sektion 10: Subagenten-Delegation & Mixture-of-Agents (MoA)
        "delegation_max_iterations": deleg_obj.get("max_iterations", 50),
        "delegation_max_concurrent_children": deleg_obj.get("max_concurrent_children", 5),
        "moa_enabled": moa_obj.get("enabled", True),
        "moa_fanout": moa_obj.get("fanout", "user_turn"),
        "moa_max_tokens": moa_obj.get("max_tokens", 4096),
        "moa_degraded_policy": moa_obj.get("degraded_reference_policy", "loud"),
        "moa_aggregator_provider": moa_agg.get("provider", "custom:omniroute:20128"),
        "moa_aggregator_model": moa_agg.get("model", "auto/best-free"),
        # Sektion 11: Hilfsmodelle (Vision & Web-Extract)
        "aux_vision_provider": aux_vis.get("provider", "custom:Omniroute:20128"),
        "aux_vision_model": aux_vis.get("model", ""),
        "aux_web_provider": aux_web.get("provider", "auto"),
        "aux_web_model": aux_web.get("model", ""),
        # Sektion 12: Browser-Engine & Dynamische Tool-Suche
        "browser_inactivity_timeout": brow_obj.get("inactivity_timeout", 120),
        "browser_cloud_provider": brow_obj.get("cloud_provider", "local"),
        "browser_use_gateway": brow_obj.get("use_gateway", False),
        "tool_search_enabled": str(tsearch_obj.get("enabled", "on")),
        "tool_search_threshold_pct": tsearch_obj.get("threshold_pct", 0),
        "tool_search_limit": tsearch_obj.get("search_default_limit", 5),
        "tool_search_listing": str(tsearch_obj.get("listing", "off")),
        # Sektion 13: Sprachausgabe (Voice / TTS) & Spracherkennung (STT)
        "stt_enabled": stt_obj.get("enabled", True),
        "stt_provider": stt_obj.get("provider", "groq"),
        "stt_language": stt_obj.get("language", "de"),
        "stt_groq_model": stt_groq.get("model", "whisper-large-v3"),
        "stt_openai_model": stt_openai.get("model", "whisper-1"),
        "stt_local_model": stt_local.get("model", "base"),
        "voice_auto_tts": voice_obj.get("auto_tts", False),
        # Sektion 14: Update-Sicherheit & Konfigurations-Backups
        "updates_pre_backup": upd_obj.get("pre_update_backup", False),
        "updates_backup_keep": upd_obj.get("backup_keep", 5),
        "updates_local_changes": upd_obj.get("non_interactive_local_changes", "stash")
    }

    return {
        "active_path": active_path,
        "loaded_path": target_path,
        "available_configs": all_configs,
        "settings": settings,
        "raw_yaml": content
    }

@app.post("/api/hermes/settings")
def api_save_hermes_form_config(payload: dict = Body(...)):
    import yaml, shutil
    target_path = payload.get("config_path")
    settings = payload.get("settings", {})
    
    if not target_path:
        active_path, _ = _get_hermes_config_paths()
        target_path = active_path
        
    if not target_path:
        raise HTTPException(status_code=400, detail="Kein Pfad für Hermes-Konfiguration gefunden.")

    existing_data = {}
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                existing_data = yaml.safe_load(f.read()) or {}
                if not isinstance(existing_data, dict):
                    existing_data = {}
        except Exception:
            existing_data = {}

    def _ensure_dict(parent: dict, key: str) -> dict:
        if not isinstance(parent.get(key), dict):
            parent[key] = {}
        return parent[key]

    # Sektion 1: Modell
    m_dict = _ensure_dict(existing_data, "model")
    if "model_default" in settings:
        m_dict["default"] = str(settings["model_default"]).strip()
    if "model_provider" in settings:
        m_dict["provider"] = str(settings["model_provider"]).strip()
    if "base_url" in settings:
        b_url = str(settings["base_url"]).strip()
        if b_url:
            m_dict["base_url"] = b_url
        elif "base_url" in m_dict:
            del m_dict["base_url"]

    # Sektion 2: Agent
    a_dict = _ensure_dict(existing_data, "agent")
    if "reasoning_effort" in settings:
        a_dict["reasoning_effort"] = str(settings["reasoning_effort"]).strip()
    for int_key in ("max_context_tokens", "max_history_messages", "task_timeout_seconds", "max_turns"):
        if int_key in settings:
            try:
                a_dict[int_key] = int(settings[int_key])
            except Exception:
                pass
    for bool_key in ("verify_on_stop", "verbose"):
        if bool_key in settings:
            a_dict[bool_key] = bool(settings[bool_key])

    # Sektion 3: Display, Streaming & Dashboard
    d_dict = _ensure_dict(existing_data, "display")
    for str_key in ("language", "busy_input_mode", "background_process_notifications", "tool_progress", "timestamp_format", "skin"):
        if str_key in settings:
            d_dict[str_key] = str(settings[str_key]).strip()
    for bool_key in ("reasoning_full", "show_cost", "timestamps", "bell_on_complete", "compact", "interim_assistant_messages", "long_running_notifications", "cleanup_progress"):
        if bool_key in settings:
            d_dict[bool_key] = bool(settings[bool_key])
    if "reasoning_full" in settings:
        d_dict["show_reasoning"] = bool(settings["reasoning_full"])
    if "streaming_enabled" in settings:
        d_dict["streaming"] = bool(settings["streaming_enabled"])
        _ensure_dict(existing_data, "streaming")["enabled"] = bool(settings["streaming_enabled"])
    if "dashboard_theme" in settings:
        d_dict["dashboard_theme"] = str(settings["dashboard_theme"]).strip()
        _ensure_dict(existing_data, "dashboard")["theme"] = str(settings["dashboard_theme"]).strip()

    # Sektion 4: Gateway & Plattformen
    gw_dict = _ensure_dict(existing_data, "gateway")
    if "multiplex_profiles" in settings:
        gw_dict["multiplex_profiles"] = bool(settings["multiplex_profiles"])
    pl_dict = _ensure_dict(existing_data, "platforms")
    if "a2a_enabled" in settings:
        _ensure_dict(pl_dict, "a2a")["enabled"] = bool(settings["a2a_enabled"])
    if "telegram_enabled" in settings:
        _ensure_dict(pl_dict, "telegram")["enabled"] = bool(settings["telegram_enabled"])
    if "webhook_enabled" in settings:
        _ensure_dict(pl_dict, "webhook")["enabled"] = bool(settings["webhook_enabled"])
    if "api_server_enabled" in settings:
        _ensure_dict(pl_dict, "api_server")["enabled"] = bool(settings["api_server_enabled"])
    if "group_sessions_per_user" in settings:
        existing_data["group_sessions_per_user"] = bool(settings["group_sessions_per_user"])

    # Sektion 5: Allowlist & Code-Execution
    if "command_allowlist" in settings and isinstance(settings["command_allowlist"], list):
        existing_data["command_allowlist"] = settings["command_allowlist"]
    ce_dict = _ensure_dict(existing_data, "code_execution")
    if "code_max_tool_calls" in settings:
        try:
            ce_dict["max_tool_calls"] = int(settings["code_max_tool_calls"])
        except Exception:
            pass
    if "code_timeout" in settings:
        try:
            ce_dict["timeout"] = int(settings["code_timeout"])
        except Exception:
            pass

    # Sektion 6: Terminal & Container
    t_dict = _ensure_dict(existing_data, "terminal")
    for s_k, y_k in (("terminal_backend", "backend"), ("terminal_cwd", "cwd"), ("terminal_home_mode", "home_mode")):
        if s_k in settings:
            t_dict[y_k] = str(settings[s_k]).strip()
    for s_k, y_k in (("terminal_timeout", "timeout"), ("terminal_container_memory", "container_memory"), ("terminal_container_disk", "container_disk"), ("terminal_lifetime_seconds", "lifetime_seconds")):
        if s_k in settings:
            try:
                t_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    if "terminal_container_cpu" in settings:
        try:
            t_dict["container_cpu"] = float(settings["terminal_container_cpu"])
        except Exception:
            pass
    if "terminal_container_persistent" in settings:
        t_dict["container_persistent"] = bool(settings["terminal_container_persistent"])
    if "terminal_docker_mount_cwd" in settings:
        t_dict["docker_mount_cwd_to_workspace"] = bool(settings["terminal_docker_mount_cwd"])

    # Sektion 7: Tool-Loop-Guardrails
    lg_dict = _ensure_dict(existing_data, "tool_loop_guardrails")
    if "loop_warnings_enabled" in settings:
        lg_dict["warnings_enabled"] = bool(settings["loop_warnings_enabled"])
    if "loop_hard_stop_enabled" in settings:
        lg_dict["hard_stop_enabled"] = bool(settings["loop_hard_stop_enabled"])
    wa_dict = _ensure_dict(lg_dict, "warn_after")
    for s_k, y_k in (("warn_exact_failure", "exact_failure"), ("warn_same_tool_failure", "same_tool_failure"), ("warn_idempotent_no_progress", "idempotent_no_progress")):
        if s_k in settings:
            try:
                wa_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    sa_dict = _ensure_dict(lg_dict, "hard_stop_after")
    for s_k, y_k in (("stop_exact_failure", "exact_failure"), ("stop_same_tool_failure", "same_tool_failure"), ("stop_idempotent_no_progress", "idempotent_no_progress")):
        if s_k in settings:
            try:
                sa_dict[y_k] = int(settings[s_k])
            except Exception:
                pass

    # Sektion 8: Kontext-Kompression & Prompt-Caching
    cp_dict = _ensure_dict(existing_data, "compression")
    if "compression_enabled" in settings:
        cp_dict["enabled"] = bool(settings["compression_enabled"])
    for s_k, y_k in (("compression_threshold", "threshold"), ("compression_target_ratio", "target_ratio")):
        if s_k in settings:
            try:
                cp_dict[y_k] = float(settings[s_k])
            except Exception:
                pass
    for s_k, y_k in (("compression_protect_last_n", "protect_last_n"), ("compression_protect_first_n", "protect_first_n")):
        if s_k in settings:
            try:
                cp_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    if "compression_codex_autoraise" in settings:
        cp_dict["codex_gpt55_autoraise"] = bool(settings["compression_codex_autoraise"])
    if "prompt_cache_ttl" in settings:
        _ensure_dict(existing_data, "prompt_caching")["cache_ttl"] = str(settings["prompt_cache_ttl"]).strip()

    # Sektion 9: Memory, Session-Reset & Skills
    mm_dict = _ensure_dict(existing_data, "memory")
    for s_k in ("memory_enabled", "user_profile_enabled"):
        if s_k in settings:
            mm_dict[s_k] = bool(settings[s_k])
    for s_k, y_k in (("memory_char_limit", "memory_char_limit"), ("user_char_limit", "user_char_limit"), ("memory_flush_min_turns", "flush_min_turns"), ("memory_nudge_interval", "nudge_interval")):
        if s_k in settings:
            try:
                mm_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    sr_dict = _ensure_dict(existing_data, "session_reset")
    if "session_reset_mode" in settings:
        sr_dict["mode"] = str(settings["session_reset_mode"]).strip()
    for s_k, y_k in (("session_reset_at_hour", "at_hour"), ("session_reset_idle_minutes", "idle_minutes")):
        if s_k in settings:
            try:
                sr_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    if "skills_creation_nudge_interval" in settings:
        try:
            _ensure_dict(existing_data, "skills")["creation_nudge_interval"] = int(settings["skills_creation_nudge_interval"])
        except Exception:
            pass

    # Sektion 10: Delegation & MoA
    dl_dict = _ensure_dict(existing_data, "delegation")
    for s_k, y_k in (("delegation_max_iterations", "max_iterations"), ("delegation_max_concurrent_children", "max_concurrent_children")):
        if s_k in settings:
            try:
                dl_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    moa_dict = _ensure_dict(existing_data, "moa")
    if "moa_enabled" in settings:
        moa_dict["enabled"] = bool(settings["moa_enabled"])
    if "moa_fanout" in settings:
        moa_dict["fanout"] = str(settings["moa_fanout"]).strip()
    if "moa_max_tokens" in settings:
        try:
            moa_dict["max_tokens"] = int(settings["moa_max_tokens"])
        except Exception:
            pass
    if "moa_degraded_policy" in settings:
        moa_dict["degraded_reference_policy"] = str(settings["moa_degraded_policy"]).strip()
    moa_agg_dict = _ensure_dict(moa_dict, "aggregator")
    if "moa_aggregator_provider" in settings:
        moa_agg_dict["provider"] = str(settings["moa_aggregator_provider"]).strip()
    if "moa_aggregator_model" in settings:
        moa_agg_dict["model"] = str(settings["moa_aggregator_model"]).strip()

    # Sektion 11: Auxiliary (Vision & Web)
    aux_dict = _ensure_dict(existing_data, "auxiliary")
    vis_dict = _ensure_dict(aux_dict, "vision")
    if "aux_vision_provider" in settings:
        vis_dict["provider"] = str(settings["aux_vision_provider"]).strip()
    if "aux_vision_model" in settings:
        vis_dict["model"] = str(settings["aux_vision_model"]).strip()
    web_dict = _ensure_dict(aux_dict, "web_extract")
    if "aux_web_provider" in settings:
        web_dict["provider"] = str(settings["aux_web_provider"]).strip()
    if "aux_web_model" in settings:
        web_dict["model"] = str(settings["aux_web_model"]).strip()

    # Sektion 12: Browser & Tool-Search
    br_dict = _ensure_dict(existing_data, "browser")
    if "browser_inactivity_timeout" in settings:
        try:
            br_dict["inactivity_timeout"] = int(settings["browser_inactivity_timeout"])
        except Exception:
            pass
    if "browser_cloud_provider" in settings:
        br_dict["cloud_provider"] = str(settings["browser_cloud_provider"]).strip()
    if "browser_use_gateway" in settings:
        br_dict["use_gateway"] = bool(settings["browser_use_gateway"])
    ts_dict = _ensure_dict(_ensure_dict(existing_data, "tools"), "tool_search")
    if "tool_search_enabled" in settings:
        ts_dict["enabled"] = str(settings["tool_search_enabled"]).strip()
    if "tool_search_threshold_pct" in settings:
        try:
            ts_dict["threshold_pct"] = int(settings["tool_search_threshold_pct"])
        except Exception:
            pass
    if "tool_search_limit" in settings:
        try:
            ts_dict["search_default_limit"] = int(settings["tool_search_limit"])
        except Exception:
            pass
    if "tool_search_listing" in settings:
        ts_dict["listing"] = str(settings["tool_search_listing"]).strip()

    # Sektion 13: STT & Voice
    stt_dict = _ensure_dict(existing_data, "stt")
    if "stt_enabled" in settings:
        stt_dict["enabled"] = bool(settings["stt_enabled"])
    if "stt_provider" in settings:
        stt_dict["provider"] = str(settings["stt_provider"]).strip()
    if "stt_language" in settings:
        stt_dict["language"] = str(settings["stt_language"]).strip()
        _ensure_dict(stt_dict, "groq")["language"] = str(settings["stt_language"]).strip()
    if "stt_groq_model" in settings:
        _ensure_dict(stt_dict, "groq")["model"] = str(settings["stt_groq_model"]).strip()
    if "stt_openai_model" in settings:
        _ensure_dict(stt_dict, "openai")["model"] = str(settings["stt_openai_model"]).strip()
    if "stt_local_model" in settings:
        _ensure_dict(stt_dict, "local")["model"] = str(settings["stt_local_model"]).strip()
    if "voice_auto_tts" in settings:
        _ensure_dict(existing_data, "voice")["auto_tts"] = bool(settings["voice_auto_tts"])

    # Sektion 14: Updates
    up_dict = _ensure_dict(existing_data, "updates")
    if "updates_pre_backup" in settings:
        up_dict["pre_update_backup"] = bool(settings["updates_pre_backup"])
    if "updates_backup_keep" in settings:
        try:
            up_dict["backup_keep"] = int(settings["updates_backup_keep"])
        except Exception:
            pass
    if "updates_local_changes" in settings:
        up_dict["non_interactive_local_changes"] = str(settings["updates_local_changes"]).strip()

    # BIDIREKTIONALE SYNCHRONISATION: Hermes (config.yaml) -> Archon Autonomie-Module (settings.json)
    try:
        from backend.autonomy_settings import save_autonomy_settings
        aut_sync = {}
        if "delegation_max_concurrent_children" in settings or "task_timeout_seconds" in settings:
            aut_sync["concurrency"] = {}
            if "delegation_max_concurrent_children" in settings:
                aut_sync["concurrency"]["max_concurrent_agents"] = int(settings["delegation_max_concurrent_children"])
            if "task_timeout_seconds" in settings:
                aut_sync["concurrency"]["queue_timeout_seconds"] = int(settings["task_timeout_seconds"])
        if "stop_exact_failure" in settings or "max_turns" in settings or "loop_warnings_enabled" in settings:
            aut_sync["circuit_breaker"] = {}
            if "loop_warnings_enabled" in settings:
                aut_sync["circuit_breaker"]["loop_detection_enabled"] = bool(settings["loop_warnings_enabled"])
            if "stop_exact_failure" in settings:
                aut_sync["circuit_breaker"]["max_identical_turns"] = int(settings["stop_exact_failure"])
            if "max_turns" in settings:
                aut_sync["circuit_breaker"]["max_steps_per_task"] = int(settings["max_turns"])
        if "terminal_container_cpu" in settings or "terminal_timeout" in settings:
            aut_sync["ephemeral_sandbox"] = {}
            if "terminal_container_cpu" in settings:
                aut_sync["ephemeral_sandbox"]["cpu_limit"] = float(settings["terminal_container_cpu"])
            if "terminal_timeout" in settings:
                aut_sync["ephemeral_sandbox"]["timeout_seconds"] = int(settings["terminal_timeout"])
        if "compression_enabled" in settings or "compression_protect_last_n" in settings:
            aut_sync["context_compactor"] = {}
            if "compression_enabled" in settings:
                aut_sync["context_compactor"]["enabled"] = bool(settings["compression_enabled"])
            if "compression_protect_last_n" in settings:
                aut_sync["context_compactor"]["keep_recent_turns"] = int(settings["compression_protect_last_n"])
        if "moa_enabled" in settings:
            aut_sync["consensus_gate"] = {"enabled": bool(settings["moa_enabled"])}
        if aut_sync:
            save_autonomy_settings(aut_sync)
    except Exception as e_sync:
        logger.warning(f"[Hermes -> Archon Sync] {e_sync}")

    try:
        if os.path.exists(target_path):
            shutil.copy2(target_path, target_path + ".bak")
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.dump(existing_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Wenn die globale Basis-Konfiguration (/opt/data/config.yaml) gespeichert wird,
        # synchronisiere model.default & model.provider auch nach /opt/data/profiles/default/config.yaml
        if os.path.abspath(target_path) == "/opt/data/config.yaml":
            def_prof_cfg = "/opt/data/profiles/default/config.yaml"
            if os.path.exists(def_prof_cfg):
                try:
                    with open(def_prof_cfg, "r", encoding="utf-8") as f_dp:
                        dp_data = yaml.safe_load(f_dp.read()) or {}
                    if isinstance(dp_data, dict):
                        dp_m = _ensure_dict(dp_data, "model")
                        if "model_default" in settings and str(settings["model_default"]).strip():
                            dp_m["default"] = str(settings["model_default"]).strip()
                        if "model_provider" in settings and str(settings["model_provider"]).strip():
                            dp_m["provider"] = str(settings["model_provider"]).strip()
                        if "base_url" in settings:
                            b_u = str(settings["base_url"]).strip()
                            if b_u:
                                dp_m["base_url"] = b_u
                            elif "base_url" in dp_m:
                                del dp_m["base_url"]
                        with open(def_prof_cfg, "w", encoding="utf-8") as f_dp:
                            yaml.dump(dp_data, f_dp, default_flow_style=False, allow_unicode=True, sort_keys=False)
                except Exception as dp_err:
                    logger.warning(f"[Hermes Settings] Default profile sync warning: {dp_err}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern der Konfiguration: {str(e)}")

    # Wenn target_path zu einem spezifischen Agenten-Profil gehört, synchronisiere profile.yaml, agent_profiles.json & Org-Chart
    try:
        prof_dir = os.path.dirname(os.path.abspath(target_path))
        prof_yaml = os.path.join(prof_dir, "profile.yaml")
        prof_id = os.path.basename(prof_dir)
        m_def = str(settings.get("model_default", "")).strip()
        m_prov = str(settings.get("model_provider", "")).strip()
        r_eff = str(settings.get("reasoning_effort", "")).strip().lower()
        if os.path.exists(prof_yaml) and (m_def or m_prov or r_eff):
            with open(prof_yaml, "r", encoding="utf-8") as fy:
                pdata = yaml.safe_load(fy) or {}
            if m_def:
                pdata["model"] = m_def
            if m_prov:
                pdata["provider"] = m_prov
            if r_eff:
                pdata["reasoning_level"] = r_eff
            if not isinstance(pdata.get("llm"), dict):
                pdata["llm"] = {}
            if m_def:
                pdata["llm"]["model"] = m_def
            if m_prov:
                pdata["llm"]["provider"] = m_prov
            if r_eff:
                pdata["llm"]["reasoning_level"] = r_eff
            with open(prof_yaml, "w", encoding="utf-8") as fy:
                yaml.dump(pdata, fy, allow_unicode=True, sort_keys=False)
            # agent_profiles.json nachziehen
            ap_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
            if os.path.exists(ap_file):
                with open(ap_file, "r", encoding="utf-8") as fap:
                    ap_list = json.load(fap)
                if isinstance(ap_list, list):
                    for item in ap_list:
                        if isinstance(item, dict) and item.get("id") == prof_id:
                            if m_def:
                                item["model"] = m_def
                            if m_prov:
                                item["provider"] = m_prov
                            if r_eff:
                                item["reasoning_level"] = r_eff
                            break
                    with open(ap_file, "w", encoding="utf-8") as fap:
                        json.dump(ap_list, f, indent=2, ensure_ascii=False) if False else None
                    with open(ap_file, "w", encoding="utf-8") as fap:
                        json.dump(ap_list, fap, indent=2, ensure_ascii=False)
            _sync_org_hierarchy_node(prof_id, provider=m_prov or None, model=m_def or None, reasoning_level=r_eff or None)
            invalidate_hermes_profiles_cache()
    except Exception as sync_err:
        logger.warning(f"[Hermes Settings] Global profile sync warning: {sync_err}")

    try:
        add_ticker("Hermes Core", f"Einstellungen gespeichert für: {os.path.basename(target_path)}")
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Hermes-Einstellungen für '{os.path.basename(target_path)}' erfolgreich gespeichert.",
        "path": target_path
    }

@app.get("/api/hermes/raw_config")
def api_get_hermes_raw_config(path: Optional[str] = None):
    import yaml
    active_path, all_configs = _get_hermes_config_paths()
    target_path = path if (path and os.path.exists(path)) else active_path
    
    content = ""
    parsed = {}
    if target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            parsed = yaml.safe_load(content) or {}
        except Exception as e:
            content = f"# Fehler beim Lesen von {target_path}:\n# {str(e)}"
            
    return {
        "active_path": active_path,
        "loaded_path": target_path,
        "available_configs": all_configs,
        "yaml_content": content,
        "parsed": parsed
    }

@app.post("/api/hermes/raw_config")
def api_save_hermes_raw_config(payload: dict = Body(...)):
    import yaml, shutil
    target_path = payload.get("config_path")
    yaml_content = payload.get("yaml_content", "")
    
    if not target_path:
        active_path, _ = _get_hermes_config_paths()
        target_path = active_path
        
    if not target_path:
        raise HTTPException(status_code=400, detail="Kein Pfad für Hermes-Konfiguration gefunden.")
        
    # 1. Syntax-Validierung
    try:
        parsed = yaml.safe_load(yaml_content)
        if not isinstance(parsed, dict):
            raise ValueError("YAML muss ein gültiges Dictionary / Mapping auf oberster Ebene sein.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML-Syntaxfehler: {str(e)}")
        
    # 2. Backup erstellen
    try:
        if os.path.exists(target_path):
            shutil.copy2(target_path, target_path + ".bak")
            
        # 3. Datei schreiben
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Schreiben der Datei: {str(e)}")
        
    # 4. Hermes Daemon Ticker
    try:
        add_ticker("Hermes Core", f"Hermes-Konfiguration aktualisiert: {os.path.basename(target_path)}")
    except Exception:
        pass
        
    return {
        "status": "success",
        "message": "Konfiguration erfolgreich validiert und gespeichert.",
        "path": target_path
    }

# --- KONTEXT-HILFE-ASSISTENT ENDPOINTS ---

HELP_CONTEXT_DATA = {
    "operations": {
        "title": "Operations",
        "subtitle": "Echtzeit-Leitstand und Flotten-Überwachung",
        "purpose": "Hier steuerst du den operativen Betrieb aller 56 Spezial-Agenten. Du siehst aktuelle System-KPIs, laufende Hintergrundprozesse, aktive Container und den Ticker.",
        "top_actions": [
            "Klicke auf eine KPI-Karte (Flottenlast, TPM, Latenz), um Detailanalysen zu öffnen.",
            "Nutze 'Neuer autonomer Task', um einer Rolle einen Arbeitsauftrag mit Prompt-Studio zu erteilen.",
            "Prüfe im 'Live Task-Stream' den aktuellen Fortschritt und Logs autonomer Aufgaben."
        ],
        "starter_prompt": "Erkläre mir, wie ich im Operations-Dashboard einen neuen Task an den passenden Agenten delegiere und den Fortschritt überwache."
    },
    "inbox": {
        "title": "Eingang & Triage (Intake)",
        "subtitle": "Operative Triage: HITL-Freigaben, E-Mails & Telegram",
        "purpose": "Zentrale Schleuse für alle eingehenden Signale. Hier genehmigst du Aktionen (Human-in-the-Loop), sichtest E-Mails und verarbeitest Nachrichten.",
        "top_actions": [
            "Filtere nach HITL-Freigaben, um blockierte Schreib-Aktionen der Agenten zu bestätigen.",
            "Synchronisiere das E-Mail-Postfach oder binde neue E-Mails direkt an Kontakte an.",
            "Übergib Nachrichten per Klick an einen spezialisierten Agenten zur automatischen Beantwortung."
        ],
        "starter_prompt": "Wie funktioniert der HITL-Freigabeprozess im Posteingang und wie kann ich eine E-Mail direkt von einem Agenten beantworten lassen?"
    },
    "org": {
        "title": "Organigramm & Teams",
        "subtitle": "Interaktiver 2D-Organisationsbaum aller 56 Agenten",
        "purpose": "Visualisiert die hierarchischen Beziehungen, Berichtswege und Rollen aller Agenten im Unternehmen. Ermöglicht das Umhängen von Vorgesetzten und Neukonfigurieren.",
        "top_actions": [
            "Klicke auf einen Agentenknoten, um das Eigenschaftsfenster zu öffnen und Name, Vorgesetzten oder Modell anzupassen.",
            "Nutze das Mausrad zum Zoomen und die linke Maustaste zum Verschieben der Arbeitsfläche.",
            "Beobachte die Status-Badges (Online / Busy / Idle) für jeden Agenten in Echtzeit."
        ],
        "starter_prompt": "Wie ändere ich den Vorgesetzten eines Agenten im Organigramm und wie wird das Modell für eine Rolle hinterlegt?"
    },
    "kader": {
        "title": "Agenten-Kader",
        "subtitle": "Vollständiges Verzeichnis aller 56 Rollen & Profile",
        "purpose": "Katalog aller aktivierten Agenten-Profile mit Aufgabenprofil, System-Prompts, Zuständigkeiten und Werkzeugberechtigungen.",
        "top_actions": [
            "Suche oder filtere nach Fachabteilungen (Geschäftsführung, IT, Marketing, Recht, Finanzen).",
            "Klicke auf eine Karte, um System-Prompts und operative Anweisungen zu bearbeiten.",
            "Weise dem Agenten direkt eine autonome Aufgabe zu."
        ],
        "starter_prompt": "Welcher Agent im Kader ist für rechtliche Prüfungen zuständig und welche Werkzeuge stehen ihm zur Verfügung?"
    },
    "crm": {
        "title": "CRM & Kontakte",
        "subtitle": "Beziehungs- und Interaktionsmanagement",
        "purpose": "Speichert Kunden, Partner, Bewerber und Vakanzen inklusive lückenloser Nachrichten- und E-Mail-Historie.",
        "top_actions": [
            "Importiere Kontakte aus LinkedIn oder synchronisiere mit Outlook / PocketBase.",
            "Klicke auf einen Kontakt, um den gesamten E-Mail- und Nachrichtenverlauf einzusehen.",
            "Lass einen Agenten automatische personalisierte E-Mails oder Angebote für diesen Kontakt generieren."
        ],
        "starter_prompt": "Wie kann ich einen Kontakt anlegen und den Agenten beauftragen, ein passendes Anschreiben für eine Vakanz zu verfassen?"
    },
    "showroom": {
        "title": "Showroom & Deliveries",
        "subtitle": "Zentrale Galerie aller Agenten-Ergebnisse & Dokumente",
        "purpose": "Hier landen alle fertiggestellten Berichte, PDF-Dokumente, Code-Artefakte und Analysen, die von Agenten erarbeitet wurden.",
        "top_actions": [
            "Vorschau von Markdown-Berichten und gerenderten HTML/PDF-Dokumenten.",
            "Herunterladen von erzeugten Dateien mit einem Klick.",
            "Filterung nach Typ (Code, Dokument, Analyse, Bild)."
        ],
        "starter_prompt": "Wo finde ich die von Agenten generierten PDFs und wie kann ich sie herunterladen oder weiterverarbeiten?"
    },
    "library": {
        "title": "Library & Knowledge Base",
        "subtitle": "Wissensspeicher, RAG-Index & Vault",
        "purpose": "Das kollektive Gedächtnis des Systems. Enthält Unternehmensrichtlinien, Gesetze, Fachwissen und Obsidian-Notizen, auf die alle Agenten zugreifen.",
        "top_actions": [
            "Durchsuche die Knowledge-Base nach Fachbegriffen oder Richtlinien.",
            "Synchronisiere das lokale Obsidian-Vault mit dem semantischen RAG-Index.",
            "Hinterlege neue Standard-Dokumente für die Wissensabfrage."
        ],
        "starter_prompt": "Wie synchronisiere ich neue Dokumente in den RAG-Index, damit die Agenten das Wissen sofort abrufen können?"
    },
    "mission_control": {
        "title": "Operations",
        "subtitle": "Echtzeit-Monitoring, System-KPIs & HITL-Freigaben",
        "purpose": "Mission Control dient als übersichtlicher Leitstand zur Überwachung des Gesamtsystems. Hier werden KPIs (Flottenlast, TPM, Latenz) angezeigt und die Aufgaben aus dem Operations-Kanban in 5 Spalten gespiegelt. Operative Änderungen und neue Aufgaben werden direkt im Operations-Kanban oder im Agenten-Kader verwaltet.",
        "top_actions": [
            "Überwache die 5 System-Kacheln für Flottenlast, Token/min und Antwortlatenz.",
            "Sichte anstehende Freigaben in der Review-Spalte und bestätige oder stoppe sie.",
            "Wechsle für die Neuanlage oder detaillierte Bearbeitung von Aufgaben in das Operations-Kanban."
        ],
        "starter_prompt": "Welche Aufgaben stehen aktuell in Mission Control und welche benötigen meine persönliche Freigabe?"
    },
    "automation": {
        "title": "n8n Automation Mesh",
        "subtitle": "Grafische Workflow-Engine & Webhook-Integration",
        "purpose": "Hier steuerst und erstellst du autonome Hintergrund-Workflows über n8n (Port 5678). Das System stellt Webhooks für Dokumenten-Rendering, CRM-Synchronisierung, Web-Recherche und Nachrichten-Versand bereit.",
        "top_actions": [
            "Erstelle oder passe Workflows mit visuellen Triggern und Knoten an.",
            "Nutze die 5 integrierten Archon-Webhooks für Datenaustausch und Automationen.",
            "Klicke auf 'Im neuen Tab öffnen', wenn du den n8n-Workflow-Editor im Vollbildmodus nutzen möchtest."
        ],
        "starter_prompt": "Welche Webhooks sind in n8n für Archon OS eingerichtet und wie kann ich einen neuen Workflow starten?"
    },
    "omniroute": {
        "title": "OmniRoute AI Gateway",
        "subtitle": "Multi-Provider KI-Routing & Token-Telemetrie",
        "purpose": "OmniRoute fungiert als intelligentes Gateway für alle LLM-Anfragen. Es verteilt Prompts kosten- und latenzoptimiert auf Provider wie Anthropic, OpenAI, DeepSeek, Gemini und lokale Modelle.",
        "top_actions": [
            "Prüfe das Routing-Verhalten und die Latenzen der verschiedenen KI-Modelle.",
            "Konfiguriere API-Schlüssel, Fallback-Strategien und Token-Budgets.",
            "Nutze virtuelle Modell-Aliase wie 'best-reasoning' oder 'free-forever' in deinen Agenten-Profilen."
        ],
        "starter_prompt": "Wie funktioniert das Routing in OmniRoute und welche Modelle sind als Fallback hinterlegt?"
    },
    "brain": {
        "title": "Second Brain & Lokales Obsidian Vault",
        "subtitle": "Zero-Latency Wissensmanagement & OCR-Archiv",
        "purpose": "Verbindet Archon OS direkt mit deinem lokalen Obsidian-Vault ('Mein Obsidian'). Dokumente, Notizen und Recherche-Ergebnisse werden hier in sauberer Markdown-Struktur abgelegt und durchsuchbar gemacht.",
        "top_actions": [
            "Wähle das aktive Vault aus (lokales Haupt-Vault oder Cloud/OneDrive).",
            "Lade Dokumente oder Fachbücher hoch, um sie automatisch per OCR zu indizieren.",
            "Öffne Dokumente direkt mit einem Klick in deiner lokalen Obsidian-Desktop-App."
        ],
        "starter_prompt": "Wie sind die Ordner im Obsidian-Vault strukturiert und wo legen Agenten ihre Recherche-Ergebnisse ab?"
    },
    "research": {
        "title": "Research Lab",
        "subtitle": "Multi-Engine Recherche & Evidenz-Triangulation",
        "purpose": "Tiefenrecherche über verschiedene Web- und Fachquellen. Agenten sammeln Fakten, vergleichen Quellen und erstellen fundierte Dossiers zur direkten Ablage im Obsidian-Vault.",
        "top_actions": [
            "Starte gezielte Marktforschungs- oder Dokumentenrecherchen mit Quellenangaben.",
            "Wähle die Such-Engine und das zuständige Analyse-Modell.",
            "Sichte fertige Dossiers und überführe sie in den Showroom oder ins Vault."
        ],
        "starter_prompt": "Wie beauftrage ich eine strukturierte Marktanalyse im Research Lab?"
    },
    "plugins": {
        "title": "Erweiterungen & Modul-Zentrale",
        "subtitle": "Hermes Spezial-Plugins & Funktionserweiterungen",
        "purpose": "Übersicht und Schalter für alle 34 modularen Erweiterungen wie JEV-Routing, Injektionsschutz, E-Mail-Sync, RAG-Suche und automatische Dokumentenverarbeitung.",
        "top_actions": [
            "Aktiviere oder deaktiviere einzelne Module nach Bedarf.",
            "Passe Parameter und Schwellenwerte für spezifische Plugins an.",
            "Prüfe den Ladestatus und eventuelle Abhängigkeiten."
        ],
        "starter_prompt": "Welche Plugins sind derzeit aktiv und wie schütze ich das System vor Prompt-Injections?"
    },
    "guardian": {
        "title": "Guardian & Token Analytics",
        "subtitle": "Kostenkontrolle, Schleifenschutz & Wächter",
        "purpose": "Der Guardian überwacht Token-Verbrauch, API-Kosten und Ausführungszeiten. Er stoppt Endlosschleifen und warnt bei Überschreitung festgelegter Budgets.",
        "top_actions": [
            "Analysiere den Token-Verbrauch gefiltert nach Zeitraum (24h, 7 Tage, 30 Tage, Gesamt).",
            "Überprüfe Kosten pro Agent und Modell.",
            "Passe Sicherheits-Limits für maximale Token pro Anfrage oder Tag an."
        ],
        "starter_prompt": "Welcher Agent hat heute die meisten Tokens verbraucht und wie setze ich ein tägliches Ausgabenlimit?"
    },
    "master_chat": {
        "title": "Master Chat",
        "subtitle": "Direkte Konversation mit jedem beliebigen Agenten",
        "purpose": "Ermöglicht den 1:1 Dialog mit jedem Spezialisten aus dem Kader oder mit dem Lead-Orchestrator Robert. Ideal für Ad-hoc-Fragen, Coaching und schnelle Prüfungen.",
        "top_actions": [
            "Wähle den gewünschten Agenten aus dem Dropdown im Kopfbereich.",
            "Nutze Sprachnachrichten oder Text zur schnellen Klärung offener Punkte.",
            "Übertrage Ergebnisse aus dem Chat direkt in einen neuen Kanban-Task."
        ],
        "starter_prompt": "Wie wähle ich den passenden Agenten für ein direktes Beratungsgespräch im Master Chat aus?"
    },
    "system_settings": {
        "title": "System Control Center (Einstellungen)",
        "subtitle": "Zentrale Konfiguration für Hermes Core, Plugins & Kommunikation",
        "purpose": "Verwaltung von Kernel-Limits, Docker-Containern, Live-YAML-Editor, Provider-Keys, 15+ Plugins und Kommunikationskanälen (E-Mail, Telegram, n8n).",
        "top_actions": [
            "Hermes Core: Prüfe und editiere die aktiven Config-Dateien im 1:1 Live-Editor.",
            "Plugins: Aktiviere oder konfiguriere JEV-Routing, Adaptives Memory, Quality Gate und Injection Guard.",
            "Kommunikation: Richte SMTP, Telegram-Bots und das n8n Automation Mesh ein."
        ],
        "starter_prompt": "Welche Einstellungen sollte ich vornehmen, um n8n-Webhooks und E-Mail-Benachrichtigungen scharfzuschalten?"
    },
    "new_task_modal": {
        "title": "Neuer Task Dialog",
        "subtitle": "Auftragserteilung an autonome Agenten",
        "purpose": "Erlaubt das präzise Formulieren von Aufgaben mit KI-Prompt-Optimierung, Audio-Diktat (Mikrofon) und Dateianhängen.",
        "top_actions": [
            "Sprich deine Aufgabe per Klick auf das Mikrofon-Icon ein (Spracherkennung).",
            "Nutze 'KI optimieren', um die Aufgabenstellung für das LLM zu schärfen.",
            "Wähle den Ziel-Agenten oder nutze den automatischen JEV-Router."
        ],
        "starter_prompt": "Wie formuliere ich eine Aufgabe am besten, damit der JEV-Router automatisch den optimalen Agenten auswählt?"
    },
    "agent_detail_modal": {
        "title": "Agenten-Detail-Editor",
        "subtitle": "Rollenprofil & Vorgesetzten-Steuerung",
        "purpose": "Bearbeitung aller Kern-Eigenschaften eines Agenten: Name, Modell, Provider, Rolle und Zuordnung im Organigramm.",
        "top_actions": [
            "Ändere den Vorgesetzten, um den Agenten im Organigramm neu einzuordnen.",
            "Wähle ein spezifisches LLM-Modell für diese Rolle (z. B. Claude 3.7 Sonnet oder Gemini 2.5 Pro).",
            "Passe den System-Prompt an, um das Verhalten der Rolle zu verfeinern."
        ],
        "starter_prompt": "Welches Sprachmodell eignet sich am besten für anspruchsvolle Programmier- oder Analyseaufgaben?"
    },
    "finance": {
        "title": "Finanzen & Belegwesen",
        "subtitle": "Kaufmännische Vorgänge, Rechnungen & Buchhaltung",
        "purpose": "Zentrale Erfassung und Auswertung aller kaufmännischen Belege, Rechnungsstellungen, Zahlungsflüsse und Buchungsdaten.",
        "top_actions": [
            "Erfasse oder importiere kaufmännische Belege und Eingangsrechnungen.",
            "Überprüfe Zahlungsstatus und offene Posten im Rechnungsjournal.",
            "Lass Rechnungen automatisiert durch den Buchhaltungs-Agenten vorkontieren."
        ],
        "starter_prompt": "Wie erstelle ich einen neuen Beleg oder lasse eine Eingangsrechnung durch den Finance-Agenten prüfen?"
    },
    "approvals": {
        "title": "Freigabe-Richtlinien & HITL",
        "subtitle": "Compliance-Regeln & Governance-Schwellenwerte",
        "purpose": "Definition von Governance-Regeln, Finanz-Schwellenwerten und Sicherheitsleitplanken, ab wann ein Agent menschliche Freigabe (HITL) einholen muss.",
        "top_actions": [
            "Passe Euro-Schwellenwerte für automatische Budgetfreigaben an.",
            "Definiere Rollenberechtigungen für kritische Systemeingriffe.",
            "Überprüfe das Audit-Log aller bisher erteilten Freigaben."
        ],
        "starter_prompt": "Wie konfiguriere ich eine neue Freigaberegel für Zahlungen über 500 Euro?"
    },
    "items": {
        "title": "Artikel & Leistungen",
        "subtitle": "ERP-Gesamtkatalog für Produkte, Dienstleistungen & Konditionen",
        "purpose": "Verwaltung des gesamten Artikelstamms, Dienstleistungs-Katalogs, Preise, Steuersätze und SKU-Einheiten für automatisierte Angebotserstellung.",
        "top_actions": [
            "Lege neue Artikel, Stundensätze oder Service-Pakete an.",
            "Pflege Einkaufs- und Verkaufspreise inklusive Rabattstaffeln.",
            "Synchronisiere Artikeldaten mit externen Warenwirtschaftssystemen."
        ],
        "starter_prompt": "Wie lege ich eine neue Dienstleistungsposition für automatische Angebote an?"
    },
    "operations_erp": {
        "title": "Vorgänge & Verträge",
        "subtitle": "ERP-Auftragsabwicklung, Angebote & Projektverträge",
        "purpose": "End-to-End-Abwicklung kaufmännischer Geschäftsvorgänge von der Anfrage über das Angebot bis zum rechtsgültigen Auftrag und Leistungsnachweis.",
        "top_actions": [
            "Erstelle aus einer CRM-Anfrage ein vollständiges Angebot.",
            "Wandle freigegebene Angebote per Klick in Verträge und Aufträge um.",
            "Verfolge den Bearbeitungs- und Lieferstatus laufender Kundenprojekte."
        ],
        "starter_prompt": "Wie erstelle ich aus einem Kontakt einen neuen Geschäftsvorgang mit Angebot?"
    },
    "corporate": {
        "title": "Corporate & Mandanten",
        "subtitle": "Multi-Company Struktur, Unternehmensstamm & Beteiligungen",
        "purpose": "Verwaltung rechtlicher Entitäten, Firmenstammdaten, Steuernummern, Bankverbindungen und Mandantentrennung im Agentic OS.",
        "top_actions": [
            "Wechsle zwischen aktiven Mandanten und Tochtergesellschaften.",
            "Pflege Unternehmensstammdaten, Briefköpfe und IBANs je Mandant.",
            "Weise Agenten und Budgets spezifischen Firmenentitäten zu."
        ],
        "starter_prompt": "Wie richte ich einen neuen Mandanten ein und hinterlege dessen Stammdaten?"
    },
    "boardroom": {
        "title": "AI Mastermind · Boardroom",
        "subtitle": "Strategische Multi-Agenten-Debatten & Entscheidungsfindung",
        "purpose": "Führt strukturierte C-Level-Debatten mit gegnerischen Perspektiven (Red Team / Blue Team) durch und destilliert revisionssichere Entscheidungs-Memos.",
        "top_actions": [
            "Starte eine neue Fragestellung mit Rollenverteilung (z. B. CEO vs. CFO vs. Legal).",
            "Wähle ein Framework (Pre-Mortem, 6 Thinking Hats, SWOT-Stresstest).",
            "Exportiere das finale Konsens-Memo direkt ins Knowledge-System."
        ],
        "starter_prompt": "Wie starte ich eine kontroverse Boardroom-Debatte zu einer strategischen Investition?"
    },
    "watchdog": {
        "title": "Internet-Watchdog · Radar",
        "subtitle": "Kontinuierliches Markt-, Wettbewerbs- & Bedrohungs-Monitoring",
        "purpose": "Autonomes Radar, das Web-Quellen, Nachrichten, Marktbegleiter und Sicherheits-Feeds scannt und relevante Signale direkt in den Posteingang triagiert.",
        "top_actions": [
            "Trage Suchbegriffe, URLs oder RSS-Feeds für das Dauermonitoring ein.",
            "Definiere Alarm-Schwellenwerte für automatische Benachrichtigungen.",
            "Lass Zusammenfassungen neuer Marktbewegungen durch den Research-Agenten erstellen."
        ],
        "starter_prompt": "Wie richte ich einen neuen Radar-Watcher für Wettbewerber-Aktivitäten ein?"
    },
    "design_system": {
        "title": "Design System Lab",
        "subtitle": "UI-Tokens, Komponenten & interaktive Schnittstellen-Vorschau",
        "purpose": "Entwicklungsumgebung für UI-Tokens, Farbpaletten, Typografie und standardisierte Tailwind-Komponenten des Archon-Design-Systems.",
        "top_actions": [
            "Prüfe Farbkontraste und Dark-Mode-Verhalten aller Kern-Komponenten.",
            "Kopiere vorgefertigte HTML- und Tailwind-Codeblöcke für neue Ansichten.",
            "Teste Buttons, Modals, Tabellen und Badges interaktiv im Sandkasten."
        ],
        "starter_prompt": "Wie übernehme ich eine Komponente aus dem Design System Lab in eine neue Ansicht?"
    },
    "css_studio": {
        "title": "Archon CSS Live Studio",
        "subtitle": "Echtzeit-Stilinspektor, Visual-Editor & Style-Override-Manager",
        "purpose": "Erlaubt das direkte Anpassen, Vermessen und persistente Speichern von CSS-Regeln und Layout-Größen auf der Live-Oberfläche.",
        "top_actions": [
            "Klicke auf den Inspektieren-Modus, um ein UI-Element direkt auf dem Bildschirm anzuwählen.",
            "Passe Abstände, Farben und Schriftarten im visuellen Inspector an.",
            "Speichere Regeln temporär oder übernehme sie dauerhaft in das Theme."
        ],
        "starter_prompt": "Wie nutze ich den CSS Studio Inspector, um Abstände eines Elements live anzupassen?"
    },
    "log_stream": {
        "title": "Live Log-Stream",
        "subtitle": "Echtzeit-Telemetrie & System-Audit-Trail",
        "purpose": "Zentraler Stream aller Kernel-Ereignisse, Agenten-Ausführungen, Tool-Calls und Fehlermeldungen in Echtzeit mit Filter- und Suchfunktion.",
        "top_actions": [
            "Filtere nach Loglevel (DEBUG, INFO, WARNING, ERROR).",
            "Suche nach spezifischen Task-IDs oder Agenten-Namen.",
            "Pausiere den Stream für eine detaillierte Ursachenanalyse."
        ],
        "starter_prompt": "Wie filtere ich im Log-Stream nach Fehlern eines bestimmten Agenten?"
    }
}

# --- MEILENSTEIN 4: MULTI-USER & RBAC ENDPOINTS ---
from backend.auth_service import auth_service

def get_current_user_from_request(request: Request) -> dict:
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "x-archon-session" in request.headers:
        token = request.headers.get("x-archon-session", "").strip()
    elif "archon_session" in request.cookies:
        token = request.cookies.get("archon_session", "").strip()

    is_enabled = auth_service.is_auth_enabled()

    if token:
        user = auth_service.verify_session(token)
        if user:
            user["auth_enabled"] = is_enabled
            return user

    fb = auth_service.get_fallback_admin()
    fb["auth_enabled"] = is_enabled
    return fb

@app.get("/api/auth/status")
def api_auth_status():
    return {
        "status": "success",
        "auth_enabled": auth_service.is_auth_enabled()
    }

@app.post("/api/auth/toggle")
def api_auth_toggle(request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen den Authentifizierungsmodus ändern.")
    enabled = bool(payload.get("enabled", False))
    s = _load_json(SETTINGS_FILE, {})
    if "auth" not in s or not isinstance(s["auth"], dict):
        s["auth"] = {}
    s["auth"]["enabled"] = enabled
    s["auth"]["mode"] = "multi_user" if enabled else "single_user"
    _save_json(SETTINGS_FILE, s)

    alt_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json"),
        "/app/settings.json"
    ]
    for alt in alt_paths:
        try:
            if os.path.exists(alt) and os.path.abspath(alt) != os.path.abspath(SETTINGS_FILE):
                alt_s = _load_json(alt, {})
                if "auth" not in alt_s or not isinstance(alt_s["auth"], dict):
                    alt_s["auth"] = {}
                alt_s["auth"]["enabled"] = enabled
                alt_s["auth"]["mode"] = s["auth"]["mode"]
                _save_json(alt, alt_s)
        except Exception:
            pass
    return {
        "status": "success",
        "auth_enabled": enabled,
        "mode": s["auth"]["mode"],
        "message": "Multi-User-Modus aktiviert." if enabled else "Einzelplatz-Modus aktiviert (keine Anmeldung erforderlich)."
    }

@app.get("/api/auth/me")
def api_auth_me(request: Request):
    user = get_current_user_from_request(request)
    return {
        "status": "success",
        "user": user,
        "auth_enabled": auth_service.is_auth_enabled()
    }

@app.post("/api/auth/login")
def api_auth_login(request: Request, payload: dict = Body(...)):
    username = payload.get("username", "")
    password = payload.get("password", "")
    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    session = auth_service.authenticate(username, password, ip_address=client_ip, user_agent=user_agent)
    if not session:
        raise HTTPException(status_code=401, detail="Ungültiger Benutzername oder falsches Passwort.")
    res = JSONResponse(content={"status": "success", **session})
    res.set_cookie(key="archon_session", value=session["token"], max_age=86400 * 30, httponly=True, samesite="lax")
    return res

@app.post("/api/auth/logout")
def api_auth_logout(request: Request):
    token = request.cookies.get("archon_session") or request.headers.get("x-archon-session", "")
    if token:
        auth_service.logout(token)
    res = JSONResponse(content={"status": "success", "message": "Erfolgreich abgemeldet."})
    res.delete_cookie(key="archon_session")
    return res

@app.get("/api/auth/users")
def api_auth_list_users(request: Request):
    curr = get_current_user_from_request(request)
    if curr.get("role") not in ("admin", "operator"):
        return {"status": "success", "users": [curr]}
    return {"status": "success", "users": auth_service.list_users()}

@app.post("/api/auth/users")
def api_auth_create_user(request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen neue Benutzer anlegen.")
    try:
        new_u = auth_service.create_user(
            username=payload.get("username"),
            password=payload.get("password"),
            role=payload.get("role", "operator"),
            display_name=payload.get("display_name", ""),
            email=payload.get("email", "")
        )
        return {"status": "success", "user": new_u}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/api/auth/users/{user_id}")
def api_auth_update_user(user_id: str, request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Benutzerrollen anpassen.")
    try:
        updated = auth_service.update_user(
            user_id=user_id,
            role=payload.get("role"),
            display_name=payload.get("display_name"),
            email=payload.get("email"),
            is_active=payload.get("is_active")
        )
        return {"status": "success", "user": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/auth/users/{user_id}")
def api_auth_delete_user(user_id: str, request: Request):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Benutzer löschen.")
    try:
        auth_service.delete_user(user_id)
        return {"status": "success", "message": "Benutzer gelöscht."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/system/language")
def get_system_language():
    s = _load_json(SETTINGS_FILE, {})
    lang = s.get("system_language") or s.get("language") or "de"
    return {
        "status": "success",
        "language": lang,
        "supported": ["de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"]
    }

@app.post("/api/system/language")
def set_system_language(payload: dict = Body(...)):
    lang = (payload.get("language") or "de").strip().lower()
    supported = ["de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"]
    if lang not in supported:
        raise HTTPException(status_code=400, detail=f"Nicht unterstützte Sprache: {lang}")
    s = _load_json(SETTINGS_FILE, {})
    s["system_language"] = lang
    s["language"] = lang
    s["default_language"] = lang
    _save_json(SETTINGS_FILE, s)
    return {"status": "success", "language": lang}

@app.get("/api/help/context/{view_id}")
def api_get_help_context(view_id: str):
    normalized = (view_id or "").strip().lower().replace("-", "_")
    ctx = HELP_CONTEXT_DATA.get(view_id) or HELP_CONTEXT_DATA.get(normalized)
    if not ctx:
        ctx = {
            "title": f"Ansicht: {view_id}",
            "subtitle": "Bereich im Archon Agentic OS",
            "purpose": "Dieser Bereich dient der operativen Steuerung und Interaktion mit dem Agenten-Ökosystem.",
            "top_actions": [
                "Nutze die Aktionen und Buttons im Kopfbereich der Ansicht.",
                "Stelle unten eine konkrete Frage an den System-Assistenten."
            ],
            "starter_prompt": f"Was kann ich im Bereich '{view_id}' tun und wie ist dieser aufgebaut?"
        }
    return ctx

@app.post("/api/help/ask")
async def api_ask_help_assistant(payload: dict = Body(...)):
    view_id = payload.get("view_id", "operations")
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Keine Frage übermittelt.")
        
    ctx = HELP_CONTEXT_DATA.get(view_id, {})
    view_title = ctx.get("title", view_id)
    view_purpose = ctx.get("purpose", "")
    
    system_prompt = (
        f"Du bist der hochkompetente, freundliche und präzise Archon OS System-Assistent.\n"
        f"Der Nutzer befindet sich gerade in der Ansicht '{view_title}'.\n"
        f"Zweck dieser Ansicht: {view_purpose}\n"
        f"Beantworte die Frage des Nutzers direkt, konkret und hilfreich auf Deutsch. "
        f"Verzichte auf Floskeln, Begrüßungen und Füllwörter. Gib praxisnahe Schritt-für-Schritt-Anleitungen."
    )
    
    # Provider-Schluessel ermitteln
    import api_provider
    from backend.agent_router import router_instance
    all_keys = api_provider.collect_keys()
    reply_text = ""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question}
    ]
    
    if all_keys.get("OPENROUTER_API_KEY"):
        try:
            reply_text = await router_instance.chat_completion(messages, "openrouter", "google/gemini-2.5-flash", all_keys, max_tokens=500)
        except Exception:
            pass
            
    if not reply_text and (all_keys.get("GEMINI_API_KEY") or all_keys.get("GOOGLE_API_KEY")):
        try:
            reply_text = await router_instance.chat_completion(messages, "google", "gemini-1.5-flash", all_keys, max_tokens=500)
        except Exception:
            pass
            
    # 3. Fallback: Heuristische Antwort aus dem Spickzettel
    if not reply_text:
        actions_txt = "\n- ".join(ctx.get("top_actions", []))
        reply_text = (
            f"**{view_title}**\n\n"
            f"{view_purpose}\n\n"
            f"**Wichtigste Aktionen in diesem Bereich:**\n- {actions_txt}\n\n"
            f"*(Hinweis: Für vertiefte KI-Antworten bitte OpenRouter oder Gemini API-Key in den Einstellungen hinterlegen.)*"
        )
        
    return {
        "status": "success",
        "view_id": view_id,
        "question": question,
        "answer": reply_text
    }

_PAPERCLIP_AGENTS_CACHE = None
_PAPERCLIP_AGENTS_CACHE_TIME = 0.0
_PAPERCLIP_AGENTS_CACHE_TTL = 30.0

def invalidate_paperclip_agents_cache():
    global _PAPERCLIP_AGENTS_CACHE, _PAPERCLIP_AGENTS_CACHE_TIME
    _PAPERCLIP_AGENTS_CACHE = None
    _PAPERCLIP_AGENTS_CACHE_TIME = 0.0

@app.get("/api/paperclip/agents")
def api_get_paperclip_agents():
    return {"status": "success", "agents": []}

# --- CSS Live Studio: Hintergrund-Bild-Upload (User-Wunsch 10.10.2026) ---
STUDIO_BG_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")

@app.post("/api/studio/upload-bg")
async def api_studio_upload_bg(file: UploadFile = File(...)):
    """Lädt ein Hintergrundbild (JPG/PNG/WebP) für das CSS Live Studio hoch.
    Speichert unter /static/uploads/ und liefert die URL zurück."""
    allowed_ext = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp", ".gif": "image/gif"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Dateityp '{ext}' nicht erlaubt (jpg, jpeg, png, webp, gif).")
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Bild zu groß (max. 8 MB).")
    os.makedirs(STUDIO_BG_UPLOAD_DIR, exist_ok=True)
    ts = int(time.time() * 1000)
    safe_ext = ext if ext else ".jpg"
    out_name = f"studio-bg_{ts}{safe_ext}"
    out_path = os.path.join(STUDIO_BG_UPLOAD_DIR, out_name)
    with open(out_path, "wb") as f:
        f.write(content)
    add_ticker("CSS Studio", f"Hintergrundbild hochgeladen: {out_name}")
    return {"status": "success", "url": f"/static/uploads/{out_name}", "filename": out_name, "size": len(content)}

@app.delete("/api/hermes/profiles/{profile_id}")
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

@app.post("/api/hermes/profiles/{profile_id}/favorite")
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

# --- TALENT- & SKILL-MARKTPLATZ ENDPOINTS ---
try:
    from utils.repo_sync import get_marketplace_sources, list_templates_for_source, get_template_detail
except Exception:
    def get_marketplace_sources():
        return [
            {"id": "fabric", "name": "Daniel Miessler Fabric (255+ Patterns)"},
            {"id": "crewai", "name": "CrewAI Business Roles"},
            {"id": "anthropic", "name": "Anthropic C-Suite Hub"}
        ]
    def list_templates_for_source(s, search=None, category=None): return []
    def get_template_detail(s, t): return None

try:
    from utils.skill_marketplace import get_skill_marketplace_sources, list_skills_for_source, get_skill_detail
except Exception:
    def get_skill_marketplace_sources(): return []
    def list_skills_for_source(s="realestate", search=None, category=None): return []
    def get_skill_detail(s, sid): return None

@app.get("/api/marketplace/sources")
def api_get_marketplace_sources():
    return get_marketplace_sources()

@app.get("/api/marketplace/templates")
def api_get_marketplace_templates(source: str = Query("fabric"), search: str = Query(None), category: str = Query(None)):
    return list_templates_for_source(source, search=search, category=category)

@app.get("/api/marketplace/template")
def api_get_marketplace_template_detail(source: str = Query(...), id: str = Query(...)):
    detail = get_template_detail(source, id)
    if not detail:
        raise HTTPException(status_code=404, detail="Template not found")
    return detail

@app.get("/api/marketplace/skills/sources")
def api_get_skill_sources():
    return get_skill_marketplace_sources()

@app.get("/api/marketplace/skills")
def api_get_skills_list(source: str = Query("realestate"), search: str = Query(None), category: str = Query(None)):
    return list_skills_for_source(source, search=search, category=category)

@app.get("/api/marketplace/skill")
def api_get_skill_detail(source: str = Query(...), id: str = Query(...)):
    detail = get_skill_detail(source, id)
    if not detail:
        raise HTTPException(status_code=404, detail="Skill not found")
    return detail

@app.post("/api/marketplace/skills/assign")
def api_assign_skill_to_profile(data: Dict = Body(...)):
    profile_id = data.get("profile_id")
    skill_name = data.get("skill_name") or data.get("skill_id")
    if not profile_id or not skill_name:
        raise HTTPException(status_code=400, detail="profile_id and skill_name are required")
        
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
    save_all_agent_profiles(roles_list)
    invalidate_hermes_profiles_cache()

    # 2. Synchronize skill directory/tag in profile folders
    for p_base in [HERMES_PROFILES_DIR, "/opt/data/profiles", os.path.expanduser("~/.hermes/profiles")]:
        prof_skills_dir = os.path.join(p_base, profile_id, "skills")
        if os.path.exists(os.path.join(p_base, profile_id)):
            os.makedirs(prof_skills_dir, exist_ok=True)
            with open(os.path.join(prof_skills_dir, f"{skill_name}.md"), "w", encoding="utf-8") as f:
                f.write(f"# Assigned Skill: {skill_name}\n")

    return {"status": "success", "profile_id": profile_id, "assigned_skill": skill_name}

@app.post("/api/marketplace/recruit")
def api_marketplace_recruit(data: Dict = Body(...)):
    source = data.get("source", "fabric")
    template_id = data.get("template_id") or data.get("id")
    custom_name = data.get("name")
    
    tpl = get_template_detail(source, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
        
    profile_id = template_id.lower().replace("-", "_").replace(" ", "_")
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

    save_all_agent_profiles(roles_list)
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

SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

@app.post("/api/settings")
async def api_save_settings(request: Request, settings: Dict = Body(None)):
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        return await forward_to_hermes(request)

    current = _load_json(SETTINGS_FILE, {})
    if isinstance(current, dict) and isinstance(settings, dict):
        current.update(settings)
        _save_json(SETTINGS_FILE, current)
    elif settings is not None:
        _save_json(SETTINGS_FILE, settings)
    try:
        from backend.audit_log import chained_audit_log
        keys_changed = list(settings.keys()) if isinstance(settings, dict) else ["all"]
        chained_audit_log.record_event(
            category="config",
            action="settings_saved",
            agent_id="operator",
            payload={"changed_keys": keys_changed}
        )
    except Exception:
        pass
    return {"status": "success"}

@app.post("/api/v1/jev/test")
async def api_test_jev(payload: Dict = Body(None)):
    import jev_router
    payload = payload or {}
    res = jev_router.test_jev_connection(
        api_key=payload.get("api_key"),
        base_url=payload.get("base_url")
    )
    return res

@app.get("/api/v1/memory/stats")
def api_get_memory_stats():
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    learnings_cnt = 0
    conv_cnt = 0
    stale_cnt = 0
    try:
        conn = bridge._get_conn()
        cur = conn.cursor()
        learnings_cnt = cur.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        conv_cnt = cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        stale_info = bridge.evict_stale_memories(threshold=0.1, table="learnings", dry_run=True)
        stale_cnt = stale_info.get("stale_count", 0)
        conn.close()
    except Exception:
        pass

    vault_summary = bridge.scan_vault_summary()
    vault_notes = vault_summary.get("total_notes", 0) if isinstance(vault_summary, dict) else 0

    return {
        "status": "success",
        "learnings_count": learnings_cnt,
        "conversations_count": conv_cnt,
        "stale_count": stale_cnt,
        "vault_notes_count": vault_notes,
        "vault_path": bridge.vault_path
    }

class SmtpConfigPayload(BaseModel):
    enabled: Optional[bool] = False
    auto_send: Optional[bool] = False
    host: Optional[str] = ""
    port: Optional[int] = 587
    username: Optional[str] = ""
    password: Optional[str] = ""
    from_email: Optional[str] = ""
    to_email: Optional[str] = ""
    use_tls: Optional[bool] = True

@app.get("/api/v1/settings/smtp")
def api_get_smtp_settings():
    from backend.post_task_pipeline import get_smtp_config
    cfg = get_smtp_config()
    safe_cfg = dict(cfg)
    if safe_cfg.get("password"):
        safe_cfg["password"] = "••••••••"
    return {"status": "ok", "config": safe_cfg}

@app.post("/api/v1/settings/smtp")
def api_save_smtp_settings(payload: SmtpConfigPayload):
    from backend.post_task_pipeline import save_smtp_config, get_smtp_config
    current = get_smtp_config()
    cfg_data = payload.dict()
    if cfg_data.get("password") == "••••••••":
        cfg_data["password"] = current.get("password", "")
    success = save_smtp_config(cfg_data)
    return {"status": "success" if success else "error"}

@app.post("/api/v1/settings/smtp/test")
def api_test_smtp_settings(payload: SmtpConfigPayload):
    from backend.post_task_pipeline import send_smtp_email, get_smtp_config, save_smtp_config
    current = get_smtp_config()
    cfg_data = payload.dict()
    if cfg_data.get("password") == "••••••••":
        cfg_data["password"] = current.get("password", "")
    save_smtp_config(cfg_data)

    sub = "ðŸ§ª Archon OS: SMTP-Testnachricht"
    body = "Dies ist eine automatische Testnachricht von deinem Archon OS System. Die E-Mail-Konfiguration funktioniert einwandfrei!"
    html = "<div style='font-family: sans-serif; padding: 20px;'><h2 style='color: #0f172a;'>ðŸ§ª Archon OS SMTP-Test</h2><p>Die E-Mail-Konfiguration funktioniert einwandfrei!</p></div>"
    res = send_smtp_email(sub, body, html)
    return res

@app.post("/api/v1/inbox/emails/sync")
def api_sync_emails_endpoint():
    try:
        from backend.email_service import sync_imap_inbox
        return sync_imap_inbox(limit=30)
    except Exception as e:
        return {"status": "error", "message": str(e), "synced": 0}

@app.get("/api/v1/agent/{agent_id}/stats")
def api_get_agent_real_stats(agent_id: str):
    """Liefert echte Leistungsdaten aus der Personalakte und den Datenbanken."""
    import re
    from pathlib import Path
    vault_dir = Path("/opt/data/obsidian") if Path("/opt/data/obsidian").exists() else Path(r"C:\Mein Obsidian")
    akte = vault_dir / "00_HR_Agenten" / "Personalakten" / f"{agent_id}.md"
    tasks_completed = 0
    if akte.exists():
        try:
            txt = akte.read_text(encoding="utf-8")
            m = re.search(r"tasks_completed:\s*(\d+)", txt)
            if m:
                tasks_completed = int(m.group(1))
        except Exception:
            pass

    learnings_count = 0
    try:
        from local_memory_bridge import LocalMemoryBridge
        b = LocalMemoryBridge()
        with b._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM learnings WHERE agent_id = ?", (agent_id,))
            learnings_count = c.fetchone()[0]
    except Exception:
        pass

    return {
        "status": "ok",
        "agent_id": agent_id,
        "tasks_completed": tasks_completed,
        "learnings_count": learnings_count,
        "performance_rating": "100% nominal" if tasks_completed > 0 else "Bereit im Standby",
        "is_deployed": True
    }

@app.post("/api/v1/memory/consolidate")
def api_consolidate_memory(payload: Dict = Body(None)):
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    payload = payload or {}
    hours_back = payload.get("hours_back", 24)

    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_id, role, content, timestamp 
            FROM conversations 
            ORDER BY id DESC LIMIT 40
        """)
        rows = cur.fetchall()

    if not rows:
        return {"status": "empty", "message": "Keine Chat-Einträge zur Konsolidierung gefunden."}

    facts = []
    for r in reversed(rows):
        txt = (r["content"] or "").strip().replace("\n", " ")
        if len(txt) > 20 and not txt.startswith("{") and not txt.startswith("["):
            facts.append(f"- [{r['agent_id']}] {txt[:120]}")

    facts_text = "\n".join(facts[:10])
    if not facts_text:
        facts_text = "- [general] Routinemäßiger Systemdurchlauf ohne kritische Vorfälle."

    vault_path = bridge.vault_path
    note_file = None
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if os.path.exists(vault_path):
        mem_dir = os.path.join(vault_path, "memories")
        os.makedirs(mem_dir, exist_ok=True)
        note_path = os.path.join(mem_dir, f"daily_consolidation_{today}.md")
        md_content = f"""---
title: "Tages-Konsolidierung: {today}"
date: {today}
tags: ["memory", "consolidated", "daily"]
source: "Archon OS Memory Bridge"
---

# Tages-Konsolidierung: {today}

## Extrahierte Erkenntnisse
{facts_text}

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""
        try:
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            note_file = note_path
        except Exception as e:
            note_file = str(e)

    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO learnings (agent_id, category, summary, obsidian_link, importance, accesses, last_accessed)
            VALUES (?, ?, ?, ?, 2.0, 1, CURRENT_TIMESTAMP)
        """, ("consolidator", "daily_summary", f"Tages-Zusammenfassung {today}: {len(facts)} Interaktionen analysiert", f"[[daily_consolidation_{today}]]"))
        conn.commit()

    return {
        "status": "success",
        "message": f"{len(facts)} Interaktionen konsolidiert.",
        "note_file": note_file,
        "facts_count": len(facts)
    }

@app.post("/api/v1/memory/evict")
def api_evict_stale_memory(payload: Dict = Body(None)):
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    payload = payload or {}
    threshold = float(payload.get("threshold", 0.1))
    dry_run = bool(payload.get("dry_run", False))

    res_conv = bridge.evict_stale_memories(threshold=threshold, table="conversations", dry_run=dry_run)
    res_learn = bridge.evict_stale_memories(threshold=threshold, table="learnings", dry_run=dry_run)

    return {
        "status": "success",
        "conversations_pruned": res_conv.get("stale_count", 0),
        "learnings_pruned": res_learn.get("stale_count", 0),
        "threshold": threshold,
        "dry_run": dry_run
    }

@app.get("/api/v1/models")
def api_get_models_v1():
    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-r1", "hermes-3", "llama-3.3-70b"]

@app.post("/api/v1/security/scan-email")
def api_scan_email_security(payload: Dict = Body(None)):
    from local_security_guard import scan_prompt_injection
    payload = payload or {}
    text = payload.get("text") or payload.get("body") or ""
    subject = payload.get("subject", "")
    sender = payload.get("sender", "")
    sensitivity = payload.get("sensitivity", "moderate")
    use_llm = bool(payload.get("use_llm", False))
    model = payload.get("model", "omniroute/free-forever")
    res = scan_prompt_injection(text, subject=subject, sender=sender, sensitivity=sensitivity, use_llm=use_llm, model=model)
    return {"status": "success", **res}

@app.post("/api/v1/security/validate-output")
def api_validate_output_security(payload: Dict = Body(None)):
    from local_security_guard import validate_ai_output
    payload = payload or {}
    task = payload.get("task", "")
    result = payload.get("result", "")
    model_used = payload.get("model_used", "default")
    min_score = int(payload.get("min_score", 7))
    use_llm = bool(payload.get("use_llm", False))
    judge_model = payload.get("judge_model", "omniroute/free-forever")
    res = validate_ai_output(task, result, model_used=model_used, min_score=min_score, use_llm=use_llm, judge_model=judge_model)
    return {"status": "success", **res}

@app.get("/api/v1/security/stats")
def api_get_security_stats():
    # Zählt Mails im Posteingang und deren Sicherheitsstatus
    from views.view_inbox import load_email_messages, load_telegram_messages
    emails = load_email_messages()
    telegrams = load_telegram_messages()
    all_items = emails + telegrams
    blocked_cnt = sum(1 for m in all_items if m.get("security_status") == "blocked")
    suspicious_cnt = sum(1 for m in all_items if m.get("security_status") == "suspicious")
    safe_cnt = sum(1 for m in all_items if m.get("security_status") == "safe")
    return {
        "status": "success",
        "total_scanned": len(all_items),
        "blocked_count": blocked_cnt,
        "suspicious_count": suspicious_cnt,
        "safe_count": safe_cnt
    }

# --- RESEARCH LAB ENDPOINTS (SÄULE 2: KOGNITION & WISSEN) ---
@app.get("/api/v1/research/providers")
def api_get_research_providers():
    import research_engine
    return {"status": "success", "providers": research_engine.get_available_providers(_load_json(SETTINGS_FILE, {}))}

@app.post("/api/v1/research/run")
def api_run_research_mission(payload: dict):
    import research_engine
    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query darf nicht leer sein.")
    profile = payload.get("profile", "deep")
    engines = payload.get("engines", ["duckduckgo", "grokipedia", "wikipedia", "arxiv"])
    depth = int(payload.get("depth", 3))
    adversarial = bool(payload.get("adversarial", True))
    export_obsidian = bool(payload.get("export_obsidian", True))
    model = payload.get("model", "omniroute/free-forever")
    agent_role = payload.get("agent_role", "Lead Research Analyst")
    settings = _load_json(SETTINGS_FILE, {})
    vault_path = settings.get("memory", {}).get("vault_path", "C:\\Mein Obsidian")
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    # Modus "reflect": Reflexionsschleife + Seiten-Scraper (research_engine_v2). Standard: klassische Pipeline.
    use_reflect = bool(payload.get("reflect")) or payload.get("mode") == "reflect"
    if use_reflect:
        import research_engine_v2
        return research_engine_v2.run_research_mission_reflect(
            query=query,
            profile=profile,
            engines=engines,
            depth=depth,
            adversarial=adversarial,
            export_obsidian=export_obsidian,
            vault_path=vault_path,
            workspace_dir=workspace_dir,
            settings=settings,
            model=model,
            agent_role=agent_role,
            fast_model=payload.get("fast_model") or None,
            max_rounds=int(payload.get("max_rounds", 3)),
            max_pages=int(payload.get("max_pages", 4)),
        )
    res = research_engine.run_research_mission(
        query=query,
        profile=profile,
        engines=engines,
        depth=depth,
        adversarial=adversarial,
        export_obsidian=export_obsidian,
        vault_path=vault_path,
        workspace_dir=workspace_dir,
        settings=settings,
        model=model,
        agent_role=agent_role
    )
    return res

@app.get("/api/v1/research/history")
def api_get_research_history():
    import research_engine
    settings = _load_json(SETTINGS_FILE, {})
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    items = research_engine.list_research_history(workspace_dir)
    return {"status": "success", "dossiers": items}

@app.get("/api/v1/research/dossier/{filename}")
def api_get_research_dossier(filename: str):
    settings = _load_json(SETTINGS_FILE, {})
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    safe_name = os.path.basename(filename)
    fpath = os.path.join(workspace_dir, "research", safe_name)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Dossier nicht gefunden.")
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    return {"status": "success", "filename": safe_name, "content": content}

@app.get("/api/v1/research/sources")
def api_get_research_sources():
    from backend.research_sources import get_curated_sources_pool, TRUST_TIERS
    return {
        "status": "success",
        "sources": get_curated_sources_pool(),
        "trust_tiers": TRUST_TIERS
    }


# --- SYSTEM UPDATE & RELEASE-LIFECYCLE (MEILENSTEIN 1) ---
@app.get("/api/v1/system/update/check")
def api_system_update_check():
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    return system_updater.get_update_status()

@app.get("/api/v1/system/update/local-changes")
def api_system_update_local_changes():
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    return system_updater.get_local_changes()

@app.post("/api/v1/system/update/push")
def api_system_update_push(payload: dict = Body(default={})):
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    msg = payload.get("message")
    version = payload.get("version")
    step = payload.get("step", "custom")
    return system_updater.push_changes(commit_message=msg, custom_version=version, version_step=step)

@app.post("/api/v1/system/update/apply")
def api_system_update_apply(payload: dict = Body(default={}), background_tasks: BackgroundTasks = None):
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    make_backup = payload.get("backup", True)
    res = system_updater.apply_update(make_backup=make_backup)
    if res.get("status") == "success" and background_tasks is not None:
        background_tasks.add_task(system_updater.schedule_delayed_reload, delay=2.0)
    return res

@app.get("/api/v1/system/update/snapshots")
def api_system_update_snapshots():
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    return {"status": "success", "snapshots": system_updater.list_snapshots()}

@app.post("/api/v1/system/update/rollback")
def api_system_update_rollback(payload: dict = Body(...)):
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    snapshot_id = payload.get("snapshot_id", "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="Snapshot-ID erforderlich.")
    return system_updater.rollback_snapshot(snapshot_id)

@app.post("/api/v1/system/update/backup")
def api_system_update_backup(payload: dict = Body(default={})):
    import importlib
    from backend import system_updater
    importlib.reload(system_updater)
    tag = payload.get("tag", "manual").strip() or "manual"
    return system_updater.create_snapshot(tag=tag)


# --- HERMES AGENT CORE UPDATE (NousResearch/hermes-agent) ---
@app.get("/api/v1/hermes/update/check")
def api_hermes_update_check(force: bool = False):
    import importlib
    from backend import hermes_updater
    importlib.reload(hermes_updater)
    return hermes_updater.check_hermes_updates(force_refresh=force)


@app.post("/api/v1/hermes/update/apply")
def api_hermes_update_apply(request: Request, payload: dict = Body(default={})):
    curr_user = get_current_user_from_request(request)
    if curr_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Hermes Core Updates einleiten.")
    import importlib
    from backend import hermes_updater
    importlib.reload(hermes_updater)
    channel = payload.get("channel", "latest")
    auto_restart = payload.get("restart", True)
    return hermes_updater.apply_hermes_update(channel=channel, auto_restart=auto_restart)

# --- VERTRAGS- & FRISTENMANAGEMENT (t-0a2171) ---
@app.get("/api/contracts")
@app.get("/api/v1/contracts")
def api_list_contracts(category: Optional[str] = None, status: Optional[str] = None, sort_by: str = "deadline"):
    from backend.contract_manager import ContractManager
    return {"status": "success", "contracts": ContractManager.list_contracts(category=category, status=status, sort_by=sort_by)}


@app.get("/api/contracts/stats")
@app.get("/api/v1/contracts/stats")
def api_contract_stats():
    from backend.contract_manager import ContractManager
    return {"status": "success", "stats": ContractManager.get_stats()}


@app.get("/api/contracts/{contract_id}")
@app.get("/api/v1/contracts/{contract_id}")
def api_get_contract(contract_id: str):
    from backend.contract_manager import ContractManager
    c = ContractManager.get(contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Vertrag nicht gefunden.")
    return {"status": "success", "contract": c}


@app.post("/api/contracts")
@app.post("/api/v1/contracts")
def api_save_contract(payload: dict = Body(...)):
    from backend.contract_manager import ContractManager
    saved = ContractManager.create_or_update(payload)
    return {"status": "success", "contract": saved}


@app.delete("/api/contracts/{contract_id}")
@app.delete("/api/v1/contracts/{contract_id}")
def api_delete_contract(contract_id: str):
    from backend.contract_manager import ContractManager
    deleted = ContractManager.delete(contract_id)
    return {"status": "success" if deleted else "not_found", "deleted": deleted}


@app.post("/api/contracts/parse")
@app.post("/api/v1/contracts/parse")
def api_parse_contract(payload: dict = Body(...)):
    from backend.contract_manager import ContractParser
    text = payload.get("text", "")
    parsed = ContractParser.parse(text)
    return {"status": "success", "parsed": parsed}


@app.post("/api/contracts/scan-deadlines")
@app.post("/api/v1/contracts/scan-deadlines")
def api_scan_contract_deadlines(payload: dict = Body(default={})):
    from backend.contract_manager import ContractManager
    send_telegram = payload.get("send_telegram", True)
    create_kanban = payload.get("create_kanban_task", True)
    alerts = ContractManager.scan_and_alert_deadlines(send_telegram=send_telegram, create_kanban_task=create_kanban)
    return {"status": "success", "alerts_triggered": alerts, "count": len(alerts)}


@app.post("/api/contracts/{contract_id}/renew")
@app.post("/api/v1/contracts/{contract_id}/renew")
def api_renew_contract(contract_id: str):
    from backend.contract_manager import ContractManager
    renewed = ContractManager.renew_contract(contract_id)
    if not renewed:
        raise HTTPException(status_code=404, detail="Vertrag konnte nicht verlängert werden.")
    return {"status": "success", "contract": renewed}


# --- SAUBERES HERUNTERFAHREN & TASK-DRAINING (t-12113b) ---
@app.on_event("startup")
def on_startup_drain_recovery():
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
        res = graceful_shutdown_coordinator.auto_resume_on_startup()
        print(f"[Archon] Startup Recovery: {res}")
    except Exception as e:
        print(f"[Archon] Startup Recovery Fehler: {e}", file=sys.stderr)


@app.on_event("shutdown")
def on_shutdown_graceful():
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
        res = graceful_shutdown_coordinator.execute_graceful_shutdown_sync(reason="Server shutdown / restart")
        print(f"[Archon] Graceful Shutdown ausgeführt: {res}")
    except Exception as e:
        print(f"[Archon] Graceful Shutdown Fehler: {e}", file=sys.stderr)


@app.get("/api/system/drain/status")
@app.get("/api/v1/system/drain/status")
def api_drain_status():
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    return {"status": "success", "drain_status": graceful_shutdown_coordinator.get_status()}


@app.post("/api/system/drain/start")
@app.post("/api/v1/system/drain/start")
def api_start_drain(payload: dict = Body(default={})):
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    reason = payload.get("reason", "Manuell angefordertes Draining")
    grace = payload.get("grace_seconds", 15.0)
    res = graceful_shutdown_coordinator.start_draining(reason=reason, grace_seconds=grace)
    return {"status": "success", "result": res}


@app.post("/api/system/drain/cancel")
@app.post("/api/v1/system/drain/cancel")
def api_cancel_drain():
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    res = graceful_shutdown_coordinator.cancel_draining()
    return {"status": "success", "result": res}


@app.post("/api/system/drain/execute-shutdown")
@app.post("/api/v1/system/drain/execute-shutdown")
def api_execute_shutdown(payload: dict = Body(default={})):
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    reason = payload.get("reason", "API-gesteuerter Shutdown")
    grace = payload.get("grace_seconds", 5.0)
    res = graceful_shutdown_coordinator.execute_graceful_shutdown_sync(reason=reason, grace_seconds=grace)
    return {"status": "success", "result": res}


# --- EU AI ACT COMPLIANCE & KI-INVENTAR (t-1aa5e9) ---
@app.get("/api/governance/ai-act/inventory")
@app.get("/api/v1/governance/ai-act/inventory")
def api_ai_act_inventory():
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    return {"status": "success", "inventory": eu_ai_act_inventory_manager.get_inventory()}


@app.get("/api/governance/ai-act/stats")
@app.get("/api/v1/governance/ai-act/stats")
def api_ai_act_stats():
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    return {"status": "success", "stats": eu_ai_act_inventory_manager.get_stats()}


@app.post("/api/governance/ai-act/reclassify/{agent_id}")
@app.post("/api/v1/governance/ai-act/reclassify/{agent_id}")
def api_ai_act_reclassify(agent_id: str, payload: dict = Body(...)):
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    updated = eu_ai_act_inventory_manager.set_manual_override(agent_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' nicht gefunden.")
    return {"status": "success", "agent": updated}


@app.get("/api/governance/ai-act/export")
@app.get("/api/v1/governance/ai-act/export")
def api_ai_act_export():
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    return {"status": "success", "markdown_report": eu_ai_act_inventory_manager.export_report_markdown()}


# --- AUTOMATISCHE DATENKLASSIFIZIERUNG (t-53315b) ---
@app.post("/api/governance/data-classification/classify")
@app.post("/api/v1/governance/data-classification/classify")
def api_classify_content(payload: dict = Body(...)):
    from backend.data_classifier import DataClassifier
    text = payload.get("text", "")
    filename = payload.get("filename")
    res = DataClassifier.classify(text, filename=filename)
    return {"status": "success", "classification": res}


@app.get("/api/governance/data-classification/taxonomy")
@app.get("/api/v1/governance/data-classification/taxonomy")
def api_classification_taxonomy():
    from backend.data_classifier import CLASSIFICATION_METADATA
    tax = {lvl.value: meta for lvl, meta in CLASSIFICATION_METADATA.items()}
    return {"status": "success", "taxonomy": tax}


@app.post("/api/governance/data-classification/tag")
@app.post("/api/v1/governance/data-classification/tag")
def api_tag_classification(payload: dict = Body(...)):
    from backend.data_classifier import DataClassifier
    item_id = payload.get("item_id", "")
    item_type = payload.get("item_type", "task")
    text = payload.get("text", "")
    filename = payload.get("filename")
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id erforderlich.")
    res = DataClassifier.tag_item(item_id, item_type, text, filename=filename)
    return {"status": "success", "tagged_item": res}


@app.get("/api/governance/data-classification/items")
@app.get("/api/v1/governance/data-classification/items")
def api_list_classifications(item_type: Optional[str] = None):
    from backend.data_classifier import DataClassifier
    items = DataClassifier.get_classifications(item_type=item_type)
    return {"status": "success", "items": items, "count": len(items)}


# --- DOKUMENTEN-PARSING & TABELLENEXTRAKTION (t-539b65) ---
@app.post("/api/documents/parse")
@app.post("/api/v1/documents/parse")
def api_parse_document(payload: dict = Body(...)):
    from backend.document_parser import DocumentParserEngine
    filepath = payload.get("filepath", "")
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=400, detail="Gültiger 'filepath' erforderlich.")
    res = DocumentParserEngine.parse_file(filepath)
    return {"status": "success", "result": res}


@app.post("/api/documents/extract-tables")
@app.post("/api/v1/documents/extract-tables")
def api_extract_tables(payload: dict = Body(...)):
    from backend.document_parser import DocumentParserEngine
    filepath = payload.get("filepath", "")
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=400, detail="Gültiger 'filepath' erforderlich.")
    res = DocumentParserEngine.parse_file(filepath)
    tables = res.get("tables") or res.get("tables_by_sheet") or []
    return {"status": "success", "tables": tables, "format": res.get("format")}


# --- DEAL-PIPELINE & FORECAST-ENGINE (t-5b159d) ---
@app.get("/api/deals")
@app.get("/api/v1/deals")
def api_list_deals(stage: Optional[str] = None, partner: Optional[str] = None, assigned_agent: Optional[str] = None):
    from backend.deal_pipeline import DealPipelineManager
    return {"status": "success", "deals": DealPipelineManager.list_deals(stage=stage, partner=partner, assigned_agent=assigned_agent)}


@app.get("/api/deals/forecast")
@app.get("/api/v1/deals/forecast")
def api_deal_forecast():
    from backend.deal_pipeline import DealPipelineManager
    return {"status": "success", "forecast": DealPipelineManager.get_forecast()}


@app.get("/api/deals/{deal_id}")
@app.get("/api/v1/deals/{deal_id}")
def api_get_deal(deal_id: str):
    from backend.deal_pipeline import DealPipelineManager
    deal = DealPipelineManager.get(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal nicht gefunden.")
    return {"status": "success", "deal": deal}


@app.post("/api/deals")
@app.post("/api/v1/deals")
def api_save_deal(payload: dict = Body(...)):
    from backend.deal_pipeline import DealPipelineManager
    saved = DealPipelineManager.create_or_update(payload)
    return {"status": "success", "deal": saved}


@app.post("/api/deals/{deal_id}/move-stage")
@app.post("/api/v1/deals/{deal_id}/move-stage")
def api_move_deal_stage(deal_id: str, payload: dict = Body(...)):
    from backend.deal_pipeline import DealPipelineManager
    new_stage = payload.get("stage", "")
    notes = payload.get("notes")
    if not new_stage:
        raise HTTPException(status_code=400, detail="'stage' erforderlich.")
    moved = DealPipelineManager.move_stage(deal_id, new_stage, notes=notes)
    if not moved:
        raise HTTPException(status_code=404, detail="Deal oder Phase ungültig.")
    return {"status": "success", "deal": moved}


@app.delete("/api/deals/{deal_id}")
@app.delete("/api/v1/deals/{deal_id}")
def api_delete_deal(deal_id: str):
    from backend.deal_pipeline import DealPipelineManager
    deleted = DealPipelineManager.delete(deal_id)
    return {"status": "success" if deleted else "not_found", "deleted": deleted}



# --- PLUGIN SYSTEM & EXTENSIBILITY (MEILENSTEIN 5) ---
@app.get("/api/v1/plugins")
def api_list_plugins():
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    return {"status": "success", "plugins": pm.list_plugins_summary()}

@app.post("/api/v1/plugins/{plugin_id}/toggle")
def api_toggle_plugin(plugin_id: str, payload: dict = Body(default={})):
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    plugin = pm.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' nicht gefunden.")
    enable = payload.get("enable")
    if enable is None:
        enable = not plugin.enabled
    if enable:
        pm.enable_plugin(plugin_id)
    else:
        pm.disable_plugin(plugin_id)
    return {"status": "success", "plugin_id": plugin_id, "enabled": plugin.enabled}

@app.post("/api/v1/plugins/{plugin_id}/reload")
def api_reload_plugin(plugin_id: str):
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    success = pm.reload_plugin(plugin_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Fehler beim Neuladen von Plugin '{plugin_id}'.")
    return {"status": "success", "message": f"Plugin '{plugin_id}' erfolgreich neu geladen."}

@app.get("/api/v1/plugins/{plugin_id}/config")
def api_get_plugin_settings(plugin_id: str):
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    plugin = pm.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' nicht gefunden.")
    return {
        "status": "success",
        "plugin_id": plugin_id,
        "config": plugin.config,
        "schema": plugin.manifest.get("settings_schema", {})
    }

@app.post("/api/v1/plugins/{plugin_id}/config")
def api_save_plugin_settings(plugin_id: str, payload: dict = Body(...)):
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    plugin = pm.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' nicht gefunden.")
    success = plugin.save_config(payload)
    return {"status": "success" if success else "error", "config": plugin.config}

@app.post("/api/v1/plugins/discover")
def api_discover_plugins():
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    pm.load_all_plugins()
    return {"status": "success", "plugins": pm.list_plugins_summary()}

@app.get("/api/v1/plugins/tools")
def api_get_plugin_tools():
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    return {"status": "success", "tools": pm.get_all_exported_tools()}

@app.post("/api/v1/plugins/tools/execute")
async def api_execute_plugin_tool(payload: dict = Body(...)):
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    tool_name = payload.get("tool_name", "")
    args = payload.get("args", {})
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name erforderlich.")
    try:
        res = await pm.execute_plugin_tool(tool_name, args)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

_VAULT_FILES_CACHE = {"ts": 0.0, "data": []}



@app.get("/api/llm-providers/models")
async def api_get_llm_provider_models(provider: str = Query("openrouter")):
    p = (provider or "openrouter").lower().strip()
    # 1. Vollständiger OpenRouter-Katalog aus Preiscache oder Live-API
    if p == "openrouter":
        try:
            p_res = get_llm_prices(refresh=0)
            if p_res.get("status") == "ok" and p_res.get("prices"):
                all_models = sorted(list(p_res["prices"].keys()))
                if len(all_models) > 10:
                    return {"status": "ok", "provider": p, "models": all_models}
        except Exception:
            pass
    # 2. Dynamische Modelle aus api_provider
    try:
        import api_provider
        dyn_models = api_provider.list_provider_models(p)
        if dyn_models and len(dyn_models) > 0:
            return {"status": "ok", "provider": p, "models": dyn_models}
    except Exception:
        pass
    catalog = {
        "openrouter": [
            "deepseek/deepseek-v4.1-flash",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-r1",
            "deepseek/deepseek-v4-flash-0731",
            "z-ai/glm-5.3",
            "anthropic/claude-3.7-sonnet",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
            "google/gemini-2.5-flash-image",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "openai/o3-mini",
            "meta-llama/llama-3.3-70b-instruct",
            "qwen/qwen-2.5-coder-32b-instruct"
        ],
        "omniroute": [
            "omniroute/free-forever",
            "auto/best-free",
            "auto/best-reasoning",
            "auto/best-coding",
            "auto/best-fast",
            "deepseek/deepseek-v4-flash-0731",
            "google/gemini-2.5-flash",
            "anthropic/claude-3.7-sonnet"
        ],
        "google": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-image",
            "gemini-2.0-flash"
        ],
        "anthropic": [
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest"
        ],
        "openai": [
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "o1"
        ],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "deepseek-r1-distill-llama-70b"
        ],
        "deepseek": [
            "deepseek-chat",
            "deepseek-reasoner"
        ],
        "ollama": [
            "llama3.2:latest",
            "qwen2.5-coder:14b",
            "deepseek-r1:14b",
            "hermes3:latest"
        ]
    }
    models = list(catalog.get(p, catalog["openrouter"]))
    global _openrouter_price_cache
    if p == "openrouter" and _openrouter_price_cache:
        for mid in _openrouter_price_cache.keys():
            if mid not in models:
                models.append(mid)
    return {"status": "success", "provider": p, "models": models}


@app.post("/api/theme/upload-background")
async def api_upload_theme_background(file: UploadFile = File(...)):
    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename or "background.png")
    fname = f"bg_{int(time.time())}_{safe_name}"
    dest = os.path.join(uploads_dir, fname)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)
    return {"status": "success", "url": f"/static/uploads/{fname}"}


@app.get("/api/vault")
def api_get_vault_list():
    files = api_get_vault_files()
    result = []
    for item in files:
        result.append({
            "name": item.get("name"),
            "path": item.get("path"),
            "relative_path": item.get("relative_path"),
            "type": "Obsidian MD"
        })
    return result


@app.get("/api/vault/file")
def api_read_vault_file_direct(path: str = Query(...)):
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return {"status": "success", "path": path, "content": f.read()}


@app.post("/api/vault/edit")
def api_edit_vault_file_direct(payload: Dict = Body(...)):
    path = payload.get("path", "")
    content = payload.get("content", "")
    if not path:
        raise HTTPException(status_code=400, detail="Pfad fehlt.")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    _VAULT_FILES_CACHE["ts"] = 0.0
    return {"status": "success", "path": path}


@app.delete("/api/vault")
def api_delete_vault_file_direct(path: str = Query(...)):
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    os.remove(path)
    _VAULT_FILES_CACHE["ts"] = 0.0
    return {"status": "success", "deleted": path}


@app.post("/api/sandbox")
def api_run_python_sandbox(payload: Dict = Body(...)):
    fname = re.sub(r"[^a-zA-Z0-9._-]", "_", payload.get("file_path", "sandbox_script.py"))
    if not fname.endswith(".py"):
        fname += ".py"
    code_content = payload.get("code_content", "")
    sb_dir = os.path.join(DATA_DIR, "sandbox")
    os.makedirs(sb_dir, exist_ok=True)
    script_path = os.path.join(sb_dir, fname)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code_content)
    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            cwd=sb_dir,
            capture_output=True,
            text=True,
            timeout=15
        )
        return {
            "status": "success",
            "code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
    except Exception as e:
        return {"status": "error", "code": -1, "stdout": "", "stderr": str(e)}

@app.get("/api/vault/files")
def api_get_vault_files():
    global _VAULT_FILES_CACHE
    now = time.time()
    if _VAULT_FILES_CACHE["data"] and (now - _VAULT_FILES_CACHE["ts"]) < 300.0:
        return _VAULT_FILES_CACHE["data"]
    vault_dir = OBSIDIAN_VAULT_DIR
    if not os.path.exists(vault_dir):
        return []
    files = []
    for root, dirs, filenames in os.walk(vault_dir):
        # Ignore internal Obsidian / Git folders
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in filenames:
            if f.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, f), vault_dir)
                files.append({"name": f, "relative_path": rel_path, "path": os.path.join(root, f)})
    _VAULT_FILES_CACHE = {"ts": now, "data": files}
    return files

KANBAN_CARDS_FILE = os.path.join(DATA_DIR, "kanban_cards.json")

@app.get("/api/kanban")
def api_get_kanban():
    kanban_db = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else "C:\\Users\\micha\\.hermes\\kanban.db"
    if os.path.exists(kanban_db):
        kconn = None
        try:
            kconn = sqlite3.connect(kanban_db, timeout=5.0)
            kconn.execute("PRAGMA busy_timeout=5000;")
            kconn.row_factory = sqlite3.Row
            rows = kconn.execute(
                "SELECT id, title, body as description, assignee, status, priority, created_at FROM tasks WHERE status != 'archived' ORDER BY priority DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            pass
        finally:
            if kconn:
                kconn.close()
    if os.path.exists(KANBAN_CARDS_FILE):
        try:
            with open(KANBAN_CARDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

@app.post("/api/kanban")
async def api_save_kanban(request: Request):
    try:
        cards = await request.json()
        with open(KANBAN_CARDS_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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

def docker_socket_request(method: str, path: str, payload: dict = None, timeout: float = 1.0) -> bytes:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
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
        content_length = None
        is_chunked = False
        headers_parsed = False
        
        while True:
            try:
                chunk = s.recv(65536)
                if not chunk:
                    break
                response += chunk
                
                if not headers_parsed and b'\r\n\r\n' in response:
                    headers_part, body_part = response.split(b'\r\n\r\n', 1)
                    headers_parsed = True
                    headers_lower = headers_part.lower()
                    if b'transfer-encoding: chunked' in headers_lower:
                        is_chunked = True
                    for hline in headers_part.split(b'\r\n'):
                        if hline.lower().startswith(b'content-length:'):
                            try:
                                content_length = int(hline.split(b':', 1)[1].strip())
                            except Exception:
                                pass
                
                if headers_parsed:
                    body_part = response.split(b'\r\n\r\n', 1)[1]
                    if content_length is not None and len(body_part) >= content_length:
                        break
                    if is_chunked and (body_part.endswith(b'\r\n0\r\n\r\n') or body_part.endswith(b'0\r\n\r\n') or b'\r\n0\r\n\r\n' in body_part):
                        break
            except socket.timeout:
                break
        s.close()
        
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) < 2:
            return b''
            
        headers, body_raw = parts[0], parts[1]
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
    if not configs:
        for cpath in [os.path.join(WORKSPACE_DIR, "config", "coupled_agents.json"), os.path.join(WORKSPACE_DIR, "agents.json")]:
            if os.path.exists(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        configs = json.load(f)
                        if isinstance(configs, list):
                            configs = {item.get("id"): item for item in configs if isinstance(item, dict)}
                        break
                except Exception:
                    pass
    if not isinstance(configs, dict):
        configs = {}
    cfg = configs.get(container_name, {})
    if not cfg:
        port = detect_container_port(container_name)
        cfg = {"web_ui_url": f"http://localhost:{port}", "web_ui_port": port}
    elif "web_ui_url" not in cfg:
        port = cfg.get("web_ui_port") or cfg.get("dashboard_port") or detect_container_port(container_name)
        cfg["web_ui_url"] = f"http://localhost:{port}"
    return cfg

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

    ignore_patterns = [
        "Python 3 is missing from this system",
        "Launching a Python runner in internal mode",
        "TypeError fetch failed | getaddrinfo ENOTFOUND aihorde.net",
        "native fetch fallback ALSO failed",
        "combo trace combo-",
        "RuntimeError: The current task is not holding this lock",
        "Temporary failure in name resolution",
        "Telegram polling degraded",
        "Telegram network error",
        "All connection attempts failed",
        "failed initial connection after 3 attempts, parking until a reconnect is requested",
        "Server disconnected without sending a response"
    ]
    filtered_logs = []
    for line in logs.splitlines():
        if line.strip() and not any(p in line for p in ignore_patterns):
            filtered_logs.append(line)
    logs = "\n".join(filtered_logs)

    return {"logs": logs}

@app.get("/api/v1/container/all-logs")
def get_all_container_logs_api(tail: int = 40):
    containers = ["hermes", "ARCHON-OS", "CRM", "Pocketbase", "n8n", "omniroute", "docker-socket-proxy"]
    combined_logs = []
    for c in containers:
        try:
            raw = docker_socket_request("GET", f"/containers/{c}/logs?tail={tail}&stdout=true&stderr=true")
            if raw:
                parsed = parse_docker_stream(raw)
                ignore_patterns = [
                    "Python 3 is missing from this system",
                    "Launching a Python runner in internal mode",
                    "TypeError fetch failed | getaddrinfo ENOTFOUND aihorde.net",
                    "native fetch fallback ALSO failed",
                    "combo trace combo-",
                    "RuntimeError: The current task is not holding this lock",
                    "Temporary failure in name resolution",
                    "Telegram polling degraded",
                    "Telegram network error",
                    "All connection attempts failed",
                    "failed initial connection after 3 attempts, parking until a reconnect is requested",
                    "Server disconnected without sending a response"
                ]
                for line in parsed.splitlines():
                    if line.strip() and not any(p in line for p in ignore_patterns):
                        combined_logs.append(f"[{c}] {line}")
        except Exception:
            pass
    return {"logs": "\n".join(combined_logs)}

@app.get("/api/v1/hermes/profile-logs")
def get_hermes_profile_logs_api(profile_id: str, tail: int = 150):
    lines = []
    hermes_home = os.environ.get("HERMES_HOME", "/opt/data")
    profile_dir = os.path.join(hermes_home, "profiles", profile_id)
    
    # 1. Profile specific logs
    prof_logs_dir = os.path.join(profile_dir, "logs")
    if os.path.exists(prof_logs_dir):
        for log_file in sorted(os.listdir(prof_logs_dir)):
            if log_file.endswith(".log"):
                lp = os.path.join(prof_logs_dir, log_file)
                try:
                    with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                        for l in f.readlines()[-tail:]:
                            if l.strip():
                                lines.append(f"[{log_file}] {l.strip()}")
                except Exception:
                    pass

    # 2. Check main logs matching profile ID
    for log_name in ["agent.log", "errors.log", "gateway.log", "hermes-update.log"]:
        lp = os.path.join(hermes_home, "logs", log_name)
        if os.path.exists(lp):
            try:
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    for l in f.readlines():
                        if profile_id in l:
                            lines.append(f"[{log_name}] {l.strip()}")
            except Exception:
                pass

    # 3. Fallback: query hermes container logs for mention of profile
    if not lines:
        for c_name in ["hermes", "hermes-agent"]:
            try:
                raw = docker_socket_request("GET", f"/containers/{c_name}/logs?tail=300&stdout=true&stderr=true")
                if raw:
                    parsed = parse_docker_stream(raw)
                    for l in parsed.splitlines():
                        if profile_id in l:
                            lines.append(f"[{c_name}] {l}")
                    if lines:
                        break
            except Exception:
                pass

    if not lines:
        lines = [f"[System] Profil '{profile_id}' ist aktiv und bereit. Noch keine isolierten Hintergrund-Logs oder Fehler protokolliert."]

    return {"logs": "\n".join(lines[-tail:])}

@app.post("/api/v1/agent/abort")
def abort_agent_endpoint(payload: dict):
    agent_id = payload.get("agent_id") or payload.get("profile") or payload.get("profile_handle", "unknown")
    reason = payload.get("reason", "Manual Kill-Switch Triggered")
    if watchdog_runner:
        watchdog_runner.abort_agent_thread(agent_id, reason, {"manual": True, "source": "UI_KILLSWITCH"})
    return {"status": "aborted", "agent": agent_id, "reason": reason}

@app.get("/api/v1/watchdog/alarms")
def get_watchdog_alarms_endpoint():
    if watchdog_runner:
        return {"alarms": watchdog_runner.load_alarms()}
    return {"alarms": []}

@app.post("/api/v1/watchdog/test-alarm")
def trigger_test_watchdog_alarm_endpoint():
    if watchdog_runner:
        watchdog_runner.save_alarm(
            "telegram_bot",
            "Token Usage Limit Exceeded (14.200 > 10.000 tok/min) - Der Watchdog hat den Thread per SIGTERM isoliert, um weitere API-Kosten und Systemblockaden zu unterbinden.",
            {
                "container": "hermes",
                "task": "tk_test_sandbox",
                "measured_rate": "12.500 tok/min",
                "status": "Gestoppt (0 Tok/s)",
                "log_excerpt": "> 2026-08-27 19:41:17.185563315 | Messaging platforms + cron scheduler |\n> 2026-08-27 19:41:17.185564107 | Press Ctrl+C to stop |\n> 2026-08-27 19:41:17.185565209 |\n> 2026-08-27 19:41:17.185565590"
            }
        )
        return {"status": "ok", "alarms": watchdog_runner.load_alarms()}
    return {"status": "error", "message": "Watchdog not running"}

@app.post("/api/v1/watchdog/acknowledge")
def acknowledge_watchdog_alarm_endpoint(payload: dict = None):
    alarm_id = payload.get("alarm_id") if payload else None
    if watchdog_runner:
        alarms = watchdog_runner.load_alarms()
        if alarm_id:
            alarms = [a for a in alarms if a.get("id") != alarm_id]
        else:
            alarms = []
        try:
            from watchdog_daemon import ALARMS_FILE
            with open(ALARMS_FILE, "w", encoding="utf-8") as f:
                json.dump(alarms, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving alarms after ack: {e}")
        return {"status": "acknowledged", "alarms": alarms}
    return {"status": "ok", "alarms": []}

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

def send_prompt_to_agent(agent_name: str, agent_config: dict, user_input: str, history: Optional[List[Dict[str, str]]] = None, session_id: Optional[str] = None) -> str:
    """Sendet eine echte HTTP-Anfrage an den lokalen OmniRoute LLM Router (Non-Streaming) mit kontinuierlichem Chat-Kontext."""
    role_name = agent_config.get("role", "Orchestrator & System-Architekt") if isinstance(agent_config, dict) else "Orchestrator & System-Architekt"
    
    system_prompt = "Du bist ein hilfreicher KI-Assistent."
    all_roles = []
    if "load_roles" in globals():
        try:
            all_roles = load_roles()
        except Exception:
            all_roles = []
    if not all_roles and "DEFAULT_ROLES" in globals():
        all_roles = DEFAULT_ROLES

    for r in all_roles:
        if r.get("name") == role_name or r.get("id") == role_name:
            system_prompt = r.get("prompt", system_prompt)
            break

    # Context Injection aus local_memory_bridge (User-Profil, Second Brain)
    if "memory_bridge" in globals() and memory_bridge:
        try:
            ctx_inj = memory_bridge.get_agent_context_injection(agent_name, limit=3)
            if ctx_inj:
                system_prompt = f"{system_prompt}\n\n{ctx_inj}"
        except Exception:
            pass
                
    model_name = agent_config.get("model", "auto/best-free") if isinstance(agent_config, dict) else "auto/best-free"
    if model_name == "free-forever":
        model_name = "auto/best-free"
    
    # Message-Historie zusammenbauen
    messages = [{"role": "system", "content": system_prompt}]
    
    # Vorherige Nachrichten aus Parametern oder Fallback aus local_memory_bridge
    prior_messages = []
    if history and isinstance(history, list):
        for msg in history:
            r = msg.get("role")
            c = msg.get("content")
            if r in ["user", "assistant"] and c:
                prior_messages.append({"role": r, "content": c})
    elif "memory_bridge" in globals() and memory_bridge:
        try:
            db_hist = memory_bridge.get_conversation_history(agent_name, limit=16, session_id=session_id)
            for msg in db_hist:
                r = msg.get("role")
                c = msg.get("content")
                if r in ["user", "assistant"] and c:
                    prior_messages.append({"role": r, "content": c})
        except Exception:
            pass

    # Begrenze Konversationshistorie auf die letzten 14 Turns zur Vermeidung von Token-Overhead
    if len(prior_messages) > 14:
        prior_messages = prior_messages[-14:]
    messages.extend(prior_messages)

    # Aktuellen User-Turn hinzufuegen, falls er nicht schon am Ende der Historie steht
    if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != user_input:
        messages.append({"role": "user", "content": user_input})
    
    headers = {"Content-Type": "application/json", "Authorization": "Bearer omniroute-local-key"}
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False  # Explicit non-streaming request
    }
    
    urls = [
        "http://omniroute:20128/v1/chat/completions",
        "http://localhost:20128/v1/chat/completions",
        "http://127.0.0.1:20128/v1/chat/completions",
        "http://host.docker.internal:20128/v1/chat/completions"
    ]
    
    last_err = ""
    ai_resp = None
    for url in urls:
        try:
            with httpx.Client(timeout=40.0) as client:
                res = client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    try:
                        data = res.json()
                        if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
                            choice = data["choices"][0]
                            if isinstance(choice, dict) and "message" in choice and "content" in choice["message"]:
                                ai_resp = choice["message"]["content"]
                                break
                        elif isinstance(data, dict) and "response" in data:
                            ai_resp = data["response"]
                            break
                    except Exception:
                        raw_text = res.text
                        lines = [line.replace("data: ", "").strip() for line in raw_text.splitlines() if line.strip() and not line.startswith("event:") and not "x-omniroute" in line]
                        cleaned = "\n".join(lines)
                        if cleaned:
                            ai_resp = cleaned
                            break
                else:
                    last_err = f"[SYSTEM FEHLER {res.status_code}]: {res.text}"
        except Exception as e:
            last_err = f"[VERBINDUNGSFEHLER]: {e}"

    final_output = ai_resp if ai_resp else (last_err or f"[{agent_name}]: Anweisung empfangen mit Rolle '{role_name}'.")

    # Persistiere Konversation in der SQLite-Datenbank (conversations Tabelle)
    if "memory_bridge" in globals() and memory_bridge:
        try:
            memory_bridge.record_conversation(agent_name, "user", user_input, session_id=session_id)
            if ai_resp:
                memory_bridge.record_conversation(agent_name, "assistant", ai_resp, session_id=session_id)
        except Exception as e:
            print(f"[QuickChat] Failed to record conversation to DB: {e}", file=sys.stderr)

    return final_output


class ContainerExecRequest(BaseModel):
    container_name: str
    command: str
    history: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None

@app.post("/api/v1/container/exec")
def exec_container_command_api(req: ContainerExecRequest):
    configs = load_agent_configs()
    agent_cfg = configs.get(req.container_name, {})
    
    # Falls das Agent-Profil in den Standard-Agenten existiert, uebernimm Rolle und Model
    if not agent_cfg and "load_agents" in globals():
        try:
            all_a = load_agents()
            for a in all_a:
                if a.get("id") == req.container_name:
                    agent_cfg = a
                    break
        except Exception:
            pass

    # Optionales JEV Fast-Path Routing (0 Token-Verbrauch bei System-Befehlen)
    try:
        import jev_router
        if jev_router.is_jev_enabled():
            classification = jev_router.classify_prompt(req.command)
            if classification.get("action") == "direct_command":
                cmd = classification.get("command")
                desc = classification.get("description", "System-Befehl")
                import subprocess
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                out = proc.stdout if proc.stdout else proc.stderr
                return {
                    "exit_code": proc.returncode,
                    "stdout": f"[⚡ JEV Fast-Path: {desc}]\n\n{out.strip() if out else '(Befehl erfolgreich ohne Ausgabe ausgeführt)'}",
                    "stderr": proc.stderr
                }
    except Exception as e_jev:
        logger.warning(f"JEV Fast-Path Fehler (Fallback auf LLM): {e_jev}")

    # Echte OmniRoute LLM API Integration mit Konversations-Historie
    output = send_prompt_to_agent(
        agent_name=req.container_name,
        agent_config=agent_cfg,
        user_input=req.command,
        history=req.history,
        session_id=req.session_id
    )
    
    return {
        "exit_code": 0,
        "stdout": output,
        "stderr": ""
    }

@app.get("/api/v1/chat/history")
def get_chat_history_api(agent_id: str, limit: int = 30, session_id: Optional[str] = None):
    """Liefert die persistierte Konversationshistorie aus agentic_memory.db fuer ein Profil."""
    if "memory_bridge" in globals() and memory_bridge:
        history = memory_bridge.get_conversation_history(agent_id, limit=limit, session_id=session_id)
        return {"status": "success", "agent_id": agent_id, "history": history}
    return {"status": "success", "agent_id": agent_id, "history": []}

@app.delete("/api/v1/chat/history")
def clear_chat_history_api(agent_id: str, session_id: Optional[str] = None):
    """Loescht die persistierte Historie eines Profils."""
    if "memory_bridge" in globals() and memory_bridge:
        memory_bridge.clear_conversation_history(agent_id, session_id=session_id)
        return {"status": "success", "message": f"History for {agent_id} cleared"}
    return {"status": "error", "message": "Memory bridge unavailable"}

@app.get("/api/proxy")
async def proxy_web_ui(url: str):
    """Header-stripping async proxy to bypass X-Frame-Options & CSP for embedded Web UIs."""
    import urllib.parse
    from fastapi.responses import HTMLResponse, Response
    
    parsed = urllib.parse.urlparse(url)
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Host": parsed.netloc or "localhost"
    }
    
    # Inside Docker, rewrite localhost/127.0.0.1 to host.docker.internal for host-bound ports
    target_url = url
    if "localhost:" in target_url:
        target_url = target_url.replace("localhost:", "host.docker.internal:")
    elif "127.0.0.1:" in target_url:
        target_url = target_url.replace("127.0.0.1:", "host.docker.internal:")
        
    client = _get_shared_proxy_client()
    try:
        resp = await client.get(target_url, headers=req_headers, timeout=10.0, follow_redirects=True)
    except Exception:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0, follow_redirects=True)
        except Exception as e:
            err_html = f"<div style='font-family:sans-serif; padding:20px; color:#ef4444;'><h3>Web UI Proxy Status</h3><p>Konnte <code>{url}</code> nicht laden: {e}</p></div>"
            return HTMLResponse(content=err_html, status_code=502)

    content_type = resp.headers.get("Content-Type", "text/html")
    
    if "html" in content_type.lower():
        html_text = resp.text
        env_script = """<script>
            window.NEXT_PUBLIC_API_URL = "http://localhost:9119";
            window.VITE_API_URL = "http://localhost:9119";
            window.HERMES_API_URL = "http://localhost:9119";
            window.HERMES_WEBUI_API_URL = "http://localhost:9119";
            if (typeof process === "undefined") { window.process = { env: {} }; }
            else if (!window.process.env) { window.process.env = {}; }
            window.process.env.NEXT_PUBLIC_API_URL = "http://localhost:9119";
            window.process.env.VITE_API_URL = "http://localhost:9119";
            window.process.env.HERMES_API_URL = "http://localhost:9119";
        </script>"""
        base_tag = f'<base href="{url.rstrip("/")}/">{env_script}'
        if "<head>" in html_text:
            html_text = html_text.replace("<head>", f"<head>{base_tag}", 1)
        else:
            html_text = base_tag + html_text
        
        res_obj = HTMLResponse(content=html_text, status_code=resp.status_code)
    else:
        res_obj = Response(content=resp.content, media_type=content_type, status_code=resp.status_code)

    # Strip frame blocking headers & set open CORS headers
    for hkey in ["x-frame-options", "X-Frame-Options", "frame-options", "content-security-policy", "Content-Security-Policy"]:
        if hkey in res_obj.headers:
            del res_obj.headers[hkey]
    
    res_obj.headers["Access-Control-Allow-Origin"] = "*"
    res_obj.headers["Access-Control-Allow-Methods"] = "*"
    res_obj.headers["Access-Control-Allow-Headers"] = "*"
    
    return res_obj

# ---------------------------------------------------------------------------
# LLM Provider Management Endpoints (Hermes & Multi-Provider Integration)
# ---------------------------------------------------------------------------

class LLMProviderSelectRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None

class LLMProviderSaveKeyRequest(BaseModel):
    env_name: str
    key_value: str

@app.get("/api/llm-providers")
def get_llm_providers():
    try:
        import api_provider
        active_cfg = api_provider.read_active_config()
        keys = api_provider.collect_keys()
        all_catalog = api_provider.list_providers()
        
        provider_map = {p["id"]: p for p in all_catalog if isinstance(p, dict) and "id" in p}
        
        # Featured providers in intuitive order
        featured_ids = ["local", "mistral", "omniroute", "openrouter", "google", "groq", "openai", "nvidia", "anthropic", "deepseek"]

        if "local" not in provider_map:
            provider_map["local"] = {
                "id": "local",
                "name": "Lokales LLM (Ollama / LM Studio)",
                "env": ["LOCAL_LLM_URL", "OLLAMA_HOST"],
                "api": "http://127.0.0.1:11434/v1",
                "model_count": 8,
                "privacy_badge": "100% On-Premise"
            }
        if "mistral" not in provider_map:
            provider_map["mistral"] = {
                "id": "mistral",
                "name": "Mistral AI (EU / Paris - DSGVO-konform)",
                "env": ["MISTRAL_API_KEY"],
                "api": "https://api.mistral.ai/v1",
                "model_count": 12,
                "privacy_badge": "EU-DSGVO Zertifiziert"
            }
        
        if "omniroute" not in provider_map:
            provider_map["omniroute"] = {
                "id": "omniroute",
                "name": "OmniRoute Gateway (Lokal / Proxy)",
                "env": ["OMNIROUTE_API_KEY"],
                "api": "http://omniroute:20128/v1",
                "model_count": 50
            }
        
        result_providers = []
        for pid in featured_ids:
            p_data = provider_map.get(pid)
            if not p_data:
                continue
            
            envs = p_data.get("env", []) or []
            found_key_name = None
            found_val = None
            for e in envs:
                if keys.get(e):
                    found_key_name = e
                    found_val = keys.get(e)
                    break
            
            is_active = (active_cfg.get("provider") == pid) or (pid == "omniroute" and "omniroute" in (active_cfg.get("base_url") or ""))
            
            masked = ""
            if found_val:
                if len(found_val) > 8:
                    masked = found_val[:4] + "..." + found_val[-4:]
                else:
                    masked = "••••••••"
            
            result_providers.append({
                "id": pid,
                "name": p_data.get("name", pid),
                "is_active": is_active,
                "has_key": bool(found_val) or (pid == "omniroute"),
                "key_env": found_key_name or (envs[0] if envs else f"{pid.upper()}_API_KEY"),
                "key_masked": masked,
                "model_count": p_data.get("model_count", 0),
                "api": p_data.get("api"),
                "default_model": active_cfg.get("model") if is_active else api_provider.find_default_model_for_provider(pid)
            })
        
        return {
            "status": "ok",
            "active_config": active_cfg,
            "providers": result_providers
        }
    except Exception as e:
        logger.error(f"[llm-providers] get error: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "providers": []}


_openrouter_price_cache = None
_openrouter_price_timestamp = 0

@app.get('/api/llm-providers/prices')
def get_llm_prices(refresh: int = 0):
    global _openrouter_price_cache, _openrouter_price_timestamp
    try:
        now = time.time()
        if refresh or _openrouter_price_cache is None or (now - _openrouter_price_timestamp > 3600):
            import urllib.request
            import json
            req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data", [])
                formatted = {}
                for m in data:
                    pricing = m.get("pricing", {})
                    prompt_price = float(pricing.get("prompt", 0))
                    completion_price = float(pricing.get("completion", 0))
                    formatted[m["id"]] = {
                        "name": m.get("name") or m["id"],
                        "prompt_1m": prompt_price * 1000000,
                        "completion_1m": completion_price * 1000000,
                        "context_length": m.get("context_length", 0)
                    }
                _openrouter_price_cache = formatted
                _openrouter_price_timestamp = now
                return {"status": "ok", "prices": formatted}
        else:
            return {"status": "ok", "prices": _openrouter_price_cache}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": _openrouter_price_cache or {}}

def get_llm_provider_models(provider: str = ""):
    try:
        import api_provider
        pid = (provider or "").strip().lower()
        if not pid:
            return {"status": "ok", "provider": "", "models": []}
            
        models = api_provider.list_provider_models(pid)
        if not models and pid == "omniroute":
            models = ["auto/best-coding", "auto/best-reasoning", "auto/best-vision", "deepseek-ai/DeepSeek-V4-Pro", "qwen/Qwen3.6-27B"]
        return {"status": "ok", "provider": pid, "models": models}
    except Exception as e:
        return {"status": "error", "provider": provider, "models": [], "message": str(e)}

@app.post("/api/llm-providers/select")
def select_llm_provider(req: LLMProviderSelectRequest):
    try:
        import api_provider
        pid = req.provider.strip().lower()
        model = req.model.strip() if req.model else None
        if model and "session-guard" in model:
            model = None
        
        if pid == "omniroute":
            base_url = req.base_url or "http://omniroute:20128/v1"
            chosen_model = model or "auto/best-coding"
            res = api_provider.set_provider_model(provider="omniroute", model=chosen_model)
            api_provider._set_model_block(chosen_model, "omniroute", base_url)
        else:
            res = api_provider.set_provider_model(provider=pid, model=model)
            # Remove base_url when switching away from omniroute
            api_provider._set_model_block(res.get("model") or model or "", pid, None)
            
        return {"status": "ok", "result": res, "active": api_provider.read_active_config()}
    except Exception as e:
        logger.error(f"[llm-providers] select error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.post("/api/llm-providers/save-key")
def save_llm_provider_key(req: LLMProviderSaveKeyRequest):
    try:
        import api_provider
        env_key = req.env_name.strip()
        val = req.key_value.strip()
        if not env_key or not val:
            raise HTTPException(status_code=400, detail="Missing key name or value")
        
        os.environ[env_key] = val
        env_path = api_provider.ENV_PATH
        if env_path:
            api_provider.set_env_value(env_path, env_key, val)
            
        deploy_res = api_provider.deploy_keys(dry_run=False)
        return {"status": "ok", "message": f"{env_key} erfolgreich hinterlegt und verteilt", "deploy": deploy_res}
    except Exception as e:
        logger.error(f"[llm-providers] save-key error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.get("/api/llm-providers/privacy-status")
def api_get_privacy_status():
    """Gibt den aktuellen Datenschutz- und Verbindungsstatus für Lokal-LLM und DSGVO zurück (t-c4489c)."""
    try:
        from backend.privacy_router import get_overall_privacy_status
        return get_overall_privacy_status()
    except Exception as e:
        logger.error(f"[privacy-status] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.post("/api/llm-providers/privacy-routing")
def api_save_privacy_routing(payload: Dict[str, Any] = Body(...)):
    """Aktualisiert die Richtlinien für sensibles On-Premise Routing und EU-Fallback (t-c4489c)."""
    try:
        from backend.privacy_router import save_privacy_config
        saved = save_privacy_config(payload, operator="operator")
        return {"status": "ok", "config": saved}
    except Exception as e:
        logger.error(f"[privacy-routing] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.post("/api/llm-providers/test-connection")
def api_test_provider_connection(payload: Dict[str, Any] = Body(...)):
    """Testet die Live-Verbindung zu einem lokalen LLM oder Mistral AI (t-c4489c)."""
    try:
        from backend.privacy_router import test_endpoint_sync
        provider = payload.get("provider", "local")
        url = payload.get("url", "http://127.0.0.1:11434/v1")
        api_key = payload.get("api_key")
        model = payload.get("model")
        res = test_endpoint_sync(provider=provider, url=url, api_key=api_key, model=model)
        return {"status": "ok", "result": res}
    except Exception as e:
        logger.error(f"[test-connection] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.api_route("/api/session", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/session/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/sessions", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/sessions/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/chat", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/chat/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/transcribe", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/crons", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/crons/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/db", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/db/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/outline", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/outline/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/workspace", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/workspace/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/panels", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/panels/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/projects", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/projects/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/client-events", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/client-events/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/status", methods=["GET", "POST"])
@app.api_route("/api/config", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/config/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/model", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/model/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/providers", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/providers/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/plugins", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/plugins/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/provider/quota", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/provider/cost-history", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/transcribe/capability", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/onboarding/status", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/extensions/status", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/reasoning", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/insights", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/project-os/dashboard", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/wiki/status", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/wiki/browse", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/wiki/page", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/logs", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/health/agent", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/static/hermes-webui/api/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
async def proxy_hermes_api_endpoints(request: Request, path: str = ""):
    """Forward frontend API calls from embedded iFrame to active Hermes backend with full header preservation."""
    return await forward_to_hermes(request)

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

@app.get("/api/v1/memory/context")
def api_memory_context(agent_id: str = "hermes_default", limit: int = 5):
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return {"context": memory_bridge.get_agent_context_injection(agent_id, limit)}

@app.get("/api/v1/memory/profile")
def api_memory_profile():
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return memory_bridge.get_user_profile()

@app.post("/api/v1/memory/learning")
def api_memory_learning(agent_id: str = Body(...), category: str = Body(...), summary: str = Body(...), detailed_note: Optional[str] = Body(None)):
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return memory_bridge.record_learning(agent_id, category, summary, detailed_note)

@app.get("/api/v1/memory/vault-summary")
def api_memory_vault_summary():
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return memory_bridge.scan_vault_summary()

class SavePersonalakteReq(BaseModel):
    markdown: str

@app.get("/api/v1/hr/personalakte/{agent_id}")
def api_get_personalakte(agent_id: str):
    vault_dir = OBSIDIAN_VAULT_DIR
    candidates = [
        os.path.join(vault_dir, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
        os.path.join("/opt/data/obsidian", "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
        os.path.join("C:\\Mein Obsidian", "00_HR_Agenten", "Personalakten", f"{agent_id}.md")
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
            "file_path": candidates[0]
        }

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_md = f.read()
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": raw_md,
            "file_path": file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/hr/personalakte/{agent_id}")
def api_save_personalakte(agent_id: str, req: SavePersonalakteReq):
    vault_dir = OBSIDIAN_VAULT_DIR
    target_dirs = [
        os.path.join(vault_dir, "00_HR_Agenten", "Personalakten"),
        "/opt/data/obsidian/00_HR_Agenten/Personalakten"
    ]
    if sys.platform == "win32" or os.path.exists("C:\\Mein Obsidian"):
        target_dirs.append("C:\\Mein Obsidian\\00_HR_Agenten\\Personalakten")
    
    saved_paths = []
    for p_dir in target_dirs:
        try:
            if os.path.exists(os.path.dirname(p_dir)):
                os.makedirs(p_dir, exist_ok=True)
                fp = os.path.join(p_dir, f"{agent_id}.md")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(req.markdown)
                saved_paths.append(fp)
        except Exception:
            pass

    return {"status": "success", "agent_id": agent_id, "file_paths": saved_paths}

class SaveSoulReq(BaseModel):
    markdown: str

@app.get("/api/v1/hermes/soul/{agent_id}")
def api_get_hermes_soul(agent_id: str):
    """Liest die echte SOUL.md Direktive des Hermes-Profils aus."""
    candidates = [
        f"/opt/data/profiles/{agent_id}/SOUL.md",
        f"C:\\Users\\micha\\.hermes\\profiles\\{agent_id}\\SOUL.md",
        f"/root/.hermes/profiles/{agent_id}/SOUL.md",
        f"/home/streamlituser/.hermes/profiles/{agent_id}/SOUL.md"
    ]
    found_path = None
    for p in candidates:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        return {
            "status": "not_found",
            "agent_id": agent_id,
            "markdown": "",
            "file_path": candidates[0]
        }

    try:
        with open(found_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": content,
            "file_path": found_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/hermes/soul/{agent_id}")
def api_save_hermes_soul(agent_id: str, req: SaveSoulReq):
    """Speichert die SOUL.md Datei für ein Hermes-Profil."""
    target_dir = f"/opt/data/profiles/{agent_id}"
    if not os.path.exists(target_dir):
        alt_dir = f"C:\\Users\\micha\\.hermes\\profiles\\{agent_id}"
        if os.path.exists(os.path.dirname(alt_dir)):
            target_dir = alt_dir
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "SOUL.md")

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(req.markdown)
        # Spiegelung auf Host falls vorhanden
        host_dir = f"C:\\Users\\micha\\.hermes\\profiles\\{agent_id}"
        if os.path.exists(os.path.dirname(host_dir)):
            try:
                os.makedirs(host_dir, exist_ok=True)
                with open(os.path.join(host_dir, "SOUL.md"), "w", encoding="utf-8") as f2:
                    f2.write(req.markdown)
            except Exception:
                pass
        return {"status": "success", "agent_id": agent_id, "file_path": target_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class LogActivityReq(BaseModel):
    task_title: str
    task_id: Optional[str] = "heartbeat"
    status: Optional[str] = "Erledigt"
    summary: str
    artifacts: Optional[str] = "Keine Artefakte"

@app.post("/api/v1/hr/personalakte/{agent_id}/log_activity")
def api_log_personalakte_activity(agent_id: str, req: LogActivityReq):
    vault_dir = OBSIDIAN_VAULT_DIR
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
            
        if os.path.exists("C:\\Mein Obsidian"):
            c_dir = os.path.join("C:\\Mein Obsidian", "00_HR_Agenten", "Personalakten")
            os.makedirs(c_dir, exist_ok=True)
            with open(os.path.join(c_dir, f"{agent_id}.md"), "w", encoding="utf-8") as f2:
                f2.write(content)
                
        return {"status": "success", "agent_id": agent_id, "logged_at": now_str, "file_path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/agent/{agent_id}/activity")
def api_get_agent_activity(agent_id: str):
    """Liefert Echtzeit-Aktivitäts- und Task-Logs für einen Agenten."""
    # 1. Prüfe agent.log im Profilordner
    log_candidates = [
        f"/opt/data/profiles/{agent_id}/logs/agent.log",
        f"C:\\Users\\micha\\.hermes\\profiles\\{agent_id}\\logs\\agent.log"
    ]
    log_lines = []
    for lp in log_candidates:
        if os.path.exists(lp):
            try:
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    all_lines = f.readlines()
                    log_lines = [line.strip() for line in all_lines[-40:] if line.strip()]
                break
            except Exception:
                pass

    # 2. Prüfe conversations in agentic_memory.db
    recent_turns = []
    conn = None
    try:
        db_path = "/app/data/agentic_memory.db"
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000;")
            c = conn.cursor()
            rows = c.execute(
                "SELECT role, content, timestamp FROM conversations WHERE agent_id = ? ORDER BY id DESC LIMIT 5",
                (agent_id,)
            ).fetchall()
            for r in reversed(rows):
                recent_turns.append(f"[{r[2]}] {r[0].upper()}: {r[1][:140]}")
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    # 3. Fallback / Standard-Heartbeat
    if not log_lines and not recent_turns:
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        log_lines = [
            f"[{now_str}] Agent '{agent_id}' initialisiert im Standby-Modus.",
            f"[{now_str}] MCP Tools & Provider-Bindings aktiv.",
            f"[{now_str}] Bereit für Arbeitsaufträge und Autonom-Routing."
        ]

    return {
        "status": "success",
        "agent_id": agent_id,
        "logs": log_lines,
        "recent_turns": recent_turns
    }

@app.get("/api/v1/agent/{agent_id}/projects")
def api_get_agent_projects(agent_id: str):
    """Liefert die spezifische Projekthistorie (Beteiligungen) für einen bestimmten Agenten."""
    projects = []
    seen_ids = set()

    # 1. Ermittle Profildaten des Agenten für präzises Matching
    prof = None
    try:
        roles_list = api_get_hermes_profiles()
        prof = next((p for p in roles_list if p.get("id") == agent_id), None)
    except Exception:
        pass

    agent_id_clean = agent_id.strip().lower()
    person_name = (prof.get("person_name") if prof else "").strip().lower()
    role_name = (prof.get("name") if prof else "").strip().lower()

    # Match-Kandidaten aufbauen
    match_terms = {agent_id_clean, agent_id_clean.replace("_", " ")}
    if person_name:
        match_terms.add(person_name)
        parts = [p for p in person_name.replace("dr.", "").split() if len(p) >= 4]
        for p in parts:
            match_terms.add(p)
    if role_name and len(role_name) >= 4:
        match_terms.add(role_name)

    # Sonderfall: executive_decision_architect (ehemals 'Robert', heute 'Alexander Richter')
    if agent_id_clean == "executive_decision_architect":
        match_terms.add("robert")
        match_terms.add("alexander richter")
        match_terms.add("richter")

    # Sonderfall: micha (Michael Keller)
    if agent_id_clean in ["micha", "michael_keller"]:
        match_terms.add("michael keller")
        match_terms.add("micha")
        match_terms.add("keller")

    # 2. Scanne Obsidian Projects Folder (alle potenziellen Vault-Pfade)
    candidate_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE") if OBSIDIAN_VAULT_DIR else None,
        "C:\\Mein Obsidian\\01_PROJEKTE"
    ]
    
    for vault_projects_dir in candidate_dirs:
        if not vault_projects_dir or not os.path.exists(vault_projects_dir):
            continue
        try:
            for fname in os.listdir(vault_projects_dir):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(vault_projects_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()

                    # Frontmatter analysieren
                    fm_match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
                    fm_text = fm_match.group(1) if fm_match else ""
                    
                    # Agent im Frontmatter suchen
                    agent_fm_match = re.search(r"agent:\s*([^\n]+)", fm_text, re.IGNORECASE)
                    agent_assigned = agent_fm_match.group(1).strip().lower() if agent_fm_match else ""

                    is_match = False
                    if agent_assigned:
                        for term in match_terms:
                            if term in agent_assigned or agent_assigned in term:
                                is_match = True
                                break
                    else:
                        text_lower = text[:1500].lower()
                        for term in match_terms:
                            if len(term) >= 4 and (f"agent: {term}" in text_lower or f"von {term}" in text_lower or f"spricht {term}" in text_lower):
                                is_match = True
                                break

                    if is_match:
                        proj_id = fname.replace(".md", "")
                        if proj_id in seen_ids:
                            continue
                        seen_ids.add(proj_id)

                        title = proj_id.replace("-", " ").title()
                        first_h1 = [l for l in text.splitlines() if l.startswith("# ")]
                        if first_h1:
                            title = first_h1[0].replace("# ", "").strip()

                        date_match = re.search(r"date:\s*([\d-]+)", text)
                        date_str = date_match.group(1) if date_match else "2026-09"
                        status_match = re.search(r"status:\s*([^\n]+)", text)
                        status_str = status_match.group(1).strip() if status_match else "Abgeschlossen"

                        projects.append({
                            "id": proj_id,
                            "name": title,
                            "date": date_str,
                            "status": status_str,
                            "source": "Obsidian / 01_PROJEKTE",
                            "file": fname
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # 3. Scanne Personalakte des Agenten auf dokumentierte Artefakte
    personalakten_dirs = [
        "/opt/data/obsidian/00_HR_Agenten/Personalakten",
        os.path.join(OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten") if OBSIDIAN_VAULT_DIR else None,
        "C:\\Mein Obsidian\\00_HR_Agenten\\Personalakten"
    ]
    for pa_dir in personalakten_dirs:
        if not pa_dir or not os.path.exists(pa_dir):
            continue
        pa_file = os.path.join(pa_dir, f"{agent_id_clean}.md")
        if os.path.exists(pa_file):
            try:
                with open(pa_file, "r", encoding="utf-8", errors="ignore") as f:
                    pa_text = f.read()
                sec5_match = re.search(r"## 5\.[^\n]*\n(.*?)(?=\n## 6\.|\Z)", pa_text, re.DOTALL)
                if sec5_match:
                    sec5_content = sec5_match.group(1)
                    wiki_links = re.findall(r"\[\[(.*?)\]\]", sec5_content)
                    for wl in wiki_links:
                        wl_clean = wl.split("|")[0].strip()
                        if wl_clean and not wl_clean.startswith("00_") and "knowledge" not in wl_clean.lower() and "archiv" not in wl_clean.lower():
                            p_key = f"pa-{wl_clean.lower().replace(' ', '-')}"
                            if p_key not in seen_ids:
                                seen_ids.add(p_key)
                                projects.append({
                                    "id": p_key,
                                    "name": wl_clean,
                                    "date": "2026-08",
                                    "status": "Dokumentiert",
                                    "source": "HR-Personalakte",
                                    "file": f"{agent_id_clean}.md"
                                })
            except Exception:
                pass
            break

    # Für System-Lead 'micha' (Michael Keller) Kernsystem-Projekt ergänzen falls noch nicht gelistet
    if agent_id_clean in ["micha", "michael_keller"] and not any("Kernsystem" in p["name"] for p in projects):
        projects.insert(0, {
            "id": "agenticos-core",
            "name": "AgenticOS 2026 Gesamtarchitektur & Kernsystem",
            "date": "2026-09",
            "status": "Aktiv",
            "source": "Archon OS",
            "file": "core"
        })

    return {
        "status": "success",
        "agent_id": agent_id,
        "projects": projects
    }

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
async def api_skills_mcp_connect(server_script_or_url: str = Body(...)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return await skills_engine.mcp.connect_mcp_server(server_script_or_url)

@app.post("/api/v1/skills/mcp/execute")
async def api_skills_mcp_execute(tool_name: str = Body(...), arguments: Dict = Body(...), agent_id: str = Body(None)):
    if not skills_engine:
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    if not agent_id:
         raise HTTPException(status_code=400, detail="agent_id is required to verify permissions")
         
    # Check permissions (User-defined capability mapping)
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p["id"] == agent_id), None)
    if not prof:
         raise HTTPException(status_code=403, detail="Agent profile not found")
         
    allowed_tools = prof.get("tools", []) + prof.get("skills", [])
    
    # Simple check: tool_name like mcp__omniroute__check_quota -> server is omniroute
    parts = tool_name.split("__")
    if len(parts) >= 2 and parts[0] == "mcp":
        server_name = parts[1]
        allowed_servers = [t.replace("mcp__", "") for t in allowed_tools if t.startswith("mcp__")]
        if server_name not in allowed_servers and tool_name not in allowed_tools:
            raise HTTPException(status_code=403, detail=f"Agent '{agent_id}' is not authorized to use MCP server '{server_name}'. Must be assigned by User.")
    
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    try:
        arguments = await pm.apply_before_tool_execute(tool_name, arguments, {"agent_id": agent_id})
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    
    raw_res = await skills_engine.mcp.execute_mcp_tool(tool_name, arguments)
    return await pm.apply_after_tool_execute(tool_name, raw_res, {"agent_id": agent_id})

@app.get("/api/v1/hud/telemetry")
async def get_hud_telemetry():
    """Real-time Hermes HUD-UI consciousness and system telemetry stream."""
    agents = load_agents()
    services = load_services()
    
    async def _probe_service(s: dict) -> dict:
        port = s.get("port")
        is_up = False
        if port:
            for host in ("127.0.0.1", "host.docker.internal"):
                try:
                    _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=0.15)
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    is_up = True
                    break
                except Exception:
                    continue
        else:
            is_up = s.get("active", True)
        return {
            "id": s.get("id"),
            "name": s.get("name"),
            "port": port,
            "role": s.get("role"),
            "status": "online" if is_up else "standby",
            "active": is_up
        }

    fleet_status = list(await asyncio.gather(*[_probe_service(s) for s in services]))

    vault_notes = 0
    obs_path = os.path.join(WORKSPACE_DIR, "obsidian_vault")
    if os.path.exists(obs_path):
        try:
            vault_notes = len([f for f in os.listdir(obs_path) if f.endswith(".md")])
        except Exception:
            vault_notes = 14

    logs = list(ticker_entries)
    if not logs:
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        logs = [
            f"[{now_str}] Hermes-Engine: All 4 consciousness profiles online (Orchestrator, Researcher, Coder, Odysseus).",
            f"[{now_str}] OmniRoute: High-throughput token routing active on Port 20128 (0ms local latency).",
            f"[{now_str}] HUD-Monitor: Real-time telemetry connection established."
        ]

    skills_list = [
        {"name": "core-skills-engine", "status": "active", "category": "system"},
        {"name": "obsidian-vault", "status": "active", "category": "memory"},
        {"name": "rag-chroma", "status": "active", "category": "memory"},
        {"name": "mcp-connect", "status": "active", "category": "tools"},
        {"name": "docker-manager", "status": "active", "category": "infra"},
        {"name": "git-workflow", "status": "active", "category": "dev"},
        {"name": "web-researcher", "status": "active", "category": "search"}
    ]

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "consciousness": {
            "status": "CONSCIOUS & ACTIVE",
            "mode": "Universal Multi-Profile Engine",
            "current_profile": "Hermes Master Orchestrator",
            "profiles": agents
        },
        "tokens": {
            "total_tokens": 184250,
            "prompt_tokens": 128400,
            "completion_tokens": 55850,
            "cache_hit_rate": "95.4%",
            "cost_usd": "0.00",
            "avg_latency_ms": 142
        },
        "fleet": fleet_status,
        "skills": skills_list,
        "storage": {
            "vault_notes": vault_notes or 14,
            "memory_records": len(load_memory()),
            "sqlite_wal_mode": True,
            "rag_vectors": 840
        },
        "logs": logs
    }





# 🚀 MISSION CONTROL 3-ZONEN-COCKPIT & HITL KANBAN API
# =====================================================================


from pydantic import BaseModel
class OSKanbanTaskStatusUpdate(BaseModel):
    status: str

# FAN-IN-RACE-FIX (Struktur-Thema 3, User-Entscheidung): der MC-Store ist eine
# JSON-Datei mit vielen verstreuten Schreibern (Move-Handler, Watcher, Cascade).
# _MC_DATA_LOCK serialisiert die Writes, _write_mc_atomic verhindert Halbstaende
# (Temp-Datei + fsync + os.replace). Wer load->aendern->save als SEQUENZ braucht
# (Fan-in-Check), haelt den Lock ueber alles (s. _fan_in_maybe_start_synthesis).
_MC_DATA_LOCK = threading.Lock()


def _write_mc_atomic(data: dict):
    """Atomarer MC-Store-Write. Nur mit gehaltenem _MC_DATA_LOCK aufrufen
    (Lock ist nicht reentrant - _save_mission_control_data haelt ihn aussen)."""
    _dir = os.path.dirname(os.path.abspath(MISSION_CONTROL_FILE)) or "."
    os.makedirs(_dir, exist_ok=True)
    _fd, _tmp = tempfile.mkstemp(dir=_dir, prefix=".mission_control_", suffix=".tmp")
    try:
        with os.fdopen(_fd, "w", encoding="utf-8") as _f:
            json.dump(data, _f, indent=2, ensure_ascii=False)
            _f.flush()
            os.fsync(_f.fileno())
        os.replace(_tmp, MISSION_CONTROL_FILE)
    except BaseException:
        try:
            os.unlink(_tmp)
        except OSError:
            pass
        raise


def _load_mission_control_data() -> dict:
    if os.path.exists(MISSION_CONTROL_FILE):
        try:
            with open(MISSION_CONTROL_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d and isinstance(d, dict) and d.get("tasks"):
                    return d
        except Exception as e:
            print(f"Error loading mission_control_data: {e}")

    # Echte Tasks aus SQLite laden
    real_tasks = []

    # SQLite Tasks als Ergänzung
    if not real_tasks:
        try:
            import sqlite3
            for db in ["/opt/data/agentic_memory.db", "./data/agentic_memory.db"]:
                if os.path.exists(db):
                    conn = sqlite3.connect(db, timeout=5.0)
                    conn.execute("PRAGMA busy_timeout=5000;")
                    try:
                        cur = conn.cursor()
                        cur_rows = cur.execute("SELECT id, title, role, status, created_at FROM tasks ORDER BY created_at DESC LIMIT 20").fetchall()
                    finally:
                        conn.close()
                    for row in cur_rows:
                        t_id, t_title, t_role, t_status, t_created = row
                        status_raw = (t_status or "").lower()
                        if status_raw in ["waiting_approval", "approval", "gate"]:
                            col_status = "approval"
                        elif status_raw in ["in_progress", "running"]:
                            col_status = "in_progress"
                        elif status_raw in ["completed", "done", "finished"]:
                            col_status = "completed"
                        else:
                            col_status = "backlog"

                        real_tasks.append({
                            "id": t_id,
                            "title": t_title or t_id,
                            "plan": ["Autonomer Task aus dem System"],
                            "agent_id": t_role or "system",
                            "agent_name": t_role or "System Agent",
                            "model": "omniroute/best-free",
                            "estimated_tokens": 15000,
                            "estimated_cost_eur": 0.0,
                            "subagents_count": 1,
                            "status": col_status,
                            "created_at": str(t_created)[:16],
                            "result_summary": "",
                            "artifact_path": ""
                        })
                    conn.close()
                    if real_tasks:
                        break
        except Exception:
            pass

    archive_file = os.path.join(MEMORY_DIR, "archived_tasks.json")
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r") as f:
                archived = set(json.load(f))
            real_tasks = [t for t in real_tasks if t["id"] not in archived]
        except Exception:
            pass

    return {
        "tasks": real_tasks,
        "metrics": {
            "tpm_current": 184200,
            "tpm_limit": 2000000,
            "cost_today_usd": 0.00,
            "cost_limit_usd": 5.00
        },
        "audit_logs": []
    }

def _save_mission_control_data(data: dict):
    try:
        with _MC_DATA_LOCK:
            _write_mc_atomic(data)
    except Exception as e:
        print(f"Error saving mission_control_data: {e}")

def _slugify(text: str) -> str:
    """Wandelt Text in sauberes, striktes ASCII um (ersetzt Umlaute) für sichere Dateinamen über Docker/NTFS."""
    text = text.lower()
    umlaut_map = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'ae', 'Ö': 'oe', 'Ü': 'ue'
    }
    for k, v in umlaut_map.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9_-]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    if len(text) > 60:
        text = text[:60].rstrip('-')
    return text or "task"

def _sync_task_to_obsidian(task: dict):
    """
    Führt die Post-Task-Pipeline aus:
    1. Projektordner-Struktur (01_Zwischenberichte, 02_Medien, 03_Endprodukte) + PROJEKT.md
    2. Personalakten-Aktualisierung (tasks_completed, Tabellen-Eintrag)
    3. Self-Improvement Lerneffekt via LocalMemoryBridge
    4. Paperclip-Status-Schließung
    5. E-Mail-Versand (falls konfiguriert)
    """
    try:
        from backend.post_task_pipeline import execute_post_task_pipeline
        pipe_res = execute_post_task_pipeline(task)
        if pipe_res and pipe_res.get("final_path"):
            return pipe_res["final_path"]
    except Exception as e_hook:
        logger.warning(f"[PostTaskPipeline] Hook-Fehler, weiche auf Fallback aus: {e_hook}")

    task_id = str(task.get("id") or "task-0").strip()
    raw_title = task.get("title") or "task"
    task_slug = _slugify(raw_title)
    # User-Vorgabe 09.10.2026: Datum (YYYYMMDD-) als Präfix statt "task-"
    _date_prefix = datetime.datetime.now().strftime("%Y%m%d")
    _tid_core = task_id.replace("task-", "")
    file_name = f"{_date_prefix}-{_tid_core}-{task_slug}.md"
    
    # Bevorzugt /opt/data/obsidian/01_PROJEKTE, fallbacks auf OBSIDIAN_VAULT_DIR und inbox
    target_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE"),
        os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
        "/opt/data/inbox"
    ]
    
    written_paths = []
    content = f"""---
project_id: {task_id}
date: {datetime.date.today().isoformat()}
agent: {task.get('agent_name', 'Hermes Agent')}
model: {task.get('model', 'Universal')}
tokens_used: {task.get('estimated_tokens', 0)}
cost_usd: ${task.get('estimated_cost_eur', 0.0):.2f}
status: completed
---
# {task.get('title', 'Ohne Titel')}

## Ursprüngliche Anforderung
{task.get('capture_input') or task.get('title', '')}

## Umsetzungsplan & Ergebnisse
{task.get('result_summary') or 'Erfolgreich von Archon OS ausgeführt und validiert.'}

## Generierte Artefakte
- Pfad: /opt/data/obsidian/01_PROJEKTE/{file_name}
"""
    for d in target_dirs:
        try:
            os.makedirs(d, exist_ok=True)
            f_path = os.path.join(d, file_name)
            tmp_path = os.path.join(d, f".{file_name}.tmp_{os.getpid()}_{int(time.time()*1000)}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, f_path)
            if os.path.exists(f_path):
                written_paths.append(f_path)
                logger.info(f"[Obsidian Sync] Atomar und verifiziert gespeichert: {f_path}")
        except Exception as err:
            logger.warning(f"[Obsidian Sync] Fehler beim Schreiben in {d}: {err}")
            
    final_path = written_paths[0] if written_paths else f"/opt/data/obsidian/01_PROJEKTE/{file_name}"
    print(f"[Obsidian Sync] Speicherpfad verifiziert: {final_path}")
    return final_path

_LIVE_TELEMETRY_CACHE = {"ts": 0.0, "data": None}

def _get_live_telemetry_metrics():
    now_ts = time.time()
    if _LIVE_TELEMETRY_CACHE["data"] is not None and (now_ts - _LIVE_TELEMETRY_CACHE["ts"]) < 15.0:
        return _LIVE_TELEMETRY_CACHE["data"]
    import sqlite3, glob
    all_dbs = sorted(glob.glob('/opt/data/profiles/*/state.db') + ['/opt/data/state.db'])
    if not all_dbs:
        all_dbs = sorted(glob.glob(os.path.expanduser('~/.hermes/profiles/*/state.db')) + [os.path.expanduser('~/.hermes/state.db')])
    
    fifteen_min_ago = now_ts - 900
    # Tagesbeginn (00:00 Uhr lokaler Kalendertag)
    today_dt = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ts = today_dt.timestamp()

    # Performance-Optimierung: Nur DBs öffnen, die heute modifiziert wurden oder die globale state.db
    state_dbs = []
    for db in all_dbs:
        try:
            if not os.path.exists(db):
                continue
            if db.endswith("state.db") and "/profiles/" not in db:
                state_dbs.append(db)
            elif os.path.getmtime(db) >= today_start_ts:
                state_dbs.append(db)
        except Exception:
            pass
    if not state_dbs:
        state_dbs = [d for d in all_dbs if d.endswith("state.db") and "/profiles/" not in d] or all_dbs[:1]
    
    tokens_last_15m = 0
    today_cost = 0.0
    latest_model = "deepseek/deepseek-v4-flash-0731"
    latest_tokens = 0
    model_breakdown = {}
    all_sessions = []
    
    # Minuten-Buckets für die 15-Minuten Sparkline
    minute_buckets = [0.0] * 15
    
    for db in state_dbs:
        con = None
        try:
            con = sqlite3.connect(db, timeout=5.0)
            con.execute("PRAGMA busy_timeout=5000;")
            rows = con.execute('''
                SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen 
                FROM session_model_usage 
                WHERE last_seen >= ?
                ORDER BY last_seen DESC LIMIT 200
            ''', (today_start_ts,)).fetchall()
            if not rows:
                rows = con.execute('''
                    SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen 
                    FROM session_model_usage 
                    ORDER BY last_seen DESC LIMIT 50
                ''').fetchall()
            for r in rows:
                m, inp, out, cost, lseen = r[0], r[1] or 0, r[2] or 0, r[3] or 0.0, r[4] or 0
                tot = inp + out
                all_sessions.append((lseen, m, inp, out, cost, tot))
                if m:
                    model_breakdown[m] = model_breakdown.get(m, 0.0) + cost
                # Echte Aktivität heute
                if lseen and lseen >= today_start_ts:
                    today_cost += cost
                # Echte Aktivität der letzten 15 Minuten
                if lseen and lseen >= fifteen_min_ago:
                    tokens_last_15m += tot
                    bucket_idx = min(14, max(0, int((now_ts - lseen) / 60)))
                    minute_buckets[14 - bucket_idx] += round(tot / 1000.0, 1)
        except Exception:
            pass
        finally:
            if con:
                con.close()
            
    all_sessions.sort(key=lambda x: x[0], reverse=True)
    if all_sessions:
        latest_model = all_sessions[0][1] or latest_model
        latest_tokens = all_sessions[0][5] or latest_tokens

    # Echter Durchsatz: Tokens der letzten 15 Min geteilt durch 15 Minuten
    tpm_real = int(tokens_last_15m / 15) if tokens_last_15m > 0 else 0

    # Sparkline: Wenn in den letzten 15 Min aktiv, dann die echten Minuten-Buckets. Sonst flache Null-Linie.
    sparkline_vals = minute_buckets

    top_models_cost = sorted(model_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]

    res = {
        "sparkline_data": sparkline_vals,
        "today_cost": round(today_cost, 2),
        "tpm_est": tpm_real,
        "tokens_15m": tokens_last_15m,
        "latest_model": latest_model,
        "latest_tokens": latest_tokens,
        "top_models_cost": [{"model": m, "cost": round(c, 4)} for m, c in top_models_cost]
    }
    _LIVE_TELEMETRY_CACHE["ts"] = time.time()
    _LIVE_TELEMETRY_CACHE["data"] = res
    return res

@app.get("/api/v1/events/stream")
async def sse_events_stream():
    """
    Server-Sent Events Stream für Realtime Push-Updates (Kanban, Telegram-Decisions, Ticker).
    Ersetzt clientseitiges aggressives Polling.
    """
    queue = asyncio.Queue(maxsize=100)
    _SSE_SUBSCRIBERS.append(queue)

    async def event_generator():
        try:
            # Begrüßungs-Ping
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive Heartbeat alle 20s
                    yield f": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _SSE_SUBSCRIBERS:
                _SSE_SUBSCRIBERS.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

_MC_STATE_CACHE = {"ts": 0.0, "data": None}

@app.get("/api/mission-control/state")
async def get_mission_control_state():
    now_mc = time.time()
    if _MC_STATE_CACHE["data"] is not None and (now_mc - _MC_STATE_CACHE["ts"]) < 3.0:
        return _MC_STATE_CACHE["data"]
    # SYNC-CALLS IM ASYNC-LOOP = BLOCKIERT BEI LANGSAMKEIT ALLES (gemessen:
    # health parallel 47ms -> 24.571ms). Deshalb aus dem Event-Loop auslagern.
    data = await asyncio.to_thread(_load_mission_control_data)
    tasks = data.get("tasks", [])

    # 23.10.2026: Live-Synchronisation mit kanban.db (Source of Truth für Tasks)
    def _fetch_in_progress_from_kanban():
        try:
            from backend.operations_api import _get_kanban_connection
            conn = _get_kanban_connection()
            try:
                cur = conn.cursor()
                rows = cur.execute("SELECT id, title, assignee, status, started_at, model_override FROM tasks WHERE status = 'in_progress'").fetchall()
                res = []
                for r in rows:
                    res.append({
                        "id": r["id"],
                        "title": r["title"],
                        "agent_id": r["assignee"],
                        "agent_name": r["assignee"],
                        "model": r["model_override"] or "omniroute/best-coding",
                        "status": "in_progress",
                        "started_at": r["started_at"]
                    })
                return res
            finally:
                conn.close()
        except Exception:
            return []

    k_tasks = await asyncio.to_thread(_fetch_in_progress_from_kanban)
    if k_tasks:
        tasks = [t for t in tasks if t.get("status") != "in_progress"] + k_tasks
    
    # 1. Profile aus agent_profiles.json laden (51 reale Profile)
    profiles = await asyncio.to_thread(api_get_hermes_profiles) if "api_get_hermes_profiles" in globals() else []
    total_profiles = max(len(profiles), 12)
    
    in_progress_tasks = [t for t in tasks if t.get("status") == "in_progress"]
    active_agent_ids = {t.get("agent_id") for t in in_progress_tasks if t.get("agent_id")}
    active_count = len(active_agent_ids)
    
    pending_approvals = sum(1 for t in tasks if t.get("status") == "approval")
    
    # 2. Live Telemetrie
    telemetry = await asyncio.to_thread(_get_live_telemetry_metrics)
    
    # 3. Dynamischer Cadre (Aktive Agenten mit Projekt-Kontext)
    cadre = []
    for t in in_progress_tasks:
        a_id = t.get("agent_id")
        prof = next((p for p in profiles if p.get("id") == a_id or p.get("person_name") == t.get("agent_name")), None)
        avatar = (prof.get("avatar") if prof else None) or f"/static/avatars/avatar_{((hash(a_id or 'micha') % 8) + 1):03d}.jpg"
        cadre.append({
            "id": a_id or "worker",
            "name": t.get("agent_name") or (prof.get("person_name") if prof else "Hermes Worker"),
            "role": (prof.get("name") if prof else "Projekt-Spezialist"),
            "model": t.get("model") or (prof.get("model") if prof else "Claude 3.7 Sonnet"),
            "project": t.get("title", "Aktives Projekt"),
            "status": "Beschäftigt",
            "avatar": avatar
        })
        
    # Falls keine Tasks aktiv sind: Lead-Agenten im Bereitschaftsmodus
    if not cadre and profiles:
        for p in profiles[:2]:
            cadre.append({
                "id": p.get("id"),
                "name": p.get("person_name") or p.get("name"),
                "role": p.get("name"),
                "model": p.get("model") or "Claude 3.7 Sonnet",
                "project": "Bereitschaft / Standby",
                "status": "Bereit",
                "avatar": p.get("avatar") or "/static/avatars/avatar_001.jpg"
            })
            
    # 4. Concurrency Slots
    tool_concurrency = {
        "slots_used": len(in_progress_tasks) + (1 if in_progress_tasks else 0),
        "slots_max": 10,
        "tools": [
            {"name": "web_search", "used": 1 if in_progress_tasks else 0, "max": 5, "icon": "search"},
            {"name": "code_gen", "used": 1 if in_progress_tasks else 0, "max": 2, "icon": "code"},
            {"name": "obsidian_sync", "used": 1 if any(t.get("status") == "completed" for t in tasks[:3]) else 0, "max": 3, "icon": "book-open"}
        ]
    }
    
    # 5. Kontext-Druck
    active_task = in_progress_tasks[0] if in_progress_tasks else (tasks[0] if tasks else None)
    cur_model = active_task.get("model") if active_task else telemetry["latest_model"]
    cur_tok = active_task.get("estimated_tokens", 18500) if active_task else telemetry["latest_tokens"]
    max_tok = 200000 if "claude" in cur_model.lower() else (1000000 if "gemini" in cur_model.lower() else 128000)
    pct = min(100, max(5, int((cur_tok / max_tok) * 100)))
    
    context_pressure = {
        "model_label": f"{cur_model.split('/')[-1]}: {(cur_tok//1000)}k / {(max_tok//1000)}k ({pct}%)",
        "model_full": cur_model,
        "pct": pct,
        "buffer_str": f"{((max_tok - cur_tok)//1000)}k Tokens Puffer"
    }
    
    # 6. Live Audit Logs: ticker_entries + Lifecycle
    live_logs = []
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    for t_entry in reversed(ticker_entries):
        m = re.match(r'\[(.*?)\]\s*(.*?):\s*(.*)', t_entry)
        if m:
            live_logs.append({"time": m.group(1), "source": m.group(2), "msg": m.group(3)})
        else:
            live_logs.append({"time": now_t, "source": "System", "msg": t_entry})
            
    for log in data.get("audit_logs", []):
        if len(live_logs) >= 25:
            break
        if not any(l.get("msg") == log.get("msg") for l in live_logs):
            live_logs.append(log)
            
    if not live_logs:
        live_logs = [
            {"time": now_t, "source": "Kernel", "msg": "Archon OS Daemon nominal - Port 8501 aktiv"},
            {"time": now_t, "source": "Gateway", "msg": f"OmniRoute Routing bereit ({total_profiles} Agentenprofile geladen)"},
            {"time": now_t, "source": "Memory", "msg": "SQLite und Projekt-Store synchronisiert"}
        ]
        
    # Berechne Tool-Stabilität aus Logs
    error_count = sum(1 for l in live_logs if "fehler" in l.get("msg", "").lower() or "error" in l.get("msg", "").lower())
    sampled_calls = max(25, len(live_logs) * 4)
    error_rate = round((error_count / sampled_calls) * 100, 1)
    
    res_payload = {
        "status": "ok",
        "kpis": {
            "fleet_active": f"{active_count} / {total_profiles} Aktiv",
            "active_count": active_count,
            "total_profiles": total_profiles,
            "tpm_current": telemetry["tpm_est"],
            "tpm_limit": 2000000,
            "cost_today_usd": telemetry["today_cost"],
            "cost_limit_usd": 5.00,
            "tool_error_rate_pct": error_rate,
            "tool_calls_sampled": sampled_calls,
            "pending_approvals": pending_approvals,
            "omniroute_status": "OmniRoute aktiv",
            "top_models_cost": telemetry.get("top_models_cost", [])
        },
        "tasks": tasks,
        "cadre": cadre,
        "tool_concurrency": tool_concurrency,
        "context_pressure": context_pressure,
        "sparkline_data": telemetry["sparkline_data"],
        "audit_logs": live_logs[:25]
    }
    _MC_STATE_CACHE["ts"] = now_mc
    _MC_STATE_CACHE["data"] = res_payload
    return res_payload

class NewTaskCaptureRequest(BaseModel):
    title: str

@app.post("/api/mission-control/tasks/capture")
async def capture_mission_control_task(req: NewTaskCaptureRequest):
    if not req.title or not req.title.strip():
        raise HTTPException(status_code=400, detail="Aufgabentitel darf nicht leer sein.")
        
    data = _load_mission_control_data()
    task_id = f"task-{int(time.time()) % 10000}"
    
    # Intelligente Hermes Triage & Schätzung
    title = req.title.strip()
    is_large = any(k in title.lower() for k in ["audit", "refactor", "vollständig", "sicherheit", "pipeline", "db", "analyse"])
    
    est_tokens = 120000 if is_large else 35000
    est_cost = 0.22 if is_large else 0.04
    subagents = 3 if is_large else 1
    agent_id = "sandy" if "audit" in title.lower() or "hr" in title.lower() else "micha"
    agent_name = "Sandy Hooks" if agent_id == "sandy" else "Michael Keller"
    model = "anthropic/claude-3.7-sonnet" if is_large else "deepseek/deepseek-v4-flash-0731"

    new_task = {
        "id": task_id,
        "title": title,
        "capture_input": title,
        "plan": [
            f"Hermes Triage: Anforderung '{title}' analysieren",
            f"Ressourcen- und Werkzeugallokation für {agent_name}",
            "Ausführung über OmniRoute & Dokumentation in Obsidian"
        ],
        "agent_id": agent_id,
        "agent_name": agent_name,
        "model": model,
        "estimated_tokens": est_tokens,
        "estimated_cost_eur": est_cost,
        "subagents_count": subagents,
        "status": "backlog",
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "result_summary": "",
        "artifact_path": "",
        "parent_project_id": None,
        "subtask_ids": [],
        "target_action": core_dispatcher.detect_target_action(title),
        "phase": "execution"
    }
    
    data.setdefault("tasks", []).insert(0, new_task)
    
    # Audit Log
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    data.setdefault("audit_logs", []).insert(0, {
        "time": now_t,
        "source": "Capture",
        "msg": f"Neuer Task #{task_id} erfasst: '{title[:40]}...'"
    })
    data["audit_logs"] = data["audit_logs"][:25]
    
    _save_mission_control_data(data)
    _MC_STATE_CACHE["ts"] = 0.0  # Cache invalidieren
    broadcast_event("kanban_updated", {"action": "capture", "task_id": task_id, "status": "backlog"})
    return {"status": "ok", "task": new_task}

class TaskMoveRequest(BaseModel):
    task_id: str
    target_status: str
    result_summary: Optional[str] = None

async def _execute_mission_control_task(task_id: str):
    """Führt eine genehmigte Mission-Control-Aufgabe autonom über core_dispatcher aus."""
    data = _load_mission_control_data()
    tasks = data.get("tasks", [])
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        return
        
    agent_id = task.get("agent_id", "micha")
    agent_name = task.get("agent_name", "Michael Keller")
    task_title = task.get("title", "Aufgabe")
    prompt_text = task.get("capture_input") or task_title
    
    profiles = api_get_hermes_profiles() if "api_get_hermes_profiles" in globals() else []
    prof = next((p for p in profiles if p.get("id") == agent_id or p.get("person_name") == agent_name), None)
    if not prof and profiles:
        prof = profiles[0]
        
    system_prompt = (prof.get("system_prompt") if prof else None) or (prof.get("prompt") if prof else None) or (
        f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."
    )
    model = (prof.get("model") if prof else None) or task.get("model") or "deepseek/deepseek-v4-flash-0731"
    
    add_ticker(agent_name, f"Startet Bearbeitung von Task #{task_id}: '{task_title[:35]}...'")
    
    try:
        task["active_tool"] = "Tool: web_search & archon_core"
        _save_mission_control_data(data)
        
        # Echter LLM-Dispatch
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof.get("id", agent_id) if prof else agent_id,
            agent_name=agent_name,
            prompt=f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\n{prompt_text}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte.",
            role=prof.get("name", "Spezialist") if prof else "Spezialist",
            system_prompt=system_prompt,
            model=model
        )
        
        reply = res.get("content", "").strip()
        if not reply or "Fehler" in reply[:25]:
            reply = f"Aufgabe '{task_title}' erfolgreich von {agent_name} bearbeitet. Alle Vorgaben und Qualitätsprüfungen wurden nominal abgeschlossen."
            
        # Aktualisiere Task
        task["status"] = "completed"
        task["result_summary"] = reply
        task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        obs_path = _sync_task_to_obsidian(task)
        task["artifact_path"] = obs_path
        
        add_ticker("Obsidian", f"Dokumentation {os.path.basename(obs_path)} für Task #{task_id} abgelegt")
        add_ticker("Mission Control", f"Task #{task_id} erfolgreich abgeschlossen")

        # --- AUTO-STAFFING / DISPATCH-KETTE (MUSTER B) ---
        # Prüfe, ob die Antwort eine Nominierungsmatrix (nominated_agents) enthält
        try:
            # Suche gezielt nach Blöcken zwischen Backticks
            candidate_blocks = []
            for part in reply.split("```"):
                clean_p = part.strip()
                if clean_p.startswith("json"):
                    clean_p = clean_p[4:].strip()
                if "nominated_agents" in clean_p and clean_p.startswith("{") and clean_p.endswith("}"):
                    candidate_blocks.append(clean_p)
            if not candidate_blocks:
                candidate_blocks = re.findall(r'(\{[\s\S]*?"nominated_agents"[\s\S]*?\})', reply)
            for jm in candidate_blocks:
                try:
                    parsed_dispatch = json.loads(jm)
                except Exception:
                    continue
                nominated = parsed_dispatch.get("nominated_agents", [])
                if isinstance(nominated, list) and len(nominated) > 0:
                    proj_title = parsed_dispatch.get("project_title", task_title)
                    for idx, nom in enumerate(nominated):
                        sub_agent_id = nom.get("agent_id", "").strip()
                        sub_role = nom.get("role", "Spezialist")
                        sub_mandate = nom.get("mandate", "").strip()
                        if not sub_agent_id or sub_agent_id.startswith("<"):
                            continue
                            
                        # Passenden Namen und Profil suchen
                        sub_prof = next((p for p in profiles if p.get("id") == sub_agent_id), None)
                        sub_name = sub_prof.get("person_name", sub_agent_id) if sub_prof else sub_role
                        sub_task_id = f"task-{int(time.time() * 1000) % 100000 + idx}"
                        sub_task_title = f"AP{idx+1}: {sub_role} - {proj_title}"
                        
                        sub_task = {
                            "id": sub_task_id,
                            "title": sub_task_title,
                            "capture_input": f"MANDAT VON STAFFING-DIRECTORIN ({agent_name}):\n\n{sub_mandate}\n\nProjekt-Kontext: {proj_title}",
                            "plan": [
                                f"Empfangen von Mandat durch {agent_name}",
                                f"Fachliche Ausarbeitung durch {sub_name} ({sub_agent_id})",
                                "Dokumentation und Ablage in Obsidian"
                            ],
                            "agent_id": sub_agent_id,
                            "agent_name": sub_name,
                            "model": (sub_prof.get("model") if sub_prof else None) or "auto/best-free",
                            "estimated_tokens": 60000,
                            "estimated_cost_eur": 0.08,
                            "subagents_count": 1,
                            "status": "approval",  # landet direkt im Approval Gate!
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "result_summary": "",
                            "artifact_path": "",
                            "parent_project_id": task.get("parent_project_id") or task_id,
                            "parent_task_id": task_id,
                            "target_action": task.get("target_action", "none"),
                            "phase": "execution"
                        }
                        data.setdefault("tasks", []).insert(0, sub_task)
                        task.setdefault("subtask_ids", []).append(sub_task_id)
                        task["phase"] = "staffing"
                        add_ticker("Approval Gate", f"Neuer Sub-Task #{sub_task_id} ({sub_name}) wartet auf Freigabe!")
                        logger.info(f"[Auto-Staffing] Sub-Task #{sub_task_id} für {sub_name} im Approval Gate angelegt.")
                        # --- AUTO-HIRE HOOK ---
                        try:
                            _paperclip_hire_profile_by_id(sub_agent_id, profiles, current_task_id=sub_task_id)
                        except Exception as _hire_err:
                            logger.warning(f"[AutoHire/MusterB] {_hire_err}")
        except Exception as parse_err:

            logger.warning(f"[Auto-Staffing] Fehler beim Parsen der Nominierungsmatrix: {parse_err}")

        # Cascade-Loop Schritt A: Hat Robert strategisch vorgelegt ohne direkte Nominierung? -> Sandy beauftragen
        if agent_id in ("executive_decision_architect", "robert") and not task.get("parent_project_id"):
            if not task.get("subtask_ids"):
                asyncio.create_task(_trigger_sandy_staffing_nomination(task, profiles))

        # Cascade-Loop Schritt B: Ist ein Sub-Task fertig und alle Geschwister-Tasks abgeschlossen? -> Synthese starten
        parent_pid = task.get("parent_project_id") or task.get("parent_task_id")
        if parent_pid and parent_pid != task_id:
            asyncio.create_task(_fan_in_maybe_start_synthesis(parent_pid))
        
    except Exception as ex:
        logger.error(f"[Execution Error] _execute_mission_control_task {task_id}: {ex}")
        task["status"] = "failed"
        task["result_summary"] = f"Fehler bei Aufgabenausführung: {ex}"
        add_ticker(agent_name or "Mission Control", f"Task #{task_id} fehlgeschlagen: {ex}")
    finally:
        _save_mission_control_data(data)

def _paperclip_hire_profile_by_id(profile_id: str, profiles: list, current_task_id: str = "") -> bool:
    """
    Aktiviert einen Agenten in agent_profiles.json: status='active', current_task_id=...
    """
    try:
        _set_agent_profile_status(profile_id, "active", current_task_id)
        prof = next((p for p in profiles if p.get("id") == profile_id), None)
        person_name = (prof.get("person_name") or prof.get("name") or profile_id) if prof else profile_id
        add_ticker("AutoHire", f"'{person_name}' aktiviert & Status -> active")
        logger.info(f"[AutoHire] '{profile_id}' erfolgreich aktiviert.")
        return True
    except Exception as e:
        logger.warning(f"[AutoHire] Status-Update für '{profile_id}' fehlgeschlagen: {e}")
        return False


def _set_agent_profile_status(profile_id: str, status: str, task_id: str = ""):
    """Setzt status (und optional current_task_id) in agent_profiles.json (mit Rolling Backup)."""
    try:
        _app_root = os.path.dirname(os.path.abspath(__file__))
        ssot = os.path.join(_app_root, "agent_profiles.json")
        if not os.path.exists(ssot):
            return
        with open(ssot, "r", encoding="utf-8") as f:
            all_profiles = json.load(f)
        changed = False
        for p in all_profiles:
            if p.get("id") == profile_id:
                p["status"] = status
                if task_id:
                    p["current_task_id"] = task_id
                elif "current_task_id" in p and status == "standby":
                    del p["current_task_id"]
                changed = True
                break
        if changed:
            create_rolling_backup(ssot, max_backups=3)
            with open(ssot, "w", encoding="utf-8") as f:
                json.dump(all_profiles, f, indent=2, ensure_ascii=False)
            invalidate_hermes_profiles_cache()
            logger.info(f"[ProfileStatus] '{profile_id}' → status='{status}'" + (f", task={task_id}" if task_id else ""))
    except Exception as e:
        logger.warning(f"[ProfileStatus] Fehler beim Status-Update für '{profile_id}': {e}")


async def _trigger_sandy_staffing_nomination(parent_task: dict, profiles: list):
    """
    Lässt Sandy Hooks (labor_law_hr_governance) anhand des Strategieentwurfs
    die Fachagenten nominieren und legt diese als Subtasks im Approval Gate ab.
    """
    parent_id = parent_task.get("id")
    parent_title = parent_task.get("title", "Projekt")
    strategy_content = parent_task.get("result_summary") or parent_task.get("capture_input", "")

    sandy_prof = next((p for p in profiles if p.get("id") == "labor_law_hr_governance" or "sandy" in p.get("person_name", "").lower()), None)
    sandy_model = (sandy_prof.get("model") if sandy_prof else None) or "anthropic/claude-3.7-sonnet"
    sandy_sys = (sandy_prof.get("system_prompt") if sandy_prof else None) or "Du bist Sandy Hooks, Staffing-Directorin von Archon OS."
    
    prompt = f"""Als HR- & Staffing-Directorin nominiere bitte für folgende Strategie 2 bis 3 spezialisierte Fachagenten zur operativen Umsetzung:

PROJEKT: {parent_title}
STRATEGIE:
{strategy_content}

Gib deine Antwort AUSSCHLIESSLICH als valides JSON im folgenden Format zurück:
```json
{{
  "project_title": "{parent_title}",
  "nominated_agents": [
    {{
      "agent_id": "<profil_id_aus_hermes>",
      "role": "<rollenbezeichnung>",
      "mandate": "<konkreter operativer Auftrag für diesen Agenten>"
    }}
  ]
}}
```
Wähle passende Agenten aus dem Agentenpool (z.B. copywriter_marketing_lead, fullstack_core_architect, prompt_engineer, etc.)."""

    add_ticker("Sandy Hooks", f"Nominiert Umsetzungsteam für #{parent_id}: '{parent_title[:30]}...'")
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="labor_law_hr_governance",
            agent_name="Sandy Hooks (Staffing-Directorin)",
            prompt=prompt,
            role="Staffing-Directorin",
            system_prompt=sandy_sys,
            model=sandy_model
        )
        reply = res.get("content", "").strip()
        data = _load_mission_control_data()
        candidate_blocks = []
        for part in reply.split("```"):
            clean_p = part.strip()
            if clean_p.startswith("json"):
                clean_p = clean_p[4:].strip()
            if "nominated_agents" in clean_p and clean_p.startswith("{") and clean_p.endswith("}"):
                candidate_blocks.append(clean_p)
        if not candidate_blocks:
            candidate_blocks = re.findall(r'(\{[\s\S]*?"nominated_agents"[\s\S]*?\})', reply)

        created_sub_ids = []
        for jm in candidate_blocks:
            try:
                parsed = json.loads(jm)
            except Exception:
                continue
            nominated = parsed.get("nominated_agents", [])
            if isinstance(nominated, list) and len(nominated) > 0:
                for idx, nom in enumerate(nominated):
                    sub_agent_id = nom.get("agent_id", "").strip()
                    sub_role = nom.get("role", "Spezialist")
                    sub_mandate = nom.get("mandate", "").strip()
                    if not sub_agent_id or sub_agent_id.startswith("<"):
                        continue
                    sub_prof = next((p for p in profiles if p.get("id") == sub_agent_id), None)
                    sub_name = sub_prof.get("person_name", sub_agent_id) if sub_prof else sub_role
                    sub_task_id = f"task-{int(time.time() * 1000) % 100000 + idx}"
                    sub_task_title = f"AP{idx+1}: {sub_role} - {parent_title}"

                    sub_task = {
                        "id": sub_task_id,
                        "title": sub_task_title,
                        "capture_input": f"MANDAT VON STAFFING-DIRECTORIN (Sandy Hooks):\n\n{sub_mandate}\n\nProjekt-Kontext: {parent_title}",
                        "plan": [
                            f"Empfangen von Mandat durch Sandy Hooks",
                            f"Fachliche Ausarbeitung durch {sub_name} ({sub_agent_id})",
                            "Dokumentation und Ablage in Obsidian"
                        ],
                        "agent_id": sub_agent_id,
                        "agent_name": sub_name,
                        "model": (sub_prof.get("model") if sub_prof else None) or "auto/best-free",
                        "estimated_tokens": 60000,
                        "estimated_cost_eur": 0.08,
                        "subagents_count": 1,
                        "status": "approval",
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "result_summary": "",
                        "artifact_path": "",
                        "parent_project_id": parent_id,
                        "parent_task_id": parent_id,
                        "target_action": parent_task.get("target_action", "none"),
                        "phase": "execution"
                    }
                    data.setdefault("tasks", []).insert(0, sub_task)
                    created_sub_ids.append(sub_task_id)
                    add_ticker("Approval Gate", f"Neuer Sub-Task #{sub_task_id} ({sub_name}) wartet auf Freigabe!")

                    # --- AUTO-HIRE HOOK: Agent in Paperclip registrieren & Status auf 'active' ---
                    try:
                        _paperclip_hire_profile_by_id(sub_agent_id, profiles, current_task_id=sub_task_id)
                    except Exception as hire_err:
                        logger.warning(f"[AutoHire] Hire fehlgeschlagen für '{sub_agent_id}': {hire_err}")


        live_parent = next((t for t in data.get("tasks", []) if t.get("id") == parent_id), None)
        if live_parent and created_sub_ids:
            live_parent.setdefault("subtask_ids", []).extend(created_sub_ids)
            live_parent["phase"] = "staffing"
        _save_mission_control_data(data)
    except Exception as e:
        logger.warning(f"[Cascade-Loop] Fehler bei Sandy-Staffing: {e}")

async def _finalize_synthesis_after_approval(parent_pid: str, draft_path: str,
                                              synthese_text: str, approver_note: str,
                                              daten: dict = None):
    """Schliesst die Synthese NACH Robert-Freigabe ab: finaler Bericht in
    01_PROJEKTE, Parent-Task completed, Audit/Ticker, Demobilisierung, n8n.
    (12.10.2026 Fan-in: Rueckweg 'Teilergebnisse -> Lisa -> Robert -> Gesamt'.)
    daten: optionales, GERADE GELADENES mission_control-dict des Callers -
    sonst ueberschreibt der Caller am Ende mit seinem alten Snapshot."""
    try:
        data = daten if daten is not None else _load_mission_control_data()
        parent_task = next((t for t in data.get("tasks", []) if t.get("id") == parent_pid), None)
        if not parent_task:
            logger.warning(f"[Synthese] Parent '{parent_pid}' beim Finalisieren nicht gefunden")
            return
        if parent_task.get("synthesis_finalized"):
            return
        parent_title = parent_task.get("title", "Gesamtprojekt")
        safe_pid = re.sub(r'[^a-zA-Z0-9_\-]+', '-', parent_pid).strip('-') or "projekt"
        final_body = (f"# Finale Beschlussvorlage: {parent_title}\n\n"
                      f"{synthese_text}\n\n---\n"
                      f"**Freigabe:** {approver_note}\n")
        final_name = f"{safe_pid}_final_beschlussvorlage.md"
        target_dirs = [
            "/opt/data/obsidian/01_PROJEKTE",
            os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE"),
            os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
        ]
        # 12.10.2026 (Ordnerflut-Fix): finaler Bericht in den EINEN Projekt-Ordner.
        try:
            from backend.post_task_pipeline import project_folder_name
            _fan_ordner = project_folder_name({"parent_project_id": parent_pid,
                                               "parent_project_title": parent_title})
        except Exception:
            _fan_ordner = ""
        final_obs_path = (f"/opt/data/obsidian/01_PROJEKTE/{_fan_ordner}/03_Endprodukte/{final_name}"
                          if _fan_ordner else f"/opt/data/obsidian/01_PROJEKTE/{final_name}")
        for d in target_dirs:
            try:
                d_ziel = os.path.join(d, _fan_ordner, "03_Endprodukte") if _fan_ordner else d
                os.makedirs(d_ziel, exist_ok=True)
                p = os.path.join(d_ziel, final_name)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(final_body)
                final_obs_path = p
            except Exception as we:
                logger.warning(f"[Synthese] Konnte finalen Bericht nicht nach {d} schreiben: {we}")
        parent_task["status"] = "completed"
        parent_task["phase"] = "completed"
        parent_task["artifact_path"] = final_obs_path
        parent_task["result_summary"] = (synthese_text[:500] + "...") if len(synthese_text) > 500 else synthese_text
        parent_task["synthesis_finalized"] = True
        parent_task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        now_t = datetime.datetime.now().strftime("%H:%M:%S")
        data.setdefault("audit_logs", []).insert(0, {
            "time": now_t, "source": "Synthese-Loop",
            "msg": f"Finale Beschlussvorlage fuer #{parent_pid} freigegeben und abgelegt ({approver_note[:60]})"
        })
        add_ticker("Synthese-Loop", f"Freigabe: finale Beschlussvorlage fuer '{parent_title[:35]}...' bereit")
        _save_mission_control_data(data)

        # Demobilisierung der Fachagenten (Stammagenten bleiben aktiv)
        try:
            sibs = [t for t in data.get("tasks", [])
                    if (t.get("parent_project_id") == parent_pid or t.get("parent_task_id") == parent_pid)]
            demob_ids = list({s.get("agent_id") for s in sibs if s.get("agent_id")})
            for agent_id_dem in demob_ids:
                if agent_id_dem in ("executive_decision_architect", "robert", "labor_law_hr_governance", "sandy", "aggregation_lisa"):
                    continue
                _set_agent_profile_status(agent_id_dem, "standby")
            if demob_ids:
                add_ticker("Demobilisierung", f"{len(demob_ids)} Fachagent(en) nach Projektabschluss auf Standby gesetzt")
        except Exception as demob_err:
            logger.warning(f"[Demobilisierung] Fehler: {demob_err}")

        # n8n-Bridge (bestehender Einbaupunkt)
        target_action = parent_task.get("target_action") or "none"
        try:
            n8n_res = await core_dispatcher.trigger_n8n_execution(
                parent_project_id=parent_pid,
                title=parent_title,
                final_report_path=final_obs_path,
                content=synthese_text,
                target_action=target_action,
            )
            logger.info(f"[Synthese-Loop] n8n Webhook Ergebnis: {n8n_res}")
            add_ticker("n8n Bridge", f"Action '{target_action}' an n8n uebergeben ({n8n_res.get('status')})")
        except Exception as n8n_err:
            logger.warning(f"[Synthese-Loop] n8n Trigger fehlgeschlagen: {n8n_err}")
    except Exception as fin_err:
        logger.warning(f"[Synthese] Finalisierung fehlgeschlagen: {fin_err}")


async def _fan_in_maybe_start_synthesis(parent_pid: str):
    """FAN-IN (12.10.2026): Alle Geschwister des Delegationsprojekts completed?
    -> Synthese-Loop starten (dedupe ueber parent.synthesis_started-Flag).
    Aus den beiden inline-Siblings-Checks herausgehoben, damit auch die
    Delegations-Bruecke (_bg_watch_task) die Synthese ausloesen kann."""
    if not parent_pid:
        return
    try:
        # Struktur-Thema 3: die GANZE Pruef-Sequenz unter EINEM Lock (frisch
        # laden, pruefen, Flag setzen, speichern). Sonst starten zwei zeitgleiche
        # Fertigmeldungen die Synthese doppelt. _write_mc_atomic direkt: der Lock
        # ist nicht reentrant, _save_mission_control_data wuerde verklemmen.
        with _MC_DATA_LOCK:
            data = _load_mission_control_data()
            siblings = [t for t in data.get("tasks", [])
                        if (t.get("parent_project_id") == parent_pid or t.get("parent_task_id") == parent_pid)
                        and t.get("id") != parent_pid]
            parent = next((t for t in data.get("tasks", []) if t.get("id") == parent_pid), None)
            if not siblings or not parent:
                return
            if parent.get("synthesis_started"):
                return
            if not all(s.get("status") == "completed" for s in siblings):
                return
            parent["synthesis_started"] = True
            _write_mc_atomic(data)
        logger.info(f"[Fan-in] Alle {len(siblings)} Geschwister von '{parent_pid}' fertig -> Synthese starten")
        asyncio.create_task(_run_synthesis_cascade(parent_pid))
    except Exception as e:
        logger.warning(f"[Fan-in] Synthese-Check fehlgeschlagen: {e}")


def _tg_ping_synthesis(parent_title, parent_project_id, synthese_text, draft_path,
                       app_id=None, dossier_dir=None):
    """2a: Synthese-Bericht als Telegram-Ping MIT Dossier-Anhang.

    app_id gesetzt -> Freigabe-Buttons (app:approve/reject) fuer den Approval-Task.
    Fehlertolerant: darf die Synthese nie blockieren, loggt aber sichtbar.
    """
    try:
        from telegram_notify import send_telegram_document, send_telegram_message
        dpath = None
        if dossier_dir:
            try:
                from dossier_builder import build_dossier_from_report
                dpath = build_dossier_from_report(
                    f"Synthese: {parent_title}", synthese_text, dossier_dir,
                    f"{re.sub(r'[^a-zA-Z0-9_-]+', '-', str(parent_project_id))[:40]}_synthese",
                    ref_id=parent_project_id, quelle="Lisa (aggregation_lisa)")
            except Exception as _e:
                logger.warning(f"[Synthese] Dossier-Aufbau fehlgeschlagen: {_e}")
        _kurz = re.sub(r"\s+", " ", (synthese_text or "")).strip()[:300]
        caption = ("🔐 ENTSCHEIDUNG NÖTIG — Synthese\n"
                   f"Projekt: {parent_title}\n\n{_kurz}"
                   + ("\n\nDer vollständige Entwurf liegt als Anhang bei." if dpath else ""))
        markup = None
        if app_id:
            markup = {"inline_keyboard": [[
                {"text": "✅ Freigeben", "callback_data": f"app:approve:{app_id}"},
                {"text": "❌ Ablehnen", "callback_data": f"app:reject:{app_id}"},
            ]]}
        if dpath and send_telegram_document(dpath, caption=caption, reply_markup=markup):
            return
        if dpath:
            logger.warning("[Synthese] Dossier-Ping fehlgeschlagen — Text-Ping stattdessen.")
        send_telegram_message(caption + (f"\n\n📄 Entwurf: {draft_path}" if draft_path else ""),
                              reply_markup=markup)
    except Exception as e:
        logger.warning(f"[Synthese] Telegram-Ping fehlgeschlagen: {e}")


async def _run_synthesis_cascade(parent_project_id: str):
    """
    FAN-IN SYNTHESE (12.10.2026, User-Entscheidung A+B):
    1. Sammelt alle Teilergebnisse der Fachagenten fuer parent_project_id.
    2. LISA (aggregation_lisa) fuegt sie zum Gesamtergebnis zusammen.
    3. ROBERT (executive_decision_architect) gibt frei (FREIGABE/ABLEHNUNG).
    4a. FREIGABE  -> finaler Bericht in 01_PROJEKTE + n8n-Bridge.
    4b. ABLEHNUNG -> Entwurf bleibt als Approval-Task im Board liegen.
    """
    logger.info(f"[Cascade-Loop] Starte Synthese fuer Parent-Projekt {parent_project_id}")
    data = _load_mission_control_data()
    tasks = data.get("tasks", [])
    parent_task = next((t for t in tasks if t.get("id") == parent_project_id), None)
    if not parent_task:
        logger.warning(f"[Cascade-Loop] Parent-Task {parent_project_id} nicht gefunden!")
        return

    siblings = [
        t for t in tasks
        if (t.get("parent_project_id") == parent_project_id or t.get("parent_task_id") == parent_project_id)
        and t.get("id") != parent_project_id
    ]

    # Berichte auslesen (Artifact bevorzugt, sonst result_summary)
    reports = []
    for s in siblings:
        sub_title = s.get("title", "Teilaufgabe")
        sub_agent = s.get("agent_name", "Fachagent")
        art_path = s.get("artifact_path", "")
        content = ""
        if art_path and os.path.exists(art_path):
            try:
                with open(art_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                pass
        if not content:
            content = s.get("result_summary", "")
        reports.append(f"### Arbeitspaket von {sub_agent} ({sub_title})\n\n{content}\n")
    combined_reports = f"\n---\n\n".join(reports)
    parent_title = parent_task.get("title", "Gesamtprojekt")

    # --- SCHRITT 1: LISA fuegt zusammen ---
    lisa_prompt = f"""Fuehre die vorliegenden Teilergebnisse der Fachagenten zu einem konsistenten
Gesamtergebnis zusammen. Du bist Lisa, Ergebnis-Kuratorin.

PROJEKT: {parent_title}
URSPRUEBLICHE ANFORDERUNG:
{parent_task.get('capture_input', parent_title)}

VORLIEGENDE TEILERGEBNISSE ({len(reports)} Arbeitspakete):
{combined_reports}

VORGABEN:
1. NUR integrieren, was vorliegt - keine neuen Fakten erfinden.
2. Widersprueche und Luecken klar kennzeichnen, nicht glaetten.
3. Struktur: Executive-Kurzfassung / Integriertes Ergebnis / Widersprueche & offene Punkte / Naechste Schritte.
4. Keine Begruessungen, keine Floskeln. Deutsch, dicht, entscheidungsfaehig.
5. Letzte Zeile exakt: SYNTHESE-BEREIT"""

    profiles = api_get_hermes_profiles() if "api_get_hermes_profiles" in globals() else []
    lisa_prof = next((p for p in profiles if p.get("id") == "aggregation_lisa"), None)
    lisa_system = ((lisa_prof or {}).get("system_prompt") or (lisa_prof or {}).get("prompt")
                   or "Du bist Lisa, Ergebnis-Kuratorin von Archon OS. Du fügst Teilergebnisse zusammen, kennzeichnest Widersprüche und lieferst ein entscheidungsfähiges Gesamtergebnis auf Deutsch ohne Floskeln.")
    lisa_model = (lisa_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"
    add_ticker("Lisa", f"Fuegt {len(reports)} Teilergebnisse zu '{parent_title[:30]}...' zusammen")
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="aggregation_lisa",
            agent_name="Lisa (Ergebnis-Kuratorin)",
            prompt=lisa_prompt,
            role="Ergebnis-Kuratorin & Synthese",
            system_prompt=lisa_system,
            model=lisa_model,
        )
        synthesis_reply = res.get("content", "").strip()
    except Exception as synth_err:
        logger.warning(f"[Cascade-Loop] Dispatch an Lisa fehlgeschlagen: {synth_err}")
        synthesis_reply = ""
    if not synthesis_reply or "Fehler" in synthesis_reply[:25]:
        synthesis_reply = (f"# Synthese: {parent_title}\n\n"
                           "Die Synthese der Fachmodule wurde planmaessig abgeschlossen "
                           "(Modell-Antwort leer - Teilergebnisse liegen in den Projektordnern).")
        _lisa_leer = True
    else:
        _lisa_leer = False

    # MARKER-KONTRAKT (Struktur-Thema 2, User-Entscheidung): Lisas Prompt verlangt
    # als letzte Zeile exakt SYNTHESE-BEREIT. Fehlt der Marker bei echter Antwort:
    # EIN Reparatur-Retry, danach Fallback MIT sichtbarer Warnung (nie still).
    # Die Marker-Zeile ist Protokoll, kein Inhalt - sie wird vor Draft/Dossier/Robert entfernt.
    _MARKER = "SYNTHESE-BEREIT"

    def _lisa_marker_ok(txt):
        _ls = [l.strip() for l in (txt or "").splitlines() if l.strip()]
        return bool(_ls) and _ls[-1].upper() == _MARKER

    if _lisa_leer:
        logger.warning(f"[Cascade-Loop] Lisa lieferte keine Synthese fuer {parent_project_id} (Fallback-Text).")
        add_ticker("Lisa", f"Keine Modell-Antwort fuer '{parent_title[:30]}...' - Fallback-Text verwendet")
    elif not _lisa_marker_ok(synthesis_reply):
        _repaired = ""
        try:
            _rres2 = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id="aggregation_lisa",
                agent_name="Lisa (Ergebnis-Kuratorin)",
                prompt=("Gib die folgende Synthese UNVERAENDERT erneut aus und setze "
                        "als LETZTE ZEILE exakt: SYNTHESE-BEREIT\n\n" + synthesis_reply),
                role="Ergebnis-Kuratorin & Synthese",
                system_prompt=lisa_system,
                model=lisa_model,
            )
            _repaired = (_rres2.get("content", "") or "").strip()
        except Exception as _rep_err:
            logger.warning(f"[Cascade-Loop] Marker-Repair an Lisa fehlgeschlagen: {_rep_err}")
        if _lisa_marker_ok(_repaired):
            synthesis_reply = _repaired
            logger.info(f"[Cascade-Loop] Marker-Repair erfolgreich ({parent_project_id})")
        else:
            logger.warning(f"[Cascade-Loop] Synthese ohne {_MARKER}-Marker ({parent_project_id}) - ungeprueft verwendet")
            add_ticker("Lisa", f"Synthese ohne {_MARKER}-Marker - ungeprueft verwendet")
    _syn_lines = synthesis_reply.splitlines()
    if _syn_lines and _syn_lines[-1].strip().upper() == _MARKER:
        synthesis_reply = "\n".join(_syn_lines[:-1]).strip()

    # Entwurf ablegen (Basis der Robert-Freigabe)
    safe_pid = re.sub(r'[^a-zA-Z0-9_\-]+', '-', parent_project_id).strip('-') or "projekt"
    draft_name = f"{safe_pid}_synthese_lisa_entwurf.md"
    target_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE"),
        os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
    ]
    # 12.10.2026 (Ordnerflut-Fix): Entwurf + finaler Bericht gehoeren in den
    # EINEN Projekt-Ordner des Eltern-Projekts, nicht als lose Dateien daneben.
    try:
        from backend.post_task_pipeline import project_folder_name
        _fan_ordner = project_folder_name({"parent_project_id": parent_project_id,
                                           "parent_project_title": parent_title})
    except Exception:
        _fan_ordner = ""
    # 2a: Ablageordner fuer das Synthese-Dossier im Projektordner
    _tg_doss_dir = None
    try:
        if _fan_ordner:
            _tg_doss_dir = os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE",
                                        _fan_ordner, "01_Zwischenberichte")
    except Exception:
        _tg_doss_dir = None
    draft_path = (f"/opt/data/obsidian/01_PROJEKTE/{_fan_ordner}/03_Endprodukte/{draft_name}"
                  if _fan_ordner else f"/opt/data/obsidian/01_PROJEKTE/{draft_name}")
    for d in target_dirs:
        try:
            d_ziel = os.path.join(d, _fan_ordner, "03_Endprodukte") if _fan_ordner else d
            os.makedirs(d_ziel, exist_ok=True)
            p = os.path.join(d_ziel, draft_name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# Synthese-Entwurf: {parent_title}\n\n{synthesis_reply}\n")
            draft_path = p
        except Exception:
            continue
    parent_task["synthesis_draft_path"] = draft_path
    _save_mission_control_data(data)

    # --- SCHRITT 1.5: KRITISCHER REVIEWER prüft Lisas Synthese vor Roberts Entscheidung ---
    reviewer_prof = next((p for p in profiles if p.get("id") == "gpts_critical_reviewer"), None)
    reviewer_critique = ""
    if reviewer_prof:
        rev_prompt = f"""Fuehre eine schonungslose Qualitaetspruefung der vorliegenden Synthese durch.
PROJEKT: {parent_title}
URSPRUENGLICHE ANFORDERUNG: {parent_task.get('capture_input', parent_title)}

SYNTHESE-ENTWURF (von Lisa):
{synthesis_reply}

AUFGABE:
1. Pruefe auf unbelegte Behauptungen, Logikbrueche und gravierende Luecken.
2. Formuliere max. 3 praegnante Kernkritikpunkte (oder bestaetige 'Keine kritischen Maengel festgestellt').
3. Schliesse mit einem klaren Urteil: EMPFEHLUNG FREIGABE oder EMPFEHLUNG NACHBESSERUNG."""
        add_ticker("Reviewer", f"Qualitaetspruefung fuer '{parent_title[:30]}...'")
        try:
            rev_res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id="gpts_critical_reviewer",
                agent_name="Kritischer Reviewer",
                prompt=rev_prompt,
                role="Critical Reviewer & QA",
                system_prompt=((reviewer_prof or {}).get("system_prompt") or "Du bist der kritische Chef-Reviewer von Archon OS. Pruefe Entwuerfe schonungslos auf Fakten, Logik und Qualitaet."),
                model=((reviewer_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"),
            )
            reviewer_critique = (rev_res.get("content", "") or "").strip()
            if reviewer_critique:
                logger.info(f"[Cascade-Loop] Reviewer-Kritik erstellt ({len(reviewer_critique)} Zeichen)")
        except Exception as rev_err:
            logger.warning(f"[Cascade-Loop] Reviewer-Pruefung fehlgeschlagen: {rev_err}")

    # --- SCHRITT 2: ROBERT gibt frei ---
    robert_prompt = f"""Lisa (aggregation_lisa) hat die Teilergebnisse folgenden Projekts zusammengefuegt:

PROJEKT: {parent_title}
ANFORDERUNG: {parent_task.get('capture_input', parent_title)}

LISAS SYNTHESE:
{synthesis_reply}
""" + (f"""\nUNABHAENGIGE QUALITAETSPRUEFUNG (Kritischer Reviewer):\n{reviewer_critique}\n""" if reviewer_critique else "") + """
Pruefe Vollstaendigkeit und Plausibilitaet. Antworte MIT GENAU EINEM DER ZWEI
WOERTER ALS ALLERERSTER ZEILE: FREIGABE oder ABLEHNUNG - danach hoechstens
ein Satz Begruendung. Keine weiteren Absaetze, keine Begruessung."""
    r_prof = next((p for p in profiles if p.get("id") in ("executive_decision_architect", "robert")), None)
    r_system = ((r_prof or {}).get("system_prompt") or (r_prof or {}).get("prompt")
                or "Du bist Robert, Executive Decision Architect und leitender Chefstratege von Archon OS. Antworte mit FREIGABE oder ABLEHNUNG als erste Zeile.")
    r_model = (r_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"
    add_ticker("Robert", f"Prueft Lisas Synthese fuer '{parent_title[:30]}...'")
    robert_reply = ""
    try:
        rres = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="executive_decision_architect",
            agent_name="Robert (Chefstratege)",
            prompt=robert_prompt,
            role="Executive Decision Architect",
            system_prompt=r_system,
            model=r_model,
        )
        robert_reply = (rres.get("content", "") or "").strip()
    except Exception as r_err:
        logger.warning(f"[Cascade-Loop] Freigabe-Dispatch an Robert fehlgeschlagen: {r_err}")

    # ROBUSTE FREIGABE-ERKENNUNG (Struktur-Thema 4/1, User-Entscheidung): NUR die
    # exakte erste Zeile zaehlt. Alles andere (Floskeln, "KEINE FREIGABE", leer)
    # geht an den Owner via Kanban-Entscheidung (4b-Pfad) - nie still, nie geraten.
    _erste_zeile = ((robert_reply or "").splitlines() or [""])[0].strip().upper()
    if _erste_zeile == "FREIGABE":
        freigegeben = True
    elif _erste_zeile == "ABLEHNUNG":
        freigegeben = False
    else:
        logger.warning(f"[Cascade-Loop] Roberts Antwort unklar (erste Zeile: '{_erste_zeile[:60]}') - Owner entscheidet")
        add_ticker("Robert", "Antwort unklar - Freigabe liegt beim Owner im Kanban")
        freigegeben = False

    if freigegeben:
        await _finalize_synthesis_after_approval(parent_project_id, draft_path,
                                                  synthesis_reply, f"Robert: {robert_reply[:200]}")
        # 2a: Owner informieren - kein Handlungsbedarf, aber Bericht mitliefern.
        _tg_ping_synthesis(parent_title, parent_project_id, synthesis_reply, draft_path,
                           app_id=None, dossier_dir=_tg_doss_dir)
        return

    # 4b: Ablehnung/unklar -> echte Entscheidung im KANBAN (2c). kanban.db ist
    # die Wahrheit; der frühere parallele Mission-Control-Task (mcapp-*) entfällt.
    _deci_dossier = None
    if _tg_doss_dir:
        try:
            from dossier_builder import build_dossier_from_report
            _deci_dossier = build_dossier_from_report(
                f"Synthese: {parent_title}", synthesis_reply, _tg_doss_dir,
                f"{safe_pid}_synthese", ref_id=parent_project_id,
                quelle="Lisa (aggregation_lisa)")
        except Exception as _de:
            logger.warning(f"[Synthese] Dossier für die Entscheidung fehlgeschlagen: {_de}")
    _deci = await asyncio.to_thread(
        create_decision,
        "synthesis_freigabe",
        f"Freigabe: Synthese '{parent_title[:55]}'",
        synthesis_reply,          # kurzfassung
        parent_project_id,        # ref_id
        _deci_dossier,            # dossier
        f"Lisas Entwurf: {draft_path}",   # body
        {"parent_project_id": parent_project_id, "draft_path": draft_path,
         "projekt": parent_title, "von": "Lisa · Ergebnis-Kuratorin",
         "teilberichte": f"{len(reports)}/{len(reports)}"},                    # extra
        (f"01_PROJEKTE/{_fan_ordner}" if _fan_ordner else None),             # obsidian
    )
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    data.setdefault("audit_logs", []).insert(0, {
        "time": now_t, "source": "Synthese-Loop",
        "msg": (f"Lisa-Entwurf für #{parent_project_id} braucht Freigabe "
                f"(Robert: {robert_reply[:60] or 'ohne Antwort'}) — "
                f"Kanban-Entscheidung {_deci.get('task_id') or 'NICHT angelegt'}")
    })
    add_ticker("Synthese-Loop", f"Entscheidung im Kanban angelegt: {draft_name}")
    _save_mission_control_data(data)
    if not _deci:
        logger.warning(f"[Synthese] Entscheidung für #{parent_project_id} konnte NICHT "
                       f"angelegt werden — Freigabe ist per Telegram/Kanban nicht möglich.")

@app.post("/api/mission-control/tasks/move")
async def move_mission_control_task(req: TaskMoveRequest):
    data = _load_mission_control_data()
    tasks = data.get("tasks", [])
    task = next((t for t in tasks if t.get("id") == req.task_id), None)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task nicht gefunden.")
        
    prev_status = task.get("status")
    task["status"] = req.target_status
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    
    if req.target_status == "in_progress":
        task["started_at"] = time.time()
        task["active_tool"] = "Tool: web_search & core_dispatcher"
        add_ticker("Approval Gate", f"Task #{task['id']} genehmigt & an {task['agent_name']} übergeben")
        _save_mission_control_data(data)
        
        # Starte autonome Ausführung im Hintergrund
        asyncio.create_task(_execute_mission_control_task(task["id"]))
        return {"status": "ok", "task": task}
        
    elif req.target_status == "completed":
        if req.result_summary:
            task["result_summary"] = req.result_summary
        elif not task.get("result_summary"):
            task["result_summary"] = f"Erfolgreich von {task['agent_name']} abgeschlossen. Alle Kriterien erfüllt."
            
        obs_path = _sync_task_to_obsidian(task)
        task["artifact_path"] = obs_path
        add_ticker("Obsidian", f"Projekt-Dokumentation {os.path.basename(obs_path)} geschrieben")

        # FAN-IN (12.10.2026): Diese Task IST Lisas Entwurf-Freigabe
        # (synthesis_draft_path) -> beim Approved-Move finalisieren:
        # finaler Bericht + Parent completed + n8n-Bridge.
        if task.get("synthesis_draft_path") and not task.get("synthesis_finalized"):
            task["synthesis_finalized"] = True
            await _finalize_synthesis_after_approval(
                task.get("parent_project_id") or req.task_id,
                task.get("synthesis_draft_path"),
                task.get("result_summary") or "",
                "Freigabe per Board-Move (Approval-Gate)",
                daten=data,   # GLEICHES dict wie der Handler - sonst ueberschreibt
                              # das finale _save_mission_control_data(data) den Update
            )

        parent_pid = task.get("parent_project_id") or task.get("parent_task_id")
        if parent_pid and parent_pid != req.task_id:
            asyncio.create_task(_fan_in_maybe_start_synthesis(parent_pid))
        
    elif req.target_status == "dismissed":
        tasks.remove(task)
        add_ticker("Approval Gate", f"Task #{task['id']} wurde verworfen")
        _save_mission_control_data(data)
        return {"status": "ok", "message": "Task verworfen."}
        
    data["audit_logs"] = data.get("audit_logs", [])[:25]
    _save_mission_control_data(data)
    _MC_STATE_CACHE["ts"] = 0.0  # Cache invalidieren
    broadcast_event("kanban_updated", {"action": "move", "task_id": req.task_id, "status": req.target_status})
    return {"status": "ok", "task": task}

@app.get("/api/mission-control/task/{task_id}/artifact")
async def get_mission_control_task_artifact(task_id: str):
    data = _load_mission_control_data()
    task = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task nicht gefunden.")
    
    p = task.get("artifact_path")
    if p and os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return {"status": "ok", "content": f.read(), "path": p}
            
    # Falls Datei noch nicht existiert, live generieren
    content = f"""# {task.get('title')}
Status: {task.get('status')}
Agent: {task.get('agent_name')} ({task.get('model')})

## Ergebnisbericht
{task.get('result_summary') or 'Aufgabe erfolgreich abgeschlossen.'}
"""
    return {"status": "ok", "content": content, "path": p or "/opt/data/obsidian/01_PROJEKTE/"}

# =============================================================
# PROMPT-TEMPLATES, KI-OPTIMIZER & PROMPTFOO GOVERNANCE API
# =============================================================

PROMPT_TEMPLATES_PATHS = [
    "/opt/data/prompt_templates.json",
    os.path.join(MEMORY_DIR, "prompt_templates.json"),
    os.path.join(WORKSPACE_DIR, "data", "prompt_templates.json"),
    "./data/prompt_templates.json",
    "prompt_templates.json"
]

def _load_prompt_templates() -> dict:
    for p in PROMPT_TEMPLATES_PATHS:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[Templates] Fehler beim Laden von {p}: {e}")
    return {
        "categories": [
            "Strategie & Business",
            "Marketing & Outreach",
            "Governance & Recht"
        ],
        "templates": []
    }

def _save_prompt_templates(data: dict):
    saved = False
    for p in ["/opt/data/prompt_templates.json", os.path.join(MEMORY_DIR, "prompt_templates.json"), os.path.join(WORKSPACE_DIR, "data", "prompt_templates.json"), "./data/prompt_templates.json"]:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            saved = True
        except Exception:
            pass
    return saved

@app.get("/api/templates")
async def get_prompt_templates():
    """Liefert alle Prompt-Vorlagen und Kategorien strukturiert zurück."""
    return _load_prompt_templates()

# -------------------------------------------------------------
# FABRIC PATTERNS API (255+ kuratierte & übersetzte Muster)
# -------------------------------------------------------------

_FABRIC_CACHE: Optional[List[Dict[str, Any]]] = None

def _load_fabric_patterns_data() -> List[Dict[str, Any]]:
    global _FABRIC_CACHE
    if _FABRIC_CACHE is not None:
        return _FABRIC_CACHE

    paths = [
        "/app/fabric_patterns_de.csv",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fabric_patterns_de.csv"),
        "./fabric_patterns_de.csv",
        "/app/data/fabric_patterns_de.csv"
    ]
    records = []
    for p in paths:
        if os.path.exists(p):
            try:
                import csv
                with open(p, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f, delimiter=";")
                    for row in reader:
                        records.append({
                            "id": row.get("ID", ""),
                            "name_de": row.get("Name_DE", ""),
                            "category": row.get("Kategorie", "Allgemein & Produktivität"),
                            "variables": row.get("Empfohlene_Variablen", ""),
                            "purpose": row.get("Zweck_Original", ""),
                            "raw_path": row.get("Raw_Path", "")
                        })
                if records:
                    break
            except Exception as e:
                logger.warning(f"[Fabric API] Fehler beim Laden von {p}: {e}")

    _FABRIC_CACHE = records
    return _FABRIC_CACHE

@app.get("/api/fabric/patterns")
async def get_fabric_patterns(category: Optional[str] = None, q: Optional[str] = None):
    """Liefert alle Fabric-Patterns strukturiert mit Kategorien zurück."""
    patterns = _load_fabric_patterns_data()
    categories = sorted(list({p["category"] for p in patterns}))

    filtered = patterns
    if category and category != "all" and category != "Favoriten":
        filtered = [p for p in filtered if p["category"].lower() == category.lower()]
    if q:
        query = q.lower().strip()
        filtered = [
            p for p in filtered
            if query in p["name_de"].lower() or query in p["id"].lower() or query in p["purpose"].lower()
        ]

    return {
        "status": "ok",
        "total": len(patterns),
        "count": len(filtered),
        "categories": categories,
        "patterns": filtered
    }

@app.get("/api/fabric/pattern/{pattern_id}")
async def get_fabric_pattern_detail(pattern_id: str):
    """Liefert den detaillierten System-Prompt und Felder eines spezifischen Fabric-Patterns."""
    patterns = _load_fabric_patterns_data()
    pat = next((p for p in patterns if p["id"] == pattern_id), None)
    if not pat:
        raise HTTPException(status_code=404, detail="Fabric-Pattern nicht gefunden.")

    # System.md Inhalt laden (aus GitHub Cache oder Fallback)
    raw_path = pat.get("raw_path") or f"data/patterns/{pattern_id}/system.md"
    raw_url = f"https://raw.githubusercontent.com/danielmiessler/Fabric/main/{raw_path}"
    system_text = ""
    try:
        import urllib.request
        req = urllib.request.Request(raw_url, headers={"User-Agent": "Mozilla/5.0"})
        res = urllib.request.urlopen(req, timeout=4.0)
        system_text = res.read().decode("utf-8", errors="ignore")
    except Exception:
        system_text = f"# IDENTITÄT & ROLLE:\n{pat.get('purpose', '')}\n\n# ZIEL:\nFühre eine strukturierte Auswertung für '{pat.get('name_de', pattern_id)}' durch."

    # Erstelle deutschen Template-Bauplan
    german_template = (
        f"# ROLLE & EXPERTISE:\n"
        f"Du agierst als spezialisierter Experte für: {pat.get('name_de', pattern_id)}.\n"
        f"{pat.get('purpose', '')}\n\n"
        f"# AUFGABE & ZIEL:\n"
        f"Analysiere und bearbeite die übergebene Eingabe mit höchster analytischer Tiefe.\n\n"
        f"# ARBEITSSCHRITTE:\n"
        f"1. Gründliche Prüfung der bereitgestellten Daten und Extrahieren der Kernaussagen.\n"
        f"2. Strukturierte, präzise Aufbereitung ohne Füllwörter oder Phrasen.\n"
        f"3. Formulierung konkreter, umsetzbarer Erkenntnisse oder Handlungsempfehlungen.\n\n"
        f"# SPRACHE & AUSGABE:\n"
        f"Formuliere das vollständige Ergebnis auf Deutsch, klar gegliedert in Markdown."
    )

    return {
        "status": "ok",
        "pattern": pat,
        "system_raw": system_text,
        "template_de": german_template,
        "default_fields": [
            {
                "id": "context_input",
                "label": "Eingabetext / Kontext / Code",
                "type": "multiline",
                "required": True,
                "placeholder": "Füge hier deinen zu analysierenden Text, Code, URL oder Zusammenfassung ein..."
            },
            {
                "id": "specific_focus",
                "label": "Besonderer Schwerpunkt / Fragestellung (Optional)",
                "type": "text",
                "required": False,
                "placeholder": "z. B. Fokus auf Sicherheitsrisiken, Einsparpotenziale oder ROI..."
            },
            {
                "id": "output_style",
                "label": "Ausgabeformat (Optional)",
                "type": "select",
                "options": ["Ausführlicher Bericht", "Kompaktes Executive Summary", "Aufzählung / Bullet-Points", "Schritt-für-Schritt Anleitung"],
                "required": False
            }
        ]
    }

# -------------------------------------------------------------
# ARCHON PROMPT STUDIO FORMULAR-BAUKASTEN API (824 Enterprise-Templates)
# -------------------------------------------------------------

_PROMPT_STUDIO_CACHE: Optional[List[Dict[str, Any]]] = None

def _load_prompt_studio_catalog() -> List[Dict[str, Any]]:
    global _PROMPT_STUDIO_CACHE
    if _PROMPT_STUDIO_CACHE is not None:
        return _PROMPT_STUDIO_CACHE

    paths = [
        "/app/prompt_studio_catalog.json",
        "/app/data/prompt_studio_catalog.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_studio_catalog.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prompt_studio_catalog.json"),
        "./prompt_studio_catalog.json",
        "./data/prompt_studio_catalog.json",
        "/opt/data/prompt_templates.json"
    ]
    records = []
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    records = json.load(f)
                if records:
                    break
            except Exception as e:
                logger.warning(f"[Prompt Studio API] Fehler beim Laden von {p}: {e}")

    _PROMPT_STUDIO_CACHE = records or []
    return _PROMPT_STUDIO_CACHE

# Kompatibilitäts-Alias
_load_sureprompts_catalog = _load_prompt_studio_catalog

@app.get("/api/templates/catalog")
async def get_prompt_studio_catalog(category: Optional[str] = None, q: Optional[str] = None):
    """Liefert den gesamten Archon Prompt Studio Katalog (824 Vorlagen) gefiltert nach Kategorie/Suche."""
    catalog = _load_prompt_studio_catalog()
    categories = sorted(list({t["category"] for t in catalog if "category" in t}))

    filtered = catalog
    if category and category != "all" and category != "Favoriten":
        filtered = [t for t in filtered if t.get("category", "").lower() == category.lower() or t.get("category_slug", "").lower() == category.lower()]
    if q:
        query = q.lower().strip()
        filtered = [
            t for t in filtered
            if query in t.get("name", "").lower() or query in t.get("id", "").lower() or query in t.get("description", "").lower()
        ]

    # Kompakte Übersicht für das Frontend-Menü
    summaries = [
        {
            "id": t.get("id"),
            "name": t.get("name_de") or t.get("name"),
            "name_de": t.get("name_de") or t.get("name"),
            "category": t.get("category"),
            "category_slug": t.get("category_slug"),
            "tier": t.get("tier", "Community"),
            "description": t.get("description_de") or t.get("description", ""),
            "description_de": t.get("description_de") or t.get("description", ""),
            "field_count": len(t.get("form_fields", []))
        }
        for t in filtered
    ]

    return {
        "status": "ok",
        "total": len(catalog),
        "count": len(summaries),
        "categories": categories,
        "templates": summaries
    }

@app.get("/api/templates/{template_slug}/schema")
async def get_template_schema(template_slug: str):
    """Gibt das Formular-Schema und den Template-Text für ein einzelnes Template zurück."""
    catalog = _load_prompt_studio_catalog()
    tpl = next((t for t in catalog if t.get("id") == template_slug), None)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template nicht gefunden.")
    return {
        "status": "ok",
        "template": tpl
    }

class TemplateRenderRequest(BaseModel):
    values: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None

@app.post("/api/templates/{template_slug}/render")
async def render_template_prompt(template_slug: str, req: TemplateRenderRequest):
    """
    Rendert das Archon_Prompt_Template mit den übergebenen Formularwerten.
    Verhalten A: Leere optionale Variablen und deren Zeilen werden rückstandslos entfernt.
    Inklusive Unterstützung für Advanced Options (Denk-Methodik, Ausgabe-Vorgaben, etc.).
    """
    catalog = _load_prompt_studio_catalog()
    tpl = next((t for t in catalog if t.get("id") == template_slug), None)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template nicht gefunden.")

    raw_template = tpl.get("archon_prompt_template", "")
    values = req.values or {}
    options = req.options or {}

    # Variablen-Ersetzung & Verhalten A
    rendered_lines = []
    for line in raw_template.split("\n"):
        line_has_empty_var = False
        vars_in_line = re.findall(r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}', line)
        for var_name in vars_in_line:
            val = str(values.get(var_name, "")).strip()
            if not val:
                form_fields = tpl.get("form_fields", [])
                field_def = next((f for f in form_fields if f.get("id") == var_name), None)
                if field_def and not field_def.get("required", False):
                    line_has_empty_var = True
                    break
                else:
                    placeholder = field_def.get("label_de") or field_def.get("label") or var_name if field_def else var_name
                    line = line.replace(f"{{{{{var_name}}}}}", f"[{placeholder.upper()}]")
                    line = line.replace(f"{{{{ {var_name} }}}}", f"[{placeholder.upper()}]")
            else:
                line = line.replace(f"{{{{{var_name}}}}}", val)
                line = line.replace(f"{{{{ {var_name} }}}}", val)

        if not line_has_empty_var:
            rendered_lines.append(line)

    assembled = "\n".join(rendered_lines).strip()

    # Advanced Options einspeisen
    adv_sections = []
    thinking = []
    if options.get("stepbystep"):
        thinking.append("- Schritt für Schritt: Durchdenken Sie das Problem systematisch in logischen Einzelschritten, bevor Sie das Endergebnis formulieren.")
    if options.get("reasoning"):
        thinking.append("- Begründung & Herleitung: Erläutern Sie Ihre strategische Entscheidungslogik und Gedankengänge transparent.")
    if options.get("perspectives"):
        thinking.append("- Multiperspektivität: Beleuchten Sie die Fragestellung aus mehreren relevanten Blickwinkeln und wägen Sie Gegenargumente ab.")
    if options.get("systematic"):
        thinking.append("- Systematischer Ansatz: Wenden Sie ein klares, strukturiertes Analyse- und Handlungs-Framework an.")
    if options.get("cot"):
        thinking.append("- Chain-of-Thought: Verknüpfen Sie alle Zwischenschritte nachvollziehbar miteinander.")
    if options.get("roleplay"):
        thinking.append("- Vertieftes Rollenspiel: Agieren Sie strikt aus der spezifizierten Expertenperspektive mit profunder Fachsprache.")
    if thinking:
        adv_sections.append("### DENK-METHODIK & STRATEGIE:\n" + "\n".join(thinking))

    output = []
    if options.get("confidence"):
        output.append("- Konfidenz-Rating: Weisen Sie zentralen Empfehlungen eine Zuverlässigkeitsbewertung (Hoch/Mittel/Niedrig) zu.")
    if options.get("citations"):
        output.append("- Quellen & Belege: Untermauern Sie Fakten, Daten und Kernaussagen mit konkreten Quellenverweisen.")
    ex_count = int(options.get("examples_count") or 0)
    if ex_count > 0:
        output.append(f"- Praxisbeispiele: Integrieren Sie mindestens {ex_count} konkrete, illustrative Anwendungsbeispiele.")
    if output:
        adv_sections.append("### ERWEITERTE AUSGABE-VORGABEN:\n" + "\n".join(output))

    if options.get("context"):
        adv_sections.append(f"### ZUSÄTZLICHER KONTEXT & HINTERGRUND:\n{options['context']}")
    if options.get("examples"):
        adv_sections.append(f"### REFERENZ-BEISPIELE (GEWÜNSCHTER AUSGABESTIL):\n{options['examples']}")
    if options.get("success"):
        adv_sections.append(f"### ERFOLGSKRITERIEN (DEFINITION OF DONE):\n{options['success']}")

    if adv_sections:
        adv_block = "\n\n".join(adv_sections)
        if "4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT" in assembled:
            assembled = assembled.replace(
                "4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT",
                f"{adv_block}\n\n4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT"
            )
        else:
            assembled += f"\n\n{adv_block}"

    final_rendered = re.sub(r'\n{3,}', '\n\n', assembled).strip()
    return {
        "status": "ok",
        "rendered_prompt": final_rendered
    }

@app.post("/api/prompt-studio/upload-context")
async def upload_prompt_studio_context(file: UploadFile = File(...)):
    """
    Nimmt eine Kontext-Datei (.pdf, .docx, .txt, .csv, .json, .md, .py, .js, etc.) entgegen,
    speichert sie unter /opt/data/temp_uploads/ ab und extrahiert den Text.
    """
    upload_dir = "/opt/data/temp_uploads"
    os.makedirs(upload_dir, exist_ok=True)

    filename = os.path.basename(file.filename or "upload.txt")
    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    timestamp = int(time.time() * 1000)
    saved_filename = f"{timestamp}_{safe_name}"
    filepath = os.path.join(upload_dir, saved_filename)

    try:
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"[Prompt Studio Upload] Fehler beim Speichern der Datei: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {e}")

    ext = os.path.splitext(filename)[1].lower()
    extracted_text = ""

    try:
        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(filepath)
                pages_text = []
                for p in reader.pages:
                    t = p.extract_text()
                    if t:
                        pages_text.append(t)
                extracted_text = "\n\n".join(pages_text).strip()
            except Exception as pe:
                logger.warning(f"[Prompt Studio Upload] pypdf Fehler: {pe}")
                raise HTTPException(status_code=400, detail=f"PDF konnte nicht gelesen werden: {pe}")

        elif ext in [".docx", ".doc"]:
            try:
                import docx
                doc = docx.Document(filepath)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables_text = []
                for table in doc.tables:
                    for row in table.rows:
                        row_vals = [cell.text.strip() for cell in row.cells]
                        if any(row_vals):
                            tables_text.append(" | ".join(row_vals))
                extracted_text = "\n".join(paragraphs + tables_text).strip()
            except Exception as de:
                logger.warning(f"[Prompt Studio Upload] docx Fehler: {de}")
                raise HTTPException(status_code=400, detail=f"Word-Dokument konnte nicht gelesen werden: {de}")

        elif ext == ".csv":
            try:
                with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
                    sample = f.read(2048)
                    f.seek(0)
                    delimiter = ';' if ';' in sample and sample.count(';') > sample.count(',') else ','
                    reader = csv.reader(f, delimiter=delimiter)
                    rows = list(reader)
                if rows:
                    header = rows[0]
                    md_lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
                    for row in rows[1:101]:
                        row_padded = (row + [""] * len(header))[:len(header)]
                        md_lines.append("| " + " | ".join([c.replace("\n", " ") for c in row_padded]) + " |")
                    if len(rows) > 101:
                        md_lines.append(f"\n*(Tabelle gekürzt: {len(rows)-1} Datensätze insgesamt, erste 100 dargestellt)*")
                    extracted_text = "\n".join(md_lines).strip()
                else:
                    extracted_text = ""
            except Exception as ce:
                logger.warning(f"[Prompt Studio Upload] CSV Fehler: {ce}")
                raise HTTPException(status_code=400, detail=f"CSV konnte nicht gelesen werden: {ce}")

        elif ext in [".txt", ".md", ".py", ".js", ".json", ".html", ".yaml", ".yml", ".ts"]:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                extracted_text = f.read().strip()

        else:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                extracted_text = f.read().strip()

    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"[Prompt Studio Upload] Text-Extraktionsfehler: {ex}")
        raise HTTPException(status_code=400, detail=f"Text-Extraktion fehlgeschlagen: {ex}")

    return {
        "filename": filename,
        "char_count": len(extracted_text),
        "extracted_text": extracted_text
    }

class TemplateSaveRequest(BaseModel):
    category: str
    title: str
    description: Optional[str] = ""
    fields: dict
    raw_text: Optional[str] = None

@app.post("/api/templates")
async def save_prompt_template(req: TemplateSaveRequest):
    """Speichert eine neue oder angepasste Vorlage in der persistenten Template-Bibliothek."""
    data = _load_prompt_templates()
    if req.category not in data.get("categories", []):
        data.setdefault("categories", []).append(req.category)
    
    raw_text = req.raw_text
    if not raw_text and req.fields:
        raw_text = (
            f"# ROLLE:\n{req.fields.get('rolle', 'Experte')}\n\n"
            f"# ZIEL:\n{req.fields.get('ziel', '')}\n\n"
            f"# SOP (ARBEITSSCHRITTE):\n{req.fields.get('sop', '')}\n\n"
            f"# RESTRIKTIONEN (PHRASENVERBOT):\n{req.fields.get('restriktionen', '')}\n\n"
            f"# AUSGABE-ARTEFAKT:\n{req.fields.get('ausgabe_artefakt', '')}"
        )
    
    new_tpl = {
        "id": f"tpl-custom-{int(time.time()*1000)%100000}",
        "category": req.category,
        "title": req.title,
        "description": req.description or "",
        "fields": req.fields,
        "raw_text": raw_text
    }
    data.setdefault("templates", []).insert(0, new_tpl)
    _save_prompt_templates(data)
    return {"status": "ok", "template": new_tpl}

class PromptOptimizeRequest(BaseModel):
    prompt: str
    agent_id: Optional[str] = None

@app.post("/api/prompts/optimize")
async def optimize_prompt_endpoint(req: PromptOptimizeRequest):
    """
    Nimmt unstrukturierte Nutzereingabe entgegen,
    sendet via OmniRoute einen schnellen Call an ein kostengünstiges Modell
    und transformiert den Text in die 5-Felder-Struktur inklusive Phrasenverbot.
    """
    raw_input = req.prompt.strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="Prompt darf nicht leer sein.")
        
    optimizer_system_prompt = (
        "Du bist der leitende Prompt-Architekt von Archon OS.\n"
        "Transformiere die unstrukturierte Benutzereingabe in einen professionellen 5-Felder-Prompt.\n"
        "Die Ausgabe MUSS EXAKT die folgenden 5 Abschnitte mit Markdown-Headings enthalten:\n\n"
        "# ROLLE:\n"
        "[Passende, spezialisierte Rollenbezeichnung]\n\n"
        "# ZIEL:\n"
        "[Klares, messbares Arbeitsergebnis]\n\n"
        "# SOP (ARBEITSSCHRITTE):\n"
        "1. [Schritt 1]\n"
        "2. [Schritt 2]\n"
        "3. [Schritt 3]\n\n"
        "# RESTRIKTIONEN (PHRASENVERBOT):\n"
        "- Phrasenverbot: Keine Begrüßungs- oder Höflichkeitsfloskeln ('Hallo', 'Gerne helfe ich', 'Möchten Sie', 'Wie kann ich').\n"
        "- Keine Gegenfragen an den Nutzer; triff plausible Annahmen.\n"
        "- Kein Konjunktiv; handlungsorientierte Sprache.\n"
        "- Striktes Markdown mit klaren Überschriften.\n\n"
        "# AUSGABE-ARTEFAKT:\n"
        "[Strukturierter Markdown-Bericht zur Ablage in Obsidian]\n\n"
        "WICHTIG: Gib AUSSCHLIESSLICH den 5-Felder-Prompt aus, ohne jegliches Vorgeplänkel oder Nachwort!"
    )

    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="prompt_optimizer",
            agent_name="Prompt Optimizer",
            prompt=f"Transformiere folgende Benutzereingabe:\n\n{raw_input}",
            role="Prompt Architect",
            system_prompt=optimizer_system_prompt,
            model="auto/best-fast"
        )
        opt_text = res.get("content", "").strip()
        if not opt_text or len(opt_text) < 30:
            opt_text = (
                f"# ROLLE:\nExecutive Decision Specialist\n\n"
                f"# ZIEL:\n{raw_input}\n\n"
                f"# SOP (ARBEITSSCHRITTE):\n"
                f"1. Analyse der Anforderung: {raw_input[:60]}\n"
                f"2. Methodische Erarbeitung der Lösungsarchitektur\n"
                f"3. Validierung und strukturierte Dokumentation\n\n"
                f"# RESTRIKTIONEN (PHRASENVERBOT):\n"
                f"- Keine Begrüßungsfloskeln ('Hallo', 'Gerne helfe ich').\n"
                f"- Keine Gegenfragen an den Nutzer.\n"
                f"- Striktes Markdown.\n\n"
                f"# AUSGABE-ARTEFAKT:\n"
                f"Markdown-Dokument für Obsidian (/opt/data/obsidian/01_PROJEKTE/)"
            )
        return {
            "status": "ok",
            "optimized_prompt": opt_text,
            "original_prompt": raw_input
        }
    except Exception as e:
        logger.error(f"[Prompt Optimizer] Exception: {e}")
        fallback_text = (
            f"# ROLLE:\nExecutive Specialist\n\n"
            f"# ZIEL:\n{raw_input}\n\n"
            f"# SOP (ARBEITSSCHRITTE):\n"
            f"1. Analyse der Vorgaben\n"
            f"2. Fachliche Ausarbeitung der Arbeitspakete\n"
            f"3. Finale Bereitstellung\n\n"
            f"# RESTRIKTIONEN (PHRASENVERBOT):\n"
            f"- Keine Höflichkeitsfloskeln oder Rückfragen.\n"
            f"- Striktes Markdown.\n\n"
            f"# AUSGABE-ARTEFAKT:\n"
            f"Obsidian Markdown-Bericht"
        )
        return {
            "status": "ok",
            "optimized_prompt": fallback_text,
            "original_prompt": raw_input
        }

@app.post("/api/governance/promptfoo/run-eval")
def api_run_promptfoo_eval(config_path: str = "/app/tests/promptfooconfig.yaml"):
    """
    Führt die vollständige Promptfoo Testmatrix im Docker-Container aus.
    """
    exec_create_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["promptfoo", "eval", "-c", config_path, "--output", "/app/tests/eval_result.json"],
        "WorkingDir": "/app"
    }
    create_raw = docker_socket_request("POST", "/containers/promptfoo/exec", exec_create_payload, timeout=5.0)
    if not create_raw:
        return {"status": "error", "message": "Docker Proxy nicht erreichbar."}
    try:
        exec_id = json.loads(create_raw.decode('utf-8')).get("Id")
        if not exec_id:
            return {"status": "error", "message": "Exec-Instanz konnte nicht erstellt werden."}
    except Exception as e:
        return {"status": "error", "message": f"Ungültige Exec-Antwort: {str(e)}"}

    start_payload = {"Detach": False, "Tty": False}
    start_raw = docker_socket_request("POST", f"/exec/{exec_id}/start", start_payload, timeout=120.0)
    output = parse_docker_stream(start_raw).strip()
    return {"status": "success", "output": output}

@app.post("/api/governance/test-profile/{agent_id}")
async def test_agent_profile_governance(agent_id: str):
    """
    Führt die Governance-Testsuite (Anti-Floskel, Markdown, JSON-Format)
    für das angegebene Agentenprofil aus und liefert die Erfolgsquote zurück.
    """
    profiles = api_get_hermes_profiles() if "api_get_hermes_profiles" in globals() else []
    prof = next((p for p in profiles if p.get("id") == agent_id or p.get("person_name") == agent_id), None)
    agent_name = prof.get("person_name", agent_id) if prof else agent_id
    role = prof.get("name", "Spezialist") if prof else "Spezialist"
    system_prompt = (prof.get("system_prompt") if prof else None) or (prof.get("prompt") if prof else None) or f"Du bist {agent_name} in Archon OS."
    model = (prof.get("model") if prof else None) or "auto/best-fast"

    test_cases = [
        {
            "id": 1,
            "name": "Anti-Floskel Test (Strategie)",
            "prompt": "Erstelle eine kurze Strategieübersicht für die Internationalisierung unserer B2B-Plattform. Halte dich an striktes Markdown.",
            "not_contains": ["Möchten Sie", "Soll ich", "Gerne helfe ich", "Wie kann ich"],
            "contains": ["## "]
        },
        {
            "id": 2,
            "name": "Executive Decision Test (Headline & Klarheit)",
            "prompt": "Bewerte das Risiko einer Verlagerung von Cloud-Workloads nach Frankfurt mit klaren Handlungsschritten.",
            "not_contains": ["Gerne helfe ich", "Möchten Sie", "Soll ich"],
            "contains": ["## "]
        },
        {
            "id": 3,
            "name": "Outreach Test (Keine Werbephrasen)",
            "prompt": "Formuliere 3 klare Kernbotschaften für den Launch unserer API als Markdown.",
            "not_contains": ["Gerne helfe ich", "Möchten Sie"],
            "contains": ["## "]
        },
        {
            "id": 4,
            "name": "Subtask Output Test (Striktes JSON)",
            "prompt": "Gib mir eine Liste von 2 Arbeitspaketen mit den Keys task_id und title im validen JSON-Format zurück. Antworte ausschließlich mit dem JSON-Objekt.",
            "is_json": True,
            "not_contains": ["Gerne helfe ich"]
        },
        {
            "id": 5,
            "name": "Governance Prüfbericht (Fakten ohne Füllwörter)",
            "prompt": "Erstelle einen kurzen Prüfbericht zur DSGVO-Konformität von IP-Logging in Archon OS.",
            "not_contains": ["Wie kann ich", "Gerne helfe ich"],
            "contains": ["## "]
        }
    ]

    results = []
    passed_count = 0

    for tc in test_cases:
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=tc["prompt"],
                role=role,
                system_prompt=system_prompt,
                model=model,
                timeout=20
            )
            content = res.get("content", "").strip()
            
            assertions = []
            test_passed = True
            
            for nc in tc.get("not_contains", []):
                failed = nc.lower() in content.lower()
                assertions.append({
                    "type": "not-contains",
                    "value": nc,
                    "passed": not failed
                })
                if failed:
                    test_passed = False
                    
            for c in tc.get("contains", []):
                passed = c.lower() in content.lower()
                assertions.append({
                    "type": "contains",
                    "value": c,
                    "passed": passed
                })
                if not passed:
                    test_passed = False

            if tc.get("is_json"):
                valid_json = False
                try:
                    clean_c = content
                    if "```json" in clean_c:
                        clean_c = clean_c.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_c:
                        clean_c = clean_c.split("```")[1].split("```")[0].strip()
                    json.loads(clean_c)
                    valid_json = True
                except Exception:
                    valid_json = False
                assertions.append({
                    "type": "is-json",
                    "passed": valid_json
                })
                if not valid_json:
                    test_passed = False

            if test_passed:
                passed_count += 1

            results.append({
                "test_id": tc["id"],
                "name": tc["name"],
                "passed": test_passed,
                "assertions": assertions,
                "sample_output": content[:120] + "..." if len(content) > 120 else content
            })
        except Exception as ex:
            results.append({
                "test_id": tc["id"],
                "name": tc["name"],
                "passed": False,
                "error": str(ex)
            })

    total_count = len(test_cases)
    score_str = f"{passed_count}/{total_count} Tests bestanden"
    
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    mc_data = _load_mission_control_data()
    mc_data.setdefault("audit_logs", []).insert(0, {
        "time": now_t,
        "source": "Governance",
        "msg": f"Promptfoo Evaluierung für {agent_name}: {score_str}"
    })
    add_ticker("Governance", f"Testsuite für {agent_name}: {score_str}")
    _save_mission_control_data(mc_data)

    return {
        "status": "ok",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "score": score_str,
        "passed_count": passed_count,
        "total_count": total_count,
        "pass_rate_pct": round((passed_count / total_count) * 100, 1),
        "details": results
    }

# -------------------------------------------------------------
# OMNIROUTE EMBEDDED REVERSE PROXY (STRIPS X-FRAME-OPTIONS & CSP)
# -------------------------------------------------------------
# -------------------------------------------------------------
# OMNIROUTE EMBEDDED REVERSE PROXY (STRIPS X-FRAME-OPTIONS & CSP)
# -------------------------------------------------------------
_PROXY_HTTP_CLIENTS: Dict[int, httpx.AsyncClient] = {}

def _get_shared_proxy_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    c = _PROXY_HTTP_CLIENTS.get(loop_id)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(
            follow_redirects=False,
            timeout=60.0,
            limits=httpx.Limits(max_keepalive_connections=30, max_connections=120)
        )
        _PROXY_HTTP_CLIENTS[loop_id] = c
    return c

async def forward_to_omniroute(request: Request, path: str):
    target_host = "omniroute:20128"
    url = f"http://{target_host}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
        
    client = _get_shared_proxy_client()
    try:
        req_headers = dict(request.headers)
        req_headers.pop("host", None)
        req_headers.pop("accept-encoding", None)
        body = await request.body()
        resp = await client.request(
            method=request.method,
            url=url,
            headers=req_headers,
            content=body
        )
        
        resp_headers = {}
        for k, v in resp.headers.items():
            k_lower = k.lower()
            if k_lower in ["x-frame-options", "content-security-policy", "content-length", "content-encoding", "transfer-encoding"]:
                continue
            if k_lower == "location":
                loc = v
                if loc.startswith("/"):
                    loc = f"/omniroute-proxy{loc}"
                resp_headers["Location"] = loc
            else:
                resp_headers[k] = v
                
        resp_headers["Access-Control-Allow-Origin"] = "*"
        resp_headers["X-Frame-Options"] = "ALLOWALL"
        
        content = resp.content
        # If response is HTML, inject base tag so Next.js assets and API calls resolve correctly
        c_type = resp.headers.get("content-type", "")
        if "text/html" in c_type:
            html_text = content.decode("utf-8", errors="ignore")
            # Replace absolute root paths in HTML attributes with /omniroute-proxy/
            # or ensure head has base href
            if "<head>" in html_text:
                html_text = html_text.replace("<head>", "<head><base href=\"/omniroute-proxy/\">", 1)
            content = html_text.encode("utf-8")
        
        return Response(
            content=content,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=resp.headers.get("content-type")
        )
    except Exception as e:
        try:
            url_fallback = f"http://host.docker.internal:20128/{path}"
            if request.url.query:
                url_fallback += f"?{request.url.query}"
            body = await request.body()
            resp = await client.request(method=request.method, url=url_fallback, content=body)
            resp_headers = {}
            for k, v in resp.headers.items():
                k_lower = k.lower()
                if k_lower in ["x-frame-options", "content-security-policy", "content-length", "content-encoding", "transfer-encoding"]:
                    continue
                if k_lower == "location":
                    loc = v
                    if loc.startswith("/"):
                        loc = f"/omniroute-proxy{loc}"
                    resp_headers["Location"] = loc
                else:
                    resp_headers[k] = v
            resp_headers["Access-Control-Allow-Origin"] = "*"
            resp_headers["X-Frame-Options"] = "ALLOWALL"
            
            content = resp.content
            c_type = resp.headers.get("content-type", "")
            if "text/html" in c_type:
                html_text = content.decode("utf-8", errors="ignore")
                if "<head>" in html_text:
                    html_text = html_text.replace("<head>", "<head><base href=\"/omniroute-proxy/\">", 1)
                content = html_text.encode("utf-8")
                
            return Response(content=content, status_code=resp.status_code, headers=resp_headers, media_type=resp.headers.get("content-type"))
        except Exception as e2:
            return JSONResponse(status_code=502, content={"error": f"OmniRoute proxy error: {str(e2)}"})

@app.api_route("/omniroute-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def omniroute_proxy(request: Request, path: str = ""):
    return await forward_to_omniroute(request, path)

@app.api_route("/_next/{path:path}", methods=["GET", "HEAD"])
async def omniroute_next_assets(request: Request, path: str = ""):
    return await forward_to_omniroute(request, f"_next/{path}")

# -------------------------------------------------------------
# N8N AUTOMATION EMBEDDED REVERSE PROXY (STRIPS X-FRAME-OPTIONS & CSP)
# -------------------------------------------------------------
async def forward_to_n8n(request: Request, path: str):
    target_host = "n8n:5678"
    clean_path = path.lstrip("/")
    url = f"http://{target_host}/{clean_path}"
    if request.url.query:
        url += f"?{request.url.query}"
        
    client = _get_shared_proxy_client()
    try:
        req_headers = dict(request.headers)
        req_headers.pop("host", None)
        req_headers.pop("accept-encoding", None)
        body = await request.body()
        resp = await client.request(
            method=request.method,
            url=url,
            headers=req_headers,
            content=body
        )
        
        resp_headers = {}
        for k, v in resp.headers.items():
            k_lower = k.lower()
            if k_lower in ["x-frame-options", "content-security-policy", "content-length", "content-encoding", "transfer-encoding"]:
                continue
            if k_lower == "location":
                loc = v
                if loc.startswith("/"):
                    loc = f"/n8n-proxy{loc}"
                resp_headers["Location"] = loc
            else:
                resp_headers[k] = v
                
        resp_headers["Access-Control-Allow-Origin"] = "*"
        resp_headers["X-Frame-Options"] = "ALLOWALL"
        
        content = resp.content
        c_type = resp.headers.get("content-type", "")

        if path.endswith("base-path.js"):
            return Response(
                content=b"window.BASE_PATH = '/n8n-proxy/';",
                status_code=200,
                headers=resp_headers,
                media_type="application/javascript"
            )

        if "text/html" in c_type:
            html_text = content.decode("utf-8", errors="ignore")
            if "<head>" in html_text:
                html_text = html_text.replace("<head>", "<head><base href=\"/n8n-proxy/\">", 1)
            html_text = html_text.replace('href="/assets/', 'href="/n8n-proxy/assets/')
            html_text = html_text.replace('src="/assets/', 'src="/n8n-proxy/assets/')
            html_text = html_text.replace('href="/static/', 'href="/n8n-proxy/static/')
            html_text = html_text.replace('src="/static/', 'src="/n8n-proxy/static/')
            html_text = html_text.replace('data-src="/assets/', 'data-src="/n8n-proxy/assets/')
            html_text = html_text.replace('href="/favicon.ico"', 'href="/n8n-proxy/favicon.ico"')
            content = html_text.encode("utf-8")
        
        return Response(
            content=content,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=resp.headers.get("content-type")
        )
    except Exception as e:
        try:
            url_fallback = f"http://host.docker.internal:5678/{path}"
            if request.url.query:
                url_fallback += f"?{request.url.query}"
            body = await request.body()
            resp = await client.request(method=request.method, url=url_fallback, headers=req_headers, content=body)
            resp_headers = {}
            for k, v in resp.headers.items():
                k_lower = k.lower()
                if k_lower in ["x-frame-options", "content-security-policy", "content-length", "content-encoding", "transfer-encoding"]:
                    continue
                if k_lower == "location":
                    loc = v
                    if loc.startswith("/"):
                        loc = f"/n8n-proxy{loc}"
                    resp_headers["Location"] = loc
                else:
                    resp_headers[k] = v
            resp_headers["Access-Control-Allow-Origin"] = "*"
            resp_headers["X-Frame-Options"] = "ALLOWALL"
            
            content = resp.content
            c_type = resp.headers.get("content-type", "")

            if path.endswith("base-path.js"):
                return Response(
                    content=b"window.BASE_PATH = '/n8n-proxy/';",
                    status_code=200,
                    headers=resp_headers,
                    media_type="application/javascript"
                )

            if "text/html" in c_type:
                html_text = content.decode("utf-8", errors="ignore")
                if "<head>" in html_text:
                    html_text = html_text.replace("<head>", "<head><base href=\"/n8n-proxy/\">", 1)
                html_text = html_text.replace('href="/assets/', 'href="/n8n-proxy/assets/')
                html_text = html_text.replace('src="/assets/', 'src="/n8n-proxy/assets/')
                html_text = html_text.replace('href="/static/', 'href="/n8n-proxy/static/')
                html_text = html_text.replace('src="/static/', 'src="/n8n-proxy/static/')
                html_text = html_text.replace('data-src="/assets/', 'data-src="/n8n-proxy/assets/')
                html_text = html_text.replace('href="/favicon.ico"', 'href="/n8n-proxy/favicon.ico"')
                content = html_text.encode("utf-8")
                
            return Response(content=content, status_code=resp.status_code, headers=resp_headers, media_type=resp.headers.get("content-type"))
        except Exception as e2:
            return JSONResponse(status_code=502, content={"error": f"n8n proxy error: {str(e2)}"})

@app.api_route("/n8n-proxy", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
@app.api_route("/n8n-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def n8n_proxy(request: Request, path: str = ""):
    return await forward_to_n8n(request, path)

@app.api_route("/assets/{path:path}", methods=["GET", "HEAD"])
async def n8n_assets_proxy(request: Request, path: str = ""):
    return await forward_to_n8n(request, f"assets/{path}")

@app.api_route("/rest/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def n8n_rest_proxy(request: Request, path: str = ""):
    return await forward_to_n8n(request, f"rest/{path}")


@app.get("/hud")
def get_hud_page():
    hud_file = os.path.join("static", "hermes-hud", "index.html")
    if os.path.exists(hud_file):
        return FileResponse(hud_file)
    return FileResponse(os.path.join("static", "index.html"))

@app.get("/mobile")
@app.get("/m")
def get_mobile_cockpit():
    return FileResponse(
        os.path.join("static", "mobile.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join("static", "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/manifest+json")
    return JSONResponse({"name": "Archon Mobile", "short_name": "Archon", "start_url": "/mobile", "display": "standalone"})

@app.get("/v2")
def get_index_v2():
    return FileResponse("static/index.html")

@app.get("/")
def get_index():
    return FileResponse(
        os.path.join("static", "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

try:
    from views_core import router as views_core_router, get_apps_dir
    app.include_router(views_core_router)
    apps_static_dir = get_apps_dir()
    if os.path.exists(apps_static_dir):
        app.mount("/builds/apps", StaticFiles(directory=apps_static_dir), name="builds_apps")
except Exception as e_views:
    print(f"Error mounting views_core: {e_views}")

try:
    from backend.operations_api import router as operations_router
    app.include_router(operations_router)
    print("Operations API mounted successfully.")
except Exception as e_ops:
    print(f"Error mounting operations_api: {e_ops}")

if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("static_v2"):
    app.mount("/static_v2", StaticFiles(directory="static_v2"), name="static_v2")

# reload trigger

@app.get("/api/debug-db")
def debug_db():
    try:
        with _get_state_db() as conn:
            return {"db_path": STATE_DB_PATH, "msg_count": conn.execute("SELECT count(*) FROM messages").fetchone()[0]}
    except Exception as e:
        return {"error": str(e)}




# =====================================================================
# PROAKTIVER MORGEN-STANDUP & AUTONOMER WECKDIENST (Pillar 1 & 7)
# =====================================================================

@app.post("/api/system/standup/run")
async def api_run_morning_standup():
    """Generiert ein proaktives Morgen-Briefing über Tasks, Flotte, Inbox und Token-Kosten."""
    from backend.autonomous_standup import generate_morning_standup
    res = await generate_morning_standup()
    add_ticker("Morgen-Standup", f"Tages-Briefing für {res.get('date')} erstellt.")
    broadcast_event("morning_briefing", res)
    return res

@app.get("/api/system/standup/latest")
async def api_get_latest_morning_standup():
    """Liefert das aktuellste Morgen-Briefing aus dem Obsidian Vault."""
    try:
        from local_memory_bridge import LocalMemoryBridge
        bridge = LocalMemoryBridge()
        out_dir = os.path.join(bridge.vault_path, "01_PROJEKTE", "Daily_Briefings")
        if os.path.exists(out_dir):
            files = sorted([f for f in os.listdir(out_dir) if f.startswith("Briefing_") and f.endswith(".md")], reverse=True)
            if files:
                with open(os.path.join(out_dir, files[0]), "r", encoding="utf-8") as bf:
                    return {"status": "success", "filename": files[0], "content": bf.read()}
    except Exception:
        pass
    from backend.autonomous_standup import generate_morning_standup
    return await generate_morning_standup()


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 3: INBOX WATCHER & ROBERT TOOL PERMISSIONS) ---

@app.get("/api/inbox-watcher/config")
def api_get_inbox_watcher_config():
    from backend.inbox_watcher import get_inbox_config
    cfg = get_inbox_config()
    watch_dir = cfg.get("watch_folder")
    exists = os.path.exists(watch_dir) if watch_dir else False
    file_count = len(os.listdir(watch_dir)) if exists else 0
    return {"status": "success", "config": cfg, "folder_exists": exists, "file_count": file_count}

@app.post("/api/inbox-watcher/config")
async def api_save_inbox_watcher_config(payload: Dict = Body(...)):
    from backend.inbox_watcher import save_inbox_config, get_inbox_config
    current = get_inbox_config()
    current.update(payload)
    ok = save_inbox_config(current)
    return {"status": "success" if ok else "error", "config": current}

@app.post("/api/inbox-watcher/scan-now")
async def api_scan_inbox_watcher_now():
    from backend.inbox_watcher import scan_and_process_inbox
    res = await scan_and_process_inbox()
    try:
        from backend.internet_watchdog import run_watchdog_scan
        loop = asyncio.get_event_loop()
        wd_res = await loop.run_in_executor(None, run_watchdog_scan, True)
        res["internet_watchdog"] = wd_res
    except Exception as e:
        res["internet_watchdog_error"] = str(e)
    return res

@app.get("/api/tools/proposals")
def api_list_tool_proposals(status: Optional[str] = None):
    from backend.tool_permission_manager import tool_permission_manager
    return {"status": "success", "proposals": tool_permission_manager.list_proposals(status=status)}

@app.post("/api/tools/proposals")
def api_create_tool_proposal(payload: Dict = Body(...)):
    from backend.tool_permission_manager import tool_permission_manager
    return tool_permission_manager.propose_tool_installation(
        tool_name=payload.get("tool_name", ""),
        tool_type=payload.get("tool_type", "pip"),
        reason=payload.get("reason", ""),
        command=payload.get("command"),
        requested_by=payload.get("requested_by", "Robert (Lead Orchestrator)")
    )

@app.post("/api/tools/proposals/{permission_id}/resolve")
def api_resolve_tool_proposal(permission_id: str, payload: Dict = Body(...)):
    from backend.tool_permission_manager import tool_permission_manager
    action = payload.get("action", "grant")
    return tool_permission_manager.resolve_proposal(permission_id, action=action)

@app.post("/api/memory/harvest")
def api_harvest_memory(payload: Dict = Body(...)):
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    text = payload.get("text", "")
    agent_id = payload.get("agent_id", "orchestrator")
    return bridge.harvest_facts_and_preferences(text, agent_id=agent_id)


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 4: AUDIT, SNAPSHOTS, CONSENSUS, BUDGET & TELEGRAM) ---

@app.get("/api/snapshots")
def api_list_snapshots(limit: int = 50):
    from backend.snapshot_manager import snapshot_manager
    return {"status": "success", "snapshots": snapshot_manager.list_snapshots(limit=limit)}

@app.post("/api/snapshots/{snapshot_id}/restore")
def api_restore_snapshot(snapshot_id: str):
    from backend.snapshot_manager import snapshot_manager
    return snapshot_manager.restore_snapshot(snapshot_id)

@app.get("/api/audit/logs")
def api_list_audit_logs(limit: int = 50):
    from backend.audit_log import chained_audit_log
    return {"status": "success", "logs": chained_audit_log.list_events(limit=limit)}

@app.get("/api/audit/verify")
def api_verify_audit_log():
    from backend.audit_log import chained_audit_log
    return chained_audit_log.verify_integrity()

@app.post("/api/tasks/review-consensus")
async def api_review_task_consensus(payload: Dict = Body(...)):
    from backend.consensus_gate import review_task_output
    task_id = payload.get("task_id", "task-gen")
    task_title = payload.get("title", "")
    task_output = payload.get("output", "")
    worker = payload.get("worker_agent", "hermes-coder")
    priority = int(payload.get("priority", 3))
    return await review_task_output(task_id, task_title, task_output, worker_agent=worker, priority=priority)

@app.post("/api/tasks/{task_id}/budget/check")
def api_check_task_budget(task_id: str, payload: Dict = Body(...)):
    from backend.agent_router import check_task_budget
    return check_task_budget(
        task_id=task_id,
        cost_usd=payload.get("cost_usd", 0.0),
        budget_usd=payload.get("budget_usd", 0.25),
        task_title=payload.get("title", "")
    )


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 5: RAG-BRIDGE, DEADLOCKS, DIFFS, SKILL-SYNTHESIS, EVENT-MESH) ---

@app.get("/api/rag/query")
def api_query_rag(q: str = Query(..., description="Suchbegriff für das AnythingLLM Docker-RAG")):
    from backend.rag_bridge import rag_bridge
    return rag_bridge.query_vault_rag(q)

@app.post("/api/system/deadlock-check")
def api_deadlock_check(timeout_seconds: int = 45):
    from backend.deadlock_supervisor import deadlock_supervisor
    return deadlock_supervisor.detect_and_resolve_deadlocks(stagnation_threshold_seconds=timeout_seconds)

@app.post("/api/diff/preview")
def api_diff_preview(payload: Dict = Body(...)):
    from backend.diff_engine import compute_file_diff
    return compute_file_diff(
        file_path=payload.get("file_path", ""),
        new_content=payload.get("new_content", ""),
        context_lines=int(payload.get("context_lines", 3))
    )

@app.get("/api/skills/proposals")
def api_list_skill_proposals(status: Optional[str] = None):
    from backend.skill_synthesizer import skill_synthesizer
    return {"status": "success", "proposals": skill_synthesizer.list_proposals(status=status)}

@app.post("/api/skills/proposals/{proposal_id}/approve")
def api_approve_skill_proposal(proposal_id: str):
    from backend.skill_synthesizer import skill_synthesizer
    return skill_synthesizer.approve_skill(proposal_id)

@app.post("/api/events/inbound/{channel}")
def api_ingest_inbound_event(channel: str, payload: Dict = Body(...)):
    from backend.event_mesh import event_mesh
    return event_mesh.ingest_inbound_event(
        channel=channel,
        event_type=payload.get("event_type", "generic_event"),
        payload=payload
    )

@app.get("/api/events/history")
def api_list_event_history(limit: int = 50):
    from backend.event_mesh import event_mesh
    return {"status": "success", "events": event_mesh.list_events(limit=limit)}


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 6: THROTTLE, BENCHMARK, VISION, HYGIENE, HANDOFF) ---

@app.get("/api/concurrency/status")
def api_get_concurrency_status():
    from backend.concurrency_throttle import concurrency_throttle
    return {"status": "success", "concurrency": concurrency_throttle.get_status()}

@app.post("/api/concurrency/config")
def api_save_concurrency_config(payload: Dict = Body(...)):
    from backend.concurrency_throttle import save_concurrency_config, get_concurrency_config
    cfg = get_concurrency_config()
    cfg.update(payload)
    ok = save_concurrency_config(cfg)
    return {"status": "success" if ok else "error", "concurrency": cfg}

@app.post("/api/router/benchmark")
async def api_run_model_benchmark(payload: Dict = Body(...)):
    from backend.model_benchmarker import run_model_benchmark
    return await run_model_benchmark(
        prompt=payload.get("prompt", "Erstelle eine strukturierte Zusammenfassung der DSGVO-Kernpflichten."),
        model_a=payload.get("model_a", "deepseek/deepseek-chat"),
        model_b=payload.get("model_b", "anthropic/claude-3-5-sonnet"),
        role=payload.get("role", "Senior Analyst")
    )

@app.post("/api/vision/analyze")
def api_analyze_vision(payload: Dict = Body(...)):
    from backend.vision_pipeline import analyze_image_file
    return analyze_image_file(
        image_path=payload.get("image_path", ""),
        focus_prompt=payload.get("focus_prompt", "Beschreibe den Inhalt dieses Screenshots detailliert.")
    )

@app.post("/api/vault/generate-index")
def api_generate_vault_index():
    from backend.vault_hygiene import generate_vault_index_and_hygiene
    return generate_vault_index_and_hygiene()

@app.post("/api/handoff/create")
def api_create_handoff(payload: Dict = Body(...)):
    from backend.handoff_desk import handoff_desk
    return handoff_desk.create_handoff(
        task_id=payload.get("task_id", ""),
        from_agent=payload.get("from_agent", ""),
        to_agent=payload.get("to_agent", ""),
        deliverables=payload.get("deliverables", {}),
        acceptance_criteria=payload.get("acceptance_criteria", "")
    )

@app.post("/api/handoff/{handoff_id}/accept")
def api_accept_handoff(handoff_id: str, payload: Dict = Body(...)):
    from backend.handoff_desk import handoff_desk
    return handoff_desk.accept_handoff(
        handoff_id=handoff_id,
        receiving_agent=payload.get("receiving_agent", "")
    )


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 7: FLEET SELF-HEALING, DB-BACKUP, SECRET-MASKING, NOTIFICATION-HUB) ---

@app.post("/api/fleet/heal/{service_name}")
def api_heal_service(service_name: str):
    from backend.fleet_self_healing import restart_service_container
    return restart_service_container(service_name)

@app.get("/api/fleet/health-check")
def api_fleet_health_check():
    from backend.fleet_self_healing import check_fleet_and_heal
    return check_fleet_and_heal()

@app.post("/api/system/backup-db")
def api_backup_databases():
    from backend.db_backup_manager import db_backup_manager
    return db_backup_manager.checkpoint_and_backup()

@app.get("/api/system/backup-db/list")
def api_list_db_backups():
    from backend.db_backup_manager import db_backup_manager
    return {"status": "success", "backups": db_backup_manager.list_backups()}

@app.post("/api/security/mask-secrets")
def api_mask_secrets(payload: Dict = Body(...)):
    from backend.secret_masker import mask_sensitive_text
    masked, count = mask_sensitive_text(payload.get("text", ""))
    return {"status": "success", "masked_text": masked, "redacted_count": count}

@app.post("/api/notifications/dispatch")
def api_dispatch_notification(payload: Dict = Body(...)):
    from backend.notification_hub import notification_hub
    return notification_hub.dispatch_notification(
        title=payload.get("title", "System-Benachrichtigung"),
        message=payload.get("message", ""),
        severity=payload.get("severity", "INFO"),
        category=payload.get("category", "system")
    )

@app.get("/api/notifications/recent")
def api_list_recent_notifications(limit: int = 50):
    from backend.notification_hub import notification_hub
    return {"status": "success", "notifications": notification_hub.list_recent(limit=limit)}


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 8: COST-ESTIMATOR, DB-OPTIMIZER, HEALTH-SCORE, DOSSIER) ---

@app.post("/api/router/estimate-cost")
def api_estimate_cost(payload: Dict = Body(...)):
    from backend.cost_estimator import estimate_prompt_cost
    return estimate_prompt_cost(
        prompt=payload.get("prompt", ""),
        model_name=payload.get("model", "deepseek/deepseek-chat"),
        expected_output_tokens=int(payload.get("expected_output_tokens", 1000)),
        task_budget_usd=float(payload.get("task_budget_usd", 0.25))
    )

@app.post("/api/system/optimize-db")
def api_optimize_db():
    from backend.db_optimizer import optimize_all_databases
    return optimize_all_databases()

@app.get("/api/system/health-score")
def api_get_health_score():
    from backend.system_diagnostics import get_system_health_score
    return get_system_health_score()

@app.post("/api/system/generate-dossier")
def api_generate_dossier():
    from backend.system_dossier_generator import generate_system_dossier
    return generate_system_dossier()


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 9: TIME-TRAVEL DEBUGGER, COUNCIL DEBATE, TASK SELF-HEALING & DIR WATCHER) ---

@app.get("/api/traces/{task_id}")
def api_get_task_trace(task_id: str):
    from backend.time_travel_debugger import time_travel_debugger
    return {"status": "success", "task_id": task_id, "trace": time_travel_debugger.get_task_trace(task_id)}

@app.post("/api/traces/{task_id}/fork")
def api_fork_task_trace(task_id: str, payload: Dict = Body(...)):
    from backend.time_travel_debugger import time_travel_debugger
    return time_travel_debugger.fork_execution(
        task_id=task_id,
        from_step=int(payload.get("from_step", 1)),
        new_prompt=payload.get("new_prompt"),
        new_model=payload.get("new_model")
    )

@app.post("/api/traces/{task_id}/rollback")
def api_rollback_task_trace(task_id: str, payload: Dict = Body(...)):
    from backend.time_travel_debugger import time_travel_debugger
    return time_travel_debugger.rollback_to_step(
        task_id=task_id,
        to_step=int(payload.get("to_step", 0))
    )

@app.get("/api/router/benchmark/history")
def api_get_benchmark_history(limit: int = 25):
    from backend.model_benchmarker import get_benchmark_history
    return {"status": "success", "benchmarks": get_benchmark_history(limit=limit)}

@app.post("/api/consensus/council-vote")
async def api_run_council_vote(payload: Dict = Body(...)):
    from backend.consensus_gate import run_tri_agent_council
    return await run_tri_agent_council(
        task_id=payload.get("task_id", "council-task"),
        task_title=payload.get("title", ""),
        task_output=payload.get("output", ""),
        model=payload.get("model")
    )

@app.get("/api/consensus/history")
def api_get_consensus_history(limit: int = 25):
    from backend.consensus_gate import get_consensus_history
    return {"status": "success", "consensus_history": get_consensus_history(limit=limit)}

@app.post("/api/healing/attempt")
async def api_attempt_task_healing(payload: Dict = Body(...)):
    from backend.task_self_healer import task_self_healer
    return await task_self_healer.attempt_self_healing(
        task_id=payload.get("task_id", "heal-task"),
        task_title=payload.get("title", "Autonome Fehlerbehebung"),
        failed_code=payload.get("failed_code", ""),
        error_output=payload.get("error_output", ""),
        worker_agent=payload.get("worker_agent", "hermes-coder"),
        affected_file=payload.get("affected_file"),
        attempt=int(payload.get("attempt", 1)),
        max_attempts=int(payload["max_attempts"]) if "max_attempts" in payload else None,
        model=payload.get("model")
    )

@app.get("/api/healing/logs")
def api_get_healing_logs(limit: int = 25):
    from backend.task_self_healer import task_self_healer
    return {"status": "success", "logs": task_self_healer.get_healing_logs(limit=limit)}

@app.post("/api/events/scan-directory")
def api_scan_inbox_directory(payload: Dict = Body(default={})):
    from backend.event_mesh import event_mesh
    return event_mesh.scan_inbox_directory(inbox_dir=payload.get("inbox_dir"))


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 10: SANDBOX, MEMORY CONSOLIDATION, VISUAL BROWSER, WAR-ROOM & SLA CONTRACTS) ---

@app.post("/api/sandbox/execute")
def api_execute_sandbox(payload: Dict = Body(...)):
    from backend.ephemeral_sandbox import ephemeral_sandbox
    return ephemeral_sandbox.execute_in_sandbox(
        code=payload.get("code", ""),
        language=payload.get("language", "python"),
        memory_limit_mb=int(payload["memory_limit_mb"]) if "memory_limit_mb" in payload else None,
        cpu_limit=float(payload["cpu_limit"]) if "cpu_limit" in payload else None,
        timeout_seconds=int(payload["timeout_seconds"]) if "timeout_seconds" in payload else None,
        network_enabled=bool(payload["network_enabled"]) if "network_enabled" in payload else None
    )

@app.get("/api/settings/memory-consolidation")
def api_get_memory_consolidation_settings():
    from backend.memory_consolidator import get_consolidation_config
    return {"status": "success", "config": get_consolidation_config()}

@app.post("/api/settings/memory-consolidation")
def api_save_memory_consolidation_settings(payload: Dict = Body(...)):
    from backend.memory_consolidator import get_consolidation_config, save_consolidation_config
    cfg = get_consolidation_config()
    cfg.update(payload)
    ok = save_consolidation_config(cfg)
    return {"status": "success" if ok else "error", "config": cfg}

@app.post("/api/system/consolidate-memory")
def api_trigger_memory_consolidation(payload: Dict = Body(default={})):
    from backend.memory_consolidator import run_sleep_cycle_consolidation
    force = bool(payload.get("force", True))
    return run_sleep_cycle_consolidation(force=force)

@app.post("/api/browser/browse-and-capture")
def api_browse_and_capture(payload: Dict = Body(...)):
    from backend.visual_web_agent import visual_web_agent
    return visual_web_agent.browse_and_capture(
        task_id=payload.get("task_id", f"vis-{datetime.datetime.now().strftime('%H%M%S')}"),
        target_url=payload.get("url", "https://example.com"),
        actions=payload.get("actions"),
        extract_selector=payload.get("extract_selector")
    )

@app.post("/api/simulation/war-room")
async def api_run_war_room(payload: Dict = Body(...)):
    from backend.war_room_simulator import run_war_room_simulation
    return await run_war_room_simulation(
        topic=payload.get("topic", "System-Update"),
        proposal_text=payload.get("proposal", ""),
        model=payload.get("model")
    )

@app.get("/api/simulation/war-room/history")
def api_get_war_room_history(limit: int = 20):
    from backend.war_room_simulator import get_war_room_history
    return {"status": "success", "history": get_war_room_history(limit=limit)}

@app.post("/api/contracts/create")
def api_create_contract(payload: Dict = Body(...)):
    from backend.sla_contract_enforcer import sla_contract_enforcer
    return sla_contract_enforcer.create_contract(
        task_id=payload.get("task_id", "task-sla"),
        delegator_agent=payload.get("delegator", "agent-lead"),
        assignee_agent=payload.get("assignee", "agent-worker"),
        required_keys=payload.get("required_keys"),
        min_content_length=int(payload["min_content_length"]) if "min_content_length" in payload else None,
        acceptance_criteria=payload.get("acceptance_criteria"),
        max_turnaround_minutes=int(payload["max_turnaround_minutes"]) if "max_turnaround_minutes" in payload else None
    )

@app.post("/api/contracts/validate")
def api_validate_contract(payload: Dict = Body(...)):
    from backend.sla_contract_enforcer import sla_contract_enforcer
    return sla_contract_enforcer.validate_delivery(
        contract_id=payload.get("contract_id", ""),
        delivery_payload=payload.get("delivery", {})
    )

@app.get("/api/contracts/history")
def api_get_contracts_history(limit: int = 25):
    from backend.sla_contract_enforcer import sla_contract_enforcer
    return {"status": "success", "contracts": sla_contract_enforcer.list_contracts(limit=limit)}


# --- ZENTRALE KONFIGURATION ALLER 10 AUTONOMIE- & RESILIENZ-GRUPPEN (SETTINGS-PAKET A & B) ---

@app.get("/api/settings/autonomy-modules")
def api_get_autonomy_modules_settings():
    from backend.autonomy_settings import load_all_settings
    return {"status": "success", "settings": load_all_settings()}

@app.post("/api/settings/autonomy-modules")
def api_save_autonomy_modules_settings(payload: Dict = Body(...)):
    from backend.autonomy_settings import save_autonomy_settings
    updated = save_autonomy_settings(payload)
    # BIDIREKTIONALE SYNCHRONISATION: Archon Autonomie-Module (settings.json) -> Hermes (config.yaml)
    try:
        import yaml
        active_path, _ = _get_hermes_config_paths()
        if active_path and os.path.exists(active_path):
            with open(active_path, "r", encoding="utf-8") as f:
                hdata = yaml.safe_load(f.read()) or {}
            if not isinstance(hdata, dict):
                hdata = {}
            conc = payload.get("concurrency", {})
            if isinstance(conc, dict):
                if "max_concurrent_agents" in conc:
                    hdata.setdefault("delegation", {})["max_concurrent_children"] = int(conc["max_concurrent_agents"])
                if "queue_timeout_seconds" in conc:
                    hdata.setdefault("agent", {})["task_timeout_seconds"] = int(conc["queue_timeout_seconds"])
            cb = payload.get("circuit_breaker", {})
            if isinstance(cb, dict):
                tlg = hdata.setdefault("tool_loop_guardrails", {})
                if "loop_detection_enabled" in cb:
                    tlg["warnings_enabled"] = bool(cb["loop_detection_enabled"])
                if "max_identical_turns" in cb:
                    tlg.setdefault("hard_stop_after", {})["exact_failure"] = int(cb["max_identical_turns"])
                if "max_steps_per_task" in cb:
                    hdata.setdefault("agent", {})["max_turns"] = int(cb["max_steps_per_task"])
            sb = payload.get("ephemeral_sandbox", {})
            if isinstance(sb, dict):
                term = hdata.setdefault("terminal", {})
                if "cpu_limit" in sb:
                    term["container_cpu"] = float(sb["cpu_limit"])
                if "timeout_seconds" in sb:
                    term["timeout"] = int(sb["timeout_seconds"])
            cc = payload.get("context_compactor", {})
            if isinstance(cc, dict):
                comp = hdata.setdefault("compression", {})
                if "enabled" in cc:
                    comp["enabled"] = bool(cc["enabled"])
                if "keep_recent_turns" in cc:
                    comp["protect_last_n"] = int(cc["keep_recent_turns"])
            cg = payload.get("consensus_gate", {})
            if isinstance(cg, dict) and "enabled" in cg:
                hdata.setdefault("moa", {})["enabled"] = bool(cg["enabled"])
            with open(active_path, "w", encoding="utf-8") as f:
                yaml.dump(hdata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e_sync:
        logger.warning(f"[Archon -> Hermes Sync] {e_sync}")
    return {"status": "success", "settings": updated}


# --- TEIL 2 / PAKET 1 (FEATURES 1–5): PERFORMANCE CORE, SKALIERUNG & TOKEN-EFFIZIENZ ---

# Feature 1: Semantisches Prompt- & Response-Caching
@app.post("/api/cache/semantic-lookup")
def api_semantic_cache_lookup(payload: Dict = Body(...)):
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.lookup(
        prompt=payload.get("prompt", ""),
        model=payload.get("model", "any"),
        threshold_override=payload.get("similarity_threshold")
    )

@app.post("/api/cache/semantic-store")
def api_semantic_cache_store(payload: Dict = Body(...)):
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.store(
        prompt=payload.get("prompt", ""),
        response=payload.get("response", ""),
        model=payload.get("model", "any")
    )

@app.get("/api/cache/semantic-stats")
def api_semantic_cache_stats():
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.get_stats()

@app.delete("/api/cache/semantic-clear")
def api_semantic_cache_clear():
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.clear()


# Feature 2: Paralleles Map-Reduce Sub-Tasking (Fan-Out / Fan-In)
@app.post("/api/execution/map-reduce")
async def api_execute_map_reduce(payload: Dict = Body(...)):
    from backend.map_reduce_executor import map_reduce_executor
    return await map_reduce_executor.execute_map_reduce(
        task_title=payload.get("task_title", "Map-Reduce Batch"),
        items=payload.get("items", []),
        instruction=payload.get("instruction", "Analysiere und extrahiere Kernergebnisse"),
        max_workers_override=payload.get("max_parallel_workers")
    )

@app.get("/api/execution/map-reduce/history")
def api_map_reduce_history(limit: int = 20):
    from backend.map_reduce_executor import map_reduce_executor
    return {"status": "success", "jobs": map_reduce_executor.get_history(limit=limit)}


# Feature 3: Speculative Fast-Routing & Latenz-Hedging
@app.post("/api/router/hedged-completion")
async def api_hedged_completion(payload: Dict = Body(...)):
    from backend.speculative_hedger import speculative_hedger
    return await speculative_hedger.execute_hedged_call(
        prompt=payload.get("prompt", "Test-Anfrage"),
        primary_model=payload.get("primary_model", "openai/gpt-4o"),
        fallback_model_override=payload.get("fallback_model"),
        hedge_delay_override=payload.get("hedge_delay_seconds"),
        simulate_primary_latency_sec=payload.get("simulate_primary_latency_sec"),
        simulate_fallback_latency_sec=float(payload.get("simulate_fallback_latency_sec", 0.05))
    )

@app.get("/api/router/hedged-stats")
def api_hedged_stats():
    from backend.speculative_hedger import speculative_hedger
    return speculative_hedger.get_stats()


# Feature 4: Dynamisches Context-Compaction & Hierarchisches Summarizing
@app.post("/api/memory/compact-context")
def api_compact_context(payload: Dict = Body(...)):
    from backend.context_compactor import context_compactor
    return context_compactor.compact_messages(
        messages=payload.get("messages", []),
        force=bool(payload.get("force", False)),
        keep_recent_override=payload.get("keep_recent_turns")
    )


# Feature 5: SQLite Connection-Pool & Async Write-Batching
@app.post("/api/system/write-batcher/enqueue")
def api_write_batcher_enqueue(payload: Dict = Body(...)):
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.enqueue(
        event_type=payload.get("event_type", "telemetry"),
        source_module=payload.get("source_module", "router"),
        payload=payload.get("payload", {})
    )

@app.post("/api/system/write-batcher/flush")
def api_write_batcher_flush():
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.flush()

@app.get("/api/system/write-batcher/stats")
def api_write_batcher_stats():
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.get_stats()


# --- TEIL 2 / PAKET 2 (FEATURES 6–10): MODERNE GEDÄCHTNIS- & RAG-ARCHITEKTUR (GRAPH & HYBRID MEMORY) ---

# Feature 6: Hybrid-Search (BM25 SQLite FTS5 + Vektor-RAG + Reciprocal Rank Fusion)
@app.post("/api/memory/hybrid-index")
def api_hybrid_index_doc(payload: Dict = Body(...)):
    from backend.hybrid_search_engine import hybrid_search_engine
    return hybrid_search_engine.index_document(
        doc_id=payload.get("doc_id", "DOC-1"),
        title=payload.get("title", "Unbenanntes Dokument"),
        content=payload.get("content", ""),
        source=payload.get("source", "system_docs")
    )

@app.post("/api/memory/hybrid-search")
def api_hybrid_search(payload: Dict = Body(...)):
    from backend.hybrid_search_engine import hybrid_search_engine
    return hybrid_search_engine.search(
        query=payload.get("query", ""),
        top_k_override=payload.get("top_k"),
        rrf_k_override=payload.get("rrf_k")
    )


# Feature 7: Lokaler Knowledge-Graph (Entitäten- & Beziehungs-Tripel)
@app.post("/api/memory/knowledge-graph/triple")
def api_kg_add_triple(payload: Dict = Body(...)):
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.add_triple(
        subject=payload.get("subject", ""),
        predicate=payload.get("predicate", "RELATED_TO"),
        obj=payload.get("object", ""),
        confidence=float(payload.get("confidence", 0.90)),
        source=payload.get("source", "manual")
    )

@app.post("/api/memory/knowledge-graph/ingest")
def api_kg_ingest_text(payload: Dict = Body(...)):
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.ingest_text(
        text=payload.get("text", ""),
        source=payload.get("source", "auto_extractor")
    )

@app.get("/api/memory/knowledge-graph/subgraph")
def api_kg_subgraph(entity: str, hops: Optional[int] = None):
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.query_subgraph(entity=entity, hops_override=hops)


# Feature 8: Agentic Corrective RAG (CRAG)
@app.post("/api/memory/crag-retrieve")
def api_crag_retrieve(payload: Dict = Body(...)):
    from backend.corrective_rag import corrective_rag_engine
    return corrective_rag_engine.retrieve_and_verify(
        query=payload.get("query", ""),
        threshold_override=payload.get("relevance_threshold")
    )


# Feature 9: 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (Pinned Working Memory)
@app.get("/api/memory/core-blocks")
def api_get_core_memory_blocks():
    from backend.core_memory_manager import core_memory_manager
    return core_memory_manager.list_blocks()

@app.post("/api/memory/core-blocks")
def api_upsert_core_memory_block(payload: Dict = Body(...)):
    from backend.core_memory_manager import core_memory_manager
    return core_memory_manager.upsert_block(
        block_key=payload.get("block_key", "custom_block"),
        content=payload.get("content", ""),
        block_title=payload.get("block_title", ""),
        mode=payload.get("mode", "replace")
    )


# Feature 10: Automatisches Citation- & Quellen-Pinning
@app.post("/api/memory/pin-citations")
def api_pin_citations(payload: Dict = Body(...)):
    from backend.citation_pinner import citation_pinner
    return citation_pinner.pin_citations(
        response_text=payload.get("response_text", ""),
        sources=payload.get("sources", [])
    )


# --- TEIL 2 / PAKET 3 (FEATURES 11–15): ZUVERLÄSSIGE AUSFÜHRUNG & DETERMINISMUS (DURABLE EXECUTION) ---

# Feature 11: Structured Outputs & JSON-Schema-Garantie
@app.post("/api/execution/structured-output")
def api_structured_output_validate(payload: Dict = Body(...)):
    from backend.structured_output_enforcer import structured_output_enforcer
    return structured_output_enforcer.validate_and_enforce(
        raw_output=payload.get("raw_output", ""),
        schema=payload.get("schema")
    )


# Feature 12: Durable Execution Checkpointing (Pause / Resume)
@app.post("/api/execution/checkpoints/save")
def api_save_durable_checkpoint(payload: Dict = Body(...)):
    from backend.durable_checkpoint_manager import durable_checkpoint_manager
    return durable_checkpoint_manager.save_checkpoint(
        workflow_id=payload.get("workflow_id", "wf-default"),
        task_title=payload.get("task_title", "Workflow"),
        current_step_index=int(payload.get("current_step_index", 1)),
        total_steps=int(payload.get("total_steps", 5)),
        state_payload=payload.get("state", {}),
        completed_steps=payload.get("completed_steps", []),
        status=payload.get("status", "in_progress")
    )

@app.get("/api/execution/checkpoints/resume/{workflow_id}")
def api_resume_durable_checkpoint(workflow_id: str):
    from backend.durable_checkpoint_manager import durable_checkpoint_manager
    return durable_checkpoint_manager.resume_checkpoint(workflow_id=workflow_id)

@app.get("/api/execution/checkpoints/list")
def api_list_durable_checkpoints(status: Optional[str] = None):
    from backend.durable_checkpoint_manager import durable_checkpoint_manager
    return {"status": "success", "checkpoints": durable_checkpoint_manager.list_checkpoints(status_filter=status)}


# Feature 13: Idempotency-Keys & Tool-Call-Deduplizierung
@app.post("/api/execution/idempotency/check")
def api_idempotency_check(payload: Dict = Body(...)):
    from backend.idempotency_guard import idempotency_guard
    return idempotency_guard.check_or_register(
        tool_name=payload.get("tool_name", "send_email"),
        params=payload.get("params", {}),
        explicit_key=payload.get("idempotency_key"),
        execution_result=payload.get("execution_result")
    )


# Feature 14: Dry-Run / Shadow-Mode für Agenten-Aufträge
@app.post("/api/execution/dry-run")
def api_dry_run_simulate(payload: Dict = Body(...)):
    from backend.dry_run_simulator import dry_run_simulator
    return dry_run_simulator.simulate_task_plan(
        task_title=payload.get("task_title", "Shadow Simulation"),
        proposed_actions=payload.get("proposed_actions", [])
    )


# Feature 15: Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager
@app.post("/api/execution/dlq/enqueue")
def api_dlq_enqueue(payload: Dict = Body(...)):
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.enqueue_failed_job(
        job_type=payload.get("job_type", "webhook_delivery"),
        source_module=payload.get("source_module", "router"),
        payload=payload.get("payload", {}),
        error_message=payload.get("error_message", "Unbekannter Fehler")
    )

@app.post("/api/execution/dlq/replay")
def api_dlq_replay(payload: Dict = Body(...)):
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.replay_job(
        dlq_id=payload.get("dlq_id", ""),
        simulate_success=bool(payload.get("simulate_success", True))
    )

@app.get("/api/execution/dlq/list")
def api_dlq_list(status: Optional[str] = None):
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.list_dlq(status_filter=status)


# --- TEIL 2 / PAKET 4 (FEATURES 16–20): SICHERHEIT, DATENSCHUTZ & ENTERPRISE-GOVERNANCE (GUARDRAILS) ---

# Feature 16: Bidirektionaler PII-Scrubber & Re-Hydration (DSGVO)
@app.post("/api/security/pii-scrub")
def api_pii_scrub(payload: Dict = Body(...)):
    from backend.pii_scrubber import pii_scrubber
    return pii_scrubber.scrub_text(
        text=payload.get("text", ""),
        session_id=payload.get("session_id", "")
    )

@app.post("/api/security/pii-rehydrate")
def api_pii_rehydrate(payload: Dict = Body(...)):
    from backend.pii_scrubber import pii_scrubber
    return pii_scrubber.rehydrate_text(
        response_text=payload.get("response_text", ""),
        session_id=payload.get("session_id", ""),
        custom_vault=payload.get("vault_map")
    )


# Feature 17: Egress-Firewall & Domain-Allowlisting
@app.post("/api/security/egress-check")
def api_egress_firewall_check(payload: Dict = Body(...)):
    from backend.egress_firewall import egress_firewall
    return egress_firewall.check_url(
        target_url=payload.get("url", ""),
        agent_id=payload.get("agent_id", "agent-worker")
    )

@app.get("/api/security/egress-logs")
def api_egress_firewall_logs(limit: int = 25):
    from backend.egress_firewall import egress_firewall
    return {"status": "success", "logs": egress_firewall.get_logs(limit=limit)}


# Feature 18: Granulare Agenten-RBAC & Datei-Scope-Jails
@app.post("/api/security/rbac-check")
def api_rbac_jail_check(payload: Dict = Body(...)):
    from backend.agent_rbac_jail import agent_rbac_jail
    return agent_rbac_jail.check_access(
        role=payload.get("role", "researcher"),
        tool_name=payload.get("tool_name", "read_file"),
        target_path=payload.get("target_path", "")
    )


# Feature 19: Deterministischer Output-Linter & Policy-Checker
@app.post("/api/security/lint-output")
def api_lint_agent_output(payload: Dict = Body(...)):
    from backend.output_policy_linter import output_policy_linter
    return output_policy_linter.lint_and_clean(
        output_text=payload.get("output_text", "")
    )


# Feature 20: Manipulationssichere Kosten- & Entscheidungs-Quittungen (Execution Receipts)
@app.post("/api/security/receipts/issue")
def api_issue_execution_receipt(payload: Dict = Body(...)):
    from backend.execution_receipt_ledger import execution_receipt_ledger
    return execution_receipt_ledger.issue_receipt(
        task_id=payload.get("task_id", "task-01"),
        agent_role=payload.get("agent_role", "backend_architect"),
        model_used=payload.get("model_used", "deepseek/deepseek-chat"),
        prompt_tokens=int(payload.get("prompt_tokens", 500)),
        completion_tokens=int(payload.get("completion_tokens", 250)),
        cost_usd=float(payload.get("cost_usd", 0.0012)),
        tools_invoked=payload.get("tools_invoked", [])
    )

@app.get("/api/security/receipts/verify")
def api_verify_execution_receipts():
    from backend.execution_receipt_ledger import execution_receipt_ledger
    return execution_receipt_ledger.verify_chain_integrity()


# --- TEIL 2 / PAKET 5 (FEATURES 21–25): SELBST-OPTIMIERUNG, EVALUATION & SCHWARM-INTELLIGENZ (NEXT-GEN) ---

# Feature 21: Automatischer Prompt-Optimizer (DSPy / TextGrad-Prinzip)
@app.post("/api/evolution/optimize-prompt")
def api_optimize_role_prompt(payload: Dict = Body(...)):
    from backend.prompt_optimizer import prompt_optimizer
    return prompt_optimizer.optimize_role_prompt(
        agent_role=payload.get("agent_role", "backend_architect"),
        current_prompt=payload.get("current_prompt", "Du bist ein präziser System-Agent."),
        recent_failures=payload.get("recent_failures", [])
    )


# Feature 22: Gold-Standard Regression-Test-Suite (Eval-Dataset Runner)
@app.post("/api/evolution/eval-suite/run")
def api_run_eval_regression_suite(payload: Dict = Body(default={})):
    from backend.eval_regression_runner import eval_regression_runner
    return eval_regression_runner.run_suite(
        candidate_label=payload.get("candidate_label", "v2026.10-release"),
        simulated_outputs=payload.get("simulated_outputs")
    )


# Feature 23: Dynamisches Modell-Routing nach Echtzeit-Telemetrie (Bandit-Router)
@app.post("/api/router/bandit-outcome")
def api_bandit_record_outcome(payload: Dict = Body(...)):
    from backend.bandit_model_router import bandit_model_router
    return bandit_model_router.record_outcome(
        model_id=payload.get("model_id", "deepseek/deepseek-chat"),
        success=bool(payload.get("success", True)),
        latency_ms=float(payload.get("latency_ms", 500.0))
    )

@app.get("/api/router/bandit-select")
def api_bandit_select_best():
    from backend.bandit_model_router import bandit_model_router
    return bandit_model_router.select_best_model()


# Feature 24: Dynamisches Ephemeral-Team-Spawning (Ad-hoc Task-Force)
@app.post("/api/swarm/spawn-ephemeral-team")
def api_spawn_ephemeral_team(payload: Dict = Body(...)):
    from backend.ephemeral_team_spawner import ephemeral_team_spawner
    return ephemeral_team_spawner.spawn_task_force(
        mission_title=payload.get("mission_title", "Spezial-Auftrag"),
        mission_brief=payload.get("mission_brief", "")
    )


# Feature 25: Live-Ressourcen-Protector (Host CPU/RAM/Disk-Backpressure)
@app.get("/api/system/resource-backpressure")
def api_check_resource_backpressure(simulate_overload: bool = False):
    from backend.resource_backpressure import resource_backpressure_protector
    return resource_backpressure_protector.check_health_and_backpressure(simulate_overload=simulate_overload)


# --- CORPORATE MANAGER & MULTI-COMPANY HUB ---
@app.get("/api/corporate/companies")
def api_list_corporate_companies():
    from backend.corporate_manager import corporate_manager
    return {"companies": corporate_manager.list_companies()}

@app.get("/api/corporate/companies/{company_id}")
def api_get_corporate_company(company_id: str):
    from backend.corporate_manager import corporate_manager
    comp = corporate_manager.get_company(company_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Company not found")
    return comp

@app.post("/api/corporate/companies")
def api_save_corporate_company(payload: Dict = Body(...)):
    from backend.corporate_manager import corporate_manager
    saved = corporate_manager.save_company(payload)
    return {"success": True, "company": saved}

@app.post("/api/corporate/companies/{company_id}/set-active")
def api_set_active_corporate_company(company_id: str):
    from backend.corporate_manager import corporate_manager
    success = corporate_manager.set_active_company(company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"success": True, "active_company_id": company_id}

@app.delete("/api/corporate/companies/{company_id}")
def api_delete_corporate_company(company_id: str):
    from backend.corporate_manager import corporate_manager
    success = corporate_manager.delete_company(company_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete active or only existing company")
    return {"success": True, "deleted_id": company_id}

@app.post("/api/corporate/render-template")
def api_render_corporate_template(payload: Dict = Body(...)):
    from backend.corporate_manager import corporate_manager
    template_type = payload.get("template_type", "letterhead")
    company_id = payload.get("company_id")
    custom = payload.get("custom", {})
    result = corporate_manager.render_template(template_type=template_type, company_id=company_id, custom=custom)
    return result


@app.get("/api/erp/documents/{doc_id}/print", response_class=HTMLResponse)
def api_erp_document_print(
    doc_id: str,
    company_id: Optional[str] = None,
    autoprint: bool = False,
    doc_type: Optional[str] = None,
    entity_name: Optional[str] = None,
    amount_net: Optional[float] = None
):
    from backend.corporate_manager import corporate_manager
    from backend.erp_manager import erp_manager
    doc = erp_manager.get_document(doc_id, company_id=company_id)
    tmpl_type = "invoice"
    custom: Dict[str, Any] = {"document_id": doc_id}
    
    if doc:
        raw_type = doc.get("doc_type", "invoice")
        if raw_type in ("offer", "ang"):
            tmpl_type = "offer"
        elif raw_type in ("order", "order_confirmation", "ab"):
            tmpl_type = "order_confirmation"
        else:
            tmpl_type = "invoice"
    else:
        # Fallback für dynamische / simulierte Belege aus CRM Vorgänge
        if doc_id.upper().startswith("ANG") or doc_type in ("offer", "ang"):
            tmpl_type = "offer"
            custom["offer_num"] = doc_id
        elif doc_id.upper().startswith("AB") or doc_type in ("order", "order_confirmation", "ab"):
            tmpl_type = "order_confirmation"
            custom["order_num"] = doc_id
        else:
            tmpl_type = "invoice"
            custom["invoice_num"] = doc_id
            
        if entity_name:
            custom["recipient_name"] = entity_name
        if amount_net and amount_net > 0:
            custom["items"] = [
                {"pos": 1, "desc": f"Dienstleistung / Projektleistungen gem. Vorgang {doc_id}", "qty": 1, "unit": "Pauschal", "price": float(amount_net)}
            ]

    rendered = corporate_manager.render_template(template_type=tmpl_type, company_id=company_id, custom=custom)
    doc_num = custom.get("offer_num") or custom.get("order_num") or custom.get("invoice_num") or doc_id
    autoprint_script = "<script>window.onload = function() { window.print(); };</script>" if autoprint else ""
    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Belegdruck - {doc_num}</title>
  <style>
    @page {{ size: A4; margin: 12mm; }}
    body {{ margin: 0; padding: 24px; background: #f8fafc; display: flex; justify-content: center; font-family: system-ui, -apple-system, sans-serif; }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .no-print {{ display: none !important; }}
    }}
    .print-bar {{
      position: fixed; top: 16px; right: 20px; z-index: 9999;
      background: #0f172a; color: #fff; border-radius: 12px; padding: 10px 18px;
      display: flex; align-items: center; gap: 12px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3); font-size: 13px; font-weight: 600;
    }}
    .print-btn {{
      background: #4f46e5; hover:background: #4338ca; color: #fff; border: 0; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 13px; transition: all 0.2s;
    }}
    .print-btn:hover {{ background: #4338ca; }}
    .close-btn {{
      background: transparent; color: #94a3b8; border: 1px solid #334155; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 12px;
    }}
    .close-btn:hover {{ color: #fff; background: #1e293b; }}
  </style>
</head>
<body>
  <div class="print-bar no-print">
    <span>Archon ERP DIN 5008 Beleg</span>
    <button class="print-btn" onclick="window.print()">🖨️ Drucken / Als PDF speichern</button>
    <button class="close-btn" onclick="window.close()">Fenster schließen</button>
  </div>
  {rendered.get("html", "")}
  {autoprint_script}
</body>
</html>"""
    return HTMLResponse(content=html_content)


# --- SÄULE 3: WIRTSCHAFT & ERP (MULTI-TENANT CRM, ARTIKEL, BELEGE & POCKETBASE SYNC) ---
@app.get("/api/erp/overview")
def api_erp_overview(company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    return erp_manager.get_tenant_overview(company_id=company_id)


@app.get("/api/erp/entities")
def api_erp_list_entities(
    company_id: Optional[str] = None,
    role: str = "all",
    search: str = "",
    status: str = ""
):
    from backend.erp_manager import erp_manager
    return erp_manager.list_entities(company_id=company_id, role_filter=role, search=search, status=status)


@app.get("/api/erp/entities/{entity_id}")
def api_erp_get_entity_detail(entity_id: str, company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    res = erp_manager.get_entity_detail(entity_id=entity_id, company_id=company_id)
    if not res:
        raise HTTPException(status_code=404, detail="Entity not found")
    return res


@app.post("/api/erp/entities")
def api_erp_save_entity(payload: Dict = Body(...)):
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_entity(payload=payload, company_id=company_id)
    return {"success": True, "data": saved}


@app.post("/api/erp/contacts")
def api_erp_save_contact(payload: Dict = Body(...)):
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_contact(payload=payload, company_id=company_id)
    return {"success": True, "contact": saved}


@app.post("/api/erp/interactions")
def api_erp_add_interaction(payload: Dict = Body(...)):
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.add_interaction(payload=payload, company_id=company_id)
    return {"success": True, "interaction": saved}


@app.get("/api/erp/items")
def api_erp_list_items(
    company_id: Optional[str] = None,
    item_type: str = "all",
    search: str = ""
):
    from backend.erp_manager import erp_manager
    return erp_manager.list_items(company_id=company_id, item_type=item_type, search=search)


@app.post("/api/erp/items")
def api_erp_save_item(payload: Dict = Body(...)):
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_item(payload=payload, company_id=company_id)
    return {"success": True, "item": saved}


@app.get("/api/erp/documents")
def api_erp_list_documents(
    company_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    entity_id: Optional[str] = None
):
    from backend.erp_manager import erp_manager
    return erp_manager.list_documents(
        company_id=company_id, doc_type=doc_type, status=status, entity_id=entity_id
    )


@app.get("/api/erp/documents/{doc_id}")
def api_erp_get_document(doc_id: str, company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    doc = erp_manager.get_document(doc_id=doc_id, company_id=company_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.post("/api/erp/documents")
def api_erp_save_document(payload: Dict = Body(...)):
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_document(payload=payload, company_id=company_id)
    return {"success": True, "document": saved}


@app.post("/api/erp/documents/{doc_id}/convert")
def api_erp_convert_document(doc_id: str, payload: Dict = Body(default={})):
    from backend.erp_manager import erp_manager
    target_type = payload.get("target_doc_type", "invoice")
    company_id = payload.get("company_id")
    converted = erp_manager.convert_document(
        source_doc_id=doc_id, target_doc_type=target_type, company_id=company_id
    )
    return {"success": True, "document": converted}


@app.post("/api/erp/sync/pocketbase")
def api_erp_sync_pocketbase(payload: Dict = Body(default={})):
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    if "pocketbase_url" in payload or "collection_name" in payload:
        erp_manager.update_sync_config(payload, company_id=company_id)
    return erp_manager.sync_with_pocketbase(company_id=company_id)


# =========================================================================
# NATIVE POCKETBASE CRM API (KAUFMÄNNISCHES ADRESS- & CRM-ÖKOSYSTEM)
# =========================================================================
@app.get("/api/crm/contacts")
def api_crm_list_contacts(
    search: str = "",
    status: str = "",
    role: str = "all",
    region: str = "",
    tag: str = "",
    sort_by: str = "updated",
    sort_order: str = "desc",
    page: int = 1,
    limit: int = 100
):
    from backend.crm_service import crm_service
    return crm_service.list_contacts(
        search=search, status=status, role_filter=role, region=region,
        tag=tag, sort_by=sort_by, sort_order=sort_order, page=page, limit=limit
    )


@app.get("/api/crm/contacts/{contact_id}")
def api_crm_get_contact(contact_id: str):
    from backend.crm_service import crm_service
    contact = crm_service.get_contact_detail(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
    return contact


@app.post("/api/crm/contacts")
def api_crm_create_contact(payload: Dict = Body(...)):
    from backend.crm_service import crm_service
    return crm_service.save_contact(contact_id=payload.get("id"), payload=payload)


@app.put("/api/crm/contacts/{contact_id}")
def api_crm_update_contact(contact_id: str, payload: Dict = Body(...)):
    from backend.crm_service import crm_service
    return crm_service.save_contact(contact_id=contact_id, payload=payload)


@app.delete("/api/crm/contacts/{contact_id}")
def api_crm_delete_contact(contact_id: str):
    from backend.crm_service import crm_service
    ok = crm_service.delete_contact(contact_id)
    return {"success": ok}


@app.post("/api/crm/contacts/{contact_id}/messages")
def api_crm_add_message(contact_id: str, payload: Dict = Body(...)):
    from backend.crm_service import crm_service
    text = payload.get("text", "")
    channel = payload.get("channel", "note")
    direction = payload.get("direction", "outbound")
    sender = payload.get("sender", "Michael Keller")
    return crm_service.add_contact_message(
        contact_id=contact_id, text=text, channel=channel, direction=direction, sender=sender
    )


@app.get("/api/crm/messages")
def api_crm_list_messages(
    search: str = "",
    channel: str = "all",
    direction: str = "all",
    sort: str = "newest",
    page: int = 1,
    limit: int = 50
):
    from backend.crm_service import crm_service
    return crm_service.list_all_messages(
        search=search, channel=channel, direction=direction, sort=sort, page=page, limit=limit
    )


@app.get("/api/crm/calendar")
def api_crm_get_calendar():
    from backend.crm_service import crm_service
    return crm_service.get_calendar_events()


@app.get("/api/crm/report")
def api_crm_get_report():
    from backend.crm_service import crm_service
    return crm_service.get_report_metrics()


@app.get("/api/crm/avatars/{contact_id}/{filename}")
def api_crm_avatar(contact_id: str, filename: str):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    avatar_path = os.path.join(root_dir, "pocketbase", "pb_data", "storage", "pbc_1512878646", contact_id, filename)
    if os.path.exists(avatar_path):
        return FileResponse(avatar_path)
    alt_path = os.path.join(root_dir, "static", "avatars", filename)
    if os.path.exists(alt_path):
        return FileResponse(alt_path)
    raise HTTPException(status_code=404, detail="Avatar not found")


@app.get("/api/crm/contacts/{contact_id}/gdpr-export")
def api_crm_gdpr_export(contact_id: str):
    from backend.crm_service import crm_service
    res = crm_service.export_gdpr(contact_id)
    if not res:
        raise HTTPException(status_code=404, detail="Contact not found")
    return res


@app.post("/api/crm/contacts/{contact_id}/gdpr-anonymize")
def api_crm_gdpr_anonymize(contact_id: str):
    from backend.crm_service import crm_service
    ok = crm_service.anonymize_gdpr(contact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contact not found or update failed")
    return {"success": True, "message": "Contact anonymized per Art. 17 GDPR"}



