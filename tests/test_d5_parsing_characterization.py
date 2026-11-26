"""D5-C2 Characterization-Tests fuer archon/core/dispatch_parsing.py (INVARIANTS §3).

Deckt ab:
1. Reinfunktion-Vertrag: parse_omniroute_response (JSON, SSE, Think-Tags, Leer/Fehler),
   clean_think_tags, _extract_tokens_usage, _resolve_openrouter_fallback_model.
2. Split-Brain-Negativprobe: monkeypatch.setattr(core_dispatcher, "parse_omniroute_response", ...)
   muss im echten Chokepoint (_dispatch_to_omniroute_or_container_impl) ankommen.
3. AST-Vertrag: X as X Re-Export auf core_dispatcher.py (+ Negativprobe ohne X as X).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import core_dispatcher

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_explicit_reexport(source: str, module: str, symbol: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name == symbol and alias.asname == symbol:
                    return True
    return False


def test_d5_c2_clean_think_tags_handles_closed_and_unclosed():
    assert core_dispatcher.clean_think_tags("<think>secret</think>Antwort") == "Antwort"
    assert core_dispatcher.clean_think_tags("Vorher<think>abgeschnitten ohne ende") == "Vorher"
    assert core_dispatcher.clean_think_tags("") == ""


def test_d5_c2_parse_omniroute_response_json_sse_and_fail_closed():
    payload = json.dumps({"choices": [{"message": {"content": "<think>x</think>Ergebnis OK"}}]})
    assert core_dispatcher.parse_omniroute_response(payload) == "Ergebnis OK"

    sse = (
        'data: {"choices": [{"delta": {"content": "Teil 1 "}}]}\n'
        'data: {"choices": [{"delta": {"content": "Teil 2"}}]}\n'
        "data: [DONE]\n"
    )
    assert core_dispatcher.parse_omniroute_response(sse) == "Teil 1 Teil 2"

    with pytest.raises(RuntimeError, match="EMPTY_OR_INVALID_RESPONSE"):
        core_dispatcher.parse_omniroute_response("")
    with pytest.raises(RuntimeError, match="EMPTY_OR_INVALID_RESPONSE"):
        core_dispatcher.parse_omniroute_response("not valid json or sse")


def test_d5_c2_extract_tokens_usage_and_fallback_model():
    raw = json.dumps({"usage": {"prompt_tokens": 123, "completion_tokens": 45}})
    assert core_dispatcher._extract_tokens_usage(raw, "hi", "ok") == (123, 45)
    # Fallback-Schaetzung bei defektem JSON
    inp, out = core_dispatcher._extract_tokens_usage("broken", "a b c", "d e")
    assert inp >= 50 and out >= 20

    assert core_dispatcher._resolve_openrouter_fallback_model("omniroute/best-coding") == "deepseek/deepseek-chat"
    assert core_dispatcher._resolve_openrouter_fallback_model("omniroute/best-reasoning") == "deepseek/deepseek-r1"
    assert core_dispatcher._resolve_openrouter_fallback_model("omniroute/anthropic/claude-3.7") == "anthropic/claude-3.7"
    assert core_dispatcher._resolve_openrouter_fallback_model("auto/unknown") == "deepseek/deepseek-chat"
    assert core_dispatcher._resolve_openrouter_fallback_model("openai/gpt-4o") == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_d5_c2_monkeypatch_parse_omniroute_response_reaches_chokepoint(monkeypatch):
    """Split-Brain-Negativprobe: Monkeypatch auf core_dispatcher.parse_omniroute_response muss im Chokepoint wirken."""
    import api_provider
    import backend.llm_egress_guard as egress_mod

    monkeypatch.setattr(core_dispatcher, "parse_omniroute_response", lambda _text: "D5_C2_PARSER_MARKER")
    monkeypatch.setattr(
        egress_mod,
        "evaluate_and_gate_llm_dispatch",
        lambda **_kw: {
            "allowed": True,
            "routed_to_local": False,
            "zero_egress_active": False,
            "provider": "openrouter",
            "model": "deepseek/deepseek-chat",
            "effective_provider": "openrouter",
            "effective_model": "deepseek/deepseek-chat",
            "data_category": "public",
            "audit_event": {},
        },
    )
    monkeypatch.setattr(
        api_provider,
        "collect_keys",
        lambda: {"OPENROUTER_API_KEY": "sk-test-d5-c2"},
    )
    monkeypatch.setattr(core_dispatcher, "_log_dispatcher_usage", lambda *_a, **_kw: _async_noop())

    class _FakeResp:
        status_code = 200
        text = '{"choices": [{"message": {"content": "UNPATCHED_RAW"}}]}'

    class _FakeClient:
        async def post(self, *_a, **_kw):
            return _FakeResp()

    monkeypatch.setattr(core_dispatcher, "_get_dispatcher_http_client", lambda: _FakeClient())

    res = await core_dispatcher._dispatch_to_omniroute_or_container_impl(
        agent_id="coder",
        agent_name="Coder",
        prompt="Teste Parser Patch-Punkt",
        provider="openrouter",
        model="deepseek/deepseek-chat",
        task_id="task-d5-c2-probe",
    )
    assert res["status"] == "success"
    assert res["content"] == "D5_C2_PARSER_MARKER"


async def _async_noop() -> None:
    return None


def test_d5_c2_ast_explicit_x_as_x_reexports_and_negative_probe():
    src = (REPO_ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    for sym in (
        "parse_omniroute_response",
        "clean_think_tags",
        "_extract_tokens_usage",
        "_resolve_openrouter_fallback_model",
        "_OMNIROUTE_OPENROUTER_FALLBACK_MAP",
    ):
        assert _has_explicit_reexport(src, "archon.core.dispatch_parsing", sym), (
            f"core_dispatcher.py muss `{sym} as {sym}` aus archon.core.dispatch_parsing re-exportieren."
        )
    # Negativprobe: Import ohne `as X` muss False liefern
    assert _has_explicit_reexport(
        "from archon.core.dispatch_parsing import parse_omniroute_response\n",
        "archon.core.dispatch_parsing",
        "parse_omniroute_response",
    ) is False
