"""Router fuer Reverse Proxies: OmniRoute & n8n."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

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

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["proxies"])

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

    ref = request.headers.get("referer", "")
    if "/anythingllm-proxy" in ref and path:
        return await forward_to_anythingllm(request, f"assets/{path}")

    fn = getattr(app_main, "forward_to_n8n", forward_to_n8n)
    res = await fn(request, f"assets/{path}")
    if res.status_code in (404, 502, 503, 504) and path:
        return await forward_to_anythingllm(request, f"assets/{path}")
    return res


@router.api_route("/rest/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def n8n_rest_proxy(request: Request, path: str = ""):
    import main as app_main

    fn = getattr(app_main, "forward_to_n8n", forward_to_n8n)
    return await fn(request, f"rest/{path}")


_ANYTHINGLLM_PROXY = None

_ANYTHINGLLM_SHIM = (
    "<script>(function(){"
    "var P='/anythingllm-proxy';"
    "function rw(u){"
    "if(typeof u==='string'){"
    "if(u.indexOf(P+'/')===0)return u;"
    "if(u==='/api'||u.indexOf('/api/')===0||u.indexOf('/api?')===0)return P+u;"
    "if(u.indexOf(location.origin+'/api')===0)return location.origin+P+u.slice(location.origin.length);"
    "}return u;}"
    "var of=window.fetch;"
    "if(of){window.fetch=function(i,n){"
    "if(typeof i==='string'){i=rw(i);}"
    "else if(i&&typeof i.url==='string'){var u=rw(i.url);if(u!==i.url){i=new Request(u,i);}}"
    "return of.call(this,i,n);};}"
    "var xo=XMLHttpRequest.prototype.open;"
    "XMLHttpRequest.prototype.open=function(m,u){"
    "var a=Array.prototype.slice.call(arguments);a[1]=rw(u);return xo.apply(this,a);};"
    "if(window.EventSource){var oe=window.EventSource;window.EventSource=function(u,c){return new oe(rw(u),c);};}"
    "if(location.pathname.indexOf(P)===0){"
    "var s=location.pathname.slice(P.length)||'/';"
    "try{window.history.replaceState(window.history.state,'',s+location.search+location.hash);}catch(e){}"
    "}"
    "})();</script>"
)


def _get_anythingllm_proxy():
    global _ANYTHINGLLM_PROXY
    if _ANYTHINGLLM_PROXY is None:
        from utils.reverse_proxy import ReverseProxy

        _ANYTHINGLLM_PROXY = ReverseProxy(
            name="AnythingLLM",
            target_host="anything-llm:3001",
            mount_prefix="/anythingllm-proxy",
            fallback_host="host.docker.internal:3001",
            html_replacements=(
                ('<base href="/anythingllm-proxy/">', f'<base href="/anythingllm-proxy/">{_ANYTHINGLLM_SHIM}'),
                ('src="/index.js"', 'src="/anythingllm-proxy/index.js"'),
                ('href="/index.css"', 'href="/anythingllm-proxy/index.css"'),
                ('href="/favicon.png"', 'href="/anythingllm-proxy/favicon.png"'),
                ('href="/manifest.json"', 'href="/anythingllm-proxy/manifest.json"'),
                ('src="/assets/', 'src="/anythingllm-proxy/assets/'),
                ('href="/assets/', 'href="/anythingllm-proxy/assets/'),
            ),
        )
    return _ANYTHINGLLM_PROXY


async def forward_to_anythingllm(request: Request, path: str):
    # Prevent 304 Not Modified from skipping HTML shim or CSS URL rewriting.
    clean_path = (path or "").lstrip("/")
    is_html_candidate = ("." not in clean_path.split("/")[-1]) or clean_path.endswith(".html")
    is_css = clean_path.endswith(".css")
    if is_html_candidate or is_css:
        raw_hdrs = [
            (k, v)
            for (k, v) in request.scope.get("headers", [])
            if k.lower() not in (b"if-none-match", b"if-modified-since")
        ]
        request.scope["headers"] = raw_hdrs
        request.__dict__.pop("_headers", None)

    res = await _get_anythingllm_proxy().forward(request, path)
    if is_css and res.status_code == 200 and getattr(res, "body", None):
        css_txt = res.body.decode("utf-8", errors="ignore")
        if "url(/" in css_txt and "url(/anythingllm-proxy/" not in css_txt:
            css_txt = css_txt.replace("url(/", "url(/anythingllm-proxy/")
            from fastapi.responses import Response as _Resp

            new_headers = {
                k: v for k, v in res.headers.items() if k.lower() != "content-length"
            }
            return _Resp(
                content=css_txt.encode("utf-8"),
                status_code=200,
                headers=new_headers,
                media_type="text/css; charset=utf-8",
            )
    return res


@router.api_route(
    "/anythingllm-proxy",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
@router.api_route(
    "/anythingllm-proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def anythingllm_proxy(request: Request, path: str = ""):
    return await forward_to_anythingllm(request, path)
