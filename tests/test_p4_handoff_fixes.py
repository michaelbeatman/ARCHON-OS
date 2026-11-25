"""Regressionstests fuer die P4-Restpunkte aus audit_reports/HANDOFF_FINAL_2026-11-25.md."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _req() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def test_p4_task_registry_preserves_zombie_on_timeout():
    from archon.core import task_registry

    async def _run():
        started = asyncio.Event()

        async def _stubborn():
            started.set()
            while True:
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    # Simuliert ignorierte Cancellation
                    await asyncio.sleep(10)

        t = task_registry.spawn(_stubborn(), name="zombie_probe")
        await started.wait()

        with patch.object(task_registry.asyncio, "wait_for", side_effect=asyncio.TimeoutError):
            removed = await task_registry.cancel_all()

        assert removed == 0
        assert "zombie_probe" in task_registry.pending()

        # Aufraeumen
        task_registry._TASKS.pop(t, None)
        t.cancel()

    asyncio.run(_run())


def test_p4_config_validator_detects_roles_field_drift(tmp_path):
    from backend.config_validator import ConfigValidator

    profiles = [{"id": "default", "prompt": "A", "person_name": "Default"}]
    roles = [{"id": "default", "prompt": "B-DRIFT", "person_name": "Default"}]
    (tmp_path / "agent_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    (tmp_path / "roles.json").write_text(json.dumps(roles), encoding="utf-8")

    cv = ConfigValidator(workspace_dir=str(tmp_path))
    errors, _warnings, _stats = cv.validate_profile_ssot({"default"})
    assert any("Feld-/Prompt-Drift" in e for e in errors)


def test_p4_v2_gdpr_erase_runtime_error_returns_500(monkeypatch):
    from archon.routers import v2_capabilities

    monkeypatch.setattr(v2_capabilities, "require_admin_or_503", lambda _r: None)
    with patch(
        "backend.tenant_db_registry.gdpr_erase_subject_data",
        side_effect=RuntimeError("db_locked"),
    ):
        with pytest.raises(HTTPException) as exc:
            v2_capabilities.api_v2_gdpr_erase(
                _req(), v2_capabilities.GdprEraseRequest(subject="Max", tenant_id="")
            )
    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "gdpr_erasure_failed"


def test_p4_v2_portal_challenge_endpoint_calls_verify_share_access(tmp_path):
    from archon.routers import v2_capabilities
    from backend import client_approval_portal as cap

    db = str(tmp_path / "portal.db")
    link = cap.create_share_link(offer_id="off-1", title="Angebot Test", db_path=db)
    _orig_verify = cap.verify_share_access

    with patch(
        "backend.client_approval_portal.verify_share_access",
        side_effect=lambda **kw: _orig_verify(db_path=db, **kw),
    ):
        res = v2_capabilities.api_v2_get_portal_challenge(
            token=link["token"],
            disclosure_session="sess-1",
        )
    assert res["status"] == "success"
    assert res["allowed"] is True
    assert res.get("ai_disclosure_token")
    assert res.get("ai_disclosure_nonce")


def test_p4_agent_router_chat_completion_uses_deterministic_guard(monkeypatch):
    from backend.agent_router import AgentRouter, SilentFailureBlockedError

    router = AgentRouter()

    async def _run():
        with patch(
            "backend.execution_routing_guard.classify_execution_layer",
            return_value={"layer": "deterministic_n8n", "requires_hitl": True, "webhook_action": "crm"},
        ):
            with pytest.raises(SilentFailureBlockedError) as exc:
                await router.chat_completion(
                    messages=[{"role": "user", "content": "ACTION: WEBHOOK_CRM"}],
                    provider="openrouter",
                    model="deepseek/deepseek-chat",
                    api_keys={"OPENROUTER_API_KEY": "sk-dummy"},
                    task_id="t-det-1",
                )
            assert "DETERMINISTIC_HITL_REQUIRED" in str(exc.value)

        with patch(
            "backend.execution_routing_guard.classify_execution_layer",
            return_value={"layer": "deterministic_script", "requires_hitl": False},
        ):
            out = await router.chat_completion(
                messages=[{"role": "user", "content": "run script"}],
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_keys={"OPENROUTER_API_KEY": "sk-dummy"},
                task_id="t-det-2",
            )
            assert "0 Tokens" in out

    asyncio.run(_run())


def test_p4_chat_image_generate_empty_choices_returns_502(monkeypatch):
    from archon.routers import chat

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": []}

    async def _run():
        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return fake_resp

        with patch.object(chat.api_provider, "collect_keys", return_value={"OPENROUTER_API_KEY": "sk-dummy"}), \
             patch("backend.llm_egress_guard.evaluate_and_gate_llm_dispatch", return_value={
                 "intended_url": "https://openrouter.ai/api/v1/chat/completions",
                 "model": "google/gemini-2.5-flash-image",
                 "data_category": "general",
                 "zero_egress_active": False,
                 "routed_to_local": False,
             }), \
             patch("backend.llm_egress_guard.enforce_egress_firewall_for_url"), \
             patch("backend.llm_egress_guard.audit_dispatch_async", return_value=None), \
             patch("backend.llm_egress_guard.sanitize_outbound_llm_payload", side_effect=lambda p, **kw: p), \
             patch("httpx.AsyncClient", return_value=_FakeAsyncClient()):
            with pytest.raises(HTTPException) as exc:
                await chat.api_tool_image_generate(
                    chat.ImageGenerateToolRequest(prompt="test image", session_id="s1")
                )
        assert exc.value.status_code == 502
        assert exc.value.detail["code"] == "EMPTY_RESPONSE"

    asyncio.run(_run())
