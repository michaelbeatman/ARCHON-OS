"""
Mission Control Router — Mission-Control-Endpunkte (State, Capture, Move, Artifact).

Extrahiert aus main.py. Nutzt Core-Module für alle Dependencies.
"""

import asyncio
import datetime
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Core-Module (kein main.py Import!)
from archon.core.mission_control import (
    _load_mission_control_data,
    _save_mission_control_data,
    update_mission_control_data,
    _MC_STATE_CACHE,
)
from archon.core.runtime import (
    OBSIDIAN_VAULT_DIR,
    WORKSPACE_DIR,
    add_ticker,
    broadcast_event,
    logger,
)
from archon.core.profiles import api_get_hermes_profiles

# Externe Dependencies (wie in main.py)
import core_dispatcher


# --------------------------------------------------
# Dependency-Injektion statt Kopie
# --------------------------------------------------
# Die Helfer (_get_live_telemetry_metrics, _sync_task_to_obsidian) und die
# Orchestrierungs-Wrapper leben weiterhin in main.py. Ihre Kopien in
# archon/core/runtime.py sind NICHT verhaltensgleich: die Telemetrie filtert
# dort 15 Minuten statt Tagesbeginn, und _sync_task_to_obsidian erzeugt ueber
# eine eigene _slugify()-Hilfe andere Dateinamen. Ein Direktimport wuerde
# Telemetriezahlen und Obsidian-Pfade still veraendern. main.py registriert
# deshalb seine eigenen Funktionen per configure() — das Muster aus
# references/modularisierung-monolith.md §2b.
_DEPS: Dict[str, Any] = {}


def configure(**deps: Any) -> None:
    """Registriert die aus main.py injizierten Abhaengigkeiten (einmalig beim Import)."""
    _DEPS.update(deps)
    _missing = {"telemetry", "sync_obsidian", "execute", "finalize_approval", "fan_in"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] mission_control: fehlende Dependencies {sorted(_missing)}")


router = APIRouter()


# --------------------------------------------------
# Request-Modelle (aus main.py übernommen)
# --------------------------------------------------

class NewTaskCaptureRequest(BaseModel):
    title: str


class TaskMoveRequest(BaseModel):
    task_id: str
    target_status: str
    result_summary: Optional[str] = None


# --------------------------------------------------
# Endpunkte
# --------------------------------------------------

@router.get("/api/mission-control/state")
async def get_mission_control_state():
    now_mc = time.time()
    if _MC_STATE_CACHE["data"] is not None and (now_mc - _MC_STATE_CACHE["ts"]) < 3.0:
        return _MC_STATE_CACHE["data"]
    # SYNC-CALLS IM ASYNC-LOOP = BLOCKIERT BEI LANGSAMKEIT ALLES (gemessen:
    # health parallel 47ms -> 24.571ms). Deshalb aus dem Event-Loop auslagern.
    data = await asyncio.to_thread(_load_mission_control_data)
    tasks = data.get("tasks", [])

    # 23.10.2026: Live-Synchronisation mit kanban.db (Source of Truth für Tasks)
    def _fetch_in_progress_from_kanban():
        try:
            from backend.operations_api import _get_kanban_connection
            conn = _get_kanban_connection()
            try:
                cur = conn.cursor()
                rows = cur.execute("SELECT id, title, assignee, status, started_at, model_override FROM tasks WHERE status = 'in_progress'").fetchall()
                res = []
                for r in rows:
                    res.append({
                        "id": r["id"],
                        "title": r["title"],
                        "agent_id": r["assignee"],
                        "agent_name": r["assignee"],
                        "model": r["model_override"] or "omniroute/best-coding",
                        "status": "in_progress",
                        "started_at": r["started_at"]
                    })
                return res
            finally:
                conn.close()
        except Exception:
            return []

    k_tasks = await asyncio.to_thread(_fetch_in_progress_from_kanban)
    if k_tasks:
        tasks = [t for t in tasks if t.get("status") != "in_progress"] + k_tasks

    # 1. Profile aus agent_profiles.json laden (51 reale Profile)
    profiles = await asyncio.to_thread(api_get_hermes_profiles)
    total_profiles = max(len(profiles), 12)

    in_progress_tasks = [t for t in tasks if t.get("status") == "in_progress"]
    active_agent_ids = {t.get("agent_id") for t in in_progress_tasks if t.get("agent_id")}
    active_count = len(active_agent_ids)

    pending_approvals = sum(1 for t in tasks if t.get("status") == "approval")

    # 2. Live Telemetrie (Original-Funktion aus main.py, per configure injiziert)
    telemetry = await asyncio.to_thread(_DEPS["telemetry"])

    # 3. Dynamischer Cadre (Aktive Agenten mit Projekt-Kontext)
    cadre = []
    for t in in_progress_tasks:
        a_id = t.get("agent_id")
        prof = next((p for p in profiles if p.get("id") == a_id or p.get("person_name") == t.get("agent_name")), None)
        avatar = (prof.get("avatar") if prof else None) or f"/static/avatars/avatar_{((hash(a_id or 'micha') % 8) + 1):03d}.jpg"
        cadre.append({
            "id": a_id or "worker",
            "name": t.get("agent_name") or (prof.get("person_name") if prof else "Hermes Worker"),
            "role": (prof.get("name") if prof else "Projekt-Spezialist"),
            "model": t.get("model") or (prof.get("model") if prof else "Claude 3.7 Sonnet"),
            "project": t.get("title", "Aktives Projekt"),
            "status": "Beschäftigt",
            "avatar": avatar
        })

    # Falls keine Tasks aktiv sind: Lead-Agenten im Bereitschaftsmodus
    if not cadre and profiles:
        for p in profiles[:2]:
            cadre.append({
                "id": p.get("id"),
                "name": p.get("person_name") or p.get("name"),
                "role": p.get("name", "Projekt-Spezialist"),
                "model": p.get("model", "Claude 3.7 Sonnet"),
                "project": "Bereit",
                "status": "Bereit",
                "avatar": p.get("avatar") or f"/static/avatars/avatar_{((hash(p.get('id') or 'lead') % 8) + 1):03d}.jpg"
            })

    # 4. Kürzlich abgeschlossene Tasks (für UI-History)
    recent_completed = [t for t in tasks if t.get("status") == "completed"][:5]

    live_logs = data.get("audit_logs", [])

    res_payload = {
        "tasks": tasks,
        "total_tasks": len(tasks),
        "in_progress": in_progress_tasks,
        "active_agents": active_count,
        "total_agents": total_profiles,
        "pending_approvals": pending_approvals,
        "cadre": cadre,
        "recent_completed": recent_completed,
        "telemetry": {
            "tokens_last_15m": telemetry.get("tokens_last_15m", 0),
            "today_cost": telemetry.get("today_cost", 0.0),
            "latest_model": telemetry.get("latest_model", "deepseek/deepseek-v4-flash-0731"),
            "latest_tokens": telemetry.get("latest_tokens", 0),
            "model_breakdown": telemetry.get("model_breakdown", {}),
            "sparkline_data": telemetry.get("sparkline_data", []),
        },
        "audit_logs": live_logs[:25]
    }
    _MC_STATE_CACHE["ts"] = now_mc
    _MC_STATE_CACHE["data"] = res_payload
    return res_payload


@router.post("/api/mission-control/tasks/capture")
async def capture_mission_control_task(req: NewTaskCaptureRequest):
    if not req.title or not req.title.strip():
        raise HTTPException(status_code=400, detail="Aufgabentitel darf nicht leer sein.")

    task_id = f"task-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    # Intelligente Hermes Triage & Schätzung
    title = req.title.strip()
    is_large = any(k in title.lower() for k in ["audit", "refactor", "vollständig", "sicherheit", "pipeline", "db", "analyse"])

    est_tokens = 120000 if is_large else 35000
    est_cost = 0.22 if is_large else 0.04
    subagents = 3 if is_large else 1
    agent_id = "sandy" if "audit" in title.lower() or "hr" in title.lower() else "micha"
    agent_name = "Sandy Hooks" if agent_id == "sandy" else "Michael Keller"
    model = "anthropic/claude-3.7-sonnet" if is_large else "deepseek/deepseek-v4-flash-0731"

    new_task = {
        "id": task_id,
        "title": title,
        "capture_input": title,
        "plan": [
            f"Hermes Triage: Anforderung '{title}' analysieren",
            f"Ressourcen- und Werkzeugallokation für {agent_name}",
            "Ausführung über OmniRoute & Dokumentation in Obsidian"
        ],
        "agent_id": agent_id,
        "agent_name": agent_name,
        "model": model,
        "estimated_tokens": est_tokens,
        "estimated_cost_eur": est_cost,
        "subagents_count": subagents,
        "status": "backlog",
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "result_summary": "",
        "artifact_path": "",
        "parent_project_id": None,
        "subtask_ids": [],
        "target_action": core_dispatcher.detect_target_action(title),
        "phase": "execution"
    }

    # Atomares Read-Modify-Write: laedt, aendert und schreibt unter EINEM Lock.
    # Vorher wurde data vorab geladen und am Ende separat gespeichert — parallele
    # Captures ueberschrieben einander (Lost Update, Audit B1). Der Aufruf
    # blockiert (Datei-I/O + fsync) und laeuft deshalb im Thread-Pool.
    def _mutate(data: dict) -> dict:
        data.setdefault("tasks", []).insert(0, new_task)
        now_t = datetime.datetime.now().strftime("%H:%M:%S")
        data.setdefault("audit_logs", []).insert(0, {
            "time": now_t,
            "source": "Capture",
            "msg": f"Neuer Task #{task_id} erfasst: '{title[:40]}...'"
        })
        data["audit_logs"] = data["audit_logs"][:25]
        return new_task

    await asyncio.to_thread(update_mission_control_data, _mutate)
    _MC_STATE_CACHE["ts"] = 0.0  # Cache invalidieren
    broadcast_event("kanban_updated", {"action": "capture", "task_id": task_id, "status": "backlog"})
    return {"status": "ok", "task": new_task}


@router.post("/api/mission-control/tasks/move")
async def move_mission_control_task(req: TaskMoveRequest):
    """Verschiebt einen Task. Zustandswechsel atomar, Seiteneffekte danach.

    Aufbau in zwei Phasen (Audit B1): Phase 1 laedt, aendert und schreibt den
    Store unter EINEM Lock und laeuft im Thread-Pool (die Datei wird per fsync
    geschrieben). Phase 2 fuehrt alles aus, was awaiten muss (Synthese-
    Finalisierung) oder Zeit kostet (execute/fan_in) — NACH dem Schreiben, damit
    kein Lock ueber einem await gehalten wird und parallele Moves einander
    nicht mehr ueberschreiben.
    """
    # ---------------- Phase 1: atomarer Zustandswechsel ----------------
    def _apply(data: dict) -> dict:
        tasks = data.get("tasks", [])
        task = next((t for t in tasks if t.get("id") == req.task_id), None)
        if task is None:
            return {"found": False}

        if req.target_status == "dismissed":
            tasks.remove(task)
            return {
                "found": True,
                "dismissed": True,
                "task": task,
                "ticker": ("Approval Gate", f"Task #{task['id']} wurde verworfen"),
            }

        task["status"] = req.target_status
        plan: dict = {"found": True, "task": task}

        if req.target_status == "in_progress":
            task["started_at"] = time.time()
            task["active_tool"] = "Tool: web_search & core_dispatcher"
            plan["ticker"] = ("Approval Gate", f"Task #{task['id']} genehmigt & an {task['agent_name']} übergeben")
            plan["execute"] = True

        elif req.target_status == "completed":
            if req.result_summary:
                task["result_summary"] = req.result_summary
            elif not task.get("result_summary"):
                task["result_summary"] = f"Erfolgreich von {task['agent_name']} abgeschlossen. Alle Kriterien erfüllt."

            # N-10: sync_obsidian darf nicht unter _MC_DATA_LOCK ausgefuehrt werden (I/O-Blockade).
            # Plan markieren und Ausfuehrung in Phase 2 ausserhalb des Locks verlagern.
            plan["needs_sync_obsidian"] = True

            # FAN-IN (12.10.2026): Diese Task IST Lisas Entwurf-Freigabe
            # (synthesis_draft_path) -> beim Approved-Move finalisieren.
            if task.get("synthesis_draft_path") and not task.get("synthesis_finalized"):
                task["synthesis_finalized"] = True
                plan["finalize"] = {
                    "parent_pid": task.get("parent_project_id") or req.task_id,
                    "draft_path": task.get("synthesis_draft_path"),
                    "text": task.get("result_summary") or "",
                }

            parent_pid = task.get("parent_project_id") or task.get("parent_task_id")
            if parent_pid and parent_pid != req.task_id:
                plan["fan_in"] = parent_pid

        data["audit_logs"] = data.get("audit_logs", [])[:25]
        return plan

    plan = await asyncio.to_thread(update_mission_control_data, _apply)

    if not plan.get("found"):
        raise HTTPException(status_code=404, detail="Task nicht gefunden.")

    task = plan["task"]

    # ---------------- Phase 2: Seiteneffekte ohne Lock ----------------
    if plan.get("ticker"):
        add_ticker(*plan["ticker"])

    if plan.get("needs_sync_obsidian") and "sync_obsidian" in _DEPS:
        try:
            obs_path = await asyncio.to_thread(_DEPS["sync_obsidian"], task)
            if obs_path:
                task["artifact_path"] = obs_path
                plan["obs_path"] = obs_path

                def _update_artifact(d: dict):
                    t = next((x for x in d.get("tasks", []) if x.get("id") == task["id"]), None)
                    if t:
                        t["artifact_path"] = obs_path

                await asyncio.to_thread(update_mission_control_data, _update_artifact)
        except Exception as e:
            logger.warning(f"[MissionControl] sync_obsidian fehlgeschlagen: {e}")

    if plan.get("obs_path"):
        add_ticker("Obsidian", f"Projekt-Dokumentation {os.path.basename(plan['obs_path'])} geschrieben")

    if plan.get("finalize"):
        fin = plan["finalize"]
        # Ohne daten-Parameter: die Finalisierung laedt den Store selbst frisch.
        # Vorher wurde das Handler-dict durchgereicht, damit ein spaeteres
        # _save_mission_control_data(data) den Update nicht ueberschreibt — der
        # Zwang entfaellt, weil hier VOR dem await geschrieben wurde.
        await _DEPS["finalize_approval"](
            fin["parent_pid"],
            fin["draft_path"],
            fin["text"],
            "Freigabe per Board-Move (Approval-Gate)",
        )

    if plan.get("execute"):
        asyncio.create_task(_DEPS["execute"](task["id"]))
    if plan.get("fan_in"):
        asyncio.create_task(_DEPS["fan_in"](plan["fan_in"]))

    _MC_STATE_CACHE["ts"] = 0.0  # Cache invalidieren
    broadcast_event("kanban_updated", {"action": "move", "task_id": req.task_id, "status": req.target_status})

    if plan.get("dismissed"):
        return {"status": "ok", "message": "Task verworfen."}
    return {"status": "ok", "task": task}


@router.get("/api/mission-control/task/{task_id}/artifact")
async def get_mission_control_task_artifact(task_id: str):
    data = _load_mission_control_data()
    task = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task nicht gefunden.")

    p = task.get("artifact_path")
    if p and os.path.exists(p) and os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            return {"status": "ok", "content": f.read(), "path": p}

    # R-13: existiert kein Artefakt, wird KEIN synthetischer Erfolgsbericht
    # ("Aufgabe erfolgreich abgeschlossen.") erfunden — ein Task ohne Ergebnis
    # muss im Cockpit als ergebnislos erkennbar bleiben.
    raise HTTPException(status_code=404, detail="Artefakt nicht gefunden.")
