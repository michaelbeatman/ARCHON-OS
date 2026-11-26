"""W1-A (D03-H1 / D03-M1) — Regressionstests.

D03-H1: Vault-Tenant-Resolver fail-closed (kein stillen ``default``-Fallback,
kein Zugriff auf die globale Vault-Wurzel, Primärmandanten mit eigenem Ordner).
D03-M1: finaler Synthese-Bericht atomar + JEDER Ziel-Fehler -> ``blocked``.

Kein PostgreSQL, kein Coroutine-Replay (docs/system/NEVER_DO_LIST.md).
"""
from __future__ import annotations

import hashlib
import os
import sys
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from archon.core import orchestration as orch  # noqa: E402
from archon.routers import vault  # noqa: E402
from backend.tenant_context import tenant_context  # noqa: E402


def _fake_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def _raise(exc: Exception):
    def _boom(*_args, **_kwargs):
        raise exc
    return _boom


@pytest.fixture
def vault_env(monkeypatch, tmp_path):
    """Isolierte Vault-Wurzel ohne main.py-Override."""
    monkeypatch.delitem(sys.modules, "main", raising=False)
    root = tmp_path / "obsidian"
    root.mkdir()
    monkeypatch.setattr(vault, "OBSIDIAN_VAULT_DIR", str(root))
    monkeypatch.setattr(vault, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(vault, "_get_vault_cache", lambda: {"ts": 0.0, "data": []})
    return vault, root


# ---------------------------------------------------------------------------
# D03-H1 — fail-closed Resolver
# ---------------------------------------------------------------------------


def test_resolver_exception_is_hard_error(vault_env, monkeypatch):
    """Resolver wirft -> RuntimeError, kein 'default'-Fallback, kein Vault-Pfad."""
    _v, _root = vault_env
    monkeypatch.setattr(tenant_context, "get_active_tenant_id", _raise(RuntimeError("resolver down")))

    with pytest.raises(RuntimeError, match="nicht aufloesbar"):
        vault._active_tenant_id()
    with pytest.raises(RuntimeError, match="nicht aufloesbar"):
        vault._get_vault_dir()


@pytest.mark.parametrize("empty", [None, "", "  ", "../outside", "a/b", ".."])
def test_invalid_tenant_ids_are_rejected(vault_env, monkeypatch, empty):
    _v, _root = vault_env
    monkeypatch.setattr(tenant_context, "get_active_tenant_id", lambda: empty)

    with pytest.raises(RuntimeError):
        vault._active_tenant_id()
    with pytest.raises(RuntimeError):
        vault._get_vault_dir()


def test_vault_endpoints_deny_when_resolver_fails(vault_env, monkeypatch):
    """KEIN Lesen/Schreiben/Loeschen in der globalen Wurzel bei Resolverfehler."""
    _v, root = vault_env
    global_note = root / "global.md"
    global_note.write_text("GLOBAL-SECRET", encoding="utf-8")
    monkeypatch.setattr(tenant_context, "get_active_tenant_id", _raise(RuntimeError("resolver down")))
    request = _fake_request()

    with pytest.raises(HTTPException) as files_exc:
        vault.api_get_vault_files(request)
    assert files_exc.value.status_code == 500

    with pytest.raises(HTTPException) as read_exc:
        vault.api_read_vault_file_direct(path=str(global_note), request=request)
    assert read_exc.value.status_code == 500

    with pytest.raises(HTTPException) as edit_exc:
        vault.api_edit_vault_file_direct(request, {"path": str(global_note), "content": "pwned"})
    assert edit_exc.value.status_code == 500
    assert global_note.read_text(encoding="utf-8") == "GLOBAL-SECRET"

    with pytest.raises(HTTPException) as del_exc:
        vault.api_delete_vault_file_direct(request, str(global_note))
    assert del_exc.value.status_code == 500
    assert global_note.is_file()


def test_cached_listing_does_not_bypass_failed_resolver(vault_env, monkeypatch):
    """Ein warmer Cache darf einen Resolverausfall nicht maskieren."""
    _v, root = vault_env
    cache = {"ts": 9999999999.0, "data": [{"name": "cached.md"}], "tenant": "tenant_alpha"}
    monkeypatch.setattr(vault, "_get_vault_cache", lambda: cache)
    monkeypatch.setattr(tenant_context, "get_active_tenant_id", _raise(RuntimeError("resolver down")))

    with pytest.raises(HTTPException) as exc:
        vault.api_get_vault_files(_fake_request())
    assert exc.value.status_code == 500


@pytest.mark.parametrize("tid", ["default", "archon-systems", "tenant_alpha"])
def test_vault_dir_is_always_root_over_tenant(vault_env, monkeypatch, tid):
    """Auch Primärmandanten bekommen einen eigenen Ordner; nie die globale Wurzel."""
    _v, root = vault_env
    monkeypatch.setattr(tenant_context, "get_active_tenant_id", lambda: tid)

    d = vault._get_vault_dir()
    assert os.path.normpath(d) == os.path.normpath(str(root / tid))
    assert os.path.isdir(d)
    assert d != str(root)


def test_file_listing_is_scoped_to_tenant(vault_env, monkeypatch):
    """Globale Notizen appear nicht in der Mandantenliste."""
    _v, root = vault_env
    (root / "global.md").write_text("global", encoding="utf-8")
    tenant_dir = root / "tenant_alpha"
    tenant_dir.mkdir()
    (tenant_dir / "own.md").write_text("own", encoding="utf-8")
    monkeypatch.setattr(tenant_context, "get_active_tenant_id", lambda: "tenant_alpha")

    files = vault.api_get_vault_files(_fake_request())
    assert [f["name"] for f in files] == ["own.md"]
    assert all(str(root / "tenant_alpha") in f["path"] for f in files)


# ---------------------------------------------------------------------------
# D03-M1 — atomarer Finalbericht, Teilfehler -> blocked
# ---------------------------------------------------------------------------


def _finalize_kwargs(data, tmp_path, *, vault_root=None, workspace=None, projekte=None):
    def _update_mc(merger):
        merger(data)
        return data

    dispatcher = Mock()
    dispatcher.trigger_n8n_execution = Mock(return_value={"status": "ok"})
    return dict(
        dispatcher=dispatcher,
        load_mc=lambda: data,
        save_mc=Mock(),
        update_mc=_update_mc,
        ticker=Mock(),
        paths={
            "OBSIDIAN_VAULT_DIR": str(vault_root or (tmp_path / "vault")),
            "WORKSPACE_DIR": str(workspace or (tmp_path / "workspace")),
        },
        folder_namer=lambda _x: "",
        set_status=Mock(),
        tg_ping=Mock(),
    )


def _parent_data():
    return {
        "tasks": [{"id": "p1", "title": "Projekt", "status": "in_progress", "phase": "staffing"}],
        "metrics": {},
        "audit_logs": [],
    }


@pytest.mark.asyncio
async def test_final_report_is_written_atomically(monkeypatch, tmp_path):
    """Temp+fsync+replace: alle Ziele erhalten exakt den Inhalt, keine .tmp-Reste."""
    monkeypatch.setattr(orch, "PROJEKTE_DIR", str(tmp_path / "projekte"))
    data = _parent_data()
    kwargs = _finalize_kwargs(data, tmp_path)

    await orch._finalize_synthesis_after_approval("p1", "/fake/draft.md", "SYNTHESE", "Robert: OK", **kwargs)

    parent = data["tasks"][0]
    assert parent["status"] == "completed"
    assert parent["synthesis_finalized"] is True
    expected = ("# Finale Beschlussvorlage: Projekt\n\nSYNTHESE\n\n---\n"
                "**Freigabe:** Robert: OK\n")
    expected_sha = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    targets = [
        tmp_path / "projekte" / "p1_final_beschlussvorlage.md",
        tmp_path / "vault" / "01_PROJEKTE" / "p1_final_beschlussvorlage.md",
        tmp_path / "workspace" / "obsidian_vault" / "01_PROJEKTE" / "p1_final_beschlussvorlage.md",
    ]
    for p in targets:
        assert p.is_file()
        assert p.read_text(encoding="utf-8") == expected
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected_sha
    assert not list(tmp_path.rglob("*.tmp*"))


@pytest.mark.asyncio
async def test_partial_target_failure_blocks_task(monkeypatch, tmp_path, caplog):
    """Ein Ziel scheitert -> blocked + failure_reason, auch wenn andere Ziele OK sind."""
    monkeypatch.setattr(orch, "PROJEKTE_DIR", str(tmp_path / "projekte"))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    # 01_PROJEKTE als DATEI: os.makedirs muss genau fuer dieses Ziel scheitern.
    (vault_root / "01_PROJEKTE").write_text("blockiert", encoding="utf-8")
    data = _parent_data()
    kwargs = _finalize_kwargs(data, tmp_path)

    await orch._finalize_synthesis_after_approval("p1", "/fake/draft.md", "SYNTHESE", "note", **kwargs)

    parent = data["tasks"][0]
    assert parent["status"] == "blocked"
    assert parent["phase"] == "blocked"
    assert parent["artifact_path"] == ""
    assert parent["synthesis_finalized"] is False
    assert "01_PROJEKTE" in (parent.get("failure_reason") or "")
    assert any("Atomares Schreiben des Finalberichts" in r.message for r in caplog.records)
    # Das erfolgreiche Ziel bleibt atomar abgelegt, wird aber nicht als Erfolg quittiert.
    assert (tmp_path / "projekte" / "p1_final_beschlussvorlage.md").is_file()
    assert not list(tmp_path.rglob("*.tmp*"))


@pytest.mark.asyncio
async def test_all_targets_failing_blocks_with_reason(monkeypatch, tmp_path):
    """Alle Ziele unwritable -> blocked mit failure_reason (kein 'written=True')."""
    monkeypatch.setattr(orch, "PROJEKTE_DIR", str(tmp_path / "projekte"))
    blockers = [
        tmp_path / "projekte",
        tmp_path / "vault" / "01_PROJEKTE",
        tmp_path / "workspace" / "obsidian_vault" / "01_PROJEKTE",
    ]
    for b in blockers:
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_text("datei-statt-ordner", encoding="utf-8")
    data = _parent_data()
    kwargs = _finalize_kwargs(data, tmp_path)

    await orch._finalize_synthesis_after_approval("p1", "/fake/draft.md", "SYNTHESE", "note", **kwargs)

    parent = data["tasks"][0]
    assert parent["status"] == "blocked"
    assert parent["synthesis_finalized"] is False
    assert parent["failure_reason"]
