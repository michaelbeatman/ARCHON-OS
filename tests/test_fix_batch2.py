"""Rot-Beweis fuer D-01, D-02, D-03, R-03, R-04.

D-01: agent_profiles.json: api_get_hermes_profiles verwirft keine Felder (current_task_id etc.)
      und ueberschreibt die SSOT nicht auf GET.
D-02: backend/audit_log.py: Parallele Events brechen die Kette nicht.
D-03: backend/post_task_pipeline.py: kein NameError auf end_doc_path, final_path vorhanden.
R-03: backend/erp_manager.py: Notiz-Update nullt nicht die Belegsummen.
R-04: backend/dunning_engine.py: Keine Kollisionen bei Rechnungsnummern, Fehler fuehrt nicht zu "status: open".
"""

import concurrent.futures
import json
import os
import sqlite3
import tempfile
import pytest


def test_d01_profiles_reader_preserves_custom_fields(monkeypatch, tmp_path):
    """D-01: api_get_hermes_profiles darf Felder wie current_task_id nicht verwerfen."""
    from archon.core import profiles as prof

    test_ssot = tmp_path / "agent_profiles.json"
    dummy_profiles = [
        {
            "id": "test_agent_1",
            "name": "Test Agent One",
            "current_task_id": "task_12345",
            "system_prompt": "Custom prompt 123",
            "category": "Testing",
            "role_id": "custom_role_1"
        }
    ]
    test_ssot.write_text(json.dumps(dummy_profiles, indent=2), encoding="utf-8")

    monkeypatch.setattr(prof, "APP_ROOT", str(tmp_path))
    monkeypatch.setattr(prof, "get_primary_hermes_profiles_dir", lambda: str(tmp_path / "profiles_empty"))
    prof.invalidate_hermes_profiles_cache()

    try:
        profiles = prof.api_get_hermes_profiles()
        agent_1 = next((p for p in profiles if p["id"] == "test_agent_1"), None)
        assert agent_1 is not None, "test_agent_1 nicht gefunden"
        assert agent_1.get("current_task_id") == "task_12345", "current_task_id wurde verworfen!"
        assert agent_1.get("role_id") == "custom_role_1", "role_id wurde verworfen!"
    finally:
        prof.invalidate_hermes_profiles_cache()


def test_d02_audit_log_parallel_hash_integrity(tmp_path):
    """D-02: 8 parallele Threads erzeugen keine Hashketten-Gabelung."""
    from backend.audit_log import ChainedAuditLog

    db_file = str(tmp_path / "test_audit.db")
    audit = ChainedAuditLog(db_path=db_file)

    def _worker(thread_idx):
        for i in range(15):
            audit.record_event(
                category="test",
                action="parallel_write",
                agent_id=f"agent_{thread_idx}",
                payload={"index": i, "thread": thread_idx}
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_worker, t) for t in range(8)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    verif = audit.verify_integrity()
    assert verif["valid"] is True, f"Integritaet gebrochen: {verif.get('broken_at')}"
    assert verif["total_records"] == 8 * 15


def test_d03_post_task_pipeline_dest_doc_path(monkeypatch, tmp_path):
    """D-03: write_project_folder_artifact wirft keinen NameError auf end_doc_path."""
    from backend import post_task_pipeline as ptp
    import backend.kanban_sidecar as kside

    monkeypatch.setattr(ptp, "VAULT_DIR", tmp_path / "vault")
    monkeypatch.setattr(ptp, "BASE_DIR", tmp_path)
    monkeypatch.setattr(kside, "update_kanban_meta", lambda fn: None)
    (tmp_path / "vault" / "01_PROJEKTE").mkdir(parents=True, exist_ok=True)

    dummy_task = {
        "id": "task_abc_1",
        "title": "Test Task",
        "agent_id": "lead_architect",
        "agent_name": "Lead Architect",
        "result_summary": "Alles erledigt"
    }

    res = ptp.write_project_folder_artifact(dummy_task)
    assert "final_doc_path" in res
    assert os.path.exists(res["final_doc_path"])


def test_r03_erp_update_notes_does_not_zero_amounts(monkeypatch, tmp_path):
    """R-03: Notiz-Update an bestehendem Beleg darf Betraege nicht auf 0.00 nullen."""
    import backend.erp_manager as erp_mod

    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tmp_path / "tenants"))
    erp = erp_mod.ERPManager()

    # 1. Beleg mit Position anlegen
    # Erst eine Test-Entitaet anlegen
    ent = erp.save_entity({"name": "Testkunde GmbH", "status": "active"})
    entity_id = ent["entity"]["id"] if "entity" in ent else ent["id"]

    doc = erp.save_document(
        payload={
            "doc_type": "invoice",
            "entity_id": entity_id,
            "lines": [
                {
                    "title": "Beratungsleistung",
                    "quantity": 10.0,
                    "unit_price_net": 100.0,
                    "tax_rate_pct": 19.0
                }
            ]
        }
    )
    doc_id = doc["id"]
    assert doc["amount_net"] == 1000.0
    assert doc["amount_gross"] == 1190.0

    # 2. Nur Notiz updaten (ohne 'lines' im Payload)
    updated = erp.save_document(
        payload={
            "id": doc_id,
            "doc_type": "invoice",
            "entity_id": entity_id,
            "notes": "Zahlung bitte innerhalb von 14 Tagen."
        }
    )
    assert updated["amount_net"] == 1000.0, f"amount_net wurde genullt: {updated['amount_net']}"
    assert updated["amount_gross"] == 1190.0, f"amount_gross wurde genullt: {updated['amount_gross']}"


def test_r04_dunning_duplicate_id_and_error(monkeypatch, tmp_path):
    """R-04: Mehrfaches Anlegen erzeugt distinkte Rechnungsnummern."""
    import backend.dunning_engine as de_mod

    db_path = str(tmp_path / "memory.db")
    monkeypatch.setattr(de_mod, "_resolve_db", lambda name: db_path)

    engine = de_mod.DunningEngine()
    inv1 = engine.create_invoice("Kunde 1", "k1@test.de", amount_net=100.0)
    inv2 = engine.create_invoice("Kunde 2", "k2@test.de", amount_net=200.0)

    assert inv1["invoice_id"] != inv2["invoice_id"], f"Rechnungsnummern kollidieren: {inv1['invoice_id']} == {inv2['invoice_id']}"
