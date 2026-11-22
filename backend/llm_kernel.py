# -*- coding: utf-8 -*-
"""
backend/llm_kernel.py
=====================
Vereinheitlichter LLM-Kernel fuer Archon OS (Punkt 3.1.1):
- Gemeinsame kanonische AUTO_MODEL_MAP (genutzt von core_dispatcher & agent_router)
- Einheitliche Modell-Kostenschaetzung (inkl. $0.00 fuer Local/:free)
- Einheitliche Output-Post-Chain: PII-Rehydrierung (sauber dict["text"]),
  Secret-Masking und Output-Policy-Linter
- Zentraler Einstieg `dispatch_llm(...)` ueber den bestehenden Dispatcher/Router-Stack
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("archon.llm_kernel")

AUTO_MODEL_MAP: Dict[str, str] = {
    "auto/best-coding": "deepseek/deepseek-chat",
    "auto/best-reasoning": "deepseek/deepseek-r1",
    "auto/best-vision": "google/gemini-2.5-flash",
    "auto/best-fast": "openai/gpt-4o-mini",
    "auto/best-free": "google/gemini-2.5-flash",
    "auto/best-creative": "anthropic/claude-3.5-sonnet",
    "auto/best-chat": "deepseek/deepseek-chat",
    "auto/coding": "deepseek/deepseek-chat",
    "auto/reasoning": "deepseek/deepseek-r1",
    "auto/vision": "google/gemini-2.5-flash",
    "auto/claude-opus": "anthropic/claude-3-opus",
    "auto/claude-sonnet": "anthropic/claude-3.5-sonnet",
}

# Konservative USD-Preise pro 1M Tokens (Input, Output)
_FALLBACK_MODEL_PRICES_PER_1M: Dict[str, Tuple[float, float]] = {
    "deepseek/deepseek-chat": (0.27, 1.10),
    "deepseek/deepseek-r1": (0.55, 2.19),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "google/gemini-2.5-flash": (0.15, 0.60),
    "google/gemini-2.5-pro": (1.25, 10.00),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-opus": (15.00, 75.00),
}


def resolve_auto_model(model: Optional[str], default: str = "deepseek/deepseek-chat") -> str:
    raw = str(model or "").strip()
    if not raw or raw.lower() in ("free-forever", "default"):
        return default
    low = raw.lower()
    if low in AUTO_MODEL_MAP:
        return AUTO_MODEL_MAP[low]
    return raw


def estimate_model_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    provider: str = "",
) -> float:
    """Berechnet geschaetzte Kosten in USD ($0.00 fuer Local/Ollama und :free-Modelle)."""
    m_low = str(model or "").strip().lower()
    p_low = str(provider or "").strip().lower()
    if p_low in ("local", "ollama", "lmstudio", "vllm") or ":free" in m_low or m_low.endswith("/free"):
        return 0.0

    in_per_1m, out_per_1m = 0.30, 1.20
    try:
        # P0-8: backend.llm_prices existiert nicht — der ImportError wurde
        # verschluckt, weshalb immer die statische 8-Modell-Tabelle galt.
        from archon.routers.llm_providers import get_llm_prices
        prices = get_llm_prices()
        if isinstance(prices, dict) and model in prices:
            entry = prices[model]
            if isinstance(entry, dict):
                in_per_1m = float(entry.get("input", entry.get("prompt_per_1m", in_per_1m)) or in_per_1m)
                out_per_1m = float(entry.get("output", entry.get("completion_per_1m", out_per_1m)) or out_per_1m)
                return round((max(0, int(input_tokens)) / 1_000_000.0) * in_per_1m + (max(0, int(output_tokens)) / 1_000_000.0) * out_per_1m, 6)
    except Exception:
        pass

    for k, (pin, pout) in _FALLBACK_MODEL_PRICES_PER_1M.items():
        if k in m_low:
            in_per_1m, out_per_1m = pin, pout
            break
    return round((max(0, int(input_tokens)) / 1_000_000.0) * in_per_1m + (max(0, int(output_tokens)) / 1_000_000.0) * out_per_1m, 6)


def finalize_llm_output(
    text: Any,
    session_id: Optional[str] = None,
    is_local: bool = False,
) -> str:
    """Einheitliche Post-Chain: PII-Rehydrierung -> Secret-Masking -> Output-Policy-Linter."""
    s = str(text or "")
    if session_id and not is_local and s:
        try:
            from backend.pii_scrubber import pii_scrubber
            rehyd = pii_scrubber.rehydrate_text(s, str(session_id))
            if isinstance(rehyd, dict) and rehyd.get("text") is not None:
                s = str(rehyd["text"])
            elif isinstance(rehyd, str):
                s = rehyd
        except Exception as exc:
            logger.debug(f"[LLMKernel] PII-Rehydrierung fehlgeschlagen: {exc}")
    try:
        from backend.secret_masker import mask_sensitive_text
        s, _ = mask_sensitive_text(s)
    except Exception as exc:
        logger.warning(f"[LLMKernel] Secret-Masking fehlgeschlagen: {exc}")
    try:
        from backend.output_policy_linter import output_policy_linter
        linted = output_policy_linter.lint_and_clean(s)
        if isinstance(linted, dict) and linted.get("cleaned_text") is not None:
            s = str(linted["cleaned_text"])
    except Exception as exc:
        logger.warning(f"[LLMKernel] Output-Policy-Linter fehlgeschlagen: {exc}")
    return s


async def _otel_start(name: str, task_id: Optional[str], agent_id: str) -> Optional[str]:
    try:
        from backend.otel_tracer import tracer
        return await asyncio.to_thread(tracer.start_trace, name, task_id, agent_id)
    except Exception as exc:
        logger.debug("[LLMKernel] OTel-Trace-Start fehlgeschlagen: %s", exc)
        return None


async def _otel_span(trace_id: str, **kwargs: Any) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.record_span, trace_id, **kwargs)
    except Exception as exc:
        logger.debug("[LLMKernel] OTel-Span fehlgeschlagen: %s", exc)


async def _otel_end(trace_id: str, status: str) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.end_trace, trace_id, status)
    except Exception as exc:
        logger.debug("[LLMKernel] OTel-Trace-Ende fehlgeschlagen: %s", exc)


async def dispatch_llm(
    *,
    agent_id: str = "default",
    agent_name: str = "Agent",
    prompt: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    role: str = "",
    system_prompt: str = "",
    model: str = "auto/best-coding",
    provider: str = "",
    reasoning_level: str = "medium",
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    stream: bool = False,
) -> Any:
    """Einheitlicher LLM-Einstiegspunkt fuer Agenten- & Chat-Calls."""
    if stream:
        # Der Router erwartet provider UND api_keys als Pflichtargumente und
        # kennt kein session_id. Der alte Aufruf erzeugte guarantee einen
        # TypeError — der gesamte Streaming-Pfad des Kernels war damit tot.
        from backend.agent_router import router_instance
        import api_provider
        msgs = list(messages or [])
        if not msgs and prompt:
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            msgs.append({"role": "user", "content": prompt})
        all_keys = api_provider.collect_keys() or {}
        eff_provider = (provider or "").strip().lower() or (
            "openrouter" if all_keys.get("OPENROUTER_API_KEY") else "omniroute"
        )
        eff_model = resolve_auto_model(model)
        gen = router_instance.stream_chat_completion(
            messages=msgs,
            provider=eff_provider,
            model=eff_model,
            api_keys=all_keys,
            reasoning_level=reasoning_level,
            agent_id=agent_id,
            role=role,
        )
        trace_id = await _otel_start("llm.stream", task_id or session_id, agent_id)

        async def _traced_stream():
            started = time.perf_counter()
            chunks: List[str] = []
            status = "OK"
            try:
                async for chunk in gen:
                    chunks.append(str(chunk))
                    yield chunk
            except Exception:
                status = "ERROR"
                raise
            finally:
                if trace_id:
                    await _otel_span(
                        trace_id,
                        name=f"llm.stream.{agent_id}",
                        span_type="llm",
                        agent_id=agent_id,
                        model=eff_model,
                        output_data="".join(chunks)[-2000:],
                        status=status,
                        duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
                        attributes={"provider": eff_provider, "stream": True},
                    )
                    await _otel_end(trace_id, status)

        return _traced_stream()

    import core_dispatcher
    eff_prompt = prompt
    if not eff_prompt and messages:
        eff_prompt = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    started = time.perf_counter()
    trace_id = await _otel_start("llm.dispatch", task_id or session_id, agent_id)
    res: Any = None
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=agent_id,
            agent_name=agent_name,
            prompt=eff_prompt,
            role=role,
            system_prompt=system_prompt,
            model=model,
            provider=provider,
            reasoning_level=reasoning_level,
            task_id=task_id,
        )
        return res
    finally:
        if trace_id:
            status = "OK"
            if isinstance(res, dict) and res.get("status") in ("error", "blocked"):
                status = "ERROR"
            in_tok = int(res.get("input_tokens", 0) or 0) if isinstance(res, dict) else 0
            out_tok = int(res.get("output_tokens", 0) or 0) if isinstance(res, dict) else 0
            cost = float(res.get("cost_usd", 0.0) or 0.0) if isinstance(res, dict) else 0.0
            await _otel_span(
                trace_id,
                name=f"llm.{agent_id}",
                span_type="llm",
                agent_id=agent_id,
                model=str(res.get("model") or model) if isinstance(res, dict) else model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
                duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
                status=status,
                attributes={"provider": str(res.get("provider") or provider) if isinstance(res, dict) else provider},
            )
            await _otel_end(trace_id, status)
