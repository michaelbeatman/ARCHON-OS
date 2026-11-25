"""FIX W1-C (F012/F015) — Persistenz-, Vault- und Backup-Härtung.

Regressionstests für:
- Corporate-Manager fail-closed bei korrupter Stammdatei
- Offline-Vault: Tenant-Resolver fail-closed + Env-Key pro Mandant
- db_paths: connect-timeout-Drift im SSOT-Gate DEFAULT AN
- Backup-Skripte: konsolidierte DBs + Tenant-DBs zur Laufzeit, Guard bei 0
- Break-Glass: konsolidierte DBs + Tenant-DBs im Notfall-Vault
"""

import hashlib
import hmac
import inspect
import os
import sys

import pytest

import backend.db_paths as db_paths


def test_corporate_corrupt_file_is_never_overwritten(tmp_path):
    from backend.corporate_manager import CorporateManager

    profile = tmp_path / "corporate_profiles.json"
    profile.write_bytes(b'{"active_company_id": "archon-systems", "companies": [BROKEN')
    before = profile.read_bytes()

    manager = CorporateManager(filepath=str(profile))
    with pytest.raises(RuntimeError, match="nicht lesbar|kein Dict"):
        manager.save_company({"id": "new-company", "name": "Neue GmbH"})

    assert profile.read_bytes() == before


def test_corporate_missing_file_still_gets_default(tmp_path):
    from backend.corporate_manager import CorporateManager

    manager = CorporateManager(filepath=str(tmp_path / "fresh" / "profiles.json"))
    companies = manager.list_companies()
    assert any(c["id"] == "archon-systems" for c in companies)


def test_vault_tenant_resolver_is_fail_closed(tmp_path, monkeypatch):
    import backend.offline_memory_vault as vault
    import backend.tenant_context as tc

    def _boom():
        raise RuntimeError("resolver down")

    monkeypatch.setattr(tc.tenant_context, "get_active_tenant_id", _boom)
    with pytest.raises(RuntimeError, match="Tenant-Kontext"):
        vault.store_memory("ns", "geheim")
    with pytest.raises(RuntimeError, match="Tenant-Kontext"):
        vault.recall_memory("ns", "geheim")

    # Bestehende Legacy-API (explizite db+key) bleibt nutzbar.
    key = vault.load_or_create_vault_key(str(tmp_path / "v.key"))
    db = str(tmp_path / "v.db")
    eid = vault.store_memory("ns", "geheim", db_path=db, key=key)
    assert any(r["id"] == eid for r in vault.recall_memory("ns", "geheim", db_path=db, key=key))


def test_vault_env_key_is_derived_per_tenant(monkeypatch):
    import backend.offline_memory_vault as vault

    monkeypatch.setenv("COMPARTMENT_VAULT_KEY", "master-secret")
    key_a = vault.load_or_create_vault_key(tenant_id="tenant-a")
    key_b = vault.load_or_create_vault_key(tenant_id="tenant-b")

    master = hashlib.sha256(b"master-secret").digest()
    expected = hmac.new(master, b"tenant-a", hashlib.sha256).digest()
    assert key_a == expected
    assert key_a != key_b
    # Ohne tenant_id gibt es bewusst keinen globalen Key.
    with pytest.raises(RuntimeError, match="tenant_id"):
        vault.load_or_create_vault_key()


def test_connect_timeout_gate_is_on_by_default(tmp_path):
    assert (
        inspect.signature(db_paths.audit_busy_timeout_ssot)
        .parameters["include_connect_timeout"]
        .default
        is True
    )
    probe_dir = tmp_path / "backend"
    probe_dir.mkdir()
    # Literal zur Laufzeit zusammensetzen, damit dieser Test nicht selbst als
    # Drift-Beispiel vom SSOT-Gate gefunden wird.
    drift_value = "9" + ".5"
    (probe_dir / "probe.py").write_text(
        f"import sqlite3\nsqlite3.connect('x.db', timeout={drift_value})\n",
        encoding="utf-8",
    )
    offenders = db_paths.audit_busy_timeout_ssot(str(tmp_path))
    assert any("connect_timeout=9.5" in value for _, _, value in offenders)
    assert db_paths.audit_busy_timeout_ssot(
        str(tmp_path), include_connect_timeout=False
    ) == []

    # Auch die CLI muss den Drift default-maessig sehen.
    assert db_paths.audit_busy_timeout_cli(
        ["--audit-busy-timeout", "--root", str(tmp_path)]
    ) == 1
    assert db_paths.audit_busy_timeout_cli(
        ["--audit-busy-timeout", "--root", str(tmp_path),
         "--no-include-connect-timeout"]
    ) == 0


def test_backup_scripts_collect_runtime_dbs_and_guard_zero(tmp_path, monkeypatch):
    import scripts.archon_daily_backup as daily
    import scripts.backup_to_nas as nas

    fake_root = tmp_path / "workspace"
    fake_root.mkdir()
    app = tmp_path / "appdata"
    app.mkdir()
    monkeypatch.setattr(daily, "ROOT", fake_root)
    monkeypatch.setattr(daily, "HERMES", fake_root / "hermes")
    monkeypatch.setattr(nas, "PROJECT_DIR", str(fake_root))
    monkeypatch.setattr(nas, "HERMES_DIR", str(fake_root / "hermes"))
    monkeypatch.setattr(db_paths, "APP_DATA_DIR", str(app))

    # 0 konsolidierte/Tenant-DBs -> leere Pflichtliste (Skripte muessen dann
    # mit Exit 1 abbrechen; dies wird ueber die Guard-Funktion geprueft).
    assert daily.required_db_targets(daily.runtime_db_targets()) == []
    nas_targets, _ = nas.runtime_db_targets()
    assert nas.required_db_targets(nas_targets) == []
    monkeypatch.setattr(sys, "argv", ["archon_daily_backup.py"])
    assert daily.main() == 1
    assert nas.run_backup() is False

    # Mit konsolidierter + Tenant-DB werden beide zur Laufzeit gefunden.
    (app / "ops.db").write_bytes(b"SQLite format 3\x00")
    tenant_db = app / "tenants" / "tenant-w1c" / "erp.db"
    tenant_db.parent.mkdir(parents=True)
    tenant_db.write_bytes(b"SQLite format 3\x00")
    daily_required = daily.required_db_targets(daily.runtime_db_targets())
    nas_targets, _ = nas.runtime_db_targets()
    assert "ops.db" in daily_required
    assert any(name.startswith("tenant_tenant-w1c__") for name in daily_required)
    assert "ops.db" in nas.required_db_targets(nas_targets)
    assert any(name.startswith("tenant_tenant-w1c__") for name in nas.required_db_targets(nas_targets))


def test_break_glass_vault_includes_consolidated_and_tenant_dbs(tmp_path, monkeypatch):
    import scripts.break_glass_recovery as bg

    fake_ws = tmp_path / "workspace"
    fake_ws.mkdir()
    app = tmp_path / "appdata"
    app.mkdir()
    for name in ("ops.db", "business.db", "memory.db"):
        (app / name).write_bytes(b"SQLite format 3\x00")
    tenant_db = app / "tenants" / "tenant-w1c" / "erp.db"
    tenant_db.parent.mkdir(parents=True)
    tenant_db.write_bytes(b"SQLite format 3\x00")

    monkeypatch.setattr(bg, "WORKSPACE_DIR", str(fake_ws))
    monkeypatch.setattr(db_paths, "APP_DATA_DIR", str(app))

    archives = [arcname for _, arcname in bg._critical_files()]
    assert any(arcname.endswith("/ops.db") for arcname in archives)
    assert any(arcname.endswith("/business.db") for arcname in archives)
    assert any(arcname.endswith("/memory.db") for arcname in archives)
    assert any("tenants/tenant-w1c/erp.db" in arcname for arcname in archives)
    assert all(not arcname.startswith("..") for arcname in archives)
    assert all(not os.path.isabs(arcname) for arcname in archives)
    assert any(arcname.startswith(bg.APP_DATA_MARKER) for arcname in archives)


if __name__ == "__main__":
    pytest.main([__file__])
