from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""
Obsidian Vault Router fuer Archon OS.
Verwaltet /api/vault/ Endpunkte (Dateiliste, Lesen, Bearbeiten, Loeschen, Index).
Extrahiert aus main.py zur Modularisierung.
"""

import os
import sys
import tempfile
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body, Request
from archon.routers._rbac import require_admin_or_503
from archon.core.runtime import logger, OBSIDIAN_VAULT_DIR
from utils.path_jail import safe_path, safe_path_within, PathJailError

from archon.routers._validated_body import PassthroughBody, as_payload
router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["vault"])

_VAULT_FILES_CACHE: Dict[str, Any] = {"ts": 0.0, "data": []}


def _atomic_write_text(
    path: str,
    content: str,
    *,
    expected_mtime: Optional[float] = None,
    expected_size: Optional[int] = None,
) -> None:
    """C20 + D03/MED: Temp+fsync+os.replace mit atomarer Konfliktprüfung.

    Der Vault-weite OS-Lock (SQLite-EXCLUSIVE auf einer separaten Lock-DB)
    serialisiert Schreibzugriffe ueber Prozessgrenzen. mtime/size werden
    UNMITTELBAR vor ``os.replace`` unter diesem Lock erneut geprueft; bei
    Abweichung HTTP 409 und kein Replace. Damit kann Obsidian nicht im Fenster
    zwischen Erstpruefung und Write dazwischenschreiben.
    """
    from backend.process_lock import try_acquire_loop_lock

    lock = try_acquire_loop_lock("vault_write", timeout=5.0)
    if lock is None:
        raise HTTPException(
            status_code=409,
            detail="Vault wird gerade von einem anderen Prozess geschrieben.",
        )
    try:
        tdir = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(tdir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=tdir, prefix=".vault_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            # D03/MED: Wiederholung der Konfliktprüfung direkt vor dem
            # Austausch — unter demselben Lock wie der Replace.
            if expected_mtime is not None and os.path.exists(path):
                try:
                    if abs(float(os.path.getmtime(path)) - float(expected_mtime)) > 0.001:
                        raise HTTPException(
                            status_code=409, detail="Vault-Datei wurde inzwischen geaendert."
                        )
                except (TypeError, ValueError):
                    pass
            if expected_size is not None and os.path.exists(path):
                try:
                    if int(os.path.getsize(path)) != int(expected_size):
                        raise HTTPException(
                            status_code=409, detail="Vault-Datei wurde inzwischen geaendert (Groesse)."
                        )
                except (TypeError, ValueError):
                    pass

            os.replace(tmp, path)
            # H (dieses Audits): ohne Directory-fsync kann der Rename nach
            # Stromausfall im FS-Journal verloren gehen (siehe db_backup_manager).
            try:
                dir_fd = os.open(tdir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        lock.release()


def _active_tenant_id() -> str:
    try:
        from backend.tenant_context import tenant_context
        return tenant_context.get_active_tenant_id() or "default"
    except Exception:
        return "default"


def _get_vault_dir() -> str:
    """Einzige, tenant-bewusste Vault-Wurzel für ALLE Vault-Endpunkte.

    G (dieses Audits): vorher war nur die Liste tenant-aware (nur als
    Cache-Key), Lese-/Schreib-/Löschpfade nutzten stets die globale Wurzel.
    Fail-closed: existiert <vault_root>/<tenant_id>, wird ausschliesslich
    dieser Mandantenordner verwendet. Andernfalls gilt der bewusst geteilte
    Vault; dann werden Mutationen zwingend auditiert (_audit_vault_mutation).
    """
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "OBSIDIAN_VAULT_DIR"):
        root = getattr(main_mod, "OBSIDIAN_VAULT_DIR")
    else:
        root = OBSIDIAN_VAULT_DIR
    tenant_dir = os.path.join(root, _active_tenant_id())
    if os.path.isdir(tenant_dir):
        return tenant_dir
    return root


def _audit_vault_mutation(action: str, path: str, tenant_id: str) -> None:
    """GoBD-Audit vor Vault-Änderungen. Bei Fehler fail-closed (kein Write)."""
    from backend.audit_log import chained_audit_log
    chained_audit_log.record_event(
        category="governance",
        action=action,
        agent_id=tenant_id,
        payload={
            "tenant_id": tenant_id,
            "vault_root": _get_vault_dir(),
            "path": path,
        },
    )


def _get_vault_cache() -> Dict[str, Any]:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_VAULT_FILES_CACHE"):
        return getattr(main_mod, "_VAULT_FILES_CACHE")
    return _VAULT_FILES_CACHE


@router.get("/api/vault/files")
def api_get_vault_files(request: Request):
    require_admin_or_503(request)
    cache = _get_vault_cache()
    now = time.time()
    _tenant_id = _active_tenant_id()
    if (
        cache.get("tenant") == _tenant_id
        and cache.get("data")
        and (now - cache.get("ts", 0.0)) < 300.0
    ):
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
    cache["tenant"] = _tenant_id
    return files


@router.get("/api/vault")
def api_get_vault_list(request: Request):
    files = api_get_vault_files(request)
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
def api_edit_vault_file_direct(request: Request, payload: PassthroughBody = Body(...)):
    require_admin_or_503(request)
    payload = as_payload(payload)
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
    # C20: Turnier-Konflikterkennung — wenn der Client eine erwartete mtime
    # mitschickt und Obsidian inzwischen gespeichert hat, nicht ueberschreiben.
    expected_mtime = payload.get("expected_mtime")
    if expected_mtime is not None and os.path.exists(real_path):
        try:
            if abs(float(os.path.getmtime(real_path)) - float(expected_mtime)) > 0.001:
                raise HTTPException(status_code=409, detail="Vault-Datei wurde inzwischen geaendert.")
        except (TypeError, ValueError):
            pass
    # H (dieses Audits): mtime allein ist kein ETag — eine Aenderung gleicher
    # Länge innerhalb derselben Sekunde blieb unbemerkt.
    expected_size = payload.get("expected_size")
    if expected_size is not None and os.path.exists(real_path):
        try:
            if int(os.path.getsize(real_path)) != int(expected_size):
                raise HTTPException(status_code=409, detail="Vault-Datei wurde inzwischen geaendert (Groesse).")
        except (TypeError, ValueError):
            pass
    # G: Audit vor der Mutation; ohne Auditnachweis wird abgelehnt.
    try:
        _audit_vault_mutation("vault_file_edited", real_path, _active_tenant_id())
    except Exception as exc:
        logger.warning("[Vault] Audit fehlgeschlagen, Edit abgelehnt: %s", exc)
        raise HTTPException(status_code=500, detail="Audit-Log nicht verfügbar — Vault-Aenderung abgelehnt.")
    os.makedirs(os.path.dirname(real_path), exist_ok=True)
    _atomic_write_text(
        real_path, content,
        expected_mtime=expected_mtime,
        expected_size=expected_size,
    )
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
    # G: Audit vor der Mutation; ohne Auditnachweis wird abgelehnt.
    try:
        _audit_vault_mutation("vault_file_deleted", real_path, _active_tenant_id())
    except Exception as exc:
        logger.warning("[Vault] Audit fehlgeschlagen, Delete abgelehnt: %s", exc)
        raise HTTPException(status_code=500, detail="Audit-Log nicht verfügbar — Vault-Löschung abgelehnt.")
    os.remove(real_path)
    cache = _get_vault_cache()
    cache["ts"] = 0.0
    return {"status": "success", "deleted": real_path}


@router.post("/api/vault/generate-index")
def api_generate_vault_index():
    from backend.vault_hygiene import generate_vault_index_and_hygiene
    return generate_vault_index_and_hygiene()
