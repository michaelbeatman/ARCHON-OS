"""
Obsidian Vault Router fuer Archon OS.
Verwaltet /api/vault/ Endpunkte (Dateiliste, Lesen, Bearbeiten, Loeschen, Index).
Extrahiert aus main.py zur Modularisierung.
"""

import hashlib
import os
import sys
import tempfile
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi import Depends as _ArchonDepends

from archon.core.runtime import OBSIDIAN_VAULT_DIR, logger
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_admin_or_503
from archon.routers._validated_body import PassthroughBody, as_payload
from utils.path_jail import PathJailError, safe_path, safe_path_within

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["vault"])

_VAULT_FILES_CACHE: Dict[str, Any] = {"ts": 0.0, "data": []}


def _atomic_write_text(
    path: str,
    content: str,
    *,
    expected_mtime: Optional[float] = None,
    expected_size: Optional[int] = None,
    expected_hash: Optional[str] = None,
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
            # Austausch — unter demselben Lock wie der Replace. Der Hash ist
            # das dritte Merkmal: mtime+size allein erkennen eine Aenderung
            # gleicher Laenge innerhalb derselben Zeiteinheit nicht. Ein
            # zwischenzeitlich geloeschtes File ist ebenfalls ein Konflikt.
            if any(v is not None for v in (expected_mtime, expected_size, expected_hash)):
                try:
                    st = os.stat(path)
                    if expected_mtime is not None and abs(st.st_mtime - float(expected_mtime)) > 0.001:
                        raise HTTPException(
                            status_code=409, detail="Vault-Datei wurde inzwischen geaendert."
                        )
                    if expected_size is not None and st.st_size != int(expected_size):
                        raise HTTPException(
                            status_code=409, detail="Vault-Datei wurde inzwischen geaendert (Groesse)."
                        )
                    if expected_hash is not None:
                        with open(path, "rb") as fh:
                            actual = hashlib.sha256(fh.read()).hexdigest()
                        if actual != str(expected_hash).strip().lower():
                            raise HTTPException(
                                status_code=409, detail="Vault-Datei wurde inzwischen geaendert (Hash)."
                            )
                except FileNotFoundError:
                    raise HTTPException(
                        status_code=409, detail="Vault-Datei wurde inzwischen geloescht."
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


def _checked_tenant_id(tid: Any) -> str:
    """D03-H1: Mandanten-ID validieren, bevor sie Teil eines Vault-Pfads wird."""
    if not isinstance(tid, str) or not tid.strip():
        raise RuntimeError("Vault: aktiver Mandant ist leer — Vault-Zugriff verweigert.")
    cleaned = tid.strip()
    if cleaned in (".", "..") or "/" in cleaned or "\\" in cleaned or "\x00" in cleaned:
        raise RuntimeError(f"Vault: ungueltige Mandanten-ID {tid!r} — Zugriff verweigert.")
    return cleaned


def _active_tenant_id() -> str:
    """D03-H1: aktiver Mandant, fail-closed.

    Frueher fiel ein Resolverfehler still auf ``"default"`` zurueck; damit landete
    ein Mandant im Vault eines anderen bzw. im gemeinsamen Vault. Ein Fehler oder
    eine leere/ungueltige ID ist jetzt ein harter Fehler ohne jeden Fallback.
    """
    try:
        from backend.tenant_context import tenant_context
        tid = tenant_context.get_active_tenant_id()
    except Exception as exc:
        raise RuntimeError(f"Vault: aktiver Mandant nicht aufloesbar: {exc}") from exc
    return _checked_tenant_id(tid)


def _get_vault_dir(tenant_id: Optional[str] = None) -> str:
    """Einzige, tenant-bewusste Vault-Wurzel für ALLE Vault-Endpunkte.

    D03-H1: immer ``<vault_root>/<tenant_id>``. Auch die Primärmandanten
    (``default``, ``archon-systems``) erhalten ihren eigenen Ordner; die globale
    Wurzel wird nie als Vault-Ziel zurueckgegeben. Ein Resolverfehler ist ein
    harter Fehler, kein stiller Fallback auf ``default``.
    """
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "OBSIDIAN_VAULT_DIR"):
        root = getattr(main_mod, "OBSIDIAN_VAULT_DIR")
    else:
        root = OBSIDIAN_VAULT_DIR
    tid = _checked_tenant_id(tenant_id if tenant_id is not None else _active_tenant_id())
    tenant_dir = os.path.join(root, tid)
    os.makedirs(tenant_dir, exist_ok=True)
    return tenant_dir


def _tenant_vault_context() -> tuple[str, str]:
    """D03-H1: (Mandant, Vault-Pfad) fuer Endpunkte; Resolverfehler => HTTP 500.

    Der Resolver wird VOR jeder Cache-Pruefung aufgerufen, damit ein zwischenzeitlich
    fehlgeschlagener Resolver nicht aus dem Cache heraus trotzdem Vault-Daten liefert.
    """
    try:
        tid = _active_tenant_id()
        return tid, _get_vault_dir(tid)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Vault-Mandant nicht aufloesbar — Zugriff verweigert: {exc}",
        ) from exc


def _audit_vault_mutation(action: str, path: str, tenant_id: str) -> None:
    """GoBD-Audit vor Vault-Änderungen. Bei Fehler fail-closed (kein Write)."""
    from backend.audit_log import chained_audit_log
    chained_audit_log.record_event(
        category="governance",
        action=action,
        agent_id=tenant_id,
        payload={
            "tenant_id": tenant_id,
            "vault_root": _get_vault_dir(tenant_id),
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
    # D03-H1: Resolver zuerst — kein gecachter Treffer bei fehlgeschlagener
    # Mandantenauflösung, kein Zugriff auf die globale Vault-Wurzel.
    _tenant_id, vault_dir = _tenant_vault_context()
    cache = _get_vault_cache()
    now = time.time()
    if (
        cache.get("tenant") == _tenant_id
        and cache.get("data")
        and (now - cache.get("ts", 0.0)) < 300.0
    ):
        return cache["data"]
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
def api_read_vault_file_direct(path: str = Query(...), request: Request = None):  # type: ignore[assignment]
    if request is not None:
        require_admin_or_503(request)
    _tid, vault_dir = _tenant_vault_context()
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
    data = as_payload(payload)
    path = data.get("path", "")
    content = data.get("content", "")
    if not path:
        raise HTTPException(status_code=400, detail="Pfad fehlt.")
    _tid, vault_dir = _tenant_vault_context()
    try:
        real_path = safe_path_within(
            path, [vault_dir], allow_write=True, allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=str(e))
    # C20: Turnier-Konflikterkennung — wenn der Client eine erwartete mtime
    # mitschickt und Obsidian inzwischen gespeichert hat, nicht ueberschreiben.
    expected_mtime = data.get("expected_mtime")
    if expected_mtime is not None and os.path.exists(real_path):
        try:
            if abs(float(os.path.getmtime(real_path)) - float(expected_mtime)) > 0.001:
                raise HTTPException(status_code=409, detail="Vault-Datei wurde inzwischen geaendert.")
        except (TypeError, ValueError):
            pass
    # H (dieses Audits): mtime allein ist kein ETag — eine Aenderung gleicher
    # Länge innerhalb derselben Sekunde blieb unbemerkt.
    expected_size = data.get("expected_size")
    if expected_size is not None and os.path.exists(real_path):
        try:
            if int(os.path.getsize(real_path)) != int(expected_size):
                raise HTTPException(status_code=409, detail="Vault-Datei wurde inzwischen geaendert (Groesse).")
        except (TypeError, ValueError):
            pass
    # D03/MED: SHA-256 als drittes Konfliktmerkmal (TOCTOU).
    expected_hash = data.get("expected_hash")
    if expected_hash is not None and os.path.exists(real_path):
        try:
            with open(real_path, "rb") as fh:
                actual_hash = hashlib.sha256(fh.read()).hexdigest()
            if actual_hash != str(expected_hash).strip().lower():
                raise HTTPException(status_code=409, detail="Vault-Datei wurde inzwischen geaendert (Hash).")
        except (OSError, TypeError, ValueError):
            pass
    # G: Audit vor der Mutation; ohne Auditnachweis wird abgelehnt.
    try:
        _audit_vault_mutation("vault_file_edited", real_path, _tid)
    except Exception as exc:
        logger.warning("[Vault] Audit fehlgeschlagen, Edit abgelehnt: %s", exc)
        raise HTTPException(status_code=500, detail="Audit-Log nicht verfügbar — Vault-Aenderung abgelehnt.")
    os.makedirs(os.path.dirname(real_path), exist_ok=True)
    _atomic_write_text(
        real_path, content,
        expected_mtime=expected_mtime,
        expected_size=expected_size,
        expected_hash=expected_hash,
    )
    cache = _get_vault_cache()
    cache["ts"] = 0.0
    return {"status": "success", "path": real_path}


@router.delete("/api/vault")
def api_delete_vault_file_direct(request: Request, path: str = Query(...)):
    require_admin_or_503(request)
    _tid, vault_dir = _tenant_vault_context()
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
        _audit_vault_mutation("vault_file_deleted", real_path, _tid)
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
