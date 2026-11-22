"""Regressionstests fuer den P1-Batch (Audit-Integritaet, Content-Machine, Auth-Default, Secret-Mounts)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------- Audit
def test_p1_audit_log_is_append_only(tmp_path):
    from backend.audit_log import ChainedAuditLog

    db = str(tmp_path / "audit.db")
    alog = ChainedAuditLog(db_path=db)
    alog.record_event("system", "test", "agent-1", {"x": 1})
    assert alog.verify_integrity()["valid"] is True

    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE audit_log SET action = 'tampered' WHERE id = 1")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_log WHERE id = 1")


def test_p1_hmac_chain_without_key_fails_closed(tmp_path, monkeypatch):
    from backend.audit_log import ChainedAuditLog

    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "regression-test-key")
    db = str(tmp_path / "hmac.db")
    alog = ChainedAuditLog(db_path=db)
    alog.record_event("system", "test", "agent-1", {"x": 1})

    result = alog.verify_integrity()
    assert result["valid"] is True
    assert result["hmac_active"] is True
    assert result["hmac_blocks"] >= 1

    monkeypatch.delenv("ARCHON_AUDIT_HMAC_KEY")
    without_key = alog.verify_integrity()
    assert without_key["valid"] is False
    assert without_key["hmac_active"] is False


# ---------------------------------------------------------------- Content-Machine
def test_p1_quality_gate_blocks_approval(tmp_path):
    from backend import content_machine as cm

    db = str(tmp_path / "content.db")
    cm.init_content_machine_db(db)
    asset = cm.create_asset(
        {"channel": "linkedin", "title": "", "hook": "", "body": "", "cta": ""},
        db_path=db,
    )
    with pytest.raises(ValueError, match="Quality-Gate"):
        cm.approve_asset(asset["id"], db_path=db)


def test_p1_scheduler_runs_publish_sweep():
    src = (REPO_ROOT / "backend/workflow_scheduler.py").read_text(encoding="utf-8")
    assert "def _run_content_publish_sweep" in src
    assert "_run_content_publish_sweep(cur_now)" in src


def test_p1_resume_finalizes_hitl_assets():
    src = (REPO_ROOT / "backend/workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "finalize_assets_for_workflow_run(run_id" in src
    #Die Finalisierung darf nicht nur im decisions.py-Router haengen.
    router = (REPO_ROOT / "archon/routers/decisions.py").read_text(encoding="utf-8")
    assert "finalize_assets_for_workflow_run" in router


# ---------------------------------------------------------------- Auth-Default
def test_p1_auth_forced_on_nonlocal_bind(monkeypatch):
    from backend.auth_service import AuthService

    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ARCHON_ENV", raising=False)
    monkeypatch.setattr(AuthService, "_read_auth_enabled", staticmethod(lambda: False))

    monkeypatch.setenv("ARCHON_BIND_IP", "127.0.0.1")
    assert AuthService.is_auth_enabled() is False

    monkeypatch.setenv("ARCHON_BIND_IP", "0.0.0.0")
    assert AuthService.is_auth_enabled() is True

    monkeypatch.setenv("ARCHON_BIND_IP", "192.168.1.10")
    assert AuthService.is_auth_enabled() is True


def test_p1_auth_forced_in_production(monkeypatch):
    from backend.auth_service import AuthService

    monkeypatch.setenv("ARCHON_BIND_IP", "127.0.0.1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(AuthService, "_read_auth_enabled", staticmethod(lambda: False))
    assert AuthService.is_auth_enabled() is True


# ---------------------------------------------------------------- Secret-Mounts
def test_p1_prod_compose_does_not_bind_repo_root():
    lines = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    active = [
        line.strip()
        for line in lines
        if "- ./:/app" in line and not line.strip().startswith("#")
    ]
    assert not active, active
    content = "\n".join(lines)
    assert "ARCHON_AUDIT_HMAC_KEY=${ARCHON_AUDIT_HMAC_KEY:-}" in content


# ---------------------------------------------------------------- HMAC-Rotation
def test_p1_hmac_epoch_rotation_keeps_old_blocks_verifiable(tmp_path, monkeypatch):
    from backend.audit_log import ChainedAuditLog

    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", raising=False)
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "old-key")
    db = str(tmp_path / "rotation.db")
    alog = ChainedAuditLog(db_path=db)
    alog.record_event("system", "old", "agent-1", {"phase": 1})
    assert alog.verify_integrity()["valid"] is True

    # Rotation: alter Key bleibt als Epoche ab Block 1, neuer Key ab Block 2.
    monkeypatch.setenv(
        "ARCHON_AUDIT_HMAC_EPOCHS",
        json.dumps([{"key": "old-key", "from_block": 1}]),
    )
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "new-key")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "2")
    assert alog.verify_integrity()["valid"] is True

    alog.record_event("system", "new", "agent-1", {"phase": 2})
    verified = alog.verify_integrity()
    assert verified["valid"] is True
    assert verified["hmac_blocks"] == 2

    # Alten Key entfernen -> alter Block nicht mehr verifizierbar (fail-closed).
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS")
    assert alog.verify_integrity()["valid"] is False


# ---------------------------------------------------------------- Content-Research
def test_p1_content_dag_uses_real_research_node():
    from backend.content_machine import build_content_repurposing_dag

    dag = build_content_repurposing_dag(
        {"id": "camp-1", "title": "Test-Campaign", "channels": ["linkedin"]}
    )
    research = next(n for n in dag["nodes"] if n["id"] == "n_research")
    assert research["type"] == "research"
    assert research.get("query")


async def test_p1_research_node_calls_engine_with_sources():
    from backend.workflow_dag_runner import _execute_research_dag_node

    fake = {
        "status": "ok",
        "synthesis": "Faktenbasierte Synthese",
        "sources": [{"title": "Quelle A", "url": "https://example.org/a", "domain": "example.org"}],
        "verdict": "HOCH",
    }
    with patch("research_engine_v2.run_research_mission_v2", return_value=fake):
        res = await _execute_research_dag_node(
            {"id": "n_research", "type": "research", "query": "Testthema"}, {}
        )

    assert res["status"] == "success"
    assert "Faktenbasierte Synthese" in res["content"]
    assert "example.org" in res["content"]
    assert res["total_sources"] == 1


# ---------------------------------------------------------------- Feedback-Loop
def test_p1_feedback_hooks_are_injected_into_master_brief(tmp_path, monkeypatch):
    from backend import content_machine as cm

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "voice_winner_hooks.md").write_text(
        "- Hook A: 3x CTR gesteigert\n- Hook B: konkrete Zahl am Anfang\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "WORKSPACE_DIR", str(tmp_path))
    with patch("local_memory_bridge.memory_bridge.search_learnings", return_value=[]):
        dag = cm.build_content_repurposing_dag(
            {"id": "camp-fb", "title": "Feedback-Test", "channels": ["linkedin"]}
        )
    brief = next(n for n in dag["nodes"] if n["id"] == "n_master_brief")
    assert "Hook A" in brief["prompt"]
    assert "ERFOLGREICHE MUSTER" in brief["prompt"]


# ---------------------------------------------------------------- Policy-Invariante
def test_p1_policy_invariant_blocks_unlimited_auto_approval(tmp_path, monkeypatch):
    import backend.approval_policy_engine as ape

    engine = ape.ApprovalPolicyEngine(db_path=str(tmp_path / "approval.db"))
    with pytest.raises(ValueError, match="Invariante"):
        engine.update_policy("finance_auto_approval_max", "1000000", user_id="admin")
    with pytest.raises(ValueError, match="numerisch"):
        engine.update_policy("finance_auto_approval_max", "unbegrenzt", user_id="admin")


# ---------------------------------------------------------------- Audit-Reste
def test_p1_audit_timestamps_are_utc(tmp_path, monkeypatch):
    from backend.audit_log import ChainedAuditLog

    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "utc-key")
    db = str(tmp_path / "utc.db")
    alog = ChainedAuditLog(db_path=db)
    alog.record_event("system", "utc", "agent-1", {"x": 1})

    with sqlite3.connect(db) as conn:
        ts = conn.execute("SELECT timestamp FROM audit_log LIMIT 1").fetchone()[0]
    assert ts.endswith("Z") or "+00:00" in ts
    assert alog.verify_integrity()["valid"] is True


def test_p1_legacy_company_fallback_is_fail_closed():
    src = (REPO_ROOT / "backend/audit_log.py").read_text(encoding="utf-8")
    assert 'ARCHON_AUDIT_LEGACY_MAX_BLOCK", "0"' in src
    assert "if int(r[\"id\"]) <= legacy_max:" in src


# ---------------------------------------------------------------- Boardroom-Trigger
def test_p1_boardroom_trigger_uses_real_profile_ids():
    src = (REPO_ROOT / "scripts/trigger_boardroom_debate.py").read_text(encoding="utf-8")
    assert 'chairman_id: str = "default"' in src
    assert "market_research_analyst" not in src
    assert '"senior_coder"' not in src
    assert "from core.agent_core" not in src
    assert "from archon.routers.boardroom import" in src

    profiles = json.loads((REPO_ROOT / "agent_profiles.json").read_text(encoding="utf-8"))
    ids = {p.get("id") for p in profiles if isinstance(p, dict)}
    assert {"default", "research_scout", "senior_fullstack_engineer"} <= ids
