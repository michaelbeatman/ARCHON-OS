"""Re-Audit Etappe 14 — D03: Nummernkreise, Tenant-Isolation, Backups, Secrets."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.tenant_context import _upsert_number_sequence

ROOT = Path(__file__).resolve().parents[1]


def _seq_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "seq.db"))
    conn.execute("""CREATE TABLE document_number_sequences (
        tenant_id TEXT NOT NULL, doc_type TEXT NOT NULL, year INTEGER NOT NULL,
        prefix TEXT NOT NULL, next_seq INTEGER NOT NULL, padding INTEGER NOT NULL DEFAULT 4,
        PRIMARY KEY (tenant_id, doc_type, year))""")
    return conn


def test_d03_number_sequence_never_lowers(tmp_path):
    conn = _seq_db(tmp_path)
    _upsert_number_sequence(conn, "t1", "invoice", 2026, "RE-", 100)
    _upsert_number_sequence(conn, "t1", "invoice", 2026, "RE-", 50)
    row = conn.execute("SELECT next_seq FROM document_number_sequences").fetchone()
    assert row[0] == 100
    conn.close()


def test_d03_number_sequence_prefix_divergence_aborts(tmp_path):
    conn = _seq_db(tmp_path)
    _upsert_number_sequence(conn, "t1", "invoice", 2026, "RE-", 10)
    with pytest.raises(ValueError, match="Nummernkreis-Divergenz"):
        _upsert_number_sequence(conn, "t1", "invoice", 2026, "XX-", 20)
    conn.close()


def test_d03_interaction_collision_is_not_silently_dropped():
    src = (ROOT / "backend" / "erp_manager.py").read_text(encoding="utf-8")
    block = src.split("def add_interaction", 1)[1].split("\n    def ", 1)[0]
    active = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith(("#", "//")))
    assert "INSERT OR IGNORE" not in active
    assert "DATENVERLUST verhindert" in block


def test_d03_tenant_resolver_fail_closed():
    src = (ROOT / "backend" / "db_paths.py").read_text(encoding="utf-8")
    assert "FULL_TENANT_ISOLATION" in src
    assert "Tenant-Resolver fehlgeschlagen bei FULL_TENANT_ISOLATION" in src


def test_d03_backup_paths_use_app_data():
    bbm = (ROOT / "backend" / "db_backup_manager.py").read_text(encoding="utf-8")
    assert 'TENANTS_DIR = os.path.join(_APP_DATA_DIR, "tenants")' in bbm
    su = (ROOT / "backend" / "system_updater.py").read_text(encoding="utf-8")
    assert "def all_db_targets()" in su
    assert 'glob.glob(os.path.join(APP_DATA_DIR, "tenants", "*", "*.db"))' in su
    backup = (ROOT / "backup_archon.py").read_text(encoding="utf-8")
    assert "_name.endswith(\".db\")" in backup


def test_d03_corporate_uses_central_switch():
    src = (ROOT / "archon" / "routers" / "corporate.py").read_text(encoding="utf-8")
    block = src.split("set-active", 1)[1].split("\n@router", 1)[0]
    assert "tenant_context.switch_tenant(" in block
    assert "set_active_company(company_id)" not in block


def test_d03_secret_restore_endpoint_and_restore_test():
    sys_src = (ROOT / "archon" / "routers" / "system.py").read_text(encoding="utf-8")
    assert '@router.post("/api/system/restore-secrets")' in sys_src
    assert "restore_secret_files(" in sys_src
    rt = (ROOT / "scripts" / "automated_restore_test.py").read_text(encoding="utf-8")
    assert "_tenant_dbs_present()" in rt
    assert "Tenant-DBs haben kein festes Pflicht-Schema" in rt
