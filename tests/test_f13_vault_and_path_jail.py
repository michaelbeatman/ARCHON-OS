"""F13 (D03): Atomarer Vault-Entwurf + Path-Jail via is_relative_to (kein startswith-Bypass)."""
from __future__ import annotations

from types import SimpleNamespace

from backend.operations_projects import resolve_task_obsidian_rel, safe_path_within


def test_f13_path_jail_blocks_sibling_prefix_bypass(tmp_path, monkeypatch):
    """Negativprobe: ../<vault>_evil/proj darf trotz identischem String-Prefix nie durchgehen."""
    vault = tmp_path / "vault"
    vault_evil = tmp_path / "vault_evil" / "proj"
    vault_ok = vault / "01_PROJEKTE" / "good_proj"
    vault_evil.mkdir(parents=True)
    vault_ok.mkdir(parents=True)

    # 1. Direkt auf safe_path_within
    assert safe_path_within(vault, "../vault_evil/proj") is None
    assert safe_path_within(vault, "01_PROJEKTE/good_proj") == vault_ok.resolve()

    # 2. Ueber resolve_task_obsidian_rel mit manipuliertem kanban_meta
    import backend.post_task_pipeline as ptp

    monkeypatch.setattr(ptp, "get_vault_dir", lambda: str(vault))
    deps = SimpleNamespace(
        load_kanban_meta=lambda: {
            "tasks": {
                "t-evil": {"obsidian": "../vault_evil/proj"},
                "t-ok": {"obsidian": "01_PROJEKTE/good_proj"},
            }
        },
        get_kanban_connection=lambda: (_ for _ in ()).throw(RuntimeError("no db")),
    )
    assert resolve_task_obsidian_rel("t-evil", deps) is None
    assert resolve_task_obsidian_rel("t-ok", deps) == "01_PROJEKTE/good_proj"
