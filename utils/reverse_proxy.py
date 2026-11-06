"""
Generischer Reverse-Proxy für eingebettete Oberflächen (n8n, OmniRoute, …).

Vorher gab es in main.py zwei nahezu identische Implementierungen
(`forward_to_omniroute`, `forward_to_n8n`) mit je ~90 Zeilen, inklusive
doppeltem Fallback-Block. Jede Korrektur musste zweimal gemacht werden.

Jetzt: eine Klasse, konfiguriert pro Ziel. Verhalten identisch:
  * entfernt X-Frame-Options / CSP (damit iframe-Einbettung funktioniert)
  * korrigiert Location-Header auf das lokale Mount-Prefix
  * injiziert <base href> und optionale HTML-Ersetzungen
  * Fallback auf host.docker.internal, wenn der Container-Name nicht auflöst
"""

from __future__ import annotations

import asyncio
from typing import Optional, Sequence

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

__all__ = ["ReverseProxy", "get_shared_client"]

_PROXY_CLIENTS: dict[int, httpx.AsyncClient] = {}


def get_shared_client() -> httpx.AsyncClient:
    """Ein AsyncClient pro Event-Loop (verhindert 'bound to different loop')."""
    loop_id = id(asyncio.get_running_loop())
    client = _PROXY_CLIENTS.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=60.0,
            limits=httpx.Limits(max_keepalive_connections=30, max_connections=120),
        )
        _PROXY_CLIENTS[loop_id] = client
    return client


_DROP_HEADERS = {
    "x-frame-options",
    "content-security-policy",
    "content-length",
    "content-encoding",
    "transfer-encoding",
}


class ReverseProxy:
    def __init__(
        self,
        name: str,
        target_host: str,
        mount_prefix: str,
        *,
        fallback_host: Optional[str] = None,
        base_href: Optional[str] = None,
        html_replacements: Sequence[tuple[str, str]] = (),
        static_overrides: Optional[dict[str, tuple[str, str]]] = None,
    ) -> None:
        self.name = name
        self.target_host = target_host
        self.mount_prefix = mount_prefix.rstrip("/")
        self.fallback_host = fallback_host
        self.base_href = base_href or (self.mount_prefix + "/")
        self.html_replacements = tuple(html_replacements)
        # z. B. {"base-path.js": ("window.BASE_PATH = '/n8n-proxy/';", "application/javascript")}
        self.static_overrides = static_overrides or {}

    # ---------------- intern ----------------

    def _build_target(self, host: str, path: str, query: str) -> str:
        url = f"http://{host}/{path.lstrip('/')}"
        if query:
            url += f"?{query}"
        return url

    def _prepare_headers(self, request: Request) -> dict:
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("accept-encoding", None)
        return headers

    def _rewrite_headers(self, upstream: httpx.Response) -> dict:
        out: dict[str, str] = {}
        for key, value in upstream.headers.items():
            lower = key.lower()
            if lower in _DROP_HEADERS:
                continue
            if lower == "location":
                if value.startswith("/") and not value.startswith(self.mount_prefix):
                    value = f"{self.mount_prefix}{value}"
                out["Location"] = value
            else:
                out[key] = value
        out["Access-Control-Allow-Origin"] = "*"
        out["X-Frame-Options"] = "ALLOWALL"
        return out

    def _transform_content(self, upstream: httpx.Response, path: str) -> tuple[bytes, Optional[str]]:
        content_type = upstream.headers.get("content-type", "")

        for suffix, (body, media_type) in self.static_overrides.items():
            if path.endswith(suffix):
                return body.encode("utf-8"), media_type

        content = upstream.content
        if "text/html" in content_type:
            html = content.decode("utf-8", errors="ignore")
            if "<head>" in html:
                html = html.replace("<head>", f'<head><base href="{self.base_href}">', 1)
            for old, new in self.html_replacements:
                html = html.replace(old, new)
            content = html.encode("utf-8")
        return content, None

    async def _do_request(self, request: Request, url: str, path: str) -> Response:
        client = get_shared_client()
        body = await request.body()
        upstream = await client.request(
            method=request.method,
            url=url,
            headers=self._prepare_headers(request),
            content=body,
        )
        headers = self._rewrite_headers(upstream)
        content, media_override = self._transform_content(upstream, path)
        return Response(
            content=content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=media_override or upstream.headers.get("content-type"),
        )

    # ---------------- oeffentlich ----------------

    async def forward(self, request: Request, path: str = "") -> Response:
        query = request.url.query or ""
        primary = self._build_target(self.target_host, path, query)
        try:
            return await self._do_request(request, primary, path)
        except Exception as first_err:
            if not self.fallback_host:
                return JSONResponse(
                    status_code=502,
                    content={"error": f"{self.name} proxy error: {first_err}"},
                )
            fallback = self._build_target(self.fallback_host, path, query)
            try:
                return await self._do_request(request, fallback, path)
            except Exception as second_err:
                return JSONResponse(
                    status_code=502,
                    content={"error": f"{self.name} proxy error: {second_err}"},
                )