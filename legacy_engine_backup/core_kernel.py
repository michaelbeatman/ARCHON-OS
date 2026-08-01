import os
import sys
import json
import asyncio
import datetime
import uvicorn
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel

# Füge Pfad hinzu, um core_storage importieren zu können
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from core_storage import CoreStorage

# FastAPI App für den Daemon
app = FastAPI(title="Hermes Agentic OS Kernel Daemon")

class EnqueueRequest(BaseModel):
    task_id: str
    agent_id: str
    payload: Dict[str, Any]

class ConfigRequest(BaseModel):
    algorithm: Optional[str] = None
    max_concurrent_tasks: Optional[int] = None
    task_timeout: Optional[float] = None


class Scheduler:
    def __init__(self, db_path: str):
        self.storage = CoreStorage(db_path)
        self.max_concurrent_tasks = 3
        self.task_timeout = 60.0  # 60 Sekunden Timeout
        self.check_interval = 5.0  # Maximaler Sleep-Interval
        
        self.algorithm = "FIFO"  # Oder "RR" (Round Robin)
        self.last_run_agent_id = None
        
        self.is_running = False
        self.wakeup_event = asyncio.Event()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.task_start_times: Dict[str, datetime.datetime] = {}
        
        self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)

    def set_config(self, algorithm: Optional[str] = None, max_concurrent: Optional[int] = None, timeout: Optional[float] = None):
        if algorithm in ["FIFO", "RR"]:
            self.algorithm = algorithm
            print(f"[Kernel] Scheduling algorithm set to {algorithm}")
        if max_concurrent is not None and max_concurrent > 0:
            self.max_concurrent_tasks = max_concurrent
            self.semaphore = asyncio.Semaphore(max_concurrent)
            print(f"[Kernel] Max concurrent tasks set to {max_concurrent}")
        if timeout is not None and timeout > 0:
            self.task_timeout = timeout
            print(f"[Kernel] Task timeout set to {timeout}s")

    async def start(self):
        self.is_running = True
        print("[Kernel] Starting Scheduler Daemon loops...")
        asyncio.create_task(self._scheduler_loop())
        asyncio.create_task(self._watchdog_loop())

    async def stop(self):
        self.is_running = False
        self.wakeup_event.set()
        # Cancel running tasks
        for task_id, task in list(self.active_tasks.items()):
            task.cancel()
        print("[Kernel] Scheduler Daemon stopped.")

    def _fetch_next_task(self) -> Optional[Dict[str, Any]]:
        """
        Holt den nächsten abzuarbeitenden Task aus der SQLite-Datenbank.
        Unterstützt FIFO und Round Robin (RR) Rotation basierend auf agent_id.
        """
        # Alle ausstehenden (pending) Tasks aus der DB holen
        conn = self.storage._get_connection()
        try:
            rows = conn.execute("SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at ASC").fetchall()
            if not rows:
                return None
            
            pending_tasks = [dict(r) for r in rows]
            # Filtere bereits aktive oder gequeue-te Tasks aus
            pending_tasks = [t for t in pending_tasks if t["task_id"] not in self.active_tasks]
            if not pending_tasks:
                return None
            
            if self.algorithm == "FIFO":
                return pending_tasks[0]
                
            elif self.algorithm == "RR":
                # Gruppiere Tasks nach agent_id
                by_agent: Dict[str, List[Dict[str, Any]]] = {}
                for t in pending_tasks:
                    by_agent.setdefault(t["agent_id"], []).append(t)
                
                unique_agents = sorted(list(by_agent.keys()))
                
                # Finde den nächsten Agenten in Rotation
                next_agent = None
                if self.last_run_agent_id is None or self.last_run_agent_id not in unique_agents:
                    next_agent = unique_agents[0]
                else:
                    idx = unique_agents.index(self.last_run_agent_id)
                    next_agent = unique_agents[(idx + 1) % len(unique_agents)]
                
                # Setze den ausgewählten Agenten und hole dessen ältesten Task
                self.last_run_agent_id = next_agent
                return by_agent[next_agent][0]
                
        finally:
            conn.close()
        return None

    async def _scheduler_loop(self):
        """
        Hauptschleife des Schedulers. Optimiert als "Sleep-until-next-due" (Tickless Kernel).
        """
        while self.is_running:
            # Prüfe, ob Ausführungsslots frei sind
            if len(self.active_tasks) >= self.max_concurrent_tasks:
                await asyncio.sleep(0.2)
                continue

            task = self._fetch_next_task()
            if task:
                # Slot belegen und Task asynchron starten (Fire-and-Forget)
                task_id = task["task_id"]
                worker_task = asyncio.create_task(self._run_task_wrapper(task))
                # Sofort registrieren, um Doppel-Fetches in der Event-Loop zu verhindern
                self.active_tasks[task_id] = worker_task
            else:
                # Keine Tasks vorhanden: Schlafe bis zum nächsten Wakeup-Event oder Timeout
                try:
                    await asyncio.wait_for(self.wakeup_event.wait(), timeout=self.check_interval)
                    self.wakeup_event.clear()
                except asyncio.TimeoutError:
                    pass

    async def _run_task_wrapper(self, task: Dict[str, Any]):
        task_id = task["task_id"]
        agent_id = task["agent_id"]
        
        async with self.semaphore:
            # Registriere Startzeit
            self.task_start_times[task_id] = datetime.datetime.now()
            
            # Setze Status in DB auf 'in_progress'
            self.storage.save_task(task_id, agent_id, "in_progress")
            print(f"[Kernel] Executing task {task_id} for agent {agent_id}...")
            
            try:
                # Simuliere die Ausführung des Agenten-Prozesses
                payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
                duration = payload.get("duration", 2) if payload else 2
                
                # Warte die simulierte Arbeitsdauer ab
                await asyncio.sleep(duration)
                
                # Erfolg abspeichern
                result = {"status": "success", "result": f"Executed by Kernel successfully. Simulated duration: {duration}s."}
                self.storage.save_task(task_id, agent_id, "completed", result=result)
                print(f"[Kernel] Task {task_id} completed.")
                
            except asyncio.CancelledError:
                # Vom Watchdog abgebrochen
                print(f"[Kernel] Task {task_id} was preemptively CANCELLED by Watchdog.")
                # Der Status wird im finalen DB-Aufruf oder vom watchdog direkt gesetzt.
                raise
            except Exception as e:
                # Fehler protokollieren
                self.storage.save_task(task_id, agent_id, "failed", result={"error": str(e)})
                print(f"[Kernel] Task {task_id} failed: {e}")
            finally:
                self.active_tasks.pop(task_id, None)
                self.task_start_times.pop(task_id, None)

    async def _watchdog_loop(self):
        """
        Watchdog-Loop. Prüft alle 30 Sekunden hängengebliebene Tasks und bricht diese ab.
        """
        while self.is_running:
            await asyncio.sleep(10.0)  # Für Tests auf 10s verkürzt (30s Standard)
            now = datetime.datetime.now()
            
            for task_id, start_time in list(self.task_start_times.items()):
                duration = (now - start_time).total_seconds()
                if duration > self.task_timeout:
                    print(f"[Watchdog] PREEMPTION WARNING: Task {task_id} hung for {duration:.1f}s. Terminating task...")
                    task_obj = self.active_tasks.get(task_id)
                    if task_obj:
                        task_obj.cancel()
                    self.task_start_times.pop(task_id, None)
                    self.active_tasks.pop(task_id, None)
                    # Status direkt auf failed setzen
                    self.storage.save_task(
                        task_id, 
                        "system", 
                        "failed", 
                        result={"error": f"Task preemptively terminated by Watchdog. Timeout of {self.task_timeout}s exceeded."}
                    )


# --- Initialisiere globalen Scheduler ---
DB_DIR = "/app/data" if os.path.exists("/app/data") else "."
DB_PATH = os.path.join(DB_DIR, "agent_os.db")
scheduler = Scheduler(DB_PATH)


@app.on_event("startup")
async def startup_event():
    await scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    await scheduler.stop()


# --- REST API Endpunkte für den Kernel ---

@app.post("/enqueue")
def enqueue_task(req: EnqueueRequest):
    # Speichere den Task als 'pending' in der DB
    scheduler.storage.save_task(
        task_id=req.task_id,
        agent_id=req.agent_id,
        status="pending",
        payload=req.payload
    )
    # Signalisiere dem Scheduler-Loop das Vorhandensein eines neuen Tasks
    scheduler.wakeup_event.set()
    return {"status": "enqueued", "task_id": req.task_id}

@app.get("/status")
def get_kernel_status():
    return {
        "status": "running" if scheduler.is_running else "stopped",
        "algorithm": scheduler.algorithm,
        "max_concurrent_tasks": scheduler.max_concurrent_tasks,
        "active_tasks_count": len(scheduler.active_tasks),
        "active_tasks_list": list(scheduler.active_tasks.keys()),
        "task_timeout": scheduler.task_timeout
    }

@app.post("/config")
def configure_kernel(req: ConfigRequest):
    scheduler.set_config(
        algorithm=req.algorithm,
        max_concurrent=req.max_concurrent_tasks,
        timeout=req.task_timeout
    )
    return {"status": "configured", "config": get_kernel_status()}

@app.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    task = scheduler.storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    return task

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8420)
