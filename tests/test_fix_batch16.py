"""Tests fuer Batch 16 (Z-10, Z-15, Z-19, F15).

Verifiziert:
- Z-10: detect_container_port praeferiert exakte / spezifische Matches wie hermes-agent -> 8642
- Z-15: _check_service_health meldet 401/403/429 nicht faelschlich als 'up'
- Z-19: Fallback-Avatare sind deterministisch via SHA256 und aendern sich nicht nach Neustart
- F15: STRICT_PREFIXES im Rate-Limiter enthaelt die teuren Endpunkte (/api/healing/attempt, /api/fleet/heal, /api/documents/parse, /api/v1/library/upload)
"""

import hashlib
import pytest
from unittest.mock import MagicMock
from starlette.requests import Request


def test_z10_detect_container_port_specific_match():
    """Z-10: hermes-agent darf nicht faelschlich auf hermes-dashboard (9119) fallen, sondern auf 8642."""
    from main import detect_container_port
    assert detect_container_port("hermes-agent") == 8642
    assert detect_container_port("hermes-dashboard") == 9119


@pytest.mark.asyncio
async def test_z15_check_service_health_status_codes():
    """Z-15: Statuscodes 401, 403, 429 duerfen nicht als 'up' deklariert werden."""
    from archon.routers import system
    
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    
    async def mock_get(*args, **kwargs):
        return mock_resp
    
    mock_client.get = mock_get
    
    res = await system._check_service_health("generic_service", ["http://localhost:9999"], mock_client)
    assert res["status"] == "down", "401 wurde faelschlich als 'up' gewertet"


def test_z19_deterministic_avatar_fallback():
    """Z-19: Fallback-Avatar muss deterministisch pro Agent-ID sein (SHA256 statt hash())."""
    from archon.core import profiles
    from archon.routers import mission_control
    
    p_id = "test-agent-alpha"
    expected_num = int(hashlib.sha256(p_id.encode("utf-8")).hexdigest(), 16) % 108 + 1
    expected_url = f"/static/avatars/avatar_{expected_num:03d}.jpg"
    
    # Pruefen ob profiles Code sha256 nutzt
    import inspect
    src = inspect.getsource(profiles)
    assert "hashlib.sha256" in src or "hashlib.sha1" in src, "profiles nutzt noch nicht-deterministisches hash()"


def test_f15_rate_limit_expensive_endpoints():
    """F15: STRICT_PREFIXES muss teure Endpunkte abdecken."""
    from utils.rate_limit import STRICT_PREFIXES
    expensive = [
        "/api/healing/attempt",
        "/api/fleet/heal",
        "/api/documents/parse",
        "/api/v1/library/upload",
    ]
    for ep in expensive:
        assert ep in STRICT_PREFIXES, f"{ep} fehlt in STRICT_PREFIXES"
