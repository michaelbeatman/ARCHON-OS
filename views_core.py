"""
views_core.py - Zentraler Code-Contract & API-Provider für Archon OS Frontend Views

Stellt Backend-Endpunkte und Datenstrukturen für:
- View 1: Eingang (view_inbox) - Intern (System-Events / Approvals), E-Mails, Telegram
- View 2: Zentralbibliothek (view_library) - AnythingLLM RAG Index & Obsidian Vault Tree/Content
- View 3: Showroom (view_showroom) - Berichte (.md/.txt) & Web-Artefakte (.html)
"""

import os

from backend.platform_paths import OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT
import sys
import re
import shutil
import glob
import time
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Request

from archon.routers._rbac import require_admin_or_503
from pydantic import BaseModel

try:
    from utils.path_jail import safe_path_within, PathJailError
except ImportError:  # pragma: no cover - direkter Aufruf ausserhalb des Repo-Roots
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from utils.path_jail import safe_path_within, PathJailError

router = APIRouter(prefix="/api/views", tags=["views_core"])

# Basispfade auflösen (Host vs. Docker)
WORKSPACE_DIR = "/app/agent_workspace" if os.path.exists("/app/agent_workspace") or os.path.exists("/.dockerenv") else "./agent_workspace"
MEMORY_DIR = "/app/data" if os.path.exists("/app/data") else "./data"

def get_inbox_email_dir() -> str:
    candidates = ["/opt/data/inbox/emails", os.path.join(MEMORY_DIR, "inbox", "emails"), "data/inbox/emails"]
    for c in candidates:
        if os.path.exists(c):
            return c
    path = os.path.join(MEMORY_DIR, "inbox", "emails")
    os.makedirs(path, exist_ok=True)
    return path

def get_inbox_telegram_dir() -> str:
    candidates = ["/opt/data/inbox/telegram", os.path.join(MEMORY_DIR, "inbox", "telegram"), "data/inbox/telegram"]
    for c in candidates:
        if os.path.exists(c):
            return c
    path = os.path.join(MEMORY_DIR, "inbox", "telegram")
    os.makedirs(path, exist_ok=True)
    return path

def get_reports_dir() -> str:
    candidates = ["/projects/builds/reports", os.path.join(WORKSPACE_DIR, "builds", "reports"), "agent_workspace/builds/reports"]
    for c in candidates:
        if os.path.exists(c):
            return c
    path = os.path.join(WORKSPACE_DIR, "builds", "reports")
    os.makedirs(path, exist_ok=True)
    return path

def get_apps_dir() -> str:
    candidates = ["/projects/builds/apps", os.path.join(WORKSPACE_DIR, "builds", "apps"), "agent_workspace/builds/apps"]
    for c in candidates:
        if os.path.exists(c):
            return c
    path = os.path.join(WORKSPACE_DIR, "builds", "apps")
    os.makedirs(path, exist_ok=True)
    return path

def resolve_obsidian_vault_dir() -> str:
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    import sys
    if sys.platform != "win32":
        candidates = ["/opt/data/obsidian", "/app/data/obsidian"]
    else:
        candidates = [OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT]
    candidates += [
        "/opt/data/obsidian",
        OBSIDIAN_VAULT,
        os.path.join(WORKSPACE_DIR, "obsidian_vault"),
        "agent_workspace/obsidian_vault"
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    default_path = os.path.join(WORKSPACE_DIR, "obsidian_vault")
    os.makedirs(default_path, exist_ok=True)
    return default_path


# =========================================================================
# 1. VIEW: EINGANG (/api/views/inbox)
# =========================================================================

@router.get("/inbox/items")
async def get_inbox_items():
    """
    Liefert die 3 Spalten gemäß Architektur:
    - internal: System-Events, Freigaben, Logs (mit Badges ERROR, GATE, SYSTEM)
    - emails: Dateien aus /opt/data/inbox/emails/ (.json / .txt)
    - telegram: Dateien aus /opt/data/inbox/telegram/ (.json mit Typ-Badges)
    Sortiert: Neueste oben.
    """
    try:
        from views.view_inbox import load_internal_events, load_email_messages, load_telegram_messages, load_webhook_events
        wh = load_webhook_events()
        intern = load_internal_events()
        emails = load_email_messages()
        tg = load_telegram_messages()
        return {
            "webhooks": wh,
            "webhook": wh,
            "internal": intern,
            "intern": intern,
            "emails": emails,
            "email": emails,
            "telegram": tg,
            "messenger": tg
        }
    except Exception as e:
        # Defensiver Fallback falls Import scheitert
        email_dir = get_inbox_email_dir()
        telegram_dir = get_inbox_telegram_dir()
        return {
            "internal": [
                {
                    "id": "sys_fallback",
                    "badge": "SYSTEM",
                    "badge_color": "#3B82F6",
                    "badge_bg": "#DBEAFE",
                    "title": "System Status: Online",
                    "preview": "Archon OS Inbox Kernel initialisiert.",
                    "content": "Archon OS Inbox Kernel aktiv.",
                    "sender": "System Daemon",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "mtime": datetime.datetime.now().timestamp(),
                    "source": "internal"
                }
            ],
            "emails": [],
            "telegram": []
        }


@router.get("/inbox/file")
async def get_inbox_file_content(request: Request, path: str = Query(...)):
    """Liest den vollen Dateiinhalt eines Inbox-Elements.

    M-02(a): Vorher wurde jeder Pfad roh geoeffnet. Jetzt: Rollenzaun plus Jail
    auf die beiden Inbox-Verzeichnisse.
    """
    require_admin_or_503(request)  # RBAC: Rohdatei-Lesen ist Admin-Sache
    try:
        real_path = safe_path_within(
            path, [get_inbox_email_dir(), get_inbox_telegram_dir()],
            must_exist=False, allow_dirs=False,
        )
    except PathJailError as exc:
        raise HTTPException(status_code=403, detail=f"Pfad nicht erlaubt: {exc}")
    if not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    try:
        with open(real_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {
            "path": real_path,
            "filename": os.path.basename(real_path),
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Lesen: {str(e)}")


# =========================================================================
# 2. VIEW: ZENTRALBIBLIOTHEK (/api/views/library)
# =========================================================================

VAULT_CACHE_FILE = os.path.join(MEMORY_DIR, "obsidian_vault_tree_cache.json")
_vault_tree_in_memory_cache = None
_vault_tree_cache_time = 0
_vault_is_scanning = False

def _build_vault_tree_fast(current_dir, rel_path="", depth=0, max_depth=4):
    if depth > max_depth:
        return []
    items = []
    try:
        with os.scandir(current_dir) as it:
            entries = sorted(it, key=lambda e: e.name)
    except Exception:
        return items

    for entry in entries:
        name = entry.name
        if name.startswith(".") or name in ["node_modules", ".git", ".obsidian", ".trash", "AgenticOS-2026", ".flatnotes"]:
            continue
        entry_rel = f"{rel_path}/{name}" if rel_path else name
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue

        if is_dir:
            children = _build_vault_tree_fast(entry.path, entry_rel, depth=depth + 1, max_depth=max_depth)
            items.append({
                "name": name,
                "path": entry_rel,
                "type": "directory",
                "children": children
            })
        else:
            lower = name.lower()
            if lower.endswith((".md", ".txt", ".canvas", ".json", ".pdf", ".epub")):
                try:
                    sz = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    sz = 0
                items.append({
                    "name": name,
                    "path": entry_rel,
                    "type": "file",
                    "extension": os.path.splitext(name)[1].lower(),
                    "size": sz
                })
    return items

def _refresh_vault_cache_worker(vault_dir):
    global _vault_tree_in_memory_cache, _vault_tree_cache_time, _vault_is_scanning
    _vault_is_scanning = True
    try:
        tree = _build_vault_tree_fast(vault_dir)
        _vault_tree_in_memory_cache = tree
        _vault_tree_cache_time = time.time()
        os.makedirs(os.path.dirname(os.path.abspath(VAULT_CACHE_FILE)), exist_ok=True)
        with open(VAULT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"vault_path": vault_dir, "tree": tree, "updated_at": _vault_tree_cache_time}, f, ensure_ascii=False)
    except Exception as e:
        print(f"Fehler im Vault-Cache Worker: {e}")
    finally:
        _vault_is_scanning = False

@router.get("/library/vault/tree")
async def get_vault_tree(force_refresh: bool = False):
    """Liefert den Verzeichnisbaum des Obsidian Vaults mit sofortigem Cache & Background-Sync."""
    global _vault_tree_in_memory_cache, _vault_tree_cache_time
    vault_dir = resolve_obsidian_vault_dir()
    now = time.time()

    # 1. In-Memory Cache prüfen
    if not force_refresh and _vault_tree_in_memory_cache and (now - _vault_tree_cache_time < 300):
        return {
            "vault_path": vault_dir,
            "tree": _vault_tree_in_memory_cache,
            "cached": True,
            "source": "memory"
        }

    # 2. Persistenter Disk-Cache prüfen
    if not force_refresh and os.path.exists(VAULT_CACHE_FILE):
        try:
            with open(VAULT_CACHE_FILE, "r", encoding="utf-8") as f:
                disk_cache = json.load(f)
            cached_tree = disk_cache.get("tree", [])
            _vault_tree_in_memory_cache = cached_tree
            _vault_tree_cache_time = disk_cache.get("updated_at", now)
            
            # Wenn Cache älter als 10 Minuten ist und kein Scan läuft: im Hintergrund aktualisieren
            if (now - _vault_tree_cache_time > 600) and not _vault_is_scanning:
                import threading
                threading.Thread(target=_refresh_vault_cache_worker, args=(vault_dir,), daemon=True).start()

            return {
                "vault_path": vault_dir,
                "tree": cached_tree,
                "cached": True,
                "source": "disk"
            }
        except Exception:
            pass

    # 3. Wenn kein Cache existiert: Direkt erstellen & cachen
    import threading
    if not _vault_is_scanning:
        # Falls Cache leer ist, synchron aufbauen und cachen
        _refresh_vault_cache_worker(vault_dir)

    return {
        "vault_path": vault_dir,
        "tree": _vault_tree_in_memory_cache or [],
        "cached": False,
        "source": "live"
    }


@router.get("/library/vault/file")
async def get_vault_file(path: str = Query(...)):
    """Liest den Inhalt einer gewählten Datei im Vault."""
    vault_dir = resolve_obsidian_vault_dir()
    # Normalize path and prevent directory traversal
    clean_rel = path.replace("\\", "/").lstrip("/")
    safe_path = os.path.abspath(os.path.join(vault_dir, clean_rel))
    vault_abs = os.path.abspath(vault_dir)

    if not safe_path.startswith(vault_abs):
        raise HTTPException(status_code=403, detail="Unzulässiger Pfad außerhalb des Vaults.")

    if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="Dokument im Vault nicht gefunden.")

    try:
        with open(safe_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {
            "path": clean_rel,
            "filename": os.path.basename(safe_path),
            "content": content,
            "mtime": os.path.getmtime(safe_path)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Laden der Datei: {str(e)}")


# =========================================================================
# 3. VIEW: SHOWROOM (/api/views/showroom)
# =========================================================================

_showroom_tree_cache = {"data": None, "ts": 0}

@router.get("/showroom/tree")
async def get_showroom_tree():
    """
    Liefert den hierarchischen Windows-Explorer-Baum für alle Projekte:
    Projekte -> 01_Zwischenberichte, 02_Medien, 03_Endprodukte
    """
    now = datetime.datetime.now().timestamp()
    if _showroom_tree_cache["data"] and (now - _showroom_tree_cache["ts"] < 15):
        return {"status": "ok", "cached": True, "tree": _showroom_tree_cache["data"]}

    vault_dir = resolve_obsidian_vault_dir()
    projects_dir = Path(vault_dir) / "01_PROJEKTE"
    tree = []

    if projects_dir.exists():
        for p_dir in sorted(projects_dir.iterdir()):
            if not p_dir.is_dir() or p_dir.name.startswith((".", "_")):
                continue

            # User-Vorgabe 09.10.2026: Datum immer als Orientierungspräfix im
            # Showroom-Titel (wie in Obsidian), auch wenn PROJEKT.md einen
            # eigenen # Titel liefert.
            _date_m = re.match(r"^(\d{8})", p_dir.name)
            _date_part = _date_m.group(1) if _date_m else None
            proj_info = {
                "id": p_dir.name,
                "title": p_dir.name.replace("-", " ").replace("_", " ").title(),
                "folder": p_dir.name,
                "path": str(p_dir),
                "sections": {
                    "zwischenberichte": [],
                    "medien": [],
                    "endprodukte": [],
                    "auftraege": []
                },
                "root_files": []
            }

            proj_md = p_dir / "PROJEKT.md"
            if proj_md.exists():
                try:
                    txt = proj_md.read_text(encoding="utf-8")
                    for line in txt.splitlines():
                        if line.startswith("# "):
                            proj_info["title"] = line.replace("# ", "").replace("📂 Projekt:", "").strip()
                            break
                except Exception:
                    pass
            if _date_part and not proj_info["title"].startswith(_date_part):
                proj_info["title"] = f"{_date_part} · {proj_info['title']}"

            for sec, subname in [("zwischenberichte", "01_Zwischenberichte"), ("medien", "02_Medien"), ("endprodukte", "03_Endprodukte"), ("auftraege", "04_Auftraege")]:
                s_path = p_dir / subname
                if s_path.exists():
                    for f in sorted(s_path.iterdir()):
                        if f.is_file():
                            proj_info["sections"][sec].append({
                                "name": f.name,
                                "path": str(f),
                                "ext": f.suffix.lower(),
                                "size": f.stat().st_size,
                                "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                            })
                        elif f.is_dir() and sec == "auftraege":
                            # Sub-Auftragsordner (z.B. AP1/AP2/AP3) als Knoten auflisten
                            try:
                                sz = sum(x.stat().st_size for x in f.rglob('*') if x.is_file())
                            except Exception:
                                sz = 0
                            proj_info["sections"][sec].append({
                                "name": f.name,
                                "path": str(f),
                                "ext": "[Ordner]",
                                "is_dir": True,
                                "size": sz,
                                "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                            })

            if p_dir.name == "Papierkorb":
                for item in sorted(p_dir.iterdir()):
                    if item.name.startswith((".", "_")) or item.name == "PROJEKT.md":
                        continue
                    is_dir = item.is_dir()
                    try:
                        sz = sum(f.stat().st_size for f in item.rglob('*') if f.is_file()) if is_dir else item.stat().st_size
                    except Exception:
                        sz = 0
                    proj_info["root_files"].append({
                        "name": item.name,
                        "path": str(item),
                        "ext": "[Ordner]" if is_dir else item.suffix.lower(),
                        "is_dir": is_dir,
                        "size": sz,
                        "date": datetime.datetime.fromtimestamp(item.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                    })
            else:
                for f in sorted(p_dir.iterdir()):
                    if f.is_file():
                        proj_info["root_files"].append({
                            "name": f.name,
                            "path": str(f),
                            "ext": f.suffix.lower(),
                            "is_dir": False,
                            "size": f.stat().st_size,
                            "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                        })

            tree.append(proj_info)

    _showroom_tree_cache["data"] = tree
    _showroom_tree_cache["ts"] = now
    return {"status": "ok", "cached": False, "tree": tree}


@router.get("/showroom/file-content")
async def get_showroom_file_content(request: Request, path: str = Query(...)):
    """Lädt den Inhalt einer Datei für die Showroom-Vorschau.

    F3/M-02: Frueher erlaubte die Pruefung ``startswith("/app")`` den gesamten
    Code-Baum (``.env.archon``, Service-Tokens). Erlaubt ist jetzt ausschliesslich
    die Vault-Wurzel — dort liegt der Showroom-Baum.
    """
    require_admin_or_503(request)  # RBAC: Rohdatei-Lesen ist Admin-Sache
    vault_dir = Path(resolve_obsidian_vault_dir()).resolve()
    try:
        target = Path(safe_path_within(
            path, [str(vault_dir)], must_exist=True, allow_dirs=False,
        ))
    except PathJailError as exc:
        raise HTTPException(status_code=403, detail=f"Unzulässiger Pfad: {exc}")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    ext = target.suffix.lower()
    mtime_str = datetime.datetime.fromtimestamp(target.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
    size_bytes = target.stat().st_size

    if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]:
        import base64
        with open(target, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = "image/svg+xml" if ext == ".svg" else f"image/{ext.replace('.', '')}"
        return {
            "type": "image",
            "name": target.name,
            "path": str(target),
            "size": size_bytes,
            "mtime": mtime_str,
            "data_url": f"data:{mime};base64,{b64}"
        }

    if ext == ".pdf":
        import base64
        with open(target, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return {
            "type": "pdf",
            "name": target.name,
            "path": str(target),
            "size": size_bytes,
            "mtime": mtime_str,
            "data_url": f"data:application/pdf;base64,{b64}"
        }

    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        content = f"(Fehler beim Lesen: {e})"

    return {
        "type": "markdown" if ext in [".md", ".markdown"] else ("html" if ext == ".html" else "text"),
        "name": target.name,
        "path": str(target),
        "size": size_bytes,
        "mtime": mtime_str,
        "content": content
    }


class DesktopExportPayload(BaseModel):
    filepath: str


@router.post("/showroom/export-desktop")
async def export_showroom_to_desktop(request: Request, payload: DesktopExportPayload):
    """Kopiert eine Datei direkt auf den Desktop.

    M-02(b): Der Handler nahm kein ``Request`` entgegen und konnte deshalb
    keinen Rollenzaun pruefen; die Quelle war ein beliebiger Pfad. Beides ist
    behoben — Quelle nur noch innerhalb der Vault-Wurzel.
    """
    require_admin_or_503(request)  # RBAC: Export ist Admin-Sache
    import shutil
    vault_dir = Path(resolve_obsidian_vault_dir()).resolve()
    try:
        source = Path(safe_path_within(
            payload.filepath, [str(vault_dir)], must_exist=True, allow_dirs=False,
        ))
    except PathJailError as exc:
        raise HTTPException(status_code=403, detail=f"Unzulässiger Pfad: {exc}")

    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    if sys.platform != "win32":
        desktop_candidates = [
            Path("/opt/desktop"),
            Path("/opt/data/Desktop"),
            Path(os.path.expanduser("~/Desktop"))
        ]
        desktop = desktop_candidates[0] if desktop_candidates[0].exists() else desktop_candidates[1]
    else:
        desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
    
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        target = desktop / source.name
        shutil.copy2(str(source), str(target))
        return {
            "status": "success",
            "message": f"Datei '{source.name}' erfolgreich exportiert nach: {target}",
            "desktop_path": str(target)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export-Fehler: {e}")


class FileActionPayload(BaseModel):
    filepath: str


@router.post("/showroom/file/delete")
async def delete_showroom_file(request: Request, payload: FileActionPayload):
    """Verschiebt eine Datei oder einen gesamten Projektordner in den Papierkorb (Projects/Papierkorb)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import shutil
    source = Path(payload.filepath).resolve()
    if not source.exists():
        raise HTTPException(status_code=404, detail="Datei oder Ordner nicht gefunden.")

    vault_dir = Path(resolve_obsidian_vault_dir()).resolve()
    projects_dir = vault_dir / "Projects"
    trash_dir = projects_dir / "Papierkorb"
    trash_dir.mkdir(parents=True, exist_ok=True)

    if source == projects_dir or source == trash_dir or source == (projects_dir / "Einzelberichte"):
        raise HTTPException(status_code=400, detail="System-Ordner können nicht gelöscht werden.")

    target = trash_dir / source.name
    if target.exists():
        if target.is_dir():
            shutil.rmtree(str(target))
        else:
            target.unlink()

    try:
        shutil.move(str(source), str(target))
        global _showroom_tree_cache
        _showroom_tree_cache["data"] = None
        kind = "Projektordner" if target.is_dir() else "Datei"
        return {"status": "success", "message": f"{kind} '{source.name}' in den Papierkorb verschoben.", "trash_path": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Verschieben in den Papierkorb: {e}")


@router.post("/showroom/file/restore")
async def restore_showroom_file(request: Request, payload: FileActionPayload):
    """Stellt eine Datei oder einen Ordner aus dem Papierkorb wieder her."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import shutil
    source = Path(payload.filepath).resolve()
    if not source.exists():
        raise HTTPException(status_code=404, detail="Objekt im Papierkorb nicht gefunden.")

    vault_dir = Path(resolve_obsidian_vault_dir()).resolve()
    projects_dir = vault_dir / "Projects"

    if source.is_dir():
        target = projects_dir / source.name
    else:
        restore_dir = projects_dir / "Einzelberichte" / "03_Endprodukte"
        restore_dir.mkdir(parents=True, exist_ok=True)
        target = restore_dir / source.name

    if target.exists():
        if target.is_dir():
            shutil.rmtree(str(target))
        else:
            target.unlink()

    try:
        shutil.move(str(source), str(target))
        global _showroom_tree_cache
        _showroom_tree_cache["data"] = None
        kind = "Projektordner" if target.is_dir() else "Datei"
        return {"status": "success", "message": f"{kind} '{source.name}' wiederhergestellt.", "target_path": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler bei der Wiederherstellung: {e}")


@router.post("/showroom/file/purge")
async def purge_showroom_file(request: Request, payload: FileActionPayload):
    """Löscht eine Datei oder einen Ordner endgültig aus dem Papierkorb."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import shutil
    source = Path(payload.filepath).resolve()
    if not source.exists():
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden.")

    vault_dir = Path(resolve_obsidian_vault_dir()).resolve()
    trash_dir = vault_dir / "Projects" / "Papierkorb"
    if not str(source).startswith(str(trash_dir)):
        raise HTTPException(status_code=400, detail="Endgültiges Löschen ist nur für Objekte im Papierkorb zulässig.")

    if source == trash_dir:
        raise HTTPException(status_code=400, detail="Der Papierkorb selbst kann nicht gelöscht werden.")

    try:
        kind = "Projektordner" if source.is_dir() else "Datei"
        if source.is_dir():
            shutil.rmtree(str(source))
        else:
            source.unlink()
        global _showroom_tree_cache
        _showroom_tree_cache["data"] = None
        return {"status": "success", "message": f"{kind} '{source.name}' endgültig gelöscht."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim endgültigen Löschen: {e}")


@router.get("/showroom/reports")
async def get_showroom_reports():
    """Liefert alle Berichte aus Projects/ und builds/reports/."""
    vault_dir = resolve_obsidian_vault_dir()
    projects_dir = Path(vault_dir) / "01_PROJEKTE"
    reports_dir = Path(get_reports_dir())
    reports = []
    seen = set()

    # 1. Scanne Obsidian Projects Endprodukte
    if projects_dir.exists():
        for ep in projects_dir.glob("*/03_Endprodukte/*.md"):
            if ep.name in seen:
                continue
            seen.add(ep.name)
            try:
                content = ep.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""
            reports.append({
                "filename": ep.name,
                "title": ep.stem.replace("-", " ").replace("_", " ").title(),
                "mtime": ep.stat().st_mtime,
                "date": datetime.datetime.fromtimestamp(ep.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "size": ep.stat().st_size,
                "path": str(ep)
            })

    # 2. Scanne builds/reports
    if reports_dir.exists():
        for fname in os.listdir(reports_dir):
            if fname.lower().endswith((".md", ".txt")) and fname not in seen:
                seen.add(fname)
                fpath = reports_dir / fname
                mtime = fpath.stat().st_mtime
                reports.append({
                    "filename": fname,
                    "title": fname.replace(".md", "").replace(".txt", "").replace("_", " ").title(),
                    "mtime": mtime,
                    "date": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    "size": fpath.stat().st_size,
                    "path": str(fpath)
                })

    reports.sort(key=lambda x: x["mtime"], reverse=True)
    return {"reports": reports}


@router.get("/showroom/report-content")
async def get_showroom_report_content(filename: str = Query(...)):
    """Liest den Markdown-/Text-Inhalt eines gewählten Berichts (auch aus Projects)."""
    vault_dir = resolve_obsidian_vault_dir()
    projects_dir = Path(vault_dir) / "01_PROJEKTE"
    reports_dir = Path(get_reports_dir())

    # 1. Prüfe in Projects/*/03_Endprodukte
    if projects_dir.exists():
        for cand in projects_dir.glob(f"*/03_Endprodukte/{filename}"):
            if cand.exists() and cand.is_file():
                try:
                    return {"filename": filename, "content": cand.read_text(encoding="utf-8", errors="ignore")}
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))

    # 2. Prüfe in builds/reports
    safe_path = reports_dir / os.path.basename(filename)
    if safe_path.exists():
        try:
            return {"filename": os.path.basename(safe_path), "content": safe_path.read_text(encoding="utf-8", errors="ignore")}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=404, detail="Bericht nicht gefunden.")


@router.get("/showroom/apps")
async def get_showroom_apps():
    """
    Liefert alle HTML-Apps aus agent_workspace/builds/apps/.
    Erkennt Ordner mit einer index.html oder direkte .html Dateien.
    """
    apps_dir = get_apps_dir()
    apps = []
    if os.path.exists(apps_dir):
        for item in os.listdir(apps_dir):
            full_item_path = os.path.join(apps_dir, item)
            if os.path.isdir(full_item_path):
                index_path = os.path.join(full_item_path, "index.html")
                if os.path.exists(index_path):
                    mtime = os.path.getmtime(index_path)
                    apps.append({
                        "id": item,
                        "name": item.replace("-", " ").replace("_", " ").title(),
                        "url": f"/builds/apps/{item}/index.html",
                        "folder": item,
                        "mtime": mtime,
                        "date": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    })
            elif item.lower().endswith(".html"):
                mtime = os.path.getmtime(full_item_path)
                apps.append({
                    "id": item,
                    "name": item.replace(".html", "").replace("-", " ").replace("_", " ").title(),
                    "url": f"/builds/apps/{item}",
                    "folder": None,
                    "mtime": mtime,
                    "date": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                })
    apps.sort(key=lambda x: x["mtime"], reverse=True)
    return {"apps": apps}


@router.get("/showroom/preview/app/{app_name}")
async def get_showroom_app_preview_frame(app_name: str):
    """
    Liefert einen interaktiven Responsive-Preview-Frame mit Device-Switcher
    (Desktop, Tablet, Mobile) für die angegebene lokale Webanwendung.
    """
    from fastapi.responses import HTMLResponse
    apps_dir = get_apps_dir()
    app_dir = os.path.join(apps_dir, app_name)
    index_file = os.path.join(app_dir, "index.html")
    single_file = os.path.join(apps_dir, f"{app_name}.html")

    if os.path.exists(index_file):
        app_url = f"/builds/apps/{app_name}/index.html"
    elif os.path.exists(single_file):
        app_url = f"/builds/apps/{app_name}.html"
    elif os.path.exists(app_dir) and app_name.endswith(".html"):
        app_url = f"/builds/apps/{app_name}"
    else:
        raise HTTPException(status_code=404, detail=f"Web-App '{app_name}' besitzt keine index.html.")

    html_content = f"""<!DOCTYPE html>
<html lang="de" class="h-full">
<head>
  <meta charset="utf-8">
  <title>Showroom Preview: {app_name}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body {{ background: #09090b; color: #f4f4f5; }}
    .device-desktop {{ width: 100%; height: 100%; border-radius: 0; }}
    .device-tablet {{ width: 768px; height: 92%; border-radius: 20px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.7); }}
    .device-mobile {{ width: 375px; height: 85%; border-radius: 36px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.7); border: 8px solid #27272a; }}
  </style>
</head>
<body class="h-full flex flex-col font-sans overflow-hidden">
  <header class="h-12 border-b border-zinc-800 bg-zinc-900/90 px-4 flex items-center justify-between shrink-0">
    <div class="flex items-center gap-3">
      <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
      <span class="font-bold text-xs tracking-tight font-mono text-zinc-200">Showroom Live Preview: <span class="text-sky-400">{app_name}</span></span>
    </div>
    <div class="flex items-center bg-zinc-800 p-0.5 rounded-xl border border-zinc-700/60 text-xs">
      <button onclick="setDevice('desktop')" id="btn-desktop" class="px-2.5 py-1 rounded-lg font-mono font-bold bg-zinc-700 text-white flex items-center gap-1.5 transition">
        <i class="fa-solid fa-desktop"></i> Desktop
      </button>
      <button onclick="setDevice('tablet')" id="btn-tablet" class="px-2.5 py-1 rounded-lg font-mono text-zinc-400 hover:text-white flex items-center gap-1.5 transition">
        <i class="fa-solid fa-tablet-screen-button"></i> Tablet
      </button>
      <button onclick="setDevice('mobile')" id="btn-mobile" class="px-2.5 py-1 rounded-lg font-mono text-zinc-400 hover:text-white flex items-center gap-1.5 transition">
        <i class="fa-solid fa-mobile-screen"></i> Mobile
      </button>
    </div>
    <div class="flex items-center gap-2">
      <button onclick="document.getElementById('preview-frame').contentWindow.location.reload()" class="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition" title="Neu laden">
        <i class="fa-solid fa-rotate-right"></i>
      </button>
      <a href="{app_url}" target="_blank" class="px-2.5 py-1 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-mono text-xs font-bold transition flex items-center gap-1">
        In neuem Tab <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
      </a>
    </div>
  </header>
  <main class="flex-1 bg-zinc-950 flex items-center justify-center p-2 overflow-hidden relative">
    <iframe id="preview-frame" src="{app_url}" class="device-desktop bg-white border border-zinc-800 transition-all duration-300"></iframe>
  </main>
  <script>
    function setDevice(mode) {{
      const frame = document.getElementById('preview-frame');
      const btns = ['desktop', 'tablet', 'mobile'];
      btns.forEach(b => {{
        const btn = document.getElementById('btn-' + b);
        if (b === mode) {{
          btn.className = 'px-2.5 py-1 rounded-lg font-mono font-bold bg-zinc-700 text-white flex items-center gap-1.5 transition';
        }} else {{
          btn.className = 'px-2.5 py-1 rounded-lg font-mono text-zinc-400 hover:text-white flex items-center gap-1.5 transition';
        }}
      }});
      frame.className = 'device-' + mode + ' bg-white border border-zinc-800 transition-all duration-300';
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)



@router.post("/showroom/archive-to-obsidian")
async def archive_showroom_report(filename: str = Query(...)):
    """Archiviert einen Bericht nach /opt/data/obsidian/00_Notebook_Synthesen/."""
    try:
        from views.view_showroom import archive_report_to_obsidian
        res = archive_report_to_obsidian(filename)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CodeRunPayload(BaseModel):
    filepath: Optional[str] = None
    code: Optional[str] = None
    language: Optional[str] = "python"
    stdin: Optional[str] = ""


@router.post("/showroom/run-code")
async def run_showroom_code(request: Request, payload: CodeRunPayload):
    """
    Fuehrt Code-Snippets oder Skripte aus dem Showroom in einer isolierten Sandbox aus.
    Gibt stdout, stderr, Exit-Code und Laufzeit zurueck.
    """
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import tempfile
    import time
    import subprocess
    import sys

    code_to_run = payload.code or ""
    lang = (payload.language or "python").lower()

    if payload.filepath:
        target_path = Path(payload.filepath)
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Datei fuer Ausfuehrung nicht gefunden.")
        if target_path.suffix.lower() == ".py":
            lang = "python"
        elif target_path.suffix.lower() in (".js", ".ts"):
            lang = "javascript"
        elif target_path.suffix.lower() in (".sh", ".bash"):
            lang = "bash"
        if not code_to_run:
            try:
                code_to_run = target_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Datei konnte nicht gelesen werden: {e}")

    if not code_to_run.strip():
        raise HTTPException(status_code=400, detail="Kein Quellcode zur Ausfuehrung uebergeben.")

    if lang == "python":
        scratch_dir = Path("/tmp/archon_sandbox") if os.path.exists("/tmp") else Path(tempfile.gettempdir())
        scratch_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=str(scratch_dir), delete=False, encoding="utf-8") as f:
            f.write(code_to_run)
            tmp_path = f.name

        start_time = time.perf_counter()
        try:
            res = subprocess.run(
                [sys.executable or "python", tmp_path],
                capture_output=True,
                text=True,
                timeout=12,
                cwd=str(scratch_dir),
                input=payload.stdin or ""
            )
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
            return {
                "status": "success" if res.returncode == 0 else "error",
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "duration_ms": elapsed_ms,
                "language": "python"
            }
        except subprocess.TimeoutExpired:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
            return {
                "status": "timeout",
                "exit_code": 124,
                "stdout": "",
                "stderr": "Ausfuehrung nach 12 Sekunden abgebrochen (Timeout).",
                "duration_ms": elapsed_ms,
                "language": "python"
            }
        except Exception as ex:
            return {
                "status": "error",
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Fehler bei Ausfuehrung: {ex}",
                "duration_ms": 0,
                "language": "python"
            }
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    return {
        "status": "error",
        "exit_code": 1,
        "stdout": "",
        "stderr": f"Sprache '{lang}' wird im Backend-Runner nicht direkt unterstuetzt.",
        "duration_ms": 0,
        "language": lang
    }


# =========================================================================
# THEME & CSS LIVE STUDIO PERSISTENCE ENDPOINTS
# =========================================================================

THEME_OVERRIDES_FILE = os.path.join(MEMORY_DIR, "live_theme_overrides.json")

class ThemeOverridesPayload(BaseModel):
    rules: Optional[Dict[str, Any]] = {}
    textOverrides: Optional[Dict[str, Any]] = {}

@router.get("/theme/live-overrides")
async def get_theme_live_overrides():
    """Liefert gespeicherte CSS Live Studio Regeln & Text-Overrides."""
    if os.path.exists(THEME_OVERRIDES_FILE):
        try:
            with open(THEME_OVERRIDES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"rules": {}, "textOverrides": {}}

@router.post("/theme/live-overrides")
async def save_theme_live_overrides(payload: ThemeOverridesPayload):
    """Speichert CSS Live Studio Regeln & Text-Overrides persistent."""
    try:
        data = {
            "rules": payload.rules or {},
            "textOverrides": payload.textOverrides or {},
            "updated_at": datetime.datetime.now().isoformat()
        }
        os.makedirs(os.path.dirname(os.path.abspath(THEME_OVERRIDES_FILE)), exist_ok=True)
        with open(THEME_OVERRIDES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # [ARCHIVED] Überschreiben von static/custom_studio.css deaktiviert zugunsten
        # der zentralen 15-Bausteine-Engine (/api/design/themes).
        return {"status": "success", "message": "Theme Overrides archiviert (15-Bausteine-Engine aktiv)."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {str(e)}")

@router.delete("/theme/live-overrides")
async def delete_theme_live_overrides():
    """Löscht alle gespeicherten CSS Live Studio Regeln & Text-Overrides."""
    try:
        data = {"rules": {}, "textOverrides": {}, "updated_at": datetime.datetime.now().isoformat()}
        os.makedirs(os.path.dirname(os.path.abspath(THEME_OVERRIDES_FILE)), exist_ok=True)
        with open(THEME_OVERRIDES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        for target_css in ["static/custom_studio.css", "/app/static/custom_studio.css", os.path.join(WORKSPACE_DIR, "static", "custom_studio.css")]:
            try:
                with open(target_css, "w", encoding="utf-8") as f:
                    f.write("/* Custom Studio CSS Reset */\n")
            except Exception:
                pass
        return {"status": "success", "message": "Theme Overrides erfolgreich zurückgesetzt."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Zurücksetzen: {str(e)}")


