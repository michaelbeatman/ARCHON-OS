"""F31 (HIGH H-D): Auth- und Tenant-Middleware verlagern sync I/O in asyncio.to_thread."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from archon.middleware.auth_gate import (
    AuthGateDeps,
    run_auth_gate_middleware,
    run_tenant_context_middleware,
)


def _make_deps() -> AuthGateDeps:
    return AuthGateDeps(
        request_has_service_token=lambda _req: False,
        auth_unavailable_response=lambda: JSONResponse(
            status_code=503, content={"error": "auth_unavailable"}
        ),
        auth_public_exact={"/livez", "/readyz", "/login"},
        auth_public_prefixes=("/static/",),
        auth_api_prefixes=("/api/",),
        auth_protected_prefixes=("/dashboard",),
    )


def _make_request(path: str = "/api/tasks", method: str = "GET", headers=None, user=None):
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        method=method,
        headers=headers or {},
        cookies={},
        state=SimpleNamespace(user=user),
    )


def test_f31_auth_gate_verify_session_is_non_blocking_and_fail_closed(monkeypatch):
    """Blockierende Auth-DB darf den Event-Loop nicht blockieren; 401/503 bleiben fail-closed."""
    from backend.auth_service import auth_service

    monkeypatch.setattr(auth_service, "is_auth_enabled", lambda: True)

    def _slow_verify(token: str):
        time.sleep(0.25)
        if token == "valid-tok":
            return {"username": "alice", "role": "admin"}
        return None

    monkeypatch.setattr(auth_service, "verify_session", _slow_verify)
    deps = _make_deps()

    async def _call_next(_req):
        return JSONResponse(status_code=200, content={"ok": True})

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        req_ok = _make_request(headers={"authorization": "Bearer valid-tok"})
        resp_ok, _ = await asyncio.gather(
            run_auth_gate_middleware(req_ok, _call_next, deps),
            _heartbeat(),
        )
        assert resp_ok.status_code == 200
        # Wenn verify_session synchron im Loop liefe, waere loop_latency >= 0.25s
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

        # Fail-closed 401 ohne Token
        req_no_tok = _make_request(headers={})
        resp_401 = await run_auth_gate_middleware(req_no_tok, _call_next, deps)
        assert resp_401.status_code == 401

        # Fail-closed 503 bei Exception in verify_session
        monkeypatch.setattr(
            auth_service,
            "verify_session",
            lambda _t: (_ for _ in ()).throw(RuntimeError("db_locked")),
        )
        req_err = _make_request(headers={"authorization": "Bearer boom"})
        resp_503 = await run_auth_gate_middleware(req_err, _call_next, deps)
        assert resp_503.status_code == 503

    asyncio.run(_run())


def test_f31_tenant_middleware_list_companies_is_non_blocking_and_enforces_known(monkeypatch):
    """list_companies() laeuft in to_thread; unbekannte X-Tenant-Id bleibt 403."""
    from backend.tenant_context import tenant_context

    class _SlowMgr:
        def list_companies(self):
            time.sleep(0.25)
            return [{"id": "acme_gmbh", "name": "Acme"}]

    monkeypatch.setattr(tenant_context, "_get_corporate_manager", lambda: _SlowMgr())
    deps = _make_deps()

    async def _call_next(_req):
        return JSONResponse(status_code=200, content={"ok": True})

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        req_known = _make_request(
            headers={"X-Tenant-Id": "acme_gmbh"},
            user={"username": "admin", "role": "admin"},
        )
        resp_ok, _ = await asyncio.gather(
            run_tenant_context_middleware(req_known, _call_next, deps),
            _heartbeat(),
        )
        assert resp_ok.status_code == 200
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

        req_unknown = _make_request(
            headers={"X-Tenant-Id": "ghost_corp"},
            user={"username": "admin", "role": "admin"},
        )
        resp_403 = await run_tenant_context_middleware(req_unknown, _call_next, deps)
        assert resp_403.status_code == 403

    asyncio.run(_run())
