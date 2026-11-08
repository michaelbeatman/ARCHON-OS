"""Tests fuer Batch 18 (F14 - Reverse-Proxy Header Sanitization & Security Headers).

Verifiziert:
- F14: reverse_proxy strippt archon_session Cookie aus den Upstream-Headern (verhindert Credential-Leck)
- F14: reverse_proxy setzt nicht pauschal Access-Control-Allow-Origin: * und X-Frame-Options: ALLOWALL
"""

from unittest.mock import MagicMock
import httpx
from utils.reverse_proxy import ReverseProxy


def test_f14_reverse_proxy_strips_archon_session_cookie():
    """F14: archon_session darf nicht an nachgelagerte Upstreams geleakt werden."""
    proxy = ReverseProxy(name="test", target_host="127.0.0.1:9999", mount_prefix="/test-proxy")
    
    dummy_req = MagicMock()
    dummy_req.headers = {
        "host": "localhost:8501",
        "accept-encoding": "gzip",
        "cookie": "theme=dark; archon_session=super_secret_session_token_12345; user=micha",
        "authorization": "Bearer something"
    }
    
    headers = proxy._prepare_headers(dummy_req)
    assert "host" not in headers
    assert "accept-encoding" not in headers
    assert "super_secret_session_token_12345" not in headers.get("cookie", "")
    assert "theme=dark" in headers.get("cookie", "")
    assert "user=micha" in headers.get("cookie", "")


def test_f14_reverse_proxy_response_headers_hardened():
    """F14: Keine unkontrollierte Öffnung von CORS und X-Frame-Options."""
    proxy = ReverseProxy(name="test", target_host="127.0.0.1:9999", mount_prefix="/test-proxy")
    
    upstream_resp = httpx.Response(
        status_code=200,
        headers={"content-type": "text/html", "x-custom": "val"}
    )
    rewritten = proxy._rewrite_headers(upstream_resp)
    
    assert rewritten.get("X-Frame-Options") == "SAMEORIGIN"
    assert rewritten.get("Access-Control-Allow-Origin") != "*"
