import os
import sys
import time
import datetime
import json
import httpx
import asyncio
import sqlite3

# --- External Agent URLs ---
# Defaulting to docker network hostnames, but can be overridden by env vars
HERMES_URL = os.getenv("HERMES_URL", "http://hermes-dashboard:9119")
ODYSSEUS_URL = os.getenv("ODYSSEUS_URL", "http://odysseus:7000")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:8080")
OMNIROUTE_URL = os.getenv("OMNIROUTE_URL", "http://omniroute:20128/v1")
N8N_URL = os.getenv("N8N_URL", "http://n8n:5678")

def detect_target_action(text: str, frontmatter: str = "") -> str:
    """
    Erkennt operative Folgeaktionen aus Prompt-Payload oder Frontmatter.
    Beispiele:
    - ACTION: POST_LINKEDIN -> publish_linkedin
    - ACTION: WEBHOOK_CRM -> webhook_crm
    - ACTION: NONE / keine Angabe -> none
    """
    try:
        import jev_router
        if jev_router.is_jev_enabled():
            c = jev_router.classify_prompt(text)
            if c.get("action") == "direct_command":
                return c.get("intent", "none")
    except Exception:
        pass

    combined = f"{frontmatter}\n{text}".upper()
    import re
    m = re.search(r'ACTION:\s*([A-Z0-9_\-]+)', combined)
    if m:
        action_val = m.group(1).strip().lower()
        if "linkedin" in action_val:
            return "publish_linkedin"
        elif "crm" in action_val:
            return "webhook_crm"
        elif "none" in action_val:
            return "none"
        return action_val
    if "POST_LINKEDIN" in combined or "PUBLISH_LINKEDIN" in combined:
        return "publish_linkedin"
    if "WEBHOOK_CRM" in combined:
        return "webhook_crm"
    return "none"

async def trigger_n8n_execution(
    parent_project_id: str,
    title: str,
    final_report_path: str,
    content: str,
    target_action: str = "none",
    timeout: int = 10
) -> dict:
    """
    Sendet einen asynchronen Outbound-Webhook an n8n (Port 5678).
    URL: http://n8n:5678/webhook/archon-execution
    """
    import datetime
    url = f"{N8N_URL}/webhook/archon-execution"
    payload = {
        "parent_project_id": parent_project_id,
        "title": title,
        "final_report_path": final_report_path,
        "content": content,
        "action": target_action or "none",
        "executed_at": datetime.datetime.now().isoformat()
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return {
                    "status": "success",
                    "code": 200,
                    "message": "n8n execution triggered successfully"
                }
            else:
                return {
                    "status": "warning",
                    "code": resp.status_code,
                    "message": f"n8n returned HTTP {resp.status_code} - stored locally"
                }
    except Exception as e:
        return {
            "status": "error",
            "message": f"n8n unreachable - stored locally: {str(e)}"
        }

async def dispatch_to_hermes(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """
    Routet Anfragen physisch an den Hermes Agent (Port 9119).
    Da Hermes eine Authentifizierung erfordert, muss ggf. ein API-Token als Header mitgeschickt werden.
    """
    url = f"{HERMES_URL}/api/chat"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('HERMES_API_TOKEN', '')}"
    }
    payload = {
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                # Versuche Standard-Chat-Completion Format zu lesen
                content = data.get("choices", [{}])[0].get("message", {}).get("content", str(data))
                return {"status": "success", "content": content}
            else:
                return {"status": "error", "content": f"Hermes Error (HTTP {resp.status_code}): {resp.text}"}
    except Exception as e:
        return {"status": "error", "content": f"Connection to Hermes failed: {str(e)}"}

async def dispatch_to_odysseus(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """
    Routet Anfragen physisch an den Odysseus Agent (Port 7000).
    """
    url = f"{ODYSSEUS_URL}/api/run"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("result", data.get("response", str(data)))
                return {"status": "success", "content": content}
            else:
                return {"status": "error", "content": f"Odysseus Error (HTTP {resp.status_code}): {resp.text}"}
    except Exception as e:
        return {"status": "error", "content": f"Connection to Odysseus failed: {str(e)}"}

async def dispatch_to_openclaw(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """
    Routet Anfragen physisch an OpenClaw. 
    (Kann über HTTP oder Subprocess aufgerufen werden, hier generisch als HTTP mock, bis CLI-Befehl bekannt ist).
    """
    url = f"{OPENCLAW_URL}/api/execute"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "task": prompt
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("output", str(data))
                return {"status": "success", "content": content}
            else:
                return {"status": "error", "content": f"OpenClaw Error (HTTP {resp.status_code}): {resp.text}"}
    except Exception as e:
        return {"status": "error", "content": f"Connection to OpenClaw failed: {str(e)}"}

def clean_think_tags(text: str) -> str:
    """
    Entfernt sauber alle <think>...</think> Abschnitte (sowohl geschlossene als auch offene/abgeschnittene).
    """
    if not text:
        return ""
    import re
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<think>[\s\S]*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()

def parse_omniroute_response(resp_text: str) -> str:
    """
    Parst Antworten von OpenAI-kompatiblen APIs (Groq, OmniRoute).
    Gibt den bereinigten Textinhalt zurück oder einen leeren String bei Fehlern.
    """
    if not resp_text:
        return ""
    try:
        data = json.loads(resp_text) if isinstance(resp_text, str) else resp_text
        if isinstance(data, dict):
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                msg = choice.get("message", {})
                content = msg.get("content") or choice.get("text") or ""
                if content:
                    return clean_think_tags(str(content))
            if "content" in data and data["content"]:
                return clean_think_tags(str(data["content"]))
    except Exception:
        pass

    # Server-Sent Events Parsing (data: {...})
    collected_content = []
    for line in resp_text.splitlines():
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            json_str = line[6:].strip()
            try:
                chunk = json.loads(json_str)
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content_piece = delta.get("content", "")
                    if content_piece:
                        collected_content.append(content_piece)
            except Exception:
                continue

    if collected_content:
        return clean_think_tags("".join(collected_content))
        
    return ""

# Globaler Concurrency Throttle (Pillar 2 / Prozessmodell)
# Drosselt gleichzeitige rechenintensive LLM-Tasks zum Schutz vor 99% CPU-Spitzen / Buffer Overflows
MAX_CONCURRENT_AGENT_TASKS = int(os.getenv("MAX_CONCURRENT_AGENT_TASKS", "5"))
_TASK_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AGENT_TASKS)

_DISPATCHER_HTTP_CLIENTS = {}

def _get_dispatcher_http_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    c = _DISPATCHER_HTTP_CLIENTS.get(loop_id)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(
            timeout=90.0,
            limits=httpx.Limits(max_keepalive_connections=25, max_connections=100)
        )
        _DISPATCHER_HTTP_CLIENTS[loop_id] = c
    return c

class _DispClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

def _log_dispatcher_usage(agent_id: str, model: str, in_tok: int, out_tok: int, task_id: str = ""):
    try:
        import sqlite3, os, time, sys
        db_path = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            
        with sqlite3.connect(db_path, timeout=15.0, factory=_DispClosingConn) as conn:
            conn.execute("PRAGMA busy_timeout=15000;")
            now = time.time()
            eff_task = task_id or f"agent_{agent_id}"
            s_id = f"task_{eff_task}" if not str(eff_task).startswith("task_") else str(eff_task)
            t_key = f"{eff_task}_{int(now)}"
            cost_usd = round((in_tok * 0.00000015) + (out_tok * 0.00000030), 6)
            
            cur = conn.cursor()
            cur.execute("SELECT id FROM sessions WHERE id = ?", (s_id,))
            if not cur.fetchone():
                unique_title = f"Task {eff_task[:25]} [{time.time_ns() % 1000000000}]"
                try:
                    cur.execute("""
                        INSERT OR IGNORE INTO sessions (
                            id, source, display_name, title, model, profile_name, started_at, message_count,
                            input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                        ) VALUES (?, 'agent_task', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """, (s_id, unique_title, unique_title, model, agent_id, now, in_tok, out_tok, cost_usd, cost_usd))
                except Exception:
                    pass
            
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
            """, (s_id, model, t_key, in_tok, out_tok, cost_usd, cost_usd, now, now))
            
            conn.execute("""
                UPDATE sessions 
                SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                    estimated_cost_usd = estimated_cost_usd + ?
                WHERE id = ?
            """, (in_tok, out_tok, cost_usd, s_id))
            
        if "main" in sys.modules:
            m = sys.modules["main"]
            if hasattr(m, "_LIVE_TELEMETRY_CACHE"):
                m._LIVE_TELEMETRY_CACHE["data"] = None
            if hasattr(m, "_MC_STATE_CACHE"):
                m._MC_STATE_CACHE["data"] = None
    except Exception as e:
        print(f"[DISPATCHER] Token telemetry write error: {e}", file=sys.stderr)

def _extract_tokens_usage(resp_text: str, prompt_str: str, reply_str: str):
    inp, out = max(50, len(prompt_str.split()) * 2), max(20, len(reply_str.split()) * 2)
    try:
        import json
        d = json.loads(resp_text) if isinstance(resp_text, str) else resp_text
        if isinstance(d, dict):
            u = d.get("usage", {})
            if isinstance(u, dict):
                inp = u.get("prompt_tokens") or u.get("input_tokens") or inp
                out = u.get("completion_tokens") or u.get("output_tokens") or out
    except Exception:
        pass
    return int(inp), int(out)

async def dispatch_to_omniroute_or_container(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "deepseek/deepseek-chat",
    provider: str = "",
    timeout: int = 15,
    reasoning_level: str = "medium",
    task_id: str = ""
) -> dict:
    """
    Zentraler Dispatcher: Nutzt dynamisch den im Profil konfigurierten Provider & das Sprachmodell.
    Ermittelt API-Keys live aus api_provider.collect_keys(), Profil-.env oder System-Environment.
    Geregelt über globalen Concurrency Throttle Semaphore (Pillar 2).
    Instrumentiert mit OpenTelemetry- / Langfuse-Spans.
    """
    t_start = time.time()
    async with _TASK_SEMAPHORE:
        res = await _dispatch_to_omniroute_or_container_exec(
            agent_id, agent_name, prompt, role, system_prompt, model, provider, timeout, reasoning_level, task_id
        )
        duration_ms = (time.time() - t_start) * 1000.0
        try:
            from backend.otel_tracer import tracer
            tr_id = f"task-{task_id}" if task_id else tracer.start_trace(f"exec.{agent_id}", task_id=task_id, agent_id=agent_id)
            tracer.record_span(
                trace_id=tr_id,
                name=f"llm.{agent_id}",
                span_type="llm",
                agent_id=agent_id,
                model=res.get("model") or model,
                input_data=prompt[:500],
                output_data=(res.get("content") or "")[:500],
                input_tokens=res.get("input_tokens", 0),
                output_tokens=res.get("output_tokens", 0),
                duration_ms=duration_ms,
                status="OK" if res.get("status") == "success" else "ERROR"
            )
        except Exception:
            pass
        return res

AUTO_MODEL_MAP = {
    "auto/best-reasoning": "deepseek/deepseek-r1",
    "auto/best-coding": "deepseek/deepseek-chat",
    "auto/best-vision": "google/gemini-2.5-flash",
    "auto/best-fast": "openai/gpt-4o-mini",
    "auto/best-free": "google/gemini-2.5-flash",
    "auto/best-creative": "anthropic/claude-3.5-sonnet",
}


async def _dispatch_to_omniroute_or_container_exec(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "deepseek/deepseek-chat",
    provider: str = "",
    timeout: int = 15,
    reasoning_level: str = "medium",
    task_id: str = ""
) -> dict:
    # Pillar 4 & Punkt 4: Aktive Memory-Injection (Erkenntnisse aus agentic_memory.db)
    memory_context_addon = ""
    try:
        from local_memory_bridge import LocalMemoryBridge
        bridge = LocalMemoryBridge()
        # Hole die wichtigsten und relevantesten Erkenntnisse für diesen Agenten
        query_hint = prompt[:100] if prompt else ""
        learnings = bridge.search_learnings(query_hint, limit=4)
        if learnings:
            lines = [f"- [{l.get('category', 'Allgemein')}] {l.get('summary')}" for l in learnings if l.get('summary')]
            if lines:
                memory_context_addon = "\n\n### [RELEVANTE ERKENNTNISSE AUS DEINEM LANGZEITGEDÄCHTNIS]:\n" + "\n".join(lines)
    except Exception as mem_err:
        pass

    # Prompt-Registry & Canary-Routing
    effective_prompt_info = None
    try:
        from backend.prompt_registry import prompt_registry
        eff = prompt_registry.get_effective_prompt(agent_id, task_id)
        if eff and eff.get("prompt"):
            system_prompt = eff["prompt"]
            effective_prompt_info = eff
            if eff.get("model") and not model:
                model = eff["model"]
    except Exception:
        pass

    full_system_prompt = f"Du bist {agent_name} (Rolle: {role}). {system_prompt}{memory_context_addon}".strip()

    messages = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": prompt}
    ]

    # Keys dynamisch aus api_provider und Environment ermitteln
    collected_keys = {}
    try:
        import api_provider
        collected_keys = api_provider.collect_keys()
    except Exception:
        pass

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY") or collected_keys.get("OPENROUTER_API_KEY") or ""
    groq_api_key = os.getenv("GROQ_API_KEY") or collected_keys.get("GROQ_API_KEY") or ""
    openai_api_key = os.getenv("OPENAI_API_KEY") or collected_keys.get("OPENAI_API_KEY") or ""
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or collected_keys.get("ANTHROPIC_API_KEY") or ""
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or collected_keys.get("GEMINI_API_KEY") or ""

    if isinstance(provider, (int, float)):
        timeout = int(provider)
        provider = ""
    prov_lower = (str(provider) if provider else "").strip().lower()
    if model in AUTO_MODEL_MAP:
        selected_model = AUTO_MODEL_MAP[model]
    elif model and model.startswith("auto/"):
        selected_model = AUTO_MODEL_MAP.get(model, "deepseek/deepseek-chat")
    else:
        selected_model = model.strip() if (model and model not in ("free-forever", "gpt-4o-mini", "default")) else "deepseek/deepseek-chat"

    # 1. Spezifischer Provider: GROQ
    if prov_lower == "groq" and groq_api_key:
        try:
            g_model = selected_model if ("llama" in selected_model or "gemma" in selected_model or "mixtral" in selected_model) else "llama-3.3-70b-versatile"
            client = _get_dispatcher_http_client()
            if True:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"},
                    json={"model": g_model, "messages": messages, "max_tokens": 1500, "temperature": 0.4}
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        _log_dispatcher_usage(agent_id, g_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": g_model}
        except Exception as e:
            print(f"[DISPATCHER] Groq direct call failed: {e}")

    # 2. Spezifischer Provider: OPENAI
    if prov_lower == "openai" and openai_api_key:
        try:
            o_model = selected_model if "gpt" in selected_model else "gpt-4o-mini"
            client = _get_dispatcher_http_client()
            if True:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"},
                    json={"model": o_model, "messages": messages, "max_tokens": 1500, "temperature": 0.4}
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        _log_dispatcher_usage(agent_id, o_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": o_model}
        except Exception as e:
            print(f"[DISPATCHER] OpenAI direct call failed: {e}")

    # 3. Spezifischer Provider: ANTHROPIC (mit Prompt-Caching für bis zu 90% Kostenreduktion)
    if prov_lower == "anthropic" and anthropic_api_key:
        try:
            a_model = selected_model if "claude" in selected_model else "claude-3-5-sonnet-20241022"
            client = _get_dispatcher_http_client()
            if True:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "anthropic-beta": "prompt-caching-2024-07-31",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": a_model,
                        "system": [
                            {
                                "type": "text",
                                "text": f"Du bist {agent_name} (Rolle: {role}). {system_prompt}".strip(),
                                "cache_control": {"type": "ephemeral"}
                            }
                        ],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1500
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = "".join([c.get("text", "") for c in data.get("content", [])])
                    if content:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        _log_dispatcher_usage(agent_id, a_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": a_model}
        except Exception as e:
            print(f"[DISPATCHER] Anthropic direct call failed: {e}")

    # 4. OpenRouter Gateway (Universal für DeepSeek, Claude, Llama, Qwen, Gemini etc.)
    if openrouter_api_key:
        try:
            or_payload = {
                "model": selected_model,
                "messages": messages,
                "max_tokens": 4096,
                "temperature": 0.4
            }
            r_lvl = (reasoning_level or "medium").strip().lower()
            effort_map = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "max": "high"}
            if r_lvl == "off":
                or_payload["reasoning"] = {"exclude": True}
            elif r_lvl in effort_map:
                or_payload["reasoning"] = {"effort": effort_map[r_lvl]}

            client = _get_dispatcher_http_client()
            if True:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "ArchonOS"
                    },
                    json=or_payload
                )
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    if content and len(content.strip()) > 5:
                        i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                        _log_dispatcher_usage(agent_id, selected_model, i_tok, o_tok, task_id)
                        return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": selected_model}
        except Exception as e:
            print(f"[DISPATCHER] OpenRouter call failed with model {selected_model}: {e}")

    # 5. Fallback: Groq Ultra-Fast API
    if groq_api_key:
        groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"]
        for g_model in groq_models:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {groq_api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": g_model,
                            "messages": messages,
                            "max_tokens": 1200,
                            "temperature": 0.5
                        }
                    )
                    if resp.status_code == 200:
                        content = parse_omniroute_response(resp.text)
                        if content and len(content.strip()) > 5:
                            i_tok, o_tok = _extract_tokens_usage(resp.text, prompt, content)
                            _log_dispatcher_usage(agent_id, g_model, i_tok, o_tok, task_id)
                            return {"status": "success", "content": content, "input_tokens": i_tok, "output_tokens": o_tok, "model": g_model}
            except Exception as e:
                continue

    # 3. Tertiär: OmniRoute Gateway (Port 20128)
    omni_urls = [
        "http://omniroute:20128/v1/chat/completions",
        f"{OMNIROUTE_URL}/chat/completions"
    ]
    omni_payload = {
        "model": model if (model and model != "free-forever") else "auto/best-coding",
        "messages": messages
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for omni_url in omni_urls:
            try:
                resp = await client.post(omni_url, json=omni_payload)
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    return {"status": "success", "content": content}
            except Exception as e:
                continue

    # 3b. Direkter OpenRouter-Fallback bei OmniRoute-Ausfall / Rate-Limit
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        try:
            or_model = model
            auto_map = {
                "auto/best-coding": "deepseek/deepseek-chat",
                "auto/best-reasoning": "deepseek/deepseek-r1",
                "auto/best-vision": "google/gemini-2.5-flash",
                "auto/best-fast": "openai/gpt-4o-mini",
                "auto/best-free": "google/gemini-2.5-flash"
            }
            or_model = auto_map.get(or_model, or_model)
            if or_model.startswith("auto/") or or_model in ("", "free-forever"):
                or_model = "deepseek/deepseek-chat"
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json"},
                    json={"model": or_model, "messages": messages, "max_tokens": 4096}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return {"status": "success", "content": content}
        except Exception:
            pass

    # 4. Direkte Container-Endpunkte
    direct_urls = [
        f"http://{agent_id}:8080/api/chat",
        f"http://{agent_id}:8000/api/run",
        f"http://{agent_id}:8080/v1/chat/completions"
    ]
    async with httpx.AsyncClient(timeout=5) as client:
        for url in direct_urls:
            try:
                resp = await client.post(url, json={"prompt": prompt, "messages": messages})
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("content") or data.get("output") or data.get("result") or str(data)
                    return {"status": "success", "content": content}
            except Exception:
                continue

        # 5. Robuste Fehlerbehandlung (Keine Dummy-Bereitschaftsmeldung vortaeuschen)
    err_msg = f"[FEHLER: Kein Sprachmodell-Provider erreichbar fuer @{agent_id} ({agent_name}) mit Modell '{selected_model}']"
    print(f"[DISPATCHER-ERROR] {err_msg}")
    return {
        "status": "error",
        "content": err_msg,
        "error": "No LLM provider available"
    }

async def dispatch_to_external_agent(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "free-forever",
    timeout: int = 30,
    provider: str = "",
    reasoning_level: str = "medium"
) -> dict:
    """
    Haupt-Dispatcher: Routet Anfragen primär an den Container und fällt nahtlos auf OmniRoute (Port 20128) zurück.
    """
    if agent_id == "hermes":
        res = await dispatch_to_hermes(agent_name, prompt, timeout)
        if res["status"] == "success":
            return res
    elif agent_id == "odysseus":
        res = await dispatch_to_odysseus(agent_name, prompt, timeout)
        if res["status"] == "success":
            return res
    elif agent_id == "openclaw" or agent_id == "openclaw-docker":
        res = await dispatch_to_openclaw(agent_name, prompt, timeout)
        if res["status"] == "success":
            return res
            
    # Falls der spezifische Container-Endpoint fehlschlägt oder ein anderer Agent gewählt wurde, OmniRoute Gateway nutzen!
    return await dispatch_to_omniroute_or_container(
        agent_id=agent_id,
        agent_name=agent_name,
        prompt=prompt,
        role=role,
        system_prompt=system_prompt,
        model=model,
        provider=provider,
        timeout=timeout,
        reasoning_level=reasoning_level
    )

CATEGORIZED_FRAMEWORKS = {
    "1. Bisherige, Agile & Innovation": {
        "CLEAR-Model": """[METHODIK-FRAMEWORK: CLEAR-MODELL]
Du wendest auf jede Fragestellung strikt das CLEAR-Analysemodell an. Strukturiere deine Denkweise und deine Ausgabe ausnahmslos in folgenden 5 Phasen:

1. CONCISE (Prägnanz):
- Reduziere die Problemstellung auf maximal 2-3 Kernsätze. Eliminiere Ablenkungen und Nebenschauplätze.

2. LOGICAL (Logische Kausalität):
- Baue eine lückenlose Argumentationskette auf (Wenn X, dann Y, weil Z). Decke Fehlschlüsse oder unbewiesene Annahmen auf.

3. EXPLICIT (Eindeutigkeit):
- Vermeide vage Begriffe. Benenne konkrete Zahlen, Methoden, Werkzeuge, Verantwortlichkeiten und eindeutige Handlungsoptionen.

4. ADAPTIVE (Anpassungsfähigkeit):
- Teste die Lösung gegen veränderte Rahmenbedingungen und Edge Cases. Zeige mindestens eine funktionale Alternative auf.

5. REFLECTIVE (Selbstkritik):
- Unterziehe dein eigenes Ergebnis einem Stresstest: Wo liegen Schwachstellen, Risiken oder blinde Flecken?

AUSGABE-FORMAT:
Antworte zwingend mit den Abschnitten:
[C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective""",

        "CREATE-Framework": """[METHODIK-FRAMEWORK: CREATE-FRAMEWORK]
Du analysierst und löst die Aufgabe entlang der 6 Stufen der verhaltensökonomischen CREATE-Action-Funktion:

1. C - Cue (Auslöser): Welches Signal oder Ereignis stößt das Problem/Verhalten an?
2. R - Reaction (Intuitive Reaktion): Welche unmittelbare, kognitive Reaktion erfolgt (System 1)?
3. E - Evaluation (Bewertung): Welche Vor- und Nachteile werden abgewogen (System 2)?
4. A - Ability (Fähigkeit/Hürden): Ist die Umsetzung einfach genug? Wo liegen Reibungsverluste/Komplexität?
5. T - Timing (Dringlichkeit): Warum muss die Handlung JETZT erfolgen?
6. E - Execute (Ausführung): Wie sieht die konkrete finale Umsetzungsschleife aus?

AUSGABE-FORMAT:
Gliedere deine Lösung sauber in die Abschnitte [C], [R], [E], [A], [T] und [E].""",

        "Design Sprint (GV / Jake Knapp)": """[METHODIK-FRAMEWORK: 5-TAGE DESIGN SPRINT]
Simuliere und durchlaufe den Design-Sprint-Prozess in 5 klaren Schritten:

1. MAP (Verstehen & Kartieren): Definiere das langfristige Ziel, zeichne die Map des Problems und wähle den Fokusbereich.
2. SKETCH (Lösungen skizzieren): Generiere verschiedene, konkurrierende Lösungsansätze im Detail.
3. DECIDE (Entscheiden): Bewerte die Ansätze kritisch und wähle die stärkste Hypothese aus.
4. PROTOTYPE (Fokussierter Prototyp): Erstelle eine konkrete, detaillierte Spezifikation/Skizze des kleinstmöglichen Testobjekts.
5. TEST (Validierung): Definiere 3-5 konkrete Testfragen und Metriken zur Überprüfung der Lösung.

AUSGABE-FORMAT:
Nutze die Abschnitte: ### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test""",

        "Double Diamond (Design Council)": """[METHODIK-FRAMEWORK: DOUBLE DIAMOND]
Löse das Problem durch den Wechsel von divergentem (öffnendem) und konvergentem (schließendem) Denken:

DIAMOND 1: DAS RICHTIGE PROBLEM FINDEN
1. Discover (Entdecken - Divergent): Exploriere das Problemfeld breit. Welche versteckten Aspekte und Perspektiven gibt es?
2. Define (Definieren - Konvergent): Verdichte die Erkenntnisse auf die eine, entscheidende Problemstellung (Problem-Definition).

DIAMOND 2: DIE RICHTIGE LÖSUNG ENTWERFEN
3. Develop (Entwickeln - Divergent): Generiere vielfältige Lösungsmöglichkeiten ohne unmittelbare Bewertung.
4. Deliver (Liefern - Konvergent): Wähle die beste Lösung, verfeinere sie und mache sie sofort einsatzbereit.

AUSGABE-FORMAT:
Nutze die Abschnitte: [1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]""",

        "Lean Startup (Eric Ries)": """[METHODIK-FRAMEWORK: LEAN STARTUP (BUILD-MEASURE-LEARN)]
Wende den empirischen Feedbackzyklus zur schnellen Hypothesenprüfung an:

1. HYPOTHESE (Glaubenssatz): Welche unbewiesene Grundannahme muss wahr sein, damit das Vorhaben funktioniert?
2. BUILD (MVP): Entwirf das Minimum Viable Product mit der geringsten Komplexität, um die Hypothese zu testen.
3. MEASURE (Messen): Definiere konkrete, nicht-manipulierbare Kennzahlen (Actionable Metrics statt Vanity Metrics).
4. LEARN (Lernen & Pivot/Persevere): Analysiere das Ergebnis: Soll das Konzept beibehalten (Persevere) oder angepasst (Pivot) werden?

AUSGABE-FORMAT:
Strukturiere deine Antwort in: 1. Hypothese | 2. Build (MVP) | 3. Measure (Metriken) | 4. Learn (Pivot/Persevere)""",

        "OKRs (Objectives and Key Results)": """[METHODIK-FRAMEWORK: OBJECTIVES AND KEY RESULTS]
Übersetze die Aufgabenstellung in ein operationalisierbares OKR-Set:

1. OBJECTIVE (Qualitatives Ziel):
- Formuliere 1-2 ambitionierte, inspirierende und einprägsame Ziele (Wo wollen wir hin?).

2. KEY RESULTS (Quantitative Messergebnisse):
- Definiere pro Objective 3 konkrete, messbare Key Results (Wie messen wir den Erfolg?).
- Format: "Steigerung/Reduzierung von X auf Y bis Z".

3. INITIATIVES (Konkrete Maßnahmen):
- Liste die spezifischen Aufgaben und Projekte auf, die notwendig sind, um die Key Results zu erreichen.

AUSGABE-FORMAT:
Verwende die Struktur: ### Objective | ### Key Results (1-3) | ### Initiativen & Action Items""",

        "STEEPLE / PESTEL": """[METHODIK-FRAMEWORK: STEEPLE / PESTEL ANALYSE]
Analysiere das externe Umfeld der Problemstellung systematisch nach folgenden 7 Makro-Faktoren:

1. Social (Soziokulturell): Demografie, Verhalten, Werte.
2. Technological (Technologisch): Innovationen, Automatisierung, Tech-Hürden.
3. Economic (Ökonomisch): Kosten, Inflation, Marktstrukturen.
4. Environmental (Ökologisch): Nachhaltigkeit, Ressourcen, Umweltauflagen.
5. Political (Politisch): Regulierungen, Stabilität, Vorgaben.
6. Legal (Rechtlich): DSGVO, Haftung, Gesetze.
7. Ethical (Ethisch): Fairness, Transparenz, KI-Ethik.

AUSGABE-FORMAT:
Führe für jeden Buchstaben [S], [T], [E], [E], [P], [L], [E] eine kurze, prägnante Risiko- und Chancenbewertung durch.""",

        "Steffi Kieffer Boardroom": """[METHODIK-FRAMEWORK: AI BOARDROOM DEBATE]
Führe eine mehrperspektivische Boardroom-Debatte durch, in der unterschiedliche Spezialisten-Perspektiven aufeinandertreffen:

1. CHARMING MODERATOR (Einleitung): Rahmenbedingung setzen und Problem präzise formulieren.
2. SKEPTIKER / RISIKOANALYSATOR: Hinterfragt Annahmen, deckt Sicherheits- und Umsetzungsrisiken auf.
3. STRATEGISCHER OPTIMIST / INNOVATOR: Fokus auf Chancen, Effizienzsteigerung und Zukunftsfähigkeit.
4. PRAGMATISCHER IMPLEMENTIERER: Fokus auf technische Machbarkeit, Ressourcen und unmittelbaren Code/Schritte.
5. CHAIRMAN SYNTHESIS (Fazit): Wiegt die Argumente gegeneinander ab und liefert eine klare, unmissverständliche Entscheidung.

AUSGABE-FORMAT:
Zeige den Dialog der Rollen gefolgt von der hervorgehobenen [CHAIRMAN SYNTHESIS]."""
    },
    "2. Ursachenanalyse, Logik & Problem-Solving": {
        "5-Why-Methode": """[METHODIK-FRAMEWORK: 5-WHY URSACHENANALYSE]
Dringe durch kaskadierendes Hinterfragen zur tatsächlichen Wurzel des Problems (Root Cause) vor:

- Problem-Statement: [Symptom präzise beschreiben]
- Warum 1: Warum tritt dieses Symptom auf? -> Antwort 1
- Warum 2: Warum passiert Antwort 1? -> Antwort 2
- Warum 3: Warum passiert Antwort 2? -> Antwort 3
- Warum 4: Warum passiert Antwort 3? -> Antwort 4
- Warum 5: Warum passiert Antwort 4? -> WURZELURSACHE (Root Cause)

KORREKTURMAßNAHME:
Definiere eine dauerhafte Lösung, die exakt an der Wurzelursache ansetzt (nicht am Symptom!).

AUSGABE-FORMAT:
Liste die 5 Why-Schritte untereinander auf und schließe mit: ### Wurzelursache & ### Gegenmaßnahme.""",

        "Cynefin-Framework (Dave Snowden)": """[METHODIK-FRAMEWORK: CYNEFIN DOMÄNEN-ANALYSE]
Ordnest die Problemstellung zuerst der richtigen System-Domäne zu und wendest das dazugehörige Handlungsmuster an:

1. DOMÄNEN-DIAGNOSE: In welcher Domäne befindet sich das Problem?
   - Offensichtlich (Simple): Ursache-Wirkung klar -> Erkennen - Kategorisieren - Reagieren.
   - Kompliziert (Complicated): Expertenwissen nötig -> Erkennen - Analysieren - Reagieren.
   - Komplex (Complex): Keine klare Ursache-Wirkung -> Probieren - Erkennen - Reagieren.
   - Chaotisch (Chaotic): Mitten im Brand -> Handeln - Erkennen - Reagieren.

2. HANDLUNGSSTRATEGIE: Leite die exakten Schritte basierend auf der diagnostizierten Domäne ab.

AUSGABE-FORMAT:
### Domänen-Zuordnung | ### Begründung | ### Handlungsstrategie""",

        "First Principles Thinking": """[METHODIK-FRAMEWORK: FIRST PRINCIPLES THINKING]
Zerlege das Problem in seine fundamentalsten Wahrheitselemente und baue von Grund auf eine neue Lösung:

1. DEKONSTRUKTION (Annahmen streichen):
   - Welche Analogien, Gewohnheiten und Branchen-Mythen verdecken das Problem? Lösche alle "Das haben wir schon immer so gemacht"-Annahmen.

2. FUNDAMENTALE WAHRHEITEN (Physik/Fakten):
   - Was sind die unumstößlichen, mathematischen, technischen oder logischen Fakten des Problems?

3. REKONSTRUKTION (Neuaufbau):
   - Baue aus diesen Grundbausteinen eine völlig neue, optimierte Lösung auf, ohne bestehende Denkmuster zu kopieren.

AUSGABE-FORMAT:
Strukturiere in: [1. Bekannte Annahmen verwerfen] | [2. Fundamentale Fakten] | [3. Neuaufbau aus Grundprinzipien]""",

        "Ishikawa-Diagramm (6M)": """[METHODIK-FRAMEWORK: ISHIKAWA (URSACHEN-WIRKUNGS-DIAGRAMM)]
Untersuche die Fehlerursachen systematisch anhand der 6M-Kategorien:

1. Mensch: Unwissenheit, Überlastung, Schnittstellenfehler.
2. Maschine/Tooling: Hardware, Server, Bug in der KI/Software.
3. Methode: Mangelhafte Prozesse, falsche Logik, fehlende Vorgaben.
4. Material/Daten: Mangelhafte Datenqualität, fehlerhafte Prompts/Input.
5. Milieu/Umfeld: Systemumgebung, Zeitdruck, Netzwerklatenzen.
6. Messung: Falsche Metriken, fehlendes Monitoring, ungenaue Logs.

HAUPTURSACHE & LÖSUNG:
Identifiziere die wahrscheinlichste Hauptursache über alle 6 Achsen hinweg.

AUSGABE-FORMAT:
Gliedere die Analyse in die 6M-Blöcke und schließe mit: ### Hauptfehlerquelle.""",

        "Porter's Five Forces": """[METHODIK-FRAMEWORK: PORTER'S 5 FORCES BRANCHENANALYSE]
Bewerte die Wettbewerbsintensität und Attraktivität der Problemstellung/des Marktes:

1. Rivalität unter bestehenden Wettbewerbern (Hoch/Mittel/Gering)
2. Bedrohung durch neue Anbieter (Eintrittsbarrieren)
3. Verhandlungsmacht der Lieferanten (Tech-Provider, APIs, Datenquellen)
4. Verhandlungsmacht der Abnehmer (Kunden, Nutzer)
5. Bedrohung durch Ersatzprodukte (Substitutionsrisiko durch andere Tech)

STRATEGISCHE EMPFEHLUNG: Wie kann das System/Produkt eine uneinnehmbare Festung (Moat) aufbauen?

AUSGABE-FORMAT:
Analysiere die 5 Kräfte einzeln und schließe mit: ### Strategische Positionierung & Moat.""",

        "SWOT-Analyse": """[METHODIK-FRAMEWORK: STRATEGISCHE SWOT-ANALYSE]
Führe eine strukturierte Matrix-Analyse der internen und externen Faktoren durch:

INTERNE FAKTOREN:
- Strengths (Stärken): Was sind die Alleinstellungsmerkmale und Kernkompetenzen?
- Weaknesses (Schwachstellen): Wo liegen Engpässe, Wissenslücken oder Ineffizienzen?

EXTERNE FAKTOREN:
- Opportunities (Chancen): Welche Markttrends, Automatisierungen oder Lücken lassen sich nutzen?
- Threats (Risiken): Welche externen Gefahren (Regulierung, Konkurrenz, Tech-Shifts) drohen?

STRATEGISCHE KRUZUNG (TOWS):
Leite mindestens 2 konkrete SO-Strategien (Stärken nutzen um Chancen zu ergreifen) und ST-Strategien (Stärken nutzen um Risiken abzuwehren) ab.

AUSGABE-FORMAT:
Verwende die Abschnitte: [Stärken] | [Schwächen] | [Chancen] | [Risiken] | [TOWS-Strategieableitung]"""
    },
    "3. Operations, Lean & Qualität": {
        "DMAIC (Six Sigma)": """[METHODIK-FRAMEWORK: DMAIC (SIX SIGMA PROZESSOPTIMIERUNG)]
Sichere die Qualität und eliminiere Prozessabweichungen strikt in 5 Phasen:

1. DEFINE (Definieren): Was ist das Problem? Wer ist der Kunde? Was ist der Qualitätsanspruch (CTQ)?
2. MEASURE (Messen): Wie sieht der aktuelle Ist-Zustand aus? Welche Daten/Metriken liegen vor?
3. ANALYZE (Analysieren): Was sind die Kernursachen für Streuung und Fehler im Prozess?
4. IMPROVE (Verbessern): Welche Maßnahmen beseitigen die Fehlerursachen vollständig?
5. CONTROL (Steuern): Wie wird der neue Standard dauerhaft überwacht (KPIs, Alerts)?

AUSGABE-FORMAT:
Strukturiere deine Antwort in die 5 Abschnitte: [Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control].""",

        "PDCA-Zyklus (Demingkreis)": """[METHODIK-FRAMEWORK: PDCA CONTINUOUS IMPROVEMENT]
Durchlaufe den kontinuierlichen Verbesserungsprozess:

1. PLAN (Planen): Analysiere die Ist-Situation, definiere das Ziel und erstelle einen konkreten Umsetzungsplan.
2. DO (Umsetzen): Führe den Plan testweise oder im kleinen Rahmen aus (Prototyping/Pilotierung).
3. CHECK (Überprüfen): Vergleiche die Ergebnisse der Umsetzung direkt mit den ursprünglichen Zielen. Wo gab es Abweichungen?
4. ACT (Agieren): Standardisiere die erfolgreiche Lösung oder passe den Plan an und starte den Zyklus neu.

AUSGABE-FORMAT:
Verwende die Abschnitte: ### Plan | ### Do | ### Check | ### Act""",

        "Theory of Constraints (TOC)": """[METHODIK-FRAMEWORK: THEORY OF CONSTRAINTS (ENGPASS-THEORIE)]
Maximiere den Durchsatz des gesamten Systems durch Fokussierung auf den schwächsten Punkt (Bottleneck):

1. IDENTIFIZIEREN: Welches ist der eine, primäre Engpass, der den Gesamtdurchsatz limitiert?
2. AUSNUTZEN: Wie kann dieser Engpass ohne große Investitionen maximal effizient ausgelastet werden?
3. UNTERORDNEN: Richte alle anderen Prozesse und Schritte im System strikt nach dem Takt des Engpasses aus.
4. BESEITIGEN: Investiere Ressourcen, um die Kapazität des Engpasses drastisch zu erweitern.
5. NIEMALS AUFHÖREN: Sobald der Engpass gehoben ist, suche sofort den NÄCHSTEN Engpass (Vermeidung von Trägheit).

AUSGABE-FORMAT:
Gliedere in: [1. Primärer Engpass] | [2. Ausnutzung] | [3. Unterordnung] | [4. Behebung]"""
    },
    "4. Strategie, Priorisierung & Change": {
        "Eisenhower-Matrix": """[METHODIK-FRAMEWORK: EISENHOWER PRIORISIERUNGS-MATRIX]
Kategorisiere alle anstehenden Teilaufgaben strikt nach Wichtigkeit und Dringlichkeit:

1. DO FIRST (Wichtig & Dringend): Sofort selbst erledigen. Exakte Ausführungsschritte festlegen.
2. SCHEDULE (Wichtig & Nicht Dringend): Terminieren und strategisch durchdenken (Hauptfokus für Langzeiterfolg).
3. DELEGATE (Nicht Wichtig & Dringend): An spezialisierte Sub-Agenten oder automatisierte Skripte auslagern.
4. ELIMINATE (Nicht Wichtig & Nicht Dringend): Komplett streichen und als Ablenkung identifizieren.

AUSGABE-FORMAT:
Präsentiere die Aufgaben aufgeteilt in die 4 Quadranten: [Quadrant I: Do] | [Quadrant II: Schedule] | [Quadrant III: Delegate] | [Quadrant IV: Eliminate]""",

        "Kano-Modell": """[METHODIK-FRAMEWORK: KANO MERKMAL-ANALYSE]
Klassifiziere die Systemfunktionen/Features nach ihrer Auswirkung auf die Nutzerzufriedenheit:

1. BASIS-MERKMALE (Must-Haves): Selbstverständliche Funktionen. Fehlen sie, herrscht große Unzufriedenheit.
2. LEISTUNGS-MERKMALE (Linear): Je mehr/schneller vorhanden, desto höher die Zufriedenheit (z.B. Geschwindigkeit, Token-Preis).
3. BEGEISTERUNGS-MERKMALE (Delighters): Unerwartete Features, die einen Aha-Effekt auslösen und echte Alleinstellung schaffen.
4. UNERWÜNSCHTE/INERHEBLICHE MERKMALE: Features, die keinen Mehrwert stiften oder den Nutzer verwirren.

AUSGABE-FORMAT:
Kategorisiere die Lösungselemente in: [Must-Haves] | [Performance-Features] | [Begeisterungs-Features]""",

        "Kotter 8-Stufen-Modell": """[METHODIK-FRAMEWORK: KOTTER CHANGE MANAGEMENT]
Strukturiere die Transformation / Systemumstellung entlang der 8 Stufen des Change Managements:

1. Dringlichkeit erzeugen (Urgency)
2. Führungskoalition aufbauen (Guiding Coalition)
3. Vision und Strategie entwickeln (Vision)
4. Die Vision kommunizieren (Communication)
5. Hindernisse beseitigen (Empowerment)
6. Schnelle Erfolge erzielen (Short-Term Wins)
7. Erfolge konsolidieren und weitere Veränderungen anstoßen (Consolidation)
8. Neue Ansätze in der Kultur verankern (Institutionalization)

AUSGABE-FORMAT:
Liefere für jede der 8 Stufen eine konkrete Handlungsanweisung für das System/Team.""",

        "McKinsey 7S": """[METHODIK-FRAMEWORK: MCKINSEY 7S ORGANISATIONSANALYSE]
Analysiere die ganzheitliche Abstimmung des Systems über 7 Dimensionen:

HARD S (Harte Faktoren):
1. Strategy (Strategie): Ausrichtung und Wettbewerbsvorteil.
2. Structure (Struktur): Systemarchitektur und Modulaufbau.
3. Systems (Systeme): Prozesse, Pipelines und Workflows.

SOFT S (Weiche Faktoren):
4. Shared Values (Unternehmenskultur/Leitbild): Grundwerte der Lösung.
5. Style (Führungsstil/Modell-Verhalten): Wie agiert das System?
6. Staff (Personal/Agenten-Ressourcen): Fähigkeiten der eingesetzten LLMs.
7. Skills (Fähigkeiten/Tools): Verfügbare APIs und operationaler Funktionsumfang.

AUSGABE-FORMAT:
Gliedere in [Hard S] und [Soft S] und zeige Diskrepanzen zwischen den Dimensionen auf.""",

        "NABC-Methode": """[METHODIK-FRAMEWORK: NABC PITCH & VALUE PROPOSITION]
Formuliere die Lösung als prägnanten, überzeugenden Wertantrag (Pitch):

1. NEED (Bedürfnis): Welches konkrete, schmerzhafte Problem des Nutzers/Systems wird adressiert?
2. APPROACH (Ansatz): Wie sieht die spezifische, innovative Lösung aus?
3. BENEFIT (Nutzen): Welchen quantifizierbaren Mehrwert/Ersparnis bringt der Ansatz?
4. COMPETITION (Wettbewerb/Alternativen): Warum ist dieser Ansatz besser als bestehende Alternativen?

AUSGABE-FORMAT:
Gliedere die Antwort präzise in: [Need] | [Approach] | [Benefit] | [Competition].""",

        "RICE-Priorisierung": """[METHODIK-FRAMEWORK: RICE PRIORISIERUNGS-SCORE]
Bewerte und ranke Backlog-Items, Features oder Handlungsoptionen quantitativ nach der RICE-Formel:
RICE Score = (Reach x Impact x Confidence) / Effort

1. REACH (Reichweite): Wie viele Nutzer/Prozesse/Kunden sind pro Quartal betroffen? (Konkrete absolute Zahl).
2. IMPACT (Auswirkung): Welchen Effekt hat das Item auf den Nutzer/das Ziel?
   - 3 = Massiv, 2 = Hoch, 1 = Mittel, 0.5 = Gering, 0.25 = Minimal.
3. CONFIDENCE (Zuversicht): Wie verlässlich sind unsere Daten/Annahmen?
   - 100% = Hohe Evidenz / Datenbasis, 80% = Mittlere Datenlage, 50% = Schätzung / Bauchgefühl.
4. EFFORT (Aufwand): Wie viele Personenmonate oder Entwicklungszeitfenster werden benötigt? (1 = 1 Monat / 1 Sprint).

SCORE-BERECHNUNG:
Berechne für jede Option den numerischen RICE-Score und erstelle eine absteigende Prioritätenliste mit klarer Umsetzungsbegründung.

AUSGABE-FORMAT:
Tabellarische Matrix: Option | Reach | Impact | Confidence | Effort | RICE Score | Empfehlung""",

        "Make-or-Buy / TCO-Scoring": """[METHODIK-FRAMEWORK: MAKE-OR-BUY & TCO-ANALYSE]
Führe eine strukturierte Bewertung für Build vs. Buy vs. Partner durch, insbesondere für KI-, Software- und Infrastruktur-Entscheidungen:

1. KERNKOMPETENZ & DIFFERENZIERUNG:
- Gehört das Modul zur Kern-IP und strategischen Differenzierung (Build) oder ist es Standard-Commodity (Buy)?

2. TOTAL COST OF OWNERSHIP (TCO) ÜBER 36 MONATE:
- Build: Initiale Entwicklungskosten + laufende Wartung, Security-Patches, Hosting/Hardware, Opportunitätskosten des Dev-Teams.
- Buy: SaaS-/API-Lizenzkosten, Vendor-Lock-in-Risiko, Integrationsaufwand, Token-Preiserhöhungsrisiko.
- Partner: Integrations- und Betreuungskosten, Abhängigkeit von Drittdienstleistern.

3. ZEITHORIZONT & TIME-TO-MARKET:
- Wie viele Wochen/Monate Vorsprung verschafft die Buy-Option gegenüber einer Eigenentwicklung?

4. DATENSCHUTZ, SOUVERÄNITÄT & RUNTIME-KONTROLLE:
- Verbleiben sensible Kundendaten auf eigener Hardware (On-Prem / Selbst-Hosting) oder fließen Daten an externe US-Cloud-Hyperscaler?

DECISION MATRIX & VERDIKT:
Fälle ein unmissverständliches Verdikt: Build, Buy oder Partner mit Meilensteinplan für die nächsten 90 Tage.

AUSGABE-FORMAT:
### Differenzierung & IP | ### TCO-3-Jahres-Vergleich | ### Risiko & Souveränität | ### Klares Verdikt & Roadmap"""
    },
    "5. Kognitive Entzerrung & Kritisches Denken": {
        "Ladder of Inference (Chris Argyris)": """[METHODIK-FRAMEWORK: LADDER OF INFERENCE]
Lege deine kognitive Schlussfolgerungskette von den Rohdaten bis zur Handlung transparent offen, um Fehlschlüsse zu vermeiden:

1. ROHDATEN: Welche beobachtbaren Fakten/Codezeilen wurden ausgewählt?
2. GEFILTERTE DATEN: Welche Daten wurden ignoriert oder hervorgehoben?
3. BEDEUTUNG (Sinngebung): Welche Bedeutung wird den Daten zugeschrieben?
4. ANNAHMEN: Welche unbewiesenen Vorannahmen fließen ein?
5. SCHLUSSFOLGERUNG: Welche logische Konsequenz wird gezogen?
6. HANDLUNG: Welche konkrete Aktion folgt daraus?

AUSGABE-FORMAT:
Zeige die Leiter von unten nach oben: [Sprosse 1: Daten] -> [Sprosse 2: Selektion] -> [Sprosse 3: Annahmen] -> [Sprosse 4: Aktion]""",

        "Pre-Mortem Analyse (Gary Klein)": """[METHODIK-FRAMEWORK: PRE-MORTEM ANALYSE]
Setze voraus, dass das geplante Projekt/der Code in 12 Monaten krisenhaft und vollständig gescheitert ist. Nimm diesen Misserfolg als mathematische Tatsache hin und arbeite rückwärts:

1. GESCHICHTE DES SCHEITERNS:
- Beschreibe das genaue Szenario des Totalschadens. Was ist schiefgegangen?

2. URSACHEN-BRAINSTORMING:
- Liste alle verdeckten Risiken, schlechten Annahmen, Zeitfresser und technischen Schwachstellen auf, die zu diesem Scheitern geführt haben.

3. PRE-EMPTIVE MAßNAHMEN:
- Leite sofortige, präventive Korrekturmaßnahmen ab, um jeden einzelnen identifizierten Scheiter-Grund HEUTE noch zu verhindern.

AUSGABE-FORMAT:
Strukturiere in: [1. Das Scheiter-Szenario] | [2. Identifizierte Todesursachen] | [3. Präventive Schutzmaßnahmen]""",

        "Red Teaming / Adversarial Analysis": """[METHODIK-FRAMEWORK: RED TEAMING / ADVERSARIAL ATTACK]
Nimm die Rolle eines aggressiven, externen Angreifers / Gegners ein und zerlege das vorgelegte Konzept:

1. ATTACK VECTORS (Angriffsflächen):
- Wo liegen Schwachstellen in der Logik, Sicherheit, Performance oder Usability?

2. EXPLOITATION (Ausnutzung):
- Wie könnte ein Gegner, Edge Case oder Systemfehler diese Lücke maximal ausnutzen?

3. DEFENSIVE HARDENING (Härtung):
- Wie muss das Konzept/der Code sofort umgebaut werden, um diesen Angriff vollkommen unmöglich zu machen?

AUSGABE-FORMAT:
### Angriffsvektoren | ### Ausnutzungs-Szenario | ### Härtungs-Maßnahmen (Blue Team)""",

        "Six Thinking Hats (Edward de Bono)": """[METHODIK-FRAMEWORK: SIX THINKING HATS]
Analysiere die Aufgabenstellung konsequent aus 6 klar getrennten Denkperspektiven:

1. WEIßER HUT (Fakten): Welche reinen Daten, Fakten und Informationen liegen vor? Was fehlt?
2. ROTER HUT (Emotionen): Welche intuitiven Bedenken, Ängste oder Bauchgefühle gibt es?
3. SCHWARZER HUT (Kritik): Wo liegen die Gefahren, Risiken, Schwachstellen und Hürden?
4. GELBER HUT (Optimismus): Was sind die Best-Case-Chancen, Vorteile und der Nutzen?
5. GRÜNER HUT (Kreativität): Welche unkonventionellen, alternativen Wege gibt es noch?
6. BLAUER HUT (Prozess): Wie sieht die finale Synthese und der nächste Prozessschritt aus?

AUSGABE-FORMAT:
Antworte zwingend geordnet nach den 6 Hüten: ⚪ Weiß | 🔴 Rot | 🖤 Schwarz | 🟡 Gelb | 🟢 Grün | 🔵 Blau""",

        "Game-Theoretic Mechanism Design": """[METHODIK-FRAMEWORK: SPIELTHEORIE & MECHANISM DESIGN]
Analysiere die Situation als spieltheoretisches System aus strategischen Akteuren, Anreizen und Informationsasymmetrien:

1. SPIELER & ZIELE (Akteure):
- Wer sind die handelnden Parteien (z.B. Käufer, Verkäufer, Wettbewerber, Nutzer, Agenten)? Welche Nutzenfunktionen maximieren sie?

2. ANREIZSTRUKTUREN & FEHLANREIZE (Incentive Alignment):
- Wo existieren Moral Hazard, Principal-Agent-Konflikte oder adverse Selektion? Welche Handlungen werden belohnt, welche bestraft?

3. GLEICHGEWICHTSANALYSE (Nash-Gleichgewicht):
- In welchem stabilen Zustand endet das System, wenn jeder Akteur eigennützig und rational seine beste Antwort wählt?

4. MECHANISM DESIGN & AUKTIONSTHEORIE:
- Wie müssen Regeln, Auszahlungsmatrizen, Verträge oder Bietverfahren (z.B. Vickrey-Auktion, Stufenrabatte, Earn-Outs) gestaltet werden, damit ehrliches Verhalten und Kooperation die dominante Strategie werden?

AUSGABE-FORMAT:
### Akteure & Nutzenfunktionen | ### Fehlanreize & Asymmetrien | ### Nash-Gleichgewicht | ### Designter Mechanismus (Dominante Strategie)"""
    },
    "6. Systemdenken & Komplexität": {
        "Causal Loop Diagrams (System Dynamics)": """[METHODIK-FRAMEWORK: CAUSAL LOOP DIAGRAMS]
Analysiere die Dynamik des Systems über Rückkopplungsschleifen:

1. SYSTEM-ELEMENTE: Identifiziere die Schlüsselvariablen des Problems.
2. VERSTÄRKENDE SCHLEIFEN (Reinforcing Loops - R):
- Welche Teufelskreise oder Positiv-Spiralen verstärken sich selbst? (Wenn A steigt, steigt B, was A weiter erhöht).
3. AUSGLEICHENDE SCHLEIFEN (Balancing Loops - B):
- Welche Dämpfer oder natürlichen Grenzen begrenzen das Wachstum/die Leistung?
4. ZEITVERZÖGERUNGEN (Delays): Wo treten verzögerte Wirkungen auf, die zu Fehlanpassungen führen?

AUSGABE-FORMAT:
Strukturiere in: [Variablen] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Zeitverzögerungen]""",

        "Iceberg Model (Systems Thinking)": """[METHODIK-FRAMEWORK: DAS EISBERG-MODELL]
Dringe unter die Oberfläche des sichtbaren Problems vor:

1. EREIGNISSE (Sichtbare Spitze): Was ist gerade passiert? (Das unmittelbare Symptom).
2. MUSTER & TRENDS (Unter der Wasserlinie): Was passiert immer wieder? Welche Historie zeigt sich?
3. SYSTEMSTRUKTUREN: Wie sind die Prozesse, Werkzeuge und Regeln aufgebaut, die dieses Muster erzeugen?
4. MENTALE MODELLE (Fundament): Welche Grundhaltungen, Überzeugungen oder Design-Philosophien halten die Struktur aufrecht?

AUSGABE-FORMAT:
Analysiere von oben nach unten: [1. Ereignis] -> [2. Muster] -> [3. Struktur] -> [4. Mentales Modell]""",

        "Second-Order Thinking (Howard Marks)": """[METHODIK-FRAMEWORK: SECOND-ORDER THINKING]
Denke über die unmittelbaren Konsequenzen einer Entscheidung hinaus:

1. EFFEKTE 1. ORDNUNG (Unmittelbar & Offensichtlich):
- Was ist die direkte Folge der Handlung/des Codes? (Fast immer positiv gedacht).

2. EFFEKTE 2. ORDNUNG (Mittelbar & Nebenwirkungen):
- Was passiert in 3-6 Monaten als direkte Konsequenz der Effekte 1. Ordnung? Welche unbeabsichtigten Nebenwirkungen entstehen?

3. EFFEKTE 3. ORDNUNG (Langfristige System-Shifts):
- Wie verändert diese Entscheidung das Gesamtsystem, die Kosten oder das Nutzerverhalten langfristig?

AUSGABE-FORMAT:
Gliedere in: [1st Order: Direkt] | [2nd Order: Nebenwirkungen] | [3rd Order: Systemwirkung]""",

        "Wardley Mapping": """[METHODIK-FRAMEWORK: WARDLEY MAPPING]
Kartiere die Komponenten des Systems entlang der Wertschöpfungskette und ihrer Evolution:

1. NORTSTERN / USER NEED: Was braucht der Nutzer an oberster Stelle?
2. WERTSCHÖPFUNGSKETTE: Welches Modul baut auf welchem auf? (Sichtbar -> Unsichtbar).
3. EVOLUTIONSSTUFEN DER KOMPONENTEN:
   - Genesis (Unbekannt, Experimentell)
   - Custom-Built (Maßgeschneidert, Eigenbau)
   - Product/Rental (Standard-Produkt/SaaS)
   - Commodity/Utility (Infrastruktur, Standard-Strom)

STRATEGISCHER ZUG: Welche Eigenbauten sollten durch Commodities ersetzt werden, um Ressourcen freizusetzen?

AUSGABE-FORMAT:
### Wertschöpfungskette | ### Evolutions-Mapping | ### Strategischer Hebel"""
    },
    "7. Zukunftsforschung, Risiko & Resilienz": {
        "Antifragilitäts-Analyse (Nassim Taleb)": """[METHODIK-FRAMEWORK: TALEB ANTIFRAGILITÄT]
Klassifiziere und optimiere das System nach seiner Reaktion auf Stress, Fehler und Volatilität:

1. FRAGIL (Bricht bei Stress): Wo führen Fehler zu fatalen Kettenreaktionen oder Abstürzen?
2. ROBUST (Hält Stress stand): Wo bleibt das System unverändert stabil, lernt aber nicht dazu?
3. ANTIFRAGIL (Gewinnt durch Stress): Wie kann das System so gebaut werden, dass es aus Fehlern, Ausnahmen und Stress Dazulernt und BESSER wird?

REFACTORING: Wandle fragile Systemkomponenten in antifragile Schleifen um (z. B. automatisches Reinforcement-Learning aus Error-Logs).

AUSGABE-FORMAT:
### Fragile Schwachstellen | ### Robuste Kernzonen | ### Antifragile Optimierungen""",

        "FMEA (Failure Mode and Effects Analysis)": """[METHODIK-FRAMEWORK: FMEA RISIKO-QUANTIFIZIERUNG]
Bewerte Systemfehler quantitativ nach der Risikoprioritätszahl (RPN = A x B x E):

1. FEHLERMÖGLICHKEIT: Was kann an Komponente X schiefgehen?
2. AUFTRETENSWAHRSCHEINLICHKEIT (A: 1-10): Wie oft kommt der Fehler vor?
3. BEDEUTUNG / SCHWERE (B: 1-10): Wie gravierend ist der Schaden für den Nutzer?
4. ENTDECKUNGSSICHERHEIT (E: 1-10): Wie schwer ist der Fehler vor dem Deployment zu erkennen? (10 = unbemerkt).
5. RPN-SCORE (A x B x E): Werte über 100 erfordern zwingend eine Überarbeitung.

KORREKTUR-ACTION: Behebe vorrangig Fehler mit den höchsten RPN-Scores.

AUSGABE-FORMAT:
Tabellarische Liste: Component | Failure Mode | A | B | E | RPN | Massnahme""",

        "OODA-Loop (John Boyd)": """[METHODIK-FRAMEWORK: OODA-LOOP ECHTZEIT-STEUERUNG]
Durchlaufe den schnellen Orientierungs- und Entscheidungszirkel:

1. OBSERVE (Beobachten): Erfasse alle verfügbaren Systemzustände, Logs, API-Feedbacks und Inputs.
2. ORIENT (Orientieren): Filtere die Daten durch aktuelle Kontextfenster, KI-Rollen und Erfahrungen. Zerschlage falsche Wahrnehmungen.
3. DECIDE (Entscheiden): Wähle schnell die effektivste Handlungsoption aus (Vermeide Analysis Paralysis).
4. ACT (Handeln): Führe den Code/die Aktion sofort aus und speise das Ergebnis direkt zurück in Schritt 1.

AUSGABE-FORMAT:
[Observe] -> [Orient] -> [Decide] -> [Act]""",

        "Scenario Planning (Shell-Methode)": """[METHODIK-FRAMEWORK: SZENARIO-PLANUNG]
Entwickle 3 plausible, voneinander unabhängige Zukunftsszenarien für das Vorhaben:

1. SZENARIO A: "BEST CASE / GROWTH" (Optimale Bedingungen)
- Wie sieht die Lösung aus und wie skaliert sie unter idealen Voraussetzungen?

2. SZENARIO B: "STAGFLATION / ADVERSARIAL" (Ressourcenknappheit / Hohe Fehlerquote)
- Wie schlägt sich das System bei extrem hohen Kosten, Ausfällen oder Latenzen?

3. SZENARIO C: "BLACK SWAN / DISRUPTION" (Unerwarteter Systemwechsel)
- Was passiert, wenn sich die Grundannahmen schlagartig ändern?

STRATEGIE: Leite Maßnahmen ab, die in ALLEN 3 Szenarien funktionieren (No-Regret-Moves).

AUSGABE-FORMAT:
[Szenario A] | [Szenario B] | [Szenario C] | [No-Regret-Maßnahmen]"""
    }
}

import copy
DEFAULT_CATEGORIZED_FRAMEWORKS = copy.deepcopy(CATEGORIZED_FRAMEWORKS)

def get_flat_framework_map() -> dict:
    flat = {}
    for cat, frameworks in CATEGORIZED_FRAMEWORKS.items():
        for fw_name, fw_val in frameworks.items():
            if isinstance(fw_val, dict):
                flat[fw_name] = {
                    "summary": fw_val.get("summary", fw_name),
                    "system_instruction": fw_val.get("system_instruction", fw_val.get("summary", ""))
                }
            else:
                flat[fw_name] = {
                    "summary": fw_val,
                    "system_instruction": fw_val
                }
    return flat

UNIVERSAL_METHODOLOGY_HEADER = """[UNIVERSAL METHODOLOGY ENGINE HEADER]
Du bist ein kompromissloser Experten-Analyst im AgentOS. 
Deine Aufgabe ist es, die Problemstellung ausschließlich durch die Linse des zugewiesenen Frameworks zu zerlegen.

STRIKTE REGELN:
1. Keine Einleitungen, kein Höflichkeits-Fluff, kein "Gerne helfe ich dir dabei".
2. Denke Schritt für Schritt (Chain-of-Thought), bevor du antwortest.
3. Überspringe KEINE Phase des Frameworks. Jeder Abschnitt muss fundiert ausgearbeitet sein.
4. Sei konkret: Nenne Zahlen, Code-Schnipsel, Werkzeuge, spezifische Risiken und eindeutige Befehle statt vager Ratschläge.
5. Halte dich exakt an das vorgegebene AUSGABE-FORMAT.
========================================"""

def get_framework_info(name: str) -> dict:
    flat = get_flat_framework_map()
    if name in flat:
        return flat[name]
    return flat.get("Steffi Kieffer Boardroom", {
        "summary": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion.",
        "system_instruction": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion."
    })

def build_final_system_prompt(selected_framework_id: str, base_system_prompt: str = "") -> str:
    """
    Kompiliert dynamisch den finalen System-Prompt aus:
    1. UNIVERSAL_METHODOLOGY_HEADER
    2. Der aus der Datenbank/Registry geladenen Methodik-Instruktion
    3. Einem optionalen Agenten-Base-Prompt
    """
    fw_info = get_framework_info(selected_framework_id)
    fw_instruction = fw_info.get("system_instruction", "") if fw_info else ""
    
    parts = [UNIVERSAL_METHODOLOGY_HEADER.strip()]
    if base_system_prompt and base_system_prompt.strip():
        parts.append(base_system_prompt.strip())
    if fw_instruction and fw_instruction.strip():
        parts.append(f"[SELECTED METHODOLOGY: {selected_framework_id}]\n{fw_instruction.strip()}")
        
    return "\n\n".join(parts)

async def stream_boardroom_debate(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30,
    use_moa: bool = False,
    moa_reference_models: list = None,
    moa_aggregator: dict = None
):
    """
    Asynchroner Generator für Live-Streaming der 'AI Boardroom' Multi-Agenten Debatte:
    Streamt Events schrittweise (start, chairman_init, round_start, agent_response, consensus_reached, final_synthesis, done).
    """
    if not active_agents:
        yield {"type": "error", "content": "Keine aktiven Agenten für den Boardroom vorhanden."}
        return
    
    framework_info = get_framework_info(framework)
    framework_instruction = framework_info["system_instruction"]

    # Chairman ist das erste Element, alle weiteren Elemente sind die Experten-Slots
    chairman = active_agents[0]
    expert_agents = active_agents[1:] if len(active_agents) > 1 else [chairman]

    yield {
        "type": "start",
        "task": task,
        "framework": framework,
        "chairman": chairman,
        "max_rounds": max_rounds
    }
    
    # 1. CHAIRMAN INITIALIZATION
    chairman_init_prompt = (
        f"Du bist der Moderator / Chairman des AI Boardrooms.\n"
        f"Strategische Aufgabe: '{task}'\n"
        f"METHODIK-FRAMEWORK: {framework}\n"
        f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
        f"Aufgabe: Rahmen das Problem kurz ein, definiere Bewertungskriterien im Sinne des Frameworks '{framework}' "
        f"und weise den Experten-Agenten ({', '.join([a['name'] for a in expert_agents])}) "
        f"erste Fokusbereiche für die Debatte zu."
    )
    
    chairman_sys_prompt = build_final_system_prompt(framework, chairman.get("prompt", ""))

    res_init = await dispatch_to_external_agent(
        agent_id=chairman["id"],
        agent_name=chairman["name"],
        prompt=chairman_init_prompt,
        role=chairman.get("role", "Orchestrator"),
        system_prompt=chairman_sys_prompt,
        model=chairman.get("model", "deepseek/deepseek-chat"),
        timeout=timeout,
        provider=chairman.get("provider", ""),
        reasoning_level=chairman.get("reasoning_level", "medium")
    )
    
    init_text = res_init.get("content", f"Problemeinrahmung für '{task}' gestartet.")
    yield {
        "type": "chairman_init",
        "round": 0,
        "agent_id": chairman["id"],
        "agent_name": chairman["name"],
        "role": chairman.get("role", "Orchestrator"),
        "model": chairman.get("model") or "deepseek/deepseek-chat",
        "content": init_text
    }

    # 2. ROUND-BASED DEBATE
    running_transcript = f"--- MODERATOR INITIALISIERUNG ---\n{init_text}\n\n"
    
    for round_num in range(1, max_rounds + 1):
        yield {
            "type": "round_start",
            "round": round_num,
            "max_rounds": max_rounds
        }
        
        if round_num == 1 and len(expert_agents) > 1:
            async def _dispatch_agent(ag):
                prompt = (
                    f"--- AI BOARDROOM DEBATTE - RUNDE {round_num} VON {max_rounds} ---\n"
                    f"Ursprüngliche Aufgabe: {task}\n"
                    f"METHODIK-FRAMEWORK: {framework}\n"
                    f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
                    f"Bisheriger Diskussionsverlauf:\n{running_transcript}\n\n"
                    f"Instruktion: Reagiere auf die Initialisierung des Moderators. "
                    f"Behalte strikt deine Rolle ({ag.get('role', 'Expert')}) bei und wende das Framework '{framework}' an. "
                    f"Formuliere deine klare Fachperspektive."
                )
                sys_prompt = build_final_system_prompt(framework, ag.get("prompt", ""))
                res = await dispatch_to_external_agent(
                    agent_id=ag["id"],
                    agent_name=ag["name"],
                    prompt=prompt,
                    role=ag.get("role", "Expert"),
                    system_prompt=sys_prompt,
                    model=ag.get("model", "deepseek/deepseek-chat"),
                    timeout=timeout,
                    provider=ag.get("provider", ""),
                    reasoning_level=ag.get("reasoning_level", "medium")
                )
                return {
                    "type": "agent_response",
                    "round": round_num,
                    "agent_id": ag["id"],
                    "agent_name": ag["name"],
                    "role": ag.get("role", "Expert"),
                    "model": ag.get("model") or "deepseek/deepseek-chat",
                    "content": res.get("content", "Keine Antwort.")
                }

            tasks = [asyncio.create_task(_dispatch_agent(a)) for a in expert_agents]
            for coro in asyncio.as_completed(tasks):
                res_event = await coro
                running_transcript += f"[{res_event['agent_name']} ({res_event['role']}) - Runde {round_num}]:\n{res_event['content']}\n\n"
                # Replicate live into task_events for #boardroom and #all-stream in Operations
                try:
                    from backend.operations_api import _get_kanban_connection
                    _k_conn = _get_kanban_connection()
                    _k_cur = _k_conn.cursor()
                    _k_now = datetime.datetime.now().isoformat()
                    _k_payload = json.dumps({
                        "author": res_event["agent_id"],
                        "message": f"[BOARDROOM RUNDE {round_num}] {res_event['content']}",
                        "target": "boardroom",
                        "broadcast": True,
                        "framework": framework
                    }, ensure_ascii=False)
                    _k_cur.execute("""
                        INSERT INTO task_events (task_id, kind, payload, created_at)
                        VALUES (?, 'boardroom_turn', ?, ?)
                    """, (f"boardroom_{int(time.time())}", _k_payload, _k_now))
                    _k_conn.commit()
                    _k_conn.close()
                except Exception as _e_rep:
                    pass

                yield res_event
        else:
            for agent in expert_agents:
                agent_prompt = (
                    f"--- AI BOARDROOM DEBATTE - RUNDE {round_num} VON {max_rounds} ---\n"
                    f"Ursprüngliche Aufgabe: {task}\n"
                    f"METHODIK-FRAMEWORK: {framework}\n"
                    f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
                    f"Bisheriger Diskussionsverlauf:\n{running_transcript}\n\n"
                    f"Instruktion: Reagiere auf die Aussagen der anderen Agenten. "
                    f"Behalte strikt deine Rolle ({agent.get('role', 'Expert')}) bei und wende das Framework '{framework}' an. "
                    f"Hinterfrage, validiere oder erweitere die Argumente deiner Vorredner explizit."
                )
                
                agent_sys_prompt = build_final_system_prompt(framework, agent.get("prompt", ""))

                res = await dispatch_to_external_agent(
                    agent_id=agent["id"],
                    agent_name=agent["name"],
                    prompt=agent_prompt,
                    role=agent.get("role", "Expert"),
                    system_prompt=agent_sys_prompt,
                    model=agent.get("model", "deepseek/deepseek-chat"),
                    timeout=timeout,
                    provider=agent.get("provider", ""),
                    reasoning_level=agent.get("reasoning_level", "medium")
                )
                
                resp_content = res.get("content", "Keine Antwort.")
                ev_agent = {
                    "type": "agent_response",
                    "round": round_num,
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "role": agent.get("role", "Expert"),
                    "model": agent.get("model") or "deepseek/deepseek-chat",
                    "content": resp_content
                }
                running_transcript += f"[{agent['name']} ({agent.get('role', 'Expert')}) - Runde {round_num}]:\n{resp_content}\n\n"
                yield ev_agent
        
        # 3. CONSENSUS CHECK & WATCHDOG
        if round_num < max_rounds:
            consensus_prompt = (
                f"Du bist der Moderator ({chairman['name']}).\n"
                f"Bisheriger Diskussionsverlauf nach Runde {round_num}:\n{running_transcript}\n\n"
                f"Prüfe, ob bereits voller Konsens erzielt wurde. Antworte NUR mit 'KONSENS_ERREICHT' oder 'DEBATTE_FORTSETZEN'."
            )
            
            check_res = await dispatch_to_external_agent(
                agent_id=chairman["id"],
                agent_name=chairman["name"],
                prompt=consensus_prompt,
                role=chairman.get("role", "Orchestrator"),
                system_prompt="Prüfe strikt, ob Konsens erreicht wurde.",
                model=chairman.get("model") or "deepseek/deepseek-chat",
                timeout=15
            )
            
            check_text = check_res.get("content", "").upper()
            if "KONSENS_ERREICHT" in check_text or "CONSENSUS" in check_text:
                yield {
                    "type": "consensus_reached",
                    "round": round_num,
                    "content": f"Konsens in Runde {round_num} vorzeitig erzielt!"
                }
                break

    # 4. FINAL SYNTHESIS (STANDARD ODER MIXTURE OF AGENTS - MoA)
    synthesis_text = ""
    if use_moa:
        # Default Referenz-Modelle falls keine übergeben wurden
        ref_models = moa_reference_models or [
            {"model": "deepseek/deepseek-chat", "provider": "openrouter", "name": "DeepSeek V3 (MoA Ref)"},
            {"model": "anthropic/claude-3.5-sonnet", "provider": "openrouter", "name": "Claude 3.5 Sonnet (MoA Ref)"},
            {"model": "meta-llama/llama-3.3-70b-instruct", "provider": "openrouter", "name": "Llama 3.3 70B (MoA Ref)"}
        ]
        agg_model = moa_aggregator or {
            "model": chairman.get("model", "deepseek/deepseek-chat"),
            "provider": chairman.get("provider", "openrouter"),
            "name": f"{chairman['name']} (MoA Aggregator)"
        }

        yield {
            "type": "moa_start",
            "reference_models": ref_models,
            "aggregator": agg_model,
            "message": f"MoA aktiviert: Starte parallele Layer-1 Synthese über {len(ref_models)} Sprachmodelle..."
        }

        moa_prompt = (
            f"Du bist ein unabhängiges Referenz-Modell im Mixture-of-Agents (MoA) Verbund.\n"
            f"Debatten-Aufgabe: '{task}'\n"
            f"Framework: '{framework}'\n\n"
            f"Diskussionsprotokoll:\n{running_transcript}\n\n"
            f"Erstelle eine präzise, eigenständige Entscheidungsvorlage mit Konsenspunkten, offenen Risiken und Empfehlungen."
        )

        async def _run_moa_ref(m_item):
            m_id = m_item.get("model", "deepseek/deepseek-chat")
            m_prov = m_item.get("provider", "openrouter")
            m_name = m_item.get("name", m_id)
            try:
                res = await dispatch_to_external_agent(
                    agent_id=f"moa_ref_{m_name}",
                    agent_name=m_name,
                    prompt=moa_prompt,
                    role="MoA Reference Model",
                    system_prompt=f"Du bist {m_name}. Liefere eine objektive, strukturierte Entscheidungsvorlage.",
                    model=m_id,
                    provider=m_prov,
                    timeout=timeout
                )
                return {"model": m_id, "provider": m_prov, "name": m_name, "content": res.get("content", ""), "status": "ok"}
            except Exception as e:
                return {"model": m_id, "provider": m_prov, "name": m_name, "content": f"Fehler bei {m_name}: {e}", "status": "error"}

        moa_tasks = [asyncio.create_task(_run_moa_ref(m)) for m in ref_models]
        moa_results = await asyncio.gather(*moa_tasks)

        running_transcript += "\n--- MIXTURE OF AGENTS (MoA) LAYER-1 REFERENZEN ---\n"
        for r in moa_results:
            running_transcript += f"[{r['name']}]:\n{r['content']}\n\n"
            yield {
                "type": "moa_ref_done",
                "model": r["model"],
                "name": r["name"],
                "status": r["status"],
                "content": r["content"]
            }

        # Jetzt der Aggregator
        agg_prompt = (
            f"Du bist der MoA-Aggregator (Mixture of Agents) für den AI Boardroom.\n"
            f"Aufgabe: '{task}' | Framework: '{framework}'\n\n"
            f"Vorheriger Diskussionsverlauf:\n{running_transcript}\n\n"
            f"Die folgenden Referenzmodelle haben unabhängig voneinander Analysen geliefert:\n"
        )
        for idx, r in enumerate(moa_results):
            agg_prompt += f"=== MODELL {idx+1}: {r['name']} ({r['model']}) ===\n{r['content']}\n\n"
        
        agg_prompt += (
            f"Synthetisiere als Aggregator alle Perspektiven:\n"
            f"1. Extrahiere die stärksten Konsenspunkte aller Modelle\n"
            f"2. Hebe Kontroversen, blinde Flecken oder Risiken hervor\n"
            f"3. Formuliere die finale verbindliche Entscheidung & Aktionsplan im Markdown-Format:\n"
            f"### 1. Key Consensus Points (MoA-Konsens)\n"
            f"### 2. Evaluierte Risiken & Dissenting Opinions\n"
            f"### 3. Actionable Decision & Umsetzungsschritte"
        )

        yield {
            "type": "moa_aggregating",
            "aggregator": agg_model,
            "message": f"Aggregator {agg_model.get('name', 'Chair')} synthetisiert alle Layer-1 Ergebnisse..."
        }

        res_agg = await dispatch_to_external_agent(
            agent_id=chairman["id"],
            agent_name=agg_model.get("name", chairman["name"]),
            prompt=agg_prompt,
            role="MoA Aggregator",
            system_prompt=chairman_sys_prompt,
            model=agg_model.get("model", chairman.get("model", "deepseek/deepseek-chat")),
            provider=agg_model.get("provider", chairman.get("provider", "openrouter")),
            timeout=timeout
        )
        synthesis_text = res_agg.get("content", "MoA Aggregator konnte keine Synthese erstellen.")
    else:
        synthesis_prompt = (
            f"Du bist der Chairman ({chairman['name']}).\n"
            f"Die Debatte zu '{task}' unter Anwendung des Frameworks '{framework}' ist beendet.\n"
            f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
            f"Gesamter Diskussionsverlauf:\n{running_transcript}\n\n"
            f"Erstelle eine finale, strukturierte Synthese im Markdown-Format mit folgenden 3 Abschnitten:\n"
            f"### 1. Key Consensus Points (Haupt-Konsenspunkte)\n"
            f"### 2. Unresolved Risks / Counterarguments (Offene Risiken & Gegenargumente)\n"
            f"### 3. Final Actionable Decision (Finale Entscheidung & konkreter Aktionsplan)"
        )
    
    res_synth = await dispatch_to_external_agent(
        agent_id=chairman["id"],
        agent_name=chairman["name"],
        prompt=synthesis_prompt,
        role=chairman.get("role", "Orchestrator"),
        system_prompt=chairman_sys_prompt,
        model=chairman.get("model", "deepseek/deepseek-chat"),
        timeout=timeout,
        provider=chairman.get("provider", ""),
        reasoning_level=chairman.get("reasoning_level", "medium")
    )
    
    synthesis_text = res_synth.get("content", "Synthese konnte nicht erstellt werden.")
    
    yield {
        "type": "final_synthesis",
        "agent_id": chairman["id"],
        "agent_name": chairman["name"],
        "role": chairman.get("role", "Orchestrator"),
        "model": chairman.get("model") or "deepseek/deepseek-chat",
        "content": synthesis_text
    }

    yield {
        "type": "done",
        "transcript": running_transcript,
        "synthesis": synthesis_text
    }


async def run_boardroom_debate(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30,
    use_moa: bool = False,
    moa_reference_models: list = None,
    moa_aggregator: dict = None
) -> dict:
    events = []
    task_res = {
        "status": "success",
        "task": task,
        "framework": framework,
        "chairman": active_agents[0] if active_agents else {},
        "max_rounds": max_rounds,
        "events": [],
        "transcript": "",
        "synthesis": ""
    }
    
    async for ev in stream_boardroom_debate(task, max_rounds, chairman_id, active_agents, framework, timeout, use_moa=use_moa, moa_reference_models=moa_reference_models, moa_aggregator=moa_aggregator):
        ev_type = ev.get("type")
        if ev_type == "start":
            task_res["chairman"] = ev.get("chairman", task_res["chairman"])
        elif ev_type == "done":
            task_res["transcript"] = ev.get("transcript", "")
            task_res["synthesis"] = ev.get("synthesis", "")
        elif ev_type == "error":
            return {"status": "error", "content": ev.get("content", "")}
        elif ev_type == "round_start":
            continue
        else:
            events.append(ev)
            
    task_res["events"] = events
    return task_res

async def execute_with_self_correction(
    agent_id: str,
    agent_name: str,
    task_description: str,
    execution_fn,
    initial_args: dict,
    max_retries: int = 3,
    role: str = "Developer",
    model: str = "deepseek/deepseek-chat"
) -> dict:
    """
    Pillar 2 / Self-Correction & Reflection Loop:
    Führt Tool-Aufrufe oder Skripte aus. Bei Fehlern (Exit-Code != 0, Exception)
    wird der Fehlertext an den Agenten zurückgespeist, damit dieser die Parameter/den Code
    analysiert, korrigiert und bis zu 3-mal selbstständig neu versucht.
    """
    attempt = 1
    current_args = dict(initial_args)
    correction_history = []
    
    while attempt <= max_retries:
        try:
            if asyncio.iscoroutinefunction(execution_fn):
                res = await execution_fn(current_args)
            else:
                res = await asyncio.to_thread(execution_fn, current_args)
            
            is_error = False
            err_msg = ""
            if isinstance(res, dict):
                if res.get("status") in ("error", "failed") or (res.get("code") is not None and res.get("code") != 0):
                    is_error = True
                    err_msg = str(res.get("stderr") or res.get("message") or res.get("content") or "Unbekannter Fehler")
            
            if not is_error:
                return {
                    "status": "success",
                    "attempts": attempt,
                    "result": res,
                    "corrections": correction_history
                }
            
            if attempt == max_retries:
                return {
                    "status": "error",
                    "attempts": attempt,
                    "message": f"Selbstkorrektur nach {max_retries} Versuchen fehlgeschlagen: {err_msg}",
                    "corrections": correction_history,
                    "last_result": res
                }
                
            reflection_prompt = (
                f"[SELBSTKORREKTUR-REFLEXION - VERSUCH {attempt}/{max_retries}]\n"
                f"Aufgabe: {task_description}\n"
                f"Bisherige Parameter/Code:\n{json.dumps(current_args, ensure_ascii=False, indent=2)}\n\n"
                f"FEHLER-AUSGABE:\n{err_msg[:1200]}\n\n"
                f"Instruktion: Analysiere den Fehler präzise. Liefere als Antwort ein valides JSON-Objekt "
                f"mit den korrigierten Parametern/Feldern, um diesen Fehler zu beheben."
            )
            
            llm_res = await dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=reflection_prompt,
                role=role,
                system_prompt="Du bist ein Experte für Fehleranalyse und autonome Selbstkorrektur. Antworte ausschließlich mit JSON.",
                model=model
            )
            
            content = llm_res.get("content", "")
            try:
                clean_json = content
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                parsed = json.loads(clean_json)
                if isinstance(parsed, dict):
                    correction_history.append({"attempt": attempt, "error": err_msg, "correction": parsed})
                    current_args.update(parsed)
            except Exception:
                correction_history.append({"attempt": attempt, "error": err_msg, "raw_response": content[:300]})
                
        except Exception as exc:
            if attempt == max_retries:
                return {
                    "status": "error",
                    "attempts": attempt,
                    "message": f"Unerwarteter Ausführungsfehler: {str(exc)}",
                    "corrections": correction_history
                }
            correction_history.append({"attempt": attempt, "exception": str(exc)})
            
        attempt += 1

    return {"status": "error", "attempts": attempt, "corrections": correction_history}
