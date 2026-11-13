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
    slot_id = task_id or f"{agent_id}-{t_start}"
    has_throttle_slot = False
    try:
        from backend.concurrency_throttle import concurrency_throttle
        await concurrency_throttle.acquire_slot(agent_id, slot_id, priority=2)
        has_throttle_slot = True
    except Exception:
        has_throttle_slot = False

    try:
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
    finally:
        if has_throttle_slot:
            try:
                from backend.concurrency_throttle import concurrency_throttle
                await concurrency_throttle.release_slot(slot_id)
            except Exception:
                pass

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

    # Spekulatives Vorladen von Entitaeten (CRM, ERP, relevante Notizen)
    prefetch_addon = ""
    try:
        from backend.speculative_prefetcher import get_speculative_prefetcher
        prefetcher = get_speculative_prefetcher()
        p_res = prefetcher.prefetch_for_task(prompt)
        p_lines = []
        if "crm_contact" in p_res:
            c = p_res["crm_contact"]
            p_lines.append(f"- CRM-Kontakt: {c.get('first_name', '')} {c.get('last_name', '')} ({c.get('email', '')}) [Firma: {c.get('company', 'Unbekannt')}]")
        if "erp_doc" in p_res:
            d = p_res["erp_doc"]
            p_lines.append(f"- ERP-Dokument: {d.get('doc_number', '')} ({d.get('type', '')}) [Status: {d.get('status', '')}]")
        if p_lines:
            prefetch_addon = "\n\n### [SPEKULATIV VORGELADENE KONTEXT-DATEN]:\n" + "\n".join(p_lines)
    except Exception:
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

    full_system_prompt = f"Du bist {agent_name} (Rolle: {role}). {system_prompt}{memory_context_addon}{prefetch_addon}".strip()

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
        "CLEAR-Model": "[METHODIK-FRAMEWORK: CLEAR-MODELL]\nDu wendest auf jede Fragestellung strikt das CLEAR-Analysemodell an. Strukturiere deine Denkweise und deine Ausgabe ausnahmslos in folgenden 5 Phasen:\n\n1. CONCISE (Prägnanz):\n- Reduziere die Problemstellung auf maximal 2-3 Kernsätze. Eliminiere Ablenkungen und Nebenschauplätze.\n\n2. LOGICAL (Logische Kausalität):\n- Baue eine lückenlose Argumentationskette auf (Wenn X, dann Y, weil Z). Decke Fehlschlüsse oder unbewiesene Annahmen auf.\n\n3. EXPLICIT (Eindeutigkeit):\n- Vermeide vage Begriffe. Benenne konkrete Zahlen, Methoden, Werkzeuge, Verantwortlichkeiten und eindeutige Handlungsoptionen.\n\n4. ADAPTIVE (Anpassungsfähigkeit):\n- Teste die Lösung gegen veränderte Rahmenbedingungen und Edge Cases. Zeige mindestens eine funktionale Alternative auf.\n\n5. REFLECTIVE (Selbstkritik):\n- Unterziehe dein eigenes Ergebnis einem Stresstest: Wo liegen Schwachstellen, Risiken oder blinde Flecken?\n\nAUSGABE-FORMAT:\nAntworte zwingend mit den Abschnitten:\n[C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective",
        "CREATE-Framework": "[METHODIK-FRAMEWORK: CREATE-FRAMEWORK]\nDu analysierst und löst die Aufgabe entlang der 6 Stufen der verhaltensökonomischen CREATE-Action-Funktion:\n\n1. C - Cue (Auslöser): Welches Signal oder Ereignis stößt das Problem/Verhalten an?\n2. R - Reaction (Intuitive Reaktion): Welche unmittelbare, kognitive Reaktion erfolgt (System 1)?\n3. E - Evaluation (Bewertung): Welche Vor- und Nachteile werden abgewogen (System 2)?\n4. A - Ability (Fähigkeit/Hürden): Ist die Umsetzung einfach genug? Wo liegen Reibungsverluste/Komplexität?\n5. T - Timing (Dringlichkeit): Warum muss die Handlung JETZT erfolgen?\n6. E - Execute (Ausführung): Wie sieht die konkrete finale Umsetzungsschleife aus?\n\nAUSGABE-FORMAT:\nGliedere deine Lösung sauber in die Abschnitte [C], [R], [E], [A], [T] und [E].",
        "Design Sprint (GV / Jake Knapp)": "[METHODIK-FRAMEWORK: 5-TAGE DESIGN SPRINT]\nSimuliere und durchlaufe den Design-Sprint-Prozess in 5 klaren Schritten:\n\n1. MAP (Verstehen & Kartieren): Definiere das langfristige Ziel, zeichne die Map des Problems und wähle den Fokusbereich.\n2. SKETCH (Lösungen skizzieren): Generiere verschiedene, konkurrierende Lösungsansätze im Detail.\n3. DECIDE (Entscheiden): Bewerte die Ansätze kritisch und wähle die stärkste Hypothese aus.\n4. PROTOTYPE (Fokussierter Prototyp): Erstelle eine konkrete, detaillierte Spezifikation/Skizze des kleinstmöglichen Testobjekts.\n5. TEST (Validierung): Definiere 3-5 konkrete Testfragen und Metriken zur Überprüfung der Lösung.\n\nAUSGABE-FORMAT:\nNutze die Abschnitte: ### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test",
        "Double Diamond (Design Council)": "[METHODIK-FRAMEWORK: DOUBLE DIAMOND]\nLöse das Problem durch den Wechsel von divergentem (öffnendem) und konvergentem (schließendem) Denken:\n\nDIAMOND 1: DAS RICHTIGE PROBLEM FINDEN\n1. Discover (Entdecken - Divergent): Exploriere das Problemfeld breit. Welche versteckten Aspekte und Perspektiven gibt es?\n2. Define (Definieren - Konvergent): Verdichte die Erkenntnisse auf die eine, entscheidende Problemstellung (Problem-Definition).\n\nDIAMOND 2: DIE RICHTIGE LÖSUNG ENTWERFEN\n3. Develop (Entwickeln - Divergent): Generiere vielfältige Lösungsmöglichkeiten ohne unmittelbare Bewertung.\n4. Deliver (Liefern - Konvergent): Wähle die beste Lösung, verfeinere sie und mache sie sofort einsatzbereit.\n\nAUSGABE-FORMAT:\nNutze die Abschnitte: [1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]",
        "Lean Startup (Eric Ries)": "[METHODIK-FRAMEWORK: LEAN STARTUP (BUILD-MEASURE-LEARN)]\nWende den empirischen Feedbackzyklus zur schnellen Hypothesenprüfung an:\n\n1. HYPOTHESE (Glaubenssatz): Welche unbewiesene Grundannahme muss wahr sein, damit das Vorhaben funktioniert?\n2. BUILD (MVP): Entwirf das Minimum Viable Product mit der geringsten Komplexität, um die Hypothese zu testen.\n3. MEASURE (Messen): Definiere konkrete, nicht-manipulierbare Kennzahlen (Actionable Metrics statt Vanity Metrics).\n4. LEARN (Lernen & Pivot/Persevere): Analysiere das Ergebnis: Soll das Konzept beibehalten (Persevere) oder angepasst (Pivot) werden?\n\nAUSGABE-FORMAT:\nStrukturiere deine Antwort in: 1. Hypothese | 2. Build (MVP) | 3. Measure (Metriken) | 4. Learn (Pivot/Persevere)",
        "OKRs (Objectives and Key Results)": "[METHODIK-FRAMEWORK: OBJECTIVES AND KEY RESULTS]\nÜbersetze die Aufgabenstellung in ein operationalisierbares OKR-Set:\n\n1. OBJECTIVE (Qualitatives Ziel):\n- Formuliere 1-2 ambitionierte, inspirierende und einprägsame Ziele (Wo wollen wir hin?).\n\n2. KEY RESULTS (Quantitative Messergebnisse):\n- Definiere pro Objective 3 konkrete, messbare Key Results (Wie messen wir den Erfolg?).\n- Format: \"Steigerung/Reduzierung von X auf Y bis Z\".\n\n3. INITIATIVES (Konkrete Maßnahmen):\n- Liste die spezifischen Aufgaben und Projekte auf, die notwendig sind, um die Key Results zu erreichen.\n\nAUSGABE-FORMAT:\nVerwende die Struktur: ### Objective | ### Key Results (1-3) | ### Initiativen & Action Items",
        "STEEPLE / PESTEL": "[METHODIK-FRAMEWORK: STEEPLE / PESTEL ANALYSE]\nAnalysiere das externe Umfeld der Problemstellung systematisch nach folgenden 7 Makro-Faktoren:\n\n1. Social (Soziokulturell): Demografie, Verhalten, Werte.\n2. Technological (Technologisch): Innovationen, Automatisierung, Tech-Hürden.\n3. Economic (Ökonomisch): Kosten, Inflation, Marktstrukturen.\n4. Environmental (Ökologisch): Nachhaltigkeit, Ressourcen, Umweltauflagen.\n5. Political (Politisch): Regulierungen, Stabilität, Vorgaben.\n6. Legal (Rechtlich): DSGVO, Haftung, Gesetze.\n7. Ethical (Ethisch): Fairness, Transparenz, KI-Ethik.\n\nAUSGABE-FORMAT:\nFühre für jeden Buchstaben [S], [T], [E], [E], [P], [L], [E] eine kurze, prägnante Risiko- und Chancenbewertung durch.",
        "Steffi Kieffer Boardroom": "[METHODIK-FRAMEWORK: AI BOARDROOM DEBATE]\nFühre eine mehrperspektivische Boardroom-Debatte durch, in der unterschiedliche Spezialisten-Perspektiven aufeinandertreffen:\n\n1. CHARMING MODERATOR (Einleitung): Rahmenbedingung setzen und Problem präzise formulieren.\n2. SKEPTIKER / RISIKOANALYSATOR: Hinterfragt Annahmen, deckt Sicherheits- und Umsetzungsrisiken auf.\n3. STRATEGISCHER OPTIMIST / INNOVATOR: Fokus auf Chancen, Effizienzsteigerung und Zukunftsfähigkeit.\n4. PRAGMATISCHER IMPLEMENTIERER: Fokus auf technische Machbarkeit, Ressourcen und unmittelbaren Code/Schritte.\n5. CHAIRMAN SYNTHESIS (Fazit): Wiegt die Argumente gegeneinander ab und liefert eine klare, unmissverständliche Entscheidung.\n\nAUSGABE-FORMAT:\nZeige den Dialog der Rollen gefolgt von der hervorgehobenen [CHAIRMAN SYNTHESIS].",
        "Jobs-to-be-Done (JTBD / Clayton Christensen)": "[METHODIK-FRAMEWORK: JOBS-TO-BE-DONE (JTBD)]\nAnalysiere die Aufgabenstellung nicht über Produktfeatures oder Demografie, sondern über den konkreten Fortschritt (\"Job\"), den der Nutzer in einer bestimmten Situation erreichen will:\n\n1. KONTEXT & AUSLÖSER (Struggling Moment): In welcher konkreten Situation stößt der bisherige Ansatz an seine Grenzen?\n2. FUNKTIONALER, EMOTIONALER & SOZIALER JOB:\n   - Funktional: Welche messbare Kernaufgabe muss erledigt werden?\n   - Emotional/Sozial: Welche Unsicherheit, Reibung oder welches Risiko soll eliminiert werden?\n3. VIER KRÄFTE DES WECHSELS (Forces of Progress):\n   - Push (Schmerz des Status Quo) & Pull (Anziehung der neuen Lösung) vs. Anxiety (Angst vorm Neuen) & Habit (Trägheit/Gewohnheit).\n4. OUTCOME-DRIVEN LÖSUNG: Entwirf die Lösung so, dass der Job schneller, verlässlicher und mit minimaler Reibung erledigt wird.\n\nAUSGABE-FORMAT:\n[1. Struggling Moment] | [2. Job-Dimensionen] | [3. Kräfte-Bilanz (Push/Pull vs. Anxiety/Habit)] | [4. Zielgenaue Lösung]",
        "Blue Ocean Strategy (ERRC-Grid)": "[METHODIK-FRAMEWORK: BLUE OCEAN STRATEGY & ERRC-GRID]\nÜberwinde ruinösen Preis- und Feature-Wettbewerb (Red Ocean) und schaffe unbestrittenen neuen Marktraum (Blue Ocean) über Value Innovation:\n\n1. RED OCEAN IST-ANALYSE: Auf welchen überfüllten Faktoren konkurriert die Branche heute zu hohen Kosten?\n2. ERRC-VIER-AKTIONEN-FORMAT:\n   - ELIMINATE (Eliminieren): Welche branchenüblichen Faktoren stiften keinen echten Nutzen mehr und werden komplett gestrichen?\n   - REDUCE (Reduzieren): Welche Standards sind überdimensioniert und werden deutlich unter Branchenniveau gesenkt?\n   - RAISE (Steigern): Welche entscheidenden Werttreiber werden weit über den Branchenstandard gehoben?\n   - CREATE (Kreieren): Welche völlig neuen Nutzenfaktoren werden erstmals geschaffen?\n3. NEUE WERTKURVE: Zeige, wie gleichzeitig Kostensenkung UND Nutzensteigerung erreicht werden.\n\nAUSGABE-FORMAT:\n### Red-Ocean-Status | ### ERRC-Matrix (Eliminate / Reduce / Raise / Create) | ### Neue Wertkurve & Differenzierung",
    },
    "2. Ursachenanalyse, Logik & Problem-Solving": {
        "5-Why-Methode": "[METHODIK-FRAMEWORK: 5-WHY URSACHENANALYSE]\nDringe durch kaskadierendes Hinterfragen zur tatsächlichen Wurzel des Problems (Root Cause) vor:\n\n- Problem-Statement: [Symptom präzise beschreiben]\n- Warum 1: Warum tritt dieses Symptom auf? -> Antwort 1\n- Warum 2: Warum passiert Antwort 1? -> Antwort 2\n- Warum 3: Warum passiert Antwort 2? -> Antwort 3\n- Warum 4: Warum passiert Antwort 3? -> Antwort 4\n- Warum 5: Warum passiert Antwort 4? -> WURZELURSACHE (Root Cause)\n\nKORREKTURMAßNAHME:\nDefiniere eine dauerhafte Lösung, die exakt an der Wurzelursache ansetzt (nicht am Symptom!).\n\nAUSGABE-FORMAT:\nListe die 5 Why-Schritte untereinander auf und schließe mit: ### Wurzelursache & ### Gegenmaßnahme.",
        "Cynefin-Framework (Dave Snowden)": "[METHODIK-FRAMEWORK: CYNEFIN DOMÄNEN-ANALYSE]\nOrdnest die Problemstellung zuerst der richtigen System-Domäne zu und wendest das dazugehörige Handlungsmuster an:\n\n1. DOMÄNEN-DIAGNOSE: In welcher Domäne befindet sich das Problem?\n   - Offensichtlich (Simple): Ursache-Wirkung klar -> Erkennen - Kategorisieren - Reagieren.\n   - Kompliziert (Complicated): Expertenwissen nötig -> Erkennen - Analysieren - Reagieren.\n   - Komplex (Complex): Keine klare Ursache-Wirkung -> Probieren - Erkennen - Reagieren.\n   - Chaotisch (Chaotic): Mitten im Brand -> Handeln - Erkennen - Reagieren.\n\n2. HANDLUNGSSTRATEGIE: Leite die exakten Schritte basierend auf der diagnostizierten Domäne ab.\n\nAUSGABE-FORMAT:\n### Domänen-Zuordnung | ### Begründung | ### Handlungsstrategie",
        "First Principles Thinking": "[METHODIK-FRAMEWORK: FIRST PRINCIPLES THINKING]\nZerlege das Problem in seine fundamentalsten Wahrheitselemente und baue von Grund auf eine neue Lösung:\n\n1. DEKONSTRUKTION (Annahmen streichen):\n   - Welche Analogien, Gewohnheiten und Branchen-Mythen verdecken das Problem? Lösche alle \"Das haben wir schon immer so gemacht\"-Annahmen.\n\n2. FUNDAMENTALE WAHRHEITEN (Physik/Fakten):\n   - Was sind die unumstößlichen, mathematischen, technischen oder logischen Fakten des Problems?\n\n3. REKONSTRUKTION (Neuaufbau):\n   - Baue aus diesen Grundbausteinen eine völlig neue, optimierte Lösung auf, ohne bestehende Denkmuster zu kopieren.\n\nAUSGABE-FORMAT:\nStrukturiere in: [1. Bekannte Annahmen verwerfen] | [2. Fundamentale Fakten] | [3. Neuaufbau aus Grundprinzipien]",
        "Ishikawa-Diagramm (6M)": "[METHODIK-FRAMEWORK: ISHIKAWA (URSACHEN-WIRKUNGS-DIAGRAMM)]\nUntersuche die Fehlerursachen systematisch anhand der 6M-Kategorien:\n\n1. Mensch: Unwissenheit, Überlastung, Schnittstellenfehler.\n2. Maschine/Tooling: Hardware, Server, Bug in der KI/Software.\n3. Methode: Mangelhafte Prozesse, falsche Logik, fehlende Vorgaben.\n4. Material/Daten: Mangelhafte Datenqualität, fehlerhafte Prompts/Input.\n5. Milieu/Umfeld: Systemumgebung, Zeitdruck, Netzwerklatenzen.\n6. Messung: Falsche Metriken, fehlendes Monitoring, ungenaue Logs.\n\nHAUPTURSACHE & LÖSUNG:\nIdentifiziere die wahrscheinlichste Hauptursache über alle 6 Achsen hinweg.\n\nAUSGABE-FORMAT:\nGliedere die Analyse in die 6M-Blöcke und schließe mit: ### Hauptfehlerquelle.",
        "Porter's Five Forces": "[METHODIK-FRAMEWORK: PORTER'S 5 FORCES BRANCHENANALYSE]\nBewerte die Wettbewerbsintensität und Attraktivität der Problemstellung/des Marktes:\n\n1. Rivalität unter bestehenden Wettbewerbern (Hoch/Mittel/Gering)\n2. Bedrohung durch neue Anbieter (Eintrittsbarrieren)\n3. Verhandlungsmacht der Lieferanten (Tech-Provider, APIs, Datenquellen)\n4. Verhandlungsmacht der Abnehmer (Kunden, Nutzer)\n5. Bedrohung durch Ersatzprodukte (Substitutionsrisiko durch andere Tech)\n\nSTRATEGISCHE EMPFEHLUNG: Wie kann das System/Produkt eine uneinnehmbare Festung (Moat) aufbauen?\n\nAUSGABE-FORMAT:\nAnalysiere die 5 Kräfte einzeln und schließe mit: ### Strategische Positionierung & Moat.",
        "SWOT-Analyse": "[METHODIK-FRAMEWORK: STRATEGISCHE SWOT-ANALYSE]\nFühre eine strukturierte Matrix-Analyse der internen und externen Faktoren durch:\n\nINTERNE FAKTOREN:\n- Strengths (Stärken): Was sind die Alleinstellungsmerkmale und Kernkompetenzen?\n- Weaknesses (Schwachstellen): Wo liegen Engpässe, Wissenslücken oder Ineffizienzen?\n\nEXTERNE FAKTOREN:\n- Opportunities (Chancen): Welche Markttrends, Automatisierungen oder Lücken lassen sich nutzen?\n- Threats (Risiken): Welche externen Gefahren (Regulierung, Konkurrenz, Tech-Shifts) drohen?\n\nSTRATEGISCHE KRUZUNG (TOWS):\nLeite mindestens 2 konkrete SO-Strategien (Stärken nutzen um Chancen zu ergreifen) und ST-Strategien (Stärken nutzen um Risiken abzuwehren) ab.\n\nAUSGABE-FORMAT:\nVerwende die Abschnitte: [Stärken] | [Schwächen] | [Chancen] | [Risiken] | [TOWS-Strategieableitung]",
        "MECE & Minto-Pyramide (Barbara Minto)": "[METHODIK-FRAMEWORK: MECE & MINTO-PYRAMIDEN-PRINZIP]\nStrukturiere Problemanalyse und Entscheidungskommunikation nach höchster Management-Beratungslogik (McKinsey / Barbara Minto):\n\n1. GOVERNING THOUGHT (Answer First): Beginne sofort mit der präzisen Kernaussage / Handlungsempfehlung in 1–2 Sätzen.\n2. MECE-ZERLEGUNG (Mutually Exclusive, Collectively Exhaustive):\n   - Zerlege das Problem in überschneidungsfreie (keine Redundanz) und erschöpfende (keine Lücken) Hauptstränge.\n3. SCQA-RAHMEN (Situation – Complication – Question – Answer): Verankere die Logik im geschäftlichen Engpass.\n4. BEWEISKETTE & DATENBELEGE: Untermauere jeden Hauptstrang mit verifizierbaren Zahlen, Fakten und Kausalbelegen.\n\nAUSGABE-FORMAT:\n### Executive Answer First | ### SCQA-Kontext | ### MECE-Analysebaum (Strang 1–3) | ### Zahlen- & Maßnahmenfazit",
        "Kepner-Tregoe Problem Analysis (KT)": "[METHODIK-FRAMEWORK: KEPNER-TREGOE PROBLEMANALYSE (IST / IST-NICHT)]\nIsoliere komplexe technische oder operative Störungsursachen durch scharfe Kontrastierung von IST und IST-NICHT:\n\n1. PROBLEMDEFINITION: Präzise Abweichung zwischen Soll-Standard und tatsächlicher Ist-Leistung.\n2. VIER-ACHSEN-SPEZIFIKATION (IST vs. IST-NICHT):\n   - WAS ist betroffen vs. WAS könnte betroffen sein, ist es aber NICHT?\n   - WO tritt es auf vs. WO tritt es NICHT auf?\n   - WANN trat es erstmals/wiederkehrend auf vs. WANN NICHT?\n   - WELCHES AUSMAß / welcher Trend zeigt sich?\n3. UNTERSCHIEDE & VERÄNDERUNGEN: Was unterscheidet das IST vom IST-NICHT und welche Änderung ging voraus?\n4. HYPOTHESENTEST: Prüfe mögliche Ursachen streng gegen alle IST- und IST-NICHT-Fakten bis zur einzig widerspruchsfreien Ursache.\n\nAUSGABE-FORMAT:\n[1. Abweichungs-Statement] | [2. IST / IST-NICHT Matrix] | [3. Kritische Änderungen] | [4. Verifizierte Ursache & Fix]",
        "Fault Tree Analysis (FTA / Fehlerbaumanalyse)": "[METHODIK-FRAMEWORK: FAULT TREE ANALYSIS (FTA / IEC 61025)]\nUntersuche kritische Systemausfälle deduktiv Top-Down über boolesche Logikgatter (UND / ODER):\n\n1. TOP-EVENT: Definiere das unerwünschte kritische Ausfallereignis an der Spitze des Fehlerbaums.\n2. LOGISCHE GATTER-ZERLEGUNG:\n   - ODER-Gatter (Single Point of Failure): Bereits EIN Teilfehler löst den Gesamtausfall aus.\n   - UND-Gatter (Redundanzbarriere): Mehrere unabhängige Fehler müssen gleichzeitig eintreten.\n3. MINIMAL CUT SETS (Minimale Schnittmengen): Identifiziere die kürzesten Fehlerpfade, die direkt zum Top-Event führen.\n4. ARCHITEKTUR-HÄRTUNG: Ersetze kritische ODER-Pfade gezielt durch unabhängige UND-Barrieren (Redundanz, Failover, Validierung).\n\nAUSGABE-FORMAT:\n### Top-Event | ### Fehlerbaum (UND/ODER-Pfade) | ### Single Points of Failure (Minimal Cut Sets) | ### Redundanz-Maßnahmen",
    },
    "3. Operations, Lean & Qualität": {
        "DMAIC (Six Sigma)": "[METHODIK-FRAMEWORK: DMAIC (SIX SIGMA PROZESSOPTIMIERUNG)]\nSichere die Qualität und eliminiere Prozessabweichungen strikt in 5 Phasen:\n\n1. DEFINE (Definieren): Was ist das Problem? Wer ist der Kunde? Was ist der Qualitätsanspruch (CTQ)?\n2. MEASURE (Messen): Wie sieht der aktuelle Ist-Zustand aus? Welche Daten/Metriken liegen vor?\n3. ANALYZE (Analysieren): Was sind die Kernursachen für Streuung und Fehler im Prozess?\n4. IMPROVE (Verbessern): Welche Maßnahmen beseitigen die Fehlerursachen vollständig?\n5. CONTROL (Steuern): Wie wird der neue Standard dauerhaft überwacht (KPIs, Alerts)?\n\nAUSGABE-FORMAT:\nStrukturiere deine Antwort in die 5 Abschnitte: [Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control].",
        "PDCA-Zyklus (Demingkreis)": "[METHODIK-FRAMEWORK: PDCA CONTINUOUS IMPROVEMENT]\nDurchlaufe den kontinuierlichen Verbesserungsprozess:\n\n1. PLAN (Planen): Analysiere die Ist-Situation, definiere das Ziel und erstelle einen konkreten Umsetzungsplan.\n2. DO (Umsetzen): Führe den Plan testweise oder im kleinen Rahmen aus (Prototyping/Pilotierung).\n3. CHECK (Überprüfen): Vergleiche die Ergebnisse der Umsetzung direkt mit den ursprünglichen Zielen. Wo gab es Abweichungen?\n4. ACT (Agieren): Standardisiere die erfolgreiche Lösung oder passe den Plan an und starte den Zyklus neu.\n\nAUSGABE-FORMAT:\nVerwende die Abschnitte: ### Plan | ### Do | ### Check | ### Act",
        "Theory of Constraints (TOC)": "[METHODIK-FRAMEWORK: THEORY OF CONSTRAINTS (ENGPASS-THEORIE)]\nMaximiere den Durchsatz des gesamten Systems durch Fokussierung auf den schwächsten Punkt (Bottleneck):\n\n1. IDENTIFIZIEREN: Welches ist der eine, primäre Engpass, der den Gesamtdurchsatz limitiert?\n2. AUSNUTZEN: Wie kann dieser Engpass ohne große Investitionen maximal effizient ausgelastet werden?\n3. UNTERORDNEN: Richte alle anderen Prozesse und Schritte im System strikt nach dem Takt des Engpasses aus.\n4. BESEITIGEN: Investiere Ressourcen, um die Kapazität des Engpasses drastisch zu erweitern.\n5. NIEMALS AUFHÖREN: Sobald der Engpass gehoben ist, suche sofort den NÄCHSTEN Engpass (Vermeidung von Trägheit).\n\nAUSGABE-FORMAT:\nGliedere in: [1. Primärer Engpass] | [2. Ausnutzung] | [3. Unterordnung] | [4. Behebung]",
        "Value Stream Mapping (VSM / Wertstromanalyse)": "[METHODIK-FRAMEWORK: VALUE STREAM MAPPING (WERTSTROMANALYSE)]\nDurchleuchte den End-to-End-Fluss von Materialien, Daten oder Aufgaben vom Auslöser bis zum Kundenergebnis und eliminiere Verschwendung (7 Muda):\n\n1. IST-WERTSTROM: Kartiere alle Prozessschritte inkl. Bearbeitungszeit (Value-Add Time), Liege-/Wartezeit (Lead Time) und Fehlerrate (% Complete & Accurate).\n2. PROCESS CYCLE EFFICIENCY (PCE): Berechne das Verhältnis aus echter Wertschöpfungszeit zur Gesamtdurchlaufzeit.\n3. VERSCHWENDUNGS-DIAGNOSE (TIMWOODS): Decke Wartezeiten, Überproduktion, Medienbrüche, Nacharbeit und unnötige Übergaben auf.\n4. SOLL-WERTSTROM (Future State): Entwirf den verschlankten Zielprozess mit Pull-Steuerung, Automatisierung und messbarer Durchlaufzeitverkürzung.\n\nAUSGABE-FORMAT:\n[1. Ist-Wertstrom & Durchlaufzeit] | [2. Identifizierte Verschwendung (Muda)] | [3. Soll-Wertstrom] | [4. Effizienzgewinn]",
        "A3 Problem-Solving (Toyota Production System)": "[METHODIK-FRAMEWORK: TOYOTA A3 PROBLEM-SOLVING REPORT]\nVerdichte Problemlösung, Ursachenanalyse und Umsetzungssteuerung auf ein diszipliniertes Toyota-A3-Entscheidungsblatt:\n\n1. HINTERGRUND & BUSINESS-RELEVANZ: Warum ist dieses Thema jetzt geschäftskritisch?\n2. IST-ZUSTAND (Gemba-Fakten): Quantifizierte Ist-Kennzahlen ohne Vermutungen.\n3. ZIELZUSTAND (Smart Target): Messbarer Soll-Wert bis zu einem klaren Stichtag.\n4. WURZELURSACHEN-ANALYSE: Kausaler Nachweis der Kernursache hinter der Lücke.\n5. GEGENMAßNAHMEN & UMSETZUNGSPLAN: Konkrete Maßnahmen mit Verantwortlichen, Terminen und erwartetem Effekt.\n6. ERFOLGSKONTROLLE & STANDARDISIERUNG: Prüfmetrik und Verankerung im Standardbetrieb (SOP).\n\nAUSGABE-FORMAT:\n### 1. Hintergrund | ### 2. Ist-Daten | ### 3. Zielwert | ### 4. Wurzelursache | ### 5. Maßnahmenplan | ### 6. Erfolgsprüfung & SOP",
        "SIPOC & RACI Prozess-Governance": "[METHODIK-FRAMEWORK: SIPOC & RACI PROZESS-ARCHITEKTUR]\nSchaffe lückenlose Schnittstellen- und Verantwortungsklarheit für komplexe Betriebs- und Projektprozesse:\n\n1. SIPOC-ABGRENZUNG:\n   - Suppliers (Zulieferer/Quellen) -> Inputs (Eingangsdaten/-güter mit Qualitätskriterien) -> Process (5–7 Kernschritte) -> Outputs (Artefakte) -> Customers (Abnehmer & SLA-Anforderungen).\n2. RACI-VERANTWORTUNGSMATRIX:\n   - Responsible (Durchführungsverantwortlich), Accountable (Genau EINE Person mit Endverantwortung/Freigabe!), Consulted (Fachexpertise vorab), Informed (Information über Ergebnis).\n3. SCHNITTSTELLEN-GUARDRAILS: Eliminiere geteilte Accountabilities und unklare Übergabepunkte.\n\nAUSGABE-FORMAT:\n### SIPOC-Übersicht | ### RACI-Matrix (Tabellarisch) | ### Übergabe- & SLA-Regeln",
    },
    "4. Strategie, Priorisierung & Change": {
        "Eisenhower-Matrix": "[METHODIK-FRAMEWORK: EISENHOWER PRIORISIERUNGS-MATRIX]\nKategorisiere alle anstehenden Teilaufgaben strikt nach Wichtigkeit und Dringlichkeit:\n\n1. DO FIRST (Wichtig & Dringend): Sofort selbst erledigen. Exakte Ausführungsschritte festlegen.\n2. SCHEDULE (Wichtig & Nicht Dringend): Terminieren und strategisch durchdenken (Hauptfokus für Langzeiterfolg).\n3. DELEGATE (Nicht Wichtig & Dringend): An spezialisierte Sub-Agenten oder automatisierte Skripte auslagern.\n4. ELIMINATE (Nicht Wichtig & Nicht Dringend): Komplett streichen und als Ablenkung identifizieren.\n\nAUSGABE-FORMAT:\nPräsentiere die Aufgaben aufgeteilt in die 4 Quadranten: [Quadrant I: Do] | [Quadrant II: Schedule] | [Quadrant III: Delegate] | [Quadrant IV: Eliminate]",
        "Kano-Modell": "[METHODIK-FRAMEWORK: KANO MERKMAL-ANALYSE]\nKlassifiziere die Systemfunktionen/Features nach ihrer Auswirkung auf die Nutzerzufriedenheit:\n\n1. BASIS-MERKMALE (Must-Haves): Selbstverständliche Funktionen. Fehlen sie, herrscht große Unzufriedenheit.\n2. LEISTUNGS-MERKMALE (Linear): Je mehr/schneller vorhanden, desto höher die Zufriedenheit (z.B. Geschwindigkeit, Token-Preis).\n3. BEGEISTERUNGS-MERKMALE (Delighters): Unerwartete Features, die einen Aha-Effekt auslösen und echte Alleinstellung schaffen.\n4. UNERWÜNSCHTE/INERHEBLICHE MERKMALE: Features, die keinen Mehrwert stiften oder den Nutzer verwirren.\n\nAUSGABE-FORMAT:\nKategorisiere die Lösungselemente in: [Must-Haves] | [Performance-Features] | [Begeisterungs-Features]",
        "Kotter 8-Stufen-Modell": "[METHODIK-FRAMEWORK: KOTTER CHANGE MANAGEMENT]\nStrukturiere die Transformation / Systemumstellung entlang der 8 Stufen des Change Managements:\n\n1. Dringlichkeit erzeugen (Urgency)\n2. Führungskoalition aufbauen (Guiding Coalition)\n3. Vision und Strategie entwickeln (Vision)\n4. Die Vision kommunizieren (Communication)\n5. Hindernisse beseitigen (Empowerment)\n6. Schnelle Erfolge erzielen (Short-Term Wins)\n7. Erfolge konsolidieren und weitere Veränderungen anstoßen (Consolidation)\n8. Neue Ansätze in der Kultur verankern (Institutionalization)\n\nAUSGABE-FORMAT:\nLiefere für jede der 8 Stufen eine konkrete Handlungsanweisung für das System/Team.",
        "McKinsey 7S": "[METHODIK-FRAMEWORK: MCKINSEY 7S ORGANISATIONSANALYSE]\nAnalysiere die ganzheitliche Abstimmung des Systems über 7 Dimensionen:\n\nHARD S (Harte Faktoren):\n1. Strategy (Strategie): Ausrichtung und Wettbewerbsvorteil.\n2. Structure (Struktur): Systemarchitektur und Modulaufbau.\n3. Systems (Systeme): Prozesse, Pipelines und Workflows.\n\nSOFT S (Weiche Faktoren):\n4. Shared Values (Unternehmenskultur/Leitbild): Grundwerte der Lösung.\n5. Style (Führungsstil/Modell-Verhalten): Wie agiert das System?\n6. Staff (Personal/Agenten-Ressourcen): Fähigkeiten der eingesetzten LLMs.\n7. Skills (Fähigkeiten/Tools): Verfügbare APIs und operationaler Funktionsumfang.\n\nAUSGABE-FORMAT:\nGliedere in [Hard S] und [Soft S] und zeige Diskrepanzen zwischen den Dimensionen auf.",
        "NABC-Methode": "[METHODIK-FRAMEWORK: NABC PITCH & VALUE PROPOSITION]\nFormuliere die Lösung als prägnanten, überzeugenden Wertantrag (Pitch):\n\n1. NEED (Bedürfnis): Welches konkrete, schmerzhafte Problem des Nutzers/Systems wird adressiert?\n2. APPROACH (Ansatz): Wie sieht die spezifische, innovative Lösung aus?\n3. BENEFIT (Nutzen): Welchen quantifizierbaren Mehrwert/Ersparnis bringt der Ansatz?\n4. COMPETITION (Wettbewerb/Alternativen): Warum ist dieser Ansatz besser als bestehende Alternativen?\n\nAUSGABE-FORMAT:\nGliedere die Antwort präzise in: [Need] | [Approach] | [Benefit] | [Competition].",
        "RICE-Priorisierung": "[METHODIK-FRAMEWORK: RICE PRIORISIERUNGS-SCORE]\nBewerte und ranke Backlog-Items, Features oder Handlungsoptionen quantitativ nach der RICE-Formel:\nRICE Score = (Reach x Impact x Confidence) / Effort\n\n1. REACH (Reichweite): Wie viele Nutzer/Prozesse/Kunden sind pro Quartal betroffen? (Konkrete absolute Zahl).\n2. IMPACT (Auswirkung): Welchen Effekt hat das Item auf den Nutzer/das Ziel?\n   - 3 = Massiv, 2 = Hoch, 1 = Mittel, 0.5 = Gering, 0.25 = Minimal.\n3. CONFIDENCE (Zuversicht): Wie verlässlich sind unsere Daten/Annahmen?\n   - 100% = Hohe Evidenz / Datenbasis, 80% = Mittlere Datenlage, 50% = Schätzung / Bauchgefühl.\n4. EFFORT (Aufwand): Wie viele Personenmonate oder Entwicklungszeitfenster werden benötigt? (1 = 1 Monat / 1 Sprint).\n\nSCORE-BERECHNUNG:\nBerechne für jede Option den numerischen RICE-Score und erstelle eine absteigende Prioritätenliste mit klarer Umsetzungsbegründung.\n\nAUSGABE-FORMAT:\nTabellarische Matrix: Option | Reach | Impact | Confidence | Effort | RICE Score | Empfehlung",
        "Make-or-Buy / TCO-Scoring": "[METHODIK-FRAMEWORK: MAKE-OR-BUY & TCO-ANALYSE]\nFühre eine strukturierte Bewertung für Build vs. Buy vs. Partner durch, insbesondere für KI-, Software- und Infrastruktur-Entscheidungen:\n\n1. KERNKOMPETENZ & DIFFERENZIERUNG:\n- Gehört das Modul zur Kern-IP und strategischen Differenzierung (Build) oder ist es Standard-Commodity (Buy)?\n\n2. TOTAL COST OF OWNERSHIP (TCO) ÜBER 36 MONATE:\n- Build: Initiale Entwicklungskosten + laufende Wartung, Security-Patches, Hosting/Hardware, Opportunitätskosten des Dev-Teams.\n- Buy: SaaS-/API-Lizenzkosten, Vendor-Lock-in-Risiko, Integrationsaufwand, Token-Preiserhöhungsrisiko.\n- Partner: Integrations- und Betreuungskosten, Abhängigkeit von Drittdienstleistern.\n\n3. ZEITHORIZONT & TIME-TO-MARKET:\n- Wie viele Wochen/Monate Vorsprung verschafft die Buy-Option gegenüber einer Eigenentwicklung?\n\n4. DATENSCHUTZ, SOUVERÄNITÄT & RUNTIME-KONTROLLE:\n- Verbleiben sensible Kundendaten auf eigener Hardware (On-Prem / Selbst-Hosting) oder fließen Daten an externe US-Cloud-Hyperscaler?\n\nDECISION MATRIX & VERDIKT:\nFälle ein unmissverständliches Verdikt: Build, Buy oder Partner mit Meilensteinplan für die nächsten 90 Tage.\n\nAUSGABE-FORMAT:\n### Differenzierung & IP | ### TCO-3-Jahres-Vergleich | ### Risiko & Souveränität | ### Klares Verdikt & Roadmap",
        "Ansoff-Matrix & Wachstumsvektoren": "[METHODIK-FRAMEWORK: ANSOFF WACHSTUMS- & RISIKOMATRIX]\nBewerte strategische Wachstumsoptionen systematisch entlang von Produkt- und Marktdimension inklusive Risikoprofil:\n\n1. MARKTDURCHDRINGUNG (Bestehendes Produkt / Bestehender Markt — geringstes Risiko): Marktanteilsgewinn, Frequenz, Retention, Preispunkt.\n2. MARKTENTWICKLUNG (Bestehendes Produkt / Neuer Markt): Geografische Expansion, neue Kundensegmente oder Vertriebskanäle.\n3. PRODUKTENTWICKLUNG (Neues Produkt / Bestehender Markt): Upsell-Module, nächste Produktgeneration für bestehende Kundenbasis.\n4. DIVERSIFIKATION (Neues Produkt / Neuer Markt — höchstes Risiko): Horizontale, vertikale oder laterale Expansion.\n5. KAPITALALLOKATION: Empfiehl die optimale Sequenzierung nach Kapitalrendite und Umsetzungsrisiko.\n\nAUSGABE-FORMAT:\n[1. Marktdurchdringung] | [2. Marktentwicklung] | [3. Produktentwicklung] | [4. Diversifikation] | [Priorisierte Wachstumssequenz]",
        "BCG Growth-Share Portfolio-Matrix": "[METHODIK-FRAMEWORK: BCG PORTFOLIO- & KAPITALALLOKATIONS-MATRIX]\nSteuere Produktlinien, Projekte oder Geschäftseinheiten nach Marktwachstum, relativem Marktanteil und Cashflow-Beitrag:\n\n1. CASH COWS (Hoher Anteil / Reifer Markt): Cashflow-Generatoren — Effizienz sichern, Überschüsse abschöpfen, Überinvestition vermeiden.\n2. STARS (Hoher Anteil / Hohes Wachstum): Zukunftsträger — gezielt skalieren, um Marktführerschaft zu verteidigen.\n3. QUESTION MARKS (Niedriger Anteil / Hohes Wachstum): Selektive Wette (Double-Down bis zum Star) oder konsequenter Ausstieg.\n4. POOR DOGS (Niedriger Anteil / Niedriges Wachstum): Gebundenes Kapital und Management-Aufmerksamkeit freisetzen (Restrukturieren / Abstoßen).\n\nAUSGABE-FORMAT:\n### Portfolio-Einordnung (Cows / Stars / Question Marks / Dogs) | ### Cashflow-Umverteilung | ### Konkrete Stop/Invest-Entscheidung",
        "VRIO-Framework (Barney / Competitive Moat)": "[METHODIK-FRAMEWORK: VRIO WETTBEWERBSVORTEILS-PRÜFUNG]\nPrüfe Ressourcen, Technologie, Daten und Fähigkeiten schonungslos auf echte, dauerhafte Verteidigbarkeit (Moat):\n\n1. VALUABLE (Wertstiftend): Erhöht die Ressource nachweislich Zahlungsbereitschaft oder senkt sie strukturell die Stückkosten?\n2. RARE (Selten): Besitzen nur wenige Wettbewerber Zugang zu dieser Fähigkeit oder Datenbasis?\n3. INIMITABLE (Schwer imitierbar): Ist das Nachbauen durch Netzwerkeffekte, Wechselkosten, Patente, Regulierung oder Historie teuer/langwierig?\n4. ORGANIZED (Organisatorisch verankert): Ist das Unternehmen operativ aufgestellt, diesen Wert voll abzuschöpfen?\n\nKLASSIFIZIERUNG: Wettbewerbsnachteil -> Parität -> Temporärer Vorteil -> Nachhaltiger Burggraben (Sustained Moat).\n\nAUSGABE-FORMAT:\nTabellarisches VRIO-Audit je Kernressource + ### Moat-Ausbaustrategie",
    },
    "5. Kognitive Entzerrung & Kritisches Denken": {
        "Ladder of Inference (Chris Argyris)": "[METHODIK-FRAMEWORK: LADDER OF INFERENCE]\nLege deine kognitive Schlussfolgerungskette von den Rohdaten bis zur Handlung transparent offen, um Fehlschlüsse zu vermeiden:\n\n1. ROHDATEN: Welche beobachtbaren Fakten/Codezeilen wurden ausgewählt?\n2. GEFILTERTE DATEN: Welche Daten wurden ignoriert oder hervorgehoben?\n3. BEDEUTUNG (Sinngebung): Welche Bedeutung wird den Daten zugeschrieben?\n4. ANNAHMEN: Welche unbewiesenen Vorannahmen fließen ein?\n5. SCHLUSSFOLGERUNG: Welche logische Konsequenz wird gezogen?\n6. HANDLUNG: Welche konkrete Aktion folgt daraus?\n\nAUSGABE-FORMAT:\nZeige die Leiter von unten nach oben: [Sprosse 1: Daten] -> [Sprosse 2: Selektion] -> [Sprosse 3: Annahmen] -> [Sprosse 4: Aktion]",
        "Pre-Mortem Analyse (Gary Klein)": "[METHODIK-FRAMEWORK: PRE-MORTEM ANALYSE]\nSetze voraus, dass das geplante Projekt/der Code in 12 Monaten krisenhaft und vollständig gescheitert ist. Nimm diesen Misserfolg als mathematische Tatsache hin und arbeite rückwärts:\n\n1. GESCHICHTE DES SCHEITERNS:\n- Beschreibe das genaue Szenario des Totalschadens. Was ist schiefgegangen?\n\n2. URSACHEN-BRAINSTORMING:\n- Liste alle verdeckten Risiken, schlechten Annahmen, Zeitfresser und technischen Schwachstellen auf, die zu diesem Scheitern geführt haben.\n\n3. PRE-EMPTIVE MAßNAHMEN:\n- Leite sofortige, präventive Korrekturmaßnahmen ab, um jeden einzelnen identifizierten Scheiter-Grund HEUTE noch zu verhindern.\n\nAUSGABE-FORMAT:\nStrukturiere in: [1. Das Scheiter-Szenario] | [2. Identifizierte Todesursachen] | [3. Präventive Schutzmaßnahmen]",
        "Red Teaming / Adversarial Analysis": "[METHODIK-FRAMEWORK: RED TEAMING / ADVERSARIAL ATTACK]\nNimm die Rolle eines aggressiven, externen Angreifers / Gegners ein und zerlege das vorgelegte Konzept:\n\n1. ATTACK VECTORS (Angriffsflächen):\n- Wo liegen Schwachstellen in der Logik, Sicherheit, Performance oder Usability?\n\n2. EXPLOITATION (Ausnutzung):\n- Wie könnte ein Gegner, Edge Case oder Systemfehler diese Lücke maximal ausnutzen?\n\n3. DEFENSIVE HARDENING (Härtung):\n- Wie muss das Konzept/der Code sofort umgebaut werden, um diesen Angriff vollkommen unmöglich zu machen?\n\nAUSGABE-FORMAT:\n### Angriffsvektoren | ### Ausnutzungs-Szenario | ### Härtungs-Maßnahmen (Blue Team)",
        "Six Thinking Hats (Edward de Bono)": "[METHODIK-FRAMEWORK: SIX THINKING HATS]\nAnalysiere die Aufgabenstellung konsequent aus 6 klar getrennten Denkperspektiven:\n\n1. WEIßER HUT (Fakten): Welche reinen Daten, Fakten und Informationen liegen vor? Was fehlt?\n2. ROTER HUT (Emotionen): Welche intuitiven Bedenken, Ängste oder Bauchgefühle gibt es?\n3. SCHWARZER HUT (Kritik): Wo liegen die Gefahren, Risiken, Schwachstellen und Hürden?\n4. GELBER HUT (Optimismus): Was sind die Best-Case-Chancen, Vorteile und der Nutzen?\n5. GRÜNER HUT (Kreativität): Welche unkonventionellen, alternativen Wege gibt es noch?\n6. BLAUER HUT (Prozess): Wie sieht die finale Synthese und der nächste Prozessschritt aus?\n\nAUSGABE-FORMAT:\nAntworte zwingend geordnet nach den 6 Hüten: ⚪ Weiß | 🔴 Rot | 🖤 Schwarz | 🟡 Gelb | 🟢 Grün | 🔵 Blau",
        "Game-Theoretic Mechanism Design": "[METHODIK-FRAMEWORK: SPIELTHEORIE & MECHANISM DESIGN]\nAnalysiere die Situation als spieltheoretisches System aus strategischen Akteuren, Anreizen und Informationsasymmetrien:\n\n1. SPIELER & ZIELE (Akteure):\n- Wer sind die handelnden Parteien (z.B. Käufer, Verkäufer, Wettbewerber, Nutzer, Agenten)? Welche Nutzenfunktionen maximieren sie?\n\n2. ANREIZSTRUKTUREN & FEHLANREIZE (Incentive Alignment):\n- Wo existieren Moral Hazard, Principal-Agent-Konflikte oder adverse Selektion? Welche Handlungen werden belohnt, welche bestraft?\n\n3. GLEICHGEWICHTSANALYSE (Nash-Gleichgewicht):\n- In welchem stabilen Zustand endet das System, wenn jeder Akteur eigennützig und rational seine beste Antwort wählt?\n\n4. MECHANISM DESIGN & AUKTIONSTHEORIE:\n- Wie müssen Regeln, Auszahlungsmatrizen, Verträge oder Bietverfahren (z.B. Vickrey-Auktion, Stufenrabatte, Earn-Outs) gestaltet werden, damit ehrliches Verhalten und Kooperation die dominante Strategie werden?\n\nAUSGABE-FORMAT:\n### Akteure & Nutzenfunktionen | ### Fehlanreize & Asymmetrien | ### Nash-Gleichgewicht | ### Designter Mechanismus (Dominante Strategie)",
        "Bayesian Updating & Superforecasting (Tetlock)": "[METHODIK-FRAMEWORK: BAYESIAN UPDATING & SUPERFORECASTING]\nErsetze Bauchgefühl und binäres Schwarz-Weiß-Denken durch kalibrierte Wahrscheinlichkeiten nach Bayes und Philip Tetlock:\n\n1. OUTSIDE VIEW (Basisrate / Prior $P(H)$): Wie oft gelingen vergleichbare Vorhaben statistisch in der Referenzklasse wirklich (ohne Insider-Optimismus)?\n2. INSIDE VIEW & EVIDENZGEWICHTUNG (Likelihood Ratio): Welche spezifischen positiven und negativen Signale verschieben die Basisrate nach oben oder unten?\n3. POSTERIOR-WAHRSCHEINLICHKEIT ($P(H|E)$): Beziffere die aktualisierte Erfolgswahrscheinlichkeit als explizites Prozent-Intervall.\n4. FALSIFIKATIONS-MEILENSTEINE: Welche konkreten Messdaten in 30/90 Tagen würden deine Wahrscheinlichkeit um $\\ge 20$ Prozentpunkte senken oder erhöhen?\n\nAUSGABE-FORMAT:\n[1. Referenzklasse & Prior %] | [2. Evidenz-Signale (+/-)] | [3. Kalibrierter Posterior %] | [4. Update-Trigger]",
        "Inversion Thinking (Charlie Munger / Jacobi)": "[METHODIK-FRAMEWORK: INVERSION THINKING (\"INVERT, ALWAYS INVERT\")]\nLöse komplexe Probleme vorwärts UND rückwärts nach Charlie Munger und Carl Gustav Jacobi: Statt nur zu fragen \"Wie erreichen wir Brillanz?\", frage zuerst \"Wie garantieren wir katastrophales Scheitern?\" und eliminiere diese Pfade:\n\n1. VORWÄRTS-ZIEL: Was ist das angestrebte positive Ergebnis?\n2. ANTI-ZIEL (Garantierter Misserfolg): Welche 5–7 Handlungen, Architekturentscheidungen oder Unterlassungen führen mit Sicherheit in das Desaster?\n3. SYSTEMATISCHE VERMEIDUNGS-BARRIEREN: Baue harte technische, vertragliche oder prozessuale Sperren gegen jeden einzelnen Misserfolgs-Pfad ein.\n4. ASYMMETRISCHER RESTPFAD: Formuliere die robuste Strategie, die übrig bleibt, wenn alle Dummheiten ausgeschlossen sind.\n\nAUSGABE-FORMAT:\n### 1. Vorwärts-Ziel | ### 2. Rezept für garantiertes Scheitern | ### 3. Harte Schutz-Barrieren | ### 4. Robuste Gewinnstrategie",
        "Steelmanning & Hegelian Dialectic (Thesis-Antithesis-Synthesis)": "[METHODIK-FRAMEWORK: STEELMANNING & HEGELSCHE DIALEKTIK]\nÜberwinde oberflächliche Kompromisse und Strohmann-Argumente, indem du widerstreitende Positionen in ihrer jeweils stärkstmöglichen Form gegeneinanderstellst:\n\n1. THESE (Stärkstes Argument für Option A): Formuliere Position A mit den besten Daten, Prämissen und ökonomischen Hebeln.\n2. ANTITHESE ALS STEELMAN (Stärkstes Gegenargument / Option B): Baue die Gegenposition NICHT als schwachen Strohmann auf, sondern mache sie so intelligent, faktenstark und unwiderlegbar wie möglich.\n3. KERNKONFLIKT DER PRÄMISSEN: An exakt welcher Annahme oder Zielgewichtung scheiden sich These und Antithese?\n4. DIALEKTISCHE SYNTHESE: Konstruiere eine Lösung höherer Ordnung, die die berechtigten Stärken beider Seiten bewahrt und den Widerspruch auflöst.\n\nAUSGABE-FORMAT:\n[1. These (Maximalform)] | [2. Steelman-Antithese] | [3. Prämissen-Bruchlinie] | [4. Überlegene Synthese]",
    },
    "6. Systemdenken & Komplexität": {
        "Causal Loop Diagrams (System Dynamics)": "[METHODIK-FRAMEWORK: CAUSAL LOOP DIAGRAMS]\nAnalysiere die Dynamik des Systems über Rückkopplungsschleifen:\n\n1. SYSTEM-ELEMENTE: Identifiziere die Schlüsselvariablen des Problems.\n2. VERSTÄRKENDE SCHLEIFEN (Reinforcing Loops - R):\n- Welche Teufelskreise oder Positiv-Spiralen verstärken sich selbst? (Wenn A steigt, steigt B, was A weiter erhöht).\n3. AUSGLEICHENDE SCHLEIFEN (Balancing Loops - B):\n- Welche Dämpfer oder natürlichen Grenzen begrenzen das Wachstum/die Leistung?\n4. ZEITVERZÖGERUNGEN (Delays): Wo treten verzögerte Wirkungen auf, die zu Fehlanpassungen führen?\n\nAUSGABE-FORMAT:\nStrukturiere in: [Variablen] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Zeitverzögerungen]",
        "Iceberg Model (Systems Thinking)": "[METHODIK-FRAMEWORK: DAS EISBERG-MODELL]\nDringe unter die Oberfläche des sichtbaren Problems vor:\n\n1. EREIGNISSE (Sichtbare Spitze): Was ist gerade passiert? (Das unmittelbare Symptom).\n2. MUSTER & TRENDS (Unter der Wasserlinie): Was passiert immer wieder? Welche Historie zeigt sich?\n3. SYSTEMSTRUKTUREN: Wie sind die Prozesse, Werkzeuge und Regeln aufgebaut, die dieses Muster erzeugen?\n4. MENTALE MODELLE (Fundament): Welche Grundhaltungen, Überzeugungen oder Design-Philosophien halten die Struktur aufrecht?\n\nAUSGABE-FORMAT:\nAnalysiere von oben nach unten: [1. Ereignis] -> [2. Muster] -> [3. Struktur] -> [4. Mentales Modell]",
        "Second-Order Thinking (Howard Marks)": "[METHODIK-FRAMEWORK: SECOND-ORDER THINKING]\nDenke über die unmittelbaren Konsequenzen einer Entscheidung hinaus:\n\n1. EFFEKTE 1. ORDNUNG (Unmittelbar & Offensichtlich):\n- Was ist die direkte Folge der Handlung/des Codes? (Fast immer positiv gedacht).\n\n2. EFFEKTE 2. ORDNUNG (Mittelbar & Nebenwirkungen):\n- Was passiert in 3-6 Monaten als direkte Konsequenz der Effekte 1. Ordnung? Welche unbeabsichtigten Nebenwirkungen entstehen?\n\n3. EFFEKTE 3. ORDNUNG (Langfristige System-Shifts):\n- Wie verändert diese Entscheidung das Gesamtsystem, die Kosten oder das Nutzerverhalten langfristig?\n\nAUSGABE-FORMAT:\nGliedere in: [1st Order: Direkt] | [2nd Order: Nebenwirkungen] | [3rd Order: Systemwirkung]",
        "Wardley Mapping": "[METHODIK-FRAMEWORK: WARDLEY MAPPING]\nKartiere die Komponenten des Systems entlang der Wertschöpfungskette und ihrer Evolution:\n\n1. NORTSTERN / USER NEED: Was braucht der Nutzer an oberster Stelle?\n2. WERTSCHÖPFUNGSKETTE: Welches Modul baut auf welchem auf? (Sichtbar -> Unsichtbar).\n3. EVOLUTIONSSTUFEN DER KOMPONENTEN:\n   - Genesis (Unbekannt, Experimentell)\n   - Custom-Built (Maßgeschneidert, Eigenbau)\n   - Product/Rental (Standard-Produkt/SaaS)\n   - Commodity/Utility (Infrastruktur, Standard-Strom)\n\nSTRATEGISCHER ZUG: Welche Eigenbauten sollten durch Commodities ersetzt werden, um Ressourcen freizusetzen?\n\nAUSGABE-FORMAT:\n### Wertschöpfungskette | ### Evolutions-Mapping | ### Strategischer Hebel",
        "Donella Meadows 12 Leverage Points": "[METHODIK-FRAMEWORK: DONELLA MEADOWS LEVERAGE POINTS (SYSTEMHEBEL)]\nVerschwende keine Ressourcen an schwachen Parameter-Korrekturen, sondern identifiziere die tiefsten Eingriffspunkte im System (von schwach nach hochwirksam):\n\n1. PARAMETER & PUFFER (Schwacher Hebel): Bloßes Drehen an Zahlen, Budgets, Fristen oder Kapazitätsgrenzen.\n2. INFORMATIONSFLÜSSE & FEEDBACK-GESCHWINDIGKEIT (Mittlerer Hebel): Wer sieht welche Konsequenzen in Echtzeit? Wo fehlen direkte Rückkopplungen?\n3. SYSTEMREGELN & ANREIZE (Starker Hebel): Wer hat Entscheidungsbefugnis, wie werden Gewinne/Strafen verteilt, welche Constraints gelten?\n4. SYSTEMZIEL & PARADIGMA (Höchster Hebel): Auf welche oberste Zielgröße ist das Gesamtsystem ausgerichtet?\n\nAUSGABE-FORMAT:\n### Diagnose schwacher Parameter-Eingriffe | ### Informations- & Regel-Hebel | ### Höchster Systemhebel & Umbauplan",
        "Viable System Model (VSM / Stafford Beer)": "[METHODIK-FRAMEWORK: VIABLE SYSTEM MODEL (KYBERNETISCHE ORGANISATION)]\nDiagnostiziere und gestalte komplexe Organisationen oder Multi-Agenten-Systeme anhand der 5 lebensnotwendigen Subsysteme nach Stafford Beer:\n\n1. SYSTEM 1 (Operative Einheiten): Wertschöpfende Facheinheiten mit notwendiger lokaler Autonomie.\n2. SYSTEM 2 (Koordination & Anti-Oszillation): Gemeinsame Standards, Protokolle und Konfliktdämpfung zwischen den Einheiten.\n3. SYSTEM 3 & 3* (Operative Steuerung & Sporadisches Audit): Ressourcenallokation, Synergien und direkter Stichproben-Durchgriff.\n4. SYSTEM 4 (Strategische Umweltaufklärung / Zukunft): Radar für Marktveränderungen, Technologiebrüche und externe Risiken.\n5. SYSTEM 5 (Normative Identität & oberste Balance): Ausgleich zwischen heutiger Effizienz (System 3) und Zukunftsfähigkeit (System 4).\n\nAUSGABE-FORMAT:\n[System 1: Betrieb] | [System 2: Koordination] | [System 3/3*: Steuerung & Audit] | [System 4: Zukunft] | [System 5: Governance-Verdikt]",
    },
    "7. Zukunftsforschung, Risiko & Resilienz": {
        "Antifragilitäts-Analyse (Nassim Taleb)": "[METHODIK-FRAMEWORK: TALEB ANTIFRAGILITÄT]\nKlassifiziere und optimiere das System nach seiner Reaktion auf Stress, Fehler und Volatilität:\n\n1. FRAGIL (Bricht bei Stress): Wo führen Fehler zu fatalen Kettenreaktionen oder Abstürzen?\n2. ROBUST (Hält Stress stand): Wo bleibt das System unverändert stabil, lernt aber nicht dazu?\n3. ANTIFRAGIL (Gewinnt durch Stress): Wie kann das System so gebaut werden, dass es aus Fehlern, Ausnahmen und Stress Dazulernt und BESSER wird?\n\nREFACTORING: Wandle fragile Systemkomponenten in antifragile Schleifen um (z. B. automatisches Reinforcement-Learning aus Error-Logs).\n\nAUSGABE-FORMAT:\n### Fragile Schwachstellen | ### Robuste Kernzonen | ### Antifragile Optimierungen",
        "FMEA (Failure Mode and Effects Analysis)": "[METHODIK-FRAMEWORK: FMEA RISIKO-QUANTIFIZIERUNG]\nBewerte Systemfehler quantitativ nach der Risikoprioritätszahl (RPN = A x B x E):\n\n1. FEHLERMÖGLICHKEIT: Was kann an Komponente X schiefgehen?\n2. AUFTRETENSWAHRSCHEINLICHKEIT (A: 1-10): Wie oft kommt der Fehler vor?\n3. BEDEUTUNG / SCHWERE (B: 1-10): Wie gravierend ist der Schaden für den Nutzer?\n4. ENTDECKUNGSSICHERHEIT (E: 1-10): Wie schwer ist der Fehler vor dem Deployment zu erkennen? (10 = unbemerkt).\n5. RPN-SCORE (A x B x E): Werte über 100 erfordern zwingend eine Überarbeitung.\n\nKORREKTUR-ACTION: Behebe vorrangig Fehler mit den höchsten RPN-Scores.\n\nAUSGABE-FORMAT:\nTabellarische Liste: Component | Failure Mode | A | B | E | RPN | Massnahme",
        "OODA-Loop (John Boyd)": "[METHODIK-FRAMEWORK: OODA-LOOP ECHTZEIT-STEUERUNG]\nDurchlaufe den schnellen Orientierungs- und Entscheidungszirkel:\n\n1. OBSERVE (Beobachten): Erfasse alle verfügbaren Systemzustände, Logs, API-Feedbacks und Inputs.\n2. ORIENT (Orientieren): Filtere die Daten durch aktuelle Kontextfenster, KI-Rollen und Erfahrungen. Zerschlage falsche Wahrnehmungen.\n3. DECIDE (Entscheiden): Wähle schnell die effektivste Handlungsoption aus (Vermeide Analysis Paralysis).\n4. ACT (Handeln): Führe den Code/die Aktion sofort aus und speise das Ergebnis direkt zurück in Schritt 1.\n\nAUSGABE-FORMAT:\n[Observe] -> [Orient] -> [Decide] -> [Act]",
        "Scenario Planning (Shell-Methode)": "[METHODIK-FRAMEWORK: SZENARIO-PLANUNG]\nEntwickle 3 plausible, voneinander unabhängige Zukunftsszenarien für das Vorhaben:\n\n1. SZENARIO A: \"BEST CASE / GROWTH\" (Optimale Bedingungen)\n- Wie sieht die Lösung aus und wie skaliert sie unter idealen Voraussetzungen?\n\n2. SZENARIO B: \"STAGFLATION / ADVERSARIAL\" (Ressourcenknappheit / Hohe Fehlerquote)\n- Wie schlägt sich das System bei extrem hohen Kosten, Ausfällen oder Latenzen?\n\n3. SZENARIO C: \"BLACK SWAN / DISRUPTION\" (Unerwarteter Systemwechsel)\n- Was passiert, wenn sich die Grundannahmen schlagartig ändern?\n\nSTRATEGIE: Leite Maßnahmen ab, die in ALLEN 3 Szenarien funktionieren (No-Regret-Moves).\n\nAUSGABE-FORMAT:\n[Szenario A] | [Szenario B] | [Szenario C] | [No-Regret-Maßnahmen]",
        "Monte-Carlo & Expected Value Entscheidungsbaum": "[METHODIK-FRAMEWORK: MONTE-CARLO & EXPECTED-VALUE ENTSCHEIDUNGSANALYSE]\nBewerte Entscheidungen unter Unsicherheit nicht mit trügerischen Punktschätzungen, sondern über Wahrscheinlichkeitsverteilungen und Erwartungswerte:\n\n1. UNSICHERHEITSTREIBER & SPANNBREITEN: Definiere für die 3–5 kritischen Variablen P10 (Pessimistisch), P50 (Median) und P90 (Optimistisch).\n2. ENTSCHEIDUNGSBAUM & EXPECTED VALUE (EV):\n   - Berechne $EV = \\sum p_i \\cdot \\text{Payoff}_i$ für jede Handlungsalternative.\n3. TAIL-RISK & RUIN-SCHUTZ (Value at Risk): Prüfe das untere 5-%-Perzentil — führt der Worst Case zu existenziellem Schaden / Liquiditätsbruch (Kelly-Kriterium)?\n4. REALOPTIONEN & STUFEN-COMMITMENT: Wie lässt sich die Investition in kleine Meilensteine schneiden, um Informationen zu kaufen, bevor das volle Kapital gebunden wird?\n\nAUSGABE-FORMAT:\n### Variablen-Spannen (P10/P50/P90) | ### Expected-Value-Vergleich | ### Downside-/Ruin-Check | ### Gestufte Options-Entscheidung",
        "Swiss Cheese Model (James Reason / Defense-in-Depth)": "[METHODIK-FRAMEWORK: SWISS CHEESE MODEL & DEFENSE-IN-DEPTH]\nEntwirf mehrschichtige Sicherheits- und Qualitätsbarrieren, damit einzelne menschliche oder technische Fehler niemals bis zum Gesamtschaden durchschlagen:\n\n1. GEFAHRENQUELLE & SCHADENSEREIGNIS: Welcher kritische Fehler (Security Breach, Fehlüberweisung, Produktionsausfall, Rechtsverstoß) muss verhindert werden?\n2. UNABHÄNGIGE ABWEHRSCHICHTEN (Cheese Slices):\n   - Schicht 1: Prävention durch Design / Architektur (Fehler unmöglich machen, Poka-Yoke).\n   - Schicht 2: Automatisierte Validierung / Guardrails / Berechtigungszäune.\n   - Schicht 3: Echtzeit-Detektion, Anomalie-Monitoring & Circuit-Breaker.\n   - Schicht 4: Eindämmung (Blast-Radius-Isolation, Rollback, Backup).\n3. LATENTE LÖCHER VERSCHIEBEN: Stelle sicher, dass keine zwei Schichten dieselbe gemeinsame Fehlerursache (Common-Mode Failure) teilen.\n\nAUSGABE-FORMAT:\n### Bedrohungsvektor | ### Abwehrschichten 1–4 & ihre aktuellen Löcher | ### Entkoppelte Härtungs-Architektur",
    },
}

CATEGORIZED_FRAMEWORKS_EN = {
    "1. Agile, Design & Innovation": {
        "CLEAR Model": "[METHODOLOGY FRAMEWORK: CLEAR MODEL]\nApply the CLEAR analytical model strictly to the problem statement. Structure your reasoning and output across all 5 phases without exception:\n\n1. CONCISE:\n- Distill the core problem down to 2–3 razor-sharp sentences. Strip away distractions and secondary noise.\n\n2. LOGICAL:\n- Build an unbroken causal argument chain (If X, then Y, because Z). Expose logical fallacies and unverified assumptions.\n\n3. EXPLICIT:\n- Ban vague abstractions. Specify exact metrics, methods, tools, owners, timelines, and unambiguous decision options.\n\n4. ADAPTIVE:\n- Stress-test the proposed solution against shifting boundary conditions and edge cases. Provide at least one viable fallback alternative.\n\n5. REFLECTIVE:\n- Subject your own conclusion to adversarial self-critique: Where do residual vulnerabilities, risks, or blind spots remain?\n\nOUTPUT FORMAT:\nStructure your response strictly with:\n[C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective",
        "CREATE Behavioral Framework": "[METHODOLOGY FRAMEWORK: CREATE ACTION FUNNEL]\nAnalyze and solve the challenge across the 6 behavioral-economics stages of the CREATE Action Funnel:\n\n1. C - Cue (Trigger): What external or internal signal initiates the behavior or workflow?\n2. R - Reaction (Intuitive System-1 Response): What immediate emotional or cognitive gut reaction occurs?\n3. E - Evaluation (Conscious System-2 Cost-Benefit): How are benefits weighed against costs and risks?\n4. A - Ability (Friction & Capability): Does the actor have the tools and low-friction path to act immediately?\n5. T - Timing (Urgency): Why must action happen NOW rather than later?\n6. E - Execute (Action & Feedback Loop): How is execution completed and reinforced?\n\nOUTPUT FORMAT:\nOrganize your deliverable cleanly into [C], [R], [E], [A], [T], and [E].",
        "Design Sprint (GV / Jake Knapp)": "[METHODOLOGY FRAMEWORK: 5-PHASE DESIGN SPRINT]\nExecute the Google Ventures Design Sprint methodology across 5 structured phases:\n\n1. MAP: Define the long-term target outcome, map the end-to-end actor journey, and isolate the critical sprint focus.\n2. SKETCH: Generate competing, concrete solution architectures in high resolution.\n3. DECIDE: Evaluate competing sketches against impact/feasibility criteria and commit to the strongest testable hypothesis.\n4. PROTOTYPE: Specify the minimum realistic artifact needed to validate the core assumption rapidly.\n5. TEST: Define 3–5 falsifiable validation questions and pass/fail metrics with real users or stakeholders.\n\nOUTPUT FORMAT:\n### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test",
        "Double Diamond (Design Council)": "[METHODOLOGY FRAMEWORK: DOUBLE DIAMOND]\nSolve the challenge by alternating systematically between divergent exploration and convergent synthesis:\n\nDIAMOND 1: SOLVING THE RIGHT PROBLEM\n1. Discover (Divergent): Explore the problem space broadly—uncover hidden stakeholder needs, system constraints, and edge cases.\n2. Define (Convergent): Synthesize findings into a single, razor-sharp problem definition and root bottleneck.\n\nDIAMOND 2: DESIGNING THE RIGHT SOLUTION\n3. Develop (Divergent): Architect distinct, competing solution pathways without premature filtering.\n4. Deliver (Convergent): Select the highest-leverage architecture, refine implementation details, and prepare immediate rollout.\n\nOUTPUT FORMAT:\n[1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]",
        "Lean Startup (Build-Measure-Learn)": "[METHODOLOGY FRAMEWORK: LEAN STARTUP (ERIC RIES)]\nApply empirical hypothesis testing to minimize wasted capital and engineering cycles:\n\n1. LEAP-OF-FAITH HYPOTHESIS: Identify the riskiest unproven value and growth assumptions that must hold true.\n2. BUILD (Minimum Viable Experiment): Design the leanest MVP or concierge test capable of validating or refuting the hypothesis.\n3. MEASURE (Actionable Metrics): Define non-gameable cohort/conversion metrics rather than vanity metrics.\n4. LEARN (Persevere or Pivot): Establish explicit numeric thresholds triggering either scaling (Persevere) or strategic redirection (Pivot).\n\nOUTPUT FORMAT:\n1. Core Hypothesis | 2. MVP Specification | 3. Actionable Metrics | 4. Pivot / Persevere Thresholds",
        "OKRs (Objectives and Key Results)": "[METHODOLOGY FRAMEWORK: OBJECTIVES AND KEY RESULTS (OKRs)]\nTranslate the strategic challenge into an execution-ready OKR cascade:\n\n1. OBJECTIVE (Qualitative North Star):\n- Formulate 1–2 ambitious, unambiguous, directional objectives (Where must we win?).\n\n2. KEY RESULTS (Quantitative Outcomes, Not Tasks):\n- Define 3 measurable Key Results per Objective (\"Move metric X from baseline A to target B by date T\").\n\n3. STRATEGIC INITIATIVES (Execution Plan):\n- List the concrete workstreams, owners, and milestones required to drive the Key Results.\n\nOUTPUT FORMAT:\n### Objective | ### Key Results (1–3) | ### High-Leverage Initiatives",
        "STEEPLE / PESTEL Macro Analysis": "[METHODOLOGY FRAMEWORK: STEEPLE / PESTEL MACRO-ENVIRONMENT AUDIT]\nAudit external macro-environmental forces systematically across all 7 dimensions:\n\n1. Social: Demographics, buyer behavior, workforce shifts, cultural norms.\n2. Technological: AI/automation shifts, infrastructure maturity, obsolescence risk.\n3. Economic: Interest rates, inflation, unit-cost dynamics, capital availability.\n4. Environmental: Carbon/ESG mandates, physical climate risk, resource constraints.\n5. Political: Trade/tariff policy, subsidies, geopolitical stability, public procurement.\n6. Legal: Regulatory compliance (GDPR/CCPA, antitrust, liability, sector statutes).\n7. Ethical: Trust, algorithmic fairness, transparency, reputational risk.\n\nOUTPUT FORMAT:\nDeliver a quantified Opportunity & Threat rating for [S], [T], [E], [E], [P], [L], and [E], followed by ### Top 3 Strategic Implications.",
        "Steffi Kieffer Boardroom": "[METHODOLOGY FRAMEWORK: EXECUTIVE AI BOARDROOM DEBATE]\nConduct a multi-perspective executive boardroom deliberation pitting distinct specialist lenses against one another:\n\n1. CHAIRMAN FRAMING: Set decision boundaries, constraints, and evaluation criteria clearly.\n2. RISK & COMPLIANCE CHALLENGER: Expose downside risks, regulatory traps, security flaws, and fragile assumptions.\n3. STRATEGIC INNOVATOR: Champion asymmetric upside, market differentiation, and long-term compounding leverage.\n4. PRAGMATIC OPERATOR: Ground the debate in execution feasibility, budget, timeline, and immediate implementation steps.\n5. CHAIRMAN RESOLUTION: Weigh competing trade-offs transparently and issue an unmistakable executive decision.\n\nOUTPUT FORMAT:\nPresent the structured specialist positions followed by a decisive [CHAIRMAN SYNTHESIS & RESOLUTION].",
        "Jobs-to-be-Done (JTBD / Clayton Christensen)": "[METHODOLOGY FRAMEWORK: JOBS-TO-BE-DONE (JTBD)]\nAnalyze demand and product strategy through the concrete progress (\"Job\") the customer is hiring a solution to achieve in a specific context:\n\n1. STRUGGLING MOMENT & CONTEXT: Under what exact operational trigger does the current workaround break down?\n2. FUNCTIONAL, EMOTIONAL & SOCIAL DIMENSIONS:\n   - Functional: What measurable core outcome must be completed?\n   - Emotional / Social: What risk, anxiety, or stakeholder friction must be eliminated?\n3. FOUR FORCES OF PROGRESS:\n   - Push of the status quo + Pull of the new solution vs. Anxiety of switching + Habit of the incumbent workflow.\n4. OUTCOME-DRIVEN SOLUTION: Engineer the offering to complete the entire job faster, cheaper, and with zero switching friction.\n\nOUTPUT FORMAT:\n[1. Struggling Moment] | [2. Job Dimensions] | [3. Four Forces Balance] | [4. Outcome-Driven Solution]",
        "Blue Ocean Strategy (ERRC Grid)": "[METHODOLOGY FRAMEWORK: BLUE OCEAN STRATEGY & ERRC GRID]\nBreak out of zero-sum Red Ocean competition and unlock uncontested market space through Value Innovation (simultaneous differentiation and lower cost):\n\n1. RED OCEAN BASELINE: Identify the commoditized industry factors where rivals over-compete at shrinking margins.\n2. ERRC FOUR-ACTIONS MATRIX:\n   - ELIMINATE: Which taken-for-granted industry factors deliver zero real buyer value and should be cut completely?\n   - REDUCE: Which over-engineered specs should be dialed well below industry norms?\n   - RAISE: Which high-impact value drivers must be elevated dramatically above industry standards?\n   - CREATE: Which entirely new sources of buyer value should be introduced for the first time?\n3. DIVERGENT VALUE CURVE: Demonstrate how cost structure drops while buyer utility surges.\n\nOUTPUT FORMAT:\n### Red Ocean Baseline | ### ERRC Grid (Eliminate / Reduce / Raise / Create) | ### New Value Curve & Tagline",
    },
    "2. Root-Cause Analysis, Logic & Problem Solving": {
        "5-Whys Root-Cause Analysis": "[METHODOLOGY FRAMEWORK: 5-WHYS ROOT-CAUSE DRILLDOWN]\nPierce past superficial symptoms to isolate the structural root cause via cascading causal interrogation:\n\n- Problem Statement: [Define observable failure or performance gap precisely]\n- Why 1: Why does this symptom occur? -> Causal Fact 1\n- Why 2: Why does Causal Fact 1 occur? -> Causal Fact 2\n- Why 3: Why does Causal Fact 2 occur? -> Causal Fact 3\n- Why 4: Why does Causal Fact 3 occur? -> Causal Fact 4\n- Why 5: Why does Causal Fact 4 occur? -> SYSTEMIC ROOT CAUSE\n\nPERMANENT COUNTERMEASURE:\nDesign a structural fix eliminating the systemic root cause rather than patching the surface symptom.\n\nOUTPUT FORMAT:\nList all 5 causal steps explicitly and conclude with ### Systemic Root Cause & ### Permanent Countermeasure.",
        "Cynefin Sense-Making Framework (Dave Snowden)": "[METHODOLOGY FRAMEWORK: CYNEFIN DOMAIN CLASSIFICATION]\nClassify the operational regime accurately before selecting a management or engineering response:\n\n1. DOMAIN DIAGNOSIS:\n   - Clear (Simple): Tight cause-and-effect -> Sense – Categorize – Respond (apply best practice / automate).\n   - Complicated: Discoverable cause-and-effect requiring expertise -> Sense – Analyze – Respond (apply good practice).\n   - Complex: Emergent causality understood only in retrospect -> Probe – Sense – Respond (run safe-to-fail experiments).\n   - Chaotic: Acute crisis with no visible constraints -> Act – Sense – Respond (stabilize bleeding immediately).\n2. REGIME-MATCHED ACTION PLAN: Derive concrete execution steps matching the diagnosed Cynefin domain without misapplying rigid rules to complex problems.\n\nOUTPUT FORMAT:\n### Cynefin Domain Diagnosis | ### Diagnostic Evidence | ### Regime-Specific Action Plan",
        "First Principles Thinking": "[METHODOLOGY FRAMEWORK: FIRST PRINCIPLES DECONSTRUCTION]\nStrip away reasoning-by-analogy and rebuild the optimal solution from bedrock physical, mathematical, and economic truths:\n\n1. ASSUMPTION STRIPPING:\n   - Expose inherited industry conventions, legacy cost structures, and \"that's how it's always done\" dogmas.\n2. BEDROCK AXIOMS (Fundamental Truths):\n   - Isolate the non-negotiable physical, technical, statutory, and unit-economic constraints that cannot be violated.\n3. GROUND-UP RECONSTRUCTION:\n   - Synthesize a step-change architecture directly from those fundamental truths without copying legacy blueprints.\n\nOUTPUT FORMAT:\n[1. Discarded Legacy Assumptions] | [2. Bedrock Fundamental Truths] | [3. Ground-Up Reconstructed Solution]",
        "Ishikawa Fishbone Diagram (6Ms)": "[METHODOLOGY FRAMEWORK: ISHIKAWA 6M CAUSE-AND-EFFECT AUDIT]\nInvestigate failure contributors systematically across all 6 operational branches:\n\n1. Man / People: Skill gaps, cognitive overload, handoff ambiguity, incentive misalignment.\n2. Machine / Infrastructure: Compute/hardware limits, software bugs, model/API instability.\n3. Method / Process: Flawed workflows, missing SOPs, broken approval or validation logic.\n4. Material / Data: Corrupted inputs, schema drift, stale upstream data, prompt defects.\n5. Milieu / Environment: Network latency, regulatory shifts, load spikes, external dependencies.\n6. Measurement / Telemetry: Blind monitoring, misleading KPIs, missing alerts, noisy logs.\n\nOUTPUT FORMAT:\nAudit each of the 6Ms systematically and conclude with ### Primary Causal Driver & Remediation.",
        "Porter's Five Forces": "[METHODOLOGY FRAMEWORK: PORTER'S FIVE FORCES INDUSTRY STRUCTURE]\nQuantify structural industry attractiveness and profit pool defensibility across 5 competitive forces:\n\n1. Competitive Rivalry Among Incumbents (High / Moderate / Low + margin impact)\n2. Threat of New Entrants (Capital, regulatory, network, and data barriers to entry)\n3. Bargaining Power of Suppliers (Compute, APIs, talent, raw materials, concentration risk)\n4. Bargaining Power of Buyers (Switching costs, price sensitivity, buyer concentration)\n5. Threat of Substitutes (Alternative workflows, open-source disruption, paradigm shifts)\n\nOUTPUT FORMAT:\nRate and evidence each of the 5 forces, concluding with ### Structural Moat & Positioning Strategy.",
        "SWOT & TOWS Strategic Matrix": "[METHODOLOGY FRAMEWORK: SWOT & ACTIONABLE TOWS CROSS-MATRIX]\nMove beyond passive SWOT lists into executable TOWS strategic pairings:\n\nINTERNAL CAPABILITIES:\n- Strengths (S): Verified proprietary advantages, assets, and cost/tech edges.\n- Weaknesses (W): Internal bottlenecks, capability gaps, and structural vulnerabilities.\n\nEXTERNAL ENVIRONMENT:\n- Opportunities (O): Asymmetric market openings, regulatory tailwinds, underserved demand.\n- Threats (T): Competitive, technological, macroeconomic, or regulatory hazards.\n\nACTIONABLE TOWS PAIRINGS:\nDerive concrete **SO** (Maxi-Maxi), **WO** (Mini-Maxi), **ST** (Maxi-Mini), and **WT** (Mini-Mini) strategic moves.\n\nOUTPUT FORMAT:\n[Strengths] | [Weaknesses] | [Opportunities] | [Threats] | [TOWS Execution Moves]",
        "MECE & Minto Pyramid Principle (Barbara Minto)": "[METHODOLOGY FRAMEWORK: MECE & MINTO PYRAMID PRINCIPLE]\nStructure analytical problem-solving and executive communication with top-tier strategy consulting rigor:\n\n1. GOVERNING THOUGHT (Answer First): Lead immediately with the decisive, action-oriented recommendation in 1–2 sentences.\n2. SCQA FRAMING: Anchor context cleanly via *Situation – Complication – Key Question – Answer*.\n3. MECE DISAGGREGATION (*Mutually Exclusive, Collectively Exhaustive*):\n   - Decompose the argument or problem tree into non-overlapping, zero-gap analytical pillars.\n4. QUANTIFIED EVIDENCE BASE: Back each pillar with verifiable metrics, calculations, and empirical proof.\n\nOUTPUT FORMAT:\n### Governing Thought (Answer First) | ### SCQA Context | ### MECE Pillar Breakdown (1–3) | ### Implementation Metrics",
        "Kepner-Tregoe Problem Analysis (IS / IS NOT)": "[METHODOLOGY FRAMEWORK: KEPNER-TREGOE (KT) IS / IS-NOT DIAGNOSTIC]\nIsolate elusive technical or operational root causes by contrasting exact boundary conditions:\n\n1. DEVIATION STATEMENT: State the exact gap between expected standard performance and observed behavior.\n2. FOUR-DIMENSION SPECIFICATION MATRIX (IS vs. IS NOT):\n   - WHAT object/defect IS observed vs. closely related objects/defects that ARE NOT affected?\n   - WHERE is it observed geographically/architecturally vs. WHERE IS IT NOT?\n   - WHEN did it first occur / recur in lifecycle timing vs. WHEN DID IT NOT?\n   - EXTENT: How many units/requests are impacted and is the trend growing, stable, or decaying?\n3. DISTINCTIONS & CHANGES: Identify what is unique to the IS column and what changed near that boundary.\n4. CAUSE TESTING: Test candidate causes against every IS and IS-NOT fact until one explains all observations without contradiction.\n\nOUTPUT FORMAT:\n[1. Deviation Statement] | [2. IS / IS-NOT Table] | [3. Distinctions & Changes] | [4. Verified Root Cause & Fix]",
        "Fault Tree Analysis (FTA / IEC 61025)": "[METHODOLOGY FRAMEWORK: DEDUCTIVE FAULT TREE ANALYSIS (FTA)]\nMap critical system failure pathways top-down using Boolean gate logic (AND / OR):\n\n1. TOP UNDESIRED EVENT: Define the exact catastrophic failure state at the apex of the tree.\n2. BOOLEAN GATE DECOMPOSITION:\n   - OR Gates (Single Points of Failure): Any single child fault triggers the parent failure immediately.\n   - AND Gates (Redundancy Barriers): All child faults must fail simultaneously for the fault to propagate.\n3. MINIMAL CUT SETS: Extract the shortest fault combinations capable of causing the Top Event.\n4. ARCHITECTURAL REMEDIATION: Convert high-probability OR gates into independent AND gates via failover, validation, and isolation.\n\nOUTPUT FORMAT:\n### Top Event | ### Boolean Fault Tree (AND/OR Paths) | ### Minimal Cut Sets (SPOFs) | ### Redundancy Hardening",
    },
    "3. Operations, Lean & Quality Excellence": {
        "DMAIC (Six Sigma)": "[METHODOLOGY FRAMEWORK: SIX SIGMA DMAIC PROCESS EXCELLENCE]\nEliminate process defects, variance, and quality drift systematically across all 5 DMAIC phases:\n\n1. DEFINE: Specify the problem, customer Critical-to-Quality (CTQ) requirements, and project scope.\n2. MEASURE: Establish baseline process capability, defect rates, and data collection validity.\n3. ANALYZE: Isolate statistically and causally verified root drivers of variation.\n4. IMPROVE: Engineer, pilot, and verify targeted process changes eliminating the root drivers.\n5. CONTROL: Lock in gains with Statistical Process Control (SPC), automated alerts, and standard operating procedures.\n\nOUTPUT FORMAT:\n[Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control]",
        "PDCA Cycle (Deming Wheel)": "[METHODOLOGY FRAMEWORK: DEMING PDCA CONTINUOUS IMPROVEMENT]\nDrive disciplined iterative improvement across the 4-stage Plan-Do-Check-Act loop:\n\n1. PLAN: Diagnose the current baseline, quantify the target improvement, and formulate a falsifiable action plan.\n2. DO: Execute a controlled, small-blast-radius pilot or prototype implementation.\n3. CHECK: Measure pilot results rigorously against predicted targets and analyze deviations.\n4. ACT: Standardize validated improvements system-wide or refine hypotheses for the next cycle.\n\nOUTPUT FORMAT:\n### Plan | ### Do | ### Check | ### Act",
        "Theory of Constraints (TOC / Eliyahu Goldratt)": "[METHODOLOGY FRAMEWORK: THEORY OF CONSTRAINTS (5 FOCUSING STEPS)]\nMaximize end-to-end system throughput by concentrating exclusively on the single governing bottleneck:\n\n1. IDENTIFY THE CONSTRAINT: Pinpoint the single resource, policy, or stage limiting total system throughput.\n2. EXPLOIT THE CONSTRAINT: Squeeze 100% productive utilization out of the bottleneck using existing resources (zero idle/waste at the constraint).\n3. SUBORDINATE EVERYTHING ELSE: Pace all upstream and downstream non-constraints strictly to serve the bottleneck (Drum-Buffer-Rope).\n4. ELEVATE THE CONSTRAINT: Invest targeted capital, automation, or capacity to break the bottleneck only after full exploitation.\n5. PREVENT INERTIA: Once broken, immediately identify the new system constraint.\n\nOUTPUT FORMAT:\n[1. Governing Bottleneck] | [2. Exploitation Plan] | [3. System Subordination] | [4. Capacity Elevation]",
        "Value Stream Mapping (VSM / Lean Flow)": "[METHODOLOGY FRAMEWORK: END-TO-END VALUE STREAM MAPPING (VSM)]\nExpose and eliminate non-value-adding waste across the entire delivery pipeline from trigger to customer outcome:\n\n1. CURRENT-STATE MAP: Quantify Process Time (Value-Add), Wait/Queue Time, Total Lead Time, and First-Pass Yield (% Complete & Accurate) per step.\n2. PROCESS CYCLE EFFICIENCY (PCE): Compute $\\text{PCE} = \\text{Value-Add Time} / \\text{Total Lead Time}$.\n3. 8-WASTES AUDIT (DOWNTIME): Pinpoint Defects, Overproduction, Waiting, Non-utilized talent, Transportation, Inventory/WIP queues, Motion, and Extra-processing.\n4. FUTURE-STATE ARCHITECTURE: Design continuous flow,WIP pull limits, and automation with quantified Lead-Time reduction.\n\nOUTPUT FORMAT:\n[1. Current-State Metrics & PCE] | [2. Waste Hotspots (DOWNTIME)] | [3. Future-State Design] | [4. Throughput Gain]",
        "A3 Problem-Solving (Toyota Production System)": "[METHODOLOGY FRAMEWORK: TOYOTA A3 EXECUTIVE PROBLEM-SOLVING]\nSynthesize diagnosis, root-cause proof, and execution governance onto a crisp single-sheet Toyota A3 structure:\n\n1. BACKGROUND & STRATEGIC CONTEXT: Why does solving this gap matter right now?\n2. CURRENT CONDITION (Gemba Facts): Verified baseline metrics and observed workflow breakdown.\n3. TARGET CONDITION: Specific measurable target metric and deadline.\n4. ROOT-CAUSE ANALYSIS: Direct causal chain explaining the gap between Current and Target.\n5. COUNTERMEASURES & EXECUTION PLAN: Concrete interventions with Owner, Due Date, and Expected Impact.\n6. CONFIRMATION OF EFFECT & FOLLOW-UP: Verification telemetry and permanent SOP standardization.\n\nOUTPUT FORMAT:\n### 1. Background | ### 2. Current Baseline | ### 3. Target State | ### 4. Root Cause | ### 5. Countermeasures | ### 6. Verification & SOP",
        "SIPOC & RACI Process Governance": "[METHODOLOGY FRAMEWORK: SIPOC BOUNDARIES & RACI ACCOUNTABILITY]\nEliminate handoff ambiguity and diffused ownership across cross-functional workflows:\n\n1. SIPOC ARCHITECTURE:\n   - Suppliers -> Inputs (with strict entry acceptance criteria) -> Process (5–7 high-level stages) -> Outputs (artifacts) -> Customers (SLA expectations).\n2. RACI GOVERNANCE MATRIX:\n   - **R**esponsible (executes work), **A**ccountable (strictly ONE single owner per deliverable holding final sign-off!), **C**onsulted (two-way input before action), **I**nformed (one-way notification after action).\n3. HANDOFF & SLA GUARDRAILS: Resolve any step with zero or multiple Accountable owners.\n\nOUTPUT FORMAT:\n### SIPOC Specification | ### RACI Matrix Table | ### Handoff & Escalation SLAs",
    },
    "4. Corporate Strategy, Prioritization & Change": {
        "Eisenhower Priority Matrix": "[METHODOLOGY FRAMEWORK: EISENHOWER URGENCY-IMPORTANCE MATRIX]\nTriage competing initiatives and tasks ruthlessly across Importance and Urgency:\n\n1. QUADRANT I — DO IMMEDIATELY (Important & Urgent): Execute first with a concrete crisis/delivery checklist.\n2. QUADRANT II — SCHEDULE & PROTECT (Important & Not Urgent): Compounding strategic work—allocate dedicated deep-work blocks.\n3. QUADRANT III — DELEGATE OR AUTOMATE (Not Important & Urgent): Route to sub-agents, scripts, or standardized SOPs.\n4. QUADRANT IV — ELIMINATE (Not Important & Not Urgent): Drop completely to protect cognitive and system bandwidth.\n\nOUTPUT FORMAT:\n[Quadrant I: Do Now] | [Quadrant II: Schedule] | [Quadrant III: Delegate/Automate] | [Quadrant IV: Eliminate]",
        "Kano Customer Value Model": "[METHODOLOGY FRAMEWORK: KANO FEATURE & SATISFACTION CLASSIFICATION]\nClassify product or service attributes by their non-linear impact on customer satisfaction and retention:\n\n1. THRESHOLD / MUST-BE ATTRIBUTES: Table-stakes expectations—absence causes immediate churn, presence merely prevents dissatisfaction.\n2. PERFORMANCE / LINEAR ATTRIBUTES: More is directly better (e.g., speed, accuracy, unit cost)—primary battleground of competitive comparison.\n3. EXCITEMENT / DELIGHTERS: Unexpected high-leverage capabilities creating disproportionate differentiation and pricing power.\n4. INDIFFERENT / REVERSE ATTRIBUTES: Bloated features nobody values (cut to save engineering cost) or features that actively annoy users.\n\nOUTPUT FORMAT:\n[Must-Be Table Stakes] | [Linear Performance Drivers] | [Asymmetric Delighters] | [Cut / Avoid List]",
        "Kotter 8-Step Change Model": "[METHODOLOGY FRAMEWORK: KOTTER 8-STEP ORGANIZATIONAL TRANSFORMATION]\nArchitect complex organizational or technical migrations across all 8 transformation stages:\n\n1. Create Genuine Urgency (Quantify cost of status-quo stagnation)\n2. Build a Guiding Coalition (Assemble cross-functional authority and champions)\n3. Form a Strategic Vision & Initiatives (Clear target state)\n4. Enlist & Communicate the Vision (Relentless, unambiguous Rollout messaging)\n5. Enable Action by Removing Barriers (Eliminate legacy blockers, permissions, and friction)\n6. Generate Short-Term Wins (Deliver visible 30-day proof points)\n7. Sustain Acceleration (Compound wins without declaring premature victory)\n8. Institute Change in Systems & Culture (Embed into SOPs, incentives, and defaults)\n\nOUTPUT FORMAT:\nProvide concrete operational actions for all 8 stages tailored to the mission.",
        "McKinsey 7S Alignment Model": "[METHODOLOGY FRAMEWORK: MCKINSEY 7S ORGANIZATIONAL ALIGNMENT]\nAudit systemic coherence and surface misalignments across Hard and Soft organizational dimensions:\n\nHARD S ELEMENTS:\n1. Strategy: Competitive thesis and resource allocation.\n2. Structure: Organizational / modular topology and reporting lines.\n3. Systems: Operational workflows, tech stack, telemetry, and incentives.\n\nSOFT S ELEMENTS:\n4. Shared Values: Core non-negotiable operating principles.\n5. Style: Leadership posture and decision-making culture.\n6. Staff: Human and AI-agent roster composition.\n7. Skills: Distinct institutional capabilities and toolchains.\n\nOUTPUT FORMAT:\n### Hard-S Audit | ### Soft-S Audit | ### Cross-Dimensional Friction & Realignment Plan",
        "NABC Value Proposition Pitch (SRI International)": "[METHODOLOGY FRAMEWORK: SRI NABC VALUE PROPOSITION]\nDistill the initiative into an investor- and board-grade NABC value thesis:\n\n1. NEED: What acute, quantified market or operational pain exists, and who owns the budget for it?\n2. APPROACH: What is the specific, defensible mechanism or architecture that solves the need?\n3. BENEFITS PER COSTS: What is the quantified ROI, payback period, or unit-cost improvement relative to total investment?\n4. COMPETITION & ALTERNATIVES: Why does this approach beat both direct competitors and \"do-nothing / internal spreadsheet\" workarounds?\n\nOUTPUT FORMAT:\n[Need] | [Approach] | [Quantified Benefits / Cost] | [Competitive Superiority]",
        "RICE Quantitative Prioritization": "[METHODOLOGY FRAMEWORK: RICE QUANTITATIVE SCORING]\nRank competing roadmap items or strategic initiatives objectively using the RICE formula:\n$$\\text{RICE Score} = \\frac{\\text{Reach} \\times \\text{Impact} \\times \\text{Confidence}}{\\text{Effort}}$$\n\n1. REACH: Concrete number of users, transactions, or accounts impacted per quarter.\n2. IMPACT: Effect per user/account (3 = Massive, 2 = High, 1 = Medium, 0.5 = Low, 0.25 = Minimal).\n3. CONFIDENCE: Evidence quality (100% = Hard empirical data, 80% = Solid benchmark, 50% = Informed estimate).\n4. EFFORT: Total person-months / engineering sprints required.\n\nOUTPUT FORMAT:\nMarkdown Table: `Initiative | Reach | Impact | Confidence | Effort | RICE Score | Verdict` followed by sequencing rationale.",
        "Make-or-Buy & 36-Month TCO Scoring": "[METHODOLOGY FRAMEWORK: BUILD vs. BUY vs. PARTNER & 36-MONTH TCO]\nEvaluate technology, AI, and operational capability decisions across IP moat and full lifecycle economics:\n\n1. STRATEGIC DIFFERENTIATION: Core proprietary IP & competitive moat (Build) vs. non-differentiating commodity utility (Buy).\n2. 36-MONTH TOTAL COST OF OWNERSHIP (TCO):\n   - Build: Engineering build cost + ongoing maintenance, security patching, infra/GPU hosting, and opportunity cost.\n   - Buy: SaaS/API licensing, usage/token escalation risk, integration cost, and vendor lock-in switching cost.\n   - Partner: Revenue share / retainer, SLA dependency, and knowledge transfer.\n3. TIME-TO-VALUE: Speed advantage in weeks/months across options.\n4. DATA SOVEREIGNTY, SECURITY & COMPLIANCE: On-prem / VPC control vs. third-party data egress exposure.\n\nOUTPUT FORMAT:\n### Core IP Assessment | ### 36-Month TCO Comparison Table | ### Sovereignty & Lock-In Risk | ### Binding Verdict & 90-Day Plan",
        "Ansoff Growth Matrix": "[METHODOLOGY FRAMEWORK: ANSOFF PRODUCT-MARKET GROWTH MATRIX]\nEvaluate expansion vectors systematically across market familiarity, product novelty, and execution risk:\n\n1. MARKET PENETRATION (Existing Product / Existing Market — Lowest Risk): Capture share, increase usage frequency, reduce churn, optimize pricing.\n2. MARKET DEVELOPMENT (Existing Product / New Market): Expand into new geographies, enterprise/SMB tiers, or distribution channels.\n3. PRODUCT DEVELOPMENT (New Product / Existing Market): Launch adjacent modules or next-gen offerings to the existing customer base.\n4. DIVERSIFICATION (New Product / New Market — Highest Risk): Related (concentric) vs. unrelated expansion requiring new capabilities.\n5. SEQUENCED CAPITAL ALLOCATION: Recommend exact phasing by risk-adjusted ROI.\n\nOUTPUT FORMAT:\n[1. Market Penetration] | [2. Market Development] | [3. Product Development] | [4. Diversification] | [Capital Allocation Sequence]",
        "BCG Growth-Share Portfolio Matrix": "[METHODOLOGY FRAMEWORK: BCG PORTFOLIO & CAPITAL ALLOCATION MATRIX]\nAllocate capital and executive bandwidth across business units, products, or initiatives by Market Growth and Relative Market Share:\n\n1. CASH COWS (High Share / Mature Growth): Harvest free cashflow, automate operations, and avoid over-reinvestment.\n2. STARS (High Share / High Growth): Invest aggressively to lock in compounding category leadership.\n3. QUESTION MARKS (Low Share / High Growth): Make a binary call—fund decisively to reach Star velocity or exit cleanly.\n4. PETS / DOGS (Low Share / Low Growth): Divest, sunset, or put on zero-overhead maintenance to free trapped capital.\n\nOUTPUT FORMAT:\n### Portfolio Classification | ### Cashflow Reallocation Loop | ### Explicit Invest / Harvest / Sunset Decisions",
        "VRIO Competitive Advantage Framework": "[METHODOLOGY FRAMEWORK: BARNEY VRIO MOAT AUDIT]\nStress-test core assets, proprietary data, technology, and distribution for durable competitive advantage:\n\n1. VALUABLE: Does the capability directly expand willingness-to-pay or structurally lower unit costs?\n2. RARE: How few competitors possess or can access an equivalent asset?\n3. INIMITABLE: Do network effects, switching costs, proprietary data flywheels, patents, or regulatory licenses make replication prohibitively costly or slow?\n4. ORGANIZED: Are governance, incentives, and GTM execution wired to capture the full economic value?\n\nVERDICT SCALE: Competitive Disadvantage -> Competitive Parity -> Temporary Advantage -> Sustained Moat.\n\nOUTPUT FORMAT:\nMarkdown VRIO Audit Table per Asset + ### Moat Deepening Roadmap",
    },
    "5. Cognitive Debiasing & Critical Thinking": {
        "Ladder of Inference (Chris Argyris)": "[METHODOLOGY FRAMEWORK: ARGYRIS LADDER OF INFERENCE]\nAudit reasoning step-by-step from raw observable facts up to executive action to eliminate premature leaps and confirmation bias:\n\n1. OBSERVABLE RAW DATA: What verifiable logs, numbers, text, or events actually exist?\n2. SELECTED DATA: Which subset of facts is being focused on—and what disconfirming data was filtered out?\n3. INTERPRETED MEANING: What cultural or contextual meaning is being attached to the selected facts?\n4. ASSUMPTIONS: What unstated premises are being applied?\n5. CONCLUSIONS: What causal or strategic deduction follows—and is it logically valid?\n6. ACTION: What concrete decision is justified once the lower rungs are verified?\n\nOUTPUT FORMAT:\nWalk up the rungs explicitly: [Rung 1: Raw Facts] -> [Rung 2: Filtered Signals] -> [Rung 3: Assumptions] -> [Rung 4: Verified Action]",
        "Pre-Mortem Analysis (Gary Klein)": "[METHODOLOGY FRAMEWORK: PROSPECTIVE HINDSIGHT PRE-MORTEM]\nAssume as an established historical fact that 12 months from today this initiative has suffered a catastrophic failure. Work backward relentlessly:\n\n1. THE AUTOPSY HEADLINE: Describe the exact nature, magnitude, and trigger of the total failure.\n2. LETHAL FAILURE DRIVERS: Surface the hidden architectural flaws, wishful unit-economic assumptions, regulatory traps, key-person bottlenecks, and market shifts that killed it.\n3. PRE-EMPTIVE IMMUNIZATION: Re-architect the plan TODAY with concrete structural safeguards neutralizing each top failure mode before launch.\n\nOUTPUT FORMAT:\n[1. The Failure Autopsy] | [2. Ranked Causes of Death] | [3. Pre-Launch Structural Safeguards]",
        "Red Teaming & Adversarial Analysis": "[METHODOLOGY FRAMEWORK: ADVERSARIAL RED TEAMING]\nAdopt the mindset of a sophisticated competitor, hostile attacker, or skeptical regulator determined to break the proposed plan or system:\n\n1. ATTACK SURFACE & VULNERABILITIES: Pinpoint the weakest assumptions across security, legal exposure, unit economics, UX, and operational dependencies.\n2. EXPLOITATION SCENARIOS: Detail exactly how an adversary, market shock, or pathological edge case exploits those weaknesses for maximum damage.\n3. BLUE-TEAM ARCHITECTURAL HARDENING: Specify immediate structural changes that close each exploit vector permanently.\n\nOUTPUT FORMAT:\n### Attack Vectors | ### Adversarial Exploit Scenarios | ### Blue-Team Hardening Directives",
        "Six Thinking Hats (Edward de Bono)": "[METHODOLOGY FRAMEWORK: DE BONO SIX THINKING HATS]\nExamine the decision sequentially through 6 strictly separated cognitive lenses without muddling modes:\n\n1. WHITE HAT (Pure Facts & Missing Data): Verified metrics, hard facts, and explicit information gaps.\n2. RED HAT (Intuition & Stakeholder Sentiment): Gut friction, buyer/team trust reactions, reputational optics.\n3. BLACK HAT (Rigorous Caution): Downside risks, legal/financial exposure, failure modes, and constraints.\n4. YELLOW HAT (Constructive Upside): Best-case value creation, synergies, and asymmetric upside.\n5. GREEN HAT (Lateral Alternatives): Non-obvious creative workarounds and structural reframings.\n6. BLUE HAT (Executive Synthesis): Final decision rule, sequencing, and immediate next actions.\n\nOUTPUT FORMAT:\n⚪ White Hat | 🔴 Red Hat | 🖤 Black Hat | 🟡 Yellow Hat | 🟢 Green Hat | 🔵 Blue Hat Synthesis",
        "Game-Theoretic Mechanism Design": "[METHODOLOGY FRAMEWORK: GAME THEORY & INCENTIVE MECHANISM DESIGN]\nModel the problem as a multi-agent strategic game governed by payoffs, private information, and equilibrium incentives:\n\n1. PLAYERS & PAYOFF FUNCTIONS: Map every rational actor (buyers, vendors, competitors, regulators, employees/agents) and what each actually optimizes for.\n2. ASYMMETRIES & PERVERSE INCENTIVES: Diagnose Principal-Agent divergence, Moral Hazard, Adverse Selection, and Free-Rider traps.\n3. NASH EQUILIBRIUM PREDICTION: Predict the stable outcome if every actor plays their self-interested best response under current rules.\n4. INCENTIVE-COMPATIBLE MECHANISM: Redesign contracts, pricing tiers, SLAs, escrow/clawbacks, or auction rules so truth-telling and value alignment become the dominant strategy.\n\nOUTPUT FORMAT:\n### Players & Payoffs | ### Moral Hazard & Asymmetries | ### Baseline Nash Equilibrium | ### Incentive-Compatible Mechanism",
        "Bayesian Updating & Superforecasting (Tetlock)": "[METHODOLOGY FRAMEWORK: BAYESIAN PROBABILITY UPDATING & SUPERFORECASTING]\nReplace vague verbal words (\"likely\", \"promising\") with calibrated probabilities grounded in base rates and diagnostic evidence:\n\n1. OUTSIDE VIEW (Reference-Class Prior $P(H)$): What is the historical statistical base rate of success across comparable real-world initiatives?\n2. INSIDE VIEW (Diagnostic Likelihood Ratios): List specific positive and negative case-specific signals and how strongly each shifts the odds.\n3. CALIBRATED POSTERIOR ($P(H|E)$): State the updated probability explicitly with a 90% confidence interval.\n4. SIGNPOSTS & FALSIFICATION TRIGGERS: Define concrete 30/90-day observable milestones that would shift your posterior by $\\ge 20$ percentage points.\n\nOUTPUT FORMAT:\n[1. Base-Rate Prior %] | [2. Diagnostic Evidence (+/-)] | [3. Calibrated Posterior %] | [4. Signpost Triggers]",
        "Inversion Thinking (Charlie Munger / Jacobi)": "[METHODOLOGY FRAMEWORK: INVERSION THINKING (\"INVERT, ALWAYS INVERT\")]\nSolve hard problems both forward and backward: instead of asking only how to succeed brilliantly, first identify everything guaranteed to cause ruin and systematically remove it:\n\n1. FORWARD OBJECTIVE: Define the desired strategic outcome clearly.\n2. INVERTED ANTI-GOAL (Guaranteed Failure Blueprint): List the 5–7 decisions, habits, or architectural flaws that would guarantee catastrophic failure.\n3. HARD PREVENTION CONSTRAINTS: Engineer non-bypassable technical, contractual, or financial guardrails blocking every failure trigger.\n4. RESIDUAL ANTI-STUPIDITY STRATEGY: Articulate the durable, high-probability strategy that remains once unforced errors are eliminated.\n\nOUTPUT FORMAT:\n### 1. Forward Objective | ### 2. Blueprint for Guaranteed Ruin | ### 3. Hard Prevention Guardrails | ### 4. Durable Winning Strategy",
        "Steelmanning & Hegelian Dialectic": "[METHODOLOGY FRAMEWORK: STEELMANNING & DIALECTICAL SYNTHESIS]\nEliminate weak strawman debates and watered-down compromises by colliding opposing theses at maximum intellectual strength:\n\n1. THESIS (Strongest Case for Option A): Articulate Option A with its sharpest logic, best empirical evidence, and highest upside.\n2. STEELMAN ANTITHESIS (Strongest Possible Case for Option B): Construct the opposing argument NOT as a caricature, but in its most rigorous, persuasive, data-backed form.\n3. CRUX OF DISAGREEMENT: Pinpoint the exact empirical assumption, time horizon, or risk weight where Thesis and Antithesis diverge.\n4. HIGHER-ORDER SYNTHESIS: Architect a third structural design that resolves the crux while preserving the core strengths of both sides.\n\nOUTPUT FORMAT:\n[1. Thesis] | [2. Steelman Antithesis] | [3. Empirical Crux] | [4. Higher-Order Synthesis]",
    },
    "6. Systems Thinking & Complexity": {
        "Causal Loop Diagrams (System Dynamics)": "[METHODOLOGY FRAMEWORK: SYSTEM DYNAMICS & CAUSAL LOOP DIAGRAMS]\nMap endogenous feedback loops, stocks, flows, and time delays governing long-term system behavior:\n\n1. CORE STOCKS & VARIABLES: Define the accumulating stocks (capital, customers, tech debt, trust) and flow rates.\n2. REINFORCING LOOPS (R — Compounding Engines or Vicious Spirals): Trace self-amplifying feedback cycles (+/+ or -/-).\n3. BALANCING LOOPS (B — Stabilizers & Ceilings): Identify natural saturation limits, capacity ceilings, and corrective dampeners.\n4. SYSTEM DELAYS: Pinpoint latency between action and observable effect that triggers oscillation or overshoot.\n\nOUTPUT FORMAT:\n[Stocks & Variables] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Time Delays & Damping Plan]",
        "Iceberg Model (Systems Thinking)": "[METHODOLOGY FRAMEWORK: SYSTEMS THINKING ICEBERG MODEL]\nMove intervention depth from reactive firefighting at the surface down to structural root architecture:\n\n1. EVENTS (Visible Tip — Reactive): What acute incident or metric spike just occurred?\n2. PATTERNS & TRENDS (Historical Trajectory — Adaptive): What recurring trend or cycle appears over weeks/quarters?\n3. UNDERLYING STRUCTURES (Rules & Architecture — Generative): What incentives, schemas, bottlenecks, and SOPs physically produce that pattern?\n4. MENTAL MODELS (Bedrock Beliefs — Transformative): What unspoken assumptions or governance beliefs keep the flawed structure in place?\n\nOUTPUT FORMAT:\n[1. Surface Event] -> [2. Recurring Pattern] -> [3. Generating Structure] -> [4. Bedrock Mental Model Shift]",
        "Second-Order Thinking (Howard Marks)": "[METHODOLOGY FRAMEWORK: SECOND- & THIRD-ORDER CONSEQUENCE ANALYSIS]\nTrace cascading consequences beyond the obvious immediate effect (\"And then what?\"):\n\n1. FIRST-ORDER EFFECTS (Immediate & Obvious — 0 to 30 Days):\n- What is the direct, intended outcome everyone sees immediately?\n\n2. SECOND-ORDER EFFECTS (Behavioral & Systemic Ripples — 1 to 6 Months):\n- How do competitors, customers, regulators, or internal teams adapt in response to the first-order change? What unintended side effects emerge?\n\n3. THIRD-ORDER EQUILIBRIUM (Long-Term Structural Shift — 6 to 36 Months):\n- What is the net long-run impact on margins, defensibility, and system complexity?\n\nOUTPUT FORMAT:\n[1st-Order Direct Effect] | [2nd-Order Adaptive Ripples] | [3rd-Order Long-Term Equilibrium & Decision]",
        "Wardley Mapping (Simon Wardley)": "[METHODOLOGY FRAMEWORK: WARDLEY VALUE-CHAIN & EVOLUTION MAPPING]\nMap system components along User Visibility (Y-axis) and Commodity Evolution (X-axis) to guide strategic resource allocation:\n\n1. ANCHOR USER NEED: Define the sovereign user/customer and their top-level need at the top of the value chain.\n2. DEPENDENCY VALUE CHAIN: Trace component dependencies from visible user experience down to invisible infrastructure.\n3. EVOLUTION STAGE PER COMPONENT:\n   - I. Genesis (Novel, uncertain, experimental)\n   - II. Custom-Built (Bespoke competitive differentiation)\n   - III. Product / Rental (Standardized commercial/open-source software)\n   - IV. Commodity / Utility (Standardized API, cloud/power utility)\n4. STRATEGIC DOCTRINE MOVES: Stop custom-building Stage-III/IV commodities; focus bespoke engineering exclusively on Stage-I/II differentiators.\n\nOUTPUT FORMAT:\n### User Anchor & Value Chain | ### Component Evolution Map (I–IV) | ### Strategic Build/Consume Moves",
        "Donella Meadows 12 Leverage Points": "[METHODOLOGY FRAMEWORK: DONELLA MEADOWS SYSTEM LEVERAGE HIERARCHY]\nAvoid burning resources on low-leverage parameter tweaks by targeting high-leverage structural intervention points:\n\n1. LOW LEVERAGE (Parameters, Subsidies & Buffers): Merely tuning numbers, budgets, headcount, or queue sizes within a broken loop.\n2. MEDIUM LEVERAGE (Information Flows & Feedback Delays): Exposing real-time consequences directly to decision-makers and tightening feedback loops.\n3. HIGH LEVERAGE (Rules, Incentives & Self-Organization): Changing system constraints, permissions, ownership rules, and reward functions.\n4. MAXIMUM LEVERAGE (Overarching System Goal & Paradigm): Redefining the objective function the entire system optimizes for.\n\nOUTPUT FORMAT:\n### Low-Leverage Traps to Avoid | ### Information & Feedback Fixes | ### Rule & Incentive Redesign | ### Top-Level System Goal",
        "Viable System Model (VSM / Stafford Beer)": "[METHODOLOGY FRAMEWORK: STAFFORD BEER CYBERNETIC VIABLE SYSTEM MODEL (VSM)]\nDiagnose organizational or multi-agent architecture across the 5 cybernetic subsystems required for autonomous viability:\n\n1. SYSTEM 1 (Autonomous Operations): Value-producing operational units and their required local autonomy.\n2. SYSTEM 2 (Anti-Oscillation Coordination): Shared schemas, scheduling protocols, and conflict damping across units.\n3. SYSTEM 3 & 3* (Operational Delivery & Sporadic Audit): Resource bargaining, internal synergy, and direct ground-truth spot audits.\n4. SYSTEM 4 (Strategic Intelligence & Outside/Future Radar): Environmental scanning, R&D, and adaptation to external shifts.\n5. SYSTEM 5 (Policy, Identity & Homeostasis): Executive arbitration balancing present exploitation (S3) against future exploration (S4).\n\nOUTPUT FORMAT:\n[System 1: Operations] | [System 2: Coordination] | [System 3/3*: Control & Audit] | [System 4: Foresight] | [System 5: Governance Balance]",
    },
    "7. Foresight, Risk & Resilience": {
        "Antifragility Analysis (Nassim Nicholas Taleb)": "[METHODOLOGY FRAMEWORK: TALEB FRAGILE–ROBUST–ANTIFRAGILE TRIAD]\nAudit and re-architect exposure to volatility, shocks, tail events, and randomness:\n\n1. FRAGILE EXPOSURES (Concave Payoffs — Harmed by Volatility): Identify hidden leverage, tight coupling, single points of failure, and uncapped downside.\n2. ROBUST BASELINE (Insensitive to Shocks): Establish cash/capacity buffers, redundancy, and strict fault isolation.\n3. ANTIFRAGILE DESIGN (Convex Payoffs — Gains from Disorder): Apply a **Barbell Strategy** (90% ultra-safe downside floor + 10% capped-loss, uncapped-upside optionality) and automated post-error learning loops.\n\nOUTPUT FORMAT:\n### Fragile Tail Exposures | ### Robustness Buffers | ### Antifragile Barbell & Optionality Design",
        "FMEA (Failure Mode and Effects Analysis)": "[METHODOLOGY FRAMEWORK: QUANTITATIVE FMEA RISK SCORING]\nQuantify and prioritize technical, legal, or operational failure modes using Risk Priority Numbers ($\\text{RPN} = S \\times O \\times D$):\n\n1. FAILURE MODE & EFFECT: Exact way each component/process step can fail and its downstream impact.\n2. SEVERITY ($S$: 1–10): Magnitude of customer, financial, safety, or regulatory harm (10 = catastrophic).\n3. OCCURRENCE ($O$: 1–10): Likelihood/frequency of the failure occurring under real load.\n4. DETECTION ($D$: 1–10): Inability of current controls to catch the fault before impact (10 = silent/undetected!).\n5. RPN MITIGATION: Every item with $\\text{RPN} > 100$ or $S \\ge 9$ mandates an immediate engineering control with re-scored target RPN.\n\nOUTPUT FORMAT:\nMarkdown Table: `Component | Failure Mode | S | O | D | RPN | Mandatory Control | Post-Fix RPN`",
        "OODA Loop (John Boyd)": "[METHODOLOGY FRAMEWORK: BOYD HIGH-TEMPO OODA LOOP]\nOutpace rapidly evolving operational or competitive environments by cycling faster and more accurately through Observe–Orient–Decide–Act:\n\n1. OBSERVE: Ingest raw real-time telemetry, market signals, logs, and adversary moves without filter lag.\n2. ORIENT (The Decisive Center): Synthesize signals against mental models, strip away outdated priors, and isolate the true mismatch.\n3. DECIDE: Commit rapidly to a clear, testable hypothesis—avoiding analysis paralysis.\n4. ACT: Execute decisively and wire immediate outcome telemetry straight back into Observation.\n\nOUTPUT FORMAT:\n[Observe: Live Signals] -> [Orient: Reframed Reality] -> [Decide: Chosen Hypothesis] -> [Act: Immediate Execution & Telemetry]",
        "Scenario Planning (Shell Matrix Method)": "[METHODOLOGY FRAMEWORK: SCENARIO PLANNING & NO-REGRET STRATEGY]\nStress-test long-term strategy across divergent, plausible future worlds driven by the 2 highest-impact, highest-uncertainty macro axes:\n\n1. SCENARIO A — ACCELERATED TAILWIND (High Growth / Favorable Regulation & Tech)\n2. SCENARIO B — STAGFLATION & FRICTION (Capital Scarcity / Cost Compression / Tightening Constraints)\n3. SCENARIO C — STRUCTURAL DISRUPTION (Paradigm Shift / Regulatory or Technological Regime Change)\n4. ROBUST PORTFOLIO: Separate **No-Regret Moves** (winning across ALL 3 scenarios) from **Contingent Options** triggered by early-warning signposts.\n\nOUTPUT FORMAT:\n[Scenario A] | [Scenario B] | [Scenario C] | [No-Regret Core Moves & Early-Warning Signposts]",
        "Monte Carlo & Expected Value Decision Tree": "[METHODOLOGY FRAMEWORK: MONTE CARLO RANGES & EXPECTED-VALUE DECISION TREE]\nEliminate point-estimate illusions by evaluating uncertain commitments across probability distributions, expected value, and ruin thresholds:\n\n1. UNCERTAINTY DISTRIBUTIONS: Define P10 (Bear), P50 (Base), and P90 (Bull) ranges for the 3–5 primary value drivers.\n2. DECISION TREE & EXPECTED VALUE ($EV$):\n   - Calculate $EV = \\sum p_i \\cdot \\text{Net Payoff}_i$ across each strategic branch including option value of staged abandonment.\n3. TAIL-RISK & RUIN CHECK (Ergo-Safety / Kelly Discipline): Verify the bottom 5% tail outcome—never accept positive EV if the left tail breaches solvency or irreversible compliance limits.\n4. STAGED TRANCHING: Structure milestone gates buying maximum information at minimum upfront capital commitment.\n\nOUTPUT FORMAT:\n### Driver Distributions (P10/P50/P90) | ### Expected-Value Tree | ### Left-Tail Solvency Check | ### Tranched Commitment Plan",
        "Swiss Cheese Model (James Reason / Defense-in-Depth)": "[METHODOLOGY FRAMEWORK: REASON SWISS CHEESE & DEFENSE-IN-DEPTH]\nArchitect independent, orthogonal defensive layers so no single human error, model hallucination, or component fault can propagate to catastrophic loss:\n\n1. HAZARD & UNACCEPTABLE LOSS: Specify the exact high-severity incident to block (security breach, erroneous wire/trade, production outage, compliance breach).\n2. FOUR ORTHOGONAL DEFENSE LAYERS (Slices):\n   - Layer 1 (Intrinsic Prevention / Poka-Yoke): Schema/type constraints making invalid states unrepresentable.\n   - Layer 2 (Automated Gatekeeping): RBAC permissions, pre-flight validation, dual-control HITL approvals.\n   - Layer 3 (Runtime Detection & Circuit Breakers): Anomaly telemetry, rate limits, automated halt thresholds.\n   - Layer 4 (Blast-Radius Containment & Recovery): Sandboxing, atomic rollbacks, immutable offline backups.\n3. COMMON-MODE ELIMINATION: Audit and eliminate shared dependencies that could align holes across multiple layers simultaneously.\n\nOUTPUT FORMAT:\n### Target Hazard | ### Layers 1–4 & Latent Holes | ### Common-Mode Decoupling & Hardening Plan",
    },
}

import copy
DEFAULT_CATEGORIZED_FRAMEWORKS = copy.deepcopy(CATEGORIZED_FRAMEWORKS)
DEFAULT_CATEGORIZED_FRAMEWORKS_EN = copy.deepcopy(CATEGORIZED_FRAMEWORKS_EN)

def get_flat_framework_map(lang: str = "de") -> dict:
    flat = {}
    sources = (
        [CATEGORIZED_FRAMEWORKS, CATEGORIZED_FRAMEWORKS_EN]
        if not str(lang or "").lower().startswith("en")
        else [CATEGORIZED_FRAMEWORKS_EN, CATEGORIZED_FRAMEWORKS]
    )
    # Load secondary first, primary second so primary wins on identical keys
    for src in reversed(sources):
        for cat, frameworks in src.items():
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

UNIVERSAL_METHODOLOGY_HEADER_EN = """[UNIVERSAL METHODOLOGY ENGINE HEADER]
You are an uncompromising principal analyst within Archon OS.
Your mandate is to dissect the problem statement strictly through the lens of the assigned methodology framework.

STRICT RULES:
1. Zero introductions, zero pleasantries, zero "Here is the analysis".
2. Reason step-by-step before formulating conclusions.
3. Skip NO phase of the framework. Every section must be rigorously substantiated.
4. Be concrete: provide numbers, formulas, code snippets, specific risks, and unambiguous decisions rather than vague advice.
5. Adhere strictly to the specified OUTPUT FORMAT.
========================================"""

def _is_english_framework(name: str) -> bool:
    for fws in CATEGORIZED_FRAMEWORKS_EN.values():
        if name in fws:
            # Check if it's uniquely in EN or contains METHODOLOGY FRAMEWORK
            val = fws[name]
            if isinstance(val, str) and "[METHODOLOGY FRAMEWORK:" in val:
                for de_fws in CATEGORIZED_FRAMEWORKS.values():
                    if name in de_fws:
                        return False
                return True
    return False

def get_framework_info(name: str, lang: str = "") -> dict:
    eff_lang = (lang or os.environ.get("ARCHON_LANGUAGE") or "").strip().lower()
    flat = get_flat_framework_map(lang="en" if eff_lang.startswith("en") else "de")
    if name in flat:
        return flat[name]
    if eff_lang.startswith("en"):
        return {
            "summary": "Conduct a structured, multi-perspective executive debate grounded in verifiable evidence, explicit trade-offs, and actionable synthesis.",
            "system_instruction": "Conduct a structured, multi-perspective executive debate grounded in verifiable evidence, explicit trade-offs, and actionable synthesis.",
        }
    return flat.get("Steffi Kieffer Boardroom", {
        "summary": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion.",
        "system_instruction": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion."
    })

def build_final_system_prompt(selected_framework_id: str, base_system_prompt: str = "", lang: str = "") -> str:
    """
    Compiles the final Boardroom system prompt from:
    1. UNIVERSAL_METHODOLOGY_HEADER (DE or EN)
    2. Selected framework methodology instruction
    3. Optional specialist base system prompt
    """
    eff_lang = (lang or os.environ.get("ARCHON_LANGUAGE") or "").strip().lower()
    use_en = eff_lang.startswith("en") or _is_english_framework(selected_framework_id)
    fw_info = get_framework_info(selected_framework_id, lang="en" if use_en else "de")
    fw_instruction = fw_info.get("system_instruction", "") if fw_info else ""

    header = UNIVERSAL_METHODOLOGY_HEADER_EN if use_en else UNIVERSAL_METHODOLOGY_HEADER
    parts = [header.strip()]
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
