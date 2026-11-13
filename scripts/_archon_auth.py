"""Service-Token für interne Aufrufe der Archon-API.

Seit der Auth-Aktivierung beantwortet Archon jeden Aufruf ohne Sitzung mit 401.
Interne Skripte, Cronjobs und n8n-Nodes weisen sich mit dem Service-Token aus,
das die Anwendung unter data/.archon_service_token ablegt.

Verwendung:
    from _archon_auth import headers, get_request
    req = urllib.request.Request(url, headers=headers())
"""

from __future__ import annotations

import os
import pathlib
import urllib.request

_TOKEN_ENV = "ARCHON_SERVICE_TOKEN"
_CANDIDATES = (
    pathlib.Path(__file__).resolve().parent.parent / "data" / ".archon_service_token",
    pathlib.Path("/app/data/.archon_service_token"),
    pathlib.Path.home() / ".hermes" / ".archon_service_token",
)


def token() -> str:
    """Liest das Service-Token aus Umgebung oder Ablage."""
    env = os.environ.get(_TOKEN_ENV, "").strip()
    if env:
        return env
    for path in _CANDIDATES:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def headers(extra: dict | None = None) -> dict:
    """Header-Dict mit Service-Token (und optionalen Zusätzen)."""
    result = {"Content-Type": "application/json"}
    value = token()
    if value:
        result["X-Archon-Service-Token"] = value
    if extra:
        result.update(extra)
    return result


def get_request(url: str, method: str = "GET", data: bytes | None = None) -> urllib.request.Request:
    """Fertiger Request mit Auth-Header."""
    return urllib.request.Request(url, data=data, headers=headers(), method=method)
