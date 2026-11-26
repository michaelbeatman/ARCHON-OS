"""D5-Cluster 2: Reine Output-/Parsing- und Modell-Fallback-Helfer.

Ausgelagert aus ``core_dispatcher.py`` (INVARIANTS §3):
- ``clean_think_tags``
- ``parse_omniroute_response``
- ``_extract_tokens_usage``
- ``_OMNIROUTE_OPENROUTER_FALLBACK_MAP``
- ``_resolve_openrouter_fallback_model``

Keine mutable Globals in diesem Cluster; alle Symbole werden auf
``core_dispatcher.py`` als ``X as X`` re-exportiert, sodass bestehende
Monkeypatch-Ziele unveraendert greifen.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Tuple

from backend.llm_kernel import AUTO_MODEL_MAP

logger = logging.getLogger("core_dispatcher")

_OMNIROUTE_OPENROUTER_FALLBACK_MAP: Dict[str, str] = {
    **AUTO_MODEL_MAP,
    "omniroute/best-coding": "deepseek/deepseek-chat",
    "omniroute/best-reasoning": "deepseek/deepseek-r1",
    "omniroute/best-vision": "google/gemini-2.5-flash",
    "omniroute/best-fast": "openai/gpt-4o-mini",
    "omniroute/best-free": "google/gemini-2.5-flash",
    "omniroute/free-forever": "google/gemini-2.5-flash",
    "omniroute/deepseek-coder": "deepseek/deepseek-chat",
}


def clean_think_tags(text: str) -> str:
    """
    Entfernt sauber alle <think>...</think> Abschnitte (sowohl geschlossene als auch offene/abgeschnittene).
    """
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>[\s\S]*$", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def parse_omniroute_response(resp_text: Any) -> str:
    """
    Parst Antworten von OpenAI-kompatiblen APIs (Groq, OmniRoute).

    D12: Eine leere/ungueltige Antwort ist ein FEHLER, keine leere Erfolgs-
    antwort. Der Parser wirft ``RuntimeError``; die Provider-Hops muessen das
    mit ``error_code=EMPTY_OR_INVALID_RESPONSE`` eskalieren.
    """
    if not resp_text:
        raise RuntimeError("EMPTY_OR_INVALID_RESPONSE: leere Provider-Antwort")
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
    except Exception as exc:
        logger.debug(f"[Dispatcher] JSON-Antwort-Extraktion fehlgeschlagen: {exc}")

    # Server-Sent Events Parsing (data: {...})
    collected_content = []
    if isinstance(resp_text, str):
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
                except Exception as sse_exc:
                    logger.debug("[Dispatcher] SSE-Chunk nicht parsbar: %s", sse_exc)
                    continue

    if collected_content:
        return clean_think_tags("".join(collected_content))

    raise RuntimeError("EMPTY_OR_INVALID_RESPONSE: keine Nutzlast in Provider-Antwort")


def _extract_tokens_usage(resp_text: Any, prompt_str: str, reply_str: str) -> Tuple[int, int]:
    inp, out = max(50, len(prompt_str.split()) * 2), max(20, len(reply_str.split()) * 2)
    try:
        d = json.loads(resp_text) if isinstance(resp_text, str) else resp_text
        if isinstance(d, dict):
            u = d.get("usage", {})
            if isinstance(u, dict):
                inp = u.get("prompt_tokens") or u.get("input_tokens") or inp
                out = u.get("completion_tokens") or u.get("output_tokens") or out
    except (ValueError, TypeError, AttributeError) as exc:
        logger.debug(f"[Dispatcher] Token-Usage-Parsing fehlgeschlagen, nutze Schaetzung: {exc}")
    return int(inp), int(out)


def _resolve_openrouter_fallback_model(model: str) -> str:
    """Normalizes OmniRoute/auto model aliases to direct OpenRouter model IDs."""
    raw = (model or "").strip()
    low = raw.lower()
    if low in _OMNIROUTE_OPENROUTER_FALLBACK_MAP:
        return _OMNIROUTE_OPENROUTER_FALLBACK_MAP[low]
    if low.startswith("omniroute/"):
        stripped = raw.split("/", 1)[1].strip()
        if f"auto/{stripped}" in _OMNIROUTE_OPENROUTER_FALLBACK_MAP:
            return _OMNIROUTE_OPENROUTER_FALLBACK_MAP[f"auto/{stripped}"]
        if "/" in stripped:
            return stripped
        return "deepseek/deepseek-chat"
    if low.startswith("auto/") or raw in ("", "free-forever"):
        return "deepseek/deepseek-chat"
    return raw
