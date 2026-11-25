"""D03/F012 — DSGVO Art.15/17Regressionstests (FIX W1-C).

Verifiziert gegen den Code:
- kanonischer Tenant-Root aus backend.db_paths.APP_DATA_DIR (ARCHON_DATA_DIR)
- kein Erfolg mit 0 Treffern bei bekannten Tenant-DBs
- _TENANT_TARGETS enthaelt Learnings/Chats/Feedback/E-Mail-Entwuerfe
- W1-B: Hook in die tenant-scoped lossless Session-DAG
"""

import sqlite3

import pytest

import backend.db_paths as db_paths
import backend.gdpr_compliance_engine as gmod


SUBJECT = "Max Mustermann"


def _make_engine(tmp_path, monkeypatch, app_dir):
    monkeypatch.setattr(db_paths, "APP_DATA_DIR", str(app_dir))
    engine = gmod.GDPRComplianceEngine()
    engine.memory_db = str(tmp_path / "central_memory.db")
    engine.kanban_db = str(tmp_path / "missing_kanban.db")
    engine.state_db = str(tmp_path / "missing_state.db")
    engine.obsidian_dir = str(tmp_path / "missing_obsidian")
    with open(engine.memory_db, "a"):
        pass
    engine._init_audit_table()
    return engine


def _create_tenant_memory_db(app_dir, tid="tenant-w1c"):
    path = app_dir / "tenants" / tid / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE learnings (id INTEGER PRIMARY KEY, summary TEXT)")
        conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, content TEXT)")
        conn.execute("CREATE TABLE human_feedback (id INTEGER PRIMARY KEY, comment TEXT)")
        conn.execute("CREATE TABLE email_drafts (draft_id TEXT PRIMARY KEY, subject TEXT, recipient TEXT)")
        conn.executemany(
            "INSERT INTO learnings (summary) VALUES (?)",
            [(f"Notiz ueber {SUBJECT}",), ("Neutraler Eintrag",)],
        )
        conn.execute("INSERT INTO conversations (content) VALUES (?)", (f"Chat mit {SUBJECT}",))
        conn.execute("INSERT INTO human_feedback (comment) VALUES (?)", (f"Feedback {SUBJECT}",))
        conn.execute(
            "INSERT INTO email_drafts (draft_id, subject, recipient) VALUES (?, ?, ?)",
            ("draft-1", f"Re: {SUBJECT}", "max@example.org"),
        )
    return path


def test_art15_finds_subject_in_app_data_dir_tenant_db(tmp_path, monkeypatch):
    app = tmp_path / "appdata"
    tenant_db = _create_tenant_memory_db(app)
    engine = _make_engine(tmp_path, monkeypatch, app)

    export = engine.export_subject_data(SUBJECT)

    tenant_hits = [
        r for r in export["sources"]["tenant_records"]
        if r.get("_db") == "memory.db"
    ]
    assert len(tenant_hits) >= 4
    assert all(r.get("_tenant") == "tenant-w1c" for r in tenant_hits)
    assert export["sources"]["tenant_dbs_scanned"] >= 1


def test_art17_redacts_memory_tables_in_tenant_db(tmp_path, monkeypatch):
    app = tmp_path / "appdata"
    tenant_db = _create_tenant_memory_db(app)
    engine = _make_engine(tmp_path, monkeypatch, app)

    result = engine.erase_subject_data(SUBJECT, dry_run=False)

    assert result["affected"]["tenant_records"] >= 4
    assert result["receipt"] is not None
    with sqlite3.connect(str(tenant_db)) as conn:
        learnings = [r[0] for r in conn.execute("SELECT summary FROM learnings")]
        chat = conn.execute("SELECT content FROM conversations").fetchone()[0]
        feedback = conn.execute("SELECT comment FROM human_feedback").fetchone()[0]
        draft = conn.execute("SELECT subject FROM email_drafts").fetchone()[0]
    assert any("[ANONYMISIERT_DSGVO_ART17]" in v for v in learnings)
    assert "[ANONYMISIERT_DSGVO_ART17]" in chat
    assert "[ANONYMISIERT_DSGVO_ART17]" in feedback
    assert "[ANONYMISIERT_DSGVO_ART17]" in draft
    assert "Mustermann" not in " ".join(learnings + [chat, feedback, draft])


def test_art17_no_success_receipt_with_zero_hits(tmp_path, monkeypatch):
    app = tmp_path / "appdata"
    _create_tenant_memory_db(app)
    engine = _make_engine(tmp_path, monkeypatch, app)

    with pytest.raises(RuntimeError, match="0 Treffer"):
        engine.erase_subject_data("Unbekannter Testsubject 99381", dry_run=False)


def test_tenant_targets_cover_all_memory_tables():
    targets = set(gmod._TENANT_TARGETS)
    assert {"learnings", "conversations", "human_feedback", "email_drafts"} <= targets
    # GoBD-geschuetzte Tabellen duerfen nicht per Target-Dict geloescht werden.
    assert "erp_documents" not in targets
    assert "receipts" not in targets


def test_art17_reaches_lossless_session_dag(tmp_path, monkeypatch):
    """W1-B: Turns/Summaries muessen mitgeschwaerzt werden."""
    app = tmp_path / "appdata"
    tenant_db = _create_tenant_memory_db(app)
    with sqlite3.connect(str(tenant_db)) as conn:
        conn.execute(
            "CREATE TABLE lcm_turns (id TEXT PRIMARY KEY, session_id TEXT, seq INTEGER, "
            "role TEXT, content TEXT, created_at REAL, tenant_id TEXT, dedup_key TEXT)"
        )
        conn.execute(
            "CREATE TABLE lcm_summaries (id TEXT PRIMARY KEY, session_id TEXT, "
            "summary_text TEXT, child_turn_ids_json TEXT, created_at REAL, "
            "tenant_id TEXT, integrity_hmac TEXT)"
        )
        conn.execute(
            "INSERT INTO lcm_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("turn-1", "s-1", 1, "user", f"Turn von {SUBJECT}", 1.0, "tenant-w1c", ""),
        )
        conn.execute(
            "INSERT INTO lcm_summaries VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sum-1", "s-1", f"Summary ueber {SUBJECT}", "[]", 1.0, "tenant-w1c", ""),
        )
    engine = _make_engine(tmp_path, monkeypatch, app)

    result = engine.erase_subject_data(SUBJECT, dry_run=False)

    assert result["affected"]["lossless_turns"] >= 1
    assert result["affected"]["lossless_summaries"] >= 1
    assert "tenant-w1c" in result["lossless_dag"]
    with sqlite3.connect(str(tenant_db)) as conn:
        turn = conn.execute("SELECT content FROM lcm_turns WHERE id='turn-1'").fetchone()[0]
        summary = conn.execute("SELECT summary_text FROM lcm_summaries WHERE id='sum-1'").fetchone()[0]
        hmac = conn.execute("SELECT integrity_hmac FROM lcm_summaries WHERE id='sum-1'").fetchone()[0]
    assert turn == "[ANONYMISIERT_DSGVO_ART17]"
    assert summary == "[ANONYMISIERT_DSGVO_ART17]"
    assert hmac  # Summary wurde neu signiert


if __name__ == "__main__":
    pytest.main([__file__])
