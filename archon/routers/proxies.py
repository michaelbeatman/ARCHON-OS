"""Router fuer Reverse Proxies: OmniRoute & n8n."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
import httpx

logger = logging.getLogger("archon.routers.proxies")

router = APIRouter(tags=["proxies"])

_PROXY_HTTP_CLIENTS: Dict[int, httpx.AsyncClient] = {}


def _get_shared_proxy_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    c = _PROXY_HTTP_CLIENTS.get(loop_id)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(
            follow_redirects=False,
            timeout=60.0,
            limits=httpx.Limits(max_keepalive_connections=30, max_connections=120),
        )
        _PROXY_HTTP_CLIENTS[loop_id] = c
    return c


_OMNIROUTE_PROXY = None


def _get_omniroute_proxy():
    global _OMNIROUTE_PROXY
    if _OMNIROUTE_PROXY is None:
        from utils.reverse_proxy import ReverseProxy

        _OMNIROUTE_PROXY = ReverseProxy(
            name="OmniRoute",
            target_host="omniroute:20128",
            mount_prefix="/omniroute-proxy",
            fallback_host="host.docker.internal:20128",
        )
    return _OMNIROUTE_PROXY


async def forward_to_omniroute(request: Request, path: str):
    return await _get_omniroute_proxy().forward(request, path)


@router.api_route(
    "/omniroute-proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def omniroute_proxy(request: Request, path: str = ""):
    import main as app_main

    fn = getattr(app_main, "forward_to_omniroute", forward_to_omniroute)
    return await fn(request, path)


@router.api_route("/_next/{path:path}", methods=["GET", "HEAD"])
async def omniroute_next_assets(request: Request, path: str = ""):
    import main as app_main

    fn = getattr(app_main, "forward_to_omniroute", forward_to_omniroute)
    return await fn(request, f"_next/{path}")


_N8N_PROXY = None


def _get_n8n_proxy():
    global _N8N_PROXY
    if _N8N_PROXY is None:
        from utils.reverse_proxy import ReverseProxy

        _N8N_PROXY = ReverseProxy(
            name="n8n",
            target_host="n8n:5678",
            mount_prefix="/n8n-proxy",
            fallback_host="host.docker.internal:5678",
            html_replacements=(
                ('href="/assets/', 'href="/n8n-proxy/assets/'),
                ('src="/assets/', 'src="/n8n-proxy/assets/'),
                ('href="/static/', 'href="/n8n-proxy/static/'),
                ('src="/static/', 'src="/n8n-proxy/static/'),
                ('data-src="/assets/', 'data-src="/n8n-proxy/assets/'),
                ('href="/favicon.ico"', 'href="/n8n-proxy/favicon.ico"'),
            ),
            static_overrides={
                "base-path.js": ("window.BASE_PATH = '/n8n-proxy/';", "application/javascript"),
            },
        )
    return _N8N_PROXY


_N8N_AUTOSTART_LOCK: Optional[asyncio.Lock] = None
_N8N_AUTOSTART_LAST_TRY: float = 0.0


async def _ensure_n8n_running() -> bool:
    """Startet den gestoppten n8n-Container einmalig über den DockerClient und wartet auf /healthz."""
    global _N8N_AUTOSTART_LOCK, _N8N_AUTOSTART_LAST_TRY
    if _N8N_AUTOSTART_LOCK is None:
        _N8N_AUTOSTART_LOCK = asyncio.Lock()

    async with _N8N_AUTOSTART_LOCK:
        now = time.monotonic()
        if now - _N8N_AUTOSTART_LAST_TRY < 15.0:
            return False
        _N8N_AUTOSTART_LAST_TRY = now

        try:
            from utils.docker_client import docker_client

            info_raw = await asyncio.to_thread(docker_client.container_json, "n8n")
            info = json.loads(info_raw.decode("utf-8", errors="ignore") or "{}")
            running = bool((info.get("State") or {}).get("Running"))
            if not running:
                logger.info("[n8n-proxy] Container 'n8n' ist gestoppt — starte automatisch nach...")
                await asyncio.to_thread(docker_client.container_action, "n8n", "start")
        except Exception as exc:
            logger.warning(f"[n8n-proxy] Auto-Start fehlgeschlagen: {exc}")
            return False

        client = _get_shared_proxy_client()
        for _ in range(24):
            try:
                resp = await client.get("http://n8n:5678/healthz", timeout=2.0)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False


async def forward_to_n8n(request: Request, path: str):
    proxy = _get_n8n_proxy()
    res = await proxy.forward(request, path)
    if res.status_code == 502:
        if await _ensure_n8n_running():
            return await proxy.forward(request, path)
    return res


@router.api_route("/n8n-proxy", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
@router.api_route(
    "/n8n-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]
)
async def n8n_proxy(request: Request, path: str = ""):
    import main as app_main

    fn = getattr(app_main, "forward_to_n8n", forward_to_n8n)
    return await fn(request, path)


@router.api_route("/assets/{path:path}", methods=["GET", "HEAD"])
async def n8n_assets_proxy(request: Request, path: str = ""):
    if path:
        try:
            from utils.path_jail import safe_path

            assets_root = os.path.abspath("assets")
            if os.path.exists(assets_root):
                target = safe_path(
                    os.path.join(assets_root, path),
                    must_exist=True,
                    extra_roots=[assets_root],
                    allow_dirs=False,
                )
                if target and os.path.isfile(target):
                    return FileResponse(target)
        except Exception:
            pass
    import main as app_main

    fn = getattr(app_main, "forward_to_n8n", forward_to_n8n)
    return await fn(request, f"assets/{path}")


@router.api_route("/rest/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def n8n_rest_proxy(request: Request, path: str = ""):
    import main as app_main

    fn = getattr(app_main, "forward_to_n8n", forward_to_n8n)
    return await fn(request, f"rest/{path}")
