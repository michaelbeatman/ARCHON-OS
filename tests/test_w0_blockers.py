"""W0 Blocker-Regressionstests fuer D04-B1 (Zero-Egress-Merge) und D07-B1 (Synthese-Recovery)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


def test_d04_b1_privacy_routing_json_cannot_weaken_hardening_flags(tmp_path: Any, monkeypatch: Any) -> None:
    """D04-B1: sensitive_local_routing=false in privacy_routing.json darf Default/Settings nicht aufweichen."""
    from backend import privacy_router as pr

    priv_file = tmp_path / "privacy_routing.json"
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"privacy": {"zero_egress": True}}),
        encoding="utf-8",
    )
    priv_file.write_text(
        json.dumps(
            {
                "zero_egress_strict": False,
                "sensitive_local_routing": False,
                "hard_block_on_local_offline": False,
                "block_crm_erp_prefetch_on_cloud": False,
                "fallback_to_eu": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pr, "PRIVACY_CFG_FILE", str(priv_file))
    monkeypatch.setattr(pr, "ROOT_SETTINGS_FILE", str(settings_file))

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is True
    assert cfg["sensitive_local_routing"] is True
    assert cfg["hard_block_on_local_offline"] is True
    assert cfg["block_crm_erp_prefetch_on_cloud"] is True
    assert cfg["fallback_to_eu"] is False


def test_d04_b1_default_sensitive_local_routing_survives_false_in_privacy_routing(tmp_path: Any, monkeypatch: Any) -> None:
    """Auch ohne settings.json darf privacy_routing.json sensitive_local_routing nicht abschalten."""
    from backend import privacy_router as pr

    priv_file = tmp_path / "privacy_routing.json"
    priv_file.write_text(
        json.dumps({"sensitive_local_routing": False, "hard_block_on_local_offline": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pr, "PRIVACY_CFG_FILE", str(priv_file))
    monkeypatch.setattr(pr, "ROOT_SETTINGS_FILE", str(tmp_path / "missing_settings.json"))

    cfg = pr.get_privacy_config()
    assert cfg["sensitive_local_routing"] is True
    assert cfg["hard_block_on_local_offline"] is True


@pytest.mark.asyncio
async def test_d07_b1_deadlock_supervisor_calls_recover_stale_synthesis_with_kwargs(monkeypatch: Any) -> None:
    """D07-B1: recover_stale_synthesis muss per Keyword-Args (ttl_seconds, restart) aufgerufen werden."""
    import archon.core.orchestration as orch
    import archon.core.task_registry as task_reg
    from archon.services import background_loops as bg

    captured: dict[str, Any] = {}

    def fake_recover_stale_synthesis(load_mc: Any, update_mc: Any, *, ttl_seconds: int = 900, restart: Any = None) -> list[str]:
        captured["load_mc"] = load_mc
        captured["update_mc"] = update_mc
        captured["ttl_seconds"] = ttl_seconds
        captured["restart"] = restart
        if restart is not None:
            restart("proj-stale-1")
        return ["proj-stale-1"]

    spawned: list[str] = []

    def fake_spawn(coro: Any, name: str = "") -> MagicMock:
        spawned.append(name)
        coro.close()
        return MagicMock()

    async def fake_cascade(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_maybe_start(pid: str, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(orch, "recover_stale_synthesis", fake_recover_stale_synthesis)
    monkeypatch.setattr(task_reg, "spawn", fake_spawn)

    fake_deps = SimpleNamespace(
        load_mission_control_data=lambda: {"tasks": []},
        update_mission_control_data=lambda _fn: None,
        mc_async_lock=asyncio.Lock(),
        run_synthesis_cascade=fake_cascade,
        orch_fan_in_maybe_start_synthesis=fake_maybe_start,
        verify_all_audit_chains=lambda: {"all_intact": True},
        mark_audit_compromised=lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(bg, "_resolve_deps", lambda: fake_deps)

    orig_sleep = asyncio.sleep
    sleep_calls = 0

    async def fake_sleep(_sec: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(bg.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await bg._deadlock_supervisor_loop.__wrapped__()

    assert captured["ttl_seconds"] == 900
    assert callable(captured["restart"])
    await orig_sleep(0)
    assert spawned == ["synthesis_restart:proj-stale-1"]
