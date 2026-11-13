"""Gemeinsame Helfer fuer die Sicherheits-Regressionstests (Cluster 1/2/4).

Kein Testmodul (Name beginnt nicht mit ``test_``) — pytest sammelt es nicht ein.
Die Tests rufen die Handler bzw. die Middleware direkt auf: kein HTTP-Stack,
kein Docker, keine LLM-Aufrufe. Alle Fachfunktionen werden gestubbt.
"""

from __future__ import annotations

import asyncio
import os
import sys

from starlette.requests import Request
from starlette.responses import JSONResponse

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADMIN = {"id": "usr_admin", "username": "admin", "role": "admin", "permissions": {},
         "is_service": False}
OPERATOR = {"id": "usr_op", "username": "lisa", "role": "operator", "permissions": {}}
VIEWER = {"id": "usr_vw", "username": "max", "role": "viewer", "permissions": {}}

# Sentinel, damit "Gate hat durchgelassen" von "Gate hat gesperrt" unterscheidbar
# bleibt, ohne echten Downstream-Code zu starten.
GATE_PASSED = 200


def make_request(path: str = "/probe", method: str = "POST", token: str | None = None,
                 headers: dict | None = None, body: bytes = b"") -> Request:
    """Baut einen minimalen ASGI-Request fuer Middleware-/Handler-Aufrufe."""
    raw_headers: list[tuple[bytes, bytes]] = []
    if token:
        raw_headers.append((b"authorization", f"Bearer {token}".encode()))
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), str(value).encode()))

    messages: list[dict] = []
    if body:
        messages.append({"type": "http.request", "body": body, "more_body": False})

    async def _receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }, receive=_receive)


def run_gate(main, request: Request):
    """Fuehrt ``auth_gate`` aus; ``call_next`` liefert einen Sentinel."""
    async def _call_next(_req):
        return JSONResponse({"passed": True}, status_code=GATE_PASSED)

    return asyncio.run(main.auth_gate(request, _call_next))


def status_of(response) -> int:
    return int(response.status_code)


def import_main():
    """Importiert ``main`` und verdrahtet den Rollenzaun (idempotent)."""
    import main  # noqa: F401  (Import verdrahtet RBAC per configure())
    return main
