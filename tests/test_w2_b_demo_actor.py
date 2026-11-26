"""
tests/test_w2_b_demo_actor.py

W2-B (Security) regression tests:

* D04-H1 — Demo ASGI guard: `/rest/push` n8n-WS alias + WebSocket Default-Deny
           + defense-in-depth gate in `_ws_forward_n8n_push` (1008 close).
* D04-M4 — `get_session_actor()` never invents an "admin" audit actor; missing
           identity fails closed with 401/503.
* D04-M6 — `resolve_agent_id()` returns a unique sentinel for empty/unknown IDs
           instead of silently mapping to the real agent `research_scout`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import archon.routers.auth as auth_router  # noqa: E402
import archon.routers.proxies as proxies  # noqa: E402
from archon.routers import _rbac  # noqa: E402
from backend import agent_aliases, demo_mode  # noqa: E402
from backend.agent_aliases import UNKNOWN_AGENT_ID, resolve_agent_id  # noqa: E402
from backend.demo_mode import (  # noqa: E402
    DEMO_HARD_BLOCKED_PREFIXES,
    DEMO_SAFE_WEBSOCKET_PATHS,
    DemoModeMiddleware,
)


def _dummy_request() -> Request:
    scope: Dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# D04-H1 — Demo-Mode: WebSocket Default-Deny & /rest/push Egress-Bypass
# ---------------------------------------------------------------------------


def _build_demo_ws_app() -> tuple[FastAPI, List[str]]:
    """App mit echten WS-Routen hinter dem Demo-Guard + Aufruf-Spy."""
    calls: List[str] = []
    app = FastAPI()
    app.add_middleware(DemoModeMiddleware)

    @app.websocket("/rest/push")
    async def root_push(ws: WebSocket) -> None:
        await ws.accept()
        calls.append("root-push")
        await ws.send_text("LIVE-N8N-EGRESS")
        await ws.close()

    @app.websocket("/n8n-proxy/rest/push")
    async def prefixed_push(ws: WebSocket) -> None:
        await ws.accept()
        calls.append("prefixed-push")
        await ws.send_text("LIVE-N8N-EGRESS")
        await ws.close()

    @app.websocket("/api/demo/ws")
    async def demo_ws(ws: WebSocket) -> None:
        await ws.accept()
        calls.append("demo-ws")
        await ws.send_text("LIVE-N8N-EGRESS")
        await ws.close()

    @app.get("/rest/push")
    async def rest_push_http() -> Dict[str, bool]:
        calls.append("rest-push-http")
        return {"proxied": True}

    return app, calls


def test_rest_push_is_in_hard_blocked_prefix_list() -> None:
    assert "/rest/push" in DEMO_HARD_BLOCKED_PREFIXES
    # ASGI scope["path"] enthaelt keine Query — der WS-Relay haengt sie erst
    # beim Upstream-Connect an (proxies.py).
    assert demo_mode._is_hard_blocked_path("/rest/push") is True
    assert demo_mode._is_hard_blocked_path("/rest/push/sub") is True


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_http_rest_push_alias_is_blocked_in_demo(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_demo_ws_app()

    response = TestClient(app).request(method, "/rest/push")

    assert response.status_code == 403
    assert response.json()["status"] == "demo_blocked"
    assert calls == [], "Der Proxy-Handler darf im Demo nie ausgefuehrt werden"


@pytest.mark.parametrize(
    "path",
    ["/rest/push", "/n8n-proxy/rest/push", "/api/demo/ws", "/some/unregistered/ws"],
)
def test_websocket_default_deny_in_demo(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_demo_ws_app()

    with pytest.raises(WebSocketDisconnect) as caught:
        with TestClient(app).websocket_connect(path):
            pass

    assert caught.value.code == 1008
    assert calls == [], f"WS-Handler {path} darf im Demo nicht laufen"


def test_websocket_safe_list_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DEMO_SAFE_WEBSOCKET_PATHS == frozenset(), "Default-Deny darf nicht vorbelegt sein"

    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    monkeypatch.setattr(demo_mode, "DEMO_SAFE_WEBSOCKET_PATHS", frozenset({"/api/demo/ws"}))
    app, calls = _build_demo_ws_app()

    with TestClient(app).websocket_connect("/api/demo/ws") as ws:
        assert ws.receive_text() == "LIVE-N8N-EGRESS"
    assert calls == ["demo-ws"]


def test_hard_blocked_websocket_wins_over_safe_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    monkeypatch.setattr(demo_mode, "DEMO_SAFE_WEBSOCKET_PATHS", frozenset({"/rest/push"}))
    app, calls = _build_demo_ws_app()

    with pytest.raises(WebSocketDisconnect) as caught:
        with TestClient(app).websocket_connect("/rest/push"):
            pass

    assert caught.value.code == 1008
    assert calls == []


class _CloseOnlyWebSocket:
    """Minimaler Fake: zeichnet nur `close()` auf — der Demo-Gate muss vor jedem
    Accept/Upstream-Connect greifen."""

    def __init__(self) -> None:
        self.headers: Dict[str, str] = {}
        self.url = SimpleNamespace(query="")
        self.close_codes: List[int] = []

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)


def test_n8n_push_proxy_has_own_demo_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    ws = _CloseOnlyWebSocket()

    asyncio.run(proxies._ws_forward_n8n_push(ws))  # type: ignore[arg-type]

    assert ws.close_codes == [1008], "Proxy muss auch ohne Middleware fail-closed sein"


# ---------------------------------------------------------------------------
# D04-M4 — Session-Actor: keine erfundene privilegierte Identitaet
# ---------------------------------------------------------------------------


def test_session_actor_without_request_never_invents_admin() -> None:
    assert _rbac.get_session_actor(None) == "unknown"
    assert _rbac.get_session_actor(None, fallback="admin") == "unknown"
    assert _rbac.get_session_actor(None, fallback="ADMIN") == "unknown"
    assert _rbac.get_session_actor(None, fallback="root") == "unknown"

    # Explizite, nicht-privilegierte Audit-Labels bleiben erlaubt.
    assert _rbac.get_session_actor(None, fallback="boardroom-service") == "boardroom-service"


def test_session_actor_with_request_uses_verified_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_router,
        "get_current_user_from_request",
        lambda request: {"username": "alice", "role": "admin", "auth_enabled": True},
    )
    assert _rbac.get_session_actor(_dummy_request()) == "alice"


def test_session_actor_session_error_fails_closed_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: Any) -> None:
        raise RuntimeError("session store offline")

    monkeypatch.setattr(auth_router, "get_current_user_from_request", _boom)

    for fallback in (None, "admin"):
        with pytest.raises(HTTPException) as caught:
            _rbac.get_session_actor(_dummy_request(), fallback=fallback)
        assert caught.value.status_code == 503


def test_session_actor_missing_identity_fails_closed_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_router,
        "get_current_user_from_request",
        lambda request: {"username": "anonymous", "role": "anonymous", "auth_enabled": True},
    )
    with pytest.raises(HTTPException) as caught:
        _rbac.get_session_actor(_dummy_request())
    assert caught.value.status_code == 401


def test_service_token_is_rejected_as_audit_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_router,
        "get_current_user_from_request",
        lambda request: {"username": "service", "role": "admin", "is_service": True},
    )
    with pytest.raises(HTTPException) as caught:
        _rbac.get_session_actor(_dummy_request())
    assert caught.value.status_code == 403


def test_audit_actor_label_never_fabricates_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: Any) -> None:
        raise RuntimeError("session store offline")

    monkeypatch.setattr(auth_router, "get_current_user_from_request", _boom)
    assert _rbac._safe_audit_actor(_dummy_request()) == "unknown"

    monkeypatch.setattr(auth_router, "get_current_user_from_request", lambda request: {"username": "bob"})
    assert _rbac._safe_audit_actor(_dummy_request()) == "bob"


# ---------------------------------------------------------------------------
# D04-M6 — Agent-Aliase: Default-Deny statt research_scout-Fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_empty_agent_id_uses_unique_sentinel(raw: str | None) -> None:
    resolved = resolve_agent_id(raw)
    assert resolved == UNKNOWN_AGENT_ID
    assert resolved != "research_scout"
    assert resolved not in ("default", "admin", "research_scout")


def test_unknown_agent_id_with_known_ids_is_sentinel() -> None:
    assert resolve_agent_id("ghost_agent", known_ids={"research_scout"}) == UNKNOWN_AGENT_ID
    assert resolve_agent_id("research_scout", known_ids=set()) == UNKNOWN_AGENT_ID
    assert agent_aliases.UNKNOWN_AGENT_ID == UNKNOWN_AGENT_ID


def test_known_aliases_still_resolve() -> None:
    assert resolve_agent_id("research") == "research_scout"
    assert resolve_agent_id("hermes-coder") == "senior_fullstack_engineer"
    assert resolve_agent_id("default") == "default"
    assert resolve_agent_id("finance_lead", known_ids={"finance_lead"}) == "finance_lead"


def test_without_known_ids_unknown_id_is_left_to_caller() -> None:
    """Ohne `known_ids` kann der Helper keine Gueltigkeit pruefen — deshalb
    muessen die Produktivaufrufer `known_ids` uebergeben und den Sentinel
    blockieren (siehe audit_reports/w2_b_report.md)."""
    assert resolve_agent_id("ghost_agent") == "ghost_agent"
