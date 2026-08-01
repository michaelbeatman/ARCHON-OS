import os
import sys
import json
import datetime
import asyncio
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# Pfad anpassen
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from core_kernel import scheduler

app = FastAPI(title="Hermes Agentic OS Command Center API")

def _safe_wakeup():
    if hasattr(scheduler.wakeup_event, "_loop") and scheduler.wakeup_event._loop:
        try:
            scheduler.wakeup_event._loop.call_soon_threadsafe(scheduler.wakeup_event.set)
        except Exception:
            scheduler.wakeup_event.set()
    else:
        scheduler.wakeup_event.set()

def _safe_cancel(task_obj):
    if task_obj:
        try:
            loop = task_obj.get_loop()
            loop.call_soon_threadsafe(task_obj.cancel)
        except Exception:
            task_obj.cancel()

# --- Pydantic Models ---
class ExecuteRequest(BaseModel):
    task_id: str
    prompt: str
    agent_id: Optional[str] = None

class InterruptionRequest(BaseModel):
    task_id: str


# --- REST API Endpunkte ---

@app.post("/api/v1/execute")
def execute_command(req: ExecuteRequest):
    """
    Nimmt Aufgaben aus der UI entgegen.
    Verarbeitet targeted Routing (z. B. "@openclaw do task").
    """
    agent_id = req.agent_id
    prompt = req.prompt.strip()

    # Kommandozeilen-Routing parsen (z. B. @hermes do research)
    if not agent_id and prompt.startswith("@"):
        parts = prompt.split(" ", 1)
        agent_id = parts[0][1:]
        prompt = parts[1] if len(parts) > 1 else ""

    if not agent_id:
        agent_id = "default_agent"

    # Standard-Arbeitsdauer von 10 Sekunden eintragen, um Pause/Resume testen zu können
    payload = {"prompt": prompt, "duration": 10, "step_index": 0}

    # Task als pending in der DB einreihen
    scheduler.storage.save_task(
        task_id=req.task_id,
        agent_id=agent_id,
        status="pending",
        payload=payload
    )

    # Wakeup-Event senden, um Scheduler-Loop anzustoßen
    _safe_wakeup()
    print(f"[Command Center] Enqueued task {req.task_id} for agent {agent_id}")
    return {"status": "enqueued", "agent_id": agent_id, "task_id": req.task_id}


@app.post("/api/v1/abort")
def abort_task(req: InterruptionRequest):
    """
    Bricht eine laufende Task hart ab.
    """
    task_id = req.task_id
    task_obj = scheduler.active_tasks.get(task_id)
    if task_obj:
        _safe_cancel(task_obj)
        
    scheduler.storage.save_task(
        task_id,
        "system",
        "failed",
        result={"error": "Task was explicitly aborted by user."}
    )
    print(f"[Command Center] Aborted task {task_id}")
    return {"status": "aborted", "task_id": task_id}


@app.post("/api/v1/pause")
def pause_task(req: InterruptionRequest):
    """
    Unterbricht eine laufende Task, speichert den Fortschritt (Context Snapshot) und versetzt sie in 'suspended'.
    """
    task_id = req.task_id
    task_obj = scheduler.active_tasks.get(task_id)
    start_time = scheduler.task_start_times.get(task_id)

    if not task_obj or not start_time:
        raise HTTPException(status_code=400, detail="Task is not currently running.")

    # Berechne abgelaufene Zeit und verbleibende Restzeit
    now = datetime.datetime.now()
    elapsed = (now - start_time).total_seconds()

    task_data = scheduler.storage.get_task(task_id)
    payload = task_data["payload"] if task_data else {}
    total_duration = payload.get("duration", 10.0) if payload else 10.0

    remaining = max(0.1, total_duration - elapsed)

    # Context Snapshot (Logits-Simulation)
    snapshot = {
        "remaining_duration": remaining,
        "step_index": payload.get("step_index", 0) + 1,
        "logits_snapshot": [0.0125, -0.456, 0.789, -0.123], # Logits Context Snapshot
        "suspended_at": now.isoformat()
    }

    # Snapshot in KV Store speichern
    scheduler.storage.set_kv(f"snapshot_{task_id}", snapshot)

    # Breche asyncio.Task ab
    _safe_cancel(task_obj)

    # Status auf suspended ändern
    scheduler.storage.save_task(task_id, task_data["agent_id"], "suspended")
    print(f"[Command Center] Suspended task {task_id} with {remaining:.2f}s remaining.")
    
    return {
        "status": "suspended",
        "task_id": task_id,
        "snapshot": snapshot
    }


@app.post("/api/v1/resume")
def resume_task(req: InterruptionRequest):
    """
    Setzt eine pausierte Task (suspended) fort.
    """
    task_id = req.task_id
    task_data = scheduler.storage.get_task(task_id)

    if not task_data or task_data["status"] != "suspended":
        raise HTTPException(status_code=400, detail="Task is not currently suspended.")

    # Lade Context Snapshot
    snapshot = scheduler.storage.get_kv(f"snapshot_{task_id}")
    if not snapshot:
        raise HTTPException(status_code=404, detail="Context snapshot not found.")

    # Wiederherstellen der Parameter aus dem Snapshot
    payload = task_data["payload"] if task_data["payload"] else {}
    payload["duration"] = snapshot["remaining_duration"]
    payload["step_index"] = snapshot["step_index"]

    # Stelle Task wieder auf pending, damit Scheduler sie neu einreiht
    scheduler.storage.save_task(
        task_id,
        task_data["agent_id"],
        "pending",
        payload=payload
    )

    # Wecke den Scheduler
    _safe_wakeup()
    print(f"[Command Center] Resumed task {task_id} with {snapshot['remaining_duration']:.2f}s remaining.")
    return {"status": "resumed", "task_id": task_id}


# --- Server-Sent Events (SSE) Telemetrie ---

@app.get("/api/v1/telemetry")
def stream_telemetry(request: Request):
    """
    Live-Telemetrie Stream für aktive Tasks, Uptime und Token-Verbrauch.
    """
    async def telemetry_generator():
        while True:
            if await request.is_disconnected():
                break

            now = datetime.datetime.now()
            running_tasks = []

            for task_id, task_obj in list(scheduler.active_tasks.items()):
                start_time = scheduler.task_start_times.get(task_id)
                uptime = (now - start_time).total_seconds() if start_time else 0.0

                task_data = scheduler.storage.get_task(task_id)
                agent_id = task_data["agent_id"] if task_data else "unknown"
                status = task_data["status"] if task_data else "in_progress"

                running_tasks.append({
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "status": status,
                    "uptime": round(uptime, 2),
                    "token_usage": int(uptime * 150)  # Simulierte 150 Tokens/Sekunde
                })

            telemetry_data = {
                "timestamp": now.isoformat(),
                "scheduler_status": "running" if scheduler.is_running else "stopped",
                "running_tasks": running_tasks
            }

            yield f"data: {json.dumps(telemetry_data)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(telemetry_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8420)
