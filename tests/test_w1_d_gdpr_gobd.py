"""W1-D (Fundament/DB) — Regressionstests für D03-M3, D03-M5, D03-L1.

Statisch gegen den Code verifizierte Befunde:
- D03-M3: physische Alt-Kopien (``*.db.bak``, ``ops.db.before_*``,
  ``_legacy_root_dbs_*``) müssen in der gemeinsamen SSOT-Liste auftauchen und
  von Art.15/17 maskiert werden; 0-Treffer bleibt ein harter Abbruch.
- D03-M5: der GoBD-Trigger muss Status-/Betragsänderungen auf gebuchten
  Belegen per ``RAISE(ABORT)`` blockieren und alte Trigger ersetzen.
- D03-L1: der gültige Primärmandant ``default`` behält Vault-Zugriff mit
  eigenem Key/AAD, ohne dass fail-closed bei Resolverfehlern verloren geht.
"""

import sqlite3

import pytest

import backend.db_paths as db_paths
import backend.erp_manager as erpmod
import backend.gdpr_compliance_engine as gmod
import backend.offline_memory_vault as ovm
import backend.tenant_context as tc

SUBJECT = "W1D Testsubject 4711"


# --------------------------------------------------------------------------- #
# D03-M3 — gemeinsame SSOT-Liste / Art.15 / Art.17
# --------------------------------------------------------------------------- #

def _make_app(tmp_path, monkeypatch):
    app = tmp_path / "appdata"
    (app / "tenants" / "default").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db_paths, "APP_DATA_DIR", str(app))
    return app


def _create_pii_db(path, subject=SUBJECT):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS learnings (id INTEGER PRIMARY KEY, summary TEXT)"
        )
        conn.execute("DELETE FROM learnings")
        conn.execute(
            "INSERT INTO learnings (summary) VALUES (?)", (f"Notiz ueber {subject}",)
        )
    return path


def _make_engine(tmp_path, monkeypatch, app):
    engine = gmod.GDPRComplianceEngine()
    engine.memory_db = str(tmp_path / "central_memory.db")
    engine.kanban_db = str(tmp_path / "missing_kanban.db")
    engine.state_db = str(tmp_path / "missing_state.db")
    engine.obsidian_dir = str(tmp_path / "missing_obsidian")
    with open(engine.memory_db, "a"):
        pass
    engine._init_audit_table()
    return engine


def _old_copy_paths(app):
    return [
        app / "tenants" / "default" / "memory.db",
        app / "tenants" / "default" / "memory.db.pre_fk_repair_20261124.db.bak",
        app / "ops.db.before_kanban_fix",
        app / "_legacy_root_dbs_20261122_222637" / "agentic_memory.db",
    ]


def test_db_copy_kind_allowlist():
    assert gmod._db_copy_kind("memory.db") == "db"
    assert gmod._db_copy_kind("memory.db.pre_fk.db.bak") == "db"
    assert gmod._db_copy_kind("ops.db.before_kanban_fix") == "db"
    assert gmod._db_copy_kind("agentic_memory.db-wal") == "sidecar"
    assert gmod._db_copy_kind("agentic_memory.db-shm") == "sidecar"
    # Nicht erlaubte Suffixe / Fremddateien bleiben draussen.
    assert gmod._db_copy_kind("memory.db-journal") is None
    assert gmod._db_copy_kind("memory.db.json") is None
    assert gmod._db_copy_kind("agent_profiles.json.bak_20260901") is None


def test_ssot_list_includes_old_copies_and_legacy_roots(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    paths = _old_copy_paths(app)
    for p in paths:
        _create_pii_db(p)
    # Nicht-leere WAL-Sidecar-Datei: muss in der SSOT-Liste stehen, aber nicht
    # als SQL-Ziel (Art.15/17 oeffnet keine -wal/-shm-Dateien).
    wal = app / "tenants" / "default" / "memory.db-wal"
    wal.write_bytes(b"sidecar-placeholder")

    files = set(gmod._tenant_db_files())
    for p in paths:
        assert str(p) in files, p
    assert str(wal) in files

    maskable = set(gmod._maskable_db_files())
    assert str(wal) not in maskable
    for p in paths:
        assert str(p) in maskable, p


def test_tenant_roots_include_legacy_root_db_dirs(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    legacy = app / "_legacy_root_dbs_20261122_222637"
    legacy.mkdir(parents=True, exist_ok=True)

    roots = gmod._tenant_roots()
    assert str(legacy) in roots
    assert str(app / "tenants") in roots


def test_art15_exports_subject_from_db_bak(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    bak = app / "tenants" / "default" / "memory.db.pre_fk_repair_20261124.db.bak"
    _create_pii_db(bak)
    engine = _make_engine(tmp_path, monkeypatch, app)

    export = engine.export_subject_data(SUBJECT)

    hits = [
        r for r in export["sources"]["tenant_records"]
        if r.get("_db") == bak.name
    ]
    assert hits, "Art.15 muss die .db.bak-Kopie durchsuchen"
    assert all(SUBJECT in str(h.get("summary")) for h in hits)


def test_art17_redacts_all_physical_copies(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    paths = _old_copy_paths(app)
    for p in paths:
        _create_pii_db(p)
    engine = _make_engine(tmp_path, monkeypatch, app)

    result = engine.erase_subject_data(SUBJECT, dry_run=False)

    assert "errors" not in result
    assert result["receipt"] is not None
    assert result["tenant_db_files_scanned"] >= len(paths)
    for p in paths:
        with sqlite3.connect(str(p)) as conn:
            values = [r[0] for r in conn.execute("SELECT summary FROM learnings")]
        assert any("[ANONYMISIERT_DSGVO_ART17]" in v for v in values), p
        assert all(SUBJECT not in v for v in values), p


def test_art17_zero_hits_still_aborts_with_old_copies(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    _create_pii_db(app / "tenants" / "default" / "memory.db.bak")
    engine = _make_engine(tmp_path, monkeypatch, app)

    with pytest.raises(RuntimeError, match="0 Treffer"):
        engine.erase_subject_data("Voellig Unbekannter 998877", dry_run=False)


# --------------------------------------------------------------------------- #
# D03-M5 — GoBD-DB-Trigger
# --------------------------------------------------------------------------- #

def _make_erp(tmp_path, monkeypatch):
    base = tmp_path / "tenants"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(erpmod, "TENANTS_BASE_DIR", str(base))
    return erpmod.ERPManager(), base


def _booked_doc(erp, doc_id="doc-w1d"):
    conn, cid = erp._get_conn("w1d-tenant")
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO crm_entities (id, display_name) VALUES (?, ?)",
            ("ent-w1d", "Test GmbH"),
        )
        conn.execute("DELETE FROM erp_documents WHERE id = ?", (doc_id,))
        conn.execute(
            """INSERT INTO erp_documents
               (id, doc_type, doc_number, status, entity_id, recipient_snapshot_json,
                issue_date, amount_net, tax_amount, amount_gross, booked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id, "invoice", "RE-2026-0001", "booked", "ent-w1d", "{}",
                "2026-01-15", 100.0, 19.0, 119.0, "2026-01-15 10:00:00",
            ),
        )
    conn.close()
    return cid


@pytest.mark.parametrize(
    "column,value",
    [
        ("status", "draft"),
        ("amount_net", 999.0),
        ("tax_amount", 1.0),
        ("amount_gross", 1.0),
        ("entity_id", "ent-other"),
        ("issue_date", "2020-01-01"),
        ("recipient_snapshot_json", '{"changed": true}'),
        ("booked_at", None),
    ],
)
def test_gobd_trigger_blocks_direct_tamper(tmp_path, monkeypatch, column, value):
    erp, _ = _make_erp(tmp_path, monkeypatch)
    cid = _booked_doc(erp)
    conn, _ = erp._get_conn(cid)

    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                f"UPDATE erp_documents SET {column} = ? WHERE id = 'doc-w1d'",
                (value,),
            )
    conn.close()


def test_gobd_trigger_allows_legitimate_paid_flow(tmp_path, monkeypatch):
    erp, _ = _make_erp(tmp_path, monkeypatch)
    cid = _booked_doc(erp)
    conn, _ = erp._get_conn(cid)

    with conn:
        conn.execute(
            "UPDATE erp_documents SET status = 'paid', paid_at = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = 'doc-w1d'",
            ("2026-01-20 12:00:00",),
        )
    row = conn.execute(
        "SELECT status, paid_at FROM erp_documents WHERE id = 'doc-w1d'"
    ).fetchone()
    conn.close()

    assert row["status"] == "paid"
    assert row["paid_at"] == "2026-01-20 12:00:00"


def test_gobd_trigger_replaces_legacy_trigger_definition(tmp_path, monkeypatch):
    """Bestands-DB mit altem (schwachem) Trigger muss beim Init gehärtet werden."""
    erp, _ = _make_erp(tmp_path, monkeypatch)
    cid = _booked_doc(erp)
    conn, _ = erp._get_conn(cid)
    with conn:
        conn.execute("DROP TRIGGER IF EXISTS erp_documents_gobd_no_tamper")
        conn.execute(
            """CREATE TRIGGER erp_documents_gobd_no_tamper
               BEFORE UPDATE ON erp_documents
               WHEN OLD.booked_at IS NOT NULL AND (
                   NEW.booked_at IS NOT OLD.booked_at
                   OR NEW.recipient_snapshot_json IS NOT OLD.recipient_snapshot_json
               )
               BEGIN SELECT RAISE(ABORT, 'old weak trigger'); END"""
        )
    conn.close()

    # Neue Manager-Instanz → _init_schema laeuft erneut und ersetzt den Trigger.
    fresh = erpmod.ERPManager()
    conn, _ = fresh._get_conn(cid)
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "UPDATE erp_documents SET status = 'draft' WHERE id = 'doc-w1d'"
            )
    conn.close()


# --------------------------------------------------------------------------- #
# D03-L1 — Primärmandant "default" im Offline-Vault
# --------------------------------------------------------------------------- #

def test_active_tenant_id_accepts_default_primary(monkeypatch):
    monkeypatch.setattr(
        tc.tenant_context, "get_active_tenant_id", lambda: "default"
    )
    assert ovm._active_tenant_id() == "default"


def test_active_tenant_id_still_fails_closed(monkeypatch):
    for value in ("", "none", "null", "undefined"):
        monkeypatch.setattr(
            tc.tenant_context, "get_active_tenant_id", lambda v=value: v
        )
        with pytest.raises(RuntimeError):
            ovm._active_tenant_id()

    def _broken():
        raise RuntimeError("resolver down")

    monkeypatch.setattr(tc.tenant_context, "get_active_tenant_id", _broken)
    with pytest.raises(RuntimeError, match="resolver down"):
        ovm._active_tenant_id()


def test_default_primary_gets_own_derived_key(monkeypatch):
    monkeypatch.setenv("COMPARTMENT_VAULT_KEY", "a" * 64)
    key_default = ovm.load_or_create_vault_key(tenant_id="default")
    key_other = ovm.load_or_create_vault_key(tenant_id="archon-systems")
    assert key_default != key_other
    with pytest.raises(RuntimeError):
        ovm.load_or_create_vault_key(tenant_id="none")


def test_default_primary_can_store_and_recall(tmp_path, monkeypatch):
    # Kein Env-Master-Key: der Vault muss den tenant-eigenen Datei-Key nutzen.
    monkeypatch.delenv("COMPARTMENT_VAULT_KEY", raising=False)
    monkeypatch.setattr(
        tc.tenant_context, "get_active_tenant_id", lambda: "default"
    )

    def _paths(tid=None):
        tenant = str(tid or ovm._active_tenant_id())
        folder = tmp_path / "tenants" / tenant
        folder.mkdir(parents=True, exist_ok=True)
        return (
            str(folder / "compartment_vault.db"),
            str(folder / "compartment.key"),
        )

    monkeypatch.setattr(ovm, "_tenant_vault_paths", _paths)
    eid = ovm.store_memory("w1d-ns", "Geheimnis des Default-Mandanten")
    hits = ovm.recall_memory("w1d-ns", "Geheimnis")

    assert eid.startswith("mem-")
    assert any(
        h["content"] == "Geheimnis des Default-Mandanten" for h in hits
    )
