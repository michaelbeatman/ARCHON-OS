"""Router fuer Live UI Editor und Design Studio (Text Replacement, HTML Freeze)."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("archon.routers.ui")

router = APIRouter(tags=["ui"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def _full_html_target_files() -> list:
    """Die Zieldateien fuer "HTML einfrieren" (existierende Kandidaten)."""
    import main as app_main

    workspace_dir = getattr(app_main, "WORKSPACE_DIR", "/app")
    candidates = [
        "/app/static/index.html",
        "static/index.html",
        os.path.join(os.path.dirname(os.path.abspath(app_main.__file__)), "static", "index.html"),
        os.path.join(workspace_dir, "static", "index.html"),
    ]
    return [p for p in set(candidates) if os.path.exists(p)]


class TextReplacementItem(BaseModel):
    original: str
    replacement: str


class TextReplacementsRequest(BaseModel):
    replacements: List[TextReplacementItem]


@router.post("/api/v1/ui/save-text-replacements")
def api_save_text_replacements(request: Request, req: TextReplacementsRequest):
    _require_admin(request)
    import main as app_main

    workspace_dir = getattr(app_main, "WORKSPACE_DIR", "/app")
    candidates = [
        "/app/static/index.html",
        "static/index.html",
        os.path.join(os.path.dirname(os.path.abspath(app_main.__file__)), "static", "index.html"),
        os.path.join(workspace_dir, "static", "index.html"),
    ]
    target_files = [p for p in set(candidates) if os.path.exists(p)]
    if not target_files:
        raise HTTPException(status_code=404, detail="Keine static/index.html Datei gefunden.")

    total_replaced = 0
    for target_path in target_files:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()

            file_replaced = 0
            for item in req.replacements:
                orig = item.original
                repl = item.replacement
                if orig and repl and orig != repl and orig in content:
                    content = content.replace(orig, repl)
                    file_replaced += 1

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
            total_replaced = max(total_replaced, file_replaced)
        except Exception as err:
            logger.warning(f"Error saving replacements to {target_path}: {err}")

    if hasattr(app_main, "add_ticker"):
        app_main.add_ticker(
            "Live UI Editor",
            f"{total_replaced} Texte dauerhaft in index.html eingefroren & gespeichert.",
        )
    return {"status": "success", "replaced_count": total_replaced}


class FullHtmlSaveRequest(BaseModel):
    html: Optional[str] = None
    custom_css: Optional[str] = None


@router.post("/api/v1/ui/save-full-html")
def api_save_full_html(request: Request, req: FullHtmlSaveRequest):
    _require_admin(request)
    import main as app_main

    fn_targets = getattr(app_main, "_full_html_target_files", _full_html_target_files)
    target_files = fn_targets()
    if not target_files:
        raise HTTPException(status_code=404, detail="Keine static/index.html Datei gefunden.")

    if not req.html or len(req.html.strip()) <= 100:
        raise HTTPException(
            status_code=400,
            detail="HTML fehlt oder ist zu kurz (< 100 Zeichen) — es wurde nichts geschrieben.",
        )

    written, failed = [], {}
    for target_path in target_files:
        tmp_path = f"{target_path}.tmp.{os.getpid()}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(req.html)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)
            written.append(target_path)
        except Exception as err:
            failed[target_path] = str(err)
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if not written:
        raise HTTPException(
            status_code=500,
            detail=f"HTML konnte in keinem Ziel gespeichert werden: {failed}",
        )
    if failed:
        logger.warning(f"[Design Studio] HTML nur teilweise gespeichert: {failed}")

    if hasattr(app_main, "add_ticker"):
        app_main.add_ticker("Design Studio", "HTML & Design-Stand erfolgreich eingefroren und gespeichert.")
    return {"status": "success", "written_to": written, "failed": failed}
