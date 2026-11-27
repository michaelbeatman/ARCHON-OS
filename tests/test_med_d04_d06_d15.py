"""Gezielte MED-Regressionstests: Re-Audit D04, D06, D15.

Deckt nur die in diesem Batch behobenen MED-Funde ab:
- D04: Ersteller-Sperre in der Approval-Engine, RBAC-Jail fail-closed.
- D06: OmniRoute-Allowlist aus .env, n8n-Webhook-Egress/Redirect-Schutz.
- D15: korrigierte Docstring-Zahl, Fremd-Cache-Gate, CrewAI-Negativabgrenzung.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# D04 — Approval-Engine
# ---------------------------------------------------------------------------


def test_d04_requester_is_persisted_and_self_approval_blocked(tmp_path):
    from backend.approval_policy_engine import ApprovalPolicyEngine

    engine = ApprovalPolicyEngine(db_path=str(tmp_path / "approval.db"))
    ev = engine.evaluate_and_enqueue("finance", "Zahlung", amount=1000.0, requester_id="alice")
    req_id = ev["request_id"]

    row = next(r for r in engine.get_requests() if r["id"] == req_id)
    assert row["requester_id"] == "alice"
    assert json.loads(row["payload_json"])["_requester_id"] == "alice"

    with pytest.raises(ValueError, match="Ersteller"):
        engine.approve_request(req_id, approver_id="alice")

    assert engine.approve_request(req_id, approver_id="bob")["status"] == "first_approved"


def test_d04_creator_check_also_uses_signed_payload_fallback(tmp_path):
    from backend.approval_policy_engine import ApprovalPolicyEngine

    engine = ApprovalPolicyEngine(db_path=str(tmp_path / "approval_payload.db"))
    ev = engine.evaluate_and_enqueue("erp", "Test", amount=100.0, payload={"_requester_id": "carol"})
    req_id = ev["request_id"]

    with pytest.raises(ValueError, match="Ersteller"):
        engine.approve_request(req_id, approver_id="carol")
    assert engine.approve_request(req_id, approver_id="dave")["status"] == "approved"


def test_d04_approve_request_has_no_default_approver():
    from backend.approval_policy_engine import ApprovalPolicyEngine

    param = inspect.signature(ApprovalPolicyEngine.approve_request).parameters["approver_id"]
    assert param.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# D04 — RBAC-Jail
# ---------------------------------------------------------------------------


def test_d04_disabled_rbac_jail_is_hard_deny(monkeypatch):
    import backend.agent_rbac_jail as jail

    monkeypatch.setattr(jail, "_get_cfg", lambda: {"enabled": False})
    monkeypatch.setattr(jail, "_audit_jail_bypass", lambda *a, **kw: None)

    res = jail.agent_rbac_jail.check_access(
        role="kernel_admin", tool_name="write_file", target_path="backend/x.py"
    )
    assert res["allowed"] is False
    assert res["bypassed"] is True
    assert res["blocked"] is True

    # Eine echte Positivpruefung bleibt unberuehrt.
    monkeypatch.setattr(jail, "_get_cfg", lambda: {"enabled": True})
    ok = jail.agent_rbac_jail.check_access(
        role="kernel_admin", tool_name="write_file", target_path="backend/x.py"
    )
    assert ok["allowed"] is True
    assert not ok.get("bypassed")


# ---------------------------------------------------------------------------
# D06 — OmniRoute-Allowlist
# ---------------------------------------------------------------------------


def test_d06_omniroute_allowlist_comes_from_dotenv(monkeypatch, tmp_path):
    mod = _load_script("omniroute_healthcheck", "scripts/omniroute_healthcheck.py")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ARCHON_OMNIROUTE_MODEL_ALLOWLIST=model-a,model-b\nOMNIROUTE_API_KEY=local-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ENV_FILE", str(env_file))
    monkeypatch.delenv(mod.MODEL_ALLOWLIST_ENV, raising=False)

    allowed = {m.strip() for m in mod._env_first(mod.MODEL_ALLOWLIST_ENV).split(",") if m.strip()}
    assert allowed == {"model-a", "model-b"}

    # Explizite Umgebung hat Vorrang vor der .env.
    monkeypatch.setenv(mod.MODEL_ALLOWLIST_ENV, "model-c")
    assert mod._env_first(mod.MODEL_ALLOWLIST_ENV) == "model-c"

    # Der OmniRoute-Key darf nicht im externen Kandidaten-Code auftauchen.
    assert "OMNIROUTE_API_KEY" not in inspect.getsource(mod.candidates)


# ---------------------------------------------------------------------------
# D06 — n8n-MCP-Webhook
# ---------------------------------------------------------------------------


def test_d06_n8n_driver_blocks_foreign_egress_target(monkeypatch):
    mod = _load_script("mcp_n8n_driver", "scripts/mcp_n8n_driver.py")
    monkeypatch.setenv("ARCHON_WEBHOOK_HMAC_SECRET", "test-only-secret")
    driver = mod.N8nMcpDriver(base_url="http://localhost:5678", api_key="test-key")

    res = driver._http_post_json("http://evil.example/webhook/x", {"a": 1})
    assert res["status"] == "error"
    assert "Egress-Block" in res["error"]


def test_d06_n8n_driver_uses_redirect_rejecting_opener(monkeypatch):
    mod = _load_script("mcp_n8n_driver_2", "scripts/mcp_n8n_driver.py")
    monkeypatch.setenv("ARCHON_WEBHOOK_HMAC_SECRET", "test-only-secret")
    driver = mod.N8nMcpDriver(base_url="http://localhost:5678", api_key="test-key")

    captured = {}

    class _NoNetworkOpener:
        def open(self, req, timeout):
            raise AssertionError("kein Netzwerkzugriff im Test")

    def _build_opener(handler):
        captured["handler"] = handler
        return _NoNetworkOpener()

    monkeypatch.setattr(mod.urllib.request, "build_opener", _build_opener)
    res = driver._http_post_json("http://localhost:5678/webhook/test", {"a": 1})

    assert res["status"] == "failed"
    assert type(captured["handler"]).__name__ == "_RejectAllRedirectsHandler"


# ---------------------------------------------------------------------------
# D15 — SSOT / Caches / CrewAI
# ---------------------------------------------------------------------------


def test_d15_build_souls_docstring_matches_accepted_count():
    src = (ROOT / "scripts" / "build_souls_ssot.py").read_text(encoding="utf-8")
    assert "EXPECTED_ARTIFACT_COUNT = 497" in src
    assert "497 Artefakte = 71 Profile x 7" in src
    assert "511 Artefakte = 73 Profile" not in src


def test_d15_unknown_foreign_cache_is_hard_drift(monkeypatch, tmp_path, capsys):
    mod = _load_script("check_soul_ssot_drift", "scripts/check_soul_ssot_drift.py")

    canon = tmp_path / "souls"
    (canon / "agent_a").mkdir(parents=True)
    (canon / "agent_a" / "SOUL.md").write_text("canonical", encoding="utf-8")

    runtime_a = tmp_path / "r1" / ".hermes" / "profiles"
    (runtime_a / "agent_a").mkdir(parents=True)
    (runtime_a / "agent_a" / "SOUL.md").write_text("canonical", encoding="utf-8")

    runtime_b = tmp_path / "r2" / "data" / "hermes_profiles"
    (runtime_b / "agent_a").mkdir(parents=True)
    (runtime_b / "agent_a" / "SOUL.md").write_text("canonical", encoding="utf-8")
    (runtime_b / "rogue_agent").mkdir()
    (runtime_b / "rogue_agent" / "SOUL.md").write_text("rogue", encoding="utf-8")

    (tmp_path / "agent_profiles.json").write_text(
        json.dumps([{"id": "agent_a"}]), encoding="utf-8"
    )

    monkeypatch.setattr(sys, "argv", ["check_soul_ssot_drift.py"])
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "CANON", canon)
    monkeypatch.setattr(mod, "RUNTIMES", (runtime_a, runtime_b))
    monkeypatch.delenv(mod.FOREIGN_CACHE_ENV, raising=False)

    assert mod.main() == 1
    assert "rogue_agent" in capsys.readouterr().out

    monkeypatch.setenv(mod.FOREIGN_CACHE_ENV, "rogue_agent")
    assert mod.main() == 0


def test_d15_crewai_templates_have_negative_scope_and_hitl():
    files = sorted((ROOT / "templates" / "crewai").glob("**/system.md"))
    assert files, "keine CrewAI-System-Prompts gefunden"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "## NOT ALLOWED / NICHT ERLAUBT" in text, f"{path}: keine Negativabgrenzung"
        assert "HITL-Freigabe" in text, f"{path}: kein HITL-Hinweis"
    # D15-M4: Art. 50 nur bei echter Außenwirkung, nicht mehr in jedem Template.
    assert any(
        "KI-generiert" in path.read_text(encoding="utf-8") for path in files
    ), "mindestens ein Außenwirkung-Template muss den Art.-50-Hinweis tragen"
