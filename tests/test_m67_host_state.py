"""M67 — Host-Zustand, deterministische Antwortprüfung, Step-Prompt.

Prüft zugleich, dass die M99-Compaction-SSOT und die Marker-Karte unverändert
funktionsfähig bleiben. Alle DB-Tests arbeiten ausschließlich mit ``tmp_path``.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from backend import llm_prices
from backend.context_compactor import (
    ContextCompactor,
    estimate_tokens,
    format_compaction_marker,
    resolve_model_context_window,
)
from backend.cost_estimator import estimate_prompt_cost
from backend.host_state_store import (
    HostState,
    HostStateConflict,
    HostStateStore,
    initial_state,
    state_key,
)
from backend.prompt_compressor import (
    MAX_STEP_TOKEN_BUDGET,
    STEP_MARKER,
    advance_from_response,
    build_step_prompt,
    format_host_state_marker,
    validate_model_response,
)

ROOT = Path(__file__).resolve().parent.parent


class _AuditCapture:
    """Minimaler Ersatz für ``chained_audit_log.record_event``."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def record_event(
        self,
        category: str,
        action: str,
        agent_id: str,
        payload: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        event = {
            "category": category,
            "action": action,
            "agent_id": agent_id,
            "payload": dict(payload),
        }
        self.events.append(event)
        return {"id": f"ev-{len(self.events)}"}


def test_host_state_roundtrip_versioning_and_tenant_keys(tmp_path: Path) -> None:
    store = HostStateStore(db_path=str(tmp_path / "agentic_memory.db"))
    state = initial_state("session_1", "job_1", "Zieldefinition", tenant_id="default")

    saved = store.save(state)
    assert saved.version == 1
    assert store.load("session_1") == saved

    # Veraltete Schreibzugriffe und falsche erwartete Versionen ändern nichts.
    with pytest.raises(HostStateConflict):
        store.save(saved)
    with pytest.raises(HostStateConflict):
        store.advance("session_1", 99, lambda current: current)

    advanced = store.advance(
        "session_1", 1, lambda current: replace(current, status="running")
    )
    assert advanced.version == 2
    assert advanced.status == "running"
    assert store.load("session_1") == advanced

    # Mandanten sind im kv_store-Key getrennt; ein fremder Mandant sieht nichts.
    assert store.load("session_1", tenant_id="mandant_b") is None
    assert state_key("session_1", "default") != state_key("session_1", "mandant_b")
    assert ".." not in state_key("session_1", "../etc")


def test_invalid_response_is_not_applied_and_is_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.audit_log import chained_audit_log

    capture = _AuditCapture()
    monkeypatch.setattr(chained_audit_log, "record_event", capture.record_event)

    store = HostStateStore(db_path=str(tmp_path / "agentic_memory.db"))
    store.save(initial_state("session_1", "job_1", "Ziel", tenant_id="default"))
    before = store.load("session_1")
    assert before is not None

    schema: Dict[str, Any] = {
        "status": {"type": "literal", "allowed": ["running", "done"]},
        "summary": {"type": "str", "max_len": 200, "required": False},
    }
    secret = "TOPSECRET_M67_9F8E"
    outcome = advance_from_response(
        store,
        session_id="session_1",
        tenant_id="default",
        response={"status": 42, "summary": secret},
        schema=schema,
        expected_version=1,
    )

    assert outcome["accepted"] is False
    assert outcome["state"] is None
    assert any("status" in error for error in outcome["errors"])
    after = store.load("session_1")
    assert after is not None and after.version == 1 and after.status == before.status
    assert capture.events[-1]["action"] == "model_response_rejected"

    # Weder Fehler-Result noch Audit-Payload dürfen Antwortwerte enthalten.
    assert secret not in json.dumps(outcome, ensure_ascii=False)
    assert secret not in json.dumps(capture.events, ensure_ascii=False)

    valid = advance_from_response(
        store,
        session_id="session_1",
        tenant_id="default",
        response={"status": "done"},
        schema=schema,
        expected_version=1,
    )
    assert valid["accepted"] is True
    assert valid["state"]["version"] == 2
    assert valid["state"]["status"] == "done"
    assert capture.events[-1]["action"] == "model_response_accepted"

    # Direkte Validierung: Typen, Pflichtfelder und unbekannte Felder.
    direct = validate_model_response({"status": "done", "extra": "ignored"}, schema)
    assert direct["valid"] is False
    assert direct["ignored_fields"] == 1
    assert validate_model_response('{"status": "done"}', schema)["valid"] is True


def test_step_prompt_budget_ssot_and_cost_estimator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    state = HostState(
        session_id="session_1",
        job_id="job_1",
        version=5,
        status="running",
        goal="Z" * 20_000,
        next_action="N" * 4_000,
        steps=tuple(
            {"id": f"s{i}", "status": "open", "summary": "x" * 500} for i in range(40)
        ),
        results=tuple({"note": "y" * 900} for _ in range(20)),
        tenant_id="default",
    )

    store = HostStateStore(db_path=str(tmp_path / "agentic_memory.db"))
    store.save(state)
    loaded = store.load("session_1")
    assert loaded is not None

    prompt = build_step_prompt(loaded, "gpt-4o", token_budget=600)
    assert STEP_MARKER in prompt["prompt"]
    assert "ZIEL:" in prompt["prompt"]
    assert prompt["input_tokens"] <= 600
    assert prompt["token_budget"] == 600
    assert isinstance(prompt["truncated"], bool)
    assert prompt["max_context_tokens"] == resolve_model_context_window("gpt-4o") == 128_000

    # Keine Duplikat-Preislogik: Prognose kommt aus cost_estimator.
    expected = estimate_prompt_cost(prompt["prompt"], "gpt-4o")
    assert prompt["cost_estimate"]["input_tokens_est"] == expected["input_tokens_est"]
    # Identische Parameter wie build_step_prompt (Output-Tokens/Budget zaehlen mit).
    expected_full = estimate_prompt_cost(
        prompt["prompt"],
        "gpt-4o",
        expected_output_tokens=prompt["expected_output_tokens"],
        task_budget_usd=0.25,
    )
    assert prompt["cost_estimate"]["estimated_cost_usd"] == expected_full["estimated_cost_usd"]
    assert prompt["within_budget"] == expected["fits_budget"]

    # Hartes Budget: auch ein riesiger Wunsch wird geklemmt.
    oversized = build_step_prompt(state, "gpt-4o", token_budget=1_000_000)
    assert oversized["token_budget"] <= MAX_STEP_TOKEN_BUDGET
    assert oversized["input_tokens"] <= MAX_STEP_TOKEN_BUDGET

    # Der Prompt enthält keinen wachsenden Chat-Verlauf, nur Host-Zustand.
    assert "[GEKÜRZT]" in prompt["prompt"]
    assert format_host_state_marker(loaded).startswith("[HOST_STATE_MARKER")
    assert estimate_tokens(prompt["prompt"]) == prompt["input_tokens"]


def test_m99_compaction_and_marker_card_remain_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    marker = format_compaction_marker(
        original_tokens=12000,
        compacted_tokens=3000,
        saved_pct=75.0,
        compacted_messages=10,
        kept_recent=4,
        max_context_tokens=200_000,
        model="anthropic/claude-3.5-sonnet",
    )
    assert marker.startswith("[COMPACTION_MARKER")
    assert "before=12000" in marker
    assert "max_context_tokens=200000" in marker

    messages = [
        {"role": "user", "content": "Analysiere backend/context_compactor.py"},
        {"role": "assistant", "content": "Entscheidung: Kontextfenster dynamisch umgesetzt."},
        {"role": "user", "content": "Nächster Schritt"},
        {"role": "assistant", "content": "Erledigt"},
        {"role": "user", "content": "Weiter"},
    ]
    result = ContextCompactor().compact_messages(
        messages,
        force=True,
        keep_recent_override=2,
        model="openai/gpt-4o",
        session_id="m67-m99-compat",
    )
    assert result["compacted"] is True
    assert result["compaction_marker"].startswith("[COMPACTION_MARKER")
    assert result["max_context_tokens"] == 128_000
    assert "Kontextfenster dynamisch umgesetzt" in result["messages"][0]["content"]

    chat_js = (ROOT / "static/js/chat_engine.js").read_text(encoding="utf-8")
    assert "COMPACTION_MARKER" in chat_js
    assert 'data-compaction-marker="true"' in chat_js
    assert "HOST_STATE_MARKER" in chat_js
    assert 'data-host-state-marker="true"' in chat_js

    chat_py = (ROOT / "archon/routers/chat.py").read_text(encoding="utf-8")
    assert "'type': 'compaction_marker'" in chat_py
    assert "'type': 'host_state'" in chat_py


def test_rbac_guards_on_m67_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """Writes bleiben hinter dem bestehenden Rollenzaun; Viewer werden geblockt."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from archon.routers import _rbac
    from archon.routers import auth as auth_router

    src = (ROOT / "archon/routers/chat.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    expected = {
        "api_get_host_state",
        "api_save_host_state",
        "api_advance_host_state",
        "api_get_host_step_prompt",
    }
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in expected:
            called = {
                item.func.id
                for item in ast.walk(node)
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
            }
            assert "require_admin_or_503" in called
            found.add(node.name)
    assert found == expected
    assert "dependencies=[_ArchonDepends(_forbid_viewer_writes)]" in src

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat/host-state/session_1",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
        "root_path": "",
    }
    request = Request(scope)
    monkeypatch.setattr(_rbac, "_audit_rbac_denial", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auth_router,
        "get_current_user_from_request",
        lambda _request: {"role": "viewer"},
    )
    with pytest.raises(HTTPException) as denied:
        _rbac.forbid_viewer_writes(request)
    assert denied.value.status_code == 403
