"""Router /api/swarm — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile

from archon.routers._rbac import require_admin_or_503
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

router = APIRouter()

@router.post("/api/swarm/spawn-ephemeral-team")
def api_spawn_ephemeral_team(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.ephemeral_team_spawner import ephemeral_team_spawner
    return ephemeral_team_spawner.spawn_task_force(
        mission_title=payload.get("mission_title", "Spezial-Auftrag"),
        mission_brief=payload.get("mission_brief", "")
    )
