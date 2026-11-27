"""W4-C: Regressionstests fuer Rollen-/Prompt-SSOT (D15-H3/H5/H6, M2/M3/M4, D01-H2).

Alle Tests pruefen den Konsumenten im Produktivpfad oder eine echte Helper-
Funktion, nicht nur die Existenz eines Artefakts (00_SOLL_SPEC.md §0).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_profiles():
    return json.loads((ROOT / "agent_profiles.json").read_text(encoding="utf-8"))


def _load_org():
    return json.loads((ROOT / "config" / "org_hierarchy.json").read_text(encoding="utf-8"))


def _build_ssot_module():
    """Laedt scripts/build_souls_ssot.py ohne Seiteneffekte auf sys.argv."""
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "w4c_build_souls_ssot", ROOT / "scripts" / "build_souls_ssot.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# D15-H3: Pflicht-Warn-Dialoge im Produktivpfad
# ---------------------------------------------------------------------------

def test_h3_all_production_prompt_paths_consume_append_negative_scope():
    from archon.core import profiles

    src = Path(profiles.__file__).read_text(encoding="utf-8")
    assert "liability_notice_block(prof)" in src
    for rel in (
        "archon/routers/chat.py",
        "archon/routers/agent_chat.py",
        "archon/routers/quickchat.py",
        "archon/routers/telegram.py",
        "archon/routers/governance.py",
        "archon/core/orchestration.py",
    ):
        assert "append_negative_scope" in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_h3_domain4_all_profiles_get_baugb_hoai_notice_in_prompt(tmp_path, monkeypatch):
    from archon.core.profiles import append_negative_scope

    monkeypatch.setenv("ARCHON_LIABILITY_ACK_STORE", str(tmp_path / "none.json"))

    construction = [p for p in _load_profiles() if str(p.get("category") or "").startswith("4.")]
    assert len(construction) == 7
    for prof in construction:
        out = append_negative_scope(prof.get("system_prompt", ""), prof)
        assert "ARCHON_LIABILITY_DISCLAIMER_v1" in out, prof["id"]
        assert "BauGB" in out and "HOAI" in out, prof["id"]
        assert "LIABILITY_ACK_REQUIRED" in out, prof["id"]


def test_h3_legal_and_medical_groups_are_injected():
    from archon.core.profiles import append_negative_scope

    by_id = {p["id"]: p for p in _load_profiles()}
    for pid, needle in (
        ("legal_counsel", "RDG"),
        ("clinical_medical_advisor", "EU-MDR"),
        ("chemistry_materials_specialist", "REACH"),
    ):
        prof = by_id[pid]
        out = append_negative_scope(prof.get("system_prompt", ""), prof)
        assert needle in out, pid


def test_h3_ack_needs_actor_and_audit_event_and_is_drift_sensitive(tmp_path, monkeypatch):
    from archon.core import profiles

    monkeypatch.setenv("ARCHON_LIABILITY_ACK_STORE", str(tmp_path / "acks.json"))
    prof = next(p for p in _load_profiles() if p["id"] == "legal_counsel")
    events: list[dict] = []
    try:
        profiles.record_liability_acknowledgement(prof, "   ", audit_event_fn=events.append)
        raise AssertionError("Bestaetigung ohne actor darf nicht gelingen")
    except ValueError:
        pass
    assert events == []

    def failing_audit(record):
        raise RuntimeError("audit unavailable")

    try:
        profiles.record_liability_acknowledgement(
            prof, "operator-1", audit_event_fn=failing_audit
        )
        raise AssertionError("Bestaetigung ohne Audit darf nicht gelingen")
    except RuntimeError:
        pass
    assert not (tmp_path / "acks.json").exists()

    record = profiles.record_liability_acknowledgement(
        prof, "operator-1", audit_event_fn=events.append
    )
    assert record["approval_id"] and record["actor"] == "operator-1"
    assert record["confirmed_at"] and record["disclaimer_sha256"]
    assert events and events[0]["approval_id"] == record["approval_id"]
    ack = profiles.active_liability_acknowledgement(prof)
    assert ack is not None
    assert ack["approval_id"] == record["approval_id"]
    assert profiles.require_liability_acknowledgement(prof)["approval_id"] == record["approval_id"]

    # Hinweis-Text geaendert => alter Ack ungueltig (fail-closed).
    from archon.core.profiles import liability_notice_block

    assert "ARCHON_LIABILITY_DISCLAIMER_v1" in liability_notice_block(prof)
    assert "LIABILITY_ACK_OK" in liability_notice_block(prof)
    monkeypatch.setitem(
        profiles._LIABILITY_GROUPS["legal_tax_finance"], "law_pill", "geänderter Hinweis"
    )
    assert "LIABILITY_ACK_REQUIRED" in liability_notice_block(prof)


def test_h3_ui_has_no_dismissable_sessionstorage_ack():
    js = (ROOT / "static" / "js" / "agent_profiles.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "views" / "agent_profiles_view.html").read_text(encoding="utf-8")
    # Kommentare dürfen das Wort nennen; entscheidend ist keine echte Nutzung.
    dialog_js = js.split("BERUFSRECHTS- & HAFTUNGS-WARNDIALOG")[1].split(
        "function selectProfileForEditor"
    )[0]
    assert "sessionStorage." not in dialog_js
    assert "sessionStorage[" not in dialog_js
    assert 'onclick="closeLiabilityDisclaimerModal(false)"' not in html
    assert "confirmLiabilityDisclaimer()" in html
    assert "/api/v1/profiles/liability-ack" in js
    assert 'cat.startsWith("4.")' in js


# ---------------------------------------------------------------------------
# D15-H5: Prompt≡Tools, Alias-Normalisierung, Isolation
# ---------------------------------------------------------------------------

def test_h5_prompt_tool_gate_catches_legacy_and_accepts_sanitized_prompts():
    from archon.core.profiles import sanitize_prompt_tool_declaration
    from backend.delegation_isolation import (
        validate_all_prompt_tool_declarations,
        validate_prompt_tool_declaration,
    )

    profiles = _load_profiles()
    legacy = validate_all_prompt_tool_declarations(profiles)
    assert legacy, "Legacy-Deklarationen muessen vom Gate sichtbar gemacht werden"
    for prof in profiles:
        normalized = dict(prof)
        normalized["prompt"] = sanitize_prompt_tool_declaration(
            prof.get("prompt", ""), prof
        )
        assert validate_prompt_tool_declaration(normalized)["ok"], prof["id"]


def test_h5_advisory_high_risk_roles_have_no_executive_tools():
    from archon.core.profiles import sanitize_prompt_tool_declaration
    from backend.agent_aliases import ADVISORY_HIGH_RISK_AGENT_IDS
    from backend.delegation_isolation import (
        ADVISORY_FORBIDDEN_TOOLS,
        effective_profile_tools,
    )

    by_id = {p["id"]: p for p in _load_profiles()}
    assert ADVISORY_HIGH_RISK_AGENT_IDS <= set(by_id)
    for pid in ADVISORY_HIGH_RISK_AGENT_IDS:
        prof = by_id[pid]
        tools = set(effective_profile_tools(prof))
        assert not (tools & ADVISORY_FORBIDDEN_TOOLS), pid
        prompt = sanitize_prompt_tool_declaration(prof.get("prompt", ""), prof)
        for tool in ADVISORY_FORBIDDEN_TOOLS:
            assert f"`{tool}`" not in prompt, (pid, tool)


def test_h5_isolation_scope_ignores_prompt_declaration():
    from backend.delegation_isolation import resolve_isolated_execution_scope

    prof = {
        "id": "research_scout",
        "tools": ["web_search"],
        "prompt": "- **Authorized System Tools & MCP Servers:** `web_search`, `terminal`, `filesystem`",
    }
    scope = resolve_isolated_execution_scope("research_scout", profiles=[prof])
    assert scope["allowed_tools"] == ["web_search"]
    assert scope["isolated"] is True


def test_h5_tool_alias_normalization_uses_org_ssot():
    from backend.agent_aliases import canonical_tool_name

    assert canonical_tool_name("FileSystem_MCP") == "filesystem"
    assert canonical_tool_name("Calculator") == "execute_code"
    assert canonical_tool_name("WebSearch") == "web_search"


# ---------------------------------------------------------------------------
# D15-H6 / D15-M2: Mandate, Freigabeinstanz, APEX, Aliase
# ---------------------------------------------------------------------------

def test_h6_single_approval_authority_and_advisory_founder():
    from archon.core.profiles import get_approval_authority_ids

    assert get_approval_authority_ids() == frozenset({"executive_decision_architect"})
    profiles = {p["id"]: p for p in _load_profiles()}
    founder, ceo = profiles["founder"], profiles["executive_decision_architect"]
    assert founder["daily_token_budget"] < ceo["daily_token_budget"]
    assert "Freigabe" in founder["negative_scope"]
    assert "advisory" in founder["description"].lower()

    org = {n["id"]: n for n in _load_org()["nodes"]}
    assert org["founder"]["tier"] == 3
    assert org["founder"].get("mandate") == "advisory_only"
    assert org["founder"].get("is_approval_authority") is False
    assert ceo["id"] in get_approval_authority_ids()


def test_m2_single_apex_and_orchestrator_alias_points_to_default():
    from backend.agent_aliases import ALIASES, resolve_agent_id

    org = _load_org()
    tier1 = {n["id"] for n in org["nodes"] if n.get("tier") == 1}
    assert tier1 == {"default"}
    assert org["aliases"]["apex"] == "default"
    assert ALIASES["hermes-orchestrator"] == "default"
    known = {p["id"] for p in _load_profiles()}
    for handle in ("hermes-orchestrator", "hermes_orchestrator", "apex"):
        assert resolve_agent_id(handle, known) == "default"


# ---------------------------------------------------------------------------
# D15-M3: Status-SSOT und Budget-Gate
# ---------------------------------------------------------------------------

def test_m3_status_projection_and_budget_gate():
    from archon.core.profiles import validate_status_budget_ssot

    result = validate_status_budget_ssot()
    assert result["status_mismatches"] == [], result
    assert result["budget_violations"] == [], result
    profiles = _load_profiles()
    org = _load_org()
    assert sum(p["status"] == "standby" for p in profiles) == sum(
        n.get("status") == "standby" for n in org["nodes"]
    )
    lisa = next(p for p in profiles if p["id"] == "aggregation_lisa")
    assert lisa["status"] == "deprecated"
    assert lisa["daily_token_budget"] == 0
    assert all(
        lisa["id"] not in (link.get("from"), link.get("to")) for link in org["links"]
    )


# ---------------------------------------------------------------------------
# D15-M4: CrewAI-Rollengrenzen
# ---------------------------------------------------------------------------

def test_m4_each_role_boundary_matches_template_role():
    module = _build_ssot_module()
    profiles = _load_profiles()
    assert module.validate_crewai_boundaries(profiles) == []
    for path in sorted((ROOT / "templates" / "crewai").glob("*/system.md")):
        text = path.read_text(encoding="utf-8")
        role_line = next((line for line in text.splitlines() if line.startswith("# ROLE:")), "")
        assert role_line, path
        for line in text.splitlines():
            if line.startswith("- Role-specific boundary ("):
                pid = line.split("(", 1)[1].split(")", 1)[0]
                assert pid == module.CREWAI_ROLE_MAP[path.parent.name], (path, pid)
        if "Art. 50" in text:
            assert path.parent.name in module.CREWAI_EXTERNAL_EFFECT_STEMS, path


def test_m4_no_hintmap_or_remaining_fallback():
    src = (ROOT / "scripts" / "build_souls_ssot.py").read_text(encoding="utf-8")
    assert "hint_map = {" not in src
    # Nur in einem Erklärungskommentar erwähnt, nicht mehr ausführbar.
    assert not any("remaining[0]" in line.split("#")[0] for line in src.splitlines())
    assert "CREWAI_ROLE_MAP" in src


# ---------------------------------------------------------------------------
# D01-H2 (JS-Seite): Erfolg nur mit task_id
# ---------------------------------------------------------------------------

def test_d01h2_bot_screen_uses_task_endpoint_and_requires_task_id():
    src = (ROOT / "static" / "js" / "agent_profiles.js").read_text(encoding="utf-8")
    fn = src.split("async function sendCadreBotScreenInstruction()", 1)[1].split(
        "window.navigateCadreBotScreen", 1
    )[0]
    assert 'fetch("/api/operations/tasks"' in fn
    assert "comm-feed/broadcast" not in fn
    assert "result.task_id" in fn
    assert "keine task_id" in fn
    assert "Live-Navigation aktiv" not in fn
    endpoint = (ROOT / "archon" / "routers" / "operations_org.py").read_text(encoding="utf-8")
    assert '@router.post("/tasks")' in endpoint
    assert '"task_id": task_id' in endpoint
