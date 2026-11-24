"""Re-Audit Etappe 6 — D02 Boardroom/Cancel, D11 Fan-in, D14 HITL-Wirksamkeit."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_d02_boardroom_prompts_produce_consensus_markers():
    src = (ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    assert src.count("KONSENS_ERREICHT") >= 2
    assert src.count("KEIN KONSENS") >= 2
    assert "Ohne Marker zählt deine" in src


def test_d02_delegation_timeout_persists_cancelled():
    src = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    assert "UPDATE tasks SET status = 'cancelled'" in src
    assert "VALUES (?, 'cancelled', ?" in src
    assert '"to": "cancelled"' in src
    assert '"cancelled"' in src.split("_TERMINAL_TASK_STATUSES =")[1].split("\n")[0]


def test_d11_fan_in_keys_survive_sqlite_reload():
    from archon.core.mission_control import _EXTENDED_TASK_KEYS
    for key in ("fan_in_child_ids", "fan_in_statements", "trace_id", "session_id", "correlation_id"):
        assert key in _EXTENDED_TASK_KEYS


def test_d14_boardroom_no_consensus_is_registered():
    from archon.core.constants import _DECISION_TYPEN
    assert "boardroom_no_consensus" in _DECISION_TYPEN


def test_d14_telegram_has_no_direct_status_fallback():
    src = (ROOT / "scripts" / "patches" / "hermes_telegram_adapter.py").read_text(encoding="utf-8")
    block = src.split("/api/decisions/decide", 1)[1].split("logger.info(\"Telegram Archon HITL button", 1)[0]
    assert "api/operations/kanban/tasks/" not in block
    assert "api/mission-control/tasks/move" not in block
    assert "kein Fallback-Status-Set" in block
