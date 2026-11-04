import os
import re
import time
import logging
import asyncio
import json
import httpx
from typing import Dict, Any, List, AsyncGenerator
from datetime import datetime

logger = logging.getLogger("agent_router")

OPENROUTER_FALLBACK_CHAIN = [
    "deepseek/deepseek-chat",
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini"
]

class RoutePolicy:
    def __init__(self, requires_high_reasoning: bool = False, max_cost_per_1k: float = 1.0, data_residency_local_only: bool = False):
        self.requires_high_reasoning = requires_high_reasoning
        self.max_cost_per_1k = max_cost_per_1k
        self.data_residency_local_only = data_residency_local_only

class AgentRouter:
    """
    Hardware Abstraction Layer (HAL) for LLM routing.
    Routes tasks dynamically, enforces Token Guard budgets, and provides automatic provider fallback.
    """
    
    def __init__(self):
        self.active_tasks: Dict[str, Any] = {}
        self._guardian_cache: Dict[str, Any] = {"ts": 0.0, "daily_budget": 2.0, "max_context_tokens": 32000}
        self._http_clients: Dict[int, httpx.AsyncClient] = {}

    def _get_shared_client(self) -> httpx.AsyncClient:
        loop_id = id(asyncio.get_running_loop())
        client = self._http_clients.get(loop_id)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                timeout=90.0,
                limits=httpx.Limits(max_keepalive_connections=25, max_connections=100)
            )
            self._http_clients[loop_id] = client
        return client

    def _get_guardian_policy(self) -> Dict[str, Any]:
        now = time.time()
        if now - self._guardian_cache.get("ts", 0.0) < 15.0:
            return self._guardian_cache

        daily_budget = 2.0
        max_context_tokens = 32000
        try:
            cost_file = os.path.expanduser("~/.hermes/cost-budget.json")
            if not os.path.exists(cost_file):
                cost_file = "/opt/data/cost-budget.json"
            if os.path.exists(cost_file):
                with open(cost_file, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                    daily_budget = float(bdata.get("daily_budget", 2.0))
        except Exception:
            pass

        try:
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            limits_file = os.path.join(workspace_dir, "memory", "guardian_limits.json")
            if os.path.exists(limits_file):
                with open(limits_file, "r", encoding="utf-8") as f:
                    ldata = json.load(f)
                    max_context_tokens = int(ldata.get("max_context_tokens", 32000))
        except Exception:
            pass

        current_spend = 0.0
        try:
            import sys
            main_mod = sys.modules.get("main")
            if main_mod and hasattr(main_mod, "_GUARDIAN_STATS_CACHE"):
                cache_24h = main_mod._GUARDIAN_STATS_CACHE.get("24h") or main_mod._GUARDIAN_STATS_CACHE.get("all")
                if cache_24h and isinstance(cache_24h.get("data"), dict):
                    current_spend = float(cache_24h["data"].get("grand_total_cost", 0.0))
        except Exception:
            pass

        cb_cfg = {}
        try:
            from backend.autonomy_settings import get_module_config
            cb_cfg = get_module_config("circuit_breaker")
        except Exception:
            pass

        self._guardian_cache = {
            "ts": now,
            "daily_budget": daily_budget,
            "current_spend": current_spend,
            "max_context_tokens": max_context_tokens,
            "loop_detection_enabled": bool(cb_cfg.get("loop_detection_enabled", True)),
            "max_identical_turns": int(cb_cfg.get("max_identical_turns", 3)),
            "jaccard_similarity_threshold": float(cb_cfg.get("jaccard_similarity_threshold", 0.90)),
            "max_steps_per_task": int(cb_cfg.get("max_steps_per_task", 15)),
            "budget_downgrade_threshold_pct": int(cb_cfg.get("budget_downgrade_threshold_pct", 80)),
            "token_clipper_enabled": bool(cb_cfg.get("token_clipper_enabled", True))
        }
        return self._guardian_cache

    def _compress_conversation_window(self, messages: List[Dict], max_ctx_chars: int) -> List[Dict]:
        """
        Sliding Window Memory Compression (Pillar 4 / Transient Context Compression):
        Verhindert Datenverlust bei langen Sessions (> max_context_tokens).
        Extrahiert Beschlüsse, Rollen-Aussagen und Kontext aus überlaufenden Nachrichten
        und bindet sie als kompakte Zusammenfassung dauerhaft oben im Prompt ein.
        """
        if len(messages) <= 3:
            return messages

        sys_msg = messages[0]
        recent_count = max(3, min(8, len(messages) // 3))
        recent_msgs = messages[-recent_count:]
        older_msgs = messages[1:-recent_count]

        if not older_msgs:
            return messages

        summary_lines = []
        for m in older_msgs:
            role = str(m.get("role", "unknown")).upper()
            content = str(m.get("content", "")).strip()
            if not content:
                continue
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            preview = lines[0] if lines else content[:120]
            if len(preview) > 160:
                preview = preview[:160] + "..."
            summary_lines.append(f"- [{role}]: {preview}")

        compact_text = (
            "### [KONSOLIDIERTER GESPRÄCHS- & ENTSCHEIDUNGSKONTEXT (AUTOMATISCH KOMPRIMIERT)]:\n"
            + "\n".join(summary_lines[-15:])
        )

        compact_msg = {
            "role": "system",
            "content": compact_text
        }

        compressed = [sys_msg, compact_msg] + recent_msgs
        total_len = sum(len(str(m.get("content", ""))) for m in compressed)
        if total_len > max_ctx_chars:
            trimmed = [sys_msg, compact_msg]
            acc = len(str(sys_msg.get("content", ""))) + len(compact_text)
            for m in reversed(recent_msgs):
                m_len = len(str(m.get("content", "")))
                if acc + m_len <= max_ctx_chars or len(trimmed) < 3:
                    trimmed.insert(2, m)
                    acc += m_len
                else:
                    break
            compressed = trimmed

        return compressed


    def check_loop_or_circuit_breaker(self, messages: List[Dict], max_identical_turns: int = 3) -> Dict[str, Any]:
        """
        Pillar 1 & 6: Loop-Detection & Runaway Circuit-Breaker
        Verhindert unendliche Argumentations- oder Tool-Schleifen.
        Prüft:
        1. Identische/wiederholte Modell-Antworten oder Tool-Aufrufe
        2. Ping-Pong-Muster zwischen Agenten
        3. Überschreitung des max_steps Limits
        """
        policy = self._get_guardian_policy()
        loop_enabled = policy.get("loop_detection_enabled", True)
        if not loop_enabled:
            return {"loop_detected": False, "tripped": False}

        max_identical_turns = int(policy.get("max_identical_turns", max_identical_turns))
        jaccard_thresh = float(policy.get("jaccard_similarity_threshold", 0.90))

        if len(messages) < max_identical_turns * 2:
            return {"loop_detected": False, "tripped": False}

        # 1. Prüfe die letzten N Antworten der Assistenz/Agenten
        assistant_contents = []
        for m in reversed(messages):
            if m.get("role") in ("assistant", "agent"):
                c = str(m.get("content", "")).strip()
                if c:
                    assistant_contents.append(c)
                if len(assistant_contents) >= max_identical_turns + 1:
                    break

        if len(assistant_contents) >= max_identical_turns:
            # Exakte Wiederholung der letzten N Turns
            first = assistant_contents[0]
            if all(first == other for other in assistant_contents[1:max_identical_turns]):
                logger.error(f"[CircuitBreaker] Endlosschleife erkannt! {max_identical_turns} identische Ausgaben.")
                return {
                    "loop_detected": True,
                    "tripped": True,
                    "reason": f"Endlosschleife: Agent wiederholt exakt dieselbe Ausgabe ({max_identical_turns}-mal)."
                }

            # Semantische Wiederholung / Ping-Pong (Token-Jaccard-Ähnlichkeit > 90%)
            def _tokens(txt):
                return set(re.findall(r'\w+', txt.lower()))

            t0 = _tokens(assistant_contents[0])
            t1 = _tokens(assistant_contents[1])
            if t0 and t1:
                overlap = len(t0 & t1) / len(t0 | t1)
                if overlap > jaccard_thresh and len(t0) > 10:
                    logger.warning(f"[CircuitBreaker] Hohe semantische Redundanz ({overlap*100:.1f}%) zwischen den letzten Runden.")
                    if len(assistant_contents) > 2:
                        t2 = _tokens(assistant_contents[2])
                        if t2 and (len(t0 & t2) / len(t0 | t2) >= jaccard_thresh):
                            logger.error("[CircuitBreaker] Zirkulärer Argumentations-Kreis erkannt. Circuit Breaker ausgelöst.")
                            return {
                                "loop_detected": True,
                                "tripped": True,
                                "reason": f"Zirkuläre Konversation erkannt (Ähnlichkeit > 90% über {max_identical_turns} Runden)."
                            }

        # 2. Schrittgrenzen-Prüfung (max_steps_per_task)
        max_steps = int(policy.get("max_steps_per_task", 15))
        if len(messages) > max_steps * 2:
            logger.error(f"[CircuitBreaker] Maximale Schrittanzahl ({max_steps}) für Task überschritten.")
            return {
                "loop_detected": True,
                "tripped": True,
                "reason": f"Task-Limit erreicht: {len(messages)//2} Interaktionsschritte überschreiten max_steps ({max_steps})."
            }

        return {"loop_detected": False, "tripped": False}

    def _enforce_token_guard(self, messages: List[Dict], provider: str, model: str, reasoning_level: str) -> tuple:
        policy = self._get_guardian_policy()
        # 0. Loop-Detection & Circuit-Breaker Prüfung
        cb_res = self.check_loop_or_circuit_breaker(messages)
        if cb_res.get("tripped"):
            logger.critical(f"[AgentRouter] CIRCUIT BREAKER AUSGELÖST: {cb_res.get('reason')}")
            messages = [
                messages[0],
                {"role": "system", "content": f"### [SYSTEM-NOTFALLSTOPP / CIRCUIT BREAKER]:\n{cb_res.get('reason')}\nBreche Ausführung sicher ab und fordere alternative Benutzeranweisung an."}
            ]

        daily_budget = policy.get("daily_budget", 2.0)
        current_spend = policy.get("current_spend", 0.0)
        max_ctx_chars = max(8000, int(policy.get("max_context_tokens", 32000)) * 4)

        # 1. Context-Window Cap mit intelligenter Rolling Summarization (Sliding Window Memory Compression)
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        if total_chars > max_ctx_chars and len(messages) > 3:
            messages = self._compress_conversation_window(messages, max_ctx_chars)
        elif total_chars > max_ctx_chars and len(messages) > 2:
            trimmed = [messages[0]]
            acc = len(str(messages[0].get("content", "")))
            for m in reversed(messages[1:]):
                m_len = len(str(m.get("content", "")))
                if acc + m_len <= max_ctx_chars or len(trimmed) < 2:
                    trimmed.insert(1, m)
                    acc += m_len
                else:
                    break
            messages = trimmed

        # 2. Budget-Stufenprüfung (80% Drosselung, 100% Spar-Fallback)
        if daily_budget > 0 and current_spend > 0:
            ratio = current_spend / daily_budget
            if ratio >= 1.0:
                if reasoning_level not in ("off", "none"):
                    logger.warning(f"[TokenGuard] Tagesbudget erreicht (${current_spend:.2f}/${daily_budget:.2f}). Reasoning deaktiviert.")
                    reasoning_level = "off"
                if provider == "openrouter" and any(expensive in model.lower() for expensive in ("opus", "sonnet", "gpt-4o", "o1", "o3", "pro")):
                    logger.warning(f"[TokenGuard] Budget-Limit überschritten: Wechsel von {model} auf deepseek/deepseek-chat.")
                    model = "deepseek/deepseek-chat"
            elif ratio >= 0.8:
                if reasoning_level in ("max", "deep", "high", "medium"):
                    logger.info(f"[TokenGuard] Budget bei {ratio*100:.0f}%: Drossele Reasoning von '{reasoning_level}' auf 'low'.")
                    reasoning_level = "low"

        return messages, model, reasoning_level

    def _build_request_payload(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str], stream: bool = False, max_tokens: int = 4096, reasoning_level: str = "medium") -> tuple:
        target_url = "http://omniroute:20128/v1/chat/completions"
        request_headers = {"Content-Type": "application/json"}
        
        provider = provider.lower().strip()
        lvl = (reasoning_level or "medium").lower().strip()
        effort_map = {
            "off": "none",
            "none": "none",
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "max": "high",
            "deep": "high"
        }
        tokens_map = {
            "off": 0,
            "none": 0,
            "minimal": 1024,
            "low": 2048,
            "medium": 4096,
            "high": 8192,
            "max": 16384,
            "deep": 16384
        }
        or_effort = effort_map.get(lvl, "medium")
        or_tokens = tokens_map.get(lvl, 4096)
        
        if provider == "google":
            target_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            g_key = api_keys.get("GEMINI_API_KEY") or api_keys.get("GOOGLE_API_KEY") or ""
            if not g_key:
                raise ValueError("Kein Google / Gemini API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {g_key}"

        elif provider == "openrouter":
            target_url = "https://openrouter.ai/api/v1/chat/completions"
            or_key = api_keys.get("OPENROUTER_API_KEY") or ""
            if not or_key:
                raise ValueError("Kein OpenRouter API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {or_key}"
            request_headers["HTTP-Referer"] = "http://localhost:8501"
            request_headers["X-Title"] = "Archon OS"

        elif provider == "groq":
            target_url = "https://api.groq.com/openai/v1/chat/completions"
            groq_key = api_keys.get("GROQ_API_KEY") or ""
            if not groq_key:
                raise ValueError("Kein Groq API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {groq_key}"

        elif provider == "openai":
            target_url = "https://api.openai.com/v1/chat/completions"
            oa_key = api_keys.get("OPENAI_API_KEY") or ""
            if not oa_key:
                raise ValueError("Kein OpenAI API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {oa_key}"

        elif provider == "nvidia":
            target_url = "https://integrate.api.nvidia.com/v1/chat/completions"
            nv_key = api_keys.get("NVIDIA_API_KEY") or ""
            if not nv_key:
                raise ValueError("Kein NVIDIA NIM API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {nv_key}"

        elif provider == "anthropic":
            target_url = "https://api.anthropic.com/v1/messages"
            ant_key = api_keys.get("ANTHROPIC_API_KEY") or ""
            if not ant_key:
                raise ValueError("Kein Anthropic API-Key gefunden.")
            request_headers["x-api-key"] = ant_key
            request_headers["anthropic-version"] = "2023-06-01"

        elif provider == "local":
            try:
                from backend.privacy_router import get_privacy_config
                cfg = get_privacy_config()
                raw_url = cfg.get("local_llm_url", "http://127.0.0.1:11434/v1").rstrip("/")
            except Exception:
                raw_url = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:11434/v1").rstrip("/")
            target_url = f"{raw_url}/chat/completions"
            omni_key = api_keys.get("LOCAL_LLM_KEY") or ""
            if omni_key:
                request_headers["Authorization"] = f"Bearer {omni_key}"

        elif provider == "mistral":
            target_url = "https://api.mistral.ai/v1/chat/completions"
            m_key = api_keys.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY", "")
            if not m_key:
                try:
                    from backend.privacy_router import get_privacy_config
                    m_key = get_privacy_config().get("mistral_api_key", "")
                except Exception:
                    pass
            if not m_key:
                raise ValueError("Kein Mistral API-Key hinterlegt.")
            request_headers["Authorization"] = f"Bearer {m_key}"

        else:
            target_url = "http://omniroute:20128/v1/chat/completions"
            omni_key = api_keys.get("OMNIROUTE_API_KEY") or ""
            if omni_key:
                request_headers["Authorization"] = f"Bearer {omni_key}"

        client_payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": 0.6,
            "max_tokens": max_tokens
        }

        # Reasoning-Konfiguration
        if provider == "openrouter":
            if or_effort == "none" or or_tokens == 0:
                client_payload["reasoning"] = {"effort": "none"}
            elif model.lower().startswith("openai/o") or "/o1" in model.lower() or "/o3" in model.lower():
                client_payload["reasoning"] = {"effort": or_effort}
            else:
                client_payload["reasoning"] = {"max_tokens": or_tokens}
                if max_tokens <= or_tokens:
                    client_payload["max_tokens"] = or_tokens + 4096

        elif provider == "google":
            if lvl in ("off", "none"):
                client_payload["thinking_config"] = {"thinking_budget": 0}
            else:
                client_payload["thinking_config"] = {"thinking_budget": or_tokens}

        elif provider == "openai":
            if lvl in ("off", "none", "minimal", "low"):
                client_payload["reasoning_effort"] = "low"
            elif lvl == "medium":
                client_payload["reasoning_effort"] = "medium"
            else:
                client_payload["reasoning_effort"] = "high"
        
        if provider == "anthropic":
            sys_msg = [m["content"] for m in messages if m["role"] == "system"]
            user_msgs = [m for m in messages if m["role"] != "system"]
            client_payload = {
                "model": model,
                "messages": user_msgs,
                "stream": stream,
                "max_tokens": max_tokens
            }
            if sys_msg:
                client_payload["system"] = sys_msg[0]
            if lvl not in ("off", "none"):
                ant_budget = max(1024, or_tokens)
                client_payload["thinking"] = {"type": "enabled", "budget_tokens": ant_budget}
                if max_tokens <= ant_budget:
                    client_payload["max_tokens"] = ant_budget + 4096
                
        return target_url, request_headers, client_payload

    async def chat_completion(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str], max_tokens: int = 4096, reasoning_level: str = "medium") -> str:
        """
        Synchronous-style asynchronous chat completion via the HAL with Token Guard & Auto-Fallback.
        """
        messages, model, reasoning_level = self._enforce_token_guard(messages, provider, model, reasoning_level)
        prov_low = provider.lower().strip()
        candidate_models = [model]
        if prov_low == "openrouter":
            for fb in OPENROUTER_FALLBACK_CHAIN:
                if fb != model and fb not in candidate_models:
                    candidate_models.append(fb)

        last_err = None
        client = self._get_shared_client()
        if True:
            for idx, m_try in enumerate(candidate_models):
                try:
                    target_url, request_headers, client_payload = self._build_request_payload(
                        messages, provider, m_try, api_keys, stream=False, max_tokens=max_tokens, reasoning_level=reasoning_level
                    )
                    resp = await client.post(target_url, headers=request_headers, json=client_payload)
                    if resp.status_code in (429, 500, 502, 503, 504, 404) and idx < len(candidate_models) - 1:
                        logger.warning(f"[AgentRouter] Model '{m_try}' returned {resp.status_code}, falling back to '{candidate_models[idx+1]}'...")
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if prov_low == "anthropic":
                        return data.get("content", [{}])[0].get("text", "")
                    return data["choices"][0]["message"]["content"]
                except Exception as e:
                    last_err = e
                    if idx < len(candidate_models) - 1:
                        logger.warning(f"[AgentRouter] Call to '{m_try}' failed ({e}), trying fallback '{candidate_models[idx+1]}'...")
                        continue
                    raise last_err

    async def stream_chat_completion(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str], reasoning_level: str = "medium") -> AsyncGenerator[str, None]:
        """
        Stream chat completion via the HAL with Token Guard & Auto-Fallback.
        """
        messages, model, reasoning_level = self._enforce_token_guard(messages, provider, model, reasoning_level)
        prov_low = provider.lower().strip()
        candidate_models = [model]
        if prov_low == "openrouter":
            for fb in OPENROUTER_FALLBACK_CHAIN:
                if fb != model and fb not in candidate_models:
                    candidate_models.append(fb)

        for idx, m_try in enumerate(candidate_models):
            try:
                target_url, request_headers, client_payload = self._build_request_payload(
                    messages, provider, m_try, api_keys, stream=True, reasoning_level=reasoning_level
                )
            except ValueError as ve:
                yield f"ERROR: {ve}"
                return

            try:
                client = self._get_shared_client()
                if True:
                    async with client.stream("POST", target_url, headers=request_headers, json=client_payload) as response:
                        if response.status_code != 200:
                            err_body = await response.aread()
                            if response.status_code in (429, 500, 502, 503, 504, 404) and idx < len(candidate_models) - 1:
                                logger.warning(f"[AgentRouter Stream] Model '{m_try}' returned {response.status_code}, falling back to '{candidate_models[idx+1]}'...")
                                continue
                            yield f"ERROR: {provider.capitalize()} Fehler (Status {response.status_code}): {err_body.decode('utf-8', errors='ignore')[:300]}"
                            return
                        else:
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(data_str)
                                        if prov_low == "anthropic":
                                            if chunk.get("type") == "content_block_delta":
                                                delta = chunk.get("delta", {})
                                                if delta.get("type") == "text_delta":
                                                    yield delta.get("text", "")
                                        else:
                                            choice = chunk.get("choices", [{}])[0]
                                            delta = choice.get("delta", {})
                                            content_piece = delta.get("content", "")
                                            if content_piece:
                                                yield content_piece
                                    except json.JSONDecodeError:
                                        pass
                            return
            except Exception as e:
                if idx < len(candidate_models) - 1:
                    logger.warning(f"[AgentRouter Stream] Error with '{m_try}' ({e}), falling back to '{candidate_models[idx+1]}'...")
                    continue
                logger.error(f"[AgentRouter] Stream error: {e}")
                yield f"ERROR: Verbindungsfehler zum LLM-Provider ({e})"
                return

    def suspend_task(self, task_id: str) -> bool:
        if task_id in self.active_tasks and self.active_tasks[task_id]["status"] == "in_progress":
            self.active_tasks[task_id]["status"] = "suspended"
            return True
        return False

# Global Singleton Router
router_instance = AgentRouter()


def check_task_budget(task_id: str, cost_usd: float, budget_usd: float = 0.25, task_title: str = "") -> dict:
    """
    Pillar 5 / TokenGuard: Prüft das Budget eines Tasks.
    Bei 100% Überschreitung wird der Task pausiert und eine Benachrichtigung per Telegram gesendet.
    """
    cost = float(cost_usd or 0.0)
    budget = float(budget_usd or 0.25)
    title = task_title or f"Task #{task_id}"

    if cost >= budget:
        try:
            import telegram_notify
            tg_text = (
                f"⚠️ *Archon OS Task-Budget Limit erreicht*\n"
                f"Aufgabe: *{title}*\n"
                f"Verbraucht: *${cost:.3f}* von *${budget:.3f}*\n\n"
                f"Der Task wurde pausiert. Bitte Budget im Dashboard freigeben oder erhöhen."
            )
            telegram_notify.send_telegram_message(tg_text)
        except Exception as e:
            print(f"[BudgetCheck] Telegram notice error: {e}")

        return {
            "status": "budget_exhausted",
            "task_id": task_id,
            "cost_usd": cost,
            "budget_usd": budget,
            "paused": True,
            "message": "Task-Budget erschöpft. Benachrichtigung an Telegram gesendet."
        }
    elif cost >= budget * 0.8:
        return {
            "status": "budget_warning",
            "task_id": task_id,
            "cost_usd": cost,
            "budget_usd": budget,
            "paused": False,
            "recommend_model": "deepseek/deepseek-chat"
        }
    return {"status": "ok", "task_id": task_id, "cost_usd": cost, "budget_usd": budget, "paused": False}
