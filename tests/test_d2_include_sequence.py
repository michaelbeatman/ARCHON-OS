# -*- coding: utf-8 -*-
"""Review-Fix zu fe9cf778 — die 6 Test-Blindflecken des Zweitblicks.

Der unabhaengige Review bestaetigte den CODE (BYTE_DIFFS=0 ueber 295 Zeilen),
fand aber: die Charakterisierung war schwaecher als ihre Behauptung. Dieser
Commit schliesst die Funde, ohne Produktionscode anzutasten.

* Fund 1: exakte Reihenfolge ALLER 75 Includes als committeter Ratchet
  (bisher nur im Temp-A/B-Skript ausserhalb des Repos).
* Fund 2: LateRouterDeps feldweise per ``is`` an die echten main-Symbole
  gebunden — ein stiller Tausch zweier Callables wird jetzt rot.
* Fund 3: ``profiles_service.configure`` wird ueber einen Spy gebunden.
* Fund 4: das zweite operations_calendar-Include (_cal_ws_r) ist eine reine
  WebSocket-Route, unsichtbar in openapi()["paths"] — hier ueber den
  include_router-Spy sichtbar gemacht.
* Fund 6: bewusstes Delta der funktionslokalen Aliase charakterisiert
  (test_v8-Aequivalent zu 2d/1).

Fund 5 (tautologische Negativproben, nur startswith, fehlende caplog-
Pruefung) wird in tests/test_d2_late_routers.py und
tests/test_d2_router_special_blocks.py::test_v5 behoben.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Tuple

import pytest
from fastapi import FastAPI

import main as app_main
from archon.routers import register_late_routers

# Gemessen per Spy auf FastAPI.include_router VOR ``import main`` (75 Aufrufe).
# Signatur = (erster Route-Pfad, Typ der ersten Route). Die WebSocket-Route des
# operations_calendar-Blocks (Fund 4) bleibt enthalten; der letzte Eintrag ist
# seit W4-C der audited Liability-Ack-Router.
_EXPECTED_INCLUDE_SEQUENCE = [
    ('/api/v1/agent/{agent_id}/activity', 'APIRoute'),
    ('/api/settings', 'APIRoute'),
    ('/api/oracle/feed', 'APIRoute'),
    ('/api/themes', 'APIRoute'),
    ('/api/services', 'APIRoute'),
    ('/api/run', 'APIRoute'),
    ('/api/v1/gateway/list', 'APIRoute'),
    ('/api/v1/watchdog/config', 'APIRoute'),
    ('/api/v1/quickchat/session/{profile_id}', 'APIRoute'),
    ('/api/v1/ui/save-text-replacements', 'APIRoute'),
    ('/api/chat/context-status', 'APIRoute'),
    ('/api/v1/brain/galaxy-data', 'APIRoute'),
    ('/api/v1/notebooks', 'APIRoute'),
    ('/api/telegram/relay', 'APIRoute'),
    ('/api/permission-gates/{gate_id}/decide', 'APIRoute'),
    ('/api/hermes/config', 'APIRoute'),
    ('/api/chat/sessions', 'APIRoute'),
    ('/api/guardian/stats', 'APIRoute'),
    ('/api/hermes/settings', 'APIRoute'),
    ('/api/help/context/{view_id}', 'APIRoute'),
    ('/api/auth/status', 'APIRoute'),
    ('/api/marketplace/sources', 'APIRoute'),
    ('/api/v1/memory/stats', 'APIRoute'),
    ('/api/v1/settings/smtp', 'APIRoute'),
    ('/api/v1/security/scan-email', 'APIRoute'),
    ('/api/v1/research/providers', 'APIRoute'),
    ('/api/v1/hermes/update/check', 'APIRoute'),
    ('/api/v1/documents/parse', 'APIRoute'),
    ('/api/v1/deals', 'APIRoute'),
    ('/api/vault/files', 'APIRoute'),
    ('/api/kanban', 'APIRoute'),
    ('/api/v2/security/warrants/issue', 'APIRoute'),
    ('/api/v2/content-machine/channels', 'APIRoute'),
    ('/api/v1/container/settings', 'APIRoute'),
    ('/api/v1/container/exec', 'APIRoute'),
    ('/api/proxy', 'APIRoute'),
    ('/api/v1/hr/personalakte/{agent_id}', 'APIRoute'),
    ('/api/prompt-studio/upload-context', 'APIRoute'),
    ('/omniroute-proxy/{path:path}', 'APIRoute'),
    ('/api/views/inbox/items', 'APIRoute'),
    ('/api/operations/kanban/tasks', 'APIRoute'),
    ('/api/inbox-watcher/config', 'APIRoute'),
    ('/api/snapshots', 'APIRoute'),
    ('/api/rag/query', 'APIRoute'),
    ('/api/settings/model-routing', 'APIRoute'),
    ('/api/crm/contacts', 'APIRoute'),
    ('/api/erp/documents/{doc_id}/print', 'APIRoute'),
    ('/api/corporate/companies', 'APIRoute'),
    ('/api/security/mask-secrets', 'APIRoute'),
    ('/api/execution/map-reduce', 'APIRoute'),
    ('/api/memory/harvest', 'APIRoute'),
    ('/api/context-packages', 'APIRoute'),
    ('/api/router/benchmark', 'APIRoute'),
    ('/api/voice/speak', 'APIRoute'),
    ('/api/swarm/spawn-ephemeral-team', 'APIRoute'),
    ('/api/v1/contracts', 'APIRoute'),
    ('/api/v1/plugins', 'APIRoute'),
    ('/api/v1/governance/ai-act/inventory', 'APIRoute'),
    ('/api/templates', 'APIRoute'),
    ('/api/boardroom/cancel', 'APIRoute'),
    ('/api/llm-providers/models', 'APIRoute'),
    ('/api/hermes/profiles', 'APIRoute'),
    ('/api/system/health', 'APIRoute'),
    ('/api/hermes/skills', 'APIRoute'),
    ('/api/mission-control/state', 'APIRoute'),
    ('/api/onboarding/status', 'APIRoute'),
    ('/api/demo/status', 'APIRoute'),
    ('/mcp/messages', 'APIRoute'),
    ('/api/v1/squad-packs/domains', 'APIRoute'),
    ('/api/v1/tenants/context', 'APIRoute'),
    ('/api/v1/playbooks', 'APIRoute'),
    ('/api/v1/preflight/estimate', 'APIRoute'),
    ('/api/v1/vault/epistemic-hygiene', 'APIRoute'),
    ('/api/v1/calendar/events', 'APIRoute'),
    ('/api/v1/calendar/ws', 'APIWebSocketRoute'),
    ('/api/v1/profiles/liability-ack', 'APIRoute'),  # W4-C / D15-H3
    ('/api/event-ledger/status', 'APIRoute'),  # M112
    ('/api/v1/compliance/inventory', 'APIRoute'),  # M68
    ('/api/policy-gates/policy', 'APIRoute'),  # M69
    ('', 'APIRoute'),  # M70/M74 (Prefix /api/needs-me wird am Include gesetzt)
]

# Fund 2: Feldname -> main-Symbol. Bindet die an der Aufrufstelle gebauten
# Deps an die echten Objekte, statt eine unabhaengige Testkopie zu bauen.
_DEP_BINDINGS: List[Tuple[str, str]] = [
    ("load_mission_control_data", "_load_mission_control_data"),
    ("save_mission_control_data", "_save_mission_control_data"),
    ("api_get_hermes_profiles", "api_get_hermes_profiles"),
    ("load_boardroom_frameworks", "load_boardroom_frameworks"),
    ("load_roles", "load_roles"),
    ("save_all_agent_profiles", "save_all_agent_profiles"),
    ("sync_org_hierarchy_node", "_sync_org_hierarchy_node"),
    ("invalidate_paperclip_agents_cache", "invalidate_paperclip_agents_cache"),
    ("profiles_service", "profiles_service"),
    ("load_json", "_load_json"),
    ("save_json", "_save_json"),
    ("broadcast_event", "broadcast_event"),
    ("require_admin", "require_admin"),
    ("skills_engine", "skills_engine"),
    ("get_live_telemetry_metrics", "_get_live_telemetry_metrics"),
    ("sync_task_to_obsidian", "_sync_task_to_obsidian"),
    ("execute_mission_control_task", "_execute_mission_control_task"),
    ("finalize_approval", "_finalize_synthesis_after_approval"),
    ("fan_in", "_fan_in_maybe_start_synthesis"),
]

# Fund 6: diese Aliase waren im Parent main-Globals, sind jetzt funktionslokal.
_LATE_ALIASES = [
    "_crm_router", "_erp_router", "_corporate_router", "_security_router",
    "_execution_router", "_memory_router", "_context_packages_router",
    "_routergate_router", "_voice_router", "_swarm_router",
    "_contracts_router", "_plugins_router2", "_governance_configure",
    "_governance_router2", "_templates_router2", "_boardroom_configure",
    "_boardroom_router2", "_llm_providers_r", "_hp_configure",
    "_hermes_profiles_r", "_system_configure", "_system_r",
    "_skills_configure", "_skills_r", "_mc_configure", "_mc_router",
    "_onboarding_r", "_demo_r", "_mcp_gateway_r", "_squad_packs_r",
    "_tenants_r", "_playbooks_r", "_preflight_r", "_hygiene_r",
    "_cal_r", "_cal_ws_r",
]


class _ProfileSpy:
    """Fund 3: zeichnet profiles_service.configure(...)-Aufrufe auf."""

    def __init__(self) -> None:
        self.calls: List[dict] = []

    def configure(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_s1_full_include_sequence_is_pinned() -> None:
    """Fund 1 + 4: exakte 75er-Sequenz gegen einen frischen main-Import.

    Der Spy sitzt auf FastAPI.include_router (Klassenebene), sieht also ALLE
    Includes unabhaengig davon, aus welchem Modul sie kommen — inklusive der
    WebSocket-Route, die in app.openapi()["paths"] unsichtbar ist.
    """
    wt = str(Path(__file__).resolve().parents[1])
    expected = [list(x) for x in _EXPECTED_INCLUDE_SEQUENCE]
    code = "\n".join([
        "import sys",
        f"sys.path.insert(0, {wt!r})",
        "import fastapi",
        "_calls = []",
        "_orig = fastapi.FastAPI.include_router",
        "def _spy(self, router, *a, **kw):",
        "    routes = getattr(router, 'routes', []) or []",
        "    first = routes[0] if routes else None",
        "    _calls.append([getattr(first, 'path', None) or '',",
        "                  type(first).__name__ if first is not None else ''])",
        "    return _orig(self, router, *a, **kw)",
        "fastapi.FastAPI.include_router = _spy",
        "import main",
        f"_expected = {expected!r}",
        "assert _calls == _expected, 'Include-Reihenfolge gekippt'",
        "assert len(_calls) == 80",
        "assert _calls[-1] == ['', 'APIRoute']",
        "assert ['/api/v1/calendar/ws', 'APIWebSocketRoute'] in _calls",
        "assert sum(1 for x in _calls if 'WebSocket' in x[1]) == 1",
        "# Negativprobe gegen eine vertauschte Reihenfolge (echte Mutation).",
        "_swapped = list(_expected)",
        "_swapped[0], _swapped[1] = _swapped[1], _swapped[0]",
        "try:",
        "    assert _calls == _swapped",
        "except AssertionError:",
        "    pass",
        "else:",
        "    raise AssertionError('NEGATIVPROBE: Vertauschung nicht erkannt')",
        "# Negativprobe gegen das geloeschte WS-Include (Fund 4).",
        "_mutated = [x for x in _calls if 'WebSocket' not in x[1]]",
        "try:",
        "    assert _mutated == _expected",
        "except AssertionError:",
        "    pass",
        "else:",
        "    raise AssertionError('NEGATIVPROBE: fehlende WS-Route nicht erkannt')",
        "print('SEQUENCE_OK')",
    ])
    env = os.environ.copy()
    seq_dir = Path(tempfile.gettempdir()) / "archon-2d-sequence"
    seq_dir.mkdir(parents=True, exist_ok=True)
    env["ARCHON_TEST_DB_ISOLATION"] = "1"
    env["ARCHON_DATA_DIR"] = str(seq_dir)
    env.setdefault("ARCHON_AUDIT_HMAC_KEY", "probe-only-" + "a" * 64)
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=wt, env=env,
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "SEQUENCE_OK" in proc.stdout, proc.stdout


def test_s2_late_router_deps_are_bound_to_real_main_symbols() -> None:
    """Fund 2: ein stiller Tausch zweier Callables muss rot werden."""
    deps = app_main._late_router_deps
    for field, attr in _DEP_BINDINGS:
        assert getattr(deps, field) is getattr(app_main, attr), (
            f"{field} ist nicht mehr main.{attr}"
        )
    # Negativprobe: ``is`` diskriminiert zwischen verschieden gemappten
    # Symbolen — der Vergleich ist kein tautologisches Immer-Gruen.
    with pytest.raises(AssertionError):
        assert getattr(deps, "load_json") is getattr(app_main, "_save_json")


def test_s3_profiles_service_configure_is_invoked() -> None:
    """Fund 3: der bewusst mitgewanderte Block ist nicht mehr ungetestet."""
    spy = _ProfileSpy()
    deps = app_main._late_router_deps._replace(profiles_service=spy)
    errors: List[str] = []
    register_late_routers(FastAPI(), errors, deps)

    assert errors == []
    assert spy.calls == [{"org_sync_node": deps.sync_org_hierarchy_node}], spy.calls
    # Negativprobe: ein fehlender Aufruf wuerde die Assertion rot machen.
    with pytest.raises(AssertionError):
        assert spy.calls == []


def test_s4_late_aliases_are_characterized_as_function_local() -> None:
    """Fund 6: bewusste Delta, kein stiller Drift (Aequivalent zu test_v8)."""
    for name in _LATE_ALIASES:
        assert not hasattr(app_main, name), (
            f"{name} ist wieder main-Global — Entscheidung pruefen"
        )
    assert hasattr(app_main, "_ROUTER_LOAD_ERRORS")
    with pytest.raises(AssertionError):
        assert not hasattr(app_main, "_ROUTER_LOAD_ERRORS")
