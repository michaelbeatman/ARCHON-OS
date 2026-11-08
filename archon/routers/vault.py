"""
Obsidian Vault Router fuer Archon OS.
Verwaltet /api/vault/ Endpunkte (Dateiliste, Lesen, Bearbeiten, Loeschen, Index).
Extrahiert aus main.py zur Modularisierung.
"""

import os
import sys
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body, Request
from archon.routers._rbac import require_admin_or_503
from archon.core.runtime import logger, OBSIDIAN_VAULT_DIR
from utils.path_jail import safe_path, safe_path_within, PathJailError

router = APIRouter(tags=["vault"])

_VAULT_FILES_CACHE: Dict[str, Any] = {"ts": 0.0, "data": []}


def _get_vault_dir() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "OBSIDIAN_VAULT_DIR"):
        return getattr(main_mod, "OBSIDIAN_VAULT_DIR")
    return OBSIDIAN_VAULT_DIR


def _get_vault_cache() -> Dict[str, Any]:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_VAULT_FILES_CACHE"):
        return getattr(main_mod, "_VAULT_FILES_CACHE")
    return _VAULT_FILES_CACHE


@router.get("/api/vault/files")
def api_get_vault_files():
    cache = _get_vault_cache()
    now = time.time()
    if cache.get("data") and (now - cache.get("ts", 0.0)) < 300.0:
        return cache["data"]
    vault_dir = _get_vault_dir()
    if not os.path.exists(vault_dir):
        return []
    files = []
    for root, dirs, filenames in os.walk(vault_dir):
        # Ignore internal Obsidian / Git folders
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in filenames:
            if f.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, f), vault_dir)
                files.append({"name": f, "relative_path": rel_path, "path": os.path.join(root, f)})
    cache["ts"] = now
    cache["data"] = files
    return files


@router.get("/api/vault")
def api_get_vault_list():
    files = api_get_vault_files()
    result = []
    for item in files:
        result.append({
            "name": item.get("name"),
            "path": item.get("path"),
            "relative_path": item.get("relative_path"),
            "type": "Obsidian MD"
        })
    return result


@router.get("/api/vault/file")
def api_read_vault_file_direct(path: str = Query(...)):
    vault_dir = _get_vault_dir()
    try:
        real_path = safe_path_within(
            path, [vault_dir], must_exist=True, allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    with open(real_path, "r", encoding="utf-8", errors="replace") as f:
        return {"status": "success", "path": real_path, "content": f.read()}


@router.post("/api/vault/edit")
def api_edit_vault_file_direct(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)
    path = payload.get("path", "")
    content = payload.get("content", "")
    if not path:
        raise HTTPException(status_code=400, detail="Pfad fehlt.")
    vault_dir = _get_vault_dir()
    try:
        real_path = safe_path_within(
            path, [vault_dir], allow_write=True, allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=str(e))
    os.makedirs(os.path.dirname(real_path), exist_ok=True)
    with open(real_path, "w", encoding="utf-8") as f:
        f.write(content)
    cache = _get_vault_cache()
    cache["ts"] = 0.0
    return {"status": "success", "path": real_path}


@router.delete("/api/vault")
def api_delete_vault_file_direct(request: Request, path: str = Query(...)):
    require_admin_or_503(request)
    vault_dir = _get_vault_dir()
    try:
        real_path = safe_path(path, must_exist=True, allow_write=True, allow_dirs=False,
                              extra_roots=[vault_dir])
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=str(e))
    vault_root = os.path.realpath(os.path.abspath(os.path.expanduser(vault_dir)))
    if real_path != vault_root and not real_path.startswith(vault_root + os.sep):
        raise HTTPException(
            status_code=403,
            detail="Loeschen nur innerhalb der Vault-Wurzel erlaubt.",
        )
    if not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    os.remove(real_path)
    cache = _get_vault_cache()
    cache["ts"] = 0.0
    return {"status": "success", "deleted": real_path}


@router.post("/api/vault/generate-index")
def api_generate_vault_index():
    from backend.vault_hygiene import generate_vault_index_and_hygiene
    return generate_vault_index_and_hygiene()
