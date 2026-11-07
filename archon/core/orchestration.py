"""
Orchestrierungskern für Mission Control — extrahiert aus main.py.

Alle externen Abhängigkeiten werden per Dependency Injection übergeben
(Defaults zeigen auf die echten Implementierungen für Backwards-Compat).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

# Lokale Imports (keine main.py, kein core_dispatcher)
from archon.core.mission_control import (
    _MC_ASYNC_LOCK,
    _load_mission_control_data as _default_load_mc,
    _save_mission_control_data as _default_save_mc,
    _write_mc_atomic,
)
from archon.core.runtime import logger


# Type aliases für DI
Dispatcher = Any  # core_dispatcher mit .dispatch_to_omniroute_or_container, .trigger_n8n_execution
LoadMC = Callable[[], Dict[str, Any]]
SaveMC = Callable[[Dict[str, Any]], None]
Ticker = Callable[[str, str], None]
GetProfiles = Callable[[], List[Dict[str, Any]]]
InvalidateProfiles = Callable[[], None]
RollingBackup = Callable[[str, int], None]
SyncObsidian = Callable[[Dict[str, Any]], str]
FolderNamer = Callable[[Dict[str, Any]], str]
TelegramSendDoc = Callable[[str, str, Optional[Dict]], bool]
TelegramSendMsg = Callable[[str, Optional[Dict]], bool]
BuildDossier = Callable[[str, str, str, str, str], str]
CreateDecision = Callable[..., Any]

# Pfad-Konstanten (können via paths-Dict überschrieben werden)
DEFAULT_OBSIDIAN_VAULT_DIR = "/opt/data/obsidian"
DEFAULT_WORKSPACE_DIR = "/mnt/raid/AgenticOS-2026"


def _task_by_id(data: dict, task_id: str):
    return next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)


def _merge_task_delta(fresh: dict, local_data: dict, task_id: str, local_tasks: list) -> None:
    """Uebertraegt nur die Aenderungen DIESES Tasks in den frisch geladenen Store.

    Der Task wird ueber einen langen await (LLM-Dispatch) hinweg als Snapshot
    gehalten. Ein komplettes `save_mc(data)` am Ende wuerde alles ueberschreiben,
    was in der Zwischenzeit am Store passiert ist — etwa ein Task, den der Nutzer
    im Board verschoben hat (Lost Update, Audit B1). Deshalb wird nur der eigene
    Task ersetzt bzw. eingefuegt und neu angelegte Sub-Tasks ergaenzt.
    """
    fresh_tasks = fresh.setdefault("tasks", [])
    fresh_ids = {t.get("id") for t in fresh_tasks}

    local_task = _task_by_id(local_data, task_id)
    if local_task is not None:
        for i, t in enumerate(fresh_tasks):
            if t.get("id") == task_id:
                fresh_tasks[i] = local_task
                break
        else:
            fresh_tasks.insert(0, local_task)

    for sub in local_tasks or []:
        if sub.get("id") not in fresh_ids:
            fresh_tasks.insert(0, sub)


async def _execute_mission_control_task(
    task_id: str,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    get_profiles: GetProfiles = None,
    sync_obsidian: SyncObsidian = None,
    trigger_sandy: Callable = None,
    fan_in: Callable = None,
) -> None:
    """Führt eine genehmigte Mission-Control-Aufgabe autonom über core_dispatcher aus."""
    # Lazy imports für Defaults (vermeiden Zyklen bei Modul-Load)
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if get_profiles is None:
        from archon.core.profiles import api_get_hermes_profiles as get_profiles
    if sync_obsidian is None:
        # Bewusst KEIN Fallback: die einzige korrekte Implementierung lebt in
        # main.py. Die frueher hier benutzte Kopie in archon.core.runtime war
        # nicht verhaltensgleich (eigene _slugify(), andere Dateinamen) und
        # haette still andere Ablagepfade erzeugt. Lieber ein bemerkter Fehler
        # als eine stille Abweichung.
        raise RuntimeError(
            "_execute_mission_control_task: Parameter 'sync_obsidian' fehlt. "
            "main.py injiziert _sync_task_to_obsidian; Aufrufer muessen die "
            "Abhaengigkeit explizit uebergeben."
        )
    if trigger_sandy is None:
        trigger_sandy = _trigger_sandy_staffing_nomination
    if fan_in is None:
        fan_in = _fan_in_maybe_start_synthesis
    data = load_mc()
    tasks = data.get("tasks", [])
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        return

    def _commit() -> None:
        """Schreibt die Aenderungen dieses Tasks.

        Mit update_mc: gezieltes Merge in den frisch geladenen Store, damit
        parallele Aenderungen an anderen Tasks nicht ueberschrieben werden.
        Ohne update_mc: RuntimeError (wie in Commit a4267fa2 an anderer Stelle).
        """
        if update_mc is not None:
            update_mc(lambda fresh: _merge_task_delta(fresh, data, task_id, tasks))
        else:
            raise RuntimeError(
                "_execute_mission_control_task: Parameter 'update_mc' fehlt. "
                "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                "Abhaengigkeit explizit uebergeben."
            )

    agent_id = task.get("agent_id", "micha")
    agent_name = task.get("agent_name", "Michael Keller")
    task_title = task.get("title", "Aufgabe")
    prompt_text = task.get("capture_input") or task_title

    profiles = get_profiles() if get_profiles else []
    prof = next((p for p in profiles if p.get("id") == agent_id or p.get("person_name") == agent_name), None)
    if not prof and profiles:
        prof = profiles[0]

    system_prompt = (prof.get("system_prompt") if prof else None) or (prof.get("prompt") if prof else None) or (
        f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."
    )
    model = (prof.get("model") if prof else None) or task.get("model") or "deepseek/deepseek-v4-flash-0731"

    ticker(agent_name, f"Startet Bearbeitung von Task #{task_id}: '{task_title[:35]}...'")

    try:
        task["active_tool"] = "Tool: web_search & archon_core"
        _commit()

        # Echter LLM-Dispatch
        res = await dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof.get("id", agent_id) if prof else agent_id,
            agent_name=agent_name,
            prompt=f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\n{prompt_text}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte.",
            role=prof.get("name", "Spezialist") if prof else "Spezialist",
            system_prompt=system_prompt,
            model=model,
        )

        reply = res.get("content", "").strip()
        if not reply or "Fehler" in reply[:25]:
            # Dispatcher meldet Fehler -> Task als failed markieren
            task["status"] = "failed"
            task["result_summary"] = f"Dispatcher-Fehler: {reply[:200] if reply else 'leere Antwort'}"
            ticker(agent_name or "Mission Control", f"Task #{task_id} fehlgeschlagen: {reply[:100]}")
            return

        # Aktualisiere Task
        task["status"] = "completed"
        task["result_summary"] = reply
        task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        obs_path = sync_obsidian(task)
        task["artifact_path"] = obs_path

        ticker("Obsidian", f"Dokumentation {os.path.basename(obs_path)} für Task #{task_id} abgelegt")
        ticker("Mission Control", f"Task #{task_id} erfolgreich abgeschlossen")

        # --- AUTO-STAFFING / DISPATCH-KETTE (MUSTER B) ---
        # Prüfe, ob die Antwort eine Nominierungsmatrix (nominated_agents) enthält
        try:
            # Suche gezielt nach Blöcken zwischen Backticks
            candidate_blocks = []
            for part in reply.split("```"):
                clean_p = part.strip()
                if clean_p.startswith("json"):
                    clean_p = clean_p[4:].strip()
                if "nominated_agents" in clean_p and clean_p.startswith("{") and clean_p.endswith("}"):
                    candidate_blocks.append(clean_p)
            if not candidate_blocks:
                candidate_blocks = re.findall(r'(\{[^\}]*"nominated_agents"[^\}]*\})', reply)
            for jm in candidate_blocks:
                try:
                    parsed_dispatch = json.loads(jm)
                except Exception:
                    continue
                nominated = parsed_dispatch.get("nominated_agents", [])
                if isinstance(nominated, list) and len(nominated) > 0:
                    proj_title = parsed_dispatch.get("project_title", task_title)
                    for idx, nom in enumerate(nominated):
                        sub_agent_id = nom.get("agent_id", "").strip()
                        sub_role = nom.get("role", "Spezialist")
                        sub_mandate = nom.get("mandate", "").strip()
                        if not sub_agent_id or sub_agent_id.startswith("<"):
                            continue

                        # Passenden Namen und Profil suchen
                        sub_prof = next((p for p in profiles if p.get("id") == sub_agent_id), None)
                        sub_name = sub_prof.get("person_name", sub_agent_id) if sub_prof else sub_role
                        sub_task_id = f"task-{int(time.time() * 1000) % 100000 + idx}"
                        sub_task_title = f"AP{idx+1}: {sub_role} - {proj_title}"

                        sub_task = {
                            "id": sub_task_id,
                            "title": sub_task_title,
                            "capture_input": f"MANDAT VON STAFFING-DIRECTORIN ({agent_name}):\n\n{sub_mandate}\n\nProjekt-Kontext: {proj_title}",
                            "plan": [
                                f"Empfangen von Mandat durch {agent_name}",
                                f"Fachliche Ausarbeitung durch {sub_name} ({sub_agent_id})",
                                "Dokumentation und Ablage in Obsidian"
                            ],
                            "agent_id": sub_agent_id,
                            "agent_name": sub_name,
                            "model": (sub_prof.get("model") if sub_prof else None) or "auto/best-free",
                            "estimated_tokens": 60000,
                            "estimated_cost_eur": 0.08,
                            "subagents_count": 1,
                            "status": "approval",
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "result_summary": "",
                            "artifact_path": "",
                            "parent_project_id": task.get("parent_project_id") or task_id,
                            "parent_task_id": task_id,
                            "target_action": task.get("target_action", "none"),
                            "phase": "execution"
                        }
                        data.setdefault("tasks", []).insert(0, sub_task)
                        task.setdefault("subtask_ids", []).append(sub_task_id)
                        task["phase"] = "staffing"
                        ticker("Approval Gate", f"Neuer Sub-Task #{sub_task_id} ({sub_name}) wartet auf Freigabe!")
                        logger.info(f"[Auto-Staffing] Sub-Task #{sub_task_id} für {sub_name} im Approval Gate angelegt.")
                        # --- AUTO-HIRE HOOK ---
                        try:
                            _paperclip_hire_profile_by_id(sub_agent_id, profiles, current_task_id=sub_task_id)
                        except Exception as _hire_err:
                            logger.warning(f"[AutoHire/MusterB] {_hire_err}")
        except Exception as parse_err:
            logger.warning(f"[Auto-Staffing] Fehler beim Parsen der Nominierungsmatrix: {parse_err}")

        # Cascade-Loop Schritt A: Hat Robert strategisch vorgelegt ohne direkte Nominierung? -> Sandy beauftragen
        if agent_id in ("executive_decision_architect", "robert") and not task.get("parent_project_id"):
            if not task.get("subtask_ids"):
                asyncio.create_task(trigger_sandy(task, profiles))

        # Cascade-Loop Schritt B: Ist ein Sub-Task fertig und alle Geschwister-Tasks abgeschlossen? -> Synthese starten
        parent_pid = task.get("parent_project_id") or task.get("parent_task_id")
        if parent_pid and parent_pid != task_id:
            asyncio.create_task(fan_in(parent_pid))

    except Exception as ex:
        logger.error(f"[Execution Error] _execute_mission_control_task {task_id}: {ex}")
        task["status"] = "failed"
        task["result_summary"] = f"Fehler bei Aufgabenausführung: {ex}"
        ticker(agent_name or "Mission Control", f"Task #{task_id} fehlgeschlagen: {ex}")
    finally:
        _commit()


def _paperclip_hire_profile_by_id(
    profile_id: str,
    profiles: list,
    current_task_id: str = "",
    *,
    set_status: Callable = None,
    ticker: Ticker = None,
) -> bool:
    """Aktiviert einen Agenten in agent_profiles.json: status='active', current_task_id=..."""
    if set_status is None:
        set_status = _set_agent_profile_status
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker

    try:
        set_status(profile_id, "active", current_task_id)
        prof = next((p for p in profiles if p.get("id") == profile_id), None)
        person_name = (prof.get("person_name") or prof.get("name") or profile_id) if prof else profile_id
        ticker("AutoHire", f"'{person_name}' aktiviert & Status -> active")
        logger.info(f"[AutoHire] '{profile_id}' erfolgreich aktiviert.")
        return True
    except Exception as e:
        logger.warning(f"[AutoHire] Status-Update für '{profile_id}' fehlgeschlagen: {e}")
        return False


def _set_agent_profile_status(
    profile_id: str,
    status: str,
    task_id: str = "",
    *,
    rolling_backup: RollingBackup = None,
    invalidate_profiles: InvalidateProfiles = None,
) -> None:
    """Setzt status (und optional current_task_id) in agent_profiles.json (mit Rolling Backup)."""
    if rolling_backup is None:
        from archon.core.runtime import create_rolling_backup as rolling_backup
    if invalidate_profiles is None:
        from archon.core.profiles import invalidate_hermes_profiles_cache as invalidate_profiles

    try:
        _app_root = os.path.dirname(os.path.abspath(__file__))
        ssot = os.path.join(_app_root, "agent_profiles.json")
        if not os.path.exists(ssot):
            return
        with open(ssot, "r", encoding="utf-8") as f:
            all_profiles = json.load(f)
        changed = False
        for p in all_profiles:
            if p.get("id") == profile_id:
                p["status"] = status
                if task_id:
                    p["current_task_id"] = task_id
                elif "current_task_id" in p and status == "standby":
                    del p["current_task_id"]
                changed = True
                break
        if changed:
            rolling_backup(ssot, max_backups=3)
            with open(ssot, "w", encoding="utf-8") as f:
                json.dump(all_profiles, f, indent=2, ensure_ascii=False)
            invalidate_profiles()
            logger.info(f"[ProfileStatus] '{profile_id}' → status='{status}'" + (f", task={task_id}" if task_id else ""))
    except Exception as e:
        logger.warning(f"[ProfileStatus] Fehler beim Status-Update für '{profile_id}': {e}")


def _merge_sandy_delta(fresh: dict, local_data: dict, parent_id: str, created_sub_ids: list, local_tasks: list) -> None:
    """Überträgt nur die Sandy-Änderungen (neue Subtasks + Parent-Update) in den frisch geladenen Store."""
    fresh_tasks = fresh.setdefault("tasks", [])
    fresh_ids = {t.get("id") for t in fresh_tasks}

    # 1. Neue Subtasks hinzufügen (nur die, die es im fresh noch nicht gibt)
    for sub in local_tasks:
        if sub.get("id") not in fresh_ids:
            fresh_tasks.insert(0, sub)

    # 2. Parent-Task aktualisieren (subtask_ids, phase)
    for i, t in enumerate(fresh_tasks):
        if t.get("id") == parent_id:
            local_parent = next((pt for pt in local_data.get("tasks", []) if pt.get("id") == parent_id), None)
            if local_parent:
                fresh_tasks[i]["subtask_ids"] = local_parent.get("subtask_ids", fresh_tasks[i].get("subtask_ids", []))
                fresh_tasks[i]["phase"] = local_parent.get("phase", fresh_tasks[i].get("phase"))
            break


def _merge_synthesis_draft_delta(fresh: dict, parent_id: str, draft_path: str) -> None:
    """Aktualisiert nur synthesis_draft_path im Parent-Task (atomar via update_mc)."""
    for t in fresh.get("tasks", []):
        if t.get("id") == parent_id:
            t["synthesis_draft_path"] = draft_path
            break


def _merge_synthesis_audit_delta(fresh: dict, parent_id: str, time_str: str, robert_reply: str, deci: dict | None, draft_name: str) -> None:
    """Fügt nur den audit_log Eintrag für die Synthese-Entscheidung hinzu (atomar via update_mc)."""
    fresh.setdefault("audit_logs", []).insert(0, {
        "time": time_str, "source": "Synthese-Loop",
        "msg": (f"Lisa-Entwurf für #{parent_id} braucht Freigabe "
                f"(Robert: {robert_reply[:60] or 'ohne Antwort'}) — "
                f"Kanban-Entscheidung {deci.get('task_id') if deci else 'NICHT angelegt'}")})


def _merge_finalize_synthesis_delta(fresh: dict, parent_pid: str, final_obs_path: str, local_parent: dict, audit_entry: dict) -> None:
    """Merged Parent-Task-Updates (status, phase, artifact_path, result_summary, synthesis_finalized, completed_at) + audit_logs."""
    for t in fresh.get("tasks", []):
        if t.get("id") == parent_pid:
            # Parent-Task-Felder übernehmen
            t["status"] = local_parent.get("status", t.get("status"))
            t["phase"] = local_parent.get("phase", t.get("phase"))
            t["artifact_path"] = local_parent.get("artifact_path", t.get("artifact_path"))
            t["result_summary"] = local_parent.get("result_summary", t.get("result_summary"))
            t["synthesis_finalized"] = local_parent.get("synthesis_finalized", t.get("synthesis_finalized"))
            t["completed_at"] = local_parent.get("completed_at", t.get("completed_at"))
            break
    # audit_logs Eintrag hinzufügen
    fresh.setdefault("audit_logs", []).insert(0, audit_entry)


async def _trigger_sandy_staffing_nomination(
    parent_task: dict,
    profiles: list,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    get_profiles: GetProfiles = None,
    paperclip_hire: Callable = None,
) -> None:
    """Lässt Sandy Hooks (labor_law_hr_governance) anhand des Strategieentwurfs die Fachagenten nominieren."""
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if get_profiles is None:
        from archon.core.profiles import api_get_hermes_profiles as get_profiles
    if paperclip_hire is None:
        paperclip_hire = _paperclip_hire_profile_by_id

    parent_id = parent_task.get("id")
    parent_title = parent_task.get("title", "Projekt")
    strategy_content = parent_task.get("result_summary") or parent_task.get("capture_input", "")

    sandy_prof = next((p for p in profiles if p.get("id") == "labor_law_hr_governance" or "sandy" in p.get("person_name", "").lower()), None)
    sandy_model = (sandy_prof.get("model") if sandy_prof else None) or "anthropic/claude-3.7-sonnet"
    sandy_sys = (sandy_prof.get("system_prompt") if sandy_prof else None) or "Du bist Sandy Hooks, Staffing-Directorin von Archon OS."

    prompt = f"""Als HR- & Staffing-Directorin nominiere bitte für folgende Strategie 2 bis 3 spezialisierte Fachagenten zur operativen Umsetzung:

PROJEKT: {parent_title}
STRATEGIE:
{strategy_content}

Gib deine Antwort AUSSCHLIESSLICH als valides JSON im folgenden Format zurück:
```json
{{
  "project_title": "{parent_title}",
  "nominated_agents": [
    {{
      "agent_id": "<profil_id_aus_hermes>",
      "role": "<rollenbezeichnung>",
      "mandate": "<konkreter operativer Auftrag für diesen Agenten>"
    }}
  ]
}}
```
Wähle passende Agenten aus dem Agentenpool (z.B. copywriter_marketing_lead, fullstack_core_architect, prompt_engineer, etc.)."""

    ticker("Sandy Hooks", f"Nominiert Umsetzungsteam für #{parent_id}: '{parent_title[:30]}...'")
    try:
        res = await dispatcher.dispatch_to_omniroute_or_container(
            agent_id="labor_law_hr_governance",
            agent_name="Sandy Hooks (Staffing-Directorin)",
            prompt=prompt,
            role="Staffing-Directorin",
            system_prompt=sandy_sys,
            model=sandy_model,
        )
        reply = res.get("content", "").strip()
        # Lokalen Snapshot laden, Änderungen vorbereiten
        data = load_mc()
        candidate_blocks = []
        for part in reply.split("```"):
            clean_p = part.strip()
            if clean_p.startswith("json"):
                clean_p = clean_p[4:].strip()
            if "nominated_agents" in clean_p and clean_p.startswith("{") and clean_p.endswith("}"):
                candidate_blocks.append(clean_p)
        if not candidate_blocks:
            candidate_blocks = re.findall(r'(\{[^}]*"nominated_agents"[^}]*\})', reply)

        created_sub_ids = []
        created_subtasks = []
        for jm in candidate_blocks:
            try:
                parsed = json.loads(jm)
            except Exception:
                continue
            nominated = parsed.get("nominated_agents", [])
            if isinstance(nominated, list) and len(nominated) > 0:
                for idx, nom in enumerate(nominated):
                    sub_agent_id = nom.get("agent_id", "").strip()
                    sub_role = nom.get("role", "Spezialist")
                    sub_mandate = nom.get("mandate", "").strip()
                    if not sub_agent_id or sub_agent_id.startswith("<"):
                        continue
                    sub_prof = next((p for p in profiles if p.get("id") == sub_agent_id), None)
                    sub_name = sub_prof.get("person_name", sub_agent_id) if sub_prof else sub_role
                    sub_task_id = f"task-{int(time.time() * 1000) % 100000 + idx}"
                    sub_task_title = f"AP{idx+1}: {sub_role} - {parent_title}"

                    sub_task = {
                        "id": sub_task_id,
                        "title": sub_task_title,
                        "capture_input": f"MANDAT VON STAFFING-DIRECTORIN (Sandy Hooks):\n\n{sub_mandate}\n\nProjekt-Kontext: {parent_title}",
                        "plan": [
                            f"Empfangen von Mandat durch Sandy Hooks",
                            f"Fachliche Ausarbeitung durch {sub_name} ({sub_agent_id})",
                            "Dokumentation und Ablage in Obsidian"
                        ],
                        "agent_id": sub_agent_id,
                        "agent_name": sub_name,
                        "model": (sub_prof.get("model") if sub_prof else None) or "auto/best-free",
                        "estimated_tokens": 60000,
                        "estimated_cost_eur": 0.08,
                        "subagents_count": 1,
                        "status": "approval",
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "result_summary": "",
                        "artifact_path": "",
                        "parent_project_id": parent_id,
                        "parent_task_id": parent_id,
                        "target_action": parent_task.get("target_action", "none"),
                        "phase": "execution"
                    }
                    data.setdefault("tasks", []).insert(0, sub_task)
                    created_sub_ids.append(sub_task_id)
                    created_subtasks.append(sub_task)
                    ticker("Approval Gate", f"Neuer Sub-Task #{sub_task_id} ({sub_name}) wartet auf Freigabe!")

                    # --- AUTO-HIRE HOOK: Agent in Paperclip registrieren & Status auf 'active' ---
                    try:
                        paperclip_hire(sub_agent_id, profiles, current_task_id=sub_task_id)
                    except Exception as hire_err:
                        logger.warning(f"[AutoHire] Hire fehlgeschlagen für '{sub_agent_id}': {hire_err}")

        # Parent-Task im lokalen Snapshot updaten (subtask_ids, phase)
        local_parent = next((t for t in data.get("tasks", []) if t.get("id") == parent_id), None)
        if local_parent and created_sub_ids:
            local_parent.setdefault("subtask_ids", []).extend(created_sub_ids)
            local_parent["phase"] = "staffing"

        # Atomares Commit: nur unser Delta (neue Subtasks + Parent-Update) in den frischen Store mergen
        def _commit():
            if update_mc is not None:
                update_mc(lambda fresh: _merge_sandy_delta(fresh, data, parent_id, created_sub_ids, created_subtasks))
            else:
                raise RuntimeError(
                    "_trigger_sandy_staffing_nomination: Parameter 'update_mc' fehlt. "
                    "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                    "Abhaengigkeit explizit uebergeben."
                )
        _commit()
    except Exception as e:
        logger.warning(f"[Cascade-Loop] Fehler bei Sandy-Staffing: {e}")


async def _finalize_synthesis_after_approval(
    parent_pid: str,
    draft_path: str,
    synthese_text: str,
    approver_note: str,
    daten: dict = None,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    paths: Dict[str, str] = None,
    folder_namer: FolderNamer = None,
    set_status: Callable = None,
    tg_ping: Callable = None,
) -> None:
    """Schliesst die Synthese NACH Robert-Freigabe ab: finaler Bericht in 01_PROJEKTE, Parent-Task completed, Audit/Ticker, Demobilisierung, n8n."""
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if paths is None:
        paths = {"OBSIDIAN_VAULT_DIR": DEFAULT_OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": DEFAULT_WORKSPACE_DIR}
    if folder_namer is None:
        try:
            from backend.post_task_pipeline import project_folder_name as folder_namer
        except Exception:
            folder_namer = lambda x: ""
    if set_status is None:
        set_status = _set_agent_profile_status
    if tg_ping is None:
        tg_ping = _tg_ping_synthesis
    if update_mc is None:
        raise RuntimeError(
            "_finalize_synthesis_after_approval: Parameter 'update_mc' fehlt. "
            "main.py injiziert update_mission_control_data; Aufrufer muessen die "
            "Abhaengigkeit explizit uebergeben."
        )

    try:
        data = daten if daten is not None else load_mc()
        parent_task = next((t for t in data.get("tasks", []) if t.get("id") == parent_pid), None)
        if not parent_task:
            logger.warning(f"[Synthese] Parent '{parent_pid}' beim Finalisieren nicht gefunden")
            return
        if parent_task.get("synthesis_finalized"):
            return
        parent_title = parent_task.get("title", "Gesamtprojekt")
        safe_pid = re.sub(r'[^a-zA-Z0-9_\-]+', '-', parent_pid).strip('-') or "projekt"
        final_body = (f"# Finale Beschlussvorlage: {parent_title}\n\n"
                      f"{synthese_text}\n\n---\n"
                      f"**Freigabe:** {approver_note}\n")
        final_name = f"{safe_pid}_final_beschlussvorlage.md"
        target_dirs = [
            "/opt/data/obsidian/01_PROJEKTE",
            os.path.join(paths["OBSIDIAN_VAULT_DIR"], "01_PROJEKTE"),
            os.path.join(paths["WORKSPACE_DIR"], "obsidian_vault", "01_PROJEKTE"),
        ]
        # 12.10.2026 (Ordnerflut-Fix): finaler Bericht in den EINEN Projekt-Ordner.
        try:
            _fan_ordner = folder_namer({"parent_project_id": parent_pid, "parent_project_title": parent_title})
        except Exception:
            _fan_ordner = ""
        final_obs_path = (f"/opt/data/obsidian/01_PROJEKTE/{_fan_ordner}/03_Endprodukte/{final_name}"
                          if _fan_ordner else f"/opt/data/obsidian/01_PROJEKTE/{final_name}")
        for d in target_dirs:
            try:
                d_ziel = os.path.join(d, _fan_ordner, "03_Endprodukte") if _fan_ordner else d
                os.makedirs(d_ziel, exist_ok=True)
                p = os.path.join(d_ziel, final_name)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(final_body)
                final_obs_path = p
            except Exception as we:
                logger.warning(f"[Synthese] Konnte finalen Bericht nicht nach {d} schreiben: {we}")

        # Parent-Task lokal updaten
        parent_task["status"] = "completed"
        parent_task["phase"] = "completed"
        parent_task["artifact_path"] = final_obs_path
        parent_task["result_summary"] = (synthese_text[:500] + "...") if len(synthese_text) > 500 else synthese_text
        parent_task["synthesis_finalized"] = True
        parent_task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        now_t = datetime.datetime.now().strftime("%H:%M:%S")

        # Audit-Log-Eintrag lokal vorbereiten
        audit_entry = {
            "time": now_t, "source": "Synthese-Loop",
            "msg": f"Finale Beschlussvorlage fuer #{parent_pid} freigegeben und abgelegt ({approver_note[:60]})"
        }

        # Atomares Commit: Parent-Task-Felder + audit_logs mergen
        def _commit():
            if update_mc is not None:
                update_mc(lambda fresh: _merge_finalize_synthesis_delta(
                    fresh, parent_pid, final_obs_path, parent_task, audit_entry))
            else:
                raise RuntimeError(
                    "_finalize_synthesis_after_approval: Parameter 'update_mc' fehlt. "
                    "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                    "Abhaengigkeit explizit uebergeben."
                )
        _commit()

        ticker("Synthese-Loop", f"Freigabe: finale Beschlussvorlage fuer '{parent_title[:35]}...' bereit")

        # Demobilisierung der Fachagenten (Stammagenten bleiben aktiv)
        try:
            sibs = [t for t in data.get("tasks", [])
                    if (t.get("parent_project_id") == parent_pid or t.get("parent_task_id") == parent_pid)]
            demob_ids = list({s.get("agent_id") for s in sibs if s.get("agent_id")})
            for agent_id_dem in demob_ids:
                if agent_id_dem in ("executive_decision_architect", "robert", "labor_law_hr_governance", "sandy", "aggregation_lisa"):
                    continue
                set_status(agent_id_dem, "standby")
            if demob_ids:
                ticker("Demobilisierung", f"{len(demob_ids)} Fachagent(en) nach Projektabschluss auf Standby gesetzt")
        except Exception as demob_err:
            logger.warning(f"[Demobilisierung] Fehler: {demob_err}")

        # n8n-Bridge (bestehender Einbaupunkt)
        target_action = parent_task.get("target_action") or "none"
        try:
            n8n_res = await dispatcher.trigger_n8n_execution(
                parent_project_id=parent_pid,
                title=parent_title,
                final_report_path=final_obs_path,
                content=synthese_text,
                target_action=target_action,
            )
            logger.info(f"[Synthese-Loop] n8n Webhook Ergebnis: {n8n_res}")
            ticker("n8n Bridge", f"Action '{target_action}' an n8n uebergeben ({n8n_res.get('status')})")
        except Exception as n8n_err:
            logger.warning(f"[Synthese-Loop] n8n Trigger fehlgeschlagen: {n8n_err}")
    except Exception as fin_err:
        logger.warning(f"[Synthese] Finalisierung fehlgeschlagen: {fin_err}")


async def _fan_in_maybe_start_synthesis(
    parent_pid: str,
    *,
    load_mc: LoadMC = _default_load_mc,
    write_mc_atomic: Callable = _write_mc_atomic,
    mc_async_lock: asyncio.Lock = _MC_ASYNC_LOCK,
    run_cascade: Callable = None,
) -> None:
    """FAN-IN (12.10.2026): Alle Geschwister des Delegationsprojekts completed? -> Synthese-Loop starten."""
    if not parent_pid:
        return
    if run_cascade is None:
        run_cascade = _run_synthesis_cascade
    try:
        # Struktur-Thema 3: die GANZE Pruef-Sequenz unter EINEM Lock (frisch
        # laden, pruefen, Flag setzen, speichern). Sonst starten zwei zeitgleiche
        # Fertigmeldungen die Synthese doppelt. _write_mc_atomic direkt: der Lock
        # ist nicht reentrant, _save_mission_control_data wuerde verklemmen.
        async with mc_async_lock:
            data = await asyncio.to_thread(load_mc)
            siblings = [t for t in data.get("tasks", [])
                        if (t.get("parent_project_id") == parent_pid or t.get("parent_task_id") == parent_pid)
                        and t.get("id") != parent_pid]
            parent = next((t for t in data.get("tasks", []) if t.get("id") == parent_pid), None)
            if not siblings or not parent:
                return
            if parent.get("synthesis_started"):
                return
            if not all(s.get("status") == "completed" for s in siblings):
                return
            parent["synthesis_started"] = True
            await asyncio.to_thread(write_mc_atomic, data)
        logger.info(f"[Fan-in] Alle {len(siblings)} Geschwister von '{parent_pid}' fertig -> Synthese starten")
        asyncio.create_task(run_cascade(parent_pid))
    except Exception as e:
        logger.warning(f"[Fan-in] Synthese-Check fehlgeschlagen: {e}")


def _tg_ping_synthesis(
    parent_title: str,
    parent_project_id: str,
    synthese_text: str,
    draft_path: str,
    app_id: str = None,
    dossier_dir: str = None,
    *,
    send_doc: TelegramSendDoc = None,
    send_msg: TelegramSendMsg = None,
    build_dossier: BuildDossier = None,
) -> None:
    """2a: Synthese-Bericht als Telegram-Ping MIT Dossier-Anhang."""
    if send_doc is None:
        from telegram_notify import send_telegram_document as send_doc
    if send_msg is None:
        from telegram_notify import send_telegram_message as send_msg
    if build_dossier is None:
        try:
            from dossier_builder import build_dossier_from_report as build_dossier
        except Exception:
            build_dossier = None

    try:
        dpath = None
        if dossier_dir and build_dossier:
            try:
                dpath = build_dossier(
                    f"Synthese: {parent_title}", synthese_text, dossier_dir,
                    f"{re.sub(r'[^a-zA-Z0-9_-]+', '-', str(parent_project_id))[:40]}_synthese",
                    ref_id=parent_project_id, quelle="Lisa (aggregation_lisa)")
            except Exception as _e:
                logger.warning(f"[Synthese] Dossier-Aufbau fehlgeschlagen: {_e}")
        _kurz = re.sub(r"\s+", " ", (synthese_text or "")).strip()[:300]
        caption = ("🔐 ENTSCHEIDUNG NÖTIG — Synthese\n"
                   f"Projekt: {parent_title}\n\n{_kurz}"
                   + ("\n\nDer vollständige Entwurf liegt als Anhang bei." if dpath else ""))
        markup = None
        if app_id:
            markup = {"inline_keyboard": [[
                {"text": "✅ Freigeben", "callback_data": f"app:approve:{app_id}"},
                {"text": "❌ Ablehnen", "callback_data": f"app:reject:{app_id}"},
            ]]}
        if dpath and send_doc(dpath, caption=caption, reply_markup=markup):
            return
        if dpath:
            logger.warning("[Synthese] Dossier-Ping fehlgeschlagen — Text-Ping stattdessen.")
        send_msg(caption + (f"\n\n📄 Entwurf: {draft_path}" if draft_path else ""), reply_markup=markup)
    except Exception as e:
        logger.warning(f"[Synthese] Telegram-Ping fehlgeschlagen: {e}")


async def _run_synthesis_cascade(
    parent_project_id: str,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    get_profiles: GetProfiles = None,
    paths: Dict[str, str] = None,
    folder_namer: FolderNamer = None,
    build_dossier: BuildDossier = None,
    create_decision: CreateDecision = None,
    finalize_approval: Callable = None,
    tg_ping: Callable = None,
) -> None:
    """
    FAN-IN SYNTHESE (12.10.2026, User-Entscheidung A+B):
    1. Sammelt alle Teilergebnisse der Fachagenten fuer parent_project_id.
    2. LISA (aggregation_lisa) fuegt sie zum Gesamtergebnis zusammen.
    3. ROBERT (executive_decision_architect) gibt frei (FREIGABE/ABLEHNUNG).
    4a. FREIGABE  -> finaler Bericht in 01_PROJEKTE + n8n-Bridge.
    4b. ABLEHNUNG -> Entwurf bleibt als Approval-Task im Board liegen.
    """
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if get_profiles is None:
        from archon.core.profiles import api_get_hermes_profiles as get_profiles
    if paths is None:
        paths = {"OBSIDIAN_VAULT_DIR": DEFAULT_OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": DEFAULT_WORKSPACE_DIR}
    if folder_namer is None:
        try:
            from backend.post_task_pipeline import project_folder_name as folder_namer
        except Exception:
            folder_namer = lambda x: ""
    if build_dossier is None:
        try:
            from dossier_builder import build_dossier_from_report as build_dossier
        except Exception:
            build_dossier = None
    if create_decision is None:
        try:
            from backend.kanban_db import create_decision as create_decision
        except Exception:
            create_decision = None
    if finalize_approval is None:
        finalize_approval = _finalize_synthesis_after_approval
    if tg_ping is None:
        tg_ping = _tg_ping_synthesis

    logger.info(f"[Cascade-Loop] Starte Synthese fuer Parent-Projekt {parent_project_id}")
    # Initialen Snapshot laden (nur für Parent-Titel und Geschwister)
    data = load_mc()
    tasks = data.get("tasks", [])
    parent_task = next((t for t in tasks if t.get("id") == parent_project_id), None)
    if not parent_task:
        logger.warning(f"[Cascade-Loop] Parent-Task {parent_project_id} nicht gefunden!")
        return

    siblings = [
        t for t in tasks
        if (t.get("parent_project_id") == parent_project_id or t.get("parent_task_id") == parent_project_id)
        and t.get("id") != parent_project_id
    ]

    # Berichte auslesen (Artifact bevorzugt, sonst result_summary) - synchron, kein await
    reports = []
    for s in siblings:
        sub_title = s.get("title", "Teilaufgabe")
        sub_agent = s.get("agent_name", "Fachagent")
        art_path = s.get("artifact_path", "")
        content = ""
        if art_path and os.path.exists(art_path):
            try:
                with open(art_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                pass
        if not content:
            content = s.get("result_summary", "")
        reports.append(f"### Arbeitspaket von {sub_agent} ({sub_title})\n\n{content}\n")
    combined_reports = f"\n---\n\n".join(reports)
    parent_title = parent_task.get("title", "Gesamtprojekt")

    # --- SCHRITT 1: LISA fuegt zusammen ---
    lisa_prompt = f"""Fuehre die vorliegenden Teilergebnisse der Fachagenten zu einem konsistenten
Gesamtergebnis zusammen. Du bist Lisa, Ergebnis-Kuratorin.

PROJEKT: {parent_title}
URSPRUEBLICHE ANFORDERUNG:
{parent_task.get('capture_input', parent_title)}

VORLIEGENDE TEILERGEBNISSE ({len(reports)} Arbeitspakete):
{combined_reports}

VORGABEN:
1. NUR integrieren, was vorliegt - keine neuen Fakten erfinden.
2. Widersprueche und Luecken klar kennzeichnen, nicht glaetten.
3. Struktur: Executive-Kurzfassung / Integriertes Ergebnis / Widersprueche & offene Punkte / Naechste Schritte.
4. Keine Begruessungen, keine Floskeln. Deutsch, dicht, entscheidungsfaehig.
5. Letzte Zeile exakt: SYNTHESE-BEREIT"""

    profiles = get_profiles() if get_profiles else []
    lisa_prof = next((p for p in profiles if p.get("id") == "aggregation_lisa"), None)
    lisa_system = ((lisa_prof or {}).get("system_prompt") or (lisa_prof or {}).get("prompt")
                   or "Du bist Lisa, Ergebnis-Kuratorin von Archon OS. Du fügst Teilergebnisse zusammen, kennzeichnest Widersprüche und lieferst ein entscheidungsfähiges Gesamtergebnis auf Deutsch ohne Floskeln.")
    lisa_model = (lisa_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"
    ticker("Lisa", f"Fuegt {len(reports)} Teilergebnisse zu '{parent_title[:30]}...' zusammen")
    try:
        res = await dispatcher.dispatch_to_omniroute_or_container(
            agent_id="aggregation_lisa",
            agent_name="Lisa (Ergebnis-Kuratorin)",
            prompt=lisa_prompt,
            role="Ergebnis-Kuratorin & Synthese",
            system_prompt=lisa_system,
            model=lisa_model,
        )
        synthesis_reply = res.get("content", "").strip()
    except Exception as synth_err:
        logger.warning(f"[Cascade-Loop] Dispatch an Lisa fehlgeschlagen: {synth_err}")
        synthesis_reply = ""
    if not synthesis_reply or "Fehler" in synthesis_reply[:25]:
        synthesis_reply = (f"# Synthese: {parent_title}\n\n"
                           "Die Synthese der Fachmodule wurde planmaessig abgeschlossen "
                           "(Modell-Antwort leer - Teilergebnisse liegen in den Projektordnern).")
        _lisa_leer = True
    else:
        _lisa_leer = False

    # MARKER-KONTRAKT (Struktur-Thema 2, User-Entscheidung): Lisas Prompt verlangt
    # als letzte Zeile exakt SYNTHESE-BEREIT. Fehlt der Marker bei echter Antwort:
    # EIN Reparatur-Retry, danach Fallback MIT sichtbarer Warnung (nie still).
    # Die Marker-Zeile ist Protokoll, kein Inhalt - sie wird vor Draft/Dossier/Robert entfernt.
    _MARKER = "SYNTHESE-BEREIT"

    def _lisa_marker_ok(txt):
        _ls = [l.strip() for l in (txt or "").splitlines() if l.strip()]
        return bool(_ls) and _ls[-1].upper() == _MARKER

    if _lisa_leer:
        logger.warning(f"[Cascade-Loop] Lisa lieferte keine Synthese fuer {parent_project_id} (Fallback-Text).")
        ticker("Lisa", f"Keine Modell-Antwort fuer '{parent_title[:30]}...' - Fallback-Text verwendet")
    elif not _lisa_marker_ok(synthesis_reply):
        _repaired = ""
        try:
            _rres2 = await dispatcher.dispatch_to_omniroute_or_container(
                agent_id="aggregation_lisa",
                agent_name="Lisa (Ergebnis-Kuratorin)",
                prompt=("Gib die folgende Synthese UNVERAENDERT erneut aus und setze "
                        "als LETZTE ZEILE exakt: SYNTHESE-BEREIT\n\n" + synthesis_reply),
                role="Ergebnis-Kuratorin & Synthese",
                system_prompt=lisa_system,
                model=lisa_model,
            )
            _repaired = (_rres2.get("content", "") or "").strip()
        except Exception as _rep_err:
            logger.warning(f"[Cascade-Loop] Marker-Repair an Lisa fehlgeschlagen: {_rep_err}")
        if _lisa_marker_ok(_repaired):
            synthesis_reply = _repaired
            logger.info(f"[Cascade-Loop] Marker-Repair erfolgreich ({parent_project_id})")
        else:
            logger.warning(f"[Cascade-Loop] Synthese ohne {_MARKER}-Marker ({parent_project_id}) - ungeprueft verwendet")
            ticker("Lisa", f"Synthese ohne {_MARKER}-Marker - ungeprueft verwendet")
    _syn_lines = synthesis_reply.splitlines()
    if _syn_lines and _syn_lines[-1].strip().upper() == _MARKER:
        synthesis_reply = "\n".join(_syn_lines[:-1]).strip()

    # --- SCHRITT 1.5: KRITISCHER REVIEWER prüft Lisas Synthese vor Roberts Entscheidung ---
    reviewer_prof = next((p for p in profiles if p.get("id") == "gpts_critical_reviewer"), None)
    reviewer_critique = ""
    if reviewer_prof:
        rev_prompt = f"""Fuehre eine schonungslose Qualitaetspruefung der vorliegenden Synthese durch.
PROJEKT: {parent_title}
URSPRUENGLICHE ANFORDERUNG: {parent_task.get('capture_input', parent_title)}

SYNTHESE-ENTWURF (von Lisa):
{synthesis_reply}

AUFGABE:
1. Pruefe auf unbelegte Behauptungen, Logikbrueche und gravierende Luecken.
2. Formuliere max. 3 praegnante Kernkritikpunkte (oder bestaetige 'Keine kritischen Maengel festgestellt').
3. Schliesse mit einem klaren Urteil: EMPFEHLUNG FREIGABE oder EMPFEHLUNG NACHBESSERUNG."""
        ticker("Reviewer", f"Qualitaetspruefung fuer '{parent_title[:30]}...'")
        try:
            rev_res = await dispatcher.dispatch_to_omniroute_or_container(
                agent_id="gpts_critical_reviewer",
                agent_name="Kritischer Reviewer",
                prompt=rev_prompt,
                role="Critical Reviewer & QA",
                system_prompt=((reviewer_prof or {}).get("system_prompt") or "Du bist der kritische Chef-Reviewer von Archon OS. Pruefe Entwuerfe schonungslos auf Fakten, Logik und Qualitaet."),
                model=((reviewer_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"),
            )
            reviewer_critique = (rev_res.get("content", "") or "").strip()
            if reviewer_critique:
                logger.info(f"[Cascade-Loop] Reviewer-Kritik erstellt ({len(reviewer_critique)} Zeichen)")
        except Exception as rev_err:
            logger.warning(f"[Cascade-Loop] Reviewer-Pruefung fehlgeschlagen: {rev_err}")

    # --- SCHRITT 2: ROBERT gibt frei ---
    robert_prompt = f"""Lisa (aggregation_lisa) hat die Teilergebnisse folgenden Projekts zusammengefuegt:

PROJEKT: {parent_title}
ANFORDERUNG: {parent_task.get('capture_input', parent_title)}

LISAS SYNTHESE:
{synthesis_reply}

""" + (f"""UNABHAENGIGE QUALITAETSPRUEFUNG (Kritischer Reviewer):
{reviewer_critique}

""" if reviewer_critique else "") + """Pruefe Vollstaendigkeit und Plausibilitaet. Antworte MIT GENAU EINEM DER ZWEI
WOERTER ALS ALLERERSTER ZEILE: FREIGABE oder ABLEHNUNG - danach hoechstens
ein Satz Begruendung. Keine weiteren Absaetze, keine Begruessung."""
    r_prof = next((p for p in profiles if p.get("id") in ("executive_decision_architect", "robert")), None)
    r_system = ((r_prof or {}).get("system_prompt") or (r_prof or {}).get("prompt")
                or "Du bist Robert, Executive Decision Architect und leitender Chefstratege von Archon OS. Antworte mit FREIGABE oder ABLEHNUNG als erste Zeile.")
    r_model = (r_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"
    ticker("Robert", f"Prueft Lisas Synthese fuer '{parent_title[:30]}...'")
    robert_reply = ""
    try:
        rres = await dispatcher.dispatch_to_omniroute_or_container(
            agent_id="executive_decision_architect",
            agent_name="Robert (Chefstratege)",
            prompt=robert_prompt,
            role="Executive Decision Architect",
            system_prompt=r_system,
            model=r_model,
        )
        robert_reply = (rres.get("content", "") or "").strip()
    except Exception as r_err:
        logger.warning(f"[Cascade-Loop] Freigabe-Dispatch an Robert fehlgeschlagen: {r_err}")

    # ROBUSTE FREIGABE-ERKENNUNG (Struktur-Thema 4/1, User-Entscheidung): NUR die
    # exakte erste Zeile zaehlt. Alles andere (Floskeln, "KEINE FREIGABE", leer)
    # geht an den Owner via Kanban-Entscheidung (4b-Pfad) - nie still, nie geraten.
    _erste_zeile = ((robert_reply or "").splitlines() or [""])[0].strip().upper()
    if _erste_zeile == "FREIGABE":
        freigegeben = True
    elif _erste_zeile == "ABLEHNUNG":
        freigegeben = False
    else:
        logger.warning(f"[Cascade-Loop] Roberts Antwort unklar (erste Zeile: '{_erste_zeile[:60]}') - Owner entscheidet")
        ticker("Robert", "Antwort unklar - Freigabe liegt beim Owner im Kanban")
        freigegeben = False

    # Entwurf ablegen (Basis der Robert-Freigabe)
    safe_pid = re.sub(r'[^a-zA-Z0-9_\-]+', '-', parent_project_id).strip('-') or "projekt"
    draft_name = f"{safe_pid}_synthese_lisa_entwurf.md"
    target_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(paths["OBSIDIAN_VAULT_DIR"], "01_PROJEKTE"),
        os.path.join(paths["WORKSPACE_DIR"], "obsidian_vault", "01_PROJEKTE"),
    ]
    # 12.10.2026 (Ordnerflut-Fix): Entwurf + finaler Bericht gehoeren in den
    # EINEN Projekt-Ordner des Eltern-Projekts, nicht als lose Dateien daneben.
    try:
        _fan_ordner = folder_namer({"parent_project_id": parent_project_id, "parent_project_title": parent_title})
    except Exception:
        _fan_ordner = ""
    # 2a: Ablageordner fuer das Synthese-Dossier im Projektordner
    _tg_doss_dir = None
    try:
        if _fan_ordner:
            _tg_doss_dir = os.path.join(paths["OBSIDIAN_VAULT_DIR"], "01_PROJEKTE",
                                        _fan_ordner, "01_Zwischenberichte")
    except Exception:
        _tg_doss_dir = None
    draft_path = (f"/opt/data/obsidian/01_PROJEKTE/{_fan_ordner}/03_Endprodukte/{draft_name}"
                  if _fan_ordner else f"/opt/data/obsidian/01_PROJEKTE/{draft_name}")
    for d in target_dirs:
        try:
            d_ziel = os.path.join(d, _fan_ordner, "03_Endprodukte") if _fan_ordner else d
            os.makedirs(d_ziel, exist_ok=True)
            p = os.path.join(d_ziel, draft_name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# Synthese-Entwurf: {parent_title}\n\n{synthesis_reply}\n")
            draft_path = p
        except Exception:
            continue

    # --- ATOMARER COMMIT: synthesis_draft_path in Parent-Task schreiben ---
    # Wir nutzen update_mc für atomares Merge (nur Parent-Task Update, keine Tasks-Listen-Änderung)
    def _commit_draft():
        if update_mc is not None:
            update_mc(lambda fresh: _merge_synthesis_draft_delta(fresh, parent_project_id, draft_path))
        else:
            raise RuntimeError(
                "_run_synthesis_cascade: Parameter 'update_mc' fehlt. "
                "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                "Abhaengigkeit explizit uebergeben."
            )
    _commit_draft()

    if freigegeben:
        await finalize_approval(parent_project_id, draft_path, synthesis_reply, f"Robert: {robert_reply[:200]}")
        # 2a: Owner informieren - kein Handlungsbedarf, aber Bericht mitliefern.
        tg_ping(parent_title, parent_project_id, synthesis_reply, draft_path, app_id=None, dossier_dir=_tg_doss_dir)
        return

    # 4b: Ablehnung/unklar -> echte Entscheidung im KANBAN (2c). kanban.db ist
    # die Wahrheit; der frühere parallele Mission-Control-Task (mcapp-*) entfällt.
    _deci_dossier = None
    if _tg_doss_dir and build_dossier:
        try:
            _deci_dossier = build_dossier(
                f"Synthese: {parent_title}", synthesis_reply, _tg_doss_dir,
                f"{safe_pid}_synthese", ref_id=parent_project_id,
                quelle="Lisa (aggregation_lisa)")
        except Exception as _de:
            logger.warning(f"[Synthese] Dossier für die Entscheidung fehlgeschlagen: {_de}")
    _deci = None
    if create_decision:
        try:
            _deci = await asyncio.to_thread(
                create_decision,
                "synthesis_freigabe",
                f"Freigabe: Synthese '{parent_title[:55]}'",
                synthesis_reply,          # kurzfassung
                parent_project_id,        # ref_id
                _deci_dossier,            # dossier
                f"Lisas Entwurf: {draft_path}",   # body
                {"parent_project_id": parent_project_id, "draft_path": draft_path,
                 "projekt": parent_title, "von": "Lisa · Ergebnis-Kuratorin",
                 "teilberichte": f"{len(reports)}/{len(reports)}"},                    # extra
                (f"01_PROJEKTE/{_fan_ordner}" if _fan_ordner else None),             # obsidian
            )
        except Exception as _de:
            logger.warning(f"[Synthese] Entscheidung anlegen fehlgeschlagen: {_de}")
    now_t = datetime.datetime.now().strftime("%H:%M:%S")

    # --- ATOMARER COMMIT: audit_logs Eintrag hinzufügen ---
    def _commit_audit():
        if update_mc is not None:
            update_mc(lambda fresh: _merge_synthesis_audit_delta(fresh, parent_project_id, now_t, robert_reply, _deci, draft_name))
        else:
            raise RuntimeError(
                "_run_synthesis_cascade: Parameter 'update_mc' fehlt. "
                "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                "Abhaengigkeit explizit uebergeben."
            )
    _commit_audit()

    ticker("Synthese-Loop", f"Entscheidung im Kanban angelegt: {draft_name}")
    if not _deci:
        logger.warning(f"[Synthese] Entscheidung für #{parent_project_id} konnte NICHT "
                       f"angelegt werden — Freigabe ist per Telegram/Kanban nicht möglich.")


__all__ = [
    "_execute_mission_control_task",
    "_paperclip_hire_profile_by_id",
    "_set_agent_profile_status",
    "_trigger_sandy_staffing_nomination",
    "_finalize_synthesis_after_approval",
    "_fan_in_maybe_start_synthesis",
    "_tg_ping_synthesis",
    "_run_synthesis_cascade",
]