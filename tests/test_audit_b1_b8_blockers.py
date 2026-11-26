"""Regressionstests fuer die 8 Audit-Blocker B1-B8 aus audit_reports/MASTER_PLAN.md."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _fake_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw_headers})


def test_b1_vault_tenant_isolation_and_admin_guard(monkeypatch, tmp_path):
    import sys

    from archon.routers import vault

    root = str(tmp_path / "obsidian")
    os.makedirs(root, exist_ok=True)
    monkeypatch.setattr(vault, "OBSIDIAN_VAULT_DIR", root)
    if "main" in sys.modules and hasattr(sys.modules["main"], "OBSIDIAN_VAULT_DIR"):
        monkeypatch.setattr(sys.modules["main"], "OBSIDIAN_VAULT_DIR", root)
    monkeypatch.setattr(vault, "_active_tenant_id", lambda: "tenant_alpha")

    tdir = vault._get_vault_dir()
    assert os.path.normpath(tdir) == os.path.normpath(os.path.join(root, "tenant_alpha"))
    assert os.path.isdir(tdir)

    def _deny(_req):
        raise HTTPException(status_code=403, detail="Admin required")

    monkeypatch.setattr(vault, "require_admin_or_503", _deny)
    with pytest.raises(HTTPException) as exc:
        vault.api_read_vault_file_direct(path="note.md", request=_fake_request())
    assert exc.value.status_code == 403


def test_b2_audit_chain_anchor_ignores_violation_events(monkeypatch, tmp_path):
    from backend import audit_log

    db_file = str(tmp_path / "audit.db")
    isolated = audit_log.ChainedAuditLog(db_path=db_file)
    monkeypatch.setattr(audit_log, "DB_PATH", db_file)
    monkeypatch.setattr(audit_log, "chained_audit_log", isolated)

    res1 = audit_log.record_chain_anchor("treasury", "abc123", 42)
    assert res1["written"] is True

    # Tail-Loeschung / kuerzerer Count -> schreibt chain_anchor_violation
    res2 = audit_log.record_chain_anchor("treasury", "def456", 10)
    assert res2["written"] is False

    anchor = audit_log.get_chain_anchor("treasury")
    assert anchor is not None
    assert anchor["head"] == "abc123"
    assert anchor["count"] == 42
    anchors = audit_log.get_chain_anchors("treasury", limit=5)
    assert len(anchors) == 1
    assert anchors[0]["head"] == "abc123"


def test_b3_jev_test_requires_admin_blocks_ssrf_and_no_key_exfiltration(monkeypatch):
    import jev_router
    from archon.routers import core_settings

    # 1) Admin-Zaun aktiv
    def _deny(_req):
        raise HTTPException(status_code=403, detail="Admin required")

    monkeypatch.setattr(core_settings, "_require_admin", _deny)
    with pytest.raises(HTTPException) as exc:
        core_settings.api_test_jev(_fake_request(), {"base_url": "https://openrouter.ai/api/v1"})
    assert exc.value.status_code == 403

    # 2) SSRF-Schutz auf /api/v1/jev/test
    monkeypatch.setattr(core_settings, "_require_admin", lambda _req: None)
    with pytest.raises(HTTPException) as exc2:
        core_settings.api_test_jev(_fake_request(), {"base_url": "http://127.0.0.1:8080/v1"})
    assert exc2.value.status_code == 400

    # 3) Keine Key-Exfiltration an abweichende base_url.
    # W4-B: der HTTP-Hop laeuft ueber utils.safe_http.safe_http_request
    # (public_only=True, keine 3xx-Follows). Eine abweichende URL wird
    # fail-closed blockiert, BEVOR ein Request mit dem gespeicherten Key
    # rausgeht. Die Headers werden am echten Chokepoint abgefangen.
    from utils import safe_http as safe_http_module
    from utils.egress_guard import EgressBlocked

    captured_headers = {}

    def _fake_safe_http_request(url, *, method, headers, timeout, max_bytes, public_only):
        captured_headers.update(dict(headers or {}))
        raise EgressBlocked("test: divergent base_url blocked", str(url))

    monkeypatch.setattr(
        jev_router,
        "get_jev_config",
        lambda: {"api_key": "sk-secret-stored", "base_url": "https://openrouter.ai/api/v1"},
    )
    monkeypatch.setattr(safe_http_module, "safe_http_request", _fake_safe_http_request)

    res = jev_router.test_jev_connection(base_url="https://attacker.example/v1")
    assert res["status"] == "blocked"
    assert res["error_code"] == "EGRESS_BLOCKED"
    assert res["code"] == 400
    assert captured_headers.get("Authorization", "") == ""


def test_b4_proof_prompt_versions_never_unknown_and_handles_zero_canary(monkeypatch):
    from backend import llm_egress_guard
    from backend.prompt_registry import prompt_registry

    # F10a: Ohne aktiven Registry-Eintrag wird KEIN `v1-static` erfunden.
    monkeypatch.setattr(prompt_registry, "list_versions", lambda _aid: [])
    prov = llm_egress_guard._proof_prompt_versions("robert")
    assert prov.verified is False
    assert prov.version is None
    assert prov.canary is None

    # Negativprobe: Registry-Fehler liefert verified=False und kein `v1-static` im Proof
    def _boom(_aid):
        raise RuntimeError("registry_offline")

    monkeypatch.setattr(prompt_registry, "list_versions", _boom)
    captured = {}

    class _FakeAuditLog:
        def record_llm_dispatch(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    llm_egress_guard._record_blocked_proof(
        alog=_FakeAuditLog(),
        agent_id="robert",
        provider="openai",
        model="gpt-4o",
        target_endpoint="https://api.openai.com/v1/chat/completions",
        action="zero_egress_blocked",
        error_code="ZERO_EGRESS_BLOCKED",
        reason="test",
    )
    assert captured["prompt_version"] != "v1-static"
    assert captured["action"].endswith("_unverified_prompt_proof")
    assert captured["extra"]["effective_prompt_info"]["verified"] is False
    assert captured["extra"]["effective_prompt_info"]["version"] is None
    assert "registry_offline" in captured["extra"]["effective_prompt_info"]["error"]

    # Positivprobe: gueltige aktive Registry-Version mit canary_percentage=0 -> verified=True
    monkeypatch.setattr(
        prompt_registry,
        "list_versions",
        lambda _aid: [{"is_active": True, "version": "v2", "canary_percentage": 0}],
    )
    prov2 = llm_egress_guard._proof_prompt_versions("robert")
    assert prov2.verified is True
    assert prov2.version == "v2"
    assert prov2.canary == "stable"


def test_b5_local_security_guard_empty_http_200_fails_closed(monkeypatch):
    import backend.llm_egress_guard as egress_guard
    import local_security_guard as lsg

    # Egress-Gate im Unit-Test durchlassen, damit wirklich urlopen + Token-Parser
    # ausgefuehrt werden (die Positivprobe "SAFE" beweist, dass urlopen erreicht wird).
    monkeypatch.setattr(
        egress_guard,
        "evaluate_and_gate_llm_dispatch",
        lambda **_kw: {"routed_to_local": True, "allowed": True},
    )
    monkeypatch.setattr(lsg, "_enforce_egress_or_block", lambda *_a, **_kw: None)

    def _mock_reply(content: str):
        class _FakeResp:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(lsg.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())

    local_url = "http://127.0.0.1:20128/v1"
    _mock_reply("   ")
    out = lsg.scan_prompt_injection(
        "harmless looking text", sensitivity="strict", use_llm=True, omniroute_url=local_url
    )
    assert out["llm_verdict"] == "error"
    assert out["verdict"] == "blocked"

    # F10a Negativproben: UNSAFE / NOT SAFE duerfen nicht per Substring als SAFE durchgehen
    for bad_reply in ("UNSAFE", "NOT SAFE", "SAFE? NO"):
        _mock_reply(bad_reply)
        res = lsg.scan_prompt_injection(
            "harmless looking text", sensitivity="strict", use_llm=True, omniroute_url=local_url
        )
        assert res["llm_verdict"] == "error", bad_reply
        assert res["verdict"] == "blocked", bad_reply
        assert res["is_safe"] is False, bad_reply

    # Positivprobe: exaktes SAFE-Token wird weiterhin akzeptiert (beweist, dass urlopen erreicht wird)
    _mock_reply("SAFE")
    ok = lsg.scan_prompt_injection(
        "harmless looking text", sensitivity="strict", use_llm=True, omniroute_url=local_url
    )
    assert ok["llm_verdict"] == "safe"
    assert ok["verdict"] == "safe"
    assert ok["is_safe"] is True


def test_b6_trajectory_budget_tool_hops_do_not_trigger_cycle_detected(tmp_path):
    from backend.trajectory_budget import reserve_hop

    db = str(tmp_path / "traj.db")
    r1 = reserve_hop("traj-b6-1", "agent_a", "dag_node_start", db_path=db)
    r2 = reserve_hop("traj-b6-1", "agent_a", "tool:search", db_path=db)
    r3 = reserve_hop("traj-b6-1", "agent_a", "tool:read", allow_repeat=True, db_path=db)
    assert r1["allowed"] is True
    assert r2["allowed"] is True
    assert r3["allowed"] is True

    # Echter Agent-Wechsel-Zyklus (A -> B -> A) bleibt blockiert
    r4 = reserve_hop("traj-b6-1", "agent_b", "agent_switch", db_path=db)
    r5 = reserve_hop("traj-b6-1", "agent_a", "agent_switch", db_path=db)
    assert r4["allowed"] is True
    assert r5["allowed"] is False
    assert r5["reason"] == "CYCLE_DETECTED"


def test_b7_synthesis_cascade_guards_against_no_consensus():
    import inspect

    from archon.core import orchestration

    src = inspect.getsource(orchestration._run_synthesis_cascade)
    assert 'startswith("CONSENSUS_REACHED")' in src


def test_b8_append_negative_scope_injects_idempotently():
    from archon.core.profiles import append_negative_scope

    prof = {"negative_scope": ["Keine Produktion-DB-Writes", "Keine E-Mails"]}
    p1 = append_negative_scope("Du bist Tester.", prof)
    assert "NEGATIVE_SCOPE" in p1
    assert "Keine Produktion-DB-Writes" in p1
    assert "Keine E-Mails" in p1

    p2 = append_negative_scope(p1, prof)
    assert p2 == p1

    # Sanity check: real agent_profiles.json has negative_scope and helper works on it
    profiles_path = Path("agent_profiles.json")
    if profiles_path.exists():
        data = json.loads(profiles_path.read_text(encoding="utf-8"))
        first_with_neg = next((p for p in data if p.get("negative_scope")), None)
        assert first_with_neg is not None
        out = append_negative_scope(first_with_neg.get("system_prompt", ""), first_with_neg)
        assert "NEGATIVE_SCOPE" in out or str(first_with_neg["negative_scope"]) in out
