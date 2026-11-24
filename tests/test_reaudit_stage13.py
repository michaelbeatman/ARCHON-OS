"""Re-Audit Etappe 13 — verbleibende HIGHs D02/D04/D08/D10/D15."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_d04_rotation_register_exists_and_gate_is_green():
    import subprocess
    import sys
    reg = ROOT / "config" / "secrets_rotation.json"
    assert reg.is_file()
    data = json.loads(reg.read_text(encoding="utf-8"))
    classes = {c["class"] for c in data["credentials"]}
    assert {"github", "telegram", "provider"} <= classes
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_secrets.py"), "--all"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-500:] + proc.stderr[-500:]


def test_d15_roles_match_ssot_prompts():
    import scripts.sync_profile_ssot as sso
    report = sso.detect_drift(allow_missing_hermes=True)
    assert report["prompt_mismatch"] == []
    assert report["drift"] is False


def test_d15_inventory_has_71_entries():
    data = json.loads((ROOT / "data" / "eu_ai_act_inventory.json").read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("items", data.get("inventory", []))
    ids = [e.get("agent_id") for e in entries if isinstance(e, dict)]
    assert len(ids) == 71
    assert "micha" not in ids and "alpha" not in ids


def test_d10_livez_fails_with_dead_watchdog():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    block = src.split('async def liveness_check()', 1)[1].split('\n@app.', 1)[0]
    assert 'or not info["loops"]["watchdog"]["alive"]' in block
    heal = (ROOT / "scripts" / "archon_autoheal.py").read_text(encoding="utf-8")
    assert 'not result.get("watchdog_stale")' in heal


def test_d08_audit_dispatch_is_async():
    guard = (ROOT / "backend" / "llm_egress_guard.py").read_text(encoding="utf-8")
    assert "async def audit_dispatch_async" in guard
    assert "await asyncio.to_thread(_write)" in guard
    for rel in ("backend/agent_router.py", "utils/notebook_engine.py", "archon/routers/chat.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "await audit_dispatch_async(" in src, rel


def test_d02_cache_respects_policy():
    src = (ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    assert "ARCHON_POLICY_VERSION" in src
    assert "Policy-Revalidierung beim Cache-Hit" in src
    assert "get_privacy_config()" in src.split("Policy-Revalidierung beim Cache-Hit", 1)[0][-400:]
