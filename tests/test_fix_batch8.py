import os
import sqlite3
import datetime
import pytest


def test_r30_audit_integrity_detects_payload_tampering(tmp_path, monkeypatch):
    """R-30: verify_audit_integrity muss Manipulation historischer Payloads erkennen."""
    from backend.approval_policy_engine import ApprovalPolicyEngine

    db_path = tmp_path / "test_approval.db"
    engine = ApprovalPolicyEngine(db_path=str(db_path))

    # Manipuliere eine historische Zeile in der DB (z.B. policy_key oder new_value geaendert)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE approval_policy_audit_chain SET new_value = 'MANIPULIERT' WHERE id = 1")
    conn.commit()
    conn.close()

    res = engine.verify_audit_integrity()
    assert res["valid"] is False, "R-30 BUG: Manipulation des Payloads wurde nicht erkannt!"
    assert res.get("broken_at_id") == 1


def test_r31_contract_renewal_preserves_end_of_month(tmp_path, monkeypatch):
    """R-31: Vertragsverlaengerung am 31.03. um 12 Monate muss auf 31.03. enden, nicht 28.03."""
    import backend.contract_manager as cm_mod
    from backend.contract_manager import ContractManager

    db_path = tmp_path / "contracts_test.db"
    monkeypatch.setattr(cm_mod, "DB_PATH", str(db_path))
    cm_mod.init_contracts_db()

    contract = {
        "id": "c-31",
        "contract_name": "Jahresvertrag Monatsende",
        "partner_name": "Test Partner",
        "start_date": "2025-03-31",
        "end_date": "2026-03-31",
        "auto_renewal_months": 12,
        "notice_period_days": 30
    }
    ContractManager.create_or_update(contract)

    renewed = ContractManager.renew_contract("c-31")
    assert renewed is not None
    assert renewed["end_date"] == "2027-03-31", f"R-31 BUG: 31.03. wurde auf {renewed['end_date']} gekappt!"


def test_r32_crm_pipeline_stats_honest_zero(tmp_path, monkeypatch):
    """R-32: CRM Funnel darf fuer leere Kontakte keine Fantasiezahlen (999, 70, 32%) melden."""
    import backend.crm_service as crm_mod
    from backend.crm_service import CRMService

    crm = CRMService()
    # Leere In-Memory DB
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE kontakte (
            id TEXT PRIMARY KEY,
            name TEXT,
            unternehmen TEXT,
            rolle TEXT,
            status TEXT,
            updated TEXT,
            nachrichtenverlauf TEXT,
            RollenVerteilungzuordnung TEXT,
            naechster_termin TEXT,
            profilbild TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE termine (
            id TEXT PRIMARY KEY,
            start TEXT
        )
    """)
    monkeypatch.setattr(crm_mod, "_get_sqlite_conn", lambda: conn)
    monkeypatch.setattr(crm_mod, "_get_pb_conn", lambda: conn)

    stats = crm.get_report_metrics()
    breakdown = {item["status"]: item["count"] for item in stats.get("status_breakdown", [])}

    assert breakdown.get("Vernetzt") == 0, f"R-32 BUG: Vernetzt meldet Phantasiezahl: {breakdown.get('Vernetzt')}"
    assert breakdown.get("Erstnachricht") == 0, f"R-32 BUG: Erstnachricht meldet Phantasiezahl: {breakdown.get('Erstnachricht')}"
    assert stats.get("reply_rate") == 0, f"R-32 BUG: reply_rate meldet {stats.get('reply_rate')}% statt 0% bei leerem Funnel"


def test_r33_gdpr_export_flags_truncation(tmp_path, monkeypatch):
    """R-33: Art. 15 DSGVO Auskunft muss Truncation transparent machen, wenn > 100 Treffer."""
    from backend.gdpr_compliance_engine import GDPRComplianceEngine

    state_db = tmp_path / "state_test.db"
    conn = sqlite3.connect(str(state_db))
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp TEXT
        )
    """)
    # Fuege 150 Nachrichten ein
    for i in range(150):
        conn.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                     (f"sess-{i}", "user", f"Geheime Info ueber Max Mustermann #{i}", "2026-11-08T10:00:00"))
    conn.commit()
    conn.close()

    engine = GDPRComplianceEngine()
    engine.state_db = str(state_db)
    engine.kanban_db = str(tmp_path / "nonexistent_kanban.db")
    engine.memory_db = str(tmp_path / "nonexistent_memory.db")
    engine.obsidian_dir = str(tmp_path / "nonexistent_obsidian")

    res = engine.export_subject_data("Max Mustermann")
    assert len(res["sources"]["chat_messages"]) == 100
    assert res["sources"].get("chat_messages_truncated") is True, "R-33 BUG: chat_messages_truncated Flag fehlt!"
    assert res.get("is_truncated") is True, "R-33 BUG: is_truncated Flag auf Root-Ebene fehlt!"
    assert res["sources"].get("chat_messages_total_count") == 150, "R-33 BUG: Ungedeckelte Gesamtzaehlung fehlt!"
