# -*- coding: utf-8 -*-
"""
Strang A — Paket A4 Regressionstests:
DB-Konsolidierung (keine stillen Datenverluste bei PK-Kollision mit abweichendem
Inhalt), Resolver-Split-Brain-Fix zwischen FULL_TENANT_ISOLATION und
28->3-Konsolidierung.
Referenz: d03 / #20.
"""
import os
import sqlite3
import pytest


def test_db_consolidation_aborts_on_divergent_pk_collision_and_allows_idempotent_rerun(tmp_path):
    from backend.db_consolidation import run_consolidation

    src_dir_1 = tmp_path / "src1"
    src_dir_2 = tmp_path / "src2"
    tgt_dir = tmp_path / "target"
    src_dir_1.mkdir()
    src_dir_2.mkdir()
    tgt_dir.mkdir()

    # Zwei Quellen mit identischem Tabellenschema, aber kollidierender PK mit unterschiedlichem Inhalt
    db1 = src_dir_1 / "deals.db"
    db2 = src_dir_2 / "deals.db"

    for db_path, name in ((db1, "Alice"), (db2, "Bob")):
        con = sqlite3.connect(str(db_path))
        try:
            con.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY, partner TEXT NOT NULL)")
            con.execute("INSERT INTO deals (id, partner) VALUES (1, ?)", (name,))
            con.commit()
        finally:
            con.close()

    # 1. Einzelne Quelle konsolidieren -> Erfolg
    rep = run_consolidation(
        source_dirs=[str(src_dir_1)],
        target_dir=str(tgt_dir),
        create_backup=False,
        activate=False,
    )
    assert rep["status"] == "success"

    # 2. Idempotenter Zweitlauf derselben Quelle -> Erfolg (alle Spalten identisch)
    rep2 = run_consolidation(
        source_dirs=[str(src_dir_1)],
        target_dir=str(tgt_dir),
        create_backup=False,
        activate=False,
    )
    assert rep2["status"] == "success"

    # 3. Divergierende PK-Kollision (id=1, 'Bob' gegen bestehendes id=1, 'Alice') -> harter Abbruch!
    with pytest.raises(RuntimeError, match="DATENVERLUST"):
        run_consolidation(
            source_dirs=[str(src_dir_2)],
            target_dir=str(tgt_dir),
            create_backup=False,
            activate=False,
        )


def test_tenant_context_consolidation_works_under_full_tenant_isolation(tmp_path, monkeypatch):
    from backend import tenant_context as tc_mod

    data_root = tmp_path / "data"
    data_root.mkdir()
    mgr = tc_mod.TenantContextManager(workspace_dir=str(tmp_path))
    monkeypatch.setattr(tc_mod, "FULL_TENANT_ISOLATION", True)
    monkeypatch.setenv("ARCHON_DB_CONSOLIDATED", "1")

    tid = "tenant_a4"
    tdir = mgr.get_tenant_dir(tid)
    os.makedirs(tdir, exist_ok=True)
    cons_biz = os.path.join(tdir, "business.db")
    con = sqlite3.connect(cons_biz)
    try:
        con.execute("CREATE TABLE deals (id TEXT PRIMARY KEY)")
        con.commit()
    finally:
        con.close()

    resolved = mgr.resolve_active_db("deals.db", company_id=tid)
    assert os.path.abspath(resolved) == os.path.abspath(cons_biz)


def test_db_paths_resolve_db_does_not_call_tenant_resolver_for_system_dbs(tmp_path, monkeypatch):
    from backend import db_paths, tenant_context as tc_mod

    calls = []
    orig = tc_mod.tenant_context.resolve_active_db

    def _spy(db_filename, company_id=None):
        calls.append(db_filename)
        return orig(db_filename, company_id)

    monkeypatch.setattr(tc_mod, "FULL_TENANT_ISOLATION", True)
    monkeypatch.setattr(tc_mod.tenant_context, "resolve_active_db", _spy)
    monkeypatch.setattr(db_paths, "_RESOLVED_DB_CACHE", {})

    path = db_paths.resolve_db("agentic_memory.db")
    assert path.endswith("agentic_memory.db")
    assert "agentic_memory.db" not in calls
