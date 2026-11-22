# -*- coding: utf-8 -*-
"""
utils/safe_http.py
==================
Zentraler SSRF-geschuetzter HTTP-Client fuer Archon OS:
- Validiert jede Ziel-URL ueber `utils.egress_guard`
- Blockiert HTTP 3xx Redirects (kein Redirect-SSRF auf IMDS/localhost)
- Begrenzt gelesene Antwortgroesse (`max_bytes`) gegen OOM-DoS
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


class _RejectAllRedirectsHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            getattr(req, "full_url", newurl) if req is not None else newurl,
            code,
            f"HTTP-Redirect ({code}) auf '{newurl}' aus SSRF-Schutzgruenden blockiert.",
            headers,
            fp,
        )


def safe_http_request(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: float = 15.0,
    max_bytes: int = 8 * 1024 * 1024,
    public_only: bool = False,
) -> Tuple[int, Dict[str, str], bytes]:
    """Fuehrt einen SSRF-sicheren HTTP-Request ohne Redirect-Following und mit Groessenlimit aus."""
    from utils.egress_guard import check_public_url, check_target_url

    safe_url = check_public_url(url) if public_only else check_target_url(url)
    req = urllib.request.Request(
        safe_url,
        data=data,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    opener = urllib.request.build_opener(_RejectAllRedirectsHandler())
    with opener.open(req, timeout=float(timeout)) as resp:
        raw = resp.read(int(max_bytes) + 1)
        if len(raw) > int(max_bytes):
            raise ValueError(f"HTTP-Antwort ueberschreitet Groessenlimit ({max_bytes} Bytes).")
        resp_headers = {str(k).lower(): str(v) for k, v in (resp.headers.items() if resp.headers else [])}
        return int(resp.status), resp_headers, raw


def safe_http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Any] = None,
    timeout: float = 15.0,
    max_bytes: int = 4 * 1024 * 1024,
    public_only: bool = False,
) -> Any:
    """Fuehrt einen SSRF-sicheren HTTP-Request aus und parst JSON."""
    hdrs = {"Accept": "application/json", **dict(headers or {})}
    body: Optional[bytes] = None
    if payload is not None:
        hdrs.setdefault("Content-Type", "application/json")
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _, _, raw = safe_http_request(
        url,
        method=method,
        headers=hdrs,
        data=body,
        timeout=timeout,
        max_bytes=max_bytes,
        public_only=public_only,
    )
    return json.loads(raw.decode("utf-8"))
