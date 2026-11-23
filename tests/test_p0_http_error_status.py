"""P0: {"status":"error"} darf nicht mit HTTP 200 zurueckgehen."""

import os
import sys
from unittest import mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import containers  # noqa: E402


@pytest.mark.asyncio
async def test_inject_container_config_failure_uses_real_http_status():
    import archon.routers._rbac as rbac

    previous = rbac._checker
    rbac._checker = lambda request: None
    try:
        with mock.patch("utils.egress_guard.check_target_url", return_value=None), mock.patch(
            "httpx.AsyncClient.post", side_effect=OSError("offline")
        ):
            response = await containers.inject_container_config(
                mock.MagicMock(),
                "hermes",
                containers.PassthroughBody(config_url="http://127.0.0.1:1/config"),
            )
    finally:
        rbac._checker = previous

    assert response.status_code >= 400
    body = response.body.decode("utf-8") if isinstance(response.body, bytes) else response.body
    assert "error" in body
