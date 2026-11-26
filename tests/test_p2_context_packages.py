"""Regressionstests: referenzierte Kontext-Pakete fuer Workflow-Stationen."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _ctx(tmp_path, monkeypatch):
    import backend.context_packages as cp

    root = str(tmp_path / "context_packages")
    monkeypatch.setattr(cp, "CTX_ROOT", root)
    monkeypatch.setattr(cp, "MANIFEST_PATH", str(Path(root) / "manifest.json"))
    return cp


def test_p2_context_package_create_and_resolve(tmp_path, monkeypatch):
    cp = _ctx(tmp_path, monkeypatch)
    raw = b"Wir haben 12% Steigerung in 30 Tagen erzielt.\n" * 20
    meta = cp.create_package(raw, "../../../studie.txt", scope="project", acl=["micha"])
    assert meta["id"].startswith("ctx_")
    assert Path(meta["path"]).is_file()
    assert ".." not in Path(meta["path"]).name
    assert meta["sha256"] == hashlib.sha256(raw).hexdigest()
    assert meta["tokens_est"] > 0

    assert cp.get_package(meta["id"])["original_name"] == "../../../studie.txt"
    assert cp.resolve_path(meta["id"]) == meta["path"]
    resolved = cp.resolve_context_refs({"input": f"Datei: {meta['id']}", "x": [meta["id"]]})
    assert resolved["input"] == f"Datei: {meta['path']}"
    assert resolved["x"] == [meta["path"]]


def test_p2_context_package_list_and_delete(tmp_path, monkeypatch):
    cp = _ctx(tmp_path, monkeypatch)
    meta = cp.create_package(b"hello world", "hello.txt")
    listed = cp.list_packages()
    assert len(listed) == 1
    assert "path" not in listed[0]
    assert cp.delete_package(meta["id"]) is True
    assert cp.list_packages() == []
    assert cp.delete_package(meta["id"]) is False


def test_p2_context_package_router_registered():
    import warnings

    import main

    router_src = (REPO_ROOT / "archon" / "routers" / "context_packages.py").read_text(encoding="utf-8")
    assert '@router.post("/api/context-packages")' in router_src
    assert "require_admin_or_503(request)" in router_src
    # G7-Migration (2d, ANALYSIS §6 #5 / Anhang D.2 „Umstellung auf V, nicht
    # Loeschen"): die beiden main.py-Quelltext-Strings ('from ... import router
    # as _context_packages_router' und 'app.include_router(...)') wuerden beim
    # Router-Split brechen (Handoff-Falle #5). Stattdessen wird die ECHTE
    # Registrierung in der App geprueft: der Endpunkt muss im OpenAPI-Schema
    # vorhanden sein. Rot, sobald der Router nicht mehr eingebunden ist —
    # unabhaengig davon, in welchem Modul include_router steht.
    # Hinweis: app.routes ist dafuer ungeeignet (FastAPI kapselt include_router
    # in _IncludedRouter mit leerem .path) -> app.openapi()["paths"].
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        paths = main.app.openapi()["paths"]
    assert "/api/context-packages" in paths
    assert "post" in paths["/api/context-packages"]
