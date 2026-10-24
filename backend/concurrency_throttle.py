"""
backend/concurrency_throttle.py
Konfigurierbare Concurrency-Drosselung mit Prioritäts-Preemption Scheduler (Pillar 1).
Ordnet wartende Aufgaben nach Prioritätsstufen:
- P3 (Dringend / Direkter Chat): Höchste Priorität, rückt an Slot-Spitze vor
- P2 (Normal / Geplante Aufgaben): Standard-Abarbeitung
- P1 (Routine / Hintergrund-Recherche): Nachrangig
Die Obergrenze max_concurrent_agents ist zur Laufzeit frei skalierbar.
"""

import os
import sys
import json
import asyncio
import heapq
from typing import Dict, Any, Optional, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

def get_concurrency_config() -> Dict[str, Any]:
    cfg = {
        "max_concurrent_agents": 4,
        "queue_timeout_seconds": 60
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                if "concurrency" in s and isinstance(s["concurrency"], dict):
                    cfg.update(s["concurrency"])
        except Exception:
            pass
    return cfg

def save_concurrency_config(new_cfg: Dict[str, Any]) -> bool:
    try:
        current = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        current["concurrency"] = new_cfg
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ConcurrencyThrottle] Config save error: {e}", file=sys.stderr)
        return False

class PriorityConcurrencyThrottle:
    def __init__(self):
        self._active_slots = {}
        self._wait_queue = [] # Heap von (-priority, arrival_time, task_id, agent_id)
        self._seq = 0
        self._lock = asyncio.Lock()

    async def acquire_slot(self, agent_id: str, task_id: str, priority: int = 2) -> bool:
        """
        Versucht einen Ausführungs-Slot zu belegen.
        Tasks mit höherer Priorität (z. B. P3) überholen Tasks mit P1/P2 in der Schlange.
        """
        cfg = get_concurrency_config()
        max_slots = max(1, int(cfg.get("max_concurrent_agents", 4)))
        timeout = float(cfg.get("queue_timeout_seconds", 60))

        start_time = asyncio.get_event_loop().time()
        
        async with self._lock:
            self._seq += 1
            # Negierte Priorität für Max-Heap-Verhalten (-3 kommt vor -1)
            heapq.heappush(self._wait_queue, (-int(priority), self._seq, task_id, agent_id))

        try:
            while True:
                async with self._lock:
                    if len(self._active_slots) < max_slots:
                        # Prüfe ob dieser Task an der Spitze der Schlange steht
                        if self._wait_queue and self._wait_queue[0][2] == task_id:
                            heapq.heappop(self._wait_queue)
                            self._active_slots[task_id] = {
                                "agent_id": agent_id,
                                "priority": priority,
                                "started_at": asyncio.get_event_loop().time()
                            }
                            return True

                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    # Timeout: aus Schlange entfernen
                    async with self._lock:
                        self._wait_queue = [item for item in self._wait_queue if item[2] != task_id]
                        heapq.heapify(self._wait_queue)
                    return False
                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            async with self._lock:
                self._wait_queue = [item for item in self._wait_queue if item[2] != task_id]
                heapq.heapify(self._wait_queue)
            raise

    async def release_slot(self, task_id: str):
        """Gibt den Slot nach Ausführung frei."""
        async with self._lock:
            if task_id in self._active_slots:
                del self._active_slots[task_id]

    def get_status(self) -> Dict[str, Any]:
        cfg = get_concurrency_config()
        max_slots = int(cfg.get("max_concurrent_agents", 4))
        active_count = len(self._active_slots)
        queued_count = len(self._wait_queue)
        
        queue_preview = []
        for neg_p, seq, t_id, a_id in sorted(self._wait_queue):
            queue_preview.append({"task_id": t_id, "agent_id": a_id, "priority": -neg_p})

        return {
            "active_agents": active_count,
            "max_concurrent_agents": max_slots,
            "available_slots": max(0, max_slots - active_count),
            "queued_tasks_count": queued_count,
            "queued_tasks": queue_preview[:5],
            "running_tasks": list(self._active_slots.keys()),
            "utilization_percent": round((active_count / max_slots) * 100, 1) if max_slots > 0 else 0
        }

concurrency_throttle = PriorityConcurrencyThrottle()
