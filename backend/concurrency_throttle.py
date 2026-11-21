"""
backend/concurrency_throttle.py
Konfigurierbare Concurrency-Drosselung mit Prioritäts-Preemption Scheduler (Pillar 1).
Ordnet wartende Aufgaben nach Prioritätsstufen:
- P3 (Dringend / Direkter Chat): Höchste Priorität, rückt an Slot-Spitze vor
- P2 (Normal / Geplante Aufgaben): Standard-Abarbeitung
- P1 (Routine / Hintergrund-Recherche): Nachrangig
Die Obergrenze max_concurrent_agents ist zur Laufzeit frei skalierbar.
"""
import logging
_archon_exc_logger = logging.getLogger("concurrency_throttle")

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
        except Exception as _exc:
            _archon_exc_logger.debug("[concurrency_throttle] Ignorierte Ausnahme (Z.32): %s", _exc)
    return cfg

def save_concurrency_config(new_cfg: Dict[str, Any]) -> bool:
    try:
        from backend.settings_json import atomic_update_settings

        def _apply(current):
            current["concurrency"] = new_cfg

        atomic_update_settings(SETTINGS_FILE, _apply)
        return True
    except Exception as e:
        print(f"[ConcurrencyThrottle] Config save error: {e}", file=sys.stderr)
        return False

class PriorityConcurrencyThrottle:
    def __init__(self):
        self._active_slots = {}
        self._wait_queue = []  # Heap von (-priority, seq, slot_key, task_id, agent_id)
        self._seq = 0
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)

    async def acquire_slot(self, agent_id: str, task_id: str, priority: int = 2) -> bool:
        """
        Versucht einen Ausführungs-Slot zu belegen.
        Tasks mit höherer Priorität (z. B. P3) überholen Tasks mit P1/P2 in der Schlange.
        """
        cfg = get_concurrency_config()
        max_slots = max(1, int(cfg.get("max_concurrent_agents", 4)))
        timeout = float(cfg.get("queue_timeout_seconds", 60))

        loop = asyncio.get_running_loop()
        start_time = loop.time()

        async with self._cond:
            self._seq += 1
            seq = self._seq
            slot_key = task_id if (task_id not in self._active_slots and all(x[2] != task_id for x in self._wait_queue)) else f"{task_id}#{seq}"
            heapq.heappush(self._wait_queue, (-int(priority), seq, slot_key, task_id, agent_id))

            try:
                while True:
                    # Prune ggf. verwaiste Slots bei Laufzeit-Konfig-Aenderung
                    cfg_now = get_concurrency_config()
                    max_slots = max(1, int(cfg_now.get("max_concurrent_agents", max_slots)))
                    if len(self._active_slots) < max_slots and self._wait_queue and self._wait_queue[0][2] == slot_key:
                        heapq.heappop(self._wait_queue)
                        self._active_slots[slot_key] = {
                            "task_id": task_id,
                            "agent_id": agent_id,
                            "priority": priority,
                            "started_at": loop.time(),
                        }
                        return True

                    remaining = timeout - (loop.time() - start_time)
                    if remaining <= 0:
                        self._wait_queue = [item for item in self._wait_queue if item[2] != slot_key]
                        heapq.heapify(self._wait_queue)
                        return False
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=min(remaining, 1.0))
                    except asyncio.TimeoutError:
                        continue
            except asyncio.CancelledError:
                self._wait_queue = [item for item in self._wait_queue if item[2] != slot_key]
                heapq.heapify(self._wait_queue)
                raise

    async def release_slot(self, task_id: str):
        """Gibt den Slot nach Ausführung frei und weckt wartende Tasks sofort."""
        async with self._cond:
            if task_id in self._active_slots:
                del self._active_slots[task_id]
            else:
                for key, info in list(self._active_slots.items()):
                    if info.get("task_id") == task_id:
                        del self._active_slots[key]
                        break
            self._cond.notify_all()

    def get_status(self) -> Dict[str, Any]:
        cfg = get_concurrency_config()
        max_slots = int(cfg.get("max_concurrent_agents", 4))
        active_count = len(self._active_slots)
        queued_count = len(self._wait_queue)
        
        queue_preview = []
        for neg_p, _seq, _slot_key, t_id, a_id in sorted(self._wait_queue):
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
