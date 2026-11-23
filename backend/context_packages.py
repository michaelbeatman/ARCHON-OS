# -*- coding: utf-8 -*-
"""
backend/context_packages.py
===========================
Wiederverwendbare Kontext-Pakete fuer Workflow-Stationen.

Ein Upload wird EINMALIG physisch abgelegt (`data/context_packages/ctx_<id>/…`)
und im Manifest mit SHA-256, Groesse, Token-Schaetzung und Memory-Scope
registriert. Stationen speichern nur die Referenz `ctx_<id>` – nicht den
Dateiinhalt. Damit bleiben Vorlagen klein und Kontext ist über mehrere
Stationen/Workflows teilbar.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import secrets
import threading
from typing import Any, Dict, List, Optional

from utils.path_jail import safe_path_within

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTX_ROOT = os.path.join(WORKSPACE_DIR, "data", "context_packages")
MANIFEST_PATH = os.path.join(CTX_ROOT, "manifest.json")
MAX_UPLOAD_BYTES = int(os.environ.get("ARCHON_MAX_CONTEXT_BYTES", str(25 * 1024 * 1024)))

VALID_SCOPES = ("private", "shared", "project", "global")
_lock = threading.RLock()


def _ensure_root() -> None:
    os.makedirs(CTX_ROOT, exist_ok=True)


def _load_manifest() -> Dict[str, Any]:
    _ensure_root()
    if not os.path.isfile(MANIFEST_PATH):
        return {"packages": {}}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("packages"), dict):
            return {"packages": {}}
        return data
    except (ValueError, OSError):
        return {"packages": {}}


def _save_manifest(data: Dict[str, Any]) -> None:
    _ensure_root()
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def _sanitize_name(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(name or "upload.bin")).strip("._") or "upload.bin"
    return clean[:120]


def _estimate_tokens(raw: bytes) -> int:
    """Grobe Näherung (~4 Zeichen/Token); fuer Text, sonst groesser."""
    try:
        text = raw.decode("utf-8")
        readable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
        if readable >= max(1, len(text) // 2):
            return max(1, len(text) // 4)
    except UnicodeDecodeError:
        pass
    return max(1, len(raw) // 1024)


def _is_expired(meta: Dict[str, Any]) -> bool:
    ttl = meta.get("ttl_seconds") or 0
    if not ttl:
        return False
    created = str(meta.get("created_at") or "")
    try:
        ts = datetime.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return (datetime.datetime.now(datetime.timezone.utc).timestamp() - ts) > float(ttl)


def create_package(
    raw: bytes,
    original_name: str,
    *,
    scope: str = "project",
    acl: Optional[List[str]] = None,
    ttl_seconds: Optional[int] = None,
    description: str = "",
) -> Dict[str, Any]:
    """Legt ein Kontext-Paket an und gibt seine Metadaten (inkl. Referenz-ID) zurueck."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("Leerer Upload.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Upload ueberschreitet das Limit von {MAX_UPLOAD_BYTES // (1024*1024)} MB.")
    scope = scope if scope in VALID_SCOPES else "project"

    with _lock:
        ctx_id = "ctx_" + secrets.token_hex(6)
        pdir = os.path.join(CTX_ROOT, ctx_id)
        os.makedirs(pdir, exist_ok=True)
        filename = _sanitize_name(original_name)
        dest = safe_path_within(os.path.join(pdir, filename), [CTX_ROOT], allow_write=True, allow_dirs=False)
        with open(dest, "wb") as fh:
            fh.write(raw)

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        meta: Dict[str, Any] = {
            "id": ctx_id,
            "original_name": str(original_name or "upload.bin")[:200],
            "filename": filename,
            "path": dest,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "tokens_est": _estimate_tokens(raw),
            "scope": scope,
            "acl": [str(a) for a in (acl or [])],
            "ttl_seconds": int(ttl_seconds or 0),
            "description": str(description or "")[:500],
            "created_at": now,
        }
        manifest = _load_manifest()
        manifest["packages"][ctx_id] = meta
        _save_manifest(manifest)
        return dict(meta)


def get_package(ctx_id: str) -> Optional[Dict[str, Any]]:
    manifest = _load_manifest()
    meta = manifest["packages"].get(str(ctx_id))
    if not meta:
        return None
    if _is_expired(meta):
        return None
    if not os.path.isfile(str(meta.get("path") or "")):
        return None
    return dict(meta)


def resolve_path(ctx_id: str) -> str:
    meta = get_package(ctx_id)
    return str(meta.get("path") or "") if meta else ""


def list_packages(*, agent_id: str = "", scope: Optional[str] = None) -> List[Dict[str, Any]]:
    manifest = _load_manifest()
    out: List[Dict[str, Any]] = []
    for meta in manifest["packages"].values():
        if _is_expired(meta) or not os.path.isfile(str(meta.get("path") or "")):
            continue
        row = dict(meta)
        row.pop("path", None)  # interner Pfad bleibt serverseitig
        out.append(row)
    return sorted(out, key=lambda m: str(m.get("created_at") or ""), reverse=True)


def delete_package(ctx_id: str) -> bool:
    with _lock:
        manifest = _load_manifest()
        meta = manifest["packages"].pop(str(ctx_id), None)
        if not meta:
            return False
        _save_manifest(manifest)
        pdir = os.path.join(CTX_ROOT, str(ctx_id))
        try:
            import shutil
            shutil.rmtree(pdir)
        except OSError:
            pass
        return True


_CTX_RE = re.compile(r"\bctx_[a-f0-9]{12}\b")


def resolve_context_refs(value: Any) -> Any:
    """Ersetzt `ctx_<id>` in Strings durch den abgelegten Dateipfad (rekursiv)."""
    if isinstance(value, str):
        def _sub(match: Any) -> str:
            path = resolve_path(match.group(0))
            return path or match.group(0)  # fehlende Referenz bleibt sichtbar
        return _CTX_RE.sub(_sub, value)
    if isinstance(value, list):
        return [resolve_context_refs(item) for item in value]
    if isinstance(value, dict):
        return {k: resolve_context_refs(v) for k, v in value.items()}
    return value


context_package_manager = None  # funktionaler Service, kein Zustand ausser Manifest
