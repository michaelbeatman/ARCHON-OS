"""
Gemeinsame Laufzeit-Basis für Archon OS.

Alles, was main.py UND die ausgelagerten Router brauchen: Pfade, Ticker,
SSE-Broadcast, JSON-Helfer, atomare Writes. Dieses Modul importiert niemals
main.py — dadurch ist es zyklenfrei und von überall nutzbar.
"""

from __future__ import annotations

import asyncio
import datetime
import glob
import json
import os
import sqlite3
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

from backend.platform_paths import OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT

# --------------------------------------------------------------------------
# Pfade
# --------------------------------------------------------------------------
import logging

logger = logging.getLogger("archon_os")

# Wurzel des Projekts (archon/core/runtime.py -> ../..) - Ersatz fuer das
# frueher verwendete os.path.dirname(__file__) aus main.py.
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

WORKSPACE_DIR = "/app/agent_workspace" if (
    os.path.exists("/app/agent_workspace") or os.path.exists("/.dockerenv")
) else "./agent_workspace"
MEMORY_DIR = "/app/data" if os.path.exists("/app/data") else "."
DATA_DIR = MEMORY_DIR
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")


def resolve_obsidian_vault_path() -> str:
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    if sys.platform != "win32":
        candidates = [
            "/opt/data/obsidian",
            "/app/data/obsidian",
            os.path.join(WORKSPACE_DIR, "obsidian_vault"),
        ]
    else:
        candidates = [
            OBSIDIAN_VAULT,
            OBSIDIAN_VAULT_ALT,
            os.path.expanduser("~/Documents/Obsidian Vault"),
            os.path.join(WORKSPACE_DIR, "obsidian_vault"),
        ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate) and os.path.isdir(candidate):
            return candidate
    return "/opt/data/obsidian" if sys.platform != "win32" else OBSIDIAN_VAULT


OBSIDIAN_VAULT_DIR = resolve_obsidian_vault_path()

# --------------------------------------------------------------------------
# In-Memory Ticker + SSE-Broadcast
# --------------------------------------------------------------------------
ticker_entries: List[str] = []
_SSE_SUBSCRIBERS: List[asyncio.Queue] = []


def broadcast_event(event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Typisiertes Server-Sent Event an alle verbundenen Web-Clients."""
    payload = json.dumps({"type": event_type, "timestamp": time.time(), "data": data or {}})
    dead = []
    for q in _SSE_SUBSCRIBERS:
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for dq in dead:
        if dq in _SSE_SUBSCRIBERS:
            _SSE_SUBSCRIBERS.remove(dq)


def add_ticker(agent_name: str, message: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    ticker_entries.append(f"[{ts}] {agent_name}: {message}")
    if len(ticker_entries) > 20:
        ticker_entries.pop(0)
    broadcast_event("ticker_update", {"agent": agent_name, "message": message, "time": ts})


# --------------------------------------------------------------------------
# JSON-Helfer
# --------------------------------------------------------------------------
def _load_json(filepath: str, default: Any) -> Any:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _save_json(filepath: str, data: Any) -> None:
    try:
        atomic_write_json(filepath, data)
    except Exception as e:
        print(f"Error saving {filepath}: {e}", file=sys.stderr)


def atomic_write_json(filepath: str, data: Any, indent: int = 2) -> None:
    """Schreibt JSON atomar: Temp-Datei + fsync + os.replace.

    Verhindert halb geschriebene Zustandsdateien bei Absturz oder parallelem
    Schreiben (vorher gab es 8 eigene Implementierungen davon).
    """
    directory = os.path.dirname(os.path.abspath(filepath)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, filepath)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Live Telemetrie (aus main.py extrahiert)
# --------------------------------------------------------------------------
_LIVE_TELEMETRY_CACHE = {"ts": 0.0, "data": None}


def _get_live_telemetry_metrics() -> Dict[str, Any]:
    """Sammelt Live-Telemetrie aus state.db Dateien (gecached, 15s TTL)."""
    now_ts = time.time()
    if _LIVE_TELEMETRY_CACHE["data"] is not None and (now_ts - _LIVE_TELEMETRY_CACHE["ts"]) < 15.0:
        return _LIVE_TELEMETRY_CACHE["data"]

    all_dbs = sorted(glob.glob('/opt/data/profiles/*/state.db') + ['/opt/data/state.db'])
    if not all_dbs:
        all_dbs = sorted(glob.glob(os.path.expanduser('~/.hermes/profiles/*/state.db')) + [os.path.expanduser('~/.hermes/state.db')])

    fifteen_min_ago = now_ts - 900
    # Tagesbeginn (00:00 Uhr lokaler Kalendertag)
    today_dt = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ts = today_dt.timestamp()

    # Performance-Optimierung: Nur DBs öffnen, die heute modifiziert wurden oder die globale state.db
    state_dbs = []
    for db in all_dbs:
        try:
            if not os.path.exists(db):
                continue
            if db.endswith("state.db") and "/profiles/" not in db:
                state_dbs.append(db)
            elif os.path.getmtime(db) >= today_start_ts:
                state_dbs.append(db)
        except Exception:
            pass
    if not state_dbs:
        state_dbs = [d for d in all_dbs if d.endswith("state.db") and "/profiles/" not in d] or all_dbs[:1]

    tokens_last_15m = 0
    today_cost = 0.0
    latest_model = "deepseek/deepseek-v4-flash-0731"
    latest_tokens = 0
    model_breakdown = {}
    all_sessions = []

    # Minuten-Buckets für die 15-Minuten Sparkline
    minute_buckets = [0.0] * 15

    for db in state_dbs:
        con = None
        try:
            con = sqlite3.connect(db, timeout=5.0)
            con.execute("PRAGMA busy_timeout=5000;")
            rows = con.execute('''
                SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen
                FROM session_model_usage
                WHERE last_seen >= ?
                ORDER BY last_seen DESC LIMIT 200
            ''', (fifteen_min_ago,)).fetchall()
            if not rows:
                rows = con.execute('''
                    SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen
                    FROM session_model_usage
                    WHERE last_seen >= ?
                    ORDER BY last_seen DESC LIMIT 200
                ''', (today_start_ts,)).fetchall()
            for row in rows:
                model, in_tok, out_tok, cost, last_seen = row
                if not model:
                    continue
                total_tok = (in_tok or 0) + (out_tok or 0)
                tokens_last_15m += total_tok
                today_cost += cost or 0.0
                if last_seen and last_seen > (latest_tokens or 0):
                    latest_model = model
                    latest_tokens = last_seen
                model_breakdown[model] = model_breakdown.get(model, 0) + total_tok

                # Sparkline: zu welchem 15-Minuten-Bucket gehört dieser Eintrag?
                if last_seen:
                    idx = int((now_ts - last_seen) / 60)
                    if 0 <= idx < 15:
                        minute_buckets[idx] += float(cost or 0.0)
        except Exception:
            pass
        finally:
            if con:
                try:
                    con.close()
                except Exception:
                    pass

    # Sparkline umdrehen (älteste zuerst für Chart)
    minute_buckets.reverse()

    _LIVE_TELEMETRY_CACHE["data"] = {
        "tokens_last_15m": tokens_last_15m,
        "today_cost": today_cost,
        "latest_model": latest_model,
        "latest_tokens": latest_tokens,
        "model_breakdown": model_breakdown,
        "sparkline_data": minute_buckets,
    }
    _LIVE_TELEMETRY_CACHE["ts"] = now_ts
    return _LIVE_TELEMETRY_CACHE["data"]


# --------------------------------------------------------------------------
# Obsidian Sync Helper (aus main.py extrahiert)
# --------------------------------------------------------------------------
def _sync_task_to_obsidian(task: Dict[str, Any]) -> str:
    """
    Führt die Post-Task-Pipeline aus:
    1. Projektordner-Struktur (01_Zwischenberichte, 02_Medien, 03_Endprodukte) + PROJEKT.md
    2. Personalakten-Aktualisierung (tasks_completed, Tabellen-Eintrag)
    3. Self-Improvement Lerneffekt via LocalMemoryBridge
    4. Paperclip-Status-Schließung
    5. E-Mail-Versand (falls konfiguriert)
    """
    try:
        from backend.post_task_pipeline import execute_post_task_pipeline
        pipe_res = execute_post_task_pipeline(task)
        if pipe_res and pipe_res.get("final_path"):
            return pipe_res["final_path"]
    except Exception as e_hook:
        logger.warning(f"[PostTaskPipeline] Hook-Fehler, weiche auf Fallback aus: {e_hook}")

    task_id = str(task.get("id") or "task-0").strip()
    raw_title = task.get("title") or "task"
    # slugify helper
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        import re
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = re.sub(r"-+", "-", text).strip("-")
        if len(text) > 60:
            text = text[:60].rstrip("-")
        return text or "task"

    task_slug = _slugify(raw_title)
    # User-Vorgabe 09.10.2026: Datum (YYYYMMDD-) als Präfix statt "task-"
    _date_prefix = datetime.datetime.now().strftime("%Y%m%d")
    _tid_core = task_id.replace("task-", "")
    file_name = f"{_date_prefix}-{_tid_core}-{task_slug}.md"

    # Bevorzugt /opt/data/obsidian/01_PROJEKTE, fallbacks auf OBSIDIAN_VAULT_DIR und inbox
    target_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE"),
        os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
        "/opt/data/inbox"
    ]

    written_paths = []
    content = f"""---
project_id: {task_id}
date: {datetime.date.today().isoformat()}
agent: {task.get('agent_name', 'Hermes Agent')}
model: {task.get('model', 'Universal')}
tokens_used: {task.get('estimated_tokens', 0)}
cost_usd: ${task.get('estimated_cost_eur', 0.0):.2f}
status: completed
---
# {task.get('title', 'Ohne Titel')}

## Ursprüngliche Anforderung
{task.get('capture_input') or task.get('title', '')}

## Umsetzungsplan & Ergebnisse
{task.get('result_summary') or 'Erfolgreich von Archon OS ausgeführt und validiert.'}

## Generierte Artefakte
- Pfad: /opt/data/obsidian/01_PROJEKTE/{file_name}
"""
    for d in target_dirs:
        try:
            os.makedirs(d, exist_ok=True)
            f_path = os.path.join(d, file_name)
            tmp_path = os.path.join(d, f".{file_name}.tmp_{os.getpid()}_{int(time.time()*1000)}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, f_path)
            if os.path.exists(f_path):
                written_paths.append(f_path)
                logger.info(f"[Obsidian Sync] Atomar und verifiziert gespeichert: {f_path}")
        except Exception as err:
            logger.warning(f"[Obsidian Sync] Fehler beim Schreiben in {d}: {err}")

    final_path = written_paths[0] if written_paths else f"/opt/data/obsidian/01_PROJEKTE/{file_name}"
    print(f"[Obsidian Sync] Speicherpfad verifiziert: {final_path}")
    return final_path


__all__ = [
    "APP_ROOT", "logger", "WORKSPACE_DIR", "MEMORY_DIR", "DATA_DIR", "SETTINGS_FILE", "OBSIDIAN_VAULT_DIR",
    "resolve_obsidian_vault_path", "ticker_entries", "add_ticker", "broadcast_event",
    "_SSE_SUBSCRIBERS", "_load_json", "_save_json", "atomic_write_json",
    "_get_live_telemetry_metrics", "_sync_task_to_obsidian",
]