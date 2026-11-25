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
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("archon.llm_kernel")


class _TracedStream:
    """Async-Iterator-Wrapper mit strukturierten Metadaten (Generatoren
    erlauben keine eigenen Attribute)."""

    def __init__(
        self,
        agen: Any,
        *,
        effective_prompt_info: Dict[str, Any],
        trace_id: str,
        session_id: str,
        correlation_id: str,
    ) -> None:
        self._agen = agen
        self.effective_prompt_info = effective_prompt_info
        self.prompt_version_info = effective_prompt_info
        self.trace_id = trace_id
        self.session_id = session_id
        self.correlation_id = correlation_id

    def __aiter__(self) -> Any:
        return self._agen


def _prompt_ref(agent_id: str, model: str = "") -> Dict[str, Any]:
    """Fallback-Referenz, damit auch geblockte/erfolglose Dispatches ein
    ``effective_prompt_info`` im Ergebnis tragen (D11/S-11.2)."""
    return {
        "agent_id": agent_id,
        "version": "",
        "version_num": 0,
        "prompt_version": "",
        "prompt_hash": "",
        "canary": False,
        "is_canary": False,
        "canary_percentage": 0,
        "model": model or "",
        "prompt_chars": 0,
        "source": "llm_kernel.fallback",
    }


def _with_dispatch_context(
    res: Any,
    *,
    agent_id: str,
    model: str,
    trace_id: str,
    session_id: str,
    correlation_id: str,
) -> Dict[str, Any]:
    """Jeder Dispatch-Return enthaelt Prompt-Referenz und Korrelationsfelder."""
    out = dict(res) if isinstance(res, dict) else {"status": "error", "content": str(res or "")}
    info = out.get("effective_prompt_info")
    if not isinstance(info, dict) or not info:
        info = _prompt_ref(agent_id, model)
        info["model"] = str(out.get("model") or model or "")
    out["effective_prompt_info"] = info
    out.setdefault("prompt_version_info", info)
    out.setdefault("trace_id", trace_id)
    out.setdefault("session_id", session_id)
    out.setdefault("correlation_id", correlation_id)
    return out


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
        # F1a: Preis-SSOT liegt in backend/. get_llm_prices() liefert
        # {"status": ..., "prices": {model_id: {"prompt_1m", "completion_1m"}}}.
        # Vorher wurde "prices" nie ausgepackt und nach "input"/"prompt_per_1m"
        # gesucht -> Live-Preise griffen nie (Antigravity-Befund).
        from backend.llm_prices import get_llm_prices
        result = get_llm_prices()
        prices = result.get("prices") if isinstance(result, dict) else None
        if (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and isinstance(prices, dict)
            and model in prices
        ):
            entry = prices[model]
            if isinstance(entry, dict):
                in_per_1m = float(entry.get("prompt_1m", in_per_1m) or in_per_1m)
                out_per_1m = float(entry.get("completion_1m", out_per_1m) or out_per_1m)
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


def _note_trace_error(message: str, exc: BaseException) -> None:
    """D16/M4: Trace-Fehler ueber die eine zentrale API melden.

    ``backend.trace_context.note_local_trace_error`` ist die einzige
    Meldekette (delegiert an ``tracer.note_local_trace_error`` und zaehlt dort
    in ``record_stats``). Lokale Fallbacks wurden entfernt, damit die
    Zaehlwege nicht divergieren.
    """
    from backend.trace_context import note_local_trace_error

    note_local_trace_error(message, exc)


async def _otel_start(name: str, task_id: Optional[str], agent_id: str) -> Optional[str]:
    try:
        from backend.otel_tracer import tracer
        return await asyncio.to_thread(tracer.start_trace, name, task_id, agent_id)
    except Exception as exc:
        _note_trace_error("[LLMKernel] OTel-Trace-Start fehlgeschlagen", exc)
        return None


async def _otel_span(trace_id: str, **kwargs: Any) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.record_span, trace_id, **kwargs)
    except Exception as exc:
        _note_trace_error("[LLMKernel] OTel-Span fehlgeschlagen", exc)


async def _otel_end(trace_id: str, status: str) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.end_trace, trace_id, status)
    except Exception as exc:
        _note_trace_error("[LLMKernel] OTel-Trace-Ende fehlgeschlagen", exc)


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
    try:
        from backend import trace_context as _tctx_module
        _tctx: Any = _tctx_module
    except Exception:
        _tctx = None

    active_trace = ""
    if _tctx is not None:
        active_trace = str(_tctx.current_trace_id() or "")
        if not active_trace:
            try:
                active_trace, _ = _tctx.ensure_trace()
            except Exception:
                active_trace = ""
    correlation_id = str(task_id or session_id or active_trace or "")

    if stream:
        # Der Router erwartet provider UND api_keys als Pflichtargumente und
        # kennt kein session_id. Das Session-/Trace-Feld wird daher ueber den
        # Trace-Kontext und die Ergebnis-Metadaten mitgefuehrt.
        from backend.agent_router import router_instance
        import api_provider
        msgs = list(messages or [])
        if not msgs and prompt:
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            msgs.append({"role": "user", "content": prompt})
        # D08/S-8.1: der Profil-.env-Scan liest ~70 Dateien synchron — nicht
        # im Event-Loop blockieren (der TTL-Cache begrenzt nur die Frequenz).
        all_keys = (await asyncio.to_thread(api_provider.collect_keys)) or {}
        eff_provider = (provider or "").strip().lower() or (
            "openrouter" if all_keys.get("OPENROUTER_API_KEY") else "omniroute"
        )
        eff_model = resolve_auto_model(model)
        trace_id = await _otel_start("llm.stream", task_id or session_id, agent_id)
        ref = _prompt_ref(agent_id, eff_model)
        # D11/S-11.2: auch der Stream-Pfad muss die echte Registry-Referenz
        # (Version/Canary/Hash) im Result zurueckgeben, nicht den leeren Fallback.
        try:
            from backend.prompt_registry import prompt_registry
            _eff = prompt_registry.get_effective_prompt(agent_id, task_id or None)
            if _eff and _eff.get("prompt"):
                _prompt_text = str(_eff.get("prompt") or "")
                _is_canary = bool(_eff.get("is_canary") or _eff.get("canary") or False)
                _version = str(
                    _eff.get("version_num") or _eff.get("version") or _eff.get("prompt_version") or ""
                )
                ref = {
                    **ref,
                    "version": _version,
                    "version_num": _eff.get("version_num") or 0,
                    "prompt_version": _version,
                    "prompt_hash": hashlib.sha256(_prompt_text.encode("utf-8")).hexdigest(),
                    "prompt_chars": len(_prompt_text),
                    "canary": _is_canary,
                    "is_canary": _is_canary,
                    "canary_percentage": _eff.get("canary_percentage") or 0,
                    "model": _eff.get("model") or eff_model,
                    "source": "prompt_registry",
                    "resolved": True,
                }
        except Exception as _pref_exc:
            logger.debug("[LLM-Kernel] Prompt-Ref im Stream-Pfad nicht aufloesbar: %s", _pref_exc)

        async def _traced_stream():
            started = time.perf_counter()
            chunks: List[str] = []
            status = "OK"
            try:
                # Kind-Span im selben Trace-Kontext (D11/S-11.4).
                span_cm = (
                    _tctx.child_span()
                    if _tctx is not None and trace_id else None
                )
                if span_cm is not None:
                    with span_cm:
                        gen = router_instance.stream_chat_completion(
                            messages=msgs,
                            provider=eff_provider,
                            model=eff_model,
                            api_keys=all_keys,
                            reasoning_level=reasoning_level,
                            agent_id=agent_id,
                            role=role,
                        )
                        async for chunk in gen:
                            chunks.append(str(chunk))
                            yield chunk
                else:
                    gen = router_instance.stream_chat_completion(
                        messages=msgs,
                        provider=eff_provider,
                        model=eff_model,
                        api_keys=all_keys,
                        reasoning_level=reasoning_level,
                        agent_id=agent_id,
                        role=role,
                    )
                    async for chunk in gen:
                        chunks.append(str(chunk))
                        yield chunk
            except Exception:
                status = "ERROR"
                raise
            finally:
                # D12: leerer Stream oder ERROR-Chunk darf nicht als OK gemeldet werden.
                if not chunks or any(str(c).startswith("ERROR:") for c in chunks):
                    status = "ERROR"
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
                        attributes={"provider": eff_provider, "stream": True,
                                    "session_id": session_id or "", "correlation_id": correlation_id},
                    )
                    await _otel_end(trace_id, status)

        # Auch der Streaming-Pfad traegt die strukturierte Referenz (kein Dict-Return).
        return _TracedStream(
            _traced_stream(),
            effective_prompt_info=ref,
            trace_id=str(trace_id or active_trace or ""),
            session_id=session_id or "",
            correlation_id=correlation_id,
        )

    import core_dispatcher
    eff_prompt = prompt
    if not eff_prompt and messages:
        eff_prompt = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    started = time.perf_counter()
    trace_id = await _otel_start("llm.dispatch", task_id or session_id, agent_id)
    # session_id/correlation_id reisen ueber den Trace-Kontext ueber Systemgrenzen.
    if _tctx is not None and (active_trace or trace_id):
        active_trace = str(trace_id or active_trace)
    # D16/M1: Den Kontext explizit mit traceparent + sampled wiederherstellen.
    # Ohne diese Werte wuerfelt use_trace_context() bei parsed is None die
    # Sampling-Entscheidung neu (ignore_parent=True) — ein incoming `…-01`
    # koennte bei parentbased_traceidratio auf `00` kippen.
    ctx_cm = None
    if _tctx is not None and active_trace:
        ctx_span = str(_tctx.current_span_id() or "")
        ctx_sampled = bool(_tctx.current_sampled())
        ctx_cm = _tctx.use_trace_context(
            trace_id=active_trace,
            span_id=ctx_span,
            traceparent=(
                _tctx.format_traceparent(active_trace, ctx_span, ctx_sampled)
                if ctx_span else None
            ),
            sampled=ctx_sampled,
        )
    res: Any = None
    try:
        if ctx_cm is not None:
            with ctx_cm:
                res = await core_dispatcher.dispatch_to_omniroute_or_container(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    prompt=eff_prompt,
                    role=role,
                    system_prompt=system_prompt,
                    model=model,
                    provider=provider,
                    reasoning_level=reasoning_level,
                    task_id=task_id or "",
                )
        else:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=eff_prompt,
                role=role,
                system_prompt=system_prompt,
                model=model,
                provider=provider,
                reasoning_level=reasoning_level,
                task_id=task_id or "",
            )
        return _with_dispatch_context(
            res,
            agent_id=agent_id,
            model=str(res.get("model") or model) if isinstance(res, dict) else model,
            trace_id=str(trace_id or active_trace or ""),
            session_id=session_id or "",
            correlation_id=correlation_id,
        )
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
