# -*- coding: utf-8 -*-
"""
utils/safe_http.py
==================
Zentraler SSRF-geschuetzter HTTP-Client fuer Archon OS:
- Validiert jede Ziel-URL ueber `utils.egress_guard`
- **Pinnt die gepruefte IP** (DNS-TOCTOU: nur ein Lookup, danach connect by IP;
  Host-Header und TLS-SNI bleiben beim Original-Host; Peer-IP wird nach dem
  Connect gegen die gepruefte IP verifiziert — fail-closed bei Abweichung)
- Blockiert HTTP 3xx Redirects (kein Redirect-SSRF auf IMDS/localhost)
- Begrenzt gelesene Antwortgroesse (`max_bytes`) gegen OOM-DoS
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import urllib.error
import urllib.parse
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


class _PinnedPeerError(ValueError):
    """Die verbundene Peer-IP weicht von der geprueften IP ab (Fail-Closed)."""


class _PinnedConnectionMixin:
    _pinned_ip: str = ""

    def _verify_pinned_peer(self) -> None:
        if not self._pinned_ip:
            return
        try:
            # `sock` wird von HTTPConnection/HTTPSConnection bereitgestellt;
            # das Mixin allein deklariert es nicht (typeshed: attr-defined).
            peer = self.sock.getpeername()[0]  # type: ignore[attr-defined]
            expected = ipaddress.ip_address(self._pinned_ip)
            actual = ipaddress.ip_address(peer)
        except Exception as exc:
            self.close()  # type: ignore[attr-defined]
            raise _PinnedPeerError(
                f"SSRF-Schutz: Peer-IP nicht verifizierbar (erwartet {self._pinned_ip}): {exc}"
            ) from exc
        if actual != expected:
            self.close()  # type: ignore[attr-defined]
            raise _PinnedPeerError(
                f"SSRF-Schutz: Peer-IP {actual} weicht von gepruefter IP {expected} ab"
            )


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    """HTTPConnection, die nur zur geprueften IP verbindet."""

    def __init__(self, *args: Any, pinned_ip: str = "", **kwargs: Any) -> None:
        self._pinned_ip = str(pinned_ip or "")
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        super().connect()
        self._verify_pinned_peer()


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    """HTTPSConnection mit IP-Pinning und TLS-SNI auf den Original-Host."""

    def __init__(
        self, *args: Any, pinned_ip: str = "", server_hostname: str = "", **kwargs: Any
    ) -> None:
        self._pinned_ip = str(pinned_ip or "")
        self._pinned_server_hostname = str(server_hostname or "")
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        # Schritt 1: roher TCP-Connect zur geprueften IP (kein zweites DNS-Lookup).
        http.client.HTTPConnection.connect(self)
        self._verify_pinned_peer()
        # Schritt 2: TLS mit SNI = Original-Host (Zertifikatspruefung bleibt wirksam).
        # `_tunnel_host` und `_context` werden zur Laufzeit von HTTPConnection.set_tunnel()
        # bzw. HTTPSConnection.__init__ gesetzt, sind aber nicht in typeshed deklariert.
        server_hostname = self._tunnel_host or self._pinned_server_hostname or self.host  # type: ignore[attr-defined]
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)  # type: ignore[attr-defined]


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self._pinned_ip = pinned_ip

    def http_open(self, req):
        factory = functools.partial(_PinnedHTTPConnection, pinned_ip=self._pinned_ip)
        return self.do_open(factory, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip: str, server_hostname: str) -> None:
        super().__init__()
        self._pinned_ip = pinned_ip
        self._server_hostname = server_hostname

    def https_open(self, req):
        factory = functools.partial(
            _PinnedHTTPSConnection, pinned_ip=self._pinned_ip,
            server_hostname=self._server_hostname,
        )
        return self.do_open(factory, req)


def _pinned_url(url: str, pinned_ip: str, host: str, port: int) -> str:
    """Baut die URL mit der IP als Host; Pfad/Query/Fragment bleiben erhalten."""
    parts = urllib.parse.urlsplit(url)
    netloc = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    if (parts.scheme == "https" and port != 443) or (parts.scheme == "http" and port != 80):
        netloc = f"{netloc}:{port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


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
    """Fuehrt einen SSRF-sicheren HTTP-Request ohne Redirect-Following aus.

    `allowed` erlaubt es internen Callern (z. B. dem OmniRoute-Gateway-Client),
    eine explizite Ziel-Allowlist zu uebergeben, statt der globalen Env-Liste.
    Der Redirect-Block und das Groessenlimit bleiben unbedingt aktiv.

    W4-B/TOC-TOU: die Validierung liefert die gepruefte IP; der Request wird
    ueber eine Connection zu genau dieser IP ausgefuehrt. Host-Header und
    TLS-SNI bleiben beim Original-Host, die Peer-IP wird nach dem Connect
    geprueft.
    """
    from utils.egress_guard import check_public_url_with_ip, check_target_url_with_ip

    validated = (
        check_public_url_with_ip(url) if public_only
        else check_target_url_with_ip(url, allowed=allowed)
    )
    safe_url = str(validated)
    pinned_ip = str(getattr(validated, "pinned_ip", "") or "")
    hdrs = dict(headers or {})
    parsed = urllib.parse.urlsplit(safe_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    handlers: list[urllib.request.BaseHandler] = []
    if pinned_ip:
        safe_url = _pinned_url(safe_url, pinned_ip, host, port)
        # Proxy-Umleitung wuerde den Connect zur geprueften IP umgehen.
        handlers.append(urllib.request.ProxyHandler({}))
        if parsed.scheme == "https":
            handlers.append(_PinnedHTTPSHandler(pinned_ip, server_hostname=host))
        else:
            handlers.append(_PinnedHTTPHandler(pinned_ip))
        for key in [k for k in hdrs if k.lower() == "host"]:
            hdrs.pop(key, None)
        default_port = 443 if parsed.scheme == "https" else 80
        hdrs["Host"] = host if port == default_port else f"{host}:{port}"

    req = urllib.request.Request(
        safe_url,
        data=data,
        headers=hdrs,
        method=method.upper(),
    )
    handlers.append(_RejectAllRedirectsHandler())
    opener = urllib.request.build_opener(*handlers)
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
