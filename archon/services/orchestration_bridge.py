"""Orchestration-Wrapper-Bruecke fuer main.py (M4).

Kapselt die 8 Wrapper-Funktionen um ``archon.core.orchestration`` per
S3-Call-Time-Injektion (``register_orchestration_bridge_deps_provider``),
damit ``main.py`` keine Orchestrierungs-Verdrahtung dupliziert und
Test-Monkeypatches auf ``main.*`` weiterhin zur Aufrufzeit greifen.
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple, Optional

from archon.core.orchestration import (
    _execute_mission_control_task as _orch_execute_mission_control_task,
)
from archon.core.orchestration import (
    _fan_in_maybe_start_synthesis as _orch_fan_in_maybe_start_synthesis,
)
from archon.core.orchestration import (
    _finalize_synthesis_after_approval as _orch_finalize_synthesis_after_approval,
)
from archon.core.orchestration import (
    _paperclip_hire_profile_by_id as _orch_paperclip_hire_profile_by_id,
)
from archon.core.orchestration import _run_synthesis_cascade as _orch_run_synthesis_cascade
from archon.core.orchestration import _set_agent_profile_status as _orch_set_agent_profile_status
from archon.core.orchestration import _tg_ping_synthesis as _orch_tg_ping_synthesis
from archon.core.orchestration import (
    _trigger_sandy_staffing_nomination as _orch_trigger_sandy_staffing_nomination,
)


class OrchestrationBridgeDeps(NamedTuple):
    dispatcher: Any
    load_mc: Callable[..., Any]
    save_mc: Callable[..., Any]
    update_mc: Callable[..., Any]
    write_mc_atomic: Callable[..., Any]
    mc_async_lock: Any
    ticker: Callable[..., Any]
    get_profiles: Callable[..., Any]
    sync_obsidian: Callable[..., Any]
    rolling_backup: Callable[..., Any]
    invalidate_profiles: Callable[..., Any]
    paths: dict[str, str]
    folder_namer: Callable[..., Any]
    build_dossier: Callable[..., Any]
    create_decision: Callable[..., Any]
    send_doc: Callable[..., Any]
    send_msg: Callable[..., Any]
    set_status: Callable[..., Any]
    paperclip_hire: Callable[..., Any]
    trigger_sandy: Callable[..., Any]
    fan_in: Callable[..., Any]
    tg_ping: Callable[..., Any]
    finalize_approval: Callable[..., Any]
    run_cascade: Callable[..., Any]


_DEPS_PROVIDER: Optional[Callable[[], OrchestrationBridgeDeps]] = None


def register_orchestration_bridge_deps_provider(
    provider: Callable[[], OrchestrationBridgeDeps],
) -> None:
    """Registriert den Call-Time-Dependency-Provider aus main.py (S3)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _deps() -> OrchestrationBridgeDeps:
    if _DEPS_PROVIDER is None:
        raise RuntimeError(
            "OrchestrationBridgeDeps provider not registered "
            "(call register_orchestration_bridge_deps_provider first)"
        )
    return _DEPS_PROVIDER()


async def _execute_mission_control_task(task_id: str) -> Any:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    return await _orch_execute_mission_control_task(
        task_id,
        dispatcher=d.dispatcher,
        load_mc=d.load_mc,
        save_mc=d.save_mc,
        # Atomares Read-Modify-Write: schreibt nur die Aenderungen DIESES Tasks
        # zurueck. Ohne diesen Parameter wuerde der ueber den LLM-Call hinweg
        # gehaltene Snapshot alle parallelen Aenderungen ueberschreiben (B1).
        update_mc=d.update_mc,
        ticker=d.ticker,
        get_profiles=d.get_profiles,
        sync_obsidian=d.sync_obsidian,
        trigger_sandy=d.trigger_sandy,
        fan_in=d.fan_in,
    )


def _paperclip_hire_profile_by_id(
    profile_id: str, profiles: list[Any], current_task_id: str = ""
) -> bool:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    return bool(
        _orch_paperclip_hire_profile_by_id(
            profile_id,
            profiles,
            current_task_id,
            set_status=d.set_status,
            ticker=d.ticker,
        )
    )


def _set_agent_profile_status(
    profile_id: str, status: str, task_id: str = ""
) -> bool:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    return bool(
        _orch_set_agent_profile_status(
            profile_id,
            status,
            task_id,
            rolling_backup=d.rolling_backup,
            invalidate_profiles=d.invalidate_profiles,
        )
    )


async def _trigger_sandy_staffing_nomination(
    parent_task: dict[str, Any], profiles: list[Any]
) -> None:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    await _orch_trigger_sandy_staffing_nomination(
        parent_task,
        profiles,
        dispatcher=d.dispatcher,
        load_mc=d.load_mc,
        save_mc=d.save_mc,
        update_mc=d.update_mc,
        ticker=d.ticker,
        get_profiles=d.get_profiles,
        paperclip_hire=d.paperclip_hire,
    )


async def _finalize_synthesis_after_approval(
    parent_pid: str,
    draft_path: str,
    synthese_text: str,
    approver_note: str,
    daten: Any = None,
) -> None:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    await _orch_finalize_synthesis_after_approval(
        parent_pid,
        draft_path,
        synthese_text,
        approver_note,
        daten,
        dispatcher=d.dispatcher,
        load_mc=d.load_mc,
        save_mc=d.save_mc,
        update_mc=d.update_mc,
        ticker=d.ticker,
        paths=d.paths,
        folder_namer=d.folder_namer,
        set_status=d.set_status,
        tg_ping=d.tg_ping,
    )


async def _fan_in_maybe_start_synthesis(parent_pid: str) -> None:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    await _orch_fan_in_maybe_start_synthesis(
        parent_pid,
        load_mc=d.load_mc,
        write_mc_atomic=d.write_mc_atomic,
        # Atomares Read-Modify-Write verhindert Lost Updates und Audit-Dupes.
        update_mc=d.update_mc,
        mc_async_lock=d.mc_async_lock,
        run_cascade=d.run_cascade,
    )


def _tg_ping_synthesis(
    parent_title: Any,
    parent_project_id: Any,
    synthese_text: Any,
    draft_path: Any,
    app_id: Any = None,
    dossier_dir: Any = None,
) -> None:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    _orch_tg_ping_synthesis(
        parent_title,
        parent_project_id,
        synthese_text,
        draft_path,
        app_id,
        dossier_dir,
        send_doc=d.send_doc,
        send_msg=d.send_msg,
        build_dossier=d.build_dossier,
    )


async def _run_synthesis_cascade(parent_project_id: str) -> None:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    d = _deps()
    await _orch_run_synthesis_cascade(
        parent_project_id,
        dispatcher=d.dispatcher,
        load_mc=d.load_mc,
        save_mc=d.save_mc,
        update_mc=d.update_mc,
        ticker=d.ticker,
        get_profiles=d.get_profiles,
        paths=d.paths,
        folder_namer=d.folder_namer,
        build_dossier=d.build_dossier,
        create_decision=d.create_decision,
        finalize_approval=d.finalize_approval,
        tg_ping=d.tg_ping,
    )
