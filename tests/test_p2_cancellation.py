"""Regressionstests fuer die zentrale Cancel-Token-Propagation."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_cancel_token_registry_and_children():
    from backend.cancellation import (
        CancelToken, cancel_scope, clear_scope, get_child_token, get_token,
    )

    root = get_token("test-cancel-root")
    child = get_child_token("test-cancel-root", "test-cancel-child")
    assert isinstance(root, CancelToken)
    assert get_token("test-cancel-root") is root
    assert child in root._children

    assert cancel_scope("test-cancel-root", "disconnect") is True
    assert root.cancelled is True
    assert root.reason == "disconnect"
    assert child.cancelled is True
    assert child.reason == "disconnect"
    with pytest.raises(asyncio.CancelledError, match="test-cancel-child"):
        child.check()

    assert cancel_scope("does-not-exist") is False
    clear_scope("test-cancel-root")
    clear_scope("test-cancel-child")
    assert get_token("test-cancel-root", create=False) is None


async def test_p2_cancel_token_wait_unblocks():
    from backend.cancellation import cancel_scope, clear_scope, get_token

    token = get_token("test-cancel-wait")
    task = asyncio.create_task(token.wait(timeout=5))
    await asyncio.sleep(0)
    assert cancel_scope("test-cancel-wait", "stop") is True
    assert await task is True
    assert token.cancelled is True
    clear_scope("test-cancel-wait")
