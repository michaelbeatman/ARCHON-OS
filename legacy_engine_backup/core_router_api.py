import os
import sys
import json
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# Pfad anpassen
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from core_storage import CoreStorage, AgentManifest
from core_drivers import MCPRegistry, MCPTool

app = FastAPI(title="Hermes Agentic OS Router API Gateway")

# Initialisierung
DB_DIR = "/app/data" if os.path.exists("/app/data") else "."
DB_PATH = os.path.join(DB_DIR, "agent_os.db")
storage = CoreStorage(DB_PATH)
registry = MCPRegistry()

# Register dummy tools for testing
registry.register_tool(
    MCPTool("mcp__filesystem__write_file", "Writes file", {"path": ".*", "content": ".*"}),
    lambda path, content: {"status": "written", "path": path}
)
registry.register_tool(
    MCPTool("mcp__filesystem__delete_file", "Deletes file", {"path": ".*"}),
    lambda path: {"status": "deleted", "path": path}
)

class EventPublisher:
    def __init__(self):
        self.listeners = []

    def subscribe(self, queue: asyncio.Queue):
        self.listeners.append(queue)

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self.listeners:
            self.listeners.remove(queue)

    async def publish(self, event: Dict[str, Any]):
        for queue in list(self.listeners):
            try:
                await queue.put(event)
            except Exception:
                pass

publisher = EventPublisher()

# --- Pydantic Request Models ---
class RouteRequest(BaseModel):
    task_type: str  # e.g., "coding", "routine"
    prompt: str
    is_sensitive: bool = False

class ToolExecutionRequest(BaseModel):
    agent_id: str
    tool_name: str
    arguments: Dict[str, Any]
    task_id: str


# --- Multi-Provider AI Routing (HAL) ---
class AIRouter:
    def __init__(self, db_storage: CoreStorage):
        self.storage = db_storage

    def route_request(self, req: RouteRequest) -> Dict[str, str]:
        # Prüfe Data Residency in den globalen Benutzereinstellungen
        data_residency = self.storage.get_preference("data_residency_policy")
        
        # Strikte Data Residency Policy: Lokale Ollama-Instanz
        if data_residency == "local" or req.is_sensitive:
            return {
                "provider": "ollama",
                "endpoint": "http://localhost:11434/v1",
                "model": "llama3",
                "note": "Routed to local instance due to data residency policy or sensitive flag."
            }
            
        # Dynamisches Routing nach Aufgabentyp
        if req.task_type == "coding":
            return {
                "provider": "anthropic",
                "endpoint": "https://api.anthropic.com/v1",
                "model": "claude-3-5-sonnet",
                "note": "Routed to high-performing coder model."
            }
        else:
            return {
                "provider": "openai",
                "endpoint": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "note": "Routed to lightweight cost-efficient model."
            }


ai_router = AIRouter(storage)


# --- REST API Endpunkte ---

@app.post("/route")
def route_ai_request(req: RouteRequest):
    return ai_router.route_request(req)


@app.post("/execute-tool")
async def execute_agent_tool(req: ToolExecutionRequest):
    """
    Führt ein Tool aus. Prüft RBAC-Rechte des Agenten und HITL-Freigaben für kritische Operationen.
    """
    # 1. RBAC Prüfung
    # Simuliere das Laden des Agenten-Manifests
    # In der Realität laden wir SUBAGENT.md, hier simulieren wir es über eine Mock-Struktur:
    allowed_tools = []
    if req.agent_id == "openclaw":
        allowed_tools = ["mcp__filesystem__write_file"]
    elif req.agent_id == "admin_agent":
        allowed_tools = ["mcp__filesystem__write_file", "mcp__filesystem__delete_file"]
        
    if req.tool_name not in allowed_tools:
        raise HTTPException(
            status_code=403, 
            detail=f"Access Denied: Agent '{req.agent_id}' has no privileges to call '{req.tool_name}'."
        )

    # 2. Human-in-the-Loop (HITL) Prüfung
    # Kritische Aktionen (z.B. Deletion) frieren den Task ein
    is_critical = "delete" in req.tool_name or req.arguments.get("critical", False)
    
    if is_critical:
        # Friere den Task-Status in der DB ein
        storage.save_task(
            task_id=req.task_id, 
            agent_id=req.agent_id, 
            status="pending_approval", 
            payload={"tool_name": req.tool_name, "arguments": req.arguments}
        )
        
        # Event in SSE Queue einreihen
        await publisher.publish({
            "event": "task_frozen",
            "task_id": req.task_id,
            "agent_id": req.agent_id,
            "tool_name": req.tool_name,
            "message": "Task requires human approval."
        })
        
        return {
            "status": "pending_approval", 
            "message": "Action requires human approval. Task execution frozen."
        }

    # Reguläre Ausführung des Tools
    try:
        res = registry.execute_tool(req.tool_name, req.arguments)
        # Event in Queue einreihen
        await publisher.publish({
            "event": "tool_executed",
            "task_id": req.task_id,
            "tool_name": req.tool_name,
            "status": "success"
        })
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str):
    """
    Gibt einen eingefrorenen Task frei und führt die kritische Aktion aus.
    """
    task = storage.get_task(task_id)
    if not task or task["status"] != "pending_approval":
        raise HTTPException(status_code=404, detail="Task not found or not pending approval.")

    payload = task["payload"]
    tool_name = payload["tool_name"]
    arguments = payload["arguments"]

    # Führe das Tool jetzt aus
    try:
        res = registry.execute_tool(tool_name, arguments)
        storage.save_task(task_id, task["agent_id"], "completed", result=res)
        
        # SSE Event
        await publisher.publish({
            "event": "task_approved",
            "task_id": task_id,
            "status": "completed"
        })
        return {"status": "approved_and_completed", "result": res}
    except Exception as e:
        storage.save_task(task_id, task["agent_id"], "failed", result={"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tasks/{task_id}/reject")
async def reject_task(task_id: str):
    """
    Lehnt den Task ab und markiert ihn als fehlgeschlagen.
    """
    task = storage.get_task(task_id)
    if not task or task["status"] != "pending_approval":
        raise HTTPException(status_code=404, detail="Task not found or not pending approval.")

    storage.save_task(
        task_id, 
        task["agent_id"], 
        "failed", 
        result={"error": "Rejected by User (Human-in-the-Loop)."}
    )
    
    # SSE Event
    await publisher.publish({
        "event": "task_rejected",
        "task_id": task_id,
        "status": "failed"
    })
    return {"status": "rejected"}


# --- Server-Sent Events (SSE) Streaming ---

@app.get("/stream")
async def stream_task_updates(request: Request):
    """
    Echtzeit-SSE-Stream für Task- und Kerneländerungen.
    """
    # Lokale Queue für diesen Client, an den Event-Loop dieses Requests gebunden
    queue = asyncio.Queue()
    publisher.subscribe(queue)

    async def event_generator():
        try:
            while True:
                # Verbindungstrennung des Clients prüfen
                if await request.is_disconnected():
                    break
                    
                try:
                    # Hole Event aus der asynchronen Queue mit kurzem Timeout
                    event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event_data)}\n\n"
                    queue.task_done()
                except asyncio.TimeoutError:
                    # Heartbeat senden, um Verbindung offen zu halten
                    yield "data: {\"event\": \"ping\"}\n\n"
        finally:
            publisher.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
