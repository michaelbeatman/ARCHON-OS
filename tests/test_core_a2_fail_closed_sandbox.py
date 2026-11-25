# -*- coding: utf-8 -*-
"""
Strang A — Paket A2 Regressionstests:
Fail-Closed-Vertraege (agent_router, container_ops, structured_output_enforcer)
und AST-Sandbox-Haertung (self_evolving_tooling).
Referenz: d01, d04, d12.
"""
import asyncio
import json
import pytest


def test_structured_output_enforcer_fails_closed_on_missing_required_fields():
    from backend.structured_output_enforcer import StructuredOutputEnforcer

    enforcer = StructuredOutputEnforcer()
    res = enforcer.validate_and_enforce(
        raw_output=json.dumps({"name": "Archon"}),
        schema={"name": "string", "amount": "integer"},
    )
    assert res["valid"] is False
    assert "amount" in res["missing_fields_filled"]
    assert "error" in res and "Pflichtfelder" in res["error"]


def test_structured_output_enforcer_fails_closed_on_coercion_failure():
    from backend.structured_output_enforcer import StructuredOutputEnforcer

    enforcer = StructuredOutputEnforcer()
    res = enforcer.validate_and_enforce(
        raw_output=json.dumps({"amount": "not-a-number"}),
        schema={"amount": "integer"},
    )
    assert res["valid"] is False
    assert any("amount" in item for item in res.get("coercion_failures", []))
    assert "error" in res


def test_structured_output_enforcer_accepts_valid_and_coercible_json():
    from backend.structured_output_enforcer import StructuredOutputEnforcer

    enforcer = StructuredOutputEnforcer()
    res = enforcer.validate_and_enforce(
        raw_output='```json\n{"name": "Archon", "amount": "42", "ratio": "1.5"}\n```',
        schema={"name": "string", "amount": "integer", "ratio": "float"},
    )
    assert res["valid"] is True
    assert res["data"]["name"] == "Archon"
    assert res["data"]["amount"] == 42
    assert res["data"]["ratio"] == 1.5


@pytest.mark.parametrize(
    "bad_code",
    [
        "import os\nx = os.getcwd()",
        "from subprocess import Popen",
        "__import__('os').system('id')",
        "eval('1+1')",
        "exec('x=1')",
        "compile('1', '<x>', 'eval')",
        "open('/etc/passwd')",
        "getattr(object, '__subclasses__')",
        "x = ().__class__.__bases__[0].__subclasses__()",
        "x = __builtins__['eval']",
        "globals()['__builtins__']",
    ],
)
def test_self_evolving_ast_blocks_escape_vectors(bad_code):
    from backend.self_evolving_tooling import _validate_synthetic_imports

    with pytest.raises(ValueError):
        _validate_synthetic_imports(bad_code, label="tool_code")


def test_self_evolving_ast_allows_pure_math_tool():
    from backend.self_evolving_tooling import _validate_synthetic_imports

    code = (
        "import math\n"
        "def calc_area(radius: float) -> float:\n"
        "    return round(math.pi * radius * radius, 4)\n"
    )
    _validate_synthetic_imports(code, label="tool_code")


def test_agent_router_rejects_empty_http_200_choices(tmp_path, monkeypatch):
    import datetime
    import sqlite3

    import backend.role_budget_engine as rbe
    from backend import agent_router
    import backend.llm_egress_guard as egress_guard

    # W3-D/F032: ohne registriertes Task-Cap blockt der Router vor dem HTTP-Call.
    # Hier soll aber genau die leere HTTP-200-Antwort geprueft werden → Cap anlegen.
    budget_db = str(tmp_path / "empty_choices_budget.db")
    rbe.init_budget_tables(db_path=budget_db)
    monkeypatch.setattr(rbe.budget_bank, "db_path", budget_db)
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(budget_db) as conn:
        conn.execute(
            "INSERT INTO task_budget_allocations "
            "(task_id, agent_id, token_budget, tokens_used, cost_limit_eur, cost_used_eur, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, 0.0, ?, ?)",
            ("test-empty-choices", "default", 50000, 100.0, now, now),
        )
        conn.commit()

    router = agent_router.AgentRouter()

    class _FakeResp:
        status_code = 200
        headers = {}
        text = '{"choices": []}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": []}

    class _FakeClient:
        async def post(self, *args, **kwargs):
            return _FakeResp()

    monkeypatch.setattr(router, "_get_shared_client", lambda: _FakeClient())
    monkeypatch.setattr(router, "_enforce_token_guard", lambda m, p, mod, rl: (m, mod, rl))
    monkeypatch.setattr(router, "_run_compliance_and_classify", lambda a, m, c: c or "internal")
    monkeypatch.setattr(
        egress_guard,
        "evaluate_and_gate_llm_dispatch",
        lambda **kw: {
            "provider": kw["provider"],
            "model": kw["model"],
            "routed_to_local": False,
            "data_category": "internal",
            "zero_egress_active": False,
        },
    )
    monkeypatch.setattr(egress_guard, "log_completed_llm_dispatch", lambda **kw: None)

    with pytest.raises(RuntimeError, match="Leere LLM-Antwort|leere|choices"):
        asyncio.run(
            router.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                provider="openai",
                model="gpt-4o-mini",
                api_keys={"OPENAI_API_KEY": "sk-test-dummy"},
                agent_id="default",
                task_id="test-empty-choices",
            )
        )


def test_container_ops_propagates_zero_egress_from_firewall_and_blocks_fake_success(monkeypatch):
    from archon.routers import container_ops
    import backend.llm_egress_guard as egress_guard
    from backend.llm_egress_guard import ZeroEgressBlockedError

    # 1. evaluate_and_gate_llm_dispatch ZeroEgressBlockedError -> explicit hard-block response
    monkeypatch.setattr(
        egress_guard,
        "evaluate_and_gate_llm_dispatch",
        lambda **kw: (_ for _ in ()).throw(ZeroEgressBlockedError("egress blocked by policy")),
    )
    out = container_ops.send_prompt_to_agent(
        agent_name="default",
        agent_config={"role": "Orchestrator & System-Architekt", "model": "openai/gpt-4o"},
        user_input="test",
        history=[],
    )
    assert "ZERO-EGRESS HARD-BLOCK" in out

    # 2. enforce_egress_firewall_for_url ZeroEgressBlockedError -> re-raised (not swallowed)
    monkeypatch.setattr(
        egress_guard,
        "evaluate_and_gate_llm_dispatch",
        lambda **kw: {
            "provider": "omniroute",
            "model": kw["model"],
            "routed_to_local": False,
            "data_category": "internal",
            "zero_egress_active": False,
        },
    )
    monkeypatch.setattr(
        egress_guard,
        "enforce_egress_firewall_for_url",
        lambda url, **kw: (_ for _ in ()).throw(ZeroEgressBlockedError("firewall blocked url")),
    )
    with pytest.raises(ZeroEgressBlockedError, match="firewall blocked url"):
        container_ops.send_prompt_to_agent(
            agent_name="default",
            agent_config={"role": "Orchestrator & System-Architekt", "model": "openai/gpt-4o"},
            user_input="test",
            history=[],
        )
