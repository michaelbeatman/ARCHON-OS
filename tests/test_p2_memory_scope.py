"""Batch C: Agent-Memory-Scope (private/shared/project/global), ACL und TTL.

Offline-Tests mit tmp_path-DBs; kein Netz, kein API-Key, keine echte Repo-DB.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _core(tmp_path, monkeypatch):
    """Core-Memory-Modul auf eine frische Temp-DB umstellen."""
    from backend import core_memory_manager as cmm

    monkeypatch.setattr(cmm, "DB_PATH", str(tmp_path / "core_mem.db"))
    cmm._init_db()  # Schema in der Temp-DB anlegen
    return cmm.core_memory_manager


def _vault(tmp_path):
    db = str(tmp_path / "vault.db")
    key = b"0123456789abcdef" * 2  # 32 Byte, deterministisch
    return db, key


def _keys(result):
    return [b["block_key"] for b in result["blocks"]]


def _ids(result):
    return [h["id"] for h in result]


def test_p2_scope_constants_canonical_and_mirrored():
    from backend import core_memory_manager as cmm
    from backend import offline_memory_vault as vault

    assert (cmm.SCOPE_PRIVATE, cmm.SCOPE_SHARED, cmm.SCOPE_PROJECT, cmm.SCOPE_GLOBAL) == (
        "private", "shared", "project", "global",
    )
    assert cmm.VALID_MEMORY_SCOPES == vault.VALID_MEMORY_SCOPES
    assert set(cmm.VALID_MEMORY_SCOPES) == {"private", "shared", "project", "global"}


def test_p2_core_private_isolation_between_agents(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    cmm.upsert_block("secret", "Nur fuer Agent A", agent_id="agent-a", scope="private")

    keys_a = _keys(cmm.list_blocks(agent_id="agent-a"))
    keys_b = _keys(cmm.list_blocks(agent_id="agent-b"))
    assert any("secret" in k for k in keys_a)
    assert not any("secret" in k for k in keys_b)
    assert "<secret" not in cmm.compile_system_prompt_injection(agent_id="agent-b")
    assert "secret" in cmm.compile_system_prompt_injection(agent_id="agent-a")


def test_p2_core_shared_visible_via_acl_only(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    cmm.upsert_block(
        "shared_note", "Team-Notiz", agent_id="owner",
        scope="shared", acl=["agent-b"],
    )

    keys_owner = _keys(cmm.list_blocks(agent_id="owner"))
    keys_b = _keys(cmm.list_blocks(agent_id="agent-b"))
    keys_c = _keys(cmm.list_blocks(agent_id="agent-c"))
    assert any("shared_note" in k for k in keys_owner)
    assert any("shared_note" in k for k in keys_b)
    assert not any("shared_note" in k for k in keys_c)


def test_p2_core_global_visible_to_all_agents(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    cmm.upsert_block("public_note", "Oeffentlich", agent_id="author", scope="global")

    for agent in ("author", "agent-b", "agent-z"):
        assert any("public_note" in k for k in _keys(cmm.list_blocks(agent_id=agent)))


def test_p2_core_project_scoping(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    cmm.upsert_block(
        "proj_fact", "Nur Projekt X", agent_id="author",
        scope="project", project_id="proj-x",
    )

    assert any("proj_fact" in k for k in _keys(
        cmm.list_blocks(agent_id="agent-b", project_id="proj-x")
    ))
    assert not any("proj_fact" in k for k in _keys(
        cmm.list_blocks(agent_id="agent-b", project_id="proj-y")
    ))
    assert not any("proj_fact" in k for k in _keys(
        cmm.list_blocks(agent_id="agent-b", project_id="")
    ))


def test_p2_core_ttl_expiry_excluded(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    cmm.upsert_block("expiring", "Laeuft ab", agent_id="author", ttl_seconds=60)
    cmm.upsert_block("lasting", "Bleibt", agent_id="author")

    from backend import core_memory_manager as cmm_mod
    with sqlite3.connect(cmm_mod.DB_PATH) as conn:
        conn.execute(
            "UPDATE core_memory_blocks SET expires_at = ? WHERE block_key LIKE '%expiring%'",
            (time.time() - 10.0,),
        )
        conn.commit()

    keys = _keys(cmm.list_blocks(agent_id="agent-b"))
    assert any("lasting" in k for k in keys)
    assert not any("expiring" in k for k in keys)
    assert "expiring" not in cmm.compile_system_prompt_injection(agent_id="agent-b")


def test_p2_core_scope_filter_parameter(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    cmm.upsert_block("pub", "Oeffentlich", agent_id="author", scope="global")
    cmm.upsert_block("priv", "Privat", agent_id="author", scope="private")

    all_keys = _keys(cmm.list_blocks(agent_id="author"))
    private_keys = _keys(cmm.list_blocks(agent_id="author", scope="private"))
    assert any("pub" in k for k in all_keys)
    assert any("priv" in k for k in all_keys)
    assert not any("pub" in k for k in private_keys)
    assert any("priv" in k for k in private_keys)


def test_p2_core_schema_migration_from_legacy_db(tmp_path, monkeypatch):
    from backend import core_memory_manager as cmm

    db = tmp_path / "legacy_core.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE core_memory_blocks (
                block_key TEXT PRIMARY KEY,
                block_title TEXT,
                content TEXT,
                pinned INTEGER DEFAULT 1,
                updated_at TEXT,
                agent_id TEXT DEFAULT 'global',
                tenant_id TEXT DEFAULT 'default'
            )
        """)
        conn.execute(
            """INSERT INTO core_memory_blocks
               (block_key, block_title, content, pinned, updated_at, agent_id, tenant_id)
               VALUES (?, ?, ?, 1, ?, ?, ?)""",
            ("legacy_note", "Alt", "Legacy-Inhalt", "2024-01-01 00:00:00", "agent-old", "default"),
        )
        conn.commit()

    monkeypatch.setattr(cmm, "DB_PATH", str(db))
    cmm._init_db()

    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(core_memory_blocks)")}
        assert {"scope", "acl_json", "expires_at", "project_id", "scope_explicit"} <= cols
        assert conn.execute(
            "SELECT scope, scope_explicit FROM core_memory_blocks WHERE block_key = 'legacy_note'"
        ).fetchone() == ("global", 0)

    # Legacy-Zeile: alter agent_id-Fallback bleibt wirksam.
    manager = cmm.core_memory_manager
    assert any("legacy_note" in k for k in _keys(manager.list_blocks(agent_id="agent-old")))
    assert not any("legacy_note" in k for k in _keys(manager.list_blocks(agent_id="agent-new")))


def test_p2_vault_private_and_shared_via_acl(tmp_path):
    from backend.offline_memory_vault import recall_memory, store_memory

    db, key = _vault(tmp_path)
    ns = "team"
    private_id = store_memory(ns, "Geheimnis A", db_path=db, key=key,
                              scope="private", agent_id="agent-a")
    shared_id = store_memory(ns, "Geteilte Notiz", db_path=db, key=key,
                             scope="shared", acl=["agent-b"], agent_id="owner")

    a = _ids(recall_memory(ns, "Notiz", db_path=db, key=key, agent_id="agent-a"))
    b = _ids(recall_memory(ns, "Notiz", db_path=db, key=key, agent_id="agent-b"))
    c = _ids(recall_memory(ns, "Notiz", db_path=db, key=key, agent_id="agent-c"))
    owner = _ids(recall_memory(ns, "Notiz", db_path=db, key=key, agent_id="owner"))
    assert private_id in a and private_id not in b and private_id not in c
    assert shared_id in b and shared_id in owner  # ACL-Mitglied + Eigentuemer
    assert shared_id not in a and shared_id not in c


def test_p2_vault_global_and_project_scoping(tmp_path):
    from backend.offline_memory_vault import recall_memory, store_memory

    db, key = _vault(tmp_path)
    ns = "proj"
    global_id = store_memory(ns, "Vault oeffentlich", db_path=db, key=key,
                             scope="global", agent_id="author")
    project_id = store_memory(ns, "Vault Projekt X", db_path=db, key=key,
                              scope="project", project_id="proj-x", agent_id="author")

    everyone = _ids(recall_memory(ns, "Vault", db_path=db, key=key, agent_id="agent-z"))
    assert global_id in everyone
    assert project_id not in everyone
    assert project_id in _ids(recall_memory(ns, "Vault", db_path=db, key=key,
                                            agent_id="agent-z", project_id="proj-x"))
    assert project_id not in _ids(recall_memory(ns, "Vault", db_path=db, key=key,
                                                agent_id="agent-z", project_id="proj-y"))


def test_p2_vault_scope_filter_and_ttl_expiry(tmp_path):
    from backend.offline_memory_vault import recall_memory, store_memory

    db, key = _vault(tmp_path)
    ns = "ttl"
    public_id = store_memory(ns, "Vault public", db_path=db, key=key, scope="global")
    expiring_id = store_memory(ns, "Vault expiring", db_path=db, key=key,
                               scope="global", ttl_seconds=60)

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE vault_entries SET expires_at = ? WHERE id = ?",
            (time.time() - 10.0, expiring_id),
        )
        conn.commit()

    hits = _ids(recall_memory(ns, "Vault", db_path=db, key=key))
    assert public_id in hits and expiring_id not in hits
    assert _ids(recall_memory(ns, "Vault", db_path=db, key=key, scope="private")) == []


def test_p2_vault_schema_migration_keeps_legacy_rows_visible(tmp_path):
    from backend.offline_memory_vault import aead_encrypt, recall_memory

    db, key = _vault(tmp_path)
    ns = "legacy"
    cipher = aead_encrypt(key, b'{"content": "Alter Vault-Eintrag", "tags": [], "vec": [0.0]}',
                          aad=ns.encode("utf-8"))
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE vault_entries (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                cipher_blob BLOB NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO vault_entries (id, namespace, cipher_blob, created_at) VALUES (?, ?, ?, ?)",
            ("mem-legacy", ns, cipher, time.time()),
        )
        conn.commit()

    hits = recall_memory(ns, "Alter Vault-Eintrag", db_path=db, key=key, agent_id="agent-x")
    assert "mem-legacy" in _ids(hits)
    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(vault_entries)")}
    assert {"scope", "acl_json", "expires_at", "project_id", "agent_id", "scope_explicit"} <= cols


def test_p2_invalid_scope_rejected_everywhere(tmp_path, monkeypatch):
    cmm = _core(tmp_path, monkeypatch)
    db, key = _vault(tmp_path)

    with pytest.raises(ValueError, match="Ungueltiger Memory-Scope"):
        cmm.upsert_block("bad", "x", scope="nonsense")
    with pytest.raises(ValueError, match="Ungueltiger Memory-Scope"):
        cmm.list_blocks(scope="nonsense")
    with pytest.raises(ValueError, match="Ungueltiger Memory-Scope"):
        cmm.compile_system_prompt_injection(scope="nonsense")
    with pytest.raises(ValueError, match="Ungueltiger Memory-Scope"):
        from backend.offline_memory_vault import store_memory
        store_memory("ns", "x", db_path=db, key=key, scope="nonsense")
    with pytest.raises(ValueError, match="Ungueltiger Memory-Scope"):
        from backend.offline_memory_vault import recall_memory
        recall_memory("ns", "x", db_path=db, key=key, scope="nonsense")


def test_p2_router_rejects_invalid_scope_with_400():
    from fastapi import HTTPException

    from archon.routers.memory import _validate_scope

    assert _validate_scope("private") == "private"
    assert _validate_scope(None) is None
    with pytest.raises(HTTPException) as exc:
        _validate_scope("nonsense")
    assert exc.value.status_code == 400
