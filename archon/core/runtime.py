"""
Gemeinsame Laufzeit-Basis für Archon OS.

Alles, was main.py UND die ausgelagerten Router brauchen: Pfade, Ticker,
SSE-Broadcast, JSON-Helfer, atomare Writes. Dieses Modul importiert niemals
main.py — dadurch ist es zyklenfrei und von überall nutzbar.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

from backend.platform_paths import OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT

# --------------------------------------------------------------------------
# Pfade
# --------------------------------------------------------------------------
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


__all__ = [
    "WORKSPACE_DIR", "MEMORY_DIR", "DATA_DIR", "SETTINGS_FILE", "OBSIDIAN_VAULT_DIR",
    "resolve_obsidian_vault_path", "ticker_entries", "add_ticker", "broadcast_event",
    "_SSE_SUBSCRIBERS", "_load_json", "_save_json", "atomic_write_json",
]