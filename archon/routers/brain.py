"""
Brain & Archiv Router (3D Galaxy, Vault API, Library & Quartz Config)
für Archon OS. Ausgelagert aus main.py zur modularen Entschlackung.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Set

import yaml
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from archon.core.cache import ttl_cache
from archon.core.roles_data import DEFAULT_ROLES
from archon.core.runtime import (
    OBSIDIAN_VAULT_DIR,
    WORKSPACE_DIR,
    logger,
)
from archon.routers._rbac import require_admin_or_503
from backend.platform_paths import OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT
from utils.path_jail import PathJailError, safe_path

router = APIRouter(tags=["brain"])

_DEPS: Dict[str, Any] = {}


def require_admin(request: Request) -> None:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "require_admin"):
        fn = getattr(main_mod, "require_admin")
        if callable(fn):
            fn(request)
            return
    fn = _DEPS.get("require_admin") or require_admin_or_503
    fn(request)


def configure(
    _spawn_background: Optional[Callable[..., Any]] = None,
    _get_rag_api_key: Optional[Callable[..., str]] = None,
    _is_rag_sync_running: Optional[Callable[..., bool]] = None,
    _RAG_SYNC_LOCK: Optional[Any] = None,
    post_docker_container_action: Optional[Callable[..., Any]] = None,
    docker_socket_request: Optional[Callable[..., Any]] = None,
    **deps: Any,
) -> None:
    """Registriert dynamische Abhängigkeiten aus main.py."""
    if _spawn_background:
        _DEPS["_spawn_background"] = _spawn_background
    if _get_rag_api_key:
        _DEPS["_get_rag_api_key"] = _get_rag_api_key
    if _is_rag_sync_running:
        _DEPS["_is_rag_sync_running"] = _is_rag_sync_running
    if _RAG_SYNC_LOCK:
        _DEPS["_RAG_SYNC_LOCK"] = _RAG_SYNC_LOCK
    if post_docker_container_action:
        _DEPS["post_docker_container_action"] = post_docker_container_action
    if docker_socket_request:
        _DEPS["docker_socket_request"] = docker_socket_request
    _DEPS.update(deps)


def _delegate_spawn_background(coro: Any, name: str = "") -> Any:
    fn = _DEPS.get("_spawn_background")
    if not fn:
        main_mod = sys.modules.get("main")
        if main_mod and hasattr(main_mod, "_spawn_background"):
            fn = getattr(main_mod, "_spawn_background")
    if fn:
        return fn(coro, name=name)
    return asyncio.create_task(coro)


def _delegate_get_rag_api_key() -> str:
    fn = _DEPS.get("_get_rag_api_key")
    if not fn:
        main_mod = sys.modules.get("main")
        if main_mod and hasattr(main_mod, "_get_rag_api_key"):
            fn = getattr(main_mod, "_get_rag_api_key")
    if fn:
        return fn()
    key = (os.environ.get("ANYTHINGLLM_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ANYTHINGLLM_API_KEY fehlt in der Umgebung.")
    return key


def _delegate_is_rag_sync_running() -> bool:
    fn = _DEPS.get("_is_rag_sync_running")
    if not fn:
        main_mod = sys.modules.get("main")
        if main_mod and hasattr(main_mod, "_is_rag_sync_running"):
            fn = getattr(main_mod, "_is_rag_sync_running")
    if fn:
        return fn()
    return False


def _delegate_post_docker_container_action(container_name: str, action: str = "start", raise_on_error: bool = False) -> dict:
    fn = _DEPS.get("post_docker_container_action")
    if not fn:
        main_mod = sys.modules.get("main")
        if main_mod and hasattr(main_mod, "post_docker_container_action"):
            fn = getattr(main_mod, "post_docker_container_action")
    if fn:
        return fn(container_name, action=action, raise_on_error=raise_on_error)
    return {}


def _delegate_docker_socket_request(method: str, path: str, payload: Any = None) -> Any:
    fn = _DEPS.get("docker_socket_request")
    if not fn:
        try:
            from archon.routers.containers import docker_socket_request as d_req
            fn = d_req
        except Exception:
            main_mod = sys.modules.get("main")
            if main_mod and hasattr(main_mod, "docker_socket_request"):
                fn = getattr(main_mod, "docker_socket_request")
    if fn:
        return fn(method, path, payload=payload)
    return None


# ============================================================================
# BRAIN & ARCHIV (3D GALAXY & VAULT API)
# ============================================================================

@router.get("/api/v1/brain/galaxy-data")
@ttl_cache(seconds=60)
def api_brain_galaxy_data(vault_limit: int = Query(600, description="Max. Vault-Notizen (0 = alle)"),
                          include_vault: bool = Query(True)):
    nodes = []
    links = []
    node_ids = set()

    # 1. Central Core Node
    core_id = "core_archon_os"
    nodes.append({
        "id": core_id,
        "name": "⚡ Archon OS Kernel",
        "group": "core",
        "color": "#38bdf8",
        "val": 35,
        "description": "Zentraler OS-Kern & Event Loop Orchestrator",
        "details": {"type": "System Kernel", "status": "Online"}
    })
    node_ids.add(core_id)

    # 2. Agenten aus agent_profiles.json & roles.json
    agent_profiles = []
    for path in [os.path.join(WORKSPACE_DIR, "agent_profiles.json"), "agent_profiles.json"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    agent_profiles = json.load(f)
                break
            except Exception:
                pass
    
    if not agent_profiles:
        agent_profiles = DEFAULT_ROLES

    for a in agent_profiles:
        aid = f"agent_{a.get('id', a.get('name'))}"
        if aid not in node_ids:
            nodes.append({
                "id": aid,
                "name": f"🤖 {a.get('name', 'Agent')}",
                "group": "agent",
                "color": "#22c55e",
                "val": 22,
                "description": a.get("category", "Autonomer Agent"),
                "details": {
                    "role_id": a.get("id"),
                    "category": a.get("category", "General"),
                    "prompt": a.get("prompt", "")[:180] + "...",
                    "skills": a.get("skills", [])
                }
            })
            node_ids.add(aid)
            links.append({"source": core_id, "target": aid, "relationship": "orchestrates", "color": "rgba(56, 189, 248, 0.4)"})

            # Connect agent skills
            for s in a.get("skills", []):
                sid = f"skill_{s}"
                if sid not in node_ids:
                    nodes.append({
                        "id": sid,
                        "name": f"⚡ {s.replace('skill-', '').replace('_', ' ').title()}",
                        "group": "skill",
                        "color": "#a855f7",
                        "val": 14,
                        "description": "Fähigkeit / Execution Skill",
                        "details": {"skill_id": s}
                    })
                    node_ids.add(sid)
                links.append({"source": aid, "target": sid, "relationship": "executes", "color": "rgba(168, 85, 247, 0.5)"})

    # 3. Obsidian Vault Notizen & Personalakten
    vault_candidates = [
        OBSIDIAN_VAULT,
        OBSIDIAN_VAULT_ALT,
        "/opt/data/obsidian",
        OBSIDIAN_VAULT_DIR,
        os.path.join(WORKSPACE_DIR, "agent_workspace", "obsidian_vault"),
        "agent_workspace/obsidian_vault",
        "/app/agent_workspace/obsidian_vault"
    ]
    vault_dir = None
    for v in vault_candidates:
        if v and os.path.exists(v):
            vault_dir = v
            break

    if vault_dir:
        for root, dirs, files in os.walk(vault_dir):
            if ".obsidian" in root or ".git" in root or "node_modules" in root:
                continue
            for file in files:
                if file.endswith(".md"):
                    rel_path = os.path.relpath(os.path.join(root, file), vault_dir).replace("\\", "/")
                    note_id = f"note_{rel_path}"
                    clean_name = file.replace(".md", "").replace("_", " ").title()
                    is_personalakte = "Personalakten" in rel_path
                    
                    if note_id not in node_ids:
                        nodes.append({
                            "id": note_id,
                            "name": f"{'📋' if is_personalakte else '📄'} {clean_name}",
                            "group": "personalakte" if is_personalakte else "vault_note",
                            "color": "#eab308" if is_personalakte else "#06b6d4",
                            "val": 16 if is_personalakte else 10,
                            "description": rel_path,
                            "details": {
                                "rel_path": rel_path,
                                "type": "Personalakte" if is_personalakte else "Vault Dokument",
                                "filename": file
                            }
                        })
                        node_ids.add(note_id)

                        # Match with agent if Personalakte
                        matched_agent = False
                        if is_personalakte:
                            for a in agent_profiles:
                                aid = f"agent_{a.get('id', a.get('name'))}"
                                if a.get("id") and a.get("id").lower() in file.lower() or file.lower().replace(".md", "") in a.get("id", "").lower():
                                    if aid in node_ids:
                                        links.append({"source": aid, "target": note_id, "relationship": "documented_in", "color": "rgba(234, 179, 8, 0.6)"})
                                        matched_agent = True
                                        break
                        if not matched_agent:
                            links.append({"source": core_id, "target": note_id, "relationship": "stores", "color": "rgba(6, 182, 212, 0.3)"})

    # --- Payload-Begrenzung -------------------------------------------------
    if not include_vault:
        _drop = {n["id"] for n in nodes if n["group"] in ("vault_note", "personalakte")}
    elif vault_limit and vault_limit > 0:
        _notes = [n for n in nodes if n["group"] == "vault_note"]
        _pa = [n for n in nodes if n["group"] == "personalakte"]
        _keep_pa = set()
        _keep_notes = set()
        for n in _pa:
            _keep_pa.add(n["id"])
        for n in _notes[:max(0, vault_limit - len(_keep_pa))]:
            _keep_notes.add(n["id"])
        _drop = {n["id"] for n in _notes if n["id"] not in _keep_notes}
    else:
        _drop = set()

    if _drop:
        nodes = [n for n in nodes if n["id"] not in _drop]
        links = [l for l in links if l.get("source") not in _drop and l.get("target") not in _drop]

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "agents_count": len([n for n in nodes if n["group"] == "agent"]),
            "skills_count": len([n for n in nodes if n["group"] == "skill"]),
            "vault_notes_count": len([n for n in nodes if "note" in n["group"] or "personalakte" in n["group"]]),
            "vault_notes_truncated": len(_drop)
        }
    }


@router.get("/api/v1/brain/vault-file")
def api_brain_vault_file(path: str):
    vault_candidates = [
        OBSIDIAN_VAULT,
        OBSIDIAN_VAULT_ALT,
        "/opt/data/obsidian",
        OBSIDIAN_VAULT_DIR,
        os.path.join(WORKSPACE_DIR, "agent_workspace", "obsidian_vault"),
        "agent_workspace/obsidian_vault",
        "/app/agent_workspace/obsidian_vault"
    ]
    vault_dir = None
    for v in vault_candidates:
        if v and os.path.exists(v):
            vault_dir = os.path.abspath(v)
            break
            
    if not vault_dir:
        raise HTTPException(status_code=404, detail="Obsidian Vault Verzeichnis nicht gefunden.")

    clean_path = path.lstrip("/\\")
    candidate = os.path.join(vault_dir, clean_path)
    try:
        real_file = safe_path(candidate, must_exist=True, allow_dirs=False)
    except PathJailError as e:
        raise HTTPException(status_code=400, detail=f"Ungültiger Dateipfad: {e}")

    # Zusätzlich: muss innerhalb des gewählten Vault-Verzeichnisses liegen
    real_vault = os.path.realpath(vault_dir)
    if not (real_file == real_vault or real_file.startswith(real_vault + os.sep)):
        raise HTTPException(status_code=400, detail="Ungültiger Dateipfad.")

    try:
        with open(real_file, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "path": path,
            "filename": os.path.basename(real_file),
            "content": content,
            "size": len(content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# NOTEBOOK & DEEP DOCS / OCR LIBRARY PIPELINE
# ---------------------------------------------------------

@router.post("/api/v1/library/upload")
async def api_library_upload(request: Request):
    # RBAC: Datei-Schreiben in den Bibliotheksbaum ist Admin-Sache. Der Zaun
    # steht VOR jedem makedirs/open, damit ein 403 keinen Seiteneffekt hat.
    require_admin_or_503(request)
    try:
        from utils.batch_library_importer import resolve_raw_docs_dir, resolve_vault_path, process_document
        raw_dir = resolve_raw_docs_dir()
        vault_dir = resolve_vault_path()
        os.makedirs(raw_dir, exist_ok=True)
        
        form = await request.form()
        uploaded_files = form.getlist("files") or form.getlist("file")
        if not uploaded_files:
            single_file = form.get("file")
            if single_file:
                uploaded_files = [single_file]
                
        if not uploaded_files:
            raise HTTPException(status_code=400, detail="Keine Dateien übermittelt.")
            
        auto_ingest = form.get("auto_ingest", "true").lower() in ["true", "1", "yes"]
        category = form.get("category", "auto")
        
        results = []
        for file in uploaded_files:
            if hasattr(file, "filename") and file.filename:
                # Traversal-Härtung: nur der Basisname wird verwendet, danach
                # läuft der Zielpfad durch das Pfad-Jail mit `raw_dir` als
                # erlaubter Wurzel. Kein Schreiben ausserhalb von raw_dir.
                name = os.path.basename(str(file.filename).replace("\\", "/")).strip()
                if not name or name in (".", ".."):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Ungueltiger Dateiname: {file.filename!r}"
                    )
                try:
                    file_path = safe_path(
                        os.path.join(raw_dir, name),
                        must_exist=False, allow_write=True,
                        allow_dirs=False, extra_roots=[raw_dir],
                    )
                except PathJailError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Dateiname nicht erlaubt: {e}"
                    )
                content = await file.read()
                def _save_file(target_path: str, data: bytes) -> None:
                    with open(target_path, "wb") as f:
                        f.write(data)
                await asyncio.to_thread(_save_file, file_path, content)
                    
                item_info = {
                    "filename": name,
                    "size_bytes": len(content),
                    "saved_path": file_path
                }
                
                if auto_ingest:
                    try:
                        ingest_res = await asyncio.to_thread(process_document, file_path, vault_dir, target_category=category)
                        item_info["ingest"] = ingest_res
                    except Exception as err:
                        item_info["ingest"] = {"status": "error", "error": str(err)}
                        
                results.append(item_info)
            
        # Wenn auto_ingest aktiv war, im Hintergrund AnythingLLM RAG-Sync anstoßen
        if auto_ingest:
            async def trigger_background_rag_sync():
                rag_lock = _DEPS.get("_RAG_SYNC_LOCK")
                if not rag_lock:
                    main_mod = sys.modules.get("main")
                    rag_lock = getattr(main_mod, "_RAG_SYNC_LOCK", None)
                if not rag_lock:
                    rag_lock = asyncio.Lock()
                async with rag_lock:
                    if _delegate_is_rag_sync_running():
                        logger.info("[RAG-Sync] Vollsync laeuft bereits; ueberspringe redundanten Start.")
                        return
                    try:
                        import subprocess
                        sync_script = os.path.join(WORKSPACE_DIR, "tools", "sync_vault_to_rag.py")
                        if not os.path.exists(sync_script):
                            sync_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools", "sync_vault_to_rag.py")
                        if os.path.exists(sync_script):
                            cmd = [sys.executable, sync_script, "--api-key", _delegate_get_rag_api_key(), "--all"]
                            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            main_mod = sys.modules.get("main")
                            if main_mod:
                                setattr(main_mod, "_RAG_SYNC_PROCESS", proc)
                    except Exception as ex:
                        logger.error(f"[RAG-Sync-Trigger] Fehler: {ex}")
            _delegate_spawn_background(trigger_background_rag_sync(), name="rag_sync_trigger")

        return {
            "status": "success",
            "uploaded_count": len(results),
            "items": results
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/library/ingest")
def api_library_ingest():
    try:
        from utils.batch_library_importer import run_batch_ingest
        summary = run_batch_ingest()
        return {
            "status": "success",
            "summary": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/library/books")
def api_library_books():
    try:
        from utils.batch_library_importer import list_indexed_books
        books = list_indexed_books()
        return {
            "status": "success",
            "count": len(books),
            "books": books
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/library/book-content")
def api_library_book_content(rel_path: str = Query(...)):
    try:
        from utils.batch_library_importer import resolve_vault_path
        vault_dir = resolve_vault_path()
        bib_dir = os.path.join(vault_dir, "03_Bibliothek_Wissen")
        
        target = os.path.abspath(os.path.join(bib_dir, rel_path.lstrip("/\\")))
        if not target.startswith(os.path.abspath(bib_dir)):
            raise HTTPException(status_code=400, detail="Ungültiger Dateipfad außerhalb der Bibliothek.")
            
        if not os.path.exists(target) or not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="Buch-Dokument nicht gefunden.")
            
        with open(target, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        return {
            "status": "success",
            "path": rel_path,
            "filename": os.path.basename(target),
            "content": content,
            "size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# QUARTZ & STATIC KNOWLEDGE CONFIGURATION
# ---------------------------------------------------------

@router.get("/api/v1/brain/quartz-config")
def api_get_quartz_config():
    config_candidates = [
        os.path.join(WORKSPACE_DIR, "quartz_app", "quartz.config.default.yaml"),
        "quartz_app/quartz.config.default.yaml",
        "/app/quartz_app/quartz.config.default.yaml"
    ]
    config_file = None
    for c in config_candidates:
        if os.path.exists(c):
            config_file = c
            break
            
    if not config_file:
        raise HTTPException(status_code=404, detail="Quartz-Konfigurationsdatei nicht gefunden.")

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return {"config": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/brain/quartz-config")
async def api_save_quartz_config(request: Request):
    require_admin(request)  # RBAC: Schreiben der Quartz-Konfiguration ist Admin-Sache
    payload = await request.json()
    new_config = payload.get("config")
    if not new_config:
        raise HTTPException(status_code=400, detail="Keine Konfiguration übergeben.")

    config_candidates = [
        os.path.join(WORKSPACE_DIR, "quartz_app", "quartz.config.default.yaml"),
        "quartz_app/quartz.config.default.yaml",
        "/app/quartz_app/quartz.config.default.yaml"
    ]
    config_file = None
    for c in config_candidates:
        if os.path.exists(c):
            config_file = c
            break
            
    if not config_file:
        config_file = "quartz_app/quartz.config.default.yaml"

    try:
        yaml_content = yaml.dump(new_config, sort_keys=False, allow_unicode=True)
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Extract active theme colors for custom.scss
        th_colors = new_config.get("configuration", {}).get("theme", {}).get("colors", {})
        dark_c = th_colors.get("darkMode", {})
        light_c = th_colors.get("lightMode", {})
        
        c_bg = dark_c.get("light") or light_c.get("light") or "#ffffff"
        c_text = dark_c.get("darkgray") or light_c.get("darkgray") or "#1e293b"
        c_dark = dark_c.get("dark") or light_c.get("dark") or "#0f172a"
        c_gray = dark_c.get("gray") or light_c.get("gray") or "#64748b"
        c_lightgray = dark_c.get("lightgray") or light_c.get("lightgray") or "#e2e8f0"
        c_sec = dark_c.get("secondary") or light_c.get("secondary") or "#2563eb"
        c_ter = dark_c.get("tertiary") or light_c.get("tertiary") or "#84a59d"
        c_hl = dark_c.get("highlight") or light_c.get("highlight") or "rgba(143, 159, 169, 0.15)"
        c_thl = dark_c.get("textHighlight") or light_c.get("textHighlight") or "#fef08a"

        custom_scss_content = f"""@use "./variables.scss" as *;

:root {{
  --light: {c_bg};
  --lightgray: {c_lightgray};
  --gray: {c_gray};
  --darkgray: {c_text};
  --dark: {c_dark};
  --secondary: {c_sec};
  --tertiary: {c_ter};
  --highlight: {c_hl};
  --textHighlight: {c_thl};
}}

:root[saved-theme="dark"], :root[saved-theme="light"], html, body, .page, article, main, header, footer, .sidebar, .center {{
  background-color: var(--light) !important;
  color: var(--darkgray) !important;
}}

h1, h2, h3, h4, h5, h6, .article-title, .page-title, .page-title a {{
  color: var(--dark) !important;
}}

a {{
  color: var(--secondary) !important;
}}
"""
        scss_candidates = [
            os.path.join(WORKSPACE_DIR, "quartz_app", "quartz", "styles", "custom.scss"),
            "quartz_app/quartz/styles/custom.scss",
            "/app/quartz_app/quartz/styles/custom.scss"
        ]
        for sc in scss_candidates:
            if os.path.exists(os.path.dirname(sc)):
                try:
                    with open(sc, "w", encoding="utf-8") as f:
                        f.write(custom_scss_content)
                except Exception:
                    pass

        # Write inside archon-quartz container if active
        try:
            b64_yaml = base64.b64encode(yaml_content.encode('utf-8')).decode('ascii')
            b64_scss = base64.b64encode(custom_scss_content.encode('utf-8')).decode('ascii')
            
            cmd = f"echo '{b64_yaml}' | base64 -d > /usr/src/app/quartz.config.default.yaml && echo '{b64_scss}' | base64 -d > /usr/src/app/quartz/styles/custom.scss"
            exec_payload = {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": ["sh", "-c", cmd]}
            # Docker-Zugriffe sind blockierend -> aus dem Event-Loop auslagern
            res_exec = await asyncio.to_thread(
                _delegate_docker_socket_request, "POST", "/containers/archon-quartz/exec", exec_payload)
            if res_exec:
                exec_id = json.loads(res_exec.decode('utf-8', errors='ignore')).get("Id")
                if exec_id:
                    await asyncio.to_thread(
                        _delegate_docker_socket_request, "POST", f"/exec/{exec_id}/start",
                        {"Detach": False, "Tty": False})

            await asyncio.to_thread(_delegate_post_docker_container_action, "archon-quartz", "restart")
        except Exception as e:
            logger.warning(f"Error updating archon-quartz via docker: {e}")

        return {"status": "success", "message": "Quartz Konfiguration gespeichert und Service neu gestartet."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
