"""Mission-Control-Store (atomare, nebenlaeufigkeitssichere Persistenz).

Aus main.py ausgelagert: die Datei hat viele Schreiber (Move-Handler, Watcher,
Cascade). _write_mc_atomic schreibt ueber Temp-Datei + fsync + os.replace,
damit nie Halbstaende entstehen. Der Thread-Lock serialisiert die Writer, der
Async-Lock schuetzt Read-Modify-Write-Sequenzen im Event-Loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
from typing import Any, Dict

from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import MEMORY_DIR

MISSION_CONTROL_FILE = os.path.join(MEMORY_DIR, "mission_control_data.json")

# EIN Lock fuer alle Schreiber. Vorher schuetzten zwei Locks dieselbe Datei:
# _MC_DATA_LOCK (threading) in _save_mission_control_data und _MC_ASYNC_LOCK
# (asyncio) in orchestration._fan_in_maybe_start_synthesis. Zwei Locks auf ein
# Ziel serialisieren nichts — ein Schreiber aus dem Event-Loop konnte sich mit
# einem aus einem Worker-Thread verzahnen (Audit B1).
# RLock statt Lock, weil _save_mission_control_data den Lock haelt und
# _write_mc_atomic ihn ebenfalls nimmt (verschachtelt); ein einfacher Lock
# wuerde sich dort selbst blockieren.
_MC_DATA_LOCK = threading.RLock()

# Nur noch fuer Abwaertskompatibilitaet exportiert; die Korrektheit haengt
# nicht mehr an diesem Lock, weil _write_mc_atomic selbsteinspannend ist.
_MC_ASYNC_LOCK = asyncio.Lock()

# State-Cache für /api/mission-control/state (3s TTL)
_MC_STATE_CACHE = {"ts": 0.0, "data": None}


def _write_mc_atomic(data: dict):
    """Atomarer MC-Store-Write (Temp-Datei + fsync + os.replace).

    Nimmt den Lock selbst (RLock, daher auch verschachtelt aufrufbar). Damit
    ist die Zusicherung "nur mit gehaltenem Lock aufrufen" nicht mehr noetig —
    ein Aufruf ohne Lock kann die Serialisierung nicht mehr umgehen.

    Achtung: enthaelt fsync und blockiert. Aus async-Handlern deshalb ueber
    asyncio.to_thread aufrufen, nicht direkt.
    """
    with _MC_DATA_LOCK:
        _dir = os.path.dirname(os.path.abspath(MISSION_CONTROL_FILE)) or "."
        os.makedirs(_dir, exist_ok=True)
        _fd, _tmp = tempfile.mkstemp(dir=_dir, prefix=".mission_control_", suffix=".tmp")
        try:
            with os.fdopen(_fd, "w", encoding="utf-8") as _f:
                json.dump(data, _f, indent=2, ensure_ascii=False)
                _f.flush()
                os.fsync(_f.fileno())
            os.replace(_tmp, MISSION_CONTROL_FILE)
        except BaseException:
            try:
                os.unlink(_tmp)
            except OSError:
                pass
            raise


def _load_mission_control_data() -> dict:
    if os.path.exists(MISSION_CONTROL_FILE):
        try:
            with open(MISSION_CONTROL_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                # F-04: Ein Store mit tasks-Liste (auch LEER nach Archivierung)
                # ist autoritativ — vorher belebte ein bewusst leeres Board alte
                # SQLite-Tasks wieder.
                if isinstance(d, dict) and isinstance(d.get("tasks"), list):
                    return d
        except Exception as e:
            print(f"Error loading mission_control_data: {e}")

    # Echte Tasks aus SQLite laden
    real_tasks = []

    # SQLite Tasks als Ergänzung
    if not real_tasks:
        try:
            import sqlite3
            for db in [os.path.join(OPT_DATA_DIR, "agentic_memory.db"), "./data/agentic_memory.db"]:
                if os.path.exists(db):
                    conn = sqlite3.connect(db, timeout=5.0)
                    conn.execute("PRAGMA busy_timeout=5000;")
                    try:
                        cur = conn.cursor()
                        cur_rows = cur.execute("SELECT id, title, role, status, created_at FROM tasks ORDER BY created_at DESC LIMIT 20").fetchall()
                    finally:
                        conn.close()
                    for row in cur_rows:
                        t_id, t_title, t_role, t_status, t_created = row
                        status_raw = (t_status or "").lower()
                        if status_raw in ["waiting_approval", "approval", "gate"]:
                            col_status = "approval"
                        elif status_raw in ["in_progress", "running"]:
                            col_status = "in_progress"
                        elif status_raw in ["completed", "done", "finished"]:
                            col_status = "completed"
                        else:
                            col_status = "backlog"

                        real_tasks.append({
                            "id": t_id,
                            "title": t_title or t_id,
                            "plan": ["Autonomer Task aus dem System"],
                            "agent_id": t_role or "system",
                            "agent_name": t_role or "System Agent",
                            "model": "omniroute/best-free",
                            "estimated_tokens": 15000,
                            "estimated_cost_eur": 0.0,
                            "subagents_count": 1,
                            "status": col_status,
                            "created_at": str(t_created)[:16],
                            "result_summary": "",
                            "artifact_path": ""
                        })
                    conn.close()
                    if real_tasks:
                        break
        except Exception:
            pass

    archive_file = os.path.join(MEMORY_DIR, "archived_tasks.json")
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r") as f:
                archived = set(json.load(f))
            real_tasks = [t for t in real_tasks if t["id"] not in archived]
        except Exception:
            pass

    # Z-08: Der Fallback-Store darf KEINE erfundene Telemetrie liefern. Vorher
    # stand hier tpm_current=184200 / tpm_limit=2000000 — die Kacheln zeigten
    # "184k TPM" als Messwert, obwohl nie gemessen wurde. Jetzt: 0-Werte plus
    # expliziter source-Hinweis, damit Clients den Fallback erkennen koennen.
    return {
        "tasks": real_tasks,
        "metrics": {
            "tpm_current": 0,
            "tpm_limit": 0,
            "cost_today_usd": 0.0,
            "cost_limit_usd": 0.0
        },
        "audit_logs": [],
        "source": "fallback_no_store"
    }

def _save_mission_control_data(data: dict):
    """Schreibt den Store. Serialisiert gegen alle anderen Schreiber.

    Achtung: Das ist ein *Write*, kein Read-Modify-Write. Wer laden, aendern
    und zurueckschreiben will, muss update_mission_control_data() benutzen —
    sonst gehen parallele Aenderungen verloren (Lost Update).
    """
    try:
        _write_mc_atomic(data)
    except Exception as e:
        from archon.core.runtime import logger
        logger.error(f"[MissionControl] Speichern fehlgeschlagen: {e}", exc_info=True)


def update_mission_control_data(mutator):
    """Atomares Read-Modify-Write: Laden, Aendern und Schreiben unter EINEM Lock.

    `mutator` bekommt das geladene dict und gibt den Rueckgabewert der Operation
    zurueck. Der Lock wird ueber die gesamte Sequenz gehalten, damit parallele
    Schreiber sich nicht gegenseitig ueberschreiben (Lost Update, Audit B1).

    Blockiert (Datei-I/O + fsync). Aus async-Handlern so aufrufen:
        await asyncio.to_thread(update_mission_control_data, mutator)

    Beispiel:
        def _add(task):
            def mutate(data):
                data.setdefault("tasks", []).insert(0, task)
                return task
            return mutate
        task = await asyncio.to_thread(update_mission_control_data, _add(new_task))
    """
    with _MC_DATA_LOCK:
        data = _load_mission_control_data()
        result = mutator(data)
        _write_mc_atomic(data)
        return result


__all__ = [
    "MISSION_CONTROL_FILE", "_MC_DATA_LOCK", "_MC_ASYNC_LOCK",
    "_write_mc_atomic", "_load_mission_control_data", "_save_mission_control_data",
    "update_mission_control_data", "_MC_STATE_CACHE",
]
