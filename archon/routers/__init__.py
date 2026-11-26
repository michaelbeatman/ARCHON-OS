"""Archon OS App-Paket.

D2/2d: Die Router-Registrierung wird schrittweise aus ``main.py`` hierher
gehoben. Auf Paketebene werden AUSSCHLIESSLICH stdlib-/fastapi-Importe
geladen (``os``, ``typing``, ``FastAPI``, ``StaticFiles``) — keine Router-
und kein ``main``-Import. Die Router-Imports bleiben bewusst zur Aufrufzeit
INNERHALB der Funktion: sie lagen in ``main.py`` in try/except-Bloecken
(fail-soft, ``_ROUTER_LOAD_ERRORS``) und duerfen beim blossen ``import main``
nicht hart scheitern. ``archon.routers.__init__`` wird bereits bei
``main.py:166`` ausgefuehrt; ein Router-Import zur Init-Zeit wuerde diesen
Schutz umgehen und ``import main`` bei einem fehlenden Router abbrechen.

KORREKTUR nach dem unabhaengigen Review (26.11.): die urspruengliche
Begruendung „Router-Module importieren main zurueck -> Zyklus" ist fuer
GENAU diese zwei Module nicht belegbar (0 Treffer in ``archon/routers/*.py``,
``_rbac.py:7-8`` dokumentiert das Gegenteil). Der lazy Import bleibt richtig,
die Begruendung war es nicht. Ebenso ist ``StaticFiles`` entgegen der
urspruenglichen Formulierung ein Modul-Ebenen-Import (harmlos).

Teilschritt 1: die zwei Sonderbloecke ``views_core`` und ``operations``.
Reine Extraktion der Registrierungslogik: Fehler-Praefixe, Prints,
Mount-Reihenfolge und die Identitaet der ``load_errors``-Liste bleiben 1:1
erhalten. Bewusst NICHT veraendert (INVARIANTS §3): die bedingte
``/builds/apps``-Mount-Abfrage, die beiden getrennten try/except-Bloecke
und die Reihenfolge der Aufrufe.

BEWUSSTE DELTA (kein „gar keine Veraenderung"): ``views_core_router``,
``operations_router``, ``get_apps_dir`` und ``apps_static_dir`` waren in
``main.py`` Modul-Globals und sind jetzt funktionslokal. Repo-weite Suche:
0 Referenzen, kein ``from main import *``; fuer externe ``getattr``/REPL-
Nutzung nicht beweisbar. Bewusst NICHT wiederhergestellt, weil ein
Modul-Level-Re-Import die fail-soft-Semantik zerstoeren wuerde.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, NamedTuple

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

__all__ = ["register_special_routers", "LateRouterDeps", "register_late_routers"]


def register_special_routers(app: FastAPI, load_errors: List[str]) -> None:
    """Registriert die zwei Sonder-Router an ihrer urspruenglichen Position.

    ``load_errors`` ist dieselbe Liste wie ``main._ROUTER_LOAD_ERRORS`` (kein
    Rebind): ``_assert_router_health()`` und ``/readyz`` lesen das Original.
    Die Aufrufstelle in ``main.py`` bleibt exakt zwischen ``_proxies_router``
    und dem ``/static/avatars``-Endpoint — Registrierungsreihenfolge ist
    Pfad-Praezedenz (INVARIANTS #7).
    """
    try:
        from views_core import get_apps_dir
        from views_core import router as views_core_router

        app.include_router(views_core_router)
        apps_static_dir = get_apps_dir()
        if os.path.exists(apps_static_dir):
            app.mount("/builds/apps", StaticFiles(directory=apps_static_dir), name="builds_apps")
    except Exception as e_views:
        load_errors.append("views_core: " + str(e_views))
        print(f"Error mounting views_core: {e_views}")

    try:
        from archon.routers.operations import router as operations_router

        app.include_router(operations_router)
        print("Operations API mounted successfully.")
    except Exception as e_ops:
        load_errors.append("operations_api: " + str(e_ops))
        print(f"Error mounting operations_api: {e_ops}")


logger = logging.getLogger("archon_os")


class LateRouterDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Abhaengigkeiten aus main.py (S3-Muster).

    Bewusst KEIN Rueckimport auf main: die 19 Symbole kommen explizit als
    Callables/Objekte herein (Kartierung §6c). ``profiles_service`` gehoert
    dazu, weil sein configure-Block bewusst innerhalb des Spans liegt.
    """
    load_mission_control_data: Any
    save_mission_control_data: Any
    api_get_hermes_profiles: Any
    load_boardroom_frameworks: Any
    load_roles: Any
    save_all_agent_profiles: Any
    sync_org_hierarchy_node: Any
    invalidate_paperclip_agents_cache: Any
    profiles_service: Any
    load_json: Any
    save_json: Any
    broadcast_event: Any
    require_admin: Any
    skills_engine: Any
    get_live_telemetry_metrics: Any
    sync_task_to_obsidian: Any
    execute_mission_control_task: Any
    finalize_approval: Any
    fan_in: Any


def register_late_routers(
    app: FastAPI, load_errors: List[str], deps: LateRouterDeps
) -> None:
    """29 try/except-Bloecke (30 Includes) 1:1 aus main.py:2841-3135.

    Aufruf an exakt alter Position: nach dem RBAC-Rollenzaun, vor
    ``_assert_router_health``. Reihenfolge = Pfad-Praezedenz (INVARIANTS #7).
    ``load_errors`` ist dieselbe Liste wie ``main._ROUTER_LOAD_ERRORS``.
    """
    try:
        from archon.routers.crm import router as _crm_router
        app.include_router(_crm_router)
    except Exception as _e_crm:
        logger.warning(f"[Router] crm nicht geladen: {_e_crm}")

        load_errors.append("crm: " + str(_e_crm))
    try:
        from archon.routers.erp import router as _erp_router
        app.include_router(_erp_router)
    except Exception as _e_erp:
        logger.warning(f"[Router] erp nicht geladen: {_e_erp}")

        load_errors.append("erp: " + str(_e_erp))
    try:
        from archon.routers.corporate import router as _corporate_router
        app.include_router(_corporate_router)
    except Exception as _e_corporate:
        logger.warning(f"[Router] corporate nicht geladen: {_e_corporate}")

        load_errors.append("corporate: " + str(_e_corporate))
    try:
        from archon.routers.security import router as _security_router
        app.include_router(_security_router)
    except Exception as _e_security:
        logger.warning(f"[Router] security nicht geladen: {_e_security}")

        load_errors.append("security: " + str(_e_security))
    try:
        from archon.routers.execution import router as _execution_router
        app.include_router(_execution_router)
    except Exception as _e_execution:
        logger.warning(f"[Router] execution nicht geladen: {_e_execution}")

        load_errors.append("execution: " + str(_e_execution))
    try:
        from archon.routers.memory import router as _memory_router
        app.include_router(_memory_router)
    except Exception as _e_memory:
        logger.warning(f"[Router] memory nicht geladen: {_e_memory}")

        load_errors.append("memory: " + str(_e_memory))
    try:
        from archon.routers.context_packages import router as _context_packages_router
        app.include_router(_context_packages_router)
    except Exception as _e_context_packages:
        logger.warning(f"[Router] context_packages nicht geladen: {_e_context_packages}")

        load_errors.append("context_packages: " + str(_e_context_packages))
    try:
        from archon.routers.routergate import router as _routergate_router
        app.include_router(_routergate_router)
    except Exception as _e_routergate:
        logger.warning(f"[Router] routergate nicht geladen: {_e_routergate}")

        load_errors.append("routergate: " + str(_e_routergate))
    try:
        from archon.routers.voice import router as _voice_router
        app.include_router(_voice_router)
    except Exception as _e_voice:
        logger.warning(f"[Router] voice nicht geladen: {_e_voice}")

        load_errors.append("voice: " + str(_e_voice))
    try:
        from archon.routers.swarm import router as _swarm_router
        app.include_router(_swarm_router)
    except Exception as _e_swarm:
        logger.warning(f"[Router] swarm nicht geladen: {_e_swarm}")

        load_errors.append("swarm: " + str(_e_swarm))
    try:
        from archon.routers.contracts import router as _contracts_router
        app.include_router(_contracts_router)
    except Exception as _e_contracts:
        logger.warning(f"[Router] contracts nicht geladen: {_e_contracts}")

        load_errors.append("contracts: " + str(_e_contracts))


    # --- Weitere ausgelagerte Router (Stufe 2) ---
    try:
        from archon.routers.plugins import router as _plugins_router2
        app.include_router(_plugins_router2)
    except Exception as _e2_plugins:
        logger.warning(f"[Router] plugins nicht geladen: {_e2_plugins}")

        load_errors.append("plugins: " + str(_e2_plugins))
    try:
        from archon.routers.governance import (
            configure as _governance_configure,
        )
        from archon.routers.governance import (
            router as _governance_router2,
        )
        _governance_configure(
            _load_mission_control_data=deps.load_mission_control_data,
            _save_mission_control_data=deps.save_mission_control_data,
            api_get_hermes_profiles=deps.api_get_hermes_profiles,
        )
        app.include_router(_governance_router2)
    except Exception as _e2_governance:
        logger.warning(f"[Router] governance nicht geladen: {_e2_governance}")

        load_errors.append("governance: " + str(_e2_governance))
    try:
        from archon.routers.templates import router as _templates_router2
        app.include_router(_templates_router2)
    except Exception as _e2_templates:
        logger.warning(f"[Router] templates nicht geladen: {_e2_templates}")

        load_errors.append("templates: " + str(_e2_templates))
    try:
        from archon.routers.boardroom import (
            configure as _boardroom_configure,
        )
        from archon.routers.boardroom import (
            router as _boardroom_router2,
        )
        _boardroom_configure(
            load_boardroom_frameworks=deps.load_boardroom_frameworks,
            load_roles=deps.load_roles,
            api_get_hermes_profiles=deps.api_get_hermes_profiles,
        )
        app.include_router(_boardroom_router2)
    except Exception as _e2_boardroom:
        logger.warning(f"[Router] boardroom nicht geladen: {_e2_boardroom}")

        load_errors.append("boardroom: " + str(_e2_boardroom))

    try:
        from archon.routers.llm_providers import router as _llm_providers_r
        app.include_router(_llm_providers_r)
    except Exception as _err_llmp:
        logger.warning(f"[Router] llm_providers nicht geladen: {_err_llmp}")

        load_errors.append("llm_providers: " + str(_err_llmp))

    try:
        from archon.routers.hermes_profiles import (
            configure as _hp_configure,
        )
        from archon.routers.hermes_profiles import (
            router as _hermes_profiles_r,
        )
        _hp_configure(
            save_all_agent_profiles=deps.save_all_agent_profiles,
            _sync_org_hierarchy_node=deps.sync_org_hierarchy_node,
            invalidate_paperclip_agents_cache=deps.invalidate_paperclip_agents_cache,
        )
        app.include_router(_hermes_profiles_r)
    except Exception as _err_hp:
        logger.warning(f"[Router] hermes_profiles nicht geladen: {_err_hp}")

        load_errors.append("hermes_profiles: " + str(_err_hp))

    # Der Profil-Service traegt nur den Organigramm-Sync als echte Abhaengigkeit.
    # Bewusst ausserhalb des Router-try: der Gate-Pfad braucht ihn auch dann.
    try:
        deps.profiles_service.configure(org_sync_node=deps.sync_org_hierarchy_node)
    except Exception as _err_ps:
        logger.warning(f"[Services] profiles_service.configure fehlgeschlagen: {_err_ps}")

    try:
        from archon.routers.system import (
            configure as _system_configure,
        )
        from archon.routers.system import (
            router as _system_r,
        )
        _system_configure(
            _load_json=deps.load_json,
            _save_json=deps.save_json,
            broadcast_event=deps.broadcast_event,
            require_admin=deps.require_admin,
        )
        app.include_router(_system_r)
    except Exception as _err_sys:
        logger.warning(f"[Router] system nicht geladen: {_err_sys}")

        load_errors.append("system: " + str(_err_sys))

    try:
        from archon.routers.skills import (
            configure as _skills_configure,
        )
        from archon.routers.skills import (
            router as _skills_r,
        )
        _skills_configure(
            skills_engine=deps.skills_engine,
            api_get_hermes_profiles=deps.api_get_hermes_profiles,
        )
        app.include_router(_skills_r)
    except Exception as _err_sk:
        logger.warning(f"[Router] skills nicht geladen: {_err_sk}")

        load_errors.append("skills: " + str(_err_sk))

    try:
        from archon.routers.mission_control import (
            configure as _mc_configure,
        )
        from archon.routers.mission_control import (
            router as _mc_router,
        )
        # Nur die Original-Funktionen aus main.py injizieren: die Kopien in
        # archon/core/runtime.py sind NICHT verhaltensgleich (Telemetrie filtert
        # dort 15 Minuten statt Tagesbeginn, _sync_task_to_obsidian nutzt eine
        # eigene _slugify()-Hilfe und erzeugt andere Dateinamen).
        _mc_configure(
            telemetry=deps.get_live_telemetry_metrics,
            sync_obsidian=deps.sync_task_to_obsidian,
            execute=deps.execute_mission_control_task,
            finalize_approval=deps.finalize_approval,
            fan_in=deps.fan_in,
        )
        app.include_router(_mc_router)
    except Exception as _err_mc:
        logger.warning(f"[Router] mission_control nicht geladen: {_err_mc}")

        load_errors.append("mission_control: " + str(_err_mc))

    try:
        from archon.routers.onboarding import router as _onboarding_r
        app.include_router(_onboarding_r)
    except Exception as _err_onb:
        logger.warning(f"[Router] onboarding nicht geladen: {_err_onb}")

        load_errors.append("onboarding: " + str(_err_onb))

    try:
        from archon.routers.demo import router as _demo_r
        app.include_router(_demo_r)
    except Exception as _err_demo:
        logger.warning(f"[Router] demo nicht geladen: {_err_demo}")

        load_errors.append("demo: " + str(_err_demo))

    try:
        from archon.routers.mcp_gateway import router as _mcp_gateway_r
        app.include_router(_mcp_gateway_r)
    except Exception as _err_mcp_gw:
        logger.warning(f"[Router] mcp_gateway nicht geladen: {_err_mcp_gw}")

        load_errors.append("mcp_gateway: " + str(_err_mcp_gw))

    try:
        from archon.routers.squad_packs import router as _squad_packs_r
        app.include_router(_squad_packs_r)
    except Exception as _err_sp:
        logger.warning(f"[Router] squad_packs nicht geladen: {_err_sp}")

        load_errors.append("squad_packs: " + str(_err_sp))

    try:
        from archon.routers.tenants import router as _tenants_r
        app.include_router(_tenants_r)
    except Exception as _err_ten:
        logger.warning(f"[Router] tenants nicht geladen: {_err_ten}")

        load_errors.append("tenants: " + str(_err_ten))

    try:
        from archon.routers.playbooks import router as _playbooks_r
        app.include_router(_playbooks_r)
    except Exception as _err_pb:
        logger.warning(f"[Router] playbooks nicht geladen: {_err_pb}")

        load_errors.append("playbooks: " + str(_err_pb))

    try:
        from archon.routers.preflight_shadow import router as _preflight_r
        app.include_router(_preflight_r)
    except Exception as _err_pf:
        logger.warning(f"[Router] preflight_shadow nicht geladen: {_err_pf}")

        load_errors.append("preflight_shadow: " + str(_err_pf))

    try:
        from archon.routers.epistemic_hygiene import router as _hygiene_r
        app.include_router(_hygiene_r)
    except Exception as _err_hyg:
        logger.warning(f"[Router] epistemic_hygiene nicht geladen: {_err_hyg}")

        load_errors.append("epistemic_hygiene: " + str(_err_hyg))

    try:
        from archon.routers.operations_calendar import router as _cal_r
        from archon.routers.operations_calendar import ws_router as _cal_ws_r
        app.include_router(_cal_r)
        app.include_router(_cal_ws_r)
    except Exception as _err_cal:
        logger.warning(f"[Router] operations_calendar nicht geladen: {_err_cal}")

        load_errors.append("operations_calendar: " + str(_err_cal))
