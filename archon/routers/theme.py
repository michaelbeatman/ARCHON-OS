"""Theme, Design Themes & Live Overrides Router.

Verwaltet Custom-Themes, Live-Studio-Overrides, CSS-Baking
und Background-Uploads.
"""

import asyncio
import os
import re
import sys
import time
import datetime
from typing import Dict, Any, Optional

from fastapi import APIRouter, Body, HTTPException, Request, UploadFile, File
from archon.core.paths import THEMES_DIR, THEME_FILE, THEME_LIVE_FILE
from archon.core.runtime import _load_json, _save_json
from archon.routers._rbac import require_admin_or_503

router = APIRouter(tags=["theme"])

os.makedirs(THEMES_DIR, exist_ok=True)

_DEPS = {
    "require_admin": require_admin_or_503,
}


def configure(*, require_admin=None):
    if require_admin is not None:
        _DEPS["require_admin"] = require_admin


def _check_admin(request: Request):
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "require_admin"):
        fn = getattr(main_mod, "require_admin")
        if fn is not _check_admin:
            return fn(request)
    fn = _DEPS.get("require_admin") or require_admin_or_503
    return fn(request)


def _get_theme_live_file() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "THEME_LIVE_FILE"):
        return getattr(main_mod, "THEME_LIVE_FILE")
    return THEME_LIVE_FILE


def _get_theme_file() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "THEME_FILE"):
        return getattr(main_mod, "THEME_FILE")
    return THEME_FILE


def _get_themes_dir() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "THEMES_DIR"):
        return getattr(main_mod, "THEMES_DIR")
    return THEMES_DIR


def _get_design_themes_targets() -> list:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "DESIGN_THEMES_TARGETS"):
        return getattr(main_mod, "DESIGN_THEMES_TARGETS")
    return DESIGN_THEMES_TARGETS


def _save_json_delegate(path: str, data: Any) -> None:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_save_json"):
        fn = getattr(main_mod, "_save_json")
        if fn is not _save_json_delegate:
            return fn(path, data)
    return _save_json(path, data)


def _load_json_delegate(path: str, default: Any) -> Any:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_load_json"):
        fn = getattr(main_mod, "_load_json")
        if fn is not _load_json_delegate:
            return fn(path, default)
    return _load_json(path, default)


def load_theme() -> Dict:
    return _load_json_delegate(_get_theme_file(), {})


def save_theme(theme_data: Dict):
    _save_json_delegate(_get_theme_file(), theme_data)


@router.get("/api/themes")
def api_get_themes():
    themes = []
    tdir = _get_themes_dir()
    if os.path.exists(tdir):
        for file in os.listdir(tdir):
            if file.endswith(".json"):
                themes.append(file.replace(".json", ""))
    return {"themes": themes}


@router.get("/api/themes/{theme_name}")
def api_get_theme_by_name(theme_name: str):
    path = os.path.join(_get_themes_dir(), f"{theme_name}.json")
    if os.path.exists(path):
        return _load_json_delegate(path, {})
    return {}


@router.post("/api/themes/{theme_name}")
def api_save_theme_by_name(theme_name: str, theme_data: dict = Body(...)):
    path = os.path.join(_get_themes_dir(), f"{theme_name}.json")
    _save_json_delegate(path, theme_data)
    return {"status": "success", "theme_name": theme_name}


@router.delete("/api/themes/{theme_name}")
def api_delete_theme_by_name(theme_name: str):
    path = os.path.join(_get_themes_dir(), f"{theme_name}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "success"}


DESIGN_THEMES_TARGETS = [
    os.path.join("config", "design_themes.json"),
    "/app/config/design_themes.json",
    os.path.join("data", "design_themes.json"),
    "/app/data/design_themes.json",
]


@router.get("/api/design/themes")
def api_get_design_themes():
    for cand in _get_design_themes_targets():
        if os.path.exists(cand):
            data = _load_json_delegate(cand, {})
            if data and "themes" in data and len(data["themes"]) > 0:
                return data
    return {"active_theme_id": "archon_current", "active_mode": "light", "themes": {}}


@router.post("/api/design/themes")
def api_save_design_themes(payload: Dict = Body(...)):
    current = api_get_design_themes()
    if "active_theme_id" in payload:
        current["active_theme_id"] = payload["active_theme_id"]
    if "active_mode" in payload:
        current["active_mode"] = payload["active_mode"]
    if "themes" in payload and isinstance(payload["themes"], dict):
        current["themes"] = payload["themes"]
    if "theme" in payload and isinstance(payload["theme"], dict):
        t = payload["theme"]
        tid = t.get("id") or "custom_" + str(int(time.time()))
        t["id"] = tid
        if "themes" not in current or not isinstance(current["themes"], dict):
            current["themes"] = {}
        current["themes"][tid] = t
        if payload.get("set_active", True):
            current["active_theme_id"] = tid

    written, failed = [], {}
    for target in _get_design_themes_targets():
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            _save_json_delegate(target, current)
            written.append(target)
        except Exception as exc:
            failed[target] = str(exc)
    if not written:
        raise HTTPException(
            status_code=500,
            detail=f"Theme konnte in keinem Ziel gespeichert werden: {failed}",
        )
    return {"status": "success", "data": current, "written_to": written, "failed": failed}


@router.delete("/api/design/themes/{theme_id}")
def api_delete_design_theme(theme_id: str):
    current = api_get_design_themes()
    themes = current.get("themes", {})
    if theme_id in themes and len(themes) > 1:
        del themes[theme_id]
        if current.get("active_theme_id") == theme_id:
            current["active_theme_id"] = next(iter(themes.keys()), "archon_current")
        written, failed = [], {}
        for target in _get_design_themes_targets():
            try:
                _save_json_delegate(target, current)
                written.append(target)
            except Exception as exc:
                failed[target] = str(exc)
        if not written:
            raise HTTPException(
                status_code=500,
                detail=f"Theme konnte in keinem Ziel geloescht werden: {failed}",
            )
        return {"status": "success", "data": current, "written_to": written, "failed": failed}
    return {"status": "success", "data": current}


@router.get("/api/theme")
def api_get_theme():
    return load_theme()


@router.post("/api/theme")
def api_save_theme(theme_data: Dict = Body(...)):
    save_theme(theme_data)
    return {"status": "success"}


@router.get("/api/theme/live-overrides")
def api_get_theme_live_overrides():
    return _load_json_delegate(_get_theme_live_file(), {"rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {}})


@router.post("/api/theme/live-overrides")
def api_save_theme_live_overrides(payload: Dict = Body(...)):
    target_file = _get_theme_live_file()
    existing = _load_json_delegate(target_file, {"rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {}})
    merged = dict(existing) if isinstance(existing, dict) else {}

    if "rawCss" in payload:
        merged["rawCss"] = payload["rawCss"]

    for field in ("rules", "textOverrides", "htmlOverrides"):
        if field in payload:
            new_val = payload[field]
            if isinstance(new_val, dict):
                if new_val:
                    if not isinstance(merged.get(field), dict):
                        merged[field] = {}
                    merged[field].update(new_val)
            else:
                merged[field] = new_val

    for meta_key in ("migration_version", "updated_at"):
        if meta_key in payload:
            merged[meta_key] = payload[meta_key]

    _save_json_delegate(target_file, merged)
    return {"status": "success"}


@router.post("/api/theme/bake-into-main-design")
def api_bake_theme_into_main_design(payload: Dict = Body(None)):
    """Kompiliert alle Live-Studio-Regeln direkt in static/custom_studio.css,
    leert die temporären Overrides auf Server und Client und setzt den Zähler auf 0 zurück.
    """
    target_file = _get_theme_live_file()
    data = payload or _load_json_delegate(target_file, {})
    rules = data.get("rules", {})
    if not rules:
        live = _load_json_delegate(target_file, {})
        rules = live.get("rules", {})

    css_lines = []
    prop_count = 0
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css_lines.append("/* ========================================================================= */")
    css_lines.append(f"/* ARCHON STUDIO BAKED CSS — Eingebrannt am: {now_str}               */")
    css_lines.append("/* ========================================================================= */\n")

    for sel, props in rules.items():
        if not props or not isinstance(props, dict):
            continue
        clean_props = []
        for p, v in props.items():
            if v is not None and str(v).strip() != "":
                clean_val = str(v).replace("!important", "").strip()
                clean_props.append(f"  {p}: {clean_val} !important;")
                prop_count += 1
        if clean_props:
            css_lines.append(f"{sel} {{")
            css_lines.extend(clean_props)
            css_lines.append("}\n")

    compiled_css = "\n".join(css_lines)

    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    studio_css_path = os.path.join(root_dir, "static", "custom_studio.css")
    try:
        with open(studio_css_path, "w", encoding="utf-8") as f:
            f.write(compiled_css)
    except Exception as e:
        print(f"[ThemeBake] Fehler beim Schreiben in custom_studio.css: {e}")

    reset_data = {
        "rules": {},
        "rawCss": "",
        "textOverrides": data.get("textOverrides", {}),
        "htmlOverrides": data.get("htmlOverrides", {}),
        "migration_version": f"baked_{int(time.time())}",
        "reset_all": True,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _save_json_delegate(target_file, reset_data)

    return {
        "status": "success",
        "baked_rules_count": prop_count,
        "selectors_count": len(rules),
        "version": reset_data["migration_version"],
        "message": f"{prop_count} Regeln erfolgreich ins permanente Hauptdesign eingebrannt.",
    }


@router.delete("/api/theme/live-overrides")
def api_delete_theme_live_overrides():
    _save_json_delegate(_get_theme_live_file(), {
        "rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {},
        "migration_version": "2026_10_27_baked_1793101139", "reset_all": True,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    return {"status": "success"}


@router.post("/api/theme/upload-background")
async def api_upload_theme_background(request: Request, file: UploadFile = File(...)):
    _check_admin(request)  # RBAC: Upload ist Admin-Sache
    allowed_ext = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp", ".gif": "image/gif"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Dateityp '{ext}' nicht erlaubt (jpg, jpeg, png, webp, gif).",
        )
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Bild zu gross (max. 8 MB).")
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    uploads_dir = os.path.join(root_dir, "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename or "background.png")
    fname = f"bg_{int(time.time())}_{safe_name}"
    dest = os.path.join(uploads_dir, fname)
    def _write_bg(path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)
    await asyncio.to_thread(_write_bg, dest, content)
    return {"status": "success", "url": f"/static/uploads/{fname}"}
