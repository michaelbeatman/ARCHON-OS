"""
backend/showroom_router.py
FastAPI Router für den überarbeiteten Archon OS Showroom & Datei-Explorer:
- Baumansicht aller Projekte in C:\\Mein Obsidian\\Projects
- Unterordner (01_Zwischenberichte, 02_Medien, 03_Endprodukte)
- Datei-Inhalte (Markdown, HTML, Bilder, Code)
- Desktop-Export
- Abwärtskompatible Endpunkte für altes Frontend
"""

import os
import sys
import shutil
import base64
import datetime
import tempfile
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

def get_vault_dir() -> Path:
    env_p = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_p and Path(env_p).exists():
        return Path(env_p)
    for cand in [Path("/opt/data/obsidian"), Path(r"C:\Mein Obsidian"), Path("C:/.Mein Obsidian")]:
        if cand.exists():
            return cand
    return Path(r"C:\Mein Obsidian")

def get_desktop_dir() -> Path:
    for cand in [Path(r"C:\Users\micha\Desktop"), Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"]:
        if cand.exists():
            return cand
    return Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"

VAULT_DIR = get_vault_dir()
PROJECTS_DIR = VAULT_DIR / "01_PROJEKTE"
BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "agent_workspace" / "builds" / "reports"
APPS_DIR = BASE_DIR / "agent_workspace" / "builds" / "apps"
DESKTOP_DIR = get_desktop_dir()

router = APIRouter(prefix="/api/views/showroom", tags=["Showroom"])

# Einfacher In-Memory Cache (TTL: 15s)
_tree_cache: Dict[str, Any] = {"data": None, "timestamp": 0}


class ExportDesktopReq(BaseModel):
    filepath: str


@router.get("/tree")
def get_showroom_tree():
    """
    Liefert den hierarchischen Windows-Explorer-Baum für alle Projekte:
    Projekte -> 01_Zwischenberichte, 02_Medien, 03_Endprodukte
    """
    now = datetime.datetime.now().timestamp()
    if _tree_cache["data"] and (now - _tree_cache["timestamp"] < 15):
        return {"status": "ok", "cached": True, "tree": _tree_cache["data"]}

    if not PROJECTS_DIR.exists():
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    tree = []
    
    # Durchsuche alle Projekt-Ordner
    for p_dir in sorted(PROJECTS_DIR.iterdir()):
        if not p_dir.is_dir() or p_dir.name.startswith((".", "_")):
            continue

        proj_info = {
            "id": p_dir.name,
            "title": p_dir.name.replace("-", " ").replace("_", " ").title(),
            "folder": p_dir.name,
            "path": str(p_dir),
            "sections": {
                "zwischenberichte": [],
                "medien": [],
                "endprodukte": []
            },
            "root_files": []
        }

        # PROJEKT.md Titel parsen, falls vorhanden
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

        # 01_Zwischenberichte
        z_dir = p_dir / "01_Zwischenberichte"
        if z_dir.exists():
            for f in sorted(z_dir.iterdir()):
                if f.is_file():
                    proj_info["sections"]["zwischenberichte"].append({
                        "name": f.name,
                        "path": str(f),
                        "ext": f.suffix.lower(),
                        "size": f.stat().st_size,
                        "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                    })

        # 02_Medien
        m_dir = p_dir / "02_Medien"
        if m_dir.exists():
            for f in sorted(m_dir.iterdir()):
                if f.is_file():
                    proj_info["sections"]["medien"].append({
                        "name": f.name,
                        "path": str(f),
                        "ext": f.suffix.lower(),
                        "size": f.stat().st_size,
                        "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                    })

        # 03_Endprodukte
        e_dir = p_dir / "03_Endprodukte"
        if e_dir.exists():
            for f in sorted(e_dir.iterdir()):
                if f.is_file():
                    proj_info["sections"]["endprodukte"].append({
                        "name": f.name,
                        "path": str(f),
                        "ext": f.suffix.lower(),
                        "size": f.stat().st_size,
                        "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                    })

        # Direkt im Projektordner liegende Dateien (z. B. PROJEKT.md)
        for f in sorted(p_dir.iterdir()):
            if f.is_file():
                proj_info["root_files"].append({
                    "name": f.name,
                    "path": str(f),
                    "ext": f.suffix.lower(),
                    "size": f.stat().st_size,
                    "date": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                })

        tree.append(proj_info)

    _tree_cache["data"] = tree
    _tree_cache["timestamp"] = now
    return {"status": "ok", "cached": False, "tree": tree}


@router.get("/file-content")
def get_file_content(path: str = Query(...)):
    """
    Lädt den Inhalt einer Datei für die Showroom-Vorschau.
    Sicherheitscheck: Nur Dateien innerhalb von Obsidian Vault oder Workspace.
    """
    target = Path(path).resolve()
    # Sicherheitsprüfung
    allowed_roots = [VAULT_DIR.resolve(), BASE_DIR.resolve(), (BASE_DIR / "agent_workspace").resolve()]
    is_safe = any(str(target).startswith(str(r)) for r in allowed_roots)
    if not is_safe or not target.exists() or not target.is_file():
        raise HTTPException(status_code=403, detail="Zugriff verweigert oder Datei existiert nicht.")

    ext = target.suffix.lower()
    mtime_str = datetime.datetime.fromtimestamp(target.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
    size_bytes = target.stat().st_size

    # Bilddateien
    if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]:
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

    # Text / Markdown / Code
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


@router.post("/export-desktop")
def export_to_desktop(req: ExportDesktopReq):
    """
    Exportiert/Kopiert eine Datei direkt auf den Desktop des Nutzers.
    """
    source = Path(req.filepath).resolve()
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=404, detail="Quelldatei nicht gefunden.")

    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    target = DESKTOP_DIR / source.name
    try:
        shutil.copy2(str(source), str(target))
        return {
            "status": "success",
            "message": f"Datei erfolgreich auf den Desktop exportiert: {target.name}",
            "desktop_path": str(target)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Exportieren: {e}")


# =============================================================================
# Abwärtskompatible Endpunkte für das alte Frontend
# =============================================================================

@router.get("/reports")
def get_legacy_reports():
    """Liefert alle Endprodukte aus Projects/ und builds/reports für Dropdowns."""
    reports = []
    seen = set()

    # 1. Scanne Obsidian Projects Endprodukte
    if PROJECTS_DIR.exists():
        for ep in PROJECTS_DIR.glob("*/03_Endprodukte/*.md"):
            if ep.name in seen:
                continue
            seen.add(ep.name)
            try:
                content = ep.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""
            reports.append({
                "id": ep.name,
                "filename": ep.name,
                "title": ep.stem.replace("-", " ").replace("_", " ").title(),
                "content": content,
                "path": str(ep),
                "mtime": ep.stat().st_mtime,
                "date": datetime.datetime.fromtimestamp(ep.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "size_bytes": ep.stat().st_size
            })

    # 2. Scanne agent_workspace/builds/reports
    if REPORTS_DIR.exists():
        for rp in REPORTS_DIR.glob("*.md"):
            if rp.name in seen:
                continue
            seen.add(rp.name)
            try:
                content = rp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""
            reports.append({
                "id": rp.name,
                "filename": rp.name,
                "title": rp.stem.replace("-", " ").replace("_", " ").title(),
                "content": content,
                "path": str(rp),
                "mtime": rp.stat().st_mtime,
                "date": datetime.datetime.fromtimestamp(rp.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "size_bytes": rp.stat().st_size
            })

    reports.sort(key=lambda x: x["mtime"], reverse=True)
    return reports


@router.get("/report-content")
def get_legacy_report_content(filename: str = Query(...)):
    """Liefert den Inhalt eines Berichts."""
    # Suche zuerst in Projects
    for cand in PROJECTS_DIR.glob(f"*/03_Endprodukte/{filename}"):
        if cand.exists():
            return {"status": "ok", "filename": filename, "content": cand.read_text(encoding="utf-8", errors="ignore")}
    # Suche in builds/reports
    r_cand = REPORTS_DIR / filename
    if r_cand.exists():
        return {"status": "ok", "filename": filename, "content": r_cand.read_text(encoding="utf-8", errors="ignore")}
    return {"status": "error", "content": "(Bericht nicht gefunden)"}


@router.get("/apps")
def get_legacy_apps():
    """Liefert verfügbare Web-Apps aus builds/apps/."""
    apps = []
    if APPS_DIR.exists():
        for d in APPS_DIR.iterdir():
            if d.is_dir():
                idx = d / "index.html"
                if idx.exists():
                    apps.append({
                        "name": d.name,
                        "url": f"/builds/apps/{d.name}/index.html",
                        "code": idx.read_text(encoding="utf-8", errors="ignore")
                    })
    return apps


class CodeRunRequest(BaseModel):
    filepath: Optional[str] = None
    code: Optional[str] = None
    language: Optional[str] = "python"
    stdin: Optional[str] = ""


@router.post("/run-code")
def run_showroom_code(req: CodeRunRequest = Body(...)):
    """
    Führt Code-Snippets oder Skripte aus dem Showroom in einer isolierten Sandbox aus.
    Gibt stdout, stderr, Exit-Code und Laufzeit zurück.
    """
    code_to_run = req.code or ""
    lang = (req.language or "python").lower()

    if req.filepath:
        target_path = Path(req.filepath)
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Datei für Ausführung nicht gefunden.")
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
        raise HTTPException(status_code=400, detail="Kein Quellcode zur Ausführung übergeben.")

    # Python Sandbox-Runner
    if lang == "python":
        scratch_dir = BASE_DIR / "agent_workspace" / "scratch"
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
                input=req.stdin or ""
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
                "stderr": "Ausführung nach 12 Sekunden abgebrochen (Timeout).",
                "duration_ms": elapsed_ms,
                "language": "python"
            }
        except Exception as ex:
            return {
                "status": "error",
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Fehler bei Ausführung: {ex}",
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
        "stderr": f"Sprache '{lang}' wird im Backend-Runner nicht direkt unterstützt.",
        "duration_ms": 0,
        "language": lang
    }
