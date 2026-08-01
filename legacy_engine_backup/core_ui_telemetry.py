import os
import sys
import json
import datetime
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# Pfad anpassen
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from core_storage import AgentManifest, CoreStorage
from core_kernel import scheduler
from core_sdk_contract import AgentContract, AOSAgent

app = FastAPI(title="Hermes Agentic OS UI Telemetry API")

# --- Pydantic Request Models ---
class DeployRequest(BaseModel):
    manifest_content: str

class ExecuteRequest(BaseModel):
    agent_id: str
    prompt: str


# --- Thread-Safe Wakeup helper ---
def _safe_wakeup():
    if hasattr(scheduler.wakeup_event, "_loop") and scheduler.wakeup_event._loop:
        try:
            scheduler.wakeup_event._loop.call_soon_threadsafe(scheduler.wakeup_event.set)
        except Exception:
            scheduler.wakeup_event.set()
    else:
        scheduler.wakeup_event.set()


# --- Endpunkte ---

@app.post("/api/v1/deploy")
def deploy_agent(req: DeployRequest):
    """
    Validiert ein Manifest im Markdown-Format (mit YAML Frontmatter)
    und speichert es unter `./manifests/{agent_id}.md`.
    """
    # 1. Temporär schreiben um auslesen zu können
    os.makedirs("./manifests", exist_ok=True)
    temp_path = "./manifests/temp_deploy.md"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(req.manifest_content)

    # 2. Manifest validieren
    try:
        manifest = AgentManifest.from_markdown(temp_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=400, detail=f"Ungültiges Manifest: {e}")

    # 3. Permanent speichern
    permanent_path = f"./manifests/{manifest.agent_id}.md"
    shutil_path = os.path.abspath(permanent_path)
    with open(shutil_path, "w", encoding="utf-8") as f:
        f.write(req.manifest_content)

    if os.path.exists(temp_path):
        os.remove(temp_path)

    print(f"[UI Telemetry] Deployed agent manifest: {manifest.agent_id}")
    return {
        "status": "deployed",
        "agent_id": manifest.agent_id,
        "name": manifest.name,
        "privilege_group": manifest.privilege_group
    }


@app.post("/api/v1/execute")
def execute_agent(req: ExecuteRequest):
    """
    Lädt das Manifest für eine agent_id, erstellt einen AgentContract
    und startet die Instanz auf dem Kernel via AOSAgent.spawn.
    """
    manifest_path = f"./manifests/{req.agent_id}.md"
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=404, detail=f"Agent-Manifest für {req.agent_id} nicht gefunden. Bitte erst deployen.")

    try:
        manifest = AgentManifest.from_markdown(manifest_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fehler beim Laden des Manifests: {e}")

    # 1. Erstelle Agenten-Kontrakt aus Manifest-Daten (Schicht 9)
    contract = AgentContract(
        agent_id=manifest.agent_id,
        name=manifest.name,
        prompt_templates={"system": manifest.system_prompt, "user": req.prompt},
        tool_schema_scopes=manifest.mcp_tools,
        model_routing_policies={"data_residency": "local" if "ollama" in manifest.base_model.lower() else "remote"},
        token_cost_budgets={"max_tokens": 10000}
    )

    # 2. Spawne Agent via SDK Binder
    agent = AOSAgent.spawn(contract, scheduler.storage.db_path)
    
    # Hole Task ID
    conn = scheduler.storage._get_connection()
    try:
        row = conn.execute("SELECT task_id FROM tasks WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1", (req.agent_id,)).fetchone()
        task_id = row["task_id"] if row else f"task_{req.agent_id}_unknown"
    finally:
        conn.close()

    # Wecke den Scheduler auf
    _safe_wakeup()

    print(f"[UI Telemetry] Triggered task execution: {task_id}")
    return {"status": "started", "task_id": task_id, "agent_id": req.agent_id}


@app.get("/api/v1/telemetry/dashboard")
def get_dashboard_data():
    """
    Liefert Echtzeitdaten über Tasks und berechnet dynamisch
    die durchschnittliche Uptime (Average Uptime) aller beendeten Tasks.
    """
    conn = scheduler.storage._get_connection()
    try:
        # 1. Alle Tasks holen
        rows = conn.execute("SELECT * FROM tasks").fetchall()
        
        running_tasks = []
        durations = []
        now = datetime.datetime.now()

        for row in rows:
            task_id = row["task_id"]
            agent_id = row["agent_id"]
            status = row["status"]
            created_at_str = row["created_at"]
            updated_at_str = row["updated_at"]

            try:
                created_at = datetime.datetime.fromisoformat(created_at_str)
                updated_at = datetime.datetime.fromisoformat(updated_at_str)
            except Exception:
                created_at = now
                updated_at = now

            # Berechne Uptime
            if status == "in_progress":
                uptime = (now - created_at).total_seconds()
            else:
                uptime = (updated_at - created_at).total_seconds()

            running_tasks.append({
                "task_id": task_id,
                "agent_id": agent_id,
                "status": status,
                "uptime": round(uptime, 2)
            })

            # Berechne historische Dauern für Average Uptime
            if status in ("completed", "failed"):
                durations.append(uptime)

        avg_uptime = sum(durations) / len(durations) if durations else 0.0

        return {
            "running_tasks": running_tasks,
            "average_uptime": round(avg_uptime, 2)
        }
    finally:
        conn.close()


@app.get("/api/v1/telemetry/logs")
def stream_telemetry_logs(request: Request):
    """
    SSE-Endpoint, der Logs und System-Heratbeats fälschungssicher streamt.
    """
    async def log_generator():
        yield f"data: {json.dumps({'message': 'SYSTEM ONLINE', 'level': 'INFO', 'timestamp': datetime.datetime.now().isoformat()})}\n\n"
        
        while True:
            if await request.is_disconnected():
                break

            now = datetime.datetime.now()
            log_data = {
                "message": "Heartbeat OK",
                "level": "INFO",
                "timestamp": now.isoformat(),
                "metrics": {
                    "active_tasks_count": len(scheduler.active_tasks),
                    "scheduler_status": "running" if scheduler.is_running else "stopped"
                }
            }
            yield f"data: {json.dumps(log_data)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(log_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
