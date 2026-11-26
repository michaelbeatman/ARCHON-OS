"""D5 Characterization-Tests fuer core_dispatcher.py (INVARIANTS §3).

Sichert vor und nach der Cluster-Extraktion (archon/core/dispatcher_frameworks.py):
1. Alle mutable Globals & Laufzeit-Patch-Punkte auf core_dispatcher bleiben erhalten.
2. Laufzeit-Rebind von core_dispatcher.CATEGORIZED_FRAMEWORKS (wie main.py:1281 /
   boardroom.py:242) wirkt sofort in get_flat_framework_map() & get_framework_info()
   — ohne Split-Brain und ohne Mutation von DEFAULT_CATEGORIZED_FRAMEWORKS.
3. Monkeypatch auf core_dispatcher.get_framework_info wirkt weiterhin in
   build_final_system_prompt().
4. AST-Vertrag fuer backend/workflow_dag_runner.py (import core_dispatcher vor
   core_dispatcher.dispatch_to_omniroute_or_container) inkl. echter Negativprobe.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path
import pytest

import core_dispatcher

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_import_before_dispatch_call(source: str) -> bool:
    """Prueft AST-basiert, ob in derselben Funktion `import core_dispatcher`
    vor `core_dispatcher.dispatch_to_omniroute_or_container(...)` steht.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            import_line = None
            call_line = None
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    if any(alias.name == "core_dispatcher" for alias in sub.names):
                        import_line = sub.lineno if import_line is None else min(import_line, sub.lineno)
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    if (
                        sub.func.attr == "dispatch_to_omniroute_or_container"
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "core_dispatcher"
                    ):
                        call_line = sub.lineno if call_line is None else min(call_line, sub.lineno)
            if import_line is not None and call_line is not None and import_line < call_line:
                return True
    return False


def test_d5_mutable_globals_and_patch_targets_present():
    """Alle INVARIANTS-§3-Globals und Patch-Ziele muessen direkt auf core_dispatcher liegen."""
    required_globals = (
        "CATEGORIZED_FRAMEWORKS",
        "CATEGORIZED_FRAMEWORKS_EN",
        "DEFAULT_CATEGORIZED_FRAMEWORKS",
        "DEFAULT_CATEGORIZED_FRAMEWORKS_EN",
        "UNIVERSAL_METHODOLOGY_HEADER",
        "UNIVERSAL_METHODOLOGY_HEADER_EN",
        "MAX_CONCURRENT_AGENT_TASKS",
        "_TASK_SEMAPHORES",
        "_DISPATCHER_HTTP_CLIENTS",
        "_PROMPT_VERSION_CTX",
        "_STRUCTURED_OUTPUT_SCHEMA_CTX",
        "httpx",
    )
    required_callables = (
        "dispatch_to_omniroute_or_container",
        "_dispatch_to_omniroute_or_container_exec",
        "_dispatch_to_omniroute_or_container_impl",
        "dispatch_to_external_agent",
        "stream_boardroom_debate",
        "run_boardroom_debate",
        "get_flat_framework_map",
        "get_framework_info",
        "build_final_system_prompt",
        "close_dispatcher_clients",
    )
    for name in required_globals:
        assert hasattr(core_dispatcher, name), f"Fehlender Mutable-Global auf core_dispatcher: {name}"
    for name in required_callables:
        assert callable(getattr(core_dispatcher, name, None)), f"Fehlendes Patch-Ziel auf core_dispatcher: {name}"


def test_d5_runtime_rebind_of_categorized_frameworks_has_no_split_brain(monkeypatch):
    """Laufzeit-Rebind (wie main.py:1281 / boardroom.py:242) muss sofort in den Helpern wirken."""
    custom_fw = {
        "99. Runtime-Test": {
            "D5-Rebind-Probe": "EXAKT_DIESER_REBIND_TEXT_D5",
        }
    }
    orig_default_keys = set(core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS.keys())

    monkeypatch.setattr(core_dispatcher, "CATEGORIZED_FRAMEWORKS", copy.deepcopy(custom_fw))

    flat = core_dispatcher.get_flat_framework_map(lang="de")
    assert "D5-Rebind-Probe" in flat
    assert flat["D5-Rebind-Probe"]["system_instruction"] == "EXAKT_DIESER_REBIND_TEXT_D5"

    info = core_dispatcher.get_framework_info("D5-Rebind-Probe", lang="de")
    assert info["system_instruction"] == "EXAKT_DIESER_REBIND_TEXT_D5"

    # DEFAULT_CATEGORIZED_FRAMEWORKS darf durch den Laufzeit-Rebind nicht mutiert sein
    assert set(core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS.keys()) == orig_default_keys
    assert "99. Runtime-Test" not in core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS


def test_d5_monkeypatch_on_get_framework_info_still_reaches_build_final_system_prompt(monkeypatch):
    """Patch-Punkt-Vertrag: Monkeypatch auf core_dispatcher.get_framework_info bleibt wirksam."""
    monkeypatch.setattr(
        core_dispatcher,
        "get_framework_info",
        lambda name, lang="": {"summary": "patched", "system_instruction": "PATCHED_FW_INSTRUCTION_D5"},
    )
    prompt = core_dispatcher.build_final_system_prompt("CLEAR-Model", base_system_prompt="BASE_PROMPT", lang="de")
    assert "PATCHED_FW_INSTRUCTION_D5" in prompt
    assert "BASE_PROMPT" in prompt


def test_d5_workflow_dag_runner_keeps_import_core_dispatcher_before_dispatch():
    """AST-Vertrag fuer INVARIANTS §3: import core_dispatcher vor Dispatch-Aufruf (+ Negativprobe)."""
    dag_src = (REPO_ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    assert _has_import_before_dispatch_call(dag_src), (
        "backend/workflow_dag_runner.py muss `import core_dispatcher` vor "
        "`core_dispatcher.dispatch_to_omniroute_or_container` behalten."
    )
    # Echte Negativprobe gegen den AST-Pruefer selbst: ohne Import muss er False liefern
    broken_src = (
        "async def _call(kwargs):\n"
        "    return await core_dispatcher.dispatch_to_omniroute_or_container(**kwargs)\n"
    )
    assert _has_import_before_dispatch_call(broken_src) is False
