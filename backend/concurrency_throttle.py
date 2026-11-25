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
import time
import asyncio
import heapq
import threading
from types import MappingProxyType
from typing import Dict, Any, Optional, List, Mapping

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

# W5: settings.json wurde pro wartendem Agenten (~1/s) neu gelesen und
# geparst. Kurzer TTL-Cache, Invalidierung beim Speichern.
# F-059: Ein EINZIGER unveraenderlicher Wert; die Referenz-Zuweisung ist
# atomar. Double-Check unter Lock macht den TTL-Rebuild single-flight, damit
# Event-Loop und FastAPI-Threadpool sich nicht gegenseitig ueberschreiben.
_CONFIG_CACHE_LOCK = threading.Lock()
# Der Cache ist ein unveraenderliches (ts, cfg)-Paar; die Werte haben
# unterschiedliche Typen, daher Mapping[str, Any] statt des inferierten
# MappingProxyType[str, float | None].
_CONFIG_CACHE: Mapping[str, Any] = MappingProxyType({"ts": 0.0, "cfg": None})
_CONFIG_TTL = 5.0


def get_concurrency_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    now = time.time()
    cached = _CONFIG_CACHE
    cfg = cached["cfg"]
    if cfg is not None and (now - cached["ts"]) < _CONFIG_TTL:
        return dict(cfg)

    with _CONFIG_CACHE_LOCK:
        cached = _CONFIG_CACHE
        now = time.time()
        cfg = cached["cfg"]
        if cfg is not None and (now - cached["ts"]) < _CONFIG_TTL:
            return dict(cfg)
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
        _CONFIG_CACHE = MappingProxyType({"ts": now, "cfg": dict(cfg)})
        return cfg

def save_concurrency_config(new_cfg: Dict[str, Any]) -> bool:
    global _CONFIG_CACHE
    try:
        from backend.settings_json import atomic_update_settings

        def _apply(current):
            current["concurrency"] = new_cfg

        atomic_update_settings(SETTINGS_FILE, _apply)
        # W5: Cache invalidieren — ebenfalls atomar und unter demselben Lock,
        # damit ein parallel laufender Rebuild die Invalidierung nicht verliert.
        with _CONFIG_CACHE_LOCK:
            _CONFIG_CACHE = MappingProxyType({"ts": 0.0, "cfg": None})
        return True
    except Exception as e:
        print(f"[ConcurrencyThrottle] Config save error: {e}", file=sys.stderr)
        return False

# W5: psutil.cpu_percent/virtual_memory/disk_usage wurde pro wartendem
# Agenten jede Sekunde neu gemessen (12+ Messungen/s bei 6 Wartenden).
# F-059: gleicher Single-Flight-Double-Check wie beim Config-Cache: genau ein
# Thread misst die Host-Metriken, alle anderen lesen danach den fertigen Wert.
_BP_CACHE_LOCK = threading.Lock()
# Analog zum Config-Cache: ts ist float, data ein Dict — gemischte Wertetypen.
_BP_CACHE: Mapping[str, Any] = MappingProxyType({"ts": 0.0, "data": {}})
_BP_TTL = 2.0


def _cached_backpressure() -> Dict[str, Any]:
    global _BP_CACHE
    now = time.time()
    cached = _BP_CACHE
    data = cached["data"]
    if data and (now - cached["ts"]) < _BP_TTL:
        return data

    with _BP_CACHE_LOCK:
        cached = _BP_CACHE
        now = time.time()
        data = cached["data"]
        if data and (now - cached["ts"]) < _BP_TTL:
            return data
        from backend.resource_backpressure import resource_backpressure_protector
        data = resource_backpressure_protector.check_health_and_backpressure()
        if not isinstance(data, dict):
            data = {}
        # Atomare Zuweisung des kompletten (ts, data)-Paares als Immutable-Dict.
        _BP_CACHE = MappingProxyType({"ts": now, "data": dict(data)})
        return _BP_CACHE["data"]


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
        cfg = await asyncio.to_thread(get_concurrency_config)
        max_slots = max(1, int(cfg.get("max_concurrent_agents", 4)))
        timeout = float(cfg.get("queue_timeout_seconds", 60))
        # Backpressure ist jetzt ein Consumer, kein Dashboard: bei
        # CPU/RAM/Disk-Ueberlast werden die verfuegbaren Slots reduziert,
        # statt weiterhin alle Agenten laufen zu lassen.
        # KRITISCH: _read_host_metrics() enthaelt psutil.cpu_percent(0.05) und
        # shutil.disk_usage() — synchron im Event-Loop wuerden N Waiter den
        # Loop mit N x 50 ms blockieren. Deshalb immer in den Threadpool.
        try:
            bp = await asyncio.to_thread(_cached_backpressure)
            if bp.get("backpressure_active"):
                max_slots = max(1, max_slots // 2)
        except Exception as bp_init_exc:
            # W3: auch beim Initial-Check fail-safe (konservativ drosseln).
            _archon_exc_logger.warning(
                "[ConcurrencyThrottle] Initialer Backpressure-Check fehlgeschlagen: %s", bp_init_exc
            )
            max_slots = 1

        loop = asyncio.get_running_loop()
        start_time = loop.time()
        # B) Der globale Scheduling-Lock darf KEINE await-Hops (Threadpool-
        # Roundtrips) umspannen: sonst blockiert jeder Waiter release_slot().
        # Config/Backpressure werden VOR dem Lock gelesen; im Lock stehen nur
        # noch Heap-/Registry-Mutationen und cond.wait().
        registered = False
        slot_key = f"{task_id}#pending"
        try:
            while True:
                # Prune ggf. verwaiste Slots bei Laufzeit-Konfig-Aenderung
                cfg_now = await asyncio.to_thread(get_concurrency_config)
                max_slots = max(1, int(cfg_now.get("max_concurrent_agents", max_slots)))
                try:
                    bp_now = await asyncio.to_thread(_cached_backpressure)
                    if bp_now.get("backpressure_active"):
                        max_slots = max(1, max_slots // 2)
                except Exception as bp_exc:
                    # W3: „Schutz schützt sich nicht selbst" — wenn die
                    # Backpressure-Erkennung ausfällt, konservativ
                    # drosseln statt ungebremst weiterzulaufen (OOM-Risiko).
                    _archon_exc_logger.warning(
                        "[ConcurrencyThrottle] Backpressure-Check fehlgeschlagen "
                        "— konservativ auf 1 Slot drosseln: %s", bp_exc
                    )
                    max_slots = 1

                async with self._cond:
                    if not registered:
                        self._seq += 1
                        seq = self._seq
                        slot_key = task_id if (task_id not in self._active_slots and all(x[2] != task_id for x in self._wait_queue)) else f"{task_id}#{seq}"
                        heapq.heappush(self._wait_queue, (-int(priority), seq, slot_key, task_id, agent_id))
                        registered = True

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
                        pass  # naechster Durchlauf liest Config/Backpressure neu
        except asyncio.CancelledError:
            if registered:
                async with self._cond:
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
