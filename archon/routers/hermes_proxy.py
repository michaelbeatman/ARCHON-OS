"""Router und Forwarder fuer Hermes-Dashboard und WebUI-Proxy."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
import weakref
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi import Depends as _ArchonDepends
from fastapi.responses import HTMLResponse, JSONResponse

from archon.core.config import config
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_admin_or_503

logger = logging.getLogger("archon.routers.hermes_proxy")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["hermes_proxy"])

_PROXY_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _hermes_proxy_token() -> str:
    """Token fuer den Hermes-Dashboard-Forward — ausschliesslich aus der Umgebung."""
    for name in (
        "HERMES_SESSION_TOKEN",
        "HERMES_DASHBOARD_SESSION_TOKEN",
        "OMNIROUTE_API_KEY",
    ):
        value = config.get_hermes_proxy_token(name)
        if value:
            return value
    return ""


# WeakKeyDictionary: id(loop) konnte nach Event-Loop-Neustart recycelt werden
# und lieferte dann einen Client eines fremden Loops (Audit 23.11.2026).
_HERMES_CLIENTS_BY_LOOP: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()
_HERMES_TARGET_CACHE: Dict[str, Any] = {"base": None, "ts": 0.0}


def _get_hermes_client() -> httpx.AsyncClient:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Aufruf ohne Loop: temporärer Client, wird vom Caller geschlossen.
        return httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=2.5),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        )
    client = _HERMES_CLIENTS_BY_LOOP.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=2.5),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        )
        _HERMES_CLIENTS_BY_LOOP[loop] = client
    return client


async def close_all_hermes_clients() -> int:
    """A5/D08: alle loop-keyed Hermes-Clients zentral am Shutdown schliessen.

    Snapshot, ``await client.aclose()``, ``clear()``. Fehler werden sichtbar
    geloggt, duerfen aber den Shutdown nicht blockieren (fail-safe).
    """
    closed = 0
    for client in list(_HERMES_CLIENTS_BY_LOOP.values()):
        try:
            if not client.is_closed:
                await client.aclose()
                closed += 1
        except Exception as exc:
            logger.debug("[Hermes-Proxy] HTTP-Client-Close-Hinweis: %s", exc)
    _HERMES_CLIENTS_BY_LOOP.clear()
    return closed


async def forward_to_hermes(request: Request) -> Response:
    path_to_use = request.url.path
    if path_to_use.startswith("/static/hermes-webui"):
        path_to_use = path_to_use[len("/static/hermes-webui"):]
    query_str = f"?{str(request.query_params)}" if request.query_params else ""

    base_candidates = [
        "http://hermes-webui:8787",
        "http://127.0.0.1:8787",
        "http://host.docker.internal:8787",
        "http://hermes-dashboard:9119",
        "http://127.0.0.1:9119",
    ]
    import time as _time
    cached_base = _HERMES_TARGET_CACHE.get("base")
    if cached_base and (_time.monotonic() - _HERMES_TARGET_CACHE.get("ts", 0.0)) < 30.0:
        ordered_bases = [cached_base] + [b for b in base_candidates if b != cached_base]
    else:
        ordered_bases = base_candidates

    # M7: interne Archon-Credentials duerfen niemals an den Hermes-Upstream
    # weitergegeben werden (gleiche Liste wie utils/reverse_proxy.py:84-105).
    _blocked = {
        "host", "content-length", "authorization", "proxy-authorization",
        "x-archon-session", "x-archon-service-token", "accept-encoding",
    }
    fwd_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _blocked
    }
    _cookies = fwd_headers.get("cookie", "")
    if "archon_session=" in _cookies:
        _clean = [
            c.strip() for c in _cookies.split(";")
            if not c.strip().startswith("archon_session=")
        ]
        if _clean:
            fwd_headers["cookie"] = "; ".join(_clean)
        else:
            fwd_headers.pop("cookie", None)
    fwd_headers["Host"] = "localhost:8787"

    hermes_token = _hermes_proxy_token()
    if not hermes_token:
        logger.error(
            "[Hermes-Proxy] Kein Session-Token konfiguriert "
            "(HERMES_SESSION_TOKEN / HERMES_DASHBOARD_SESSION_TOKEN / OMNIROUTE_API_KEY) — "
            "Request abgewiesen."
        )
        return Response(
            content=json.dumps(
                {
                    "error": "proxy_not_configured",
                    "detail": "Kein Hermes-Session-Token konfiguriert; Forward abgewiesen.",
                }
            ),
            status_code=502,
            media_type="application/json",
        )

    fwd_headers["X-Hermes-Session-Token"] = hermes_token
    fwd_headers["Authorization"] = f"Bearer {hermes_token}"
    try:
        from backend.trace_context import (
            child_span,
            current_trace_id,
            extract_headers,
            inject_headers,
            start_trace,
        )
        incoming_tp = extract_headers(request.headers)
        if not current_trace_id():
            start_trace(incoming_tp)
        # Grenze 7: eigene Kausalkante zum Hermes-Upstream. inject_headers()
        # ohne child_span() wuerde die Span-ID des Senders selbst als
        # traceparent tragen (Self-Parenting). child_span() uebernimmt
        # tracestate und Sampled-Flag unverändert und erzeugt eine neue
        # 64-Bit-Span-ID; nur innerhalb dieses Blocks injizieren.
        with child_span(incoming=incoming_tp):
            fwd_headers = inject_headers(fwd_headers)
    except Exception as exc:
        logger.warning("[Hermes-Proxy] Trace-Kontext konnte nicht injiziert werden: %s", exc)

    body = await request.body()
    client = _get_hermes_client()
    last_err = None
    for base in ordered_bases:
        target = f"{base}{path_to_use}{query_str}"
        try:
            resp = await client.request(
                method=request.method,
                url=target,
                headers=fwd_headers,
                content=body if body else None,
            )
            _HERMES_TARGET_CACHE["base"] = base
            _HERMES_TARGET_CACHE["ts"] = _time.monotonic()
            resp_headers: dict[str, str] = {}
            tp_out = resp.headers.get("traceparent") or fwd_headers.get("traceparent")
            if tp_out:
                resp_headers["traceparent"] = tp_out
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("Content-Type", "application/json"),
            )
        except Exception as e:
            last_err = e
            continue
    logger.warning("[Hermes-Proxy] Upstream nicht erreichbar (%s): %s", path_to_use, last_err)
    return Response(
        content=json.dumps({"error": "proxy_unreachable", "detail": "Hermes-Backend nicht erreichbar."}),
        status_code=502,
        media_type="application/json",
    )


@router.get("/api/proxy", dependencies=[_ArchonDepends(require_admin_or_503)])
async def proxy_web_ui(url: str):
    """Header-stripping async proxy to bypass X-Frame-Options & CSP for embedded Web UIs."""
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")
    from utils.egress_guard import EgressBlocked, check_target_url

    try:
        check_target_url(url)
    except EgressBlocked as blocked:
        logger.warning(
            f"[Proxy] SSRF-Ziel blockiert: {blocked.reason} ({url[:120]})"
        )
        return JSONResponse(
            status_code=403,
            content={"error": "Ziel nicht erlaubt", "detail": blocked.reason},
        )

    parsed = urllib.parse.urlparse(url)
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Host": parsed.netloc or "localhost",
    }

    target_url = url
    if "localhost:" in target_url:
        target_url = target_url.replace("localhost:", "host.docker.internal:")
    elif "127.0.0.1:" in target_url:
        target_url = target_url.replace("127.0.0.1:", "host.docker.internal:")

    client = app_main._get_shared_proxy_client()
    try:
        resp = await client.get(
            target_url, headers=req_headers, timeout=10.0, follow_redirects=False
        )
    except Exception:
        try:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10.0,
                follow_redirects=False,
            )
        except Exception as e:
            import html as _html
            err_html = f"<div style='font-family:sans-serif; padding:20px; color:#ef4444;'><h3>Web UI Proxy Status</h3><p>Konnte <code>{_html.escape(url, quote=True)}</code> nicht laden: {_html.escape(str(e), quote=True)}</p></div>"
            return HTMLResponse(content=err_html, status_code=502)

    content_type = resp.headers.get("Content-Type", "text/html")

    if "html" in content_type.lower():
        import html as _html
        html_text = resp.text
        env_script = """<script>
            window.NEXT_PUBLIC_API_URL = "http://localhost:9119";
            window.VITE_API_URL = "http://localhost:9119";
            window.HERMES_API_URL = "http://localhost:9119";
            window.HERMES_WEBUI_API_URL = "http://localhost:9119";
            if (typeof process === "undefined") { window.process = { env: {} }; }
            else if (!window.process.env) { window.process.env = {}; }
            window.process.env.NEXT_PUBLIC_API_URL = "http://localhost:9119";
            window.process.env.VITE_API_URL = "http://localhost:9119";
            window.process.env.HERMES_API_URL = "http://localhost:9119";
        </script>"""
        safe_base_url = _html.escape(url.rstrip("/") + "/", quote=True)
        base_tag = f'<base href="{safe_base_url}">{env_script}'
        if "<head>" in html_text:
            html_text = html_text.replace("<head>", f"<head>{base_tag}", 1)
        else:
            html_text = base_tag + html_text

        res_obj = HTMLResponse(content=html_text, status_code=resp.status_code)
    else:
        res_obj = Response(  # type: ignore[assignment]
            content=resp.content,
            media_type=content_type,
            status_code=resp.status_code,
        )

    for hkey in [
        "x-frame-options",
        "X-Frame-Options",
        "frame-options",
        "content-security-policy",
        "Content-Security-Policy",
    ]:
        if hkey in res_obj.headers:
            del res_obj.headers[hkey]

    res_obj.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    )
    res_obj.headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, X-Requested-With, Accept, Origin"
    )

    return res_obj


_HERMES_ROUTES = [
    "/api/session",
    "/api/session/{path:path}",
    "/api/sessions",
    "/api/sessions/{path:path}",
    "/api/chat",
    "/api/chat/{path:path}",
    "/api/transcribe",
    "/api/crons",
    "/api/crons/{path:path}",
    "/api/db",
    "/api/db/{path:path}",
    "/api/outline",
    "/api/outline/{path:path}",
    "/api/workspace",
    "/api/workspace/{path:path}",
    "/api/panels",
    "/api/panels/{path:path}",
    "/api/projects",
    "/api/projects/{path:path}",
    "/api/client-events",
    "/api/client-events/{path:path}",
    "/api/status",
    "/api/config",
    "/api/config/{path:path}",
    "/api/model",
    "/api/model/{path:path}",
    "/api/providers",
    "/api/providers/{path:path}",
    "/api/plugins",
    "/api/plugins/{path:path}",
    "/api/provider/quota",
    "/api/provider/cost-history",
    "/api/transcribe/capability",
    "/api/extensions/status",
    "/api/reasoning",
    "/api/insights",
    "/api/project-os/dashboard",
    "/api/wiki/status",
    "/api/wiki/browse",
    "/api/wiki/page",
    "/api/logs",
    "/api/health/agent",
    "/static/hermes-webui/api/{path:path}",
]


async def proxy_hermes_api_endpoints(request: Request, path: str = ""):
    """Forward frontend API calls from embedded iFrame to active Hermes backend."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        require_admin_or_503(request)
    else:
        try:
            from archon.routers.auth import get_current_user_from_request
            from backend.auth_service import auth_service

            if auth_service.is_auth_enabled():
                user = get_current_user_from_request(request)
                if user.get("role") in ("viewer", "anonymous"):
                    raise HTTPException(
                        status_code=403,
                        detail="Zugriff auf Hermes-Proxy fuer Viewer/Anonyme gesperrt.",
                    )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Auth-Service fuer Hermes-Proxy nicht verfuegbar.",
            ) from exc
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")
    return await app_main.forward_to_hermes(request)


for _route_path in _HERMES_ROUTES:
    _methods = ["GET", "POST"] if _route_path == "/api/status" else ["GET", "POST", "OPTIONS", "PUT", "PATCH", "DELETE"]
    router.add_api_route(_route_path, proxy_hermes_api_endpoints, methods=_methods)
