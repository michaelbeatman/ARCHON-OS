import logging
import asyncio
import json
import httpx
from typing import Dict, Any, List, AsyncGenerator
from datetime import datetime

logger = logging.getLogger("agent_router")

class RoutePolicy:
    def __init__(self, requires_high_reasoning: bool = False, max_cost_per_1k: float = 1.0, data_residency_local_only: bool = False):
        self.requires_high_reasoning = requires_high_reasoning
        self.max_cost_per_1k = max_cost_per_1k
        self.data_residency_local_only = data_residency_local_only

class AgentRouter:
    """
    Hardware Abstraction Layer (HAL) for LLM routing.
    Routes tasks dynamically and abstracts provider HTTP implementations.
    """
    
    def __init__(self):
        self.active_tasks: Dict[str, Any] = {}

    def _build_request_payload(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str], stream: bool = False, max_tokens: int = 4096) -> tuple:
        target_url = "http://omniroute:20128/v1/chat/completions"
        request_headers = {"Content-Type": "application/json"}
        
        provider = provider.lower().strip()
        
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
                
        return target_url, request_headers, client_payload

    async def chat_completion(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str], max_tokens: int = 4096) -> str:
        """
        Synchronous-style asynchronous chat completion via the HAL.
        """
        target_url, request_headers, client_payload = self._build_request_payload(messages, provider, model, api_keys, stream=False, max_tokens=max_tokens)
        
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(target_url, headers=request_headers, json=client_payload)
            resp.raise_for_status()
            data = resp.json()
            if provider.lower() == "anthropic":
                return data.get("content", [{}])[0].get("text", "")
            return data["choices"][0]["message"]["content"]

    async def stream_chat_completion(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str]) -> AsyncGenerator[str, None]:
        """
        Stream chat completion via the HAL.
        """
        try:
            target_url, request_headers, client_payload = self._build_request_payload(messages, provider, model, api_keys, stream=True)
        except ValueError as ve:
            yield f"ERROR: {ve}"
            return

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream("POST", target_url, headers=request_headers, json=client_payload) as response:
                    if response.status_code != 200:
                        err_body = await response.aread()
                        yield f"ERROR: {provider.capitalize()} Fehler (Status {response.status_code}): {err_body.decode('utf-8', errors='ignore')[:300]}"
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
                                    if provider.lower() == "anthropic":
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
        except Exception as e:
            logger.error(f"[AgentRouter] Stream error: {e}")
            yield f"ERROR: Verbindungsfehler zum LLM-Provider ({e})"

    def suspend_task(self, task_id: str) -> bool:
        if task_id in self.active_tasks and self.active_tasks[task_id]["status"] == "in_progress":
            self.active_tasks[task_id]["status"] = "suspended"
            return True
        return False

# Global Singleton Router
router_instance = AgentRouter()
