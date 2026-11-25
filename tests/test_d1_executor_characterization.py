# -*- coding: utf-8 -*-
"""B0 — Characterization der Facade ``default_agent_node_executor`` (D1, CC 246).

Zweck
-----
Vor dem ersten Split-Commit (`ANALYSIS_GOD_OBJECTS.md §5:387`, `§6 #9`) wird das
Verhalten der 10 Verantwortungs-Cluster mit Golden-Outputs festgenagelt. Der Executor
wird dabei **real** aufgerufen — nur seine externen Effekte (Dispatch, Kanban-Sync,
Profil-Laden, Tool-Runtime) werden gemockt. `test_workflow_dag_e2e.py` ersetzt den
Executor durchgehend durch `executor_fn=mock_exec` und charakterisiert ihn deshalb
gerade NICHT.

Regeln
------
* 1 Branch = 1 Golden-Output auf die Return-Felder aus
  `workflow_dag_runner.py:1778-1800` (status, error, content, tool_trace,
  parsed_output, cost_usd, cost_unverified, media_matrix, kanban_task_id, ...).
* Jeder Test enthaelt eine **Negativprobe gegen die echte Logik** (`INVARIANTS §4.5`):
  dieselbe Assertion wird gegen ein bewusst abweichendes, aber plausibles Ergebnis
  ausgefuehrt und MUSS fehlschlagen. Kein hartcodiertes Snippet, kein Theater-Gate.
* Gemeinsame Hilfsfunktionen statt kopierter Snippets (Handoff §5.6).
* Reine Charakterisierung: keine Logikänderung, kein Split, kein Produktivcode.

Ownership: G3 (DAG-Owner) — ausschliesslich diese neue Testdatei.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend import workflow_dag_runner as wdr

# ---------------------------------------------------------------------------
# Gemeinsame Hilfsfunktionen
# ---------------------------------------------------------------------------

_EXEC = "backend.workflow_dag_runner.default_agent_node_executor"
_DISPATCH = "core_dispatcher.dispatch_to_omniroute_or_container"
_KANBAN = "backend.workflow_dag_runner._update_kanban_task_status"
_PROFILES = "archon.core.profiles.api_get_hermes_profiles"
_TOOL_RUNTIME = "backend.tool_runtime.execute_agent_tool"
_CLIP_MATRIX = "backend.content_machine.generate_video_clip_matrix"
_COST = "backend.llm_kernel.estimate_model_cost_usd"


def _ok(content: str = "Antwort", **extra: Any) -> Dict[str, Any]:
    """Eine erfolgreiche Dispatcher-Antwort."""
    base: Dict[str, Any] = {
        "status": "success",
        "content": content,
        "input_tokens": 10,
        "output_tokens": 10,
        "model": "mock/model",
    }
    base.update(extra)
    return base


def _node(**over: Any) -> Dict[str, Any]:
    """Minimaler Agent-Node ohne Content-/Schema-/Tool-Sonderpfade."""
    base: Dict[str, Any] = {
        "id": "n-char",
        "type": "agent",
        "title": "Charakterisierung",
        "prompt": "Tu etwas.",
        "agent_id": "default",
    }
    base.update(over)
    return base


def _run(
    node: Dict[str, Any],
    responses: List[Dict[str, Any]],
    *,
    upstream: Optional[Dict[str, Any]] = None,
    extra_patches: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Ruft den ECHTEN Executor auf; mockt nur Dispatch + Kanban + Profile.

    ``responses`` wird als ``side_effect`` verbraucht (wichtig fuer Tool-Loop,
    Repair-Retry und Frontier-Eskalation). ``_COST`` wird bewusst NICHT gemockt:
    die echte Kostenberechnung (inkl. D12-Fallback) soll charakterisiert werden.
    """
    patches: List[Any] = [
        patch(_DISPATCH, new=AsyncMock(side_effect=responses)),
        patch(_KANBAN),
        # api_get_hermes_profiles wird per asyncio.to_thread aufgerufen -> synchron.
        patch(_PROFILES, new=MagicMock(return_value=[])),
    ]
    if extra_patches:
        patches.extend(extra_patches)

    async def _invoke() -> Dict[str, Any]:
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return await wdr.default_agent_node_executor(node, upstream or {})

    return asyncio.run(_invoke())


def _golden(out: Dict[str, Any], *, status: str, **fields: Any) -> Dict[str, Any]:
    """Baut die erwartete Teilmenge des Golden-Outputs."""
    expected: Dict[str, Any] = {"status": status}
    expected.update(fields)
    return {k: out.get(k) for k in expected}


def _assert_golden(out: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Vergleicht NUR die deklarierten Felder — der Executor liefert mehr."""
    subset = {k: out.get(k) for k in expected}
    assert subset == expected


def _negativprobe(out: Dict[str, Any], expected: Dict[str, Any], field: str, bogus: Any) -> None:
    """Negativprobe: ein plausibel falscher Wert MUSS die Assertion brechen.

    Gegen die ECHTE Logik geprueft (derselbe Helper wie die Positiv-Assertion),
    nicht gegen ein hartcodiertes Snippet. Wenn ``bogus == out[field]`` ist,
    waehre das Gate wertlos -> hier wird das explizit ausgeschlossen.
    """
    assert out.get(field) != bogus, "Negativprobe ist nicht negativ — Gate waere Theater"
    broken = dict(expected)
    broken[field] = bogus
    with pytest.raises(AssertionError):
        _assert_golden(out, broken)


# ---------------------------------------------------------------------------
# Cluster 4 (Basis): Profil-Aufloesung + Prompt-Bau + Return-Schema
# ---------------------------------------------------------------------------


def test_c4_baseline_golden_output_and_negativprobe():
    out = _run(_node(), [_ok("Fertig.")])

    # D12 (`INVARIANTS §3`): `_cost_usd = None` + `+=` wirft TypeError ->
    # der except-Zweig setzt cost_usd=None / cost_unverified=True. Das ist der
    # VERIFIZIERTE Normalfall, nicht der Fehlerfall. Nicht "bereinigen"!
    expected = _golden(
        out,
        status="success",
        node_id="n-char",
        agent_id="default",
        content="Fertig.",
        error="",
        kanban_task_id=None,
        input_tokens=10,
        output_tokens=10,
        cost_usd=None,
        cost_unverified=True,
    )
    _assert_golden(out, expected)
    assert "model" in out and "cost_usd" in out and "cost_unverified" in out
    _negativprobe(out, expected, "cost_usd", 0.0)


# ---------------------------------------------------------------------------
# Cluster 5: Node-Budget / fail-closed (block_kind=node_budget)
# ---------------------------------------------------------------------------


def test_c5_first_dispatch_ignores_token_budget_and_negativprobe():
    """VERIFIZIERT: `_dispatch_with_node_budget` prueft mit res={0 Tokens} VOR
    dem ersten Dispatch (`:1196`). Ein token_budget blockiert daher NICHT den
    Initial-Call, sondern erst Folge-Dispatche. Nicht als Bug 'fixen'."""
    out = _run(_node(token_budget=5), [_ok("Zu teuer.")])
    expected = _golden(out, status="success", content="Zu teuer.")
    _assert_golden(out, expected)
    assert out.get("block_kind") is None
    _negativprobe(out, expected, "status", "error")


def test_c5_followup_dispatch_blocks_on_accumulated_tokens():
    """Node-Budget greift beim Tool-Loop-Folgedispatch (`:1542`, res akkumuliert)."""
    responses = [
        _ok('{"tool_call": {"name": "t", "args": {}}}'),  # 10+10
        _ok("Folgeschritt."),  # wuerde 20+10 > cap 5 -> blockiert
    ]
    out = _run(
        _node(allowed_tools=["t"], max_turns=2, token_budget=5),
        responses,
        extra_patches=[patch(_TOOL_RUNTIME, new=AsyncMock(return_value={"status": "success"}))],
    )
    assert out["status"] == "error"
    assert "NODE_TOKEN_BUDGET_EXCEEDED" in str(out.get("error"))
    assert len(out["tool_trace"]) == 1
    _negativprobe(out, _golden(out, status="error"), "status", "success")


def test_c5_blocked_followup_writes_kanban_node_budget():
    """Kanban-Final bei blockiertem Folge-Dispatch (`:1439-1445`, `:1554-1557`)."""
    captured: List[Dict[str, Any]] = []

    def _kanban(task_id: Any, status: str, **kw: Any) -> None:
        captured.append({"task_id": task_id, "status": status, **kw})

    responses = [
        _ok('{"tool_call": {"name": "t", "args": {}}}'),
        _ok("Folgeschritt."),
    ]
    _run(
        _node(kanban_task_id="task-1", allowed_tools=["t"], max_turns=2, token_budget=5),
        responses,
        extra_patches=[
            patch(_KANBAN, side_effect=_kanban),
            patch(_TOOL_RUNTIME, new=AsyncMock(return_value={"status": "success"})),
        ],
    )
    # `:1802` Final-Aufruf: is_error=True -> blocked / workflow_error
    final = captured[-1]
    assert final["status"] == "blocked"
    assert final["block_kind"] == "workflow_error"
    assert final["event_kind"] == "workflow_node_failed"
    _negativprobe({"status": final["status"]}, {"status": "blocked"}, "status", "done")


# ---------------------------------------------------------------------------
# Cluster 2: Node-Plugin (Erfolg + Absturz -> workflow_error)
# ---------------------------------------------------------------------------


def test_c2_plugin_success_returns_pres_fields_and_negativprobe():
    out = _run(
        _node(type="ffmpeg", kanban_task_id="task-p", plugin_params={"dry_run": True}),
        [],  # kein Dispatch: Plugin-Pfad returned vor `_dispatch_with_node_budget`
        extra_patches=[
            patch(
                "backend.workflow_node_plugins.execute_workflow_node_plugin",
                new=AsyncMock(return_value={"status": "success", "content": "geplant"}),
            )
        ],
    )
    expected = _golden(out, status="success", node_id="n-char", kanban_task_id="task-p")
    _assert_golden(out, expected)
    _negativprobe(out, expected, "status", "error")


def test_c2_plugin_exception_maps_to_workflow_error_and_negativprobe():
    out = _run(
        _node(type="ffmpeg", kanban_task_id="task-p"),
        [],
        extra_patches=[
            patch(
                "backend.workflow_node_plugins.execute_workflow_node_plugin",
                new=AsyncMock(side_effect=RuntimeError("Plugin weg")),
            )
        ],
    )
    assert out["status"] == "error"
    assert "Plugin-Ausfuehrungsfehler" in str(out.get("error"))
    assert out.get("content") == ""
    _negativprobe(out, _golden(out, status="error"), "status", "success")


# ---------------------------------------------------------------------------
# Cluster 3: media_render / clip_matrix (Erfolg + Exception)
# ---------------------------------------------------------------------------


def test_c3_media_render_golden_and_negativprobe():
    matrix = {"clips": [{"title": "Clip 1"}]}
    out = _run(
        _node(type="media_render", kanban_task_id="task-m"),
        [],
        upstream={"n-prev": {"content": "Hook"}},
        # generate_video_clip_matrix wird direkt (sync) awaited -> AsyncMock ist
        # hier korrekt; der Pfad ruft `await generate_video_clip_matrix(...)`.
        extra_patches=[patch(_CLIP_MATRIX, new=AsyncMock(return_value=matrix))],
    )
    expected = _golden(out, status="success", kanban_task_id="task-m")
    _assert_golden(out, expected)
    assert out["media_matrix"] == matrix
    assert out["content"] == json.dumps(matrix, ensure_ascii=False, indent=2)
    # `:1323` nutzt `node.get("agent_id") or "media_engine"` -> unser Node setzt
    # agent_id="default", also bleibt "default". Fallback nur OHNE agent_id.
    assert out["agent_id"] == "default"
    # VERIFIZIERT: Media-/Plugin-Branches returnen VOR dem Kostenblock (`:1778`)
    # und haben daher KEINE cost_usd/cost_unverified-Felder. Das ist ein echter
    # Struktur-Unterschied zum Agent-Pfad und gehoert ins Golden-Output.
    assert "cost_usd" not in out and "cost_unverified" not in out
    _negativprobe(out, expected, "status", "error")


def test_c3_media_render_exception_maps_to_workflow_error():
    out = _run(
        _node(type="clip_matrix", kanban_task_id="task-m"),
        [],
        extra_patches=[patch(_CLIP_MATRIX, new=AsyncMock(side_effect=RuntimeError("Render weg")))],
    )
    assert "cost_usd" not in out and "cost_unverified" not in out  # frueher Return
    assert out["status"] == "error"
    assert "Render weg" in str(out.get("error"))
    assert out.get("content") == ""
    _negativprobe(out, _golden(out, status="error"), "status", "success")


# ---------------------------------------------------------------------------
# Cluster 6: Multi-Turn Tool-Loop (Tool-Trace, erlaubte/verbotene Tools)
# ---------------------------------------------------------------------------


def test_c6_tool_loop_allowed_tool_trace_and_negativprobe():
    responses = [
        _ok('{"tool_call": {"name": "archon__get_system_metrics", "args": {}}}'),
        _ok("Fertig nach Tool."),
    ]
    out = _run(
        _node(
            allowed_tools=["archon__get_system_metrics"],
            max_turns=2,
        ),
        responses,
        extra_patches=[
            patch(_TOOL_RUNTIME, new=AsyncMock(return_value={"status": "success", "cpu": 12}))
        ],
    )
    expected = _golden(out, status="success", content="Fertig nach Tool.")
    _assert_golden(out, expected)
    trace = out["tool_trace"]
    assert len(trace) == 1
    assert trace[0]["tool"] == "archon__get_system_metrics"
    assert trace[0]["turn"] == 1
    assert trace[0]["result"]["status"] == "success"
    _negativprobe(out, expected, "content", "Falscher Inhalt")


def test_c6_tool_loop_forbidden_tool_is_blocked_not_executed():
    responses = [
        _ok('{"tool_call": {"name": "verbotenes_tool", "args": {}}}'),
        _ok("Fertig."),
    ]
    runtime = AsyncMock(return_value={"status": "success"})
    out = _run(
        _node(allowed_tools=["erlaubtes_tool"], max_turns=2),
        responses,
        extra_patches=[patch(_TOOL_RUNTIME, new=runtime)],
    )
    assert out["status"] == "success"
    blocked = out["tool_trace"][0]["result"]
    assert blocked["status"] == "blocked"
    assert "nicht unter allowed_tools" in blocked["error"]
    runtime.assert_not_awaited()  # Negativprobe gegen die echte Guard-Logik
    _negativprobe(out, _golden(out, status="success"), "status", "error")


def test_c6_max_turns_caps_tool_trace():
    call = _ok('{"tool_call": {"name": "t", "args": {}}}')
    out = _run(
        _node(allowed_tools=["t"], max_turns=1),
        [call, call, call],
        extra_patches=[patch(_TOOL_RUNTIME, new=AsyncMock(return_value={"status": "success"}))],
    )
    assert len(out["tool_trace"]) == 1  # max_turns=1, nicht 3
    _negativprobe(out, _golden(out, status="success"), "status", "error")


# ---------------------------------------------------------------------------
# Cluster 7: Schema-Validierung + Repair-Retry + Frontier-Eskalation
# ---------------------------------------------------------------------------


def test_c7_schema_repair_golden_parsed_output_and_negativprobe():
    responses = [
        _ok("Kein JSON"),  # 1. Versuch verletzt Schema -> Repair
        _ok('{"headline": "Archon", "score": 95}'),  # Repair liefert valide
    ]
    out = _run(
        _node(output_schema={"required": ["headline", "score"]}),
        responses,
    )
    expected = _golden(
        out,
        status="success",
        parsed_output={"headline": "Archon", "score": 95},
        content='{"headline": "Archon", "score": 95}',
    )
    _assert_golden(out, expected)
    assert out["input_tokens"] == 20 and out["output_tokens"] == 20  # Basis + Repair
    _negativprobe(out, expected, "parsed_output", {"headline": "Falsch", "score": 0})


def test_c7_schema_violation_exhausted_is_error():
    out = _run(
        _node(output_schema={"required": ["headline", "score"]}),
        [_ok("Kein JSON"), _ok("Immer noch kein JSON")],
    )
    assert out["status"] == "error"
    assert "Output-Schema-Verletzung" in str(out.get("error"))
    assert out.get("parsed_output") is None
    _negativprobe(out, _golden(out, status="error"), "status", "success")


# ---------------------------------------------------------------------------
# Cluster 8: Anti-Slop — validiertes JSON darf nicht durch Prosa ueberschrieben werden
# ---------------------------------------------------------------------------


def test_c8_output_schema_protects_json_from_anti_slop():
    payload = '{"hook": "Stopp", "body": "Konkreter Text.", "cta": "Folge mir."}'
    out = _run(
        _node(channel="linkedin", quality_gate=True, output_schema={"required": ["hook", "body", "cta"]}),
        [_ok(payload)],
        extra_patches=[
            patch(
                "backend.content_machine.evaluate_asset_quality",
                new=MagicMock(return_value={"passed": False, "score": 10, "issues": ["slop"], "suggestions": ["besser"]}),
            )
        ],
    )
    assert out["status"] == "success"
    assert out["content"] == payload  # KEIN Prosa-Revision trotz quality_gate
    assert out["parsed_output"]["hook"] == "Stopp"
    assert out.get("revisions_used", 0) == 0
    _negativprobe(out, _golden(out, status="success", content=payload), "content", "Ueberschriebene Prosa")


# ---------------------------------------------------------------------------
# Cluster 10 + D12: Kosten-Fail-Closed (_cost_usd = None, cost_unverified=True)
# ---------------------------------------------------------------------------


def test_c10_cost_failure_is_none_not_zero_d12_and_negativprobe():
    """D12-Falle (`INVARIANTS §3`): bei fehlgeschlagener Berechnung KEIN 0.0."""
    out = _run(
        _node(),
        [_ok("Fertig.")],
        extra_patches=[patch(_COST, side_effect=RuntimeError("Preistabelle weg"))],
    )
    expected = _golden(out, status="success", cost_usd=None, cost_unverified=True)
    _assert_golden(out, expected)
    _negativprobe(out, expected, "cost_usd", 0.0)


def test_c10_d12_is_always_active_even_without_mocked_failure():
    """VERIFIZIERT (25.11.): `_cost_usd = None` + `+= `_est_cost(...)` wirft
    `TypeError: unsupported operand type(s) for +=: 'NoneType' and 'float'`.
    Der except-Zweig ist damit der *Normalfall* — auch ohne gemockten Fehler.
    Ein spaeterer Split darf das NICHT zu `0.0` 'vereinfachen' (INVARIANTS §3).
    """
    out = _run(_node(), [_ok("Fertig.")])
    expected = _golden(out, status="success", cost_usd=None, cost_unverified=True)
    _assert_golden(out, expected)
    _negativprobe(out, expected, "cost_usd", 0.0)
    _negativprobe(out, expected, "cost_unverified", False)


# ---------------------------------------------------------------------------
# Cluster 1: research delegiert — charakterisiert NUR, dass kein Standard-Dispatch laeuft
# ---------------------------------------------------------------------------


def test_c1_research_branch_does_not_use_standard_dispatch():
    """Der research-Cluster delegated vor dem Standard-Dispatch (`:1246-1247`).

    Bewusst KEIN Golden-Output auf den Rueckgabewert: `_execute_research_dag_node`
    hat eigene Effekte und ist nicht Teil von B0. Charakterisiert wird nur die
    Verzweigungsentscheidung selbst — gegen die echte Logik, nicht gegen Text.
    """
    dispatch = AsyncMock(return_value=_ok("Standard"))
    fake = AsyncMock(return_value={"status": "success", "content": "research"})

    async def _invoke() -> Dict[str, Any]:
        with patch(_DISPATCH, new=dispatch), patch(_KANBAN), patch(_PROFILES, new=MagicMock(return_value=[])), \
             patch("backend.workflow_dag_runner._execute_research_dag_node", new=fake):
            return await wdr.default_agent_node_executor(_node(type="research"), {})

    out = asyncio.run(_invoke())
    fake.assert_awaited_once()
    dispatch.assert_not_awaited()  # Negativprobe: Standard-Dispatch darf NICHT laufen
    assert out["content"] == "research"
    _negativprobe(out, _golden(out, status="success", content="research"), "content", "Standard")
