"""Router und Forwarder fuer Hermes-Dashboard und WebUI-Proxy."""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from archon.routers._rbac import require_admin_or_503

logger = logging.getLogger("archon.routers.hermes_proxy")

router = APIRouter(tags=["hermes_proxy"])

_PROXY_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _hermes_proxy_token() -> str:
    """Token fuer den Hermes-Dashboard-Forward — ausschliesslich aus der Umgebung."""
    for name in (
        "HERMES_SESSION_TOKEN",
        "HERMES_DASHBOARD_SESSION_TOKEN",
        "OMNIROUTE_API_KEY",
    ):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


async def forward_to_hermes(request: Request) -> Response:
    path_to_use = request.url.path
    if path_to_use.startswith("/static/hermes-webui"):
        path_to_use = path_to_use[len("/static/hermes-webui"):]
    query_str = f"?{str(request.query_params)}" if request.query_params else ""

    candidates = [
        f"http://hermes-webui:8787{path_to_use}{query_str}",
        f"http://127.0.0.1:8787{path_to_use}{query_str}",
        f"http://host.docker.internal:8787{path_to_use}{query_str}",
        f"http://hermes-dashboard:9119{path_to_use}{query_str}",
        f"http://127.0.0.1:9119{path_to_use}{query_str}",
    ]

    fwd_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ["host", "content-length", "authorization"]
    }
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

    body = await request.body()
    last_err = None
    for target in candidates:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(
                    method=request.method,
                    url=target,
                    headers=fwd_headers,
                    content=body if body else None,
                    timeout=15.0,
                )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("Content-Type", "application/json"),
            )
        except Exception as e:
            last_err = e
            continue
    return Response(
        content=json.dumps({"error": "proxy_unreachable", "detail": str(last_err)}),
        status_code=502,
        media_type="application/json",
    )


@router.get("/api/proxy")
async def proxy_web_ui(url: str):
    """Header-stripping async proxy to bypass X-Frame-Options & CSP for embedded Web UIs."""
    from utils.egress_guard import EgressBlocked, check_target_url
    import main as app_main

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
            target_url, headers=req_headers, timeout=10.0, follow_redirects=True
        )
    except Exception:
        try:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10.0,
                follow_redirects=True,
            )
        except Exception as e:
            err_html = f"<div style='font-family:sans-serif; padding:20px; color:#ef4444;'><h3>Web UI Proxy Status</h3><p>Konnte <code>{url}</code> nicht laden: {e}</p></div>"
            return HTMLResponse(content=err_html, status_code=502)

    content_type = resp.headers.get("Content-Type", "text/html")

    if "html" in content_type.lower():
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
        base_tag = f'<base href="{url.rstrip("/")}/">{env_script}'
        if "<head>" in html_text:
            html_text = html_text.replace("<head>", f"<head>{base_tag}", 1)
        else:
            html_text = base_tag + html_text

        res_obj = HTMLResponse(content=html_text, status_code=resp.status_code)
    else:
        res_obj = Response(
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
    "/api/onboarding/status",
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
    if request.method in _PROXY_WRITE_METHODS:
        require_admin_or_503(request)
    import main as app_main
    return await app_main.forward_to_hermes(request)


for _route_path in _HERMES_ROUTES:
    _methods = ["GET", "POST"] if _route_path == "/api/status" else ["GET", "POST", "OPTIONS", "PUT", "DELETE"]
    router.add_api_route(_route_path, proxy_hermes_api_endpoints, methods=_methods)
