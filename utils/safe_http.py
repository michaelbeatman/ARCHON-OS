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

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Optional, Tuple


def webhook_signature_headers(body: bytes, secret_env: str = "ARCHON_WEBHOOK_HMAC_SECRET") -> Dict[str, str]:
    """H5: HMAC-SHA256-Signatur fuer ausgehende Webhooks.

    Der Secret kommt ausschliesslich aus der Umwelt (kein Default, kein Repo).
    Ist keiner konfiguriert, wird nicht signiert — Empfaenger mit
    Signaturpruefung lehnen den Request dann ab (fail-closed beim Empfaenger).
    """
    secret = (os.environ.get(secret_env) or "").strip()
    if not secret or not body:
        return {}
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {
        "X-Archon-Webhook-Signature": f"sha256={digest}",
        "X-Archon-Webhook-Algorithm": "HMAC-SHA256",
    }


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
    allowed: Optional[Iterable[str]] = None,
) -> Tuple[int, Dict[str, str], bytes]:
    """Fuehrt einen SSRF-sicheren HTTP-Request ohne Redirect-Following und mit Groessenlimit aus.

    `allowed` erlaubt es internen Callern (z. B. dem OmniRoute-Gateway-Client),
    eine explizite Ziel-Allowlist zu uebergeben, statt der globalen Env-Liste.
    Der Redirect-Block und das Groessenlimit bleiben unbedingt aktiv.
    """
    from utils.egress_guard import check_public_url, check_target_url

    safe_url = check_public_url(url) if public_only else check_target_url(url, allowed=allowed)
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
    allowed: Optional[Iterable[str]] = None,
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
        allowed=allowed,
    )
    return json.loads(raw.decode("utf-8"))
